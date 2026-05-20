"""Unit tests for arke.memory.manager (P1.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

import arke.memory.manager as mod
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

    def test_db_permissions_600(self, mm, tmp_path):
        """Newly created .db files must have owner-only permissions (600)."""
        import stat

        for name in ("global.db", "project.db", "session.db", "cache.db"):
            path = tmp_path / name
            mode = stat.S_IMODE(path.stat().st_mode)
            assert mode == 0o600, f"{name} has mode {oct(mode)}, expected 0o600"

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


def test_load_db_paths_prefers_workspace_config(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_cfg_dir = workspace_root / ".arke" / "config"
    workspace_cfg_dir.mkdir(parents=True, exist_ok=True)
    workspace_cfg = workspace_cfg_dir / "workspace.toml"

    workspace_cfg.write_text(
        "[memory]\n"
        "global_path = \".arke/memory/global.db\"\n"
        "project_path = \".arke/memory/project.db\"\n"
        "session_path = \".arke/sessions/session_custom.db\"\n"
        "cache_path = \".arke/memory/cache.db\"\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace_root))

    paths = mod._load_db_paths()

    assert paths["global"] == workspace_root / ".arke" / "memory" / "global.db"
    assert paths["project"] == workspace_root / ".arke" / "memory" / "project.db"
    assert paths["session"] == workspace_root / ".arke" / "sessions" / "session_custom.db"
    assert paths["cache"] == workspace_root / ".arke" / "memory" / "cache.db"


def test_load_db_paths_workspace_default_session_is_dated(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_cfg_dir = workspace_root / ".arke" / "config"
    workspace_cfg_dir.mkdir(parents=True, exist_ok=True)
    workspace_cfg = workspace_cfg_dir / "workspace.toml"

    workspace_cfg.write_text(
        "[memory]\n"
        "global_path = \".arke/memory/global.db\"\n"
        "project_path = \".arke/memory/project.db\"\n"
        "cache_path = \".arke/memory/cache.db\"\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace_root))

    paths = mod._load_db_paths()

    expected_name = f"session_{datetime.now().strftime('%Y%m%d')}.db"
    assert paths["session"] == workspace_root / ".arke" / "sessions" / expected_name


# ---------------------------------------------------------------------------
# S050 — H3/H5: DB permissions migration
# ---------------------------------------------------------------------------


def test_db_permissions_migration_from_644(tmp_path, monkeypatch):
    """Existing .db files with world-readable permissions (644) must be
    migrated to 600 when MemoryManager bootstraps."""
    import os
    import stat

    # Pre-create a global.db with 644 permissions (as if created before the fix)
    db_path = tmp_path / "global.db"
    db_path.touch()
    os.chmod(db_path, 0o644)
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o644

    monkeypatch.setattr(
        mod,
        "_load_db_paths",
        lambda: {
            "global": db_path,
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    MemoryManager()

    mode = stat.S_IMODE(db_path.stat().st_mode)
    assert mode == 0o600, f"Expected 600 after migration, got {oct(mode)}"
