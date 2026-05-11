"""MemoryManager — manages the 4 SQLite databases for Arke kernel v0.1.

Databases:
    global   — persistent preferences, tool usage, skills
    project  — docs and FTS5 full-text search
    session  — transient state and active tasks
    cache    — LLM response cache with TTL

All databases are opened in WAL mode (``journal_mode=WAL``) for
concurrent read safety.  Databases and tables are created lazily on
first access.
"""

from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_BASE_DIR = Path(__file__).parent.parent.parent
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Tables that belong to each database (used for selective schema init)
_DB_TABLE_PREFIXES: dict[str, list[str]] = {
    "global": [
        "config", "tool_usage", "skills", "pattern_log", "agent_learnings",
        "cognitive_threads", "interaction_density", "initiative_simulation_log",
    ],
    "project": ["docs"],
    "session": ["session_context", "active_tasks", "chat_history", "memory_fts"],
    "cache": ["llm_cache"],
}


def _load_db_paths() -> dict[str, Path]:
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        mem = data.get("memory", {})
        return {
            "global": _BASE_DIR / mem.get("global_path", "memory/global.db"),
            "project": _BASE_DIR / mem.get("project_path", "memory/project.db"),
            "session": _BASE_DIR / mem.get("session_path", "memory/session.db"),
            "cache": _BASE_DIR / mem.get("cache_path", "memory/cache.db"),
        }
    except FileNotFoundError:
        # Fallback defaults
        return {
            "global": _BASE_DIR / "memory" / "global.db",
            "project": _BASE_DIR / "memory" / "project.db",
            "session": _BASE_DIR / "memory" / "session.db",
            "cache": _BASE_DIR / "memory" / "cache.db",
        }


class MemoryManager:
    """Thread-safe manager for the 4 Arke SQLite databases.

    Each call opens a short-lived connection to avoid long-held locks.
    WAL mode is activated once per database file at bootstrap.
    """

    def __init__(self) -> None:
        self._paths = _load_db_paths()
        self._schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        for db_name in self._paths:
            self._bootstrap(db_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, db: str, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute *query* on *db* and return all rows.

        Args:
            db: Database name — ``'global'``, ``'project'``, ``'session'``, ``'cache'``.
            query: SQL statement (SELECT or DML).
            params: Positional parameters for parameterised queries.

        Returns:
            List of ``sqlite3.Row`` objects.
        """
        with self._connect(db) as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.fetchall()

    def search(self, db: str, term: str) -> list[sqlite3.Row]:
        """FTS5 full-text search on ``docs_fts`` (project.db).

        Args:
            db: Must be ``'project'`` for FTS5 results.
            term: Search term.

        Returns:
            Matching rows from ``docs_fts``.
        """
        fts_query = "SELECT * FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank"
        with self._connect(db) as conn:
            cursor = conn.execute(fts_query, (term,))
            return cursor.fetchall()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect(self, db: str) -> sqlite3.Connection:
        path = self._paths[db]
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def _bootstrap(self, db: str) -> None:
        """Create tables and enable WAL mode if the database is new."""
        path = self._paths[db]
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect(db) as conn:
            # Enable WAL for all databases
            conn.execute("PRAGMA journal_mode=WAL")
            # Run only the relevant schema sections
            self._init_schema(conn, db)
            conn.commit()

        # One-time FTS5 rebuild for session.db to populate existing chat_history rows
        if db == "session":
            with self._connect(db) as conn:
                try:
                    conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
                    conn.commit()
                except Exception:  # noqa: BLE001
                    pass  # OK if rebuild already ran or no rows exist

        log.info("memory.bootstrap", db=db, path=str(path))

    def _init_schema(self, conn: sqlite3.Connection, db: str) -> None:
        """Execute schema statements relevant to *db*."""
        # Split schema on CREATE TABLE / CREATE VIRTUAL TABLE boundaries
        # Note: We handle CREATE TRIGGER separately since they contain semicolons in the body
        statements = [s.strip() for s in self._schema.split(";") if s.strip()]
        prefixes = _DB_TABLE_PREFIXES.get(db, [])

        # First pass: Create tables
        for stmt in statements:
            low = stmt.lower()
            
            # Process CREATE TABLE statements that match this db's tables
            if "create table" in low or "create virtual table" in low:
                if any(f"table if not exists {p}" in low for p in prefixes):
                    conn.execute(stmt)
        
        # Second pass: Handle triggers directly from raw schema text
        # This avoids issues with semicolons inside trigger bodies
        if db == "session":
            import re
            # Find all CREATE TRIGGER ... END; blocks for chat_history
            trigger_pattern = r'CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+\w+\s+.*?\s+ON\s+chat_history\s+BEGIN\s+.*?\s+END;'
            triggers = re.findall(trigger_pattern, self._schema, re.IGNORECASE | re.DOTALL)
            for trigger_stmt in triggers:
                conn.execute(trigger_stmt)
