"""Targeted tests for the _INFORMATIONAL_RE regex fix.

Verifies that informational questions route to RAG while genuine
grievances still reach the GrievanceWorkflow.
"""

import pytest

from app.grievance.workflow import GrievanceWorkflow
from app.routes.chat import _should_route_to_grievance
from app.web_rag.query_classifier import QueryClassifier

_classifier = QueryClassifier()


def _classify(query):
    return _classifier.classify(query.lower())


class TestInformationalRegex:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.wf = GrievanceWorkflow()

    def test_1_pacs_services_to_rag(self):
        q = "What services does a PACS provide to its members?"
        cls = _classify(q)
        assert not _should_route_to_grievance(cls, q), (
            "PACS services query should route to RAG, not grievance"
        )

    def test_2_cooperative_responsibilities_to_rag(self):
        q = "What are the basic responsibilities of a cooperative society?"
        cls = _classify(q)
        assert not _should_route_to_grievance(cls, q), (
            "Cooperative responsibilities query should route to RAG"
        )

    def test_3_pmfby_info_to_rag(self):
        q = "What is PMFBY?"
        cls = _classify(q)
        assert not _should_route_to_grievance(cls, q), (
            "PMFBY informational query should route to RAG"
        )

    def test_4_pmfby_claim_delay_to_grievance(self):
        q = "Why hasn't my PMFBY claim been paid?"
        cls = _classify(q)
        assert _should_route_to_grievance(cls, q), (
            "PMFBY claim delay query should route to grievance"
        )

    def test_5_pmfby_complaint_to_grievance(self):
        q = "I applied for PMFBY and my claim hasn't been paid. I want to complain."
        cls = _classify(q)
        assert _should_route_to_grievance(cls, q), (
            "PMFBY complaint query should route to grievance"
        )

    def test_6_electricity_bill_wrong_to_grievance(self):
        q = "My electricity bill is wrong."
        cls = _classify(q)
        assert _should_route_to_grievance(cls, q), (
            "Electricity bill wrong query should route to grievance"
        )

    def test_7_can_apply_pmfby_to_rag(self):
        q = "Can I apply for PMFBY?"
        cls = _classify(q)
        assert not _should_route_to_grievance(cls, q), (
            "PMFBY application query should route to RAG"
        )

    def test_8_register_cooperative_member_to_rag(self):
        q = "How do I register as a member of a cooperative society?"
        cls = _classify(q)
        assert not _should_route_to_grievance(cls, q), (
            "Cooperative registration query should route to RAG"
        )


class TestInformationalRegexEdgeCases:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.wf = GrievanceWorkflow()

    def test_why_question_with_problem_signal_stays_grievance(self):
        q = "Why is my electricity bill wrong?"
        assert self.wf.is_grievance_query(q), (
            "'Why' question with problem signal should be grievance"
        )

    def test_how_to_with_no_problem_is_informational(self):
        q = "How to apply for a PMFBY claim?"
        assert not self.wf.is_grievance_query(q), (
            "'How to' question with no problem signal should be informational"
        )

    def test_can_question_with_no_problem_is_informational(self):
        q = "Can a cooperative society get a bank loan?"
        assert not self.wf.is_grievance_query(q), (
            "'Can' question with no problem signal should be informational"
        )

    def test_non_question_with_problem_signal_stays_grievance(self):
        q = "My electricity bill is wrong."
        assert self.wf.is_grievance_query(q), (
            "Non-question with problem signal should be grievance"
        )

    def test_which_question_informational(self):
        q = "Which PMFBY scheme is best for Kharif crops?"
        assert not self.wf.is_grievance_query(q), (
            "'Which' question should be informational"
        )

    def test_should_question_informational(self):
        q = "Should I apply for PMFBY this season?"
        assert not self.wf.is_grievance_query(q), (
            "'Should' question with no problem signal should be informational"
        )
