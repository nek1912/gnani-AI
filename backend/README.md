# JanSahay Backend — FastAPI & RAG Engine

Multilingual, evidence-grounded citizen-assistance backend for cooperative governance in India.
It powers JanSahay's RAG pipelines (PACS bylaws, cooperative societies law, PMFBY crop insurance, financial inclusion),
voice interaction, and interactive grievance redressal workflows.

> **Core Principle:** The LLM never hallucinates or guesses facts from internal weights.
> Every factual statement is strictly grounded in retrieved document chunks. If evidence
> is insufficient or citations fail verification, the system safely **abstains**.

---

## Architecture & Pipeline Flow

```
User Request (with Clerk JWT)
  │
  ├── 1. Language Detection & Normalization (app/language.py) — 11 Indic languages + English
  ├── 2. Domain Classification (app/domains.py) — AnchorStore: 7 domains + out_of_scope
  ├── 3. Translation to English (app/providers/sarvam_translator.py / translator.py)
  │
  ├─▶ [grievance domain] ────────► GrievanceWorkflow.process_message()
  │                                9-stage state machine, Supabase persistence
  │
  ├─▶ [out_of_scope] ────────────► Scope boundary message, abstained=True
  │
  └─▶ [all other domains] ───────► RAGOrchestrator.run()
                                    ├── StaticRAGService (Supabase pgvector hybrid dense + lexical RRF)
                                    ├── WebRAGService (Tavily/SerpApi-Google/Firecrawl multi-branch)
                                    ├── EvidenceController (merge & curated prompt builder)
                                    ├── Grounded LLM generation (Groq primary → Gemini fallback)
                                    ├── CitationVerifier (strict set-membership verification)
                                    ├── Real-time Step Queue (emits multi-stage SSE progress)
                                    └── RAGResponse (answer + citations + confidence)
  │
  └── 4. Language conversion to user language & speech synthesis (Gnani AI STT/TTS)
      5. Paced typewriter token emission over Server-Sent Events (SSE)
```

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI application entrypoint & router registrations
│   ├── auth.py                    # Clerk JWT JWKS token authentication
│   ├── config.py                  # Pydantic settings & environment configuration
│   ├── contracts.py               # Core typed contracts (EvidenceChunk, RAGResult, RAGResponse, etc.)
│   ├── domains.py                 # AnchorStore domain classifier (keyword rules + cosine similarity)
│   ├── evidence_gate.py           # Evidence gate thresholds (TOP1_THRESHOLD=0.25, MIN_CHUNKS=2)
│   ├── citation_verifier.py       # Strict set-membership citation validator & prefix normalizer
│   ├── answer_grounding.py        # Post-generation grounding & claim verification
│   ├── evidence_controller.py     # Multi-source evidence merger & prompt synthesis
│   ├── llm_fallback.py            # Primary Groq → Gemini fallback execution wrapper
│   ├── language.py                # Multi-script Indic language detection & normalization
│   ├── speech_text.py             # Speech text normalization & audio segmentation
│   ├── session_store.py           # Supabase session history persistence & thread isolation
│   ├── routes/                    # API endpoints
│   │   ├── chat.py                # POST /chat and POST /chat/stream (SSE streaming)
│   │   ├── voice.py               # POST /voice, /voice/transcribe, /voice/speak
│   │   ├── conversations.py       # GET /conversations/{session_id}
│   │   ├── evidence.py            # GET /evidence/{chunk_id} provenance lookup
│   │   ├── grievance.py           # REST grievance operations
│   │   ├── documents.py           # Source PDF & document serving
│   │   ├── translate.py           # Fast batch translation endpoints
│   │   └── webhooks.py            # Clerk auth webhooks
│   ├── services/
│   │   ├── rag_orchestrator.py    # Async dual-pipeline orchestrator with live SSE step queue
│   │   ├── static_rag.py          # Supabase hybrid retrieval (dense pgvector + lexical RRF)
│   │   ├── web_rag.py             # 10-step Web RAG service with cooperative deadlines
│   │   ├── voice_service.py       # Multi-provider voice (Gnani AI → Sarvam AI → Azure Speech)
│   │   └── lang_memory.py         # Session language preference memory
│   ├── providers/                 # External service provider integrations
│   │   ├── gnani_voice.py         # Gnani AI Prisma v3.0 STT & Timbre v3.0 TTS
│   │   ├── sarvam_voice.py        # Sarvam AI STT & TTS
│   │   ├── azure_voice.py         # Azure Cognitive Speech STT fallback
│   │   ├── groq_llm.py            # Groq high-speed LLM provider (primary)
│   │   ├── gemini_llm.py          # Google Gemini provider (fallback & grievance)
│   │   ├── embeddings.py          # Jina Embeddings v3 (`jina-embeddings-v3`, 768d)
│   │   ├── reranker.py            # Jina reranker client (disabled by default)
│   │   ├── sarvam_translator.py   # Sarvam translation provider
│   │   └── translator.py          # Azure / fallback translation provider
│   ├── grievance/                 # 9-stage interactive grievance redressal state machine
│   │   ├── workflow.py            # GrievanceWorkflow main controller & Supabase persistence
│   │   ├── classifier.py          # Grievance category & department classifier
│   │   ├── draft_builder.py       # Formal grievance draft generator & summary builder
│   │   ├── entity_extractor.py    # Rule-based entity & detail extraction
│   │   ├── semantic_extractor.py  # LLM-assisted semantic missing field extractor
│   │   ├── submission_guide.py    # Official portal & submission route resolver
│   │   ├── status_lookup.py       # Application status tracking guidance
│   │   └── models.py              # Grievance state, draft, and field schema definitions
│   ├── web_rag/                   # Multi-source web discovery subsystem
│   │   ├── service.py             # WebDiscoveryService (bounded concurrent branches, MAX_BRANCHES=8)
│   │   ├── tavily_client.py       # Tavily search API client
│   │   ├── serpapi_client.py      # SerpApi Google search engine client
│   │   ├── firecrawl_client.py    # Firecrawl web scrape & crawl client
│   │   ├── recovery.py            # ≤2 single-axis recovery rounds with cooperative deadline
│   │   └── mandate_map.py         # Government authority & jurisdictional domain mapping
│   ├── retrieval/                 # Classical & fused retrieval components
│   │   ├── bm25_retriever.py      # BM25 in-memory lexical retrieval
│   │   ├── gemini_reranker.py     # Gemini cross-encoder semantic reranker
│   │   └── rrf.py                 # Reciprocal Rank Fusion implementation
│   ├── security/
│   │   └── source_verifier.py     # Domain authority & trust-score filtering
│   └── data/                      # Rules & taxonomy data
│       ├── keyword_rules.json     # Fast deterministic keyword classification rules
│       ├── domain_anchors.json    # Cosine centroid anchors for domain routing
│       └── DOMAIN_TAXONOMY.md     # Governance domain definitions
├── seed_parser.py                 # MinerU content_list_v2.json → canonical chunk JSONL
├── ingest_seed.py                 # Jina-v3 embedding generation & Supabase database ingestion
├── schema.sql                     # Complete Supabase Postgres schema (tables, HNSW index, match RPCs)
├── pyproject.toml                 # Package definition & dependencies
└── tests/                         # Pytest test suite (chat routes, orchestrator, grounding, eval)
```

---

## Environment Configuration

Backend configuration is loaded **exclusively** from `backend/.env` (absolute path).
Never split environment variables across multiple files.

Key environment variables:

```bash
# Core LLM Providers
GROQ_API_KEY=               # Primary LLM provider
GEMINI_API_KEY=             # Fallback LLM provider & grievance model
GROQ_MODEL=                 # Groq model identifier
GEMINI_MODEL=               # Gemini fallback model identifier

