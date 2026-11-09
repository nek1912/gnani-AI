# RAG Repair Baseline Report

**Date:** 2026-08-28  
**Status:** IN PROGRESS — Gold foundation being validated

---

## Current Valid Baseline

### Test Suite Results

| Suite | Passed | Failed | Skipped | Total |
|-------|--------|--------|---------|-------|
| backend/tests | 95 | 2 | 0 | 97 |
| ingestion/tests | 32 | 0 | 10 | 42 |
| tests/ (root) | 14 | 8 | 0 | 22 |
| **TOTAL** | **141** | **10** | **10** | **161** |

**Failed tests:**
- `test_schema_smoke.py` (2) — DNS failure (not code bug)
- `test_corpus_check.py` (8) — Test logic issues

### Corpus State

| Metric | Value |
|--------|-------|
| Documents | 5 |
| Chunks | 226 |
| Embedding model | jina-embeddings-v3 |
| Embedding dimension | 768 |
| Corpus hash | 2fc08e7d9e959de4 |
| Git commit | 861bae9 |

### Gold Set State

| Metric | Value |
|--------|-------|
| Total cases | 245 |
| Answerable | 40 |
| Unanswerable | 205 |
| Corrected cases | 40 |
| Verified cases | 38 |
| Unverified cases | 2 |
| Domains with answerable | 2 (pacs_governance: 17, pmfby: 21, adversarial: 2) |
| Domains without answerable | 5 (schemes, agriculture, financial_inclusion, grievance, out_of_scope) |

### Retrieval Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Recall@1 | 0.100 | 0.40 | FAIL |
| Recall@3 | 0.225 | 0.60 | FAIL |
| Recall@5 | 0.350 | 0.80 | FAIL |
| MRR | 0.193 | 0.50 | FAIL |
| Domain accuracy | 1.000 | 0.85 | PASS (diagnostic) |
| Jurisdiction contamination | 0 | 0 | PASS |

### Failure Analysis

| Failure Type | Count | Percentage |
|--------------|-------|------------|
| NO_OVERLAP | 19 | 47.5% |
| FULL_OVERLAP | 14 | 35.0% |
| PARTIAL_OVERLAP | 7 | 17.5% |

| Root Cause | Count | Percentage |
|------------|-------|------------|
| Domain routing mismatch | 19 | 47.5% |
| Partial retrieval - chunks ranked too low | 19 | 47.5% |
| Gold chunks do not exist in database | 2 | 5.0% |

---

## Historical Invalid Metrics (DO NOT USE)

| Metric | Old Value | Why Invalid |
|--------|-----------|-------------|
| Recall@1 | 0.125 | Gold set was mechanically generated |
| Recall@3 | 0.375 | Same 6 chunks repeated across 40 cases |
| Recall@5 | 0.425 | Not semantically relevant |
| MRR | 0.249 | Not semantically relevant |

---

## Key Findings

### 1. Gold Generator Defect (FIXED)
- `populate_gold_chunk_ids.py` took first 3 chunks by position
- Same 6 unique chunks repeated across 120 assignments
- Now replaced with semantic keyword-based selection

### 2. PMFBY Gold Chunk Error (FIXED)
- Gold chunk `e2c84858` was about "Surplus Sharing"
- Question asked about "risks covered"
- Now corrected to `f945e35d` which covers "Coverage of Risks and Exclusions"

### 3. Missing Gold Chunks (FIXED)
- 2 cases had gold chunks that don't exist in database
- Now corrected to use existing chunks

### 4. Domain Routing Mismatch (47.5% of failures)
- Gold chunks are from different domains than classifier output
- Need to investigate if this is a gold-set error or retrieval error

### 5. Chunk Ranking Issues (47.5% of failures)
- Gold chunks exist but are not ranked in top positions
- Need to investigate embedding quality or retrieval parameters

### 6. Financial Inclusion Domain (UNVALIDATED)
- Zero answerable cases
- Domain accuracy=100% is meaningless for this domain
- Need to add answerable cases or document limitation

---

## Next Steps

1. Complete gold validation for remaining 2 unverified cases
2. Investigate domain routing mismatches
3. Audit chunking quality
4. Audit embedding quality
5. Run controlled retrieval ablations
6. Build repeatable benchmark harness
