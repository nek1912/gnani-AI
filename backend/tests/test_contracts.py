"""Tests for immutable RAG contracts.

Verifies:
- EmbeddingProfile fingerprint determinism
- DocumentMetadata status/jurisdiction logic
- ChunkMetadata validation
- NormalizedQuery and HardFilter construction
- AbstentionReason and ConfidenceBand enums
- Answer and Citation structure
- EvaluationRunProvenance completeness
"""

from datetime import date

import pytest

from app.contracts import (
    AbstentionReason,
    Answer,
    AtomicClaim,
    AuthorityTier,
    ChunkMetadata,
    Citation,
    ConfidenceBand,
    DocumentMetadata,
    DocumentStatus,
    EmbeddingProfile,
    EvaluationRunProvenance,
    HardFilter,
    JurisdictionLevel,
    NormalizedQuery,
)


# ---------------------------------------------------------------------------
# EmbeddingProfile
# ---------------------------------------------------------------------------

class TestEmbeddingProfile:
    def test_fingerprint_deterministic(self):
        p1 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768)
        p2 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768)
        assert p1.fingerprint() == p2.fingerprint()

    def test_fingerprint_changes_on_model(self):
        p1 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768)
        p2 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v2",
                              dimension=768)
        assert p1.fingerprint() != p2.fingerprint()

    def test_fingerprint_changes_on_dimension(self):
        p1 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768)
        p2 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=512)
        assert p1.fingerprint() != p2.fingerprint()

    def test_fingerprint_changes_on_task_mode(self):
        p1 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768, document_task="retrieval.passage")
        p2 = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                              dimension=768, document_task="retrieval.document")
        assert p1.fingerprint() != p2.fingerprint()

    def test_fingerprint_16_chars(self):
        p = EmbeddingProfile(provider="jina", model_id="jina-embeddings-v3",
                             dimension=768)
        fp = p.fingerprint()
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_zero_dimension_rejected(self):
        with pytest.raises(ValueError, match="dimension must be positive"):
            EmbeddingProfile(provider="jina", model_id="m", dimension=0)

    def test_negative_dimension_rejected(self):
        with pytest.raises(ValueError, match="dimension must be positive"):
            EmbeddingProfile(provider="jina", model_id="m", dimension=-1)


# ---------------------------------------------------------------------------
# DocumentMetadata
# ---------------------------------------------------------------------------

class TestDocumentMetadata:
    def _make_doc(self, **overrides) -> DocumentMetadata:
        defaults = {
            "source_id": "src-001", "document_id": "doc-001", "version_id": "v1",
            "title": "Test Doc", "domain": "schemes",
        }
        defaults.update(overrides)
        return DocumentMetadata(**defaults)

    def test_active_document(self):
        doc = self._make_doc(status=DocumentStatus.ACTIVE)
        assert doc.is_active_as_of() is True

    def test_superseded_document(self):
        doc = self._make_doc(status=DocumentStatus.SUPERSEDED)
        assert doc.is_active_as_of() is False

    def test_effective_date_range(self):
        doc = self._make_doc(
            status=DocumentStatus.ACTIVE,
            effective_start=date(2024, 1, 1),
            effective_end=date(2025, 12, 31),
        )
        assert doc.is_active_as_of(date(2024, 6, 15)) is True
        assert doc.is_active_as_of(date(2023, 6, 15)) is False
        assert doc.is_active_as_of(date(2026, 6, 15)) is False

    def test_unknown_status_treated_as_potentially_active(self):
        doc = self._make_doc(status=DocumentStatus.UNKNOWN)
        assert doc.is_active_as_of() is True

    def test_state_normalized(self):
        doc = self._make_doc(jurisdiction_level=JurisdictionLevel.STATE,
                             state="  Gujarat  ")
        assert doc.state == "gujarat"

    def test_none_state_preserved(self):
        doc = self._make_doc(state=None)
        assert doc.state is None


# ---------------------------------------------------------------------------
# ChunkMetadata
# ---------------------------------------------------------------------------

class TestChunkMetadata:
    def test_valid_chunk(self):
        c = ChunkMetadata(chunk_id="abc123", document_version_id="v1",
                          ordinal=0)
        assert c.chunk_id == "abc123"

    def test_ordinal_must_be_non_negative(self):
        with pytest.raises(ValueError):
            ChunkMetadata(chunk_id="abc", document_version_id="v1",
                          ordinal=-1)


