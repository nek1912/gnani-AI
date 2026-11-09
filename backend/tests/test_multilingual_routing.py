"""Multilingual grievance routing tests.

Verifies that translation failure does NOT change the intended routing.
Tests both translation-success and translation-failure paths for 6 cases.
"""


from app.routes.chat import _should_route_to_grievance, _GUIDANCE_INTENTS
from app.web_rag.query_classifier import QueryClassifier

_qc = QueryClassifier()


def _classify(query_lower: str):
    return _qc.classify(query_lower)


# ── Translation-failure path: raw non-english queries ──────────────────────


class TestTranslationFailure:
    """Raw non-English queries routed as if translation failed."""

    def test_1_gu_info_to_rag(self):
        q = "PMFBY શું છે અને તે ખેડૂતોને કેવી રીતે મદદ કરે છે?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="gu"), (
            "Gujarati informational should route to RAG, not grievance"
        )

    def test_2_hi_info_to_rag(self):
        q = "पीएमएफबीवाई क्या है और यह किसानों को कैसे लाभ पहुँचाता है?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="hi"), (
            "Hindi informational should route to RAG, not grievance"
        )

    def test_3_gu_grievance_to_grievance(self):
        q = "મારી PACS એ મેં માંગેલી સેવા આપી નથી અને કોઈ મારી મદદ કરી રહ્યું નથી. હું ફરિયાદ કરવા માંગુ છું."
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="gu"), (
            "Gujarati grievance with 'ફરિયાદ' should route to grievance"
        )

    def test_4_hi_grievance_to_grievance(self):
        q = "मैंने पीएमएफबीवाई के लिए आवेदन किया था लेकिन मेरा दावा अभी तक नहीं मिला है। मैं शिकायत करना चाहता हूँ।"
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="hi"), (
            "Hindi grievance with 'शिकायत' should route to grievance even when APPLICATION also matches"
        )

    def test_5_en_grievance_to_grievance(self):
        q = "Why hasn't my PMFBY claim been paid?"
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="en"), (
            "English grievance should route to grievance"
        )

    def test_6_en_info_to_rag(self):
        q = "What services does a PACS provide to its members?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="en"), (
            "English informational should route to RAG"
        )


# ── Translation-success path: translated english queries ───────────────────


class TestTranslationSuccess:
    """Translated English queries routed after successful translation."""

    def test_1_gu_info_translated(self):
        q = "What is PMFBY and how does it help farmers?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="en")

    def test_2_hi_info_translated(self):
        q = "What is PMFBY and how does it benefit farmers?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="en")

    def test_3_gu_grievance_translated(self):
        q = "My PACS did not provide the service I requested and nobody is helping me. I want to file a complaint."
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="en")

    def test_4_hi_grievance_translated(self):
        q = "I applied for PMFBY but my claim has not been received yet. I want to complain."
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="en")

    def test_5_en_grievance_unchanged(self):
        q = "Why hasn't my PMFBY claim been paid?"
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="en")

    def test_6_en_info_unchanged(self):
        q = "What services does a PACS provide to its members?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q, input_lang="en")


# ── Tier 2 override: guidance intent + grievance keyword ───────────────────


class TestTierTwoOverride:
    """When both guidance and grievance keywords present, grievance wins."""

    def test_hi_grievance_with_application_keyword(self):
        # Two distinct REGISTRATION hits beat one GRIEVANCE hit outright,
        # so the Tier 2 override (not the Tier 1 intent rule) routes this
        # to grievance. Single-hit ties now resolve to GRIEVANCE directly.
        q = "मुझे PMFBY में पंजीकरण करना है, please help me enroll, लेकिन मेरी शिकायत है कि portal काम नहीं करता।"
        cls = _classify(q.lower())
        assert cls.intent == "REGISTRATION", "QC should pick REGISTRATION (2 distinct hits beat 1)"
        assert _should_route_to_grievance(cls, q, input_lang="hi"), (
            "Tier 2 override: grievance keyword in raw query should override REGISTRATION"
        )

    def test_en_grievance_with_application_keyword(self):
        q = "I applied for PMFBY and my claim hasn't been paid. I want to complain."
        cls = _classify(q.lower())
        assert _should_route_to_grievance(cls, q, input_lang="en"), (
            "English query with 'complain' should route to grievance"
        )

    def test_guidance_without_grievance_stays_rag(self):
        q = "How do I apply for PMFBY?"
        cls = _classify(q.lower())
        assert cls.intent in _GUIDANCE_INTENTS
        assert not _should_route_to_grievance(cls, q, input_lang="en"), (
            "Pure guidance query without grievance keyword should route to RAG"
        )


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_gu_negation_without_grievance_keyword(self):
        """Non-English query with problem indicators but no explicit grievance keyword."""
        q = "મારું PMFBY દાવો હજુ મળ્યું નથી"
        cls = _classify(q.lower())
        result = _should_route_to_grievance(cls, q, input_lang="gu")
        # No grievance keyword in query → Tier 3: non-English → False → RAG
        assert not result

    def test_hi_negation_without_grievance_keyword(self):
        q = "मेरा PMFBY दावा अभी तक नहीं मिला"
        cls = _classify(q.lower())
        result = _should_route_to_grievance(cls, q, input_lang="hi")
        assert not result

    def test_en_negation_with_problem_signal(self):
        """English query with problem signal — should still route to grievance."""
        q = "My PMFBY claim has not been received"
        cls = _classify(q.lower())
        result = _should_route_to_grievance(cls, q, input_lang="en")
        assert result

    def test_default_input_lang_is_en(self):
        """Without input_lang, behavior matches English path."""
        q = "What is PMFBY?"
        cls = _classify(q.lower())
        assert not _should_route_to_grievance(cls, q)
