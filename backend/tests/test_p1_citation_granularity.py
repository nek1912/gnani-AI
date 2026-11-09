"""P1 regression: citation granularity / claim-to-evidence binding.

Defect: grounding checks claims against CONCATENATED evidence text, so a
claim cited to chunk A passes when only uncited chunk B contains the fact.

Invariant under test: for a claim with an explicit citation, the CITED
evidence item(s) must individually support the claim. Uncited evidence must
not silently rescue a cited claim. Multi-citation sentences may be supported
by the UNION of their cited chunks. Sentences without citations keep the
legacy whole-pool check (citation-free direct calls and single trailing
citations must not regress).
"""
from __future__ import annotations

from unittest.mock import patch

from app.answer_grounding import verify_answer_grounding
from app.citation_verifier import VerificationResult
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


CHUNK_A_ID = "aaaaaaaa11111111"
CHUNK_B_ID = "bbbbbbbb22222222"
CHUNK_C_ID = "cccccccc33333333"

CHUNK_A_CONTENT = "PMFBY covers notified crops."
CHUNK_B_CONTENT = "Claims must be reported within 72 hours."


def _make_chunk(chunk_id: str, content: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type="static",  # type: ignore[arg-type]
        title="Test Document",
        url="",
        page=1,
        section="Overview",
        domain="pmfby",
        jurisdiction="central",
        state=None,
        dense_score=0.9,
    )


def _chunks_ab() -> list[EvidenceChunk]:
    return [
        _make_chunk(CHUNK_A_ID, CHUNK_A_CONTENT),
        _make_chunk(CHUNK_B_ID, CHUNK_B_CONTENT),
    ]


# ---------------------------------------------------------------------------
# Direct grounding: wrong-chunk citation must NOT pass (the core defect)
# ---------------------------------------------------------------------------


