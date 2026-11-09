# Provider Setup Runbook

Follow this order to create all provider accounts and populate `backend/.env`
(the backend's only config source; see `.env.example` for the full variable
list and `backend/app/config.py` for code defaults). All keys are server-side
only — never expose them via non-`VITE_` variables or commit them.

## 1. Supabase (Postgres + pgvector)

1. Go to https://supabase.com/dashboard
2. Click **New Project**
3. Project name: `sahayak-dev`
4. Region: nearest to your team
5. Apply `backend/schema.sql` in the SQL editor (creates `documents`,
   `chunks` with `vector(768)` HNSW index, `sessions`, `grievance_states`,
   plus the `match_chunks` RPC)
6. Copy **Project URL** and **service_role key** into `backend/.env`:
   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_KEY=<service_role key>
   ```

## 2. Jina (primary embeddings, 768d)

1. Go to https://jina.ai and create an API key
2. Add to `backend/.env` (second key is an optional rotation spare):
   ```
   JINA_API_KEY=...
   JINA_API_KEY_2=...
   ```
3. Model is `jina-embeddings-v3` (task-typed `retrieval.query` /
   `retrieval.passage`), configured in `config.py`.

## 3. Groq (primary LLM)

1. Go to https://console.groq.com → **API Keys** → create a key
2. Add to `backend/.env` (numbered keys are rotation spares):
   ```
   GROQ_API_KEY=gsk_...
   GROQ_API_KEY_1=...
   GROQ_API_KEY_2=...
   GROQ_MODEL=openai/gpt-oss-120b
   GROQ_FALLBACK_MODEL=qwen/qwen3.8-27b
   ```
3. Do NOT use `llama-3.3-70b-versatile` — it is dead on Groq (HTTP 404).
   (`.env.example` still names it; `config.py` defaults are empty on purpose.)

## 4. Gemini (fallback LLM + WebRAG reranker + grievance model)

1. Go to https://aistudio.google.com → **Get API key**
2. Add to `backend/.env`:
   ```
   GEMINI_API_KEY=...
   GEMINI_MODEL=gemini-2.5-flash
   GRIEVANCE_GEMINI_MODEL=gemini-3.5-flash-lite
   ```
3. Gemini embedding is the embeddings fallback when Jina fails.

## 5. Sarvam AI (primary STT, TTS, translation)

1. Go to https://sarvam.ai, register and obtain an API key
2. Add to `backend/.env` (second key is a rotation spare):
   ```
   SARVAM_API_KEY=...
   SARVAM_API_KEY_2=...
   ```
3. Roles: primary STT → Azure fallback; TTS primary (Azure TTS is
   deliberately excluded — poor Indic output); translation primary
   (Mayura v1) → Azure Translator fallback.

## 6. Gnani AI Vachana (Prisma v3.0 STT + Timbre v3.0 TTS)

Gnani is the **primary** voice provider — tried before Sarvam in both
STT and TTS chains. Supports 10 languages (bn, en, gu, hi, kn, ml,
mr, pa, ta, te — no Odia). Odia automatically falls through to Sarvam/Azure.

1. Contact Gnani AI (https://api.vachana.ai) to obtain an API key ID
2. Add to `backend/.env`:
   ```
   GNANI_API_KEY=...
   GNANI_STT_MODEL=prisma-v3.0
   GNANI_TTS_MODEL=timbre-v3.0
   GNANI_TTS_VOICE=Shivani
   GNANI_STT_TIMEOUT_S=30
   GNANI_TTS_TIMEOUT_S=30
   GNANI_STT_OUTPUT_FORMAT=verbatim
   GNANI_STT_AUTO_DETECT=true
   ```
3. STT endpoint: `POST https://api.vachana.ai/stt/v3` (multipart/form-data,
   `X-API-Key-ID` header, `prisma-v3.0`, `language_code=indic-auto`, 30s max audio)
4. TTS endpoint: `POST https://api.vachana.ai/api/v1/tts/inference` (JSON body,
   returns raw binary WAV audio, `X-API-Key-ID` header)
5. Without `GNANI_API_KEY`, Gnani providers report `enabled=False` and the
   fallback chain (Sarvam → Azure) handles all voice traffic transparently.

## 7. Tavily (primary web search)

