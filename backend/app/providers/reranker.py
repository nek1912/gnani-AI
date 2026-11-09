"""Jina reranker adapter — Phase 4.

Calls Jina Reranker v2 API to re-score candidate chunks.
Falls back to identity (no reranking) on any failure.
"""
from __future__ import annotations

import httpx

from app.config import REQUEST_TIMEOUT_S, get_settings
from app.key_rotator import KeyRotator


class JinaReranker:
    """Thin wrapper around Jina Reranker v2 API."""

    def __init__(self, timeout_s: float | None = None) -> None:
        settings = get_settings()
        self._model = settings.reranker_model
        self._endpoint = "https://api.jina.ai/v1/rerank"
        self._timeout_s = timeout_s if timeout_s is not None else settings.jina_reranker_timeout_s
        keys = settings.jina_keys
        self._rotator = KeyRotator(keys, name="jina-reranker") if keys else None

    @property
    def _key(self) -> str:
        if self._rotator:
            return self._rotator.current_key
        return ""

    def rerank(self, query: str, documents: list[dict],
               top_n: int | None = None) -> list[dict]:
        """Re-score documents by relevance to query.

        Args:
            query: The user query string.
            documents: List of dicts with at least 'content' or 'text' key.
            top_n: If set, return only top_n results.

        Returns:
            List of dicts sorted by reranker score (descending).
            Each dict gains a 'reranker_score' key.
            On failure, returns documents unchanged (identity fallback).
        """
        if not documents:
            return []

        # Build document list for Jina API
        docs_for_jina = []
        for i, doc in enumerate(documents):
            text = doc.get("content") or doc.get("text") or ""
            docs_for_jina.append({"text": text, "index": i})

        try:
            def _rerank_with_key(key: str) -> list[dict]:
                with httpx.Client(timeout=self._timeout_s) as client:
                    resp = client.post(
                        self._endpoint,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "query": query,
                            "documents": [d["text"] for d in docs_for_jina],
                            "top_n": top_n or len(documents),
                            "return_documents": False,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json().get("results", [])

            if self._rotator:
                results = self._rotator.try_keys(_rerank_with_key)
            else:
                results = _rerank_with_key(self._key)

            # Map reranker results back to original documents
            reranked = []
            for r in results:
                idx = r.get("index", 0)
                score = r.get("relevance_score", 0.0)
                doc = dict(documents[idx])
                doc["reranker_score"] = score
                reranked.append(doc)

            return reranked

        except Exception:
            # Identity fallback: return original docs with original scores
            return documents