# ---------------------------------------------------------------------------
# NormalizedQuery
# ---------------------------------------------------------------------------

class TestNormalizedQuery:
    def test_construction(self):
        q = NormalizedQuery(original_text="PMFBY kya hai?",
                            normalized_text="pmfby kya hai",
                            language="hi")
        assert q.language == "hi"
        assert q.transformation_lineage == []

    def test_dates_extracted(self):
        q = NormalizedQuery(
            original_text="What about 2024?",
            normalized_text="what about 2024",
            dates_mentioned=["2024"])
        assert "2024" in q.dates_mentioned


# ---------------------------------------------------------------------------
# HardFilter
# ---------------------------------------------------------------------------

class TestHardFilter:
    def test_default_filter(self):
        f = HardFilter()
        assert f.status == DocumentStatus.ACTIVE
        assert f.domain is None

    def test_domain_filter(self):
        f = HardFilter(domain="schemes", state="gujarat")
        assert f.domain == "schemes"
        assert f.state == "gujarat"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_abstention_reasons_comprehensive(self):
        reasons = list(AbstentionReason)
        assert len(reasons) >= 10
        assert AbstentionReason.NO_ELIGIBLE_SOURCE in reasons
        assert AbstentionReason.CITATION_FAILURE in reasons

    def test_confidence_bands(self):
        assert ConfidenceBand.HIGH.value == "high"
        assert ConfidenceBand.MEDIUM.value == "medium"
        assert ConfidenceBand.LOW.value == "low"

    def test_document_statuses(self):
        assert DocumentStatus.ACTIVE.value == "active"
        assert DocumentStatus.SUPERSEDED.value == "superseded"

    def test_authority_tiers(self):
        assert AuthorityTier.PRIMARY.value == "primary"
        assert AuthorityTier.SECONDARY.value == "secondary"


# ---------------------------------------------------------------------------
# Answer & Citation
# ---------------------------------------------------------------------------

class TestAnswer:
    def test_abstained_answer(self):
        a = Answer(answer_text="", abstained=True,
                   abstention_reason=AbstentionReason.NO_ELIGIBLE_SOURCE)
        assert a.abstained is True
        assert a.confidence == ConfidenceBand.LOW

    def test_answer_with_citations(self):
        cite = Citation(chunk_id="abc123", source_id="src-001",
                        title="Doc", section="1.1", page=1)
        a = Answer(answer_text="Answer [chunk:abc123]", citations=[cite],
                   confidence=ConfidenceBand.HIGH)
        assert len(a.citations) == 1
        assert a.citations[0].chunk_id == "abc123"

    def test_atomic_claims(self):
        claim = AtomicClaim(claim_text="PMFBY provides insurance",
                            evidence_chunk_ids=["abc123"],
                            is_supported=True)
        a = Answer(answer_text="test", atomic_claims=[claim])
        assert a.atomic_claims[0].is_supported is True


# ---------------------------------------------------------------------------
# EvaluationRunProvenance
# ---------------------------------------------------------------------------

class TestEvaluationRunProvenance:
    def test_construction(self):
        p = EvaluationRunProvenance(
            run_id="run-001", git_commit="abc123def",
            raw_metrics={"recall@5": 0.6, "mrr": 0.509})
        assert p.run_id == "run-001"
        assert p.raw_metrics["recall@5"] == 0.6
        assert p.failed_case_rankings == []


# ---------------------------------------------------------------------------
# Evidence Controller Data Models
# ---------------------------------------------------------------------------

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


def test_flagged_claim_creation():
    from app.contracts import FlaggedClaim
    fc = FlaggedClaim(
        claim_id="fc-001",
        claim_text="PMFBY premium is 2%",
        claim_type="static",
        flag_reason="unverified amount",
        requires_evidence="static",
    )
    assert fc.claim_id == "fc-001"
    assert fc.claim_text == "PMFBY premium is 2%"
    assert fc.claim_type == "static"
    assert fc.flag_reason == "unverified amount"
    assert fc.requires_evidence == "static"


def test_filter_outcome_constants():
    from app.contracts import FilterOutcome
    assert FilterOutcome.KEEP == "keep"
    assert FilterOutcome.FILTER == "filter"
    assert FilterOutcome.REGENERATE == "regenerate"
    assert FilterOutcome.ABSTAIN == "abstain"
