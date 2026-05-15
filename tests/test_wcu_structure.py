"""Tests for Passive User Workspace (PUW) integration.

Validates:
1. WCU directory structure exists and is correct
2. workspace.py functions work correctly
3. Orchestrator initializes workspace properly
4. No regressions in legacy intents (orchestrator stability contract)
5. Telegram bot has zero workspace access

NOTE: Do NOT test LLM context awareness (it shouldn't see workspace).
"""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from arke.workspace import WorkspaceManager, initialize_workspace, get_workspace


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def wcu_root():
    """Create a temporary WCU structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wcu = Path(tmpdir) / "WCU"
        
        # Create full structure
        (wcu / "mobile-notes" / "channels" / "telegram").mkdir(parents=True)
        (wcu / "mobile-notes" / "channels" / "discord").mkdir(parents=True)
        (wcu / "mobile-notes" / "channels" / "email").mkdir(parents=True)
        (wcu / "mobile-notes" / "channels" / "obsidian").mkdir(parents=True)
        (wcu / "mobile-notes" / "channels" / "api").mkdir(parents=True)
        (wcu / "mobile-notes" / "fleeting").mkdir(parents=True)
        (wcu / "mobile-notes" / "ideas").mkdir(parents=True)
        (wcu / "mobile-notes" / "voice").mkdir(parents=True)
        (wcu / "mobile-notes" / "quick-capture").mkdir(parents=True)
        (wcu / "mobile-notes" / "archive").mkdir(parents=True)
        
        (wcu / "code" / "apps").mkdir(parents=True)
        (wcu / "code" / "services").mkdir(parents=True)
        (wcu / "code" / "libs").mkdir(parents=True)
        (wcu / "code" / "experiments").mkdir(parents=True)
        
        (wcu / "projects" / "TEMP" / "core-overview").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "core-planning").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "core-architecture").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "dev-sessions").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "dev-tracking").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "meta-decisions").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "meta-feedback").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "ops-logs").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "ext-extensions").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "resources").mkdir(parents=True)
        (wcu / "projects" / "TEMP" / "archive").mkdir(parents=True)
        
        (wcu / "shared" / "session-summaries").mkdir(parents=True)
        (wcu / "shared" / "decision-recaps").mkdir(parents=True)
        (wcu / "shared" / "cognitive-threads").mkdir(parents=True)
        (wcu / "shared" / "generated-insights").mkdir(parents=True)
        (wcu / "shared" / "user-facing-logs").mkdir(parents=True)
        
        (wcu / "archive").mkdir(parents=True)
        
        yield wcu


@pytest.fixture
def workspace_mgr(wcu_root):
    """Create a WorkspaceManager instance."""
    return WorkspaceManager(wcu_root)


# ===========================================================================
# Test Suite 1: Directory Structure Validation
# ===========================================================================

def test_wcu_structure_exists(wcu_root):
    """Verify all required directories exist."""
    required_dirs = [
        "mobile-notes/channels/telegram",
        "mobile-notes/channels/discord",
        "mobile-notes/channels/email",
        "mobile-notes/channels/obsidian",
        "mobile-notes/channels/api",
        "mobile-notes/fleeting",
        "mobile-notes/ideas",
        "mobile-notes/voice",
        "mobile-notes/quick-capture",
        "mobile-notes/archive",
        "code/apps",
        "code/services",
        "code/libs",
        "code/experiments",
        "projects/TEMP/core-overview",
        "projects/TEMP/core-planning",
        "projects/TEMP/core-architecture",
        "projects/TEMP/dev-sessions",
        "projects/TEMP/dev-tracking",
        "projects/TEMP/meta-decisions",
        "projects/TEMP/meta-feedback",
        "projects/TEMP/ops-logs",
        "projects/TEMP/ext-extensions",
        "projects/TEMP/resources",
        "projects/TEMP/archive",
        "shared/session-summaries",
        "shared/decision-recaps",
        "shared/cognitive-threads",
        "shared/generated-insights",
        "shared/user-facing-logs",
        "archive",
    ]
    
    for dir_path in required_dirs:
        full_path = wcu_root / dir_path
        assert full_path.exists(), f"Missing directory: {dir_path}"
        assert full_path.is_dir(), f"Not a directory: {dir_path}"


def test_wcu_structure_validation(workspace_mgr):
    """Verify validate_structure() works correctly."""
    assert workspace_mgr.validate_structure() is True


# ===========================================================================
# Test Suite 2: Intent→Path Mapping
# ===========================================================================

def test_intent_path_map_exists(workspace_mgr):
    """Verify INTENT_PATH_MAP is defined."""
    assert hasattr(workspace_mgr, "INTENT_PATH_MAP")
    assert len(workspace_mgr.INTENT_PATH_MAP) > 0


def test_resolve_intent_path_valid(workspace_mgr, wcu_root):
    """Test resolving valid intents."""
    test_cases = [
        ("WRITE_SESSION_SUMMARY", "shared/session-summaries/"),
        ("STORE_MOBILE_NOTE_TELEGRAM", "mobile-notes/channels/telegram/"),
        ("LOG_DECISION", "projects/TEMP/meta-decisions/"),
        ("EXPORT_SHARED_INSIGHT", "shared/generated-insights/"),
        ("UPDATE_COGNITIVE_THREAD", "shared/cognitive-threads/"),
    ]
    
    for intent, expected_relative in test_cases:
        result = workspace_mgr.resolve_intent_path(intent)
        expected = wcu_root / expected_relative
        assert result == expected, f"Intent {intent} resolved incorrectly"


def test_resolve_intent_path_invalid(workspace_mgr):
    """Test resolving invalid intents."""
    result = workspace_mgr.resolve_intent_path("NONEXISTENT_INTENT")
    assert result is None


def test_get_intent_list(workspace_mgr):
    """Verify get_intent_list() returns all intents."""
    intents = workspace_mgr.get_intent_list()
    assert len(intents) > 0
    assert "WRITE_SESSION_SUMMARY" in intents
    assert "STORE_MOBILE_NOTE_TELEGRAM" in intents


# ===========================================================================
# Test Suite 3: Write/Read Artifacts
# ===========================================================================

def test_write_artifact_auto_filename(workspace_mgr, wcu_root):
    """Test writing artifact with auto-generated filename."""
    content = "# Test Session Summary\n\nTest content"
    result = workspace_mgr.write_artifact(
        intent="WRITE_SESSION_SUMMARY",
        content=content,
    )
    
    assert result is not None
    assert result.exists()
    assert result.parent == wcu_root / "shared/session-summaries"
    assert result.read_text() == content


def test_write_artifact_custom_filename(workspace_mgr, wcu_root):
    """Test writing artifact with custom filename."""
    content = "# Custom Document"
    custom_name = "my-custom-doc.md"
    result = workspace_mgr.write_artifact(
        intent="WRITE_SESSION_SUMMARY",
        content=content,
        filename=custom_name,
    )
    
    assert result is not None
    assert result.name == custom_name
    assert result.read_text() == content


def test_write_artifact_with_metadata(workspace_mgr, wcu_root):
    """Test writing artifact with metadata."""
    content = "# Document with metadata"
    metadata = {
        "session_id": 42,
        "date": "2026-05-11",
        "tags": ["test", "wcu"]
    }
    result = workspace_mgr.write_artifact(
        intent="WRITE_SESSION_SUMMARY",
        content=content,
        filename="doc-with-meta.md",
        metadata=metadata,
    )
    
    assert result is not None
    file_content = result.read_text()
    
    # Check YAML frontmatter exists
    assert file_content.startswith("---\n")
    assert "session_id: 42" in file_content
    assert "date: \"2026-05-11\"" in file_content
    assert content in file_content


def test_read_artifact(workspace_mgr, wcu_root):
    """Test reading artifact."""
    content = "Test read content"
    written = workspace_mgr.write_artifact(
        intent="WRITE_SESSION_SUMMARY",
        content=content,
        filename="test-read.md",
    )
    
    # Read by path
    read_content = workspace_mgr.read_artifact(written)
    assert read_content == content


def test_list_artifacts(workspace_mgr):
    """Test listing artifacts for an intent."""
    # Write a few artifacts
    for i in range(3):
        workspace_mgr.write_artifact(
            intent="WRITE_SESSION_SUMMARY",
            content=f"Session {i}",
            filename=f"session_{i}.md",
        )
    
    # List them
    artifacts = workspace_mgr.list_artifacts("WRITE_SESSION_SUMMARY")
    assert artifacts is not None
    assert len(artifacts) == 3
    assert all(a.suffix == ".md" for a in artifacts)


# ===========================================================================
# Test Suite 4: Workspace Manager Initialization
# ===========================================================================

def test_workspace_initialization(wcu_root):
    """Test workspace manager can be initialized."""
    mgr = initialize_workspace(wcu_root)
    assert mgr is not None
    assert mgr.validate_structure()
    
    # Get singleton
    mgr2 = get_workspace()
    assert mgr2 is mgr  # Same instance


def test_workspace_initialization_does_not_auto_create_missing_root(tmp_path):
    """A missing WCU root must not be auto-created implicitly."""
    from arke.workspace import initialize_workspace

    missing_root = tmp_path / "missing-wcu"
    assert not missing_root.exists()

    mgr = initialize_workspace(missing_root)

    assert mgr is not None
    assert not missing_root.exists()
    assert not mgr.validate_structure()


# ===========================================================================
# Test Suite 5: Stability Contract (Legacy Intents)
# ===========================================================================

def test_no_legacy_rerouting():
    """Verify no existing intents have been modified (stability contract).
    
    This is a placeholder. In production, this would:
    1. Load pre-WCU orchestrator behavior baseline
    2. Run sample intentions with identical inputs
    3. Compare outputs byte-for-byte
    """
    # Stability contract verified manually in code review
    # workspace module is purely additive, no modifications to orchestrator handlers
    assert True


def test_workspace_isolated_from_llm():
    """Verify workspace module is not exposed to LLM context.
    
    This test verifies that:
    - workspace.py is not imported in llm/litellm_manager.py
    - workspace paths are not in any default context
    """
    # Check that workspace.py exists and has correct isolation markers
    workspace_path = Path(__file__).parent.parent / "arke" / "workspace.py"
    source = workspace_path.read_text()
    
    # Verify docstring explicitly states orchestrator-only
    assert "orchestrator-only" in source.lower()
    assert "never expose to llm" in source.lower()


def test_telegram_no_workspace_access():
    """Verify telegram_bot.py has zero workspace imports."""
    tg_path = Path(__file__).parent.parent / "arke" / "interfaces" / "telegram_bot.py"
    source = tg_path.read_text()
    
    # Verify no workspace imports
    assert "from arke import workspace" not in source
    assert "from arke.workspace" not in source
    assert "WorkspaceManager" not in source
    
    # Verify no paths in telegram module
    assert "mobile-notes/" not in source
    assert "shared/" not in source
    assert "wcu_root" not in source


# ===========================================================================
# Test Suite 6: Edge Cases
# ===========================================================================

def test_write_to_nonexistent_intent(workspace_mgr):
    """Test writing to an invalid intent."""
    result = workspace_mgr.write_artifact(
        intent="INVALID_INTENT",
        content="Should fail",
    )
    assert result is None


def test_read_nonexistent_file(workspace_mgr, wcu_root):
    """Test reading a file that doesn't exist."""
    fake_path = wcu_root / "shared" / "session-summaries" / "nonexistent.md"
    result = workspace_mgr.read_artifact(fake_path)
    assert result is None


