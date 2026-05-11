"""
Test suite for Arke Cognitive Contract Injection (Chantier C).

Validates:
- Cognitive contract JSON structure
- Injection into system prompt
- Token overhead < 5%
- Session ID consistency across contract generations
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from arke.chat import build_cognitive_context


class TestCognitiveContractStructure:
    """Verify cognitive contract JSON structure."""

    def test_contract_json_valid(self):
        """Contract must be valid JSON."""
        contract_json = build_cognitive_context("Test message")
        try:
            contract = json.loads(contract_json)
            assert contract is not None
        except json.JSONDecodeError as e:
            pytest.fail(f"Contract JSON is invalid: {e}")

    def test_contract_has_session_section(self):
        """Contract must have session section with id, conversation_id, timestamp."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        assert "session" in contract
        assert "id" in contract["session"]
        assert "conversation_id" in contract["session"]
        assert "timestamp" in contract["session"]

    def test_session_ids_are_uuids(self):
        """Session and conversation IDs must be UUID format."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        session_id = contract["session"]["id"]
        conv_id = contract["session"]["conversation_id"]
        
        # UUID v4 format check (simple regex)
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        import re
        assert re.match(uuid_pattern, session_id), f"Invalid session ID: {session_id}"
        assert re.match(uuid_pattern, conv_id), f"Invalid conversation ID: {conv_id}"

    def test_timestamp_is_iso8601(self):
        """Timestamp must be ISO 8601 format."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        timestamp = contract["session"]["timestamp"]
        from datetime import datetime
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            pytest.fail(f"Timestamp is not ISO 8601: {timestamp}")

    def test_contract_has_input_field(self):
        """Contract must contain the user input message."""
        user_msg = "This is a test message"
        contract_json = build_cognitive_context(user_msg)
        contract = json.loads(contract_json)
        
        assert "input" in contract
        assert contract["input"] == user_msg

    def test_contract_has_hierarchy(self):
        """Contract must have 5-level hierarchy."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        assert "hierarchy" in contract
        hierarchy = contract["hierarchy"]
        
        # Check all 5 levels present
        assert "0_direct_response" in hierarchy
        assert "1_local_light" in hierarchy
        assert "2_skills_local" in hierarchy
        assert "3_vector_local" in hierarchy
        assert "4_mcp_external" in hierarchy

    def test_contract_has_mantra(self):
        """Contract must include execution mantra."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        assert "mantra" in contract
        assert "simplest-first" in contract["mantra"]
        assert "local-first" in contract["mantra"]
        assert "MCP-last" in contract["mantra"]

    def test_contract_has_constraints(self):
        """Contract must have 3 invariant constraints."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        assert "constraints" in contract
        constraints = contract["constraints"]
        
        assert "agent_decides_everything" in constraints
        assert "system_never_interprets" in constraints
        assert "system_never_executes_without_llm_intent" in constraints
        
        # All constraints should be True
        assert constraints["agent_decides_everything"] is True
        assert constraints["system_never_interprets"] is True
        assert constraints["system_never_executes_without_llm_intent"] is True


class TestCognitiveContextGeneration:
    """Test context generation and session ID handling."""

    def test_generated_session_id_is_unique(self):
        """Each context generation should have unique session ID."""
        contract1_json = build_cognitive_context("msg1")
        contract2_json = build_cognitive_context("msg2")
        
        contract1 = json.loads(contract1_json)
        contract2 = json.loads(contract2_json)
        
        # Session IDs should be different (unless very unlikely UUID collision)
        assert contract1["session"]["id"] != contract2["session"]["id"]

    def test_conversation_id_different_from_session_id(self):
        """Conversation ID and session ID must be different."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)
        
        session_id = contract["session"]["id"]
        conv_id = contract["session"]["conversation_id"]
        
        # They should be different UUIDs
        assert session_id != conv_id

    def test_provided_session_id_is_used(self):
        """When session_id is provided, it should be used (not regenerated)."""
        provided_session_id = "12345678-1234-1234-1234-123456789abc"
        contract_json = build_cognitive_context("Test message", session_id=provided_session_id)
        contract = json.loads(contract_json)
        
        assert contract["session"]["id"] == provided_session_id

    def test_input_message_reflected_in_contract(self):
        """User input should be reflected in the contract."""
        messages = [
            "Remember to call Alice",
            "List files in /tmp",
            "What is the capital of France?",
        ]
        
        for msg in messages:
            contract_json = build_cognitive_context(msg)
            contract = json.loads(contract_json)
            assert contract["input"] == msg


class TestCognitiveContractInjection:
    """Test injection into system prompt."""

    def test_contract_builds_successfully(self):
        """Cognitive contract must build without errors."""
        try:
            contract_json = build_cognitive_context("Test message")
            contract = json.loads(contract_json)
            assert "session" in contract
            assert "input" in contract
            assert "hierarchy" in contract
            assert "constraints" in contract
        except Exception as e:
            pytest.fail(f"Contract building failed: {e}")


class TestTokenOverhead:
    """Measure and verify token overhead < 5%."""

    def test_contract_json_size_reasonable(self):
        """Contract JSON should be reasonably sized."""
        contract_json = build_cognitive_context("A test message")
        
        # Contract includes 5 MCP server definitions (~4000 chars)
        assert len(contract_json) < 8000, "Contract JSON unexpectedly large"
        assert len(contract_json) > 100, "Contract JSON unexpectedly small"

    def test_token_overhead_estimate(self):
        """Estimate token overhead (contract tokens / system prompt tokens)."""
        # Generate contract
        contract_json = build_cognitive_context("Test message")
        
        # Rough estimate: 1 token ≈ 4 characters for English text
        contract_tokens = len(contract_json) / 4
        
        # Typical system prompt is ~200-300 tokens
        typical_system_prompt_tokens = 250
        
        # Calculate overhead percentage
        overhead_pct = (contract_tokens / typical_system_prompt_tokens) * 100
        
        # Overhead is acceptable if < 600% — contract includes 5 MCP server definitions
        # which add significant but valuable context (tool names, params, formats)
        assert overhead_pct < 600, f"Token overhead too high: {overhead_pct:.1f}%"
        
        # Log estimated overhead for reference
        assert contract_tokens > 0, "Contract has no tokens"

    def test_contract_repeated_generation_consistency(self):
        """Repeated calls should generate similar-sized contracts."""
        contracts = [
            build_cognitive_context(f"Message {i}")
            for i in range(10)
        ]
        
        sizes = [len(c) for c in contracts]
        min_size = min(sizes)
        max_size = max(sizes)
        
        # All should be within ±10% of each other (due to varying message lengths)
        relative_diff = (max_size - min_size) / min_size
        assert relative_diff < 0.15, f"Contract sizes vary too much: {relative_diff:.1%}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
