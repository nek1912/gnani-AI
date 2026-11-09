from app.contracts import EvidenceChunk
from app.facets import select_coverage


def _c(cid, score, domain="pmfby"):
    return EvidenceChunk(chunk_id=cid, content="x", source_type="static",
                         title="t", domain=domain, jurisdiction="central", dense_score=score)


def test_round_robin_beats_score_only():
    per = {"pmfby": [_c("a1", 0.9)], "schemes": [_c("b1", 0.41)]}
    merged, cov = select_coverage(per)
    ids = [c.chunk_id for c in merged]
    assert "a1" in ids and "b1" in ids
    assert cov["pmfby"]["status"] == "supported"
