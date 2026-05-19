"""ThreadExtractor -- extracts latent cognitive threads from exchanges.

After each rich exchange (> EXTRACTION_MIN_CHARS and containing cognitive
markers), a daemon thread silently calls the LLM to extract 0-3 cognitive
threads and stores them in ``cognitive_threads`` (global.db).

A cancellation event is checked before the LLM call: if the user sends
another message within CANCEL_GRACE_SECONDS, the extraction is abandoned
(no LLM cost incurred).

A module-level ``threading.Lock`` protects all reads/writes to
``cognitive_threads`` against race conditions with the SocialOrchestrator.

This module never prints or logs to stdout. All errors are silently swallowed
to ensure the REPL is never interrupted.
"""

from __future__ import annotations

import json
import re
import threading
import time

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants (can be overridden by config; kept simple for Phase 0)
# ---------------------------------------------------------------------------

EXTRACTION_MIN_CHARS: int = 200
CANCEL_GRACE_SECONDS: float = 10.0

# Cognitive markers: if any of these appear the exchange qualifies for extraction
_COGNITIVE_MARKERS: tuple[str, ...] = (
    "comment", "pourquoi", "si ", "peut-être", "je me demande",
    "intéressant", "curieux", "imagine", "suppose", "hypothèse",
    "connexion", "lien", "implique", "signifie", "paradoxe",
    "how", "why", "what if", "interesting", "wonder", "suppose",
)

# Module-level lock: protects cognitive_threads read/write from concurrent access
# Shared with SocialOrchestrator (imported from here)
threads_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
Tu analyses un échange homme-LLM pour en extraire des fils cognitifs latents.

Un fil cognitif est une idée, question ou connexion qui mérite d'être approfondie
dans le futur — pas encore résolue, ou susceptible d'ouvrir de nouvelles directions.

Règles strictes :
- Extrais 0 à 3 fils maximum.
- Ignore les échanges purement transactionnels (commandes, corrections, requêtes techniques sans profondeur).
- N'invente pas de fils non présents dans l'échange.
- Pour chaque fil, estime un score d'importance entre 0.0 et 1.0.
  0.3 = intéressant mais superficiel
  0.6 = idée réelle qui mérite reprise
  0.9 = connexion rare, bifurcation majeure

Réponds uniquement avec du JSON valide, sans texte autour :
[
  {
    "content": "formulation précise du fil cognitif",
    "importance_score": 0.7,
    "tags": ["tag1", "tag2"]
  }
]

Si aucun fil ne vaut la peine, réponds : []

ÉCHANGE À ANALYSER :
{exchange}
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_extract(user_msg: str, agent_response: str) -> bool:
    """Return True if this exchange qualifies for thread extraction."""
    combined = (user_msg + " " + agent_response).lower()
    if len(combined) < EXTRACTION_MIN_CHARS:
        return False
    return any(marker in combined for marker in _COGNITIVE_MARKERS)


def extract_async(
    mm: object,
    session_id: str,
    user_msg: str,
    agent_response: str,
    cancel_event: threading.Event,
) -> None:
    """Spawn a daemon thread that extracts threads and stores them.

    Args:
        mm: MemoryManager instance.
        session_id: Current session identifier.
        user_msg: The user's message text.
        agent_response: The agent's full response text.
        cancel_event: Caller sets this to abort extraction before LLM call.
    """
    if not should_extract(user_msg, agent_response):
        return

    t = threading.Thread(
        target=_extraction_worker,
        args=(mm, session_id, user_msg, agent_response, cancel_event),
        daemon=True,
        name="arke-thread-extractor",
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _extraction_worker(
    mm: object,
    session_id: str,
    user_msg: str,
    agent_response: str,
    cancel_event: threading.Event,
) -> None:
    """Background worker. Aborts silently on cancel or any error."""
    try:
        # Courtesy pause: let the user start reading the response
        for _ in range(int(CANCEL_GRACE_SECONDS * 10)):
            if cancel_event.is_set():
                log.debug("thread_extractor.cancelled", session_id=session_id)
                return
            time.sleep(0.1)

        exchange_text = f"[USER]\n{user_msg}\n\n[AGENT]\n{agent_response}"
        prompt = _EXTRACTION_PROMPT.format(exchange=exchange_text)

        from arke.llm.litellm_manager import LiteLLMManager

        manager = LiteLLMManager()
        response_text, _cost, _tokens = manager.complete(
            prompt,
            task_type="summary",
            max_tokens=400,
        )

        threads = _parse_threads(response_text)
        if not threads:
            return

        _store_threads(mm, session_id, threads, user_msg, agent_response)

    except Exception as exc:  # noqa: BLE001 — never interrupt the REPL
        log.warning("thread_extractor.error", error=str(exc), exc_type=type(exc).__name__)


def _parse_threads(raw: str) -> list[dict]:
    """Parse the LLM JSON response into a list of thread dicts."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            score = float(item.get("importance_score", 0.5))
            score = max(0.0, min(1.0, score))
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            result.append({
                "content": content,
                "importance_score": score,
                "tags": json.dumps(tags),
            })
        return result
    except (json.JSONDecodeError, ValueError):
        return []


def _store_threads(
    mm: object,
    session_id: str,
    threads: list[dict],
    user_msg: str,
    agent_response: str,
) -> None:
    """Write extracted threads to global.db under the module lock."""
    with threads_lock:
        for t in threads:
            try:
                mm.query(
                    "global",
                    "INSERT INTO cognitive_threads "
                    "(session_id, content, source_exchange_at, importance_score, tags) "
                    "VALUES (?, ?, datetime('now'), ?, ?)",
                    (session_id, t["content"], t["importance_score"], t["tags"]),
                )
                log.debug(
                    "thread_extractor.stored",
                    score=t["importance_score"],
                    preview=t["content"][:60],
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("thread_extractor.store_error", error=str(exc), exc_type=type(exc).__name__)
