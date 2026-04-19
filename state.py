"""
Bridge State DB — SQLite-backed state tracking for every idea in the pipeline.
Prevents duplicate processing and gives the operator full pipeline visibility.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

_log = logging.getLogger("claude_bridge.state")


class BridgeStateDB:
    def __init__(self, db_path: str = "bridge_state.db"):
        self.db_path = db_path
        self._init()

    def _init(self):
        conn = self._conn()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline (
                    idea_id       TEXT PRIMARY KEY,
                    stage         TEXT NOT NULL,
                    title         TEXT,
                    score         INTEGER,
                    project_id    TEXT,
                    deploy_url    TEXT,
                    checkout_url  TEXT,
                    repo_url      TEXT,
                    payload       TEXT,
                    meta          TEXT,
                    created_at    TEXT,
                    updated_at    TEXT
                )
            """)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    # ── Writes ────────────────────────────────────────────────────────────────

    def mark_received(self, idea_id: str, payload: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO pipeline
                    (idea_id, stage, title, score, payload, created_at, updated_at)
                VALUES (?, 'received', ?, ?, ?, ?, ?)
            """, (
                idea_id,
                payload.get("title", ""),
                payload.get("score", 0),
                json.dumps(payload),
                self._now(),
                self._now(),
            ))

    def update_stage(self, idea_id: str, stage: str, meta: Optional[dict] = None):
        with self._conn() as conn:
            extra = meta or {}
            conn.execute("""
                UPDATE pipeline SET
                    stage      = ?,
                    project_id = COALESCE(?, project_id),
                    deploy_url = COALESCE(?, deploy_url),
                    checkout_url = COALESCE(?, checkout_url),
                    repo_url   = COALESCE(?, repo_url),
                    meta       = ?,
                    updated_at = ?
                WHERE idea_id = ?
            """, (
                stage,
                extra.get("project_id"),
                extra.get("deploy_url"),
                extra.get("checkout_url"),
                extra.get("repo_url"),
                json.dumps(extra),
                self._now(),
                idea_id,
            ))

    # ── Reads ─────────────────────────────────────────────────────────────────

    def already_processed(self, idea_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT idea_id FROM pipeline WHERE idea_id = ?", (idea_id,)
            ).fetchone()
        return row is not None

    def get(self, idea_id: str) -> Optional[dict]:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM pipeline WHERE idea_id = ?", (idea_id,)
                ).fetchone()
            if not row:
                return None
            cols = ["idea_id","stage","title","score","project_id","deploy_url",
                    "checkout_url","repo_url","payload","meta","created_at","updated_at"]
            return dict(zip(cols, row))
        except sqlite3.Error:
            _log.exception("DB read error (get)")
            return None

    def count_processed(self) -> int:
        try:
            with self._conn() as conn:
                return conn.execute("SELECT COUNT(*) FROM pipeline").fetchone()[0]
        except sqlite3.Error:
            _log.exception("DB read error (count_processed)")
            return 0

    def count_by_stage(self, stage: str) -> int:
        try:
            with self._conn() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM pipeline WHERE stage = ?", (stage,)
                ).fetchone()[0]
        except sqlite3.Error:
            _log.exception("DB read error (count_by_stage)")
            return 0

    def count_in_progress(self) -> int:
        try:
            terminal = ("launched", "factory_failed", "brief_invalid", "error", "skipped")
            placeholders = ",".join("?" * len(terminal))
            with self._conn() as conn:
                return conn.execute(
                    f"SELECT COUNT(*) FROM pipeline WHERE stage NOT IN ({placeholders})",
                    terminal,
                ).fetchone()[0]
        except sqlite3.Error:
            _log.exception("DB read error (count_in_progress)")
            return 0

    def all_launched(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT idea_id, title, deploy_url, checkout_url, created_at "
                "FROM pipeline WHERE stage = 'launched' ORDER BY created_at DESC"
            ).fetchall()
        return [
            {"idea_id": r[0], "title": r[1], "deploy_url": r[2],
             "checkout_url": r[3], "launched_at": r[4]}
            for r in rows
        ]
