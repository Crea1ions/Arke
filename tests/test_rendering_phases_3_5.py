"""Tests for Phase 3-5 rendering modules."""

import pytest
from arke.rendering.streaming import StreamingOutputBuffer
from arke.rendering.rendering_debug import DebugRenderer, set_render_mode, get_render_mode
from arke.rendering.input_normalizer import InputNormalizer, normalize_input


# Phase 3 — Streaming Tests
class TestStreamingOutputBuffer:
    def test_buffer_init(self):
        buf = StreamingOutputBuffer()
        assert buf.get_flushed_count() == 0
    
    def test_append_token(self):
        buf = StreamingOutputBuffer()
        result = buf.append_token("hello")
        assert result == "hello"
    
    def test_flush_remaining(self):
        buf = StreamingOutputBuffer()
        buf.append_token("test")
        remaining = buf.flush_remaining()
        assert isinstance(remaining, str)
    
    def test_incomplete_ansi_detection(self):
        assert StreamingOutputBuffer._ends_with_incomplete_ansi("\033[")
        assert not StreamingOutputBuffer._ends_with_incomplete_ansi("hello")
        assert not StreamingOutputBuffer._ends_with_incomplete_ansi("\033[1m")


# Phase 4 — Debug Renderer Tests
class TestDebugRenderer:
    def test_debug_renderer_init(self):
        renderer = DebugRenderer()
        assert renderer is not None
    
    def test_render_with_internals(self):
        renderer = DebugRenderer()
        result = renderer.render_with_internals("test", {"token_count": 5})
        assert "test" in result
        assert "[DEBUG RENDERING]" in result
    
    def test_render_mode_setter(self):
        set_render_mode("debug")
        assert get_render_mode() == "debug"
        set_render_mode("normal")
        assert get_render_mode() == "normal"
    
    def test_invalid_render_mode(self):
        with pytest.raises(ValueError):
            set_render_mode("invalid")


# Phase 5 — Input Normalizer Tests
class TestInputNormalizer:
    def test_normalize_crlf(self):
        normalizer = InputNormalizer()
        result = normalizer.normalize("hello\r\nworld\r\n")
        assert result == "hello\nworld"
    
    def test_normalize_cr(self):
        normalizer = InputNormalizer()
        result = normalizer.normalize("hello\rworld")
        # Bare CR is stripped (removed), not converted to newline
        assert result == "helloworld"
    
    def test_normalize_strips_whitespace(self):
        normalizer = InputNormalizer()
        result = normalizer.normalize("  hello world  \n")
        assert result == "hello world"
    
    def test_detect_large_paste_multiline(self):
        normalizer = InputNormalizer()
        large = "\n".join(["line"] * 10)
        assert normalizer.detect_large_paste(large)
    
    def test_detect_large_paste_chars(self):
        normalizer = InputNormalizer()
        large = "x" * 600
        assert normalizer.detect_large_paste(large)
    
    def test_reset_turn_state(self):
        normalizer = InputNormalizer()
        normalizer.reset_turn_state()
        assert normalizer._injection_count == 0
    
    def test_normalize_input_convenience(self):
        result = normalize_input("hello\r\nworld")
        assert result == "hello\nworld"
    
    def test_invalid_utf8_rejected(self):
        normalizer = InputNormalizer()
        with pytest.raises(ValueError):
            normalizer.normalize("hello\ud800world")  # Invalid UTF-8
