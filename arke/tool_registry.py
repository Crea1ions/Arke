"""
Arke Tool Registry — Informational-only repository of available tools.

This registry is purely descriptive. It tells the agent what tools are available
and their characteristics (level, latency, cost). The registry is injected into
the agent context as-is; it never drives routing logic or system decisions.

The system cannot read this registry to make routing decisions. It exists solely
to inform the agent about its available capabilities.
"""

# Tool Registry — Static at runtime
# Updated only when new tools are added to the system
TOOL_REGISTRY = {
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Level 1 — Local, fast, free, deterministic
    # Direct access to system resources (no LLM, no network)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    "cli": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 50,
        "description": "Command-line interface — run shell commands deterministically"
    },
    
    "fs": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 10,
        "description": "File system operations — read, write, list, delete files"
    },
    
    "sqlite": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 20,
        "description": "SQLite database queries — structured data retrieval"
    },
    
    "memory_fts5": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 15,
        "description": "Full-text search in memory — fast keyword matching"
    },
    
    "memory_write": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 15,
        "description": "Write to memory — agent-controlled storage (was implicit, now explicit)"
    },
    
    "memory_read": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 15,
        "description": "Read from memory — agent-controlled retrieval (was implicit, now explicit)"
    },
    
    "memory_forget": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 15,
        "description": "Delete from memory — agent-controlled erasure (was implicit, now explicit)"
    },
    
    "memory_search": {
        "level": 1,
        "local": True,
        "cost": 0,
        "latency_ms": 20,
        "description": "Search agent learnings — find similar past experiences from agent_learnings table"
    },
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Level 2 — Skills (learned patterns)
    # Deterministic workflows based on patterns detected by skill_detector
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    "skill_local": {
        "level": 2,
        "local": True,
        "cost": 0,
        "latency_ms": 100,
        "description": "Learned skills — workflows executed by orchestrator (agent must request explicitly)"
    },
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Level 3 — Advanced local (vectorial + LLM)
    # Semantic search and language model calls
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    "vector_search": {
        "level": 3,
        "local": True,
        "cost": 0,
        "latency_ms": 200,
        "description": "Semantic search — sqlite-vec embeddings, local semantic matching"
    },
    
    "llm": {
        "level": 3,
        "local": False,
        "cost": 0.001,
        "latency_ms": 800,
        "description": "Language model — external LLM via LiteLLM (fallback for semantic reasoning)"
    },
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Level 4 — External (MCP, rare, peripheral)
    # Model Context Protocol clients for external services
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    "mcp": {
        "level": 4,
        "local": False,
        "cost": 0.01,
        "latency_ms": 2000,
        "description": "Model Context Protocol — external services (periphery, rare)"
    },
}


def get_tool_metadata(tool_name: str) -> dict | None:
    """
    Retrieve metadata for a specific tool.
    
    Args:
        tool_name: Name of the tool (e.g., 'cli', 'fs', 'memory_write')
    
    Returns:
        Tool metadata dict if exists, None otherwise.
    """
    return TOOL_REGISTRY.get(tool_name)


def list_all_tools() -> list[dict]:
    """
    Return all tools sorted by level (ascending).
    
    Returns:
        List of (tool_name, metadata) tuples, sorted by level.
    """
    return sorted(
        TOOL_REGISTRY.items(),
        key=lambda item: item[1]["level"]
    )


def validate_registry() -> bool:
    """
    Validate registry structure.
    
    Ensures:
    - All tools have required fields (level, local, cost, latency_ms)
    - Level ordering is consistent (1 < 2 < 3 < 4)
    - Memory tools (write, read, forget) are present
    
    Returns:
        True if valid, raises ValueError otherwise.
    """
    required_fields = {"level", "local", "cost", "latency_ms"}
    
    for tool_name, metadata in TOOL_REGISTRY.items():
        # Check all required fields present
        if not required_fields.issubset(metadata.keys()):
            raise ValueError(f"Tool '{tool_name}' missing fields: {required_fields - metadata.keys()}")
        
        # Check level is valid
        if metadata["level"] not in {1, 2, 3, 4}:
            raise ValueError(f"Tool '{tool_name}' has invalid level: {metadata['level']}")
    
    # Check memory tools present
    memory_tools = {"memory_write", "memory_read", "memory_forget"}
    if not memory_tools.issubset(TOOL_REGISTRY.keys()):
        raise ValueError(f"Missing memory tools: {memory_tools - TOOL_REGISTRY.keys()}")
    
    # Check level ordering constraint
    levels = [metadata["level"] for metadata in TOOL_REGISTRY.values()]
    if not (min(levels) == 1 and max(levels) == 4):
        raise ValueError(f"Level range invalid: {min(levels)} to {max(levels)} (expected 1-4)")
    
    return True


# Validate at import time
if __name__ != "__main__":
    validate_registry()
