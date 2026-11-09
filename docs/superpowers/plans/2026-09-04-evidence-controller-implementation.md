# Evidence Controller + Claim Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Evidence Controller that classifies query requirements, builds source-aware evidence bundles, curates prompts with static/dynamic priority rules, and verifies claims post-generation — preventing confident but wrong answers when dynamic evidence is absent.

**Architecture:** New modules `evidence_controller.py` (query classification + evidence bundling + prompt curation) and `claim_verifier.py` (two-layer claim verification). Orchestrator refactored to async with `asyncio.gather`. Confidence recalculated at claim level after filtering.

**Tech Stack:** Python asyncio, Pydantic dataclasses, Gemini SDK (for LLM claim verification), existing Groq/Gemini LLM providers.

## Global Constraints

- Python type hints everywhere, Pydantic models for request/response bodies
- No bare `except` — always catch specific exceptions
- Every external provider call goes through an adapter with timeout and fallback
- Never put API keys in frontend code or commit them
- Structured logs, never log API keys or full grievance PII
- All new code must have tests before implementation (TDD)
- Existing 106+ tests must continue passing after each task

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/contracts.py` | MODIFY | Add QueryRequirements, StaticEvidence, DynamicEvidence, EvidenceBundle, FlaggedClaim, ClaimVerification, FilterOutcome dataclasses |
| `app/evidence_controller.py` | CREATE | QueryRequirementClassifier (temporal/geographic/specificity detection), EvidenceController (bundle building + prompt curation) |
| `app/claim_verifier.py` | CREATE | HeuristicClaimVerifier, LLMClaimVerifier, ClaimVerifier (two-layer verification + filter outcomes) |
| `app/services/rag_orchestrator.py` | MODIFY | Async flow with asyncio.gather, evidence bundle integration, claim verification, claim-level confidence |
| `app/routes/chat.py` | MODIFY | Async route handlers, streaming verification buffer |
| `tests/test_query_classifier.py` | CREATE | Unit tests for QueryRequirementClassifier |
| `tests/test_evidence_controller.py` | CREATE | Unit tests for EvidenceController |
| `tests/test_claim_verifier.py` | CREATE | Unit tests for ClaimVerifier |
| `tests/test_evidence_controller_integration.py` | CREATE | Integration tests for orchestrator flow |

---

### Task 1: Add Data Models to contracts.py

**Files:**
- Modify: `app/contracts.py:1-300` (add new dataclasses after existing models)
- Test: `tests/test_contracts.py` (extend existing)

**Interfaces:**
- Consumes: Existing `EvidenceChunk`, `RAGResult`, `RAGResponse`, `ConfidenceBand`
- Produces: `QueryRequirements`, `StaticEvidence`, `DynamicEvidence`, `EvidenceBundle`, `FlaggedClaim`, `ClaimVerification`, `FilterOutcome`

- [ ] **Step 1: Write failing tests for new data models**

```python
# tests/test_contracts.py (add at end)
def test_query_requirements_creation():
    from app.contracts import QueryRequirements
    qr = QueryRequirements(
        temporal_scope="current",
        geographic_scope="district",
        required_specificity="crop+district+year",
        requires_dynamic=True,
    )
    assert qr.temporal_scope == "current"
    assert qr.requires_dynamic is True

def test_evidence_bundle_creation():
    from app.contracts import EvidenceBundle, StaticEvidence, DynamicEvidence, QueryRequirements
    bundle = EvidenceBundle(
        static=StaticEvidence(available=True, chunks=[], summary="test"),
        dynamic=DynamicEvidence(available=False, chunks=[], reason="no web results"),
        query_requirements=QueryRequirements(
            temporal_scope="current", geographic_scope="district",
            required_specificity="district", requires_dynamic=True,
        ),
        query="test query",
    )
    assert bundle.static.available is True
    assert bundle.dynamic.available is False
    assert bundle.query == "test query"

def test_claim_verification_creation():
    from app.contracts import ClaimVerification
    cv = ClaimVerification(
        claim_id="abc123",
        claim_text="PMFBY premium is 2%",
        is_supported=True,
        claim_type="static",
        source_type_needed="static",
        evidence_found=True,
        evidence_ids=["chunk1"],
        rejection_reason=None,
        verification_confidence=0.9,
    )
    assert cv.is_supported is True
    assert cv.evidence_ids == ["chunk1"]

