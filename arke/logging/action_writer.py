"""Action audit log writer with daily rotation and fsync durability.

Format: JSONL (one JSON event per line) with automatic daily rotation.
No errors from logging should crash the agent (fail-silent design).
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


def mask_secrets(command: str) -> str:
    """Masquer les secrets dans les commandes CLI avant logging."""
    if not command:
        return command
    
    patterns = [
        (r'--password[=\s]\S+', '--password=***'),
        (r'-p\s+\S+', '-p ***'),
        (r'-u\s+[^\s:]+:[^\s]+', '-u user:***'),  # curl -u user:password
        (r'--token[=\s]\S+', '--token=***'),
        (r'TOKEN=\S+', 'TOKEN=***'),
        (r'Authorization:\s+Bearer\s+\S+', 'Authorization: Bearer ***'),
        (r'api[_-]key[=\s]\S+', 'api_key=***'),
    ]
    
    result = command
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def truncate_command(command: str, max_len: int = 100) -> str:
    """Truncate command with ellipsis indicator if too long."""
    if len(command) <= max_len:
        return command
    return command[:max_len - 3] + "..."


def log_action(
    logs_dir: Path,
    session_id: str,
    mode: str,
    tool: str,
    action: str,
    command: Optional[str] = None,
    rc: int = 0,
    duration_ms: int = 0,
    step: int = 0,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Append action to audit log (JSONL) with automatic daily rotation.
    
    Args:
        logs_dir: Path to logs directory (.arke/logs)
        session_id: Current session identifier
        mode: Agent mode (ask, search, plan, agent)
        tool: Tool used (cli, fs, sqlite, mcp, memory, etc.)
        action: Action type (execute, read, write, search, etc.)
        command: Optional command or query executed (will be masked)
        rc: Return code (0 = success)
        duration_ms: Duration in milliseconds
        step: Step number in task sequence
        details: Optional extra fields (files modified, tokens, etc.)
    """
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        log_path = logs_dir / f"actions_{date_str}.log"
        
        # Mask secrets and truncate command
        safe_command = None
        if command:
            safe_command = truncate_command(mask_secrets(command))
        
        event = {
            "ts": now.isoformat(timespec="milliseconds"),
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "mode": mode,
            "tool": tool,
            "action": action,
            "command": safe_command,
            "rc": rc,
            "duration_ms": duration_ms,
            "step": step,
            "details": details or {},
        }
        
        # Append to log with fsync durability
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    
    except OSError:
        # Fail silently — logging errors must never crash the agent
        pass
