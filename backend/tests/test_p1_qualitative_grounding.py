"""P1 qualitative grounding: geographic-scope claims.

Known gap (verified pre-fix): the grounding machinery extracts/checks only
numbers, dates, entities, and conditions. A qualitative answer such as
"helps all farmers in Gujarat with full support" passes against evidence
"launched in 2016" with HIGH confidence because no extractor fires.

Safe scope for THIS file: explicit geographic-scope claims built from a
closed gazetteer of canonical Indian state names plus closed marker sets
(exclusivity: only/solely/exclusively/limited to/restricted to/confined to;
universality: all/every/each/everyone/everybody). No similarity thresholds,
no open-vocabulary noun checks, no LLM judge.

Covered (must be flagged or repaired):
  A. identical supported qualitative claim -> PASS (guard)
  C. universal + state with generic evidence -> FLAG
  D. exclusive state vs national evidence -> FLAG
  D2. state substitution (different explicit state) -> FLAG
  D3. exclusive state contradicted by multi-state evidence -> FLAG
  H. modest paraphrase without scope words -> PASS (guard)

Documented gaps (xfail strict: tripwire if behavior ever changes):
  B. novel topic nouns ("housing assistance")
  E. pure universal/absolute without a state anchor
  F. mixed supported + guaranteed-absolute sentence
  G. negation polarity flip

All tests use deterministic evidence/answers. No live providers, LLM,
Supabase, SerpApi, Tavily, or Firecrawl calls.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.answer_grounding import verify_answer_grounding
from app.config import Settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    DynamicEvidence,
    EvidenceAssessment,
    EvidenceBundle,
    EvidenceChunk,
    EvidenceSufficiency,
    QueryRequirements,
    RAGResult,
    SourceRole,
    StaticEvidence,
)
from app.services.rag_orchestrator import RAGOrchestrator
from app.web_rag.query_classifier import QueryClassification


# ---------------------------------------------------------------------------
# Helpers (deterministic fakes only)
# ---------------------------------------------------------------------------


def _make_chunk(content: str, chunk_id: str = "abc12345def67890") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type="static",
        title="Test Document",
        section="Test Section",
        domain="pmfby",
        jurisdiction="central",
        state=None,
        dense_score=0.8,
    )


def _make_settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq-key",
        "gemini_api_key": "test-gemini-key",
        "jina_api_key": "test-jina-key",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "reranker_enabled": False,
        "sarvam_api_key": "",
        "sarvam_api_key_2": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _rag(
    chunks: list[EvidenceChunk] | None = None,
    abstained: bool = False,
) -> RAGResult:
    return RAGResult(
        chunks=chunks or [],
        abstained=abstained,
        reason=None if not abstained else AbstentionReason.NO_ELIGIBLE_SOURCE,
        band=ConfidenceBand.MEDIUM,
        domain="pmfby",
    )


def _classification() -> QueryClassification:
    return QueryClassification(
        domain="pmfby",
        jurisdiction="central",
        state=None,
        intent="INFORMATIONAL",
        confidence=0.85,
    )


def _bundle(web_chunks: list[EvidenceChunk]) -> EvidenceBundle:
    return EvidenceBundle(
        static=StaticEvidence(available=False, chunks=[], summary="none"),
        dynamic=DynamicEvidence(available=True, chunks=web_chunks),
        query_requirements=QueryRequirements(
            temporal_scope="current",
            geographic_scope="state",
            required_specificity="state",
            requires_dynamic=True,
        ),
        query="test query",
    )


def _assessment() -> EvidenceAssessment:
    return EvidenceAssessment(
        source_role=SourceRole.WEB_PRIMARY,
        sufficiency=EvidenceSufficiency.SUFFICIENT,
        static_quality="low",
        web_quality="medium",
        assessment_text="test",
    )


async def _run_orchestrator(
    grounded_answer_text: str,
    web_chunks: list[EvidenceChunk],
):
    orch = RAGOrchestrator(_make_settings())
    sr = _rag(abstained=True)
    wr = _rag(chunks=web_chunks)
    with patch.object(orch._static_rag, "retrieve", return_value=sr), \
        patch.object(orch._web_rag, "retrieve", return_value=wr), \
        patch.object(
            orch._evidence_controller, "build_bundle",
            return_value=_bundle(web_chunks),
        ), \
        patch.object(
            orch._evidence_controller, "assess_evidence", return_value=_assessment(),
        ), \
        patch.object(
            orch._evidence_controller, "build_curated_prompt",
            return_value=("system", "user prompt"),
        ), \
        patch(
            "app.services.rag_orchestrator.grounded_answer",
            return_value=grounded_answer_text,
        ):
        return await orch.run(
            query="test query",
            english_query="test query",
            embedding=[0.1] * 768,
            domain="pmfby",
            state=None,
            classification=_classification(),
            history=None,
            lang="en",
            session_id="sess-qual",
        )


# ---------------------------------------------------------------------------
# A. Supported identical qualitative claim (guard: must PASS)
# ---------------------------------------------------------------------------


class TestASupportedIdentical:
    def test_identical_qualitative_passes(self):
        chunk = _make_chunk(
            "Farmers with an active PMFBY policy may submit claims "
            "through the prescribed process."
        )
        result = verify_answer_grounding(
            "Farmers with an active PMFBY policy may submit claims "
            "through the prescribed process.",
            [chunk],
        )
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Headline known failure: "launched in 2016" vs "all farmers in Gujarat"
# ---------------------------------------------------------------------------


class TestHeadlineFailure:
    def test_universal_state_vs_bare_year_evidence_flagged(self):
        chunk = _make_chunk("The scheme was launched in 2016.")
        result = verify_answer_grounding(
            "The scheme helps all farmers in Gujarat with full support.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "geography" for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# C. Unsupported universal + state with generic evidence
# ---------------------------------------------------------------------------


class TestCUniversalState:
    def test_universal_state_with_generic_evidence_flagged(self):
        chunk = _make_chunk(
            "PMFBY provides crop insurance against crop loss from sowing to harvest."
        )
        result = verify_answer_grounding(
            "All farmers in Gujarat are eligible.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "geography" for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# D. Exclusive / substituted geographic claims
# ---------------------------------------------------------------------------


class TestDExclusiveGeography:
    def test_exclusive_state_vs_national_evidence_flagged(self):
        chunk = _make_chunk("The scheme is implemented nationally.")
        result = verify_answer_grounding(
            "The scheme is available only in Gujarat.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "geography" for c in result.unsupported_claims)

    def test_state_substitution_flagged(self):
        chunk = _make_chunk("The scheme is available in Maharashtra.")
        result = verify_answer_grounding(
            "The scheme is available in Gujarat.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "geography" for c in result.unsupported_claims)

    def test_exclusive_contradicted_by_multi_state_evidence_flagged(self):
        chunk = _make_chunk("The scheme covers farmers in Gujarat and Maharashtra.")
        result = verify_answer_grounding(
            "The scheme is available only in Gujarat.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "geography" for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# Guards: legitimate state mentions must NOT be flagged
# ---------------------------------------------------------------------------


class TestGeoGuards:
    def test_inclusive_state_with_national_evidence_passes(self):
        """Inclusive personalization ("in Gujarat") against national-scope
        evidence is legitimate and must not be flagged."""
        chunk = _make_chunk("The scheme is implemented nationally.")
        result = verify_answer_grounding(
            "The scheme is available in Gujarat.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_exclusive_state_with_matching_evidence_passes(self):
        chunk = _make_chunk("The scheme is available only in Gujarat.")
        result = verify_answer_grounding(
            "The scheme is available only in Gujarat.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_plain_answer_without_states_unaffected(self):
        chunk = _make_chunk("PMFBY premium is 2% for kharif crops.")
        result = verify_answer_grounding(
            "PMFBY premium is 2% for kharif crops.",
            [chunk],
        )
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# H. Modest paraphrase without scope words (guard: must PASS)
# ---------------------------------------------------------------------------


class TestHParaphrase:
    def test_modest_paraphrase_passes(self):
        chunk = _make_chunk(
            "Farmers with an active PMFBY policy may submit claims "
            "through the prescribed process."
        )
        result = verify_answer_grounding(
            "Growers holding a valid policy can file claims via the official procedure.",
            [chunk],
        )
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Orchestrator end-to-end: repair / abstain contract for geography
# ---------------------------------------------------------------------------


class TestOrchestratorGeography:
    async def test_mixed_supported_plus_exclusive_repaired(self):
        chunks = [_make_chunk("PMFBY premium is 2% for kharif crops.")]
        response = await _run_orchestrator(
            "PMFBY premium is 2% for kharif crops. "
            "The scheme is available only in Gujarat. [chunk:abc12345]",
            chunks,
        )
        assert response.abstained is False
        assert "2%" in response.answer
        assert "Gujarat" not in response.answer

    async def test_single_exclusive_sentence_abstains(self):
        chunks = [_make_chunk("The scheme is implemented nationally.")]
        response = await _run_orchestrator(
            "The scheme is available only in Gujarat. [chunk:abc12345]",
            chunks,
        )
        assert response.abstained is True
        assert response.confidence == 0.0


# ---------------------------------------------------------------------------
# Documented gaps: strict xfail tripwires (XPASS fails the suite)
# ---------------------------------------------------------------------------


class TestDocumentedGaps:
    @pytest.mark.xfail(
        strict=True,
        reason="B: novel topic nouns need open-vocabulary checking (forbidden heuristic)",
    )
    def test_unrelated_topic_flagged(self):
        chunk = _make_chunk("PMFBY guidelines describe crop-loss assessment.")
        result = verify_answer_grounding(
            "PMFBY provides free housing assistance to every farmer.",
            [chunk],
        )
        assert result.has_unsupported_claims is True

    @pytest.mark.xfail(
        strict=True,
        reason="E: pure universal/absolute without a state anchor has no reliable lexical check",
    )
    def test_pure_universal_without_state_flagged(self):
        chunk = _make_chunk(
            "Eligible farmers may receive assistance subject to the applicable conditions."
        )
        result = verify_answer_grounding(
            "Every farmer receives full assistance.",
            [chunk],
        )
        assert result.has_unsupported_claims is True

    @pytest.mark.xfail(
        strict=True,
        reason="F: absolute-guarantee sentence without a state anchor is not checkable",
    )
    def test_mixed_guarantee_portion_flagged(self):
        chunk = _make_chunk("PMFBY premium is 2% for kharif crops.")
        result = verify_answer_grounding(
            "PMFBY premium is 2% for kharif crops. "
            "The government also guarantees full financial support to every applicant.",
            [chunk],
        )
        assert result.has_unsupported_claims is True

    @pytest.mark.xfail(
        strict=True,
        reason="G: negation polarity flip needs predicate-level semantics, not lexical presence",
    )
    def test_negation_flip_flagged(self):
        chunk = _make_chunk("Applicants must submit document X.")
        result = verify_answer_grounding(
            "Applicants do not need document X.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
