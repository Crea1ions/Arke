from __future__ import annotations

import arke.memory.manager as mem_mod
from arke.memory.manager import MemoryManager
from arke.orchestrator import _exec_sqlite
from arke.task_graph import Step


def _mm_with_tmp_dbs(tmp_path, monkeypatch) -> MemoryManager:
    monkeypatch.setattr(
        mem_mod,
        "_load_db_paths",
        lambda: {
            "global": tmp_path / "global.db",
            "project": tmp_path / "project.db",
            "session": tmp_path / "session.db",
            "cache": tmp_path / "cache.db",
        },
    )
    return MemoryManager()


def test_sqlite_compat_rewrites_message_column_for_chat_history(tmp_path, monkeypatch):
    mm = _mm_with_tmp_dbs(tmp_path, monkeypatch)
    mm.query(
        "session",
        "INSERT INTO chat_history (role, content, model_used) VALUES (?, ?, ?)",
        ("user", "poeme: Le Laboureur et ses enfants", "flash"),
    )
    day = mm.query("session", "SELECT date(timestamp) AS d FROM chat_history ORDER BY id DESC LIMIT 1", ())[0]["d"]

    step = Step(
        id="step_1",
        tool="sqlite",
        arguments={
            "db": "session",
            "query": "SELECT message FROM chat_history WHERE date(timestamp) = ?",
            "params": (day,),
        },
    )
    out = _exec_sqlite(step)

    assert out["return_code"] == 0
    assert "Laboureur" in out["stdout"]


def test_sqlite_compat_rewrites_bare_date_column_for_chat_history(tmp_path, monkeypatch):
    mm = _mm_with_tmp_dbs(tmp_path, monkeypatch)
    mm.query(
        "session",
        "INSERT INTO chat_history (role, content) VALUES (?, ?)",
        ("user", "discussion sur La Fontaine"),
    )
    day = mm.query("session", "SELECT date(timestamp) AS d FROM chat_history ORDER BY id DESC LIMIT 1", ())[0]["d"]

    step = Step(
        id="step_1",
        tool="sqlite",
        arguments={
            "db": "session",
            "query": "SELECT content FROM chat_history WHERE date = ?",
            "params": (day,),
        },
    )
    out = _exec_sqlite(step)

    assert out["return_code"] == 0
    assert "La Fontaine" in out["stdout"]
