# AI Agent / Session Instructions

> **Read this before writing any code.** The codebase source files are the
> ground truth. This file describes the system's design decisions and guardrails
> that must be respected.

---

## What this system is

A multilingual, evidence-grounded citizen-assistance chatbot for cooperative
governance in India. It answers questions about PACS governance, PMFBY crop
insurance, financial inclusion, and helps users file grievances with government
departments.

**The LLM never generates factual claims from its own knowledge.**
Every answer is grounded in retrieved document chunks. If no relevant chunk is
found, the system abstains rather than guessing.

---

## How the system works (summary)

```
User message
  │
  ├── Language detection (app/language.py)        en/hi/gu/mr/bn/ta/te/kn/pa/or/ml
  ├── Domain classification (app/domains.py)       AnchorStore: keyword + cosine
  ├── Translation to English (if needed)           Sarvam → Azure fallback
  │
  ├─[grievance domain]──► GrievanceWorkflow.process_message()
  │                        9-stage state machine, Supabase-persisted
  │
  ├─[out_of_scope]────────► Return scope message, abstained=True
  │
  └─[all other domains]──► RAGOrchestrator.run()
                            ├── StaticRAGService  (Supabase pgvector)
                            ├── WebRAGService     (Tavily/SerpApi-Google/Firecrawl 10-step)
                            ├── EvidenceController (merge + prompt build)
                            ├── LLM generation    (Groq → Gemini fallback)
                            ├── citation_verifier  (invalid → ABSTAIN)
                            └── RAGResponse
  │
  └── Translate back to user language (if needed)
      Save to session history
      Return structured JSON response
```

---

## Key files

| What | Where |
|---|---|
| App entry point + route registration | `backend/app/main.py` |
| Chat endpoint (sync + SSE stream) | `backend/app/routes/chat.py` |
| Voice endpoint | `backend/app/routes/voice.py` |
| Domain classifier (AnchorStore) | `backend/app/domains.py` |
| Config + all env vars | `backend/app/config.py` |
| RAG orchestrator | `backend/app/services/rag_orchestrator.py` |
| Static RAG (Supabase pgvector hybrid) | `backend/app/services/static_rag.py` |
| Web RAG (10-step Tavily/SerpApi-Google/Firecrawl) | `backend/app/services/web_rag.py` |
| WebDiscovery recovery + referrals | `backend/app/web_rag/recovery.py`, `referrals.py`, `mandate_map.py`, `validity.py`, `leads.py`, `clusters.py`, `diversity.py`, `facets.py`, `identifiers.py`, `impersonation.py`, `expansion.py`, `lexicon.py`, `status.py` |
| Clerk auth (mandatory on chat/voice/grievance-write) | `backend/app/auth.py` |
| Evidence controller + prompt builder | `backend/app/evidence_controller.py` |
| Evidence gate (abstention thresholds) | `backend/app/evidence_gate.py` |
| Citation verifier (full `web_*` IDs kept whole; truncated 8-char web prefixes stay ambiguous → invalid) | `backend/app/citation_verifier.py` |
| Gemini reranker + Jina fallback (deadline clamped ≥10s, API minimum) | `backend/app/retrieval/gemini_reranker.py` |
| Grievance workflow | `backend/app/grievance/workflow.py` |
| Voice service (STT/TTS fallback) | `backend/app/services/voice_service.py` |
| LLM providers | `backend/app/providers/groq_llm.py`, `gemini_llm.py` |
| Embedding providers | `backend/app/providers/embeddings.py` |
| Translation providers | `backend/app/providers/sarvam_translator.py`, `translator.py` |
| Contracts (typed models) | `backend/app/contracts.py` |
| Session store | `backend/app/session_store.py` |
| Database schema | `backend/schema.sql` |
| Frontend (React 19 + Vite 8 SPA, not a PWA) | `frontend/` |
| Main chat UI | `frontend/src/components/ChatWindow.tsx` |
| i18n (11 languages) | `frontend/src/lib/i18n/` |
| Document ingestion | `backend/seed_parser.py`, `backend/ingest_seed.py` |

---

## Guardrails (enforced in code, not just prompts)

1. **Evidence gate before LLM**: If no chunk exceeds `TOP1_THRESHOLD=0.25`,
   the system abstains without calling the LLM at all.
2. **Citation verification**: Every `[chunk:id]` in the LLM output must map to
   a chunk that was actually retrieved in this request. If not → ABSTAIN.
3. **No hallucination fallback**: `AllProvidersFailedError` → ABSTAIN, never a
   guessed answer.
4. **Out-of-scope = scope message**: Never answer out-of-scope with a guessed
   factual answer.
5. **Grievance responses**: Always `is_official_submission: false`. The system
   guides to official portals, never claims to submit.
