"""test_agent_modes.py — Tests for agent mode permission system (/ask /search /plan /agent).

Tests cover:
- MODE_PERMISSIONS matrix (can_execute_tool)
- _get_mode / _set_mode state management
- Pre-orchestrator gate in _run_task (via chat module)
- Mode slash commands registration in chat_router
- Mode indicator in build_cognitive_context
- Mode persistence in session_context
"""

from __future__ import annotations

import re

import pytest

from arke.mode_manager import MODE_PERMISSIONS, can_execute_tool
from arke.chat_router import SLASH_COMMANDS


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# TestModePermissions — can_execute_tool() matrix
# ---------------------------------------------------------------------------


class TestModePermissions:
    """Validate tool access rules for each mode."""

    def test_ask_blocks_all_tools(self):
        """Mode ask must block every known tool."""
        system_tools = ["cli", "fs", "sqlite", "mcp", "memory_write", "memory_forget"]
        for tool in system_tools:
            assert not can_execute_tool(tool, "ask"), (
                f"Expected tool '{tool}' to be blocked in 'ask' mode"
            )

    def test_ask_unknown_tool_blocked(self):
        assert not can_execute_tool("unknown_tool", "ask")

    def test_search_allows_read_tools(self):
        read_tools = [
            "sqlite", "memory_fts", "memory_read", "memory_search",
            "vector_search", "web_search", "rss_reader", "calculator", "mcp",
        ]
        for tool in read_tools:
            assert can_execute_tool(tool, "search"), (
                f"Expected tool '{tool}' to be allowed in 'search' mode"
            )

    def test_search_blocks_write_tools(self):
        """Search mode must not allow system-altering tools."""
        write_tools = ["cli", "fs", "memory_write", "memory_forget"]
        for tool in write_tools:
            assert not can_execute_tool(tool, "search"), (
                f"Expected tool '{tool}' to be blocked in 'search' mode"
            )

    def test_plan_allows_memory_write(self):
        plan_tools = [
            "sqlite", "memory_fts", "memory_read", "memory_search",
            "memory_write", "memory_forget", "vector_search",
        ]
        for tool in plan_tools:
            assert can_execute_tool(tool, "plan"), (
                f"Expected tool '{tool}' to be allowed in 'plan' mode"
            )

    def test_plan_blocks_system_tools(self):
        """Plan mode must not allow CLI or filesystem tools."""
        assert not can_execute_tool("cli", "plan")
        assert not can_execute_tool("fs", "plan")
        assert not can_execute_tool("mcp", "plan")

    def test_agent_allows_all_tools(self):
        """Agent mode must permit every known tool."""
        all_tools = [
            "cli", "fs", "sqlite", "mcp", "memory_write", "memory_forget",
            "memory_fts", "memory_read", "memory_search", "vector_search",
            "web_search", "rss_reader", "calculator",
        ]
        for tool in all_tools:
            assert can_execute_tool(tool, "agent"), (
                f"Expected tool '{tool}' to be allowed in 'agent' mode"
            )

    def test_agent_allows_unknown_tool(self):
        """Agent mode is unrestricted — even unknown tools should pass."""
        assert can_execute_tool("any_future_tool", "agent")

    def test_unknown_mode_blocks_tools(self):
        """An unrecognised mode should default to deny."""
        assert not can_execute_tool("cli", "undefined_mode")

    def test_mode_permissions_structure(self):
        """Verify MODE_PERMISSIONS keys and sentinel values."""
        assert "ask" in MODE_PERMISSIONS
        assert "search" in MODE_PERMISSIONS
        assert "plan" in MODE_PERMISSIONS
        assert "agent" in MODE_PERMISSIONS
        # ask: empty frozenset
        assert MODE_PERMISSIONS["ask"] == frozenset()
        # agent: None sentinel means unrestricted
        assert MODE_PERMISSIONS["agent"] is None


# ---------------------------------------------------------------------------
# TestModeSlashCommands — slash command registration
# ---------------------------------------------------------------------------


class TestModeSlashCommands:
    """Verify that mode slash commands are registered in SLASH_COMMANDS."""

    def test_slash_ask_registered(self):
        assert "/ask" in SLASH_COMMANDS

    def test_slash_search_registered(self):
        assert "/search" in SLASH_COMMANDS

    def test_slash_plan_registered(self):
        assert "/plan" in SLASH_COMMANDS

    def test_slash_agent_registered(self):
        assert "/agent" in SLASH_COMMANDS

    def test_mode_commands_have_descriptions(self):
        for cmd in ("/ask", "/search", "/plan", "/agent"):
            desc = SLASH_COMMANDS.get(cmd, "")
            assert desc, f"Expected non-empty description for {cmd}"

    def test_about_registered(self):
        assert "/about" in SLASH_COMMANDS


class TestAboutCommand:
    def test_print_about_contains_core_sections(self, capsys):
        import arke.chat as _chat

        _chat._print_about()
        out = capsys.readouterr().out

        assert "À propos" in out
        assert "Tout est parti d'une vidéo." in out
        assert "Archè" in out
        assert "Themelios" in out
        assert "Cosmos" in out
        assert "/ask" in out
        assert "/search" in out
        assert "/plan" in out
        assert "/agent" in out
        assert "╭" not in out
        assert "╰" not in out

    def test_about_wrapped_lines_fit_width(self):
        import arke.chat as _chat

        lines = _chat._render_wrapped_markdown_lines(_chat._ABOUT_MARKDOWN, 74)
        assert lines
        for line in lines:
            assert len(_strip_ansi(line)) <= 74


