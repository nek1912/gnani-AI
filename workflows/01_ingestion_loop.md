# Workflow: Ingestion Loop

**Purpose:** Deterministically transform official source documents into queryable vector embeddings in Supabase, with full rollback safety and no invalid data entering the database.

**Status:** SPEC SUPERSEDED — implemented differently (see note)

> **Current state (code-grounded):** this loop was never built as specified — there is no `run_ingestion.py`, no `ingestion/` package, and no `ingestion/tests/`. Actual ingestion is `backend/seed_parser.py` (MinerU `content_list_v2.json` → `corpus/seeds/chunks_jsonl/*.jsonl`) + `backend/ingest_seed.py` (embed + insert into Supabase). `corpus/manifests/mvp_sources.yaml` exists, and `atomic_replace_document()` exists in the migrations. Treat the body below as the design record, not the implementation.

---

## Trigger

**Event:** Seed file changes (`corpus/seeds/chunks_jsonl/*.jsonl`) OR source PDF changes (`corpus/seeds/*.pdf`)

**Schedule:** None — event-driven only. Ingestion runs when corpus changes, not on a timer.

**Entry point:** `python run_ingestion.py` from project root

---

## Inputs

| Input | Source | Required | Validation |
|-------|--------|----------|------------|
| Seed JSONL files | `corpus/seeds/chunks_jsonl/*.jsonl` | Yes | Must be valid JSONL with content, metadata fields |
| Seed/MD files | `corpus/seeds/*.md` | No | Pre-extracted markdown (legacy) |
| PDF files | `corpus/seeds/*.pdf` | Yes | Source PDFs for ingestion |
| Embedding provider | `JINA_API_KEY` env var | Yes | Must be non-empty |
| Supabase credentials | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` env vars | Yes | Must be non-empty |
| Chunker config | Hardcoded in `ingestion/chunker.py` | Yes | Target 600 tokens, min 400, max 800, overlap 80 |

---

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Ingested documents | Supabase `documents` table | Row per source_id |
| Ingested chunks | Supabase `chunks` table | Row per chunk, with `vector(768)` embedding |
| Ingestion log | `ingestion_output.log` / `ingestion_error.log` | Structured text |
| Dry-run report | stdout | JSON summary of what would be done |

---

## Pipeline Stages

```
manifest loaded
    ↓
all MVP files validated (fail-fast if any missing)
    ↓
all manifest fields validated (fail-fast if any invalid)
    ↓
for each source:
    ↓
    extract PDF→markdown (pdfplumber)
    ↓
    validate extraction (min 50 chars, valid UTF-8)
    ↓
    chunk markdown (heading-based, 600-token target)
    ↓
    validate chunks (no empty, no duplicate, metadata attached)
    ↓
    generate embeddings (Jina v3, 768-dim)
    ↓
    validate embeddings (correct dimension, no nulls)
    ↓
    atomic replace in Supabase (delete old → insert new + chunks)
    ↓
    verify insertion (document exists, chunks exist, embedding dim correct)
    ↓
next source
    ↓
summary report
```

---

## Invariants

1. **No invalid embedding enters Supabase.** If embedding dimension ≠ 768 or embedding is null, reject before DB insertion.

2. **Failed source does not affect other sources.** Source A failing must not prevent Source B from ingesting. The loop continues with isolated failures.

3. **Failed ingestion does not destroy previous valid data.** If embedding or DB insertion fails, the old document + chunks must remain intact.

4. **Idempotency.** Running ingestion twice with the same manifest produces the same logical corpus state. No duplicate documents, no duplicate chunks.

5. **Every chunk retains provenance.** Each chunk must have: `document_id` (FK), `page` (int), `section` (text), `content` (text), `embedding` (vector(768)), `metadata` (jsonb).

6. **Source_id uniqueness.** Two documents with the same `source_id` cannot coexist. The second ingestion replaces the first.

7. **No orphan chunks.** Every chunk must reference a valid `document_id`.

---

## Failure Behavior

| Failure Point | Behavior | Recovery |
|---------------|----------|----------|
| Manifest YAML invalid | Abort entire run. No processing. | Fix manifest, re-run |
| MVP file missing | Abort entire run. No processing. | Add file, re-run |
| Manifest field invalid | Abort entire run for that source. Others may proceed if isolated. | Fix field, re-run |
| PDF extraction fails | Skip source. Log error. Old DB record preserved. | Fix PDF, re-run |
| Extraction too short (<50 chars) | Skip source. Log warning. Old DB record preserved. | Check PDF content, re-run |
| Chunking produces 0 chunks | Skip source. Log error. Old DB record preserved. | Check extraction output |
| Embedding provider timeout | Retry 3x with exponential backoff. If all retries fail, skip source. | Re-run when provider available |
| Embedding provider 429 | Retry with backoff. If exhaustion, skip source. | Re-run after rate limit resets |
| Embedding wrong dimension | Reject. Do not insert. Skip source. | Check provider config |
| DB delete fails | Abort for this source. Old record preserved. | Check Supabase connectivity |
| DB insert fails | Abort for this source. Old record preserved (delete already happened — THIS IS THE ATOMICITY BUG). | Fix DB, re-run |
| DB insert chunk fails mid-batch | Partial insertion possible. Orphan chunks may exist. | Run DB integrity loop |

---

## Atomicity Fix (Required Before Production)

**Current bug:** `atomic_replace_document` SQL function deletes before inserting. If a mid-insert fails, the delete is not rolled back.

**Why BEGIN/COMMIT inside the function is wrong:** PostgreSQL functions already execute within a transaction context. The function invocation itself is atomic — if it raises an exception, the entire invocation rolls back. Explicit `BEGIN`/`COMMIT` inside a function body is not valid transaction-control logic for normal functions.

**Fix:** The function body is already correct in structure (delete → insert). The fix is:
1. Remove any internal exception handling that swallows errors and continues
2. Let exceptions propagate naturally — PostgreSQL rolls back the entire function invocation
3. The Python caller catches the exception and handles it (skip source, preserve old data)

```sql
CREATE OR REPLACE FUNCTION atomic_replace_document(
    p_source_id TEXT,
    p_doc_data JSONB,
    p_chunks_data JSONB
) RETURNS UUID AS $$
DECLARE
    v_doc_id UUID;
    v_chunk JSONB;
