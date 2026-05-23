"""Tests for arke.cognitive_initiative_gate — CIG Phase 1.

All tests use an in-memory SQLite fixture that exposes the MemoryManager
interface (mm.query(db, sql, params)) without touching disk databases.

Invariants verified:
- Gates return (None, None) when conditions are not met
- No initiative when paused
- No initiative when density below threshold
- No initiative when no eligible dormant threads
- No initiative when keyword overlap < 2
- Initiative generated when all gates pass
- initiative_log rows: accepted defaults to NULL (not False)
- auto_calibrate: adjusts threshold on ≥ 30 explicit samples
- auto_calibrate: no change when samples < 30
"""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import MagicMock

import pytest

from unittest.mock import patch

from arke.cognitive_initiative_gate import (
    _DEFAULTS,
    _apply_decay,
    _cosine_similarity,
    _get_hybrid_context_candidates,
    auto_calibrate_threshold,
    cognitive_initiative_engine,
    compute_interaction_density,
    compute_utility_score,
    detect_positive_signal,
    generate_soft_reactivation,
    get_divergent_thread,
    get_dormant_threads,
    is_contextually_anchored,
    log_initiative,
    mark_initiative_accepted,
)
from arke.vector.embedder import VectorDisabledError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_global_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interaction_density (
            day TEXT PRIMARY KEY,
            exchange_count INTEGER DEFAULT 0,
            avg_depth_score REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS cognitive_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL DEFAULT 'test',
            content TEXT NOT NULL,
            summary TEXT,
            importance_score REAL DEFAULT 0.5,
            reactivation_score REAL DEFAULT 0,
            density_context REAL,
            status TEXT DEFAULT 'open',
            activation_count INTEGER DEFAULT 0,
            ignored_count INTEGER DEFAULT 0,
            last_activated_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            tags TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS initiative_log (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            type TEXT DEFAULT 'soft_reactivation',
            density_snapshot REAL,
            accepted INTEGER DEFAULT NULL,
            context_anchor TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content);
    """)
    conn.commit()


@pytest.fixture()
def mm():
    """MemoryManager mock backed by an in-memory SQLite for global.db queries."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_global_schema(conn)

    mock = MagicMock()

    def _query(db: str, sql: str, params: tuple = ()):
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.fetchall()

    mock.query.side_effect = _query
    mock._conn = conn  # expose for assertions
    return mock


def _seed_density(mm, avg_depth_score: float) -> None:
    """Insert 7 days of density rows so AVG returns avg_depth_score."""
    for i in range(7):
        mm.query(
            "global",
            "INSERT OR REPLACE INTO interaction_density (day, exchange_count, avg_depth_score) "
            "VALUES (date('now', ?), 5, ?)",
            (f"-{i} days", avg_depth_score),
        )


def _seed_dormant_thread(mm, reactivation_score: float = 0.8,
                          content: str = "problème connexion réseau timeout",
                          summary: str = "bug réseau timeout") -> int:
    mm.query(
        "global",
        "INSERT INTO cognitive_threads (content, summary, status, reactivation_score, importance_score) "
        "VALUES (?, ?, 'dormant', ?, ?)",
        (content, summary, reactivation_score, reactivation_score),
    )
    rows = mm.query("global", "SELECT last_insert_rowid() AS id", ())
    return rows[0]["id"]


def _seed_session_message(mm, role: str, content: str) -> int:
    mm.query(
        "session",
        "INSERT INTO chat_history (role, content) VALUES (?, ?)",
        (role, content),
    )
    rows = mm.query("session", "SELECT last_insert_rowid() AS id", ())
    row_id = int(rows[0]["id"])
    mm.query("session", "INSERT INTO memory_fts(rowid, content) VALUES (?, ?)", (row_id, content))
    return row_id


def _seed_session_message_at(mm, role: str, content: str, days_old: int) -> int:
    mm.query(
        "session",
        "INSERT INTO chat_history (role, content, timestamp) VALUES (?, ?, datetime('now', ?))",
        (role, content, f"-{days_old} days"),
    )
    rows = mm.query("session", "SELECT last_insert_rowid() AS id", ())
    row_id = int(rows[0]["id"])
    mm.query("session", "INSERT INTO memory_fts(rowid, content) VALUES (?, ?)", (row_id, content))
    return row_id


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

class TestCigGates:
    """Each test verifies a single rejection gate returns (None, None)."""

    def test_no_initiative_when_paused(self, mm):
        """Gate 0: paused=True must short-circuit immediately."""
        _seed_density(mm, 0.9)
        _seed_dormant_thread(mm)
        context = {"intention": "problème connexion réseau", "response": "timeout réseau"}
        result = cognitive_initiative_engine(mm, context, paused=True)
        assert result == (None, None)

    def test_no_initiative_when_density_below_threshold(self, mm):
        """Gate 1: density < 0.5 must return (None, None)."""
        _seed_density(mm, 0.2)
        _seed_dormant_thread(mm)
        context = {"intention": "problème connexion réseau", "response": "timeout réseau"}
        result = cognitive_initiative_engine(mm, context, paused=False)
        assert result == (None, None)

    def test_no_initiative_when_no_dormant_threads(self, mm):
        """Gate 2: no eligible threads → (None, None)."""
        _seed_density(mm, 0.8)
        # Insert an 'open' thread (not dormant)
        mm.query(
            "global",
            "INSERT INTO cognitive_threads (content, status, reactivation_score, importance_score) "
            "VALUES ('problème connexion réseau', 'open', 0.8, 0.8)",
            (),
        )
        context = {"intention": "problème connexion réseau", "response": "timeout réseau"}
        result = cognitive_initiative_engine(mm, context, paused=False)
        assert result == (None, None)

    def test_no_initiative_when_thread_not_anchored(self, mm):
        """Gate 3: zero keyword overlap → (None, None)."""
        _seed_density(mm, 0.8)
        _seed_dormant_thread(mm, content="machine learning neural network", summary="deep learning")
        context = {"intention": "faire la cuisine", "response": "recette carbonara pâtes"}
        result = cognitive_initiative_engine(mm, context, paused=False)
        assert result == (None, None)

    def test_no_initiative_when_reactivation_score_below_threshold(self, mm):
        """Gate 2: thread score < reactivation_threshold (0.65) → excluded."""
        _seed_density(mm, 0.8)
        _seed_dormant_thread(mm, reactivation_score=0.3)
        context = {"intention": "problème connexion réseau", "response": "timeout réseau"}
        result = cognitive_initiative_engine(mm, context, paused=False)
        assert result == (None, None)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestCigHappyPath:
    def test_initiative_generated_when_all_gates_pass(self, mm):
        """All gates pass → returns (str, str) with non-empty initiative text and log_id."""
        _seed_density(mm, 0.8)
        context = {
            "intention": "pourquoi la connexion réseau échoue",
            "response": "timeout détecté sur le serveur réseau",
        }
        with patch("arke.cognitive_initiative_gate._get_hybrid_context_candidates") as mock_candidates:
            mock_candidates.return_value = (
                [
                    {
                        "id": "chat:1",
                        "source_id": "chat:1",
                        "content": "problème connexion réseau timeout serveur",
                        "summary": "bug réseau timeout",
                        "reactivation_score": 0.92,
                        "importance_score": 0.92,
                        "effective_score": 0.92,
                        "final_score": 0.92,
                        "source": "session_sql",
                        "status": "session_candidate",
                    }
                ],
                {"semantic_applied": False, "fallback_reason": "test", "candidate_k": 1},
            )
            text, log_id = cognitive_initiative_engine(mm, context, paused=False)
        assert text is not None
        assert len(text) > 10
        assert log_id is not None
        # Verify log row exists with accepted = NULL
        rows = mm.query("global", "SELECT accepted FROM initiative_log WHERE id = ?", (log_id,))
        assert len(rows) == 1
        assert rows[0]["accepted"] is None  # NOT False — absence ≠ rejection

    def test_initiative_logs_selected_source_and_semantic_flags(self, mm):
        _seed_density(mm, 0.8)
        context = {
            "intention": "pourquoi la connexion réseau échoue",
            "response": "timeout détecté sur le serveur réseau",
        }
        with patch("arke.cognitive_initiative_gate._get_hybrid_context_candidates") as mock_candidates, \
             patch("arke.cognitive_initiative_gate._log_cig_proof") as mock_proof:
            mock_candidates.return_value = (
                [
                    {
                        "id": "chat:7",
                        "source_id": "chat:7",
                        "content": "problème connexion réseau timeout serveur",
                        "summary": "bug réseau timeout",
                        "reactivation_score": 0.88,
                        "importance_score": 0.88,
                        "effective_score": 0.88,
                        "final_score": 0.88,
                        "source": "session_fts",
                        "status": "session_candidate",
                    }
                ],
                {"semantic_applied": True, "fallback_reason": None, "candidate_k": 5},
            )
            text, log_id = cognitive_initiative_engine(mm, context, paused=False)

        assert text is not None
        assert log_id is not None
        mock_proof.assert_any_call(
            "initiative_generated",
            {
                "thread_id": "chat:7",
                "thread_status": "session_candidate",
                "thread_source": "session_fts",
                "selected_source_id": "chat:7",
                "semantic_applied": True,
                "fallback_reason": None,
                "effective_score": 0.88,
                "final_score": 0.88,
                "density": 0.8,
                "log_id": log_id,
            },
        )


class TestHybridContextCandidates:
    def test_hybrid_candidates_fallback_to_lexical_on_timeout(self, mm):
        _seed_session_message_at(mm, "user", "problème connexion réseau timeout serveur", days_old=8)
        _seed_session_message_at(mm, "assistant", "ça ressemble à un bug réseau timeout", days_old=8)

        with patch("arke.cognitive_initiative_gate.load_hybrid_search_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.rerank_memory_candidates_hybrid") as mock_rerank:
            mock_cfg.return_value = type(
                "Cfg",
                (),
                {
                    "candidate_k": 20,
                    "final_n": 5,
                    "semantic_timeout_ms": 50,
                    "enabled": True,
                    "lexical_weight": 0.7,
                    "semantic_weight": 0.3,
                    "query_cache_enabled": True,
                    "query_cache_ttl_sec": 3600,
                },
            )()

            def _blocked_rerank(**kwargs):
                import time
                time.sleep(0.2)
                return {"results": [], "semantic_applied": True, "fallback_reason": None}

            mock_rerank.side_effect = _blocked_rerank
            candidates, meta = _get_hybrid_context_candidates(
                mm,
                {"intention": "connexion réseau", "response": "timeout serveur"},
            )

        assert candidates
        assert meta["semantic_applied"] is False
        assert meta["fallback_reason"] == "outer_timeout"
        assert meta["candidate_k"] == 20
        assert float(candidates[0]["final_score"]) == pytest.approx(1.0)

    def test_hybrid_candidates_ignore_recent_messages_and_keep_old_links(self, mm):
        _seed_session_message_at(mm, "user", "problème connexion réseau timeout ancien", days_old=8)
        _seed_session_message_at(mm, "assistant", "analyse timeout réseau ancien", days_old=8)
        _seed_session_message_at(mm, "user", "problème connexion réseau timeout récent", days_old=2)
        _seed_session_message_at(mm, "assistant", "analyse timeout réseau récente", days_old=2)

        with patch("arke.cognitive_initiative_gate.load_hybrid_search_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.rerank_memory_candidates_hybrid") as mock_rerank, \
             patch("arke.cognitive_initiative_gate._get_config") as mock_cig_cfg:
            mock_cfg.return_value = type(
                "Cfg",
                (),
                {
                    "candidate_k": 20,
                    "final_n": 5,
                    "semantic_timeout_ms": 50,
                    "enabled": False,
                    "lexical_weight": 0.7,
                    "semantic_weight": 0.3,
                    "query_cache_enabled": True,
                    "query_cache_ttl_sec": 3600,
                },
            )()
            mock_cig_cfg.return_value = {**_DEFAULTS, "session_link_min_age_days": 7}
            mock_rerank.return_value = {
                "results": [
                    {
                        "id": 1,
                        "content": "problème connexion réseau timeout ancien",
                        "lexical_score": 0.8,
                        "source": "session_sql",
                    }
                ],
                "semantic_applied": False,
                "fallback_reason": "hybrid_disabled",
            }

            candidates, meta = _get_hybrid_context_candidates(
                mm,
                {"intention": "connexion réseau timeout", "response": "serveur timeout"},
            )

        assert candidates
        assert all("récent" not in str(candidate["content"]) for candidate in candidates)
        assert any("ancien" in str(candidate["content"]) for candidate in candidates)
        assert meta["session_link_min_age_days"] == 7


# ---------------------------------------------------------------------------
# initiative_log: NULL default (no bias)
# ---------------------------------------------------------------------------

class TestInitiativeLog:
    def test_log_initiative_creates_row_with_null_accepted(self, mm):
        """log_initiative must insert accepted=NULL, not 0."""
        log_id = log_initiative(mm, thread_id=42, density_snapshot=0.7, context_anchor="réseau bug")
        rows = mm.query("global", "SELECT * FROM initiative_log WHERE id = ?", (log_id,))
        assert len(rows) == 1
        assert rows[0]["accepted"] is None

    def test_mark_initiative_accepted_sets_to_one(self, mm):
        """mark_initiative_accepted must set accepted=1 (explicit positive signal)."""
        log_id = log_initiative(mm, thread_id=7, density_snapshot=0.6, context_anchor="test")
        mark_initiative_accepted(mm, log_id)
        rows = mm.query("global", "SELECT accepted FROM initiative_log WHERE id = ?", (log_id,))
        assert rows[0]["accepted"] == 1


# ---------------------------------------------------------------------------
# Auto-calibration
# ---------------------------------------------------------------------------

class TestAutoCalibrate:
    def _seed_initiative_log(self, mm, total: int, accepted_count: int) -> None:
        """Seed `total` rows in initiative_log with `accepted_count` accepted=1."""
        for i in range(total):
            row_id = str(uuid.uuid4())
            accepted = 1 if i < accepted_count else 0
            mm.query(
                "global",
                "INSERT INTO initiative_log (id, accepted) VALUES (?, ?)",
                (row_id, accepted),
            )

    def test_auto_calibrate_raises_threshold_on_low_acceptance(self, mm):
        """accepted_ratio=0.1 (3/30) → threshold rises by 0.05."""
        self._seed_initiative_log(mm, total=30, accepted_count=3)
        new_threshold = auto_calibrate_threshold(mm, current_threshold=0.5)
        assert new_threshold == pytest.approx(0.55, abs=0.01)

    def test_auto_calibrate_no_change_when_insufficient_samples(self, mm):
        """< 30 rows WHERE accepted IS NOT NULL → threshold unchanged."""
        self._seed_initiative_log(mm, total=5, accepted_count=1)
        new_threshold = auto_calibrate_threshold(mm, current_threshold=0.5)
        assert new_threshold == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_is_contextually_anchored_true(self):
        thread = {"content": "problème connexion réseau timeout", "summary": "bug réseau"}
        context = {"intention": "connexion réseau échoue", "response": "timeout réseau détecté"}
        assert is_contextually_anchored(thread, context) is True

    def test_is_contextually_anchored_false(self):
        thread = {"content": "machine learning neural", "summary": "deep learning"}
        context = {"intention": "faire cuisine", "response": "recette pâtes"}
        assert is_contextually_anchored(thread, context) is False

    def test_generate_soft_reactivation_uses_summary(self):
        thread = {"content": "long content here " * 20, "summary": "bug réseau"}
        text = generate_soft_reactivation(thread)
        assert "bug réseau" in text
        assert text.endswith("?")

    def test_generate_soft_reactivation_falls_back_to_content(self):
        thread = {"content": "problème connexion réseau", "summary": ""}
        text = generate_soft_reactivation(thread)
        assert "problème" in text


# ---------------------------------------------------------------------------
# Session 024: Semantic anchor (hybrid keyword/vector)
# ---------------------------------------------------------------------------

class TestSemanticAnchor:
    """Hybrid semantic/keyword anchor — Session 024."""

    # -- cosine similarity unit tests --

    def test_cosine_similarity_identical_vectors(self):
        assert _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector_returns_zero(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

    # -- hybrid anchor tests --

    def test_semantic_anchor_high_similarity_returns_true(self):
        """semantic_anchor=True + cosine = 1.0 (same vector returned) → True."""
        thread = {"content": "deep learning optimizer", "summary": "neural networks"}
        context = {"intention": "machine learning algorithms", "response": "neural training"}
        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.Embedder") as mock_emb_cls:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "semantic_anchor": True,
                "semantic_threshold": 0.65,
            }
            mock_emb_cls.return_value.embed.return_value = [1.0, 0.0, 0.0]  # identical → 1.0
            result = is_contextually_anchored(thread, context)
        assert result is True

    def test_semantic_anchor_low_similarity_returns_false(self):
        """semantic_anchor=True + orthogonal vectors → cosine = 0.0 < 0.65 → False."""
        thread = {"content": "cuisine italienne pâtes", "summary": "recette carbonara"}
        context = {"intention": "physique quantique", "response": "mécanique ondulatoire"}
        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.Embedder") as mock_emb_cls:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "semantic_anchor": True,
                "semantic_threshold": 0.65,
            }
            mock_emb_cls.return_value.embed.side_effect = [
                [1.0, 0.0, 0.0],  # thread vector
                [0.0, 1.0, 0.0],  # context vector → cosine = 0.0
            ]
            result = is_contextually_anchored(thread, context)
        assert result is False

    def test_semantic_anchor_falls_back_to_keyword_on_vector_disabled(self):
        """VectorDisabledError → keyword fallback; overlap ≥ 2 → True."""
        thread = {"content": "problème connexion réseau timeout", "summary": "bug réseau"}
        context = {"intention": "connexion réseau échoue", "response": "timeout réseau"}
        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.Embedder") as mock_emb_cls:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "semantic_anchor": True,
                "semantic_threshold": 0.65,
            }
            mock_emb_cls.return_value.embed.side_effect = VectorDisabledError("disabled")
            result = is_contextually_anchored(thread, context)
        # keyword fallback: "connexion", "réseau", "timeout" → overlap ≥ 2 → True
        assert result is True

    def test_semantic_anchor_disabled_never_calls_embedder(self):
        """semantic_anchor=False → Embedder constructor never called; keyword path only."""
        thread = {"content": "problème connexion réseau", "summary": "bug réseau"}
        context = {"intention": "connexion réseau échoue", "response": "timeout réseau"}
        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg, \
             patch("arke.cognitive_initiative_gate.Embedder") as mock_emb_cls:
            mock_cfg.return_value = {**_DEFAULTS, "semantic_anchor": False}
            result = is_contextually_anchored(thread, context)
        mock_emb_cls.assert_not_called()
        assert result is True


