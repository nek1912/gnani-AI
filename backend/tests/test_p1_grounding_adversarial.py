"""P1 adversarial grounding matrix: evidence-sufficiency / answer-grounding.

Every test uses deterministic fakes (mocked pipelines + mocked LLM).
No live SerpApi/Tavily/Firecrawl/LLM/Supabase calls.

Map to the required matrix:
  A. no evidence            -> no unsupported substantive answer
  B. irrelevant evidence    -> abstained-pipeline chunks never citable
  C. correct evidence       -> normal grounded answer (guard)
  D. partial evidence       -> substring must not count as support
  E. conflicting evidence   -> wrong number flagged, both sources preserved
  F. invalid citation       -> repair removes the unsupported sentence
  G. citation-not-support   -> valid ID citing wrong number does not ground
  H. verifier failure       -> exceptions abstain, never fail open
  I. weak/unverified evidence -> fail closed (web gate + source verifier)
  J. mixed claims           -> Claim 2 removed, Claim 1 kept (not silent pass)
"""

from __future__ import annotations

from unittest.mock import patch

from app.answer_grounding import UnsupportedClaim, verify_answer_grounding
from app.config import Settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceAssessment,
    EvidenceChunk,
    EvidenceSufficiency,
    DynamicEvidence,
    EvidenceBundle,
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


def _chunk(
    chunk_id: str = "abc12345def67890",
    content: str = "PMFBY premium is 2% for kharif crops.",
    source_type: str = "web",
    domain: str = "pmfby",
    dense_score: float = 0.9,
    url: str = "https://pmfby.gov.in",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type=source_type,
        title="PMFBY doc",
        url=url,
        page=1,
        section="Overview",
        domain=domain,
        jurisdiction="central",
        state=None,
        dense_score=dense_score,
    )


