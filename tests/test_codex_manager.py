from __future__ import annotations

from pathlib import Path

import pytest

from arke.codex.manager import (
    append_codex_entry,
    ensure_codex_files,
    get_codex_for_mode,
    get_codex_paths,
    load_codex,
)


def test_ensure_codex_files_creates_both_yaml(tmp_path: Path):
    created = ensure_codex_files(tmp_path)
    paths = get_codex_paths(tmp_path)

    assert paths["ask"].exists()
    assert paths["opt"].exists()
    assert len(created) == 2


def test_load_codex_ask_has_required_sections(tmp_path: Path):
    ensure_codex_files(tmp_path)
    ask = load_codex("ask", tmp_path)

    assert ask["version"] == "1.0"
    assert "metadata" in ask
    assert isinstance(ask["axioms"], list)
    assert isinstance(ask["theoria"], list)


def test_append_codex_entry_updates_section(tmp_path: Path):
    ensure_codex_files(tmp_path)
    append_codex_entry("opt", tmp_path, "nomos", "Toujours valider avant merge.")
    opt = load_codex("opt", tmp_path)

    assert "Toujours valider avant merge." in opt["nomos"]


def test_append_codex_entry_rejects_unknown_section(tmp_path: Path):
    ensure_codex_files(tmp_path)
    with pytest.raises(ValueError, match="Section invalide"):
        append_codex_entry("ask", tmp_path, "nomos", "x")


def test_get_codex_for_mode_maps_ask_and_agent(tmp_path: Path):
    ensure_codex_files(tmp_path)

    ask_ctx = get_codex_for_mode("ask", tmp_path)
    agent_ctx = get_codex_for_mode("agent", tmp_path)

    assert ask_ctx["kind"] == "ask"
    assert agent_ctx["kind"] == "opt"
