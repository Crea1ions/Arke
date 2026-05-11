"""ChatRouter — dispatch des entrées utilisateur vers les 4 modes du REPL.

Modes
-----
* **slash**   : ``/help``, ``/stats``, ``/skills``, ``/config``, ``/check``,
                ``/clear``, ``/exit`` — action directe, sans LLM.
* **model**   : ``@flash``, ``@claude``, ``@mistral``, ``@local`` en début de
                ligne — override du modèle pour cette requête uniquement.
* **memory**  : phrases clés françaises/anglaises pour écrire ou lire
                ``session_context``.
* **task**    : tout le reste → ``orchestrator.run()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

# ---------------------------------------------------------------------------
# Model aliases — @alias → litellm model string
# ---------------------------------------------------------------------------

MODEL_ALIASES: dict[str, str] = {
    "flash":   "gemini/gemini-2.0-flash",
    "claude":  "anthropic/claude-sonnet-4-5",
    "mistral": "mistral/mistral-large-latest",
    "local":   "ollama/mistral",
}

# ---------------------------------------------------------------------------
# Slash commands registry
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/help":   "Affiche cette aide",
    "/stats":  "Statistiques d'usage + scores des skills",
    "/skills": "Liste les skills actifs",
    "/skill":  "Génère une skill à partir des apprentissages récents (distillation)",
    "/status": "État réel du système (bases, skills, mémoire, providers)",
    "/config": "Configuration interactive (LLM, télémétrie, sandbox, vectoriel)",
    "/check":  "Vérifie l'état de chaque composant (providers, bwrap, sqlite-vec, OTel)",
    "/model":  "Sélecteur de modèle LLM interactif",
    "/memory": "Affiche les notes mémorisées de la session",
    "/about":  "À propos d'Arke (architecture, philosophie)",
    "/clear":  "Efface l'historique de session",
    "/exit":   "Quitter Arke Chat",
    "/threads":            "Liste les fils cognitifs actifs",
    "/drop-thread":        "Abandonne un fil cognitif (/drop-thread <id>)",
    "/pause-initiatives":  "Suspend les initiatives cognitive (/pause-initiatives [heures])",
    "/resume-initiatives": "Réactive les initiatives cognitives",
}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class RouteKind(Enum):
    SLASH = auto()
    MODEL_OVERRIDE = auto()
    LLM_AGENT = auto()  # Agent-first: all non-slash/@ messages go to agent via orchestrator


@dataclass
class RouteResult:
    """Routing decision returned by :func:`route`."""

    kind: RouteKind
    #: The slash command (e.g. ``"/help"``) or None.
    slash: str | None = None
    #: Cleaned intention text (slash and @alias stripped).
    intention: str = ""
    #: Model alias key (e.g. ``"flash"``) or None.
    model_alias: str | None = None
    #: Resolved litellm model string, or None.
    model_id: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def route(raw: str) -> RouteResult:
    """Classify *raw* user input and return a :class:`RouteResult`.

    Args:
        raw: Stripped user input from the REPL prompt.

    Returns:
        Routing decision.  Never raises.
    """
    text = raw.strip()

    # --- Slash command -------------------------------------------------------
    first_word = text.split()[0].lower() if text.split() else ""
    if first_word in SLASH_COMMANDS:
        return RouteResult(kind=RouteKind.SLASH, slash=first_word, intention=text)

    # --- @model override -------------------------------------------------------
    model_alias: str | None = None
    model_id: str | None = None
    if text.startswith("@"):
        parts = text.split(None, 1)
        alias = parts[0][1:].lower()
        if alias in MODEL_ALIASES:
            model_alias = alias
            model_id = MODEL_ALIASES[alias]
            text = parts[1].strip() if len(parts) > 1 else ""
            return RouteResult(
                kind=RouteKind.MODEL_OVERRIDE,
                intention=text,
                model_alias=model_alias,
                model_id=model_id,
            )

    # --- Everything else → Agent (agent-first principle) ---------------------
    # System never interprets intent. Agent sees full message and decides.
    return RouteResult(
        kind=RouteKind.LLM_AGENT,
        intention=text,
        model_alias=model_alias,
        model_id=model_id,
    )


# ---------------------------------------------------------------------------
# Session memory helpers
# ---------------------------------------------------------------------------

# Stop words removed before keyword matching in memory queries
_MEMORY_STOP_WORDS: frozenset[str] = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "ce", "cet",
    "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa",
    "ses", "notre", "votre", "leur", "que", "qui", "quoi", "dont", "ou",
    "et", "en", "sur", "sous", "dans", "par", "pour", "avec", "sans",
    "est", "sont", "a", "au", "aux", "me", "moi", "se", "si", "lui", "y",
    "the", "a", "an", "of", "in", "at", "to", "what", "is", "my", "i", "it",
})


def _memory_keywords(text: str) -> list[str]:
    """Return significant tokens (len ≥ 2, not stop words) from *text*."""
    return [
        w.strip("\"'.,!?;:")
        for w in text.lower().split()
        if w.strip("\"'.,!?;:") not in _MEMORY_STOP_WORDS
        and len(w.strip("\"'.,!?;:")) >= 2
    ]


def memory_write(mm: MemoryManager, content: str) -> None:
    """Append *content* to ``session_context`` (key ``chat_notes``)."""
    rows = mm.query("session", "SELECT value FROM session_context WHERE key = 'chat_notes'", ())
    existing = rows[0]["value"] if rows else ""
    new_value = f"{existing}\n- {content}".strip()
    mm.query(
        "session",
        "INSERT OR REPLACE INTO session_context (key, value, ttl) VALUES ('chat_notes', ?, NULL)",
        (new_value,),
    )


def memory_read(mm: MemoryManager, query: str) -> str:
    """Return stored notes from ``session_context``.

    If *query* is empty, returns all notes.  Otherwise returns notes whose
    lines contain at least one significant keyword from *query* (tolerant
    matching — handles paraphrasing such as "le nom du serveur" vs the stored
    note "le serveur s'appelle titan").
    """
    rows = mm.query("session", "SELECT value FROM session_context WHERE key = 'chat_notes'", ())
    if not rows:
        return ""
    notes: str = rows[0]["value"] or ""
    if not query:
        return notes
    kws = _memory_keywords(query)
    if not kws:
        return notes
    matched = [line for line in notes.splitlines() if any(kw in line.lower() for kw in kws)]
    return "\n".join(matched)


def memory_forget(mm: MemoryManager, target: str) -> int:
    """Clear session memory.

    * If *target* is empty: delete all ``chat_notes`` and ``chat_history``.
    * If *target* has keywords: remove lines that contain any significant
      keyword from *target* (tolerant matching, handles paraphrasing).

    Returns:
        Number of items removed.
    """
    if not target:
        mm.query("session", "DELETE FROM session_context WHERE key = 'chat_notes'", ())
        rows = mm.query("session", "SELECT COUNT(*) AS n FROM chat_history", ())
        count = rows[0]["n"] if rows else 0
        mm.query("session", "DELETE FROM chat_history", ())
        return count + 1

    rows = mm.query("session", "SELECT value FROM session_context WHERE key = 'chat_notes'", ())
    if not rows:
        return 0
    notes: str = rows[0]["value"] or ""
    before = notes.splitlines()
    kws = _memory_keywords(target)
    if kws:
        after = [line for line in before if not any(kw in line.lower() for kw in kws)]
    else:
        after = [line for line in before if target.lower() not in line.lower()]
    removed = len(before) - len(after)
    mm.query(
        "session",
        "INSERT OR REPLACE INTO session_context (key, value, ttl) VALUES ('chat_notes', ?, NULL)",
        ("\n".join(after),),
    )
    return removed


def history_append(mm: MemoryManager, role: str, content: str, model_used: str | None = None) -> None:
    """Append a message to ``chat_history``."""
    mm.query(
        "session",
        "INSERT INTO chat_history (role, content, model_used) VALUES (?, ?, ?)",
        (role, content, model_used),
    )


def history_recent(mm: MemoryManager, n: int = 5) -> list[dict]:
    """Return the *n* most recent messages from ``chat_history``."""
    rows = mm.query(
        "session",
        "SELECT role, content, model_used, timestamp FROM chat_history ORDER BY id DESC LIMIT ?",
        (n,),
    )
    return [dict(r) for r in reversed(rows)]
