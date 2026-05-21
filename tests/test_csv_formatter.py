"""Tests for S051 V1 CSV formatter and mode-aware projection helpers."""

from __future__ import annotations

from arke.formatters.csv_formatter import format_csv_header_only, format_csv_rows


def test_format_csv_header_only():
    csv_text = format_csv_header_only(["a", "b"])
    assert csv_text == "a,b\r\n"


def test_format_csv_rows_handles_missing_values():
    csv_text = format_csv_rows(["a", "b", "c"], [{"a": "x", "c": "z"}])
    assert "a,b,c" in csv_text
    assert "x,,z" in csv_text


def test_format_csv_rows_quotes_multiline_and_commas():
    csv_text = format_csv_rows(
        ["text"],
        [{"text": "hello,world\nline2"}],
    )
    assert '"hello,world\nline2"' in csv_text


def test_chat_mode_columns_from_state_schema():
    import arke.chat as chat

    cols = chat._mode_csv_columns("ask")
    assert cols
    assert "mode" in cols
    assert "response_text" in cols


def test_chat_build_mode_csv_uses_declared_columns():
    import arke.chat as chat

    csv_text = chat._build_mode_csv(
        "agent",
        session_id="s-1",
        intention="fix bug",
        response_text="done",
        tool_requested="cli",
        status="ok",
    )
    header = csv_text.splitlines()[0]
    assert header == "mode,session_id,task,tool_requested,status,response_text"
    assert "agent,s-1,fix bug,cli,done,done" in csv_text


def test_chat_build_mode_csv_agent_status_canonicalization():
    import arke.chat as chat

    csv_text = chat._build_mode_csv(
        "agent",
        session_id="s-3",
        intention="run checks",
        response_text="in progress",
        tool_requested="cli",
        status="running",
    )
    assert "agent,s-3,run checks,cli,in_progress,in progress" in csv_text


def test_chat_build_mode_csv_plan_header_prioritizes_next_action():
    import arke.chat as chat

    csv_text = chat._build_mode_csv(
        "plan",
        session_id="s-4",
        intention="prepare release",
        response_text="1. Créer branche\n2. Exécuter tests",
    )
    assert csv_text.splitlines()[0] == "mode,session_id,goal,next_action,steps_count,response_text"


def test_chat_build_mode_csv_unknown_mode_header_only_fallback():
    import arke.chat as chat

    csv_text = chat._build_mode_csv(
        "unknown",
        session_id="s-2",
        intention="q",
        response_text="r",
    )
    assert csv_text.splitlines()[0] == "mode,session_id,input_text,response_text"