# Database & Embeddings
SUPABASE_URL=               # Supabase project URL
SUPABASE_SERVICE_KEY=       # Supabase service role key (for pgvector RPCs)
JINA_API_KEY=               # Jina Embeddings v3 API key (768 dimensions)

# Voice Services (STT / TTS)
GNANI_API_KEY=              # Gnani AI (Prisma v3.0 STT + Timbre v3.0 TTS) primary
SARVAM_API_KEY=             # Sarvam AI STT, TTS & Translation
AZURE_SPEECH_KEY=           # Azure Cognitive Speech (optional STT fallback)
AZURE_SPEECH_REGION=        # Azure speech region (e.g. centralindia)

# Web RAG Search Providers
TAVILY_API_KEY_1=           # Tavily web search key
SERPAPI_API_KEY_1=          # SerpApi Google search key
SEARCH_PROVIDERS=tavily     # Comma-separated search providers (tavily, serpapi)
WEB_RAG_TIMEOUT_S=45.0      # Web RAG deadline budget in seconds

# Authentication
CLERK_SECRET_KEY=           # Clerk backend secret key
CLERK_ISSUER=               # Clerk issuer URL (https://<instance>.clerk.accounts.dev)
```

---

## Local Setup & Development

### 1. Install Dependencies

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

FastAPI OpenAPI documentation is available at `http://localhost:8000/docs`.

---

## Database Setup & Corpus Ingestion

1. Run `backend/schema.sql` in your Supabase SQL editor to create:
   - `documents` — Document provenance and metadata.
   - `chunks` — Chunk text and `embedding vector(768)` with HNSW cosine index.
   - `sessions` — User conversation state.
   - `grievance_states` — Multi-turn grievance workflow persistence.
   - `match_chunks` RPC — 6-argument hybrid search function.

2. Ingest official seed documents:
```bash
python seed_parser.py
python ingest_seed.py
```

---

## Running Tests

Run the test suite using `pytest`:

```bash
# Run all chat route and orchestrator tests:
python -m pytest tests/test_chat_route_refactored.py tests/test_services_rag_orchestrator.py

# Run routing hierarchy tests:
python -m pytest tests/test_routing_hierarchy.py tests/test_multilingual_routing.py

# Run answer grounding tests:
python -m pytest tests/test_answer_grounding.py
```

---

## API Endpoints

| Endpoint | Method | Auth Required | Description |
|---|---|---|---|
| `/chat` | `POST` | Yes (Clerk) | Synchronous RAG query endpoint |
| `/chat/stream` | `POST` | Yes (Clerk) | Server-Sent Events (SSE) streaming (`step`, `thinking`, `token`, `metadata`, `done`) |
| `/voice` | `POST` | Yes (Clerk) | Multipart voice input (STT → RAG → TTS audio output) |
| `/voice/transcribe` | `POST` | No | Base64 audio transcription |
| `/voice/speak` | `POST` | No | Text-to-speech audio synthesis |
| `/conversations/{session_id}` | `GET` | Yes (Clerk) | Retrieve conversation history |
| `/evidence/{chunk_id}` | `GET` | No | Retrieve citation chunk provenance |
| `/grievance` | `POST` | Yes (Clerk) | Direct grievance state machine progression |
| `/documents/pdf/{filename}` | `GET` | No | Serve official source document PDFs |
| `/health` | `GET` | No | Service health check |

