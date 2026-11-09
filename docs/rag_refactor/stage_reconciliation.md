# RAG Refactor Stage Reconciliation

**Date:** 2026-08-28
**Git commit:** 861bae959e8d6ab74e6cac5165e9a745210894e2
**Test results:** 173 passed, 0 failed, 2 deselected (integration)

## Stage 0: Baseline

| Field | Value |
|-------|-------|
| **Intended** | Reproduce frozen snapshot, save baseline artifact |
| **Implemented** | `artifacts/rag/baseline.json` |
| **Migration** | N/A |
| **Tests** | Retrieval eval script run |
| **Evidence** | `eval/retrieval_report.json` |
| **Status** | COMPLETE |
| **Blockers** | None |
| **Acceptance** | Baseline recorded with correct metrics |

**Note:** The "8732d dimension mismatch" in the original baseline.json was a false claim. The real issue was provider mismatch (Gemini stored, Jina queried). Corrected in baseline.json.

## Stage 1: Immutable Contracts

| Field | Value |
|-------|-------|
| **Intended** | Typed Pydantic models for all pipeline stages |
| **Implemented** | `backend/app/contracts.py` (12 models) |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_contracts.py` (27 pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE |
| **Blockers** | None |
| **Acceptance** | All 27 contract tests pass |

## Stage 2: Additive Database Migrations

| Field | Value |
|-------|-------|
| **Intended** | Additive schema for embedding_profiles, corpus_versions, etc. |
| **Implemented** | `backend/migrations/0005_rag_contracts.sql` |
| **Migration** | 0005 (additive only, no destructive changes) |
| **Tests** | `backend/tests/test_migration_0005.py` (11 pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE (not applied to live DB yet) |
| **Blockers** | Requires manual `supabase db push` to apply |
| **Acceptance** | SQL syntax valid, contract columns present |

## Stage 3: Refactor Ingestion Pipeline

| Field | Value |
|-------|-------|
| **Intended** | Checksum/idempotent, staging, atomic activation |
| **Implemented** | `ingestion/ingestion/pipeline.py`, `checksums.py`, `extraction_quality.py` |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_pipeline_components.py` (14 pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE (not wired to live ingestion yet) |
| **Blockers** | Needs integration with run_ingestion.py |
| **Acceptance** | All 14 pipeline component tests pass |

## Stage 4: Shadow Embedding Indexes

| Field | Value |
|-------|-------|
| **Intended** | Build shadow index, compare, activate atomically |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | Requires evaluation comparison infrastructure |
| **Acceptance** | Shadow index built, compared, activated |

## Stage 5: Fix Hybrid Retrieval

| Field | Value |
|-------|-------|
| **Intended** | Dense + lexical with deterministic RRF fusion |
| **Implemented** | `backend/app/hybrid_retrieval.py` (122 lines) |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_rag_refactor.py` (5 retrieval tests pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE (integrated into chat route) |
| **Blockers** | Eval script still uses old retrieve() function |
| **Acceptance** | RRF fusion deterministic, tie-breaking verified |

## Stage 6: Keep Reranking Optional

| Field | Value |
|-------|-------|
| **Intended** | Reranker optional, feature-flagged, bounded |
| **Implemented** | `backend/app/providers/reranker.py` exists (120 lines) |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | PARTIAL (code exists, not integrated) |
| **Blockers** | Not wired into chat route |
| **Acceptance** | Reranker optional, falls back to RRF |

## Stage 7: Implement Evidence Gate

| Field | Value |
|-------|-------|
| **Intended** | Typed abstention reasons, calibrated confidence |
| **Implemented** | `backend/app/evidence_gate.py` (90 lines) |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_rag_refactor.py` (8 gate tests pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE (integrated into chat route) |
| **Blockers** | None |
| **Acceptance** | All 8 evidence gate tests pass |

## Stage 8: Make Citation Verification Unavoidable

| Field | Value |
|-------|-------|
| **Intended** | Every answer passes through verifier |
| **Implemented** | `backend/app/citation_verifier.py` (170 lines) |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_rag_refactor.py` (13 citation tests pass) |
| **Evidence** | Test output |
| **Status** | COMPLETE (integrated into chat route) |
| **Blockers** | Route-coverage test needed |
| **Acceptance** | All 13 citation tests pass |

## Stage 9: Calibrate Confidence

| Field | Value |
|-------|-------|
| **Intended** | high/medium/low bands, outcome-calibrated |
| **Implemented** | `backend/app/evidence_gate.py:compute_confidence_band()` |
| **Migration** | N/A |
| **Tests** | `backend/tests/test_rag_refactor.py` (2 confidence tests pass) |
| **Evidence** | Test output |
| **Status** | PARTIAL (heuristic bands, not calibrated) |
| **Blockers** | Needs held-out evaluation data for calibration |
| **Acceptance** | Bands calibrated on dev set, evaluated on test set |

## Stage 10: Enforce Multilingual and Voice Parity

| Field | Value |
|-------|-------|
| **Intended** | Shared RAG path for text and voice |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | Bhashini adapter is stubbed |
| **Acceptance** | Text and voice use same pipeline |

## Stage 11: Version Caches

| Field | Value |
|-------|-------|
| **Intended** | Versioned cache keys |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | None |
| **Acceptance** | Cache keys include all version components |

## Stage 12: Security and Observability

| Field | Value |
|-------|-------|
| **Intended** | PII-minimized traces, security tests |
| **Implemented** | `eval/security_check.py` exists |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | PARTIAL (basic security scan exists) |
| **Blockers** | Needs comprehensive security test suite |
| **Acceptance** | All security tests pass |

## Stage 13: Shadow and Canary Release

| Field | Value |
|-------|-------|
| **Intended** | Shadow mode, canary, rollback |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | Needs deployment infrastructure |
| **Acceptance** | Shadow comparison, canary rollout, rollback tested |

## Stage 14: Legacy Deletion

| Field | Value |
|-------|-------|
| **Intended** | Remove legacy code after observation |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | Needs stages 0-13 complete |
| **Acceptance** | Legacy removed, no consumers remain |

## Stage 15: Release Gates

| Field | Value |
|-------|-------|
| **Intended** | Mandatory GO conditions |
| **Implemented** | NOT IMPLEMENTED |
| **Migration** | N/A |
| **Tests** | N/A |
| **Evidence** | N/A |
| **Status** | NOT STARTED |
| **Blockers** | Needs all prior stages complete |
| **Acceptance** | All gates pass |

## Summary

| Status | Stages |
|--------|--------|
| **COMPLETE** | 0, 1, 2, 3, 5, 7, 8 |
| **PARTIAL** | 4, 6, 9, 12 |
| **NOT STARTED** | 10, 11, 13, 14, 15 |

**Overall: PARTIAL** — Core pipeline (retrieval, evidence gate, citations) is implemented and tested. Missing: shadow indexes, reranker integration, confidence calibration, multilingual/voice, caching, security, deployment.
