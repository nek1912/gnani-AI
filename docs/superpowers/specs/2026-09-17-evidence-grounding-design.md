# Design: Strict Evidence-Grounded Answer Generation (RAG V3 Part 3)

**Date:** 2026-09-17
**Status:** Approved
**Scope:** Strengthen answer generation to be mechanically faithful to retrieved evidence

---

## Problem

Current grounding is entirely prompt-based. The LLM is asked to self-insert `[chunk:ID]` markers, but post-generation verification only checks citation ID membership. When the LLM fails (C01: enumeration collapse, D06: unsupported numbers, S08: section confusion), there is no safety net.

**Observed failures:**
- C01: PMFBY coverage types replaced with "natural-and-climatic risk cover"
- D06: "Age 18-70 years" added when not in evidence
- S08: HR policy information attributed to loan policy

---

## Approach

**Option A: Prompt-Heavy + Regex Guard**

Strengthen the system prompt with explicit evidence-grounding rules, add a two-layer post-generation verification (regex first, LLM for complex cases), and add enumeration detection.

**Tradeoffs:**
- ✅ ~300 lines of new code
- ✅ No extra LLM calls for simple cases (regex handles most)
- ✅ Fast — regex is O(n), no added latency for 90% of queries
- ⚠️ Regex can't catch semantic hallucinations (e.g., "HR policy" → "loan policy")
- ⚠️ LLM verification adds ~2-5s latency for complex cases

---

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/evidence_controller.py` | Strengthen `_SOURCE_PRIORITY_PROMPT`, add `detect_enumeration_question()`, add `_LANG_NAMES` for all 11 languages |
| `backend/app/services/rag_orchestrator.py` | Wire `verify_answer_grounding()` after LLM generation |
| `backend/app/answer_grounding.py` | **NEW** — `verify_answer_grounding()`, `GroundingResult`, regex extraction, LLM verification |
| `backend/tests/test_answer_grounding.py` | **NEW** — 10+ unit tests for grounding behavior |
| `backend/tests/test_evaluation.py` | **NEW** — 20+ real-world evaluation test cases |

---

## Design Details

### 1. Strengthened System Prompt

Update `_SOURCE_PRIORITY_PROMPT` in `evidence_controller.py` with 8 new rules:

**Rule 1: EVIDENCE IS THE ONLY FACTUAL AUTHORITY**
Every factual claim must be directly supported by supplied evidence. No general knowledge, no inference, no gap-filling from memory. If evidence doesn't establish a fact, say "The available sources do not establish it."

**Rule 2: PRESERVE MATERIAL TERMS EXACTLY**
When evidence contains named items (eligibility criteria, coverage types, loan types, authorities, documents, deadlines, rates, percentages, amounts, thresholds, conditions, exceptions, legal provisions, procedural steps), reproduce their terminology verbatim.

**Rule 3: DO NOT SUBSTITUTE SYNONYMS FOR ENUMERATED FACTS**
If evidence gives a finite list, reproduce the list faithfully. Don't compress A + B + C + D into "various related risks" unless the user explicitly asks for a high-level summary.

**Rule 4: NUMBERS AND THRESHOLDS ARE CLOSED-WORLD**
Never generate a number unless it appears in the supplied evidence. This includes age limits, percentages, premium rates, loan amounts, dates, durations, monetary limits, acreage, thresholds.

**Rule 5: DO NOT MERGE DOCUMENT SECTIONS**
Use the evidence item's actual section/document identity. Don't attribute HR policy information to loan policy, membership rules to loan sanction rules, one scheme's conditions to another scheme.

**Rule 6: HANDLE CONFLICTS EXPLICITLY**
If two evidence items contain conflicting information, state that the retrieved sources contain conflicting information and identify the relevant source/document.

**Rule 7: MISSING INFORMATION MUST REMAIN MISSING**
If the evidence doesn't answer an aspect of the question, say "The available sources do not specify this." Do NOT attempt to complete the answer using general knowledge.

**Rule 8: USER-FRIENDLY LANGUAGE IS ALLOWED, BUT FACTUAL TERMS MUST SURVIVE**
The answer can be simplified for rural users. However, explanation may be simplified but factual terminology may not be replaced when replacement changes meaning.

### 2. Enumeration Detector

New function `detect_enumeration_question(question: str) -> bool` in `evidence_controller.py`.

Detects when user asks for:
- types, categories, kinds
- eligibility, requirements, conditions
- documents, steps, benefits
- exclusions, features, coverage, authorities

When detected, adds instruction to prompt: "The user is asking for a list/enumeration. You MUST reproduce ALL enumerated items from the evidence exactly as they appear. Do not compress into a generic summary."

### 3. Post-Generation Regex Guard

New file `backend/app/answer_grounding.py` with:

```python
@dataclass
class UnsupportedClaim:
    claim_text: str
    claim_type: str  # "number", "date", "entity", "condition"
    evidence_chunk_ids: list[str]  # chunks that SHOULD support this claim
    reason: str

