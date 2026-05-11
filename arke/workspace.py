"""
Workspace abstraction layer for Passive User Workspace (PUW) integration.

CRITICAL: This module is orchestrator-only. Never expose to LLM context.
Never import in LLM interfaces (llm/litellm_manager.py, chat.py LLM paths).
Telegram bot and other interfaces MUST NOT access this directly.

All filesystem operations to WCU go through the orchestrator via intent mapping.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class WorkspaceManager:
    """Manages PUW (Passive User Workspace) filesystem operations."""

    # Intent-to-path mapping (orchestrator authority)
    INTENT_PATH_MAP = {
        # Layer 1: mobile-notes (capture)
        "STORE_MOBILE_NOTE_TELEGRAM": "mobile-notes/channels/telegram/",
        "STORE_MOBILE_NOTE_DISCORD": "mobile-notes/channels/discord/",
        "STORE_MOBILE_NOTE_EMAIL": "mobile-notes/channels/email/",
        "STORE_MOBILE_NOTE_OBSIDIAN": "mobile-notes/channels/obsidian/",
        "STORE_MOBILE_NOTE_API": "mobile-notes/channels/api/",
        "CAPTURE_QUICK_NOTE": "mobile-notes/quick-capture/",
        "CAPTURE_FLEETING": "mobile-notes/fleeting/",
        "CAPTURE_IDEA": "mobile-notes/ideas/",
        "CAPTURE_VOICE": "mobile-notes/voice/",
        
        # Layer 4: shared (restitution)
        "WRITE_SESSION_SUMMARY": "shared/session-summaries/",
        "LOG_DECISION": "projects/TEMP/meta-decisions/",
        "EXPORT_SHARED_INSIGHT": "shared/generated-insights/",
        "LOG_USER_FACING_EVENT": "shared/user-facing-logs/",
        "UPDATE_COGNITIVE_THREAD": "shared/cognitive-threads/",
        "RECAP_DECISION": "shared/decision-recaps/",
        
        # Layer 3: projects/TEMP (structuration)
        "LOG_PROJECT_FEEDBACK": "projects/TEMP/meta-feedback/",
        "LOG_PROJECT_OPS": "projects/TEMP/ops-logs/",
    }

    def __init__(self, wcu_root: Path):
        """
        Initialize WorkspaceManager.
        
        Args:
            wcu_root: Path to WCU root directory (e.g., ~/arke-workspace/WCU)
        """
        self.wcu_root = Path(wcu_root)

    def validate_structure(self) -> bool:
        """
        Validate that WCU directory structure exists.
        
        Returns:
            True if all required directories exist, False otherwise.
        """
        required_dirs = [
            "mobile-notes/channels/{telegram,discord,email,obsidian,api}",
            "mobile-notes/{fleeting,ideas,voice,quick-capture,archive}",
            "code/{apps,services,libs,experiments}",
            "projects/TEMP/{core-overview,core-planning,core-architecture,dev-sessions,dev-tracking,meta-decisions,meta-feedback,ops-logs,ext-extensions,resources,archive}",
            "shared/{session-summaries,decision-recaps,cognitive-threads,generated-insights,user-facing-logs}",
            "archive",
        ]
        
        try:
            # Check main layers exist
            assert (self.wcu_root / "mobile-notes").exists(), "mobile-notes/ missing"
            assert (self.wcu_root / "code").exists(), "code/ missing"
            assert (self.wcu_root / "projects" / "TEMP").exists(), "projects/TEMP/ missing"
            assert (self.wcu_root / "shared").exists(), "shared/ missing"
            assert (self.wcu_root / "archive").exists(), "archive/ missing"
            
            # Check key subfolders
            assert (self.wcu_root / "mobile-notes" / "channels" / "telegram").exists()
            assert (self.wcu_root / "shared" / "session-summaries").exists()
            assert (self.wcu_root / "projects" / "TEMP" / "meta-decisions").exists()
            
            return True
        except AssertionError as e:
            print(f"❌ WCU structure validation failed: {e}")
            return False

    def resolve_intent_path(self, intent: str) -> Optional[Path]:
        """
        Resolve an intent to its WCU storage path.
        
        Args:
            intent: Intent name (e.g., "WRITE_SESSION_SUMMARY")
            
        Returns:
            Full path to storage location, or None if intent unknown.
        """
        if intent not in self.INTENT_PATH_MAP:
            print(f"⚠️  Unknown intent: {intent}")
            return None
        
        relative_path = self.INTENT_PATH_MAP[intent]
        return self.wcu_root / relative_path

    def write_artifact(
        self,
        intent: str,
        content: str,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        Write artifact to WCU based on intent.
        
        Args:
            intent: Intent name (determines path)
            content: Content to write
            filename: Optional custom filename. If None, auto-generates.
            metadata: Optional metadata dict to include (stored as JSON header)
            
        Returns:
            Path to written file, or None if failed.
        """
        target_path = self.resolve_intent_path(intent)
        if not target_path:
            return None
        
        # Ensure directory exists
        target_path.mkdir(parents=True, exist_ok=True)
        
        # Generate filename if not provided
        if filename is None:
            timestamp = datetime.now().isoformat()
            filename = f"{timestamp}_{intent}.md"
        
        file_path = target_path / filename
        
        try:
            # Prepend metadata as YAML frontmatter if provided
            output = content
            if metadata:
                yaml_header = "---\n"
                for key, value in metadata.items():
                    yaml_header += f"{key}: {json.dumps(value)}\n"
                yaml_header += "---\n\n"
                output = yaml_header + content
            
            file_path.write_text(output, encoding="utf-8")
            print(f"✅ Wrote artifact: {file_path.relative_to(self.wcu_root)}")
            return file_path
        except Exception as e:
            print(f"❌ Failed to write artifact: {e}")
            return None

    def read_artifact(self, file_path: Path) -> Optional[str]:
        """
        Read artifact from WCU.
        
        Args:
            file_path: Path to artifact (relative or absolute)
            
        Returns:
            Content of file, or None if failed.
        """
        if not file_path.is_absolute():
            file_path = self.wcu_root / file_path
        
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"❌ Failed to read artifact: {e}")
            return None

    def list_artifacts(self, intent: str) -> Optional[list]:
        """
        List all artifacts for a given intent.
        
        Args:
            intent: Intent name
            
        Returns:
            List of Path objects, or None if intent invalid.
        """
        target_path = self.resolve_intent_path(intent)
        if not target_path or not target_path.exists():
            return None
        
        try:
            return sorted(target_path.glob("*"))
        except Exception as e:
            print(f"❌ Failed to list artifacts: {e}")
            return None

    def get_intent_list(self) -> list:
        """Return list of all available intents."""
        return list(self.INTENT_PATH_MAP.keys())


