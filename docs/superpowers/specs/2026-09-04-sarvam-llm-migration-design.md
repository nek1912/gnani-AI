# Design Spec: Sarvam-105B LLM Migration & Language Pipeline Simplification

**Date:** 2026-09-04
**Status:** Approved
**Scope:** MVP (Tier 1) — multilingual cooperative governance chatbot for rural Indian citizens

---

## 1. Problem Statement

The current architecture has three issues affecting rural user experience:

1. **Chunk IDs leaking into client responses** — despite prompt instructions and frontend regex, `[chunk:xxx]` markers sometimes appear in the answer text and citations panel
2. **Unnatural language flow** — the pipeline translates the user's query to English for retrieval, generates an English answer via Groq, then translates back to the user's language. This adds latency and produces unnatural responses
3. **No mixed-language support** — users who ask in Hinglish, Gujlish, or other code-mixed styles get monolingual responses

**Target audience:** Rural Indian citizens with limited English proficiency. Answers must be simple, clear, helpful, and in the user's language — including code-mixed styles.

---

## 2. Design Principles

1. **Prevent bad evidence before generation** rather than detecting bad answers after
2. **Minimum latency with acceptable correctness** — no extra model calls for verification
3. **No hardcoded word lists** — find engineering solutions, not brittle patterns
4. **Backend guarantees clean output** — frontend is UI-only defense, not the security mechanism
5. **Source-role rules override raw retrieval scores** — a high-quality web chunk doesn't become "primary" for a general policy question

---

## 3. Architecture Overview

### Current Flow (to change)

```
User query (Hindi)
  → translate to English
  → embed (Jina v3)
  → Static RAG ∥ Web RAG
  → merge evidence
  → Groq (Llama 3.3 70B) generates English answer
  → translate to Hindi
  → client
```

### New Flow

```
User query (any language / code-mixed)
  → language detection (dominant + mix ratio)
  → translate to English (for Jina v3 embedding only)
  → embed (English query)
  → domain classification (QueryClassifier)
  → Static RAG (Supabase pgvector) ∥ Web RAG (Tavily/Firecrawl)
  → Evidence Assessment (source-role, quality, sufficiency)
  → Evidence Controller (prompt construction)
  → Sarvam-105B (generates directly in user's language)
  → citation extraction + set-membership validation
  → strip [chunk:ID] from answer
  → client
```

**Key difference:** No output translation. Sarvam-105B natively generates in Indian languages and code-mixed styles.

---

## 4. Component Designs

### 4.1 LLM Provider: Sarvam-105B

**New file:** `backend/app/providers/sarvam_chat.py`

| Property | Value |
|---|---|
| API endpoint | `POST https://api.sarvam.ai/v1/chat/completions` |
| Auth headers | `api-subscription-key: {key}` (preferred, per official docs) |
| Model | `sarvam-105b` (128K context) |
| Streaming | Server-Sent Events (SSE) — optional, NOT part of MVP correctness path |
| Reasoning | `reasoning_effort=None` (disabled for latency-sensitive RAG) |
| Timeout | 30s connect, 120s read |
| Fallback chain | Sarvam key 1 → Sarvam key 2 → Groq → abstain |

The adapter follows the existing provider pattern: explicit timeout, fallback handling, never called directly from route handlers.

**Environment variables:**
```
SARVAM_API_KEY_1=sk_xxx        # Primary
SARVAM_API_KEY_2=sk_xxx        # Fallback
SARVAM_MODEL=sarvam-105b       # Default
GROQ_API_KEY=xxx               # Tertiary fallback
```

**Changes to existing files:**
- `backend/app/providers/__init__.py` — register SarvamChatProvider as primary LLM
- `backend/app/routes/chat.py` — update provider references
- `backend/app/services/rag_orchestrator.py` — use new provider

### 4.2 Language Pipeline Simplification

**Changes to `backend/app/routes/chat.py`:**

| Step | Current | New |
|---|---|---|
| Input translation | `_translate_to_english()` | **Keep** — Jina v3 needs English input |
| Output translation | `_translate_from_english()` | **Remove** — Sarvam generates directly |
| Language passing | `lang` only | `lang` + `language_mix` to orchestrator |

**Removed:** Post-generation translation block (lines ~314-318 in current chat.py).

