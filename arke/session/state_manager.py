"""Session state management with checkpoint-and-resume semantics (Phase 4)."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


class SessionStateManager:
    """Manages session state with crash detection and checkpoint recovery."""
    
    def __init__(self, arke_root: Path, proposed_session_id: Optional[str] = None):
        """Initialize or resume session state.
        
        Args:
            arke_root: Path to .arke directory
            proposed_session_id: Optional session ID to use (for testing)
        """
        self.arke_root = arke_root
        self.state_path = arke_root / "state.json"
        self.checkpoint_interval = 5
        self.messages_count = 0
        self.tools_used: set = set()
        self.modes_used: set = set()
        
        if proposed_session_id:
            self.session_id = proposed_session_id
        else:
            self.session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        self.state = self._load_or_init()
        self.messages_count = int(self.state.get("messages_count", 0))
        # Persist normalized schema immediately so state.json is always complete.
        self.checkpoint()

    def _base_state(self) -> Dict[str, Any]:
        """Return base state schema for a fresh session."""
        return {
            "session_id": self.session_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_active_at": None,
            "mode_initial": "ask",
            "mode_current": "ask",
            "messages_count": 0,
            "modes_used": ["ask"],
            "tools_used": [],
            "last_checkpoint_step": 0,
            "checkpoint_interval": self.checkpoint_interval,
            "preferences": {},
            "crashed": False,
            "resumed_from": None,
            "closed_at": None,
            "migrated_from": [],
            "last_synced_workspace": None,
        }
    
    def _load_or_init(self) -> Dict[str, Any]:
        """Load existing state or initialize new session."""
        base = self._base_state()

        if self.state_path.exists():
            try:
                raw_state = json.loads(self.state_path.read_text(encoding="utf-8"))

                # Bootstrap placeholder written by ensure_arke_workspace() is not a real session yet.
                if raw_state.get("workspace_initialized") and not raw_state.get("session_id"):
                    return base

                state = dict(raw_state)

                # Normalize missing keys from legacy/bootstrap state.
                for key, value in base.items():
                    state.setdefault(key, value)

                # Detect crash: prior session exists and was not closed cleanly.
                if state.get("session_id") and not state.get("closed_at"):
                    state["crashed"] = True
                    state["resumed_from"] = state.get("session_id")
                    # Reuse session_id if resuming from crash
                    self.session_id = state.get("session_id", self.session_id)
                    state["session_id"] = self.session_id
                else:
                    # Clean close: start fresh session
                    state["session_id"] = self.session_id
                    state["crashed"] = False
                    state["resumed_from"] = None
                    state["closed_at"] = None
                    state["started_at"] = datetime.now(timezone.utc).isoformat()
                
                # Reset messages_count and tools for new run
                state["messages_count"] = 0
                state["tools_used"] = []
                state["modes_used"] = ["ask"]
                state["mode_current"] = "ask"
                state["last_checkpoint_step"] = 0
                return state
            except (json.JSONDecodeError, OSError):
                pass
        
        # New session initialization
        return base
    
    def record_message(self) -> None:
        """Increment message counter and checkpoint if needed."""
        self.messages_count += 1
        self.state["messages_count"] = self.messages_count
        self.state["last_active_at"] = datetime.now(timezone.utc).isoformat()
        
        if self.messages_count % self.checkpoint_interval == 0:
            self.checkpoint()
    
    def record_tool_usage(self, tool: str, mode: str) -> None:
        """Track tool and mode usage."""
        if tool and tool not in self.state["tools_used"]:
            self.state["tools_used"].append(tool)
        
        if mode and mode not in self.state["modes_used"]:
            self.state["modes_used"].append(mode)
        
        if mode:
            self.state["mode_current"] = mode
    
    def checkpoint(self) -> None:
        """Save state atomically to temp file + replace."""
        tmp_path = self.state_path.with_suffix(".tmp")
        self.state["last_checkpoint_step"] = self.messages_count
        
        try:
            tmp_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp_path, self.state_path)
        except OSError:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    
    def close_session(self) -> None:
        """Mark session as cleanly closed."""
        self.state["closed_at"] = datetime.now(timezone.utc).isoformat()
        self.checkpoint()
    
    def get_session_info(self) -> Dict[str, Any]:
        """Return current session state snapshot."""
        return self.state.copy()
