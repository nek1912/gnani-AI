# System Architecture

> Source of truth: the actual code. This document reflects what is currently implemented.

## 1. Overview

Evidence-grounded, multilingual citizen-assistance platform for cooperative governance, PMFBY crop insurance, financial inclusion, and grievance filing in India.

**Core principle:** The LLM is NOT the source of truth. It only synthesizes retrieved evidence into an answer. Every citation must map to a chunk actually retrieved in that request. Invalid citation → abstain.

---

## 2. High-level diagram

```
                        USER
                          |
                          v
              +---------------------------+
              |  React 19 + Vite 8 SPA    |
              |  (static bundle, no PWA:  |
              |   no manifest/SW)         |
              |  / /chat /grievance       |
              |  /schemes /services       |
              |  /library /faq /legal     |
              |  /sign-in /sign-up        |
              +------------+--------------+
              (browser → FastAPI direct,
               Clerk Bearer, no proxy)
                          |
                        HTTPS
                          |
                          v
             +---------------------------+
             |  FastAPI (app/main.py)    |
             |  /chat  /chat/stream      |
             |  /voice /voice/transcribe |
             |  /voice/speak             |
             |  /conversations           |
             |  /evidence  /grievance    |
             |  /health /health/providers|
              +------+------+------+------+
                     |      |      |
           +---------+      |      +----------+
           v                v                 v
 +-----------------+ +----------+  +------------------+
 | Language Layer  | | Domain   |  | Grievance        |
 | detect_query_   | | AnchorSt.|  | Workflow         |
 | languages()     | | keyword  |  | 9-stage state    |
 | Sarvam transl.  | | + cosine |  | machine          |
 | Azure fallback  | | classify |  | (Supabase-backed)|
 +-----------------+ +----------+  +--------+---------+
                                          |
                                   Output boundary
                                   translation layer
                                   (user values kept
                                    verbatim)
                                          |
                                          v
                                  Translated grievance
                                  response + metadata
                          |
                          v
             +---------------------------+
             |      RAGOrchestrator      |
             |  asyncio.gather both      |
             |  pipelines in parallel    |
             +--------+--------+---------+
                      |        |
          +-----------+        +-----------+
          v                               v
 +------------------+          +--------------------+
  | StaticRAGService |          | WebRAGService      |
  | Supabase pgvec.  |          | 10-step pipeline   |
  | hybrid retrieval |          | Tavily/SerpApi/    |
  | (dense + lexical |          | Firecrawl          |
  |  RRF fusion)     |          | BM25 → Gemini pre- |
 |  RRF fusion)     |          | rank → RRF →       |
 | EvidenceChunks   |          | Gemini final-rank  |
 +------------------+          | → source verify    |
          |                    | EvidenceChunks     |
          |                    +--------------------+
          +----------+---------+
                     v
          +---------------------+
          | EvidenceController  |
          | build_bundle()      |
          | assess_evidence()   |
          | build_curated_      |
          |   prompt()          |
          +----------+----------+
                     |
                     v
          +---------------------+
          | LLM (grounded_ans.) |
          | Groq (primary)      |
          | Gemini (fallback)   |
          +----------+----------+
                     |
                     v
          +---------------------+
          | citation_verifier   |
          | verify_citations()  |
          | invalid → ABSTAIN   |
          +----------+----------+
                     |
                     v
             RAGResponse (answer, citations,
             confidence, mode, speech_text)
```

---

## 3. Request flow: `/chat` and `/chat/stream`

