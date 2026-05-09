"""Tests for P3.1 — SkillRegistry: activation, listing, pruning, touch."""

from __future__ import annotations

import pytest

import arke.memory.manager as mem_mod
from arke.memory.manager import MemoryManager
from arke.skill_detector import SkillTemplate
from arke.skill_registry import PRUNE_DAYS, SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
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
def registry(mm):
    """SkillRegistry using the isolated MemoryManager."""
    return SkillRegistry(memory=mm)


@pytest.fixture()
def sample_template():
    return SkillTemplate(
        name="analyse-logs-nginx",
        description="Skill auto-détecté : 'analyse logs nginx' via cli (5×)",
        prompt_template="Tu es spécialisé dans : analyse logs nginx.\nUtilise l'outil cli.",
        tool="cli",
        trigger_count=5,
        bucket="analyse logs nginx",
    )


# ---------------------------------------------------------------------------
# TestActivate
# ---------------------------------------------------------------------------


class TestActivate:
    def test_activate_creates_row(self, registry, mm, sample_template):
        registry.activate(sample_template)
        rows = mm.query("global", "SELECT * FROM skills WHERE name = ?", ("analyse-logs-nginx",))
        assert len(rows) == 1

    def test_activate_returns_uuid_string(self, registry, sample_template):
        skill_id = registry.activate(sample_template)
        assert isinstance(skill_id, str)
        assert len(skill_id) == 36  # UUID format: 8-4-4-4-12

    def test_activate_stores_tool(self, registry, mm, sample_template):
        registry.activate(sample_template)
        rows = mm.query("global", "SELECT tool FROM skills WHERE name = ?", ("analyse-logs-nginx",))
        assert rows[0]["tool"] == "cli"

    def test_activate_stores_prompt_template(self, registry, mm, sample_template):
        registry.activate(sample_template)
        rows = mm.query("global", "SELECT prompt_template FROM skills WHERE name = ?", ("analyse-logs-nginx",))
        assert "cli" in rows[0]["prompt_template"]


# ---------------------------------------------------------------------------
# TestListActive
# ---------------------------------------------------------------------------


class TestListActive:
    def test_empty_returns_empty_list(self, registry):
        assert registry.list_active() == []

    def test_newly_activated_skill_appears(self, registry, sample_template):
        registry.activate(sample_template)
        skills = registry.list_active()
        assert len(skills) == 1
        assert skills[0]["name"] == "analyse-logs-nginx"

    def test_includes_reuse_score_key(self, registry, sample_template):
        registry.activate(sample_template)
        skills = registry.list_active()
        assert "reuse_score" in skills[0]

    def test_reuse_score_is_zero_for_unused(self, registry, sample_template):
        registry.activate(sample_template)
        skills = registry.list_active()
        assert skills[0]["reuse_score"] == pytest.approx(0.0)

    def test_skill_absent_after_prune_window(self, registry, mm, sample_template):
        """A skill with last_used > PRUNE_DAYS ago must not appear in list_active."""
        skill_id = registry.activate(sample_template)
        # Simulate 31-day-old last_used
        mm.query(
            "global",
            "UPDATE skills SET last_used = datetime('now', ?) WHERE id = ?",
            (f"-{PRUNE_DAYS + 1} days", skill_id),
        )
        skills = registry.list_active()
        assert not any(s["id"] == skill_id for s in skills)


# ---------------------------------------------------------------------------
# TestPrune
# ---------------------------------------------------------------------------


class TestPrune:
    def test_prune_returns_zero_when_nothing_to_prune(self, registry):
        assert registry.prune() == 0

    def test_prune_keeps_fresh_skills(self, registry, mm, sample_template):
        registry.activate(sample_template)
        deleted = registry.prune()
        assert deleted == 0

    def test_prune_deletes_stale_skills(self, registry, mm, sample_template):
        skill_id = registry.activate(sample_template)
        mm.query(
            "global",
            "UPDATE skills SET last_used = datetime('now', ?) WHERE id = ?",
            (f"-{PRUNE_DAYS + 1} days", skill_id),
        )
        deleted = registry.prune()
        assert deleted == 1
        rows = mm.query("global", "SELECT * FROM skills WHERE id = ?", (skill_id,))
        assert len(rows) == 0

    def test_prune_never_deletes_unused_new_skills(self, registry, mm, sample_template):
        """Skills with last_used IS NULL are never pruned."""
        registry.activate(sample_template)
        deleted = registry.prune()
        assert deleted == 0
        assert len(registry.list_active()) == 1


# ---------------------------------------------------------------------------
# TestTouch
# ---------------------------------------------------------------------------


class TestTouch:
    def test_touch_increments_usage_count(self, registry, mm, sample_template):
        skill_id = registry.activate(sample_template)
        registry.touch(skill_id)
        rows = mm.query("global", "SELECT usage_count FROM skills WHERE id = ?", (skill_id,))
        assert rows[0]["usage_count"] == 1

    def test_touch_multiple_increments(self, registry, mm, sample_template):
        skill_id = registry.activate(sample_template)
        for _ in range(3):
            registry.touch(skill_id)
        rows = mm.query("global", "SELECT usage_count FROM skills WHERE id = ?", (skill_id,))
        assert rows[0]["usage_count"] == 3

    def test_touch_sets_last_used(self, registry, mm, sample_template):
        skill_id = registry.activate(sample_template)
        registry.touch(skill_id)
        rows = mm.query("global", "SELECT last_used FROM skills WHERE id = ?", (skill_id,))
        assert rows[0]["last_used"] is not None
