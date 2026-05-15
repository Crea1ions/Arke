from __future__ import annotations

from arke.security import check_command, is_blacklisted_path, is_safe_path
from arke.task_graph import Step
import arke.orchestrator as orch


def test_is_safe_path_inside_workspace(tmp_path):
    safe_file = tmp_path / "docs" / "note.txt"
    assert is_safe_path(safe_file, tmp_path) is True


def test_is_safe_path_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    assert is_safe_path(outside, tmp_path) is False


def test_is_blacklisted_path_for_system_path():
    assert is_blacklisted_path("/etc/passwd") is True


def test_is_blacklisted_path_for_workspace_file(tmp_path):
    assert is_blacklisted_path(tmp_path / "safe.txt") is False


def test_exec_fs_blocks_path_outside_workspace(tmp_path):
    step = Step(id="s1", tool="fs", arguments={"path": "../etc/passwd"})
    result = orch._exec_fs(step, {"WORKSPACE_ROOT": str(tmp_path)})
    assert result["return_code"] == 1
    assert "Path blocked outside workspace" in result["stderr"]


def test_exec_fs_reads_file_inside_workspace(tmp_path):
    file_path = tmp_path / "ok.txt"
    file_path.write_text("hello", encoding="utf-8")

    step = Step(id="s2", tool="fs", arguments={"path": "ok.txt"})
    result = orch._exec_fs(step, {"WORKSPACE_ROOT": str(tmp_path)})

    assert result["return_code"] == 0
    assert result["stdout"] == "hello"


def test_exec_fs_blocks_blacklisted_absolute_path_without_workspace_root():
    step = Step(id="s3", tool="fs", arguments={"path": "/etc/passwd"})
    result = orch._exec_fs(step, {})
    assert result["return_code"] == 1
    assert "Path blocked by security policy" in result["stderr"]


def test_exec_fs_blocks_symlink_pointing_outside_workspace(tmp_path):
    outside_file = tmp_path.parent / "outside-secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    link = tmp_path / "leak-link"
    link.symlink_to(outside_file)

    step = Step(id="s4", tool="fs", arguments={"path": "leak-link"})
    result = orch._exec_fs(step, {"WORKSPACE_ROOT": str(tmp_path)})
    assert result["return_code"] == 1
    assert "Path blocked outside workspace" in result["stderr"]


def test_check_command_allows_printf_from_whitelist():
    # Must not raise: printf is required for multi-line file creation via CLI.
    check_command('printf "ok\\n" > /workspace/test.txt')


def test_check_command_allows_tree_from_whitelist():
    # Must not raise: tree is a useful read-only inspection command.
    check_command('tree /workspace')


def test_exec_fs_accepts_workspace_alias(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    step = Step(id="s5", tool="fs", arguments={"path": "/workspace/note.txt"})
    result = orch._exec_fs(step, {"WORKSPACE_ROOT": str(tmp_path)})

    assert result["return_code"] == 0
    assert result["stdout"] == "hello"
