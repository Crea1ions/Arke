"""Arke Rendering Package — deterministic, stable I/O layer.

Public API:
- rendering_spec : Canonical Markdown→ANSI mapping
- markdown_renderer : MarkdownRenderer class for rendering
- rendering_debug : DebugRenderer for debug-mode output
- streaming : StreamingOutputBuffer for single-pass streaming
- input_normalizer : Input normalization & sanitization
"""

from __future__ import annotations

__all__ = [
    "rendering_spec",
    "markdown_renderer",
    "rendering_debug",
    "streaming",
    "input_normalizer",
]