```
POST /chat (or /chat/stream for SSE)   [requires Clerk JWT → 401 without it]
  │
  ├── require_auth()                → verify Clerk session JWT, else 401
  ├── resolve_and_remember()      → detect/remember response language (en/hi/gu/mr/bn/ta/te/kn/pa/or/ml)
  ├── detect_query_languages()    → dominant language + language_mix
  ├── _translate_to_english()     → Sarvam (primary) → Azure (fallback)
  ├── get_embedding_provider().embed_texts()  → 768d Jina v3 embedding
   ├── AnchorStore.classify()      → domain (keyword rules + cosine similarity, floor 0.20)
  ├── QueryClassifier.classify()  → web RAG classification (domain, jurisdiction, state)
  │
  ├─[if domain == "grievance"]────────────────────────────────────────────────┐
  │   GrievanceWorkflow.process_message()                                     │
  │   State machine: INTAKE→CLASSIFICATION→ENTITY_EXTRACTION→                │
  │   MISSING_FIELDS→FOLLOWUP→DRAFT_READY→SUBMISSION_GUIDE→                  │
  │   STATUS_LOOKUP→COMPLETE                                                  │
  │   Persists to Supabase `grievance_states` table                           │
  │   Returns WorkflowResult (English-only internal state)                    │
  │                                                                           │
  │   Output translation boundary:                                            │
  │     draft_summary values → translated                                     │
  │     canonical dict top-level → translated                                 │
  │     submission data (portal, steps, docs, timeline) → translated          │
  │     field labels → translated via FIELD_LABELS lookup                     │
  │     user-entered values → preserved verbatim                              │
  │     URLs → preserved unchanged                                            │
  │                                                                           │
  ├─[if domain == "out_of_scope"]──────────────────────────────────────────── │
  │   Return scope message, abstained=True                                    │
  │                                                                           │
  └─[else RAG path]─────────────────────────────────────────────────────────►│
      RAGOrchestrator.run()                                                   │
        ├── asyncio.gather:                                                   │
  │     StaticRAGService.retrieve()  → Supabase pgvector hybrid         │
  │     WebRAGService.retrieve(deadline=started+web_rag_timeout_s)            │
  │       → Tavily/SerpApi-Google/Firecrawl 10-step + ≤2 recovery rounds;     │
  │       no NEW recovery round starts past the deadline (asyncio               │
  │       cancellation cannot stop the worker thread)                           │
        ├── EvidenceController.build_bundle()                                 │
        ├── EvidenceController.build_curated_prompt()                         │
        ├── grounded_answer(GroqLLMProvider, GeminiLLMProvider, ...)          │
        ├── _auto_append_citations()   (if LLM forgot to cite)                │
        ├── verify_citations()         → invalid chunk ref → ABSTAIN          │
        ├── strip_citations()          → clean visible answer                 │
        ├── _calculate_confidence()    → band-based, dual-source +0.10        │
        └── RAGResponse                                                       │
      │                                                                       │
      _translate_from_english()  Sarvam → Azure (if lang != "en")            │
      save_message() / trim_messages()                                        │
      return dict                                                        ◄────┘
```

---

## 4. Request flow: `/voice`

```
POST /voice (multipart: audio file + language + session_id)
  │
  ├── VoiceService.speech_to_text()
  │     Gnani Prisma v3.0 STT (primary, 15s timeout, no Odia → falls through)
  │     → Sarvam STT (fallback, 15s timeout)
  │     → Azure STT (fallback, 15s timeout)
  │     → VoiceUnavailableError
  │
  ├── chat() handler (same pipeline as /chat)
  │
  └── VoiceService.text_to_speech(speech_text, language)
        Gnani Timbre v3.0 TTS (primary, 20s timeout, no Odia → falls through)
        → Sarvam TTS (fallback)
        → Azure excluded — poor Indic output
        → VoiceUnavailableError (returns null audio, text answer still returned)

Response: { answer, transcribed_text, audio_base64, language, domain,
            confidence, citations, abstained }
```

---

## 5. Streaming SSE events (`/chat/stream`)

Events emitted in order:
1. `thinking` — `{ text: "Searching official documents & web..." }`
2. `thinking` — `{ text: "Analyzing evidence from both sources..." }`
3. `thinking` — `{ text: "Preparing answer..." }`
4. `token` — `{ text: "word " }` (one per word)
5. `metadata` — `{ domain, confidence, confidence_level, citations, abstained, language, mode }`
6. `done` — `{}`

---

## 6. Domain taxonomy

`pacs_governance | pacs_computerization | pmfby | financial_inclusion | schemes | agriculture | grievance | out_of_scope`

