"""Router — deterministic intent-to-tool mapping for Arke kernel v0.1.

Routing hierarchy (immutable until v0.2):
    cli → fs → sqlite → script → api → mcp → llm

The router is intentionally kept under 100 lines of logic.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from arke.task_graph import Step, StepStatus, Task, Validation

# ---------------------------------------------------------------------------
# Routing layer keywords
# ---------------------------------------------------------------------------

_CLI_COMMANDS: frozenset[str] = frozenset(
    {
        "echo", "cat", "grep", "find", "ls", "head", "tail",
        "wc", "sort", "uniq", "awk", "sed", "cut", "tr",
        "mogrify", "convert", "ffmpeg",
        "git", "python", "python3",
        "curl", "wget", "jq",
    }
)

_FS_KEYWORDS: frozenset[str] = frozenset(
    {"read", "write", "file", "fichier", "directory", "dossier", "path", "chemin", "list"}
)

_SQLITE_KEYWORDS: frozenset[str] = frozenset(
    {"query", "database", "sqlite", "requête", "select"}
)

# Grep/text-search pattern — "cherche X", "recherche X dans Y" → cli (grep)
_GREP_RE = re.compile(
    r'^(cherche|recherche|search|grep|find\s+text|trouve)\b',
    re.IGNORECASE,
)

_LOG_KEYWORDS: frozenset[str] = frozenset(
    {"log", "logs", "analyse", "analyz", "erreur", "error", "nginx", "apache", "access.log"}
)

_MCP_KEYWORDS: frozenset[str] = frozenset(
    {
        "issue", "pr", "pull-request", "github", "gitlab", "ticket",
        "crée", "cree", "create", "open", "ouvre", "mcp", "contextforge",
        "deploy", "déploie", "notify", "notifie", "send", "envoie",
    }
)

# File extension pattern — detects explicit file references in intentions
_PATH_RE = re.compile(
    r'\b[\w\-]+\.(?:py|md|txt|toml|yaml|yml|json|sh|js|ts|rs|go'
    r'|c|cpp|h|log|sql|csv|xml|html|css|conf|cfg|env|lock|ini)\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_tool(intention: str, context: dict[str, Any], weights: dict[str, float] | None = None) -> str:  # noqa: ARG001
    """Return the single best tool name for *intention*.

    Args:
        intention: Raw user intention string.
        context: Execution context dict (project_path, log_file, …).
        weights: Optional routing weights produced by
            :func:`_load_weights`.  When a tool has weight ``≥ 2.0``
            (i.e. ≥ 5 past successes), it is preferred over the default
            ``'llm'`` fallback.

    Returns:
        One of ``'cli'``, ``'fs'``, ``'sqlite'``, ``'llm'``.
    """
    words = intention.lower().split()
    first_word = words[0] if words else ""

    if first_word in _CLI_COMMANDS:
        return "cli"
    # Text-search request ("cherche X", "recherche X dans …") → grep via cli
    if _GREP_RE.match(intention):
        return "cli"
    # Explicit file reference (e.g. "quel est le contenu de README.md") → fs
    if _PATH_RE.search(intention):
        return "fs"
    if _FS_KEYWORDS & set(words):
        return "fs"
    if _SQLITE_KEYWORDS & set(words):
        return "sqlite"
    if _MCP_KEYWORDS & set(words):
        return "mcp"

    # No keyword match — prefer a boosted tool over the default LLM fallback.
    if weights:
        for tool in ("cli", "fs", "sqlite", "mcp"):
            if weights.get(tool, 1.0) >= 2.0:
                return tool
    return "llm"


def plan(intention: str, context: dict[str, Any]) -> Task:
    """Build a Task graph from *intention* and *context*.

    **AGENT-FIRST PRINCIPLE**: Check agent_decision BEFORE pattern matching.
    If agent has decided (via _ask_agent in chat.py), always use that.
    Only if no agent decision, fall back to pattern-based routing.

    Supports multi-step sequences when agent_decision contains "multi_step" key.

    Args:
        intention: Raw user intention string.
        context: Execution context dict (may contain agent_decision from LLM).

    Returns:
        A ``Task`` ready for execution by the orchestrator.
    """
    # Step 1: If agent has already decided the tool (from _ask_agent in chat.py), use that
    # This respects the agent-first principle: system never decides tools
    agent_decision = context.get("agent_decision")
    if agent_decision:
        # Check for multi-step sequences
        multi_step = agent_decision.get("multi_step")
        if multi_step and isinstance(multi_step, list) and len(multi_step) > 1:
            # Multi-step task: create steps for each tool in sequence
            steps = []
            for tool_spec in multi_step:
                tool = tool_spec.get("tool")
                args = tool_spec.get("args", {})
                
                # Set defaults for each tool type
                if tool == "cli":
                    args.setdefault("command", intention)
                elif tool == "fs":
                    args.setdefault("path", intention)
                elif tool == "sqlite":
                    args.setdefault("query", intention)
                
                if tool in ["cli", "fs", "sqlite", "mcp"]:
                    step = _single_step(tool, intention, context, args)
                    steps.append(step)
            
            if steps:
                return Task(id=_new_id(), description=intention, steps=steps)
        
        # Single-step or fallback
        tool = agent_decision.get("tool")
        args = agent_decision.get("args", {})
        # Set defaults for each tool type
        if tool == "cli":
            args.setdefault("command", intention)
        elif tool == "fs":
            args.setdefault("path", intention)
        elif tool == "sqlite":
            args.setdefault("query", intention)
        elif tool == "memory_search":
            args.setdefault("query", intention)
        # Note: tool="llm" is never returned by _ask_agent
        # (it's executed directly there, not passed to orchestrator)
        if tool in ["cli", "fs", "sqlite", "mcp", "memory_search"]:
            step = _single_step(tool, intention, context, args)
            return Task(id=_new_id(), description=intention, steps=[step])

    # Step 2: If no agent decision, check for recognized patterns (fallback only)
    low = intention.lower()
    if _is_log_analysis(low):
        # For log analysis, extract logs via CLI only
        # (no LLM summarization here, as _exec_llm was removed)
        return _plan_log_analysis_cli_only(intention, context)

    # Step 3: If no agent decision and no pattern match, system decides tool (rarely happens)
    weights = _load_weights()
    tool = select_tool(intention, context, weights)
    step = _single_step(tool, intention, context)
    return Task(id=_new_id(), description=intention, steps=[step])


# ---------------------------------------------------------------------------
# Path extraction helper
# ---------------------------------------------------------------------------


def _extract_path(intention: str, context: dict[str, Any]) -> str:
    """Extract a file path from *intention* or *context*.

    Tries, in order:
    1. ``context["path"]`` if explicitly provided.
    2. First file-extension match in *intention* (e.g. ``README.md``).
    3. Falls back to current directory ``"."``.
    """
    if "path" in context:
        return context["path"]
    m = _PATH_RE.search(intention)
    if m:
        return m.group(0)
    return "."


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------


def _is_log_analysis(low: str) -> bool:
    """True when the intention looks like a log-analysis compound request."""
    matched = sum(1 for kw in _LOG_KEYWORDS if kw in low)
    return matched >= 2


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def _plan_log_analysis_cli_only(intention: str, context: dict[str, Any]) -> Task:
    """Extract logs via CLI for analysis.
    
    Since _exec_llm() was removed from orchestrator, we no longer create
    compound tasks with tool="llm". Instead, we extract the logs via CLI,
    and the agent can decide what to do next (summarize, analyze, etc.)
    via a subsequent call to _ask_agent().
    
    Args:
        intention: User intention (should contain log analysis keywords)
        context: Execution context (may contain log_file path)
    
    Returns:
        Task with a single CLI step to extract error logs
    """
    log_file = context.get("log_file", "access.log")
    step_grep = Step(
        id="step_1",
        tool="cli",
        arguments={"command": f"grep -E '\\s5[0-9][0-9]\\s' {log_file}"},
        validation=Validation(type="return_code", expected=0),
    )
    return Task(id=_new_id(), description=intention, steps=[step_grep])


def _to_grep_command(intention: str) -> str:
    """Convert a natural-language search request to a grep command.

    Examples::

        "cherche sqlite"                 → 'grep -r "sqlite" .'
        'cherche "sqlite" dans README.md' → 'grep "sqlite" README.md'
        "recherche erreur dans logs/"    → 'grep -r "erreur" logs/'
    """
    _GREP_INTENT_RE = re.compile(
        r'^(?:cherche|recherche|search|grep|trouve)\s+'
        r'["\']?(?P<term>[^"\']+?)["\']?'
        r'(?:\s+(?:dans|in|dans\s+le\s+fichier|dans\s+les\s+fichiers)\s+(?P<path>\S+))?'
        r'\s*$',
        re.IGNORECASE,
    )
    m = _GREP_INTENT_RE.match(intention.strip())
    if not m:
        # Fallback: pass through as-is (the intent is already a shell command)
        return intention.strip()
    term = m.group("term").strip().strip('"\'')
    path = (m.group("path") or ".").strip()
    flag = "" if (_PATH_RE.search(path) or path != ".") else "-r "
    return f'grep {flag}"{term}" {path}'


def _single_step(tool: str, intention: str, context: dict[str, Any], args: dict[str, Any] | None = None) -> Step:
    args = args or {}
    if tool == "cli":
        # Use agent-provided command if available, else parse from intention
        if "command" in args:
            command = args["command"]
        else:
            command = (
                _to_grep_command(intention)
                if _GREP_RE.match(intention)
                else intention.strip()
            )
        return Step(
            id="step_1",
            tool="cli",
            arguments={"command": command},
            validation=Validation(type="return_code", expected=0),
        )
    if tool == "fs":
        # Use agent-provided path if available, else extract from intention
        path = args.get("path") or _extract_path(intention, context)
        return Step(
            id="step_1",
            tool="fs",
            arguments={"path": path, "operation": "read"},
            validation=Validation(type="file_exists", expected=path),
        )
    if tool == "sqlite":
        query = args.get("query", intention.strip())
        # Auto-detect db if not provided by agent
        db = args.get("db")
        if not db:
            # Auto-detect based on table name
            if any(table in query.lower() for table in ["session_context", "chat_history", "memory_fts"]):
                db = "session"
            else:
                db = "global"
        return Step(
            id="step_1",
            tool="sqlite",
            arguments={"db": db, "query": query, "params": args.get("params", ())},
        )
    if tool == "mcp":
        # Pass ALL agent-provided args directly — _exec_mcp() expects _server/tool_name/tool_args
        return Step(
            id="step_1",
            tool="mcp",
            arguments=args,
            validation=Validation(type="return_code", expected=0),
        )
    if tool == "memory_search":
        query = args.get("query", intention.strip())
        return Step(
            id="step_1",
            tool="memory_search",
            arguments={
                "query": query,
                "limit": args.get("limit", 5),
                "db": args.get("db", "global"),
            },
            validation=Validation(type="return_code", expected=0),
        )
    # llm fallback
    return Step(
        id="step_1",
        tool="llm",
        arguments={
            "prompt_template": args.get("prompt_template", intention),
            "task_type": args.get("task_type", "reasoning"),
            "max_tokens": args.get("max_tokens", 500),
        },
    )


def _new_id() -> str:
    return str(uuid.uuid4())


def _load_weights() -> dict[str, float]:
    """Load routing weights from SkillManager.

    Returns an empty dict on any failure so routing always degrades
    gracefully to the default keyword-based hierarchy.
    """
    try:
        from arke.skill_manager import SkillManager  # lazy — avoids import cycle

        sm = SkillManager()
        return {t: sm.get_weight(t) for t in ("cli", "fs", "sqlite", "mcp", "llm")}
    except Exception:  # noqa: BLE001
        return {}