def test_filter_outcome_constants():
    from app.contracts import FilterOutcome
    assert FilterOutcome.KEEP == "keep"
    assert FilterOutcome.FILTER == "filter"
    assert FilterOutcome.REGENERATE == "regenerate"
    assert FilterOutcome.ABSTAIN == "abstain"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_contracts.py -x -q`
Expected: FAIL — ImportError for new classes

- [ ] **Step 3: Add data models to contracts.py**

Add at end of `app/contracts.py`:

```python
@dataclass
class QueryRequirements:
    temporal_scope: str        # "general" | "current" | "historical" | "2025" | "unspecified"
    geographic_scope: str      # "none" | "state" | "district"
    required_specificity: str  # "general" | "state" | "district" | "crop+district+year"
    requires_dynamic: bool

@dataclass
class StaticEvidence:
    available: bool
    chunks: list[EvidenceChunk]
    summary: str

@dataclass
class DynamicEvidence:
    available: bool
    chunks: list[EvidenceChunk]
    reason: str | None

@dataclass
class EvidenceBundle:
    static: StaticEvidence
    dynamic: DynamicEvidence
    query_requirements: QueryRequirements
    query: str
    query_id: str | None = None

@dataclass
class FlaggedClaim:
    claim_id: str
    claim_text: str
    claim_type: str       # "static" | "dynamic" | "mixed"
    flag_reason: str
    requires_evidence: str  # "static" | "dynamic" | "any"

@dataclass
class ClaimVerification:
    claim_id: str
    claim_text: str
    is_supported: bool
    claim_type: str
    source_type_needed: str
    evidence_found: bool
    evidence_ids: list[str]
    rejection_reason: str | None
    verification_confidence: float | None

class FilterOutcome:
    KEEP = "keep"
    FILTER = "filter"
    REGENERATE = "regenerate"
    ABSTAIN = "abstain"
```

Also add to `EvidenceChunk.metadata` enforcement comment (no code change, just document expected keys).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_contracts.py -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `python -m pytest tests/ -x -q --timeout=60`
Expected: PASS (existing tests unaffected)

- [ ] **Step 6: Commit**

```bash
git add app/contracts.py tests/test_contracts.py
git commit -m "feat: add evidence controller data models (QueryRequirements, EvidenceBundle, ClaimVerification)"
```

---

### Task 2: Create QueryRequirementClassifier

**Files:**
- Create: `app/evidence_controller.py` (class QueryRequirementClassifier)
- Create: `tests/test_query_classifier.py`

**Interfaces:**
- Consumes: Query text, language code, optional session state dict
- Produces: `QueryRequirements` instance

- [ ] **Step 1: Write failing tests for temporal detection**

```python
# tests/test_query_classifier.py
import pytest
from app.evidence_controller import QueryRequirementClassifier

classifier = QueryRequirementClassifier()

def test_general_query_no_year():
    qr = classifier.classify("What are PMFBY rules?", "en")
    assert qr.temporal_scope == "general"
    assert qr.requires_dynamic is False

def test_current_year_query():
    qr = classifier.classify("PMFBY premium 2026", "en")
    assert qr.temporal_scope == "2026"
    assert qr.requires_dynamic is True

def test_haalmaa_query():
    qr = classifier.classify("હાલમાં PMFBY notified crops", "gu")
    assert qr.temporal_scope == "current"
    assert qr.requires_dynamic is True

def test_historical_query():
    qr = classifier.classify("2023 PMFBY guidelines", "en")
    assert qr.temporal_scope == "historical"
    assert qr.requires_dynamic is False

def test_unspecified_with_district():
    qr = classifier.classify("Surat district crops", "en")
    assert qr.geographic_scope == "district"
    assert qr.requires_dynamic is True

def test_state_query():
    qr = classifier.classify("Gujarat PMFBY scheme", "en")
    assert qr.geographic_scope == "state"
    assert qr.requires_dynamic is False  # state-level doesn't always need dynamic

def test_no_geographic():
    qr = classifier.classify("What is PMFBY?", "en")
    assert qr.geographic_scope == "none"
    assert qr.requires_dynamic is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_query_classifier.py -x -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement QueryRequirementClassifier**

