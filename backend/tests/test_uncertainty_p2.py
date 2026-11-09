"""P2-2 state-uncertainty routing tests.

Covers: explicit state wins, district implies state, national scope
suppresses defaults, MSCS exemption, assumed dampening (factor +
ranking effect), explicit full weight, national banking preserved,
wrong-state non-preference via defaults, branch bounds.
"""

from types import SimpleNamespace

from app.web_rag.expansion import assumed_dampen_factor
from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.service import WebDiscoveryService

_classifier = QueryClassifier()


class TestResolutionPriority:
    def test_explicit_state_wins(self):
        cls = _classifier.classify("Crop insurance in Gujarat")
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_district_implies_state(self):
        cls = _classifier.classify("KCC rules Junagadh district")
        assert cls.district == "Junagadh"
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_district_beats_session(self):
        cls = _classifier.classify("Crop claim Junagadh", default_state="Maharashtra")
        assert cls.district == "Junagadh"
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"

    def test_explicit_state_beats_district_conflict(self):
        cls = _classifier.classify("Maharashtra Junagadh query")
        assert cls.state == "Maharashtra"

    def test_national_scope_no_default(self):
        cls = _classifier.classify("National cooperative database registration")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.assumed_state is False

    def test_national_beats_session(self):
        cls = _classifier.classify(
            "All India crop insurance rules", default_state="Gujarat"
        )
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_mscs_exempt(self):
        cls = _classifier.classify(
            "Multi-state cooperative society election rules"
        )
        assert cls.society_type == "mscs"
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_international_not_national(self):
        cls = _classifier.classify("International cooperative day Gujarat")
        assert cls.state == "Gujarat"


class TestAssumedDampening:
    def test_factor_assumed_crop_insurance(self):
        assert assumed_dampen_factor({"crop_insurance"}, True) == 0.5

    def test_factor_explicit_full(self):
        assert assumed_dampen_factor({"crop_insurance"}, False) == 1.0

    def test_factor_other_subjects_full(self):
        assert assumed_dampen_factor({"banking"}, True) == 1.0
        assert assumed_dampen_factor(set(), True) == 1.0

    def test_stamped_on_results(self):
        from app.web_rag.retrieval_scorer import rescore

        classification = SimpleNamespace(
            intent="INFORMATIONAL", state="Gujarat", domain="pmfby",
            society_type=None, case_year=None, season=None,
            jurisdiction_source="subject_default", assumed_state=True,
            district=None,
        )
        results = [{
            "chunk_id": "web_x_c101", "source_url": "https://pmfby.gov.in/g",
            "url": "https://pmfby.gov.in/g", "title": "t", "web_title": "t",
            "text": "text", "content": "text", "bm25_score": 1.0,
            "official": True, "trusted_secondary": False,
        }]
        ranked = rescore("PMFBY test", results, classification)
        assert ranked[0]["assumed_dampen"] == 0.5
        assert ranked[0]["mandate_fit"] == round(0.30 * 0.5, 4)

    def test_explicit_full_weight_stamped(self):
        from app.web_rag.retrieval_scorer import rescore

        classification = SimpleNamespace(
            intent="INFORMATIONAL", state="Gujarat", domain="pmfby",
            society_type=None, case_year=None, season=None,
            jurisdiction_source="explicit", assumed_state=False,
            district=None,
        )
        results = [{
            "chunk_id": "web_x_c101", "source_url": "https://pmfby.gov.in/g",
            "url": "https://pmfby.gov.in/g", "title": "t", "web_title": "t",
            "text": "text", "content": "text", "bm25_score": 1.0,
            "official": True, "trusted_secondary": False,
        }]
        ranked = rescore("PMFBY test", results, classification)
        assert ranked[0]["assumed_dampen"] == 1.0


class TestBranchBehavior:
    def _branches(self, query, **kwargs):
        cls = _classifier.classify(query, **kwargs)
        service = WebDiscoveryService()
        return service._build_stage1_branches(query, cls, query), cls

    def test_pmfby_stateless_branches_bounded(self):
        # P1: no-signal PMFBY is central with no invented state; branch
        # count stays bounded.
        branches, cls = self._branches("What is PMFBY?")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.assumed_state is False
        assert len(branches) <= WebDiscoveryService.MAX_BRANCHES

    def test_pmfby_gujarat_explicit(self):
        _branches, cls = self._branches("Crop insurance in Gujarat")
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_pmfby_maharashtra(self):
        branches, cls = self._branches("Crop insurance in Maharashtra")
        assert cls.state == "Maharashtra"
        assert cls.jurisdiction_source == "explicit"
        names = [b["name"] for b in branches]
        assert "gujarati" not in names and "hindi" not in names

    def test_gujarat_only_scheme(self):
        _branches, cls = self._branches(
            "How do I apply for i-Khedut tractor subsidy in Gujarat?"
        )
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"

    def test_national_banking_unaffected(self):
        from unittest.mock import patch

        service = WebDiscoveryService()
        items = [{
            "url": "https://rbi.org.in/commonman/faq",
            "title": "RBI bank complaint FAQ",
            "content": "RBI bank complaint ombudsman process. " * 10,
            "raw_content": "", "score": 0.9,
        }]
        with patch.object(
            WebDiscoveryService, "_search_all", return_value=list(items)
        ):
            result = service.discover("Bank complaint RBI ombudsman")
        urls = [r.get("source_url") for r in result["results"]]
        assert any("rbi.org.in" in u for u in urls)

    def test_national_district_query(self):
        _branches, cls = self._branches("KCC rules Junagadh")
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"