class TestWrongChunkCitation:
    def test_wrong_chunk_citation_fails(self):
        result = verify_answer_grounding(
            "Claims must be reported within 72 hours. [chunk:aaaaaaaa]",
            _chunks_ab(),
        )
        assert result.has_unsupported_claims is True

    def test_correct_single_chunk_citation_passes(self):
        result = verify_answer_grounding(
            "PMFBY covers notified crops. [chunk:aaaaaaaa]",
            _chunks_ab(),
        )
        assert result.has_unsupported_claims is False

    def test_uncited_supporting_chunk_does_not_rescue(self):
        # Cited chunk A lacks the fact; supporting chunk B is uncited.
        result = verify_answer_grounding(
            "Claims must be reported within 72 hours. [chunk:aaaaaaaa]",
            _chunks_ab(),
        )
        assert result.has_unsupported_claims is True
        assert any("must be" in c.claim_text for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# Multi-citation support must be preserved (no overcorrection)
# ---------------------------------------------------------------------------


class TestMultiCitationSupport:
    def test_union_of_cited_chunks_supports(self):
        chunks = [
            _make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured."),
            _make_chunk(CHUNK_B_ID, "The late fee is 5% of the dues."),
        ]
        result = verify_answer_grounding(
            "The premium is 2% and the late fee is 5%. "
            "[chunk:aaaaaaaa][chunk:bbbbbbbb]",
            chunks,
        )
        assert result.has_unsupported_claims is False

    def test_single_citation_of_split_fact_fails(self):
        chunks = [
            _make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured."),
            _make_chunk(CHUNK_B_ID, "The late fee is 5% of the dues."),
        ]
        result = verify_answer_grounding(
            "The premium is 2% and the late fee is 5%. [chunk:aaaaaaaa]",
            chunks,
        )
        assert result.has_unsupported_claims is True
        assert any("5%" in c.claim_text for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# Multiple claims with different citations are checked independently
# ---------------------------------------------------------------------------


class TestPerClaimCitationBinding:
    def test_each_claim_against_own_citation_passes(self):
        chunks = [
            _make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured."),
            _make_chunk(CHUNK_B_ID, "The deadline is 31 March 2025."),
        ]
        result = verify_answer_grounding(
            "The premium is 2%. [chunk:aaaaaaaa] "
            "The deadline is 31 March 2025. [chunk:bbbbbbbb]",
            chunks,
        )
        assert result.has_unsupported_claims is False

    def test_swapped_citations_fail(self):
        chunks = [
            _make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured."),
            _make_chunk(CHUNK_B_ID, "The deadline is 31 March 2025."),
        ]
        result = verify_answer_grounding(
            "The premium is 2%. [chunk:bbbbbbbb] "
            "The deadline is 31 March 2025. [chunk:aaaaaaaa]",
            chunks,
        )
        assert result.has_unsupported_claims is True


# ---------------------------------------------------------------------------
# Citation-free answers keep the legacy whole-pool contract
# ---------------------------------------------------------------------------


class TestCitationFreeContract:
    def test_citation_free_supported_answer_passes(self):
        result = verify_answer_grounding(
            "The premium is 2% of the sum insured.",
            [_make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured.")],
        )
        assert result.has_unsupported_claims is False

    def test_citation_free_unsupported_answer_fails(self):
        result = verify_answer_grounding(
            "The premium is 12% of the sum insured.",
            [_make_chunk(CHUNK_A_ID, "The premium is 2% of the sum insured.")],
        )
        assert result.has_unsupported_claims is True

    def test_uncited_sentence_uses_whole_pool(self):
        # First sentence uncited but supported by pool; must not newly fail.
        chunks = [_make_chunk(CHUNK_A_ID, "PMFBY premium is 2% for kharif crops.")]
        result = verify_answer_grounding(
            "PMFBY premium is 2% for kharif crops. "
            "The scheme is available only in Gujarat. [chunk:aaaaaaaa]",
            chunks,
        )
        # Only the Gujarat sentence is unsupported, not the uncited first one.
        assert result.has_unsupported_claims is True
        assert all(
            "2%" not in c.claim_text for c in result.unsupported_claims
        )


# ---------------------------------------------------------------------------
# Dangling citations fail closed at the grounding layer
# ---------------------------------------------------------------------------


class TestInvalidCitationAtGrounding:
    def test_dangling_citation_fails_closed(self):
        chunks = [_make_chunk(CHUNK_A_ID, "Claims must be reported quickly.")]
        result = verify_answer_grounding(
            "Claims must be reported quickly. [chunk:ffffffff]",
            chunks,
        )
        assert result.has_unsupported_claims is True


# ---------------------------------------------------------------------------
# Distractor chunks must neither rescue nor break a correctly cited claim
# ---------------------------------------------------------------------------


class TestDistractorChunks:
    def test_correct_citation_with_distractors_passes(self):
        chunks = [
            _make_chunk(CHUNK_A_ID, CHUNK_A_CONTENT),
            _make_chunk(CHUNK_B_ID, CHUNK_B_CONTENT),
            _make_chunk(CHUNK_C_ID, "The helpline number is 1800-419-3333."),
        ]
        result = verify_answer_grounding(
            "PMFBY covers notified crops. [chunk:aaaaaaaa]",
            chunks,
        )
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Orchestrator end-to-end (shared grounding path for chat + streaming)
# ---------------------------------------------------------------------------


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
        "answer_grounding_llm_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_rag_result(
    chunks: list[EvidenceChunk] | None = None,
    abstained: bool = False,
    band: ConfidenceBand | None = None,
) -> RAGResult:
    return RAGResult(
        chunks=chunks or [],
        abstained=abstained,
        reason=None if not abstained else AbstentionReason.NO_ELIGIBLE_SOURCE,
        band=band,
        domain="pmfby",
    )


def _make_bundle(chunks: list[EvidenceChunk]) -> EvidenceBundle:
    return EvidenceBundle(
        static=StaticEvidence(available=True, chunks=chunks, summary="test"),
        dynamic=DynamicEvidence(available=False, chunks=[]),
        query_requirements=QueryRequirements(
            temporal_scope="general",
            geographic_scope="none",
            required_specificity="general",
            requires_dynamic=False,
        ),
        query="test query",
    )


def _assessment() -> EvidenceAssessment:
    return EvidenceAssessment(
        source_role=SourceRole.STATIC_PRIMARY,
        sufficiency=EvidenceSufficiency.SUFFICIENT,
        static_quality="high",
        web_quality="low",
        assessment_text="test",
    )


async def _run_orchestrator(llm_answer: str, chunks: list[EvidenceChunk]):
    orch = RAGOrchestrator(_make_settings())
    static_result = _make_rag_result(chunks=chunks, band=ConfidenceBand.HIGH)
    web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
    classification = QueryClassification(
        domain="pmfby",
        jurisdiction="central",
        state=None,
        intent="INFORMATIONAL",
        confidence=0.9,
    )
    with (
        patch.object(orch._static_rag, "retrieve", return_value=static_result),
        patch.object(orch._web_rag, "retrieve", return_value=web_result),
        patch.object(
            orch._evidence_controller, "build_bundle",
            return_value=_make_bundle(chunks),
        ),
        patch.object(
            orch._evidence_controller, "assess_evidence", return_value=_assessment()
        ),
        patch.object(
            orch._evidence_controller,
            "build_curated_prompt",
            return_value=("system", "user prompt"),
        ),
        patch(
            "app.services.rag_orchestrator.grounded_answer", return_value=llm_answer
        ),
        patch(
            "app.services.rag_orchestrator.verify_citations",
            return_value=VerificationResult(is_valid=True),
        ),
    ):
        return await orch.run(
            query="PMFBY help",
            english_query="PMFBY help",
            embedding=[0.1] * 768,
            domain="pmfby",
            state=None,
            classification=classification,
            history=None,
            lang="en",
            session_id="sess-cit-gran",
        )


class TestOrchestratorCitationBinding:
    async def test_wrong_cited_sentence_repaired_and_capped(self):
        resp = await _run_orchestrator(
            "PMFBY covers notified crops. [chunk:aaaaaaaa] "
            "Claims must be reported within 72 hours. [chunk:aaaaaaaa]",
            _chunks_ab(),
        )
        assert resp.abstained is False
        assert "notified crops" in resp.answer
        assert "72 hours" not in resp.answer
        # Grounding repair path: prior confidence guarantee preserved.
        assert resp.confidence == 0.6
        assert resp.confidence_level == ConfidenceBand.MEDIUM

    async def test_correct_citations_preserve_high(self):
        resp = await _run_orchestrator(
            "PMFBY covers notified crops. [chunk:aaaaaaaa] "
            "Claims must be reported within 72 hours. [chunk:bbbbbbbb]",
            _chunks_ab(),
        )
        assert resp.abstained is False
        assert "notified crops" in resp.answer
        assert "72 hours" in resp.answer
        assert resp.confidence == 0.9
        assert resp.confidence_level == ConfidenceBand.HIGH

    async def test_single_wrong_cited_sentence_abstains(self):
        resp = await _run_orchestrator(
            "Claims must be reported within 72 hours. [chunk:aaaaaaaa]",
            _chunks_ab(),
        )
        assert resp.abstained is True
        assert resp.confidence == 0.0
        assert resp.confidence_level == ConfidenceBand.LOW