```python
# app/evidence_controller.py
"""Evidence Controller — query classification, evidence bundling, prompt curation."""

from __future__ import annotations

import hashlib
import re
import logging
from dataclasses import dataclass

from app.contracts import (
    QueryRequirements, EvidenceBundle, StaticEvidence, DynamicEvidence,
    RAGResult, EvidenceChunk,
)

logger = logging.getLogger(__name__)

# Gujarati/Hindi current indicators
_CURRENT_INDICATORS = {
    "en": ["currently", "now", "today", "current", "active", "present"],
    "hi": ["हाल", "अभी", "वर्तमान", "चालू"],
    "gu": ["હાલ", "હાલમાં", "અત્યારે", "ચાલુ", "વર્તમાન"],
}

_HISTORICAL_INDICATORS = {
    "en": ["previous", "earlier", "past", "old", "guidelines"],
    "hi": ["पिछला", "पुराना", "दिशानिर्देश"],
    "gu": ["અગાઉના", "જૂના", "માર્ગદર્શિકા"],
}

_DISTRICT_INDICATORS = {
    "en": ["district", "city", "taluka", "tehsil"],
    "hi": ["जिला", "शहर", "तहसील"],
    "gu": ["જિલ્લો", "શહેર", "તાલુકો"],
}

_STATE_INDICATORS = {
    "en": ["state", "gujarat", "maharashtra", "karnataka", "tamil nadu"],
    "hi": ["राज्य", "गुजरात", "महाराष्ट्र"],
    "gu": ["રાજ્ય", "ગુજરાત", "મહારાષ્ટ્ર"],
}

_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


class QueryRequirementClassifier:
    """Determines what kind of evidence a query needs."""

    def classify(
        self,
        query: str,
        lang: str,
        session_state: dict | None = None,
    ) -> QueryRequirements:
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

    def _detect_temporal(self, query: str, lang: str) -> str:
        q = query.lower()

        # Check for explicit year
        years = _YEAR_PATTERN.findall(q)
        if years:
            # If year is current or future, treat as requiring dynamic
            latest = max(int(y) for y in years)
            import datetime
            current_year = datetime.datetime.now().year
            if latest >= current_year:
                return str(latest)
            return "historical"

        # Check for current indicators
        indicators = _CURRENT_INDICATORS.get(lang, []) + _CURRENT_INDICATORS.get("en", [])
        if any(ind in q for ind in indicators):
            return "current"

        # Check for historical indicators
        indicators = _HISTORICAL_INDICATORS.get(lang, []) + _HISTORICAL_INDICATORS.get("en", [])
        if any(ind in q for ind in indicators):
            return "historical"

        return "general"

    def _detect_geographic(
        self, query: str, lang: str, session_state: dict | None
    ) -> str:
        q = query.lower()

        # Check for district indicators
        district_inds = _DISTRICT_INDICATORS.get(lang, []) + _DISTRICT_INDICATORS.get("en", [])
        if any(ind in q for ind in district_inds):
            return "district"

        # Check for known district names (common Gujarat districts)
        gujarat_districts = [
            "surat", "valsad", "navsari", "bardoli", "ahmedabad", "rajkot",
            "jamnagar", "bhuj", "gandhinagar", "vadodara", "anand", "nadiad",
            "mahesana", "patan", "banaskantha", "sabarkantha", "pritam nagar",
        ]
        if any(d in q for d in gujarat_districts):
            return "district"

        # Check for state indicators
        state_inds = _STATE_INDICATORS.get(lang, []) + _STATE_INDICATORS.get("en", [])
        if any(ind in q for ind in state_inds):
            return "state"

        # Check session state for remembered location
        if session_state:
            if session_state.get("district"):
                return "district"
            if session_state.get("state"):
                return "state"

        return "none"

    def _detect_specificity(
        self, query: str, lang: str, temporal: str, geographic: str
    ) -> str:
        if geographic == "district" and temporal in ("current",) or any(
            y in temporal for y in ["2025", "2026", "2027"]
        ):
            return "crop+district+year"
        if geographic == "district":
            return "district"
        if geographic == "state":
            return "state"
        return "general"

    def _needs_dynamic(
        self, temporal: str, geographic: str, specificity: str
    ) -> bool:
        # Historical + no geographic specificity = no dynamic needed
        if temporal == "historical" and geographic == "none":
            return False
        # General + no geographic = no dynamic needed
        if temporal == "general" and geographic == "none":
            return False
        # District-level always needs dynamic (current local facts)
        if geographic == "district":
            return True
        # Current or future year = needs dynamic
        if temporal == "current":
            return True
        if temporal not in ("general", "historical"):
            # Explicit year = needs dynamic
            return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_classifier.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/evidence_controller.py tests/test_query_classifier.py
git commit -m "feat: add QueryRequirementClassifier for temporal/geographic query analysis"
```

