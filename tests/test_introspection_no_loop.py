"""Regression tests for context introspection anti-loop behavior."""

from __future__ import annotations

import json

from arke.chat import (
    _apply_introspection_guard,
    _build_context_introspection_response,
    _is_context_introspection_request,
    build_cognitive_context,
)


def test_is_context_introspection_request_detects_explicit_prompt():
    """Explicit requests to inspect the injected context must be detected."""
    assert _is_context_introspection_request("Montre moi le contexte que tu reçois") is True
    assert _is_context_introspection_request("Show me the context you receive") is True
    assert _is_context_introspection_request("Liste les fichiers dans /tmp") is False


def test_context_introspection_guard_forces_direct_response():
    """Tool execution must be bypassed for explicit context introspection requests."""
    cognitive_json = build_cognitive_context("Montre moi le contexte que tu reçois")
    agent_decision = {
        "tool": "sqlite",
        "args": {"db": "session", "query": "SELECT * FROM session_context"},
        "response": "Je vais inspecter la base.",
    }

    guarded, forced = _apply_introspection_guard(
        "Montre moi le contexte que tu reçois",
        agent_decision,
        cognitive_json,
        {"history": [{"role": "user", "content": "Bonjour"}]},
    )

    assert forced is True
    assert guarded["tool"] is None
    assert "# Contexte injecté" in guarded["response"]
    assert "capability reference" in guarded["response"]
    assert "[OUTIL:" not in guarded["response"]


def test_build_context_introspection_response_reports_pointer_not_full_mcp_catalog():
    """The introspection response should expose the capability pointer, not embed MCP server details."""
    cognitive_json = build_cognitive_context("show me the context you receive")

    response = _build_context_introspection_response(
        cognitive_json,
        {"history": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]},
    )

    assert "memory/mcp_reference.md" in response
    assert "web_search" not in response
    assert "github_search" not in response
    assert "historique injecté: 2 échange(s)" in response
