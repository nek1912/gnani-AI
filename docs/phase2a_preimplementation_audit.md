# Phase 2A Pre-Implementation Audit Report

**Date:** 2026-08-27
**Audit approach:** Data-flow (manifest → ingestion → chunking → embedding → storage → retrieval → generation → citations)
**Status:** Complete

---

## 1. Current Ingestion Architecture

### File Discovery
- **Mechanism:** `SEEDS_DIR.glob("*.md")` at `ingestion/ingestion/ingest.py:41`
- **Scope:** Only discovers `.md` files in `corpus/seeds/` directory
- **Gap:** **P0** — The 5 MVP manifest PDFs will never be discovered. Pipeline is non-functional for its primary purpose.

### MVP Manifest Integration
- **Current:** `mvp_sources.yaml` is NOT loaded at runtime. Metadata is duplicated in YAML frontmatter of each `.md` file.
- **Gap:** **P1** — Manifest metadata (source_id, effective_date, issuing_organization, etc.) is never programmatically reconciled with frontmatter.

### Idempotency
- **Current:** DELETE by `source_id` before INSERT (`ingest.py:13`). Re-running overwrites cleanly.
- **Gap:** **P1** — If `source_id` changes between runs, old rows become orphaned. No staleness detection.

### Determinism
- **Current:** Deterministic for same input files (modulo embedding non-determinism from Gemini API).
- **Status:** Acceptable.

---

## 2. Current PDF-Processing Behavior

### PDF Extraction
- **Current:** **None.** No code calls Docling or any PDF parser. The pipeline assumes pre-chunked markdown input.
- **Gap:** **P0** — MVP manifest specifies 5 PDF sources; no extraction path exists.

### PDF Detection
- **Current:** No mechanism to detect scanned vs digital-text PDFs.
- **Gap:** **P2** — Manifest distinguishes `digital_scanned: "digital_text"` but this is not enforced.

### Extraction Failure Handling
- **Current:** No error handling around file processing. One bad file kills the entire run.
- **Gap:** **P1** — No per-file error isolation.

---

## 3. Current Chunking Behavior

### Algorithm
- **Heading-aware splitting:** `_HEADING = re.compile(r"^#{1,6}\s", re.M)` splits on markdown headings.
- **Oversized section splitting:** `_split_long()` splits sections exceeding `max_tokens` using word-count windows with overlap.
- **Undersized section merging:** Sections below `min_tokens` merge with previous chunk if combined size ≤ `max_tokens`.

### Token/Chunk Limits
| Parameter | Default |
|-----------|---------|
| `target_tokens` | 600 |
| `min_tokens` | 400 |
| `max_tokens` | 800 |
| `overlap_tokens` | 80 |

### Page/Section Preservation
- **Current:** Page and section metadata come from file-level frontmatter, not from within the document. All chunks from one file share the same page/section value.
- **Gap:** **P1** — Retrieval cannot distinguish which page/section a chunk came from within a multi-page PDF.

### Empty Chunks
- **Current:** Filtered out (`chunker.py:37`).
- **Status:** Acceptable.

### Overlap Determinism
- **Current:** Fixed-step sliding windows (`step = max(target - overlap, 1)`).
- **Status:** Acceptable.

---

## 4. Current Metadata Model

### MVP Manifest Fields (21 fields)
`source_id`, `filename`, `path`, `actual_title`, `issuing_organization`, `document_date`, `effective_date`, `document_type`, `jurisdiction`, `state`, `official_source_url`, `digital_scanned`, `status`, `primary_supplementary`, `target_domain`, `target_seed`, `collection_status`, `mvp_required`, `modifies`, `base_incorporates`, `legal_note`, `verification_note`

### DB Schema Fields (13 fields)
`id`, `source_id`, `title`, `organization`, `jurisdiction`, `state`, `domain`, `document_type`, `source_url`, `effective_date`, `verified_date`, `document_hash`, `created_at`

### Critical Gaps

| Gap | Severity | Evidence |
|-----|----------|----------|
| `document_date` not in DB | **P0** | Manifest has both `document_date` and `effective_date`; DB only has `effective_date` |
| `official_domain` not stored | **P0** | Required by Gate 2 Invariant 1; not in manifest, DB, or seeds |
| `source_type` not stored | **P0** | Required by Gate 2 Invariant 1; not in any metadata source |
| `status` not in DB | **P1** | "current_reference" vs "current_amendment" affects retrieval freshness |
| `primary_supplementary` not in DB | **P1** | Primary vs supplementary affects which document is authoritative |
| `modifies` / `base_incorporates` not in DB | **P1** | Amendment chain relationships lost |
| `legal_note` not in DB | **P1** | Safety disclaimers unavailable at generation time |
| `source_quality` in seeds but not in DB | **P1** | Quality marker lost at storage |

