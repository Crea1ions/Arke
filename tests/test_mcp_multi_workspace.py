from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import arke.mcp_cache as mcp_cache_mod
from arke.orchestrator import _exec_mcp
from arke.task_graph import Step


class _NoCache:
    def get(self, tool_name, tool_args):  # noqa: ARG002
        return None

    def put(self, tool_name, tool_args, response):  # noqa: ARG002
        return None


def _step() -> Step:
    return Step(
        id="step_1",
        tool="mcp",
        arguments={
            "_server": "web_search",
            "tool_name": "web_search",
            "tool_args": {"query": "test"},
        },
    )


def test_exec_mcp_resolves_paths_against_arke_root(monkeypatch):
    arke_root = Path(__file__).resolve().parents[1]
    script_path = arke_root / "arke/interfaces/mcp_servers/web_search.py"

    monkeypatch.setattr(mcp_cache_mod, "McpCache", _NoCache)

    def _fake_load(_fh):  # noqa: ARG001
        return {
            "mcp_servers": {
                "web_search": {
                    "enabled": True,
                    "command": ".venv/bin/python",
                    "args": ["arke/interfaces/mcp_servers/web_search.py", "--stdio"],
                    "timeout": 30,
                }
            }
        }

    monkeypatch.setattr("tomllib.load", _fake_load)

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": {"content": [{"text": "{\"ok\": true}"}]}}),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)

    out = _exec_mcp(_step())

    assert out["return_code"] == 0
    assert '"ok": true' in out["stdout"]

    expected_python = (arke_root / ".venv/bin/python").resolve()
    expected_script = script_path.resolve()

    assert captured["cwd"] == str(arke_root)
    assert captured["cmd"][0] == str(expected_python)
    assert captured["cmd"][1] == str(expected_script)
    assert captured["cmd"][2] == "--stdio"


def test_exec_mcp_falls_back_to_current_python_if_binary_missing(monkeypatch):
    arke_root = Path(__file__).resolve().parents[1]

    monkeypatch.setattr(mcp_cache_mod, "McpCache", _NoCache)

    def _fake_load(_fh):  # noqa: ARG001
        return {
            "mcp_servers": {
                "web_search": {
                    "enabled": True,
                    "command": ".venv/bin/python-missing",
                    "args": ["arke/interfaces/mcp_servers/web_search.py", "--stdio"],
                    "timeout": 30,
                }
            }
        }

    monkeypatch.setattr("tomllib.load", _fake_load)

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": {"content": [{"text": "{\"ok\": true}"}]}}),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)

    out = _exec_mcp(_step())

    assert out["return_code"] == 0
    assert captured["cwd"] == str(arke_root)
    assert captured["cmd"][0] == sys.executable


def test_exec_mcp_rejects_fallback_on_unsupported_python(monkeypatch):
    monkeypatch.setattr(mcp_cache_mod, "McpCache", _NoCache)

    def _fake_load(_fh):  # noqa: ARG001
        return {
            "mcp_servers": {
                "web_search": {
                    "enabled": True,
                    "command": ".venv/bin/python-missing",
                    "args": ["arke/interfaces/mcp_servers/web_search.py", "--stdio"],
                    "timeout": 30,
                }
            }
        }

    monkeypatch.setattr("tomllib.load", _fake_load)
    monkeypatch.setattr("arke.orchestrator._is_supported_python_for_mcp_fallback", lambda: False)

    out = _exec_mcp(_step())

    assert out["return_code"] == 1
    assert "unsupported" in out["stderr"].lower()