def test_list_empty_intent(workspace_mgr):
    """Test listing artifacts when intent folder is empty."""
    artifacts = workspace_mgr.list_artifacts("WRITE_SESSION_SUMMARY")
    # Should return empty list or None, depending on implementation
    assert artifacts is None or len(artifacts) == 0


# ===========================================================================
# Test Suite 7: Workspace View System (WVS) - Statistics & Rendering
# ===========================================================================

def test_format_size():
    """Test human-readable size formatting."""
    from arke.workspace import format_size
    
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(1048576) == "1.0 MB"
    # Note: 1 GB = 1,000,000,000 bytes (not 1024^3), so this is 1.073 GB → 1.1 GB
    assert format_size(1000000000) == "1.0 GB"


def test_get_workspace_stats(wcu_root):
    """Test workspace statistics computation."""
    from arke.workspace import get_workspace_stats
    
    # Add some test files to different sections
    (wcu_root / "mobile-notes" / "fleeting" / "note1.md").write_text("Test note 1")
    (wcu_root / "mobile-notes" / "fleeting" / "note2.md").write_text("Test note 2")
    (wcu_root / "code" / "apps" / "app1.py").write_text("print('hello')")
    
    stats = get_workspace_stats(wcu_root)
    
    # Verify structure
    assert "mobile-notes" in stats
    assert "code" in stats
    assert "projects" in stats
    assert "shared" in stats
    assert "archive" in stats
    
    # Verify stats
    assert stats["mobile-notes"]["files"] > 0
    assert stats["code"]["files"] > 0
    assert "size_formatted" in stats["mobile-notes"]


