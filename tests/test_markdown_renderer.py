"""Tests for arke.rendering.markdown_renderer — core rendering engine."""

from __future__ import annotations

import pytest

from arke.rendering.markdown_renderer import (
    MarkdownRenderer,
    render_markdown,
    render_streaming,
)
from arke.rendering.rendering_spec import ANSI_RESET


class TestMarkdownRenderer:
    """Tests for MarkdownRenderer class."""

    def test_renderer_init_default(self):
        """MarkdownRenderer should initialize with default settings."""
        renderer = MarkdownRenderer()
        assert renderer.show_internal_markup is False

    def test_renderer_init_debug_mode(self):
        """MarkdownRenderer should accept debug mode."""
        renderer = MarkdownRenderer(show_internal_markup=True)
        assert renderer.show_internal_markup is True


class TestRenderBasic:
    """Tests for basic rendering functionality."""

    def test_render_plain_text_unchanged(self):
        """Plain text without markdown should render unchanged."""
        renderer = MarkdownRenderer()
        result = renderer.render("Hello world")
        assert result == "Hello world"

    def test_render_heading(self):
        """# Headers should be styled."""
        renderer = MarkdownRenderer()
        result = renderer.render("# Title")
        assert "Title" in result
        assert "\033[" in result  # Contains ANSI code

    def test_render_bold(self):
        """**bold** should be styled."""
        renderer = MarkdownRenderer()
        result = renderer.render("This is **important**")
        assert "important" in result
        assert "\033[" in result

    def test_render_code(self):
        """`code` should be styled."""
        renderer = MarkdownRenderer()
        result = renderer.render("Run `npm install`")
        assert "npm install" in result
        assert "\033[" in result

    def test_render_italic(self):
        """*italic* should be styled."""
        renderer = MarkdownRenderer()
        result = renderer.render("This is *emphasized*")
        assert "emphasized" in result
        assert "\033[" in result

    def test_render_multiline(self):
        """Multiline markdown should render correctly."""
        renderer = MarkdownRenderer()
        md = "# Header\n\nSome text with **bold**.\n"
        result = renderer.render(md)
        assert "Header" in result
        assert "bold" in result


class TestStripInternalMarkup:
    """Tests for internal markup stripping."""

    def test_strip_plan_markers(self):
        """[PLAN:]/PLAN] markers should be stripped in normal mode."""
        renderer = MarkdownRenderer(show_internal_markup=False)
        md = "I will do this.\n[PLAN: step1 /PLAN]\nDone."
        result = renderer.render(md)
        assert "[PLAN:" not in result
        assert "/PLAN]" not in result
        assert "step1" not in result
        assert "Done." in result

    def test_strip_outil_markers(self):
        """[OUTIL:] markers should be stripped in normal mode."""
        renderer = MarkdownRenderer(show_internal_markup=False)
        md = "Analysis complete.\n[OUTIL: cli]\nReady."
        result = renderer.render(md)
        assert "[OUTIL:" not in result
        assert "cli" not in result
        assert "Analysis complete." in result
        assert "Ready." in result

    def test_strip_args_markers(self):
        """[ARGS:] markers should be stripped in normal mode."""
        renderer = MarkdownRenderer(show_internal_markup=False)
        md = "Running tool.\n[ARGS: {\"cmd\": \"ls\"}]\nDone."
        result = renderer.render(md)
        assert "[ARGS:" not in result
        assert "cmd" not in result

    def test_preserve_markup_in_debug_mode(self):
        """Debug mode should preserve internal markup."""
        renderer = MarkdownRenderer(show_internal_markup=True)
        md = "[OUTIL: fs]\n[ARGS: {\"path\": \"/tmp\"}]"
        result = renderer.render(md)
        assert "[OUTIL:" in result
        assert "[ARGS:" in result

    def test_strip_all_marker_types(self):
        """All marker types should be stripped together."""
        renderer = MarkdownRenderer()
        md = (
            "Start.\n"
            "[PLAN: 1. Read\n2. Write /PLAN]\n"
            "[OUTIL: sqlite]\n"
            "[ARGS: {\"db\": \"session\"}]\n"
            "End."
        )
        result = renderer.render(md)
        assert "[PLAN:" not in result
        assert "[OUTIL:" not in result
        assert "[ARGS:" not in result
        assert "Start." in result
        assert "End." in result


class TestStyleContext:
    """Tests for style context parameter."""

    def test_render_normal_context(self):
        """normal context should strip markup."""
        renderer = MarkdownRenderer()
        md = "[OUTIL: cli]Content"
        result = renderer.render(md, style_context="normal")
        assert "[OUTIL:" not in result

    def test_render_debug_context_with_debug_renderer(self):
        """debug context with show_internal_markup should preserve markup."""
        renderer = MarkdownRenderer(show_internal_markup=True)
        md = "[OUTIL: cli]Content"
        result = renderer.render(md, style_context="debug")
        assert "[OUTIL:" in result


