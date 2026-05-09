"""Tests for router_rs — Rust/PyO3 extension (P2.1).

Validates:
1. Same API as arke.router (Python fallback) — no regression
2. Panic-safe: empty inputs raise ValueError, not crashes
3. Performance: 1 000 calls < 1 ms average (< 1 s total)
"""

from __future__ import annotations

import time

import pytest

import router_rs


# ---------------------------------------------------------------------------
# API parity with arke.router
# ---------------------------------------------------------------------------


class TestSelectTool:
    def test_cli_echo(self):
        assert router_rs.select_tool("echo hello", {}) == "cli"

    def test_cli_grep(self):
        assert router_rs.select_tool("grep error access.log", {}) == "cli"

    def test_cli_cat(self):
        assert router_rs.select_tool("cat README.md", {}) == "cli"

    def test_fs_read(self):
        assert router_rs.select_tool("read the config file", {}) == "fs"

    def test_fs_list(self):
        assert router_rs.select_tool("list the directory contents", {}) == "fs"

    def test_sqlite_query(self):
        assert router_rs.select_tool("query the database for skills", {}) == "sqlite"

    def test_llm_fallback(self):
        assert router_rs.select_tool("what is the capital of France?", {}) == "llm"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            router_rs.select_tool("", {})

    def test_whitespace_raises(self):
        with pytest.raises(ValueError):
            router_rs.select_tool("   ", {})


class TestPlan:
    def test_plan_echo_single_step(self):
        plan = router_rs.plan("echo hello", {})
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool"] == "cli"
        assert plan["steps"][0]["arguments"]["command"] == "echo hello"

    def test_plan_log_analysis_two_steps(self):
        # Now returns single CLI step (agent handles LLM summarization separately)
        plan = router_rs.plan(
            "analyse les logs nginx et résume les erreurs critiques",
            {"log_file": "tests/fixtures/access.log"},
        )
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool"] == "cli"

    def test_plan_log_analysis_dependencies(self):
        # Single CLI step has no dependencies
        plan = router_rs.plan(
            "analyse les logs nginx et résume les erreurs critiques",
            {"log_file": "access.log"},
        )
        deps = list(plan["steps"][0]["dependencies"])
        assert len(deps) == 0

    def test_plan_log_analysis_correct_log_file(self):
        plan = router_rs.plan(
            "analyse les logs nginx errors",
            {"log_file": "custom.log"},
        )
        assert "custom.log" in plan["steps"][0]["arguments"]["command"]

    def test_plan_has_id(self):
        plan = router_rs.plan("echo hello", {})
        assert "id" in plan
        assert plan["id"].startswith("rs-")

    def test_plan_unique_ids(self):
        p1 = router_rs.plan("echo a", {})
        p2 = router_rs.plan("echo b", {})
        assert p1["id"] != p2["id"]

    def test_plan_description(self):
        plan = router_rs.plan("echo hello world", {})
        assert plan["description"] == "echo hello world"

    def test_plan_empty_raises(self):
        with pytest.raises(ValueError):
            router_rs.plan("", {})


# ---------------------------------------------------------------------------
# Non-regression: Rust vs Python router produce identical decisions
# ---------------------------------------------------------------------------


class TestRustPythonParity:
    """Rust router must produce identical tool selections as the Python router."""

    CASES = [
        ("echo hello", {}),
        ("grep error access.log", {}),
        ("cat README.md", {}),
        ("read the config file", {}),
        ("list the directory contents", {}),
        ("query the database for skills", {}),
        ("what is the capital of France?", {}),
    ]

    def test_select_tool_parity(self):
        from arke.router import select_tool as py_select_tool

        for intention, ctx in self.CASES:
            py_result = py_select_tool(intention, ctx)
            rs_result = router_rs.select_tool(intention, ctx)
            assert rs_result == py_result, (
                f"Mismatch for '{intention}': Python={py_result}, Rust={rs_result}"
            )

    def test_plan_step_count_parity(self):
        from arke.router import plan as py_plan

        log_intention = "analyse les logs nginx et résume les erreurs critiques"
        ctx = {"log_file": "tests/fixtures/access.log"}

        py_task = py_plan(log_intention, ctx)
        rs_plan = router_rs.plan(log_intention, ctx)

        assert len(rs_plan["steps"]) == len(py_task.steps), (
            f"Step count mismatch: Python={len(py_task.steps)}, Rust={len(rs_plan['steps'])}"
        )

    def test_plan_tools_parity(self):
        from arke.router import plan as py_plan

        log_intention = "analyse les logs nginx et résume les erreurs critiques"
        ctx = {"log_file": "tests/fixtures/access.log"}

        py_task = py_plan(log_intention, ctx)
        rs_plan = router_rs.plan(log_intention, ctx)

        py_tools = [s.tool for s in py_task.steps]
        rs_tools = [s["tool"] for s in rs_plan["steps"]]
        assert rs_tools == py_tools


# ---------------------------------------------------------------------------
# Performance: < 1 ms average per call (P2.1 criterion)
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_select_tool_1000_calls_under_1s(self):
        """1 000 calls to select_tool must complete in < 1 second total (avg < 1 ms)."""
        N = 1000
        start = time.perf_counter()
        for _ in range(N):
            router_rs.select_tool("echo hello", {})
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / N) * 1000
        assert elapsed < 1.0, (
            f"1 000 calls took {elapsed:.3f}s — must be < 1s"
        )
        print(f"\n  select_tool: {N} calls in {elapsed*1000:.1f} ms — avg {avg_ms:.4f} ms/call")

    def test_plan_1000_calls_under_1s(self):
        """1 000 calls to plan must complete in < 1 second total."""
        N = 1000
        start = time.perf_counter()
        for _ in range(N):
            router_rs.plan("echo hello", {})
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / N) * 1000
        assert elapsed < 1.0, (
            f"1 000 plan calls took {elapsed:.3f}s — must be < 1s"
        )
        print(f"\n  plan: {N} calls in {elapsed*1000:.1f} ms — avg {avg_ms:.4f} ms/call")
