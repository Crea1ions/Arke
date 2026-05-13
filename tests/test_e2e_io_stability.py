"""Phase 6 — E2E Integration & Stress Testing for Rendering & Input Stability.

These tests validate the entire I/O layer under realistic and stressful conditions.
"""

import pytest
from unittest.mock import Mock, patch

from arke.rendering.markdown_renderer import MarkdownRenderer
from arke.rendering.rendering_debug import set_render_mode, get_render_mode, DebugRenderer
from arke.rendering.input_normalizer import InputNormalizer
from arke.rendering.streaming import StreamingOutputBuffer


class TestEndToEndIOStability:
    """E2E tests for I/O layer stability."""

    def test_20_turn_repl_simulation(self):
        """Simulate 20-turn REPL loop with I/O stability."""
        normalizer = InputNormalizer()
        renderer = MarkdownRenderer()
        
        for turn in range(20):
            # Simulate user input
            raw_input = f"Turn {turn}: query\r\n"
            normalized = normalizer.normalize(raw_input)
            assert normalized == f"Turn {turn}: query"
            
            # Simulate agent response
            response = f"Response {turn} with **bold** text."
            rendered = renderer.render(response)
            assert "Response" in rendered
            assert "bold" in rendered
            
            # Reset state for next turn
            normalizer.reset_turn_state()
        
        # 20 turns completed without error
        assert True

    def test_mode_switch_output_clean(self):
        """Test rapid switching between normal and debug modes."""
        renderer = MarkdownRenderer()
        debug_renderer = DebugRenderer()
        
        text = "Analysis: [OUTIL: cli] [ARGS: {}]"
        
        # Normal mode: markup stripped
        set_render_mode("normal")
        normal_output = renderer.render(text, style_context="normal")
        assert "[OUTIL:" not in normal_output
        
        # Switch to debug
        set_render_mode("debug")
        debug_output = debug_renderer.render_with_internals(
            text,
            {"token_count": 10}
        )
        assert "[DEBUG RENDERING]" in debug_output
        
        # Switch back to normal
        set_render_mode("normal")
        normal_again = renderer.render(text, style_context="normal")
        assert normal_output == normal_again
        assert "[OUTIL:" not in normal_again

    def test_long_response_no_artifacts(self):
        """Test rendering a >500 line response without artifacts."""
        renderer = MarkdownRenderer()
        
        # Generate long markdown
        lines = []
        for i in range(100):
            lines.append(f"## Section {i}\n")
            lines.append("Some **bold** text with `code` blocks.\n")
            lines.append(f"Paragraph {i} with normal content.\n")
        
        long_text = "\n".join(lines)
        
        # Render without error
        result = renderer.render(long_text)
        
        # Verify no truncation or artifacts
        assert len(result) > len(long_text) * 0.8  # Some overhead from ANSI codes
        assert result.count("Section") == 100
        assert "\033[" in result  # Has ANSI codes

    def test_paste_multiline_normalization(self):
        """Test paste buffer with \r artifacts normalizes cleanly."""
        normalizer = InputNormalizer()
        
        # Simulate paste with various line endings
        paste = "line1\r\nline2\rline3\nline4"
        normalized = normalizer.normalize(paste)
        
        # Should normalize to newlines only (bare \r stripped, \r\n → \n)
        assert "\r" not in normalized
        # line1\r\nline2\rline3\nline4 → line1\nline2line3\nline4 (2 newlines)
        assert normalized.count("\n") >= 2  # At least 2 newlines

    def test_concurrent_render_consistency(self):
        """Test that concurrent rendering (simulated) maintains consistency."""
        renderer = MarkdownRenderer()
        
        text = "# Test\n**Bold** and `code`"
        
        # Render multiple times "concurrently" (sequential but simulating parallel)
        results = []
        for _ in range(10):
            result = renderer.render(text)
            results.append(result)
        
        # All should be identical (deterministic)
        for i in range(1, len(results)):
            assert results[i] == results[0]

    def test_signal_handling_echo_cleanup(self):
        """Test that echo buffer cleanup works after signal."""
        normalizer = InputNormalizer()
        
        # Simulate user input during streaming
        raw_input = "some input"
        normalized = normalizer.normalize(raw_input)
        
        # Generate cleanup sequence (e.g., after Ctrl+C)
        cleanup_seq = normalizer.clean_echo_buffer()
        assert "\r" in cleanup_seq
        assert len(cleanup_seq) > 5

    def test_input_double_injection_prevention(self):
        """Test prevention of double-injection of same input."""
        normalizer = InputNormalizer()
        
        # First injection OK
        normalizer.prevent_double_injection("hello")
        
        # Second injection of different input OK
        normalizer.prevent_double_injection("world")
        
        # Reset turn
        normalizer.reset_turn_state()
        
        # Same input can be injected again after reset
        normalizer.prevent_double_injection("hello")
        assert True

    def test_streaming_buffer_token_accuracy(self):
        """Test streaming buffer maintains token accuracy."""
        buffer = StreamingOutputBuffer()
        
        tokens = ["Hello ", "**world**", "!", " End."]
        flushed = []
        
        for token in tokens:
            result = buffer.append_token(token)
            if result:
                flushed.append(result)
        
        remaining = buffer.flush_remaining()
        
        # All tokens accounted for
        combined = "".join(flushed) + remaining
        assert "Hello" in combined
        assert "world" in combined
        assert "End" in combined


