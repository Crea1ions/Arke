"""Task Classifier — Categorizes tasks into SIMPLE, COMPLEX, or DANGEROUS.

Implements the three-tier classification from the Cognitive Contract:
  1. SIMPLE/BASIQUE → Exécution immédiate (read-only, single step, no side effects)
  2. COMPLEX/LONGUE → Demander confirmation (multi-step, modifications, state mutations)
  3. DANGEROUS → Toujours demander explicite (destructive, sensitive paths, shell operators)

Classification informs execution flow in chat.py:
  - simple   → execute directly, display results
  - complex  → show plan, ask yes/no confirmation
  - dangerous → show command, ask explicit "OUI" confirmation
"""

from __future__ import annotations

import re
from typing import Literal

TaskCategory = Literal["simple", "complex", "dangerous"]


# Dangerous command patterns (must be detected and always require confirmation)
_DANGEROUS_PATTERNS = [
    r"^rm\s",  # rm, rm -f, rm -rf
    r"^rmdir\s",  # rmdir
    r"^unlink\s",  # unlink
    r"^truncate\s",  # truncate
    r"^dd\s",  # dd (destructive)
    r"DELETE\s+FROM",  # SQL DELETE
    r"DROP\s+TABLE",  # SQL DROP
    r"DROP\s+DATABASE",  # SQL DROP DB
    r"^truncate\s+table",  # SQL truncate
]

# Dangerous tool names
_DANGEROUS_TOOLS = ["cli", "sqlite"]  # CLI can run rm, etc; sqlite can drop

# Restricted paths (outside /tmp, /home/*/projects, user workspace)
_RESTRICTED_PATHS = [
    "/etc/",
    "/root/",
    "/boot/",
    "/sys/",
    "/proc/",
    "/dev/",
    "~/.bashrc",
    "~/.ssh/",
    "~/.aws/",
]

# Read-only, safe tool names
_SAFE_READONLY_TOOLS = ["web_search", "calculator", "rss_reader", "github"]

# Simple operations (no state mutation) - DIAGNOSTIC keywords
_SIMPLE_OPERATIONS = [
    "search",
    "read",
    "list",
    "check",
    "verify",
    "analyze",
    "convert",
    "calculate",
    "fetch",
    "explore",
    "rapport",
    "report",
    "status",
    "state",
    "diagnostic",
    "diagnostique",
    "health",
    "santé",
    "test",
    "stat",
    "info",
    "information",
]


def classify(
    intention: str,
    tools: list[str] | None = None,
    step_count: int = 1,
    args: dict | None = None,
) -> TaskCategory:
    """Classify a task into SIMPLE, COMPLEX, or DANGEROUS.

    Args:
        intention: User's raw intention string.
        tools: List of tool names to be used (e.g., ["web_search", "cli"]).
        step_count: Number of orchestrated steps (>1 → multi-step).
        args: Tool arguments (to detect dangerous operations).

    Returns:
        "simple" | "complex" | "dangerous"

    Classification Logic:
        1. If dangerous pattern detected → "dangerous"
        2. If multi-step (step_count > 1) or write/mutation tools → "complex"
        3. Otherwise → "simple"
    """
    tools = tools or []
    args = args or {}

    # Check 1: Dangerous patterns in intention or args
    if _is_dangerous(intention, args):
        return "dangerous"

    # Check 2: Dangerous tools with any args
    if any(t in _DANGEROUS_TOOLS for t in tools):
        # CLI or SQLite could be dangerous, classify based on args
        if _contains_dangerous_args(args):
            return "dangerous"
        # Otherwise, it's complex (modification potential)
        if step_count > 1:
            return "complex"
        # Single CLI/SQLite read → could be simple if just query
        if _is_safe_readonly_operation(intention, args):
            return "simple"
        return "complex"

    # Check 3: Multi-step always complex
    if step_count > 1:
        return "complex"

    # Check 4: Safe tools only
    if tools and all(t in _SAFE_READONLY_TOOLS for t in tools):
        return "simple"

    # Check 5: Default to complex if uncertain
    return "complex"


def _is_dangerous(intention: str, args: dict) -> bool:
    """Detect dangerous operations in intention or command args."""
    # Check intention string for keywords
    if any(
        keyword in intention.lower()
        for keyword in ["delete", "remove", "destroy", "erase", "wipe", "drop"]
    ):
        return True

    # Check for dangerous shell commands in args
    for arg_key, arg_val in args.items():
        if isinstance(arg_val, str):
            if _matches_dangerous_pattern(arg_val):
                return True
        elif isinstance(arg_val, dict):
            if _is_dangerous(str(arg_val), arg_val):
                return True

    return False


def _contains_dangerous_args(args: dict) -> bool:
    """Check if args dict contains dangerous commands or paths."""
    for key, val in args.items():
        if isinstance(val, str):
            # Check for dangerous commands
            if _matches_dangerous_pattern(val):
                return True
            # Check for restricted paths
            if any(path in val for path in _RESTRICTED_PATHS):
                return True
        elif isinstance(val, dict):
            if _contains_dangerous_args(val):
                return True

    return False


def _matches_dangerous_pattern(text: str) -> bool:
    """Check if text matches any dangerous regex pattern."""
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _is_safe_readonly_operation(intention: str, args: dict) -> bool:
    """Detect if operation is read-only (SELECT, cat, ls, etc)."""
    intention_lower = intention.lower()

    # Check intention for read-only keywords
    for op in _SIMPLE_OPERATIONS:
        if op in intention_lower:
            return True

    # Check SQL query type
    for val in args.values():
        if isinstance(val, str):
            if val.strip().upper().startswith("SELECT"):
                return True
            # df, free, uptime, ps, top are all diagnostic commands
            if any(cmd in val for cmd in ["df -", "free -", "uptime", "ps ", "top ", "cat ", "ls ", "file ", "stat "]):
                return True

    return False


def explain(category: TaskCategory) -> str:
    """Return user-friendly explanation of classification."""
    explanations = {
        "simple": "✓ Tâche simple (lecture seule) — exécution immédiate",
        "complex": (
            "⠋ Tâche complexe (modifications, multi-étapes) — "
            "demande de confirmation"
        ),
        "dangerous": (
            "⚠️ Opération dangereuse (destructive) — "
            "confirmation explicite requise"
        ),
    }
    return explanations.get(category, "?")
