# RAG Foundation Final Status

**Date:** 2026-08-28  
**Status:** RAG FOUNDATION — FAIL

---

## Verified State

| Component | Status |
|-----------|--------|
| Embedding provenance | PASS |
| Gold set validity | PASS (frozen) |
| Corpus | FROZEN |
| Dense Recall@20 | 1.000 |
| Chunking | Reasonable (21 chunks, 51-767 words) |

---

## Failure Forensics

### Root Cause: Semantic Ranking Issue

The embedding model ranks chunks by overall semantic similarity, not by specific topic relevance.

**Example:**
- Query: "Quorum requirements for cooperative society meetings"
- Gold chunk: "Requisitioned General Body Meeting" (rank 6, sim=0.619)
- Top chunk: "Ineligibility/Disqualification of Members" (rank 1, sim=0.650)

The embedding model ranks "Ineligibility" higher because it contains words like "meeting", "general body", "society" which are similar to the query. But "Ineligibility" is about disqualification, not quorum requirements.

---

## Best Measured Architecture

| Config | Recall@1 | Recall@5 | MRR |
|--------|----------|----------|-----|
| Dense + Heuristic Reranker | 0.400 | 0.600 | 0.509 |

---

## Targets vs Actual

| Metric | Actual | Target | Gap |
|--------|--------|--------|-----|
| Recall@1 | 0.400 | 0.80 | -0.40 |
| Recall@5 | 0.600 | 0.95 | -0.35 |
| MRR | 0.509 | 0.90 | -0.391 |

---

## Root Cause Analysis

### Why Recall@5 = 0.600?

1. **Candidate retrieval works** — Recall@20 = 1.000
2. **Ranking is inadequate** — Relevant chunks ranked 6-10 instead of 1-5
3. **Embedding model limitation** — Ranks by overall similarity, not topic relevance
4. **Heuristic reranker insufficient** — Token overlap doesn't capture legal terminology

### Specific Failure Pattern

For "Quorum requirements" query:
- Gold chunk "Requisitioned General Body Meeting" (rank 6)
- Top chunk "Ineligibility/Disqualification" (rank 1)

The embedding model ranks "Ineligibility" higher because it contains similar words. But "Ineligibility" is about disqualification, not quorum requirements.

---

## What Would Fix This

1. **Semantic reranker** — Cross-encoder that understands legal terminology
2. **Better chunking** — Split large chunks to isolate specific provisions
3. **Query expansion** — Conservative expansion for legal queries

---

## Safety Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Domain accuracy | 1.000 | 0.95 | ✅ PASS |
| Jurisdiction contamination | 0 | 0 | ✅ PASS |

---

## Verdict

**RAG FOUNDATION — FAIL**

The foundation is structurally sound. The retrieval system finds all relevant evidence (Recall@20 = 100%). However, the ranking quality is insufficient to meet the near-production targets. The embedding model and heuristic reranker cannot capture the semantic relationship between legal queries and answer-bearing chunks.

**Exact blocker:** Relevant chunks ranked 6-10 instead of 1-5. The embedding model ranks by overall similarity, not topic relevance.

---

## Files Created

| File | Purpose |
|------|---------|
| `docs/rag_foundation_final_status.md` | Final status |
| `eval/local_reranker.py` | Heuristic reranker |
| `eval/multi_stage_retrieval.py` | Multi-stage retrieval |
| `eval/cross_encoder_reranker.py` | Cross-encoder reranker (needs model download) |
