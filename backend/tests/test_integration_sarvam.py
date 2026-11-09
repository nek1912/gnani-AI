"""Integration test for Sarvam LLM migration end-to-end flow."""

from app.evidence_controller import EvidenceController, strip_citations
from app.contracts import (
    RAGResult, EvidenceChunk, QueryRequirements,
    SourceRole, EvidenceSufficiency,
)


def test_strip_citations_removes_all_formats():
    """Verify backend guarantee: no [chunk:xxx] in answer after stripping."""
    answers = [
        "Scheme requires [chunk:a0eebc99] registration.",
        "Premium is [chunk:web_a1b2c3d4e5f6_c102] ₹2000.",
        "Multiple [chunk:abc12345] and [chunk:web_xyz789_c42] citations.",
        "No citations here.",
        "Edge case: [chunk:] empty id.",
    ]
    for answer in answers:
        clean, _ids = strip_citations(answer)
        assert "[chunk:" not in clean, f"Chunk ID leaked in: {clean}"
        assert "(chunk:" not in clean, f"Chunk ID leaked in: {clean}"


def test_evidence_assessment_flow():
    """Test the full assessment flow from RAGResult to prompt text."""
    controller = EvidenceController()

    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="Policy text", source_type="static",
                      title="PMFBY Guidelines", dense_score=0.8),
        EvidenceChunk(chunk_id="static_002", content="Rules text", source_type="static",
                      title="Eligibility Criteria", dense_score=0.7),
    ])
    web_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="web_abc123_c1", content="Current premium", source_type="web",
                      title="Current Rates", url="https://example.com", dense_score=0.9),
    ])
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )

    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (EvidenceSufficiency.SUFFICIENT, EvidenceSufficiency.PARTIAL)
    assert "Dynamic evidence" in assessment.assessment_text or "web" in assessment.assessment_text.lower()
