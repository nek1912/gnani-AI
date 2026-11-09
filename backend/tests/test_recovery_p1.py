"""P1-4 bounded recovery tests.

Covers: evidence-state assessment for every state, single-axis
modification, recovery hints, the retrieve loop (recover-then-pass,
hard 2-round bound, legacy opt-out, no DOMAIN_MISMATCH retry,
jurisdiction widening, facet-targeted recovery, clean terminal
abstention).
"""

from unittest.mock import patch

from app.contracts import AbstentionReason
from app.services.web_rag import WebRAGService
from app.web_rag.query_classifier import QueryClassification
from app.web_rag.recovery import (
    MAX_RECOVERY_ROUNDS,
    OUTDATED,
    PARTIAL,
    TERMINAL,
    VALID_BUT_LOW_SCORE,
    WEAK,
    WRONG_JURISDICTION,
    CONFLICTING,
    assess_evidence_state,
    modify_for_axis,
    recovery_hint,
)


def _cls(**overrides):
    params = {
        "domain": "pmfby", "jurisdiction": "state", "state": "Gujarat",
        "district": None, "society_type": None, "intent": "INFORMATIONAL",
        "confidence": 0.8, "case_year": None, "season": None,
        "jurisdiction_source": "explicit", "assumed_state": False,
    }
    params.update(overrides)
    return QueryClassification(**params)


def _source(chunk_id, score=85.0, url="https://pmfby.gov.in/guidelines",
            jurisdiction="central", state=None, tier=4, role="instrument",
            validity=None, official=True):
    source = {
        "chunk_id": chunk_id,
        "source_url": url, "url": url,
        "title": "PMFBY guidelines", "web_title": "PMFBY guidelines",
        "text": "PMFBY guidelines text", "content": "PMFBY guidelines text",
        "bm25_score": 1.0, "gemini_score": score, "rerank_score": score,
        "rerank_applicable": True, "official": official,
        "trusted_secondary": False, "source_tier": tier,
        "document_role": role, "mandate_fit": 0.30,
        "query_domain": "pmfby", "jurisdiction": jurisdiction, "state": state,
    }
    if validity is not None:
        source["validity"] = validity
    return source


def _discovery(results, domain="pmfby", **meta):
    base = {
        "results": results,
        "classification": {"domain": domain, "jurisdiction": "state", "state": "Gujarat"},
        "discovery_metadata": {
            "branches_run": ["primary", "jurisdiction"],
            "facet_coverage": {},
        },
    }
    base["discovery_metadata"].update(meta)
    return base


class TestAssessEvidenceState:
    def test_domain_mismatch_terminal(self):
        state, axis = assess_evidence_state([], [], {}, "DOMAIN_MISMATCH", _cls(), {})
        assert (state, axis) == (TERMINAL, "none")

    def test_gate_jurisdiction_mismatch(self):
        state, axis = assess_evidence_state(
            [_source("a", state="Maharashtra", jurisdiction="state")],
            [], {}, "JURISDICTION_MISMATCH", _cls(), {},
        )
        assert (state, axis) == (WRONG_JURISDICTION, "jurisdiction")

    def test_pool_state_mismatch(self):
        state, axis = assess_evidence_state(
            [_source("a", state="Maharashtra", jurisdiction="state")],
            [], {"relevant": False}, None, _cls(), {},
        )
        assert (state, axis) == (WRONG_JURISDICTION, "jurisdiction")

    def test_outdated_superseded_pool(self):
        pool = [_source("a", validity={"supersession_status": "superseded"})]
        state, axis = assess_evidence_state(pool, [], {"relevant": False}, None, _cls(), {})
        assert (state, axis) == (OUTDATED, "validity")

    def test_conflicting_mixed_tiers(self):
        pool = [
            _source("a", tier=4, official=True),
            _source("b", tier=0, official=False, url="https://blog.example/x"),
        ]
        state, axis = assess_evidence_state(pool, [], {"relevant": False}, None, _cls(), {})
        assert (state, axis) == (CONFLICTING, "authority")

    def test_partial_uncovered_facet(self):
        accepted = [_source("a")]
        coverage = {"deadline": {"supported": False, "chunk_ids": []}}
        state, axis = assess_evidence_state(
            accepted, accepted, {"relevant": True}, None, _cls(), coverage
        )
        assert state == PARTIAL
        assert axis == "facet:deadline"

    def test_valid_but_low_score_authoritative(self):
        accepted = [_source("a")]
        state, axis = assess_evidence_state(
            accepted, accepted, {"relevant": True},
            "BELOW_TOP1_THRESHOLD", _cls(), {},
        )
        assert (state, axis) == (VALID_BUT_LOW_SCORE, "authority")

    def test_valid_but_low_score_no_authority_terminal(self):
        accepted = [_source("a", tier=0, official=False, role="secondary",
                            url="https://blog.example/x")]
        accepted[0]["mandate_fit"] = 0.0
        state, axis = assess_evidence_state(
            accepted, accepted, {"relevant": True},
            "BELOW_TOP1_THRESHOLD", _cls(), {},
        )
        assert (state, axis) == (TERMINAL, "none")

    def test_weak_default(self):
        state, axis = assess_evidence_state([], [], {"relevant": False}, None, _cls(), {})
        assert (state, axis) == (WEAK, "language")


