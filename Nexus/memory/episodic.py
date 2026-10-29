"""Episodic memory backed by SQLite."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path


class EpisodicMemory:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: stores may be written by the engine thread
        # and closed by the atexit hook on the main thread.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                source TEXT,
                content TEXT,
                role TEXT
            )
        """)
        # Databases created before the role column existed get it added here.
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(events)")}
        if "role" not in columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN role TEXT")
        self.conn.commit()

    @staticmethod
    def _escape_like(text: str) -> str:
        """Escape LIKE wildcards so user text matches literally (`%`, `_`, `\\`)."""
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def add_event(self, source: str, content: str, role: str | None = None):
        self.conn.execute(
            "INSERT INTO events (source, content, role) VALUES (?, ?, ?)",
            (source, content, role),
        )
        self.conn.commit()

    def search(self, query: str, limit: int = 10, include_role: bool = False):
        columns = (
            "timestamp, source, content, role"
            if include_role
            else "timestamp, source, content"
        )
        cursor = self.conn.execute(
            f"SELECT {columns} FROM events "
            "WHERE content LIKE ? ESCAPE '\\' ORDER BY timestamp DESC LIMIT ?",
            (f"%{self._escape_like(query)}%", limit),
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