6. **Reranker off by default**: `RERANKER_ENABLED=false`. Enabling it drops
   Recall@1 from 0.85 to 0.50 on current eval set. Do not enable without new
   evidence.
7. **WebDiscovery concurrency is frozen**: `_search_branches()` × `_search_all()`
   `ThreadPoolExecutor` fan-out, `MAX_BRANCHES=8`, provider timeout 5s,
   `web_rag_timeout_s=30.0`. No asyncio inside WebDiscovery, no new executors,
   no wider pools.
8. **SerpApi Search Index is rejected** (decision A, 2026-10-05): evaluated
   against post-Sarvam canonical queries, no full-pipeline rescue demonstrated.
   Do not integrate it or any new search provider without explicit instruction.
9. **Cooperative WebRAG deadline** (2026-10-06): `WebRAGService.retrieve()`
   takes an optional absolute `deadline`; no NEW recovery round starts past it.
   The orchestrator passes `started + web_rag_timeout_s` on both web paths.
   Cancelling the asyncio task does NOT stop the `to_thread` worker — never
   rely on cancellation to bound WebRAG work. Count bound (`MAX_RECOVERY_ROUNDS=2`),
   thresholds, RRF/BM25/verifier/branches stay untouched.

---

## API contract (backend endpoints)

```
POST /chat   (requires Clerk JWT → 401 {"detail":"Not authenticated"} without it)
  Body: { question, session_id, language, ui_language_explicit?, state?, as_of_date?, history?, mode? }
  language: "en" | "hi" | "gu" | "mr" | "bn" | "ta" | "te" | "kn" | "pa" | "or" | "ml"
  Response: { answer, language, domain, intent, entities, confidence,
              confidence_level, citations, abstained, speech_text,
              speech_segments, follow_up_question, mode, conversation_id }

POST /chat/stream
  Same body as /chat
  SSE events: thinking | token | metadata | done

POST /voice          (multipart: audio file, language, session_id, state)
POST /voice/transcribe (JSON: { audio: base64, language })
POST /voice/speak    (JSON: { text, language, segments? })

GET  /conversations/{session_id}
GET  /evidence/{...}
POST /grievance
GET  /health
GET  /health/providers
```

---

## Domain taxonomy

```
pacs_governance       PACS byelaws, cooperative societies law
pacs_computerization  PACS computerization scheme
pmfby                 Pradhan Mantri Fasal Bima Yojana (crop insurance)
financial_inclusion   National Strategy for Financial Inclusion 2025-30
schemes               Government schemes (no corpus ingested yet)
agriculture           Agriculture domain (no corpus ingested yet)
grievance             Routed to GrievanceWorkflow, never to RAG
out_of_scope          Returns scope message, abstained=True
```

---

## Environment variables (see `backend/app/config.py` for all)

Required:
- `GROQ_API_KEY` — primary LLM
- `GEMINI_API_KEY` — fallback LLM, Gemini reranker, grievance model
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — database
- `JINA_API_KEY` — primary embeddings

Optional (voice):
- `SARVAM_API_KEY`, `SARVAM_API_KEY_2` — STT, TTS, translation
- `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` — fallback STT

Optional (web RAG):
- `TAVILY_API_KEY_1`, `TAVILY_API_KEY_2` — web search
- `SERPAPI_API_KEY_1`, `SERPAPI_API_KEY_2` — SerpApi Google web search
- `SEARCH_PROVIDERS` — e.g. `tavily,serpapi` (code default: `tavily`)
- `FIRECRAWL_API_KEY` — web crawl
- `WEB_RAG_TIMEOUT_S` — outer WebRAG budget, seconds (code default: `45.0`)

Auth (required for chat/voice/grievance-write):
- `CLERK_SECRET_KEY`, `CLERK_ISSUER` — backend JWT verification
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` — frontend sign-in

Frontend proxy convention:
- `BACKEND_API_URL` is the backend BASE (e.g. `http://localhost:8000`, no `/chat`
  suffix). Restart `npm run dev` after changing `.env.local`.

Optional (translation):
- `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION`, `AZURE_TRANSLATOR_ENDPOINT`

---

## Running locally

```bash
# Backend
cd backend
pip install -e .
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
cp .env.example .env   # fill in VITE_ values
npm run dev   # starts on :5173
```

Backend reads ONLY `backend/.env` (absolute path); a repo-root `.env`, if
present, is ignored with a warning — never split keys across two files.

---

## Deployment

- **Backend**: Render (`render.yaml`, backend only) — `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Frontend**: pure static bundle (`npm run build` → `dist/`), any static host/CDN
- **Database**: Supabase (schema in `backend/schema.sql`)
