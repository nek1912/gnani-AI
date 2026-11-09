"""P1 jurisdiction-consistency tests (RED first).

Enforces the explicit / session / national distinction:

- unspecified state must NOT acquire Gujarat merely because the domain
  is Gujarat-competent (no silent subject default)
- explicit state is respected and beats inherited session state
- session state is still inherited when the query names no state
- national/central queries stay central
- naive state substrings ("goa" in "goat") must not invent a state
- unknown-publisher evidence must not inherit an explicit query state
- Settings.selected_state (dead duplicate config source) is removed
"""

_classifier = None


def _qc():
    global _classifier
    if _classifier is None:
        from app.web_rag.query_classifier import QueryClassifier

        _classifier = QueryClassifier()
    return _classifier


class TestUnspecifiedState:
    def test_pmfby_without_state_is_central(self):
        cls = _qc().classify("what is pmfby?")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.jurisdiction_source == "none"
        assert cls.assumed_state is False

    def test_schemes_without_state_is_central(self):
        cls = _qc().classify("what is atal pension yojana?")
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_board_of_nominees_invents_no_state(self):
        cls = _qc().classify(
            "how do i file a dispute with the board of nominees?"
        )
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_grievance_without_state_is_central(self):
        cls = _qc().classify("complaint: garbage not collected in my area.")
        assert cls.state is None
        assert cls.jurisdiction == "central"


class TestExplicitVsSession:
    def test_explicit_state_respected(self):
        cls = _qc().classify("crop insurance in maharashtra")
        assert cls.state == "Maharashtra"
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_explicit_beats_session(self):
        cls = _qc().classify(
            "crop insurance in gujarat", default_state="Maharashtra"
        )
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"

    def test_session_inherited_when_no_signal(self):
        cls = _qc().classify("what is pmfby?", default_state="Maharashtra")
        assert cls.state == "Maharashtra"
        assert cls.jurisdiction_source == "session"
        assert cls.assumed_state is True

    def test_district_still_implies_gujarat(self):
        cls = _qc().classify("crop claim junagadh")
        assert cls.district == "Junagadh"
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"


class TestNationalPreserved:
    def test_all_india_stays_central(self):
        cls = _qc().classify("national crop insurance policy for all india")
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_national_beats_session(self):
        cls = _qc().classify(
            "all india crop insurance rules", default_state="Gujarat"
        )
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_international_does_not_suppress_gujarat(self):
        cls = _qc().classify("international cooperative day gujarat")
        assert cls.state == "Gujarat"


class TestNaiveStateSubstrings:
    def test_goat_is_not_goa(self):
        cls = _qc().classify("goat farming subsidy")
        assert cls.state is None

    def test_explicit_maharashtra_still_works(self):
        cls = _qc().classify("what is pmfby in bihar?")
        assert cls.state == "Bihar"
        assert cls.jurisdiction_source == "explicit"


class TestDeadConfigRemoved:
    def test_settings_has_no_selected_state(self):
        from app.config import Settings

        assert "selected_state" not in Settings.model_fields


class TestEffectiveStatePrecedence:
    def test_explicit_query_state_beats_session_state(self):
        from app.web_rag.query_classifier import resolve_expected_state

        cls = _qc().classify("crop insurance in maharashtra")
        assert cls.jurisdiction_source == "explicit"
        assert resolve_expected_state("Gujarat", cls) == "Maharashtra"

    def test_session_state_used_when_no_explicit_signal(self):
        from app.web_rag.query_classifier import resolve_expected_state

        cls = _qc().classify("what is pmfby?", default_state="Maharashtra")
        assert cls.jurisdiction_source == "session"
        assert resolve_expected_state("Maharashtra", cls) == "Maharashtra"

    def test_no_state_anywhere_gives_none(self):
        from app.web_rag.query_classifier import resolve_expected_state

        cls = _qc().classify("what is pmfby?")
        assert resolve_expected_state(None, cls) is None

    def test_national_scope_beats_session_state(self):
        from app.web_rag.query_classifier import resolve_expected_state

        cls = _qc().classify("all india crop insurance rules")
        assert cls.state is None
        assert resolve_expected_state("Gujarat", cls) is None


class TestUnknownPublisherStamping:
    def test_explicit_state_does_not_stamp_unknown(self):
        from app.services.web_rag import stamp_classification_state

        classification_data = {
            "domain": "pmfby",
            "jurisdiction": "state",
            "state": "Maharashtra",
            "jurisdiction_source": "explicit",
        }
        result: dict = {}
        stamped = stamp_classification_state(result, classification_data)
        assert stamped.get("state") is None
        assert stamped.get("jurisdiction") is None

    def test_session_state_may_stamp_unknown(self):
        from app.services.web_rag import stamp_classification_state

        classification_data = {
            "domain": "pmfby",
            "jurisdiction": "state",
            "state": "Gujarat",
            "jurisdiction_source": "session",
        }
        result: dict = {}
        stamped = stamp_classification_state(result, classification_data)
        assert stamped.get("state") == "Gujarat"

    def test_existing_values_never_overwritten(self):
        from app.services.web_rag import stamp_classification_state

        classification_data = {
            "domain": "pmfby",
            "jurisdiction": "state",
            "state": "Gujarat",
            "jurisdiction_source": "session",
        }
        result = {"jurisdiction": "central", "state": None}
        stamped = stamp_classification_state(result, classification_data)
        assert stamped.get("jurisdiction") == "central"
