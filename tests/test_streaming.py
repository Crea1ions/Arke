"""Tests for LLM streaming functionality — Phase 1 Session 013."""

from __future__ import annotations

import json
import re
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace

import pytest

from arke.llm.litellm_manager import LiteLLMManager
from arke.chat import StreamingMarkdownDisplay, _ask_agent, _strip_internal_markup, _synthesize_tool_results
from arke.task_graph import StepStatus
from arke import chat_theme as T


class MockStreamingChunk:
    """Mock a litellm streaming chunk."""

    def __init__(self, content: str):
        self.choices = [MagicMock()]
        self.choices[0].delta = MagicMock()
        self.choices[0].delta.content = content


# ============================================================================
# Tests for LiteLLMManager.stream_complete()
# ============================================================================


def test_stream_complete_basic_streaming():
    """Test that stream_complete() yields tokens from streaming API."""
    manager = LiteLLMManager()

    # Mock litellm.completion with streaming response
    mock_chunks = [
        MockStreamingChunk("Hello "),
        MockStreamingChunk("world"),
        MockStreamingChunk("!"),
    ]

    # Mock only the provider check and set a mock key
    with patch.dict("os.environ", {"GEMINI_API_KEY": "mock_key"}):
        with patch("litellm.completion") as mock_completion:
            mock_completion.return_value = iter(mock_chunks)

            # Call stream_complete
            tokens = list(manager.stream_complete("test prompt", max_tokens=100))

            # Verify tokens accumulated
            assert tokens == ["Hello ", "world", "!"]
            assert "".join(tokens) == "Hello world!"


def test_stream_complete_handles_empty_chunks():
    """Test that stream_complete() handles chunks with None content."""
    manager = LiteLLMManager()

    # Mock chunks with some None content
    mock_chunks = [
        MockStreamingChunk("Test"),
        MockStreamingChunk(None),  # Should be skipped
        MockStreamingChunk(" response"),
    ]

    with patch.dict("os.environ", {"GEMINI_API_KEY": "mock_key"}):
        with patch("litellm.completion") as mock_completion:
            mock_completion.return_value = iter(mock_chunks)

            tokens = list(manager.stream_complete("test prompt"))

            # None chunks should be skipped
            assert "".join(tokens) == "Test response"


def test_stream_complete_fallback_on_error():
    """Test that stream_complete() falls back to next provider on error."""
    manager = LiteLLMManager()
    manager._fallback_order = ["provider1", "provider2"]

    # Mock: first provider fails, second succeeds
    with patch.object(manager, "_has_required_api_key", return_value=True):
        with patch.object(
            manager, "_stream_provider"
        ) as mock_stream_provider:

            def side_effect(provider_key, *args, **kwargs):
                if provider_key == "provider1":
                    raise RuntimeError("Provider 1 failed")
                else:
                    # Provider 2 succeeds
                    yield "Success"

            mock_stream_provider.side_effect = side_effect

            tokens = list(manager.stream_complete("test prompt"))
            assert tokens == ["Success"]


# ============================================================================
# Tests for StreamingMarkdownDisplay
# ============================================================================


def test_streaming_display_accumulates_tokens():
    """Test that StreamingMarkdownDisplay accumulates tokens correctly."""
    display = StreamingMarkdownDisplay(use_live=False)

    display.add_token("Hello ")
    display.add_token("world")
    display.add_token("!")

    assert display.get_full_text() == "Hello world!"


def test_streaming_display_with_markdown():
    """Test that StreamingMarkdownDisplay handles Markdown correctly."""
    display = StreamingMarkdownDisplay(use_live=False)

    display.add_token("## Title\n")
    display.add_token("This is **bold** text\n")
    display.add_token("- Item 1\n")

    result = display.get_full_text()
    assert "## Title" in result
    assert "**bold**" in result
    assert "- Item 1" in result


def test_streaming_display_handles_tool_markers():
    """Test that StreamingMarkdownDisplay handles [OUTIL:] markers."""
    display = StreamingMarkdownDisplay(use_live=False)

    display.add_token("I will use a tool.\n")
    display.add_token("[OUTIL: cli]\n")
    display.add_token("[ARGS: {\"command\": \"ls\"}]")

    result = display.get_full_text()
    assert "[OUTIL: cli]" in result
    assert "[ARGS:" in result


def test_streaming_display_hides_internal_markers_from_stdout():
    """Internal control markers must stay out of the visible streaming output."""
    display = StreamingMarkdownDisplay(use_live=False)

    with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
        display.add_token("Analyse en cours\n")
        display.add_token("[OUTIL: sqlite]\n")
        display.add_token("[ARGS: {\"db\": \"session\"}]")
        display.add_token("\nRésultat prêt")
        display.close()

    visible = "".join(call.args[0] for call in mock_write.call_args_list)
    assert "Analyse en cours" in visible
    assert "Résultat prêt" in visible
    assert "[OUTIL:" not in visible
    assert "[ARGS:" not in visible


