"""Tests for arke.social_orchestrator — Phase 0C cognitive continuity."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

import pytest

from arke.social_orchestrator import SocialOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mm():
    """Minimal MemoryManager mock with in-memory SQLite for interaction_density."""
    mock = MagicMock()

    # In-memory connection for density queries
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS interaction_density "
        "(day TEXT PRIMARY KEY, exchange_count INTEGER DEFAULT 0, avg_depth_score REAL DEFAULT 0.0)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cognitive_threads "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, content TEXT, "
        "summary TEXT, source_exchange_at TEXT, importance_score REAL DEFAULT 0.5, "
        "status TEXT DEFAULT 'open', activation_count INTEGER DEFAULT 0, "
        "ignored_count INTEGER DEFAULT 0, last_activated_at TEXT, "
        "rescored_at TEXT, created_at TEXT, tags TEXT DEFAULT '[]')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_context "
        "(key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()

    mock.conn.return_value.__enter__ = lambda s: conn
    mock.conn.return_value.__exit__ = MagicMock(return_value=False)

    # Make conn() a context manager
    cm = MagicMock()
    cm.__enter__ = lambda s: conn
    cm.__exit__ = MagicMock(return_value=False)
    mock.conn.return_value = cm
    mock.conn.side_effect = lambda db: cm

    return mock, conn


@pytest.fixture()
def so(mm):
    mock_mm, conn = mm
    orchestrator = SocialOrchestrator(mock_mm, "test-session-id")
    yield orchestrator, conn
    orchestrator.stop()


# ---------------------------------------------------------------------------
# is_user_idle / record_input
# ---------------------------------------------------------------------------


def test_is_user_idle_false_just_after_input(so):
    orch, _ = so
    orch.record_input()
    assert not orch.is_user_idle()


def test_is_user_idle_true_when_old_timestamp(so):
    orch, _ = so
    # Artificially set last_input far in the past
    orch._last_input_at = time.time() - 9999
    assert orch.is_user_idle()


# ---------------------------------------------------------------------------
# Phase 0: observation mode
# ---------------------------------------------------------------------------


def test_has_pending_initiative_false_in_observation_mode(so):
    orch, _ = so
    assert orch._observation_mode is True
    assert not orch.has_pending_initiative()


def test_pop_initiative_returns_none_in_observation_mode(so):
    orch, _ = so
    assert orch.pop_initiative() is None


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


def test_pause_disables_initiatives(so):
    orch, _ = so
    orch.pause(2.0)
    assert orch._enabled is False


def test_resume_clears_pause(so):
    orch, _ = so
    orch.pause(2.0)
    orch.resume()
    assert orch._enabled is True


# ---------------------------------------------------------------------------
# Pattern selection by density tier
# ---------------------------------------------------------------------------


def test_select_allowed_patterns_low_density(so):
    orch, _ = so
    with patch.object(orch, "_get_density_score", return_value=1.0):
        patterns = orch._select_allowed_patterns()
    assert patterns == ["REPRISE"]


def test_select_allowed_patterns_mid_density(so):
    orch, _ = so
    with patch.object(orch, "_get_density_score", return_value=5.0):
        patterns = orch._select_allowed_patterns()
    assert "QUESTION" in patterns
    assert "REPRISE" in patterns


def test_select_allowed_patterns_high_density(so):
    orch, _ = so
    with patch.object(orch, "_get_density_score", return_value=10.0):
        patterns = orch._select_allowed_patterns()
    assert len(patterns) == 4