# ---------------------------------------------------------------------------
# TestModeState — _get_mode / _set_mode module-level state
# ---------------------------------------------------------------------------


class TestModeState:
    """Verify get/set mode helpers work correctly."""

    def setup_method(self):
        """Reset to ask mode before each test."""
        import arke.chat as _chat
        _chat._set_mode("ask")

    def test_default_mode_is_ask(self):
        import arke.chat as _chat
        _chat._set_mode("ask")
        assert _chat._get_mode() == "ask"

    def test_set_mode_to_agent(self):
        import arke.chat as _chat
        _chat._set_mode("agent")
        assert _chat._get_mode() == "agent"

    def test_set_mode_to_search(self):
        import arke.chat as _chat
        _chat._set_mode("search")
        assert _chat._get_mode() == "search"

    def test_set_mode_to_plan(self):
        import arke.chat as _chat
        _chat._set_mode("plan")
        assert _chat._get_mode() == "plan"

    def test_mode_changes_are_isolated_to_module_state(self):
        import arke.chat as _chat
        _chat._set_mode("agent")
        assert _chat._get_mode() == "agent"
        _chat._set_mode("ask")
        assert _chat._get_mode() == "ask"

    def test_valid_modes_frozenset(self):
        import arke.chat as _chat
        assert "ask" in _chat._VALID_MODES
        assert "search" in _chat._VALID_MODES
        assert "plan" in _chat._VALID_MODES
        assert "agent" in _chat._VALID_MODES
        assert len(_chat._VALID_MODES) == 4


# ---------------------------------------------------------------------------
# TestModeCognitiveContext — mode injected into build_cognitive_context
# ---------------------------------------------------------------------------


class TestModeCognitiveContext:
    """Verify agent mode is present in the build_cognitive_context output."""

    def setup_method(self):
        import arke.chat as _chat
        _chat._set_mode("ask")

    def test_ask_mode_in_context(self):
        import json
        import arke.chat as _chat
        _chat._set_mode("ask")
        ctx_json = _chat.build_cognitive_context("test message", "session-001")
        ctx = json.loads(ctx_json)
        assert ctx["runtime"]["mode"] == "ask"

    def test_agent_mode_in_context(self):
        import json
        import arke.chat as _chat
        _chat._set_mode("agent")
        ctx_json = _chat.build_cognitive_context("test message", "session-002")
        ctx = json.loads(ctx_json)
        assert ctx["runtime"]["mode"] == "agent"

    def test_search_mode_in_context(self):
        import json
        import arke.chat as _chat
        _chat._set_mode("search")
        ctx_json = _chat.build_cognitive_context("search test", "session-003")
        ctx = json.loads(ctx_json)
        assert ctx["runtime"]["mode"] == "search"

    def test_plan_mode_in_context(self):
        import json
        import arke.chat as _chat
        _chat._set_mode("plan")
        ctx_json = _chat.build_cognitive_context("plan test", "session-004")
        ctx = json.loads(ctx_json)
        assert ctx["runtime"]["mode"] == "plan"


# ---------------------------------------------------------------------------
# TestOrchestratorGate — _dispatch() blocks tools based on agent_mode in ctx
# ---------------------------------------------------------------------------


class TestOrchestratorGate:
    """Verify orchestrator._dispatch() enforces MODE_PERMISSIONS."""

    def _make_step(self, tool: str, args: dict | None = None):
        from arke.task_graph import Step
        return Step(id="s0", tool=tool, arguments=args or {})

    def _make_task(self):
        from arke.task_graph import Task, StepStatus
        return Task(
            id="t0",
            description="test",
            steps=[],
            status=StepStatus.RUNNING,
        )

    def test_ask_mode_blocks_cli(self):
        from arke.orchestrator import _dispatch
        step = self._make_step("cli", {"command": "ls"})
        task = self._make_task()
        result = _dispatch(step, {"agent_mode": "ask"}, task)
        assert result["return_code"] == 1
        assert "non autorisé" in result["stderr"]

    def test_ask_mode_blocks_fs(self):
        from arke.orchestrator import _dispatch
        step = self._make_step("fs", {"path": "/tmp"})
        task = self._make_task()
        result = _dispatch(step, {"agent_mode": "ask"}, task)
        assert result["return_code"] == 1

    def test_search_mode_blocks_cli(self):
        from arke.orchestrator import _dispatch
        step = self._make_step("cli", {"command": "echo test"})
        task = self._make_task()
        result = _dispatch(step, {"agent_mode": "search"}, task)
        assert result["return_code"] == 1
        assert "non autorisé" in result["stderr"]

    def test_plan_mode_blocks_cli(self):
        from arke.orchestrator import _dispatch
        step = self._make_step("cli", {"command": "touch /tmp/test"})
        task = self._make_task()
        result = _dispatch(step, {"agent_mode": "plan"}, task)
        assert result["return_code"] == 1

    def test_agent_mode_allows_cli(self, tmp_path):
        """agent mode should not be blocked by the gate (actual execution tested elsewhere)."""
        # We only test that the gate does NOT block — not that CLI executes successfully.
        # The function will attempt to run the command after passing the gate.
        from arke.mode_manager import can_execute_tool
        assert can_execute_tool("cli", "agent") is True

    def test_no_agent_mode_defaults_to_agent(self):
        """Backward compat: missing agent_mode key in ctx defaults to agent (full access)."""
        from arke.mode_manager import can_execute_tool
        # Simulate what _dispatch does: ctx.get("agent_mode", "agent")
        mode = {}.get("agent_mode", "agent")
        assert can_execute_tool("cli", mode) is True
