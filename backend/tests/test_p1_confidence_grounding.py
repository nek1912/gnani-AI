"""P1 regression: final confidence must reflect grounding outcome.

Contract under test:
- confidence is currently derived from retrieval bands only.
- A repaired answer (unsupported content removed) must NOT retain HIGH.
- Smallest defensible downgrade: cap repaired-but-supportable answers at
  0.6 / MEDIUM (below the 0.7 HIGH threshold in both the orchestrator and
  the chat _confidence_level mapping), preserving LOW/MEDIUM otherwise.
- Fully supported answers: behavior unchanged.
- Grounding abstention: LOW/0 unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

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


def _make_chunk(
    chunk_id: str = "abc12345def67890",
    content: str = "PMFBY launched in 2016. PMFBY provides crop insurance.",
    source_type: str = "static",
    dense_score: float = 0.9,
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type=source_type,  # type: ignore[arg-type]
        title="PMFBY Guidelines",
        url="https://pmfby.gov.in",
        page=1,
        section="Overview",
        domain="pmfby",
        jurisdiction="central",
        state=None,
        dense_score=dense_score,
    )


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


def _make_classification() -> QueryClassification:
    return QueryClassification(
        domain="pmfby",
        jurisdiction="central",
        state=None,
        intent="INFORMATIONAL",
        confidence=0.9,
    )


def _make_bundle(chunks: list[EvidenceChunk]) -> EvidenceBundle:
    return EvidenceBundle(
        static=StaticEvidence(
            available=True, chunks=chunks, summary="test static"
        ),
        dynamic=DynamicEvidence(available=False, chunks=[]),
        query_requirements=QueryRequirements(
            temporal_scope="general",
            geographic_scope="none",
            required_specificity="general",
            requires_dynamic=False,
        ),
        query="test query",
    )


def _balanced_assessment() -> EvidenceAssessment:
    return EvidenceAssessment(
        source_role=SourceRole.STATIC_PRIMARY,
        sufficiency=EvidenceSufficiency.SUFFICIENT,
        static_quality="high",
        web_quality="low",
        assessment_text="test",
    )


async def _run_orchestrator(
    orch: RAGOrchestrator,
    static_result: RAGResult,
    web_result: RAGResult,
    llm_answer: str,
):
    bundle = _make_bundle(static_result.chunks)
    with (
        patch.object(orch._static_rag, "retrieve", return_value=static_result),
        patch.object(orch._web_rag, "retrieve", return_value=web_result),
        patch.object(orch._evidence_controller, "build_bundle", return_value=bundle),
        patch.object(
            orch._evidence_controller, "assess_evidence", return_value=_balanced_assessment()
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
            classification=_make_classification(),
            history=None,
            lang="en",
            session_id="sess-p1",
        )


# ---------------------------------------------------------------------------
# A. Fully grounded answer — existing behavior preserved
# ---------------------------------------------------------------------------


class TestFullyGroundedPreserved:
    async def test_fully_supported_high_stays_high(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk()
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.HIGH)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        # No numeric/date/entity/condition/geography claims beyond evidence.
        llm_answer = "PMFBY provides crop insurance [chunk:abc12345]."
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is False
        assert resp.confidence == 0.9
        assert resp.confidence_level == ConfidenceBand.HIGH
        assert "crop insurance" in resp.answer


# ---------------------------------------------------------------------------
# B. Repaired answer — must be downgraded from HIGH
# ---------------------------------------------------------------------------


class TestRepairedDowngraded:
    async def test_repaired_answer_capped_at_medium(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk()
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.HIGH)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        llm_answer = (
            "PMFBY provides crop insurance [chunk:abc12345]. "
            "PMFBY helps all farmers in Gujarat with full support [chunk:abc12345]."
        )
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is False
        # Unsupported Gujarat sentence must be gone.
        assert "Gujarat" not in resp.answer
        assert "crop insurance" in resp.answer
        # Critical: must NOT retain HIGH.
        assert resp.confidence_level != ConfidenceBand.HIGH
        assert resp.confidence < 0.7
        # Exact contract: capped at 0.6 / MEDIUM.
        assert resp.confidence == 0.6
        assert resp.confidence_level == ConfidenceBand.MEDIUM


# ---------------------------------------------------------------------------
# C. Grounding abstention — LOW/0 preserved
# ---------------------------------------------------------------------------


class TestGroundingAbstention:
    async def test_unsupportable_answer_abstains_low_zero(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk()
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.HIGH)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        # Only an unsupported geography claim; repair leaves nothing supportable.
        llm_answer = "PMFBY helps all farmers in Gujarat with full support [chunk:abc12345]."
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is True
        assert resp.confidence == 0.0
        assert resp.confidence_level == ConfidenceBand.LOW


# ---------------------------------------------------------------------------
# D. HIGH retrieval + grounding repair — retrieval HIGH must not leak
# ---------------------------------------------------------------------------


class TestHighRetrievalRepairLeak:
    async def test_high_retrieval_repair_does_not_leak_high(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk(dense_score=0.95)
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.HIGH)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        # Sanity: retrieval-only confidence would be HIGH (0.9).
        base_conf, base_band = orch._calculate_confidence(
            static_result, web_result, True, False, []
        )
        assert base_conf == 0.9
        assert base_band == ConfidenceBand.HIGH
        llm_answer = (
            "PMFBY provides crop insurance [chunk:abc12345]. "
            "PMFBY helps all farmers in Gujarat with full support [chunk:abc12345]."
        )
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is False
        assert resp.confidence != base_conf
        assert resp.confidence < 0.7
        assert resp.confidence_level == ConfidenceBand.MEDIUM


# ---------------------------------------------------------------------------
# E. MEDIUM retrieval + fully grounded — no upgrade
# ---------------------------------------------------------------------------


class TestMediumRetrievalNoUpgrade:
    async def test_medium_retrieval_supported_stays_as_is(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk(dense_score=0.4)
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.MEDIUM)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        llm_answer = "PMFBY provides crop insurance [chunk:abc12345]."
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is False
        # Static MEDIUM alone -> 0.7 / HIGH under current bands; the fix must
        # not UPGRADE a fully-grounded answer beyond existing behavior.
        assert resp.confidence == 0.7
        assert resp.confidence_level == ConfidenceBand.HIGH


# ---------------------------------------------------------------------------
# F. LOW retrieval + fully grounded — LOW intact
# ---------------------------------------------------------------------------


class TestLowRetrievalIntact:
    async def test_low_retrieval_supported_stays_low(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk(dense_score=0.3)
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.LOW)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        llm_answer = "PMFBY provides crop insurance [chunk:abc12345]."
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.abstained is False
        assert resp.confidence == 0.4
        assert resp.confidence_level == ConfidenceBand.LOW


# ---------------------------------------------------------------------------
# G. No grounding change — byte-for-byte confidence preserved
# ---------------------------------------------------------------------------


class TestNoGroundingChangeUnchanged:
    async def test_supported_answer_confidence_unchanged(self):
        orch = RAGOrchestrator(_make_settings())
        chunk = _make_chunk()
        static_result = _make_rag_result(chunks=[chunk], band=ConfidenceBand.HIGH)
        web_result = _make_rag_result(abstained=True, band=ConfidenceBand.LOW)
        expected_conf, expected_band = orch._calculate_confidence(
            static_result, web_result, True, False, []
        )
        llm_answer = "PMFBY provides crop insurance [chunk:abc12345]."
        resp = await _run_orchestrator(orch, static_result, web_result, llm_answer)
        assert resp.confidence == expected_conf
        assert resp.confidence_level == expected_band