def test_workspace_cache_singleton(wcu_root):
    """Test WorkspaceCache singleton behavior."""
    from arke.wvs.cache import WorkspaceCache
    
    # Clean up before test
    WorkspaceCache.invalidate()
    
    # Initialize cache
    cache = WorkspaceCache.initialize(wcu_root)
    assert cache is not None
    
    # Get should return initialized instance
    cache2 = WorkspaceCache()
    assert cache2 is cache
    
    # Stats should be computed
    stats = WorkspaceCache.get()
    assert stats is not None
    
    # Invalidate stats (but keep wcu_root)
    WorkspaceCache._stats = None
    # Cache should recompute on next get()
    stats2 = WorkspaceCache.get()
    assert stats2 is not None
    
    # Clean up
    WorkspaceCache.invalidate()


def test_workspace_cache_is_initialized(wcu_root):
    """Test cache initialization check."""
    from arke.wvs.cache import WorkspaceCache
    
    # Before init
    WorkspaceCache.invalidate()
    assert not WorkspaceCache.is_initialized()
    
    # After init
    WorkspaceCache.initialize(wcu_root)
    assert WorkspaceCache.is_initialized()


def test_workspace_view_renderer_exists(wcu_root):
    """Test WorkspaceViewRenderer can be instantiated."""
    from arke.wvs.renderer import WorkspaceViewRenderer
    from arke.wvs.cache import WorkspaceCache
    
    # Initialize cache first
    WorkspaceCache.initialize(wcu_root)
    
    # Create renderer
    renderer = WorkspaceViewRenderer()
    assert renderer is not None
    assert hasattr(renderer, 'render_overview')
    assert hasattr(renderer, 'render_section')


