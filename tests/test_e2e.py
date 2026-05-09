"""End-to-end test — test_nginx_log_analysis (Phase 1 truth stone).

This test validates the complete kernel pipeline without mocking LLM calls.
It uses a mock LLM to remain deterministic, cost-free, and fast.

For a real LLM run (manual validation only):
    ARKE_E2E_REAL_LLM=1 pytest tests/test_e2e.py -v
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from arke import orchestrator
from arke.task_graph import StepStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_LOG = "tests/fixtures/access.log"

# Simulated LLM response that references HTTP 500
_MOCK_LLM_RESPONSE = (
    "3 erreurs HTTP 500 ont été détectées dans les logs nginx. "
    "Ces erreurs indiquent des pannes serveur internes. "
    "Recommandation : vérifier les logs applicatifs associés."
)


def _mock_llm_complete(prompt: str, task_type: str = "reasoning", max_tokens: int = 500):
    """Deterministic LLM stub — checks that grep output is in the prompt."""
    assert "500" in prompt, "LLM prompt must contain grep output with 500 errors"
    return _MOCK_LLM_RESPONSE, 0.0, 42  # response, cost_eur, tokens_used


# ---------------------------------------------------------------------------
# The truth-stone test
# ---------------------------------------------------------------------------


def test_nginx_log_analysis():
    """
    Test de vérité Phase 1 — Pierre de touche du noyau Arke.

    Scénario : un fichier access.log contient 1 000 lignes
    dont 3 erreurs HTTP 500.

    Commande : arke run "analyse les logs nginx et résume les erreurs critiques"

    NEW ARCHITECTURE: Router now returns only CLI (grep) step.
    LLM summarization is handled by agent via _ask_agent() in chat.py.
    This test validates that the CLI grep step works correctly.
    """
    result = orchestrator.run(
        "analyse les logs nginx et résume les erreurs critiques",
        context={"log_file": FIXTURE_LOG},
    )

    # The router chose grep only (CLI) - no LLM step from router
    assert len(result.steps) == 1, (
        f"Should have 1 CLI step, got {len(result.steps)} steps"
    )
    assert result.steps[0].tool == "cli", (
        f"Step 1 must be CLI (grep), got: {result.steps[0].tool}"
    )

    # The deterministic gate validated the CLI step
    assert result.steps[0].validation is not None
    assert result.steps[0].validation.type == "return_code"
    assert result.steps[0].status == StepStatus.SUCCESS

    # Overall task succeeded
    assert result.status == StepStatus.SUCCESS

    # No hallucination on deterministic steps — grep must find the 3 errors
    grep_output: str = result.steps[0].output.get("stdout", "")
    assert grep_output.count(" 500 ") == 3, (
        f"grep must find exactly 3 HTTP 500 errors, found: {grep_output.count(' 500 ')}"
    )


# ---------------------------------------------------------------------------
# Additional integration smoke-tests
# ---------------------------------------------------------------------------


def test_arke_run_echo():
    """arke run 'echo hello' → output is 'hello'."""
    result = orchestrator.run("echo hello", {})
    assert result.status == StepStatus.SUCCESS
    assert result.steps[0].tool == "cli"
    stdout = result.steps[0].output.get("stdout", "").strip()
    assert stdout == "hello"


def test_arke_run_blocked_command():
    """Commands outside the whitelist must be rejected."""
    result = orchestrator.run("reboot", {})
    assert result.status == StepStatus.FAILED


def test_arke_run_task_has_unique_ids():
    """Each run produces a unique task ID."""
    r1 = orchestrator.run("echo a", {})
    r2 = orchestrator.run("echo b", {})
    assert r1.id != r2.id
