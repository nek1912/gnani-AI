"""Tests for the QueryClassifier-authoritative routing hierarchy.

Verifies that a confident QueryClassifier guidance intent is NOT overridden
by is_grievance_query(), while genuine complaints still reach the
GrievanceWorkflow.
"""

from unittest.mock import patch

from app.routes.chat import _should_route_to_grievance, _GUIDANCE_INTENTS
from app.web_rag.query_classifier import QueryClassifier

_classifier = QueryClassifier()


def _classify(query):
    return _classifier.classify(query.lower())


class TestRoutingHierarchy:

    def test_A_pan_card_docs_goes_to_rag(self):
        q = "What documents are required to apply for a PAN card in India?"
        cls = _classify(q)
        assert cls.intent == "APPLICATION", f"unexpected intent: {cls.intent}"
        assert cls.domain != "grievance"
        assert not _should_route_to_grievance(cls, q)

    def test_B_pmfby_info_goes_to_rag(self):
        q = "What is PMFBY? Explain in brief."
        cls = _classify(q)
        assert cls.domain == "pmfby"
        assert not _should_route_to_grievance(cls, q)

    def test_C_pmfby_complaint_goes_to_grievance(self):
        q = "I applied for PMFBY and my claim hasn't been paid. I want to complain."
        cls = _classify(q)
        assert cls.intent == "GRIEVANCE", f"unexpected intent: {cls.intent}"
        assert _should_route_to_grievance(cls, q)

    @patch("app.routes.chat._get_grievance_workflow")
    def test_D_ayushman_bharat_goes_to_rag(self, mock_wf):
        q = "What is the process to apply for an Ayushman Bharat health card?"
        cls = _classify(q)
        # Starts with "What is" → INFORMATIONAL (ambiguous) → is_grievance_query tiebreaker
        # Since it's informational, is_grievance_query returns False → RAG
        assert cls.intent == "INFORMATIONAL"
        mock_wf.return_value.is_grievance_query.return_value = False
        assert not _should_route_to_grievance(cls, q)

    def test_E_hindi_passport_goes_to_rag(self):
        q = "\u092d\u093e\u0930\u0924 \u092e\u0947\u092a\u093e\u0938\u094d\u092a\u094b\u0930\u094d\u091f \u0915\u0947 \u0932\u093f\u090f \u0906\u0935\u0947\u0926\u0928 \u0915\u0930\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928-\u0915\u094c\u0928 \u0938\u0947 \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u0906\u0935\u0936\u094d\u092f\u0915 \u0939\u0948\u0902?"
        cls = _classify(q)
        assert cls.intent in _GUIDANCE_INTENTS, f"unexpected intent: {cls.intent}"
        assert not _should_route_to_grievance(cls, q)

    @patch("app.routes.chat._get_grievance_workflow")
    def test_F_electricity_bill_wrong_falls_through(self, mock_wf):
        q = "My electricity bill is wrong."
        cls = _classify(q)
        assert cls.intent == "INFORMATIONAL", f"unexpected intent: {cls.intent}"
        mock_wf.return_value.is_grievance_query.return_value = True
        assert _should_route_to_grievance(cls, q)
        mock_wf.return_value.is_grievance_query.assert_called_once_with(q)

    @patch("app.routes.chat._get_grievance_workflow")
    def test_F_electricity_bill_not_grievance(self, mock_wf):
        q = "My electricity bill is wrong."
        cls = _classify(q)
        assert cls.intent == "INFORMATIONAL"
        mock_wf.return_value.is_grievance_query.return_value = False
        assert not _should_route_to_grievance(cls, q)


class TestGuidanceIntentsBypass:

    @patch("app.routes.chat._get_grievance_workflow")
    def test_guidance_skips_detector(self, mock_wf):
        q = "How do I apply for a driving licence?"
        cls = _classify(q)
        assert cls.intent in _GUIDANCE_INTENTS
        assert not _should_route_to_grievance(cls, q)
        mock_wf.return_value.is_grievance_query.assert_not_called()

    @patch("app.routes.chat._get_grievance_workflow")
    def test_grievance_skips_detector(self, mock_wf):
        q = "Complaint: garbage not collected in my area."
        cls = _classify(q)
        assert cls.intent == "GRIEVANCE"
        assert _should_route_to_grievance(cls, q)
        mock_wf.return_value.is_grievance_query.assert_not_called()


class TestIntentClassification:

    def test_pan_docs(self):
        cls = _classify("What documents are required to apply for a PAN card in India?")
        assert cls.intent == "APPLICATION"
        assert cls.domain == "schemes"

    def test_pmfby_info(self):
        cls = _classify("What is PMFBY? Explain in brief.")
        assert cls.intent == "INFORMATIONAL"
        assert cls.domain == "pmfby"

    def test_pmfby_complaint(self):
        cls = _classify("I applied for PMFBY and my claim hasn't been paid. I want to complain.")
        assert cls.intent == "GRIEVANCE"
        assert cls.domain == "pmfby"

    def test_ayushman_bharat(self):
        cls = _classify("What is the process to apply for an Ayushman Bharat health card?")
        # Starts with "What is" → INFORMATIONAL wins over APPLICATION
        assert cls.intent == "INFORMATIONAL"

    def test_hindi_passport(self):
        q = "\u092d\u093e\u0930\u0924 \u092e\u0947\u092a\u093e\u0938\u094d\u092a\u094b\u0930\u094d\u091f \u0915\u0947 \u0932\u093f\u090f \u0906\u0935\u0947\u0926\u0928 \u0915\u0930\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928-\u0915\u094c\u0928 \u0938\u0947 \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u0906\u0935\u0936\u094d\u092f\u0915 \u0939\u0948\u0902?"
        cls = _classify(q)
        assert cls.intent in _GUIDANCE_INTENTS

    def test_electricity_bill(self):
        cls = _classify("My electricity bill is wrong.")
        assert cls.intent == "INFORMATIONAL"
        assert cls.domain == "general"
