"""PlanTracker — tracks plan confirmations and manages opt-in auto-execution.

Design invariants (Phase 2, aligned with Arke cognitive contract):
- The system DETECTS repetition (counter increment).
- The system PROPOSES auto-execution after N confirmations.
- The system NEVER sets auto_executable without explicit user consent.
- auto_exec_mode is read from arke.toml [orchestrator].

Flow:
    1. User confirms a plan → record_approval() called.
    2. If count reaches auto_exec_suggest_after and auto_executable is False
       → propose_optin() is called by chat.py (outside this module).
    3. If user says yes → set_auto_executable() called.
    4. On future plans → is_auto_executable() checked before _confirm_plan().
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

_BASE_DIR = Path(__file__).parent.parent
_DEFAULT_SUGGEST_AFTER = 3


def _load_auto_exec_config() -> tuple[str, int]:
    """Return (auto_exec_mode, auto_exec_suggest_after) from arke.toml.

    Returns:
        mode: ``"disabled"`` | ``"after_consent"`` | ``"always"``.
        suggest_after: Number of confirmations before proposing opt-in.
    """
    config_path = _BASE_DIR / "config" / "arke.toml"
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
        orch = data.get("orchestrator", {})
        mode = str(orch.get("auto_exec_mode", "disabled"))
        suggest_after = int(orch.get("auto_exec_suggest_after", _DEFAULT_SUGGEST_AFTER))
        return mode, suggest_after
    except FileNotFoundError:
        return "disabled", _DEFAULT_SUGGEST_AFTER


def plan_hash(plan_text: str) -> str:
    """Return SHA-256 hex digest of the normalised *plan_text*.

    Normalisation: strip, collapse whitespace, lowercase — ensures the same
    plan proposed with minor spacing differences produces the same key.

    Args:
        plan_text: Raw plan text extracted from ``[PLAN:…/PLAN]`` markers.

    Returns:
        64-character hexadecimal string.
    """
    normalised = re.sub(r"\s+", " ", plan_text.strip().lower())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class PlanTracker:
    """Tracks per-plan approval counts and manages opt-in auto-execution.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager` instance.
            A new one is created lazily when *None*.
    """

    def __init__(self, memory: MemoryManager | None = None) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM

            memory = _MM()
        self._mem = memory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_approval(self, phash: str, intention_pattern: str) -> int:
        """Increment approval counter for *phash*; create row if absent.

        Args:
            phash: Plan hash from :func:`plan_hash`.
            intention_pattern: Short description of the intention (for audit).

        Returns:
            New ``plan_approved_count`` after the increment.
        """
        # Upsert: create or update
        rows = self._mem.query(
            "global",
            "SELECT id, plan_approved_count FROM agent_learnings"
            " WHERE plan_hash = ? LIMIT 1",
            (phash,),
        )
        if rows:
            row_id = rows[0]["id"]
            self._mem.query(
                "global",
                "UPDATE agent_learnings"
                " SET plan_approved_count = plan_approved_count + 1"
                " WHERE id = ?",
                (row_id,),
            )
            new_count: int = rows[0]["plan_approved_count"] + 1
        else:
            self._mem.query(
                "global",
                "INSERT INTO agent_learnings"
                " (intention_pattern, tool_sequence, success, plan_hash,"
                "  plan_approved_count, auto_executable, success_rate)"
                " VALUES (?, ?, 1, ?, 1, 0, 1.0)",
                (intention_pattern, "[]", phash),
            )
            new_count = 1
        return new_count

    def get_approved_count(self, phash: str) -> int:
        """Return current ``plan_approved_count`` for *phash* (0 if not found).

        Args:
            phash: Plan hash from :func:`plan_hash`.
        """
        rows = self._mem.query(
            "global",
            "SELECT plan_approved_count FROM agent_learnings"
            " WHERE plan_hash = ? LIMIT 1",
            (phash,),
        )
        return int(rows[0]["plan_approved_count"]) if rows else 0

    def is_auto_executable(self, phash: str) -> bool:
        """Return True only if the user has explicitly opted-in for *phash*.

        Never returns True unless :meth:`set_auto_executable` was called with
        ``True`` after explicit user consent.

        Args:
            phash: Plan hash from :func:`plan_hash`.
        """
        mode, _ = _load_auto_exec_config()
        if mode == "disabled":
            return False  # Always require confirmation when mode=disabled
        rows = self._mem.query(
            "global",
            "SELECT auto_executable FROM agent_learnings"
            " WHERE plan_hash = ? LIMIT 1",
            (phash,),
        )
        if not rows:
            return False
        return bool(rows[0]["auto_executable"])

    def should_propose_optin(self, phash: str) -> bool:
        """Return True if count has reached threshold and opt-in not yet set.

        This is the trigger for chat.py to present the consent prompt.  It
        returns False when ``auto_exec_mode = "disabled"`` so that the feature
        can be completely suppressed without code changes.

        Args:
            phash: Plan hash from :func:`plan_hash`.
        """
        mode, suggest_after = _load_auto_exec_config()
        if mode not in ("after_consent", "always"):
            return False
        rows = self._mem.query(
            "global",
            "SELECT plan_approved_count, auto_executable FROM agent_learnings"
            " WHERE plan_hash = ? LIMIT 1",
            (phash,),
        )
        if not rows:
            return False
        count = int(rows[0]["plan_approved_count"])
        already_set = bool(rows[0]["auto_executable"])
        return count >= suggest_after and not already_set

    def set_auto_executable(self, phash: str, value: bool) -> None:
        """Persist explicit user consent for *phash*.

        Must only be called after the user has explicitly said yes to the
        opt-in prompt.  Setting ``value=False`` resets consent (user said no).

        Args:
            phash: Plan hash from :func:`plan_hash`.
            value: True = user opted in; False = user declined.
        """
        int_val = 1 if value else 0
        self._mem.query(
            "global",
            "UPDATE agent_learnings SET auto_executable = ? WHERE plan_hash = ?",
            (int_val, phash),
        )
        # If user declined, reset count to avoid re-prompting every call
        if not value:
            self._mem.query(
                "global",
                "UPDATE agent_learnings SET plan_approved_count = 0 WHERE plan_hash = ?",
                (phash,),
            )
