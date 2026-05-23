"""S054 retrieval orchestrator — control flow for hybrid memory search.

Responsibilities:
- feature flag
- timeout budget
- deterministic lexical fallback
- stage orchestration (lexical -> semantic -> rerank)

Non-responsibilities:
- score fusion math (delegated to ``hybrid_reranker``)
"""

from __future__ import annotations

import hashlib
import tomllib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from arke.memory.hybrid_reranker import rerank_candidates

_BASE_DIR = Path(__file__).parent.parent.parent
_CONFIG_PATH = _BASE_DIR / "config" / "arke.toml"

# Local-first in-process query embedding cache (S054 V1).
# key -> (expiry_monotonic, embedding)
_QUERY_EMBEDDING_CACHE: dict[str, tuple[float, list[float]]] = {}


@dataclass(frozen=True)
class HybridSearchConfig:
    enabled: bool = True
    candidate_k: int = 20
    final_n: int = 5
    semantic_timeout_ms: int = 800
    lexical_weight: float = 0.7
    semantic_weight: float = 0.3
    query_cache_enabled: bool = True
    query_cache_ttl_sec: int = 3600


def load_hybrid_search_config() -> HybridSearchConfig:
    """Load S054 config from ``[memory_search_hybrid]`` section."""
    try:
        with open(_CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)
        raw = data.get("memory_search_hybrid", {})
    except FileNotFoundError:
        raw = {}

    return HybridSearchConfig(
        enabled=bool(raw.get("enabled", True)),
        candidate_k=int(raw.get("candidate_k", 20)),
        final_n=int(raw.get("final_n", 5)),
        semantic_timeout_ms=int(raw.get("semantic_timeout_ms", 800)),
        lexical_weight=float(raw.get("lexical_weight", 0.7)),
        semantic_weight=float(raw.get("semantic_weight", 0.3)),
        query_cache_enabled=bool(raw.get("query_cache_enabled", True)),
        query_cache_ttl_sec=int(raw.get("query_cache_ttl_sec", 3600)),
    )


def _run_with_timeout(func, timeout_s: float):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        return future.result(timeout=timeout_s)


def _query_cache_key(query: str, model_version: str) -> str:
    payload = f"{model_version}\x00{query}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _query_cache_get(key: str) -> list[float] | None:
    now = monotonic()
    val = _QUERY_EMBEDDING_CACHE.get(key)
    if val is None:
        return None
    expiry, embedding = val
    if expiry <= now:
        _QUERY_EMBEDDING_CACHE.pop(key, None)
        return None
    return embedding


def _query_cache_put(key: str, embedding: list[float], ttl_sec: int) -> None:
    _QUERY_EMBEDDING_CACHE[key] = (monotonic() + max(ttl_sec, 1), embedding)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def rerank_memory_candidates_hybrid(
    *,
    search_query: str,
    lexical_candidates: list[dict[str, Any]],
    limit: int = 5,
    config: HybridSearchConfig | None = None,
) -> dict[str, Any]:
    """Run S054 hybrid rerank on lexical candidates with lexical fallback.

    This function is source-agnostic by design: lexical retrieval happens
    upstream in the existing SQL/FTS flow. S054 only reranks top-K candidates.
    """
    cfg = config or load_hybrid_search_config()
    final_n = max(1, min(limit, cfg.final_n))

    lexical = lexical_candidates[: max(cfg.candidate_k, 1)]
    if not lexical:
        return {"results": [], "semantic_applied": False, "fallback_reason": "no_lexical_results"}

    if not cfg.enabled:
        return {
            "results": lexical[:final_n],
            "semantic_applied": False,
            "fallback_reason": "hybrid_disabled",
        }

    try:
        from arke.vector.embedder import Embedder, VectorDisabledError

        timeout_s = max(cfg.semantic_timeout_ms, 1) / 1000.0
        start = monotonic()
        embedder = Embedder()
        if not embedder.enabled:
            raise VectorDisabledError("vector disabled")

        model_version = embedder.model
        query_cache_key = _query_cache_key(search_query, model_version)
        query_embedding = None
        if cfg.query_cache_enabled:
            query_embedding = _query_cache_get(query_cache_key)

        if query_embedding is None:
            query_embedding = _run_with_timeout(lambda: embedder.embed(search_query), timeout_s)
            if cfg.query_cache_enabled:
                _query_cache_put(query_cache_key, query_embedding, cfg.query_cache_ttl_sec)

        candidates_with_sem: list[dict[str, Any]] = []
        for cand in lexical:
            remaining = timeout_s - (monotonic() - start)
            if remaining <= 0:
                raise FuturesTimeoutError()

            candidate_text = str(cand.get("candidate_text", "")).strip()
            if not candidate_text:
                # Keep candidate but neutral semantic score if no text payload.
                cand_copy = dict(cand)
                cand_copy["semantic_score"] = 0.0
                candidates_with_sem.append(cand_copy)
                continue

            cand_embedding = _run_with_timeout(lambda text=candidate_text: embedder.embed(text), remaining)
            cand_copy = dict(cand)
            cand_copy["semantic_score"] = _cosine_similarity(query_embedding, cand_embedding)
            candidates_with_sem.append(cand_copy)

        reranked = rerank_candidates(
            candidates_with_sem,
            lexical_weight=cfg.lexical_weight,
            semantic_weight=cfg.semantic_weight,
            lexical_key="lexical_score",
            semantic_key="semantic_score",
        )
        return {"results": reranked[:final_n], "semantic_applied": True, "fallback_reason": None}
    except Exception as exc:  # noqa: BLE001
        return {
            "results": lexical[:final_n],
            "semantic_applied": False,
            "fallback_reason": type(exc).__name__,
        }


def search_agent_learnings_hybrid(
    *,
    search_query: str,
    lexical_candidates: list[dict[str, Any]],
    limit: int = 5,
    config: HybridSearchConfig | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias kept during transition."""
    return rerank_memory_candidates_hybrid(
        search_query=search_query,
        lexical_candidates=lexical_candidates,
        limit=limit,
        config=config,
    )
