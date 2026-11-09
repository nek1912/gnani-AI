"""
BM25 ranking for Tavily web results.

Tavily discovers the web pages.

BM25 performs lexical keyword ranking over the discovered
web content.

This is NOT the application's final semantic retrieval system.
It is the web-discovery ranking stage.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:

    return re.findall(
        r"\b\w+\b",
        str(text or "").lower(),
    )


class WebBM25Ranker:

    def rank_candidates(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 12,
    ) -> list[dict]:
        return self.rank(query=query, results=candidates, top_k=top_k)

    def rank(
        self,
        query: str,
        results: list[dict],
        top_k: int = 12,
    ) -> list[dict]:

        if not query.strip():
            return []

        if not results:
            return []

        corpus = []

        for result in results:

            searchable_text = " ".join(
                [
                    str(
                        result.get(
                            "title",
                            "",
                        )
                    ),
                    str(
                        result.get(
                            "text",
                            "",
                        )
                    ),
                    str(
                        result.get(
                            "content",
                            "",
                        )
                    ),
                ]
            )

            corpus.append(
                tokenize(searchable_text)
            )

        query_tokens = tokenize(query)

        if not query_tokens:
            return results[:top_k]

        bm25 = BM25Okapi(
            corpus
        )

        scores = bm25.get_scores(
            query_tokens
        )

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )

        ranked = []

        for index in ranked_indices:

            result = dict(
                results[index]
            )

            result[
                "bm25_score"
            ] = float(
                scores[index]
            )

            ranked.append(
                result
            )

            if len(ranked) >= top_k:
                break

        return ranked
