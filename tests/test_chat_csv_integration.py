"""Integration tests for S051 V1 CSV snapshots in arke.chat.

Verifies explicit writes of csv_last_input and csv_last_output by mode.
"""

from __future__ import annotations

import pytest

import arke.memory.manager as memory_mod
from arke.memory.manager import MemoryManager


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    """MemoryManager wired to temporary SQLite files."""
    monkeypatch.setattr(
        memory_mod,
        "_load_db_paths",
        lambda: {
            "global": tmp_path / "global.db",
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    return MemoryManager()


@pytest.mark.parametrize("mode", ["ask", "search", "plan", "agent"])
def test_chat_persists_csv_input_and_output_by_mode(mm: MemoryManager, mode: str):
    """Each mode must write csv_last_input and csv_last_output keys."""
    import arke.chat as chat

    session_id = f"s-{mode}"
    intention = f"intention {mode}"
    response = f"response {mode}"

    input_csv = chat._build_mode_csv(
        mode,
        session_id=session_id,
        intention=intention,
        response_text="",
        status="input",
    )
    output_csv = chat._build_mode_csv(
        mode,
        session_id=session_id,
        intention=intention,
        response_text=response,
        tool_requested="cli" if mode == "agent" else "",
        status="done" if mode == "agent" else "ok",
    )

    chat._persist_session_csv(mm, "csv_last_input", input_csv)
    chat._persist_session_csv(mm, "csv_last_output", output_csv)

    in_rows = mm.query(
        "session",
        "SELECT value FROM session_context WHERE key = 'csv_last_input'",
        (),
    )
    out_rows = mm.query(
        "session",
        "SELECT value FROM session_context WHERE key = 'csv_last_output'",
        (),
    )

    assert in_rows and out_rows
    in_csv = in_rows[0]["value"]
    out_csv = out_rows[0]["value"]

    expected_header = ",".join(chat._mode_csv_columns(mode))
    assert in_csv.splitlines()[0] == expected_header
    assert out_csv.splitlines()[0] == expected_header
    assert f"{mode},{session_id}" in in_csv
    assert f"{mode},{session_id}" in out_csv


def test_chat_csv_snapshot_keys_are_replaced_not_duplicated(mm: MemoryManager):
    """Repeated writes must replace the same session_context keys."""
    import arke.chat as chat

    csv_a = chat._build_mode_csv(
        "search",
        session_id="s-1",
        intention="first",
        response_text="first response",
    )
    csv_b = chat._build_mode_csv(
        "search",
        session_id="s-2",
        intention="second",
        response_text="second response",
    )

    chat._persist_session_csv(mm, "csv_last_output", csv_a)
    chat._persist_session_csv(mm, "csv_last_output", csv_b)

    rows = mm.query(
        "session",
        "SELECT value FROM session_context WHERE key = 'csv_last_output'",
        (),
    )
    assert len(rows) == 1
    assert "s-2" in rows[0]["value"]
    assert "s-1" not in rows[0]["value"]
