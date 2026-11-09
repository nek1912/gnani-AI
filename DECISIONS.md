# Decisions Log

Tracks deviations from original design or significant architectural choices.
When something is permanently changed, both this log AND the relevant doc are updated.

Each entry: what changed, why, what it replaced, when.

---

## Log

### Embedding model: Jina v3 as primary (not Gemini)
**Date:** 2026-08-26 → finalized  
**What:** `jina-embeddings-v3` (768d, task-typed) is the primary embedding model. Gemini embedding is the fallback. Configured via `embed_model` and `jina_embed_model` in `config.py`.  
**Why:** Jina v3 supports task-type differentiation (`retrieval.query` vs `retrieval.passage`), which improves asymmetric retrieval quality. Gemini embedding is kept as fallback.  
**Current state (from `app/providers/embeddings.py`):** JinaEmbeddingProvider primary, GeminiEmbeddingProvider fallback.

---

### Gemini embedding model: `gemini-embedding-2` (config default, overridable)
**Date:** 2026-08-26  
**What:** Config default is `gemini-embedding-2`. This is only used as fallback when Jina fails.  
**Note:** Earlier debates about `gemini-embedding-001` vs `gemini-embedding-2` are moot — Jina is primary. Gemini embedding is fallback only.

---

### Dropped NyayaSetu-Offline-Multilingual-AI as dependency
**Date:** 2026-08-26  
**What:** Grievance workflow is custom-built in `backend/app/grievance/`.  
**Why:** Could not verify the referenced repo (no stars, forks, or evidence of existence). Built from scratch with full control.

---

### Single Supabase instance for vectors + relational data
**Date:** 2026-08-26  
**What:** Supabase Postgres + pgvector for both chunk embeddings and grievance state.  
**Why:** One free-tier service vs two (separate Qdrant + Postgres). Simplifies ops.  
**Schema:** `documents`, `chunks` (vector 768d, HNSW cosine), `sessions`, `grievance_states`.

---

### Sarvam AI as primary voice + translation provider
**Date:** 2026-09-02  
**What:** `SarvamSTTProvider`, `SarvamTTSProvider`, `SarvamTranslator` are primary. Azure is fallback for STT only. Azure TTS is deliberately excluded.  
**Why:** Sarvam handles Indic languages (Hindi, Gujarati, Marathi, Bengali, Tamil) far better than Azure TTS. Azure TTS reads Indian languages as English gibberish.  
**Current state:** `VoiceService` in `app/services/voice_service.py`:
  - STT: Sarvam → Azure → `VoiceUnavailableError`
  - TTS: Sarvam only → `VoiceUnavailableError`

---

### Evidence gate thresholds
**Date:** 2026-09-02  
**What:** `TOP1_THRESHOLD=0.25`, `SECONDARY_THRESHOLD=0.30`, `MIN_CHUNKS_ABOVE_SECONDARY=2` in `config.py`.  
**Why:** Tests established these as the appropriate thresholds. Lower values were too permissive.

---

### Reranker wired but disabled
**Date:** 2026-09-02  
**What:** `RERANKER_ENABLED=false` in config. Jina reranker is wired in `StaticRAGService._apply_reranker()` but not called by default.  
**Why:** Enabling the reranker drops Recall@1 from 0.85 → 0.50 and Recall@5 from 0.975 → 0.875 on the current gold set. Do not enable without a new eval showing improvement.

---

### Out-of-scope queries abstain (not answered with disclaimer)
**Date:** 2026-09-02  
**What:** When `AnchorStore` classifies a query as `out_of_scope`, the system returns `abstained=True` with a scope message and no factual content.  
**Why:** The previous behavior generated a general answer with a disclaimer, which violated the core principle that the LLM is never the source of truth. Out-of-scope → abstain, not guess.  
**Current code:** `chat.py` lines ~286–300.

---

