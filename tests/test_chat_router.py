"""Tests for S050 — M6: /clear --all purges global.db learnings."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import arke.memory.manager as mod
from arke.memory.manager import MemoryManager
from arke.chat_router import SLASH_COMMANDS, memory_forget


def test_codex_slash_command_registered():
    assert "/codex" in SLASH_COMMANDS


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    """MemoryManager wired to a temporary directory."""
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


class TestMemoryForgetAll:
    """memory_forget(mm, '--all') purges session and global memory."""

    def _seed(self, mm: MemoryManager) -> None:
        """Seed all four purge targets with one row each."""
        mm.query("session", "INSERT INTO chat_history (role, content) VALUES (?, ?)", ("user", "hello"))
        mm.query("session", "INSERT OR REPLACE INTO session_context (key, value) VALUES ('chat_notes', 'note')", ())
        mm.query("global", "INSERT INTO agent_learnings (intention_pattern, tool_sequence) VALUES (?, ?)", ("learned something", "[]"))
        mm.query("global", "INSERT INTO cognitive_threads (session_id, content) VALUES (?, ?)", ("sess-001", "thread content"))

    def _count(self, mm: MemoryManager, db: str, table: str) -> int:
        rows = mm.query(db, f"SELECT COUNT(*) AS n FROM {table}", ())
        return rows[0]["n"] if rows else 0

    def test_clear_all_purges_chat_history(self, mm):
        self._seed(mm)
        memory_forget(mm, "--all")
        assert self._count(mm, "session", "chat_history") == 0

    def test_clear_all_purges_agent_learnings(self, mm):
        self._seed(mm)
        memory_forget(mm, "--all")
        assert self._count(mm, "global", "agent_learnings") == 0

    def test_clear_all_purges_cognitive_threads(self, mm):
        self._seed(mm)
        memory_forget(mm, "--all")
        assert self._count(mm, "global", "cognitive_threads") == 0

    def test_clear_all_returns_minus_one(self, mm):
        """Sentinel value -1 distinguishes full purge from partial clear."""
        result = memory_forget(mm, "--all")
        assert result == -1

    def test_clear_standard_preserves_agent_learnings(self, mm):
        """memory_forget(mm, '') must NOT delete agent_learnings."""
        self._seed(mm)
        memory_forget(mm, "")
        assert self._count(mm, "global", "agent_learnings") == 1

    def test_clear_all_with_spaces(self, mm):
        """'  --all  ' (with surrounding spaces) must trigger full purge."""
        self._seed(mm)
        memory_forget(mm, "  --all  ")
        assert self._count(mm, "global", "agent_learnings") == 0
