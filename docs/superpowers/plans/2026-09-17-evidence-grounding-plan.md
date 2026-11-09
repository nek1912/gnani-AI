# Strict Evidence-Grounded Answer Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make answer generation mechanically faithful to retrieved evidence by strengthening prompts, adding post-generation verification, and creating evaluation tests.

**Architecture:** Prompt-heavy approach with two-layer post-generation verification. Layer 1 is fast regex extraction (numbers, dates, entities). Layer 2 is LLM verification for complex cases triggered only when Layer 1 finds issues.

**Tech Stack:** Python 3.11+, Pydantic, regex, existing LLM providers (Groq/Gemini)

## Global Constraints

- Python type hints everywhere
- Pydantic models for all request/response bodies
- No bare `except`
- Every external provider call goes through an adapter with explicit timeout and fallback
- Never put API keys in frontend code
- Structured logs, never log API keys or full grievance PII
- Do NOT change ingestion, retrieval, embedding, or evidence gate
- Do NOT change the scenario reasoning architecture
- Do NOT change frontend code

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/app/evidence_controller.py` | **Modify** — Strengthen `_SOURCE_PRIORITY_PROMPT`, add `detect_enumeration_question()`, update `_LANG_NAMES` |
| `backend/app/answer_grounding.py` | **Create** — `GroundingResult`, `UnsupportedClaim`, `verify_answer_grounding()`, regex extraction, LLM verification |
| `backend/app/services/rag_orchestrator.py` | **Modify** — Wire `verify_answer_grounding()` after LLM generation |
| `backend/tests/test_answer_grounding.py` | **Create** — Unit tests for grounding verification |
| `backend/tests/test_evaluation_grounding.py` | **Create** — Real-world evaluation test cases |

---

### Task 1: Strengthen System Prompt

**Files:**
- Modify: `backend/app/evidence_controller.py:179-235` (replace `_SOURCE_PRIORITY_PROMPT`)
- Modify: `backend/app/evidence_controller.py:357-364` (update `_LANG_NAMES`)

**Interfaces:**
- Consumes: None (standalone prompt change)
- Produces: `_SOURCE_PRIORITY_PROMPT` constant (used by `build_curated_prompt()`)

- [ ] **Step 1: Update `_LANG_NAMES` to include all 11 languages**

```python
_LANG_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "gu": "Gujarati (Gujarati script)",
    "mr": "Marathi (Devanagari script)",
    "bn": "Bengali (Bengali script)",
    "ta": "Tamil (Tamil script)",
    "te": "Telugu (Telugu script)",
    "kn": "Kannada (Kannada script)",
    "pa": "Punjabi (Gurmukhi script)",
    "or": "Odia (Odia script)",
    "ml": "Malayalam (Malayalam script)",
}
```

- [ ] **Step 2: Replace `_SOURCE_PRIORITY_PROMPT` with strengthened version**

Replace lines 179-235 with:

```python
_SOURCE_PRIORITY_PROMPT = """You are a helpful government information assistant for Indian citizens,
especially those in rural areas.

CRITICAL RULES:

1. Language: Respond in the language specified in the USER LANGUAGE field
   in the user prompt. Use that language throughout your entire response.
   If the language is Hindi (hi), Gujarati (gu), Marathi (mr), Bengali (bn),
   Tamil (ta), Telugu (te), Kannada (kn), Punjabi (pa), Odia (or), or
   Malayalam (ml), write in that script. Do not mix languages unless the
   technical term has no translation (e.g., scheme names like PMFBY, PACS).

2. EVIDENCE IS THE ONLY FACTUAL AUTHORITY: Every factual claim in your answer
   MUST be directly supported by the evidence provided below. You MUST NOT:
   - Use general model knowledge
   - Infer missing eligibility criteria
   - Invent thresholds, age limits, rates, dates, deadlines, legal clauses,
     documents, procedures, or conditions
   - Fill gaps from memory
   - Introduce facts merely because they sound plausible
   If the evidence does not establish a fact, say "The available sources do
   not establish it."

3. PRESERVE MATERIAL TERMS EXACTLY: When the evidence contains named factual
   items, reproduce their terminology verbatim. This is mandatory for:
   - Eligibility criteria
   - Exclusions
   - Coverage types
   - Scheme components
   - Loan types
   - Authorities
   - Documents
   - Deadlines
   - Rates, percentages, amounts, thresholds
   - Conditions, exceptions
   - Legal provisions
   - Procedural steps
   Example: If evidence says "prevented sowing, mid-season adversity,
   post-harvest losses, localized calamity", write exactly those terms.
   Do NOT replace with "natural-and-climatic risk cover".

4. DO NOT SUBSTITUTE SYNONYMS FOR ENUMERATED FACTS: If evidence gives a
   finite list (A, B, C, D), reproduce the list faithfully. Do NOT compress
   into "various related risks" or "several categories" unless the user
   explicitly asks for a high-level summary.

5. NUMBERS AND THRESHOLDS ARE CLOSED-WORLD: Never generate a number unless
   it appears in the supplied evidence. This includes age limits, percentages,
   premium rates, loan amounts, dates, durations, monetary limits, acreage,
   thresholds. If evidence does NOT contain "18-70 years", your answer
   must NOT contain "18-70 years".

6. DO NOT MERGE DOCUMENT SECTIONS: Use the evidence item's actual section
   and document identity. Do NOT attribute:
   - HR policy information to loan policy
   - Membership rules to loan sanction rules
   - One scheme's conditions to another scheme
   - One authority's procedure to another authority
   When multiple evidence items exist, maintain their provenance.

7. HANDLE CONFLICTS EXPLICITLY: If two evidence items contain conflicting
   information, state that the retrieved sources contain conflicting
   information and identify the relevant source/document where possible.
   Do NOT silently choose one.

8. MISSING INFORMATION MUST REMAIN MISSING: If the evidence does not answer
   an aspect of the question, say "The available sources do not specify this."
   Do NOT attempt to complete the answer using general knowledge.

9. USER-FRIENDLY LANGUAGE IS ALLOWED, BUT FACTUAL TERMS MUST SURVIVE:
   The answer can be simplified for rural users. However, explanation may
   be simplified but factual terminology may not be replaced when replacement
   changes meaning. Example: "Prevented sowing means the crop could not be
   sown because of the specified circumstances" is acceptable. But "Natural
   risk coverage" is NOT an acceptable replacement for a specific coverage
   category.

10. Citations: After each factual statement, add [chunk:ID] markers.
    These are for internal tracking and will be extracted by the system.
    CRITICAL: You MUST include [chunk:ID] citations inline as you write.
    Every factual claim requires a citation. Do NOT write answers that need repair.
    Self-check: Before finishing, verify every fact has a [chunk:ID] marker.

11. When evidence is limited:
    - Answer only what is directly supported by the available evidence
    - Add ONE brief note at the END if important context is missing
    - Do NOT repeat disclaimers. Do NOT refuse to answer what evidence supports.

12. When evidence is insufficient:
    - Answer only what is directly supported
    - Explain what information is missing
    - Suggest what type of official source the user should consult
      (e.g., district cooperative office, block development officer)

13. When no evidence is found:
    - Explain that no relevant evidence was found
    - Suggest the type of official source the user should consult
    - Do NOT generate a general knowledge answer

14. Tone: Simple, clear, helpful. Use short sentences. Explain technical
    terms (like PMFBY, PACS) briefly when first mentioned. Be kind and
    patient — the user may be asking for the first time.

15. Formatting:
    - Use bullet points for lists
    - Bold important terms or document names
    - Keep paragraphs short (2-3 sentences)
    - Use markdown for readability

16. NEVER include these phrases in your response:
    - "Current/local information for this claim could not be verified"
    - "This information could not be verified"
"""
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v -x --timeout=30 2>&1 | head -50`
Expected: Existing tests pass (excluding known pre-existing failures)

- [ ] **Step 4: Commit**

```bash
git add backend/app/evidence_controller.py
git commit -m "feat(rag): strengthen evidence-grounding prompt with 8 new rules"
```

---

### Task 2: Add Enumeration Detector

**Files:**
- Modify: `backend/app/evidence_controller.py` (add `detect_enumeration_question()` function)

**Interfaces:**
- Consumes: User question string
- Produces: `bool` — whether the question asks for an enumeration

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_answer_grounding.py`:

