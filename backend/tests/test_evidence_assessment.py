"""Tests for EvidenceAssessment models and assess_evidence logic."""
from app.contracts import (
    EvidenceAssessment,
    EvidenceChunk,
    EvidenceSufficiency,
    QueryRequirements,
    RAGResult,
    SourceRole,
)
from app.evidence_controller import EvidenceController


def test_source_role_values():
    assert SourceRole.STATIC_PRIMARY.value == "static_primary"
    assert SourceRole.WEB_PRIMARY.value == "web_primary"
    assert SourceRole.BALANCED.value == "balanced"


def test_evidence_sufficiency_values():
    assert EvidenceSufficiency.SUFFICIENT.value == "sufficient"
    assert EvidenceSufficiency.PARTIAL.value == "partial"
    assert EvidenceSufficiency.INSUFFICIENT.value == "insufficient"
    assert EvidenceSufficiency.EMPTY.value == "empty"


def test_evidence_assessment_model():
    assessment = EvidenceAssessment(
        source_role=SourceRole.WEB_PRIMARY,
        sufficiency=EvidenceSufficiency.PARTIAL,
        static_quality="low",
        web_quality="high",
        assessment_text="Dynamic evidence is stronger.",
    )
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency == EvidenceSufficiency.PARTIAL


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_chunks(source_type: str, count: int, scores: list[float] | None = None) -> list[EvidenceChunk]:
    chunks = []
    for i in range(count):
        score = scores[i] if scores else 0.5
        chunks.append(EvidenceChunk(
            chunk_id=f"{source_type}_{i:05d}",
            content=f"Content {i}",
            source_type=source_type,
            title=f"Source {i}",
            dense_score=score,
        ))
    return chunks


# ---------------------------------------------------------------------------
# assess_evidence() tests
# ---------------------------------------------------------------------------

def test_assess_web_primary_for_current_query():
    controller = EvidenceController()
    static_result = RAGResult(chunks=_make_chunks("static", 5, [0.8, 0.7, 0.6, 0.5, 0.4]))
    web_result = RAGResult(chunks=_make_chunks("web", 3, [0.9, 0.8, 0.7]))
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (EvidenceSufficiency.SUFFICIENT, EvidenceSufficiency.PARTIAL)


def test_assess_static_primary_for_policy_query():
    controller = EvidenceController()
    static_result = RAGResult(chunks=_make_chunks("static", 8, [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]))
    web_result = RAGResult(chunks=_make_chunks("web", 1, [0.3]))
    query_req = QueryRequirements(
        temporal_scope="general",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.STATIC_PRIMARY


def test_assess_empty_when_no_chunks():
    controller = EvidenceController()
    static_result = RAGResult(chunks=[], abstained=True)
    web_result = RAGResult(chunks=[], abstained=True)
    query_req = QueryRequirements(
        temporal_scope="general",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.sufficiency == EvidenceSufficiency.EMPTY


def test_current_query_with_no_dynamic_evidence():
    """CRITICAL REGRESSION TEST.

    Historical bug: current/local query + dynamic=EMPTY + static=AVAILABLE
    → static evidence was used to answer as if current, producing wrong answer.

    This test verifies:
    1. Source role is WEB_PRIMARY (current query)
    2. Sufficiency is INSUFFICIENT (no dynamic evidence)
    3. Prompt explicitly says current/local fact cannot be established
    """
    controller = EvidenceController()
    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="General PMFBY rules",
                      source_type="static", title="PMFBY Guidelines", dense_score=0.8),
    ])
    web_result = RAGResult(chunks=[], abstained=True)  # No dynamic evidence
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)

    # Must NOT be SUFFICIENT — dynamic evidence is missing for current query
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (
        EvidenceSufficiency.INSUFFICIENT,
        EvidenceSufficiency.PARTIAL,
        EvidenceSufficiency.EMPTY,
    )
    assert assessment.sufficiency != EvidenceSufficiency.SUFFICIENT
    # Assessment text must warn that current/local facts cannot be established
    assert "current" in assessment.assessment_text.lower() or "dynamic" in assessment.assessment_text.lower()


def test_historical_query_prefers_period_matching_evidence():
    """Historical queries should prefer evidence matching the requested period."""
    controller = EvidenceController()
    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="2023 rules",
                      source_type="static", title="2023 Guidelines", dense_score=0.8),
    ])
    web_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="web_001", content="2024 notification",
                      source_type="web", title="2024 Update", dense_score=0.7),
    ])
    query_req = QueryRequirements(
        temporal_scope="2023",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    # Should prefer static (2023 matches historical query)
    assert assessment.source_role in (SourceRole.STATIC_PRIMARY, SourceRole.BALANCED)
