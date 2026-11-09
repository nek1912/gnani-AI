"""P0-5 bounded facet retrieval tests.

Covers: intent->facet mapping, implied-only branch generation (no
over-generation), branch cap, concurrent branch execution,
cross-branch dedup, RRF/fusion stability, and advisory-only facet
coverage (never a second gate).
"""

import threading
from unittest.mock import patch

from app.web_rag.facets import (
    MAX_FACET_BRANCHES,
    facet_coverage,
    facets_for_intent,
    result_facets,
)
from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.service import WebDiscoveryService

_classifier = QueryClassifier()


def _item(url, title, text):
    return {
        "url": url,
        "title": title,
        "content": text,
        "raw_content": text,
        "score": 0.9,
        "favicon": None,
    }


_FIXTURES = [
    _item(
        "https://pmfby.gov.in/guidelines",
        "PMFBY crop insurance Gujarat guidelines",
        "PMFBY crop insurance Gujarat guidelines eligibility criteria "
        "for notified crops. " * 10,
    ),
    _item(
        "https://agri.gujarat.gov.in/schemes",
        "Gujarat agriculture schemes portal apply online",
        "Gujarat agriculture schemes portal apply online status track "
        "form download. " * 10,
    ),
]


def _branches(query):
    cls = _classifier.classify(query)
    service = WebDiscoveryService()
    return service._build_stage1_branches(query, cls, query), cls


class TestFacetMapping:
    def test_deadline_intent_single_facet(self):
        assert facets_for_intent("DEADLINE") == ["deadline"]

    def test_grievance_intent_two_facets(self):
        assert facets_for_intent("GRIEVANCE") == ["escalation", "authority"]

    def test_informational_implies_nothing(self):
        assert facets_for_intent("INFORMATIONAL") == []
        assert facets_for_intent("COMPARISON") == []
        assert facets_for_intent(None) == []

    def test_application_implies_procedure(self):
        assert facets_for_intent("APPLICATION") == ["procedure"]


class TestBranchGeneration:
    def test_simple_one_facet_query(self):
        branches, _ = _branches("Tell me the subsidy deadline")
        facet_branches = [b for b in branches if b["name"].startswith("facet:")]
        assert len(facet_branches) == 1
        assert facet_branches[0]["name"] == "facet:deadline"

    def test_two_facet_grievance_query(self):
        branches, _ = _branches(
            "My crop insurance claim was rejected; how do I appeal?"
        )
        facet_names = sorted(
            b["name"] for b in branches if b["name"].startswith("facet:")
        )
        assert facet_names == ["facet:authority", "facet:escalation"]

    def test_no_facet_branches_for_informational(self):
        branches, _ = _branches("What is PMFBY?")
        assert not [b for b in branches if b["name"].startswith("facet:")]
        assert "doctype" not in [b["name"] for b in branches]

    def test_facet_branch_cap(self):
        # Even the richest intent yields at most MAX_FACET_BRANCHES.
        branches, _ = _branches(
            "My crop insurance claim was rejected in Gujarat; how do I appeal?"
        )
        facet_branches = [b for b in branches if b["name"].startswith("facet:")]
        assert len(facet_branches) <= MAX_FACET_BRANCHES

    def test_total_branch_cap(self):
        queries = [
            "My crop insurance claim was rejected in Gujarat; how do I appeal?",
            "What is PMFBY?",
            "How do I apply for i-Khedut tractor subsidy in Junagadh?",
            "My electricity bill is wrong.",
        ]
        for query in queries:
            branches, _ = _branches(query)
            assert len(branches) <= WebDiscoveryService.MAX_BRANCHES, query
            assert branches[0]["name"] == "primary", query

    def test_typical_branch_counts(self):
        branches, _ = _branches("What is PMFBY?")
        # P1: no-signal query is central — primary + hindi only, no
        # jurisdiction/gujarati branches without a state signal.
        assert len(branches) == 2
        assert [b["name"] for b in branches] == ["primary", "hindi"]
        branches, _ = _branches("My electricity bill is wrong.")
        assert len(branches) == 1

    def test_facet_branch_uses_anchors(self):
        branches, _ = _branches(
            "Tell me the subsidy deadline in Gujarat"
        )
        facet_branch = next(b for b in branches if b["name"] == "facet:deadline")
        assert any("gujarat" in d for d in facet_branch["include_domains"])
        assert "last date" in facet_branch["query"]

    def test_doctype_branch_terms(self):
        branches, _ = _branches(
            "How do I apply for i-Khedut tractor subsidy in Junagadh?"
        )
        doctype = next(b for b in branches if b["name"] == "doctype")
        assert "GR" in doctype["query"] or "circular" in doctype["query"]


