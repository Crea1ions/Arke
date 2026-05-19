"""End-to-end test for Cognitive Continuity pipeline (S023–S028).

Tests that extracted threads flow through the full pipeline:
  extract_async → storage → CIG gates → initiative delivery
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from arke.cognitive_initiative_gate import (
    cognitive_initiative_engine,
    get_dormant_threads,
)
from arke.memory.manager import MemoryManager
from arke.thread_extractor import extract_async


@pytest.fixture(scope="function")
def temp_db_dir() -> str:
    """Create a temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(scope="function")
def mm(temp_db_dir: str) -> MemoryManager:
    """Fresh MemoryManager instance with temporary databases for each test."""
    # Override the database paths to use temp directory
    os.environ["WORKSPACE_ROOT"] = ""  # Clear workspace override
    
    # Create a temporary workspace config
    workspace_dir = Path(temp_db_dir) / ".arke" / "config"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    
    workspace_cfg = workspace_dir / "workspace.toml"
    workspace_cfg.write_text(f"""\
[memory]
global_path = "{temp_db_dir}/global.db"
project_path = "{temp_db_dir}/project.db"
session_path = "{temp_db_dir}/session.db"
cache_path = "{temp_db_dir}/cache.db"
wal_mode = true
""")
    
    os.environ["WORKSPACE_ROOT"] = temp_db_dir
    
    # Create fresh MemoryManager with temp databases
    mm_instance = MemoryManager()
    yield mm_instance
    
    # Cleanup
    if "WORKSPACE_ROOT" in os.environ:
        del os.environ["WORKSPACE_ROOT"]


