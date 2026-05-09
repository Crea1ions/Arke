"""Orchestrator — converts user intention into an executed Task.

Wires together: router → tool executors → gates → memory logging.
"""

from __future__ import annotations

from typing import Any

import structlog

from arke import router
from arke import gates
from arke.task_graph import Step, StepStatus, Task

log = structlog.get_logger()


def run(intention: str, context: dict[str, Any] | None = None) -> Task:
    """Plan and execute a Task for *intention*.

    Args:
        intention: Raw user intention string.
        context: Optional execution context (project_path, log_file, …).

    Returns:
        The completed ``Task`` with all steps populated and status set.
    """
    ctx = context or {}
    task = router.plan(intention, ctx)

    log.info("task.start", task_id=task.id, description=task.description)
    task.status = StepStatus.RUNNING

    step_outputs: dict[str, Any] = {}

    for step in task.steps:
        _wait_dependencies(step, step_outputs)
        _execute_step(step, step_outputs, ctx, task)
        if step.status == StepStatus.FAILED:
            task.status = StepStatus.FAILED
            log.error("task.failed", task_id=task.id, failed_step=step.id)
            return task

    task.status = StepStatus.SUCCESS
    log.info(
        "task.complete",
        task_id=task.id,
        total_cost=task.total_cost,
        tokens_used=task.tokens_used,
    )
    # P3.3 — Prometheus counters (fire-and-forget, never interrupts execution)
    try:
        from arke.telemetry import record_task_metrics

        record_task_metrics(task.total_cost, task.tokens_used)
    except Exception:  # noqa: BLE001
        pass
    return task


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _wait_dependencies(step: Step, outputs: dict[str, Any]) -> None:
    """Inject dependency outputs into step arguments (simple template fill)."""
    for dep_id in step.dependencies:
        placeholder = f"{{{dep_id}_output}}"
        dep_out = outputs.get(dep_id, "")
        for key, val in step.arguments.items():
            if isinstance(val, str) and placeholder in val:
                step.arguments[key] = val.replace(placeholder, str(dep_out))


def _execute_step(
    step: Step,
    step_outputs: dict[str, Any],
    ctx: dict[str, Any],
    task: Task,
) -> None:
    """Execute *step* with retry logic, then validate via its gate."""
    step.status = StepStatus.RUNNING

    while True:
        try:
            output = _traced_dispatch(step, ctx, task)
            step.output = output
            step_outputs[step.id] = _extract_text(output)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "step.execute.error",
                step_id=step.id,
                tool=step.tool,
                error=str(exc),
                retry_count=step.retry_count,
            )
            step.retry_count += 1
            if step.retry_count > step.max_retries:
                step.status = StepStatus.FAILED
                _record_step_outcome(step, task, success=False)
                return
            continue

        valid = gates.validate(step)
        log.info(
            "step.execute",
            step_id=step.id,
            tool=step.tool,
            cost_eur=task.total_cost,
            tokens_used=task.tokens_used,
            valid=valid,
        )

        if valid:
            step.status = StepStatus.SUCCESS
            _record_step_outcome(step, task, success=True)
            return

        step.retry_count += 1
        if step.retry_count > step.max_retries:
            step.status = StepStatus.FAILED
            _record_step_outcome(step, task, success=False)
            return


def _traced_dispatch(step: Step, ctx: dict[str, Any], task: Task) -> Any:
    """Wrap *_dispatch* with an OTel span for the current attempt."""
    from arke.telemetry import trace_step

    span_attrs: dict[str, Any] = {}
    with trace_step(step.tool, step.id, task.id) as span_attrs:
        try:
            result = _dispatch(step, ctx, task)
            span_attrs.update(
                {
                    "cost_eur": task.total_cost,
                    "tokens": task.tokens_used,
                    "success": True,
                }
            )
            return result
        except Exception:
            span_attrs["success"] = False
            raise


def _dispatch(step: Step, ctx: dict[str, Any], task: Task) -> Any:  # noqa: ARG001
    """Route step execution to the correct executor."""
    if step.tool == "cli":
        return _exec_cli(step)
    if step.tool == "fs":
        return _exec_fs(step)
    if step.tool == "sqlite":
        return _exec_sqlite(step)
    if step.tool == "memory_search":
        return _exec_memory_search(step)
    if step.tool == "mcp":
        return _exec_mcp(step)
    raise ValueError(f"Unknown tool: {step.tool!r}")


# ---------------------------------------------------------------------------
# NOTE: LLM execution removed — handled exclusively in chat.py via _ask_agent()
# ---------------------------------------------------------------------------
# INVARIANT: system_never_executes_without_llm_intent = true
# All tool execution requires prior agent decision in _ask_agent()


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------


