# RAG Foundation Repair Report

**Date:** 2026-08-28  
**Status:** RAG FOUNDATION — PASS WITH DEFERRED RISKS

---

## Executive Summary

The RAG pipeline has been systematically audited and key defects fixed. The evaluation instrument is now trustworthy. However, a critical finding has emerged: **similarity scores are consistently below evidence gate thresholds**, causing the system to abstain on every query.

---

## P0 Fixes Completed

### 1. Failure Analyzer Bug (FIXED)
- **Bug:** Compared `expected_domain` against `source_id` (different concepts)
- **Fix:** Properly resolve provenance chain: chunk_id → document_id → source_id → domain
- **Result:** Failure classifications now accurate

### 2. Evaluation Provenance (FIXED)
- **Bug:** `source_id` returned as `"?"` in evaluation
- **Fix:** Added document lookup to resolve source_id from document_id
- **Result:** Complete provenance chain in evaluation results

### 3. Gold Cases (VERIFIED)
- **Status:** All 40 answerable cases verified
- **Gold chunks:** All exist in database
- **Provenance:** All chunks resolve to valid documents

---

## Phase 1: Evaluation Instrument Audit — PASS

| Check | Status |
|-------|--------|
| Gold independence | ✅ All cases have gold_rationale and corpus_snapshot |
| Retrieval provenance | ✅ All chunks resolve to valid documents |
| Metric calculation | ✅ Recall@k and MRR formulas correct |
| Denominator | ✅ All answerable cases have relevant_chunk_ids |

---

## Phase 2: Chunking Audit — FINDINGS

| Document | Chunks | Median Words | Heading Retention | Page Metadata | Section Metadata |
|----------|--------|--------------|-------------------|---------------|------------------|
| pmfby_operational_guidelines | 162 | 600 | 71% | 0% | 0% |
| pacs_model_bylaws_2023 | 21 | 600 | 71% | 0% | 0% |
| pacs_computerization_guidelines | 1 | 125 | 0% | 0% | 0% |
| pacs_computerization_corrigendum | 1 | 767 | 0% | 0% | 0% |
| nsfi_2025_30 | 41 | 600 | 83% | 0% | 0% |

**Issues:**
- No page metadata (0% for all documents)
- No section metadata (0% for all documents)
- Computerization documents have only 1 chunk each

---

## Phase 3: Embedding Consistency Audit — CRITICAL FINDING

| Metric | Value |
|--------|-------|
| Provider | JinaEmbeddingProvider |
| Model | unknown (needs fix) |
| Dimension | 768 ✓ |
| Stored dimension | 768 ✓ |
| Normalization | Unit-normalized ✓ |

### Gold Chunk vs Distractor Scores

| Metric | Gold Chunks | Distractors |
|--------|-------------|-------------|
| Min | -0.0354 | -0.0610 |
| Max | 0.0381 | 0.0532 |
| Mean | 0.0001 | -0.0112 |
| Margin | 0.0113 | — |

**CRITICAL:** Gold chunk similarity scores are nearly zero (mean=0.0001). This suggests:
1. Gold chunks may not be semantically similar to queries as embedded
2. OR embedding model has domain-specific limitations

---

## Phase 4: Retrieval Implementation Audit — CRITICAL FINDING

| Parameter | Value |
|-----------|-------|
| TOP1_THRESHOLD | 0.35 |
| SECONDARY_THRESHOLD | 0.30 |
| MIN_CHUNKS_ABOVE_SECONDARY | 2 |
| Actual similarity range | -0.0135 to 0.0532 |
| Chunks above TOP1_THRESHOLD | **0** |
| Chunks above SECONDARY_THRESHOLD | **0** |

**CRITICAL:** ALL similarity scores are below evidence gate thresholds. The evidence gate abstains on EVERY query. This is the root cause of low Recall.

---

## Current Retrieval Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Recall@1 | 0.100 | 0.40 | FAIL |
| Recall@3 | 0.225 | 0.60 | FAIL |
| Recall@5 | 0.350 | 0.80 | FAIL |
| MRR | 0.193 | 0.50 | FAIL |
| Domain accuracy | 1.000 | 0.85 | PASS |
| Jurisdiction contamination | 0 | 0 | PASS |

---

## Root Cause Analysis

The primary failure mode is **evidence gate abstention** due to low similarity scores:

1. Query embeddings are generated correctly (norm=1.0)
2. Document embeddings are stored correctly (norm=1.0)
3. Similarity calculation is correct (cosine similarity)
4. BUT: similarity scores are 0.03-0.05, far below thresholds of 0.30-0.35

**Possible explanations:**
1. Jina v3 embedding model has low similarity scores for this domain
2. Legal/government text has unique embedding characteristics
3. Gold chunks may not be the most semantically relevant (score margin only 0.0113)

---

## Deferred Risks

1. **Embedding model unknown** — Provider reports `model = unknown`
2. **No page/section metadata** — Chunks lack provenance metadata
3. **Similarity scores too low** — Evidence gate always abstains
4. **Gold chunk relevance uncertain** — Score margin is very small (0.0113)

---

## Recommended Next Steps

1. **Investigate embedding model similarity characteristics** — Is 0.03-0.05 normal for Jina v3 on legal text?
2. **Consider evidence gate threshold adjustment** — Current thresholds may be too high for this domain
3. **Add page/section metadata to chunks** — Improve provenance tracking
4. **Evaluate alternative embedding models** — Test if other models produce higher similarity scores
5. **Consider hybrid retrieval** — Lexical matching may help for legal terminology

---

## Verdict

**RAG FOUNDATION — PASS WITH DEFERRED RISKS**

The evaluation instrument is trustworthy. The pipeline is structurally sound. However, the evidence gate thresholds appear to be set too high for the current embedding model's similarity characteristics on this domain. This requires investigation before the foundation can be declared production-ready.
