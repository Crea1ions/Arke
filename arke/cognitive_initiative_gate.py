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

import json
import math
import os
import random
import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import structlog

from arke.enricher import ArkeEnricher
from arke.logging.action_writer import log_action
from arke.memory.hybrid_reranker import rerank_candidates
from arke.memory.retrieval_orchestrator import (
    load_hybrid_search_config,
    rerank_memory_candidates_hybrid,
)
from arke.vector.embedder import Embedder, VectorDisabledError

log = structlog.get_logger()


def _log_cig_proof(action: str, details: dict[str, Any], rc: int = 0) -> None:
    """Write CIG proof events to action logs for post-run diagnosis."""
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd()))
    logs_dir = workspace_root / ".arke" / "logs"
    session_id = "cig"
    try:
        session_id = str(details.get("session_id") or "cig")
    except Exception:  # noqa: BLE001
        pass
    log_action(
        logs_dir=logs_dir,
        session_id=session_id,
        mode="ask",
        tool="cig",
        action=action,
        rc=rc,
        details=details,
    )

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "enabled": True,
    "threshold_density": 0.5,
    "reactivation_threshold": 0.65,
    "allow_bootstrap_open_threads": True,
    "session_link_min_age_days": 7,
    "min_silence_minutes": None,
    "initiative_cooldown_minutes": 8,
    "activation_penalty": 0.08,
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


def _resolve_min_silence_minutes(cfg: dict[str, Any]) -> float:
    """Return effective silence window for CIG gate.

    Priority:
    1) [cognitive_initiative_gate].min_silence_minutes
    2) [social_orchestrator].min_silence_minutes
    3) default 5.0
    """
    value = cfg.get("min_silence_minutes")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass

    cfg_path = Path(__file__).parent.parent / "config" / "arke.toml"
    try:
        import tomllib

        with open(cfg_path, "rb") as fh:
            data = tomllib.load(fh)
        so_value = data.get("social_orchestrator", {}).get("min_silence_minutes")
        if so_value is not None:
            return max(0.0, float(so_value))
    except Exception:  # noqa: BLE001
        pass

    return 5.0


def _seconds_between_last_two_user_turns(mm: object) -> float:
    """Return gap in seconds between the two latest user turns.

    Using user-turn spacing avoids false rejections caused by per-loop
    heartbeat updates. If insufficient history is available, returns +inf.
    """
    try:
        rows = mm.query(
            "session",
            "SELECT timestamp FROM chat_history "
            "WHERE role = 'user' "
            "ORDER BY id DESC LIMIT 2",
            (),
        )
        if rows and len(rows) >= 2:
            latest = str(_row_get(rows[0], "timestamp", "") or "")
            previous = str(_row_get(rows[1], "timestamp", "") or "")
            if latest and previous:
                t1 = datetime.fromisoformat(latest)
                t0 = datetime.fromisoformat(previous)
                return max(0.0, (t1 - t0).total_seconds())
    except Exception:  # noqa: BLE001
        pass
    return float("inf")


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
                "importance_score": float(r["importance_score"] or 0.0),
                "reactivation_score": _apply_decay(score, days_dormant, decay_rate),
                "status": "dormant",
                "source": "dormant",
            })
        return result
    except Exception:  # noqa: BLE001
        pass
    return []


