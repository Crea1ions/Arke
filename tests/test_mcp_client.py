"""Tests for P2.3 — McpClient: JSON-RPC, routing, fallback graceful."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from arke.interfaces.mcp_client import McpClient, McpUnavailableError


# ---------------------------------------------------------------------------
# Helpers — fake HTTP responses
# ---------------------------------------------------------------------------


def _make_response(body: dict, status: int = 200) -> MagicMock:
    """Build a mock context-manager mimicking urllib.request.urlopen."""
    raw = json.dumps(body).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


_TOOLS_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "github_create_issue",
                "description": "Create a GitHub issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "github_list_issues",
                "description": "List open GitHub issues",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    },
}

_CALL_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [{"type": "text", "text": "Issue #42 created: test"}],
        "isError": False,
    },
}


# ---------------------------------------------------------------------------
# TestListTools
# ---------------------------------------------------------------------------


class TestListTools:
    def test_returns_tool_list(self):
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=_make_response(_TOOLS_RESPONSE)):
            tools = client.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "github_create_issue"

    def test_empty_tools_list(self):
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=_make_response(resp)):
            tools = client.list_tools()
        assert tools == []

    def test_server_unreachable_raises(self):
        import urllib.error

        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with pytest.raises(McpUnavailableError, match="unreachable"):
                client.list_tools()


# ---------------------------------------------------------------------------
# TestCallTool
# ---------------------------------------------------------------------------


class TestCallTool:
    def test_successful_call_returns_text(self):
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=_make_response(_CALL_RESPONSE)):
            result = client.call_tool("github_create_issue", {"title": "test"})
        assert result["isError"] is False
        assert result["content"][0]["text"] == "Issue #42 created: test"

    def test_json_rpc_error_raises_value_error(self):
        err_resp = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32601, "message": "Method not found"},
        }
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=_make_response(err_resp)):
            with pytest.raises(ValueError, match="MCP error"):
                client.call_tool("unknown_tool", {})

    def test_invalid_json_raises_unavailable(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(McpUnavailableError, match="Invalid JSON"):
                client.call_tool("github_create_issue", {})

    def test_tool_error_flag_returned(self):
        err_result = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "Permission denied"}],
                "isError": True,
            },
        }
        client = McpClient(base_url="http://localhost:3000/mcp", timeout=1)
        with patch("urllib.request.urlopen", return_value=_make_response(err_result)):
            result = client.call_tool("github_create_issue", {"title": "x"})
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# TestDisabled
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_disabled_raises_unavailable(self, monkeypatch):
        import arke.interfaces.mcp_client as mod

        monkeypatch.setattr(mod, "_load_mcp_config", lambda: ("http://x", 1, False))
        client = McpClient()
        with pytest.raises(McpUnavailableError, match="disabled"):
            client.list_tools()


# ---------------------------------------------------------------------------
# TestRouterMcp — routing integration
# ---------------------------------------------------------------------------


class TestRouterMcp:
    def test_create_issue_routes_to_mcp(self):
        from arke import router

        assert router.select_tool("crée une issue GitHub test", {}) == "mcp"

    def test_github_keyword_routes_to_mcp(self):
        from arke import router

        assert router.select_tool("github open ticket", {}) == "mcp"

    def test_cli_keyword_not_overridden_by_mcp(self):
        from arke import router

        assert router.select_tool("grep errors access.log", {}) == "cli"

    def test_plan_mcp_intent_creates_mcp_step(self, monkeypatch):
        """plan() produces a single mcp step when routing is mcp."""
        import arke.router as router_mod

        # Disable DB weight lookup for isolation
        monkeypatch.setattr(router_mod, "_load_weights", lambda: {})
        task = router_mod.plan("crée une issue GitHub 'bug #1'", {})
        assert len(task.steps) == 1
        assert task.steps[0].tool == "mcp"


# ---------------------------------------------------------------------------
# TestOrchestratorFallback — graceful fallback when MCP is down
# ---------------------------------------------------------------------------


class TestOrchestratorFallback:
    def test_mcp_unavailable_returns_failed_step(self, monkeypatch):
        """_exec_mcp returns return_code=1 with clear message when unreachable."""
        import urllib.error

        from arke.task_graph import Step

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            from arke.orchestrator import _exec_mcp

            step = Step(
                id="step_1",
                tool="mcp",
                arguments={"tool_name": "github_create_issue", "tool_args": {"title": "x"}},
            )
            result = _exec_mcp(step)

        assert result["return_code"] == 1
        assert "MCP" in result["stderr"]  # error message lang may vary

    def test_mcp_unavailable_message_no_crash(self, monkeypatch):
        """Full orchestrator run gracefully handles MCP unavailability."""
        import urllib.error

        # MCP step has max_retries=2 — urlopen is called 3 times (1 + 2 retries)
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            import arke.router as router_mod

            monkeypatch.setattr(router_mod, "_load_weights", lambda: {})

            from arke import orchestrator
            from arke.task_graph import StepStatus

            task = orchestrator.run("crée une issue GitHub 'test'", {})

        # Step exhausted retries — task FAILED, no Python exception raised
        assert task.status == StepStatus.FAILED
        assert task.steps[0].retry_count > 0
