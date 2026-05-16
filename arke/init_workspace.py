"""Workspace bootstrap for per-project `.arke` initialization.

This module creates and maintains the local workspace runtime area:

- `.arke/config`
- `.arke/sessions`
- `.arke/logs`
- `.arke/memory`
- `.arke/state.json`
- `.arke/config/workspace.toml`

All operations are idempotent and best-effort: initialization issues are
reported as warnings and should not crash the CLI startup flow.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

import structlog

log = structlog.get_logger()


@dataclass(slots=True)
class WorkspaceInitResult:
    """Outcome of a workspace bootstrap attempt."""

    workspace_root: Path
    arke_root: Path
    created: bool = False
    created_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gitignore_updated: bool = False


def resolve_workspace_root(workspace_root: Path | None = None) -> Path:
    """Resolve workspace root with priority: arg > env > cwd."""
    if workspace_root is not None:
        return Path(workspace_root).expanduser().resolve()

    env_root = os.environ.get("WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    return Path.cwd().resolve()


def _atomic_write_text(target: Path, content: str) -> None:
    """Atomically write text content to *target* via temp file + replace."""
    tmp_path = target.with_suffix(f"{target.suffix}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, target)


def _normalize_state_payload(payload: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Ensure required state.json keys exist for backward compatibility."""
    normalized = dict(payload)
    normalized.setdefault("workspace_initialized", True)
    normalized.setdefault("initialized_at", now.isoformat())
    normalized.setdefault("legacy_migration", {"prompted": False, "accepted": False})
    normalized.setdefault("last_synced_workspace", None)
    return normalized