def get_candidate_threads(
    mm: object,
    max_age_days: int,
    allow_bootstrap_open_threads: bool,
) -> list[dict]:
    """Return candidate threads for CIG startup and steady-state reactivation.

    Priority is given to dormant threads. When enabled, startup bootstrap also
    includes open/resurfaced threads so CIG can initiate before a dormant state
    transition exists.
    """
    candidates: list[dict] = []
    seen_ids: set[int] = set()

    dormant = get_dormant_threads(mm, max_age_days)
    for t in dormant:
        tid = int(t["id"])
        seen_ids.add(tid)
        candidates.append(t)

    if not allow_bootstrap_open_threads:
        return candidates

    try:
        rows = mm.query(
            "global",
            "SELECT id, content, summary, reactivation_score, importance_score, created_at, status "
            "FROM cognitive_threads "
            "WHERE status IN ('open', 'resurfaced') "
            "  AND (reactivation_score > 0 OR importance_score > 0) "
            "  AND (last_activated_at IS NULL "
            "       OR last_activated_at >= date('now', ? ))",
            (f"-{max_age_days} days",),
        )
    except Exception:  # noqa: BLE001
        rows = []

    cfg = _get_config()
    decay_rate = cfg.get("decay_rate", 0.95)
    today = date.today()
    for r in rows:
        tid = int(r["id"])
        if tid in seen_ids:
            continue

        raw_score = float(r["reactivation_score"] or r["importance_score"] or 0.0)
        created_raw = r["created_at"] or ""
        days_dormant = 0
        if created_raw:
            try:
                days_dormant = max(0, (today - date.fromisoformat(created_raw[:10])).days)
            except ValueError:
                pass

        candidates.append(
            {
                "id": tid,
                "content": r["content"] or "",
                "summary": r["summary"] or "",
                "importance_score": float(r["importance_score"] or 0.0),
                "reactivation_score": _apply_decay(raw_score, days_dormant, decay_rate),
                "status": r["status"] or "open",
                "source": "bootstrap_open",
            }
        )

    candidates.sort(key=lambda t: float(t.get("reactivation_score") or 0.0), reverse=True)
    return candidates


def _build_search_query(context: dict[str, Any]) -> str:
    intention = str(context.get("intention") or "").strip()
    response = str(context.get("response") or "").strip()
    query = f"{intention} {response}".strip()
    return query[:400]


def _tokenize_query_for_lexical(query: str) -> list[str]:
    words = [w for w in re.findall(r"[a-zàâäéèêëîïôùûüç]+", query.lower()) if len(w) >= 4]
    seen: set[str] = set()
    dedup: list[str] = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        dedup.append(word)
    return dedup[:10]


def _lexical_candidates_from_session(
    mm: object,
    search_query: str,
    candidate_k: int,
    min_age_days: int,
) -> list[dict[str, Any]]:
    """Fetch lexical candidates from session memory using FTS first, then SQL fallback."""
    candidates: list[dict[str, Any]] = []
    min_age_days = max(0, int(min_age_days))

    try:
        rows = mm.query(
            "session",
            """
            SELECT c.id, c.role, c.content, c.timestamp, bm25(memory_fts) AS bm25_score
            FROM memory_fts
            JOIN chat_history c ON c.id = memory_fts.rowid
            WHERE memory_fts MATCH ?
              AND c.timestamp <= datetime('now', ?)
            ORDER BY bm25(memory_fts)
            LIMIT ?
            """,
            (search_query, f"-{min_age_days} days", candidate_k),
        )
        for row in rows:
            entry = dict(row)
            candidates.append(
                {
                    "id": entry.get("id"),
                    "role": entry.get("role"),
                    "timestamp": entry.get("timestamp"),
                    "lexical_score": -float(entry.get("bm25_score", 0.0) or 0.0),
                    "candidate_text": entry.get("content", ""),
                    "content": entry.get("content", ""),
                    "source": "session_fts",
                }
            )
    except Exception:  # noqa: BLE001
        candidates = []

    if candidates:
        return candidates

    # Deterministic fallback when FTS is unavailable or yields nothing.
    try:
        rows = mm.query(
            "session",
            "SELECT id, role, content, timestamp FROM chat_history "
            "WHERE role IN ('user', 'assistant') "
            "  AND timestamp <= datetime('now', ?) "
            "ORDER BY id DESC LIMIT ?",
            (f"-{min_age_days} days", max(candidate_k * 8, candidate_k)),
        )
    except Exception:  # noqa: BLE001
        rows = []

    tokens = _tokenize_query_for_lexical(search_query)
    if not tokens:
        return []

    scored: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        content = str(entry.get("content") or "")
        if not content:
            continue
        content_l = content.lower()
        overlap = sum(1 for token in tokens if token in content_l)
        if overlap <= 0:
            continue
        lexical_score = overlap / float(len(tokens))
        scored.append(
            {
                "id": entry.get("id"),
                "role": entry.get("role"),
                "timestamp": entry.get("timestamp"),
                "lexical_score": lexical_score,
                "candidate_text": content,
                "content": content,
                "source": "session_sql",
            }
        )

    scored.sort(key=lambda x: float(x.get("lexical_score") or 0.0), reverse=True)
    return scored[:candidate_k]


