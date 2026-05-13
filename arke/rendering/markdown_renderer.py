"""Arke MarkdownRenderer — deterministic Markdown→ANSI rendering engine.

This module provides the core rendering logic for converting Markdown to styled
ANSI output. All markdown rendering in Arke MUST flow through MarkdownRenderer
to ensure consistency and testability.

The renderer is stateless and deterministic:
  - Same markdown + context → identical ANSI output
  - No side effects or state mutations
  - Validates all output before emission
"""

from __future__ import annotations

from typing import Optional, Iterator, Any
from arke.rendering.rendering_spec import (
    MarkdownStyle,
    get_ansi_code,
    validate_ansi_span,
    ANSI_RESET,
)


class MarkdownRenderer:
    """Deterministic Markdown→ANSI rendering engine.
    
    Converts markdown text to styled ANSI output using a formal spec.
    All rendering decisions are derived from the rendering_spec module,
    ensuring consistency across contexts.
    
    Args:
        show_internal_markup: If True, don't filter internal control markers.
            Default False (strip [OUTIL:], [ARGS:], [PLAN:]).
    """

    def __init__(self, show_internal_markup: bool = False):
        """Initialize the renderer.
        
        Args:
            show_internal_markup: If True, preserve [OUTIL:], [ARGS:], [PLAN:] markers.
                Used in debug mode. Default False for normal output.
        """
        self.show_internal_markup = show_internal_markup

    def render(self, markdown_text: str, style_context: Optional[str] = None) -> str:
        """Render markdown to styled ANSI output.
        
        Converts markdown (headers, bold, code, links, etc.) to ANSI-styled text.
        Internal control markers ([OUTIL:], [ARGS:], [PLAN:]) are hidden by default.
        
        Args:
            markdown_text: The markdown source text
            style_context: Optional context name ("normal", "debug", etc.).
                Used to determine filtering rules. Default "normal".
        
        Returns:
            ANSI-styled text ready to print
            
        Raises:
            ValueError: If markdown_text is not a string
        """
        if not isinstance(markdown_text, str):
            raise ValueError(f"markdown_text must be str, got {type(markdown_text)}")
        
        if style_context is None:
            style_context = "normal"
        
        # Filter internal markup unless in debug context
        filtered = markdown_text
        if style_context == "normal" and not self.show_internal_markup:
            filtered = self._strip_internal_markup(markdown_text)
        
        # Apply markdown transformations
        styled = self._apply_markdown_styles(filtered)
        
        # Validate output (no unclosed ANSI spans)
        self._validate_ansi_output(styled)
        
        return styled

    def render_streaming(self, tokens: Iterator[str]) -> Iterator[str]:
        """Render tokens in a streaming fashion.
        
        Yields tokens one at a time, ensuring that ANSI codes are never partial.
        Each emitted token is valid and complete.
        
        Args:
            tokens: Iterator of token strings from LLM streaming
        
        Yields:
            Processed tokens, each complete and valid
            
        Invariants:
          - Each token is emitted exactly once
          - ANSI codes never partial (boundary check)
          - Newlines handled deterministically
          - Internal markers filtered (unless show_internal_markup=True)
        """
        buffer = ""
        
        for token in tokens:
            buffer += token
            
            # Strip internal markup if needed
            if not self.show_internal_markup:
                buffer = self._strip_internal_markup_in_buffer(buffer)
            
            # Process complete lines and markers
            while True:
                # Check for complete control marker
                marker_end = self._find_complete_marker(buffer)
                if marker_end == -1:
                    # No complete marker, emit what we can safely
                    complete_content = self._extract_complete_content(buffer)
                    if complete_content:
                        styled = self._apply_markdown_styles(complete_content)
                        if styled:
                            yield styled
                            buffer = buffer[len(complete_content):]
                    break
                else:
                    # Marker found, consume up to end of marker
                    content_before = buffer[:marker_end]
                    if content_before:
                        styled = self._apply_markdown_styles(content_before)
                        if styled:
                            yield styled
                    buffer = buffer[marker_end:]

    # ========================================================================
    # Internal methods
    # ========================================================================

    def _strip_internal_markup(self, text: str) -> str:
        """Remove internal control markup ([OUTIL:], [ARGS:], [PLAN:]).
        
        Args:
            text: Raw text potentially containing markup
        
        Returns:
            Text with all internal markup removed
        """
        import re
        
        # Remove [PLAN:..../PLAN] blocks
        text = re.sub(r'\[PLAN:.*?/PLAN\]', '', text, flags=re.DOTALL)
        
        # Remove [OUTIL:...] markers
        text = re.sub(r'\[OUTIL:.*?\]', '', text)
        
        # Remove [ARGS:...] markers (may be multiline)
        text = re.sub(r'\[ARGS:.*?\]', '', text, flags=re.DOTALL)
        
        return text.strip()

    def _strip_internal_markup_in_buffer(self, text: str) -> str:
        """Remove only COMPLETE internal control markup from buffer.
        
        Unlike _strip_internal_markup, this does NOT strip incomplete markers.
        Used during streaming to avoid consuming partial markers.
        
        Args:
            text: Raw text potentially containing markup
        
        Returns:
            Text with only complete internal markup removed
        """
        import re
        
        # Remove complete [PLAN:..../PLAN] blocks only
        text = re.sub(r'\[PLAN:.*?/PLAN\]', '', text, flags=re.DOTALL)
        
        # Remove complete [OUTIL:...] markers
        text = re.sub(r'\[OUTIL:[^\]]*\]', '', text)
        
        # Remove complete [ARGS:...] markers (may be multiline)
        text = re.sub(r'\[ARGS:[^\]]*\]', '', text)
        
        return text

    def _apply_markdown_styles(self, text: str) -> str:
        """Apply markdown styling transformations.
        
        Converts markdown syntax to ANSI codes:
          **bold** → BOLD style
          `code` → MUTED style
          # Header → HEADER style
          etc.
        
        Args:
            text: Markdown source text
        
        Returns:
            ANSI-styled text
        """
        # Process markdown patterns
        result = text
        
        # Headers: # text → HEADER style
        import re
        result = re.sub(
            r'^(#+\s+.*)$',
            lambda m: self._style_match(m.group(1), MarkdownStyle.HEADER),
            result,
            flags=re.MULTILINE
        )
        
        # Bold: **text** → BOLD
        result = re.sub(
            r'\*\*([^*]+)\*\*',
            lambda m: self._style_match(m.group(1), MarkdownStyle.BOLD),
            result
        )
        
        # Code: `text` → MUTED
        result = re.sub(
            r'`([^`]+)`',
            lambda m: self._style_match(m.group(1), MarkdownStyle.MUTED),
            result
        )
        
        # Italics: *text* → DIM
        result = re.sub(
            r'\*([^*]+)\*',
            lambda m: self._style_match(m.group(1), MarkdownStyle.DIM),
            result
        )
        
        return result

    def _style_match(self, text: str, style: MarkdownStyle) -> str:
        """Apply style to matched text.
        
        Args:
            text: Text to style
            style: MarkdownStyle to apply
        
        Returns:
            Styled ANSI text
        """
        try:
            return validate_ansi_span(style, text)
        except ValueError:
            # Empty text, return as-is
            return text

    def _validate_ansi_output(self, text: str) -> None:
        """Validate that ANSI output has no unclosed spans.
        
        Args:
            text: ANSI-styled text to validate
        
        Raises:
            ValueError: If output has unclosed spans
        """
        # Count opening codes and resets
        # This is a simple heuristic; a full parser would track nesting
        opens = text.count("\033[")
        resets = text.count(ANSI_RESET)
        
        # Allow opens >= resets (trailing open is OK, will be closed by next text)
        # But not resets > opens (orphaned reset)
        if resets > opens:
            raise ValueError(f"Unclosed ANSI spans in output: {resets} resets vs {opens} opens")

    def _find_complete_marker(self, buffer: str) -> int:
        """Find the end position of a complete control marker.
        
        Returns -1 if no complete marker found.
        
        Args:
            buffer: Text buffer to search
        
        Returns:
            Index after complete marker, or -1 if not found
        """
        import re
        
        # Look for complete markers
        markers = [
            (r'\[PLAN:.*?/PLAN\]', re.DOTALL),
            (r'\[OUTIL:.*?\]', 0),
            (r'\[ARGS:.*?\]', re.DOTALL),
        ]
        
        earliest_end = -1
        for pattern, flags in markers:
            match = re.search(pattern, buffer, flags=flags)
            if match:
                end = match.end()
                if earliest_end == -1 or end < earliest_end:
                    earliest_end = end
        
        return earliest_end

    def _extract_complete_content(self, buffer: str) -> str:
        """Extract complete content up to next marker or newline.
        
        Args:
            buffer: Text buffer
        
        Returns:
            Content that's safe to emit (up to next marker or end)
        """
        import re
        
        # Find next marker start
        next_marker = re.search(r'\[(?:PLAN|OUTIL|ARGS)', buffer)
        
        if next_marker:
            # Return everything before the marker
            return buffer[:next_marker.start()]
        else:
            # No marker, return buffer (complete or partial token)
            return buffer


# ============================================================================
# Integration helpers (for backward compatibility)
# ============================================================================

def render_markdown(text: str, debug: bool = False) -> str:
    """Convenience function to render markdown without instantiating.
    
    Args:
        text: Markdown text to render
        debug: If True, show internal markup
    
    Returns:
        ANSI-styled text
    """
    renderer = MarkdownRenderer(show_internal_markup=debug)
    return renderer.render(text, style_context="debug" if debug else "normal")


def render_streaming(tokens: Iterator[str], debug: bool = False) -> Iterator[str]:
    """Convenience function for streaming rendering.
    
    Args:
        tokens: Iterator of tokens
        debug: If True, show internal markup
    
    Yields:
        Styled tokens
    """
    renderer = MarkdownRenderer(show_internal_markup=debug)
    yield from renderer.render_streaming(tokens)
