"""SkillManager — tracks per-tool usage and exposes routing weights.

Writes to ``global.db`` via MemoryManager.  Routing weights are read
by the router to prefer historically reliable tools.

Behaviour:
    - Each successful step execution → :meth:`record_success`
    - Each failed step execution    → :meth:`record_failure`
    - After ``BOOST_THRESHOLD`` successes, :meth:`get_weight` returns ``2.0``
      (tool becomes preferred fallback in the router).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

#: Number of successes required before a tool's routing weight doubles.
BOOST_THRESHOLD: int = 5


class SkillManager:
    """Records tool usage events and computes routing weights from global.db.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager` instance.
            If *None*, a new instance is created on demand.
    """

    def __init__(self, memory: MemoryManager | None = None) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM  # lazy

            memory = _MM()
        self._mem = memory

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record_success(
        self,
        tool_name: str,
        cost_eur: float = 0.0,
        tokens_used: int = 0,
    ) -> None:
        """Insert a success event for *tool_name* into global.db.

        Args:
            tool_name: Tool identifier (``'cli'``, ``'fs'``, ``'sqlite'``, ``'llm'``).
            cost_eur: LLM cost in euros (``0.0`` for non-LLM tools).
            tokens_used: Tokens consumed (``0`` for non-LLM tools).
        """
        self._mem.query(
            "global",
            "INSERT INTO tool_usage (tool_name, success, cost_eur, tokens_used)"
            " VALUES (?, 1, ?, ?)",
            (tool_name, cost_eur, tokens_used),
        )

    def record_failure(self, tool_name: str) -> None:
        """Insert a failure event for *tool_name* into global.db.

        Args:
            tool_name: Tool identifier.
        """
        self._mem.query(
            "global",
            "INSERT INTO tool_usage (tool_name, success) VALUES (?, 0)",
            (tool_name,),
        )

    # ------------------------------------------------------------------
    # Weight queries
    # ------------------------------------------------------------------

    def get_weight(self, tool_name: str) -> float:
        """Return the routing weight for *tool_name*.

        Returns:
            ``2.0`` if the tool has at least :data:`BOOST_THRESHOLD` successes,
            otherwise ``1.0``.
        """
        rows = self._mem.query(
            "global",
            "SELECT SUM(success) AS successes FROM tool_usage WHERE tool_name = ?",
            (tool_name,),
        )
        count = rows[0]["successes"] if rows and rows[0]["successes"] is not None else 0
        return 2.0 if int(count) >= BOOST_THRESHOLD else 1.0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> list[dict]:
        """Return per-tool usage statistics ordered by success count.

        Returns:
            List of dicts with keys: ``tool_name``, ``total_calls``,
            ``successes``, ``success_rate`` (percentage, 0–100).
        """
        rows = self._mem.query(
            "global",
            """
            SELECT
                tool_name,
                COUNT(*) AS total_calls,
                SUM(success) AS successes,
                ROUND(100.0 * SUM(success) / COUNT(*), 1) AS success_rate
            FROM tool_usage
            GROUP BY tool_name
            ORDER BY successes DESC, tool_name ASC
            """,
            (),
        )
        return [dict(row) for row in rows]