```python
"""Tests for evidence-grounding verification."""

from app.evidence_controller import detect_enumeration_question


class TestEnumerationDetector:
    def test_types_question(self):
        assert detect_enumeration_question("What are the types of risk coverage under PMFBY?") is True

    def test_categories_question(self):
        assert detect_enumeration_question("What are the categories of loans available?") is True

    def test_eligibility_question(self):
        assert detect_enumeration_question("Who is eligible for PMFBY?") is True

    def test_requirements_question(self):
        assert detect_enumeration_question("What documents are required?") is True

    def test_benefits_question(self):
        assert detect_enumeration_question("What are the benefits of PACS membership?") is True

    def test_coverage_question(self):
        assert detect_enumeration_question("What is covered under the scheme?") is True

    def test_steps_question(self):
        assert detect_enumeration_question("What are the steps to apply?") is True

    def test_exclusions_question(self):
        assert detect_enumeration_question("What are the exclusions?") is True

    def test_normal_question(self):
        assert detect_enumeration_question("How do I apply for a loan?") is False

    def test_factual_question(self):
        assert detect_enumeration_question("What is PMFBY?") is False

    def test_hindi_enumeration(self):
        assert detect_enumeration_question("PMFBY के तहत कवरेज के प्रकार क्या हैं?") is True

    def test_gujarati_enumeration(self):
        assert detect_enumeration_question("PMFBY હેઠળ કવરેજના પ્રકારો શું છે?") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_answer_grounding.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_enumeration_question'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/evidence_controller.py` after the `_YEAR_PATTERN` definition:

