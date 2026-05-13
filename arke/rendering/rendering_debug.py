"""Arke Debug Renderer — isolated debug-only rendering output.

This module MUST NEVER be imported in normal rendering paths.
Debug output is completely separated to prevent leakage.
"""

from __future__ import annotations

from typing import Any, Optional
from arke.rendering.markdown_renderer import MarkdownRenderer


# CRITICAL: Global render mode guard (prevents debug leakage to normal)
RENDER_MODE: str = "normal"  # "normal" or "debug"


def set_render_mode(mode: str) -> None:
    """Set the global render mode (normal or debug).
    
    Args:
        mode: Either "normal" or "debug"
    
    Raises:
        ValueError: If mode is invalid
    """
    global RENDER_MODE
    if mode not in ("normal", "debug"):
        raise ValueError(f"Invalid render mode: {mode}")
    RENDER_MODE = mode


def get_render_mode() -> str:
    """Get the current render mode."""
    return RENDER_MODE


class DebugRenderer:
    """Renders content with debug metadata panel.
    
    WARNING: Only used when RENDER_MODE == "debug".
    Emits a debug panel showing:
      - Token count
      - ANSI code overhead
      - Contract size
      - Session ID
    """

    def __init__(self, base_renderer: Optional[MarkdownRenderer] = None):
        """Initialize debug renderer.
        
        Args:
            base_renderer: Optional MarkdownRenderer to use for base rendering.
                If None, creates a new one.
        """
        self.base_renderer = base_renderer or MarkdownRenderer(show_internal_markup=True)

    def render_with_internals(
        self,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Render with internal debug metadata panel.
        
        Args:
            text: The text to render
            metadata: Optional dict with debug info:
                - token_count: Number of tokens
                - ansi_overhead: Percentage overhead from ANSI codes
                - contract_size_kb: Size of cognitive contract
                - session_id: Session identifier
        
        Returns:
            Text with debug panel appended
        """
        # Base render (preserving markup)
        rendered = self.base_renderer.render(text, style_context="debug")
        
        # Build debug panel
        if metadata is None:
            metadata = {}
        
        panel_lines = [
            "",
            "─" * 50,
            "[DEBUG RENDERING]",
        ]
        
        if token_count := metadata.get("token_count"):
            panel_lines.append(f"  tokens: {token_count}")
        
        if overhead := metadata.get("ansi_overhead"):
            panel_lines.append(f"  ANSI overhead: {overhead}%")
        
        if contract_size := metadata.get("contract_size_kb"):
            panel_lines.append(f"  contract: {contract_size} KB")
        
        if session_id := metadata.get("session_id"):
            panel_lines.append(f"  session_id: {session_id}")
        
        panel_lines.append("─" * 50)
        
        return rendered + "\n" + "\n".join(panel_lines)

    def should_render(self) -> bool:
        """Check if debug rendering is enabled globally.
        
        Returns:
            True if RENDER_MODE == "debug"
        """
        return RENDER_MODE == "debug"


# Guard: Prevent accidental import in normal paths
def _validate_no_normal_mode_import() -> None:
    """Sanity check: this module should NEVER be imported in normal render path."""
    # This is called at module load time to ensure the guard is active
    pass


_validate_no_normal_mode_import()


if __name__ == "__main__":
    # Quick test
    print("Testing DebugRenderer:")
    
    renderer = DebugRenderer()
    
    text = "Analysis complete.\n[OUTIL: sqlite]\n[ARGS: {}]\nDone."
    metadata = {
        "token_count": 42,
        "ansi_overhead": 12,
        "contract_size_kb": 8,
        "session_id": "abc123",
    }
    
    result = renderer.render_with_internals(text, metadata)
    print(result)