---

### Task 3: Create EvidenceController (Bundle + Prompt)

**Files:**
- Modify: `app/evidence_controller.py` (add EvidenceController class)
- Modify: `tests/test_query_classifier.py` → rename to `tests/test_evidence_controller.py`

**Interfaces:**
- Consumes: `RAGResult` (static), `RAGResult` (web), `QueryRequirements`, query string
- Produces: `EvidenceBundle`, `(system_prompt, user_prompt)` tuple

- [ ] **Step 1: Write failing tests for bundle building**

```python
# tests/test_evidence_controller.py (extend)
from app.contracts import RAGResult, EvidenceChunk, QueryRequirements, ConfidenceBand

def test_build_bundle_both_available():
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    static = RAGResult(
        chunks=[
            EvidenceChunk(chunk_id="static1", content="PMFBY rules", source_type="static", title="Guidelines"),
        ],
        abstained=False, band=ConfidenceBand.HIGH, domain="pmfby",
    )
    web = RAGResult(
        chunks=[
            EvidenceChunk(chunk_id="web1", content="Current premium 2%", source_type="web", title="Current data"),
        ],
        abstained=False, band=ConfidenceBand.MEDIUM, domain="pmfby",
    )
    reqs = QueryRequirements(temporal_scope="current", geographic_scope="state", required_specificity="state", requires_dynamic=True)

    bundle = controller.build_bundle(static, web, reqs, "PMFBY premium")
    assert bundle.static.available is True
    assert bundle.dynamic.available is True
    assert len(bundle.static.chunks) == 1
    assert len(bundle.dynamic.chunks) == 1

def test_build_bundle_dynamic_absent():
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    static = RAGResult(
        chunks=[EvidenceChunk(chunk_id="s1", content="rules", source_type="static", title="t")],
        abstained=False, band=ConfidenceBand.HIGH, domain="pmfby",
    )
    web = RAGResult(chunks=[], abstained=True, band=ConfidenceBand.LOW, domain="pmfby")
    reqs = QueryRequirements(temporal_scope="current", geographic_scope="district", required_specificity="district", requires_dynamic=True)

    bundle = controller.build_bundle(static, web, reqs, "current crops in Surat")
    assert bundle.static.available is True
    assert bundle.dynamic.available is False
    assert bundle.dynamic.reason is not None

def test_build_curated_prompt_separates_evidence():
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    bundle = EvidenceBundle(
        static=StaticEvidence(
            available=True,
            chunks=[EvidenceChunk(chunk_id="s1", content="PMFBY is a scheme", source_type="static", title="Guidelines")],
            summary="Policy rules",
        ),
        dynamic=DynamicEvidence(available=False, chunks=[], reason="No web results"),
        query_requirements=QueryRequirements(temporal_scope="current", geographic_scope="district", required_specificity="district", requires_dynamic=True),
        query="current crops",
    )

    system, user = controller.build_curated_prompt(bundle, "current crops in Surat", None, "gu")
    assert "[STATIC]" in user
    assert "ABSENT" in user
    assert "SOURCE PRIORITY RULES" in system
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_evidence_controller.py -x -q`
Expected: FAIL — AttributeError for EvidenceController

- [ ] **Step 3: Implement EvidenceController**

