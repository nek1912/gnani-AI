import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi


BASE_DIR = Path(__file__).resolve().parent.parent.parent

METADATA_PATH = (
    BASE_DIR
    / "data"
    / "indexes"
    / "section_metadata.json"
)


def tokenize(text: str) -> list[str]:
    text = str(text or "").lower()
    return re.findall(r"\b\w+\b", text)


class BM25Retriever:

    def __init__(self, metadata_path=METADATA_PATH):
        print("Loading BM25 retrieval system...")

        metadata_path = Path(metadata_path)

        if not metadata_path.exists():
            print(f"Warning: BM25 metadata not found at {metadata_path}, BM25 ranking disabled")
            self.metadata = []
            self.tokenized_corpus = []
            self.bm25 = None
            return

        print("Loading metadata...")

        with open(metadata_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)

        if not self.metadata:
            raise RuntimeError("Metadata contains no chunks.")

        print(f"Preparing BM25 corpus: {len(self.metadata)} chunks")

        self.tokenized_corpus = []

        for item in self.metadata:
            text = item.get("text", "")
            self.tokenized_corpus.append(tokenize(text))

        print("Building BM25 index...")

        self.bm25 = BM25Okapi(self.tokenized_corpus)

        print("BM25 retrieval system ready.")
        print(f"Documents: {len(self.metadata)}")

    @staticmethod
    def _build_result(metadata: dict, score: float) -> dict:
        return {
            "score": float(score),
            "bm25_score": float(score),
            "chunk_id": metadata.get("chunk_id"),
            "document_id": metadata.get("document_id"),
            "source_url": metadata.get("source_url"),
            "source_title": metadata.get(
                "source_title",
                metadata.get("title"),
            ),
            "title": metadata.get(
                "title",
                metadata.get("source_title"),
            ),
            "section_id": metadata.get("section_id"),
            "section_title": metadata.get("section_title"),
            "section_type": metadata.get("section_type"),
            "page": metadata.get("page"),
            "language": metadata.get("language"),
            "text": metadata.get("text", ""),
        }

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        query = str(query or "").strip()

        if not query or not self.bm25:
            return []

        if top_k <= 0:
            return []

        query_tokens = tokenize(query)

        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )

        results = []

        for index_id in ranked_indices[:top_k]:
            metadata = self.metadata[index_id]
            results.append(
                self._build_result(
                    metadata=metadata,
                    score=scores[index_id],
                )
            )

        return results

    def rank_candidates(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 15,
    ) -> list[dict]:
        query = str(query or "").strip()

        if not query or not self.bm25:
            return candidates[:top_k] if candidates else []

        if not candidates:
            return []

        if top_k <= 0:
            return []

        query_tokens = tokenize(query)

        if not query_tokens:
            return []

        tokenized_candidates = []

        for candidate in candidates:
            searchable_text = " ".join(
                [
                    str(candidate.get("text", "")),
                    str(candidate.get("title", "")),
                    str(candidate.get("source_title", "")),
                    str(candidate.get("section_title", "")),
                ]
            )
            tokenized_candidates.append(tokenize(searchable_text))

        temporary_bm25 = BM25Okapi(tokenized_candidates)

        scores = temporary_bm25.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(candidates)),
            key=lambda i: (scores[i], -i),
            reverse=True,
        )

        results = []

        for index in ranked_indices[:top_k]:
            candidate = dict(candidates[index])
            score = float(scores[index])
            candidate["bm25_score"] = score
            candidate["score"] = score
            candidate["retriever"] = "bm25"
            results.append(candidate)

        return results


_retriever = None


def retrieve(query: str, top_k: int = 5):
    global _retriever

    if _retriever is None:
        _retriever = BM25Retriever()

    return _retriever.retrieve(query=query, top_k=top_k)


def rank_candidates(
    query: str,
    candidates: list[dict],
    top_k: int = 15,
):
    global _retriever

    if _retriever is None:
        _retriever = BM25Retriever()

    return _retriever.rank_candidates(
        query=query,
        candidates=candidates,
        top_k=top_k,
    )
