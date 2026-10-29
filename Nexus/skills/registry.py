"""Skill Registry stores and retrieves automation skill metadata."""
import sqlite3
from pathlib import Path
import json


class SkillRegistry:
    """Manages skill registration, lookup, and scheduling."""

    def __init__(self, db_path=None):
        if db_path is None:
            from Nexus.config import settings
            db_path = settings.skills_dir / "skills.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the APScheduler job thread and the engine
        # thread share this connection (SQLite serializes access; Python's
        # sqlite3 build is thread-safe for serialized mode).
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                python_code TEXT,
                trigger_phrase TEXT,
                cron_schedule TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                last_run TEXT,
                exit_code INTEGER,
                runtime REAL
            )"""
        )
        self.conn.commit()

    def register(self, skill_name, description, python_code,
                 trigger_phrase=None, cron_schedule=None, update_if_exists=False):
        """Register a new skill in the registry.

        Returns True if successful, False if the skill name already exists —
        unless `update_if_exists=True`, in which case the existing row is
        updated in place and True is returned. Trigger/cron values of None
        leave any existing schedule untouched, so regenerating a skill's code
        does not silently drop its cron job.
        """
        try:
            self.conn.execute(
                "INSERT INTO skills (name, description, python_code, trigger_phrase, cron_schedule) "
                "VALUES (?, ?, ?, ?, ?)",
                (skill_name, description, python_code, trigger_phrase, cron_schedule),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            if not update_if_exists:
                return False
            self.conn.execute(
                "UPDATE skills SET description = ?, python_code = ?, "
                "trigger_phrase = COALESCE(?, trigger_phrase), "
                "cron_schedule = COALESCE(?, cron_schedule) "
                "WHERE name = ?",
                (description, python_code, trigger_phrase, cron_schedule, skill_name),
            )
            self.conn.commit()
            return True

    def get(self, skill_name):
        """Retrieve a skill by name."""
        cursor = self.conn.execute(
            "SELECT name, description, python_code, trigger_phrase, cron_schedule, created_at, last_run, exit_code, runtime FROM skills WHERE name = ?",
            (skill_name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "description": row[1],
            "python_code": row[2],
            "trigger_phrase": row[3],
            "cron_schedule": row[4],
            "created_at": row[5],
            "last_run": row[6],
            "exit_code": row[7],
            "runtime": row[8],
        }

    def list_all(self):
        """List all registered skills."""
        cursor = self.conn.execute(
            "SELECT name, description, trigger_phrase, cron_schedule, created_at FROM skills ORDER BY name"
        )
        return [
            {
                "name": row[0],
                "description": row[1],
                "trigger_phrase": row[2],
                "cron_schedule": row[3],
                "created_at": row[4],
            }
            for row in cursor.fetchall()
        ]

    def update_last_run(self, skill_name, exit_code, runtime):
        """Update the last runtime metrics for a skill."""
        self.conn.execute(
            "UPDATE skills SET last_run = datetime('now'), exit_code = ?, runtime = ? WHERE name = ?",
            (exit_code, runtime, skill_name),
        )
        self.conn.commit()

    def delete(self, skill_name):
        """Delete a skill from the registry."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM skills WHERE name = ?",
            (skill_name,),
        )
        if cursor.fetchone()[0] == 0:
            return False
        self.conn.execute("DELETE FROM skills WHERE name = ?", (skill_name,))
        self.conn.commit()
        return True

    def close(self):
        """Close the underlying connection (idempotent)."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False