### Tamil added to ChatRequest.language
**Date:** 2026-09-02  
**What:** `language: Literal["en", "hi", "gu", "mr", "bn", "ta"]` — Tamil added.  
**Why:** Frontend i18n had Tamil (TA) but backend schema didn't, causing 422 errors.

---

### Dual-pipeline RAG: static + web run in parallel
**Date:** 2026-09-03 (finalized in RAGOrchestrator)  
**What:** `asyncio.gather` runs `StaticRAGService.retrieve` and `WebRAGService.retrieve` concurrently. Results merged into one `EvidenceBundle`.  
**Why:** Reduces latency; both sources inform the answer when available. Mode is `dual_rag`, `static`, or `web` based on which pipelines returned evidence.

---

### Auto-append citations when LLM omits them
**Date:** 2026-09-02  
**What:** `RAGOrchestrator._auto_append_citations()` appends `[chunk:XXXXXXXX]` markers from the top 3 chunks if the LLM output contains no citation markers at all.  
**Why:** Even with explicit citation instructions, some LLM calls omit markers. Fallback ensures the citation verifier has something to check. If truly no evidence, the gate would have abstained before reaching generation.

---

### GrievanceWorkflow persists state in Supabase
**Date:** 2026-09-03  
**What:** `grievance_states` table in Supabase. Full `GrievanceState` serialized to JSON, upserted on `conversation_id`.  
**Why:** Multi-turn grievance workflow requires server-side state across HTTP requests. Session ID / conversation ID is the key.

---

### Streaming endpoint uses word-level token emission
**Date:** 2026-09-04  
**What:** `/chat/stream` splits the final answer by spaces and emits each word as a `token` SSE event.  
**Why:** Groq does not support true streaming in the current integration. Word-level pseudo-streaming gives a streaming feel without needing true token streaming from the LLM provider.

---

### TTS uses `speech_text` not `answer`
**Date:** 2026-09-04  
**What:** Voice route passes `rag_result.get("speech_text")` to TTS, never the raw `answer`.  
**Why:** The raw answer contains `[chunk:id]` citation markers. `speech_text` is the citation-stripped version produced post-verification. TTS of citation markers is nonsense audio.

---

### Bounded evidence/context layers
**Date:** 2026-09-05
**What:** EvidenceController caps the generation prompt to top 3 static + top 3 dynamic chunks (3000 chars each). ContextBuilder defaults to max 8 chunks total. Web RAG caps at 12 chunks per source. These are independent layers — retrieval returns more, but each downstream stage further bounds what it processes.
**Why:** Intentional engineering control to bound context size and generation latency/cost while retaining sufficient evidence for grounded answers. Transplanted from eGovAssistant proven defaults.

---

### Bounded generation output
**Date:** 2026-09-05
**What:** `GENERATION_MAX_TOKENS = 1800` for normal generation, `REPAIR_MAX_TOKENS = 2200` for citation repair. These values are sent to Groq as `max_tokens` in the API request.
**Why:** Intentional engineering control to bound generation output size and latency/cost. Value transplanted from eGovAssistant proven defaults.

---

### Grievance localization: output-boundary translation, not LLM translation
**Date:** 2026-09-10
**What:** All grievance workflow processing happens in English only. Translation is applied at the output boundary in `_process_grievance_message()` and `/grievances/*` endpoints. User-entered values are preserved verbatim; only system-generated metadata (submission data, field labels, draft summary values, canonical dict top-level) is translated via the provider chain. Field labels use a static `FIELD_LABELS` lookup dict (150+ entries) rather than LLM translation.
**Why:** LLM translation of user values risks hallucination or content drift. Static lookup for field labels avoids latency and cost of per-request LLM calls. Output-boundary translation ensures English-only internal state while delivering fully localized responses.
**Current state:** `chat.py` and `grievance.py` both apply translation before returning responses. Frontend uses `field_label` from backend for tab rendering.

---