---

## 5. Current Embedding Behavior

### Provider
- **Model:** `gemini-embedding-2`, 768 dims
- **Calling pattern:** One HTTP request per string (sequential, not batched)
- **Dimension validation:** Enforced (`embeddings.py:23-24`)
- **Timeout:** 30 seconds

### Error Handling
| Error Type | Handling |
|------------|----------|
| HTTP errors | `raise_for_status()` raises `HTTPStatusError` |
| Rate limiting (429) | Not handled — immediate failure |
| Timeout | `httpx.TimeoutException` raised |
| Partial batch failure | Entire batch fails, no partial results |

### Gaps

| Gap | Severity | Evidence |
|-----|----------|----------|
| No fallback embedding provider | **P0** | Unlike LLM providers (Groq primary, Gemini fallback), embeddings have no fallback |
| No retry logic for transient failures | **P1** | Rate limiting (429), timeouts not retried |
| Sequential processing only | **P2** | One HTTP request per text; ~70 sequential requests for anchor store warming |

---

## 6. Current Supabase Ingestion Behavior

### match_chunks RPC
- **Filter logic:** Domain filter (nullable), jurisdiction filter (central OR state match), state filter (nullable)
- **Ordering:** Cosine similarity (`1 - (embedding <=> query_embedding)`)
- **Limit:** `least(match_count, 20)`

### Ingestion Flow
```
For each seed file:
  1. parse_chunk_file(path)       → YAML frontmatter + content
  2. DELETE documents WHERE source_id = X (cascades to chunks)
  3. INSERT new document row
  4. chunk_markdown(content)      → text pieces
  5. embed_texts(pieces)          → vectors
  6. For each piece: INSERT chunk row
```

### Gaps

| Gap | Severity | Evidence |
|-----|----------|----------|
| No state value normalization | **P0** | "Gujarat" vs "gujarat" would split into separate rows; `match_chunks` does exact equality |
| No transactional atomicity | **P0** | DELETE → INSERT cycle not wrapped in transaction; mid-failure leaves inconsistent state |
| No similarity threshold in RPC | **P1** | Returns all results regardless of similarity score |
| `chunks.metadata` never populated | **P1** | JSONB column exists but always `{}` |
| No index on `documents.domain` or `documents.state` | **P2** | Sequential scan on documents table for filtering |
| Chunk insert is not batched | **P2** | One HTTP round-trip per chunk |

---

## 7. Current Retrieval Behavior

### Production Retrieval
- **Function:** `retrieve()` at `retrieval.py:25-35`
- **Top-K:** 6 (hardcoded default)
- **Evidence gate:** Runs before generation with 5 checks:
  1. Empty chunks → abstain
  2. Domain mismatch → abstain (defense-in-depth)
  3. Jurisdiction mismatch → abstain (defense-in-depth)
  4. Top-1 similarity < 0.35 → abstain
  5. Fewer than 2 chunks with similarity ≥ 0.30 → abstain

### Confidence Calculation
```
confidence = min(0.6 * top1_similarity + 0.4 * (strong_count / total_chunks), 1.0)
```

### Gaps

| Gap | Severity | Evidence |
|-----|----------|----------|
| Provisional thresholds (0.35/0.30/2) | **P1** | Marked "calibrated in Phase 4"; no empirical evidence for actual corpus |
| No reranking | **P2** | pgvector cosine is sole ranking signal |
| No retrieval latency monitoring | **P2** | Gate 2 report shows "p50/p95 Not yet measured" |

---

## 8. Current Citation Behavior

### Generation
- **System prompt:** "You answer ONLY from the numbered context chunks"
- **User prompt:** Includes chunk content with `[chunk:ID]` markers
- **Citation verification:** `verify_citations()` cross-references every `[chunk:ID]` against actual retrieved set

### Evidence Gating Before Generation
- **Yes.** Gate runs at `chat.py:65-68`; if abstained, route returns immediately without calling LLM.

### Gaps

| Gap | Severity | Evidence |
|-----|----------|----------|
| `grounded_answer()` bypasses `verify_citations()` | **P1** | Invalid citations survive in answer text while silently removed from citations list |
| Domain/jurisdiction not in LLM context | **P2** | Available on `RetrievedChunk` but not passed to prompt |
| `INSUFFICIENT_EVIDENCE` check is fragile | **P2** | Exact string equality; LLM may append whitespace/punctuation |

---

## 9. Current Failure Handling