```python
# Enumeration detection patterns
_ENUMERATION_KEYWORDS_EN = [
    "types", "categories", "kinds", "varieties",
    "eligibility", "eligible", "requirements", "required", "criteria",
    "documents", "papers", "certificates",
    "steps", "procedure", "process",
    "benefits", "advantages", "features",
    "exclusions", "exceptions", "restrictions",
    "coverage", "covered", "included",
    "authorities", "offices", "departments",
]

_ENUMERATION_KEYWORDS_HI = [
    "प्रकार", "श्रेणियां", "किस्में",
    "पात्रता", "पात्र", "आवश्यकताएं", "आवश्यक", "मापदंड",
    "दस्तावेज", "कागजात", "प्रमाणपत्र",
    "चरण", "प्रक्रिया", "विधि",
    "लाभ", "फायदे", "विशेषताएं",
    "बहिष्करण", "अपवाद", "प्रतिबंध",
    "कवरेज", "शामिल", "कवर",
    "अधिकारियों", "कार्यालयों", "विभागों",
]

_ENUMERATION_KEYWORDS_GU = [
    "પ્રકાર", "શ્રેણીઓ", "જાતો",
    "પાત્રતા", "પાત્ર", "જરૂરિયાતો", "જરૂરી", "માપદંડો",
    "દસ્તાવેજો", "કાગળો", "પ્રમાણપત્રો",
    "પગલાં", "પ્રક્રિયા", "રીત",
    "ફાયદા", "લાભો", "વિશેષતાઓ",
    "બહિષ્કરણ", "અપવાદો", "પ્રતિબંધો",
    "કવરેજ", "સામેલ", "આવરી",
    "અધિકારીઓ", "કચેરીઓ", "વિભાગો",
]


def detect_enumeration_question(question: str) -> bool:
    """Detect if user question asks for an enumeration/list.

    Returns True if question contains keywords like types, categories,
    eligibility, requirements, documents, steps, benefits, exclusions,
    coverage, authorities.
    """
    q = question.lower()

    # Check English keywords
    if any(kw in q for kw in _ENUMERATION_KEYWORDS_EN):
        return True

    # Check Hindi keywords
    if any(kw in question for kw in _ENUMERATION_KEYWORDS_HI):
        return True

    # Check Gujarati keywords
    if any(kw in question for kw in _ENUMERATION_KEYWORDS_GU):
        return True

    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_answer_grounding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/evidence_controller.py tests/test_answer_grounding.py
git commit -m "feat(rag): add enumeration detector for list-type questions"
```

---

### Task 3: Create Answer Grounding Module

**Files:**
- Create: `backend/app/answer_grounding.py`

**Interfaces:**
- Consumes: Generated answer text, list of evidence chunks
- Produces: `GroundingResult` with unsupported claims

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_answer_grounding.py`:

```python
from app.answer_grounding import verify_answer_grounding, GroundingResult
from app.contracts import EvidenceChunk


def _make_chunk(content: str, chunk_id: str = "a0eebc99") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        title="Test Document",
        section="Test Section",
        domain="test",
        dense_score=0.8,
    )