class TestConcurrentBranches:
    def test_branches_run_concurrently(self):
        service = WebDiscoveryService()
        second_started = threading.Event()
        first_can_finish = threading.Event()
        calls = []

        def fake_search_all(query, **kwargs):
            name = (kwargs.get("include_domains") or ["?"])[0]
            calls.append(name)
            if "PRIMARY-MARKER" in query:
                assert second_started.wait(timeout=10), "second branch never started"
                return []
            second_started.set()
            first_can_finish.wait(timeout=10)
            return []

        branches = [
            {
                "name": "first",
                "query": "PRIMARY-MARKER slow query",
                "max_results": 5,
                "only_official": False,
            },
            {
                "name": "second",
                "query": "fast query",
                "max_results": 5,
                "only_official": False,
            },
        ]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            merged, counts = service._search_branches(branches)

        # If execution were sequential, the first branch would block
        # forever waiting for the second branch's event.
        assert merged == []
        assert set(counts) == {"first", "second"}

    def test_branch_failure_does_not_kill_siblings(self):
        service = WebDiscoveryService()

        def fake_search_all(query, **kwargs):
            if "boom" in query:
                raise RuntimeError("branch boom")
            return [_item("https://example.gov.in/a", "Title words here", "Body " * 30)]

        branches = [
            {"name": "bad", "query": "boom query", "only_official": False},
            {"name": "good", "query": "fine query", "only_official": False},
        ]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            merged, counts = service._search_branches(branches)

        assert len(merged) == 1
        assert merged[0]["branch"] == "good"
        assert counts.get("good") == 1

    def test_cross_branch_dedup_first_wins(self):
        service = WebDiscoveryService()
        shared = _item("https://example.gov.in/shared", "Shared title", "Shared " * 30)

        def fake_search_all(query, **kwargs):
            return [dict(shared)]

        branches = [
            {"name": "a", "query": "query a", "only_official": False},
            {"name": "b", "query": "query b", "only_official": False},
        ]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            merged, _ = service._search_branches(branches)

        assert len(merged) == 1
        assert merged[0]["branch"] == "a"


class TestCoverageAdvisory:
    def test_coverage_detects_supported_facet(self):
        results = [
            {
                "chunk_id": "web_abc_c101",
                "web_title": "Scheme eligibility criteria",
                "title": "Scheme eligibility criteria",
                "text": "Who is eligible and the criteria for applicants.",
            }
        ]
        coverage = facet_coverage(results, ["eligibility", "deadline"])
        assert coverage["eligibility"]["supported"] is True
        assert coverage["eligibility"]["chunk_ids"] == ["web_abc_c101"]
        assert coverage["deadline"]["supported"] is False
        assert results[0]["facets"] == ["eligibility"]

    def test_result_facets_empty_without_match(self):
        assert result_facets("General overview", "Nothing specific here.", ["deadline"]) == []

    def test_coverage_is_advisory_not_gate(self):
        # Fixture carries no facet words: coverage all False, yet
        # discover() still returns results (no second gate).
        service = WebDiscoveryService()

        def fake_search_all(query, **kwargs):
            return list(_FIXTURES)

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("Tell me the subsidy deadline")

        assert len(result["results"]) > 0
        assert result["discovery_metadata"]["facets_implied"] == ["deadline"]
        assert "facet_coverage" in result["discovery_metadata"]

    def test_coverage_metadata_shape(self):
        service = WebDiscoveryService()

        def fake_search_all(query, **kwargs):
            return list(_FIXTURES)

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("What is PMFBY?")

        assert result["discovery_metadata"]["facets_implied"] == []
        assert result["discovery_metadata"]["facet_coverage"] == {}
