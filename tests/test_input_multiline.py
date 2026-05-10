"""Session 018 — Tests for multiline paste buffering in the REPL input.

Tests for:
- _read_paste_buffered() returns single-line input unchanged
- Paste detected: full text re-injected into readline for user review
- User must press Enter (second input() call) to confirm
- readline hook is always cleared (finally block)
- \u21b5 placeholders in reviewed text are restored to real newlines
- EOF from os.read() exits accumulation loop cleanly
- fd O_NONBLOCK flag is always restored
"""

from __future__ import annotations

import fcntl
import os
from unittest.mock import patch, call, MagicMock

import pytest

from arke.chat import _read_paste_buffered, _PASTE_NL


_FAKE_FD = 0
_OLD_FL = 0


def _fcntl_se():
    """Minimal fcntl side_effect: F_GETFL → old_fl, two F_SETFL → None."""
    return [_OLD_FL, None, None]


class TestReadPasteBuffered:
    """Tests for the _read_paste_buffered() helper."""

    # ------------------------------------------------------------------
    # single-line (normal typing) — no second input() call
    # ------------------------------------------------------------------

    def test_single_line_no_extra_data(self):
        """Single-line input returns unchanged; input() called exactly once."""
        with patch("builtins.input", return_value="hello world") as mock_input, \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=BlockingIOError):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")
        assert result == "hello world"
        mock_input.assert_called_once_with("› ")

    def test_prompt_forwarded_to_input(self):
        """The prompt string is forwarded to input() unchanged."""
        captured = []

        def fake_input(p=""):
            captured.append(p)
            return "x"

        with patch("builtins.input", side_effect=fake_input), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=BlockingIOError):
            ms.fileno.return_value = _FAKE_FD
            _read_paste_buffered("MY_PROMPT")

        assert captured == ["MY_PROMPT"]

    # ------------------------------------------------------------------
    # paste detection — second input() for review
    # ------------------------------------------------------------------

    def test_paste_triggers_review_prompt(self):
        """Paste detected: input() is called twice and hook is set then cleared."""
        paste_bytes = b"line two\nline three\n"
        # Second input() simulates user pressing Enter on the pre-filled display
        display_text = f"line one{_PASTE_NL}line two{_PASTE_NL}line three"
        input_calls = ["line one", display_text]

        with patch("builtins.input", side_effect=input_calls) as mock_input, \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook") as mock_hook, \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")

        # Two input() calls: first to capture initial line, second for review
        assert mock_input.call_count == 2
        # Hook set with a callable, then cleared
        assert mock_hook.call_count == 2
        assert mock_hook.call_args_list[-1] == call(None)
        # Newlines restored from \u21b5 placeholders
        assert result == "line one\nline two\nline three"

    def test_user_can_edit_paste_before_sending(self):
        """If user edits the display text, edited version is returned."""
        paste_bytes = b"original line two\n"
        # User deleted and retyped the second line
        edited = f"line one{_PASTE_NL}EDITED line two"
        input_calls = ["line one", edited]

        with patch("builtins.input", side_effect=input_calls), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook"), \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")

        assert result == "line one\nEDITED line two"

    def test_empty_lines_within_paste_preserved(self):
        """Blank lines inside a paste block round-trip correctly."""
        paste_bytes = b"\nsecond paragraph\n"
        display_text = f"first paragraph{_PASTE_NL}{_PASTE_NL}second paragraph"
        input_calls = ["first paragraph", display_text]

        with patch("builtins.input", side_effect=input_calls), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook"), \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")

        assert result == "first paragraph\n\nsecond paragraph"

    def test_crlf_line_endings_normalised(self):
        """Windows-style \\r\\n endings are normalised before review."""
        paste_bytes = b"line two\r\nline three\r\n"
        display_text = f"line one{_PASTE_NL}line two{_PASTE_NL}line three"
        input_calls = ["line one", display_text]

        with patch("builtins.input", side_effect=input_calls), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook"), \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")

        assert result == "line one\nline two\nline three"

    def test_eof_from_os_read_exits_loop_cleanly(self):
        """Empty bytes from os.read() (EOF) stops accumulation without error."""
        with patch("builtins.input", return_value="only line"), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", return_value=b""):
            ms.fileno.return_value = _FAKE_FD
            result = _read_paste_buffered("› ")

        assert result == "only line"

    # ------------------------------------------------------------------
    # readline hook safety
    # ------------------------------------------------------------------

    def test_hook_cleared_on_keyboard_interrupt_during_review(self):
        """readline hook is cleared even if user presses Ctrl+C during review."""
        paste_bytes = b"line two\n"

        with pytest.raises(KeyboardInterrupt), \
             patch("builtins.input", side_effect=["line one", KeyboardInterrupt()]), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=_fcntl_se()), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook") as mock_hook, \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            _read_paste_buffered("› ")

        assert mock_hook.call_args_list[-1] == call(None)

    # ------------------------------------------------------------------
    # fd flag restoration (invariant)
    # ------------------------------------------------------------------

    def test_fd_restored_to_blocking_single_line(self):
        """O_NONBLOCK is always cleared after reading, even with one line."""
        fcntl_calls = []

        def track_fcntl(fd, cmd, *args):
            fcntl_calls.append((fd, cmd, args))
            return _OLD_FL if cmd == fcntl.F_GETFL else None

        with patch("builtins.input", return_value="x"), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=track_fcntl), \
             patch("os.read", side_effect=BlockingIOError):
            ms.fileno.return_value = _FAKE_FD
            _read_paste_buffered("› ")

        assert fcntl_calls[2] == (_FAKE_FD, fcntl.F_SETFL, (_OLD_FL,))

    def test_fd_restored_on_bad_utf8(self):
        """fd is restored even when decode hits bad bytes (errors='replace')."""
        fcntl_calls = []

        def track_fcntl(fd, cmd, *args):
            fcntl_calls.append((fd, cmd, args))
            return _OLD_FL if cmd == fcntl.F_GETFL else None

        paste_bytes = b"line two\xff\xfe\n"
        display_text = f"line one{_PASTE_NL}line two��"
        input_calls = ["line one", display_text]

        with patch("builtins.input", side_effect=input_calls), \
             patch("sys.stdin") as ms, \
             patch("fcntl.fcntl", side_effect=track_fcntl), \
             patch("os.read", side_effect=[paste_bytes, BlockingIOError]), \
             patch("readline.set_pre_input_hook"), \
             patch("readline.insert_text"), \
             patch("readline.redisplay"):
            ms.fileno.return_value = _FAKE_FD
            _read_paste_buffered("› ")  # must not raise

        assert fcntl_calls[2] == (_FAKE_FD, fcntl.F_SETFL, (_OLD_FL,))


