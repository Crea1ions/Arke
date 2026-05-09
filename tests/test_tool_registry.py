"""
Test suite for Arke Tool Registry.

Validates:
- Registry structure (all tools have required fields)
- Level ordering (1 < 2 < 3 < 4)
- Memory tools present (write, read, forget)
- Tool metadata accessibility
"""

import pytest
from arke.tool_registry import (
    TOOL_REGISTRY,
    get_tool_metadata,
    list_all_tools,
    validate_registry,
)


class TestToolRegistryStructure:
    """Verify registry structure and fields."""

    def test_registry_not_empty(self):
        """Registry must contain tools."""
        assert len(TOOL_REGISTRY) > 0

    def test_all_tools_have_required_fields(self):
        """All tools must have level, local, cost, latency_ms."""
        required_fields = {"level", "local", "cost", "latency_ms"}
        
        for tool_name, metadata in TOOL_REGISTRY.items():
            assert required_fields.issubset(metadata.keys()), \
                f"Tool '{tool_name}' missing fields: {required_fields - metadata.keys()}"

    def test_all_levels_valid(self):
        """All tools must have level 1-4."""
        for tool_name, metadata in TOOL_REGISTRY.items():
            assert metadata["level"] in {1, 2, 3, 4}, \
                f"Tool '{tool_name}' has invalid level: {metadata['level']}"

    def test_local_field_is_boolean(self):
        """local field must be boolean."""
        for tool_name, metadata in TOOL_REGISTRY.items():
            assert isinstance(metadata["local"], bool), \
                f"Tool '{tool_name}' has non-boolean 'local': {metadata['local']}"

    def test_cost_is_numeric(self):
        """cost field must be numeric."""
        for tool_name, metadata in TOOL_REGISTRY.items():
            assert isinstance(metadata["cost"], (int, float)), \
                f"Tool '{tool_name}' has non-numeric cost: {metadata['cost']}"

    def test_latency_is_positive_integer(self):
        """latency_ms must be positive integer."""
        for tool_name, metadata in TOOL_REGISTRY.items():
            assert isinstance(metadata["latency_ms"], int) and metadata["latency_ms"] > 0, \
                f"Tool '{tool_name}' has invalid latency: {metadata['latency_ms']}"


class TestLevelOrdering:
    """Verify tool hierarchy levels."""

    def test_level_ordering_constraint(self):
        """Tools must span levels 1-4."""
        levels = set(metadata["level"] for metadata in TOOL_REGISTRY.values())
        assert levels == {1, 2, 3, 4}, f"Expected levels 1-4, got: {levels}"

    def test_level_1_tools_present(self):
        """Level 1 tools must exist."""
        level_1_tools = {name for name, meta in TOOL_REGISTRY.items() if meta["level"] == 1}
        assert len(level_1_tools) > 0, "No level 1 tools found"

    def test_level_2_tools_present(self):
        """Level 2 tools must exist."""
        level_2_tools = {name for name, meta in TOOL_REGISTRY.items() if meta["level"] == 2}
        assert len(level_2_tools) > 0, "No level 2 tools found"

    def test_level_3_tools_present(self):
        """Level 3 tools must exist."""
        level_3_tools = {name for name, meta in TOOL_REGISTRY.items() if meta["level"] == 3}
        assert len(level_3_tools) > 0, "No level 3 tools found"

    def test_level_4_tools_present(self):
        """Level 4 tools must exist."""
        level_4_tools = {name for name, meta in TOOL_REGISTRY.items() if meta["level"] == 4}
        assert len(level_4_tools) > 0, "No level 4 tools found"


class TestMemoryTools:
    """Verify memory tool presence and correctness."""

    def test_memory_write_present(self):
        """memory_write tool must be present."""
        assert "memory_write" in TOOL_REGISTRY, "memory_write tool missing"

    def test_memory_read_present(self):
        """memory_read tool must be present."""
        assert "memory_read" in TOOL_REGISTRY, "memory_read tool missing"

    def test_memory_forget_present(self):
        """memory_forget tool must be present."""
        assert "memory_forget" in TOOL_REGISTRY, "memory_forget tool missing"

    def test_memory_tools_are_level_1(self):
        """Memory tools must be level 1 (fast, local)."""
        assert TOOL_REGISTRY["memory_write"]["level"] == 1
        assert TOOL_REGISTRY["memory_read"]["level"] == 1
        assert TOOL_REGISTRY["memory_forget"]["level"] == 1

    def test_memory_tools_are_local(self):
        """Memory tools must be local (no external calls)."""
        assert TOOL_REGISTRY["memory_write"]["local"] is True
        assert TOOL_REGISTRY["memory_read"]["local"] is True
        assert TOOL_REGISTRY["memory_forget"]["local"] is True

    def test_memory_tools_are_free(self):
        """Memory tools must have zero cost."""
        assert TOOL_REGISTRY["memory_write"]["cost"] == 0
        assert TOOL_REGISTRY["memory_read"]["cost"] == 0
        assert TOOL_REGISTRY["memory_forget"]["cost"] == 0


class TestRegistryHelpers:
    """Test utility functions."""

    def test_get_tool_metadata_existing_tool(self):
        """get_tool_metadata should return metadata for existing tool."""
        metadata = get_tool_metadata("cli")
        assert metadata is not None
        assert metadata["level"] == 1

    def test_get_tool_metadata_nonexistent_tool(self):
        """get_tool_metadata should return None for nonexistent tool."""
        metadata = get_tool_metadata("nonexistent_tool_xyz")
        assert metadata is None

    def test_list_all_tools_sorted_by_level(self):
        """list_all_tools should return tools sorted by level."""
        tools = list_all_tools()
        assert len(tools) == len(TOOL_REGISTRY)
        
        # Verify sorting
        levels = [meta["level"] for name, meta in tools]
        assert levels == sorted(levels), "Tools not sorted by level"

    def test_validate_registry_succeeds(self):
        """validate_registry should pass for valid registry."""
        assert validate_registry() is True


class TestToolCharacteristics:
    """Verify tool characteristics match expectations."""

    def test_level_1_local_and_free(self):
        """Level 1 tools should be local and free."""
        level_1_tools = {name: meta for name, meta in TOOL_REGISTRY.items() if meta["level"] == 1}
        for name, meta in level_1_tools.items():
            assert meta["local"] is True, f"{name} (level 1) is not local"
            assert meta["cost"] == 0, f"{name} (level 1) has non-zero cost"

    def test_mcp_is_level_4(self):
        """MCP tool should be level 4 (external, peripheral)."""
        assert "mcp" in TOOL_REGISTRY
        assert TOOL_REGISTRY["mcp"]["level"] == 4
        assert TOOL_REGISTRY["mcp"]["local"] is False

    def test_llm_is_level_3(self):
        """LLM tool should be level 3 (advanced, external)."""
        assert "llm" in TOOL_REGISTRY
        assert TOOL_REGISTRY["llm"]["level"] == 3
        assert TOOL_REGISTRY["llm"]["local"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