### Ingestion Failures
- **Current:** No error handling. One bad seed kills entire run.
- **Gap:** **P0** — No per-file error isolation.

### Embedding Failures
- **Current:** No retry logic. 429/5xx errors cause immediate failure.
- **Gap:** **P1** — No exponential backoff for transient failures.

### Retrieval Failures
- **Current:** Supabase exceptions caught by `_SAFE_FAILURES` → abstain. `Pydantic.ValidationError` NOT in `_SAFE_FAILURES` → 500.
- **Gap:** **P1** — Schema drift produces 500 instead of graceful abstention.

### Chat Route Failures
- **Current:** `_SAFE_FAILURES` tuple catches expected dependency failures. Unknown exceptions propagate as 500.
- **Gap:** **P1** — No structured logging; failures silently converted to generic abstain message.

---

## 10. Resource/Memory Risks

### Memory Profile
| Component | Memory | Risk |
|-----------|--------|------|
| FastAPI backend | ~50-80MB | LOW |
| Anchor store | ~10-20MB | LOW |
| Embedding provider | Minimal | LOW |
| Supabase client | Minimal | LOW |
| NumPy arrays | ~430KB | LOW |

### Assessment
All major data structures are bounded and small. Memory usage is well within 8GB RAM / 512MB Render Free limits.

---

## 11. Security Risks

### .env Handling
- **Status:** PASS (with concern)
- `.gitignore` covers `.env` files
- **Concern:** `backend/.env` may already be tracked by Git. Verify with `git ls-files --cached backend/.env`.

### Path Traversal
- **Status:** PASS
- No user-controlled path input reaches file I/O operations.

### Arbitrary File Ingestion
- **Status:** PASS
- Ingestion is CLI-only with hardcoded seed directory.

### CORS Configuration
- **Status:** PASS (for prototype)
- `allow_methods=["*"]` and `allow_headers=["*"]` are permissive but acceptable for prototype.

---

## 12. Production-vs-Evaluation Inconsistencies

### Discrepancy 1: `source_id` Bug in Eval
- **Location:** `eval/run_retrieval_eval.py:62`
- **Issue:** Extracts non-existent `source_id` from RPC (should be `document_id`)
- **Impact:** Source-level evaluation impossible with this data

### Discrepancy 2: Eval Does Not Run Evidence Gate
- **Location:** Eval `main()` vs Production `chat.py:65-68`
- **Issue:** Eval measures raw retrieval recall without gate filtering
- **Impact:** Recall metrics overstate production accuracy

### Discrepancy 3: Gold Cases Have Empty `relevant_chunk_ids`
- **Location:** `eval/gold_cases.yaml`
- **Issue:** All `relevant_chunk_ids` are `[]` (placeholders)
- **Impact:** Eval currently evaluates 0 cases

### Discrepancy 4: Gold Case Source IDs Don't Match MVP Manifest
- **Issue:** Gold cases use `model_pacs_bylaws`, MVP manifest uses `pacs_model_bylaws_2023`
- **Impact:** Retrieval chunks won't match evaluation expectations

---

## 13. Missing Functionality

| Functionality | Status | Required By |
|---------------|--------|-------------|
| PDF extraction (Docling) | **Missing** | MVP ingestion |
| Manifest-driven file discovery | **Missing** | MVP ingestion |
| Frontmatter validation | **Missing** | Ingestion robustness |
| Retry logic for embeddings | **Missing** | Reliability |
| Fallback embedding provider | **Missing** | Reliability |
| Per-file error isolation | **Missing** | Ingestion robustness |
| Transactional ingestion | **Missing** | Data integrity |
| State value normalization | **Missing** | Data integrity |
| Chunk-level page/section metadata | **Missing** | Retrieval quality |
| Gold case source ID alignment | **Missing** | Evaluation |
| `relevant_chunk_ids` population | **Missing** | Evaluation |

---

## 14. Bugs Discovered

| Bug | Severity | Location | Impact |
|-----|----------|----------|--------|
| `source_id` extraction in eval | **High** | `eval/run_retrieval_eval.py:62` | Always returns empty string |
| `grounded_answer()` bypasses citation verification | **Medium** | `chat.py:70-71` | Invalid citations survive in answer text |
| `Pydantic.ValidationError` not in `_SAFE_FAILURES` | **Medium** | `chat.py:33-40` | Schema drift produces 500 |
| `INSUFFICIENT_EVIDENCE` fragile string check | **Low** | `generation.py:58` | May miss LLM variations |

---

## 15. Recommended Minimal Changes

### P0 — Must Fix Before Any Ingestion

