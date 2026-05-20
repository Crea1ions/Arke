"""Sandbox -- wraps shell commands with bubblewrap for filesystem isolation.

Two isolation modes (controlled by ``arke.toml [sandbox] mode``):

``full`` (legacy default)
    The host root is mounted read-only (``--ro-bind / /``).  The agent can
    read all files on the system but cannot write anywhere except ``/tmp``.

``workspace`` (recommended)
    The host root is **not** mounted.  Only the minimal set of system paths
    required to execute shell commands is exposed read-only (``/usr``,
    ``/bin``, ``/lib``, ``/lib64``, ``/etc/passwd``, ``/etc/hosts``,
    ``/etc/resolv.conf``, ``/etc/ssl``, ``/etc/ca-certificates``).  The
    agent's writable working directory is ``~/arke-agent-workspace``, mounted
    at ``/workspace`` inside the container.  Additional read-only host
    directories can be listed in ``config/security.toml``
    ``[[workspace.allowed_dirs]]``.

If ``bwrap`` is not installed, execution falls back to the unsandboxed
``subprocess.run`` path and a ``UserWarning`` is emitted.

Config (arke.toml)::

    [sandbox]
    enabled = true
    mode    = "workspace"   # or "full"
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
import warnings
from pathlib import Path
from typing import Any


class SandboxFallbackError(RuntimeError):
    """Raised when bubblewrap fails at runtime and allow_fallback is false."""


_CONFIG_PATH = Path(__file__).parent.parent / "config" / "arke.toml"
_SECURITY_PATH = Path(__file__).parent.parent / "config" / "security.toml"

# Dedicated agent workspace -- the only writable location in workspace mode.
AGENT_WORKSPACE = Path.home() / "arke-agent-workspace"

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


def _load_allowed_dirs() -> list[dict]:
    """Return the ``[[workspace.allowed_dirs]]`` list from *security.toml*.

    Each entry is a dict with at least a ``"path"`` key and an optional
    ``"read_only"`` bool (defaults to ``True``).
    """
    try:
        with open(_SECURITY_PATH, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("workspace", {}).get("allowed_dirs", [])
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------


def _resolve_workspace_root(workspace_root: str | Path | None) -> Path:
    """Resolve the effective workspace root for command execution."""
    if workspace_root is None:
        return AGENT_WORKSPACE
    root = Path(workspace_root).expanduser()
    if not root.is_absolute():
        root = root.resolve()
    return root


def _ensure_workspace(workspace_root: str | Path | None = None) -> Path:
    """Create the agent workspace tree if it does not exist."""
    root = _resolve_workspace_root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(exist_ok=True)
    (root / "output").mkdir(exist_ok=True)
    return root


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
# bwrap argv builders
# ---------------------------------------------------------------------------

# System paths that are always mounted read-only in workspace mode.
_WORKSPACE_SYS_BINDS: list[str] = [
    "/usr",
    "/bin",
    "/etc/passwd",
    "/etc/group",
    "/etc/hosts",
    "/etc/resolv.conf",
]

# Optional paths -- skipped silently if absent on the current system.
_WORKSPACE_SYS_OPTIONAL: list[str] = [
    "/lib",
    "/lib64",
    "/etc/ssl",
    "/etc/ca-certificates",
]


def _build_workspace_argv(
    command: str,
    allowed_dirs: list[dict],
    workspace_root: str | Path | None = None,
) -> list[str]:
    """Build a minimal-privilege bwrap argv for workspace isolation mode."""
    effective_workspace = _ensure_workspace(workspace_root)

    argv: list[str] = [
        "bwrap",
        "--unshare-pid",
        "--unshare-net",
        "--tmpfs", "/tmp",  # noqa: S108
        "--proc", "/proc",
        "--dev", "/dev",
        # Workspace: writable agent sandbox mounted at /workspace
        "--bind", str(effective_workspace), "/workspace",
        "--chdir", "/workspace",
    ]

    # Mandatory system read-only binds
    for path in _WORKSPACE_SYS_BINDS:
        if os.path.exists(path):
            argv += ["--ro-bind", path, path]

    # Optional system paths (skip if absent)
    for path in _WORKSPACE_SYS_OPTIONAL:
        if os.path.exists(path):
            argv += ["--ro-bind", path, path]

    # User-configured additional read-only directories
    for entry in allowed_dirs:
        host_path = os.path.expanduser(entry.get("path", ""))
        if not host_path or not os.path.exists(host_path):
            continue
        # Safety: block home root and / to prevent accidental full exposure
        if host_path in ("/", str(Path.home())):
            continue
        argv += ["--ro-bind", host_path, host_path]

    argv += ["--die-with-parent", "--", "sh", "-c", command]
    return argv


def _build_full_argv(command: str) -> list[str]:
    """Build the legacy full-system read-only bwrap argv."""
    return [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--tmpfs", "/tmp",  # noqa: S108
        "--unshare-pid",
        "--die-with-parent",
        "--",
        "sh", "-c", command,
    ]


def _run_unsandboxed(
    command: str,
    timeout: int,
    workspace_root: str | Path | None,
) -> subprocess.CompletedProcess[str]:
    """Run command without bwrap, constrained to the effective workspace cwd."""
    effective_workspace = _ensure_workspace(workspace_root)
    workspace_host = effective_workspace.as_posix().rstrip("/")
    # In fallback mode, /workspace does not exist on host FS.
    # Remap sandbox alias to the real host workspace path.
    remapped = command.replace("/workspace/", f"{workspace_host}/")
    remapped = re.sub(r"(?<!\S)/workspace(?!\S)", workspace_host, remapped)
    return subprocess.run(  # noqa: S603
        remapped,
        shell=True,  # noqa: S602
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(effective_workspace),
    )


def _is_bwrap_runtime_permission_error(stderr: str) -> bool:
    """Detect bwrap runtime capability failures that should trigger fallback."""
    text = (stderr or "").lower()
    if "bwrap:" not in text:
        return False
    return "failed rtm_newaddr" in text or "operation not permitted" in text


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def sandboxed_run(
    command: str,
    timeout: int = 30,
    *,
    sandbox_enabled: bool = True,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Execute *command* optionally inside a bubblewrap sandbox.

    The isolation mode is determined by ``arke.toml [sandbox] mode``:
    - ``"workspace"`` (default): minimal-privilege, dedicated workspace only.
    - ``"full"`` (legacy): host root mounted read-only.

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
            "bubblewrap (bwrap) not found -- running without sandbox. "
            "Install bwrap for read-only filesystem isolation.",
            UserWarning,
            stacklevel=2,
        )

    if use_sandbox:
        cfg = load_sandbox_config()
        mode = cfg.get("mode", "workspace")
        allow_fallback = cfg.get("allow_fallback", True)

        if mode == "full":
            argv = _build_full_argv(command)
        else:
            allowed_dirs = _load_allowed_dirs()
            argv = _build_workspace_argv(command, allowed_dirs, workspace_root=workspace_root)

        result = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0 and _is_bwrap_runtime_permission_error(result.stderr):
            if not allow_fallback:
                raise SandboxFallbackError(
                    "bubblewrap runtime permission failure. "
                    "Set [sandbox] allow_fallback = true in arke.toml to permit unsandboxed fallback."
                )
            warnings.warn(
                "bubblewrap runtime permission failure -- falling back to unsandboxed execution "
                "in workspace cwd.",
                UserWarning,
                stacklevel=2,
            )
            result = _run_unsandboxed(command, timeout, workspace_root)
    else:
        result = _run_unsandboxed(command, timeout, workspace_root)

    return {
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
