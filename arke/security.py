"""Security — command whitelist enforcement for Arke kernel v0.1.

Reads allowed_commands from config/security.toml.
Raises ValueError for any command not in the whitelist.
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import structlog

log = structlog.get_logger()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "security.toml"


def _load_whitelist() -> frozenset[str]:
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)
        allowed: list[str] = data.get("shell", {}).get("allowed_commands", [])
        unsafe: bool = data.get("shell", {}).get("unsafe_mode", False)
        if unsafe:
            log.warning("security.unsafe_mode_enabled")
            return frozenset()  # empty = no enforcement
        return frozenset(allowed)
    except FileNotFoundError:
        log.warning("security.config_missing", path=str(_CONFIG_PATH))
        return frozenset()


def check_command(command: str) -> None:
    """Raise ``ValueError`` if *command* is not in the whitelist.

    Parses the first executable token (skipping variable assignments,
    operators, and redirections).

    Args:
        command: Full shell command string.

    Raises:
        ValueError: When the base executable is not whitelisted.
    """
    whitelist = _load_whitelist()
    if not whitelist:
        # unsafe_mode or missing config — allow everything (dev only)
        return

    try:
        tokens = shlex.split(command)
    except ValueError:
        raise ValueError(f"Malformed command: {command!r}")

    if not tokens:
        raise ValueError("Empty command")

    # Skip variable assignments, operators, and redirections to find first executable
    shell_operators = {"&&", "||", ";", "|", "&", ">", ">>", "<", "2>"}
    base_cmd = None
    for token in tokens:
        # Skip operators and redirections
        if token in shell_operators:
            continue
        # Skip variable assignments (contains '=' but not in a path)
        if "=" in token and not token.startswith("/") and not token.startswith("./"):
            continue
        # Skip redirections like > or >>
        if token.startswith((">", "<")):
            continue
        # This should be the first actual command
        base_cmd = Path(token).name  # strip any path prefix
        break

    if not base_cmd:
        raise ValueError(f"No executable found in command: {command!r}")

    if base_cmd not in whitelist:
        log.error(
            "security.blocked",
            command=command,
            base=base_cmd,
        )
        raise ValueError(
            f"Command '{base_cmd}' is not in the security whitelist. "
            "Add it to config/security.toml if intentional."
        )
