"""Cognitive Initiative Gate (CIG) — Phase 1 controlled soft reactivation.

Invariants (non-negotiable):
- The system never initiates interaction for novelty.
- The system only reactivates existing cognitive threads.
- The system never introduces new topics autonomously.
- The system never optimizes engagement.
- The system prioritizes silence (None) over uncertain initiative.
- Absence of user reply is NOT logged as rejection (accepted stays NULL).

Anchor modes (configured via arke.toml [cognitive_initiative_gate]):
- semantic_anchor = false (default): keyword overlap ≥ 2 words — deterministic, no I/O.
- semantic_anchor = true: cosine similarity via Embedder; falls back to keyword
  on VectorDisabledError or any exception. Requires [vector] enabled = true.
"""

from __future__ import annotations

import math
import random
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

import structlog

from arke.vector.embedder import Embedder, VectorDisabledError

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "enabled": True,
    "threshold_density": 0.5,
    "reactivation_threshold": 0.65,
    "thread_max_age_days": 14,
    "auto_calibrate": True,
    "calibration_min_samples": 30,
    "semantic_anchor": False,
    "semantic_threshold": 0.65,
    "divergence_rate": 0.05,
    "decay_rate": 0.95,
    "utility_weights": {
        "reactivation": 0.4,
        "importance": 0.3,
        "density": 0.2,
        "relevance": 0.1,
    },
}


def _load_config() -> dict:
    """Load [cognitive_initiative_gate] from arke.toml, merge with defaults."""
    cfg_path = Path(__file__).parent.parent / "config" / "arke.toml"
    try:
        import tomllib
        with open(cfg_path, "rb") as fh:
            data = tomllib.load(fh)
        return {**_DEFAULTS, **data.get("cognitive_initiative_gate", {})}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULTS)


# Module-level config cache (loaded once per process, same pattern as social_orchestrator)
_cfg: Optional[dict] = None


def _get_config() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = _load_config()
    return _cfg


# ---------------------------------------------------------------------------
# Semantic similarity helpers (used when semantic_anchor = true)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [0, 1] between two float vectors.

    Returns 0.0 if either vector is zero-length.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_similarity(thread: dict, context: dict) -> float:
    """Return cosine similarity between thread and context via Embedder.

    Raises VectorDisabledError if vector search is disabled in config.
    Caller must handle exceptions and fall back to keyword anchor.
    """
    thread_text = ((thread.get("summary") or "") + " " + thread.get("content", "")[:200]).strip()
    context_text = (context.get("intention", "") + " " + context.get("response", "")[:200]).strip()
    embedder = Embedder()
    t_vec = embedder.embed(thread_text)
    c_vec = embedder.embed(context_text)
    return _cosine_similarity(t_vec, c_vec)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _apply_decay(score: float, days_dormant: int, rate: float = 0.95) -> float:
    """Apply exponential decay to a reactivation score.

    Returns ``score * (rate ** days_dormant)`` with a floor of 0.05 so that
    threads remain marginally discoverable even after long dormancy.

    Args:
        score: Original reactivation score (0.0–1.0).
        days_dormant: Days since thread creation. Negative values treated as 0.
        rate: Decay multiplier per day (0.0–1.0). 0.95 = 5 % decay per day.
    """
    decayed = score * (rate ** max(0, days_dormant))
    return max(0.05, decayed)