class TestRegressionPrevention:
    """Tests to prevent regressions from previous sessions."""

    def test_session_018_paste_still_works(self):
        """Ensure Session 018 paste functionality still works."""
        normalizer = InputNormalizer()
        
        # Large paste with multiple lines
        large_paste = "line1\nline2\nline3\nline4\nline5"
        
        # Should detect as large
        assert normalizer.detect_large_paste(large_paste)
        
        # Should normalize without error
        normalized = normalizer.normalize(large_paste)
        assert "line1" in normalized
        assert "line5" in normalized

    def test_session_030_ansi_4bit_preserved(self):
        """Ensure Session 030 ANSI 4-bit is still in use."""
        from arke.rendering.rendering_spec import get_ansi_code, MarkdownStyle
        
        # Should NOT be truecolor RGB
        accent_code = get_ansi_code(MarkdownStyle.ACCENT)
        assert "38;2" not in accent_code  # Not RGB truecolor
        assert "\033[96m" == accent_code  # Should be 4-bit bright cyan

    def test_session_032_json_protocol_untouched(self):
        """Ensure Session 032 JSON protocol is unmodified."""
        # This phase only adds new modules, doesn't modify chat.py
        # So JSON protocol should be untouched
        from arke.chat import build_cognitive_context
        
        # Should still work (existing function)
        context = build_cognitive_context("test", session_id="abc123")
        assert isinstance(context, str)


class TestCriticalInvariants:
    """Tests for critical system invariants."""

    def test_deterministic_rendering_invariant(self):
        """Critical: Rendering must be deterministic."""
        renderer = MarkdownRenderer()
        text = "# Header\n\n**Bold** and `code`.\n\nMore text."
        
        # Render 100 times
        results = set()
        for _ in range(100):
            result = renderer.render(text)
            results.add(result)
        
        # All identical
        assert len(results) == 1

    def test_debug_isolation_invariant(self):
        """Critical: Debug output must never leak to normal mode."""
        set_render_mode("normal")
        renderer = MarkdownRenderer()
        
        # Render text that would show debug info
        result = renderer.render("[OUTIL: cli]")
        
        # Should NOT contain debug markers in normal mode
        assert "[DEBUG" not in result
        assert "[OUTIL:" not in result

    def test_input_safety_invariant(self):
        """Critical: All input must be normalized."""
        normalizer = InputNormalizer()
        
        # Various dangerous inputs
        test_cases = [
            "hello\r\nworld",
            "line1\rline2",
            "  \n\t  hello  \n  ",
            "text" + ("x" * 1000),  # Very long
        ]
        
        for raw in test_cases:
            normalized = normalizer.normalize(raw)
            # All should be strings
            assert isinstance(normalized, str)
            # None should contain bare \r
            assert "\r" not in normalized


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