### Session isolation via useRef in ChatWindow
**Date:** 2026-10-10
**What:** `sessionId` in `ChatWindow.tsx` changed from `useState` to `useRef` + `resetSessionId()`. Reset on new-chat, load-conversation, delete-conversation, clear-all-history, and URL query param handlers.
**Why:** `useState` created `sessionId` once and never reset it, causing grievance state to leak across "New Chat" actions. Backend fresh-state defense in `GrievanceWorkflow.process_message()` complements this by detecting new complaints after completed grievances.

---

### SerpApi Search Index rejected for the hackathon (decision A)
**Date:** 2026-10-05
**What:** `engine=search_index` was tested live with the existing SerpApi key against post-Sarvam canonical queries (15-scenario matrix + corrected multilingual re-audit). Not integrated; `providers.py` factory and `_search_all()` fan-out unchanged.
**Why:** Endpoint works (HTTP 200, structured `organic_results`), but no full-pipeline rescue demonstrated (static-insufficient + Tavily/Google-weak + Index-authoritative + gate-accepted never co-occurred); ignores `site:`/`OR` operators the query builder relies on; substantial wrong-jurisdiction government noise; ~2× SerpApi call cost. Do not revisit before the hackathon.

---

### Final WebDiscovery hardening H1+H2+H3/H4 (then freeze)
**Date:** 2026-10-05
**What:** `mandate_map.py:37` agriculture subjects += `crop_relief`, `crop_insurance` (H1, data-only) · `query_classifier.py` ≥2-distinct-explicit-states + society-context gate → `mscs`/central (H2) + `mscs`,`crcs`→cooperative keywords (H3) + `pmjjby`,`pmsby`→schemes keywords (H4; `apy` skipped — substring of "therapy"). Readiness U-AG-1 now Gujarat-GR-top-1, U-MS-1 now CRCS-top.
**Why:** Last two known wrong-top answers from the final readiness audit; minutes-scale data-only fixes with measured zero fallout (comparison questions, Gujarat-only and explicit-MSCS paths verified unchanged).

---

### WebDiscovery concurrency frozen
**Date:** 2026-10-05
**What:** `_search_branches()` × `_search_all()` `ThreadPoolExecutor` fan-out, `MAX_BRANCHES=8`, per-provider timeout 5s, `web_rag_timeout_s=30.0`, provider/branch failure isolation — verified by audit + timing probes (branch scaling flat: 1/4/8 branches ≈ same wall-clock) and locked by tests (`test_web_discovery_providers.py`, `test_facets_p0.py` concurrency lock-ins).
**Why:** Adequate bounded parallelism already exists. No asyncio in WebDiscovery, no new/wider executors, no new providers, no reranker change without new evidence.

---

### Cooperative deadline for WebRAG recovery (timeout lifecycle fix)
**Date:** 2026-10-06
**What:** `WebRAGService.retrieve()` accepts an optional absolute `deadline` (`time.monotonic()`). The initial attempt always runs; no NEW recovery round starts once the deadline passes (`metadata["deadline_stopped_recovery"]` stamped). `RAGOrchestrator` passes `started + web_rag_timeout_s` on both web-only and dual paths. Locked by `backend/tests/test_web_rag_deadline.py` (8 tests).
**Why:** `asyncio.wait_for` + `task.cancel()` does not stop the `asyncio.to_thread` worker — recovery kept running past the timeout, computed a strong result, and had it discarded while the caller already fell back (live-demo phantom success). Proven with a minimal event-loop reproduction before fixing.
**What it replaced:** Nothing — previously the outer budget was incommunicable (`retrieve()` took no deadline kwarg). Count bound (`MAX_RECOVERY_ROUNDS=2`), thresholds, RRF/BM25/verifier/branches unchanged; timeout still enforced; timed-out WebRAG still falls back safely.

---