# ---------------------------------------------------------------------------
# Session 026: Positive signal detection + acceptance feedback loop
# ---------------------------------------------------------------------------

class TestPositiveSignalDetection:
    """detect_positive_signal + mark_initiative_accepted feedback loop."""

    def test_overlap_two_words_returns_true(self):
        """≥ 2 words (len ≥ 4) shared between raw and initiative text → True."""
        initiative = "On avait exploré une piste sur « bug réseau timeout » récemment. Tu veux reprendre ?"
        raw = "oui le problème réseau timeout est toujours là"
        assert detect_positive_signal(raw, initiative) is True

    def test_overlap_one_word_returns_false(self):
        """Only 1 shared word (len ≥ 4) → False."""
        initiative = "On avait exploré une piste sur « machine learning » récemment. Tu veux reprendre ?"
        raw = "parle-moi de machine"
        assert detect_positive_signal(raw, initiative) is False

    def test_empty_raw_returns_false(self):
        """Empty raw string → False (no signal)."""
        assert detect_positive_signal("", "une piste sur réseau timeout connexion") is False

    def test_empty_initiative_returns_false(self):
        """Empty initiative text → False (nothing to match against)."""
        assert detect_positive_signal("connexion réseau timeout", "") is False

    def test_mark_accepted_called_when_signal_detected(self, mm):
        """Full loop: log initiative → detect overlap → accepted = 1."""
        log_id = log_initiative(mm, thread_id=5, density_snapshot=0.7, context_anchor="réseau")
        # Verify NULL before detection
        rows = mm.query("global", "SELECT accepted FROM initiative_log WHERE id = ?", (log_id,))
        assert rows[0]["accepted"] is None

        # Simulate user reply with positive signal
        initiative_text = "On avait exploré une piste sur « bug réseau timeout » récemment. Tu veux reprendre ?"
        raw = "oui le bug réseau timeout m'intéresse toujours"
        if detect_positive_signal(raw, initiative_text):
            mark_initiative_accepted(mm, log_id)

        rows = mm.query("global", "SELECT accepted FROM initiative_log WHERE id = ?", (log_id,))
        assert rows[0]["accepted"] == 1


