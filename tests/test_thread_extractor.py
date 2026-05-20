"""Tests for arke.thread_extractor — Phase 0B cognitive continuity."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from arke.thread_extractor import (
    EXTRACTION_MIN_CHARS,
    _COGNITIVE_MARKERS,
    _parse_threads,
    should_extract,
)


# ---------------------------------------------------------------------------
# should_extract
# ---------------------------------------------------------------------------


def test_should_extract_below_threshold():
    """Short text (< EXTRACTION_MIN_CHARS) → False."""
    short = "Bonjour."
    assert not should_extract(short, "Réponse courte.")


def test_should_extract_no_markers():
    """Long text without any cognitive marker → False."""
    text = "a " * (EXTRACTION_MIN_CHARS // 2 + 10)
    assert not should_extract(text, text)


def test_should_extract_qualifying():
    """Long text with at least one cognitive marker → True."""
    marker = _COGNITIVE_MARKERS[0]
    long_text = f"Voici une réflexion : {marker} " + ("x " * 100)
    assert should_extract(long_text, long_text)


# ---------------------------------------------------------------------------
# _parse_threads
# ---------------------------------------------------------------------------


def test_parse_threads_valid_json():
    raw = json.dumps([{"content": "Idée A", "importance_score": 0.7, "tags": ["arch"]}])
    result = _parse_threads(raw)
    assert len(result) == 1
    assert result[0]["content"] == "Idée A"
    assert result[0]["importance_score"] == 0.7


def test_parse_threads_empty_array():
    assert _parse_threads("[]") == []


def test_parse_threads_markdown_fenced():
    raw = "```json\n[{\"content\": \"X\", \"importance_score\": 0.5, \"tags\": []}]\n```"
    result = _parse_threads(raw)
    assert len(result) == 1
    assert result[0]["content"] == "X"


def test_parse_threads_invalid_json():
    assert _parse_threads("not-json{{") == []


def test_parse_threads_clamps_score_above():
    raw = json.dumps([{"content": "X", "importance_score": 1.8, "tags": []}])
    result = _parse_threads(raw)
    assert result[0]["importance_score"] == 1.0


def test_parse_threads_clamps_score_below():
    raw = json.dumps([{"content": "X", "importance_score": -0.3, "tags": []}])
    result = _parse_threads(raw)
    assert result[0]["importance_score"] == 0.0


# ---------------------------------------------------------------------------
# extract_async — cancellation before LLM call
# ---------------------------------------------------------------------------


def test_extract_async_cancels_before_llm():
    """Setting cancel_event before grace period elapses → LLM never called."""
    from arke.thread_extractor import extract_async, CANCEL_GRACE_SECONDS

    marker = _COGNITIVE_MARKERS[0]
    long_text = f"{marker} " + ("test " * 100)

    mm = MagicMock()
    cancel_event = threading.Event()

    with patch("arke.llm.litellm_manager.LiteLLMManager") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        mock_llm.complete.return_value = ("[]", 0.0, 0)

        thread = extract_async(mm, "sess-001", long_text, long_text, cancel_event)
        # Cancel immediately — before grace period
        cancel_event.set()
        thread.join(timeout=CANCEL_GRACE_SECONDS + 2)

        mock_llm.complete.assert_not_called()


# ---------------------------------------------------------------------------
# v1.1 Tests: Hierarchy, relations, scores, tags, confidence
# ---------------------------------------------------------------------------


def test_parse_threads_v11_full_fields():
    """Test parsing v1.1 JSON with all new fields."""
    raw = json.dumps(
        [
            {
                "content": "Main idea",
                "importance_score": 0.8,
                "depth_score": 0.7,
                "relevance_score": 0.9,
                "thread_type": "primary",
                "tags": ["philosophie", "question"],
                "related_thread_index": None,
                "relation_type": None,
                "relation_evidence": None,
                "extraction_confidence": 0.85,
            }
        ]
    )
    result = _parse_threads(raw)
    assert len(result) == 1
    t = result[0]
    assert t["content"] == "Main idea"
    assert t["importance_score"] == 0.8
    assert t["depth_score"] == 0.7
    assert t["relevance_score"] == 0.9
    assert t["thread_type"] == "primary"
    assert "philosophie" in t["tags"]
    assert t["extraction_confidence"] == 0.85


def test_parse_threads_v11_invalid_thread_type():
    """Invalid thread_type → defaults to 'primary'."""
    raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "thread_type": "invalid_type",
            }
        ]
    )
    result = _parse_threads(raw)
    assert result[0]["thread_type"] == "primary"


def test_parse_threads_v11_invalid_tags_filtered():
    """Invalid tags not in taxonomy → filtered out."""
    raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "tags": ["philosophie", "invalid_tag", "science"],
            }
        ]
    )
    result = _parse_threads(raw)
    tags = json.loads(result[0]["tags"])
    assert "philosophie" in tags
    assert "science" in tags
    assert "invalid_tag" not in tags


def test_parse_threads_v11_relation_validation():
    """Valid relation_type → accepted; invalid → null."""
    valid_raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "relation_type": "elaboration",
                "related_thread_index": 0,
            }
        ]
    )
    result = _parse_threads(valid_raw)
    assert result[0]["relation_type"] == "elaboration"

    invalid_raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "relation_type": "invalid_relation",
            }
        ]
    )
    result = _parse_threads(invalid_raw)
    assert result[0]["relation_type"] is None


def test_parse_threads_v11_related_index_integer():
    """related_thread_index must be integer or null."""
    raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "related_thread_index": 1,
            }
        ]
    )
    result = _parse_threads(raw)
    assert result[0]["related_thread_index"] == 1

    # Invalid index (string) → null
    invalid_raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "related_thread_index": "not_an_int",
            }
        ]
    )
    result = _parse_threads(invalid_raw)
    assert result[0]["related_thread_index"] is None


def test_parse_threads_v11_scores_clamped():
    """All scores clamped to [0, 1]."""
    raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 1.5,
                "depth_score": -0.2,
                "relevance_score": 2.0,
                "extraction_confidence": -1.0,
            }
        ]
    )
    result = _parse_threads(raw)
    t = result[0]
    assert t["importance_score"] == 1.0
    assert t["depth_score"] == 0.0
    assert t["relevance_score"] == 1.0
    assert t["extraction_confidence"] == 0.0


def test_parse_threads_v11_defaults_when_missing():
    """Missing v1.1 fields → use defaults."""
    raw = json.dumps([{"content": "X", "importance_score": 0.5}])
    result = _parse_threads(raw)
    t = result[0]
    assert t["depth_score"] == 0.5  # default
    assert t["relevance_score"] == 0.5  # default
    assert t["thread_type"] == "primary"  # default
    assert t["extraction_confidence"] == 0.5  # default
    assert t["related_thread_index"] is None  # default


def test_parse_threads_v11_relation_evidence_truncated():
    """relation_evidence truncated to 500 chars."""
    long_evidence = "x" * 1000
    raw = json.dumps(
        [
            {
                "content": "X",
                "importance_score": 0.5,
                "relation_evidence": long_evidence,
            }
        ]
    )
    result = _parse_threads(raw)
    assert len(result[0]["relation_evidence"]) <= 500


def test_parse_threads_v11_backwards_compat():
    """Old v1.0 format still works (all new fields optional)."""
    old_v10_raw = json.dumps(
        [
            {
                "content": "Old idea",
                "importance_score": 0.6,
                "tags": ["histoire"],
            }
        ]
    )
    result = _parse_threads(old_v10_raw)
    assert len(result) == 1
    assert result[0]["content"] == "Old idea"
    assert result[0]["importance_score"] == 0.6


# ---------------------------------------------------------------------------
# S050 — L1: prompt template uses .replace(), not .format()
# ---------------------------------------------------------------------------


def test_extraction_prompt_replace_no_key_error():
    """_EXTRACTION_PROMPT.replace() must not raise KeyError even when the
    prompt contains literal curly braces (JSON examples in the template)."""
    from arke.thread_extractor import _EXTRACTION_PROMPT

    # This would raise KeyError with .format() if the prompt has {json_field}
    prompt = _EXTRACTION_PROMPT.replace("{exchange}", "test user message")
    assert "test user message" in prompt


def test_extraction_worker_no_key_error():
    """_extraction_worker should not swallow a KeyError when building the prompt."""
    from arke.thread_extractor import extract_async, CANCEL_GRACE_SECONDS

    marker = _COGNITIVE_MARKERS[0]
    long_text = f"{marker} " + ("test " * 100)

    mm = MagicMock()
    cancel_event = threading.Event()

    with patch("arke.llm.litellm_manager.LiteLLMManager") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        mock_llm.complete.return_value = ("[]", 0.0, 0)

        thread = extract_async(mm, "sess-s050", long_text, long_text, cancel_event)
        thread.join(timeout=CANCEL_GRACE_SECONDS + 5)

        # LLM must have been called (no early exit from exception)
        mock_llm.complete.assert_called_once()
