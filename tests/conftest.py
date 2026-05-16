"""conftest.py — shared pytest fixtures and the P2.5 metrics report plugin.

After each full test run, a cost/tokens/latency summary is printed to the
terminal (only when the ``arke.task_graph`` module was used during the run).

The report is appended to the standard pytest summary output via the
``pytest_terminal_summary`` hook so it appears even in CI.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Session-wide metrics collector
# ---------------------------------------------------------------------------


class _MetricsCollector:
    """Accumulates task metrics across the test session."""

    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []
        self._start = time.perf_counter()

    def record(self, task_id: str, tool: str, cost: float, tokens: int, duration_ms: float) -> None:
        self.tasks.append(
            {
                "task_id": task_id,
                "tool": tool,
                "cost_eur": cost,
                "tokens": tokens,
                "duration_ms": duration_ms,
            }
        )

    def elapsed_s(self) -> float:
        return time.perf_counter() - self._start

    def total_cost(self) -> float:
        return sum(t["cost_eur"] for t in self.tasks)

    def total_tokens(self) -> int:
        return sum(t["tokens"] for t in self.tasks)

    def avg_latency_ms(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(t["duration_ms"] for t in self.tasks) / len(self.tasks)


# ---------------------------------------------------------------------------
# Pytest plugin hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config._arke_metrics = _MetricsCollector()  # type: ignore[attr-defined]


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    """Print the Arke cost/tokens/latency report after the test summary."""
    mc: _MetricsCollector = getattr(config, "_arke_metrics", None)
    if mc is None or not mc.tasks:
        return

    terminalreporter.write_sep("=", "Arke Metrics Report (P2.5)")
    terminalreporter.write_line(
        f"  Tasks recorded : {len(mc.tasks)}"
    )
    terminalreporter.write_line(
        f"  Total cost     : {mc.total_cost():.6f} €"
    )
    terminalreporter.write_line(
        f"  Total tokens   : {mc.total_tokens()}"
    )
    terminalreporter.write_line(
        f"  Avg latency    : {mc.avg_latency_ms():.2f} ms / task"
    )
    terminalreporter.write_line(
        f"  Suite elapsed  : {mc.elapsed_s():.2f} s"
    )


# ---------------------------------------------------------------------------
# Shared fixture — exposes the metrics collector to tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def arke_metrics(pytestconfig: pytest.Config) -> _MetricsCollector:
    """Return the session-scoped metrics collector."""
    return pytestconfig._arke_metrics  # type: ignore[attr-defined]