Classification: keyword rules first (instant, case-insensitive); fallback to cosine similarity of 768d anchor embeddings (floor 0.20 → `out_of_scope`).

Domain alias mapping in StaticRAGService:
- `pacs` → `pacs_governance`
- `finlit` → `financial_inclusion`
- `cooperative` → `pacs_governance`

---

## 7. Database schema (Supabase)

```sql
documents
---------
id (uuid PK), source_id (unique), title, organization, domain, jurisdiction,
state, document_type, source_url, effective_date, verified_date, created_at

chunks
------
id (uuid PK), document_id (FK → documents), stable_chunk_id,
page, page_start, page_end, section, subsection, clause,
content, embedding vector(768),   ← HNSW cosine index
domain, jurisdiction, state, source_url, source_file, created_at

sessions
--------
session_id (PK), state (jsonb), expires_at, created_at

grievance_states
----------------
conversation_id (PK), user_id, state_json (full GrievanceState as JSON),
created_at, updated_at
```

`match_chunks` RPC: dense vector search with domain + state + effective-date (`as_of_date`) filter, returns top-k by cosine similarity. The app always sends all six keys (`query_embedding, match_domain, match_state, match_count, as_of_date, match_entity_id`) so PostgREST unambiguously selects the 6-arg overload — a 4-key call fails with PGRST203 where both overloads exist.

---

## 8. Hybrid retrieval (StaticRAGService)

```
query_embedding
    │
    ├── _dense_retrieve()     → match_chunks RPC (pgvector cosine, domain+state filter)
    └── _lexical_retrieve()   → term-overlap on chunks.content (Python BM25-style)
                                 filtered to eligible doc IDs first
    │
    └── _reciprocal_rank_fusion()
          dense_weight=0.6, lexical_weight=0.4, k=60
          → top-k fused candidates
    │
    └── _enrich_chunks()      → attach stable_chunk_id + provenance metadata
    │
    └── evidence_gate()       → TOP1_THRESHOLD=0.25, SECONDARY_THRESHOLD=0.30,
                                 MIN_CHUNKS_ABOVE_SECONDARY=2
                                 → abstained? + ConfidenceBand
```

Optional Jina reranker wired after step 2, **currently disabled** (`RERANKER_ENABLED=false`).

---

## 9. Web RAG pipeline (WebRAGService) — 10 steps + bounded recovery

Recovery (after step 10 abstains): at most `MAX_RECOVERY_ROUNDS=2` single-axis rounds (`recovery.py`: jurisdiction/validity/authority/language/facet), one full discover + steps 3–10 each. Cooperative deadline: `retrieve(deadline)` is passed `started + web_rag_timeout_s` by the orchestrator; no NEW round starts past it, so a late success is never computed after fallback. Thresholds, RRF, BM25, verifier unchanged.

1. **Domain scope gate** — abstain if domain unsupported (`DOMAIN_MISMATCH`); `"general"` proceeds (internal classifier may refine)
2. **Web discovery** — `WebDiscoveryService` via Tavily / SerpApi Google / Firecrawl (bounded concurrent branches × concurrent provider fan-out)
3. **BM25 ranking** — `BM25Retriever`, top 15
4. **Gemini pre-ranking** — `GeminiReranker.pre_rank()`, top 15
5. **RRF fusion** — fuse BM25 + Gemini pre-rank lists
6. **Gemini final reranking** — `GeminiReranker.final_rerank()`, top 8
7. **Relevance gate** — minimum score threshold 40.0
8. **Source verification** — `SourceVerifier` (class default trust ≥ 35.0; `WebRAGService` constructs it with 20.0)
9. **Evidence threshold** — abstain if no accepted sources
10. **Convert to EvidenceChunks** → unified `evidence_gate()`

---

## 10. Confidence scoring

```
static_band → static_conf (high=0.9, medium=0.7, low=0.4)
web_band    → web_conf    (same mapping)

if dual source:  confidence = min((static_conf + web_conf)/2 + 0.10, 1.0)
if static only:  confidence = static_conf
if web only:     confidence = web_conf

Bands:  ≥0.7 → HIGH,  ≥0.5 → MEDIUM,  else → LOW
```

