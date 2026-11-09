"""P2-1 terminology expansion + PMFBY opt-out exception tests.

Covers: bounded scoped expansion (rules/terms caps, no rewrite of the
user query, unrelated queries untouched), recorded application,
exception demotion (Gujarat ladder-type only, instruments exempt,
other jurisdictions inert), national-PMFBY preservation, and branch
cap compliance.
"""

from app.web_rag.expansion import (
    exception_demotion,
    expansion_terms,
    home_evidence_present,
    load_exceptions,
    load_expansion,
)
from app.web_rag.query_classifier import QueryClassifier

_classifier = QueryClassifier()


class TestExpansionData:
    def test_loads_bounded_rules(self):
        data = load_expansion()
        assert 1 <= len(data["rules"]) <= 5
        assert data["max_rules_per_query"] <= 2
        assert data["max_terms_per_rule"] <= 6

    def test_exception_explicit(self):
        data = load_exceptions()
        assert len(data["exceptions"]) == 1
        exc = data["exceptions"][0]
        assert exc["id"] == "pmfby-gujarat-optout"
        assert exc["opt_out_state"] == "Gujarat"
        assert exc["since"] == "Kharif 2020"
        assert exc["penalty"] < 0
        assert "instrument" not in (exc.get("demote_roles") or [])


class TestExpansionTerms:
    def test_crop_insurance_expands(self):
        cls = _classifier.classify("Crop insurance claim in Gujarat")
        terms, applied = expansion_terms(
            "Crop insurance claim in Gujarat", cls
        )
        assert "crop-relief" in applied
        assert len(terms) <= 12
        # Never duplicates query vocabulary.
        for term in terms:
            assert term.lower() not in "crop insurance claim in gujarat"

    def test_unrelated_query_untouched(self):
        cls = _classifier.classify("My electricity bill is wrong.")
        terms, applied = expansion_terms("My electricity bill is wrong.", cls)
        assert terms == [] and applied == {}

    def test_bounds_hold(self):
        cls = _classifier.classify("Crop insurance claim Gujarat relief")
        _terms, applied = expansion_terms("x", cls)
        assert len(applied) <= 2
        assert all(len(v) <= 6 for v in applied.values())

    def test_registry_query_gets_no_relief_terms(self):
        # agriculture-domain but not about relief: the crop-relief rule
        # must stay silent (require_any gate) so branch queries are not
        # polluted with unrelated synonyms.
        q = "Farmer Registry Gujarat official website registration process"
        cls = _classifier.classify(q)
        terms, applied = expansion_terms(q, cls)
        assert "crop-relief" not in applied
        for noisy in ("relief", "relief package", "assistance", "compensation"):
            assert noisy not in terms

    def test_claim_query_still_expands(self):
        q = "Farmer crop insurance claim rejected in Gujarat"
        cls = _classifier.classify(q)
        _terms, applied = expansion_terms(q, cls)
        assert "crop-relief" in applied


class TestExceptionDemotion:
    def test_gujarat_ladder_demoted(self):
        penalty = exception_demotion(
            "https://pmfby.gov.in/contact", "implementation",
            {"crop_insurance"}, "Gujarat", home_evidence_present=True,
        )
        assert penalty == -0.8

    def test_instrument_exempt(self):
        assert exception_demotion(
            "https://pmfby.gov.in/guidelines", "instrument",
            {"crop_insurance"}, "Gujarat", home_evidence_present=True,
        ) == 0.0

    def test_other_state_inert(self):
        assert exception_demotion(
            "https://pmfby.gov.in/contact", "implementation",
            {"crop_insurance"}, "Maharashtra", home_evidence_present=True,
        ) == 0.0

    def test_no_home_evidence_no_demotion(self):
        assert exception_demotion(
            "https://pmfby.gov.in/contact", "implementation",
            {"crop_insurance"}, "Gujarat", home_evidence_present=False,
        ) == 0.0

    def test_home_evidence_detection(self):
        pool = [
            {"source_url": "https://agri.gujarat.gov.in/gr/x",
             "web_title": "Relief GR", "title": "Relief GR",
             "official": True, "trusted_secondary": False},
            {"source_url": "https://pmfby.gov.in/contact",
             "web_title": "Contact", "title": "Contact",
             "official": True, "trusted_secondary": False},
        ]
        assert home_evidence_present(pool, "Gujarat") is True
        assert home_evidence_present(pool, "Maharashtra") is False
        assert home_evidence_present([], "Gujarat") is False


class TestRankingIntegration:
    def _discover(self, query, fixtures):
        from unittest.mock import patch

        from app.web_rag.service import WebDiscoveryService
        import eval.webdiscovery_fixtures as fx

        service = WebDiscoveryService()
        items = [dict(fx.F[name]) for name in fixtures]
        with patch.object(
            WebDiscoveryService, "_search_all", return_value=list(items)
        ):
            return service.discover(query)

    def test_gujarat_gr_beats_ladder(self):
        """Eval I-IN-03/T-HI-03 mechanism: GR top when relief evidence exists."""
        result = self._discover(
            "Gujarat farmer crop insurance claim rejected PMFBY or state relief?",
            ["OFF_GR_KRP", "PMFBY_LADDER"],
        )
        top = result["results"][0]
        assert "agri.gujarat.gov.in" in top["source_url"]
        assert top["exception_penalty"] == 0.0
        ladder = next(
            r for r in result["results"] if "pmfby.gov.in/contact" in r["source_url"]
        )
        assert ladder["exception_penalty"] == -0.8
        # Original query preserved; expansion recorded.
        assert result["query"].startswith("Gujarat farmer crop insurance")
        assert "crop-relief" in result["discovery_metadata"]["terminology_expansion"]

    def test_national_pmfby_unaffected(self):
        """Genuine national question: ladder competitive, never demoted."""
        result = self._discover(
            "Crop insurance claim in Maharashtra district",
            ["OFF_GR_KRP", "PMFBY_LADDER"],
        )
        urls = [r["source_url"] for r in result["results"]]
        assert any("pmfby.gov.in" in u for u in urls)
        for chunk in result["results"]:
            assert chunk.get("exception_penalty", 0.0) == 0.0

    def test_branch_cap_with_expansion(self):
        from app.web_rag.service import WebDiscoveryService

        cls = _classifier.classify(
            "How do I apply for i-Khedut tractor subsidy in Junagadh Gujarat?"
        )
        service = WebDiscoveryService()
        branches = service._build_stage1_branches("q", cls, "q")
        assert len(branches) <= WebDiscoveryService.MAX_BRANCHES
