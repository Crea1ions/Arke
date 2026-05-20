"""Tests for Themelios-Archè data contract (Session 044).

Tests cover:
1. Themelios thread contract validation (schema)
2. Archè enrichment contract validation (schema + invariants)
3. ArkeEnricher behavior (tone inference, text immutability)
4. Contract enforcement (permissive validation)
"""

import json
from datetime import datetime, timedelta

import pytest

from arke.enricher import ArkeEnricher
from arke.schemas.loader import ContractValidator, get_validator


class TestThreadContract:
    """Validate Themelios thread schema."""

    def test_valid_thread_minimal(self):
        """Thread with only required fields passes validation."""
        validator = get_validator()
        thread = {
            "thread_id": "uuid-123",
            "content": "A discussion about philosophy",
            "score": 0.75,
            "created_at": "2026-05-19T10:00:00Z",
        }
        assert validator.validate_thread(thread)

    def test_valid_thread_full(self):
        """Thread with all contract fields passes validation."""
        validator = get_validator()
        thread = {
            "thread_id": "uuid-123",
            "content": "A discussion about philosophy",
            "summary": "Plato and reality",
            "score": 0.75,
            "days_dormant": 5,
            "density_snapshot": 0.6,
            "context_anchor": "Plato",
            "created_at": "2026-05-19T10:00:00Z",
            "last_activated_at": "2026-05-18T15:30:00Z",
            "tags": ["philosophie", "hypothèse"],
        }
        assert validator.validate_thread(thread)

    def test_invalid_thread_missing_required_thread_id(self):
        """Thread missing required thread_id fails validation."""
        validator = get_validator()
        thread = {
            "content": "A discussion",
            "score": 0.75,
            "created_at": "2026-05-19T10:00:00Z",
        }
        assert not validator.validate_thread(thread)

    def test_invalid_thread_missing_required_score(self):
        """Thread missing required score fails validation."""
        validator = get_validator()
        thread = {
            "thread_id": "uuid-123",
            "content": "A discussion",
            "created_at": "2026-05-19T10:00:00Z",
        }
        assert not validator.validate_thread(thread)

    def test_invalid_thread_score_out_of_range_low(self):
        """Thread with score < 0.05 fails validation."""
        validator = get_validator()
        thread = {
            "thread_id": "uuid-123",
            "content": "A discussion",
            "score": 0.03,  # Below minimum 0.05
            "created_at": "2026-05-19T10:00:00Z",
        }
        assert not validator.validate_thread(thread)

    def test_invalid_thread_score_out_of_range_high(self):
        """Thread with score > 1.0 fails validation."""
        validator = get_validator()
        thread = {
            "thread_id": "uuid-123",
            "content": "A discussion",
            "score": 1.5,  # Above maximum 1.0
            "created_at": "2026-05-19T10:00:00Z",
        }
        assert not validator.validate_thread(thread)


class TestEnrichmentContract:
    """Validate Archè enrichment schema."""

    def test_valid_enrichment_empty(self):
        """Empty enrichment dict passes validation."""
        validator = get_validator()
        enrichment = {}
        assert validator.validate_enrichment(enrichment)

    def test_valid_enrichment_with_tone(self):
        """Enrichment with formulation_tone and source passes validation."""
        validator = get_validator()
        enrichment = {
            "formulation_tone": "curiosité",
            "formulation_tone_source": "Tags: philosophie, hypothèse",
        }
        assert validator.validate_enrichment(enrichment)

    def test_valid_enrichment_all_fields(self):
        """Enrichment with all optional fields passes validation."""
        validator = get_validator()
        enrichment = {
            "formulation_context": "User asked about Plato",
            "formulation_tone": "prudence",
            "formulation_tone_source": "Thread ancient (25d) + score low (0.55)",
        }
        assert validator.validate_enrichment(enrichment)

    def test_invalid_enrichment_tone_not_in_enum(self):
        """Enrichment with invalid tone value fails validation."""
        validator = get_validator()
        enrichment = {
            "formulation_tone": "excited",  # Not in ["neutral", "curiosité", "prudence"]
            "formulation_tone_source": "Invalid source",
        }
        assert not validator.validate_enrichment(enrichment)

    def test_invalid_enrichment_additional_property(self):
        """Enrichment with unknown property fails validation (additionalProperties=false)."""
        validator = get_validator()
        enrichment = {
            "formulation_tone": "curiosité",
            "formulation_tone_source": "Tags: test",
            "unknown_field": "This should not be here",
        }
        assert not validator.validate_enrichment(enrichment)

    def test_contract_version_is_1_0(self):
        """Contract version should be '1.0'."""
        validator = get_validator()
        assert validator.contract_version == "1.0"