def compute_utility_score(
    thread: dict,
    density: float,
    relevance_score: float = 0.0,
    weights: dict | None = None,
) -> float:
    """Return a composite utility score for *thread* used to rank candidates.

    Formula::

        U = w_r * reactivation_score
          + w_i * importance_score
          + w_d * density
          + w_v * relevance_score

    Weights are loaded from ``[cognitive_initiative_gate.utility_weights]`` in
    arke.toml and can be overridden via the *weights* parameter (useful in
    tests).

    Args:
        thread: Dict with ``reactivation_score`` and ``importance_score`` keys.
        density: Current interaction density (0.0–1.0) from
            :func:`compute_interaction_density`.
        relevance_score: Optional semantic relevance score (0.0–1.0).
            Defaults to 0.0 when semantic_anchor is disabled.
        weights: Optional weight dict overriding arke.toml values.

    Returns:
        Composite score in [0.0, 1.0] (not clamped, but inputs are already
        normalised so the result stays in range under normal conditions).
    """
    cfg = _get_config()
    w = dict(cfg.get("utility_weights", _DEFAULTS["utility_weights"]))
    if weights:
        w.update(weights)

    r = float(thread.get("reactivation_score") or 0.0)
    i = float(thread.get("importance_score") or 0.0)
    return (
        w.get("reactivation", 0.4) * r
        + w.get("importance", 0.3) * i
        + w.get("density", 0.2) * density
        + w.get("relevance", 0.1) * relevance_score
    )


def compute_interaction_density(mm: object) -> float:
    """Return average avg_depth_score over the past 7 days (0.0–1.0).

    Uses avg_depth_score (0–1 scale) rather than exchange_count so that the
    threshold_density = 0.5 configuration is meaningful.
    """
    try:
        rows = mm.query(
            "global",
            "SELECT AVG(avg_depth_score) AS avg FROM interaction_density "
            "WHERE day >= date('now', '-7 days')",
            (),
        )
        if rows and rows[0]["avg"] is not None:
            return float(rows[0]["avg"])
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def get_dormant_threads(mm: object, max_age_days: int) -> list[dict]:
    """Return dormant threads eligible for reactivation, ordered by score desc.

    A thread is eligible if:
    - status = 'dormant'
    - reactivation_score > 0
    - last_activated_at IS NULL (never sent) OR within max_age_days
    """
    try:
        rows = mm.query(
            "global",
            "SELECT id, content, summary, reactivation_score, importance_score, created_at "
            "FROM cognitive_threads "
            "WHERE status = 'dormant' "
            "  AND reactivation_score > 0 "
            "  AND (last_activated_at IS NULL "
            "       OR last_activated_at >= date('now', ? )) "
            "ORDER BY reactivation_score DESC",
            (f"-{max_age_days} days",),
        )
        cfg = _get_config()
        decay_rate = cfg.get("decay_rate", 0.95)
        today = date.today()
        result = []
        for r in rows:
            score = float(r["reactivation_score"] or r["importance_score"] or 0.0)
            created_raw = r["created_at"] or ""
            days_dormant = 0
            if created_raw:
                try:
                    days_dormant = max(0, (today - date.fromisoformat(created_raw[:10])).days)
                except ValueError:
                    pass
            result.append({
                "id": r["id"],
                "content": r["content"] or "",
                "summary": r["summary"] or "",
                "reactivation_score": _apply_decay(score, days_dormant, decay_rate),
            })
        return result
    except Exception:  # noqa: BLE001
        pass
    return []


def get_divergent_thread(mm: object, max_age_days: int) -> Optional[dict]:
    """Return a random dormant thread for divergent reactivation (Serendipity principle).

    Unlike get_dormant_threads(), this function ignores reactivation_score ordering
    and returns a random eligible thread. No contextual anchor check is applied.

    Invariant: only uses real memory threads — never synthetic content.
    Returns None when no eligible dormant threads exist.
    """
    threads = get_dormant_threads(mm, max_age_days)
    eligible = [t for t in threads if t["reactivation_score"] > 0]
    if not eligible:
        return None
    return random.choice(eligible)