# ---------------------------------------------------------------------------
# Session 027: Divergence Fertile (Serendipity principle)
# ---------------------------------------------------------------------------

class TestDivergenceFertile:
    """get_divergent_thread, divergent generate_soft_reactivation, divergent engine path."""

    def test_generate_soft_reactivation_divergent_prefix(self):
        """divergent=True → text contains '⚡' and ends with '?'."""
        thread = {"content": "architecture microservices", "summary": "design services"}
        text = generate_soft_reactivation(thread, divergent=True)
        assert "⚡" in text
        assert text.endswith("?")

    def test_generate_soft_reactivation_divergent_different_from_normal(self):
        """Divergent and normal templates are textually distinct."""
        thread = {"content": "architecture microservices", "summary": "design services"}
        normal = generate_soft_reactivation(thread, divergent=False)
        divergent_text = generate_soft_reactivation(thread, divergent=True)
        assert normal != divergent_text

    def test_generate_soft_reactivation_default_is_not_divergent(self):
        """Default call (no divergent arg) uses normal contextual template."""
        thread = {"content": "test content", "summary": "test summary"}
        text = generate_soft_reactivation(thread)
        assert "⚡" not in text

    def test_get_divergent_thread_returns_random_eligible(self, mm):
        """get_divergent_thread returns one of the seeded dormant threads."""
        _seed_dormant_thread(mm, reactivation_score=0.8, content="thread A", summary="A")
        _seed_dormant_thread(mm, reactivation_score=0.7, content="thread B", summary="B")
        result = get_divergent_thread(mm, max_age_days=14)
        assert result is not None
        assert result["content"] in ("thread A", "thread B")

    def test_get_divergent_thread_returns_none_when_no_threads(self, mm):
        """No dormant threads → get_divergent_thread returns None."""
        result = get_divergent_thread(mm, max_age_days=14)
        assert result is None

    def test_divergent_path_logs_divergent_type(self, mm):
        """When divergent path fires (rate=1.0), initiative_log.type = 'divergent_reactivation'."""
        _seed_density(mm, 0.8)
        _seed_dormant_thread(mm, content="architecture microservices", summary="design services")
        context = {"intention": "faire la cuisine", "response": "recette carbonara pâtes"}

        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "divergence_rate": 1.0,
                "threshold_density": 0.5,
                "reactivation_threshold": 0.01,
            }
            text, log_id = cognitive_initiative_engine(mm, context, paused=False)

        assert text is not None
        assert "⚡" in text
        rows = mm.query("global", "SELECT type FROM initiative_log WHERE id = ?", (log_id,))
        assert rows[0]["type"] == "divergent_reactivation"

    def test_divergent_rate_zero_never_diverges(self, mm):
        """divergence_rate=0.0 → always takes contextual path (Gate 3 checked)."""
        _seed_density(mm, 0.8)
        _seed_dormant_thread(mm, content="machine learning neural", summary="deep learning")
        context = {"intention": "faire la cuisine", "response": "recette pâtes carbonara"}

        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "divergence_rate": 0.0,
                "threshold_density": 0.5,
                "reactivation_threshold": 0.01,
            }
            result = cognitive_initiative_engine(mm, context, paused=False)

        assert result == (None, None)


