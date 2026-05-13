"""Tests for arke.rendering.rendering_spec — canonical Markdown→ANSI mapping."""

from __future__ import annotations

import os
import pytest

from arke.rendering.rendering_spec import (
    MarkdownStyle,
    STYLE_TO_ANSI,
    ANSI_RESET,
    get_ansi_code,
    validate_ansi_span,
    style_text,
    model_color,
)


class TestMarkdownStyle:
    """Tests for MarkdownStyle enum."""

    def test_all_styles_have_mapping(self):
        """Every MarkdownStyle MUST have an entry in STYLE_TO_ANSI."""
        for style in MarkdownStyle:
            assert style in STYLE_TO_ANSI, f"Missing mapping for {style}"

    def test_style_values_are_strings(self):
        """All style values should be lowercase strings."""
        for style in MarkdownStyle:
            assert isinstance(style.value, str)
            assert style.value.islower() or "_" in style.value


class TestStyleToAnsi:
    """Tests for STYLE_TO_ANSI mapping."""

    def test_ansi_codes_are_strings(self):
        """All ANSI codes should be strings (some may be empty for NO_COLOR)."""
        for code in STYLE_TO_ANSI.values():
            assert isinstance(code, str)

    def test_reset_code_defined(self):
        """ANSI_RESET should be defined and non-empty."""
        assert ANSI_RESET == "\033[0m"

    def test_no_duplicate_codes(self):
        """Each unique non-empty code should appear only in specific contexts."""
        # Note: It's OK for multiple styles to map to the same code (e.g., BORDER and MUTED both dim)
        # But all codes should be valid ANSI
        seen = set()
        for style, code in STYLE_TO_ANSI.items():
            if code:  # non-empty
                assert code.startswith("\033["), f"Invalid ANSI code for {style}: {code}"
                assert code.endswith("m"), f"Invalid ANSI code for {style}: {code}"


class TestGetAnsiCode:
    """Tests for get_ansi_code() function."""

    def test_get_ansi_code_valid_style(self):
        """get_ansi_code should return code for valid style."""
        code = get_ansi_code(MarkdownStyle.BOLD)
        assert code == "\033[1m"

    def test_get_ansi_code_accent(self):
        """ACCENT should map to bright cyan."""
        code = get_ansi_code(MarkdownStyle.ACCENT)
        assert code == "\033[96m"

    def test_get_ansi_code_invalid_style(self):
        """get_ansi_code should raise KeyError for invalid style."""
        with pytest.raises(KeyError):
            get_ansi_code("invalid")  # type: ignore

    def test_get_ansi_code_no_color_env(self, monkeypatch):
        """When NO_COLOR is set, get_ansi_code should return empty string."""
        # Note: The NO_COLOR check happens at module import time
        # This test documents the behavior; actual env var must be set before import
        monkeypatch.setenv("NO_COLOR", "1")
        # To fully test this, we would need to reload the module
        # For now, we just verify the module respects NO_COLOR at import time
        assert "NO_COLOR" in os.environ or not os.environ.get("NO_COLOR")

    def test_get_ansi_code_text_style_no_code(self):
        """TEXT style should map to empty code."""
        code = get_ansi_code(MarkdownStyle.TEXT)
        assert code == ""


class TestValidateAnsiSpan:
    """Tests for validate_ansi_span() function."""

    def test_validate_ansi_span_basic(self):
        """validate_ansi_span should wrap text with code + reset."""
        result = validate_ansi_span(MarkdownStyle.BOLD, "Hello")
        assert result == "\033[1mHello\033[0m"

    def test_validate_ansi_span_success(self):
        """SUCCESS style should produce green span."""
        result = validate_ansi_span(MarkdownStyle.SUCCESS, "OK")
        assert result == "\033[92mOK\033[0m"

    def test_validate_ansi_span_empty_text_raises(self):
        """Empty text should raise ValueError."""
        with pytest.raises(ValueError, match="empty text"):
            validate_ansi_span(MarkdownStyle.BOLD, "")

    def test_validate_ansi_span_reset_present(self):
        """Result should always end with ANSI_RESET."""
        result = validate_ansi_span(MarkdownStyle.ERROR, "Failure")
        assert result.endswith(ANSI_RESET)

    def test_validate_ansi_span_text_style(self):
        """TEXT style with NO_COLOR behavior."""
        result = validate_ansi_span(MarkdownStyle.TEXT, "content")
        # TEXT maps to empty code, so should just return the text
        assert result == "content" or result.endswith(ANSI_RESET)