# Singleton instance (initialized by orchestrator)
_workspace_manager: Optional[WorkspaceManager] = None


def initialize_workspace(wcu_root: Path) -> WorkspaceManager:
    """
    Initialize the workspace manager singleton.
    
    CRITICAL: Call only from orchestrator.py, never from LLM interfaces.
    
    Args:
        wcu_root: Path to WCU root directory
        
    Returns:
        WorkspaceManager instance
    """
    global _workspace_manager
    _workspace_manager = WorkspaceManager(wcu_root)
    
    # Validate structure on init
    if not _workspace_manager.validate_structure():
        print("⚠️  Warning: WCU structure incomplete, will attempt auto-creation")
        _auto_create_structure(wcu_root)
    
    return _workspace_manager


def get_workspace() -> Optional[WorkspaceManager]:
    """Get the workspace manager singleton (after initialization)."""
    return _workspace_manager


def _auto_create_structure(wcu_root: Path):
    """Automatically create missing WCU directories."""
    required_dirs = [
        "mobile-notes/channels/{telegram,discord,email,obsidian,api}",
        "mobile-notes/{fleeting,ideas,voice,quick-capture,archive}",
        "code/{apps,services,libs,experiments}",
        "projects/TEMP/{core-overview,core-planning,core-architecture,dev-sessions,dev-tracking,meta-decisions,meta-feedback,ops-logs,ext-extensions,resources,archive}",
        "shared/{session-summaries,decision-recaps,cognitive-threads,generated-insights,user-facing-logs}",
        "archive",
    ]
    
    try:
        for dir_spec in required_dirs:
            # Expand {a,b,c} patterns
            if "{" in dir_spec:
                base, rest = dir_spec.split("{")
                options, suffix = rest.split("}")
                for opt in options.split(","):
                    full_dir = (wcu_root / base / opt / suffix).resolve()
                    full_dir.mkdir(parents=True, exist_ok=True)
            else:
                (wcu_root / dir_spec).mkdir(parents=True, exist_ok=True)
        
        print(f"✅ WCU structure auto-created at {wcu_root}")
    except Exception as e:
        print(f"❌ Failed to auto-create WCU structure: {e}")


