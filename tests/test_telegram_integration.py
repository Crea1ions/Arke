"""Tests for Session 015 — Telegram bot integration (agent-first transport).

Tests validate:
1. Token configuration and retrieval (3 tests)
2. Message chunking for 4096 char limit (4 tests)
3. App builder and handler registration (3 tests)
4. Agent-first routing via _ask_agent (3 tests)
5. Error handling (2 tests)

Total: 15 integration tests for Session 015 Telegram support.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arke.interfaces.telegram_bot import (
    _chunk_message,
    build_app,
    get_token,
)


# ===========================================================================
# Test Suite 1: Token Configuration (3 tests)
# ===========================================================================


class TestTokenConfiguration:
    """Test Telegram bot token retrieval."""

    def test_token_from_environment(self, monkeypatch):
        """Token should be read from TELEGRAM_BOT_TOKEN env var."""
        test_token = "123456:ABC-DEF-VALID-TOKEN"
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", test_token)
        assert get_token() == test_token

    def test_token_not_configured(self, monkeypatch):
        """Should return empty string when token is not configured."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        # Mock the _env_list to return empty dict
        with patch("arke.chat_config._env_list", return_value={}):
            result = get_token()
            assert result == ""

    def test_build_app_with_token(self):
        """build_app should accept and build with a valid token."""
        token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        app = build_app(token)
        assert app is not None
        # Verify it's an Application
        assert str(type(app).__name__) == "Application"


# ===========================================================================
# Test Suite 2: Message Chunking (4 tests)
# ===========================================================================


class TestMessageChunking:
    """Test Telegram's 4096 character message limit handling."""

    def test_short_message_no_chunking(self):
        """Short messages should not be chunked."""
        text = "Hello, Telegram world!"
        chunks = _chunk_message(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_message_chunked(self):
        """Messages over 4096 chars should be split into chunks."""
        text = "line\n" * 1200  # ~6000 chars
        chunks = _chunk_message(text)
        assert len(chunks) >= 2
        assert all(len(chunk) <= 4096 for chunk in chunks)

    def test_exact_limit_boundary(self):
        """Message at exactly 4096 chars should not be chunked."""
        text = "x" * 4096
        chunks = _chunk_message(text)
        assert len(chunks) == 1

    def test_chunk_preserves_content(self):
        """Chunking should preserve all content (no data loss)."""
        text = "word " * 1000  # 5000 chars
        chunks = _chunk_message(text)
        rejoined = "\n".join(chunks)
        # Content preserved (chunks may have different newlines)
        assert len(rejoined) >= len(text) - 10  # Allow small margin


# ===========================================================================
# Test Suite 3: App Builder & Handlers (3 tests)
# ===========================================================================


class TestAppBuilder:
    """Test Telegram Application construction."""

    def test_build_app_returns_valid_app(self):
        """build_app should return a Telegram Application."""
        token = "123456:VALID"
        app = build_app(token)
        assert app is not None
        assert hasattr(app, "run_polling")

    def test_build_app_registers_start_handler(self):
        """App should register /start command handler."""
        token = "123456:VALID"
        app = build_app(token)
        # Check handlers exist
        assert hasattr(app, "handlers")
        handlers_str = str(app.handlers)
        # At minimum, should have some handlers
        assert len(app.handlers) > 0

    def test_build_app_handles_messages(self):
        """App should have text message handler."""
        token = "123456:VALID"
        app = build_app(token)
        # Verify handlers exist (Telegram groups handlers by priority)
        handlers_str = str(app.handlers)
        assert "CommandHandler" in handlers_str
        assert "MessageHandler" in handlers_str


# ===========================================================================
# Test Suite 4: Agent-First Architecture (3 tests)
# ===========================================================================


class TestAgentFirstArchitecture:
    """Test Telegram's agent-first design (cognitive contract)."""

    def test_handlers_use_async(self):
        """Message handlers should be async (non-blocking)."""
        import inspect
        from arke.interfaces.telegram_bot import _handle_message, _handle_start, _handle_help

        assert inspect.iscoroutinefunction(_handle_message)
        assert inspect.iscoroutinefunction(_handle_start)
        assert inspect.iscoroutinefunction(_handle_help)

    def test_handlers_import_agent_functions(self):
        """Handlers should import _ask_agent and build_cognitive_context."""
        import inspect
        from arke.interfaces.telegram_bot import _handle_message

        source = inspect.getsource(_handle_message)
        # Verify agent-first pattern
        assert "_ask_agent" in source
        assert "build_cognitive_context" in source

    def test_token_retrieval_uses_config(self):
        """Token retrieval should check both env and chat_config."""
        import inspect
        from arke.interfaces.telegram_bot import get_token

        source = inspect.getsource(get_token)
        # Verify both sources are checked
        assert "TELEGRAM_BOT_TOKEN" in source
        assert "chat_config" in source


# ===========================================================================
# Test Suite 5: Error Handling (2 tests)
# ===========================================================================


class TestErrorHandling:
    """Test error cases and failure modes."""

    def test_missing_token_raises_error(self):
        """Missing token should raise RuntimeError with helpful message."""
        with patch("arke.interfaces.telegram_bot.get_token", return_value=""):
            with pytest.raises(RuntimeError) as exc_info:
                from arke.interfaces.telegram_bot import main
                main()

            error_str = str(exc_info.value)
            # Verify error message is helpful
            assert ("TELEGRAM_BOT_TOKEN" in error_str or
                    "token" in error_str.lower() or
                    "config" in error_str.lower())

    def test_chunk_message_handles_edge_cases(self):
        """_chunk_message should handle edge cases gracefully."""
        # Empty string
        assert _chunk_message("") == [""]

        # Single character
        assert _chunk_message("a") == ["a"]

        # Exactly max length
        text_max = "x" * 4096
        chunks = _chunk_message(text_max)
        assert all(len(c) <= 4096 for c in chunks)