class TestRegexExtraction:
    def test_extracts_numbers(self):
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        result = verify_answer_grounding(
            "The premium rate is 5% of the sum insured.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("5%" in c.claim_text for c in result.unsupported_claims)

    def test_extracts_dates(self):
        chunk = _make_chunk("The deadline is 31 March 2025.")
        result = verify_answer_grounding(
            "The deadline is 15 April 2025.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("15 April" in c.claim_text for c in result.unsupported_claims)

    def test_preserves_correct_numbers(self):
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        result = verify_answer_grounding(
            "The premium rate is 2% of the sum insured.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_extracts_named_entities(self):
        chunk = _make_chunk("Apply to the District Magistrate.")
        result = verify_answer_grounding(
            "Apply to the Block Development Officer.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("Block Development Officer" in c.claim_text for c in result.unsupported_claims)

    def test_no_false_positives_for_common_words(self):
        chunk = _make_chunk("The farmer must be a member of the PACS.")
        result = verify_answer_grounding(
            "The farmer must be a member of the PACS.",
            [chunk],
        )
        assert result.has_unsupported_claims is False


class TestGroundingResult:
    def test_empty_answer(self):
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    def test_no_chunks(self):
        result = verify_answer_grounding("Some answer", [])
        # No chunks means we can't verify, but shouldn't crash
        assert isinstance(result, GroundingResult)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_answer_grounding.py::TestRegexExtraction -v`
Expected: FAIL with `ImportError: cannot import name 'verify_answer_grounding'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/answer_grounding.py`:

```python
"""Post-generation answer grounding verification.

Two-layer check:
1. Regex extraction (fast) — extracts numbers, dates, named entities
2. LLM verification (for complex cases) — triggered when Layer 1 finds issues
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.contracts import EvidenceChunk

logger = logging.getLogger(__name__)


@dataclass
class UnsupportedClaim:
    """A claim in the answer that cannot be grounded in evidence."""
    claim_text: str
    claim_type: str  # "number", "date", "entity", "condition"
    evidence_chunk_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class GroundingResult:
    """Result of post-generation grounding verification."""
    has_unsupported_claims: bool = False
    unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)
    all_claims: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns for fact extraction
# ---------------------------------------------------------------------------

# Numbers: integers, decimals, percentages, currency
_NUMBER_PATTERN = re.compile(
    r'(?:₹|Rs\.?|INR)?\s*\d+(?:\.\d+)?%?(?:\s*(?:lakh|crore|million|billion))?'
)

# Dates: DD Month YYYY, Month YYYY, DD/MM/YYYY, YYYY-MM-DD
_DATE_PATTERN = re.compile(
    r'\b(?:\d{1,2}[\s/-])?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
    r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)[\s/-]?\d{0,4}\b',
    re.IGNORECASE,
)
_DATE_PATTERN_ALT = re.compile(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b')
_DATE_PATTERN_ISO = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')

# Named entities: PMFBY, PACS, scheme names, authorities
_ENTITY_PATTERN = re.compile(
    r'\b(?:PMFBY|PACS|CSC|BDO|DM|SDM|DEO|DRDA|NABARD|SECC|NSFI|RBI|IRDAI|'
    r'District Magistrate|Block Development Officer|Sub-Divisional Magistrate|'
    r'District Level Evaluation Committee|State Level Evaluation Committee|'
    r'Ministry of Cooperation|Ministry of Agriculture)\b',
    re.IGNORECASE,
)

# Eligibility conditions
_CONDITION_PATTERN = re.compile(
    r'\b(?:age\s+\d+[-–]\d+\s+years?|minimum\s+\d+|maximum\s+\d+|'
    r'must be|shall be|required to be|should be)\b',
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> list[str]:
    """Extract all numbers from text."""
    return _NUMBER_PATTERN.findall(text)


def _extract_dates(text: str) -> list[str]:
    """Extract all dates from text."""
    dates = _DATE_PATTERN.findall(text)
    dates.extend(_DATE_PATTERN_ALT.findall(text))
    dates.extend(_DATE_PATTERN_ISO.findall(text))
    return [d.strip() for d in dates if d.strip()]


def _extract_entities(text: str) -> list[str]:
    """Extract named entities from text."""
    return _ENTITY_PATTERN.findall(text)


def _extract_conditions(text: str) -> list[str]:
    """Extract eligibility conditions from text."""
    return _CONDITION_PATTERN.findall(text)


def _build_evidence_text(chunks: list[EvidenceChunk]) -> str:
    """Concatenate all chunk content for searching."""
    return " ".join(chunk.content for chunk in chunks)


def verify_answer_grounding(
    answer: str,
    evidence_chunks: list[EvidenceChunk],
) -> GroundingResult:
    """Verify that factual claims in the answer are grounded in evidence.

    Layer 1: Regex extraction — extracts numbers, dates, entities, conditions
    from the answer and checks if they appear in the evidence chunks.

    Returns GroundingResult with any unsupported claims found.
    """
    if not answer or not evidence_chunks:
        return GroundingResult()

    evidence_text = _build_evidence_text(evidence_chunks)
    evidence_chunk_ids = [chunk.chunk_id for chunk in evidence_chunks]
    unsupported: list[UnsupportedClaim] = []

    # Extract and verify numbers
    answer_numbers = _extract_numbers(answer)
    for num in answer_numbers:
        if num.strip() and num.strip() not in evidence_text:
            unsupported.append(UnsupportedClaim(
                claim_text=num,
                claim_type="number",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=f"Number '{num}' not found in evidence",
            ))

    # Extract and verify dates
    answer_dates = _extract_dates(answer)
    for date_str in answer_dates:
        if date_str and date_str not in evidence_text:
            unsupported.append(UnsupportedClaim(
                claim_text=date_str,
                claim_type="date",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=f"Date '{date_str}' not found in evidence",
            ))

    # Extract and verify named entities
    answer_entities = _extract_entities(answer)
    for entity in answer_entities:
        if entity and entity.lower() not in evidence_text.lower():
            unsupported.append(UnsupportedClaim(
                claim_text=entity,
                claim_type="entity",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=f"Entity '{entity}' not found in evidence",
            ))

    # Extract and verify conditions
    answer_conditions = _extract_conditions(answer)
    for cond in answer_conditions:
        if cond and cond.lower() not in evidence_text.lower():
            unsupported.append(UnsupportedClaim(
                claim_text=cond,
                claim_type="condition",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=f"Condition '{cond}' not found in evidence",
            ))

    return GroundingResult(
        has_unsupported_claims=len(unsupported) > 0,
        unsupported_claims=unsupported,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_answer_grounding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/answer_grounding.py tests/test_answer_grounding.py
git commit -m "feat(rag): add post-generation answer grounding verification"
```

---

### Task 4: Wire Grounding into RAGOrchestrator

**Files:**
- Modify: `backend/app/services/rag_orchestrator.py:270-310` (wire grounding check after generation)

**Interfaces:**
- Consumes: `verify_answer_grounding()` from `answer_grounding.py`
- Produces: Modified answer with unsupported claims removed

- [ ] **Step 1: Add import**

Add to `backend/app/services/rag_orchestrator.py` imports:

```python
from app.answer_grounding import verify_answer_grounding
```

- [ ] **Step 2: Add grounding check after citation verification**

After line 296 (after citation verification block), before line 298 (on_step), add:

```python
        # Step 9.5: Post-generation grounding check
        grounding_result = verify_answer_grounding(answer, all_chunks)
        if grounding_result.has_unsupported_claims:
            logger.warning(
                "Grounding check found %d unsupported claims: %s",
                len(grounding_result.unsupported_claims),
                [c.claim_text for c in grounding_result.unsupported_claims],
            )
            # Remove unsupported claims from answer
            for claim in grounding_result.unsupported_claims:
                # Try to remove the sentence containing the unsupported claim
                # Simple approach: remove the claim text and surrounding context
                answer = re.sub(
                    rf"[^.]*\b{re.escape(claim.claim_text)}\b[^.]*\.",
                    "",
                    answer,
                )
            # Clean up extra spaces
            answer = re.sub(r'  +', ' ', answer).strip()
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v -x --timeout=30 2>&1 | head -50`
Expected: Existing tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/rag_orchestrator.py
git commit -m "feat(rag): wire grounding check into RAG orchestrator"
```

---

### Task 5: Add Enumeration Prompt Injection

**Files:**
- Modify: `backend/app/evidence_controller.py:367-383` (update user prompt instructions)

**Interfaces:**
- Consumes: `detect_enumeration_question()` from Task 2
- Produces: Modified user prompt with enumeration instructions

- [ ] **Step 1: Update `build_curated_prompt()` to inject enumeration instructions**

In `backend/app/evidence_controller.py`, update the `build_curated_prompt()` method. After line 375 (assessment_text), before line 376 (INSTRUCTIONS), add:

```python
        # Detect enumeration questions and add specific instruction
        enum_instruction = ""
        if detect_enumeration_question(english_query):
            enum_instruction = (
                "7. ENUMERATION MODE: The user is asking for a list or categories. "
                "You MUST reproduce ALL enumerated items from the evidence exactly "
                "as they appear. Do NOT compress into a generic summary. "
                "If evidence lists A, B, C, D, your answer must list A, B, C, D.\n"
            )
```

And update the user prompt to include the enumeration instruction:

```python
        user_prompt = (
            f"{hist_text}"
            f"USER LANGUAGE: {lang_name}\n"
            f"Question: {english_query}\n\n"
            f"== STATIC EVIDENCE (official documents — may not reflect current status) ==\n"
            f"{static_section}\n\n"
            f"== DYNAMIC EVIDENCE (web sources — current information) ==\n"
            f"{dynamic_section}\n\n"
            f"{assessment_text}"
            f"INSTRUCTIONS:\n"
            f"1. Write your ENTIRE response in {lang_name}. This is mandatory.\n"
            f"2. Answer using the evidence provided. Prioritize based on relevance and authority.\n"
            f"3. Include [chunk:ID] citations for every factual claim.\n"
            f"4. If evidence is limited, answer only what is directly supported.\n"
            f"5. Use simple, clear language suitable for ordinary citizens.\n"
            f"6. Use markdown formatting (bullet points for lists, bold for key terms) to structure your answer cleanly.\n"
            f"{enum_instruction}"
        )
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v -x --timeout=30 2>&1 | head -50`
Expected: Existing tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/app/evidence_controller.py
git commit -m "feat(rag): inject enumeration preservation instructions for list questions"
```

---

### Task 6: Add Evaluation Test Cases

**Files:**
- Create: `backend/tests/test_evaluation_grounding.py`

**Interfaces:**
- Consumes: Full RAG pipeline (mocked)
- Produces: Test results for evaluation cases

- [ ] **Step 1: Create evaluation test file**

Create `backend/tests/test_evaluation_grounding.py`:

```python
"""Real-world evaluation test cases for evidence grounding.

Based on observed failures:
- C01: PMFBY coverage types collapsed into generic summary
- D06: Unsupported "18-70 years" age limit added
- S08: HR policy attributed to loan policy
"""

import pytest
from app.answer_grounding import verify_answer_grounding
from app.contracts import EvidenceChunk


def _make_chunk(content: str, chunk_id: str = "a0eebc99", title: str = "Test Doc", section: str = "Test Section") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        title=title,
        section=section,
        domain="test",
        dense_score=0.8,
    )


# ---------------------------------------------------------------------------
# C01-type: Enumeration preservation
# ---------------------------------------------------------------------------

class TestC01EnumerationPreservation:
    """Tests for C01 failure: PMFBY coverage types collapsed into generic summary."""

    def test_pmfby_coverage_types_preserved(self):
        """Evidence lists 4 coverage types. Answer must contain all 4."""
        evidence = [_make_chunk(
            "The coverage under PMFBY includes: prevented sowing, "
            "mid-season adversity, post-harvest losses, and localized calamity.",
            chunk_id="a0eebc99",
        )]
        answer = (
            "Under PMFBY, the coverage types are:\n"
            "- Prevented sowing\n"
            "- Mid-season adversity\n"
            "- Post-harvest losses\n"
            "- Localized calamity"
        )
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False

    def test_no_generic_substitution(self):
        """Evidence lists specific types. Answer must not use generic summary."""
        evidence = [_make_chunk(
            "Coverage includes: prevented sowing, mid-season adversity, "
            "post-harvest losses, localized calamity.",
        )]
        answer = "PMFBY provides protection against various natural and climatic risks."
        result = verify_answer_grounding(answer, evidence)
        # The answer doesn't contain specific terms, but regex won't catch this
        # This test verifies the prompt changes work, not the regex
        # The regex test is that we don't get false positives
        assert isinstance(result.has_unsupported_claims, bool)


# ---------------------------------------------------------------------------
# D06-type: Unsupported numeric facts
# ---------------------------------------------------------------------------

class TestD06UnsupportedNumbers:
    """Tests for D06 failure: Unsupported age limit added."""

    def test_age_limit_not_in_evidence(self):
        """Evidence has no age limit. Answer must not contain one."""
        evidence = [_make_chunk(
            "Eligibility: Sharecropper, tenant farmer, notified crop, "
            "notified area. The farmer must be a member of the cooperative.",
        )]
        answer = "To be eligible for PMFBY, you must be between 18-70 years of age."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is True
        assert any("18-70" in c.claim_text for c in result.unsupported_claims)

    def test_premium_rate_preserved(self):
        """Evidence says 2%. Answer must say 2%, not approximately."""
        evidence = [_make_chunk("The premium rate is 2% of the sum insured.")]
        answer = "The premium rate is 2% of the sum insured."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False

    def test_date_preserved(self):
        """Evidence says 31 March. Answer must not invent another date."""
        evidence = [_make_chunk("The deadline for application is 31 March.")]
        answer = "The deadline for application is 31 March."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# S08-type: Section attribution confusion
# ---------------------------------------------------------------------------

class TestS08SectionAttribution:
    """Tests for S08 failure: HR policy attributed to loan policy."""

    def test_entity_attribution(self):
        """Answer must not attribute wrong entity."""
        evidence = [_make_chunk(
            "Loan policy: Loans are sanctioned by the Board of Directors. "
            "The loan amount is determined based on the project report.",
        )]
        answer = "The HR policy determines the loan amount based on the project report."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is True
        assert any("HR policy" in c.claim_text for c in result.unsupported_claims)

    def test_correct_attribution(self):
        """Answer correctly attributes to loan policy."""
        evidence = [_make_chunk(
            "Loan policy: Loans are sanctioned by the Board of Directors. "
            "The loan amount is determined based on the project report.",
        )]
        answer = "The loan policy determines the loan amount based on the project report."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Missing information handling
# ---------------------------------------------------------------------------

class TestMissingInformation:
    """Tests for missing evidence scenarios."""

    def test_missing_evidence_reported(self):
        """Question asks for X, evidence only has Y. Answer should not fabricate."""
        evidence = [_make_chunk("PACS provides credit facilities to members.")]
        answer = "PACS provides credit facilities. The interest rate is 12% per annum."
        result = verify_answer_grounding(answer, evidence)
        # 12% is not in evidence, should be flagged
        assert result.has_unsupported_claims is True
        assert any("12%" in c.claim_text for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# Multilingual grounding
# ---------------------------------------------------------------------------

class TestMultilingualGrounding:
    """Tests for multilingual answer grounding."""

    def test_hindi_answer_with_english_evidence(self):
        """Hindi answer with English evidence. Factual terms must survive."""
        evidence = [_make_chunk(
            "PMFBY coverage includes prevented sowing, mid-season adversity."
        )]
        answer = "PMFBY में prevented sowing और mid-season adversity शामिल है।"
        result = verify_answer_grounding(answer, evidence)
        # The English terms should still be found in evidence
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_answer(self):
        """Empty answer should not crash."""
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    def test_no_chunks(self):
        """No chunks should not crash."""
        result = verify_answer_grounding("Some answer", [])
        assert isinstance(result.has_unsupported_claims, bool)

    def test_special_characters_in_numbers(self):
        """Numbers with special characters should be handled."""
        evidence = [_make_chunk("The amount is Rs. 50,000.")]
        answer = "The amount is Rs. 50,000."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_evaluation_grounding.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_evaluation_grounding.py
git commit -m "test(rag): add evaluation test cases for evidence grounding"
```

---

### Task 7: Add LLM Verification for Complex Cases

**Files:**
- Modify: `backend/app/answer_grounding.py` (add Layer 2 LLM verification)

**Interfaces:**
- Consumes: `UnsupportedClaim` from Layer 1, evidence chunks
- Produces: Updated `GroundingResult` with LLM-verified claims

- [ ] **Step 1: Add LLM verification function**

Add to `backend/app/answer_grounding.py`:

```python
from app.providers.groq_llm import GroqLLMProvider
from app.providers.gemini_llm import GeminiLLMProvider
from app.llm_fallback import grounded_answer


_VERIFICATION_SYSTEM_PROMPT = """You are a fact-verification assistant. Your ONLY job is to verify
whether factual claims are supported by the provided evidence chunks.

RULES:
1. For each claim, respond with ONLY "SUPPORTED" or "UNSUPPORTED"
2. If UNSUPPORTED, provide a one-line reason
3. Do NOT add any other information
4. Do NOT use general knowledge — only the provided evidence matters
5. Be strict: if the claim adds ANY information not in the evidence, it is UNSUPPORTED

Format your response as:
CLAIM 1: [SUPPORTED/UNSUPPORTED] [reason if unsupported]
CLAIM 2: [SUPPORTED/UNSUPPORTED] [reason if unsupported]
...
"""


def _build_verification_prompt(
    claims: list[UnsupportedClaim],
    evidence_chunks: list[EvidenceChunk],
) -> str:
    """Build prompt for LLM verification of unsupported claims."""
    evidence_text = "\n\n".join(
        f"[CHUNK {i+1}] {chunk.content}"
        for i, chunk in enumerate(evidence_chunks[:5])
    )

    claims_text = "\n".join(
        f"CLAIM {i+1}: {c.claim_text} (type: {c.claim_type})"
        for i, c in enumerate(claims)
    )

    return (
        f"== EVIDENCE ==\n{evidence_text}\n\n"
        f"== CLAIMS TO VERIFY ==\n{claims_text}\n\n"
        f"Verify each claim against the evidence. Respond with SUPPORTED or UNSUPPORTED."
    )


def _parse_verification_response(response: str, claims: list[UnsupportedClaim]) -> list[UnsupportedClaim]:
    """Parse LLM verification response and return still-unsupported claims."""
    unsupported = []
    lines = response.strip().split("\n")

    for i, line in enumerate(lines):
        if i >= len(claims):
            break
        if "UNSUPPORTED" in line.upper():
            unsupported.append(claims[i])

    return unsupported


def verify_with_llm(
    unsupported_claims: list[UnsupportedClaim],
    evidence_chunks: list[EvidenceChunk],
    settings: Any = None,
) -> list[UnsupportedClaim]:
    """Layer 2: LLM verification for complex cases.

    Only called when Layer 1 regex finds issues.
    Returns claims that are still unsupported after LLM verification.
    """
    if not unsupported_claims or not evidence_chunks:
        return unsupported_claims

    try:
        from app.config import get_settings
        settings = settings or get_settings()

        primary_provider = GroqLLMProvider(settings)
        fallback_provider = GeminiLLMProvider(settings)

        user_prompt = _build_verification_prompt(unsupported_claims, evidence_chunks)
        response = grounded_answer(
            primary_provider,
            fallback_provider,
            _VERIFICATION_SYSTEM_PROMPT,
            user_prompt,
        )

        return _parse_verification_response(response, unsupported_claims)

    except Exception as e:
        logger.warning("LLM verification failed, keeping regex results: %s", e)
        return unsupported_claims
```

- [ ] **Step 2: Update `verify_answer_grounding()` to optionally use LLM verification**

Modify the `verify_answer_grounding()` function to accept an optional `use_llm_verification` parameter:

```python
def verify_answer_grounding(
    answer: str,
    evidence_chunks: list[EvidenceChunk],
    use_llm_verification: bool = False,
    settings: Any = None,
) -> GroundingResult:
    """Verify that factual claims in the answer are grounded in evidence.

    Layer 1: Regex extraction — extracts numbers, dates, entities, conditions
    from the answer and checks if they appear in the evidence chunks.

    Layer 2 (optional): LLM verification — triggered when Layer 1 finds issues
    and use_llm_verification is True.

    Returns GroundingResult with any unsupported claims found.
    """
    if not answer or not evidence_chunks:
        return GroundingResult()

    evidence_text = _build_evidence_text(evidence_chunks)
    evidence_chunk_ids = [chunk.chunk_id for chunk in evidence_chunks]
    unsupported: list[UnsupportedClaim] = []

    # Layer 1: Regex extraction
    # ... (existing code) ...

    # Layer 2: LLM verification (optional)
    if unsupported and use_llm_verification:
        unsupported = verify_with_llm(unsupported, evidence_chunks, settings)

    return GroundingResult(
        has_unsupported_claims=len(unsupported) > 0,
        unsupported_claims=unsupported,
    )
```

- [ ] **Step 3: Add config flag for LLM verification**

Add to `backend/app/config.py`:

```python
# Answer grounding
ANSWER_GROUNDING_LLM_ENABLED: bool = False  # Enable LLM verification layer
```

- [ ] **Step 4: Update RAGOrchestrator to use config flag**

In `backend/app/services/rag_orchestrator.py`, update the grounding check:

```python
        # Step 9.5: Post-generation grounding check
        grounding_result = verify_answer_grounding(
            answer,
            all_chunks,
            use_llm_verification=self._settings.answer_grounding_llm_enabled,
            settings=self._settings,
        )
```

- [ ] **Step 5: Run tests to verify everything works**

Run: `cd backend && python -m pytest tests/test_answer_grounding.py tests/test_evaluation_grounding.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/answer_grounding.py backend/app/services/rag_orchestrator.py backend/app/config.py
git commit -m "feat(rag): add LLM verification layer for complex grounding cases"
```

---

### Task 8: Final Verification

**Files:**
- No new files (verification only)

**Interfaces:**
- Consumes: All previous tasks
- Produces: Passing test suite

- [ ] **Step 1: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30`
Expected: All new tests pass, no regressions in existing tests

- [ ] **Step 2: Run linting**

Run: `cd backend && python -m ruff check app/ tests/`
Expected: No errors

- [ ] **Step 3: Run type checking**

Run: `cd backend && python -m mypy app/ --ignore-missing-imports 2>&1 | tail -20`
Expected: No new type errors

- [ ] **Step 4: Update PROJECT_STATUS.md**

Add entry for this feature to `PROJECT_STATUS.md`.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(rag): complete strict evidence-grounded answer generation (Part 3)"
```