# ============================================================================
# Workspace View System (WVS) — Statistics & Scanning
# ============================================================================

def format_size(size_bytes: int) -> str:
    """
    Format bytes to human-readable size.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.2 MB", "520 KB")
    """
    for unit, divisor in [("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)]:
        if size_bytes >= divisor:
            return f"{size_bytes / divisor:.1f} {unit}"
    return f"{size_bytes} B"


def _scan_section(
    path: Path,
    max_depth: int = 2,
    max_files: int = 50,
    current_depth: int = 0,
) -> Dict[str, Any]:
    """
    Recursively scan a section directory, respecting depth/size limits.
    
    Hides empty directories automatically.
    
    Args:
        path: Directory path to scan
        max_depth: Maximum recursion depth
        max_files: If exceeded, set truncated=True and stop
        current_depth: Current recursion depth (internal)
        
    Returns:
        Dict with keys:
            - files: int (total count)
            - size_bytes: int (total size)
            - subdirs: list of dict (subdirectory details, max 2 levels)
            - truncated: bool (true if size limit exceeded)
    """
    result = {
        "files": 0,
        "size_bytes": 0,
        "subdirs": [],
        "truncated": False,
    }
    
    if not path.exists():
        return result
    
    try:
        items = sorted(path.iterdir())
        
        for item in items:
            if result["files"] > max_files:
                result["truncated"] = True
                break
            
            if item.is_file():
                result["files"] += 1
                result["size_bytes"] += item.stat().st_size
            elif item.is_dir() and current_depth < max_depth:
                subdir_scan = _scan_section(
                    item,
                    max_depth=max_depth,
                    max_files=max_files,
                    current_depth=current_depth + 1,
                )
                
                # Only include non-empty subdirectories
                if subdir_scan["files"] > 0 or subdir_scan["subdirs"]:
                    result["subdirs"].append({
                        "name": item.name,
                        "files": subdir_scan["files"],
                        "size_bytes": subdir_scan["size_bytes"],
                        "subdirs": subdir_scan["subdirs"],
                        "truncated": subdir_scan["truncated"],
                    })
                    result["files"] += subdir_scan["files"]
                    result["size_bytes"] += subdir_scan["size_bytes"]
    
    except Exception as e:
        print(f"⚠️  Warning scanning {path}: {e}")
    
    return result


def get_workspace_stats(wcu_root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Scan WCU and return statistics by section.
    
    CRITICAL: This is orchestrator-only. Never expose to LLM.
    
    Args:
        wcu_root: Path to WCU root directory
        
    Returns:
        Dict mapping section name → stats dict:
        {
            "mobile-notes": {
                "files": 44,
                "size_bytes": 520000,
                "size_formatted": "520 KB",
                "subdirs": [{...}],
                "truncated": False,
            },
            ...
        }
    """
    wcu_root = Path(wcu_root)
    sections = ["mobile-notes", "code", "projects", "shared", "archive"]
    
    stats = {}
    
    for section in sections:
        section_path = wcu_root / section
        
        if section == "projects":
            # Special case: projects/TEMP
            section_path = section_path / "TEMP"
        
        section_stats = _scan_section(section_path, max_depth=2, max_files=50)
        section_stats["size_formatted"] = format_size(section_stats["size_bytes"])
        
        stats[section] = section_stats
    
    return stats