def is_contextually_anchored(thread: dict, context: dict) -> bool:
    """Return True if the thread is contextually anchored to the current context.

    Anchor mode is controlled by ``semantic_anchor`` in arke.toml:
    - False (default): keyword overlap ≥ 2 words (len ≥ 4) — deterministic, no I/O.
    - True: cosine similarity via Embedder ≥ semantic_threshold. Falls back to
      keyword anchor if VectorDisabledError or any exception is raised.
    """
    cfg = _get_config()
    if cfg.get("semantic_anchor", False):
        try:
            sim = _semantic_similarity(thread, context)
            return sim >= cfg.get("semantic_threshold", 0.65)
        except Exception:  # noqa: BLE001  # VectorDisabledError or network error
            pass  # fall through to keyword anchor

    # Keyword anchor (default and fallback)
    def _words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-zàâäéèêëîïôùûüç]+", text.lower()) if len(w) >= 4}

    thread_words = _words(thread.get("content", "") + " " + thread.get("summary", ""))
    context_words = _words(
        context.get("intention", "") + " " + context.get("response", "")
    )
    return len(thread_words & context_words) >= 2


def generate_soft_reactivation(thread: dict, divergent: bool = False) -> str:
    """Build a canonical soft-reactivation question from a thread.

    Uses summary if available, otherwise first 120 chars of content.
    Format: French open question, never directive.

    Args:
        thread: Dict with 'summary' and/or 'content' keys.
        divergent: If True, prefix with a serendipitous framing instead of
                   contextual framing. Signals to the user this is an unexpected
                   connection rather than a contextual reactivation.
    """
    anchor = (thread.get("summary") or thread.get("content", "")[:120]).strip()
    if not anchor:
        return ""
    if divergent:
        return (
            f"⚡ Connexion inattendue : on avait une piste sur « {anchor} ». "
            "Rien à voir avec ce dont tu parles, mais ça me semble intéressant. Tu veux y revenir ?"
        )
    return (
        f"On avait exploré une piste sur « {anchor} » récemment. "
        "Ça pourrait être lié à ce dont tu parles. Tu veux reprendre ?"
    )


