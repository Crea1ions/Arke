"""test_mode_manager.py — Tests for arke.mode_manager (Session 032).

Tests cover:
- get_mode / set_mode state management
- is_valid_mode validation
- MODE_PERMISSIONS matrix
- can_execute_tool per mode
- load_mode_schema per mode
- build_input_context structure and mode injection
"""

from __future__ import annotations

import json

import pytest

import arke.mode_manager as mm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_mode():
    """Reset mode to 'ask' before every test."""
    mm.set_mode("ask")
    yield
    mm.set_mode("ask")


# ---------------------------------------------------------------------------
# TestGetSetMode
# ---------------------------------------------------------------------------


class TestGetSetMode:
    def test_default_mode_is_ask(self):
        assert mm.get_mode() == "ask"

    def test_set_mode_dev(self):
        mm.set_mode("dev")
        assert mm.get_mode() == "dev"

    def test_set_mode_search(self):
        mm.set_mode("search")
        assert mm.get_mode() == "search"

    def test_set_mode_plan(self):
        mm.set_mode("plan")
        assert mm.get_mode() == "plan"

    def test_set_mode_invalid_raises(self):
        with pytest.raises(ValueError, match="Mode invalide"):
            mm.set_mode("undefined_mode")

    def test_set_mode_empty_raises(self):
        with pytest.raises(ValueError):
            mm.set_mode("")

    def test_mode_change_is_persistent(self):
        mm.set_mode("dev")
        assert mm.get_mode() == "dev"
        mm.set_mode("plan")
        assert mm.get_mode() == "plan"


# ---------------------------------------------------------------------------
# TestIsValidMode
# ---------------------------------------------------------------------------


class TestIsValidMode:
    def test_valid_modes(self):
        for mode in ("ask", "search", "plan", "dev"):
            assert mm.is_valid_mode(mode)

    def test_invalid_mode(self):
        assert not mm.is_valid_mode("undefined")
        assert not mm.is_valid_mode("")
        assert not mm.is_valid_mode("DEV")  # case-sensitive


# ---------------------------------------------------------------------------
# TestModePermissionsMatrix
# ---------------------------------------------------------------------------


class TestModePermissionsMatrix:
    def test_ask_has_empty_frozenset(self):
        assert mm.MODE_PERMISSIONS["ask"] == frozenset()

    def test_dev_is_none_unrestricted(self):
        assert mm.MODE_PERMISSIONS["dev"] is None

    def test_search_contains_read_tools(self):
        expected = {"sqlite", "memory_fts", "memory_read", "vector_search", "web_search"}
        assert expected.issubset(mm.MODE_PERMISSIONS["search"])

    def test_plan_contains_memory_write(self):
        assert "memory_write" in mm.MODE_PERMISSIONS["plan"]
        assert "memory_forget" in mm.MODE_PERMISSIONS["plan"]

    def test_plan_excludes_cli(self):
        assert "cli" not in mm.MODE_PERMISSIONS["plan"]
        assert "fs" not in mm.MODE_PERMISSIONS["plan"]

    def test_all_four_modes_present(self):
        for mode in ("ask", "search", "plan", "dev"):
            assert mode in mm.MODE_PERMISSIONS


# ---------------------------------------------------------------------------
# TestCanExecuteTool
# ---------------------------------------------------------------------------


class TestCanExecuteTool:
    def test_ask_blocks_cli(self):
        assert not mm.can_execute_tool("cli", "ask")

    def test_ask_blocks_all_system_tools(self):
        for tool in ("cli", "fs", "sqlite", "mcp", "memory_write"):
            assert not mm.can_execute_tool(tool, "ask")

    def test_search_allows_sqlite(self):
        assert mm.can_execute_tool("sqlite", "search")

    def test_search_blocks_cli(self):
        assert not mm.can_execute_tool("cli", "search")

    def test_search_blocks_fs(self):
        assert not mm.can_execute_tool("fs", "search")

    def test_plan_allows_memory_write(self):
        assert mm.can_execute_tool("memory_write", "plan")

    def test_plan_blocks_cli(self):
        assert not mm.can_execute_tool("cli", "plan")

    def test_dev_allows_cli(self):
        assert mm.can_execute_tool("cli", "dev")

    def test_dev_allows_everything(self):
        for tool in ("cli", "fs", "sqlite", "mcp", "memory_write", "any_future_tool"):
            assert mm.can_execute_tool(tool, "dev")

    def test_unknown_mode_blocks_all(self):
        assert not mm.can_execute_tool("cli", "unknown_mode")


