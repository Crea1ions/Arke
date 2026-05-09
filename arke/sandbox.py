"""Sandbox — wraps shell commands with bubblewrap for read-only filesystem isolation.

When ``bwrap`` is available and sandbox is enabled, every CLI command is
executed inside a bubblewrap container with:

- ``--ro-bind / /``  — the host root mounted read-only
- ``--dev /dev``     — fresh ``/dev`` (no access to host device files)
- ``--tmpfs /tmp``   — writable tmpfs for the session
- ``--unshare-pid``  — isolated PID namespace
- ``--die-with-parent`` — container dies when parent process exits

If ``bwrap`` is not installed, execution falls back to the unsandboxed
``subprocess.run`` path and a ``UserWarning`` is emitted.

Config (arke.toml)::

    [sandbox]
    enabled = true   # set false to disable (not recommended)
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import warnings
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "arke.toml"

# Cached availability check
_bwrap_available: bool | None = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_sandbox_config() -> dict:
    """Read ``[sandbox]`` section from *arke.toml*."""
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh).get("sandbox", {})
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def is_bwrap_available() -> bool:
    """Return ``True`` if :command:`bwrap` is installed and on ``$PATH``."""
    global _bwrap_available
    if _bwrap_available is None:
        _bwrap_available = shutil.which("bwrap") is not None
    return _bwrap_available


def _reset_availability_cache() -> None:
    """Reset the bwrap availability cache (used in tests only)."""
    global _bwrap_available
    _bwrap_available = None


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def sandboxed_run(
    command: str,
    timeout: int = 30,
    *,
    sandbox_enabled: bool = True,
) -> dict[str, Any]:
    """Execute *command* optionally inside a bubblewrap read-only sandbox.

    Args:
        command: Shell command string (must be pre-validated by
            :func:`arke.security.check_command` before calling this function).
        timeout: Maximum wall-clock time in seconds.
        sandbox_enabled: When ``False`` the sandbox is bypassed regardless of
            whether ``bwrap`` is installed.

    Returns:
        Dict with keys ``return_code`` (int), ``stdout`` (str), ``stderr`` (str).

    Raises:
        subprocess.TimeoutExpired: If the command exceeds *timeout* seconds.
    """
    use_sandbox = sandbox_enabled and is_bwrap_available()

    if sandbox_enabled and not is_bwrap_available():
        warnings.warn(
            "bubblewrap (bwrap) not found — running without sandbox. "
            "Install bwrap for read-only filesystem isolation.",
            UserWarning,
            stacklevel=2,
        )

    if use_sandbox:
        argv = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--tmpfs", "/tmp",  # noqa: S108
            "--unshare-pid",
            "--die-with-parent",
            "--",
            "sh", "-c", command,
        ]
        result = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    else:
        result = subprocess.run(  # noqa: S603
            command,
            shell=True,  # noqa: S602
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return {
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
