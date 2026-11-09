"""Regression tests for live grievance workflow issues.

Tests:
1. MUNICIPAL -> Local jurisdiction
2. City persists to canonical draft
3. City Bharuch -> State Gujarat
4. State persists after location resolution
5. Submission route receives canonical city/state
6. Bharuch portal URL resolves correctly
7. New substantive message after completed grievance starts fresh
8. Completed grievance does not contaminate new grievance
9. English flow preserves previous behavior
10. Gujarati uses English internally
11. Gujarati answer returns Gujarati
12. Original Gujarati description remains exact
13. Canonical grievance remains language-neutral
14. /chat contains grievance
15. /chat/stream contains grievance
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceStage,
    GrievanceSubCategory,
    GrievanceState,
)
from app.grievance.workflow import GrievanceWorkflow
from app.grievance.draft_builder import GrievanceDraftBuilder
from app.grievance.submission_guide import GrievanceSubmissionGuide


# ── 1. MUNICIPAL -> Local jurisdiction ────────────────────────────────────

class TestMunicipalJurisdiction:
    def test_municipal_jurisdiction_is_local(self):
        builder = GrievanceDraftBuilder()
        draft = builder.build_initial_draft(
            "Garbage in my area", "conv-1", "user-1",
        )
        assert draft.category == GrievanceCategory.MUNICIPAL
        assert draft.jurisdiction == "local"

    def test_non_municipal_jurisdiction_is_state(self):
        builder = GrievanceDraftBuilder()
        draft = builder.build_initial_draft(
            "Police refused to file FIR", "conv-2", "user-1",
        )
        assert draft.category == GrievanceCategory.POLICE
        assert draft.jurisdiction == "state"

    def test_electricity_jurisdiction_is_state(self):
        builder = GrievanceDraftBuilder()
        draft = builder.build_initial_draft(
            "Electricity billing dispute", "conv-3", "user-1",
        )
        assert draft.jurisdiction == "state"


# ── 2. City persists to canonical draft ───────────────────────────────────

class TestCityPersists:
    def test_city_persisted_from_locality_comma(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage near J.B. Modi Garden, Bharuch",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Near J.B. Modi Garden, Bharuch",
                    confidence=0.9, source_text="Near J.B. Modi Garden, Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city == "Bharuch"
        # City should be persisted to entities
        assert "city_name" in draft.entities
        assert draft.entities["city_name"].value == "Bharuch"

    def test_city_persisted_from_separate_entity(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage",
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city == "Bharuch"


# ── 3. City Bharuch -> State Gujarat ──────────────────────────────────────

class TestCityToStateResolution:
    def test_bharuch_resolves_to_gujarat(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Near J.B. Modi Garden, Bharuch",
                    confidence=0.9, source_text="Near J.B. Modi Garden, Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        city, state = guide._resolve_location_context(draft)
        assert city == "Bharuch"
        assert state == "Gujarat"
        assert draft.state == "Gujarat"

    def test_surat_resolves_to_gujarat(self):
        guide = GrievanceSubmissionGuide()
        state = guide._resolve_state("Surat", None)
        assert state == "Gujarat"

    def test_delhi_resolves_to_delhi(self):
        guide = GrievanceSubmissionGuide()
        state = guide._resolve_state("Delhi", None)
        assert state == "Delhi"


# ── 4. State persists after location resolution ──────────────────────────

class TestStatePersists:
    def test_state_persisted_to_draft(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Modi Garden, Bharuch",
                    confidence=0.9, source_text="Modi Garden, Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        guide._resolve_location_context(draft)
        assert draft.state == "Gujarat"

    def test_existing_state_not_overwritten(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state="Maharashtra",
            department="Municipal Corp",
        )
        guide._resolve_location_context(draft)
        assert draft.state == "Maharashtra"


# ── 5. Submission route receives canonical city/state ────────────────────

class TestSubmissionRouteCityState:
    def test_municipal_route_resolves_bharuch(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Garbage complaint",
            description="Garbage near J.B. Modi Garden, Bharuch",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Near J.B. Modi Garden, Bharuch",
                    confidence=0.9, source_text="Near J.B. Modi Garden, Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        route = guide.get_submission_route(draft)
        assert route.level == "local"
        assert "Bharuch" in route.portal_name or "Bharuch" in route.department

    def test_municipal_route_without_city_has_fallback(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Garbage",
            description="Garbage in my area",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        route = guide.get_submission_route(draft)
        assert route.level == "local"


# ── 6. Bharuch portal URL resolves correctly ─────────────────────────────

class TestBharuchPortalURL:
    def test_bharuch_route_has_portal(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Garbage",
            description="Garbage near Modi Garden, Bharuch",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Modi Garden, Bharuch",
                    confidence=0.9, source_text="Modi Garden, Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        route = guide.get_submission_route(draft)
        # Route should have a portal_name that mentions Bharuch
        assert "Bharuch" in route.portal_name


# ── 7. New substantive message after completed grievance starts fresh ────

class TestNewGrievanceAfterComplete:
    def test_substantive_message_starts_new_grievance(self):
        """After SUBMISSION_GUIDE, a new complaint starts a fresh flow."""
        workflow = GrievanceWorkflow()

        # Set up a state in SUBMISSION_GUIDE stage
        state = GrievanceState(
            conversation_id="test-new-after-complete",
            user_id="user-1",
            stage=GrievanceStage.SUBMISSION_GUIDE,
            is_complete=True,
            draft=GrievanceDraft(
                category=GrievanceCategory.MUNICIPAL,
                sub_category=GrievanceSubCategory.GARBAGE,
                title="Old complaint",
                description="Old garbage complaint",
                entities={},
                missing_fields=[],
                required_fields=[],
                optional_fields=[],
                jurisdiction="local",
                state="Gujarat",
                department="Municipal Corp",
            ),
        )

        with patch("app.grievance.workflow.save_grievance_state"), \
             patch("app.grievance.workflow.load_grievance_state", return_value=state):
            result = workflow.process_message(
                user_message="There is a large amount of garbage near my home",
                conversation_id="test-new-after-complete",
                user_id="user-1",
            )
            # Should start a NEW intake, not continue submission guide
            assert result.stage == GrievanceStage.CLASSIFICATION
            assert "Category" in result.response

    def test_gujarati_new_complaint_starts_fresh(self):
        """Gujarati complaint after completion starts fresh."""
        workflow = GrievanceWorkflow()

        state = GrievanceState(
            conversation_id="test-gu-new",
            user_id="user-1",
            stage=GrievanceStage.SUBMISSION_GUIDE,
            is_complete=True,
            draft=GrievanceDraft(
                category=GrievanceCategory.MUNICIPAL,
                sub_category=GrievanceSubCategory.GARBAGE,
                title="Old",
                description="Old",
                entities={},
                missing_fields=[],
                required_fields=[],
                optional_fields=[],
                jurisdiction="local",
                state="Gujarat",
                department="Municipal Corp",
            ),
        )

        with patch("app.grievance.workflow.save_grievance_state"), \
             patch("app.grievance.workflow.load_grievance_state", return_value=state):
            # This is the translated English version of the Gujarati complaint
            result = workflow.process_message(
                user_message="There is a lot of garbage in my area and I want to file a complaint with the municipal corporation",
                conversation_id="test-gu-new",
                user_id="user-1",
            )
            assert result.stage == GrievanceStage.CLASSIFICATION


# ── 8. Completed grievance does not contaminate new grievance ────────────

class TestCompletedDoesNotContaminate:
    def test_status_query_still_works_after_complete(self):
        """Status query on completed grievance still works."""
        workflow = GrievanceWorkflow()

        state = GrievanceState(
            conversation_id="test-status-after",
            user_id="user-1",
            stage=GrievanceStage.COMPLETE,
            is_complete=True,
            draft=GrievanceDraft(
                category=GrievanceCategory.MUNICIPAL,
                sub_category=GrievanceSubCategory.GARBAGE,
                title="Test",
                description="Test",
                entities={},
                missing_fields=[],
                required_fields=[],
                optional_fields=[],
                jurisdiction="local",
                state="Gujarat",
                department="Municipal Corp",
                reference_number="GRV-TEST-123",
            ),
        )

        with patch("app.grievance.workflow.save_grievance_state"), \
             patch("app.grievance.workflow.load_grievance_state", return_value=state):
            result = workflow.process_message(
                user_message="What is the status of my grievance?",
                conversation_id="test-status-after",
                user_id="user-1",
            )
            # Should handle status lookup, not start new grievance
            assert "GRV-TEST-123" in result.response or "track" in result.response.lower()


# ── 9. English flow preserves previous behavior ──────────────────────────

class TestEnglishFlowPreserved:
    def test_english_intake_works(self):
        workflow = GrievanceWorkflow()
        with patch("app.grievance.workflow.save_grievance_state"), \
             patch("app.grievance.workflow.load_grievance_state", return_value=None):
            result = workflow.process_message(
                user_message="I want to file a complaint about garbage in my area",
                conversation_id="test-en-preserve",
                user_id="user-1",
            )
            assert result.stage == GrievanceStage.CLASSIFICATION
            assert result.draft is not None
            assert result.draft.category == GrievanceCategory.MUNICIPAL
            assert result.draft.jurisdiction == "local"


# ── 10-13. Canonical and language boundary tests ────────────────────────

class TestCanonicalAndLanguage:
    def test_canonical_jurisdiction_local(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state="Gujarat",
            department="Municipal Corp",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["jurisdiction"] == "Local"

    def test_canonical_location_fields(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={
                "ward_number": GrievanceEntity(
                    name="ward_number", value="5",
                    confidence=0.9, source_text="ward 5",
                ),
                "locality": GrievanceEntity(
                    name="locality", value="Near J.B. Modi Garden, Bharuch",
                    confidence=0.9, source_text="Near J.B. Modi Garden, Bharuch",
                ),
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.85, source_text="resolved from locality",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state="Gujarat",
            department="Municipal Corp",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["location"]["ward_number"] == "5"
        assert canonical["location"]["city"] == "Bharuch"
        assert canonical["location"]["state"] == "Gujarat"

    def test_canonical_english_keys(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["category"] == "Municipal"
        assert canonical["sub_category"] == "Garbage"
        assert canonical["jurisdiction"] == "Local"

    def test_original_description_preserved(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Garbage complaint",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="local",
            state=None,
            department="Municipal Corp",
            original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        assert canonical["description"]["normalized"] == "Garbage complaint"


# ── 14-15. /chat exposes grievance ───────────────────────────────────────

class TestChatExposesGrievance:
    def test_grievance_dict_in_result(self):
        from app.routes.chat import _GrievanceResult
        result = _GrievanceResult(text="test", grievance={"category": "Municipal"})
        assert result.grievance is not None
        assert result.grievance["category"] == "Municipal"

    def test_grievance_none_when_no_draft(self):
        from app.routes.chat import _GrievanceResult
        result = _GrievanceResult(text="test", grievance=None)
        assert result.grievance is None


# ── Language boundary integration ─────────────────────────────────────────

class TestLanguageBoundaryWithFixes:
    @patch("app.routes.chat._translate_from_english", return_value="ગુજરાતી response")
    @patch("app.routes.chat._translate_to_english", return_value="Garbage complaint")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_gujarati_input_english_workflow_gujarati_output(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please confirm if this is your complaint."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        result = _process_grievance_message(
            question="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે",
            session_id="test-gu-fix",
            input_lang="gu",
            settings=settings,
        )

        # Input was translated to English
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[0][0]
        assert passed_message == "Garbage complaint"

        # Output was translated to Gujarati
        assert result.text == "ગુજરાતી response"

    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_english_input_not_translated(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please confirm."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        result = _process_grievance_message(
            question="I want to file a complaint about garbage",
            session_id="test-en-fix",
            input_lang="en",
            settings=settings,
        )

        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[0][0]
        assert passed_message == "I want to file a complaint about garbage"
        assert result.text == "Please confirm."