# ---------------------------------------------------------------------------
# TestLoadModeSchema
# ---------------------------------------------------------------------------


class TestLoadModeSchema:
    def test_ask_schema_loads(self):
        schema = mm.load_mode_schema("ask")
        assert isinstance(schema, dict)
        assert schema.get("mode") == "ask"

    def test_search_schema_loads(self):
        schema = mm.load_mode_schema("search")
        assert isinstance(schema, dict)
        assert schema.get("mode") == "search"

    def test_plan_schema_loads(self):
        schema = mm.load_mode_schema("plan")
        assert isinstance(schema, dict)
        assert schema.get("mode") == "plan"

    def test_dev_schema_loads(self):
        schema = mm.load_mode_schema("dev")
        assert isinstance(schema, dict)
        assert schema.get("mode") == "dev"

    def test_ask_schema_has_no_tools(self):
        schema = mm.load_mode_schema("ask")
        assert schema.get("contract", {}).get("rules", {}).get("no_tools") is True

    def test_search_schema_has_allowed_tools(self):
        schema = mm.load_mode_schema("search")
        assert "allowed_tools" in schema
        assert "sqlite" in schema["allowed_tools"]

    def test_plan_schema_has_memory_write(self):
        schema = mm.load_mode_schema("plan")
        assert "memory_write" in schema.get("allowed_tools", [])

    def test_dev_schema_unrestricted(self):
        schema = mm.load_mode_schema("dev")
        assert schema.get("allowed_tools") == "unrestricted"

    def test_unknown_mode_returns_empty_dict(self):
        schema = mm.load_mode_schema("nonexistent_mode")
        assert schema == {}


# ---------------------------------------------------------------------------
# TestBuildInputContext
# ---------------------------------------------------------------------------


class TestBuildInputContext:
    def test_returns_valid_json(self):
        result = mm.build_input_context("ask", "hello world")
        ctx = json.loads(result)
        assert isinstance(ctx, dict)

    def test_runtime_mode_field(self):
        for mode in ("ask", "search", "plan", "dev"):
            result = mm.build_input_context(mode, "test")
            ctx = json.loads(result)
            assert ctx["runtime"]["mode"] == mode

    def test_input_user_message(self):
        result = mm.build_input_context("ask", "my question")
        ctx = json.loads(result)
        assert ctx["input"]["user_message"] == "my question"

    def test_session_id_generated_if_absent(self):
        result = mm.build_input_context("ask", "test")
        ctx = json.loads(result)
        assert ctx["runtime"]["session_id"]

    def test_session_id_preserved_if_provided(self):
        result = mm.build_input_context("ask", "test", session_id="fixed-id")
        ctx = json.loads(result)
        assert ctx["runtime"]["session_id"] == "fixed-id"

    def test_schema_merged_into_context(self):
        """Schema fields (mode, contract, scope) must appear in the output."""
        result = mm.build_input_context("ask", "test")
        ctx = json.loads(result)
        # Schema for 'ask' includes 'contract' key
        assert "contract" in ctx

    def test_history_length_zero_when_empty(self):
        result = mm.build_input_context("dev", "test", history=None)
        ctx = json.loads(result)
        assert ctx["input"]["history_length"] == 0

    def test_history_length_reflects_history(self):
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = mm.build_input_context("dev", "test", history=history)
        ctx = json.loads(result)
        assert ctx["input"]["history_length"] == 2

    def test_turn_id_is_unique_per_call(self):
        r1 = json.loads(mm.build_input_context("ask", "test"))
        r2 = json.loads(mm.build_input_context("ask", "test"))
        assert r1["runtime"]["turn_id"] != r2["runtime"]["turn_id"]
