"""Minimal PyQt6 main window for Nexus MVP."""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel,
    QDialog, QDialogButtonBox, QFormLayout, QComboBox,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer

from Nexus.config import settings
from Nexus.core.privacy_gate import PrivacyGate
from Nexus.ui.privacy_dashboard import PrivacyDashboard


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

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
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

        # Menu bar with Privacy Dashboard
        menubar = self.menuBar()
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
            self.status_label.setText("Status: Ready (model loads on first message)")

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
        form.addRow("Model:", QLabel(settings.nebius_model))

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
