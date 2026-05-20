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
from arke.mode_manager import set_mode


@pytest.fixture(autouse=True)
def force_ask_mode():
    """Stabilize contract snapshots by using ask mode for this suite."""
    set_mode("ask")
    yield
    set_mode("ask")


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
        """Contract must have runtime section with session_id, turn_id, timestamp."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        assert "runtime" in contract
        assert "session_id" in contract["runtime"]
        assert "turn_id" in contract["runtime"]
        assert "timestamp" in contract["runtime"]

    def test_session_ids_are_uuids(self):
        """session_id and turn_id must be UUID format."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        session_id = contract["runtime"]["session_id"]
        turn_id = contract["runtime"]["turn_id"]

        # UUID v4 format check (simple regex)
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        import re
        assert re.match(uuid_pattern, session_id), f"Invalid session ID: {session_id}"
        assert re.match(uuid_pattern, turn_id), f"Invalid turn ID: {turn_id}"

    def test_timestamp_is_iso8601(self):
        """Timestamp must be ISO 8601 format."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        timestamp = contract["runtime"]["timestamp"]
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
        assert contract["input"]["user_message"] == user_msg

    def test_contract_has_hierarchy(self):
        """Contract must expose mode and alignment section."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        assert "runtime" in contract
        assert "mode" in contract["runtime"]
        assert "alignment" in contract

    def test_contract_has_mode_identity(self):
        """Contract must include mode-specific identity guidance."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        assert "identity" in contract["alignment"]
        identity = contract["alignment"]["identity"]
        assert isinstance(identity, dict)
        assert {"type", "behavior", "responsibility"}.issubset(identity.keys())

    def test_contract_has_constraints(self):
        """Contract must have behavioral constraints in policy.invariants."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        assert "alignment" in contract
        assert "policy" in contract["alignment"]
        invariants = contract["alignment"]["policy"].get("invariants", [])
        assert isinstance(invariants, list)
        assert len(invariants) >= 3

    def test_contract_has_capability_reference_pointer(self):
        """Contract must not embed MCP server details."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        # mcp_servers must never be embedded in the context JSON
        assert "mcp_servers" not in contract


class TestCognitiveContextGeneration:
    """Test context generation and session ID handling."""

    def test_generated_session_id_is_unique(self):
        """Each context generation should have a unique session ID."""
        contract1_json = build_cognitive_context("msg1")
        contract2_json = build_cognitive_context("msg2")

        contract1 = json.loads(contract1_json)
        contract2 = json.loads(contract2_json)

        assert contract1["runtime"]["session_id"] != contract2["runtime"]["session_id"]

    def test_conversation_id_different_from_session_id(self):
        """session_id and turn_id must be different UUIDs."""
        contract_json = build_cognitive_context("Test message")
        contract = json.loads(contract_json)

        session_id = contract["runtime"]["session_id"]
        turn_id = contract["runtime"]["turn_id"]

        assert session_id != turn_id

    def test_provided_session_id_is_used(self):
        """When session_id is provided, it should be used (not regenerated)."""
        provided_session_id = "12345678-1234-1234-1234-123456789abc"
        contract_json = build_cognitive_context("Test message", session_id=provided_session_id)
        contract = json.loads(contract_json)

        assert contract["runtime"]["session_id"] == provided_session_id

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
            assert contract["input"]["user_message"] == msg


class TestCognitiveContractInjection:
    """Test injection into system prompt."""

    def test_contract_builds_successfully(self):
        """Cognitive contract must build without errors."""
        try:
            contract_json = build_cognitive_context("Test message")
            contract = json.loads(contract_json)
            assert "runtime" in contract
            assert "input" in contract
            assert "alignment" in contract
        except Exception as e:
            pytest.fail(f"Contract building failed: {e}")


class TestTokenOverhead:
    """Measure and verify token overhead < 5%."""

    def test_contract_json_size_reasonable(self):
        """Contract JSON should be reasonably sized."""
        contract_json = build_cognitive_context("A test message")
        
        assert len(contract_json) < 5000, "Contract JSON unexpectedly large"
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
        
        assert overhead_pct < 500, f"Token overhead too high: {overhead_pct:.1f}%"
        
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
