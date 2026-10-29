"""Append-only audit logger."""
import sqlite3
from datetime import datetime
from pathlib import Path


class AuditLogger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                action TEXT,
                actor TEXT DEFAULT 'user',
                detail TEXT,
                risk_level TEXT,
                ip_address TEXT DEFAULT '127.0.0.1'
            )
        """)
        self.conn.commit()

    def log(self, action: str, detail: str, risk_level: str = "low",
            actor: str = "user", ip_address: str | None = None):
        """Append one row; actor/ip identify the request context the entry came from."""
        self.conn.execute(
            "INSERT INTO audit (action, actor, detail, risk_level, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (action, actor, detail, risk_level, ip_address or "127.0.0.1"),
        )
        self.conn.commit()

    def get_logs(self, limit: int = 100):
        cursor = self.conn.execute(
            "SELECT timestamp, action, detail, risk_level FROM audit ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()

    def close(self):
        """Close the underlying connection (idempotent)."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
