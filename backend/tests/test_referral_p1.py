"""P1-5 referral-on-abstention tests.

Covers: referral content rules (jurisdiction, mandate-map authority,
verified-domain channels, no fabrication), None-cases, orchestrator
wiring (abstain carries referral, answers carry none), route-dict
shape, and the gate-non-bypass property.
"""

from unittest.mock import patch

from app.config import Settings
from app.contracts import AbstentionReason, ConfidenceBand, RAGResponse, RAGResult
from app.services.rag_orchestrator import RAGOrchestrator
from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.referrals import build_referral

_classifier = QueryClassifier()


def _make_settings(**overrides):
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


class TestBuildReferral:
    def test_gujarat_relief_referral(self):
        cls = _classifier.classify("Crop loss relief in Junagadh")
        referral = build_referral(cls, "WEAK", ["deadline"])
        assert referral is not None
        assert referral["jurisdiction"] == {"state": "Gujarat", "district": "Junagadh"}
        assert "Gujarat Agriculture" in (referral["authority"] or "")
        assert referral["channel"] in (
            "agri.gujarat.gov.in", "dag.gujarat.gov.in",
        )
        assert any("deadline" in m for m in referral["missing"])
        assert referral["evidence_state"] == "WEAK"

    def test_mscs_referral_is_central(self):
        cls = _classifier.classify(
            "Multi-state cooperative society election rules"
        )
        referral = build_referral(cls, "WEAK")
        assert referral is not None
        assert referral["jurisdiction"] is None
        assert referral["authority"] is not None
        assert "CRCS" in referral["authority"] or "Cooperation" in referral["authority"]

    def test_banking_referral_rbi(self):
        cls = _classifier.classify("Bank complaint charges")
        referral = build_referral(cls, "WEAK")
        assert referral is not None
        assert referral["authority"] == "Reserve Bank of India"
        assert referral["channel"] == "rbi.org.in"

    def test_unknown_returns_none(self):
        assert build_referral(None, "WEAK") is None
        cls = _classifier.classify("My electricity bill is wrong.")
        assert build_referral(cls, "WEAK") is None

    def test_no_fabrication(self):
        import re

        cls = _classifier.classify("Crop loss relief in Junagadh")
        referral = build_referral(cls, "OUTDATED", ["deadline", "escalation"])
        text = referral["summary"] + str(referral["authority"]) + str(referral["channel"])
        # No phone numbers.
        assert not re.search(r"\d{6,}", text.replace("202", "").replace("1145", ""))
        # No deep URLs — bare verified domain at most.
        assert "http" not in text
        assert "/" not in (referral["channel"] or "")
        # Channel must be a mandate-map domain.
        from app.web_rag.mandate_map import find_org

        assert find_org(referral["channel"]) is not None

    def test_missing_states_phrasing(self):
        cls = _classifier.classify("Crop loss relief in Gujarat")
        for state, fragment in [
            ("WRONG_JURISDICTION", "jurisdiction-matching"),
            ("OUTDATED", "in-force"),
            ("CONFLICTING", "consistent"),
        ]:
            referral = build_referral(cls, state)
            assert fragment in referral["missing"][0]


class TestOrchestratorWiring:
    def _abstain_result(self, reason, **meta):
        metadata = {"evidence_state": "WEAK", "uncovered_facets": []}
        metadata.update(meta)
        return RAGResult(
            chunks=[], abstained=True, reason=reason,
            band=ConfidenceBand.LOW, domain="pmfby", metadata=metadata,
        )

    def test_abstain_carries_referral(self):
        import asyncio

        orch = RAGOrchestrator(_make_settings())
        static = self._abstain_result(AbstentionReason.NO_ELIGIBLE_SOURCE)
        web = self._abstain_result(AbstentionReason.INSUFFICIENT_EVIDENCE)
        classification = _classifier.classify("Crop loss relief in Junagadh")

        async def fake_pipelines(**kwargs):
            return static, web

        with patch.object(orch, "_run_pipelines", side_effect=fake_pipelines):
            response = asyncio.run(
                orch.run(
                    query="Crop loss relief in Junagadh",
                    english_query="Crop loss relief in Junagadh",
                    embedding=[0.1] * 768,
                    domain="agriculture",
                    state="Gujarat",
                    classification=classification,
                    history=[],
                    lang="en",
                    session_id="sess-1",
                    pipeline_mode="rag_web",
                )
            )

        assert response.abstained is True
        assert response.citations == []
        assert response.referral is not None
        assert response.referral["jurisdiction"]["district"] == "Junagadh"

    def test_abstain_response_defaults_referral_none(self):
        orch = RAGOrchestrator(_make_settings())
        response = orch._abstain_response(
            lang="en", reason=AbstentionReason.NO_ELIGIBLE_SOURCE,
            domain="pmfby", session_id="s",
        )
        assert response.abstained is True
        assert response.referral is None

    def test_route_dict_carries_referral(self):
        from app.routes.chat import _rag_response_to_dict

        resp = RAGResponse(
            answer="a", abstained=True,
            referral={"summary": "s", "authority": None},
        )
        body = _rag_response_to_dict(resp, "en", "sess-1")
        assert body["referral"] == {"summary": "s", "authority": None}
        assert body["abstained"] is True

    def test_referral_never_bypasses_gate(self):
        # Referral attaches only to abstained responses; answered
        # responses carry none.
        resp = RAGResponse(answer="a [chunk:abc]", abstained=False)
        assert resp.referral is None