class TestArkeEnricher:
    """Test ArkeEnricher layer for enrichment behavior."""

    def test_enrich_infers_curiosite_from_tags(self):
        """Enricher infers 'curiosité' tone from philosophical tags (PRIMARY)."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-1",
            "content": "Discussion about Plato",
            "score": 0.8,
            "tags": ["philosophie", "paradoxe"],
            "days_dormant": 2,
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative text", thread, context)

        assert enrichment.get("formulation_tone") == "curiosité"
        assert "Tags indiquent" in enrichment.get("formulation_tone_source", "")
        assert text == "Initiative text"  # Text UNCHANGED

    def test_enrich_infers_prudence_from_age_and_score(self):
        """Enricher infers 'prudence' from old age + low score (SECONDARY)."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-2",
            "content": "Old discussion",
            "score": 0.6,
            "tags": [],  # No curiosity tags
            "days_dormant": 25,  # Old (> 20d)
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        assert enrichment.get("formulation_tone") == "prudence"
        assert "ancien" in enrichment.get("formulation_tone_source", "")

    def test_enrich_omits_tone_for_neutral_threads(self):
        """Neutral threads (no special tags, young, normal score) → no tone enrichment."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-3",
            "content": "Standard discussion",
            "score": 0.7,
            "tags": ["general"],  # Not a curiosity tag
            "days_dormant": 5,  # Young (< 20d)
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        assert "formulation_tone" not in enrichment
        assert "formulation_tone_source" not in enrichment

    def test_enrich_never_modifies_initiative_text(self):
        """Enrichment NEVER modifies the initiative text (returns it unchanged)."""
        enricher = ArkeEnricher()
        original_text = "Original initiative about AI philosophy"
        thread = {
            "thread_id": "uuid-4",
            "content": "Content",
            "score": 0.8,
            "tags": ["philosophie"],
        }
        context = {"intention": "User wants to discuss epistemology"}

        text, enrichment = enricher.enrich(original_text, thread, context)

        assert text == original_text
        assert enrichment  # But enrichment dict is populated

    def test_enrich_never_modifies_thread_raw(self):
        """Enrichment NEVER modifies the thread_raw dict."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-5",
            "content": "Original content",
            "score": 0.7,
            "tags": ["philosophie"],
        }
        original_thread = thread.copy()

        text, enrichment = enricher.enrich("Text", thread, {})

        assert thread == original_thread

    def test_enrich_adds_formulation_context_from_intention(self):
        """Enricher adds formulation_context when user_intention is in context."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-6",
            "content": "Content",
            "score": 0.7,
            "tags": [],
            "days_dormant": 10,
        }
        context = {"intention": "Discuss epistemology and knowledge"}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        assert "formulation_context" in enrichment
        assert "epistemology" in enrichment["formulation_context"]

    def test_enrich_handles_tags_as_json_string(self):
        """Enricher handles tags stored as JSON string (from DB)."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-7",
            "content": "Content",
            "score": 0.8,
            "tags": json.dumps(["philosophie", "théorie"]),  # Stored as JSON string
            "days_dormant": 2,
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        assert enrichment.get("formulation_tone") == "curiosité"

    def test_enrich_handles_missing_tags(self):
        """Enricher gracefully handles missing or None tags."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-8",
            "content": "Content",
            "score": 0.7,
            "tags": None,  # No tags
            "days_dormant": 10,
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        # Should fall through to SECONDARY logic
        assert "formulation_tone" not in enrichment  # score not low enough

    def test_enrichment_is_validated(self):
        """Enricher validates enrichment dict against schema (permissive)."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-9",
            "content": "Content",
            "score": 0.8,
            "tags": ["philosophie"],  # Will infer curiosité
            "days_dormant": 2,
        }
        context = {}

        text, enrichment = enricher.enrich("Initiative", thread, context)

        # Validation should pass (enrichment is valid per schema)
        validator = get_validator()
        assert validator.validate_enrichment(enrichment)

    def test_enrich_with_empty_context(self):
        """Enricher handles completely empty context gracefully."""
        enricher = ArkeEnricher()
        thread = {
            "thread_id": "uuid-10",
            "content": "Content",
            "score": 0.5,
            "tags": [],
            "days_dormant": 1,
        }
        context = {}

        # Should not raise, should return minimal enrichment
        text, enrichment = enricher.enrich("Initiative", thread, context)
        assert text == "Initiative"


class TestContractInvariants:
    """Test that all contract invariants hold."""

    def test_invariant_no_emotional_fields_in_thread_contract(self):
        """Themelios thread contract contains no emotional or subjective fields."""
        validator = get_validator()
        schema = validator.thread_schema
        
        # Check invariant text
        assert "Aucun champ émotionnel ou subjectif" in schema.get("invariant", "")
        
        # Verify schema does not permit tone, emotion, sentiment fields
        props = schema.get("properties", {})
        emotional_keywords = ["emotion", "sentiment", "tone", "feeling"]
        for key in props.keys():
            assert not any(kw in key.lower() for kw in emotional_keywords)

    def test_invariant_archè_enrichment_strict(self):
        """Archè enrichment contract disallows additional properties."""
        validator = get_validator()
        schema = validator.enrichment_schema
        
        # additionalProperties must be false
        assert schema.get("additionalProperties") is False

    def test_invariant_tone_enum_exhaustive(self):
        """formulation_tone enum is exhaustive for v1.0."""
        validator = get_validator()
        schema = validator.enrichment_schema
        
        tone_enum = (
            schema.get("properties", {})
            .get("formulation_tone", {})
            .get("enum", [])
        )
        
        # Should contain exactly these three tones for v1.0
        expected_tones = ["neutral", "curiosité", "prudence"]
        assert set(tone_enum) == set(expected_tones)

    def test_invariant_tone_source_is_string_not_enum(self):
        """formulation_tone_source is string (no enum), unlike tone."""
        validator = get_validator()
        schema = validator.enrichment_schema
        
        tone_source_schema = (
            schema.get("properties", {})
            .get("formulation_tone_source", {})
        )
        
        assert tone_source_schema.get("type") == "string"
        assert "enum" not in tone_source_schema  # No enum for source

    def test_validator_is_singleton(self):
        """get_validator() returns same instance (singleton pattern)."""
        v1 = get_validator()
        v2 = get_validator()
        assert v1 is v2

    def test_enricher_uses_shared_validator(self):
        """ArkeEnricher uses shared validator instance."""
        enricher1 = ArkeEnricher()
        enricher2 = ArkeEnricher()
        
        # Both should share the same validator instance
        assert enricher1.validator is enricher2.validator
        assert enricher1.validator is get_validator()