def log_initiative(
    mm: object,
    thread_id: object,
    density_snapshot: float,
    context_anchor: str,
    initiative_type: str = "soft_reactivation",
) -> str:
    """Insert a row into initiative_log; return the generated uuid id.

    accepted is left NULL (unknown) — absence of reply is NOT logged as rejection.

    Args:
        initiative_type: 'soft_reactivation' (default) or 'divergent_reactivation'.
    """
    log_id = str(uuid.uuid4())
    try:
        mm.query(
            "global",
            "INSERT INTO initiative_log (id, thread_id, type, density_snapshot, context_anchor) "
            "VALUES (?, ?, ?, ?, ?)",
            (log_id, str(thread_id), initiative_type, density_snapshot, context_anchor),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("cig.log_initiative_error", error=str(exc))
    return log_id


def mark_initiative_accepted(mm: object, log_id: str) -> None:
    """Mark an initiative as explicitly accepted (Phase 2+ only).

    Called only when a clear positive signal is detected (e.g., user directly
    engages with the reactivated thread). Never called automatically.
    """
    try:
        mm.query(
            "global",
            "UPDATE initiative_log SET accepted = 1 WHERE id = ?",
            (log_id,),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("cig.mark_accepted_error", error=str(exc))


def detect_positive_signal(raw: str, initiative_text: str) -> bool:
    """Return True if user input `raw` shows engagement with the last initiative.

    Uses the same keyword overlap heuristic as is_contextually_anchored:
    ≥ 2 words of length ≥ 4 in common between the user's input and the
    initiative text that was displayed.

    Always returns False when either argument is empty.
    """
    if not raw or not initiative_text:
        return False

    def _words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-zàâäéèêëîïôùûüç]+", text.lower()) if len(w) >= 4}

    return len(_words(raw) & _words(initiative_text)) >= 2


def auto_calibrate_threshold(mm: object, current_threshold: float) -> float:
    """Adjust threshold_density based on acceptance ratio (Phase 2 calibration).

    Only runs when calibration_min_samples rows WHERE accepted IS NOT NULL exist.
    If accepted ratio > 0.7  → lower threshold by 0.05 (floor 0.4).
    If accepted ratio < 0.3  → raise threshold by 0.05 (ceil 0.8).
    Otherwise                → unchanged.

    NULL rows are excluded — absence of reply does NOT count as rejection.
    """
    cfg = _get_config()
    if not cfg.get("auto_calibrate", True):
        return current_threshold

    min_samples = cfg.get("calibration_min_samples", 30)
    try:
        rows = mm.query(
            "global",
            "SELECT COUNT(*) AS total, SUM(accepted) AS accepted_sum "
            "FROM initiative_log WHERE accepted IS NOT NULL",
            (),
        )
        if not rows:
            return current_threshold
        total = rows[0]["total"] or 0
        if total < min_samples:
            return current_threshold
        accepted_sum = rows[0]["accepted_sum"] or 0
        ratio = accepted_sum / total
        if ratio > 0.7:
            return max(0.4, round(current_threshold - 0.05, 2))
        if ratio < 0.3:
            return min(0.8, round(current_threshold + 0.05, 2))
    except Exception:  # noqa: BLE001
        pass
    return current_threshold


def cognitive_initiative_engine(
    mm: object,
    context: dict,
    paused: bool = False,
) -> tuple[str, str] | tuple[None, None]:
    """Main CIG pipeline. Returns (initiative_text, log_id) or (None, None).

    Conservative by design: returns (None, None) on any ambiguity.
    No LLM calls. No side effects beyond initiative_log INSERT.

    Args:
        mm: MemoryManager instance.
        context: Dict with keys 'intention' (str) and 'response' (str).
        paused: If True, skip immediately (SocialOrchestrator is paused).
    """
    # Gate 0: system-level pause (SocialOrchestrator._enabled = False)
    if paused:
        return None, None

    cfg = _get_config()

    if not cfg.get("enabled", True):
        return None, None

    # Gate 1: interaction density
    density = compute_interaction_density(mm)
    threshold = auto_calibrate_threshold(mm, cfg["threshold_density"])
    if density < threshold:
        log.debug("cig.rejected.density", density=density, threshold=threshold)
        return None, None

    # Gate 2: dormant threads exist
    threads = get_dormant_threads(mm, cfg["thread_max_age_days"])
    eligible = [t for t in threads if t["reactivation_score"] >= cfg["reactivation_threshold"]]
    if not eligible:
        log.debug("cig.rejected.no_eligible_threads")
        return None, None

    # Divergence gate: with probability divergence_rate, skip contextual anchor
    # and select a random dormant thread (Serendipity principle).
    # Invariant: only uses real memory — never synthetic content.
    divergence_rate = cfg.get("divergence_rate", 0.0)
    is_divergent = divergence_rate > 0.0 and random.random() < divergence_rate

    if is_divergent:
        divergent_thread = get_divergent_thread(mm, cfg["thread_max_age_days"])
        if divergent_thread is not None:
            text = generate_soft_reactivation(divergent_thread, divergent=True)
            if not text:
                return None, None
            anchor = (divergent_thread.get("summary") or divergent_thread.get("content", "")[:60]).strip()
            log_id = log_initiative(mm, divergent_thread["id"], density, anchor, "divergent_reactivation")
            log.info("cig.divergent_initiative", thread_id=divergent_thread["id"], density=density)
            return text, log_id
        # No divergent thread available → fall through to normal contextual path

    thread = eligible[0]  # highest reactivation_score (sorted by query)

    # Rank eligible threads by composite utility score (Phase 2)
    thread = max(
        eligible,
        key=lambda t: compute_utility_score(t, density),
    )

    # Gate 3: contextual anchor
    if not is_contextually_anchored(thread, context):
        log.debug("cig.rejected.no_anchor", thread_id=thread["id"])
        return None, None

    # All gates passed → generate
    text = generate_soft_reactivation(thread)
    if not text:
        return None, None

    anchor = (thread.get("summary") or thread.get("content", "")[:60]).strip()
    log_id = log_initiative(mm, thread["id"], density, anchor)
    log.info("cig.initiative_generated", thread_id=thread["id"], density=density)
    return text, log_id
