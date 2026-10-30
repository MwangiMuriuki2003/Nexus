"""Minimal PyQt6 main window for Nexus MVP."""
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel,
    QDialog, QDialogButtonBox, QFormLayout, QComboBox,
)
from PyQt6.QtGui import QAction, QImage, QPalette, QPainter, QPixmap
from PyQt6.QtCore import Qt, QTimer, QRect

from Nexus.config import asset_path, settings
from Nexus.core.privacy_gate import PrivacyGate
from Nexus.keys import resolve_cloud_config
from Nexus.ui.privacy_dashboard import PrivacyDashboard

# Background logo: how much of the window it covers and how faint it is.
WATERMARK_IMAGE = "nexus-logo-2-hex.png"
WATERMARK_FILL = 0.5
WATERMARK_OPACITY = 0.10


def watermark_pixmap() -> QPixmap:
    """The logo with its white paper keyed out to soft alpha.

    The shipped asset is an opaque JPEG (it only carries a `.png` name), so
    drawn as-is it would lay a bright square over the chat. Alpha is derived
    from luminance: white paper vanishes, the blue artwork stays — which is
    what makes a faint backdrop possible on both light and dark palettes.
    """
    image = QImage(str(asset_path(WATERMARK_IMAGE)))
    if image.isNull():
        return QPixmap()  # asset missing: the window renders without a backdrop

    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    bits = image.bits()
    bits.setsize(image.sizeInBytes())
    pixels = np.frombuffer(bits, dtype=np.uint8).reshape(
        image.height(), image.width(), 4
    ).copy()
    # uint32: 299*r + 587*g + 114*b reaches 255000, which overflows uint16.
    red, green, blue = (pixels[..., i].astype(np.uint32) for i in range(3))
    luminance = (299 * red + 587 * green + 114 * blue) // 1000
    pixels[..., 3] = (255 - luminance).astype(np.uint8)

    keyed = QImage(
        pixels.data, image.width(), image.height(), image.width() * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()  # copy: detaches from the numpy buffer's lifetime
    return QPixmap.fromImage(keyed)


class WatermarkedWidget(QWidget):
    """Central widget that paints the logo *behind* its children.

    Children paint after their parent, so the logo can never cover the chat,
    input or status line — and the chat view is transparent so the backdrop
    shows through instead of being hidden by an opaque text area.
    """

    def __init__(self, logo: QPixmap, parent=None):
        super().__init__(parent)
        self.logo = logo

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.fillRect(
                event.rect(), self.palette().color(QPalette.ColorRole.Window)
            )
            if self.logo.isNull():
                return
            box = self.logo.size()
            box.scale(
                int(self.width() * WATERMARK_FILL),
                int(self.height() * WATERMARK_FILL),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            target = QRect(
                (self.width() - box.width()) // 2,
                (self.height() - box.height()) // 2,
                box.width(),
                box.height(),
            )
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setOpacity(WATERMARK_OPACITY)
            painter.drawPixmap(target, self.logo)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nexus — Private Desktop Brain")
        self.resize(900, 700)
        # Single engine, built lazily on first send: it owns the LLM, memory,
        # skills and scheduler, so every message goes through the full pipeline.
        self.engine = None
        # Qt mode approval: injects the modal-backed callback into the gate.
        self.privacy_gate = PrivacyGate(settings, approval_callback=self._approval_modal)

        # Privacy dashboard (lazy init)
        self.privacy_dashboard = None

        central = WatermarkedWidget(watermark_pixmap())
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        # Transparent so the logo backdrop behind it stays visible; the widget
        # itself paints the palette's background colour, so contrast is intact.
        self.chat_display.setStyleSheet("QTextEdit { background: transparent; }")
        layout.addWidget(self.chat_display)

        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask anything... (prefix !ultra for cloud reasoning)")
        self.input_field.returnPressed.connect(self.handle_send)
        input_row.addWidget(self.input_field)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.handle_send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self.status_label = QLabel("Status: Starting...")
        layout.addWidget(self.status_label)

        # Menu bar: settings + privacy dashboard
        menubar = self.menuBar()
        edit_menu = menubar.addMenu("Edit")
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._show_settings)
        edit_menu.addAction(settings_action)

        view_menu = menubar.addMenu("View")
        privacy_action = QAction("Privacy Dashboard", self)
        privacy_action.setShortcut("Ctrl+Shift+P")
        privacy_action.triggered.connect(self._show_privacy_dashboard)
        view_menu.addAction(privacy_action)

        if not self.model_path.exists():
            self.status_label.setText(
                f"Status: No local model at {self.model_path} — run `python -m Nexus setup`"
            )
        else:
            self.status_label.setText(
                f"Status: Ready (model loads on first message) — {self._cloud_state()}"
            )

    @staticmethod
    def _cloud_state() -> str:
        """Short suffix describing whether a bring-your-own key is configured."""
        return (
            "cloud key configured"
            if resolve_cloud_config(settings).configured
            else "local-only (no cloud key)"
        )

    def _show_settings(self):
        """Open the Settings dialog (bring your own key + endpoint prefs)."""
        from Nexus.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(settings, privacy_gate=self.privacy_gate, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        current = self.status_label.text()
        if current.startswith("Status: No local model"):
            return  # the missing-model advice is the important part here
        self.status_label.setText(f"{current.split(' — ')[0]} — {self._cloud_state()}")

    @property
    def model_path(self):
        return settings.model_dir / settings.gguf_filename

    def _get_engine(self):
        """Build the single NexusEngine on first use (LLM loading lives there)."""
        if self.engine is None:
            from Nexus.core.engine import NexusEngine

            if not self.model_path.exists():
                raise RuntimeError(
                    f"No local model at {self.model_path} — run `python -m Nexus setup`"
                )
            self.engine = NexusEngine(
                settings=settings,
                privacy_gate=self.privacy_gate,
            )
            self.status_label.setText("Status: Running locally")
        return self.engine

    def _approval_modal(self, reason: str, token_estimate: int) -> bool:
        """PrivacyGate approval callback: modal with reason/tokens/model + scope.

        Blocks for at most `approval_timeout` (30s) seconds and defaults to deny.
        Session/Always scope flips the gate's cached approval for later requests.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Approve cloud request?")
        dialog.setModal(True)

        form = QFormLayout(dialog)
        form.addRow("Reason:", QLabel(reason))
        form.addRow("Estimated tokens:", QLabel(f"~{token_estimate}"))
        # The effective model: a custom one saved in Settings, not just the default.
        form.addRow("Model:", QLabel(self.privacy_gate.cloud_config.model))

        scope = QComboBox()
        scope.addItems(["Once", "Session", "Always"])
        form.addRow("Approval scope:", scope)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Approve")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Deny")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        # Timeout: nobody answers within 30s -> reject (deny).
        QTimer.singleShot(self.privacy_gate.approval_timeout * 1000, dialog.reject)

        approved = dialog.exec() == QDialog.DialogCode.Accepted
        if approved and scope.currentText() in ("Session", "Always"):
            self.privacy_gate.approved = True
        return approved

    def _show_privacy_dashboard(self):
        """Show the privacy dashboard widget."""
        if self.privacy_dashboard is None:
            from Nexus.core.memory_manager import MemoryManager

            # Reuse the engine's stores when they exist so the dashboard shows
            # the same data the engine is writing to.
            memory = getattr(self.engine, "memory", None)
            if memory is None:
                memory = MemoryManager(
                    episodic_db_path=settings.db_path,
                    semantic_persist_dir=settings.chroma_path,
                )
            self.privacy_dashboard = PrivacyDashboard(
                settings=settings,
                privacy_gate=self.privacy_gate,
                memory_manager=memory,
                parent=self,
            )
        self.privacy_dashboard.show()
        self.privacy_dashboard.raise_()

    def handle_send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.chat_display.append(f"<b>You:</b> {text}")

        try:
            engine = self._get_engine()
        except Exception as e:
            self.chat_display.append(f"<b>Error:</b> {e}<br>")
            self.status_label.setText(f"Status: {e}")
            return

        try:
            # Full pipeline: routing, memory retrieval, skills, audit, privacy gate.
            result = engine.process_message(text)
        except Exception as e:
            self.chat_display.append(f"<b>Error:</b> {e}<br>")
            return

        response = result.get("response", "")
        self.chat_display.append(f"<b>Nexus:</b> {response}<br>")

        if result.get("cloud_approved"):
            self.status_label.setText("Status: Cloud burst approved")
        else:
            self.status_label.setText("Status: Running locally")
