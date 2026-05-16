"""Orchestrator — converts user intention into an executed Task.

Wires together: router → tool executors → gates → memory logging.

WORKSPACE INTEGRATION: orchestrator is the sole authority for PUW (Passive User Workspace)
filesystem I/O. workspace.py provides orchestrator-only abstraction layer.
LLM never sees workspace structure or paths.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import structlog

from arke import router
from arke import gates
from arke.task_graph import Step, StepStatus, Task
from arke import workspace  # PUW integration (orchestrator-only)
from arke.logging.action_writer import log_action

log = structlog.get_logger()


def run(intention: str, context: dict[str, Any] | None = None) -> Task:
    """Plan and execute a Task for *intention*.

    Args:
        intention: Raw user intention string.
        context: Optional execution context (project_path, log_file, wcu_root, …).

    Returns:
        The completed ``Task`` with all steps populated and status set.
    """
    ctx = context or {}
    
    # Initialize workspace on first run (orchestrator-only, never exposed to LLM)
    _initialize_workspace_once(ctx)
    
    task = router.plan(intention, ctx)

    log.info("task.start", task_id=task.id, description=task.description)
    task.status = StepStatus.RUNNING

    step_outputs: dict[str, Any] = {}
    
    # Determine if this is a multi-step exploration task (agent specified multiple tools)
    # Multi-step tasks are more resilient: continue on failure instead of stopping
    is_multi_step = len(task.steps) > 1
    has_failures = False

    for step in task.steps:
        _wait_dependencies(step, step_outputs)
        _execute_step(step, step_outputs, ctx, task)
        if step.status == StepStatus.FAILED:
            has_failures = True
            log.warning("step.failed", step_id=step.id, is_multi_step=is_multi_step)
            if not is_multi_step:
                # Single-step: fail immediately (original behavior)
                task.status = StepStatus.FAILED
                log.error("task.failed", task_id=task.id, failed_step=step.id)
                return task
            # Multi-step: log failure but continue to next step

    # Determine final status based on whether any steps completed successfully
    if has_failures:
        # If we have failures, check if we got any successful steps
        successful_steps = [s for s in task.steps if s.status == StepStatus.SUCCESS]
        if successful_steps:
            # Multi-step with partial success: mark as SUCCESS but log partial
            task.status = StepStatus.SUCCESS
            log.info(
                "task.complete_partial",
                task_id=task.id,
                total_steps=len(task.steps),
                successful=len(successful_steps),
            )
        else:
            # All steps failed
            task.status = StepStatus.FAILED
            log.error("task.failed_all_steps", task_id=task.id)
    else:
        # All steps succeeded
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

# Workspace initialization flag (orchestrator-only)
_workspace_initialized = False


def _initialize_workspace_once(ctx: dict[str, Any]) -> None:
    """Initialize workspace manager if not already done (orchestrator-only).
    
    CRITICAL: This is orchestrator-internal. Never expose workspace to LLM.
    """
    global _workspace_initialized
    if _workspace_initialized:
        return

    try:
        # Legacy WCU is opt-in: only initialize when an explicit root exists.
        wcu_root = ctx.get("wcu_root") or ctx.get("workspace_wcu_root")
        if not wcu_root:
            log.info("workspace.skipped_no_root")
            return

        wcu_root = Path(wcu_root).expanduser()
        if not wcu_root.exists():
            log.info("workspace.skipped_missing_root", wcu_root=str(wcu_root))
            return

        # Initialize workspace manager without creating anything implicitly.
        workspace.initialize_workspace(wcu_root)
        _workspace_initialized = True
        log.info("workspace.initialized", wcu_root=str(wcu_root))
    except Exception as e:
        log.warning("workspace.initialization.failed", error=str(e))
        # Don't fail the whole orchestrator, just warn


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
    step_start = time.perf_counter()

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
                _log_step_action(step, ctx, task, step_start, success=False)
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
            _log_step_action(step, ctx, task, step_start, success=True)
            return

        step.retry_count += 1
        if step.retry_count > step.max_retries:
            step.status = StepStatus.FAILED
            _record_step_outcome(step, task, success=False)
            _log_step_action(step, ctx, task, step_start, success=False)
            return


def _log_step_action(step: Step, ctx: dict[str, Any], task: Task, start_time: float, success: bool) -> None:
    """Log step execution to action audit trail."""
    try:
        workspace_root = Path(ctx.get("WORKSPACE_ROOT", "."))
        logs_dir = workspace_root / ".arke" / "logs"
        
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        
        log_action(
            logs_dir=logs_dir,
            session_id=ctx.get("session_id", "unknown"),
            mode=ctx.get("agent_mode", "ask"),
            tool=step.tool,
            action="execute",
            command=str(step.arguments.get("command", "")) if step.tool == "cli" else None,
            rc=0 if success else 1,
            duration_ms=duration_ms,
            step=step.id,
            details={
                "status": step.status.name,
                "retry_count": step.retry_count,
                "task_id": task.id,
            },
        )
    except Exception:  # noqa: BLE001
        pass  # Fail silently


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
    # Agent mode gating: block execution if tool not permitted in current mode.
    # Backward compatibility for direct orchestrator calls uses unrestricted agent mode.
    mode = ctx.get("agent_mode", "agent")
    if not can_execute_tool(step.tool, mode):
        return {
            "return_code": 1,
            "stdout": "",
            "stderr": (
                f"[Mode /{mode}] Outil '{step.tool}' non autorisé. "
                f"Utilisez /agent pour exécuter des outils système."
            ),
        }
    if step.tool == "cli":
        return _exec_cli(step, ctx)
    if step.tool == "fs":
        return _exec_fs(step, ctx)
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


def _exec_cli(step: Step, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a whitelisted shell command inside a bubblewrap sandbox."""
    from arke.security import check_command, normalize_cli_command_paths  # lazy import to avoid circular
    from arke.sandbox import load_sandbox_config, sandboxed_run

    command: str = step.arguments["command"]
    run_ctx = ctx or {}
    workspace_root = run_ctx.get("WORKSPACE_ROOT")

    try:
        command = normalize_cli_command_paths(command, workspace_root)
    except ValueError as exc:
        return {"return_code": 1, "stdout": "", "stderr": str(exc)}

    try:
        check_command(command)  # raises ValueError if not whitelisted
    except ValueError as exc:
        return {"return_code": 1, "stdout": "", "stderr": str(exc)}

    cfg = load_sandbox_config()
    sandbox_enabled: bool = cfg.get("enabled", True)
    return sandboxed_run(
        command,
        timeout=30,
        sandbox_enabled=sandbox_enabled,
        workspace_root=workspace_root,
    )


