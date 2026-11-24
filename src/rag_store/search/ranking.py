"""Reciprocal rank fusion.

This is the documented hybrid ranking method. PostgreSQL ``ts_rank_cd`` is reported
as a lexical rank and is not described as BM25.
"""

from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + position)
    return scores


def ordered(scores: dict[str, float]) -> list[str]:
    return sorted(scores, key=lambda item: scores[item], reverse=True)