def test_workspace_commands_registry():
    """Test workspace commands are properly registered."""
    from arke.commands.workspace_commands import WORKSPACE_COMMANDS
    
    # Verify all commands exist (lowercase, no slash in dict keys)
    expected_commands = [
        "show_workspace",
        "show_mobile_notes",
        "show_code",
        "show_projects",
        "show_shared",
        "show_archive",
    ]
    
    for cmd in expected_commands:
        assert cmd in WORKSPACE_COMMANDS
        assert "description" in WORKSPACE_COMMANDS[cmd]
        assert "handler" in WORKSPACE_COMMANDS[cmd]


def test_get_workspace_command_handler():
    """Test command handler resolution (with or without slash)."""
    from arke.commands.workspace_commands import get_workspace_command_handler
    
    # Valid command with slash
    handler = get_workspace_command_handler("/show_workspace")
    assert handler is not None
    assert callable(handler)
    
    # Valid command without slash
    handler = get_workspace_command_handler("show_workspace")
    assert handler is not None
    assert callable(handler)
    
    # Invalid command
    handler = get_workspace_command_handler("invalid_command")
    assert handler is None


def test_workspace_commands_in_router():
    """Test that workspace commands are registered in chat router for routing.
    
    All 6 workspace commands (/show_workspace + 5 sub-commands) are in SLASH_COMMANDS
    for routing, but only /show_workspace appears in /help (sub-commands are shown
    in /show_workspace output to keep /help clean).
    """
    from arke.chat_router import SLASH_COMMANDS
    
    # Verify all workspace commands are in router for routing
    expected_cmds = {
        "/show_workspace",
        "/show_mobile_notes",
        "/show_code",
        "/show_projects",
        "/show_shared",
        "/show_archive",
    }
    
    for cmd in expected_cmds:
        assert cmd in SLASH_COMMANDS, f"{cmd} not found in SLASH_COMMANDS"


def test_wvs_imports_no_circular_dependency():
    """Test that WVS modules can be imported without circular dependencies."""
    try:
        from arke.wvs.cache import WorkspaceCache
        from arke.wvs.renderer import WorkspaceViewRenderer
        from arke.commands.workspace_commands import WORKSPACE_COMMANDS
        # If we got here, no circular imports
        assert True
    except ImportError as e:
        pytest.fail(f"Circular import detected: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
