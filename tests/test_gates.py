"""Unit tests for arke.gates (P1.2)."""

from __future__ import annotations

import pytest

from arke.gates import validate
from arke.task_graph import Step, StepStatus, Validation


def _step(gate_type: str, expected, output) -> Step:
    return Step(
        id="s1",
        tool="cli",
        arguments={},
        validation=Validation(type=gate_type, expected=expected),
        output=output,
    )


class TestFileExists:
    def test_passes_for_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("ok")
        step = _step("file_exists", str(f), None)
        assert validate(step) is True

    def test_fails_for_missing_file(self, tmp_path):
        step = _step("file_exists", str(tmp_path / "missing.txt"), None)
        assert validate(step) is False


class TestReturnCode:
    def test_passes_when_code_matches(self):
        step = _step("return_code", 0, {"return_code": 0, "stdout": "ok", "stderr": ""})
        assert validate(step) is True

    def test_fails_when_code_differs(self):
        step = _step("return_code", 0, {"return_code": 1, "stdout": "", "stderr": "err"})
        assert validate(step) is False

    def test_fails_when_output_missing_key(self):
        step = _step("return_code", 0, {"stdout": "ok"})
        assert validate(step) is False

    def test_fails_when_output_is_string(self):
        step = _step("return_code", 0, "plain string")
        assert validate(step) is False


class TestJsonSchema:
    def test_passes_valid_object(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        step = _step("json_schema", schema, {"name": "Arke"})
        assert validate(step) is True

    def test_fails_invalid_object(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        step = _step("json_schema", schema, {"age": 42})
        assert validate(step) is False

    def test_parses_json_string(self):
        import json

        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        step = _step("json_schema", schema, json.dumps({"x": 1}))
        assert validate(step) is True

    def test_fails_malformed_json_string(self):
        schema = {"type": "object"}
        step = _step("json_schema", schema, "{not valid json}")
        assert validate(step) is False


class TestNoGate:
    def test_always_passes_when_no_validation(self):
        step = Step(id="s1", tool="cli", arguments={}, validation=None, output={"return_code": 1})
        assert validate(step) is True


class TestUnknownGate:
    def test_fails_gracefully(self):
        step = _step("unknown_gate_type", None, None)
        assert validate(step) is False