@dataclass
class GroundingResult:
    has_unsupported_claims: bool
    unsupported_claims: list[UnsupportedClaim]
    all_claims: list[dict]  # claim -> evidence mapping
```

**Layer 1 — Regex extraction (fast, O(n)):**
- Extract all numbers (integers, decimals, percentages, currency)
- Extract all dates (DD Month, Month YYYY, YYYY-MM-DD, etc.)
- Extract named entities (scheme names like PMFBY, PACS, authorities)
- Extract eligibility conditions (keywords: "age", "years", "minimum", "maximum", "must be", "shall be")
- For each extracted item, check if it appears in the cited chunks' content
- Flag items that don't appear in any cited chunk

**Layer 2 — LLM verification (for complex cases):**
- If Layer 1 finds suspicious claims, send those specific claims + cited chunks to LLM for verification
- LLM prompt: "Given these evidence chunks, verify whether each claim is supported. Return SUPPORTED or UNSUPPORTED with reason."
- Only triggered when Layer 1 finds issues (not for every query)

### 4. Integration into RAGOrchestrator

Wire `verify_answer_grounding()` into `rag_orchestrator.py` after LLM generation:

```python
# After generation
answer = grounded_answer(...)

# Post-generation grounding check
grounding_result = verify_answer_grounding(answer, all_chunks)
if grounding_result.has_unsupported_claims:
    answer = _rewrite_with_supported_claims(answer, grounding_result, all_chunks)
```

**Behavior when unsupported claims found:**
- Remove unsupported claims from the answer
- Add note: "The available sources do not establish [X]"
- Do NOT invent replacement facts

### 5. Tests

New test file `backend/tests/test_answer_grounding.py`:

1. **Exact enumeration preservation** — Evidence has A, B, C, D. Answer must contain all 4.
2. **No generic substitution** — "A, B, C, D" must not become "various related risks"
3. **Unsupported numeric fact** — Evidence has no age limit. Answer must not contain "18-70 years"
4. **Unsupported eligibility condition** — Evidence doesn't have a condition. Answer must not generate it.
5. **Section attribution** — Loan answer must not cite HR section
6. **Missing evidence** — Question asks for X, evidence only has Y. Answer must report X as unsupported.
7. **Conflicting evidence** — Two chunks disagree. Answer must surface conflict.
8. **Numeric preservation** — Evidence says "2%". Answer must say 2%.
9. **Date preservation** — Evidence says "31 March". Answer must not invent another deadline.
10. **Multilingual answer** — Hindi question + English evidence. Factual terms must survive translation.

### 6. Evaluation

Create 20+ real-world evaluation test cases based on C01/D06/S08 failure patterns:

- **C01-type:** Questions asking for enumerations (types, categories, eligibility)
- **D06-type:** Questions where LLM might add unsupported eligibility criteria
- **S08-type:** Questions where LLM might confuse document sections
- **Direct questions:** Factual, enumeration
- **Scenario questions:** Multi-condition
- **Multilingual questions:** Hindi, Gujarati, etc.
- **Missing information cases:** Evidence doesn't cover the question
- **Negative/unsupported questions:** Questions with no relevant evidence

---

## What This Does NOT Change

- Ingestion pipeline (no changes)
- Retrieval pipeline (no changes)
- Embedding model (no changes)
- Evidence gate thresholds (no changes)
- Citation format `[chunk:ID]` (no changes)
- Scenario reasoning architecture (no changes)
- Frontend code (no changes)

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| False positives in regex guard | Tune thresholds based on evaluation. Start conservative (only flag high-confidence mismatches). |
| LLM verification adds latency | Only triggered when regex finds issues (~10% of queries). Can be disabled via config flag. |
| Prompt changes affect existing behavior | Run full evaluation suite before/after. Compare accuracy metrics. |
| Multilingual regex extraction | Focus on English evidence content (evidence is always in English). Answer language doesn't affect extraction. |

---

## Success Criteria

After implementation:
1. C01 is fixed — PMFBY coverage types preserved exactly
2. D06 is fixed — No unsupported "18-70 years" in answer
3. S08 is fixed — No section attribution confusion
4. Overall accuracy improves from 57.1% toward 70%+
5. Evidence coverage remains 100%
6. Unsupported claims reported drops to 0
7. Latency increase < 5s for 90% of queries
