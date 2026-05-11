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
