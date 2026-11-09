"""Static RAG service — encapsulates Supabase pgvector hybrid retrieval.

Provides a single entry point for the static retrieval pipeline:
  1. Hybrid retrieval (dense + lexical with RRF fusion)
  2. Optional Jina reranker (if enabled)
  3. Conversion to EvidenceChunk contracts
  4. Unified evidence gate validation
  5. Returns typed RAGResult
"""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
    RAGResult,
    RetrievalCandidate,
)
from app.db import get_supabase
from app.evidence_gate import evidence_gate
from app.providers.reranker import JinaReranker
from app.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

_DOMAIN_MAP = {
    "pacs": "pacs_governance",
    "finlit": "financial_inclusion",
    "cooperative": "pacs_governance",
    "agriculture": "pmfby",  # No agri docs yet — route to closest corpus
}


class StaticRAGService:
    """Encapsulates Supabase pgvector hybrid retrieval pipeline.

    Usage:
        service = StaticRAGService(settings)
        result = service.retrieve(
            embedding=[...],
            query="What is PMFBY?",
            domain="pmfby",
            state="gujarat",
        )
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def retrieve(
        self,
        embedding: list[float],
        query: str,
        domain: str,
        state: str | None,
        k: int | None = None,
        as_of_date: str | None = None,
    ) -> RAGResult:
        """Run static RAG pipeline and return typed result.

        Args:
            embedding: Query embedding vector.
            query: English query text.
            domain: Requested domain (raw, before _DOMAIN_MAP).
            state: Requested state filter (or None for central only).
            k: Number of chunks to retrieve. Defaults to 25 (the old
               25-if-reranked-else-6 split was removed; retrieval always
               fetches 25 and the reranker truncates to top_n=15).
            as_of_date: Optional ISO date for effective-date filtering at
                the SQL layer (passed through to match_chunks).

        Returns:
            RAGResult with chunks, abstention info, and confidence band.
        """
        retrieval_domain = _DOMAIN_MAP.get(domain, domain)
        effective_k = k or 25

        # Step 1: Hybrid retrieval
        try:
            supabase = get_supabase()
            chunks = self._retrieve_hybrid(
                supabase, embedding, query, retrieval_domain, state,
                k=effective_k, as_of_date=as_of_date,
            )
        except Exception:
            logger.exception("Static RAG retrieval failed")
            return RAGResult(
                chunks=[],
                abstained=True,
                reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                band=ConfidenceBand.LOW,
                domain=retrieval_domain,
            )

        # Step 2: Optional reranker
        if self._settings.reranker_enabled and chunks:
            chunks = self._apply_reranker(query, chunks)

        # Step 3: Convert to EvidenceChunk
        evidence_chunks = [self._to_evidence_chunk(c, retrieval_domain) for c in chunks]

        # Step 4: Evidence gate
        try:
            abstained, reason, band = evidence_gate(
                evidence_chunks,
                expected_domain=retrieval_domain,
                expected_state=state,
            )
        except Exception:
            logger.exception("Evidence gate failed")
            abstained, reason, band = True, AbstentionReason.CITATION_FAILURE, ConfidenceBand.LOW

        logger.info(
            "StaticRAGService result: chunks=%d abstained=%s reason=%s band=%s",
            len(evidence_chunks), abstained, reason, band,
        )

        return RAGResult(
            chunks=evidence_chunks,
            abstained=abstained,
            reason=reason,
            band=band,
            domain=retrieval_domain,
        )

    def _apply_reranker(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """Apply Jina reranker to reorder chunks. Returns original on failure."""
        try:
            reranker = JinaReranker()
            docs_for_rerank = [
                {"chunk_id": c.chunk_id, "content": c.content} for c in chunks
            ]
            reranked = reranker.rerank(query, docs_for_rerank, top_n=15)
            chunks_by_id = {c.chunk_id: c for c in chunks}
            return [
                chunks_by_id[r["chunk_id"]]
                for r in reranked
                if r["chunk_id"] in chunks_by_id
            ]
        except Exception:
            logger.warning("Reranker failed, returning original chunks")
            return chunks

    # ── Hybrid retrieval (inlined from hybrid_retrieval.py) ────────────────

    @staticmethod
    def _retrieve_hybrid(
        supabase, query_embedding: list[float], query_text: str,
        domain: str, state: str | None, k: int = 6,
        as_of_date: str | None = None,
    ) -> list[RetrievedChunk]:
        """Hybrid retrieval: dense + lexical with RRF fusion."""
        dense_chunks = _dense_retrieve(
            supabase, query_embedding, domain, state, k=k, as_of_date=as_of_date,
        )
        try:
            lexical_chunks = _lexical_retrieve(supabase, query_text, domain, state, k=k)
        except Exception:
            lexical_chunks = []

        if not lexical_chunks:
            return _enrich_chunks(supabase, dense_chunks)

        dense_candidates = []
        for i, chunk in enumerate(dense_chunks):
            dense_candidates.append(RetrievalCandidate(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_id=chunk.source_file or "",
                dense_rank=i + 1,
                dense_score=chunk.similarity,
                filter_decisions={"domain": chunk.domain == domain, "active": True},
            ))

        lexical_candidates = []
        for i, chunk in enumerate(lexical_chunks):
            lexical_candidates.append(RetrievalCandidate(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_id=chunk.source_file or "",
                lexical_rank=i + 1,
                lexical_score=chunk.similarity or 0.5,
                filter_decisions={"domain": chunk.domain == domain, "active": True},
            ))

        fused = _reciprocal_rank_fusion(dense_candidates, lexical_candidates)

        chunk_map: dict[str, RetrievedChunk] = {}
        for c in dense_chunks:
            chunk_map[c.chunk_id] = c
        for c in lexical_chunks:
            if c.chunk_id not in chunk_map:
                chunk_map[c.chunk_id] = c

        result = []
        for candidate in fused[:k]:
            chunk = chunk_map.get(candidate.chunk_id)
            if chunk:
                result.append(chunk)

        return _enrich_chunks(supabase, result or dense_chunks)

    @staticmethod
    def _to_evidence_chunk(chunk: RetrievedChunk, domain: str) -> EvidenceChunk:
        """Convert a RetrievedChunk to an EvidenceChunk contract."""
        return EvidenceChunk(
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            source_type="static",
            title=chunk.title,
            url=chunk.source_url,
            page=chunk.page,
            section=chunk.section,
            domain=chunk.domain or domain,
            jurisdiction=chunk.jurisdiction,
            state=chunk.state,
            dense_score=chunk.similarity,
            metadata={
                "stable_chunk_id": chunk.stable_chunk_id,
                "document_id": chunk.document_id,
                "source_file": chunk.source_file,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "subsection": chunk.subsection,
                "clause": chunk.clause,
            },
        )


# ── Module-level hybrid retrieval helpers (inlined from hybrid_retrieval.py) ──


def _dense_retrieve(supabase, query_embedding: list[float], domain: str,
                    state: str | None, k: int = 10,
                    as_of_date: str | None = None,
                    match_entity_id: str | None = None) -> list[RetrievedChunk]:
    """Dense retrieval via match_chunks RPC.

    PostgREST selects among overloaded match_chunks functions by the set
    of body keys. Live DBs carry both the legacy 4-arg overload and the
    newer 6-arg overload (as_of_date + match_entity_id); a 4-key call
    matches both and fails with 300/PGRST203. Always sending all 6 keys
    selects the 6-arg overload unambiguously (null extras = no filtering,
    i.e. legacy-equivalent behavior).
    """
    params = {
        "query_embedding": query_embedding,
        "match_domain": domain,
        "match_state": state,
        "match_count": k,
        "as_of_date": as_of_date,
        "match_entity_id": match_entity_id,
    }
    try:
        rows = supabase.rpc("match_chunks", params).execute().data or []
    except Exception as e:
        # Backward compat with DBs that only have the legacy overload:
        # PostgREST reports "no matching overload" (PGRST202) when the
        # 6-key call matches nothing. Only then retry the legacy 4-key
        # call. PGRST203 (ambiguity) must NOT fall back — fewer keys
        # re-trigger it.
        msg = str(e)
        code = getattr(e, "code", "") or ""
        if "PGRST202" in code or "PGRST202" in msg or "Could not find the function" in msg:
            rows = supabase.rpc("match_chunks", {
                "query_embedding": query_embedding,
                "match_domain": domain,
                "match_state": state,
                "match_count": k,
            }).execute().data or []
        else:
            raise
    return [
        RetrievedChunk(
            chunk_id=str(r.get("chunk_id") or r["id"]),
            stable_chunk_id=r.get("stable_chunk_id") or str(r.get("chunk_id") or r["id"]),
            document_id=str(r.get("document_id") or ""),
            title=r.get("title") or "",
            page=r.get("page") or 0,
            page_start=r.get("page_start") or r.get("page") or 0,
            page_end=r.get("page_end") or r.get("page") or 0,
            section=r.get("section") or "",
            subsection=r.get("subsection") or "",
            clause=r.get("clause") or "",
            content=r.get("content") or "",
            similarity=r.get("similarity") or 0.0,
            source_url=r.get("source_url") or "",
            source_file=r.get("source_file") or "",
            domain=r.get("domain") or domain,
            jurisdiction=r.get("jurisdiction") or "central",
            state=r.get("state"),
        )
        for r in rows
    ]


def _lexical_retrieve(supabase, query_text: str, domain: str,
                      state: str | None, k: int = 10) -> list[RetrievedChunk]:
    """Lexical retrieval via term-overlap on chunks.content."""
    doc_rows = (
        supabase.table("documents")
        .select("id, title, jurisdiction, state, domain, source_url")
        .execute()
        .data or []
    )
    eligible = {
        d["id"]
        for d in doc_rows
        if d.get("domain") == domain and (
            d.get("jurisdiction") == "central"
            or (state is not None and d.get("state") == state)
        )
    }
    if not eligible:
        return []

    rows = (
        supabase.table("chunks")
        .select("id, content, document_id, page, section")
        .in_("document_id", list(eligible))
        .limit(2000)
        .execute()
        .data or []
    )

    import re
    raw_tokens = [re.sub(r"[^\w]", "", t.lower()) for t in query_text.split()]
    STOP_WORDS = {
        "what", "is", "a", "an", "the", "in", "of", "to", "for", "and", "or", "on", "are",
        "it", "this", "that", "how", "why", "who", "which", "where", "can", "i", "you",
        "my", "me", "do", "does", "did", "be", "been", "being", "have", "has", "had",
        "tell", "about", "give", "list", "show", "detail", "details", "scheme", "yojana",
    }
    query_terms = [t for t in raw_tokens if t and (len(t) > 2 or t in ("pm", "id")) and t not in STOP_WORDS]
    if not query_terms:
        query_terms = [t for t in raw_tokens if t]

    scored = []
    for row in rows:
        content_lower = row["content"].lower()
        sec_lower = (row.get("section") or "").lower()
        matches = sum(2 if t in sec_lower else 1 for t in query_terms if t in content_lower or t in sec_lower)
        if matches > 0:
            scored.append((matches, row))

    scored.sort(key=lambda x: -x[0])

    doc_meta = {d["id"]: d for d in doc_rows}
    results = []
    for _, row in scored[:k]:
        d = doc_meta.get(row["document_id"])
        if not d:
            continue
        results.append(RetrievedChunk(
            chunk_id=str(row["id"]),
            stable_chunk_id=str(row["id"]),
            document_id=str(row["document_id"]),
            title=d.get("title") or "",
            page=row.get("page") or 0,
            page_start=row.get("page_start") or row.get("page") or 0,
            page_end=row.get("page_end") or row.get("page") or 0,
            section=row.get("section") or "",
            content=row["content"],
            similarity=0.50,
            source_url=d.get("source_url", ""),
            domain=d.get("domain") or domain,
            jurisdiction=d.get("jurisdiction") or "central",
            state=d.get("state"),
        ))
    return results


def _enrich_chunks(supabase, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Attach stable application chunk_id + provenance metadata."""
    if not chunks:
        return chunks
    uuids = [c.chunk_id for c in chunks]
    try:
        rows = (
            supabase.table("chunks")
            .select("id, chunk_id, document_id, section, metadata")
            .in_("id", uuids)
            .execute()
            .data or []
        )
    except Exception:
        return chunks
    by_id = {str(r["id"]): r for r in rows}
    for c in chunks:
        r = by_id.get(c.chunk_id)
        if not r:
            continue
        meta = r.get("metadata") or {}
        c.stable_chunk_id = r.get("chunk_id")
        c.document_id = r.get("document_id")
        c.source_file = meta.get("source_file", "") or ""
        c.page_start = meta.get("page_start") or c.page
        c.page_end = meta.get("page_end") or c.page
        c.subsection = meta.get("subsection", "") or ""
        c.clause = meta.get("clause", "") or ""
    return chunks


