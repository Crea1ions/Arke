from __future__ import annotations

import json

from arke.session.state_manager import SessionStateManager


def test_session_id_uses_uuid_suffix(tmp_path):
    arke_root = tmp_path / ".arke"
    arke_root.mkdir(parents=True)

    mgr = SessionStateManager(arke_root)

    assert mgr.session_id.startswith("session_")
    parts = mgr.session_id.split("_")
    assert len(parts) == 3
    assert len(parts[1]) == 14
    assert len(parts[2]) == 8


def test_session_state_lock_file_created(tmp_path):
    arke_root = tmp_path / ".arke"
    arke_root.mkdir(parents=True)

    SessionStateManager(arke_root)

    assert (arke_root / "state.lock").exists()


def test_state_checkpoint_persists_with_lock(tmp_path):
    arke_root = tmp_path / ".arke"
    arke_root.mkdir(parents=True)

    mgr = SessionStateManager(arke_root)
    mgr.record_message()
    mgr.checkpoint()

    state = json.loads((arke_root / "state.json").read_text(encoding="utf-8"))
    assert state["messages_count"] == 1
    assert state["last_checkpoint_step"] == 1