1. **Add PDF extraction pipeline** — Wire Docling to parse MVP PDFs into markdown
2. **Add manifest-driven file discovery** — Replace `*.md` glob with manifest-based file loading
3. **Normalize state values** — Lowercase/trim state before DB insert
4. **Add transactional ingestion** — Wrap DELETE → INSERT in transaction
5. **Add `document_date`, `official_domain`, `source_type` to DB schema**

### P1 — Must Fix Before Gate 2

6. **Add retry logic for embeddings** — Exponential backoff for 429/5xx
7. **Add per-file error isolation** — Try/except around each file processing
8. **Add frontmatter validation** — Validate required fields before processing
9. **Fix `grounded_answer()` citation verification** — Route through `generate_answer()` or add verification
10. **Add `Pydantic.ValidationError` to `_SAFE_FAILURES`**
11. **Add structured logging** — Log failures with context
12. **Align gold case source IDs with MVP manifest**

### P2 — Should Fix

13. **Add chunk-level page/section metadata** — Preserve from PDF extraction
14. **Add similarity threshold to `match_chunks` RPC**
15. **Add index on `documents(domain, state)`**
16. **Batch chunk inserts** — Single HTTP round-trip per document

---

## 16. Files That Would Need Modification

| File | Changes Required |
|------|------------------|
| `ingestion/ingestion/ingest.py` | Add PDF discovery, manifest loading, error handling, transactions |
| `ingestion/ingestion/loader.py` | Add frontmatter validation, line ending handling |
| `ingestion/ingestion/chunker.py` | Add chunk-level metadata preservation |
| `backend/migrations/0001_init.sql` | Add `document_date`, `official_domain`, `source_type` columns |
| `backend/app/providers/embeddings.py` | Add retry logic, fallback provider |
| `backend/app/retrieval.py` | Add similarity threshold parameter |
| `backend/app/routes/chat.py` | Fix citation verification, add `Pydantic.ValidationError` to safe failures |
| `backend/app/generation.py` | Fix `INSUFFICIENT_EVIDENCE` check |
| `eval/run_retrieval_eval.py` | Fix `source_id` bug, add evidence gate |
| `eval/gold_cases.yaml` | Align source IDs, populate chunk IDs after ingestion |

---

## 17. Tests That Should Be Added

| Test | Coverage Target |
|------|-----------------|
| PDF extraction integration test | Docling parsing of MVP PDFs |
| Manifest-driven ingestion test | File discovery from manifest |
| Frontmatter validation test | Missing/invalid required fields |
| Embedding retry test | 429/5xx retry with backoff |
| Transactional ingestion test | Mid-failure rollback |
| State normalization test | Casing consistency |
| Citation verification test | Invalid citations in answer text |
| Evidence gate test | Domain/jurisdiction mismatch |
| Eval evidence gate integration | Gated recall measurement |

---

## 18. Dependencies/Blockers

| Dependency | Required By | Status |
|------------|-------------|--------|
| Gemini API key | Embedding generation | **Required** |
| Supabase project | Ingestion + retrieval | **Required** |
| Official PDF documents | MVP ingestion | **Primary blocker** — team must provide |
| Docling library | PDF parsing | **Required** |
| FAISS (optional) | Local eval | Nice-to-have |

---

## Summary

### Critical Findings (P0)

1. **PDF files are never discovered** — Glob pattern `*.md` excludes MVP PDFs
2. **No Docling integration** — No PDF extraction path exists
3. **State value normalization missing** — Casing mismatches cause invisible chunks
4. **No transactional ingestion** — Mid-failure leaves inconsistent state
5. **Missing DB columns** — `document_date`, `official_domain`, `source_type` required by Gate 2
6. **No fallback embedding provider** — Gemini outage = complete failure

### Key Gaps (P1)

1. **Gold case source IDs don't match MVP manifest** — Evaluation will fail
2. **No retry logic for embeddings** — Transient failures cause immediate failure
3. **No per-file error isolation** — One bad file kills entire run
4. **`grounded_answer()` bypasses citation verification** — Invalid citations survive in answer text
5. **Provisional thresholds uncalibrated** — May cause excessive false abstentions

### Assessment

The current codebase is a **seed-corpus prototype** built for hand-authored markdown files. It is **not ready** for the MVP corpus of 5 PDFs. Before Phase 2A ingestion can proceed, the pipeline needs:

1. PDF extraction (Docling)
2. Manifest-driven file discovery
3. Frontmatter validation
4. Transactional ingestion
5. State normalization
6. DB schema additions
7. Gold case source ID alignment

These are all addressable with minimal changes to the existing architecture. No redesign is required.
