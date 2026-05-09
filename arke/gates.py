"""Gates — deterministic step validators for Arke kernel v0.1.

Each gate checks post-execution output without raising exceptions.
Failures are logged as structured JSON and return False.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog

from arke.task_graph import Step

log = structlog.get_logger()


def validate(step: Step) -> bool:
    """Validate a step's output against its declared gate.

    Never raises. Returns ``False`` on any validation failure and
    emits a structured JSON log entry.

    Args:
        step: The step to validate (must have ``output`` populated).

    Returns:
        ``True`` if validation passes or no gate is declared.
    """
    if step.validation is None:
        return True

    gate_type = step.validation.type
    expected = step.validation.expected

    try:
        if gate_type == "file_exists":
            return _gate_file_exists(step, expected)
        if gate_type == "return_code":
            return _gate_return_code(step, expected)
        if gate_type == "json_schema":
            return _gate_json_schema(step, expected)

        log.error(
            "gate.unknown",
            step_id=step.id,
            gate_type=gate_type,
        )
        return False

    except Exception as exc:  # noqa: BLE001
        log.error(
            "gate.exception",
            step_id=step.id,
            gate_type=gate_type,
            error=str(exc),
        )
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _gate_file_exists(step: Step, expected: Any) -> bool:
    """Check that a file path exists on the filesystem."""
    path = str(expected)
    exists = os.path.exists(path)
    if not exists:
        log.error(
            "gate.file_exists.failed",
            step_id=step.id,
            path=path,
        )
    return exists


def _gate_return_code(step: Step, expected: Any) -> bool:
    """Check that the step output's ``return_code`` matches *expected*."""
    output = step.output
    if not isinstance(output, dict) or "return_code" not in output:
        log.error(
            "gate.return_code.missing",
            step_id=step.id,
            output=repr(output),
        )
        return False

    actual = output["return_code"]
    ok = actual == int(expected)
    if not ok:
        log.error(
            "gate.return_code.failed",
            step_id=step.id,
            expected=expected,
            actual=actual,
        )
    return ok


def _gate_json_schema(step: Step, expected: Any) -> bool:
    """Validate step output against a JSON Schema dict.

    *expected* must be a JSON Schema object (dict).
    """
    try:
        import jsonschema  # local import — optional heavy dep
    except ModuleNotFoundError:
        log.error("gate.json_schema.missing_dep", step_id=step.id)
        return False

    output = step.output
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError as exc:
            log.error(
                "gate.json_schema.invalid_json",
                step_id=step.id,
                error=str(exc),
            )
            return False

    try:
        jsonschema.validate(instance=output, schema=expected)
        return True
    except jsonschema.ValidationError as exc:
        # Build a human-readable field reference (e.g. "name" or "address.city")
        field = ".".join(str(p) for p in exc.absolute_path) if exc.absolute_path else None
        if field:
            human_msg = f"Schéma invalide : champ '{field}' — {exc.message}"
        else:
            # Missing required field: extract it from the message when possible
            # jsonschema emits "'field' is a required property"
            human_msg = f"Schéma invalide : {exc.message}"
        log.error(
            "gate.json_schema.failed",
            step_id=step.id,
            message=human_msg,
            field=field,
        )
        return False