def _get_hybrid_context_candidates(mm: object, context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return context-related candidates using S054 lexical prefilter + hybrid rerank."""
    search_query = _build_search_query(context)
    if not search_query:
        return [], {
            "semantic_applied": False,
            "fallback_reason": "empty_query",
            "candidate_k": 0,
            "search_query": "",
        }

    cfg = load_hybrid_search_config()
    cig_cfg = _get_config()
    bounded_k = max(1, min(int(cfg.candidate_k), 20))
    min_age_days = max(0, int(cig_cfg.get("session_link_min_age_days", 7)))
    lexical_candidates = _lexical_candidates_from_session(mm, search_query, bounded_k, min_age_days)

    result_box: dict[str, Any] = {}
    error_box: dict[str, str] = {}

    def _run_rerank() -> None:
        try:
            result_box["value"] = rerank_memory_candidates_hybrid(
                search_query=search_query,
                lexical_candidates=lexical_candidates,
                limit=max(1, min(int(cfg.final_n), 5)),
                config=cfg,
            )
        except Exception as exc:  # noqa: BLE001
            error_box["type"] = type(exc).__name__

    timeout_s = max(float(cfg.semantic_timeout_ms) / 1000.0, 0.05)
    worker = threading.Thread(target=_run_rerank, daemon=True, name="cig-hybrid-rerank")
    worker.start()
    worker.join(timeout=timeout_s)

    if worker.is_alive():
        result = {
            "results": lexical_candidates[: max(1, min(int(cfg.final_n), 5))],
            "semantic_applied": False,
            "fallback_reason": "outer_timeout",
        }
    elif "type" in error_box:
        result = {
            "results": lexical_candidates[: max(1, min(int(cfg.final_n), 5))],
            "semantic_applied": False,
            "fallback_reason": error_box["type"],
        }
    else:
        result = result_box.get("value") or {
            "results": lexical_candidates[: max(1, min(int(cfg.final_n), 5))],
            "semantic_applied": False,
            "fallback_reason": "empty_result",
        }
    ranked = result.get("results", []) or []

    if ranked and not bool(result.get("semantic_applied", False)):
        needs_fallback_normalization = any(cand.get("final_score") is None for cand in ranked)
        if needs_fallback_normalization:
            ranked = rerank_candidates(
                ranked,
                lexical_weight=1.0,
                semantic_weight=0.0,
                lexical_key="lexical_score",
                semantic_key="semantic_score",
            )

    out: list[dict[str, Any]] = []
    for cand in ranked:
        source_id = f"chat:{cand.get('id')}"
        text = str(cand.get("content") or cand.get("candidate_text") or "")
        lexical_score = float(cand.get("lexical_score") or 0.0)
        semantic_score = float(cand.get("semantic_score") or 0.0)
        if "final_score" in cand and cand.get("final_score") is not None:
            final_score = float(cand.get("final_score") or 0.0)
        else:
            # SQL fallback lexical_score is already normalized in [0, 1].
            # FTS fallback uses inverted BM25, so clamp into a stable eligibility range.
            final_score = lexical_score if lexical_score <= 1.0 else 1.0
        out.append(
            {
                "id": source_id,
                "source_id": source_id,
                "content": text,
                "summary": text[:120],
                "reactivation_score": final_score,
                "importance_score": final_score,
                "effective_score": final_score,
                "lexical_score": lexical_score,
                "semantic_score": semantic_score,
                "final_score": final_score,
                "status": "session_candidate",
                "source": str(cand.get("source") or "session"),
                "timestamp": cand.get("timestamp"),
            }
        )

    meta = {
        "semantic_applied": bool(result.get("semantic_applied", False)),
        "fallback_reason": result.get("fallback_reason"),
        "candidate_k": bounded_k,
        "session_link_min_age_days": min_age_days,
        "search_query": search_query,
    }
    return out, meta


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _row_get(row: object, key: str, default: Any = None) -> Any:
    """Return a value from dict-like rows and sqlite3.Row safely."""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except Exception:  # noqa: BLE001
        return default


def _get_last_initiative_thread_id(mm: object) -> Optional[int]:
    """Return the most recently generated initiative thread id if available."""
    try:
        rows = mm.query(
            "global",
            "SELECT thread_id FROM initiative_log "
            "WHERE thread_id IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1",
            (),
        )
        if rows and _row_get(rows[0], "thread_id") is not None:
            raw = str(_row_get(rows[0], "thread_id"))
            if raw.startswith("chat:"):
                return None
            return _safe_int(raw, default=-1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _apply_exposure_penalties(
    mm: object,
    threads: list[dict],
    cooldown_minutes: float,
    activation_penalty: float,
) -> list[dict]:
    """Compute effective score with cooldown and exposure penalties.

    Threads recently activated are downranked within cooldown window; repeated
    activation_count also applies a bounded penalty to avoid the same thread
    monopolizing initiatives.
    """
    if not threads:
        return []

    ids = [str(int(t["id"])) for t in threads if t.get("id") is not None]
    if not ids:
        return threads

    placeholders = ",".join(["?"] * len(ids))
    meta: dict[int, dict[str, Any]] = {}
    try:
        rows = mm.query(
            "global",
            "SELECT id, activation_count, last_activated_at FROM cognitive_threads "
            f"WHERE id IN ({placeholders})",
            tuple(ids),
        )
        for r in rows:
            meta[_safe_int(r.get("id"), -1)] = {
                "activation_count": _safe_int(r.get("activation_count"), 0),
                "last_activated_at": r.get("last_activated_at"),
            }
    except Exception:  # noqa: BLE001
        meta = {}

    now = datetime.now()
    out: list[dict] = []
    cooldown_seconds = max(0.0, float(cooldown_minutes) * 60.0)
    for t in threads:
        tid = _safe_int(t.get("id"), -1)
        m = meta.get(tid, {})
        activation_count = _safe_int(m.get("activation_count"), 0)
        base_score = float(t.get("reactivation_score") or 0.0)
        penalty_count = min(0.35, max(0.0, float(activation_penalty)) * activation_count)

        penalty_cooldown = 0.0
        last_activated_raw = m.get("last_activated_at")
        if last_activated_raw:
            try:
                last_ts = datetime.fromisoformat(str(last_activated_raw))
                since = max(0.0, (now - last_ts).total_seconds())
                if since < cooldown_seconds and cooldown_seconds > 0:
                    # Strong temporary downrank during cooldown window.
                    penalty_cooldown = 0.5 * (1.0 - (since / cooldown_seconds))
            except ValueError:
                pass

        effective = max(0.0, base_score - penalty_count - penalty_cooldown)
        item = dict(t)
        item["activation_count"] = activation_count
        item["effective_score"] = effective
        out.append(item)

    out.sort(key=lambda x: float(x.get("effective_score") or 0.0), reverse=True)
    return out


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
    templates = [
        "On avait exploré une piste sur « {anchor} » récemment. Ça pourrait être lié à ce dont tu parles. Tu veux reprendre ?",
        "Je peux relancer un ancien fil autour de « {anchor} ». Tu veux qu'on l'approfondisse maintenant ?",
        "Je repense à « {anchor} » dans notre historique. Tu préfères qu'on l'articule avec le sujet actuel ?",
        "On peut rouvrir la piste « {anchor} » sous un angle différent. Tu veux tenter cette bifurcation ?",
    ]
    idx_seed = _safe_int(thread.get("id"), 0) + _safe_int(thread.get("activation_count"), 0)
    tpl = templates[idx_seed % len(templates)]
    return tpl.format(anchor=anchor)


def log_initiative(
    mm: object,
    thread_id: object,
    density_snapshot: float,
    context_anchor: str,
    initiative_type: str = "soft_reactivation",
    thread_raw: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
    contract_version: str | None = None,
) -> str:
    """Insert a row into initiative_log; return the generated uuid id.

    accepted is left NULL (unknown) — absence of reply is NOT logged as rejection.

    Args:
        initiative_type: 'soft_reactivation' (default) or 'divergent_reactivation'.
        thread_raw: Optional Themelios thread dict (for contract traceability).
        enrichment: Optional Archè enrichment metadata dict.
        contract_version: Optional contract version (e.g., "1.0").
    """
    log_id = str(uuid.uuid4())
    try:
        # Try with new columns first (thread_raw, arch_enrichment, contract_version)
        thread_raw_json = json.dumps(thread_raw) if thread_raw else None
        enrichment_json = json.dumps(enrichment) if enrichment else None
        
        mm.query(
            "global",
            "INSERT INTO initiative_log (id, thread_id, type, density_snapshot, context_anchor, "
            "thread_raw, arch_enrichment, contract_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                str(thread_id),
                initiative_type,
                density_snapshot,
                context_anchor,
                thread_raw_json,
                enrichment_json,
                contract_version,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback: columns may not exist yet (pre-migration)
        try:
            mm.query(
                "global",
                "INSERT INTO initiative_log (id, thread_id, type, density_snapshot, context_anchor) "
                "VALUES (?, ?, ?, ?, ?)",
                (log_id, str(thread_id), initiative_type, density_snapshot, context_anchor),
            )
        except Exception as exc2:  # noqa: BLE001
            log.debug("cig.log_initiative_error", error=str(exc2))
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


def mark_initiative_delivered(mm: object, log_id: str) -> None:
    """Mark initiative delivery and update thread lifecycle state.

    Called when an initiative is actually shown in REPL, not only generated.
    """
    try:
        rows = mm.query(
            "global",
            "SELECT thread_id FROM initiative_log WHERE id = ? LIMIT 1",
            (log_id,),
        )
        if not rows or _row_get(rows[0], "thread_id") is None:
            return

        thread_id = _safe_int(_row_get(rows[0], "thread_id"), default=-1)
        if thread_id < 0:
            return

        mm.query(
            "global",
            "UPDATE cognitive_threads SET "
            "activation_count = activation_count + 1, "
            "last_activated_at = datetime('now'), "
            "status = 'resurfaced' "
            "WHERE id = ?",
            (thread_id,),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("cig.mark_delivered_error", error=str(exc), log_id=log_id)


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


def _get_thread_raw(mm: object, thread_id: object) -> dict[str, Any]:
    """Fetch complete thread data from cognitive_threads for enrichment.
    
    Returns a dict with all thread columns needed for Themelios contract validation.
    Returns empty dict if thread not found.
    """
    try:
        rows = mm.query(
            "global",
            "SELECT id, content, summary, reactivation_score, importance_score, "
            "created_at, tags, status, activation_count, ignored_count, last_activated_at, "
            "thread_type, depth_score, relevance_score, relation_type, relation_evidence, extraction_confidence "
            "FROM cognitive_threads WHERE id = ? LIMIT 1",
            (str(thread_id),),
        )
        if rows:
            thread = dict(rows[0])
            # Normalize thread_id key for enrichment schema
            thread["thread_id"] = str(thread.get("id", thread_id))
            thread["score"] = float(thread.get("reactivation_score") or 0.0)
            return thread
    except Exception:  # noqa: BLE001
        pass
    return {}


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
        _log_cig_proof("gate_reject", {"gate": "paused"})
        return None, None

    cfg = _get_config()

    if not cfg.get("enabled", True):
        _log_cig_proof("gate_reject", {"gate": "disabled"})
        return None, None

    # Gate 1: interaction density
    density = compute_interaction_density(mm)
    threshold = auto_calibrate_threshold(mm, cfg["threshold_density"])
    if density < threshold:
        log.debug("cig.rejected.density", density=density, threshold=threshold)
        _log_cig_proof(
            "gate_reject",
            {
                "gate": "density",
                "density": round(float(density), 4),
                "threshold": round(float(threshold), 4),
            },
        )
        return None, None

    # Gate 1.5: minimal user silence before initiative attempt
    min_silence_minutes = _resolve_min_silence_minutes(cfg)
    elapsed_seconds = _seconds_between_last_two_user_turns(mm)
    required_seconds = max(0.0, float(min_silence_minutes) * 60.0)
    if elapsed_seconds < required_seconds:
        _log_cig_proof(
            "gate_reject",
            {
                "gate": "min_silence_not_met",
                "elapsed_seconds": round(float(elapsed_seconds), 3),
                "required_seconds": round(float(required_seconds), 3),
                "min_silence_minutes": float(min_silence_minutes),
            },
        )
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
            
            # NEW: Enrich with Archè metadata
            enricher = ArkeEnricher()
            thread_raw = _get_thread_raw(mm, divergent_thread["id"])
            text, enrichment = enricher.enrich(text, thread_raw, context)
            
            log_id = log_initiative(
                mm,
                divergent_thread["id"],
                density,
                anchor,
                "divergent_reactivation",
                thread_raw=thread_raw,
                enrichment=enrichment,
                contract_version=enricher.validator.contract_version,
            )
            log.info("cig.divergent_initiative", thread_id=divergent_thread["id"], density=density)
            return text, log_id
        # No divergent thread available → fall through to normal contextual path

    # Gate 2: candidate memories from session lexical prefilter + hybrid rerank.
    threads, retrieval_meta = _get_hybrid_context_candidates(mm, context)
    eligible = [t for t in threads if float(t.get("effective_score") or 0.0) >= cfg["reactivation_threshold"]]
    if not eligible:
        log.debug("cig.rejected.no_eligible_threads")
        source_counts: dict[str, int] = {}
        for t in threads:
            source = str(t.get("source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        _log_cig_proof(
            "gate_reject",
            {
                "gate": "no_eligible_threads",
                "candidate_threads": len(threads),
                "source_counts": source_counts,
                "reactivation_threshold": float(cfg["reactivation_threshold"]),
                "semantic_applied": retrieval_meta.get("semantic_applied", False),
                "fallback_reason": retrieval_meta.get("fallback_reason"),
                "candidate_k": retrieval_meta.get("candidate_k", 0),
            },
        )
        return None, None

    # Rank eligible candidates by final hybrid score.
    thread = max(eligible, key=lambda t: float(t.get("final_score") or t.get("effective_score") or 0.0))

    # Guardrail: avoid immediate same-thread repetition when alternatives exist.
    last_thread_id = _get_last_initiative_thread_id(mm)
    current_id = str(thread.get("id") or "")
    if last_thread_id is not None and _safe_int(thread.get("id"), -1) == last_thread_id:
        alternatives = [t for t in eligible if _safe_int(t.get("id"), -1) != last_thread_id]
        if alternatives:
            thread = max(alternatives, key=lambda t: float(t.get("final_score") or t.get("effective_score") or 0.0))
    elif current_id:
        try:
            rows = mm.query(
                "global",
                "SELECT thread_id FROM initiative_log WHERE thread_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (),
            )
        except Exception:  # noqa: BLE001
            rows = []
        last_source_id = str(_row_get(rows[0], "thread_id", "") or "") if rows else ""
        alternatives = [t for t in eligible if str(t.get("id") or "") != last_source_id]
        if alternatives:
            thread = max(alternatives, key=lambda t: float(t.get("final_score") or t.get("effective_score") or 0.0))

    # Gate 3: contextual anchor
    if not is_contextually_anchored(thread, context):
        log.debug("cig.rejected.no_anchor", thread_id=thread["id"])
        _log_cig_proof(
            "gate_reject",
            {
                "gate": "no_anchor",
                "thread_id": thread["id"],
            },
        )
        return None, None

    # All gates passed → generate
    text = generate_soft_reactivation(thread)
    if not text:
        return None, None

    anchor = (thread.get("summary") or thread.get("content", "")[:60]).strip()
    
    # NEW: Enrich with Archè metadata
    enricher = ArkeEnricher()
    thread_raw = _get_thread_raw(mm, thread["id"])
    text, enrichment = enricher.enrich(text, thread_raw, context)
    
    log_id = log_initiative(
        mm,
        thread["id"],
        density,
        anchor,
        thread_raw=thread_raw,
        enrichment=enrichment,
        contract_version=enricher.validator.contract_version,
    )
    log.info("cig.initiative_generated", thread_id=thread["id"], density=density)
    _log_cig_proof(
        "initiative_generated",
        {
            "thread_id": thread["id"],
            "thread_status": thread.get("status"),
            "thread_source": thread.get("source"),
            "selected_source_id": thread.get("source_id") or thread.get("id"),
            "semantic_applied": retrieval_meta.get("semantic_applied", False),
            "fallback_reason": retrieval_meta.get("fallback_reason"),
            "effective_score": round(float(thread.get("effective_score") or thread.get("reactivation_score") or 0.0), 4),
            "final_score": round(float(thread.get("final_score") or thread.get("effective_score") or 0.0), 4),
            "density": round(float(density), 4),
            "log_id": log_id,
        },
    )
    return text, log_id
