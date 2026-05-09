"""Tests for P3.1 — SkillDetector: pattern detection and template generation."""

from __future__ import annotations

import pytest

import arke.memory.manager as mem_mod
from arke.memory.manager import MemoryManager
from arke.skill_detector import (
    BUCKET_WORDS,
    PATTERN_THRESHOLD,
    SkillDetector,
    _make_bucket,
    _make_template,
)


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
def detector(mm):
    """SkillDetector using the isolated MemoryManager."""
    return SkillDetector(memory=mm, threshold=PATTERN_THRESHOLD)


@pytest.fixture()
def detector_low(mm):
    """SkillDetector with threshold=2 for easier pattern triggering in tests."""
    return SkillDetector(memory=mm, threshold=2)


# ---------------------------------------------------------------------------
# Bucket normalisation
# ---------------------------------------------------------------------------


class TestBucketNormalisation:
    def test_stop_words_removed(self):
        bucket = _make_bucket("analyse les logs nginx")
        assert "les" not in bucket
        assert "analyse" in bucket
        assert "logs" in bucket

    def test_limits_to_bucket_words(self):
        long_intention = "analyze error logs nginx server apache proxy backend"
        bucket = _make_bucket(long_intention)
        assert len(bucket.split()) <= BUCKET_WORDS

    def test_punctuation_stripped(self):
        bucket = _make_bucket("Analyse, les logs! nginx?")
        assert "," not in bucket
        assert "!" not in bucket

    def test_case_insensitive(self):
        b1 = _make_bucket("Analyse logs Nginx")
        b2 = _make_bucket("analyse logs nginx")
        assert b1 == b2

    def test_equivalent_intentions_same_bucket(self):
        b1 = _make_bucket("Analyse logs nginx")
        b2 = _make_bucket("analyse les logs nginx")
        assert b1 == b2


# ---------------------------------------------------------------------------
# TestRecord
# ---------------------------------------------------------------------------


class TestRecord:
    def test_record_inserts_pattern_log(self, detector, mm):
        detector.record("cli", "analyse les logs nginx")
        rows = mm.query("global", "SELECT * FROM pattern_log", ())
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "cli"

    def test_record_stores_normalised_bucket(self, detector, mm):
        detector.record("fs", "Lire les fichiers config")
        rows = mm.query("global", "SELECT bucket FROM pattern_log", ())
        assert rows[0]["bucket"] == "lire fichiers config"

    def test_multiple_records_accumulate(self, detector, mm):
        for _ in range(3):
            detector.record("cli", "analyse logs nginx")
        rows = mm.query("global", "SELECT * FROM pattern_log", ())
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# TestDetectNew
# ---------------------------------------------------------------------------


class TestDetectNew:
    def test_empty_below_threshold_returns_empty(self, detector):
        for _ in range(PATTERN_THRESHOLD - 1):
            detector.record("cli", "analyse logs nginx")
        assert detector.detect_new() == []

    def test_at_threshold_returns_template(self, detector):
        for _ in range(PATTERN_THRESHOLD):
            detector.record("cli", "analyse logs nginx")
        templates = detector.detect_new()
        assert len(templates) == 1

    def test_template_tool_matches(self, detector):
        for _ in range(PATTERN_THRESHOLD):
            detector.record("fs", "lire fichiers config")
        templates = detector.detect_new()
        assert templates[0].tool == "fs"

    def test_template_name_is_slug(self, detector):
        for _ in range(PATTERN_THRESHOLD):
            detector.record("cli", "analyse logs nginx")
        tmpl = detector.detect_new()[0]
        assert " " not in tmpl.name  # slug: spaces replaced by '-'
        assert "-" in tmpl.name or len(tmpl.name.split()) == 1

    def test_template_has_prompt(self, detector):
        for _ in range(PATTERN_THRESHOLD):
            detector.record("sqlite", "interroger base projets")
        tmpl = detector.detect_new()[0]
        assert len(tmpl.prompt_template) > 10

    def test_template_trigger_count_correct(self, detector):
        for _ in range(PATTERN_THRESHOLD + 2):
            detector.record("llm", "résumer texte rapport")
        tmpl = detector.detect_new()[0]
        assert tmpl.trigger_count == PATTERN_THRESHOLD + 2

    def test_detect_new_skips_existing_skills(self, detector, mm):
        """When a skill with the same name+tool already exists, it must not reappear."""
        for _ in range(PATTERN_THRESHOLD):
            detector.record("cli", "analyse logs nginx")
        # Manually insert a skill with the same name
        slug = "analyse-logs-nginx"
        mm.query(
            "global",
            "INSERT INTO skills (id, name, tool) VALUES ('abc', ?, ?)",
            (slug, "cli"),
        )
        assert detector.detect_new() == []

    def test_custom_threshold_respected(self, mm):
        d = SkillDetector(memory=mm, threshold=3)
        for _ in range(2):
            d.record("cli", "analyse logs nginx")
        assert d.detect_new() == []
        d.record("cli", "analyse logs nginx")
        assert len(d.detect_new()) == 1


# ---------------------------------------------------------------------------
# TestMakeTemplate (unit)
# ---------------------------------------------------------------------------


class TestMakeTemplate:
    def test_name_slugified(self):
        tmpl = _make_template("cli", "analyse logs nginx", 5)
        assert tmpl.name == "analyse-logs-nginx"

    def test_description_contains_tool_and_count(self):
        tmpl = _make_template("fs", "lire fichiers", 7)
        assert "fs" in tmpl.description
        assert "7" in tmpl.description

    def test_bucket_preserved(self):
        tmpl = _make_template("llm", "résumer texte", 5)
        assert tmpl.bucket == "résumer texte"