BEGIN
    -- Validate inputs (raise exception if invalid → rolls back entire invocation)
    IF p_source_id IS NULL THEN
        RAISE EXCEPTION 'source_id cannot be null';
    END IF;
    IF p_doc_data IS NULL THEN
        RAISE EXCEPTION 'doc_data cannot be null';
    END IF;
    IF p_chunks_data IS NULL OR jsonb_array_length(p_chunks_data) = 0 THEN
        RAISE EXCEPTION 'chunks_data must be non-empty array';
    END IF;

    -- Delete old document (cascades to chunks via FK)
    DELETE FROM chunks WHERE document_id = (
        SELECT id FROM documents WHERE source_id = p_source_id
    );
    DELETE FROM documents WHERE source_id = p_source_id;

    -- Insert new document
    INSERT INTO documents (source_id, title, organization, domain, jurisdiction, state,
                           document_type, source_url, effective_date, document_date,
                           verified_date, source_type)
    VALUES (
        p_source_id,
        p_doc_data->>'title',
        p_doc_data->>'organization',
        p_doc_data->>'domain',
        p_doc_data->>'jurisdiction',
        p_doc_data->>'state',
        p_doc_data->>'document_type',
        p_doc_data->>'source_url',
        (p_doc_data->>'effective_date')::DATE,
        (p_doc_data->>'document_date')::DATE,
        COALESCE((p_doc_data->>'verified_date')::DATE, CURRENT_DATE),
        COALESCE(p_doc_data->>'source_type', 'seed')
    ) RETURNING id INTO v_doc_id;

    -- Insert chunks
    FOR v_chunk IN SELECT * FROM jsonb_array_elements(p_chunks_data)
    LOOP
        INSERT INTO chunks (document_id, page, section, content, embedding)
        VALUES (
            v_doc_id,
            COALESCE((v_chunk->>'page')::INTEGER, 0),
            COALESCE(v_chunk->>'section', ''),
            v_chunk->>'content',
            -- Supabase pgvector handles JSONB→vector conversion
            (v_chunk->>'embedding')::VECTOR(768)
        );
    END LOOP;

    RETURN v_doc_id;
END;
$$ LANGUAGE plpgsql;
```

**Key insight:** No `BEGIN`/`COMMIT` in the function body. If ANY statement fails (DELETE, INSERT, type cast), PostgreSQL raises an exception and rolls back the entire function invocation — including the earlier DELETE. The old data is preserved automatically.

**Also:** Wire Python ingestion code to use this RPC function instead of manual delete-then-insert.

---

## Checkpoint

**None.** This workflow runs autonomously. No human-in-the-loop.

If the entire run fails (manifest invalid, all sources fail), log the failure and exit non-zero. The next run after fixing the issue will retry everything.

---

## Brief (Post-Run Summary)

After each run, output:

```
INGESTION COMPLETE
  Sources processed: N/11
  Succeeded: N
  Failed: N (list source_ids)
  Total chunks: N
  Embedding dimension: 768
  Duration: Ns
  Status: PASS / FAIL
```

If any source failed, list:
- Source ID
- Failure reason
- Whether old DB record was preserved

---

## CI Integration

**Trigger:** Push to `main` that modifies `corpus/manifests/mvp_sources.yaml` or `corpus/seeds/*.md`

**Steps:**
1. Run `python run_ingestion.py --dry-run` — verify manifest validity and file existence
2. Run `pytest ingestion/tests/test_manifest.py -v` — verify manifest invariants
3. Run `pytest ingestion/tests/test_chunker.py -v` — verify chunking logic
4. Run `pytest ingestion/tests/test_pdf_extractor.py -v` — verify extraction (requires files on disk)
5. If dry-run passes, run full ingestion against staging Supabase
6. Run DB integrity loop (workflow 3) to verify results

**Exit codes:**
- 0: All sources ingested successfully
- 1: One or more sources failed (check logs)

---

## Acceptance Criteria

- [ ] All 11 sources ingested without error
- [ ] No duplicate documents in `documents` table
- [ ] No orphan chunks in `chunks` table
- [ ] All embeddings are 768-dimensional
- [ ] Running ingestion twice produces same logical state
- [ ] Failed source does not affect other sources
- [ ] Atomicity fix applied and verified
- [ ] Test bug in `test_mvp_files_exist` fixed
