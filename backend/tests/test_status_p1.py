"""P1-8 status-evidence branch tests.

Covers: status detection (intent + vocabulary, GU/HI words),
branch execution and scoping, non-status exclusion, branch cap,
discover integration, and status+validity combination (currency
from validity, never recency).
"""

from unittest.mock import patch

from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.service import WebDiscoveryService
from app.web_rag.status import (
    STATUS_PUBLISHERS,
    is_status_query,
    status_branch_terms,
)

_classifier = QueryClassifier()


def _branches(query):
    cls = _classifier.classify(query)
    service = WebDiscoveryService()
    return service._build_stage1_branches(query, cls, query), cls


class TestStatusDetection:
    def test_status_intent(self):
        assert is_status_query("Check my application status", "STATUS") is True

    def test_status_vocabulary(self):
        assert is_status_query("Is the scheme still active?", "INFORMATIONAL") is True
        assert is_status_query("Has the old circular been discontinued?") is True

    def test_gujarati_status_word(self):
        assert is_status_query("યોજનાની સ્થિતિ શું છે?") is True

    def test_non_status(self):
        assert is_status_query("What is PMFBY?", "INFORMATIONAL") is False
        assert is_status_query("How do I apply for KCC?", "APPLICATION") is False

    def test_terms_bounded(self):
        assert 1 <= len(status_branch_terms()) <= 4


class TestStatusBranch:
    def test_status_query_runs_branch(self):
        branches, _ = _branches("Check my KCC application status")
        names = [b["name"] for b in branches]
        assert "status" in names
        branch = next(b for b in branches if b["name"] == "status")
        assert branch["only_official"] is True
        assert branch["max_results"] <= 8

    def test_status_anchors_include_publishers(self):
        branches, _ = _branches("Check my KCC application status in Gujarat")
        branch = next(b for b in branches if b["name"] == "status")
        for publisher in STATUS_PUBLISHERS:
            assert publisher in branch["include_domains"]

    def test_non_status_no_branch(self):
        branches, _ = _branches("What is PMFBY?")
        assert "status" not in [b["name"] for b in branches]

    def test_cap_holds_with_status(self):
        branches, _ = _branches(
            "Check my crop insurance claim status in Junagadh district Gujarat"
        )
        assert len(branches) <= WebDiscoveryService.MAX_BRANCHES

    def test_discover_integration(self):
        service = WebDiscoveryService()

        def fake_search_all(query, **kwargs):
            return [
                {
                    "url": "https://pmfby.gov.in/status",
                    "title": "PMFBY application status check",
                    "content": "Check PMFBY application status online here. " * 20,
                    "raw_content": "",
                    "score": 0.9,
                }
            ]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("Check my PMFBY application status")

        assert "status" in result["discovery_metadata"]["branches_run"]

    def test_status_combines_with_validity(self):
        """Adversarial #17: currency from validity, never recency."""
        from app.web_rag.retrieval_scorer import rescore
        from types import SimpleNamespace

        classification = SimpleNamespace(
            intent="STATUS", state="Gujarat", domain="finlit",
            society_type=None, case_year=None, season=None,
        )

        def result(url, validity):
            return {
                "chunk_id": "web_x_c101", "source_url": url, "url": url,
                "title": "Ombudsman scheme status", "web_title": "Ombudsman scheme status",
                "text": "scheme status", "content": "scheme status",
                "bm25_score": 2.0, "official": True, "trusted_secondary": False,
                "validity": validity,
            }

        pool = [
            result("https://rbi.org.in/2026/scheme", {"supersession_status": "superseded"}),
            result(
                "https://rbidocs.rbi.org.in/rdocs/scheme-2026",
                {"supersession_status": "current", "effective_from": "2026-07-01"},
            ),
        ]
        ranked = rescore("Is the ombudsman scheme still active?", pool, classification)
        assert "rbidocs" in ranked[0]["source_url"]