### Clerk authentication mandatory on chat/voice/grievance-write endpoints
**Date:** 2026-10-06 (code state; enforced in `app/auth.py` + route `Depends(require_auth)`)
**What:** `POST /chat`, `POST /chat/stream` (and grievance-write + voice routes) return `401 {"detail":"Not authenticated"}` without a valid Clerk JWT. The browser attaches Clerk's session token directly (`src/lib/backend.ts`); there is no proxy server since the 2026-10-05 React+Vite migration. Pre-existing route tests that post without a token fail with 401 — unrelated to retrieval.
**Why:** Demo requires signed-in users; backend never serves RAG without an authenticated `user_id`.

---

### `VITE_BACKEND_API_URL` is the backend base URL (direct-access convention)
**Date:** 2026-10-06 (updated post React+Vite migration)
**What:** `VITE_BACKEND_API_URL=http://localhost:8000` (no `/chat` suffix). The browser calls FastAPI directly; `src/lib/backend.ts` maps legacy `/api/*` paths (`/api/chat`→`/chat`, `/api/chat/stream`→`/chat/stream`, etc.) and attaches the bearer token. No proxy server, no second port. (Supersedes the Next.js `/api` proxy convention.)
**Why:** The 2026-10-05 migration removed the Next.js BFF; the browser holds only Clerk's session token and `CLERK_SECRET_KEY` never leaves the backend.

---

### `backend/.env` is the only backend config source
**Date:** 2026-10-06
**What:** `app/config.py::_env_file()` returns the absolute path of `backend/.env`. A repo-root `.env`, if present, is ignored with a `RuntimeWarning`. Neither file is git-tracked (only `.env.example` files are).
**Why:** CWD-relative `env_file=".env"` silently picked up different files depending on launch directory; then the repo-root preference silently shadowed the fully-populated `backend/.env`, leaving Tavily/SerpApi/Sarvam keys unevaluated. Absolute-path single source + loud warning on the ignored file.
**What it replaced:** Repo-root preference with stale-`backend/.env` warning (2026-10-05 migration era).

---

### Gemini reranker deadline floor 10s
**Date:** 2026-10-06
**What:** `gemini_reranker_timeout_s` default `8.0` → `10.0`, plus `max(GEMINI_MIN_DEADLINE_S=10.0, configured)` clamp in `GeminiReranker.__init__`. Jina fallback, timeout protection, and rerank logic unchanged.
**Why:** google-genai rejects manually-set deadlines below 10s with `400 INVALID_ARGUMENT`, so every rerank attempt failed before falling back. Live-verified: Gemini pre-rank succeeds in ~2s after the fix.

---

### Full web citation IDs (no 8-char truncation for `web_*`)
**Date:** 2026-10-06
**What:** `short_citation_id()` keeps `web_{hex}_c{N}` IDs whole in prompts, auto-appended markers, and response citations; the verifier matches full web IDs (static UUIDs keep the 8-char prefix; the >1-match ambiguity rule is unchanged). Truncated web prefixes stay invalid and are repaired to full IDs.
**Why:** Same-URL web chunks share the 12-hex stem, so every truncated marker was ambiguous → legitimate web answers always abstained (live MSCS case). Live-verified post-fix: MSCS answer passes HIGH 1.0 with 23 valid citations.

---

### `rag-fix` merged to `main` + backend freeze
**Date:** 2026-10-06
**What:** `rag-fix` (static 6-key RPC + as_of_date threading, grounding enforcement, PACS prompt fix, insurance-keyword fix, citation URL allowlist + marker normalization + full web IDs, Gemini 10s floor) merged into `main` (merge commit `403b9de`). Two same-hunk conflicts (`retrieval/__init__.py`, `services/static_rag.py`) resolved toward `rag-fix` (functional superset of `main`'s independent same fix); `main`'s `_env_file()`/Firecrawl/provider changes kept. Full suite 1434 passed / 83 pre-existing baseline failures; ruff clean; live smoke A–J passed.
**Why:** Freeze the validated backend before the hackathon demo. Accepted residual risks: external provider variance, no INSURANCE grievance category, Sarvam EN→GU code-mixing.
