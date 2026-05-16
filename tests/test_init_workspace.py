from __future__ import annotations

from pathlib import Path

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