def _exec_fs(step: Step, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read a file or list a directory from the filesystem."""
    import os
    from arke.security import is_blacklisted_path, is_safe_path

    path: str = step.arguments["path"]
    run_ctx = ctx or {}
    workspace_root = run_ctx.get("WORKSPACE_ROOT")

    resolved_path = path
    if workspace_root:
        root = Path(workspace_root)
        candidate = Path(path)
        if candidate.is_absolute():
            if str(candidate) == "/workspace":
                resolved_path = str(root)
            elif str(candidate).startswith("/workspace/"):
                rel = Path(str(candidate).removeprefix("/workspace/"))
                resolved_path = str((root / rel).resolve(strict=False))
            else:
                resolved_path = str(candidate)
        else:
            resolved_path = str(root / candidate)

        if not is_safe_path(resolved_path, workspace_root):
            return {
                "return_code": 1,
                "stdout": "",
                "stderr": f"Path blocked outside workspace: {path}",
            }

    if is_blacklisted_path(resolved_path):
        return {
            "return_code": 1,
            "stdout": "",
            "stderr": f"Path blocked by security policy: {path}",
        }

    if not os.path.exists(resolved_path):
        return {"return_code": 1, "stdout": "", "stderr": f"File not found: {path}"}

    if os.path.isdir(resolved_path):
        entries = sorted(os.listdir(resolved_path))
        return {"return_code": 0, "stdout": "\n".join(entries), "stderr": ""}

    with open(resolved_path, "r", encoding="utf-8") as fh:
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
    """Execute MCP call - supports both legacy ContextForge and individual servers"""
    import subprocess
    import json
    import tomllib
    from pathlib import Path
    
    args = step.arguments
    
    # Initialize variables before use
    server_name = args.get("_server") or args.get("server")
    tool_name = args.get("tool_name") or args.get("tool")

    # Support du format {service, action, params} (utilisé par l'agent)
    if not server_name and not tool_name:
        service = args.get("service")
        action = args.get("action")
        params = args.get("params", {})
        
        if service and action:
            # Mapping service/action → server/tool
            service_tool_map = {
                ("freeweb", "search"): ("freeweb", "web_search"),
                ("calculator", "calculate"): ("calculator", "calculate"),
                ("rss_reader", "read"): ("rss_reader", "read_rss"),
                ("github", "search"): ("github", "github_search"),
            }
            
            mapped = service_tool_map.get((service, action))
            if mapped:
                server_name, tool_name = mapped
                # params devient tool_args
                args["tool_args"] = params
                args["_server"] = server_name
                args["tool_name"] = tool_name

    # Now server_name and tool_name are set from args

    # Mode 1: Serveur MCP individuel (freeweb, calculator, etc.)
    if server_name and tool_name:
        # --- MCP Cache: check before live execution ---
        from arke.mcp_cache import McpCache as _McpCache
        _tool_args = args.get("tool_args", {})
        _mcp_cache: _McpCache | None = None
        try:
            _mcp_cache = _McpCache()
            _cached = _mcp_cache.get(tool_name, _tool_args)
            if _cached is not None:
                return {"return_code": 0, "stdout": _cached, "stderr": ""}
        except Exception:
            pass  # cache failure must never block live execution
        # --- End MCP Cache check ---

        config_path = Path(__file__).parent.parent / "config" / "arke.toml"
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                servers = config.get("mcp_servers", {})
                
                if server_name not in servers:
                    return {
                        "return_code": 1,
                        "stdout": "",
                        "stderr": f"MCP: serveur inconnu: {server_name}. Disponibles: {list(servers.keys())}"
                    }
                
                cfg = servers[server_name]
                if not cfg.get("enabled", True):
                    return {
                        "return_code": 1,
                        "stdout": "",
                        "stderr": f"MCP: serveur désactivé: {server_name}"
                    }
                
                request = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args.get("tool_args", {})},
                    "id": 1
                }
                
                proc = subprocess.run(
                    [cfg["command"]] + cfg.get("args", []),
                    input=json.dumps(request),
                    capture_output=True,
                    text=True,
                    timeout=cfg.get("timeout", 30)
                )
                
                if proc.returncode != 0:
                    return {
                        "return_code": 1,
                        "stdout": "",
                        "stderr": f"MCP {server_name} error: {proc.stderr[:500]}"
                    }
                
                response = json.loads(proc.stdout)
                result_content = response.get("result", {}).get("content", [])
                
                if result_content:
                    result_text = result_content[0].get("text", "{}")
                    try:
                        result_json = json.loads(result_text)
                        _out = json.dumps(result_json, indent=2)
                        try:
                            if _mcp_cache is not None:
                                _mcp_cache.put(tool_name, _tool_args, _out)
                        except Exception:
                            pass
                        return {
                            "return_code": 0,
                            "stdout": _out,
                            "stderr": ""
                        }
                    except:
                        try:
                            if _mcp_cache is not None:
                                _mcp_cache.put(tool_name, _tool_args, result_text)
                        except Exception:
                            pass
                        return {
                            "return_code": 0,
                            "stdout": result_text,
                            "stderr": ""
                        }
                
                return {
                    "return_code": 1,
                    "stdout": "",
                    "stderr": "MCP: réponse vide"
                }
        except Exception as e:
            return {
                "return_code": 1,
                "stdout": "",
                "stderr": f"MCP error: {str(e)}"
            }
    
    # Mode 2: Legacy ContextForge
    from arke.interfaces.mcp_client import McpClient, McpUnavailableError

    try:
        client = McpClient()
        tool_name: str | None = step.arguments.get("tool_name")
        tool_args: dict = step.arguments.get("tool_args", {})

        if tool_name is None:
            tools = client.list_tools()
            if not tools:
                return {
                    "return_code": 1,
                    "stdout": "",
                    "stderr": "MCP: no tools available from ContextForge",
                }
            tool_name = tools[0]["name"]
        
        result = client.call_tool(tool_name, tool_args)
        return {
            "return_code": 0,
            "stdout": json.dumps(result, indent=2),
            "stderr": ""
        }
    except McpUnavailableError as e:
        return {
            "return_code": 1,
            "stdout": "",
            "stderr": f"MCP unavailable: {e}",
        }


def _extract_text(output: Any) -> str:
    """Pull plain text from an executor output dict."""
    if isinstance(output, dict):
        return output.get("stdout", "")
    return str(output)


# ---------------------------------------------------------------------------
# Agent mode — tool permission matrix (source: arke.mode_manager)
# ---------------------------------------------------------------------------

from arke.mode_manager import MODE_PERMISSIONS, can_execute_tool  # noqa: E402



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
