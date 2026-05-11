"""SkillRegistry — CRUD for activated skills stored in global.db.

Skills are persisted in the ``skills`` table.  A *reusability score*
rewards recently-used skills; :meth:`SkillRegistry.prune` removes skills
that have not been used for :data:`PRUNE_DAYS` days.

Reusability score
-----------------
::

    score = usage_count / max(1, age_in_days)

A skill used 10 times over 2 days scores 5.0; a brand-new unused skill
scores 0.0.  :meth:`list_active` orders results by score descending.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager
    from arke.skill_detector import SkillTemplate

#: Days without any usage before a skill becomes eligible for pruning.
PRUNE_DAYS: int = 30


class SkillRegistry:
    """Manages the lifecycle of activated skills in global.db.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager`.
            Created lazily if *None*.
    """

    def __init__(self, memory: MemoryManager | None = None) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM  # lazy

            memory = _MM()
        self._mem = memory

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, template: SkillTemplate) -> str:
        """Persist a skill derived from a :class:`~arke.skill_detector.SkillTemplate`.

        If a skill with the same name already exists, returns its existing id
        without creating a duplicate.

        Args:
            template: The proposed skill to activate.

        Returns:
            UUID string of the ``skills`` row (new or existing).
        """
        existing = self._mem.query(
            "global",
            "SELECT id FROM skills WHERE name = ? LIMIT 1",
            (template.name,),
        )
        if existing:
            return existing[0]["id"]

        skill_id = str(uuid.uuid4())
        self._mem.query(
            "global",
            """
            INSERT INTO skills (id, name, description, prompt_template, tool)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                skill_id,
                template.name,
                template.description,
                template.prompt_template,
                template.tool,
            ),
        )
        return skill_id

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_active(self) -> list[dict]:
        """Return skills still within the :data:`PRUNE_DAYS` inactivity window.

        Includes brand-new skills (``last_used IS NULL``) which have never
        been invoked yet.  Each dict contains all ``skills`` columns plus
        a computed ``reuse_score`` float.

        Returns:
            List of skill dicts ordered by ``reuse_score DESC``, then name.
        """
        rows = self._mem.query(
            "global",
            """
            SELECT *,
                   ROUND(
                       CAST(usage_count AS REAL) /
                       MAX(1, CAST(
                           JULIANDAY('now') - JULIANDAY(created_at)
                       AS INTEGER)),
                       3
                   ) AS reuse_score
            FROM skills
            WHERE last_used IS NULL
               OR JULIANDAY('now') - JULIANDAY(last_used) <= ?
            ORDER BY reuse_score DESC, name ASC
            """,
            (PRUNE_DAYS,),
        )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(self) -> int:
        """Delete skills unused for more than :data:`PRUNE_DAYS` days.

        Skills that have never been used (``last_used IS NULL``) are
        **not** pruned — they were just created and may still be useful.

        Returns:
            Number of skills deleted.
        """
        rows_before = self._mem.query(
            "global", "SELECT COUNT(*) AS n FROM skills", ()
        )
        self._mem.query(
            "global",
            """
            DELETE FROM skills
            WHERE last_used IS NOT NULL
              AND JULIANDAY('now') - JULIANDAY(last_used) > ?
            """,
            (PRUNE_DAYS,),
        )
        rows_after = self._mem.query(
            "global", "SELECT COUNT(*) AS n FROM skills", ()
        )
        before = rows_before[0]["n"] if rows_before else 0
        after = rows_after[0]["n"] if rows_after else 0
        return before - after

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def touch(self, skill_id: str) -> None:
        """Increment ``usage_count`` and refresh ``last_used`` for *skill_id*.

        Args:
            skill_id: UUID of the skill row to update.
        """
        self._mem.query(
            "global",
            """
            UPDATE skills
               SET usage_count = usage_count + 1,
                   last_used   = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (skill_id,),
        )