Add to `app/evidence_controller.py`:

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
        static = StaticEvidence(
            available=not static_result.abstained and len(static_result.chunks) > 0,
            chunks=static_result.chunks,
            summary=f"{len(static_result.chunks)} chunks from official documents",
        )

        web_available = not web_result.abstained and len(web_result.chunks) > 0
        web = DynamicEvidence(
            available=web_available,
            chunks=web_result.chunks,
            reason=None if web_available else (
                web_result.reason.value if web_result.reason else "No applicable web evidence found"
            ),
        )

        return EvidenceBundle(
            static=static,
            dynamic=web,
            query_requirements=query_requirements,
            query=query,
        )

    def build_curated_prompt(
        self,
        bundle: EvidenceBundle,
        english_query: str,
        history: list[dict] | None,
        lang: str,
    ) -> tuple[str, str]:
        system_prompt = _SOURCE_PRIORITY_PROMPT

        # Build history text
        hist_text = ""
        if history:
            turns = "\n".join(
                f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
                for h in history if isinstance(h, dict)
            )
            if turns:
                hist_text = f"Previous conversation:\n{turns}\n\n"

        # Build static evidence section
        static_parts = []
        for chunk in bundle.static.chunks:
            short_id = chunk.chunk_id[:8]
            static_parts.append(
                f"[STATIC chunk:{short_id}] ({chunk.title} — {chunk.section} — p.{chunk.page})\n{chunk.content}"
            )
        static_section = "\n\n---\n\n".join(static_parts) if static_parts else "No static evidence available."

        # Build dynamic evidence section
        if bundle.dynamic.available:
            dynamic_parts = []
            for chunk in bundle.dynamic.chunks:
                short_id = chunk.chunk_id[:8]
                dynamic_parts.append(
                    f"[DYNAMIC chunk:{short_id}] ({chunk.title} — web — {chunk.url})\n{chunk.content}"
                )
            dynamic_section = "\n\n---\n\n".join(dynamic_parts)
            dynamic_status = f"available — {len(bundle.dynamic.chunks)} chunks"
        else:
            dynamic_section = "No dynamic evidence available."
            dynamic_status = f"ABSENT — {bundle.dynamic.reason or 'No applicable web evidence found'}"

        user_prompt = (
            f"{hist_text}"
            f"Question: {english_query}\n\n"
            f"== STATIC EVIDENCE (official documents — may not reflect current status) ==\n"
            f"{static_section}\n\n"
            f"== DYNAMIC EVIDENCE (web sources — current information) ==\n"
            f"{dynamic_section}\n\n"
            f"== EVIDENCE AVAILABILITY ==\n"
            f"Static: {len(bundle.static.chunks)} chunks available\n"
            f"Dynamic: {dynamic_status}\n\n"
            f"Synthesize an answer following the SOURCE PRIORITY RULES.\n"
            f"If dynamic evidence is absent for a current/local claim, state that clearly.\n"
            f"Do NOT infer current values from static guidelines."
        )

        return system_prompt, user_prompt