---

## 11. Fallback chains

```
STT:  Gnani Prisma v3.0 → Sarvam → Azure → VoiceUnavailableError
TTS:  Gnani Timbre v3.0 → Sarvam → VoiceUnavailableError (Azure excluded)
LLM:  Groq (primary) → Gemini (fallback) → AllProvidersFailedError → ABSTAIN
Embed: Jina (primary) → Gemini (fallback)
Translation: Sarvam → Azure → return original
```

---

## 12. Evidence/context and generation controls

Multiple independent layers bound the amount of evidence and tokens processed:

**Evidence controller** (`evidence_controller.py`) — caps what enters the generation prompt:
- Static evidence: top 3 highest-quality chunks only
- Dynamic (web) evidence: top 3 highest-quality chunks only
- Per-chunk text: truncated at `MAX_CHARS_PER_CHUNK = 3000`

**Web RAG** (`web_rag/service.py`) — caps chunks per web source:
- `WEB_MAX_CHUNKS_PER_SOURCE = 12`

**Generation token limit** (`config.py`, `groq_llm.py`):
- Normal generation: `GENERATION_MAX_TOKENS = 1800`
- Citation repair is deterministic (marker removal + re-append), not a second LLM call.

These are separate layers (retrieval → evidence selection → prompt assembly → generation) and are not contradictory. Each bounds a different stage of the pipeline.

The limits are intentional engineering controls to bound context size and generation latency/cost while retaining sufficient evidence for grounded answers.

---

## 13. Grievance workflow stages

| Stage | What happens |
|---|---|
| INTAKE | Classify complaint; if too vague, ask for more detail |
| CLASSIFICATION | Present category/subcategory/department; ask to confirm |
| ENTITY_EXTRACTION | Extract entities from description; update draft |
| MISSING_FIELDS | (routes to ENTITY_EXTRACTION) |
| FOLLOWUP | Ask for missing required fields one at a time |
| DRAFT_READY | Present complete draft + submission route |
| SUBMISSION_GUIDE | Offer status tracking guidance |
| STATUS_LOOKUP | Provide reference number + status check URL |
| COMPLETE | Workflow done; can restart or ask sub-questions |

State persisted to Supabase `grievance_states` (upsert on `conversation_id`).

---

## 14. Grievance localization architecture

All grievance workflow processing happens in **English only**. Translation is applied at the output boundary, ensuring user-entered values are preserved verbatim while system-generated text is translated.

**Backend translation points:**

```
_grievance_message()
  ├─ draft_summary values        → title, description translated
  ├─ top-level canonical dict    → category, sub_category, department, jurisdiction, title
  ├─ submission data             → portal_name, department, level, steps, documents, timeline, disclaimer
  └─ field labels                → field_label from FIELD_LABELS dict (150+ entries)

/grievances/finalize endpoint    → same submission + canonical dict translation
/grievances/clarify endpoint     → draft_summary + field_label translation
```

**User value preservation rules:**
- User-entered text (title, description, answers) → copied verbatim, never translated by LLM
- URLs → preserved unchanged
- Submission metadata (portal names, department names, steps) → translated via provider chain
- Field labels → translated via `field_detector.FIELD_LABELS` lookup (not LLM)

**Frontend translation points:**
- `GrievanceClassificationPanel`: tab labels use `t()` from dictionaries
- `GrievanceFieldPanel`: tab labels use `f.field_label || f.field.replace(/_/g, " ")`
- `GrievanceCard`: disclaimer, buttons use `t()`
- `GrievanceFlow`: wizard submit uses `t("grievanceWizard.submitting")`

**Supported languages:** `en | hi | gu | mr | bn | ta | te | kn | pa | or | ml` — same as chat.

---

## 15. Non-functional constraints

- No personal GPU; free-tier / cloud-only
- Every external provider call has a strict timeout
- Render cold starts expected; Supabase may pause after inactivity
- Free-tier rate limits expected (Groq key rotation supported)
- Minimal PII — no secrets in frontend or source control
- Reranker: wired but disabled (`RERANKER_ENABLED=false`)
