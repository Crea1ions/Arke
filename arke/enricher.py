"""Archè enrichment layer — add metadata to Themelios threads."""

import json
from typing import Any, Dict, Optional, Tuple

import structlog

from arke.schemas.loader import get_validator

log = structlog.get_logger()


class ArkeEnricher:
    """Enriches Themelios threads with Archè metadata.
    
    Key invariant: Enrichment adds metadata ONLY. Initiative text and thread_raw
    are NEVER modified. Enrichment metadata is stored in initiative_log for traceability.
    """

    def __init__(self):
        """Initialize enricher with validator."""
        self.validator = get_validator()

    def enrich(
        self,
        initiative_text: str,
        thread_raw: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        """Enrich a Themelios thread with Archè metadata.

        Args:
            initiative_text: Raw initiative text from generate_soft_reactivation()
            thread_raw: Themelios thread dict (from cognitive_threads DB)
            context: Contextual metadata (may include user_intention, etc.)

        Returns:
            (initiative_text_unchanged, enrichment_dict)
            
        IMPORTANT: initiative_text is returned UNCHANGED. Enrichment adds
        metadata ONLY for traceability in initiative_log.
        """
        enrichment = {}

        # Infer formulation_tone from thread tags (PRIMARY) + age/score (SECONDARY)
        tone, tone_source = self._infer_formulation_tone(thread_raw, context)
        if tone:  # Only add if non-neutral
            enrichment["formulation_tone"] = tone
            enrichment["formulation_tone_source"] = tone_source

        # Add formulation_context if user_intention is present
        if context.get("intention"):
            enrichment["formulation_context"] = (
                f"User intent: {context['intention'][:60]}..."
            )

        # Validate enrichment (permissive: warn only)
        if enrichment:
            self.validator.validate_enrichment(enrichment)

        # INVARIANT: Text is NEVER modified
        return initiative_text, enrichment

    def _infer_formulation_tone(
        self, thread: Dict[str, Any], context: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Infer formulation tone from thread properties.

        Strategy:
        - PRIMARY: Infer from thread TAGS (if present)
        - SECONDARY: Infer from age + score (if tags absent or empty)
        - DEFAULT: None (neutral — no enrichment)

        Returns:
            (tone, source_justification) or (None, None) if neutral
            
        Tone values:
            "curiosité": exploratory, hypothetical, philosophical threads
            "prudence": old threads with low scores (reactivate with caution)
            None: neutral (default, no enrichment)
        """
        tags = thread.get("tags", [])
        
        # Handle tags as JSON string (from DB) or list
        if isinstance(tags, str):
            try:
                tags = json.loads(tags) if tags else []
            except (json.JSONDecodeError, TypeError):
                tags = []

        score = thread.get("score", 0.5)
        days_dormant = thread.get("days_dormant", 0)

        # PRIMARY: Infer from tags
        # Tags like "philosophie", "hypothèse", "paradoxe" → curiosité
        curiosity_tags = {
            "philosophie",
            "hypothèse",
            "paradoxe",
            "question",
            "débat",
            "théorie",
            "spéculation",
            "exploration",
        }
        
        if tags and any(tag.lower() in curiosity_tags for tag in tags):
            matched_tags = [t for t in tags if t.lower() in curiosity_tags]
            return (
                "curiosité",
                f"Tags indiquent exploration: {', '.join(matched_tags[:2])}",
            )

        # SECONDARY: Check age + score → prudence pour threads anciens
        if days_dormant > 20 and score < 0.7:
            return (
                "prudence",
                f"Thread ancien ({days_dormant}d) et score bas ({score:.2f})",
            )

        # DEFAULT: neutral (no enrichment)
        return (None, None)
