from __future__ import annotations

from pathlib import Path
import json
from unittest.mock import patch

from arke.init_workspace import ensure_arke_workspace


def test_ensure_arke_workspace_creates_expected_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    result = ensure_arke_workspace()

    assert result.created is True
    assert (tmp_path / ".arke").exists()
    assert (tmp_path / ".arke" / "config").exists()
    assert (tmp_path / ".arke" / "sessions").exists()
    assert (tmp_path / ".arke" / "logs").exists()
    assert (tmp_path / ".arke" / "memory").exists()
    assert (tmp_path / ".arke" / "state.json").exists()
    state_content = (tmp_path / ".arke" / "state.json").read_text(encoding="utf-8")
    assert '"last_synced_workspace": null' in state_content
    assert (tmp_path / ".arke" / "config" / "workspace.toml").exists()
    assert (tmp_path / ".gitignore").exists()
    assert ".arke/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_ensure_arke_workspace_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    first = ensure_arke_workspace()
    second = ensure_arke_workspace()

    assert first.created is True
    assert second.created is False
    assert second.warnings == []


def test_ensure_arke_workspace_gitignore_no_duplicate(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".arke/\n", encoding="utf-8")

    ensure_arke_workspace(tmp_path)

    lines = [line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()]
    assert lines.count(".arke/") == 1


def test_ensure_arke_workspace_adds_missing_last_synced_workspace_key(tmp_path):
    arke_root = tmp_path / ".arke"
    arke_root.mkdir(parents=True)
    legacy_state = arke_root / "state.json"
    legacy_state.write_text(
        '{\n  "workspace_initialized": true,\n  "initialized_at": "2026-05-16T00:00:00+00:00"\n}\n',
        encoding="utf-8",
    )

    ensure_arke_workspace(tmp_path)

    updated = legacy_state.read_text(encoding="utf-8")
    assert '"last_synced_workspace": null' in updated


def test_legacy_migration_prompt_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    # Create a fake legacy source so migration prompt path is exercised.
    legacy_dir = tmp_path / "arke-workspace"
    (legacy_dir / "sessions").mkdir(parents=True)

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=AssertionError("prompt should not be called")):
        ensure_arke_workspace(tmp_path)


def test_legacy_migration_decline_is_persisted_when_prompt_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARKE_ENABLE_LEGACY_MIGRATION_PROMPT", "1")

    # Create a fake legacy source so migration prompt path is exercised.
    legacy_dir = tmp_path / "arke-workspace"
    (legacy_dir / "sessions").mkdir(parents=True)

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="N") as prompt:
        ensure_arke_workspace(tmp_path)
        assert prompt.call_count == 1

    # Second run should not ask again because decline is persisted.
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=AssertionError("prompt should not be called")):
        ensure_arke_workspace(tmp_path)

    state = json.loads((tmp_path / ".arke" / "state.json").read_text(encoding="utf-8"))
    assert state["legacy_migration"]["prompted"] is True
    assert state["legacy_migration"]["accepted"] is False