def _ensure_state_schema(state_path: Path, now: datetime) -> None:
    """Patch existing state.json files with missing keys (idempotent)."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    normalized = _normalize_state_payload(state, now)
    if normalized != state:
        _atomic_write_text(
            state_path,
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        )


def get_last_synced_workspace(workspace_root: Path | None = None) -> str | None:
    """Return the last synced workspace path stored in .arke/state.json."""
    root = resolve_workspace_root(workspace_root)
    state_path = root / ".arke" / "state.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = state.get("last_synced_workspace")
    return str(value) if value else None


def update_last_synced_workspace(
    synced_workspace_root: Path | str,
    state_workspace_root: Path | None = None,
) -> bool:
    """Update last_synced_workspace in .arke/state.json.

    Args:
        synced_workspace_root: Workspace path that was synced.
        state_workspace_root: Workspace containing .arke/state.json (defaults to resolved current root).
    """
    root = resolve_workspace_root(state_workspace_root)
    state_path = root / ".arke" / "state.json"
    if not state_path.exists():
        return False

    now = datetime.now(timezone.utc)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    normalized = _normalize_state_payload(state, now)
    normalized["last_synced_workspace"] = str(Path(synced_workspace_root).expanduser().resolve())
    try:
        _atomic_write_text(
            state_path,
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        )
        return True
    except OSError:
        return False


def _default_workspace_toml(now: datetime) -> str:
    session_name = f"session_{now.strftime('%Y%m%d')}.db"
    return (
        "[workspace]\n"
        "root = \".\"\n\n"
        "[security]\n"
        "sandbox_mode = \"workspace\"\n\n"
        "[agent]\n"
        "mode = \"default\"\n"
        "supports_simultaneous_sessions = false\n\n"
        "[memory]\n"
        "global_path = \".arke/memory/global.db\"\n"
        "project_path = \".arke/memory/project.db\"\n"
        f"session_path = \".arke/sessions/{session_name}\"\n"
        "cache_path = \".arke/memory/cache.db\"\n"
    )


def _detect_and_migrate_legacy(arke_root: Path, workspace_root: Path) -> Dict[str, Any]:
    """Detect and propose migration of legacy Arke data.
    
    Returns:
        {"migrated": bool, "sources": list[str]}
    """
    legacy_paths = [
        Path.home() / ".local" / "share" / "arke",
        Path.home() / ".arke",
        workspace_root / "arke-workspace",
        workspace_root / "arke-agent-workspace",
    ]
    
    found = [p for p in legacy_paths if p.exists()]
    if not found:
        return {"migrated": False, "sources": []}

    # Startup must stay quiet by default: interactive legacy migration is opt-in.
    if os.environ.get("ARKE_ENABLE_LEGACY_MIGRATION_PROMPT", "0") != "1":
        return {"migrated": False, "sources": found}

    state_file = arke_root / "state.json"
    state_payload: Dict[str, Any] = {}
    migration_state: Dict[str, Any] = {}
    if state_file.exists():
        try:
            state_payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state_payload = {}
    migration_state = dict(state_payload.get("legacy_migration", {}))
    if migration_state.get("prompted") is True:
        return {"migrated": False, "sources": found}
    
    # Non-interactive context: skip migration
    if not sys.stdin.isatty():
        log.info("migration.skipped_non_interactive", legacy_count=len(found))
        return {"migrated": False, "sources": found}
    
    # Prompt en français (défaut: N)
    prompt_text = "Anciennes données Arke détectées dans:\n"
    for p in found:
        prompt_text += f"  - {p}\n"
    prompt_text += f"\nVoulez-vous les migrer vers {arke_root}/ ? (o/N) "
    
    try:
        response = input(prompt_text).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return {"migrated": False, "sources": found}
    
    if response != "o":
        state_payload["legacy_migration"] = {"prompted": True, "accepted": False}
        try:
            state_file.write_text(
                json.dumps(state_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        log.info("migration.declined_by_user")
        return {"migrated": False, "sources": found}
    
    # Migrate sessions
    legacy_sessions = [p / "sessions" for p in found if (p / "sessions").exists()]
    if legacy_sessions:
        dest = arke_root / "sessions" / "legacy"
        dest.mkdir(parents=True, exist_ok=True)
        for src_dir in legacy_sessions:
            for f in src_dir.glob("*"):
                if not (dest / f.name).exists():
                    try:
                        shutil.copy2(f, dest / f.name)
                    except OSError:
                        pass
    
    # Migrate logs
    legacy_logs = [p / "logs" for p in found if (p / "logs").exists()]
    if legacy_logs:
        dest = arke_root / "logs" / "legacy"
        dest.mkdir(parents=True, exist_ok=True)
        for src_dir in legacy_logs:
            for f in src_dir.glob("*"):
                if not (dest / f.name).exists():
                    try:
                        shutil.copy2(f, dest / f.name)
                    except OSError:
                        pass
    
    # Record migration in state.json
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["migrated_from"] = [str(p) for p in found]
            state["legacy_migration"] = {"prompted": True, "accepted": True}
            state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass
    
    log.info("migration.completed", sources=len(found))
    return {"migrated": True, "sources": found}


def _ensure_gitignore_entry(workspace_root: Path) -> bool:
    """Ensure `.arke/` is ignored. Returns True when file was updated."""
    gitignore_path = workspace_root / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(".arke/\n", encoding="utf-8")
        return True

    lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    normalized = {line.strip() for line in lines}
    if ".arke/" in normalized or ".arke" in normalized:
        return False

    suffix = "\n" if lines else ""
    gitignore_path.write_text(gitignore_path.read_text(encoding="utf-8") + suffix + ".arke/\n", encoding="utf-8")
    return True


def ensure_arke_workspace(workspace_root: Path | None = None) -> WorkspaceInitResult:
    """Create `.arke` workspace structure if missing.

    This function is idempotent and non-throwing by design. Any operational
    issue is captured in the returned warnings.
    """
    root = resolve_workspace_root(workspace_root)
    arke_root = root / ".arke"
    now = datetime.now(timezone.utc)

    result = WorkspaceInitResult(workspace_root=root, arke_root=arke_root)

    required_dirs = [
        arke_root,
        arke_root / "config",
        arke_root / "sessions",
        arke_root / "logs",
        arke_root / "memory",
    ]

    for directory in required_dirs:
        try:
            pre_exists = directory.exists()
            directory.mkdir(parents=True, exist_ok=True)
            if not pre_exists:
                result.created = True
                result.created_paths.append(str(directory.relative_to(root)))
        except OSError as exc:
            result.warnings.append(f"mkdir_failed:{directory}:{exc}")
            return result

    state_path = arke_root / "state.json"
    if not state_path.exists():
        payload = _normalize_state_payload({}, now)
        try:
            _atomic_write_text(state_path, json.dumps(payload, indent=2) + "\n")
            result.created = True
            result.created_paths.append(str(state_path.relative_to(root)))
        except OSError as exc:
            result.warnings.append(f"state_write_failed:{state_path}:{exc}")
    else:
        try:
            _ensure_state_schema(state_path, now)
        except OSError as exc:
            result.warnings.append(f"state_schema_update_failed:{state_path}:{exc}")

    workspace_cfg = arke_root / "config" / "workspace.toml"
    if not workspace_cfg.exists():
        try:
            workspace_cfg.write_text(_default_workspace_toml(now), encoding="utf-8")
            result.created = True
            result.created_paths.append(str(workspace_cfg.relative_to(root)))
        except OSError as exc:
            result.warnings.append(f"workspace_toml_failed:{workspace_cfg}:{exc}")

    try:
        result.gitignore_updated = _ensure_gitignore_entry(root)
    except OSError as exc:
        result.warnings.append(f"gitignore_update_failed:{root / '.gitignore'}:{exc}")

    # Phase 5: Detect and propose legacy data migration
    try:
        migration_result = _detect_and_migrate_legacy(arke_root, root)
        if migration_result["migrated"]:
            result.created_paths.append("legacy/sessions/")
            result.created_paths.append("legacy/logs/")
    except Exception as e:
        result.warnings.append(f"migration_attempt_failed:{e}")

    return result
