"""P1 classifier-consistency tests (RED first).

Covers the known collision classes between AnchorStore (first-match,
word-boundary) and QueryClassifier (substring, max-score tie-break):

- PMJJBY/PMSBY vs PMFBY (generic "apply/registration for" outweighs codes)
- RTI vs PACS (domain tie hides the grievance signal)
- grievance/complaint about crop insurance (intent tie hides GRIEVANCE)
- district-collector / ICT-style substring collisions
- APY anti-substring guard (therapy must never match a pension keyword)
- AnchorStore <-> QueryClassifier agreement on fixed classes
- single deterministic effective-domain rule used by both pipelines
"""

import re

import numpy as np

from app.domains import AnchorStore

_classifier = None


def _qc():
    global _classifier
    if _classifier is None:
        from app.web_rag.query_classifier import QueryClassifier

        _classifier = QueryClassifier()
    return _classifier


def _anchor_rules():
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).parent.parent / "data" / "keyword_rules.json").read_text(
            encoding="utf-8"
        )
    )


def _anchor_store():
    rules = _anchor_rules()
    vecs = {d: np.zeros(16) for d in rules}
    return AnchorStore(rules=rules, domain_vectors=vecs)


class TestSchemeCodeCollisions:
    def test_pmfby_code_beats_generic_registration_phrase(self):
        cls = _qc().classify("registration for pmfby")
        assert cls.domain == "pmfby"

    def test_pmfby_code_beats_generic_apply_phrase(self):
        cls = _qc().classify("i am going to apply for pmfby")
        assert cls.domain == "pmfby"

    def test_pmjjby_stays_schemes(self):
        cls = _qc().classify("what is pmjjby?")
        assert cls.domain == "schemes"

    def test_pmsby_stays_schemes(self):
        cls = _qc().classify("what is pmsby?")
        assert cls.domain == "schemes"

    def test_pmfby_vs_pmjjby_is_deterministic(self):
        # Both codes present: no single right answer, but the outcome
        # must be deterministic and must not fall through to a generic
        # domain (previously "agriculture" via farm/farmers double-count).
        first = _qc().classify("pmfby vs pmjjby which is better for farmers?")
        second = _qc().classify("pmfby vs pmjjby which is better for farmers?")
        assert first.domain == second.domain
        assert first.domain in ("pmfby", "schemes")


class TestGrievanceSafety:
    def test_rti_pacs_routes_to_grievance(self):
        cls = _qc().classify("rti for pacs audit report")
        assert cls.domain == "grievance"

    def test_pacs_complaint_intent_is_grievance(self):
        cls = _qc().classify(
            "my pacs loan was rejected, i want to complain about my society"
        )
        assert cls.intent == "GRIEVANCE"
        assert cls.domain == "grievance"

    def test_crop_insurance_complaint_keeps_grievance_intent(self):
        cls = _qc().classify(
            "my crop insurance claim rejected, i want to complain"
        )
        assert cls.intent == "GRIEVANCE"


class TestNaiveSubstringCollisions:
    def test_goat_does_not_trigger_goa(self):
        cls = _qc().classify("goat farming subsidy")
        assert cls.state is None

    def test_therapy_does_not_trigger_pension(self):
        cls = _qc().classify("i need therapy for stress")
        assert cls.domain == "general"

    def test_district_collector_does_not_hijack_domain(self):
        cls = _qc().classify(
            "no response from the district collector office for 3 months"
        )
        assert cls.domain != "pacs_computerization"

    def test_driving_licence_beats_generic_apply_for(self):
        cls = _qc().classify("how to apply for driving licence?")
        assert cls.domain == "driving_licence"


class TestAnchorQueryClassifierAgreement:
    def test_ict_query_not_computerization(self):
        domain, _ = _anchor_store().classify(
            "Tell me about the ICT project", [0.0] * 16
        )
        assert domain != "pacs_computerization"

    def test_driving_licence_agreement(self):
        domain, _ = _anchor_store().classify(
            "How to apply for driving licence?", [0.0] * 16
        )
        assert domain == "driving_licence"
        assert _qc().classify("how to apply for driving licence?").domain == (
            "driving_licence"
        )

    def test_rules_have_no_bare_ict_keyword(self):
        rules = _anchor_rules()
        for domain, kws in rules.items():
            assert "ict" not in [k.lower() for k in kws], domain

    def test_pan_docs_still_schemes(self):
        # Guard: generic "apply for" with no scheme code keeps working.
        cls = _qc().classify(
            "what documents are required to apply for a pan card in india?"
        )
        assert cls.domain == "schemes"

    def test_pmfby_info_still_pmfby(self):
        cls = _qc().classify("what is pmfby? explain in brief.")
        assert cls.domain == "pmfby"

    def test_legitimate_gujarat_pmfby_still_works(self):
        cls = _qc().classify("crop insurance in gujarat")
        assert cls.domain == "pmfby"
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"


class TestEffectiveDomainRule:
    def test_anchor_wins_when_specific(self):
        from app.web_rag.query_classifier import effective_domain

        cls = _qc().classify("what is pmjjby?")
        assert cls.domain == "schemes"
        assert effective_domain("financial_inclusion", cls) == (
            "financial_inclusion"
        )

    def test_classifier_fills_in_for_general_anchor(self):
        from app.web_rag.query_classifier import effective_domain

        cls = _qc().classify("what is pmfby?")
        assert effective_domain("general", cls) == "pmfby"
        assert effective_domain("", cls) == "pmfby"

    def test_out_of_scope_anchor_is_preserved(self):
        from app.web_rag.query_classifier import effective_domain

        cls = _qc().classify("what is pmfby?")
        assert effective_domain("out_of_scope", cls) == "out_of_scope"

    def test_word_boundary_helper(self):
        from app.web_rag.query_classifier import _match_keyword

        assert _match_keyword("goa", "goat farming") is False
        assert _match_keyword("goa", "i love goa beaches") is True
        assert _match_keyword("crop insurance", "crop insurance claim") is True
        assert re.search(r"\bapy\b", "therapy") is None
