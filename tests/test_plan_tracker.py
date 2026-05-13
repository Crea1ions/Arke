"""Tests for Phase 2 — PlanTracker: approval tracking and opt-in auto-exec."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

import arke.plan_tracker as pt_mod
from arke.plan_tracker import PlanTracker, plan_hash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_learnings (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            intention_pattern   TEXT    NOT NULL,
            tool_sequence       TEXT    NOT NULL DEFAULT '[]',
            success             INTEGER NOT NULL DEFAULT 1,
            outcome_summary     TEXT,
            lesson              TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            plan_hash           TEXT,
            plan_approved_count INTEGER DEFAULT 0,
            auto_executable     INTEGER DEFAULT 0,
            success_rate        REAL    DEFAULT 1.0
        );
    """)
    conn.commit()


@pytest.fixture()
def mm():
    """MemoryManager mock backed by in-memory SQLite for global.db queries."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_schema(conn)

    mock = MagicMock()

    def _query(db: str, sql: str, params: tuple = ()):
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.fetchall()

    mock.query.side_effect = _query
    return mock


@pytest.fixture()
def tracker(mm):
    return PlanTracker(memory=mm)


# ---------------------------------------------------------------------------
# TestPlanHash
# ---------------------------------------------------------------------------


class TestPlanHash:
    def test_same_text_same_hash(self):
        assert plan_hash("1. Lister les fichiers\n2. Analyser") == plan_hash(
            "1. Lister les fichiers\n2. Analyser"
        )

    def test_different_text_different_hash(self):
        assert plan_hash("step 1") != plan_hash("step 2")

    def test_whitespace_normalised(self):
        """Extra spaces / newlines must not change the hash."""
        assert plan_hash("  step 1  ") == plan_hash("step 1")

    def test_case_normalised(self):
        """Uppercase and lowercase must produce the same hash."""
        assert plan_hash("STEP ONE") == plan_hash("step one")

    def test_hash_is_64_chars(self):
        assert len(plan_hash("anything")) == 64


# ---------------------------------------------------------------------------
# TestPlanTrackerApproval
# ---------------------------------------------------------------------------


class TestPlanTrackerApproval:
    def test_first_approval_creates_row(self, tracker):
        phash = plan_hash("step 1")
        count = tracker.record_approval(phash, "test intention")
        assert count == 1

    def test_second_approval_increments(self, tracker):
        phash = plan_hash("step 1")
        tracker.record_approval(phash, "test")
        count = tracker.record_approval(phash, "test")
        assert count == 2

    def test_get_approved_count_zero_if_unknown(self, tracker):
        assert tracker.get_approved_count(plan_hash("unknown plan")) == 0

    def test_get_approved_count_matches_record_calls(self, tracker):
        phash = plan_hash("my plan")
        for _ in range(3):
            tracker.record_approval(phash, "intention")
        assert tracker.get_approved_count(phash) == 3


# ---------------------------------------------------------------------------
# TestPlanTrackerAutoExec
# ---------------------------------------------------------------------------


class TestPlanTrackerAutoExec:
    def test_auto_executable_false_by_default(self, tracker):
        phash = plan_hash("fresh plan")
        tracker.record_approval(phash, "test")
        assert tracker.is_auto_executable(phash) is False

    def test_is_auto_executable_false_when_mode_disabled(self, tracker, monkeypatch):
        """Even after explicit set, mode=disabled must return False."""
        phash = plan_hash("plan A")
        tracker.record_approval(phash, "test")
        tracker.set_auto_executable(phash, True)
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("disabled", 3))
        assert tracker.is_auto_executable(phash) is False

    def test_is_auto_executable_true_after_optin(self, tracker, monkeypatch):
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("after_consent", 3))
        phash = plan_hash("plan B")
        tracker.record_approval(phash, "test")
        tracker.set_auto_executable(phash, True)
        assert tracker.is_auto_executable(phash) is True

    def test_set_auto_executable_false_resets_count(self, tracker, monkeypatch):
        """Declining consent resets count to avoid re-prompting immediately."""
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("after_consent", 3))
        phash = plan_hash("plan C")
        for _ in range(3):
            tracker.record_approval(phash, "test")
        tracker.set_auto_executable(phash, False)
        assert tracker.get_approved_count(phash) == 0


# ---------------------------------------------------------------------------
# TestPlanTrackerOptinProposal
# ---------------------------------------------------------------------------


class TestPlanTrackerOptinProposal:
    def test_should_not_propose_when_mode_disabled(self, tracker, monkeypatch):
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("disabled", 3))
        phash = plan_hash("plan X")
        for _ in range(3):
            tracker.record_approval(phash, "test")
        assert tracker.should_propose_optin(phash) is False

    def test_should_propose_after_threshold_and_not_yet_set(self, tracker, monkeypatch):
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("after_consent", 3))
        phash = plan_hash("plan Y")
        for _ in range(3):
            tracker.record_approval(phash, "test")
        assert tracker.should_propose_optin(phash) is True

    def test_should_not_propose_below_threshold(self, tracker, monkeypatch):
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("after_consent", 3))
        phash = plan_hash("plan Z")
        tracker.record_approval(phash, "test")  # only 1 approval
        assert tracker.should_propose_optin(phash) is False

    def test_should_not_propose_when_already_opted_in(self, tracker, monkeypatch):
        monkeypatch.setattr(pt_mod, "_load_auto_exec_config", lambda: ("after_consent", 3))
        phash = plan_hash("plan W")
        for _ in range(3):
            tracker.record_approval(phash, "test")
        tracker.set_auto_executable(phash, True)
        assert tracker.should_propose_optin(phash) is False