def _reciprocal_rank_fusion(
    dense_candidates: list[RetrievalCandidate],
    lexical_candidates: list[RetrievalCandidate],
    k: int = 60,
    dense_weight: float = 0.6,
    lexical_weight: float = 0.4,
) -> list[RetrievalCandidate]:
    """Fuse dense and lexical results using deterministic weighted RRF."""
    dense_ranks = {c.chunk_id: i + 1 for i, c in enumerate(dense_candidates)}
    lexical_ranks = {c.chunk_id: i + 1 for i, c in enumerate(lexical_candidates)}

    all_candidates: dict[str, RetrievalCandidate] = {}
    for c in dense_candidates:
        all_candidates[c.chunk_id] = c
    for c in lexical_candidates:
        if c.chunk_id not in all_candidates:
            all_candidates[c.chunk_id] = c

    fused: list[tuple[float, int, str, str, RetrievalCandidate]] = []
    for chunk_id, candidate in all_candidates.items():
        dense_rank = dense_ranks.get(chunk_id)
        lexical_rank = lexical_ranks.get(chunk_id)

        dense_score = dense_weight / (k + dense_rank) if dense_rank else 0.0
        lexical_score = lexical_weight / (k + lexical_rank) if lexical_rank else 0.0
        fused_score = dense_score + lexical_score

        component_ranks = [r for r in [dense_rank, lexical_rank] if r is not None]
        best_rank = min(component_ranks) if component_ranks else k

        fused.append((fused_score, best_rank, candidate.document_id,
                       candidate.chunk_id, candidate))

    fused.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))

    result = []
    for rank, (score, _, _, _, candidate) in enumerate(fused, 1):
        candidate.fused_score = round(score, 8)
        candidate.final_rank = rank
        result.append(candidate)

    return result
