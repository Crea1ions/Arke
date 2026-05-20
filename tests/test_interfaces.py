"""Tests for S050 — M4: MyTeamHub token security hardening."""

from __future__ import annotations

import pytest


class TestMyTeamGatewayToken:
    """_init_myteam_state must raise RuntimeError if ARKE_MYTEAM_TOKEN is absent."""

    def test_raises_without_token(self, tmp_path, monkeypatch):
        """RuntimeError raised when ARKE_MYTEAM_TOKEN env var is not set."""
        monkeypatch.delenv("ARKE_MYTEAM_TOKEN", raising=False)

        from arke.interfaces.myteam_api import MyTeamGateway

        gw = MyTeamGateway()
        with pytest.raises(RuntimeError, match="ARKE_MYTEAM_TOKEN"):
            gw._init_myteam_state(tmp_path)

    def test_succeeds_with_token(self, tmp_path, monkeypatch):
        """No exception when ARKE_MYTEAM_TOKEN is set."""
        monkeypatch.setenv("ARKE_MYTEAM_TOKEN", "test-secure-token-value")

        from arke.interfaces.myteam_api import MyTeamGateway

        gw = MyTeamGateway()
        gw._init_myteam_state(tmp_path)  # must not raise

        state_file = tmp_path / ".arke" / "myteam" / "state.json"
        assert state_file.exists()

    def test_default_token_constant_removed(self):
        """DEFAULT_ARKE_LOCAL_TOKEN must not exist in the module."""
        import arke.interfaces.myteam_api as mod

        assert not hasattr(mod, "DEFAULT_ARKE_LOCAL_TOKEN"), (
            "Hardcoded default token constant must be removed (M4)"
        )

    def test_state_file_permissions_600(self, tmp_path, monkeypatch):
        """state.json written by _init_myteam_state must have permissions 600."""
        import stat

        monkeypatch.setenv("ARKE_MYTEAM_TOKEN", "test-token-for-perms")

        from arke.interfaces.myteam_api import MyTeamGateway

        gw = MyTeamGateway()
        gw._init_myteam_state(tmp_path)

        state_file = tmp_path / ".arke" / "myteam" / "state.json"
        mode = stat.S_IMODE(state_file.stat().st_mode)
        assert mode == 0o600, f"state.json has mode {oct(mode)}, expected 0o600"
