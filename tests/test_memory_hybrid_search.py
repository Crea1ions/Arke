from __future__ import annotations

from arke.memory.hybrid_reranker import rerank_candidates
from arke.memory.retrieval_orchestrator import HybridSearchConfig, rerank_memory_candidates_hybrid
from arke.router import plan


def test_reranker_normalizes_and_computes_final_score():
    candidates = [
        {"id": 1, "lexical_score": 10.0, "semantic_score": -1.0},
        {"id": 2, "lexical_score": 5.0, "semantic_score": 1.0},
    ]

    ranked = rerank_candidates(candidates, lexical_weight=0.7, semantic_weight=0.3)

    assert len(ranked) == 2
    assert all("lexical_score_norm" in c for c in ranked)
    assert all("semantic_score_norm" in c for c in ranked)
    assert all("final_score" in c for c in ranked)
    # Candidate #1 keeps higher final score due to stronger lexical component.
    assert ranked[0]["id"] == 1


def test_hybrid_search_falls_back_to_lexical_when_disabled():
    candidates = [
        {
            "id": 1,
            "lexical_score": 0.9,
            "candidate_text": "search query alpha\nalpha details",
        },
        {
            "id": 2,
            "lexical_score": 0.8,
            "candidate_text": "search query beta\nbeta details",
        },
    ]
    cfg = HybridSearchConfig(enabled=False, candidate_k=20, final_n=5)

    out = rerank_memory_candidates_hybrid(
        search_query="query",
        lexical_candidates=candidates,
        limit=5,
        config=cfg,
    )

    assert out["semantic_applied"] is False
    assert out["fallback_reason"] == "hybrid_disabled"
    assert len(out["results"]) == 2


def test_hybrid_search_falls_back_when_semantic_fails(monkeypatch):
    class _BrokenEmbedder:
        enabled = True
        model = "test-model"

        def embed(self, text):  # noqa: ARG002
            raise RuntimeError("embed failure")

    monkeypatch.setattr("arke.vector.embedder.Embedder", _BrokenEmbedder)

    candidates = [
        {
            "id": 1,
            "lexical_score": 0.9,
            "candidate_text": "query one\ndetails one",
        }
    ]
    cfg = HybridSearchConfig(enabled=True, semantic_timeout_ms=100)

    out = rerank_memory_candidates_hybrid(
        search_query="query",
        lexical_candidates=candidates,
        limit=5,
        config=cfg,
    )

    assert out["semantic_applied"] is False
    assert out["fallback_reason"] == "RuntimeError"
    assert len(out["results"]) == 1


def test_router_builds_memory_search_step_from_agent_decision():
    task = plan(
        "find similar learnings about sqlite",
        {
            "agent_decision": {
                "tool": "memory_search",
                "args": {"query": "sqlite", "limit": 3, "db": "global"},
            }
        },
    )
    assert len(task.steps) == 1
    assert task.steps[0].tool == "memory_search"
    assert task.steps[0].arguments["query"] == "sqlite"
    assert task.steps[0].arguments["limit"] == 3
