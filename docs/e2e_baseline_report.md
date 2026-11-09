# E2E Baseline Report

**Date:** 2026-08-27  
**Status:** BASELINE COMPLETE — NO CODE CHANGES MADE

---

## 1. Actual Architecture (Code-Verified)

### Embedding Provider
- **Primary:** Jina Embeddings v3 (`jina-embeddings-v3`) via `https://api.jina.ai/v1/embeddings`
- **Fallback:** Gemini `gemini-embedding-2` (only if `JINA_API_KEY` missing)
- **Dimension:** 768 (hardcoded in `backend/app/config.py:27`)
- **Config location:** `backend/app/providers/embeddings.py:104-112`
- **Discrepancy:** CLAUDE.md states "Gemini API, model `gemini-embedding-2`" — code uses Jina as primary

### PDF Extraction
- **Actual:** `pdfplumber` (NOT Docling)
- **Implementation:** `ingestion/ingestion/pdf_extractor.py`
- **Method:** Page-by-page text extraction with `<!-- Page N -->` markers
- **No OCR, no table extraction, no layout analysis**
- **Discrepancy:** CLAUDE.md and code comments say "Docling" — implementation uses pdfplumber

### MVP Corpus
- **Manifest:** `corpus/manifests/mvp_sources.yaml`
- **5 sources listed, all with `.md` file paths** (pre-extracted markdown, not PDFs)
- **Actual files on disk:** NONE — all 5 MVP files are missing from `corpus/seeds/`
- **PDF extraction path exists** but MVP sources bypass it via pre-existing markdown

---

## 2. Supabase Schema (Migration-Verified)

### Tables
| Table | Key Columns | Notes |
|-------|-------------|-------|
| `documents` | id (uuid PK), source_id (text UNIQUE), title, organization, jurisdiction (CHECK: central/state), state, domain, document_type, source_url, effective_date, document_date, verified_date, document_hash, source_type, created_at | |
| `chunks` | id (uuid PK), document_id (uuid FK→documents ON DELETE CASCADE), page (int), section (text), content (text), embedding (vector(768)), metadata (jsonb), created_at | |
| `sessions` | session_id (uuid PK), state (jsonb), updated_at, expires_at | |
| `grievances` | id (uuid PK), reference (text UNIQUE), status (CHECK), category, location, language, payload (jsonb) | |
| `feedback` | id (uuid PK), session_id, message_id, rating (1-5), note | |

### Indexes
- `chunks_embedding_hnsw` — HNSW on `embedding vector_cosine_ops`
- `chunks_document_idx` — B-tree on `document_id`
- `documents_source_type_idx` — B-tree on `source_type`

### RPC Functions
- `match_chunks(query_embedding, match_domain, match_state, match_count)` — Vector search with domain/jurisdiction filtering, cosine distance ordering, max 20 results
- `atomic_replace_document(p_source_id, p_doc_data, p_chunks_data)` — Delete-then-insert (NOT transactional — mid-insert failure leaves data deleted)
- `purge_expired_sessions()` — Cleanup expired sessions

---

## 3. Ingestion Pipeline (Code-Verified)

### Path A: Seed Ingestion (`seeds_to_supabase`)
For `.md` files with YAML frontmatter in `corpus/seeds/`:
1. Parse YAML frontmatter + markdown body
2. Delete old document by source_id
3. Insert document metadata
4. Chunk markdown body
5. Generate embeddings
6. Insert chunks with embeddings

### Path B: PDF Manifest Ingestion (`manifest_to_supabase`)
For PDF sources in `corpus/manifests/mvp_sources.yaml`:
1. Load manifest YAML
2. Validate all MVP files exist (fails entire run if any missing)
3. Validate required fields (fails entire run if invalid)
4. For each source: extract PDF→markdown→chunk→embed→insert
5. Error isolation: individual PDF failures don't stop others

### Chunker Configuration (`ingestion/ingestion/chunker.py`)
- Split on markdown headings (`# ` through `###### `)
- Target: 600 tokens, Min: 400, Max: 800, Overlap: 80 tokens
- Undersized trailing sections merge into previous chunk
- Long sections split with word-based overlap

---

## 4. Retrieval Pipeline (Code-Verified)

