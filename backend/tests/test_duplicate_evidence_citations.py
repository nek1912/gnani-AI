"""Regression: duplicate chunk IDs across facets must not fail verification.

Live failure (2026-10-08, gu pacs_governance query):
  StaticRAGService returned the same 10 chunks under two overlapping facets
  (facet queries identical when the query is <24 words → _slice_query is a
  no-op). select_coverage round-robin then emitted [A,B,A,B,...] and
  verify_citation_ids treated the doubled 8-char prefix as ambiguous →
  CITATION_FAILURE → abstain despite HIGH static band.

Locks both halves of the fix:
  1. select_coverage dedupes the round-robin head.
  2. verify_citation_ids dedupes identical evidence IDs before matching
     (defense-in-depth for any other merge path).
"""
from app.citation_verifier import verify_citation_ids
from app.contracts import EvidenceChunk
from app.facets import select_coverage


def _c(cid, score):
    return EvidenceChunk(chunk_id=cid, content="x", source_type="static",
                         title="t", domain="pacs_governance",
                         jurisdiction="central", dense_score=score)


UUID_A = "a9b6630a-1111-2222-3333-444444444444"
UUID_B = "58aba4c2-aaaa-bbbb-cccc-dddddddddddd"


def test_select_coverage_dedupes_overlapping_facets():
    """Same chunks under two facets appear once in merged."""
    shared = [_c(UUID_A, 0.9), _c(UUID_B, 0.85)] + [
        _c(f"other-{i:04d}-1111-2222-3333-444444444444", 0.8 - i * 0.01)
        for i in range(8)
    ]
    merged, _ = select_coverage({"f1": list(shared), "f2": list(shared)})
    ids = [c.chunk_id for c in merged]
    assert len(ids) == len(set(ids)), f"duplicates in merged: {ids}"
    assert UUID_A in ids and UUID_B in ids


def test_verify_dedupes_identical_evidence_ids():
    """Same UUID listed twice is NOT an ambiguous prefix."""
    answer = "Policy holds [chunk:a9b6630a]."
    valid, invalid = verify_citation_ids(answer, [UUID_A, UUID_A, UUID_B])
    assert valid == [UUID_A]
    assert invalid == []
