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
- Pour chaque fil, estime des scores entre 0.0 et 1.0 :
  0.3 = intéressant mais superficiel
  0.6 = idée réelle qui mérite reprise
  0.9 = connexion rare, bifurcation majeure

=== VERSION 1.1 NOUVELLES RÈGLES ===

1. HIÉRARCHIE : Pour chaque fil, indique son type :
   - "primary" : thème principal de l'échange
   - "sub_theme" : sous-thème, ramification du thème principal
   - "example" : exemple concret ou illustration
   - "question" : question ouverte, relance dialogique (« Pour aller plus loin »)

2. RELATIONS : Si plusieurs fils sont extraits, indique pour chacun :
   - "related_thread_index" : l'index (0, 1, 2) du fil auquel il est lié, ou null si aucun
   - "relation_type" : une valeur parmi ["elaboration", "contrast", "example_of", "question_followup", null]
   - "relation_evidence" : court extrait de l'échange qui justifie ce lien, ou null

3. SCORES DÉCOMPOSÉS : En plus du score global, fournis :
   - "depth_score" : 0.0-1.0 — à quel point l'idée est profonde vs superficielle
   - "relevance_score" : 0.0-1.0 — à quel point elle est pertinente pour la suite

4. TAGS CONTRÔLÉS : Choisis parmi cette taxonomie fermée (1 à 3 tags max) :
   ["philosophie", "science", "éthique", "architecture", "méthode", "question",
    "hypothèse", "paradoxe", "métaphore", "histoire", "technique", "exploration"]

5. VALIDATION : Ajoute un champ :
   - "extraction_confidence" : 0.0-1.0 — ta confiance dans la qualité globale de cette extraction

