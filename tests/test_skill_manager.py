"""Tests for P2.2 — SkillManager: usage tracking and routing weights."""

from __future__ import annotations

import pytest

import arke.memory.manager as mem_mod
from arke.memory.manager import MemoryManager
from arke.skill_manager import BOOST_THRESHOLD, SkillManager


# ---------------------------------------------------------------------------
# Fixtures — isolated SQLite databases in a temp directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    """MemoryManager wired to a temporary directory (no side-effects)."""
    monkeypatch.setattr(
        mem_mod,
        "_load_db_paths",
        lambda: {
            "global": tmp_path / "global.db",
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    return MemoryManager()


@pytest.fixture()
def sm(mm):
    """SkillManager using the isolated MemoryManager."""
    return SkillManager(memory=mm)


# ---------------------------------------------------------------------------
# TestRecordUsage
# ---------------------------------------------------------------------------


class TestRecordUsage:
    def test_record_success_inserts_row(self, sm, mm):
        sm.record_success("cli")
        rows = mm.query("global", "SELECT * FROM tool_usage WHERE tool_name = ?", ("cli",))
        assert len(rows) == 1
        assert rows[0]["success"] == 1

    def test_record_failure_inserts_row(self, sm, mm):
        sm.record_failure("llm")
        rows = mm.query("global", "SELECT * FROM tool_usage WHERE tool_name = ?", ("llm",))
        assert len(rows) == 1
        assert rows[0]["success"] == 0

    def test_record_success_stores_cost_and_tokens(self, sm, mm):
        sm.record_success("llm", cost_eur=0.003, tokens_used=450)
        rows = mm.query("global", "SELECT * FROM tool_usage WHERE tool_name = ?", ("llm",))
        assert rows[0]["cost_eur"] == pytest.approx(0.003)
        assert rows[0]["tokens_used"] == 450

    def test_multiple_records_accumulate(self, sm, mm):
        for _ in range(3):
            sm.record_success("cli")
        rows = mm.query("global", "SELECT * FROM tool_usage WHERE tool_name = ?", ("cli",))
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# TestGetWeight
# ---------------------------------------------------------------------------


class TestGetWeight:
    def test_unknown_tool_returns_1(self, sm):
        assert sm.get_weight("unknown_tool") == 1.0

    def test_below_threshold_returns_1(self, sm):
        for _ in range(BOOST_THRESHOLD - 1):
            sm.record_success("fs")
        assert sm.get_weight("fs") == 1.0

    def test_at_threshold_returns_2(self, sm):
        for _ in range(BOOST_THRESHOLD):
            sm.record_success("cli")
        assert sm.get_weight("cli") == 2.0

    def test_above_threshold_returns_2(self, sm):
        for _ in range(BOOST_THRESHOLD + 5):
            sm.record_success("sqlite")
        assert sm.get_weight("sqlite") == 2.0

    def test_failures_do_not_count_toward_boost(self, sm):
        for _ in range(BOOST_THRESHOLD):
            sm.record_failure("cli")
        assert sm.get_weight("cli") == 1.0

    def test_mixed_counts_below_threshold(self, sm):
        for _ in range(BOOST_THRESHOLD - 2):
            sm.record_success("cli")
        for _ in range(5):
            sm.record_failure("cli")
        assert sm.get_weight("cli") == 1.0


# ---------------------------------------------------------------------------
# TestGetStats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_empty_returns_empty_list(self, sm):
        assert sm.get_stats() == []

    def test_single_tool_counts(self, sm):
        sm.record_success("cli")
        sm.record_failure("cli")
        stats = sm.get_stats()
        assert len(stats) == 1
        row = stats[0]
        assert row["tool_name"] == "cli"
        assert row["total_calls"] == 2
        assert row["successes"] == 1
        assert row["success_rate"] == 50.0

    def test_sorted_by_successes_descending(self, sm):
        for _ in range(3):
            sm.record_success("llm")
        for _ in range(5):
            sm.record_success("cli")
        stats = sm.get_stats()
        assert stats[0]["tool_name"] == "cli"
        assert stats[1]["tool_name"] == "llm"

    def test_perfect_success_rate(self, sm):
        for _ in range(BOOST_THRESHOLD):
            sm.record_success("fs")
        stats = sm.get_stats()
        assert stats[0]["success_rate"] == 100.0


# ---------------------------------------------------------------------------
# TestRouterWeights — test select_tool weight integration (no DB needed)
# ---------------------------------------------------------------------------


class TestRouterWeights:
    def test_boosted_cli_preferred_over_llm_fallback(self):
        from arke import router

        weights = {"cli": 2.0, "fs": 1.0, "sqlite": 1.0, "llm": 1.0}
        assert router.select_tool("do something ambiguous entirely", {}, weights) == "cli"

    def test_no_boost_falls_back_to_llm(self):
        from arke import router

        weights = {"cli": 1.0, "fs": 1.0, "sqlite": 1.0, "llm": 1.0}
        assert router.select_tool("do something ambiguous entirely", {}, weights) == "llm"

    def test_keyword_match_wins_over_boost(self):
        from arke import router

        # "read" is an FS keyword and not a CLI command — must win even when cli is boosted
        weights = {"cli": 2.0, "fs": 1.0, "sqlite": 1.0, "llm": 1.0}
        assert router.select_tool("read large files from disk", {}, weights) == "fs"

    def test_no_weights_arg_unchanged_behaviour(self):
        from arke import router

        # Calling without weights must behave exactly as before P2.2
        assert router.select_tool("grep errors access.log", {}) == "cli"
        assert router.select_tool("read the config file", {}) == "fs"
        assert router.select_tool("query database for users", {}) == "sqlite"
