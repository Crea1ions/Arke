"""Regression tests for deterministic project-memory responses."""

from __future__ import annotations

from arke.chat import _build_project_memory_response, _is_project_memory_request


class _FakeMemoryManager:
    def __init__(self, rows):
        self._rows = rows

    def query(self, db, query, params):  # noqa: ANN001
        return self._rows


def test_project_memory_request_detection():
    assert _is_project_memory_request("Quel est ton dernier projet ?") is True
    assert _is_project_memory_request("What is your last project?") is True
    assert _is_project_memory_request("Liste les fichiers du dossier") is False


def test_build_project_memory_response_when_empty():
    mm = _FakeMemoryManager(rows=[])
    response = _build_project_memory_response(mm)
    assert "aucun projet mémorisé" in response.lower()


def test_build_project_memory_response_when_present():
    mm = _FakeMemoryManager(rows=[{"value": "Arke Session 037 hardening"}])
    response = _build_project_memory_response(mm)
    assert "Arke Session 037 hardening" in response
    assert "dernier projet mémorisé" in response.lower()
