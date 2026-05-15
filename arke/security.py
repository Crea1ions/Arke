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

# Explicitly blocked host-sensitive roots for filesystem access.
_BLACKLISTED_PATH_PREFIXES: tuple[Path, ...] = (
    Path("/etc"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/root"),
    Path("/boot"),
    Path("/run"),
    Path("/var/log"),
    Path.home() / ".ssh",
)

_SHELL_OPERATORS: frozenset[str] = frozenset({
    "|",
    "||",
    "&&",
    ";",
    "(",
    ")",
    "<",
    ">",
    ">>",
})


def _looks_like_path_token(token: str) -> bool:
    """Heuristic: return True when a CLI token likely represents a path."""
    if not token:
        return False
    if any(ch.isspace() for ch in token):
        return False
    if "://" in token:
        return False
    if token.startswith(("/", "./", "../", "~/")):
        return True
    if token in (".", ".."):
        return True
    # Guard against HTML/templating snippets like </html> or <a/b>.
    if any(ch in token for ch in "<>{}()[]\"'`$"):
        return False
    return "/" in token


def _lex_shell(command: str) -> list[str]:
    """Lex shell command while splitting punctuation operators even without spaces."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _join_shell_tokens(tokens: list[str]) -> str:
    """Join shell tokens while preserving operators semantics."""
    out: list[str] = []
    for token in tokens:
        if token in _SHELL_OPERATORS:
            out.append(token)
        else:
            # Keep plain tokens unquoted to preserve shell expansions
            # (brace/glob) used by agent-generated commands.
            if token == "" or any(ch.isspace() for ch in token):
                out.append(shlex.quote(token))
            else:
                out.append(token)
    return " ".join(out)


def _normalize_single_path_token(token: str, workspace_root: Path) -> str:
    """Normalize one path token to /workspace/<relative>, enforcing security."""
    import os
    # Permet d'injecter un $HOME fictif pour les tests
    home_env = os.environ.get("HOME")
    if home_env:
        home = Path(home_env).resolve(strict=False)
        candidate_path = Path(token.replace("~", home_env, 1)).resolve(strict=False) if token.startswith("~") else Path(token).expanduser()
    else:
        home = Path.home().resolve(strict=False)
        candidate_path = Path(token).expanduser()
    # Si le chemin expandu commence par le home utilisateur ET le workspace_root == home,
    # alors on mappe ~/... dans /workspace/...
    if candidate_path.is_absolute():
        # Accept sandbox-internal paths as aliases to the host workspace root.
        if str(candidate_path) == "/workspace":
            resolved = workspace_root
        elif str(candidate_path).startswith("/workspace/"):
            rel = Path(str(candidate_path).removeprefix("/workspace/"))
            resolved = (workspace_root / rel).resolve(strict=False)
        # Nouveau : mappe $HOME/xxx dans /workspace/xxx si workspace_root == $HOME
        elif str(candidate_path).startswith(str(home)) and workspace_root.resolve(strict=False) == home:
            rel = candidate_path.relative_to(home)
            resolved = (workspace_root / rel).resolve(strict=False)
        else:
            resolved = candidate_path.resolve(strict=False)
    else:
        resolved = (workspace_root / candidate_path).resolve(strict=False)

    if is_blacklisted_path(resolved):
        raise ValueError(f"Path blocked by security policy: {token}")
    if not is_safe_path(resolved, workspace_root):
        raise ValueError(f"Path blocked outside workspace: {token}")

    rel = resolved.relative_to(workspace_root)
    mapped = Path("/workspace") / rel
    return mapped.as_posix()


def _normalize_shell_fragment(fragment: str, workspace_root: Path, *, nested: bool) -> str:
    """Normalize a shell fragment and return a safe reconstructed command string."""
    tokens = _lex_shell(fragment)
    if not tokens:
        return fragment

    normalized: list[str] = [tokens[0]]
    for idx, token in enumerate(tokens[1:], start=1):
        prev_token = tokens[idx - 1]
        if token in _SHELL_OPERATORS:
            normalized.append(token)
            continue

        # Handle --key=value style options where value can be a path.
        if token.startswith("--") and "=" in token:
            key, value = token.split("=", 1)
            if _looks_like_path_token(value):
                value = _normalize_single_path_token(value, workspace_root)
            normalized.append(f"{key}={value}")
            continue

        # Keep option flags untouched.
        if token.startswith("-"):
            normalized.append(token)
            continue

        # Support advanced quoted shell snippets only when explicitly passed as
        # command fragments (e.g. bash -lc "cat ./a|wc -l").
        if nested and prev_token in {"-c", "-lc", "-xc", "-ec"}:
            normalized.append(_normalize_shell_fragment(token, workspace_root, nested=False))
            continue

        if _looks_like_path_token(token):
            normalized.append(_normalize_single_path_token(token, workspace_root))
        else:
            normalized.append(token)

    return _join_shell_tokens(normalized)


def normalize_cli_command_paths(command: str, workspace_root: str | Path | None) -> str:
    """Normalize and validate path-like CLI args before sandbox execution.

    Rules:
    - Keeps the executable token unchanged.
    - For path-like tokens, resolves them from ``workspace_root`` and maps them
      to ``/workspace/...`` for sandbox compatibility.
    - Blocks blacklisted paths and any path escaping ``workspace_root``.
    - If ``workspace_root`` is None, returns command unchanged.
    """
    if workspace_root is None:
        return command

    root = Path(workspace_root).expanduser().resolve(strict=False)
    return _normalize_shell_fragment(command, root, nested=True)


def is_blacklisted_path(path: str | Path) -> bool:
    """Return True if *path* resolves under a blocked sensitive prefix."""
    candidate = Path(path).expanduser().resolve(strict=False)
    for prefix in _BLACKLISTED_PATH_PREFIXES:
        blocked_root = prefix.expanduser().resolve(strict=False)
        try:
            if candidate.is_relative_to(blocked_root):
                return True
        except AttributeError:
            if str(candidate).startswith(str(blocked_root)):
                return True
    return False


def is_safe_path(path: str | Path, workspace_root: str | Path | None) -> bool:
    """Return True when *path* is inside *workspace_root*.

    If ``workspace_root`` is ``None``, the check is permissive and returns True
    for backward compatibility.
    """
    if workspace_root is None:
        return True

    root = Path(workspace_root).expanduser().resolve(strict=False)
    candidate = Path(path).expanduser().resolve(strict=False)

    try:
        return candidate.is_relative_to(root)
    except AttributeError:
        # Fallback for Python versions without Path.is_relative_to
        return str(candidate).startswith(str(root))


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
