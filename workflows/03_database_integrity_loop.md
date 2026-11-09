# Workflow: Database Integrity Loop

**Purpose:** Verify that Supabase contains a structurally valid corpus — no orphans, no duplicates, no wrong dimensions, no stale data — after every ingestion run.

**Status:** SPEC SUPERSEDED — implemented differently (see note)

> **Current state (code-grounded):** this loop was never built as specified — there is no `python -m eval.corpus_check` and no `eval/*.json` report writers. The closest code coverage is `backend/tests/test_schema_smoke.py` plus schema-level constraints in `backend/schema.sql`/migrations. `corpus/manifests/mvp_sources.yaml` exists. Treat the body below as the design record, not the implementation.

---

## Trigger

**Event:** Ingestion completion (workflow 1) OR manual invocation

**Schedule:** None — event-driven only. Runs after every ingestion.

**Entry point:** `python -m eval.corpus_check` from project root

---

## Inputs

| Input | Source | Required | Validation |
|-------|--------|----------|------------|
| Supabase credentials | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` env vars | Yes | Must be non-empty |
| MVP manifest | `corpus/manifests/mvp_sources.yaml` | Yes | Must parse as valid YAML |
| Expected domains | Hardcoded in check script | Yes | Must match `backend/data/domain_anchors.json` keys |

---

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Integrity report | stdout + `eval/integrity_report.json` | JSON with pass/fail per check |
| Orphan chunks | `eval/orphan_chunks.json` | JSON list of chunk IDs with no valid document |
| Duplicate report | `eval/duplicates.json` | JSON list of duplicate source_ids or chunk_ids |
| Corpus snapshot | `eval/corpus_snapshot.json` | JSON with hash, counts, model, dimension |

---

## Checks Performed

### Structural Checks

1. **No orphan chunks.** Every `chunks.document_id` references a valid `documents.id`.

2. **No duplicate source_ids.** Each `documents.source_id` is unique.

3. **No duplicate chunk_ids.** Each `chunks.id` is unique.

4. **No null embeddings.** Every `chunks.embedding` is non-null.

5. **Correct embedding dimension.** Every `chunks.embedding` has exactly 768 dimensions.

6. **No empty content.** Every `chunks.content` is non-empty.

7. **No empty titles.** Every `documents.title` is non-empty.

8. **Valid domain values.** Every `documents.domain` is in the approved domain list.

9. **Valid jurisdiction values.** Every `documents.jurisdiction` is either 'central' or 'state'.

10. **State set for state jurisdiction.** If `jurisdiction = 'state'`, `state` must be non-null.

### Consistency Checks

11. **Manifest↔filesystem match.** Every file in the manifest exists on disk.

12. **Manifest↔DB match.** Every manifest `source_id` has a corresponding DB row.

13. **DB↔manifest match.** Every DB `source_id` (with `source_type = 'pdf'` or `'seed'`) appears in the manifest.

14. **Chunks per document reasonable.** No document has 0 chunks. No document has >1000 chunks (sanity check).

15. **Metadata completeness.** Every document has: title, organization, domain, jurisdiction, document_type, source_url.

### Temporal Checks

16. **No future effective_dates.** No document has `effective_date` after today.

17. **verified_date present.** Every document has a non-null `verified_date`.

---

## Invariants

1. **Orphan chunks must not exist.** If any orphan is found, it's a blocking failure.

2. **Wrong-dimension embeddings must not exist.** If any embedding ≠ 768 dims, it's a blocking failure.

3. **DB must match manifest.** If a source_id is in DB but not manifest, it's a warning (may be legacy). If a source_id is in manifest but not DB, it's a failure (ingestion incomplete).

4. **No placeholder content.** If any document title or chunk content contains "TODO", "placeholder", "TBD", or similar, it's a failure.

---

## Failure Behavior

| Failure Point | Behavior | Recovery |
|---------------|----------|----------|
| Supabase unreachable | Abort. Cannot verify what doesn't exist. | Fix connectivity, re-run |
| Orphan chunks found | **BLOCKING FAILURE.** Report chunk IDs. | Run cleanup, re-ingest |
| Wrong embedding dimension | **BLOCKING FAILURE.** Report chunk IDs. | Re-embed affected chunks |
| Duplicate source_id | **BLOCKING FAILURE.** Report source_ids. | Deduplicate, re-run |
| DB↔manifest mismatch | Report mismatched source_ids. | Sync manifest or re-ingest |
| Null embeddings found | **BLOCKING FAILURE.** Report chunk IDs. | Re-embed affected chunks |
| Invalid domain values | Report invalid values. | Fix domain classifier or re-ingest |

---

## Checkpoint

**None.** This workflow runs autonomously. Failures produce reports, not human prompts.

If blocking failure triggered, exit non-zero and log the specific violations.

---

## Brief (Post-Run Summary)

```
DATABASE INTEGRITY CHECK COMPLETE
  Documents: N
  Chunks: N
  Orphans: N (target: 0)
  Duplicates: N (target: 0)
  Null embeddings: N (target: 0)
  Wrong dimension: N (target: 0)
  Invalid domains: N (target: 0)
  Manifest↔DB match: N/N
  Duration: Ns
  Verdict: PASS / FAIL
  
  Blocking failures: [list]
  Warnings: [list]
```

---

## Corpus Snapshot

After successful check, generate a reproducible snapshot:

```json
{
  "corpus_hash": "sha256 of sorted source_ids + chunk counts",
  "document_count": 5,
  "chunk_count": 226,
  "source_ids": ["pacs_model_bylaws_2023", ...],
  "embedding_model": "jina-embeddings-v3",
  "embedding_dimension": 768,
  "ingestion_timestamp": "2026-08-27T18:30:00Z",
  "code_commit": "abc123"
}
```

This snapshot is stored in `eval/corpus_snapshot.json` and used by retrieval evaluation (workflow 2) to verify it's testing against the expected corpus.

---

## CI Integration

**Trigger:** After every successful ingestion run.

**Steps:**
1. Run this integrity check
2. If blocking failure, CI fails — do not proceed to retrieval evaluation
3. If warnings only, CI passes but warnings are logged

**Exit codes:**
- 0: All checks pass
- 1: Blocking failure(s) found
- 2: Supabase unreachable

---

## Acceptance Criteria

- [ ] Zero orphan chunks
- [ ] Zero duplicate source_ids
- [ ] Zero null embeddings
- [ ] Zero wrong-dimension embeddings
- [ ] All documents have valid domain values
- [ ] All documents have valid jurisdiction values
- [ ] DB matches manifest (all manifest source_ids in DB)
- [ ] Corpus snapshot generated
