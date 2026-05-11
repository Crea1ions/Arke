"""
Workspace Commands Registry — Single Source of Truth

CRITICAL: This module is orchestrator-only. Never expose to LLM context.

Defines all workspace-related slash commands, their metadata, and handler resolution.
"""

from typing import Dict, Any, Callable, Optional
from arke.wvs.renderer import WorkspaceViewRenderer


# Single source of truth for workspace commands
WORKSPACE_COMMANDS = {
    "show_workspace": {
        "description": "Visualize entire workspace structure",
        "section": None,  # root overview
        "handler": "render_overview",
    },
    "show_mobile_notes": {
        "description": "Details of mobile-notes (capture layer)",
        "section": "mobile-notes",
        "handler": "render_section",
    },
    "show_code": {
        "description": "Details of code artifacts",
        "section": "code",
        "handler": "render_section",
    },
    "show_projects": {
        "description": "Details of projects/TEMP (structuration layer)",
        "section": "projects",
        "handler": "render_section",
    },
    "show_shared": {
        "description": "Details of shared restitution outputs",
        "section": "shared",
        "handler": "render_section",
    },
    "show_archive": {
        "description": "Archive contents",
        "section": "archive",
        "handler": "render_section",
    },
}


def get_workspace_command_handler(cmd: str) -> Optional[Callable]:
    """
    Resolve a command name to its handler function.
    
    Args:
        cmd: Command name with or without slash (e.g., "SHOW_WORKSPACE" or "/SHOW_WORKSPACE")
        
    Returns:
        Callable handler, or None if command unknown
    """
    # Strip leading slash if present
    cmd_key = cmd.lstrip("/")
    
    if cmd_key not in WORKSPACE_COMMANDS:
        return None
    
    meta = WORKSPACE_COMMANDS[cmd_key]
    renderer = WorkspaceViewRenderer()
    
    if meta["handler"] == "render_overview":
        # root overview command
        return lambda: print(renderer.render_overview())
    elif meta["handler"] == "render_section":
        # section detail command
        section = meta["section"]
        if section is None:
            return None
        return lambda: print(renderer.render_section(section))
    
    return None
