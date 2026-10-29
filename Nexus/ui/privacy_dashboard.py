"""Privacy Dashboard UI widget for Nexus.

Displays:
- Local vs cloud usage statistics
- Audit log viewer
- Data sources (episodic + semantic memory counts)
- Privacy gate approval status
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QTextEdit, QPushButton, QGroupBox, QFrame,
                              QSplitter, QComboBox, QSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QPalette

from Nexus.core.privacy_gate import PrivacyGate
from Nexus.core.memory_manager import MemoryManager
from Nexus.config import Settings


class PrivacyDashboard(QWidget):
    """Widget showing privacy status, audit logs, and usage statistics."""

    def __init__(self, settings: Settings, privacy_gate: PrivacyGate,
                 memory_manager: MemoryManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.privacy_gate = privacy_gate
        self.memory_manager = memory_manager

        self.setWindowTitle("Nexus — Privacy Dashboard")
        self.resize(800, 600)

        self._setup_ui()
        self._refresh_data()

        # Refresh every 30 seconds
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_data)
        self.refresh_timer.start(30_000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Top summary cards ---
        summary_box = QGroupBox("Usage Summary")
        summary_layout = QHBoxLayout(summary_box)

        # Local usage card
        self.local_label = QLabel("Local: -- calls")
        self.local_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        summary_layout.addWidget(self.local_label)

        # Cloud usage card
        self.cloud_label = QLabel("Cloud: -- calls (pending)")
        self.cloud_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        summary_layout.addWidget(self.cloud_label)

        # Divider
        divider = QFrame()
        divider.setFrameStyle(QFrame.Shape.VLine)
        divider.setMidLineWidth(1)
        summary_layout.addWidget(divider)

        # Approval status
        self.status_label = QLabel("Status: Local-only mode")
        self.status_label.setStyleSheet("font-size: 12px; color: #666;")
        summary_layout.addWidget(self.status_label)

        layout.addWidget(summary_box)

        # --- Audit Log Section ---
        log_box = QGroupBox("Audit Log")
        log_layout = QVBoxLayout(log_box)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 9))
        self.log_text.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4; border: 1px solid #555;"
        )
        log_layout.addWidget(self.log_text)

        # Controls
        ctrl_layout = QHBoxLayout()
        # Append-only logs are never wiped silently: archive first, log the
        # wipe, then trim the live table down to the log_cleared trail.
        self.archive_log_btn = QPushButton("Export & Archive")
        self.archive_log_btn.clicked.connect(self._export_and_archive)
        ctrl_layout.addWidget(self.archive_log_btn)

        self.log_level_filter = QComboBox()
        self.log_level_filter.addItems(["All", "low", "medium", "high"])
        self.log_level_filter.currentTextChanged.connect(self._filter_logs)
        ctrl_layout.addWidget(QLabel("Filter:"))
        ctrl_layout.addWidget(self.log_level_filter)

        self.log_count_spin = QSpinBox()
        self.log_count_spin.setRange(10, 500)
        self.log_count_spin.setValue(100)
        self.log_count_spin.valueChanged.connect(self._refresh_data)
        ctrl_layout.addWidget(QLabel("Max entries:"))
        ctrl_layout.addWidget(self.log_count_spin)

        log_layout.addLayout(ctrl_layout)
        layout.addWidget(log_box)

        # --- Memory Data Sources ---
        memory_box = QGroupBox("Memory Data Sources")
        memory_layout = QVBoxLayout(memory_box)

        self.episodic_label = QLabel("Episodic events: --")
        self.semantic_label = QLabel("Semantic entries: --")
        self.intent_label = QLabel("Intent queries: --")

        memory_layout.addWidget(self.episodic_label)
        memory_layout.addWidget(self.semantic_label)
        memory_layout.addWidget(self.intent_label)
        layout.addWidget(memory_box)

        # --- Bottom: Export / Refresh ---
        bottom_layout = QHBoxLayout()
        self.export_btn = QPushButton("Export Logs...")
        self.export_btn.clicked.connect(self._export_logs)
        bottom_layout.addWidget(self.export_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_data)
        bottom_layout.addWidget(self.refresh_btn)

        layout.addLayout(bottom_layout)

        # Initial spacing
        layout.addStretch()

    def _refresh_data(self):
        """Refresh all dashboard data displays."""
        self._update_usage_stats()
        self._update_audit_logs()
        self._update_memory_stats()

    def _update_usage_stats(self):
        """Update local vs cloud usage statistics."""
        # Count from audit logs by action column: approved cloud requests are
        # the ones where data actually left the device; everything else (and
        # denied bursts) ran locally.
        try:
            all_logs = self.privacy_gate.audit.get_logs(limit=500) or []
            cloud_count = sum(
                1 for log in all_logs
                if log[1] == "cloud_request" and "denied" not in log[2]
            )
            local_count = sum(1 for log in all_logs if log[1] != "cloud_request")
            self.local_label.setText(f"Local: {local_count} calls")
            self.cloud_label.setText(f"Cloud: {cloud_count} calls (approved)")
        except Exception:
            self.local_label.setText("Local: -- calls")
            self.cloud_label.setText("Cloud: -- calls")

        # Update approval status
        if self.privacy_gate.approved:
            self.status_label.setText("Status: Cloud approval active")
            self.status_label.setStyleSheet(
                "font-size: 12px; color: #4caf50;"
            )
        else:
            self.status_label.setText("Status: Local-only mode (default)")
            self.status_label.setStyleSheet(
                "font-size: 12px; color: #ff9800;"
            )

    def _update_audit_logs(self):
        """Update the audit log display."""
        try:
            limit = self.log_count_spin.value()
            # Filter by selected level
            level = self.log_level_filter.currentText()
            all_logs = self.privacy_gate.audit.get_logs(limit=limit)

            # Apply filter
            if level != "All":
                filtered_logs = [
                    log for log in all_logs if log[3] == level
                ]
            else:
                filtered_logs = all_logs

            # Format for display
            lines = []
            for log_entry in filtered_logs[-50:]:  # Show last 50
                timestamp, action, detail, risk = log_entry[:4]
                risk_display = {"low": "LOW", "medium": "MED", "high": "HIGH"}.get(
                    risk, risk
                )
                lines.append(
                    f"<{timestamp[-8:]}> {risk_display:>5} | {action:30} | {detail}"
                )

            self.log_text.setPlainText("\n".join(lines) if lines else "No audit logs yet.")
        except Exception as e:
            self.log_text.setPlainText(f"Error loading logs: {e}")

    def _update_memory_stats(self):
        """Update memory data source counts."""
        try:
            # Episodic memory count
            episodic = self.memory_manager.episodic
            # We can't easily count without opening, so show a reasonable estimate
            self.episodic_label.setText(
                f"Episodic events: {self._count_episodic_events()}"
            )
            self.semantic_label.setText(
                f"Semantic entries: {self._count_semantic_entries()}"
            )
            self.intent_label.setText(
                f"Intent queries: active"
            )
        except Exception:
            self.episodic_label.setText("Episodic events: --")
            self.semantic_label.setText("Semantic entries: --")
            self.intent_label.setText("Intent queries: --")

    def _count_episodic_events(self) -> int:
        """Count episodes in the episodic memory store."""
        try:
            conn = self.memory_manager.episodic.conn
            cursor = conn.execute("SELECT COUNT(*) FROM events")
            return cursor.fetchone()[0]
        except Exception:
            return 0

    def _count_semantic_entries(self) -> int:
        """Count entries in semantic memory."""
        try:
            return self.memory_manager.semantic.count()
        except Exception:
            return 0

    def _export_and_archive(self):
        """Snapshot the audit log, record a `log_cleared` event, then trim.

        The snapshot is written before anything is deleted, and the
        `log_cleared` row survives the trim so the append-only trail still
        shows what happened and where the data went.
        """
        import datetime
        import json
        from pathlib import Path

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = Path(self.settings.data_dir) / "archives"
        archive_path = archive_dir / f"audit_log_{timestamp}.json"

        try:
            entries = self.privacy_gate.audit.get_logs(limit=500)
            keys = ("timestamp", "action", "detail", "risk_level")
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path.write_text(
                json.dumps([dict(zip(keys, row)) for row in entries], indent=2),
                encoding="utf-8",
            )

            # Record the wipe before deleting anything.
            self.privacy_gate.audit.log(
                action="log_cleared",
                detail=f"archived {len(entries)} entries to {archive_path}",
                risk_level="medium",
            )
            # Keep only the log_cleared trail; content now lives in the snapshot.
            self.privacy_gate.audit.conn.execute(
                "DELETE FROM audit WHERE action != 'log_cleared'"
            )
            self.privacy_gate.audit.conn.commit()

            self._refresh_data()
            self.log_text.append(f"\n✓ Logs archived to: {archive_path}")
        except Exception as e:
            self.log_text.append(f"\n✗ Archive failed: {e}")

    def _export_logs(self):
        """Export audit logs to a file."""
        import datetime
        from pathlib import Path

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = Path.home() / f".nexus" / f"audit_log_{timestamp}.db"

        try:
            # Copy the audit database
            import shutil
            shutil.copy2(
                self.privacy_gate.audit.conn.filename,
                export_path,
            )
            self.log_text.append(
                f"\n✓ Logs exported to: {export_path}"
            )
        except Exception as e:
            self.log_text.append(f"\n✗ Export failed: {e}")

    def _filter_logs(self, level: str):
        """Apply log level filter."""
        self._update_audit_logs()


def show_privacy_dashboard(parent=None):
    """Show the privacy dashboard modal dialog."""
    from Nexus.config import settings
    from Nexus.core.privacy_gate import PrivacyGate
    from Nexus.core.memory_manager import MemoryManager

    # If no parent provided, create a minimal instance
    if parent is None:
        # This would need a QApplication - user should integrate into their main window
        from PyQt6.QtWidgets import QApplication
        import sys
        app = QApplication(sys.argv) if QApplication.instance() is None else QApplication.instance()
        dashboard = PrivacyDashboard(settings, PrivacyGate(settings),
                                      MemoryManager(
                                          str(settings.db_path),
                                          str(settings.chroma_path)
                                      ))
        dashboard.show()
        return dashboard

    # If parent provided, create as child widget
    dashboard = PrivacyDashboard(
        parent.settings, parent.privacy_gate if hasattr(parent, 'privacy_gate') else PrivacyGate(parent.settings),
        parent.memory_manager if hasattr(parent, 'memory_manager') else MemoryManager(
            str(parent.settings.db_path),
            str(parent.settings.chroma_path)
        ),
        parent
    )
    dashboard.show()
    return dashboard