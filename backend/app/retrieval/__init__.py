from pydantic import BaseModel

from app.config import MIN_CHUNKS_ABOVE_SECONDARY, SECONDARY_THRESHOLD, TOP1_THRESHOLD


class RetrievedChunk(BaseModel):
    chunk_id: str            # internal database UUID (kept for citation matching)
    stable_chunk_id: str | None = None  # deterministic application-level ID
    document_id: str | None = None
    title: str
    page: int
    page_start: int | None = None
    page_end: int | None = None
    section: str
    subsection: str = ""
    clause: str = ""
    content: str
    similarity: float
    source_url: str = ""
    source_file: str = ""
    domain: str = ""
    jurisdiction: str
    state: str | None = None


class GateResult(BaseModel):
    abstained: bool
    reason: str | None = None
    confidence: float = 0.0


def retrieve(supabase, query_embedding: list[float], domain: str,
             state: str | None, k: int = 6,
             as_of_date: str | None = None,
             match_entity_id: str | None = None) -> list[RetrievedChunk]:
    # Always send the full 6-key param set so PostgREST unambiguously
    # selects the 6-arg match_chunks overload on DBs that also carry the
    # legacy 4-arg overload (4-key calls fail with 300/PGRST203 there).
    # Null extras mean "no filtering", i.e. legacy-equivalent behavior.
    params = {
        "query_embedding": query_embedding, "match_domain": domain,
        "match_state": state, "match_count": k,
        "as_of_date": as_of_date, "match_entity_id": match_entity_id,
    }
    rows = supabase.rpc("match_chunks", params).execute().data or []
    return [RetrievedChunk(
        chunk_id=str(r.get("chunk_id") or r["id"]),
        stable_chunk_id=r.get("stable_chunk_id") or str(r.get("chunk_id") or r["id"]),
        document_id=str(r["document_id"]),
        title=r["title"],
        page=r.get("page") or 0,
        page_start=r.get("page_start") or r.get("page") or 0,
        page_end=r.get("page_end") or r.get("page") or 0,
        section=r.get("section") or "",
        subsection=r.get("subsection") or "",
        clause=r.get("clause") or "",
        content=r["content"],
        similarity=r["similarity"],
        source_url=r.get("source_url") or "",
        source_file=r.get("source_file") or "",
        domain=r.get("domain") or domain,
        jurisdiction=r.get("jurisdiction") or "central",
        state=r.get("state"),
    ) for r in rows]


def _jurisdiction_ok(chunk: RetrievedChunk, expected_state: str | None) -> bool:
    return chunk.jurisdiction == "central" or chunk.state == expected_state


def evidence_gate(chunks: list[RetrievedChunk], expected_domain: str | None = None,
                  expected_state: str | None = None) -> GateResult:
    if not chunks:
        return GateResult(abstained=True, reason="no_chunks")
    if expected_domain is not None and any(c.domain != expected_domain for c in chunks):
        return GateResult(abstained=True, reason="domain_mismatch_in_retrieval")
    if not all(_jurisdiction_ok(c, expected_state) for c in chunks):
        return GateResult(abstained=True, reason="jurisdiction_mismatch_in_retrieval")
    sims = sorted((c.similarity for c in chunks), reverse=True)
    if sims[0] < TOP1_THRESHOLD:
        return GateResult(abstained=True, reason="below_top1_threshold")
    strong = sum(1 for s in sims if s >= SECONDARY_THRESHOLD)
    if strong < MIN_CHUNKS_ABOVE_SECONDARY:
        return GateResult(abstained=True, reason="insufficient_supporting_chunks")
    base = sims[0] * 0.6
    coverage = min(strong / 3, 1.0) * 0.3
    domain_bonus = 0.1 if (expected_domain is not None and
                           all(c.domain == expected_domain for c in chunks)) else 0.0
    confidence = base + coverage + domain_bonus
    if sims[0] < 0.3:
        confidence = min(confidence, 0.4)
    confidence = round(min(confidence, 1.0), 2)
    return GateResult(abstained=False, reason=None, confidence=confidence)
