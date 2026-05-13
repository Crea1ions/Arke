"""Arke Rendering Specification — canonical Markdown→ANSI mapping.

This module defines the single source of truth for all Markdown styling to ANSI
code transformations. All rendering operations MUST use these mappings to ensure
deterministic, consistent output across all contexts.

Key invariants:
  1. Each MarkdownStyle maps to exactly one ANSI code
  2. No inline ANSI construction (all codes defined here)
  3. All spans are validated for correctness before emission
  4. Nested styles are handled via composition, never nesting ANSI codes
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class MarkdownStyle(str, Enum):
    """Canonical markdown styling tokens.
    
    Each style maps to a specific ANSI 4-bit code (no truecolor).
    """

    # Text styles
    BOLD = "bold"
    DIM = "dim"
    ITALIC = "italic"

    # Semantic colors — ANSI 4-bit palette
    TEXT = "text"              # default (no code)
    MUTED = "muted"            # dim secondary text
    ACCENT = "accent"          # bright cyan (Arke identity)
    SUCCESS = "success"        # bright green (success/done)
    WARNING = "warning"        # bright yellow (caution)
    ERROR = "error"            # bright red (failure)
    USER = "user"              # white (user input)
    
    # Structural elements
    BORDER = "border"          # dim structural chrome
    HEADER = "header"          # accent + bold

    # Model-specific colors
    MODEL_FLASH = "model_flash"
    MODEL_CLAUDE = "model_claude"
    MODEL_MISTRAL = "model_mistral"
    MODEL_LOCAL = "model_local"


# ANSI Code Mapping — Single Source of Truth
# All codes are ANSI 4-bit (16-color) — no truecolor
STYLE_TO_ANSI: Final[dict[MarkdownStyle, str]] = {
    # Text styles
    MarkdownStyle.BOLD: "\033[1m",
    MarkdownStyle.DIM: "\033[2m",
    MarkdownStyle.ITALIC: "\033[3m",
    
    # Semantic colors
    MarkdownStyle.TEXT: "",                    # default (no code)
    MarkdownStyle.MUTED: "\033[2m",            # dim (code 2)
    MarkdownStyle.ACCENT: "\033[96m",          # bright cyan
    MarkdownStyle.SUCCESS: "\033[92m",         # bright green
    MarkdownStyle.WARNING: "\033[93m",         # bright yellow
    MarkdownStyle.ERROR: "\033[91m",           # bright red
    MarkdownStyle.USER: "\033[37m",            # white
    
    # Structural
    MarkdownStyle.BORDER: "\033[2m",           # dim
    MarkdownStyle.HEADER: "\033[1m\033[96m",   # bold + bright cyan
    
    # Model colors
    MarkdownStyle.MODEL_FLASH: "\033[96m",     # bright cyan
    MarkdownStyle.MODEL_CLAUDE: "\033[95m",    # bright magenta
    MarkdownStyle.MODEL_MISTRAL: "\033[92m",   # bright green
    MarkdownStyle.MODEL_LOCAL: "\033[33m",     # yellow
}

# ANSI Reset Code — restores terminal to default state
ANSI_RESET: Final[str] = "\033[0m"

# Helper: NO_COLOR environment support
import os
_NO_COLOR: Final[bool] = (
    os.environ.get("NO_COLOR") is not None
    or os.environ.get("TERM") == "dumb"
)


def get_ansi_code(style: MarkdownStyle) -> str:
    """Get the ANSI code for a given style.
    
    If NO_COLOR is set, returns empty string (respects user preference).
    
    Args:
        style: The MarkdownStyle to retrieve
    
    Returns:
        ANSI escape code (e.g., "\\033[96m") or empty string if NO_COLOR
    
    Raises:
        KeyError: If style is not in STYLE_TO_ANSI
    """
    if _NO_COLOR:
        return ""
    return STYLE_TO_ANSI[style]


def validate_ansi_span(style: MarkdownStyle, text: str) -> str:
    """Validate and return a properly formatted ANSI span.
    
    Ensures that the emitted ANSI code is closed by ANSI_RESET.
    
    Args:
        style: The style to apply
        text: The text to style
    
    Returns:
        Text wrapped with ANSI code and reset (e.g., "\\033[1mHello\\033[0m")
    
    Raises:
        ValueError: If text is empty (no point styling nothing)
    """
    if not text:
        raise ValueError("Cannot create span for empty text")
    
    code = get_ansi_code(style)
    if not code:  # NO_COLOR mode
        return text
    
    return f"{code}{text}{ANSI_RESET}"


def style_text(text: str, *styles: MarkdownStyle) -> str:
    """Apply multiple styles to text (composition).
    
    Applies styles in order, each wrapping the previous result.
    Example: style_text("bold cyan", MarkdownStyle.BOLD, MarkdownStyle.ACCENT)
    
    Args:
        text: The text to style
        *styles: MarkdownStyle enums to apply in order
    
    Returns:
        Text with all styles applied
    """
    result = text
    for style in styles:
        try:
            result = validate_ansi_span(style, result)
        except ValueError:
            # If NO_COLOR mode, skip and continue
            pass
    return result


# Model color helper (backward compatibility)
def model_color(alias: str) -> str:
    """Get ANSI color for a model alias.
    
    Args:
        alias: Model name (flash, claude, mistral, local, pro, etc.)
    
    Returns:
        ANSI code for the model's color
    """
    model_styles = {
        "flash": MarkdownStyle.MODEL_FLASH,
        "claude": MarkdownStyle.MODEL_CLAUDE,
        "mistral": MarkdownStyle.MODEL_MISTRAL,
        "local": MarkdownStyle.MODEL_LOCAL,
        "pro": MarkdownStyle.MODEL_LOCAL,
    }
    style = model_styles.get(alias, MarkdownStyle.ACCENT)
    return get_ansi_code(style)


if __name__ == "__main__":
    # Quick validation script
    print("Arke Rendering Specification")
    print("=" * 50)
    print(f"Total styles: {len(MarkdownStyle)}")
    print(f"Total ANSI mappings: {len(STYLE_TO_ANSI)}")
    print(f"NO_COLOR mode: {_NO_COLOR}")
    print()
    print("Sample styles:")
    for style in [MarkdownStyle.BOLD, MarkdownStyle.ACCENT, MarkdownStyle.ERROR]:
        code = get_ansi_code(style)
        print(f"  {style.value:20} → {repr(code)}")
    print()
    print("Sample span:")
    span = validate_ansi_span(MarkdownStyle.SUCCESS, "Success!")
    print(f"  {repr(span)}")