**New flow in chat.py:**
```python
# 1. Detect language
lang, language_mix = detect_query_languages(req.question)

# 2. Translate to English for embedding
english_query = await _translate_to_english(req.question, lang)

# 3. Generate embedding
embedding = await generate_embedding(english_query)

# 4. Run RAG (no output translation after this)
rag_response = await orchestrator.run(
    query=req.question,
    english_query=english_query,
    embedding=embedding,
    lang=lang,
    language_mix=language_mix,
    ...
)

# 5. Return directly — Sarvam already generated in user's language
return rag_response
```

### 4.3 Mixed Language Detection

**Changes to `backend/app/language.py`:**

Extend `detect_query_languages()` to return:
- `lang: str` — dominant language code (existing)
- `language_mix: dict[str, float] | None` — language ratios when ≥2 languages detected above 15% threshold

**Detection method:** Unicode script analysis (existing). No hardcoded word lists, no external models.

**Known limitation:** Romanized Hindi/Gujarati (written in Latin script) cannot be reliably identified through Unicode script analysis alone. Do NOT add word dictionaries or another model to solve this — let Sarvam-105B naturally handle code-mixed input through the prompt instruction to "preserve the user's language and code-switching style naturally."

**MVP scope:** `dominant language + optional script-based language_mix`. That's it.

**Examples:**
| Input | `lang` | `language_mix` |
|---|---|---|
| "PMFBY scheme kya hai" | `hi` | `{"hi": 0.5, "en": 0.5}` |
| "What is the premium rate?" | `en` | `None` |
| "ગુજરાત સહકાર યોજનा" | `gu` | `None` |
| "Cooperative society ka rules" | `hi` | `{"hi": 0.6, "en": 0.4}` |

**Orchestrator change:** Accept `language_mix` parameter, pass to evidence controller for prompt construction.

### 4.4 Prompt Engineering Rewrite

**File:** `backend/app/evidence_controller.py` — replace `_SOURCE_PRIORITY_PROMPT`

```
You are a helpful government information assistant for Indian citizens,
especially those in rural areas.

CRITICAL RULES:

1. Language: Respond in the user's language. If the question mixes languages
   (e.g., Hindi + English), respond naturally in that same style. Preserve the
   user's language and code-switching style naturally. Do not force everything
   into one language.

2. Evidence: Use the evidence provided to answer.
   - STATIC EVIDENCE (official documents): Rules, definitions, policy,
     procedures, eligibility criteria. Always in English.
   - DYNAMIC EVIDENCE (web sources): Current facts, notifications,
     availability, current values. May be in any language.
   Use both when relevant. Prioritize evidence based on relevance,
   authority, specificity, and freshness. Do not use weaker evidence
   when it conflicts with stronger evidence. Do not infer current or
   local facts from static evidence alone.

3. Citations: After each factual statement, add [chunk:ID] markers.
   These are for internal tracking and will be extracted by the system.
   You must include them for every factual claim.

4. When evidence is limited:
   - Answer only what is directly supported by the available evidence
   - Add ONE brief note at the END if important context is missing
   - Do NOT repeat disclaimers. Do NOT refuse to answer what evidence supports.

5. When evidence is insufficient:
   - Answer only what is directly supported
   - Explain what information is missing
   - Suggest what type of official source the user should consult
     (e.g., district cooperative office, block development officer)

6. When no evidence is found:
   - Explain that no relevant evidence was found
   - Suggest the type of official source the user should consult
   - Do NOT generate a general knowledge answer

7. Tone: Simple, clear, helpful. Use short sentences. Explain technical
   terms (like PMFBY, PACS) briefly when first mentioned. Be kind and
   patient — the user may be asking for the first time.

8. Formatting:
   - Use bullet points for lists
   - Bold important terms or document names
   - Keep paragraphs short (2-3 sentences)
   - Use markdown for readability
```

**Prompt construction changes in `EvidenceController.build_curated_prompt()`:**

- Inject `{user_language}` and `{language_mix}` dynamically
- Replace chunk-count status with evidence strength assessment
- Evidence strength text examples:
  - "Static evidence is stronger for this query. Use it as the primary source."
  - "Dynamic evidence is stronger for this query. Static evidence provides background context."
  - "Both sources provide comparable evidence. Use them together."

### 4.5 Evidence Assessment

