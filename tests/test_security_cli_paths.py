from __future__ import annotations

import shlex
from pathlib import Path

import pytest

import arke.orchestrator as orch
import arke.security as sec
from arke.task_graph import Step


def test_normalize_cli_command_paths_maps_relative_to_workspace(tmp_path):
    target = tmp_path / "logs" / "app.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok", encoding="utf-8")

    cmd = sec.normalize_cli_command_paths("cat ./logs/app.log", tmp_path)
    assert cmd == "cat /workspace/logs/app.log"


def test_normalize_cli_command_paths_blocks_outside_workspace(tmp_path):
    with pytest.raises(ValueError, match="outside workspace"):
        sec.normalize_cli_command_paths("cat ../secret.txt", tmp_path)


def test_normalize_cli_command_paths_blocks_blacklisted_absolute(tmp_path):
    with pytest.raises(ValueError, match="security policy"):
        sec.normalize_cli_command_paths("cat /etc/passwd", tmp_path)


def test_normalize_cli_command_paths_blocks_relative_symlink_escape(tmp_path):
    outside_file = tmp_path.parent / "outside-link-target.txt"
    outside_file.write_text("secret", encoding="utf-8")

    link = tmp_path / "links" / "escape"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside_file)

    with pytest.raises(ValueError, match="outside workspace"):
        sec.normalize_cli_command_paths("cat ./links/escape", tmp_path)


def test_exec_cli_normalizes_paths_before_sandbox(monkeypatch, tmp_path):
    import arke.sandbox as sb

    observed: dict[str, str] = {}

    def _fake_run(command, timeout=30, *, sandbox_enabled=True, workspace_root=None):
        observed["command"] = command
        return {"return_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(sb, "load_sandbox_config", lambda: {"enabled": False})
    monkeypatch.setattr(sb, "sandboxed_run", _fake_run)
    monkeypatch.setattr(sec, "check_command", lambda command: None)

    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    step = Step(id="c1", tool="cli", arguments={"command": "cat ./file.txt"})
    result = orch._exec_cli(step, {"WORKSPACE_ROOT": str(tmp_path)})

    assert result["return_code"] == 0
    assert observed["command"] == "cat /workspace/file.txt"


def test_normalize_cli_command_paths_option_value_normalized(tmp_path):
    p = tmp_path / "out.txt"
    p.write_text("x", encoding="utf-8")

    cmd = sec.normalize_cli_command_paths("echo hello --output=./out.txt", tmp_path)
    assert cmd == "echo hello --output=/workspace/out.txt"


def test_normalize_cli_command_paths_pipeline_without_spaces(tmp_path):
    target = tmp_path / "log.txt"
    target.write_text("line", encoding="utf-8")

    cmd = sec.normalize_cli_command_paths("cat ./log.txt|wc -l", tmp_path)
    assert cmd == "cat /workspace/log.txt | wc -l"


def test_normalize_cli_command_paths_nested_shell_fragment(tmp_path):
    target = tmp_path / "nested.txt"
    target.write_text("line", encoding="utf-8")

    cmd = sec.normalize_cli_command_paths('bash -lc "cat ./nested.txt|wc -l"', tmp_path)
    parts = shlex.split(cmd)
    assert parts[0] == "bash"
    assert parts[1] == "-lc"
    assert parts[2] == "cat /workspace/nested.txt | wc -l"


def test_normalize_cli_command_paths_nested_fragment_blocks_escape(tmp_path):
    with pytest.raises(ValueError, match="outside workspace"):
        sec.normalize_cli_command_paths('bash -lc "cat ../secret.txt | wc -l"', tmp_path)


def test_normalize_cli_command_paths_accepts_workspace_alias(tmp_path):
    target = tmp_path / "alias.txt"
    target.write_text("ok", encoding="utf-8")

    cmd = sec.normalize_cli_command_paths("cat /workspace/alias.txt", tmp_path)
    assert cmd == "cat /workspace/alias.txt"


def test_normalize_cli_command_paths_blocks_workspace_alias_escape(tmp_path):
    with pytest.raises(ValueError, match="outside workspace"):
        sec.normalize_cli_command_paths("cat /workspace/../secret.txt", tmp_path)


def test_normalize_cli_command_paths_keeps_brace_expansion(tmp_path):
    cmd = sec.normalize_cli_command_paths(
        "mkdir -p /workspace/site-static/{assets/{css,js,images},pages/blog}",
        tmp_path,
    )
    assert "{assets/{css,js,images},pages/blog}" in cmd
    assert "'" not in cmd


def test_normalize_cli_command_paths_expands_tilde(tmp_path):
    # Simule un $HOME fictif pour l'utilisateur
    import os
    home = str(tmp_path / "homeuser")
    os.makedirs(home, exist_ok=True)
    # Crée un sous-dossier cible
    target = Path(home) / "dev" / "Arke-Agent-workspace"
    target.mkdir(parents=True, exist_ok=True)
    # Force la variable d'environnement HOME
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        # Commande avec tilde
        cmd = sec.normalize_cli_command_paths(f"mkdir -p ~{'/dev/Arke-Agent-workspace'}", home)
        # Le chemin doit être mappé dans /workspace
        assert "/workspace/dev/Arke-Agent-workspace" in cmd
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            del os.environ["HOME"]


def test_normalize_cli_command_paths_does_not_treat_html_payload_as_path(tmp_path):
    cmd = sec.normalize_cli_command_paths(
        "printf '<!DOCTYPE html><html></html>' > /workspace/site-static/index.html",
        tmp_path,
    )
    assert "printf" in cmd
    assert "<!DOCTYPE html><html></html>" in cmd
    assert "/workspace/site-static/index.html" in cmd


def test_exec_cli_allows_printf_payload_with_redirect(monkeypatch, tmp_path):
    import arke.sandbox as sb

    observed: dict[str, str] = {}

    def _fake_run(command, timeout=30, *, sandbox_enabled=True, workspace_root=None):
        observed["command"] = command
        return {"return_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(sb, "load_sandbox_config", lambda: {"enabled": False})
    monkeypatch.setattr(sb, "sandboxed_run", _fake_run)
    monkeypatch.setattr(sec, "check_command", lambda command: None)

    step = Step(
        id="c2",
        tool="cli",
        arguments={
            "command": "printf '<!DOCTYPE html><html></html>' > /workspace/site-static/index.html"
        },
    )
    result = orch._exec_cli(step, {"WORKSPACE_ROOT": str(tmp_path)})

    assert result["return_code"] == 0
    assert "/workspace/site-static/index.html" in observed["command"]
