"""Tests for Phase 4 action logging and session state management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arke.logging.action_writer import log_action, mask_secrets, truncate_command
from arke.session.state_manager import SessionStateManager


class TestActionWriter:
    def test_log_action_creates_daily_file(self, tmp_path):
        """Verify action log creates daily-rotated JSONL files."""
        logs_dir = tmp_path / "logs"
        log_action(logs_dir, "sess1", "ask", "cli", "execute", "ls -la", 0, 100, 1)
        
        files = list(logs_dir.glob("actions_*.log"))
        assert len(files) == 1
        assert "actions_" in files[0].name
        
        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        
        event = json.loads(lines[0])
        assert event["event_id"].startswith("evt_")
        assert event["rc"] == 0
        assert event["tool"] == "cli"
        assert event["session_id"] == "sess1"
    
    def test_log_action_masks_secrets(self, tmp_path):
        """Verify secrets are masked in logged commands."""
        logs_dir = tmp_path / "logs"
        log_action(logs_dir, "sess1", "ask", "cli", "execute", "curl -u user:password123 https://api.example.com", 0, 50, 1)
        
        lines = list(logs_dir.glob("actions_*.log"))[0].read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[0])
        
        assert "password123" not in event["command"]
        assert "***" in event["command"]
    
    def test_log_action_truncates_long_commands(self, tmp_path):
        """Verify long commands are truncated with ellipsis."""
        logs_dir = tmp_path / "logs"
        long_cmd = "a" * 200
        log_action(logs_dir, "sess1", "ask", "cli", "execute", long_cmd, 0, 50, 1)
        
        lines = list(logs_dir.glob("actions_*.log"))[0].read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[0])
        
        assert len(event["command"]) <= 103  # 100 max + "..."
        assert event["command"].endswith("...")


class TestMaskSecrets:
    def test_mask_password_flag(self):
        cmd = "mysql -u root --password=secret123 -h localhost"
        masked = mask_secrets(cmd)
        assert "secret123" not in masked
        assert "--password=***" in masked
    
    def test_mask_bearer_token(self):
        cmd = "curl -H 'Authorization: Bearer sk_test_abc123xyz' https://api.example.com"
        masked = mask_secrets(cmd)
        assert "sk_test_abc123xyz" not in masked
        assert "Bearer ***" in masked


class TestTruncateCommand:
    def test_short_command_unchanged(self):
        cmd = "ls -la"
        assert truncate_command(cmd) == cmd
    
    def test_long_command_truncated_with_ellipsis(self):
        cmd = "a" * 150
        truncated = truncate_command(cmd, max_len=100)
        assert len(truncated) == 100
        assert truncated.endswith("...")


class TestSessionStateManager:
    def test_new_session_initialization(self, tmp_path):
        """Verify new session initializes correctly."""
        state_mgr = SessionStateManager(tmp_path)
        
        assert state_mgr.session_id.startswith("session_")
        assert state_mgr.state["messages_count"] == 0
        assert state_mgr.state["crashed"] is False
    
    def test_record_message_increments_count(self, tmp_path):
        """Verify message recording increments counter."""
        state_mgr = SessionStateManager(tmp_path)
        
        for i in range(7):
            state_mgr.record_message()
        
        assert state_mgr.state["messages_count"] == 7
        assert state_mgr.state["last_checkpoint_step"] == 5  # checkpoint at 5
    
    def test_checkpoint_saves_atomically(self, tmp_path):
        """Verify checkpoints are saved atomically."""
        state_mgr = SessionStateManager(tmp_path)
        
        for _ in range(5):
            state_mgr.record_message()
        
        state_file = tmp_path / "state.json"
        assert state_file.exists()
        
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["messages_count"] == 5
        assert saved["last_checkpoint_step"] == 5
    
    def test_crash_detection_and_resume(self, tmp_path):
        """Verify crash detection and session reuse on resume."""
        # First session: incomplete (no closed_at)
        state_mgr1 = SessionStateManager(tmp_path, proposed_session_id="session_001")
        state_mgr1.record_message()
        state_mgr1.checkpoint()
        
        # Simulate second run (crash recovery)
        state_mgr2 = SessionStateManager(tmp_path)
        
        # Should detect crash and reuse session_id
        assert state_mgr2.state["crashed"] is True
        assert state_mgr2.state["resumed_from"] == "session_001"
    
    def test_close_session_marks_completion(self, tmp_path):
        """Verify session closure marks it as complete."""
        state_mgr = SessionStateManager(tmp_path)
        state_mgr.record_message()
        state_mgr.close_session()
        
        state_file = tmp_path / "state.json"
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        
        assert saved["closed_at"] is not None
    
    def test_record_tool_usage(self, tmp_path):
        """Verify tool and mode tracking."""
        state_mgr = SessionStateManager(tmp_path)
        
        state_mgr.record_tool_usage("cli", "ask")
        state_mgr.record_tool_usage("fs", "agent")
        state_mgr.record_tool_usage("cli", "agent")  # Duplicate, should not add
        
        assert len(state_mgr.state["tools_used"]) == 2
        assert "cli" in state_mgr.state["tools_used"]
        assert state_mgr.state["mode_current"] == "agent"