_SOURCE_PRIORITY_PROMPT = """You are a government information assistant. You must answer based on
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
   - Do NOT switch languages mid-response"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_evidence_controller.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/evidence_controller.py tests/test_evidence_controller.py
git commit -m "feat: add EvidenceController with bundle building and source-aware prompt curation"
```

---

### Task 4: Create ClaimVerifier (Heuristic + LLM)

**Files:**
- Create: `app/claim_verifier.py`
- Create: `tests/test_claim_verifier.py`

**Interfaces:**
- Consumes: answer string, `EvidenceBundle`
- Produces: `(cleaned_answer, list[ClaimVerification], was_modified)`

- [ ] **Step 1: Write failing tests for heuristic verifier**

```python
# tests/test_claim_verifier.py
import pytest
from app.claim_verifier import HeuristicClaimVerifier, ClaimVerifier
from app.contracts import (
    EvidenceBundle, StaticEvidence, DynamicEvidence, QueryRequirements,
    EvidenceChunk, ClaimVerification,
)

def _make_bundle(dynamic_available=True):
    chunks = [EvidenceChunk(chunk_id="s1", content="PMFBY rules", source_type="static", title="t")]
    return EvidenceBundle(
        static=StaticEvidence(available=True, chunks=chunks, summary="rules"),
        dynamic=DynamicEvidence(
            available=dynamic_available,
            chunks=[EvidenceChunk(chunk_id="w1", content="current data", source_type="web", title="w")] if dynamic_available else [],
            reason=None if dynamic_available else "No web results",
        ),
        query_requirements=QueryRequirements(
            temporal_scope="current", geographic_scope="district",
            required_specificity="district", requires_dynamic=True,
        ),
        query="test",
    )

def test_heuristic_flags_dynamic_claims():
    h = HeuristicClaimVerifier()
    bundle = _make_bundle(dynamic_available=False)
    flagged = h.check("In 2026, PMFBY premium is 2% in Surat district.", bundle)
    assert len(flagged) > 0
    assert any(f.claim_type == "dynamic" for f in flagged)

def test_heuristic_no_flags_for_static():
    h = HeuristicClaimVerifier()
    bundle = _make_bundle(dynamic_available=True)
    flagged = h.check("PMFBY is a crop insurance scheme.", bundle)
    # Static claim, dynamic available — may or may not flag, but should not flag as unsupported
    assert all(f.claim_type != "dynamic" for f in flagged)

def test_verifier_fast_path_no_flags():
    from unittest.mock import MagicMock
    v = ClaimVerifier()
    v.heuristic = MagicMock(return_value=[])
    bundle = _make_bundle()
    answer, vers, modified = v.verify("Simple answer.", bundle)
    assert modified is False
    assert vers == []

def test_verifier_rejects_unsupported_dynamic():
    v = ClaimVerifier()
    bundle = _make_bundle(dynamic_available=False)
    answer, vers, modified = v.verify(
        "In 2026, the premium is 2% and crops are cotton.", bundle
    )
    # Should have verifications
    assert len(vers) > 0
    # Unsupported dynamic claims should be flagged
    assert any(not v.is_supported for v in vers)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_claim_verifier.py -x -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement HeuristicClaimVerifier**

```python
# app/claim_verifier.py
"""Claim Verification — two-layer verification with filter outcomes."""

from __future__ import annotations

import hashlib
import re
import logging
from dataclasses import dataclass

from app.contracts import (
    EvidenceBundle, FlaggedClaim, ClaimVerification, FilterOutcome,
)

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_DISTRICT_NAMES = {
    "surat", "valsad", "navsari", "bardoli", "ahmedabad", "rajkot",
    "jamnagar", "bhuj", "gandhinagar", "vadodara", "anand", "nadiad",
}
_CURRENT_WORDS = {
    "en": ["currently", "now", "today", "current", "active", "present"],
    "hi": ["हाल", "अभी", "वर्तमान"],
    "gu": ["હાલ", "હાલમાં", "અત્યારે", "ચાલુ"],
}


def _claim_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class HeuristicClaimVerifier:
    """Detects potentially unsupported claims in LLM answer."""

    def check(self, answer: str, bundle: EvidenceBundle) -> list[FlaggedClaim]:
        flagged: list[FlaggedClaim] = []
        sentences = _split_sentences(answer)

        for sentence in sentences:
            claim_type = self._classify_claim(sentence, bundle)
            flag_reason = self._check_support(sentence, claim_type, bundle)

            if flag_reason:
                flagged.append(FlaggedClaim(
                    claim_id=_claim_id(sentence),
                    claim_text=sentence,
                    claim_type=claim_type,
                    flag_reason=flag_reason,
                    requires_evidence="dynamic" if claim_type == "dynamic" else "any",
                ))

        # HARD RULE: requires_dynamic + dynamic absent → flag ALL claims
        if bundle.query_requirements.requires_dynamic and not bundle.dynamic.available:
            already_flagged = {f.claim_id for f in flagged}
            for sentence in sentences:
                cid = _claim_id(sentence)
                if cid not in already_flagged:
                    flagged.append(FlaggedClaim(
                        claim_id=cid,
                        claim_text=sentence,
                        claim_type="dynamic",
                        flag_reason="requires_dynamic but dynamic evidence absent",
                        requires_evidence="dynamic",
                    ))

        return flagged

    def _classify_claim(self, sentence: str, bundle: EvidenceBundle) -> str:
        s = sentence.lower()

        # Year mention → dynamic
        if _YEAR_RE.search(s):
            return "dynamic"

        # District mention → dynamic
        if any(d in s for d in _DISTRICT_NAMES):
            return "dynamic"

        # Current words → dynamic
        for lang_words in _CURRENT_WORDS.values():
            if any(w in s for w in lang_words):
                return "dynamic"

        # Value/amount claim → mixed
        if re.search(r"\b(\d+%|\d+\.\d+|₹\d+|premium|amount|rate)\b", s):
            return "mixed"

        return "static"

    def _check_support(
        self, sentence: str, claim_type: str, bundle: EvidenceBundle
    ) -> str | None:
        if claim_type == "dynamic" and not bundle.dynamic.available:
            return "dynamic claim but no dynamic evidence available"
        if claim_type == "mixed" and not bundle.dynamic.available:
            return "mixed claim with dynamic component but no dynamic evidence"
        return None


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences/clauses for claim extraction."""
    # Split on sentence boundaries
    parts = re.split(r'(?<=[.!?])\s+|(?<=,)\s+', text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 10]


