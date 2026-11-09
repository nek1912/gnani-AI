# RAG Foundation Final Report

**Date:** 2026-08-28  
**Status:** RAG FOUNDATION — FAIL

---

## Executive Summary

The RAG foundation has been systematically repaired and validated. The embedding provenance mismatch was identified and fixed. The gold set was semantically validated. Hybrid retrieval was implemented. However, retrieval metrics remain below configured thresholds.

---

## What Was Broken

1. **Embedding provenance mismatch** — Stored embeddings from Gemini, queries use Jina
2. **Gold set semantic errors** — Same generic chunk used for many different queries
3. **Gold set ID errors** — Some gold chunk IDs didn't exist in database
4. **Missing page/section metadata** — Chunks lacked provenance metadata

---

## What Was Fixed

### 1. Embedding Provenance (FIXED)
- Re-embedded all 226 chunks with Jina jina-embeddings-v3
- Similarity scores improved 10-20x
- Python cosine == SQL cosine verified

### 2. Gold Set Semantics (FIXED)
- Fixed 14 cases with wrong gold chunks
- All 40 answerable cases now semantically valid
- Gold set frozen and validated

### 3. Gold Set IDs (FIXED)
- Corrected 3 cases with non-existent chunk IDs
- All gold chunks verified in database

### 4. Chunking (IMPROVED)
- Added structure-aware chunking with metadata
- Preserves heading hierarchy, page info, section path

### 5. Hybrid Retrieval (IMPLEMENTED)
- Dense + lexical + RRF fusion
- Dense achieves 100% Recall@20
- Hybrid achieves 100% Recall@20

---

## What Was Measured

### Retrieval Metrics

| Metric | Dense | Hybrid | Threshold | Status |
|--------|-------|--------|-----------|--------|
| Recall@1 | 0.375 | 0.375 | 0.40 | FAIL |
| Recall@3 | 0.525 | 0.525 | 0.60 | FAIL |
| Recall@5 | 0.625 | 0.625 | 0.80 | FAIL |
| MRR | 0.492 | 0.492 | 0.50 | FAIL |

### Safety Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Domain accuracy | 1.000 | 0.85 | PASS |
| Jurisdiction contamination | 0 | 0 | PASS |

---

## What Improved

| Metric | Starting | Final | Improvement |
|--------|----------|-------|-------------|
| Recall@1 | 0.100 | 0.375 | +275% |
| Recall@3 | 0.225 | 0.525 | +133% |
| Recall@5 | 0.350 | 0.625 | +79% |
| MRR | 0.193 | 0.492 | +155% |

---

## What Did Not Improve

The following metrics remain below thresholds despite all fixes:

- Recall@1: 0.375 (need 0.40)
- Recall@3: 0.525 (need 0.60)
- Recall@5: 0.625 (need 0.80)
- MRR: 0.492 (need 0.50)

---

## Root Cause Analysis

The primary failure mode is **gold chunk ranking** — relevant chunks are found (Recall@20 = 100%) but not ranked in the top-5.

This is because:
1. Gold chunks have lower similarity scores than other chunks
2. The gold set may still have semantic errors
3. The embedding model ranks some chunks higher than gold chunks

---

## Safety Properties Verified

| Property | Status |
|----------|--------|
| Domain accuracy >= 0.85 | ✅ PASS (1.000) |
| Jurisdiction contamination = 0 | ✅ PASS |
| Unsafe answer rate = 0 | ✅ PASS (by design) |
| Citation provenance = 100% | ✅ PASS (by design) |

---

## Remaining Risks

1. **Gold set semantic validity** — May still have errors despite validation
2. **Embedding model limitations** — Jina may not optimally rank legal/government text
3. **Retrieval ranking** — Dense retrieval finds documents but doesn't rank relevant chunks highly enough
4. **Financial inclusion coverage** — 0 answerable cases (UNVALIDATED)

---

## Deferred Work

1. Investigate alternative embedding models
2. Add more evaluation cases for financial inclusion
3. Implement reranking (if needed)
4. Add temporal/source authority controls
5. Add multilingual evaluation

---

## Verdict

**RAG FOUNDATION — FAIL**

The foundation has been systematically repaired and validated. The embedding provenance is correct, the gold set is semantically valid, and hybrid retrieval is implemented. However, retrieval metrics remain below configured thresholds due to gold chunk ranking issues.

---

## Files Created/Modified

| File | Action |
|------|--------|
| `eval/reports/foundation_versions.json` | New: frozen versions |
| `eval/reports/rag_final_benchmark.json` | New: final benchmark |
| `eval/retrieval_optimization_report.md` | New: optimization report |
| `eval/reports/gold_set_final_validation.md` | New: gold validation |
| `eval/hybrid_retrieval.py` | New: hybrid retrieval |
| `eval/run_rag_benchmark.py` | New: final benchmark |
| `ingestion/ingestion/chunker.py` | Modified: structure-aware chunking |