Réponds uniquement avec du JSON valide, sans texte autour :
[
  {
    "content": "formulation précise du fil cognitif",
    "importance_score": 0.7,
    "depth_score": 0.6,
    "relevance_score": 0.8,
    "thread_type": "primary",
    "tags": ["philosophie", "question"],
    "related_thread_index": null,
    "relation_type": null,
    "relation_evidence": null,
    "extraction_confidence": 0.85
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
    """Parse the LLM JSON response into a list of thread dicts (v1.1).
    
    Validates and normalizes:
    - Scores: importance, depth, relevance, confidence (clamped to [0, 1])
    - thread_type: must be in {primary, sub_theme, example, question}
    - tags: must be in the closed taxonomy (12 valid tags)
    - relation_type: must be in {elaboration, contrast, example_of, question_followup}
    - related_thread_index: integer or null
    
    All new fields default gracefully if missing.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return []
        
        # Valid enums
        valid_types = {"primary", "sub_theme", "example", "question"}
        valid_tags = {
            "philosophie", "science", "éthique", "architecture", "méthode",
            "question", "hypothèse", "paradoxe", "métaphore", "histoire",
            "technique", "exploration"
        }
        valid_relations = {"elaboration", "contrast", "example_of", "question_followup"}
        
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
            # Extract and validate content
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            
            # Clamp all scores to [0, 1]
            importance = float(item.get("importance_score", 0.5))
            importance = max(0.0, min(1.0, importance))
            
            depth = float(item.get("depth_score", 0.5))
            depth = max(0.0, min(1.0, depth))
            
            relevance = float(item.get("relevance_score", 0.5))
            relevance = max(0.0, min(1.0, relevance))
            
            confidence = float(item.get("extraction_confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            
            # Validate thread_type
            thread_type = item.get("thread_type", "primary")
            if thread_type not in valid_types:
                thread_type = "primary"
            
            # Validate and filter tags
            raw_tags = item.get("tags", [])
            if not isinstance(raw_tags, list):
                raw_tags = []
            tags = [t for t in raw_tags if t in valid_tags]
            
            # Validate related_thread_index
            related_idx = item.get("related_thread_index")
            if related_idx is not None:
                try:
                    related_idx = int(related_idx)
                except (ValueError, TypeError):
                    related_idx = None
            
            # Validate relation_type
            relation_type = item.get("relation_type")
            if relation_type not in valid_relations:
                relation_type = None
            
            # If related_idx is set but relation_type is missing, log warning
            if related_idx is not None and relation_type is None:
                log.warning("thread_extractor.relation_type_missing", related_idx=related_idx)
            
            # Extract relation_evidence
            relation_evidence = item.get("relation_evidence")
            if relation_evidence is not None:
                relation_evidence = str(relation_evidence).strip()[:500]  # Limit to 500 chars
            
            result.append({
                "content": content,
                "importance_score": importance,
                "depth_score": depth,
                "relevance_score": relevance,
                "thread_type": thread_type,
                "tags": json.dumps(tags),
                "related_thread_index": related_idx,
                "relation_type": relation_type,
                "relation_evidence": relation_evidence,
                "extraction_confidence": confidence,
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
    """Write extracted threads to global.db under the module lock (v1.1).
    
    Two-pass approach:
    1. Insert all threads with related_thread_index preserved as metadata
    2. Resolve references: for threads with related_thread_index, 
       fetch the target thread ID and update related_thread_id
    """
    with threads_lock:
        inserted_ids: list[int] = []
        
        # Pass 1: Insert all threads, collect row IDs
        for t in threads:
            try:
                mm.query(
                    "global",
                    "INSERT INTO cognitive_threads "
                    "(session_id, content, source_exchange_at, importance_score, tags, "
                    " thread_type, depth_score, relevance_score, "
                    " related_thread_id, relation_type, relation_evidence, "
                    " extraction_confidence) "
                    "VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        t["content"],
                        t["importance_score"],
                        t["tags"],
                        t["thread_type"],
                        t["depth_score"],
                        t["relevance_score"],
                        None,  # related_thread_id: will update in pass 2 if needed
                        t["relation_type"],
                        t["relation_evidence"],
                        t["extraction_confidence"],
                    ),
                )
                log.debug(
                    "thread_extractor.stored",
                    thread_type=t["thread_type"],
                    depth_score=t["depth_score"],
                    confidence=t["extraction_confidence"],
                    preview=t["content"][:60],
                )
            except Exception as exc:
                log.warning("thread_extractor.store_error", error=str(exc), exc_type=type(exc).__name__)
        
        # Pass 2: Resolve relations if any thread has related_thread_index
        for i, t in enumerate(threads):
            if t.get("related_thread_index") is not None:
                try:
                    rel_idx = t["related_thread_index"]
                    if 0 <= rel_idx < len(threads) and rel_idx != i:
                        # The related thread is also in this batch
                        # We need to find its ID: assume threads are inserted in order,
                        # so the N-th thread inserted gets a rowid in sequence.
                        # Query for the most recent N threads for this session
                        recent_threads = mm.query(
                            "global",
                            "SELECT id FROM cognitive_threads "
                            "WHERE session_id = ? "
                            "ORDER BY id DESC "
                            "LIMIT ?",
                            (session_id, len(threads)),
                        )
                        
                        # recent_threads are in DESC order, so reverse to get insertion order
                        if len(recent_threads) == len(threads):
                            thread_ids = [row["id"] for row in reversed(recent_threads)]
                            target_id = thread_ids[rel_idx]
                            current_id = thread_ids[i]
                            
                            # Update the current thread with related_thread_id
                            mm.query(
                                "global",
                                "UPDATE cognitive_threads SET related_thread_id = ? WHERE id = ?",
                                (target_id, current_id),
                            )
                            log.debug(
                                "thread_extractor.relation_resolved",
                                thread_id=current_id,
                                related_thread_id=target_id,
                                relation_type=t["relation_type"],
                            )
                except Exception as exc:
                    log.warning(
                        "thread_extractor.relation_resolution_error",
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )
