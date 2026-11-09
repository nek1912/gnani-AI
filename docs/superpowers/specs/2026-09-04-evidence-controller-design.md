# Evidence Controller + Claim Verification Design Spec

**Date:** 2026-09-04
**Status:** Approved
**Author:** opencode

## Problem Statement

The current hybrid RAG architecture (static + dynamic) merges evidence into a flat list and tells the LLM to "use whichever evidence best answers the question." This causes the LLM to use static policy/guideline evidence to answer queries requiring current, district-specific facts — producing confident but wrong answers.

**Example failure:**
- Query: "મારા જિલ્લામાં PMFBY માટે હાલમાં કઈ કઈ પાકો notified છે?"
- Static RAG: 6 chunks from PMFBY guidelines 2023
- Dynamic RAG: 0 chunks (no current district data)
- Current behavior: LLM answers confidently using 2023 guidelines as if they are current
- Expected behavior: LLM explains it cannot verify current notifications without district-specific evidence

## Guiding Principle

> **Static evidence may explain the rule; dynamic evidence must establish the current/local fact.**

## Final Invariant

> **Every factual claim in the returned final answer must either have supporting evidence appropriate to its claim type or be explicitly presented as unverified/abstained.**

## Architecture

```
                         Query
                           │
              ┌────────────┴────────────┐
              │                         │
         Static RAG                 Dynamic RAG
         (async)                    (async)
              │                         │
       policy/rules/general      current/local facts
              │                         │
              └────────────┬────────────┘
                           │
                  Query Requirement Classifier
                  + Session location resolver
                           │
                    Evidence Controller
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Evidence metadata           Query requirements
       source=static/web           temporal/locality
       freshness                   specificity
       applicability
             │                           │
             └─────────────┬─────────────┘
                           │
                     LLM Curator
                           │
                     Draft answer
                           │
                  Claim Verification
                  ┌────────┴────────┐
            Heuristic check    LLM check (if needed)
                  │                     │
                  └─────────┬───────────┘
                            │
                   Filter/regenerate
                            │
                   Re-verify (if regenerated)
                            │
                   Confidence calculation
                            │
                          Answer
```

## Section 1: Data Models

### File: `app/contracts.py` (additions)

```python
@dataclass
class QueryRequirements:
    """Derived from the user query — what kind of evidence is needed."""
    temporal_scope: str        # "general" | "current" | "historical" | explicit year like "2025"
    geographic_scope: str      # "none" | "state" | "district"
    required_specificity: str  # "general" | "state" | "district" | "crop+district+year"
    requires_dynamic: bool     # True if answer needs current/local facts
    # NOTE: requires_web_for_claims is derived per-claim, not here.
    # A query can require dynamic evidence for some claims while still
    # allowing independently supported static claims.

@dataclass
class StaticEvidence:
    """Static RAG evidence with metadata."""
    available: bool
    chunks: list[EvidenceChunk]
    summary: str  # brief description of what static evidence covers

@dataclass
class DynamicEvidence:
    """Dynamic (web) RAG evidence with metadata."""
    available: bool
    chunks: list[EvidenceChunk]
    reason: str | None  # if absent, why (e.g., "No applicable district-specific evidence found")

@dataclass
class EvidenceBundle:
    """Structured evidence with source-aware metadata."""
    static: StaticEvidence
    dynamic: DynamicEvidence
    query_requirements: QueryRequirements
    query: str  # original query for traceability
    query_id: str | None = None  # optional traceability ID

@dataclass
class FlaggedClaim:
    """A claim flagged by heuristic verification."""
    claim_id: str  # stable identifier for this claim (e.g., hash or index)
    claim_text: str
    claim_type: str  # "static" | "dynamic" | "mixed"
    flag_reason: str
    requires_evidence: str  # "static" | "dynamic" | "any"

@dataclass
class ClaimVerification:
    """Result of checking a claim against evidence."""
    claim_id: str  # stable identifier, matches FlaggedClaim.claim_id
    claim_text: str
    is_supported: bool
    claim_type: str  # "static" | "dynamic" | "mixed"
    source_type_needed: str  # "static" | "dynamic" | "none"
    evidence_found: bool
    evidence_ids: list[str]  # chunk IDs that support this claim
    rejection_reason: str | None
    verification_confidence: float | None  # LLM verifier's confidence (None = uncertain)

@dataclass
class FilterOutcome:
    """Explicit outcome of claim filtering."""
    KEEP = "keep"       # claim is supported, keep as-is
    FILTER = "filter"   # claim is unsupported, remove from answer
    REGENERATE = "regenerate"  # claim needs rephrasing with caveats
    ABSTAIN = "abstain" # claim cannot be salvaged, abstain from answering this part
```

### EvidenceChunk Metadata Additions

`EvidenceChunk` already has `source_type`, `jurisdiction`, `state` fields. Add structured metadata for freshness and applicability:

```python
# In EvidenceChunk.metadata dict, enforce these keys:
metadata = {
    "source_type": "static" | "web",     # redundant with field, but explicit
    "freshness": "current" | "historical" | "unknown",  # derived from document date
    "applicability": "high" | "medium" | "low" | "unknown",  # from reranker/evidence gate
    "document_date": "2023" | None,      # year of the source document
    "retrieved_at": "2026-09-04T...",    # when this chunk was retrieved
}
```

## Section 2: Query Requirement Classifier

### File: `app/evidence_controller.py` (new)

```python
class QueryRequirementClassifier:
    """Determines what kind of evidence a query needs."""

    def classify(self, query: str, lang: str, session_state: dict | None = None) -> QueryRequirements:
        temporal = self._detect_temporal(query, lang)
        geographic = self._detect_geographic(query, lang, session_state)
        specificity = self._detect_specificity(query, lang, temporal, geographic)
        requires_dynamic = self._needs_dynamic(temporal, geographic, specificity)

        return QueryRequirements(
            temporal_scope=temporal,
            geographic_scope=geographic,
            required_specificity=specificity,
            requires_dynamic=requires_dynamic,
        )
```

**Temporal classification rules:**

| Pattern | temporal_scope | requires_dynamic |
|---------|---------------|-----------------|
| "PMFBY rules" (no year, no current indicator) | "general" | False |
| "PMFBY 2026 premium" (explicit future/current year) | "2026" | True |
| "હાલમાં notified crops" (explicit current indicator) | "current" | True |
| "2023 guidelines" (explicit past year) | "historical" | False |
| "Surat district crops" (no temporal indicator) | "unspecified" | **Depends on geographic** — if district-specific, treat as requiring current |

**Key rule:** Temporal inference is explicit — "current" only when the query asks for active/current information (contains "હાલમાં", "currently", "now", "today"). An unspecified temporal scope with a district mention is NOT automatically "current" — it means the user likely wants current info, but the classifier marks it as `requires_dynamic=True` due to geographic specificity, not temporal certainty.

**Session/location resolution:**
- If `session_state` contains a remembered `state` or `district`, use it to resolve geographic scope
- If `geographic_scope == "district"` but no district is identified (from query or session), the system must ask for the missing location rather than infer one
- District-specific queries without an identified district → `abstain/ask_for_location`

## Section 3: Evidence Controller

### File: `app/evidence_controller.py` (continued)

```python
class EvidenceController:
    """Wraps static + web evidence with metadata and requirements."""

    def build_bundle(
        self,
        static_result: RAGResult,
        web_result: RAGResult,
        query_requirements: QueryRequirements,
        query: str,
    ) -> EvidenceBundle:
        # Tag each chunk with source_type, freshness, applicability
        # Determine if dynamic evidence is available vs absent
        # Calculate claim-level support potential

    def build_curated_prompt(
        self,
        bundle: EvidenceBundle,
        english_query: str,
        history: list[dict] | None,
        lang: str,
    ) -> tuple[str, str]:  # (system_prompt, user_prompt)
        # System prompt has SOURCE PRIORITY RULES
        # User prompt separates static/dynamic evidence with headers
        # If dynamic is absent: explicit instruction not to infer
```

### System Prompt — Source Priority Rules

```
You are a government information assistant. You must answer based on
the evidence provided, following these SOURCE PRIORITY RULES:

1. STATIC EVIDENCE (official documents, guidelines, policies) may establish:
   - Policy definitions and legal framework
   - Eligibility rules and general procedures
   - Historical or general scheme structure
   - How processes work (notification, application, etc.)

2. DYNAMIC EVIDENCE (web sources, current data) must establish:
   - Current values, amounts, figures
   - Current notifications and active schemes
   - District/state-specific information
   - Current portal/service availability
   - Current insurer assignments
   - Current premium/coverage figures

3. RULES FOR COMBINED EVIDENCE:
   - Never use static evidence to state a current/local fact unless
     dynamic evidence explicitly confirms it
   - If dynamic evidence is absent or insufficient for a current/local
     claim, say so clearly — do NOT infer from static evidence
   - Static evidence can explain the rule/framework surrounding an
     unanswered dynamic claim

4. EVIDENCE SEPARATION:
   - Evidence marked [STATIC] comes from official documents (may be outdated)
   - Evidence marked [DYNAMIC] comes from web sources (current but may vary)
   - Treat them as having different epistemic roles

5. CITATIONS:
   - After EVERY factual sentence, add the citation: [chunk:ID]
   - Use the EXACT citation marker shown in the evidence
   - Use ONLY half-width square brackets []

6. LANGUAGE:
   - Respond in the SAME language as the question
   - Do NOT switch languages mid-response
```

### User Prompt Template

```
{conversation_history}

Question: {english_query}

== STATIC EVIDENCE (official documents — may not reflect current status) ==
{static_chunks}

== DYNAMIC EVIDENCE (web sources — current information) ==
{dynamic_chunks_or_status}

== EVIDENCE AVAILABILITY ==
Static: {static_count} chunks available
Dynamic: {dynamic_status} ("available — {N} chunks" or "ABSENT — {reason}")

Available sources: {static_count} from official documents, {dynamic_count} from web

Synthesize an answer following the SOURCE PRIORITY RULES.
If dynamic evidence is absent for a current/local claim, state that clearly.
Do NOT infer current values from static guidelines.
```

## Section 4: Claim Verification (Two-Layer)

### File: `app/claim_verifier.py` (new)

#### Layer 1: Heuristic Check (<10ms)

```python
class HeuristicClaimVerifier:
    """Detects potentially unsupported claims in LLM answer."""

    def check(self, answer: str, bundle: EvidenceBundle) -> list[FlaggedClaim]:
        flagged = []

        # Split answer into atomic claims (sentence-level or clause-level)
        # For each claim:
        #   - Assign stable claim_id (hash of claim text)
        #   - Detect year mentions → check if dynamic evidence covers that year
        #   - Detect district/city names → check if dynamic evidence covers that location
        #   - Detect value claims ("premium is X", "amount is Y") → check if evidence supports
        #   - Detect notification claims → check if dynamic evidence exists

        # HARD RULE: If requires_dynamic=True and dynamic evidence is absent:
        #   automatically flag ALL claims that could be interpreted as current/local,
        #   even if heuristic doesn't detect them

        return flagged
```

**Heuristic patterns:**

| Pattern | claim_type | requires_evidence |
|---------|-----------|-------------------|
| Year mention (2025, 2026) | "dynamic" | "dynamic" |
| District/city name | "dynamic" | "dynamic" |
| "હાલમાં", "currently", "now" | "dynamic" | "dynamic" |
| Value/amount claim | "mixed" | "any" — dynamic component needs dynamic evidence |
| Policy/rule explanation | "static" | "static" |

**Mixed claim support definition:** A mixed claim is unsupported only when its dynamic component lacks required evidence. If a mixed claim has both static-supported and dynamic-unsupported parts, the static part survives and the dynamic part is filtered.

#### Layer 2: LLM Verification (when heuristic flags claims)

```python
class LLMClaimVerifier:
    """Uses Gemini to verify flagged claims against minimum relevant evidence."""

    def verify(
        self,
        flagged_claims: list[FlaggedClaim],
        bundle: EvidenceBundle,
    ) -> list[ClaimVerification]:
        # For each flagged claim:
        #   1. Find minimum relevant evidence chunks (not all chunks)
        #   2. Ask Gemini: does this evidence support this claim?
        #   3. Return verification with evidence_ids
        #   4. If Gemini is uncertain (verification_confidence=None or low),
        #      do NOT treat as fully supported — treat as uncertain
```

**Verifier disagreement/uncertainty handling:**
- If `verification_confidence is None` → treat as uncertain, not fully supported
- If `verification_confidence < 0.5` → flag for manual review / abstain
- Do not automatically treat uncertain verifications as supported

#### Combined Entry Point

```python
class ClaimVerifier:
    """Two-layer claim verification with explicit filter outcomes."""

    def verify(
        self,
        answer: str,
        bundle: EvidenceBundle,
    ) -> tuple[str, list[ClaimVerification], bool]:
        # Layer 1: heuristic
        flagged = self.heuristic.check(answer, bundle)

        if not flagged:
            return answer, [], False  # fast path, no LLM call

        # Layer 2: LLM verification
        verifications = self.llm.verify(flagged, bundle)

        # Determine filter outcomes
        outcomes = self._determine_outcomes(verifications, bundle)

        # Apply outcomes: KEEP, FILTER, REGENERATE, ABSTAIN
        answer, was_modified = self._apply_outcomes(answer, outcomes, verifications, bundle)

        if was_modified:
            # Re-verify: REPLACE old verification set, do not append/merge
            verifications = self._reverify(answer, bundle)

        return answer, verifications, was_modified
```

**Filter outcomes:**
- `KEEP`: claim is supported, keep as-is in answer
- `FILTER`: claim is unsupported, remove sentence from answer
- `REGENERATE`: claim needs rephrasing with caveats (e.g., "According to 2023 guidelines, the framework is...")
- `ABSTAIN`: claim cannot be salvaged, replace with abstention text

**Critical rules:**
- `_filter_or_regenerate()` must never silently delete essential content
- After regeneration, re-verification REPLACES the old verification set (not append/merge)
- If `requires_dynamic=True` and dynamic evidence is absent: no surviving claim requiring dynamic evidence can be marked supported

## Section 5: Confidence Recalculation

**Confidence is calculated AFTER claim filtering/regeneration, based on claims remaining in the final answer.**

```python
def _calculate_claim_confidence(
    self,
    answer: str,
    verifications: list[ClaimVerification],
    bundle: EvidenceBundle,
) -> tuple[float, ConfidenceBand]:  # (confidence, band)
    # If no verifications (abstention or simple answer):
    if not verifications:
        if bundle.query_requirements.requires_dynamic and not bundle.dynamic.available:
            return 0.3, ConfidenceBand.LOW  # capped for missing dynamic evidence
        return self._evidence_level_confidence(bundle)

    # Only count claims that survive in the final answer (use claim_id matching)
    surviving = [v for v in verifications if self._claim_survives(v, answer)]

    if not surviving:
        # All claims were filtered out — low confidence
        return 0.2, ConfidenceBand.LOW

    # Use traceable count (supported + has evidence_ids) for ratio
    traceable = sum(
        1 for v in surviving
        if v.is_supported and v.evidence_ids
    )
    total = len(surviving)

    support_ratio = traceable / total if total > 0 else 0.0

    # Dynamic claims that are unsupported drag confidence down more
    dynamic_unsupported = sum(
        1 for v in surviving
        if not v.is_supported and v.claim_type == "dynamic"
    )

    # Mixed claims with unsupported dynamic component
    mixed_with_dynamic_unsupported = sum(
        1 for v in surviving
        if v.claim_type == "mixed" and not v.is_supported
        and v.source_type_needed == "dynamic"
    )

    # Uncertain verifications (verification_confidence is None or low)
    uncertain = sum(
        1 for v in surviving
        if v.verification_confidence is not None and v.verification_confidence < 0.5
    )

    if dynamic_unsupported > 0 or mixed_with_dynamic_unsupported > 0:
        confidence = min(support_ratio * 0.5, 0.4)
    elif uncertain > 0:
        confidence = min(support_ratio * 0.7, 0.6)
    elif support_ratio >= 0.8:
        confidence = 0.9
    elif support_ratio >= 0.5:
        confidence = 0.7
    else:
        confidence = 0.4

    # Enforce cap for requires_dynamic + dynamic absent
    if bundle.query_requirements.requires_dynamic and not bundle.dynamic.available:
        confidence = min(confidence, 0.4)

    # Map to band (separate from confidence value)
    if confidence >= 0.7:
        band = ConfidenceBand.HIGH
    elif confidence >= 0.5:
        band = ConfidenceBand.MEDIUM
    else:
        band = ConfidenceBand.LOW

    return round(confidence, 2), band
```

**`_claim_survives` method:** Uses `claim_id` matching, not substring matching. Each claim gets a stable ID at extraction time; the verification set and final answer both track these IDs.

## Section 6: Async Architecture

**Current state:** `static_rag.retrieve()` and `web_rag.retrieve()` are synchronous methods. They use synchronous Supabase client, synchronous httpx, etc.

**Approach:** Wrap sync methods with `asyncio.to_thread()` for concurrent execution. Do NOT make the provider SDKs async — that would be a much larger refactor.

```python
class RAGOrchestrator:
    async def run(self, ...) -> RAGResponse:
        # Step 1: Run both pipelines concurrently with error isolation
        static_task = asyncio.create_task(
            asyncio.to_thread(self._static_rag.retrieve, ...)
        )
        web_task = asyncio.create_task(
            asyncio.to_thread(self._web_rag.retrieve, ...)
        )

        # gather with return_exceptions=True so one failure doesn't kill the other
        results = await asyncio.gather(
            static_task, web_task, return_exceptions=True
        )

        # Handle partial failures gracefully
        static_result = results[0] if not isinstance(results[0], Exception) else RAGResult.abstained(...)
        web_result = results[1] if not isinstance(results[1], Exception) else RAGResult.abstained(...)

        if isinstance(results[0], Exception):
            logger.warning("Static RAG failed: %s", results[0])
        if isinstance(results[1], Exception):
            logger.warning("Web RAG failed: %s", results[1])

        # Step 2: Classify query requirements (fast, local)
        query_reqs = self._query_classifier.classify(query, lang, session_state)

        # Step 3: Check for missing required location
        if query_reqs.geographic_scope == "district" and not self._has_district(query_reqs, session_state):
            return self._ask_for_location(lang, session_id)

        # Step 4: Build evidence bundle
        bundle = self._evidence_controller.build_bundle(
            static_result, web_result, query_reqs, query
        )

        # Step 5: Build curated prompt
        system_prompt, user_prompt = self._evidence_controller.build_curated_prompt(
            bundle, english_query, history, lang
        )

        # Step 6: Generate answer (async LLM call)
        answer = await asyncio.to_thread(
            grounded_answer, GroqLLMProvider(...), GeminiLLMProvider(...),
            system_prompt, user_prompt
        )

        # Step 7: Claim verification (heuristic fast, LLM if needed)
        answer, verifications, was_modified = await asyncio.to_thread(
            self._claim_verifier.verify, answer, bundle
        )

        # Step 8: Confidence on FINAL answer (after filtering)
        confidence, band = self._calculate_claim_confidence(
            answer, verifications, bundle
        )

        # Step 9: Build response
        ...
```

**Failure handling for `asyncio.gather()`:**
- `return_exceptions=True` prevents one pipeline failure from canceling the other
- Each pipeline failure is logged and results in an abstained result for that pipeline
- The other pipeline's evidence is still used

**Route handlers become async:**
```python
@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    ...

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    ...
```

## Section 7: Streaming Claim Verification

For `/chat/stream`, claim verification must NOT stream an answer as final before verification completes.

**Approach:**
1. Stream thinking indicators during retrieval + LLM generation
2. Buffer the full answer (do NOT stream tokens yet)
3. Run claim verification on the buffered answer
4. Stream the verified/final answer tokens
5. Include verification metadata in the final SSE event

```python
async def chat_stream(req: ChatRequest):
    # ... retrieval + generation (stream thinking indicators) ...
    answer = await asyncio.to_thread(grounded_answer, ...)

    # Claim verification (buffer, don't stream yet)
    answer, verifications, _ = await asyncio.to_thread(
        self._claim_verifier.verify, answer, bundle
    )

    # Now stream the verified answer
    for token in answer.split(" "):
        yield _sse_event("token", {"text": token + " "})

    # Include verification metadata
    yield _sse_event("metadata", {
        "verifications": [...],
        "confidence": confidence,
        ...
    })
```

## Section 8: Integration Flow

```
retrieve → classify → build bundle → curate → verify → filter/regenerate → re-verify if regenerated → calculate confidence → return
```

**Detailed steps:**

1. **Retrieve**: Static RAG + Dynamic RAG run concurrently via `asyncio.gather(return_exceptions=True)`
2. **Classify**: `QueryRequirementClassifier.classify()` determines temporal/geographic scope (with session state)
3. **Location check**: If district required but not identified → ask for location
4. **Build bundle**: `EvidenceController.build_bundle()` wraps evidence with metadata
5. **Curate**: `EvidenceController.build_curated_prompt()` builds source-aware prompt
6. **Generate**: LLM generates answer from curated prompt
7. **Verify**: `ClaimVerifier.verify()` runs heuristic → LLM (if needed)
8. **Filter/regenerate**: Apply KEEP/FILTER/REGENERATE/ABSTAIN outcomes
9. **Re-verify**: If regenerated, REPLACE old verification set with new one
10. **Calculate confidence**: Based on surviving claims in final answer (after filtering)
11. **Return**: RAGResponse with claim-level confidence

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `app/evidence_controller.py` | CREATE | QueryRequirementClassifier, EvidenceController |
| `app/claim_verifier.py` | CREATE | HeuristicClaimVerifier, LLMClaimVerifier, ClaimVerifier |
| `app/contracts.py` | MODIFY | Add QueryRequirements, StaticEvidence, DynamicEvidence, EvidenceBundle, FlaggedClaim, ClaimVerification, FilterOutcome |
| `app/services/rag_orchestrator.py` | MODIFY | Async flow, evidence bundle, curated prompt, claim verification, confidence |
| `app/routes/chat.py` | MODIFY | Async route handlers, streaming verification |
| `app/services/static_rag.py` | NO CHANGE | Already sync, wrapped with asyncio.to_thread |
| `app/services/web_rag.py` | NO CHANGE | Already sync, wrapped with asyncio.to_thread |

## Testing Strategy

### Required regression tests:

1. **`static=6, dynamic=0` must not produce a confident current/local factual answer**
   - Query: "હાલમાં Surat જિલ્લામાં PMFBY notified crops"
   - Static: 6 chunks from guidelines
   - Dynamic: 0 chunks
   - Expected: Answer explains rules, does NOT list current crops, confidence ≤ 0.4

2. **Mixed answers: valid static portion survives, dynamic portion abstained**
   - Query: "PMFBY rules and current premium in Surat"
   - Static: rules chunks (valid)
   - Dynamic: 0 chunks
   - Expected: Rules explained from static, premium stated as unverifiable, confidence reflects partial support

3. **Explicit historical queries do NOT require current web evidence**
   - Query: "2023 PMFBY guidelines"
   - Static: 2023 guidelines chunks
   - Dynamic: 0 chunks (irrelevant)
   - Expected: Full answer from static, high confidence, no dynamic required

### Additional required tests:

4. Unit tests for `QueryRequirementClassifier` (temporal, geographic, specificity detection)
5. Unit tests for `HeuristicClaimVerifier` (pattern detection, mixed claim handling)
6. Unit tests for `EvidenceController.build_bundle()` (metadata tagging, availability)
7. Unit tests for `EvidenceController.build_curated_prompt()` (prompt structure)
8. Unit tests for `ClaimVerifier` (end-to-end verification flow, filter outcomes)
9. Unit tests for confidence calculation (edge cases: no verifications, all unsupported, mixed, uncertain)
10. Integration tests for async orchestrator flow
11. Tests for retrieval failure (one pipeline fails, other still used)
12. Tests for LLM verification failure (Gemini fails, heuristic results used)
13. Tests for regeneration failure (regeneration produces worse answer, original kept)
14. Tests for timeout cases (pipeline timeout, LLM timeout)
15. Tests for session-based location resolution
