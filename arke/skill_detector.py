"""SkillDetector — detects repetitive usage patterns and proposes new skills.

A *pattern* is a ``(tool_name, intention_bucket)`` pair that has been recorded
at least :data:`PATTERN_THRESHOLD` times.  When a new pattern is detected and
no matching skill already exists, :meth:`SkillDetector.detect_new` returns
:class:`SkillTemplate` objects for the caller to activate.

Bucket normalisation
--------------------
The intention is lowercased, stripped of stop-words, and the first
:data:`BUCKET_WORDS` non-stop-words are joined to form the bucket key.  This
ensures that ``"Analyse logs nginx"`` and ``"analyse les logs nginx"`` map to
the same bucket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arke.memory.manager import MemoryManager

#: Minimum occurrences before a (tool, bucket) pair becomes a skill candidate.
PATTERN_THRESHOLD: int = 5

#: Number of significant words retained when building a bucket key.
BUCKET_WORDS: int = 4

_STOP_WORDS: frozenset[str] = frozenset(
    {
        # French
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "en",
        "au", "aux", "par", "sur", "dans", "avec", "pour", "que", "qui",
        "est", "sont", "a", "je", "tu", "il", "on", "nous",
        # English
        "the", "an", "of", "in", "on", "at", "to", "for", "is", "are",
        "and", "or", "from", "with", "this", "that", "it",
    }
)


@dataclass
class SkillTemplate:
    """A proposed skill generated from a detected usage pattern.

    Attributes:
        name: Suggested skill name (slug form of the bucket).
        description: Human-readable description shown to the user.
        prompt_template: Pre-filled system prompt for LLM-assisted calls.
        tool: Primary tool the skill delegates to.
        trigger_count: Number of pattern occurrences that triggered detection.
        bucket: Normalised intention bucket that was matched.
    """

    name: str
    description: str
    prompt_template: str
    tool: str
    trigger_count: int
    bucket: str


class SkillDetector:
    """Records intention–tool pairs and detects reusable patterns.

    Args:
        memory: Optional :class:`~arke.memory.manager.MemoryManager`.
            Created lazily if *None*.
        threshold: Minimum occurrences before a pattern is proposed.
            Defaults to :data:`PATTERN_THRESHOLD`.
    """

    def __init__(
        self,
        memory: MemoryManager | None = None,
        threshold: int = PATTERN_THRESHOLD,
    ) -> None:
        if memory is None:
            from arke.memory.manager import MemoryManager as _MM  # lazy

            memory = _MM()
        self._mem = memory
        self._threshold = threshold

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, tool_name: str, intention: str) -> None:
        """Persist one ``(tool, bucket)`` observation to ``pattern_log``.

        Args:
            tool_name: The tool that was used (``'cli'``, ``'fs'``, …).
            intention: The raw task description or user intention string.
        """
        bucket = _make_bucket(intention)
        self._mem.query(
            "global",
            "INSERT INTO pattern_log (tool_name, bucket) VALUES (?, ?)",
            (tool_name, bucket),
        )

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_new(self) -> list[SkillTemplate]:
        """Return :class:`SkillTemplate` objects for patterns not yet skilled.

        A pattern qualifies when its occurrence count >= threshold **and** no
        row in ``skills`` already has the same ``tool`` and ``name`` (derived
        from the bucket slug).

        Returns:
            List of proposed :class:`SkillTemplate` objects (may be empty).
        """
        rows = self._mem.query(
            "global",
            """
            SELECT p.tool_name, p.bucket, COUNT(*) AS cnt
            FROM pattern_log p
            WHERE NOT EXISTS (
                SELECT 1 FROM skills s
                WHERE s.tool = p.tool_name
                  AND s.name = REPLACE(p.bucket, ' ', '-')
            )
            GROUP BY p.tool_name, p.bucket
            HAVING COUNT(*) >= ?
            ORDER BY cnt DESC
            """,
            (self._threshold,),
        )
        return [
            _make_template(row["tool_name"], row["bucket"], row["cnt"])
            for row in rows
        ]


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _make_bucket(intention: str) -> str:
    """Normalise an intention string into a short bucket key.

    Strips punctuation, lowercases, removes stop-words, and keeps only the
    first :data:`BUCKET_WORDS` significant words.

    Args:
        intention: Raw intention string.

    Returns:
        Space-joined string of at most :data:`BUCKET_WORDS` significant words.
    """
    cleaned = re.sub(r"[^a-z\xc0-\u017e\s]", "", intention.lower())
    words = cleaned.split()
    significant = [w for w in words if w not in _STOP_WORDS]
    return " ".join(significant[:BUCKET_WORDS])


def _make_template(tool_name: str, bucket: str, count: int) -> SkillTemplate:
    """Build a :class:`SkillTemplate` from a detected pattern.

    Args:
        tool_name: Tool identifier.
        bucket: Normalised intention bucket key.
        count: Number of observed occurrences.

    Returns:
        Populated :class:`SkillTemplate`.
    """
    slug = re.sub(r"\s+", "-", bucket.strip())
    return SkillTemplate(
        name=slug,
        description=(
            f"Skill auto-détecté : {bucket!r} via {tool_name} ({count}\u00d7)"
        ),
        prompt_template=(
            f"Tu es un assistant spécialisé dans : {bucket}.\n"
            f"Utilise l'outil {tool_name} pour répondre précisément."
        ),
        tool=tool_name,
        trigger_count=count,
        bucket=bucket,
    )