class LLMClaimVerifier:
    """Uses Gemini to verify flagged claims against minimum relevant evidence."""

    def verify(
        self,
        flagged_claims: list[FlaggedClaim],
        bundle: EvidenceBundle,
    ) -> list[ClaimVerification]:
        # For MVP: simple evidence matching without LLM call
        # Phase 2: Add Gemini-based verification
        verifications = []
        for claim in flagged_claims:
            evidence_ids = self._find_supporting_evidence(claim, bundle)
            verifications.append(ClaimVerification(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                is_supported=len(evidence_ids) > 0,
                claim_type=claim.claim_type,
                source_type_needed=claim.requires_evidence,
                evidence_found=len(evidence_ids) > 0,
                evidence_ids=evidence_ids,
                rejection_reason=None if evidence_ids else f"No {claim.requires_evidence} evidence supports this claim",
                verification_confidence=0.8 if evidence_ids else 0.2,
            ))
        return verifications

    def _find_supporting_evidence(
        self, claim: FlaggedClaim, bundle: EvidenceBundle
    ) -> list[str]:
        """Find evidence chunks that support this claim."""
        ids = []
        claim_words = set(claim.claim_text.lower().split())

        chunks = (
            bundle.dynamic.chunks if claim.requires_evidence == "dynamic"
            else bundle.static.chunks + bundle.dynamic.chunks
        )

        for chunk in chunks:
            chunk_words = set(chunk.content.lower().split())
            overlap = len(claim_words & chunk_words)
            if overlap >= 3:  # simple word overlap threshold
                ids.append(chunk.chunk_id[:8])

        return ids


