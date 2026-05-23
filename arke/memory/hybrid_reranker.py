"""Hybrid reranker (S054) — pure scoring module.

This module is intentionally side-effect free:
- no timeout handling
- no fallback handling
- no feature-flag logic

It only normalizes lexical/semantic score spaces and computes the final score.
"""

from __future__ import annotations

from typing import Any


def _minmax(values: list[float]) -> list[float]:
    """Return min-max normalized values in [0, 1].

    If all values are equal, return 1.0 for all items to preserve ordering
    from prior stages.
    """
    if not values:
        return []
    v_min = min(values)
    v_max = max(values)
    if v_max == v_min:
        return [1.0] * len(values)
    span = v_max - v_min
    return [(v - v_min) / span for v in values]


def _normalize_semantic(value: float) -> float:
    """Normalize cosine from [-1, 1] into [0, 1].

    When cosine is already in [0, 1], this remains monotonic.
    """
    mapped = (value + 1.0) / 2.0
    if mapped < 0.0:
        return 0.0
    if mapped > 1.0:
        return 1.0
    return mapped


def rerank_candidates(
    candidates: list[dict[str, Any]],
    *,
    lexical_weight: float = 0.7,
    semantic_weight: float = 0.3,
    lexical_key: str = "lexical_score",
    semantic_key: str = "semantic_score",
) -> list[dict[str, Any]]:
    """Return reranked candidates with normalized component scores.

    Args:
        candidates: Candidate dicts containing at least lexical/semantic raw scores.
        lexical_weight: Weight for normalized lexical score.
        semantic_weight: Weight for normalized semantic score.
        lexical_key: Input key name for raw lexical score.
        semantic_key: Input key name for raw semantic score.

    Returns:
        New list sorted by ``final_score`` (desc).
    """
    if not candidates:
        return []

    raw_lexical = [float(c.get(lexical_key, 0.0) or 0.0) for c in candidates]
    lexical_norm = _minmax(raw_lexical)

    out: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        sem_raw = float(candidate.get(semantic_key, 0.0) or 0.0)
        sem_norm = _normalize_semantic(sem_raw)
        lex_norm = lexical_norm[idx]
        final_score = lexical_weight * lex_norm + semantic_weight * sem_norm

        enriched = dict(candidate)
        enriched["lexical_score_norm"] = lex_norm
        enriched["semantic_score_norm"] = sem_norm
        enriched["final_score"] = final_score
        out.append(enriched)

    out.sort(key=lambda c: c.get("final_score", 0.0), reverse=True)
    return out
