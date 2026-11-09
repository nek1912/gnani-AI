# MVP-First RAG Plan

**Date:** 2026-08-28
**Goal:** Working demo that proves the RAG pipeline end-to-end

---

## What Actually Exists (verified)

| Component | Status | Evidence |
|-----------|--------|----------|
| Dense retrieval | WORKING | chat.py line 76: `retrieve_hybrid()` |
| Hybrid retrieval | PARTIAL | Dense works, lexical is naive |
| Evidence gate v1 | WORKING | chat.py line 82: `evidence_gate()` |
| Evidence gate v2 | DEAD CODE | Imported (line 19) but never called |
| Citation verifier | WORKING | chat.py line 93: `verify_citations_v2()` |
| Reranker | DEAD CODE | File exists, never imported |
| Jina embeddings | WORKING | 226 chunks at 768d |
| Frontend | WORKING | localhost only |
| Voice | STUB | Hardcoded strings |

---

## MVP Scope (what we're building)

### 1. Wire evidence_gate_v2 (5 min)
- File: `backend/app/routes/chat.py`
- Change: Line 82: `evidence_gate(...)` → `evidence_gate_v2(...)`
- Why: v2 has typed abstention reasons, defense-in-depth

### 2. Wire reranker (15 min)
- File: `backend/app/routes/chat.py`
- Add: Import reranker, call after retrieval
- Feature flag: `RERANKER_ENABLED` env var

### 3. Apply migration 0005 (5 min)
- Command: `supabase db push`
- Why: Adds tables for embedding profiles, corpus versions

### 4. Add Jina task-type differentiation (15 min)
- File: `backend/app/providers/embeddings.py`
- Add: `task` parameter to embed_texts()
- Values: `retrieval.query` for queries, `retrieval.passage` for documents

### 5. Voice: Azure primary, Sarvam fallback (2-3 hours)
- Files to create:
  - `backend/app/providers/azure_voice.py`
  - `backend/app/providers/sarvam_voice.py`
  - `backend/app/routes/voice.py`
- Endpoints: `/voice/transcribe`, `/voice/speak`
- Fallback chain: Azure → Sarvam → text-only

### 6. Confidence calibration (30 min)
- File: `backend/app/evidence_gate.py`
- Replace: Heuristic `0.6 * top1 + 0.4 * (strong / total)`
- With: Simple threshold-based bands (high/medium/low)

### 7. Run ingestion on existing MD files (30 min)
- Use: `corpus/seeds/*.md` from manifest
- Verify: Chunk count increases from 226

---

## What We're NOT Doing (MVP)

- ❌ HTML scraping
- ❌ Corpus expansion beyond existing MD files
- ❌ PWA manifest/service worker
- ❌ Security hardening (rate limiting, etc.)
- ❌ Observability (structured logging, tracing)
- ❌ Deployment to Render/Vercel
- ❌ Gold cases expansion
- ❌ Hindi evaluation dataset

---

## Execution Order

| Step | Task | Time | Prerequisite |
|------|------|------|--------------|
| 1 | Wire evidence_gate_v2 | 5 min | None |
| 2 | Wire reranker | 15 min | Step 1 |
| 3 | Apply migration 0005 | 5 min | Step 2 |
| 4 | Add Jina task-type | 15 min | Step 3 |
| 5 | Azure/Sarvam voice | 2-3 hrs | Step 4 |
| 6 | Confidence calibration | 30 min | Step 5 |
| 7 | Run ingestion | 30 min | Step 6 |

**Total estimated time: 4-5 hours**

---

## Environment Variables Needed

```env
# Azure (primary voice)
AZURE_SPEECH_KEY=your_key
AZURE_SPEECH_REGION=centralindia

# Sarvam (fallback voice)
SARVAM_API_KEY=your_key

# Existing (already set)
JINA_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

---

## Success Criteria (MVP)

1. ✅ PMFBY question → answer with citations
2. ✅ Hindi question → answer in Hindi
3. ✅ Voice question → text → answer → voice response
4. ✅ Out-of-scope question → abstention
5. ✅ All 183 tests pass (no regressions)
