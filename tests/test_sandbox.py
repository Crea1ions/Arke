"""Tests for S050 — C2: SandboxFallbackError when allow_fallback=false."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from arke.sandbox import SandboxFallbackError, sandboxed_run


class TestSandboxFallbackError:
    """SandboxFallbackError raised when bwrap fails and allow_fallback=false."""

    def _make_bwrap_failure(self) -> MagicMock:
        """subprocess.run result that looks like a bwrap runtime permission error."""
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "bwrap: failed rtm_newaddr operation not permitted"
        return result

    def test_raises_when_fallback_disabled(self):
        """SandboxFallbackError raised when allow_fallback=false in config."""
        with (
            patch("arke.sandbox.is_bwrap_available", return_value=True),
            patch("arke.sandbox.load_sandbox_config", return_value={
                "mode": "workspace",
                "allow_fallback": False,
            }),
            patch("arke.sandbox._build_workspace_argv", return_value=["bwrap", "echo", "hi"]),
            patch("arke.sandbox._load_allowed_dirs", return_value=[]),
            patch("subprocess.run", return_value=self._make_bwrap_failure()),
        ):
            with pytest.raises(SandboxFallbackError, match="allow_fallback"):
                sandboxed_run("echo hi")

    def test_warns_when_fallback_allowed(self, tmp_path):
        """UserWarning emitted (not raised) when allow_fallback=true and bwrap fails."""
        unsandboxed_result = MagicMock()
        unsandboxed_result.returncode = 0
        unsandboxed_result.stdout = "hi"
        unsandboxed_result.stderr = ""

        with (
            patch("arke.sandbox.is_bwrap_available", return_value=True),
            patch("arke.sandbox.load_sandbox_config", return_value={
                "mode": "workspace",
                "allow_fallback": True,
            }),
            patch("arke.sandbox._build_workspace_argv", return_value=["bwrap", "echo", "hi"]),
            patch("arke.sandbox._load_allowed_dirs", return_value=[]),
            patch("subprocess.run", return_value=self._make_bwrap_failure()),
            patch("arke.sandbox._run_unsandboxed", return_value=unsandboxed_result),
        ):
            import warnings

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = sandboxed_run("echo hi")

            assert any(issubclass(w.category, UserWarning) for w in caught), (
                "Expected UserWarning when fallback is allowed"
            )

    def test_sandbox_fallback_error_is_runtime_error(self):
        """SandboxFallbackError must be a RuntimeError subclass."""
        assert issubclass(SandboxFallbackError, RuntimeError)