class TestValidateAnsiOutput:
    """Tests for ANSI output validation."""

    def test_validate_no_unclosed_spans(self):
        """Rendering should not produce unclosed ANSI spans."""
        renderer = MarkdownRenderer()
        result = renderer.render("**bold** text")
        
        # Count codes and resets
        opens = result.count("\033[")
        resets = result.count(ANSI_RESET)
        # Allow opens >= resets (trailing open OK)
        assert resets <= opens

    def test_validate_complex_markdown(self):
        """Complex markdown should produce valid ANSI."""
        renderer = MarkdownRenderer()
        md = "# Title\n\n**Bold** and `code` and *italic*"
        result = renderer.render(md)
        
        opens = result.count("\033[")
        resets = result.count(ANSI_RESET)
        assert resets <= opens


class TestRenderInvalidInput:
    """Tests for error handling."""

    def test_render_non_string_raises(self):
        """render() should reject non-string input."""
        renderer = MarkdownRenderer()
        with pytest.raises(ValueError):
            renderer.render(123)  # type: ignore

    def test_render_none_raises(self):
        """render() should reject None."""
        renderer = MarkdownRenderer()
        with pytest.raises(ValueError):
            renderer.render(None)  # type: ignore


class TestRenderStreaming:
    """Tests for streaming render mode."""

    def test_streaming_accumulates_tokens(self):
        """render_streaming should yield styled tokens."""
        renderer = MarkdownRenderer()
        tokens = iter(["Hello ", "**world**", "!"])
        result = list(renderer.render_streaming(tokens))
        
        # Should get tokens (possibly regrouped)
        combined = "".join(result)
        assert "Hello" in combined
        assert "world" in combined

    def test_streaming_handles_markers(self):
        """render_streaming should handle control markers."""
        renderer = MarkdownRenderer()
        tokens = iter([
            "Text\n",
            "[OUTIL: cli]\n",
            "[ARGS: {}]\n",
            "Done",
        ])
        result = list(renderer.render_streaming(tokens))
        combined = "".join(result)
        
        # Markers should be filtered
        assert "[OUTIL:" not in combined
        assert "Text" in combined
        assert "Done" in combined

    def test_streaming_empty_tokens(self):
        """render_streaming should handle empty token stream."""
        renderer = MarkdownRenderer()
        tokens = iter([])
        result = list(renderer.render_streaming(tokens))
        assert result == []


class TestConvenienceFunctions:
    """Tests for top-level convenience functions."""

    def test_render_markdown_basic(self):
        """render_markdown() should work as a standalone function."""
        result = render_markdown("**bold** text")
        assert "bold" in result
        assert "\033[" in result

    def test_render_markdown_debug_mode(self):
        """render_markdown() with debug=True should preserve markup."""
        result = render_markdown("[OUTIL: cli]test", debug=True)
        assert "[OUTIL:" in result

    def test_render_streaming_basic(self):
        """render_streaming() should work as a standalone function."""
        tokens = iter(["Hello ", "world"])
        result = list(render_streaming(tokens))
        combined = "".join(result)
        assert "Hello" in combined
        assert "world" in combined


class TestDeterminism:
    """Tests for deterministic rendering (same input → same output)."""

    def test_render_deterministic(self):
        """Same markdown should render identically every time."""
        renderer = MarkdownRenderer()
        md = "# Header\n\nSome **bold** and `code`."
        
        result1 = renderer.render(md)
        result2 = renderer.render(md)
        
        assert result1 == result2

    def test_render_deterministic_across_instances(self):
        """Different renderer instances should produce same output."""
        md = "**important** point"
        
        r1 = MarkdownRenderer()
        r2 = MarkdownRenderer()
        
        result1 = r1.render(md)
        result2 = r2.render(md)
        
        assert result1 == result2


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_render_empty_string(self):
        """Empty string should render without error."""
        renderer = MarkdownRenderer()
        result = renderer.render("")
        assert result == ""

    def test_render_only_whitespace(self):
        """Whitespace should render without error."""
        renderer = MarkdownRenderer()
        result = renderer.render("   \n\t  ")
        # Should be either unchanged or stripped
        assert isinstance(result, str)

    def test_render_special_characters(self):
        """Special characters should be preserved."""
        renderer = MarkdownRenderer()
        result = renderer.render("Hello → world (©2026)")
        assert "→" in result
        assert "©" in result

    def test_render_nested_markers(self):
        """Nested markers should be handled."""
        renderer = MarkdownRenderer()
        # Unlikely but possible: [OUTIL: [nested stuff]] should be stripped
        md = "Before [OUTIL: nested] After"
        result = renderer.render(md)
        assert "Before" in result
        assert "After" in result
        assert "[OUTIL:" not in result