def _rag(
    chunks: list[EvidenceChunk] | None = None,
    abstained: bool = False,
    reason: AbstentionReason | None = None,
) -> RAGResult:
    return RAGResult(
        chunks=chunks or [],
        abstained=abstained,
        reason=reason,
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
    static_result: RAGResult | None = None,
    web_abstained: bool = False,
):
    orch = RAGOrchestrator(_make_settings())
    sr = (
        static_result
        if static_result is not None
        else _rag(abstained=True, reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
    )
    wr = _rag(chunks=web_chunks, abstained=web_abstained)
    with patch.object(orch._static_rag, "retrieve", return_value=sr), \
        patch.object(orch._web_rag, "retrieve", return_value=wr), \
        patch.object(
            orch._evidence_controller, "build_bundle",
            return_value=_bundle(web_chunks if not web_abstained else []),
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
            session_id="sess-adv",
        )


# ---------------------------------------------------------------------------
# A. No evidence
# ---------------------------------------------------------------------------


class TestANoEvidence:
    def test_nonempty_answer_with_zero_chunks_is_unsupported(self):
        """Unit: a factual answer with no evidence must not verify clean."""
        result = verify_answer_grounding("The premium is 12% per annum.", [])
        assert result.has_unsupported_claims is True

    def test_empty_answer_with_zero_chunks_stays_clean(self):
        """Guard: an empty answer makes no claims, so nothing is unsupported."""
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    async def test_both_pipelines_abstained_still_abstains(self):
        """Guard: existing safe-abstention path is intact."""
        orch = RAGOrchestrator(_make_settings())
        sr = _rag(abstained=True, reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
        wr = _rag(abstained=True, reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
        with patch.object(orch._static_rag, "retrieve", return_value=sr), \
            patch.object(orch._web_rag, "retrieve", return_value=wr):
            response = await orch.run(
                query="q",
                english_query="q",
                embedding=[0.1] * 768,
                domain="pmfby",
                state=None,
                classification=_classification(),
                history=None,
                lang="en",
                session_id="sess-adv-a",
            )
        assert response.abstained is True
        assert response.confidence == 0.0


# ---------------------------------------------------------------------------
# B. Irrelevant evidence (abstained pipeline must not leak into citations)
# ---------------------------------------------------------------------------


class TestBIrrelevantEvidence:
    def test_prompt_hides_abstained_static_chunks(self):
        """Abstained static chunks must not reach the LLM prompt."""
        from app.evidence_controller import EvidenceController

        bad = _chunk(
            chunk_id="bad11111deadbeef",
            content="IRRELEVANT_WRONG_DOMAIN_SECRETS",
            source_type="static",
            domain="wrong",
        )
        good = _chunk()
        sr = _rag(chunks=[bad], abstained=True, reason=AbstentionReason.DOMAIN_MISMATCH)
        wr = _rag(chunks=[good])
        controller = EvidenceController()
        from app.evidence_controller import QueryRequirementClassifier

        qr = QueryRequirementClassifier().classify("what is premium?", "en")
        bundle = controller.build_bundle(sr, wr, qr, "what is premium?")
        _, user_prompt = controller.build_curated_prompt(
            bundle, "what is premium?", None, "en"
        )
        assert "IRRELEVANT_WRONG_DOMAIN_SECRETS" not in user_prompt
        assert "2%" in user_prompt

    async def test_abstained_pipeline_chunks_not_citable(self):
        """A marker pointing at an abstained-pipeline chunk must not survive."""
        bad = _chunk(
            chunk_id="bad11111deadbeef",
            content="IRRELEVANT_WRONG_DOMAIN_SECRETS",
            source_type="static",
            domain="wrong",
        )
        good = _chunk(content="PMFBY premium is 2% for kharif crops.")
        sr = _rag(chunks=[bad], abstained=True, reason=AbstentionReason.DOMAIN_MISMATCH)
        response = await _run_orchestrator(
            "PMFBY premium is 2% for kharif crops. "
            "[chunk:bad11111] [chunk:abc12345]",
            [good],
            static_result=sr,
        )
        cited = {c["chunk_id"] for c in response.citations}
        assert "bad11111" not in cited
        assert response.abstained is False
        assert "2%" in response.answer


# ---------------------------------------------------------------------------
# C. Correct evidence (guard)
# ---------------------------------------------------------------------------


class TestCCorrectEvidence:
    async def test_supported_answer_returned_normally(self):
        chunks = [_chunk(content="PMFBY premium is 2% for kharif crops.")]
        response = await _run_orchestrator(
            "PMFBY premium is 2% for kharif crops. [chunk:abc12345]",
            chunks,
        )
        assert response.abstained is False
        assert "2%" in response.answer
        assert response.confidence > 0.0


# ---------------------------------------------------------------------------
# D. Partial evidence (substring must not count as support)
# ---------------------------------------------------------------------------


class TestDPartialEvidence:
    def test_shorter_number_inside_longer_number_is_unsupported(self):
        """'2%' must not verify against evidence that only states '12%'."""
        chunk = _chunk(
            chunk_id="a0eebc99",
            content="The premium is 12% of the sum insured.",
            source_type="static",
        )
        result = verify_answer_grounding("The premium is 2% of the sum.", [chunk])
        assert result.has_unsupported_claims is True
        assert any("2%" in c.claim_text for c in result.unsupported_claims)

    def test_exact_number_still_supported(self):
        """Guard: an exact number match must keep verifying clean."""
        chunk = _chunk(
            chunk_id="a0eebc99",
            content="The premium is 2% of the sum insured.",
            source_type="static",
        )
        result = verify_answer_grounding("The premium is 2% of the sum.", [chunk])
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# E. Conflicting evidence
# ---------------------------------------------------------------------------


class TestEConflictingEvidence:
    async def test_wrong_number_against_conflicting_sources_flagged(self):
        """Chunks say 12%/13%; answering 2% must not emit as grounded."""
        chunks = [
            _chunk(chunk_id="aaaa1111bbbb2222", content="The premium is 12%."),
            _chunk(chunk_id="cccc3333dddd4444", content="The premium is 13%."),
        ]
        response = await _run_orchestrator(
            "The premium is 2% of the sum insured. [chunk:aaaa1111]",
            chunks,
        )
        assert response.abstained or "2%" not in response.answer

    async def test_both_conflicting_sources_preserved_for_disclosure(self):
        """Guard: conflicts must not be silently narrowed to one source."""
        chunks = [
            _chunk(chunk_id="aaaa1111bbbb2222", content="The premium is 12%."),
            _chunk(chunk_id="cccc3333dddd4444", content="The premium is 13%."),
        ]
        response = await _run_orchestrator(
            "The premium is 12% of the sum insured. [chunk:aaaa11111]",
            chunks,
        )
        # 12% is supported by one source; the other source must still be
        # visible in citations so a conflict can be disclosed, not hidden.
        cited = {c["chunk_id"] for c in response.citations}
        assert "aaaa1111" in cited
        assert "cccc3333" in cited


# ---------------------------------------------------------------------------
# F. Invalid citation (repair must remove the unsupported sentence)
# ---------------------------------------------------------------------------


class TestFInvalidCitation:
    def test_repair_removes_percent_sentence(self):
        """Repair must handle non-word claims like '12%' (no \\b trap)."""
        repaired = RAGOrchestrator._repair_unsupported_claims(
            "The premium is 12% per annum. The premium is 2% of the sum.",
            [UnsupportedClaim(claim_text="12%", claim_type="number", reason="x")],
        )
        assert "12%" not in repaired
        assert "2%" in repaired


# ---------------------------------------------------------------------------
# G. Citation exists but does not support the claim
# ---------------------------------------------------------------------------


class TestGCitationNotSupporting:
    async def test_valid_id_with_wrong_number_does_not_ground(self):
        """A real chunk ID cannot ground a number absent from all evidence."""
        chunks = [_chunk(content="The premium is 12% of the sum insured.")]
        response = await _run_orchestrator(
            "The premium is 2% of the sum insured. [chunk:abc12345]",
            chunks,
        )
        assert response.abstained or "2%" not in response.answer


# ---------------------------------------------------------------------------
# H. Verifier failure (exceptions must abstain, never fail open)
# ---------------------------------------------------------------------------


class TestHVerifierFailure:
    async def test_citation_verifier_exception_abstains(self):
        chunks = [_chunk()]
        orch = RAGOrchestrator(_make_settings())
        sr = _rag(abstained=True, reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
        wr = _rag(chunks=chunks)
        with patch.object(orch._static_rag, "retrieve", return_value=sr), \
            patch.object(orch._web_rag, "retrieve", return_value=wr), \
            patch.object(
                orch._evidence_controller, "build_bundle",
                return_value=_bundle(chunks),
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
                return_value="PMFBY premium is 2%. [chunk:abc12345]",
            ), \
            patch(
                "app.services.rag_orchestrator.verify_citations",
                side_effect=RuntimeError("verifier exploded"),
            ):
            response = await orch.run(
                query="q",
                english_query="q",
                embedding=[0.1] * 768,
                domain="pmfby",
                state=None,
                classification=_classification(),
                history=None,
                lang="en",
                session_id="sess-adv-h1",
            )
        assert response.abstained is True
        assert response.confidence == 0.0

    async def test_grounding_verifier_exception_abstains(self):
        chunks = [_chunk()]
        orch = RAGOrchestrator(_make_settings())
        sr = _rag(abstained=True, reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
        wr = _rag(chunks=chunks)
        with patch.object(orch._static_rag, "retrieve", return_value=sr), \
            patch.object(orch._web_rag, "retrieve", return_value=wr), \
            patch.object(
                orch._evidence_controller, "build_bundle",
                return_value=_bundle(chunks),
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
                return_value="PMFBY premium is 2%. [chunk:abc12345]",
            ), \
            patch(
                "app.services.rag_orchestrator.verify_answer_grounding",
                side_effect=RuntimeError("grounding exploded"),
            ):
            response = await orch.run(
                query="q",
                english_query="q",
                embedding=[0.1] * 768,
                domain="pmfby",
                state=None,
                classification=_classification(),
                history=None,
                lang="en",
                session_id="sess-adv-h2",
            )
        assert response.abstained is True
        assert response.confidence == 0.0


# ---------------------------------------------------------------------------
# I. Weak / unverified evidence (web pipeline must fail closed)
# ---------------------------------------------------------------------------


def _discovery_payload(results: list[dict]) -> dict:
    return {
        "results": results,
        "classification": {
            "domain": "pmfby",
            "jurisdiction": "central",
            "state": None,
        },
        "discovery_metadata": {"facet_coverage": {}, "branches_run": []},
    }


def _web_source(chunk_id: str = "web_aaa111", text: str = "PMFBY premium is 2%.") -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "title": "PMFBY",
        "source_url": "https://pmfby.gov.in/x",
        "rerank_score": 90.0,
        "bm25_score": 5.0,
    }


class TestIWeakEvidence:
    def test_source_verification_failure_accepts_nothing(self):
        """Verifier crash must not accept every source as evidence."""
        from app.services.web_rag import WebRAGService

        svc = WebRAGService()
        discovered = [_web_source()]
        with patch.object(
            svc.bm25, "rank_candidates", return_value=list(discovered)
        ), patch.object(
            svc.reranker, "_passthrough_pre_rank", return_value=list(discovered)
        ), patch(
            "app.services.web_rag.reciprocal_rank_fusion", return_value=list(discovered)
        ), patch.object(
            svc.reranker, "final_rerank", return_value=list(discovered)
        ), patch.object(
            svc.source_verifier, "verify_and_filter",
            side_effect=RuntimeError("verifier down"),
        ):
            result, _diag = svc._process_discovery(
                query="q",
                discovery=_discovery_payload(discovered),
                classification=_classification(),
                state=None,
                effective_domain="pmfby",
                top_k=8,
                as_of_date=None,
            )
        assert result.abstained is True
        assert result.chunks == []

    def test_evidence_gate_exception_fails_closed(self):
        """A gate crash must abstain, never emit evidence as sufficient."""
        from app.services.web_rag import WebRAGService

        svc = WebRAGService()
        discovered = [_web_source()]
        with patch.object(
            svc.bm25, "rank_candidates", return_value=list(discovered)
        ), patch.object(
            svc.reranker, "_passthrough_pre_rank", return_value=list(discovered)
        ), patch(
            "app.services.web_rag.reciprocal_rank_fusion", return_value=list(discovered)
        ), patch.object(
            svc.reranker, "final_rerank", return_value=list(discovered)
        ), patch(
            "app.services.web_rag.evidence_gate",
            side_effect=RuntimeError("gate down"),
        ):
            result, _diag = svc._process_discovery(
                query="q",
                discovery=_discovery_payload(discovered),
                classification=_classification(),
                state=None,
                effective_domain="pmfby",
                top_k=8,
                as_of_date=None,
            )
        assert result.abstained is True


# ---------------------------------------------------------------------------
# J. Mixed supported + unsupported claims
# ---------------------------------------------------------------------------


class TestJMixedClaims:
    async def test_unsupported_number_removed_supported_kept(self):
        """Claim 2 must not silently pass; Claim 1 must survive repair."""
        chunks = [_chunk(content="PMFBY premium is 2% for kharif crops.")]
        response = await _run_orchestrator(
            "PMFBY premium is 2% for kharif crops. "
            "PMFBY premium is 12% for rabi crops. [chunk:abc12345]",
            chunks,
        )
        assert response.abstained is False
        assert "12%" not in response.answer
        assert "2%" in response.answer