# ---------------------------------------------------------------------------
# Session 028: Oubli Progressif (exponential decay)
# ---------------------------------------------------------------------------

def _seed_old_dormant_thread(
    mm,
    reactivation_score: float = 0.8,
    days_old: int = 30,
    content: str = "old thread",
    summary: str = "old summary",
) -> int:
    """Seed a dormant thread with created_at backdated by days_old."""
    mm.query(
        "global",
        "INSERT INTO cognitive_threads "
        "(content, summary, status, reactivation_score, importance_score, created_at) "
        "VALUES (?, ?, 'dormant', ?, ?, datetime('now', ?))",
        (content, summary, reactivation_score, reactivation_score, f"-{days_old} days"),
    )
    rows = mm.query("global", "SELECT last_insert_rowid() AS id", ())
    return rows[0]["id"]


class TestOubliProgressif:
    """_apply_decay and in-memory score decay in get_dormant_threads (Session 028)."""

    def test_apply_decay_zero_days_unchanged(self):
        """0 days dormant → score is unchanged."""
        assert _apply_decay(0.8, 0) == pytest.approx(0.8)

    def test_apply_decay_reduces_score_with_age(self):
        """Score decreases with days dormant (default rate=0.95)."""
        result = _apply_decay(0.8, 10, rate=0.95)
        assert result < 0.8
        assert result == pytest.approx(0.8 * (0.95 ** 10))

    def test_apply_decay_floor_at_005(self):
        """Score never falls below 0.05 even after extreme dormancy."""
        result = _apply_decay(0.8, 200, rate=0.95)
        assert result == pytest.approx(0.05)

    def test_apply_decay_rate_one_no_decay(self):
        """rate=1.0 → score unchanged regardless of days."""
        assert _apply_decay(0.7, 30, rate=1.0) == pytest.approx(0.7)

    def test_decay_applied_in_get_dormant_threads(self, mm):
        """Old thread has lower decayed score than a fresh thread with same original score."""
        _seed_dormant_thread(mm, reactivation_score=0.8, content="fresh thread", summary="fresh")
        _seed_old_dormant_thread(mm, reactivation_score=0.8, days_old=30,
                                  content="old thread", summary="old")
        threads = get_dormant_threads(mm, max_age_days=60)
        by_content = {t["content"]: t["reactivation_score"] for t in threads}
        assert "fresh thread" in by_content and "old thread" in by_content
        assert by_content["fresh thread"] > by_content["old thread"]

    def test_decay_below_threshold_filtered_by_engine(self, mm):
        """Thread decayed below reactivation_threshold is not selected by engine."""
        _seed_density(mm, 0.8)
        # 0.7 * (0.95 ** 15) ≈ 0.324 < 0.65 → rejected at Gate 2
        _seed_old_dormant_thread(mm, reactivation_score=0.7, days_old=15,
                                  content="neural network learning",
                                  summary="deep learning neural")
        context = {"intention": "neural network", "response": "deep learning neural"}

        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "decay_rate": 0.95,
                "divergence_rate": 0.0,
                "threshold_density": 0.5,
                "reactivation_threshold": 0.65,
            }
            result = cognitive_initiative_engine(mm, context, paused=False)

        assert result == (None, None)