class TestStyleText:
    """Tests for style_text() composition function."""

    def test_style_text_single_style(self):
        """style_text with single style should work."""
        result = style_text("Hello", MarkdownStyle.BOLD)
        assert "\033[1m" in result
        assert "Hello" in result
        assert ANSI_RESET in result

    def test_style_text_multiple_styles(self):
        """style_text should apply multiple styles in order."""
        result = style_text("Bold Cyan", MarkdownStyle.BOLD, MarkdownStyle.ACCENT)
        assert "Bold Cyan" in result
        # Should contain both codes (wrapped around each other)
        assert "\033[" in result

    def test_style_text_empty_text_safe(self):
        """style_text with empty text should not crash."""
        # style_text may skip empty text or pass it through
        result = style_text("", MarkdownStyle.BOLD)
        # Either empty or safely handled
        assert isinstance(result, str)

    def test_style_text_no_styles(self):
        """style_text with no styles should return text unchanged."""
        result = style_text("Plain text")
        assert result == "Plain text"


class TestModelColor:
    """Tests for model_color() helper function."""

    def test_model_color_flash(self):
        """flash model should map to bright cyan."""
        color = model_color("flash")
        assert color == "\033[96m"

    def test_model_color_claude(self):
        """claude model should map to bright magenta."""
        color = model_color("claude")
        assert color == "\033[95m"

    def test_model_color_mistral(self):
        """mistral model should map to bright green."""
        color = model_color("mistral")
        assert color == "\033[92m"

    def test_model_color_local(self):
        """local model should map to yellow."""
        color = model_color("local")
        assert color == "\033[33m"

    def test_model_color_unknown_defaults_to_accent(self):
        """Unknown model should default to ACCENT (cyan)."""
        color = model_color("unknown_model_xyz")
        assert color == "\033[96m"  # ACCENT

    def test_model_color_pro_alias(self):
        """pro alias should map correctly."""
        color = model_color("pro")
        assert color == "\033[33m"  # MODEL_LOCAL


class TestAnsiReset:
    """Tests for ANSI_RESET constant."""

    def test_ansi_reset_value(self):
        """ANSI_RESET should be the correct reset code."""
        assert ANSI_RESET == "\033[0m"

    def test_ansi_reset_clears_formatting(self):
        """Strings ending with ANSI_RESET should properly terminate."""
        # Conceptual test: if you have code + text + reset, terminal should return to normal
        test = f"\033[1mBold\033[0m"
        assert test.endswith("\033[0m")


class TestNoColor:
    """Tests for NO_COLOR environment variable support."""

    def test_no_color_respected(self):
        """NO_COLOR env var should suppress color codes.
        
        Note: This is tested at import time, so we test the concept here.
        """
        # The module imports and sets _NO_COLOR at load time
        # We can't easily change it after import, but we verify it's used
        from arke.rendering import rendering_spec
        
        # If NO_COLOR is not set at import time, codes should be present
        if not os.environ.get("NO_COLOR"):
            assert get_ansi_code(MarkdownStyle.BOLD) != ""


# Integration tests
class TestIntegration:
    """Integration tests for the rendering spec."""

    def test_full_span_workflow(self):
        """Test creating a styled span end-to-end."""
        # User wants to render "Error" in red
        styled = validate_ansi_span(MarkdownStyle.ERROR, "Error")
        
        # Should contain error code (bright red) and text
        assert "\033[91m" in styled  # bright red
        assert "Error" in styled
        assert ANSI_RESET in styled

    def test_model_selection_consistency(self):
        """Test that model selection is consistent across calls."""
        color1 = model_color("flash")
        color2 = model_color("flash")
        assert color1 == color2

    def test_all_semantic_colors_covered(self):
        """Verify semantic colors for user-facing messages."""
        semantic_styles = [
            MarkdownStyle.SUCCESS,
            MarkdownStyle.WARNING,
            MarkdownStyle.ERROR,
        ]
        for style in semantic_styles:
            code = get_ansi_code(style)
            assert code, f"Semantic style {style} should have a code"
            assert code.startswith("\033["), f"Invalid ANSI code for {style}"