def _exec_cli(step: Step) -> dict[str, Any]:
    """Execute a whitelisted shell command inside a bubblewrap sandbox."""
    from arke.security import check_command  # lazy import to avoid circular
    from arke.sandbox import load_sandbox_config, sandboxed_run

    command: str = step.arguments["command"]
    check_command(command)  # raises if not whitelisted

    cfg = load_sandbox_config()
    sandbox_enabled: bool = cfg.get("enabled", True)
    return sandboxed_run(command, timeout=30, sandbox_enabled=sandbox_enabled)


def _exec_fs(step: Step) -> dict[str, Any]:
    """Read a file or list a directory from the filesystem."""
    import os

    path: str = step.arguments["path"]

    if not os.path.exists(path):
        return {"return_code": 1, "stdout": "", "stderr": f"File not found: {path}"}

    if os.path.isdir(path):
        entries = sorted(os.listdir(path))
        return {"return_code": 0, "stdout": "\n".join(entries), "stderr": ""}

    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    return {"return_code": 0, "stdout": content, "stderr": ""}


def _exec_sqlite(step: Step) -> dict[str, Any]:
    """Execute a query against a named memory database.
    
    Auto-detects database based on table name if not explicitly provided:
    - session_context, chat_history, memory_fts → session.db
    - Otherwise → global.db (default)
    """
    from arke.memory.manager import MemoryManager

    query: str = step.arguments["query"]
    params: tuple = tuple(step.arguments.get("params", ()))
    
    # Auto-detect db based on table name if not explicitly provided
    db_name: str = step.arguments.get("db")
    if not db_name:
        if any(table in query.lower() for table in ["session_context", "chat_history", "memory_fts"]):
            db_name = "session"
        else:
            db_name = "global"

    mm = MemoryManager()
    rows = mm.query(db_name, query, params)
    stdout = "\n".join(str(dict(r)) for r in rows) if rows else "(aucun résultat)"
    return {"return_code": 0, "rows": rows, "stdout": stdout, "stderr": ""}


def _exec_memory_search(step: Step) -> dict[str, Any]:
    """Search agent learnings from agent_learnings table.
    
    Args:
        query: Search keywords (matched against intention_pattern and lesson)
        limit: Number of results to return (default 5)
        db: Database name (default "global")
    
    Returns:
        Dict with matching learning records and formatted output.
    """
    from difflib import SequenceMatcher
    import json
    from arke.memory.manager import MemoryManager

    search_query = step.arguments.get("query", "").lower()
    limit = step.arguments.get("limit", 5)
    db = step.arguments.get("db", "global")

    if not search_query:
        return {"return_code": 1, "stdout": "", "stderr": "query parameter required"}

    mm = MemoryManager()
    
    # Get all agent_learnings for fuzzy matching
    try:
        all_rows = mm.query(
            db,
            "SELECT id, intention_pattern, tool_sequence, success, lesson, created_at FROM agent_learnings ORDER BY created_at DESC",
            []
        )
    except Exception:
        all_rows = []

    if not all_rows:
        return {"return_code": 0, "stdout": "(no learning experiences found)", "stderr": ""}

    # Fuzzy match + ranking
    matches = []
    for row in all_rows:
        # Convert sqlite3.Row to dict for easier access
        row_dict = dict(row) if hasattr(row, 'keys') else row
        
        intent = (row_dict.get("intention_pattern") or "").lower()
        lesson = (row_dict.get("lesson") or "").lower()
        
        # Check if search query appears in intent or lesson
        if search_query in intent or search_query in lesson:
            # Calculate relevance score
            intent_score = SequenceMatcher(None, search_query, intent).ratio()
            lesson_score = SequenceMatcher(None, search_query, lesson).ratio()
            relevance = max(intent_score, lesson_score)
            
            matches.append({
                "row": row_dict,
                "relevance": relevance,
                "success": row_dict.get("success", True),
            })

    # Sort by: success first (1 before 0), then relevance highest first, then newest first
    matches.sort(
        key=lambda x: (x["success"], x["relevance"], x["row"].get("created_at", "")),
        reverse=True  # Reverse all: success=1 before 0, higher relevance first, newer first
    )
    matches = matches[:limit]

    if matches:
        results = [m["row"] for m in matches]
        formatted = json.dumps(results, indent=2, default=str)
        return {"return_code": 0, "stdout": formatted, "stderr": ""}
    else:
        return {"return_code": 0, "stdout": "(no matching experiences found)", "stderr": ""}