# ---------------------------------------------------------------------------
# TestComputeUtilityScore (Phase 2)
# ---------------------------------------------------------------------------


class TestComputeUtilityScore:
    """Verify composite utility score formula and weight application."""

    _THREAD = {"reactivation_score": 0.8, "importance_score": 0.6}
    _W = {"reactivation": 0.4, "importance": 0.3, "density": 0.2, "relevance": 0.1}

    def test_score_uses_all_components(self):
        """U = 0.4*r + 0.3*i + 0.2*d + 0.1*v"""
        score = compute_utility_score(
            self._THREAD, density=0.5, relevance_score=0.3, weights=self._W
        )
        expected = 0.4 * 0.8 + 0.3 * 0.6 + 0.2 * 0.5 + 0.1 * 0.3
        assert score == pytest.approx(expected, abs=1e-9)

    def test_default_relevance_is_zero(self):
        """When relevance_score omitted, it defaults to 0.0."""
        score_explicit = compute_utility_score(
            self._THREAD, density=0.5, relevance_score=0.0, weights=self._W
        )
        score_default = compute_utility_score(self._THREAD, density=0.5, weights=self._W)
        assert score_explicit == pytest.approx(score_default)

    def test_higher_reactivation_wins(self):
        """Thread with higher reactivation_score must score higher (all else equal)."""
        low = {"reactivation_score": 0.3, "importance_score": 0.5}
        high = {"reactivation_score": 0.9, "importance_score": 0.5}
        assert compute_utility_score(high, density=0.5, weights=self._W) > \
               compute_utility_score(low, density=0.5, weights=self._W)

    def test_weight_override(self):
        """Custom weights must override defaults."""
        importance_only = {"reactivation": 0.0, "importance": 1.0, "density": 0.0, "relevance": 0.0}
        score = compute_utility_score(self._THREAD, density=0.9, weights=importance_only)
        assert score == pytest.approx(0.6)  # 1.0 * importance_score

    def test_zero_scores_produce_zero(self):
        thread = {"reactivation_score": 0.0, "importance_score": 0.0}
        assert compute_utility_score(thread, density=0.0, weights=self._W) == pytest.approx(0.0)

    def test_engine_selects_highest_ranked_hybrid_candidate(self, mm):
        """Engine must pick the highest final_score candidate from the hybrid retrieval path."""
        _seed_density(mm, 0.9)
        with patch("arke.cognitive_initiative_gate._get_config") as mock_cfg:
            mock_cfg.return_value = {
                **_DEFAULTS,
                "divergence_rate": 0.0,
                "threshold_density": 0.5,
                "reactivation_threshold": 0.65,
                "utility_weights": {"reactivation": 0.4, "importance": 0.3,
                                    "density": 0.2, "relevance": 0.1},
            }
            with patch("arke.cognitive_initiative_gate._get_hybrid_context_candidates") as mock_candidates:
                mock_candidates.return_value = (
                    [
                        {
                            "id": "chat:1",
                            "source_id": "chat:1",
                            "content": "réseau connexion timeout problème candidate A",
                            "summary": "candidate A",
                            "reactivation_score": 0.71,
                            "importance_score": 0.71,
                            "effective_score": 0.71,
                            "final_score": 0.71,
                            "source": "session_sql",
                            "status": "session_candidate",
                        },
                        {
                            "id": "chat:2",
                            "source_id": "chat:2",
                            "content": "réseau connexion timeout problème candidate B",
                            "summary": "candidate B",
                            "reactivation_score": 0.93,
                            "importance_score": 0.93,
                            "effective_score": 0.93,
                            "final_score": 0.93,
                            "source": "session_sql",
                            "status": "session_candidate",
                        },
                    ],
                    {"semantic_applied": False, "fallback_reason": "test", "candidate_k": 2},
                )
                text, log_id = cognitive_initiative_engine(
                    mm,
                    {"intention": "réseau connexion timeout", "response": "timeout problème"},
                    paused=False,
                )
        assert text is not None
        rows = mm.query("global", "SELECT thread_id FROM initiative_log WHERE id = ?", (log_id,))
        assert rows[0]["thread_id"] == "chat:2"
