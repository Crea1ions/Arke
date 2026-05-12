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
    # Phase 1 is now the default (observation_mode=False in arke.toml)
    assert orch._observation_mode is False
    # Queue is empty at construction → False regardless of mode
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


# ---------------------------------------------------------------------------
# Session 025: Phase 1 — active initiative delivery
# ---------------------------------------------------------------------------


@pytest.fixture()
def so_phase1(mm):
    """SocialOrchestrator with observation_mode=False (Phase 1)."""
    mock_mm, conn = mm
    orch = SocialOrchestrator(mock_mm, "test-phase1-session")
    orch._observation_mode = False  # bypass arke.toml to force Phase 1
    yield orch, conn
    orch.stop()


class TestSocialOrchestratorPhase1:
    """Phase 1: observation_mode=False — queue fill, delivery, suppression."""

    def test_generate_and_queue_sets_pending_initiative(self, so_phase1):
        """`_generate_and_queue` fills `_pending_initiative` and `_pending_thread_id`."""
        orch, _ = so_phase1
        thread = {"id": 42, "content": "problème connexion réseau timeout", "summary": "bug réseau"}
        orch._generate_and_queue(thread, ["REPRISE"])
        assert orch._pending_initiative is not None
        assert len(orch._pending_initiative) > 10
        assert orch._pending_thread_id == 42

    def test_generate_and_queue_uses_cig_template(self, so_phase1):
        """Generated text uses the canonical CIG template (ends with '?')."""
        orch, _ = so_phase1
        thread = {"id": 7, "content": "architecture microservices", "summary": "design services"}
        orch._generate_and_queue(thread, ["REPRISE", "QUESTION"])
        assert orch._pending_initiative is not None
        assert orch._pending_initiative.endswith("?")

    def test_generate_and_queue_empty_thread_does_not_queue(self, so_phase1):
        """Thread with no content and no summary → queue stays empty."""
        orch, _ = so_phase1
        thread = {"id": 99, "content": "", "summary": ""}
        orch._generate_and_queue(thread, ["REPRISE"])
        assert orch._pending_initiative is None
        assert orch._pending_thread_id is None

    def test_has_pending_initiative_true_when_queued(self, so_phase1):
        """`has_pending_initiative()` returns True in Phase 1 when queue is filled."""
        orch, _ = so_phase1
        orch._pending_initiative = "On avait exploré une piste sur « design services » récemment."
        assert orch.has_pending_initiative() is True

    def test_has_pending_initiative_false_when_empty(self, so_phase1):
        """`has_pending_initiative()` returns False in Phase 1 when queue is empty."""
        orch, _ = so_phase1
        orch._pending_initiative = None
        assert orch.has_pending_initiative() is False

    def test_pop_initiative_returns_text_and_clears_queue(self, so_phase1):
        """`pop_initiative()` returns the queued text and clears it."""
        orch, _ = so_phase1
        orch._pending_initiative = "On avait exploré une piste sur « test » récemment. Tu veux reprendre ?"
        orch._pending_thread_id = None  # avoid DB call in _mark_initiative_sent
        text = orch.pop_initiative()
        assert "test" in text
        assert orch._pending_initiative is None

    def test_suppression_reason_user_active_when_not_idle(self, so_phase1):
        """`_suppression_reason()` returns 'user_active' when user just interacted."""
        orch, _ = so_phase1
        orch.record_input()  # sets _last_input_at = now
        reason = orch._suppression_reason()
        assert reason == "user_active"

    def test_suppression_reason_already_queued(self, so_phase1):
        """`_suppression_reason()` returns 'already_queued' when pending initiative exists."""
        orch, _ = so_phase1
        orch._last_input_at = time.time() - 9999  # force idle
        orch._pending_initiative = "existing initiative text"
        reason = orch._suppression_reason()
        assert reason == "already_queued"

    def test_suppression_reason_none_when_idle_and_queue_empty(self, so_phase1):
        """`_suppression_reason()` returns None (can proceed) when idle and nothing queued."""
        orch, _ = so_phase1
        orch._last_input_at = time.time() - 9999
        orch._pending_initiative = None
        reason = orch._suppression_reason()
        assert reason is None