def test_strip_internal_markup_removes_control_blocks():
    """User-visible text must not keep plan or tool control markup."""
    raw = (
        "Je vérifie les données.\n"
        "[PLAN:\n1. Lire les logs\n/PLAN]\n"
        "[OUTIL: fs]\n"
        "[ARGS: {\"path\": \"/tmp/log.txt\"}]\n"
        "Résultat prêt."
    )

    cleaned = _strip_internal_markup(raw)

    assert "Je vérifie les données." in cleaned
    assert "Résultat prêt." in cleaned
    assert "[PLAN:" not in cleaned
    assert "[OUTIL:" not in cleaned
    assert "[ARGS:" not in cleaned


def test_streaming_display_close_safe():
    """Test that calling close() multiple times is safe."""
    display = StreamingMarkdownDisplay(use_live=False)

    # Should not raise
    display.close()
    display.close()


def test_streaming_display_uses_first_line_prefix():
    display = StreamingMarkdownDisplay(
        use_live=False,
        line_prefix="NEXT ",
        first_line_prefix="FIRST ",
    )

    with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
        display.add_token("one\n")
        display.add_token("two\n")
        display.close()

    visible = "".join(call.args[0] for call in mock_write.call_args_list)
    assert "FIRST one" in visible
    assert "NEXT two" in visible


def test_streaming_display_wraps_with_max_content_width():
    display = StreamingMarkdownDisplay(
        use_live=False,
        line_prefix="P ",
        max_content_width=10,
    )

    with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
        display.add_token("0123456789abcdefghij")
        display.close()

    visible = "".join(call.args[0] for call in mock_write.call_args_list)
    plain = re.sub(r"\x1b\[[0-9;]*m", "", visible)
    lines = [line for line in plain.splitlines() if line]
    assert len(lines) >= 2
    for line in lines:
        assert line.startswith("P ")
        assert len(line) <= 12


def test_theme_block_marker_is_distinct_colorless_text_removed():
    marker_line = T.step_output("Hello")
    plain = re.sub(r"\x1b\[[0-9;]*m", "", marker_line)
    assert plain.startswith("└─ ")
    assert "Hello" in plain


def test_user_icon_uses_warm_block_marker_color():
    block = T.user_block("hello")
    assert "◉" in block
    assert T.BLOCK_MARKER in block


def test_agent_theme_hides_model_name_and_icon():
    prompt = T.prompt_line("flash")
    header = T.agent_header("flash")
    footer = T.agent_footer("flash")

    def strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    prompt_plain = strip_ansi(prompt)
    header_plain = strip_ansi(header)
    footer_plain = strip_ansi(footer)

    assert "Arke" in prompt_plain
    assert "Arke" in header_plain
    assert "Arke" in footer_plain
    assert "Flash" not in prompt_plain
    assert "Flash" not in header_plain
    assert "Flash" not in footer_plain
    assert "⚡" not in prompt_plain
    assert "⚡" not in header_plain
    assert "⚡" not in footer_plain


# ============================================================================
# Tests for _ask_agent() with streaming
# ============================================================================


def test_ask_agent_streaming_accumulates_tokens():
    """Test that _ask_agent() with stream callback accumulates all tokens."""
    with patch("arke.chat._load_env_file"):
        with patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
            mock_manager = MagicMock()

            # Mock stream_complete to return tokens
            mock_manager.stream_complete.return_value = iter([
                "I will help.\n",
                "[OUTIL: cli]\n",
                "[ARGS: {\"command\": \"echo test\"}]",
            ])

            MockLLMClass.return_value = mock_manager

            # Collect tokens via callback
            collected_tokens = []

            def capture_callback(token):
                collected_tokens.append(token)

            result = _ask_agent(
                cognitive_json="{}",
                intention="test task",
                context={},
                stream_display_callback=capture_callback,
            )

            # Verify tokens were collected
            assert collected_tokens == [
                "I will help.\n",
                "[OUTIL: cli]\n",
                "[ARGS: {\"command\": \"echo test\"}]",
            ]

            # Verify tool was parsed
            assert result["tool"] == "cli"
            assert result["args"] == {"command": "echo test"}


def test_ask_agent_without_streaming():
    """Test that _ask_agent() without callback uses non-streaming API."""
    with patch("arke.chat._load_env_file"):
        with patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
            mock_manager = MagicMock()

            # Mock non-streaming complete()
            mock_manager.complete.return_value = (
                "Direct response without tools",
                0.01,
                50,
            )

            MockLLMClass.return_value = mock_manager

            result = _ask_agent(
                cognitive_json="{}",
                intention="test task",
                context={},
                stream_display_callback=None,  # No streaming
            )

            # Verify non-streaming API was used
            mock_manager.complete.assert_called_once()
            mock_manager.stream_complete.assert_not_called()

            # Verify response
            assert result["tool"] is None
            assert result["response"] == "Direct response without tools"