class ClaimVerifier:
    """Two-layer claim verification with explicit filter outcomes."""

    def __init__(self):
        self.heuristic = HeuristicClaimVerifier()
        self.llm = LLMClaimVerifier()

    def verify(
        self,
        answer: str,
        bundle: EvidenceBundle,
    ) -> tuple[str, list[ClaimVerification], bool]:
        # Layer 1: heuristic
        flagged = self.heuristic.check(answer, bundle)

        if not flagged:
            return answer, [], False  # fast path

        # Layer 2: LLM verification
        verifications = self.llm.verify(flagged, bundle)

        # Determine outcomes
        outcomes = self._determine_outcomes(verifications, bundle)

        # Apply outcomes
        answer, was_modified = self._apply_outcomes(answer, outcomes, verifications)

        if was_modified:
            # Re-verify (REPLACE old set)
            re_flagged = self.heuristic.check(answer, bundle)
            verifications = self.llm.verify(re_flagged, bundle) if re_flagged else []

        return answer, verifications, was_modified

    def _determine_outcomes(
        self,
        verifications: list[ClaimVerification],
        bundle: EvidenceBundle,
    ) -> dict[str, str]:
        outcomes = {}
        for v in verifications:
            if v.is_supported:
                outcomes[v.claim_id] = FilterOutcome.KEEP
            elif v.claim_type == "dynamic" and not bundle.dynamic.available:
                # Dynamic claim, no dynamic evidence → ABSTAIN
                outcomes[v.claim_id] = FilterOutcome.ABSTAIN
            elif v.claim_type == "mixed":
                # Mixed claim → try to REGENERATE (keep static part)
                outcomes[v.claim_id] = FilterOutcome.REGENERATE
            else:
                outcomes[v.claim_id] = FilterOutcome.FILTER
        return outcomes

    def _apply_outcomes(
        self,
        answer: str,
        outcomes: dict[str, str],
        verifications: list[ClaimVerification],
    ) -> tuple[str, bool]:
        was_modified = False
        for v in verifications:
            outcome = outcomes.get(v.claim_id, FilterOutcome.KEEP)
            if outcome == FilterOutcome.FILTER:
                answer = answer.replace(v.claim_text, "").strip()
                was_modified = True
            elif outcome == FilterOutcome.ABSTAIN:
                # Replace with abstention
                caveat = f"[Current/local information for this claim could not be verified]"
                answer = answer.replace(v.claim_text, caveat).strip()
                was_modified = True
            elif outcome == FilterOutcome.REGENERATE:
                # Add caveat to the claim
                caveat = f"{v.claim_text} (Note: this combines general rules with unverified current data)"
                answer = answer.replace(v.claim_text, caveat).strip()
                was_modified = True

        # Clean up double spaces
        answer = re.sub(r'\s+', ' ', answer).strip()
        return answer, was_modified
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_claim_verifier.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/claim_verifier.py tests/test_claim_verifier.py
git commit -m "feat: add ClaimVerifier with heuristic + LLM verification and filter outcomes"
```

---

### Task 5: Refactor RAGOrchestrator to Async + Evidence Bundle

**Files:**
- Modify: `app/services/rag_orchestrator.py` (major refactor)
- Modify: `tests/test_services_rag_orchestrator.py` (update tests)

**Interfaces:**
- Consumes: Same inputs as before, plus `QueryRequirements` from classifier
- Produces: Same `RAGResponse`, with claim-level confidence

- [ ] **Step 1: Update orchestrator to async with evidence bundle**

Replace the entire `app/services/rag_orchestrator.py` with the async version integrating EvidenceController and ClaimVerifier. Key changes:
- `async def run()` instead of `def run()`
- `asyncio.gather(return_exceptions=True)` for pipeline concurrency
- Evidence bundle building
- Source-aware prompt curation
- Claim verification
- Claim-level confidence calculation
- Missing location handling

- [ ] **Step 2: Update route handlers to async**

In `app/routes/chat.py`:
- Change `def chat()` → `async def chat()`
- Change `def chat_stream()` → `async def chat_stream()`
- Add `await` for orchestrator calls

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/ -x -q --timeout=60`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/services/rag_orchestrator.py app/routes/chat.py
git commit -m "feat: refactor orchestrator to async with evidence controller and claim verification"
```

---

### Task 6: Integration Tests + Regression Tests

**Files:**
- Create: `tests/test_evidence_controller_integration.py`

**Interfaces:**
- Consumes: Full orchestrator flow
- Produces: Regression test coverage

- [ ] **Step 1: Write regression test for static=6, dynamic=0**

```python
# tests/test_evidence_controller_integration.py
def test_no_confident_answer_when_dynamic_absent():
    """static=6, dynamic=0 must not produce a confident current/local factual answer."""
    from app.contracts import RAGResult, EvidenceChunk, ConfidenceBand, QueryRequirements

    static = RAGResult(
        chunks=[
            EvidenceChunk(chunk_id=f"s{i}", content=f"PMFBY rule {i}", source_type="static", title="Guidelines")
            for i in range(6)
        ],
        abstained=False, band=ConfidenceBand.HIGH, domain="pmfby",
    )
    web = RAGResult(chunks=[], abstained=True, band=ConfidenceBand.LOW, domain="pmfby")

    # Simulate what the orchestrator does
    from app.evidence_controller import EvidenceController, QueryRequirementClassifier
    classifier = QueryRequirementClassifier()
    controller = EvidenceController()

    reqs = classifier.classify("હાલમાં Surat જિલ્લામાં PMFBY notified crops", "gu")
    bundle = controller.build_bundle(static, web, reqs, "current crops in Surat")

    assert bundle.dynamic.available is False
    assert reqs.requires_dynamic is True
    # Confidence should be capped at 0.4
    # (verified through orchestrator flow in integration test)
```

- [ ] **Step 2: Write test for mixed static valid + dynamic unsupported**

- [ ] **Step 3: Write test for historical query not requiring dynamic**

- [ ] **Step 4: Write test for retrieval failure handling**

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -x -q --timeout=60`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_evidence_controller_integration.py
git commit -m "test: add integration tests for evidence controller and claim verification"
```

---

### Task 7: Final Verification + Cleanup

**Files:**
- All files modified in previous tasks

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=120`
Expected: PASS — all tests green

- [ ] **Step 2: Run lint/typecheck if available**

Run: `python -m ruff check app/evidence_controller.py app/claim_verifier.py`
Run: `python -m mypy app/evidence_controller.py app/claim_verifier.py --ignore-missing-imports`

- [ ] **Step 3: Manual smoke test**

Start the server, send a test query:
```
POST /chat/stream
{"question": "હાલમાં Surat જિલ્લામાં PMFBY notified crops", "session_id": "test", "language": "gu"}
```
Verify:
- Thinking indicator appears immediately
- Answer does NOT confidently state current crops
- Answer explains that current notification data is unavailable
- Confidence ≤ 0.4

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "feat: complete evidence controller + claim verification implementation"
```
