"""Unit tests for arke.memory.manager (P1.2)."""

from __future__ import annotations

import sqlite3

import pytest

from arke.memory.manager import MemoryManager


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    """Return a MemoryManager wired to a temporary directory."""
    # Redirect DB paths to tmp_path
    import arke.memory.manager as mod

    monkeypatch.setattr(
        mod,
        "_load_db_paths",
        lambda: {
            "global": tmp_path / "global.db",
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    return MemoryManager()


class TestBootstrap:
    def test_databases_created(self, mm, tmp_path):
        for name in ("global.db", "project.db", "session.db", "cache.db"):
            assert (tmp_path / name).exists()

    def test_wal_mode_enabled(self, mm, tmp_path):
        conn = sqlite3.connect(tmp_path / "global.db")
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert row[0] == "wal"

    def test_global_tables_exist(self, mm, tmp_path):
        conn = sqlite3.connect(tmp_path / "global.db")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert {"config", "tool_usage", "skills"}.issubset(tables)

    def test_session_tables_exist(self, mm, tmp_path):
        conn = sqlite3.connect(tmp_path / "session.db")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert {"session_context", "active_tasks"}.issubset(tables)

    def test_cache_table_exists(self, mm, tmp_path):
        conn = sqlite3.connect(tmp_path / "cache.db")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "llm_cache" in tables


class TestQuery:
    def test_insert_and_select(self, mm):
        mm.query("global", "INSERT INTO config (key, value) VALUES (?, ?)", ("lang", "fr"))
        rows = mm.query("global", "SELECT value FROM config WHERE key = ?", ("lang",))
        assert rows[0]["value"] == "fr"

    def test_empty_result(self, mm):
        rows = mm.query("global", "SELECT * FROM config")
        assert rows == []


class TestSearch:
    def test_fts_returns_empty_on_new_db(self, mm):
        rows = mm.search("project", "arke")
        assert rows == []


class TestFTS5Sync:
    def test_fts5_sync_after_insert(self, mm):
        """Verify FTS5 trigger automatically syncs chat_history inserts to memory_fts.
        
        This test confirms that:
        1. Inserting a row into chat_history fires the trigger
        2. memory_fts contains the new row immediately (no rebuild needed)
        3. FTS5 full-text search finds the content
        """
        # Insert a message into chat_history
        mm.query(
            "session",
            "INSERT INTO chat_history (role, content, model_used) VALUES (?, ?, ?)",
            ("user", "recherche vectorielle test", "flash"),
        )
        
        # Immediately query memory_fts (trigger should have fired)
        # FTS5 MATCH syntax for full-text search
        rows = mm.query(
            "session",
            "SELECT rowid, content FROM memory_fts WHERE memory_fts MATCH ?",
            ("vectorielle",)
        )
        
        # Assert the row appears in FTS5
        assert len(rows) == 1
        assert "recherche vectorielle test" in rows[0]["content"]
    
    def test_fts5_sync_multiple_inserts(self, mm):
        """Verify multiple inserts all sync to FTS5."""
        messages = [
            ("user", "premier message test"),
            ("arke", "réponse du système"),
            ("user", "deuxième interrogation"),
        ]
        
        for role, content in messages:
            mm.query(
                "session",
                "INSERT INTO chat_history (role, content) VALUES (?, ?)",
                (role, content),
            )
        
        # Search for a term that should find multiple rows
        rows = mm.query(
            "session",
            "SELECT COUNT(*) as cnt FROM memory_fts"
        )
        
        # Assert all 3 rows are in FTS5
        assert rows[0]["cnt"] == 3
    
    def test_fts5_search_finds_content(self, mm):
        """Verify FTS5 search actually finds messages by content."""
        # Insert a unique message
        mm.query(
            "session",
            "INSERT INTO chat_history (role, content) VALUES (?, ?)",
            ("user", "unique_marker_12345"),
        )
        
        # Search for it using FTS5 MATCH
        rows = mm.query(
            "session",
            "SELECT content FROM memory_fts WHERE memory_fts MATCH ?",
            ("unique_marker",)
        )
        
        assert len(rows) == 1
        assert "unique_marker_12345" in rows[0]["content"]
