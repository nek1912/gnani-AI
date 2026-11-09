# Project: Multilingual Cooperative Governance & Legal Assistance Chatbot

You are assisting on an evidence-grounded, multilingual citizen-assistance PWA.

**Before doing anything else in a new session: read `PROJECT_STATUS.md`.** It
tells you what's actually built and what the current state is. This file
(CLAUDE.md) tells you the rules and stack that don't change.

---

## Non-negotiable principles

- The LLM is NEVER the source of truth. Every factual answer must be grounded in
  retrieved official documents with verifiable citations.
- If retrieval confidence is low or no supporting chunk exists, set `abstained: true`.
  Do not guess. Do not let the LLM override this in code.
- Never fabricate eligibility, amounts, dates, deadlines, legal clauses, or contacts.
- Grievances are PROTOTYPE references only. Always `is_official_submission: false`.
  Never claim real government registration or a real CPGRAMS integration.
- Central and state law can differ. Always attach jurisdiction + effective-date
  metadata. Never present a national/model rule as universally applicable across states.
- Every citation must map to a chunk ID that was actually retrieved in that request.
  Invalid citation → ABSTAIN.

---

## Stack (do not change without a logged decision — see DECISIONS.md)

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React 19 + Vite 8 + React Router 7 + Tailwind CSS 4 | Static SPA in `frontend/`. **Not a PWA** — no manifest, no service worker |
| Frontend API access | Direct browser → FastAPI | The browser attaches Clerk's session token. `src/lib/backend.ts` owns the URL mapping. Never reintroduce a proxy holding `CLERK_SECRET_KEY` — it is not needed and adds a port to deploy |
| Backend | FastAPI (Python ≥3.11) on Render Free | `uvicorn app.main:app` |
| DB + vectors | Supabase Postgres + pgvector (HNSW cosine) | 768d embeddings |
| Embeddings | Jina Embeddings v3 (primary) | 768d, task-typed |
| Embeddings fallback | Gemini embedding | 768d fallback |
| LLM primary | Groq (key rotation supported) | `groq_model` in config |
| LLM fallback | Gemini | `gemini_model` in config |
| Voice STT | Sarvam AI (primary) → Azure Speech (fallback) | |
| Voice TTS | Sarvam AI only | Azure excluded (bad Indic output) |
| Translation | Sarvam Mayura v1 (primary) → Azure Translator (fallback) | |
| Web search | Tavily (primary) / SerpApi Google / Firecrawl | for WebRAGService |
| Document parsing | MinerU `content_list_v2.json` | seed_parser.py |
| Reranker | Jina reranker (wired, disabled) | `RERANKER_ENABLED=false`; Gemini reranker deadline clamped ≥10s (API minimum) |

---

## API contracts (current — match `backend/app/routes/`)

```
/chat + /chat/stream require a Clerk JWT (401 without it); the browser
attaches Clerk's session token as `Authorization: Bearer <token>` directly —
there is no proxy server. `VITE_BACKEND_API_URL` is the backend BASE
(no `/chat` suffix); `src/lib/backend.ts` owns the legacy `/api/*` mapping.

POST /chat
POST /chat/stream                 ← SSE streaming version
POST /voice                       ← full audio→STT→RAG→TTS pipeline
POST /voice/transcribe            ← STT only
POST /voice/speak                 ← TTS only
POST /grievance                   ← grievance REST endpoint
POST /grievances/finalize         ← finalize grievance (returns submission guide + translated data)
POST /grievances/fields           ← get grievance field schema for a stage
POST /grievances/clarify          ← answer clarification question
POST /grievances/answer           ← answer a specific field
GET  /conversations/{session_id}
GET  /evidence/{...}
GET  /health
GET  /health/providers
```

The frontend calls FastAPI **directly** from the browser and attaches Clerk's
own session token as `Authorization: Bearer`. There is no proxy server and no
second port. `src/lib/backend.ts` owns the base URL, the legacy `/api/*` →
FastAPI path mapping, and the bearer header; `App.tsx` registers Clerk's
`useAuth().getToken` there once at mount.

Because requests are cross-origin, `ALLOWED_ORIGINS` in `backend/.env`
(the backend's single source of truth) must list the frontend's origin.
`CLERK_ISSUER` there must match the frontend's Clerk instance — if they
diverge, every authenticated call 401s.

Chat request: `{ question, session_id, language, ui_language_explicit?, state?, as_of_date?, history?, mode? }`  
Language values: `"en" | "hi" | "gu" | "mr" | "bn" | "ta" | "te" | "kn" | "pa" | "or" | "ml"`

Chat response: `{ answer, language, domain, intent, entities, confidence, confidence_level, citations, abstained, speech_text, speech_segments, follow_up_question, mode, conversation_id }`

SSE events: `thinking | token | metadata | done`

---

## Coding conventions

- Python: type hints everywhere, Pydantic models for all request/response bodies,
  no bare `except`.
- Every external provider call goes through an adapter with explicit timeout and
  fallback handling — never call a provider SDK directly from route handlers.
- Never put API keys in frontend code or commit them. Only `VITE_`-prefixed vars reach the browser bundle; `CLERK_SECRET_KEY` is read only by the backend.
  Backend environment variables only. `CLERK_SECRET_KEY` and `CLERK_ISSUER` stay in `backend/.env` (the only backend source of truth); a repo-root `.env`, if present, is ignored with a warning.
- Structured logs. Never log API keys, auth tokens, or full grievance PII.
- Write tests for: domain routing, jurisdiction filtering, retrieval, citation
  validity, abstention, grievance workflow, provider fallback.

---

## What's implemented (summary — see PROJECT_STATUS.md for full detail)

- ✅ `/chat` and `/chat/stream` — full dual-pipeline RAG (static + web in parallel)
- ✅ `/voice` — Sarvam STT → chat handler → Sarvam TTS
- ✅ `/voice/transcribe` and `/voice/speak` — standalone STT/TTS endpoints
- ✅ GrievanceWorkflow — 9-stage state machine, Supabase-persisted
- ✅ Domain classification — AnchorStore (keyword + cosine, floor 0.20)
- ✅ StaticRAGService — Supabase pgvector hybrid retrieval (dense + lexical RRF)
- ✅ WebRAGService — 10-step pipeline (Tavily/SerpApi-Google/Firecrawl → BM25 → Gemini rerank → verify) + ≤2 single-axis recovery rounds with cooperative deadline (no new round past `started + web_rag_timeout_s`)
- ✅ Evidence gate, citation verifier, abstention
- ✅ 11-language frontend (EN, HI, GU, MR, BN, TA, TE, KN, PA, OR, ML) with chat, grievance, schemes, library pages. Coverage is incomplete: 791 of 3,740 strings untranslated (`npm run i18n:coverage`); missing keys fall back to English
- ✅ Document ingestion: 11 docs, 4778 chunks (pacs_governance, pacs_computerization, pmfby, financial_inclusion)
- ✅ Grievance localization — `FIELD_PROMPTS` (30 prompts), `SUBMISSION_STEPS`, `FOLLOWUP_PREFIX`, `WORKFLOW_PREFIX` maps in `translations.py`; `translate_field_prompt()` for field questions; frontend field card labels via `dictionaries.ts` i18n lookup

---

## When unsure

- Prefer code over comments — read the actual file before assuming what it does.
- Push back on scope creep, citing this file.
- State assumptions explicitly rather than silently picking one.
- Never invent APIs, repositories, or free-tier limits you haven't verified.
- At the end of every working session, update `PROJECT_STATUS.md` before stopping.