class TestModifyForAxis:
    def test_jurisdiction_widens(self):
        original = _cls()
        modified = modify_for_axis(original, "jurisdiction")
        assert modified is not original
        assert modified.state is None
        assert modified.jurisdiction == "central"
        assert modified.jurisdiction_source == "recovery"
        assert original.state == "Gujarat"  # untouched

    def test_jurisdiction_noop_when_central(self):
        central = _cls(jurisdiction="central", state=None)
        assert modify_for_axis(central, "jurisdiction") is None

    def test_other_axes_keep_classification(self):
        original = _cls()
        assert modify_for_axis(original, "validity") is original
        assert modify_for_axis(None, "validity") is None

    def test_language_hint_missing(self):
        hint = recovery_hint("language", branches_run=["primary"])
        assert hint["languages"] == ["gujarati", "hindi"]

    def test_facet_hint_parsing(self):
        hint = recovery_hint("facet:deadline,escalation")
        assert hint["facets"] == ["deadline", "escalation"]


def _run_retrieve(service, discoveries, **kwargs):
    """Retrieve with mocked discover (side_effect list) + real downstream,
    except the reranker which is pinned to passthrough (backend/.env
    enables the live reranker; unit tests must not hit the network)."""
    with patch.object(
        service.web_discovery, "discover", side_effect=list(discoveries)
    ), patch.object(
        service.reranker, "final_rerank",
        side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
    ):
        return service.retrieve(query="Crop insurance Gujarat", **kwargs)


class TestRetrieveLoop:
    def test_recover_then_pass(self):
        """Adversarial: weak first attempt, recovery round succeeds."""
        service = WebRAGService()
        weak = [_source("w1", score=10.0)]
        good = [_source("g1", score=85.0)]
        result = _run_retrieve(
            service, [_discovery(weak), _discovery(good)]
        )
        assert result.abstained is False
        assert result.metadata["recovery_rounds"] == 1
        assert result.metadata["recovery_axes"] == ["language"]
        assert len(result.chunks) == 1

    def test_hard_two_round_bound(self):
        """Adversarial #11 (part): two failed rounds -> terminal, 3 discovers."""
        service = WebRAGService()
        assert MAX_RECOVERY_ROUNDS == 2
        weak = [_source("w1", score=5.0)]
        with patch.object(
            service.web_discovery, "discover",
            return_value=_discovery(weak),
        ) as mock_discover, patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(query="Crop insurance Gujarat")
        assert mock_discover.call_count == 3  # initial + 2 rounds
        assert result.abstained is True
        assert result.metadata["recovery_rounds"] == 2
        assert len(result.metadata["recovery_axes"]) == 2

    def test_zero_rounds_is_legacy(self):
        service = WebRAGService(max_recovery_rounds=0)
        weak = [_source("w1", score=5.0)]
        with patch.object(
            service.web_discovery, "discover",
            return_value=_discovery(weak),
        ) as mock_discover, patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(query="Crop insurance Gujarat")
        assert mock_discover.call_count == 1
        assert result.abstained is True
        assert result.reason == AbstentionReason.BELOW_TOP1_THRESHOLD

    def test_jurisdiction_recovery_widens(self):
        """Adversarial #7: wrong-state evidence -> jurisdiction recovery."""
        service = WebRAGService()
        mh = [_source("m1", score=85.0, jurisdiction="state",
                      state="Maharashtra",
                      url="https://maharashtra.gov.in/scheme")]
        central = [_source("c1", score=85.0)]
        seen_classifications = []

        def fake_discover(query, classification=None, as_of_date=None, recovery=None):
            seen_classifications.append(classification)
            if classification is not None and classification.state is None:
                return _discovery(central)
            return _discovery(mh)

        with patch.object(
            service.web_discovery, "discover", side_effect=fake_discover
        ), patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            # P1: explicit Gujarat query (no silent default) with only
            # Maharashtra evidence -> jurisdiction recovery widens.
            result = service.retrieve(query="Crop insurance scheme Gujarat")

        assert result.abstained is False
        assert result.metadata["recovery_axes"] == ["jurisdiction"]
        widened = [c for c in seen_classifications if c is not None and c.state is None]
        assert widened, "expected a widened (stateless) recovery classification"

    def test_partial_facet_recovery(self):
        """Adversarial #10: missing facet -> facet-specific recovery only."""
        service = WebRAGService()
        weak = [_source("w1", score=10.0)]
        good = [_source("g1", score=85.0)]
        recovery_hints = []

        def fake_discover(query, classification=None, as_of_date=None, recovery=None):
            if recovery:
                recovery_hints.append(recovery)
                return _discovery(good)
            return _discovery(weak, facet_coverage={
                "deadline": {"supported": False, "chunk_ids": []},
            })

        with patch.object(
            service.web_discovery, "discover", side_effect=fake_discover
        ), patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(query="Tell me the PMFBY subsidy deadline")

        assert result.abstained is False
        assert recovery_hints, "expected a facet recovery round"
        assert recovery_hints[0]["axis"] == "facet"
        assert "deadline" in recovery_hints[0]["facets"]
        assert result.metadata["recovery_axes"] == ["facet:deadline"]

    def test_terminal_carries_evidence_state(self):
        service = WebRAGService(max_recovery_rounds=0)
        weak = [_source("w1", score=5.0)]
        with patch.object(
            service.web_discovery, "discover",
            return_value=_discovery(weak),
        ), patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(query="Crop insurance Gujarat")
        assert result.metadata["evidence_state"] in ("WEAK", "SUFFICIENT")
        assert result.metadata["recovery_rounds"] == 0
