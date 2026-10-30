"""Settings dialog: bring your own API key and cloud endpoint preferences.

The dialog edits two things that `Nexus.keys` persists:

* `CloudPrefs` — provider label, base URL and model (plain JSON, not secret)
* `KeyStore`   — the API key itself, kept in the OS keyring when one exists

Saving calls `PrivacyGate.refresh_config()` so a key or endpoint changed while
the app is running applies to the very next cloud request.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from Nexus.keys import CloudPrefs, KeyStore, resolve_cloud_config

PROVIDER_NEBIUS = "nebius"
PROVIDER_CUSTOM = "custom"


class SettingsDialog(QDialog):
    """Cloud provider, endpoint and API key settings."""

    def __init__(self, settings, privacy_gate=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.privacy_gate = privacy_gate
        self.key_store = KeyStore(settings.data_dir)

        self.setWindowTitle("Nexus — Settings")
        self.setModal(True)
        self.setMinimumWidth(440)
        self._build_ui()
        self._populate()

    # -- UI -------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Endpoint -----------------------------------------------------------
        endpoint_box = QGroupBox("Cloud endpoint")
        endpoint_form = QFormLayout(endpoint_box)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem(
            "Nebius Token Factory (default)", PROVIDER_NEBIUS
        )
        self.provider_combo.addItem(
            "Custom — any OpenAI-compatible endpoint", PROVIDER_CUSTOM
        )
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        endpoint_form.addRow("Provider:", self.provider_combo)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.studio.nebius.com/v1/")
        endpoint_form.addRow("Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("nvidia/Nemotron-3-Ultra-550B")
        endpoint_form.addRow("Model:", self.model_edit)
        root.addWidget(endpoint_box)

        # API key ------------------------------------------------------------
        key_box = QGroupBox("API key (bring your own)")
        key_layout = QVBoxLayout(key_box)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("paste your API key")
        key_layout.addWidget(self.key_edit)

        self.key_status = QLabel("No key stored — cloud bursts stay disabled.")
        self.key_status.setWordWrap(True)
        key_layout.addWidget(self.key_status)

        key_buttons = QHBoxLayout()
        self.remove_key_btn = QPushButton("Remove stored key")
        self.remove_key_btn.setEnabled(False)
        self.remove_key_btn.clicked.connect(self._remove_key)
        key_buttons.addWidget(self.remove_key_btn)
        key_buttons.addStretch(1)
        key_layout.addLayout(key_buttons)
        root.addWidget(key_box)

        note = QLabel(
            "The key stays in this device's credential store and is only sent "
            "when you explicitly approve a cloud request."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self):
        config = resolve_cloud_config(self.settings)
        index = self.provider_combo.findData(
            PROVIDER_CUSTOM if config.provider == PROVIDER_CUSTOM else PROVIDER_NEBIUS
        )
        self.provider_combo.setCurrentIndex(max(index, 0))
        self.base_url_edit.setText(config.base_url)
        self.model_edit.setText(config.model)
        self._refresh_key_status()

    def _refresh_key_status(self):
        masked = self.key_store.mask()
        if masked:
            where = (
                "the OS keyring"
                if self.key_store.location() == "keyring"
                else str(self.key_store.key_file)
            )
            self.key_status.setText(f"Stored in {where}: {masked}")
            self.remove_key_btn.setEnabled(True)
            self.key_edit.setPlaceholderText("paste a new key to replace it")
        else:
            self.key_status.setText(
                "No key stored — cloud bursts stay disabled until you add one."
            )
            self.remove_key_btn.setEnabled(False)
            self.key_edit.setPlaceholderText("paste your API key")

    def _provider_changed(self):
        """Switching to Nebius restores its defaults; custom starts blank."""
        if self.provider_combo.currentData() == PROVIDER_NEBIUS:
            self.base_url_edit.setText(self.settings.nebius_base_url)
            self.model_edit.setText(self.settings.nebius_model)
        else:
            self.base_url_edit.clear()
            self.model_edit.clear()

    # -- actions -------------------------------------------------------------

    def _save(self):
        key = self.key_edit.text().strip()
        try:
            CloudPrefs.update(
                self.settings.data_dir,
                provider=self.provider_combo.currentData(),
                base_url=self.base_url_edit.text(),
                model=self.model_edit.text(),
            )
            if key:
                self.key_store.set(key)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return

        self._apply_to_running_app()
        self.accept()

    def _remove_key(self):
        self.key_store.delete()
        self.key_edit.clear()
        self._apply_to_running_app()
        self._refresh_key_status()

    def _apply_to_running_app(self):
        """Re-read key + prefs so the live engine uses them without a restart."""
        if self.privacy_gate is not None:
            self.privacy_gate.refresh_config()
