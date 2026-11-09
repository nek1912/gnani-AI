from app.retrieval import GateResult, RetrievedChunk, evidence_gate


def mk(sim: float, domain: str = "pmfby", jurisdiction: str = "central",
       state: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(chunk_id="c1", stable_chunk_id="test:p1:c0",
                          document_id="d1", title="T", page=1,
                          page_start=1, page_end=1, section="S",
                          content="C", similarity=sim, source_url="https://x",
                          domain=domain, jurisdiction=jurisdiction, state=state)


def test_gate_pass():
    g = evidence_gate([mk(0.62), mk(0.41), mk(0.33)], expected_domain="pmfby")
    assert not g.abstained and g.confidence == round(0.6 * 0.62 + 0.4 * (3 / 3), 2)


def test_gate_abstains_low_top1():
    assert evidence_gate([mk(0.31)]).abstained


def test_gate_abstains_insufficient_secondary():
    assert evidence_gate([mk(0.80), mk(0.28)]).abstained


def test_gate_empty():
    g = evidence_gate([])
    assert g.abstained and g.confidence == 0.0
    assert isinstance(g, GateResult)


def test_gate_rejects_wrong_domain_chunk():
    g = evidence_gate([mk(0.9), mk(0.7, domain="finlit")],
                      expected_domain="pmfby")
    assert g.abstained


def test_gate_rejects_wrong_state_document():
    g = evidence_gate([mk(0.9), mk(0.7, jurisdiction="state", state="maharashtra")],
                      expected_domain="pmfby", expected_state="gujarat")
    assert g.abstained
