# JanSahay — Multilingual Cooperative Governance & Legal Assistance Chatbot

Evidence-grounded, multilingual (English + Hindi + Gujarati + Marathi + Bengali + Tamil + Telugu + Kannada + Punjabi + Odia + Malayalam)
citizen-assistance SPA for cooperative governance, legal guidance, schemes, PMFBY,
financial literacy, and grievance redressal. (Static single-page app — not a PWA:
no manifest, no service worker.)

> **Core principle:** the LLM is **never** the source of truth. Every factual
> answer must be grounded in retrieved official documents with verifiable
> citations. If retrieval confidence is low or no supporting chunk exists, the
> system **abstains** — it never guesses.

---

### 📖 Solution Overview & Pitch

For an in-depth breakdown of the problem, our evidence-backed architecture, and the multilingual voice pipeline powered by Gnani AI, see the [Full Solution Pitch](Project_Solution_Pitch.md).

---

---

## 🔗 Live Deployment & Video Walkthrough

* 🌐 **Live Application:** [gnani-ai-flax.vercel.app](https://gnani-ai-flax.vercel.app/)
* 🎥 **Video Demonstration:** [Watch Demo on Google Drive](https://drive.google.com/file/d/1_OTJN_aDn7Swesk1FLK8iazvSPRbsl4N/view?usp=drivesdk)

---

## What It Does

- Answers questions from official government sources with verifiable citations
- **11 languages**: English, Hindi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Punjabi, Odia, Malayalam
- Routes queries across 7 AnchorStore domains: agriculture, financial_inclusion, grievance, pacs_computerization, pacs_governance, pmfby, schemes (+ `out_of_scope`)
- Applies jurisdiction filtering (central + selected state — currently Gujarat)
- **Hybrid retrieval**: dense vector search (pgvector) + lexical search (RRF fusion)
- Abstains when evidence is insufficient — never guesses
- Prototype grievance workflow with follow-up questions, status lookup, and
  full multilingual localization (system text translated; user values preserved)
  (`is_official_submission: false` — no real government integration)
- Voice input/output via Gnani AI (Prisma v3.0 STT + Timbre v3.0 TTS) primary, Sarvam AI fallback, Azure STT fallback (features strict 16kHz downsampling, zero-gain AEC protection, request serialization, and <2s answer summarization)
- Responsive static SPA (desktop + mobile); browser calls FastAPI directly, no proxy server

---

## Architecture

```
React+Vite SPA ──▶ FastAPI API ──▶ Domain Router (keyword + anchor + LLM)
  (browser attaches        │
   Clerk JWT directly)      ├─▶ Hybrid retrieval (dense pgvector + lexical)
                           │       └─▶ optional reranker (wired, OFF by default)
                           ├─▶ Web discovery (Tavily + SerpApi Google, bounded concurrent branches)
                           ├─▶ Evidence gate (abstention if no citation)
                           ├─▶ Citation verifier
                           ├─▶ Real-time SSE thinking stream (A2UI & AG-UI multi-step trace)
                           └─▶ Grounded LLM (Groq primary, Gemini fallback)
                                        └─▶ Answer / abstain + citations + confidence
                                        ▼
                                   Supabase Postgres + pgvector (HNSW)
```

The evidence gate runs **before** the LLM: the model can never upgrade a
low-confidence or uncited result into an answer.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite 8 + React Router 7 + Tailwind CSS 4 (static SPA, not a PWA) |
| Backend | FastAPI (Python 3.11+) |
| Database | Supabase Postgres + pgvector (HNSW cosine index) |
| Embeddings | Jina Embeddings v3 (`jina-embeddings-v3`), 768d |
| LLM | Groq (primary) + Gemini (fallback); model names come from `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` / `GEMINI_MODEL` env (`config.py` defaults are empty; note `.env.example` still names the retired `llama-3.3-70b-versatile` — do not use it) |
| Reranker | Jina reranker (wired, disabled — `RERANKER_ENABLED=false`) |
| Voice | Gnani AI (Prisma v3.0 STT + Timbre v3.0 TTS) primary, Sarvam AI fallback, Azure STT fallback, text-only final |
| Document parsing | MinerU `content_list_v2.json` |
| Eval | Supabase-backed retrieval eval, pytest |

---

## Project Structure

For dedicated module documentation, see [Backend README](backend/README.md) and [Frontend README](frontend/README.md).

```
backend/
  app/
    main.py                FastAPI entrypoint (8 routers: chat, voice, conversations, evidence, grievance, documents, translate, webhooks)
    routes/
      chat.py              /chat + /chat/stream — language detect → domain classify → RAGOrchestrator or GrievanceWorkflow (live multi-stage SSE steps)
      voice.py             /voice, /voice/transcribe, /voice/speak
      conversations.py     /conversations/{session_id}
      evidence.py          /evidence/...
      grievance.py         /grievance REST endpoint
      documents.py         /documents/... PDF & document serving
      translate.py         /translate batch translation
      webhooks.py          Clerk auth webhooks
    domains.py             AnchorStore domain classifier (keyword rules + cosine similarity)
    evidence_gate.py       abstention thresholds (TOP1=0.25, SECONDARY=0.30, MIN_CHUNKS=2)
    citation_verifier.py   set-membership citation validation
    evidence_controller.py EvidenceBundle builder + curated prompt
    contracts.py           Pydantic models: EvidenceChunk, RAGResult, RAGResponse, etc.
    llm_fallback.py        grounded_answer() with Groq → Gemini fallback
    config.py              all settings and thresholds (pydantic-settings)
    providers/             groq_llm.py, gemini_llm.py, embeddings.py, reranker.py,
                            sarvam_voice.py, azure_voice.py, sarvam_translator.py, translator.py,
                            gnani_voice.py
    services/
      rag_orchestrator.py  async dual-pipeline (static + web), asyncio.gather, merge, generate, verify
      static_rag.py        Supabase pgvector hybrid retrieval (dense + lexical RRF)
      web_rag.py           10-step web RAG: Tavily/SerpApi-Google/Firecrawl → BM25 → Gemini rerank → source verify
      voice_service.py     STT/TTS with provider fallback (Gnani → Sarvam → Azure)
      lang_memory.py       language preference memory
    grievance/             9-stage state machine
      workflow.py          GrievanceWorkflow (main orchestrator + Supabase persistence)
      classifier.py        complaint category classifier
      draft_builder.py     draft construction and update
      entity_extractor.py  entity extraction from user messages
      field_detector.py    missing field detection
      semantic_extractor.py semantic field extraction
      submission_guide.py  portal + submission route lookup
      status_lookup.py     status check guidance
      models.py            GrievanceState, GrievanceDraft, GrievanceTurn, etc.
    retrieval/             bm25_retriever.py, gemini_reranker.py, rrf.py
    web_rag/               service.py (WebDiscoveryService: bounded concurrent branches × provider fan-out, MAX_BRANCHES=8), query_classifier.py,
                           serpapi_client.py (SerpApi Google engine), tavily_client.py, firecrawl_client.py, providers.py (factory),
                           recovery.py (≤2 single-axis recovery rounds + cooperative `deadline`), referrals.py (abstention referrals),
                           mandate_map.py (+.json authority map), validity.py, leads.py, clusters.py, diversity.py,
                           facets.py, identifiers.py, impersonation.py, expansion.py (+.json), lexicon.py (+.json),
                           status.py, retrieval_scorer.py
    security/              source_verifier.py (trust-score filtering)
    data/                  keyword_rules.json, domain_anchors.json
  seed_parser.py           MinerU content_list_v2.json → canonical chunk JSONL
  ingest_seed.py           Jina-v3 embed + insert into Supabase
  schema.sql               Full Supabase schema (documents, chunks, sessions, grievance_states)
  tests/                   pytest test suite (incl. eval_rag_v3.py retrieval eval)

frontend/
  src/
    App.tsx                Router + Clerk provider wiring
    main.tsx               Entry point
    pages/                 HomePage, ChatPage, GrievancePage, SchemesPage, ServicesPage,
                           LibraryPage, FaqPage, LegalPage (+ detail pages)
    components/
      ChatWindow.tsx        Main chat UI (SSE streaming, voice, citations, persistent thinking process)
      FloatingChatWidget.tsx Floating quick-chat modal launcher
      EvidenceBand.tsx      Confidence band indicator component
      chat/                 ThinkingProcess (A2UI/AG-UI animation, live elapsed timer, cycling micro-thoughts), MessageBubble, GrievanceFlow, panels, cards
      layout/               Header, TopNav, Footer
      motion/               Reveal, Stagger
      ui/                   Button, Badge, Icons, etc.
    lib/
      backend.ts            FastAPI base URL + legacy /api/* path mapping + bearer header
      api.ts                Backend API client (via backend.ts)
      i18n/                 11-language i18n provider + dictionaries
      speech.ts             Browser speech recording
  index.html               SPA entry
  vite.config.ts           Dev server (port 5173, strictPort)

corpus/
  seeds/json_files/        MinerU content_list_v2.json per source (ingestion input)

workflows/                  Agent workflow loop docs (ingestion, retrieval, database, etc.)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Supabase project (free tier) with pgvector
- API keys: Supabase, Jina (embeddings), Groq, Gemini, Sarvam AI

### Backend

```bash
cd backend
# backend/.env is the single source of truth for backend config
# (absolute path, never CWD-relative)
pip install -e .
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # fill in VITE_ values
npm run dev            # starts on :5173
```

### Environment Variables

See `.env.example`. Key variables:

```
SUPABASE_URL=             # Supabase project URL
SUPABASE_SERVICE_KEY=     # Supabase service role key
JINA_API_KEY=             # Jina embeddings
GROQ_API_KEY=             # Groq LLM
GEMINI_API_KEY=           # Gemini fallback LLM
SARVAM_API_KEY=           # Sarvam AI voice (STT + TTS) + translation
GNANI_API_KEY=            # Gnani AI voice (Prisma v3.0 STT + Timbre v3.0 TTS) primary provider
TAVILY_API_KEY_1=         # Tavily web search (dynamic RAG; _2 = rotation spare)
SERPAPI_API_KEY_1=        # SerpApi Google web search (_2 = fallback spare)
SEARCH_PROVIDERS=         # e.g. tavily,serpapi (.env.example default: tavily,firecrawl)
WEB_RAG_TIMEOUT_S=        # outer WebRAG budget in seconds (code default 45.0)
RERANKER_ENABLED=false    # reranker is wired but OFF (see PROJECT_STATUS)
CLERK_SECRET_KEY=         # Clerk auth (required for /chat, /voice, grievance-write)
CLERK_ISSUER=             # e.g. https://<instance>.clerk.accounts.dev
```

Backend reads ONLY `backend/.env` (absolute path). A repo-root `.env`, if
present, is ignored with a warning — never split keys across two files.
Frontend keys are `VITE_*` in `frontend/.env` (`VITE_BACKEND_API_URL` is the
backend BASE, e.g. `http://localhost:8000`).

### Database Setup

Apply `backend/schema.sql` to your Supabase project via the SQL editor.

Tables created:
- `documents` — source documents with jurisdiction/state/domain metadata
- `chunks` — content chunks with `embedding vector(768)` + HNSW cosine index
- `sessions` — session state (jsonb)
- `grievance_states` — multi-turn grievance state (full GrievanceState as JSON)

RPC: `match_chunks(query_embedding, match_domain, match_state, match_count,
as_of_date)` per `backend/schema.sql` (live DBs additionally carry a 6-arg
overload with `match_entity_id`; the app always sends all six keys so PostgREST
unambiguously selects the 6-arg overload — a 4-key call fails with PGRST203)

### Ingestion (corpus build)

Place each source's MinerU export at `corpus/seeds/json_files/<source>_content_list_v2.json`,
then:

```bash
python backend/seed_parser.py     # content_list_v2.json → chunks_jsonl/*.jsonl
python backend/ingest_seed.py     # embed (Jina v3) + insert into Supabase
```

Current frozen corpus: **11 documents, 4,778 embedded chunks (768d Jina v3)**.

---

## Supported Languages

| Language | Code | Status |
|---|---|---|
| English | `en` | Full support |
| Hindi | `hi` | Full support |
| Gujarati | `gu` | Full support |
| Marathi | `mr` | Full support |
| Bengali | `bn` | Full support |
| Tamil | `ta` | Full support |
| Telugu | `te` | Full support |
| Kannada | `kn` | Full support |
| Punjabi | `pa` | Full support |
| Odia | `or` | Full support |
| Malayalam | `ml` | Full support |

All UI strings translated. Backend responds in the same language as the question.

---

## RAG Pipelines

### Static RAG (Retrieval-Augmented Generation)
- Hybrid retrieval: dense vector search (pgvector) + lexical search (RRF fusion)
- Domain + jurisdiction filtering before candidate ranking
- Evidence gate with configurable thresholds
- Citation verification against retrieved chunks
- Abstains when evidence insufficient

### Dynamic RAG (Web-Grounded)
- Tavily + SerpApi Google web search for current information (bounded concurrent branches × provider fan-out; SerpApi Search Index evaluated 2026-10-05 and rejected)
- Bounded recovery: ≤2 single-axis rounds (`recovery.py`); cooperative deadline — no new round starts past `started + web_rag_timeout_s` (task cancellation can't stop the worker thread)
- Gemini reranker for semantic scoring
- Answer generation with Groq primary, Gemini fallback (model names from env)
- Full domain coverage: active web discovery across `pmfby`, `pacs_governance`, `pacs_computerization`, `financial_inclusion`, `schemes`, and `agriculture`
- Dual-pipeline source synthesis: multi-facet queries retrieve and surface both official document citations and verified live web sources in the drawer
- Language-matching: responds in same language as question

### Auth + frontend access
- `/chat`, `/chat/stream` (and grievance-write/voice) require a Clerk JWT → `401 {"detail":"Not authenticated"}` without it
- No proxy server: the browser calls FastAPI directly with Clerk's session token (`frontend/src/lib/backend.ts` owns the base URL, legacy `/api/*` path mapping, and bearer header). `VITE_BACKEND_API_URL` is the backend BASE (e.g. `http://localhost:8000`)

---

## Safety

- API keys are server-side only — never in frontend code (only `VITE_*` reaches the browser bundle; `CLERK_SECRET_KEY` stays in the backend).
- Every citation maps to a chunk actually retrieved in that request.
- Low retrieval confidence / no valid citation forces abstention.
- Jurisdiction + effective-date metadata on all legal/cooperative answers.
- Grievances are prototype-only (`is_official_submission: false`) — no real CPGRAMS.
- Structured logs without PII or secrets.

---

## License

Built for a hackathon. See repository for license details.