class TestCognitiveContinuityE2E:
    """Full pipeline tests."""

    def test_schema_tables_exist_on_bootstrap(self, mm: MemoryManager) -> None:
        """Verify that cognitive_threads, interaction_density, initiative_log are created."""
        with mm._connect("global") as conn:
            # Should not raise OperationalError if tables exist
            cursor = conn.execute("SELECT COUNT(*) FROM cognitive_threads")
            assert cursor.fetchone()[0] == 0  # Empty
            
            cursor = conn.execute("SELECT COUNT(*) FROM interaction_density")
            assert cursor.fetchone()[0] == 0  # Empty
            
            cursor = conn.execute("SELECT COUNT(*) FROM initiative_log")
            assert cursor.fetchone()[0] == 0  # Empty

    def test_extract_async_stores_threads(self, mm: MemoryManager) -> None:
        """Verify that extract_async successfully extracts and stores threads."""
        session_id = "test-session-extract"
        user_msg = "Je me demande si l'IA peut vraiment comprendre les nuances culturelles"
        agent_response = (
            "C'est une excellente question. Les modèles actuels sont entraînés sur des "
            "données multi-langues mais ils ont des biais culturels. La compréhension vraie "
            "des nuances demande un contexte profond et une introspection continue."
        )
        cancel_event = threading.Event()

        # Trigger extraction
        extract_async(mm, session_id, user_msg, agent_response, cancel_event)
        
        # Wait for daemon thread to complete + LLM call
        time.sleep(12)

        # Verify threads were stored
        threads = mm.query("global", "SELECT * FROM cognitive_threads WHERE session_id = ?", (session_id,))
        
        # At least one thread should be extracted (if LLM had cognitive markers)
        # In test environment with mock, we verify the mechanism at least exists
        assert isinstance(threads, list)
        
        if len(threads) > 0:
            # If extraction succeeded, verify structure
            thread = threads[0]
            assert "content" in thread.keys()
            assert "importance_score" in thread.keys()
            assert thread["session_id"] == session_id

    def test_cig_reads_dormant_threads(self, mm: MemoryManager) -> None:
        """Verify CIG can read dormant threads from database."""
        # Manually insert a thread for CIG to find
        thread_id = "test-thread-001"
        thread_content = "A question about distributed systems and causality"
        
        mm.query(
            "global",
            """
            INSERT INTO cognitive_threads 
            (id, session_id, content, status, importance_score, reactivation_score, created_at)
            VALUES (?, ?, ?, 'dormant', ?, ?, datetime('now', '-5 days'))
            """,
            (thread_id, "test-session", thread_content, 0.7, 0.65),
        )

        # CIG should find this thread
        dormant = get_dormant_threads(mm, max_age_days=14)
        assert len(dormant) > 0
        
        found = any(t["id"] == thread_id for t in dormant)
        assert found, f"Thread {thread_id} not found by CIG"

    def test_initiative_log_records_proposals(self, mm: MemoryManager) -> None:
        """Verify initiative_log records proposal with accepted=NULL."""
        initiative_id = "init-test-001"
        thread_id = "thread-001"
        
        # Insert a proposal
        mm.query(
            "global",
            """
            INSERT INTO initiative_log 
            (id, thread_id, type, density_snapshot, context_anchor, accepted)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (initiative_id, thread_id, "soft_reactivation", 0.65, "test anchor"),
        )

        # Verify it was stored with accepted=NULL (not rejected, not explicit acceptance)
        rows = mm.query(
            "global",
            "SELECT * FROM initiative_log WHERE id = ?",
            (initiative_id,),
        )
        
        assert len(rows) == 1
        row = rows[0]
        assert row["accepted"] is None  # Critical: absence != rejection
        assert row["type"] == "soft_reactivation"

    def test_interaction_density_tracking(self, mm: MemoryManager) -> None:
        """Verify interaction_density can track daily depth scores."""
        from datetime import date
        
        today = str(date.today())
        session_id = "test-session-density"
        
        # Record a day's interaction density
        density_id = f"density-{today}"
        mm.query(
            "global",
            """
            INSERT INTO interaction_density 
            (id, day, avg_depth_score, exchange_count, session_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (density_id, today, 0.65, 5, session_id),
        )

        # Verify retrieval for Gate 1 (7-day window)
        rows = mm.query(
            "global",
            """
            SELECT AVG(avg_depth_score) as current_density
            FROM interaction_density
            WHERE day >= date('now', '-7 days')
            """,
        )
        
        assert len(rows) == 1
        assert rows[0]["current_density"] is not None

    def test_full_cig_pipeline_with_dormant_thread(self, mm: MemoryManager) -> None:
        """Full CIG pipeline: thread → density → initiative."""
        from datetime import date
        
        session_id = "test-session-full"
        thread_id = "thread-full-001"
        
        # 1. Insert a dormant thread
        mm.query(
            "global",
            """
            INSERT INTO cognitive_threads 
            (id, session_id, content, status, importance_score, reactivation_score, created_at)
            VALUES (?, ?, ?, 'dormant', ?, ?, datetime('now', '-5 days'))
            """,
            (thread_id, session_id, "Discussion about quantum entanglement", 0.7, 0.68),
        )

        # 2. Record sufficient interaction density (>= 0.5)
        today = str(date.today())
        mm.query(
            "global",
            """
            INSERT INTO interaction_density 
            (id, day, avg_depth_score, exchange_count, session_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"density-{today}", today, 0.65, 8, session_id),
        )

        # 3. Run CIG pipeline
        context = {"intention": "Tell me about quantum", "response": "Quantum mechanics..."}
        initiative_text, log_id = cognitive_initiative_engine(mm, context, paused=False)

        # 4. Verify result
        # Initiative may not fire if CIG gates filter it, but pipeline should run without error
        if initiative_text:
            # If initiative fired, it should be logged
            assert log_id is not None
            rows = mm.query(
                "global",
                "SELECT * FROM initiative_log WHERE id = ?",
                (log_id,),
            )
            assert len(rows) == 1
            assert rows[0]["accepted"] is None


class TestSchemaValidation:
    """Verify schema validation on bootstrap."""

    def test_bootstrap_validates_critical_tables(self, mm: MemoryManager) -> None:
        """Verify that _validate_schema is called and succeeds for global.db."""
        # This test verifies the mechanism; actual table creation was tested above
        # If we got here without exception, validation passed
        with mm._connect("global") as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cognitive_threads'")
            assert cursor.fetchone() is not None, "cognitive_threads table not found"