1. Go to https://tavily.com, create an API key
2. Add to `backend/.env` (second key races the first concurrently):
   ```
   TAVILY_API_KEY_1=...
   TAVILY_API_KEY_2=...
   ```

## 8. SerpApi Google (live web-search provider)

1. Go to https://serpapi.com, create an API key
2. Add to `backend/.env` (second key is a sequential fallback):
   ```
   SERPAPI_API_KEY_1=...
   SERPAPI_API_KEY_2=...
   SEARCH_PROVIDERS=tavily,serpapi
   ```
3. Only `engine=google` is used. The SerpApi **Search Index** engine was
   evaluated 2026-10-05 and rejected (see DECISIONS.md) — do not enable it.

## 9. Firecrawl (web crawl / scrape fallback)

1. Go to https://firecrawl.dev, create an API key
2. Add to `backend/.env`:
   ```
   FIRECRAWL_API_KEY=...
   ```

## 10. Azure (fallback STT + fallback translation)

1. Create a Speech resource and a Translator resource in the Azure portal
2. Add to `backend/.env`:
   ```
   AZURE_SPEECH_KEY=...
   AZURE_SPEECH_REGION=...
   AZURE_TRANSLATOR_KEY=...
   AZURE_TRANSLATOR_REGION=...
   AZURE_TRANSLATOR_ENDPOINT=...
   ```
3. Azure is fallback-only: STT fallback, translation fallback. Azure TTS
   is not used.

## 11. Clerk (mandatory auth for chat/voice/grievance-write)

1. Go to https://clerk.com, create an application
2. Add to `backend/.env`:
   ```
   CLERK_SECRET_KEY=...
   CLERK_ISSUER=https://<instance>.clerk.accounts.dev
   CLERK_WEBHOOK_SECRET=...   # only if syncing users via /webhooks/clerk
   ```
3. Add to `frontend/.env`:
   ```
   VITE_CLERK_PUBLISHABLE_KEY=...
   ```
   (`CLERK_ISSUER` above must be the same Clerk application.)
4. Without a valid JWT, `/chat`, `/chat/stream` (and grievance-write/voice)
   return `401 {"detail":"Not authenticated"}`. Pre-existing route tests
   that post without a token fail with 401 for this reason.

## 12. Hosting (Render backend, static frontend)

- **Backend (Render):** connect the repo; start command
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (see `render.yaml`).
  Free tier sleeps on inactivity (cold starts expected).
- **Frontend:** pure static bundle (`npm run build` → `dist/`), any static
  host/CDN. The browser calls FastAPI directly (`VITE_BACKEND_API_URL` is
  the backend BASE, e.g. `http://localhost:8000`); no proxy server.

## Key budgets / timeouts (see `backend/app/config.py`)

| Setting | Code default |
|---|---|
| `WEB_RAG_TIMEOUT_S` (outer WebRAG budget, cooperative deadline) | `30.0` |
| WebDiscovery provider timeout | `5s`, `MAX_BRANCHES=8` (frozen) |
| Gemini reranker timeout | `10.0` (clamped ≥10s — google-genai API minimum) |
| `RERANKER_ENABLED` | `false` (keep off — Recall@1 drops 0.85→0.50 when on) |
| Evidence gate | `TOP1_THRESHOLD=0.25`, `SECONDARY_THRESHOLD=0.30`, `MIN_CHUNKS_ABOVE_SECONDARY=2` |

## Smoke Tests

There are no standalone `scripts/smoke_*.py` files. After accounts exist and
`backend/.env` is populated, verify from `backend/`:

```bash
python -m pytest tests/test_health.py tests/test_llm_fallback.py tests/test_embedding_retry.py -q
```

Expected: all pass — provider fallback chains (Groq→Gemini, Jina→Gemini
embeddings) work without live credentials. For a live check, hit
`GET /health/providers` with the backend running.

## Model ID Verification

- **Groq**: `openai/gpt-oss-120b` (primary), `qwen/qwen3.8-27b` (fallback) — verify at https://console.groq.com/docs/models
- **Gemini LLM**: `gemini-2.5-flash` — verify at https://ai.google.dev/gemini-api/docs

If model IDs have changed, use the documented successor and update `backend/.env`
(`config.py` reads model names from the environment; its defaults are empty).