**New enum and model in `backend/app/evidence_controller.py` or `contracts.py`:**

```python
class SourceRole(Enum):
    STATIC_PRIMARY = "static_primary"    # General policy/rules/definitions
    WEB_PRIMARY = "web_primary"          # Current/local/notification/value
    BALANCED = "balanced"                # Both relevant

class EvidenceSufficiency(Enum):
    SUFFICIENT = "sufficient"      # Enough quality evidence to answer
    PARTIAL = "partial"            # Some evidence, gaps remain
    INSUFFICIENT = "insufficient"  # Not enough to answer properly
    EMPTY = "empty"                # No evidence found

class EvidenceAssessment(BaseModel):
    source_role: SourceRole
    sufficiency: EvidenceSufficiency
    static_quality: Literal["high", "medium", "low"]
    web_quality: Literal["high", "medium", "low"]
    assessment_text: str  # Human-readable, injected into prompt
```

**Assessment logic:**

```python
def assess_evidence(self, static_result, web_result, query_requirements):
    # 1. Source-role match: which source SHOULD have the answer?
    source_role = self._determine_source_role(query_requirements)

    # 2. Quality: retrieval scores above threshold, domain relevance
    static_quality = self._score_quality(static_result.chunks)
    web_quality = self._score_quality(web_result.chunks)

    # 3. Sufficiency: enough to answer the specific question?
    sufficiency = self._check_sufficiency(
        static_result, web_result, source_role, query_requirements
    )

    # 4. Generate assessment text for prompt
    assessment_text = self._generate_assessment_text(
        source_role, sufficiency, static_quality, web_quality
    )

    return EvidenceAssessment(...)
```

**Source-role rules:**

| Query type | Primary source | Secondary source |
|---|---|---|
| Current/local/notification/value | Dynamic (web) | Static (background) |
| General policy/rules/definitions | Static | Dynamic (supplementary) |
| Historical (specific period) | Evidence matching period | Other as context |
| Both relevant | Compare quality, use both | — |

**Query classification extension:** Add `temporal_relevance` tag to `QueryClassifier` output: `current`, `general`, `historical`.

### 4.6 Chunk ID Fix (3-Layer Defense)

#### Layer 1: Prompt (Section 4.4)
- LLM is told to include `[chunk:ID]` for every factual claim (internal markers)
- System extracts them — no instruction to "hide"

#### Layer 2: Backend extraction (new)
**New function in `backend/app/evidence_controller.py` or `orchestrator.py`:**

```python
def strip_citations(answer: str) -> tuple[str, list[str]]:
    """Extract [chunk:ID] markers from LLM output.

    Returns (clean_answer, extracted_ids).
    Backend guarantee: clean_answer contains no [chunk:xxx] patterns.

    Actual chunk-ID formats in this RAG system:
    - Static: 8-char hex prefix of UUID (e.g., 'a0eebc99')
    - Web: 'web_{hex12}_c{N}' prefix (e.g., 'web_a1b2c3d4e5f6_c102')
    The LLM is instructed to use the first 8 chars in [chunk:ID] markers.
    Use a broad capture group to match any characters between chunk: and ].
    """
    pattern = r'\[chunk:([^\]]+)\]'
    ids = re.findall(pattern, answer)
    clean = re.sub(pattern, '', answer)
    # Clean up extra whitespace from stripping
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean, ids
```

**Called at the LLM boundary** — immediately after Sarvam generates, before any other post-processing.

**Verification (set-membership only):** Check that every extracted chunk ID exists in the evidence supplied to the LLM. If an ID doesn't exist in the evidence set:
- Strip it from the answer (already done by `strip_citations`)
- Log a warning
- Do NOT call another LLM to verify — just strip and continue