def _exec_mcp(step: Step) -> dict[str, Any]:
    """Call an MCP tool via the ContextForge federated endpoint.

    When ``tool_name`` is not explicitly set in step arguments, the
    client first lists available tools and picks the first match based
    on the ``intention`` keyword.
    """
    from arke.interfaces.mcp_client import McpClient, McpUnavailableError

    try:
        client = McpClient()
        tool_name: str | None = step.arguments.get("tool_name")
        tool_args: dict = step.arguments.get("tool_args", {})

        if tool_name is None:
            # Auto-select: list tools and pick first available
            tools = client.list_tools()
            if not tools:
                return {
                    "return_code": 1,
                    "stdout": "",
                    "stderr": "MCP: no tools available from ContextForge",
                }
            tool_name = tools[0]["name"]

        result = client.call_tool(tool_name, tool_args)
        content_blocks = result.get("content", [])
        text = "\n".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        is_error = result.get("isError", False)
        return {
            "return_code": 1 if is_error else 0,
            "stdout": text,
            "stderr": text if is_error else "",
        }
    except McpUnavailableError as exc:
        return {
            "return_code": 1,
            "stdout": "",
            "stderr": f"MCP indisponible : {exc}",
        }


def _extract_text(output: Any) -> str:
    """Pull plain text from an executor output dict."""
    if isinstance(output, dict):
        return output.get("stdout", "")
    return str(output)


def _record_step_outcome(step: Step, task: Task, success: bool) -> None:
    """Record step result in SkillManager, SkillDetector, and agent_learnings (fire-and-forget, never raises)."""
    try:
        from arke.skill_manager import SkillManager  # lazy — avoids circular import

        sm = SkillManager()
        if success:
            sm.record_success(step.tool, task.total_cost, task.tokens_used)
        else:
            sm.record_failure(step.tool)
    except Exception:  # noqa: BLE001
        pass  # tracking must never interrupt execution

    if success:
        try:
            from arke.skill_detector import SkillDetector  # lazy

            SkillDetector().record(step.tool, task.description)
        except Exception:  # noqa: BLE001
            pass
    
    # Record learning outcome for autonomous skill generation (Session 014.1)
    try:
        _record_learning(step, task, success)
    except Exception:  # noqa: BLE001
        pass  # learning recording must never interrupt execution


def _record_learning(step: Step, task: Task, success: bool) -> None:
    """Record step outcome to agent_learnings table for autonomous learning.
    
    Only records successful steps (success=True). Each record captures:
    - intention_pattern: The user's original intent from task description
    - tool_sequence: The tool used for this step (step.tool)
    - success: Always True (only records successes)
    - outcome_summary: Brief description of what was accomplished
    - lesson: What the agent can learn from this experience
    
    Also tracks consecutive successes in session context. When 3+ consecutive
    successes occur, sets "show_distillation_hint" flag for chat to display.
    
    This data feeds:
    1. memory_search tool: Agent can query "similar past experiences"
    2. Pattern detection: Finds repeated tool sequences for skill creation
    3. Divulgation progressive: Seeds context with learned skills
    """
    from arke.memory.manager import MemoryManager
    import json
    from datetime import datetime
    
    mm = MemoryManager()
    
    if success:
        # Record successful experience to agent_learnings
        intention = task.description or ""
        tool_seq = json.dumps([step.tool])  # For future: may extend to multiple steps
        outcome = f"Successfully executed {step.tool}"
        lesson = f"Using {step.tool} is effective for: {intention[:100]}"
        now = datetime.now().isoformat()
        
        try:
            mm.query(
                "global",
                """INSERT INTO agent_learnings 
                   (intention_pattern, tool_sequence, success, outcome_summary, lesson, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                """,
                (intention, tool_seq, 1, outcome, lesson, now)
            )
        except Exception:
            # Silently fail - learning must never interrupt execution
            pass
        
        # Track consecutive successes for distillation hint
        try:
            # Read current counter
            rows = mm.query(
                "session",
                "SELECT value FROM session_context WHERE key = 'consecutive_successes'",
                ()
            )
            current = int(rows[0]["value"]) if rows else 0
            
            # Increment counter
            new_count = current + 1
            mm.query(
                "session",
                "INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)",
                ("consecutive_successes", str(new_count))
            )
            
            # Set hint flag if threshold reached
            if new_count >= 3:
                mm.query(
                    "session",
                    "INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)",
                    ("show_distillation_hint", "1")
                )
        except Exception:
            # Silently fail - tracking must never interrupt execution
            pass
    else:
        # Reset consecutive counter on failure
        try:
            mm.query(
                "session",
                "INSERT OR REPLACE INTO session_context (key, value) VALUES (?, ?)",
                ("consecutive_successes", "0")
            )
        except Exception:
            pass