def test_synthesize_tool_results_includes_canonical_cli_summary():
    """CLI synthesis prompt must include canonical facts before LLM response."""
    fake_step = SimpleNamespace(
        tool="cli",
        status=StepStatus.SUCCESS,
        arguments={"command": "rm /workspace/test-001.md && ls /workspace/"},
        output={"return_code": 0, "stdout": "archive\nMOC_project.md\n", "stderr": ""},
    )

    captured = {}

    with patch("arke.chat._load_env_file"), patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
        mock_manager = MagicMock()
        mock_manager.complete.return_value = ("OK", 0.0, 0)

        def _capture(prompt, task_type="reasoning", max_tokens=1024):
            captured["prompt"] = prompt
            return ("OK", 0.0, 0)

        mock_manager.complete.side_effect = _capture
        MockLLMClass.return_value = mock_manager

        result = _synthesize_tool_results("suprime le fichier test-001.md", [fake_step])

    assert result == "OK"
    assert "RÉSUMÉ CLI CANONIQUE" in captured["prompt"]
    assert "rm /workspace/test-001.md" in captured["prompt"]
    assert "Statut canonique: succès" in captured["prompt"]


def test_ask_agent_prompt_does_not_teach_confirmation_flow():
    """The system prompt must not reintroduce visible plans or confirmation prompts."""
    with patch("arke.chat._load_env_file"):
        with patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
            mock_manager = MagicMock()

            def _fake_stream_complete(prompt: str, task_type: str = "reasoning", max_tokens: int = 2048):
                assert "Proceed with this plan?" not in prompt
                assert "[PLAN:" not in prompt
                assert "Ne demande jamais de confirmation" in prompt
                return iter(["Réponse directe"]) 

            mock_manager.stream_complete.side_effect = _fake_stream_complete
            MockLLMClass.return_value = mock_manager

            result = _ask_agent(
                cognitive_json="{}",
                intention="teste le prompt",
                context={},
                stream_display_callback=lambda t: None,
            )

            assert result["tool"] is None
            assert result["response"] == "Réponse directe"


def test_ask_agent_streaming_parses_tool_marker():
    """Test that streaming response correctly parses tool markers."""
    with patch("arke.chat._load_env_file"):
        with patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
            mock_manager = MagicMock()

            # Simulate streaming multi-line response with tool marker
            mock_manager.stream_complete.return_value = iter([
                "Let me check the file.\n",
                "[OUTIL: fs]\n",
                "[ARGS: {\"path\": \"/etc/hostname\"}]",
            ])

            MockLLMClass.return_value = mock_manager

            result = _ask_agent(
                cognitive_json="{}",
                intention="read hostname",
                context={},
                stream_display_callback=lambda t: None,  # No-op callback
            )

            # Verify tool decision
            assert result["tool"] == "fs"
            assert result["args"] == {"path": "/etc/hostname"}
            assert "check the file" in (result.get("response") or "")


# ============================================================================
# Integration-style tests
# ============================================================================


def test_streaming_end_to_end_markdown():
    """Test streaming a complete Markdown response."""
    display = StreamingMarkdownDisplay(use_live=False)

    # Simulate streaming response
    tokens = [
        "# Résultats\n",
        "\n",
        "Les fichiers trouvés:\n",
        "- file1.txt\n",
        "- file2.txt\n",
        "\n",
        "Total: 2 fichiers",
    ]

    for token in tokens:
        display.add_token(token)

    result = display.get_full_text()
    assert "# Résultats" in result
    assert "- file1.txt" in result
    assert "Total: 2 fichiers" in result

    display.close()


def test_streaming_preserves_json_args():
    """Test that streaming preserves valid JSON in [ARGS:] blocks."""
    json_content = {
        "db": "session",
        "query": "SELECT * FROM session_context WHERE key = ?",
        "params": ["project_name"],
    }

    with patch("arke.chat._load_env_file"):
        with patch("arke.llm.litellm_manager.LiteLLMManager") as MockLLMClass:
            mock_manager = MagicMock()

            # Stream response with complex JSON
            response_tokens = [
                "I'll query the database.\n",
                "[OUTIL: sqlite]\n",
                "[ARGS: " + json.dumps(json_content) + "]",
            ]

            mock_manager.stream_complete.return_value = iter(response_tokens)
            MockLLMClass.return_value = mock_manager

            result = _ask_agent(
                cognitive_json="{}",
                intention="query database",
                context={},
                stream_display_callback=lambda t: None,
            )

            # Verify JSON parsed correctly
            assert result["tool"] == "sqlite"
            assert result["args"]["db"] == "session"
            assert result["args"]["params"] == ["project_name"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