**Limitation (explicit):** This validation verifies that every extracted chunk ID exists in the evidence supplied to the LLM. Semantic claim verification (does the citation actually support the claim it's attached to) is out of scope for MVP.

#### Layer 3: Frontend (UI-only defense)
**Changes to `frontend/src/components/chat/MessageBubble.tsx`:**

Expand `cleanAnswerText()` regex patterns to match any characters inside `[chunk:...]`:
```typescript
// Use broad capture to match any chunk-ID format (hex, web_ prefix, etc.)
/\[chunk:[^\]]+\]/gi,               // [chunk:anything]
/\(chunk:[^\)]+\)/gi,               // (chunk:anything)
/\[Chunk:[^\]]+\]/gi,               // [Chunk:anything]
/\[CHUNK:[^\]]+\]/gi,               // [CHUNK:anything]
```

**Citations panel:** Verify it only shows `title`, `page`, `source_label`, `url` — never `chunk_id`.

---

## 5. Provider Fallback Chain

```
Sarvam key 1 (primary)
  ↓ on failure (429, 500, timeout)
Sarvam key 2 (fallback)
  ↓ on failure
Groq (Llama 3.3 70B) (tertiary)
  ↓ on failure
Abstain (return helpful message in user's language)
```

**Failure detection:** HTTP 429 (rate limit), 5xx (server error), timeout (>30s connect or >120s read).

**When Groq is used as fallback:** Groq receives the **same evidence-controlled prompt** and citation requirements as Sarvam. Do NOT create a separate weaker Groq path. Groq generates in English. If `lang != "en"`, apply output translation via existing `_translate_from_english()` only for this fallback path. This keeps the translation overhead isolated to the fallback case.

---

## 6. Performance Optimizations

| Optimization | Impact | Complexity |
|---|---|---|
| Eliminate output translation (Sarvam primary) | Removes one API call per request | Low |
| Parallel citation extraction + response preparation | Reduces post-generation latency | Low |
| Fast citation validation (set-membership only — verifies IDs exist in evidence, not semantic claim support) | No extra model call | Low |
| Keep `asyncio.gather()` for Static ∥ Web RAG | Already parallel | None |

**Deferred (not MVP):**
- Input translation caching
- Streaming optimization (verify before delivery first)
- Semantic LLM verification (adds latency, not needed for MVP)

---

## 7. Files to Change

| File | Change |
|---|---|
| `backend/app/providers/sarvam_chat.py` | **New** — Sarvam chat completions adapter |
| `backend/app/providers/__init__.py` | Register SarvamChatProvider |
| `backend/app/routes/chat.py` | Remove output translation, pass language_mix |
| `backend/app/language.py` | Extend detect_query_languages() for mixed language |
| `backend/app/evidence_controller.py` | Rewrite prompt, add EvidenceAssessment, add strip_citations() |
| `backend/app/contracts.py` | Add EvidenceAssessment model |
| `backend/app/services/rag_orchestrator.py` | Accept language_mix, use EvidenceAssessment |
| `frontend/src/components/chat/MessageBubble.tsx` | Expand cleanAnswerText() regex |
| `backend/.env` | Add SARVAM_API_KEY_1, SARVAM_API_KEY_2 |

---

## 8. Testing Strategy

| Test | What it validates |
|---|---|
| SarvamChatProvider unit tests | Adapter handles success, 429, 500, timeout, fallback to key 2 |
| Language detection tests | Mixed language detection, code-mixed ratios, edge cases |
| Evidence assessment tests | Source-role matching, sufficiency states, assessment text generation |
| Strip citations tests | Regex extraction, edge cases (nested brackets, partial matches) |
| Prompt construction tests | Language injection, evidence strength text, mixed-language prompts |
| Integration test (end-to-end) | Hindi query → English retrieval → Sarvam Hindi answer, no chunk IDs in output |
| Fallback chain test | Sarvam down → key 2 → Groq → abstain |

---

## 9. Success Criteria

1. **No chunk IDs in client responses** — backend guarantee, frontend defense
2. **Answers in user's language** — including code-mixed styles (Hinglish, Gujlish)
3. **No output translation latency** — Sarvam generates directly
4. **Graceful degradation** — one weak source prioritizes the stronger; both weak explains limitation; both empty abstains with helpful guidance
5. **Rural-friendly tone** — simple, clear, short sentences, technical terms explained
6. **Provider resilience** — 3-tier fallback chain (Sarvam × 2 + Groq)

---

## 10. Out of Scope (MVP)

- Multilingual embedding model (keep Jina v3 + English translation for now)
- Semantic LLM verification (adds latency, not needed)
- Additional classifiers/rerankers (unless profiling proves they help)
- Input translation caching (defer until profiling)
- Streaming optimization (verify correctness first, optimize later)
- WhatsApp/Android/iOS integration
