"""SocialOrchestrator -- manages cognitive initiative timing (Phase 1: active delivery).

Responsibilities (purely deterministic):
- Track user activity via ``record_input()`` / ``is_user_idle()``
- Schedule candidate initiative moments using probabilistic timing
- Compute allowed patterns based on interaction_density
- In Phase 0: log what WOULD have been sent to ``initiative_simulation_log``
  without generating or delivering anything to the user
- Maintain a pending initiative queue (used by chat.py pull in Phase 1)

The orchestrator never reads message content, never calls LLM, and never
selects what to say. It only works with:
  - scores (REAL)
  - timestamps (TEXT)
  - density counts (INTEGER)
  - cooldowns and probabilities

This is the key invariant: Social Orchestrator is non-semantic.

Thread safety: all reads/writes to ``cognitive_threads`` go through
``threads_lock`` imported from ``thread_extractor``.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Config defaults (overridden by arke.toml [social_orchestrator])
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "enabled": True,
    "observation_mode": True,          # Phase 0: log only, no delivery
    "min_silence_minutes": 30,
    "active_hours_start": 8,
    "active_hours_end": 23,
    "density_base_minutes": 120,       # base delay at average usage
    "extraction_min_chars": 200,
    "first_initiative_min_score": 0.6, # higher threshold for first ever initiative
    "normal_initiative_min_score": 0.4,
    "max_ignored_before_dormant": 3,
}

# Pattern unlocked at each density tier (avg exchanges/day over 7 days)
_PATTERN_BY_DENSITY: list[tuple[float, list[str]]] = [
    (0.0, ["REPRISE"]),
    (3.0, ["QUESTION", "OBSERVATION", "REPRISE"]),
    (8.0, ["QUESTION", "OBSERVATION", "BIFURCATION", "REPRISE"]),
]


def _load_config() -> dict:
    from pathlib import Path
    import tomllib

    cfg_path = Path(__file__).parent.parent / "config" / "arke.toml"
    try:
        with open(cfg_path, "rb") as fh:
            data = tomllib.load(fh)
        return {**_DEFAULTS, **data.get("social_orchestrator", {})}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULTS)


# ---------------------------------------------------------------------------
# SocialOrchestrator
# ---------------------------------------------------------------------------


class SocialOrchestrator:
    """Deterministic timing layer for cognitive initiative delivery.

    Usage::

        so = SocialOrchestrator(mm, session_id)
        so.start()                       # begins the scheduling loop
        so.record_input()                # call before every _read_paste_buffered()
        if so.has_pending_initiative():  # check in REPL loop head
            if so.is_user_idle():
                initiative = so.pop_initiative()  # None in Phase 0
        so.stop()
    """

    def __init__(self, mm: object, session_id: str) -> None:
        self._mm = mm
        self._session_id = session_id
        self._cfg = _load_config()
        self._enabled: bool = self._cfg["enabled"]
        self._observation_mode: bool = self._cfg["observation_mode"]

        self._pending_initiative: Optional[str] = None
        self._pending_thread_id: Optional[int] = None
        self._last_input_at: float = time.time()
        self._timer: Optional[threading.Timer] = None
        self._stopped = threading.Event()

        # Import lock from thread_extractor (shared)
        from arke.thread_extractor import threads_lock
        self._lock = threads_lock

    # ------------------------------------------------------------------
    # Public API (called from chat.py REPL loop)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduling loop."""
        if not self._enabled:
            return
        self._schedule_next()
        mode = "OBSERVATION" if self._observation_mode else "ACTIVE"
        log.info("social_orchestrator.start", mode=mode, session=self._session_id)

    def stop(self) -> None:
        """Cancel any pending timer and shut down."""
        self._stopped.set()
        if self._timer is not None:
            self._timer.cancel()
        log.info("social_orchestrator.stop", session=self._session_id)

    def record_input(self) -> None:
        """Call before every _read_paste_buffered() to track user activity."""
        self._last_input_at = time.time()
        # Persist to session_context so other processes can read it
        try:
            self._mm.query(
                "session",
                "INSERT OR REPLACE INTO session_context (key, value) "
                "VALUES ('so_last_input_at', ?)",
                (str(self._last_input_at),),
            )
        except Exception:  # noqa: BLE001
            pass

    def is_user_idle(self) -> bool:
        """Return True if the user has been silent for min_silence_minutes."""
        min_secs = self._cfg["min_silence_minutes"] * 60
        return (time.time() - self._last_input_at) >= min_secs

    def has_pending_initiative(self) -> bool:
        """Return True if an initiative is queued (always False in Phase 0)."""
        if self._observation_mode:
            return False
        if not self._enabled:
            return False
        return self._pending_initiative is not None

    def pop_initiative(self) -> Optional[str]:
        """Consume and return the queued initiative text (None in Phase 0)."""
        if not self._enabled:
            return None
        text = self._pending_initiative
        thread_id = self._pending_thread_id
        self._pending_initiative = None
        self._pending_thread_id = None
        if thread_id is not None:
            self._mark_initiative_sent(thread_id)
        return text

    def record_response(self, user_reply: str) -> None:
        """Call after the user replies to an initiative to reset ignored_count.

        In Phase 1 only. Allows threads to survive multiple rounds.
        """
        # If there was a recently sent initiative, this counts as a response
        pass  # Phase 1 feature — wire up properly then

    # ------------------------------------------------------------------
    # Scheduling (internal)
    # ------------------------------------------------------------------

    def _schedule_next(self) -> None:
        if self._stopped.is_set():
            return
        delay = self._compute_next_delay()
        self._timer = threading.Timer(delay, self._on_timer_fire)
        self._timer.daemon = True
        self._timer.start()

    def _compute_next_delay(self) -> float:
        """Probabilistic organic timing: base ± 40% jitter, scaled by density."""
        density = self._get_density_score()
        base_secs = self._cfg["density_base_minutes"] * 60
        # Denser usage → shorter base delay (min 15 min)
        scaled = base_secs * max(0.25, 1.0 - (density / 20.0))
        jitter = scaled * random.uniform(-0.4, 0.4)
        return max(15 * 60, scaled + jitter)  # floor: 15 minutes

    def _on_timer_fire(self) -> None:
        """Called by the timer thread when a scheduling opportunity arrives."""
        if self._stopped.is_set():
            return
        try:
            self._evaluate_initiative_opportunity()
        except Exception as exc:  # noqa: BLE001
            log.debug("social_orchestrator.timer_error", error=str(exc))
        finally:
            self._schedule_next()  # always reschedule

    def _evaluate_initiative_opportunity(self) -> None:
        """Core evaluation: select thread, check conditions, log or queue."""
        if not self._is_active_hour():
            return

        thread = self._select_best_thread()
        if thread is None:
            return

        allowed = self._select_allowed_patterns()
        reason = self._suppression_reason()

        if self._observation_mode:
            # Phase 0: log the simulation only
            try:
                self._mm.query(
                    "global",
                    "INSERT INTO initiative_simulation_log "
                    "(thread_id, would_have_sent_at, thread_summary, "
                    "allowed_patterns, suppressed_reason) "
                    "VALUES (?, datetime('now'), ?, ?, ?)",
                    (
                        thread["id"],
                        thread["content"][:200],
                        json.dumps(allowed),
                        reason,
                    ),
                )
                log.info(
                    "social_orchestrator.simulation",
                    thread_id=thread["id"],
                    score=thread["importance_score"],
                    patterns=allowed,
                    suppressed=reason,
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("social_orchestrator.sim_log_error", error=str(exc))
        else:
            # Phase 1: generate and queue (not yet wired)
            if reason is None:
                self._generate_and_queue(thread, allowed)

    def _suppression_reason(self) -> Optional[str]:
        """Return why an initiative would be suppressed, or None if it would go through."""
        if not self.is_user_idle():
            return "user_active"
        if self._pending_initiative is not None:
            return "already_queued"
        return None

    def _select_best_thread(self) -> Optional[dict]:
        """Select the highest-scoring eligible thread (deterministic, no LLM)."""
        min_score = (
            self._cfg["first_initiative_min_score"]
            if not self._any_initiative_sent()
            else self._cfg["normal_initiative_min_score"]
        )
        with self._lock:
            try:
                rows = self._mm.query(
                    "global",
                    "SELECT id, content, importance_score, activation_count, tags "
                    "FROM cognitive_threads "
                    "WHERE status IN ('open', 'resurfaced') "
                    "AND importance_score >= ? "
                    "ORDER BY importance_score DESC, created_at ASC "
                    "LIMIT 1",
                    (min_score,),
                )
                if rows:
                    r = rows[0]
                    return {
                        "id": r["id"],
                        "content": r["content"],
                        "importance_score": r["importance_score"],
                        "activation_count": r["activation_count"],
                        "tags": r["tags"],
                    }
            except Exception as exc:  # noqa: BLE001
                log.debug("social_orchestrator.select_error", error=str(exc))
        return None

    def _select_allowed_patterns(self) -> list[str]:
        """Return patterns allowed given current interaction density."""
        density = self._get_density_score()
        allowed = ["REPRISE"]  # always available
        for threshold, patterns in _PATTERN_BY_DENSITY:
            if density >= threshold:
                allowed = patterns
        return allowed

    def _get_density_score(self) -> float:
        """Average daily exchange count over the past 7 days."""
        try:
            rows = self._mm.query(
                "global",
                "SELECT AVG(exchange_count) AS avg FROM interaction_density "
                "WHERE day >= date('now', '-7 days')",
                (),
            )
            if rows and rows[0]["avg"] is not None:
                return float(rows[0]["avg"])
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def _is_active_hour(self) -> bool:
        """Return True if current local time is within the active window."""
        now = datetime.now()
        h = now.hour
        return self._cfg["active_hours_start"] <= h < self._cfg["active_hours_end"]

    def _any_initiative_sent(self) -> bool:
        """Return True if at least one initiative has been activated (ever)."""
        try:
            rows = self._mm.query(
                "global",
                "SELECT COUNT(*) AS n FROM cognitive_threads "
                "WHERE activation_count > 0",
                (),
            )
            return bool(rows and rows[0]["n"] > 0)
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # Thread lifecycle mutations
    # ------------------------------------------------------------------

    def _mark_initiative_sent(self, thread_id: int) -> None:
        """Transition thread state after sending an initiative."""
        with self._lock:
            try:
                self._mm.query(
                    "global",
                    "UPDATE cognitive_threads SET "
                    "activation_count = activation_count + 1, "
                    "last_activated_at = datetime('now'), "
                    "status = CASE "
                    "  WHEN activation_count >= 1 THEN 'resurfaced' "
                    "  ELSE status END "
                    "WHERE id = ?",
                    (thread_id,),
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("social_orchestrator.mark_sent_error", error=str(exc))

    def mark_initiative_ignored(self, thread_id: int) -> None:
        """Call when user does not reply to an initiative within the timeout."""
        with self._lock:
            try:
                self._mm.query(
                    "global",
                    "UPDATE cognitive_threads SET "
                    "ignored_count = ignored_count + 1, "
                    "status = CASE "
                    "  WHEN ignored_count + 1 >= ? THEN 'dormant' "
                    "  ELSE status END "
                    "WHERE id = ?",
                    (self._cfg["max_ignored_before_dormant"], thread_id),
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("social_orchestrator.mark_ignored_error", error=str(exc))

    # ------------------------------------------------------------------
    # Phase 1: initiative generation and queuing
    # ------------------------------------------------------------------

    def _generate_and_queue(self, thread: dict, allowed_patterns: list[str]) -> None:
        """Phase 1: generate initiative text and queue it for REPL delivery.

        Uses CIG's generate_soft_reactivation() so that both delivery paths
        (SO timer-based + CIG post-exchange) produce the same canonical template.
        No-ops when the generated text is empty (thread has no content/summary).
        """
        from arke.cognitive_initiative_gate import generate_soft_reactivation

        text = generate_soft_reactivation(thread)
        if not text:
            log.debug("social_orchestrator.generate_empty", thread_id=thread.get("id"))
            return
        self._pending_initiative = text
        self._pending_thread_id = thread["id"]
        log.info(
            "social_orchestrator.initiative_queued",
            thread_id=thread["id"],
            patterns=allowed_patterns,
        )

    # ------------------------------------------------------------------
    # Density tracking (called from chat.py after each exchange)
    # ------------------------------------------------------------------

    def record_exchange(self, depth_score: float = 0.5) -> None:
        """Record one exchange for interaction_density tracking.

        Args:
            depth_score: Proxy for exchange depth (0.0–1.0).
                         Use ``min(len(content) / 1000, 1.0)`` as a simple heuristic.
        """
        try:
            self._mm.query(
                "global",
                "INSERT INTO interaction_density (day, exchange_count, avg_depth_score) "
                "VALUES (date('now'), 1, ?) "
                "ON CONFLICT(day) DO UPDATE SET "
                "exchange_count = exchange_count + 1, "
                "avg_depth_score = (avg_depth_score * exchange_count + excluded.avg_depth_score) "
                "                  / (exchange_count + 1)",
                (depth_score,),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("social_orchestrator.density_error", error=str(exc))

    # ------------------------------------------------------------------
    # Slash command support
    # ------------------------------------------------------------------

    def pause(self, duration_hours: float = 8.0) -> None:
        """Pause initiatives for *duration_hours* hours."""
        if self._timer is not None:
            self._timer.cancel()
        until = time.time() + duration_hours * 3600
        try:
            self._mm.query(
                "session",
                "INSERT OR REPLACE INTO session_context (key, value) "
                "VALUES ('so_pause_until', ?)",
                (str(until),),
            )
        except Exception:  # noqa: BLE001
            pass
        self._enabled = False
        log.info("social_orchestrator.paused", hours=duration_hours)

    def resume(self) -> None:
        """Resume initiatives immediately."""
        try:
            self._mm.query(
                "session",
                "DELETE FROM session_context WHERE key = 'so_pause_until'",
                (),
            )
        except Exception:  # noqa: BLE001
            pass
        self._enabled = True
        self._stopped.clear()
        self._schedule_next()
        log.info("social_orchestrator.resumed")

    def disable(self) -> None:
        """Disable initiatives immediately (mode-driven, no duration)."""
        if self._timer is not None:
            self._timer.cancel()
        self._enabled = False
        log.info("social_orchestrator.disabled")

    def enable(self) -> None:
        """Enable initiatives (mode-driven, used when entering /ask)."""
        self._enabled = True
        self._stopped.clear()
        self._schedule_next()
        log.info("social_orchestrator.enabled")

    def list_threads(self) -> list[dict]:
        """Return active threads for /threads command."""
        with self._lock:
            try:
                rows = self._mm.query(
                    "global",
                    "SELECT id, content, importance_score, status, "
                    "activation_count, ignored_count, created_at "
                    "FROM cognitive_threads "
                    "WHERE status IN ('open', 'resurfaced') "
                    "ORDER BY importance_score DESC "
                    "LIMIT 20",
                    (),
                )
                return [dict(r) for r in rows]
            except Exception:  # noqa: BLE001
                return []

    def drop_thread(self, thread_id: int) -> bool:
        """Mark a thread consumed manually. Returns True on success."""
        with self._lock:
            try:
                self._mm.query(
                    "global",
                    "UPDATE cognitive_threads SET status = 'consumed' WHERE id = ?",
                    (thread_id,),
                )
                return True
            except Exception:  # noqa: BLE001
                return False