### Request Flow (`backend/app/routes/chat.py`)
1. Language detection (`language.py`)
2. Query embedding via Jina/Gemini
3. Domain classification (`domains.py`):
   - Keyword rules from `backend/data/keyword_rules.json` (exact substring match)
   - Fallback: cosine similarity against domain anchors from `backend/data/domain_anchors.json`
   - Floor: 0.45 (`DOMAIN_FLOOR`)
4. Session state resolution
5. Retrieval via `match_chunks` RPC (k=6)
6. Evidence gate (`retrieval.py`):
   - Abstains if: no chunks, wrong domain, wrong jurisdiction, top1_sim < 0.35, fewer than 2 chunks ≥ 0.30
   - Confidence: `min(0.6 * top1_sim + 0.4 * (strong_count / total_count), 1.0)`
7. Generation via Groq (primary) → Gemini (fallback)
8. Citation verification: parse `[chunk:ID]` markers, validate against actual chunk IDs
9. Response: `{answer, language, domain, confidence, citations[], abstained, follow_up_question}`

### Safe Failure Handling
- `CitationError` → 200 + abstained
- `AllProvidersFailedError` → 200 + abstained
- HTTP errors → 200 + abstained
- PostgREST errors → 200 + abstained

---

## 5. Actual Document/Chunk Counts

| Metric | Value | Source |
|--------|-------|--------|
| MVP documents on disk | 0/5 | Filesystem check |
| Documents in DB | Unknown | Supabase unreachable (DNS failure) |
| Chunks in DB | Unknown | Supabase unreachable |
| Embedding dimension | 768 | Code constant |
| Embedding model | jina-embeddings-v3 | Runtime config |

---

## 6. Test Suite Results

### Backend Tests (`backend/tests/`)
- **Total:** 97 tests
- **Passed:** 95
- **Failed:** 2 (schema smoke tests — DNS failure, not code bugs)
- **Warnings:** 2 (deprecated supabase parameters)

### Ingestion Tests (`ingestion/tests/`)
- **Total:** 42 tests
- **Passed:** 31
- **Failed:** 1 (MVP files missing from disk)
- **Skipped:** 10 (integration tests requiring Supabase)

### Root-Level Tests
- `test_gold_cases_validation.py` — Gold cases YAML integrity
- `test_corpus_check.py` — Corpus validation
- `test_source_recall.py` — Manual evaluation script (not pytest)
- `test_retrieval.py` — Manual retrieval test (not pytest)
- `test_dry_run.py` — Manual dry-run test (not pytest)

---

## 7. Known Failures & Discrepancies

### Critical Discrepancies
1. **Embedding provider mismatch:** Code uses Jina, documentation says Gemini
2. **PDF extraction mismatch:** Code uses pdfplumber, documentation says Docling
3. **MVP corpus missing:** All 5 seed files not on disk
4. **Atomic replacement not transactional:** `atomic_replace_document` deletes before insert

### Test Failures
1. `test_schema_smoke.py` — 2 tests fail due to DNS resolution (Supabase unreachable)
2. `test_pdf_extractor.py::test_mvp_files_exist` — MVP files not on disk

### Environment Issues
- Supabase not reachable from this machine (DNS failure)
- JINA_API_KEY present in `.env` but actual connectivity untested
- No Gemini API key visible in `.env`

---

## 8. Provider Account Status (Actual)

| Provider | .env Key Present | Actual Connectivity |
|----------|------------------|---------------------|
| Jina | JINA_API_KEY=*** | Untested (DNS failure blocks) |
| Gemini | Not visible | Untested |
| Groq | GROQ_API_KEY=*** | Untested |
| Supabase | SUPABASE_URL, SUPABASE_KEY | DNS failure |

---

## 9. Blocking Issues

1. **Supabase unreachable:** DNS resolution fails — cannot verify DB state, run integration tests, or test end-to-end
2. **MVP corpus missing:** No seed documents on disk — cannot test ingestion pipeline
3. **Provider connectivity untested:** Cannot verify embedding/generation providers work

---

## 10. Baseline Conclusion

**The system is partially implemented with significant documentation-code discrepancies.**

- Unit tests pass (95/97 backend, 31/42 ingestion)
- Integration tests cannot run (Supabase unreachable)
- MVP corpus not available for testing
- Atomic replacement function has a latent bug (non-transactional)
- Documentation is outdated in multiple places

**No code changes were made during this baseline inspection.**
