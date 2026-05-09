"""Tests for P3.2 — VectorIndex, Embedder, semantic CLI, benchmark."""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from arke.vector.embedder import DEFAULT_DIMS, DEFAULT_MODEL, Embedder, VectorDisabledError
from arke.vector.index import VectorIndex, load_vector_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIMS = 4  # small dimension for all tests (speed + simplicity)


def _unit_vec(i: int, n: int = DIMS) -> list[float]:
    """Return a unit vector with 1.0 at position i, 0.0 elsewhere."""
    v = [0.0] * n
    v[i % n] = 1.0
    return v


def _rand_vec(seed: int, n: int = DIMS) -> list[float]:
    """Deterministic pseudo-random vector (normalised)."""
    import random

    rng = random.Random(seed)
    v = [rng.gauss(0, 1) for _ in range(n)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# ---------------------------------------------------------------------------
# TestVectorIndexLifecycle
# ---------------------------------------------------------------------------


class TestVectorIndexLifecycle:
    def test_index_creates_tables(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS, enabled=True)
        assert idx.count() == 0

    def test_index_inserts_document(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        doc_id = idx.index("hello world", _unit_vec(0))
        assert isinstance(doc_id, int)
        assert doc_id > 0
        assert idx.count() == 1

    def test_index_multiple_documents(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        for i in range(5):
            idx.index(f"doc {i}", _unit_vec(i))
        assert idx.count() == 5

    def test_search_returns_nearest(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        idx.index("doc A", [1.0, 0.0, 0.0, 0.0])
        idx.index("doc B", [0.0, 1.0, 0.0, 0.0])
        idx.index("doc C", [0.0, 0.0, 1.0, 0.0])

        results = idx.search([1.0, 0.0, 0.0, 0.0], k=1)
        assert len(results) == 1
        assert results[0]["content"] == "doc A"

    def test_search_result_keys(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        idx.index("hello", _unit_vec(0))
        r = idx.search(_unit_vec(0), k=1)
        assert set(r[0].keys()) >= {"doc_id", "content", "distance"}

    def test_search_distance_same_vector_is_zero(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        v = [1.0, 0.0, 0.0, 0.0]
        idx.index("exact", v)
        r = idx.search(v, k=1)
        assert r[0]["distance"] == pytest.approx(0.0, abs=1e-5)

    def test_search_respects_k(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS)
        for i in range(10):
            idx.index(f"doc {i}", _rand_vec(i))
        results = idx.search(_rand_vec(99), k=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# TestVectorIndexDisabled
# ---------------------------------------------------------------------------


class TestVectorIndexDisabled:
    def test_disabled_index_returns_minus_one(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS, enabled=False)
        result = idx.index("content", _unit_vec(0))
        assert result == -1

    def test_disabled_search_returns_empty(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS, enabled=False)
        assert idx.search(_unit_vec(0)) == []

    def test_disabled_count_returns_zero(self, tmp_path):
        idx = VectorIndex(db_path=tmp_path / "g.db", dimensions=DIMS, enabled=False)
        assert idx.count() == 0


# ---------------------------------------------------------------------------
# TestEmbedder
# ---------------------------------------------------------------------------


class TestEmbedder:
    def test_disabled_raises_vector_disabled_error(self):
        e = Embedder(enabled=False)
        with pytest.raises(VectorDisabledError):
            e.embed("test")

    def test_disabled_enabled_property_false(self):
        e = Embedder(enabled=False)
        assert e.enabled is False

    def test_enabled_embed_calls_litellm(self):
        fake_vec = [0.1, 0.2, 0.3, 0.4]
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": fake_vec}]

        with patch("litellm.embedding", return_value=mock_resp) as mock_emb:
            e = Embedder(model="test-model", dimensions=4, enabled=True)
            result = e.embed("hello")

        mock_emb.assert_called_once_with(model="test-model", input=["hello"])
        assert result == fake_vec

    def test_default_model_and_dims(self):
        e = Embedder(enabled=False)
        # disabled, so we can read config without calling API
        assert e.dimensions == DEFAULT_DIMS
        assert e.model == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# TestBenchmark — 1 000 documents, search < 50 ms
# ---------------------------------------------------------------------------


class TestBenchmark:
    N_DOCS = 1_000
    DIMS_BENCH = 32  # realistic dims for fast benchmark in CI

    def test_search_1000_docs_under_50ms(self, tmp_path):
        """P3.2 must have: kNN on 1 000 documents < 50 ms."""
        idx = VectorIndex(
            db_path=tmp_path / "bench.db",
            dimensions=self.DIMS_BENCH,
            enabled=True,
        )

        # Insert 1 000 random documents
        for i in range(self.N_DOCS):
            idx.index(f"document #{i}", _rand_vec(i, self.DIMS_BENCH))

        assert idx.count() == self.N_DOCS

        query = _rand_vec(999999, self.DIMS_BENCH)
        results, elapsed_ms = idx.search_timed(query, k=5)

        assert len(results) <= 5
        assert elapsed_ms < 50.0, (
            f"kNN search on {self.N_DOCS} docs took {elapsed_ms:.1f} ms — "
            f"exceeds 50 ms threshold"
        )


# ---------------------------------------------------------------------------
# TestLoadVectorConfig
# ---------------------------------------------------------------------------


class TestLoadVectorConfig:
    def test_returns_dict(self, tmp_path, monkeypatch):
        """load_vector_config() returns a dict (possibly empty)."""
        cfg = load_vector_config()
        assert isinstance(cfg, dict)

    def test_missing_config_returns_empty(self, tmp_path, monkeypatch):
        """When arke.toml does not exist, returns {}."""
        import arke.vector.index as idx_mod

        real_base = idx_mod._BASE_DIR
        monkeypatch.setattr(idx_mod, "_BASE_DIR", tmp_path)
        cfg = idx_mod.load_vector_config()
        assert cfg == {}
        monkeypatch.setattr(idx_mod, "_BASE_DIR", real_base)


# ---------------------------------------------------------------------------
# TestSemanticsEndToEnd — VectorIndex round-trip with mock embedder
# ---------------------------------------------------------------------------


class TestSemanticsEndToEnd:
    def test_index_and_retrieve_by_meaning(self, tmp_path):
        """Index 3 docs with distinct directions, query the nearest one."""
        idx = VectorIndex(db_path=tmp_path / "e2e.db", dimensions=DIMS, enabled=True)

        docs = [
            ("nginx log analysis", [1.0, 0.0, 0.0, 0.0]),
            ("github pull request", [0.0, 1.0, 0.0, 0.0]),
            ("résumer un document PDF", [0.0, 0.0, 1.0, 0.0]),
        ]
        for content, vec in docs:
            idx.index(content, vec)

        # Query close to "nginx log analysis" direction
        results = idx.search([0.99, 0.14, 0.0, 0.0], k=1)
        assert results[0]["content"] == "nginx log analysis"

    def test_search_returns_ordered_by_distance(self, tmp_path):
        """Results must be sorted nearest-first."""
        idx = VectorIndex(db_path=tmp_path / "e2e.db", dimensions=DIMS, enabled=True)
        idx.index("near", [1.0, 0.0, 0.0, 0.0])
        idx.index("far", [0.0, 0.0, 0.0, 1.0])

        results = idx.search([1.0, 0.0, 0.0, 0.0], k=5)
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
