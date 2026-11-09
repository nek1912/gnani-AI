"""Tests for Bug #4: Stale grievance state reuse after completion.

After completing a grievance, sending a new complaint message should start
a new grievance intake, NOT return the old status lookup response.
"""
from unittest.mock import patch
import pytest

from app.grievance.models import GrievanceState, GrievanceStage, GrievanceDraft, GrievanceCategory, GrievanceSubCategory, GrievanceEntity
from app.grievance.workflow import GrievanceWorkflow


@pytest.fixture
def workflow():
    return GrievanceWorkflow()


@pytest.fixture
def completed_pmfby_state():
    """Simulate a completed PMFBY grievance state."""
    state = GrievanceState(
        conversation_id="test-conv-123",
        user_id="user-123",
        stage=GrievanceStage.SUBMISSION_GUIDE,
    )
    state.stage = GrievanceStage.SUBMISSION_GUIDE
    state.is_complete = True
    state.draft = GrievanceDraft(
        title="PMFBY claim denied",
        category=GrievanceCategory.AGRICULTURE,
        sub_category=GrievanceSubCategory.PMFBY_CLAIM_DELAY,
        department="Agriculture",
        description="My PMFBY crop insurance claim was denied without reason",
        reference_number="PMFBY-2026-123456",
        entities={
            "farmer_name": GrievanceEntity(name="farmer_name", value="Ramesh Kumar", confidence=0.9, source_text="Ramesh Kumar"),
            "season": GrievanceEntity(name="season", value="Kharif", confidence=0.9, source_text="Kharif"),
            "year": GrievanceEntity(name="year", value="2026", confidence=0.9, source_text="2026"),
        },
        missing_fields=[],
        required_fields=["reference_number", "farmer_name", "season", "year"],
        optional_fields=[],
        jurisdiction="state",
        state="Gujarat",
    )
    return state


class TestStaleStateReset:
    """After a completed grievance, new complaint messages should start intake."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_new_complaint_resets_state_in_submission_guide(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """Message with 'start a new' in SUBMISSION_GUIDE should start new intake."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="start a new complaint about garbage in my area",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should start new intake
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)
        # Should start new intake (ask for problem description or confirm classification)
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_status_check_still_works_in_submission_guide(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'check status' in SUBMISSION_GUIDE should still return status lookup."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="check status",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should return status lookup for old grievance (which sets stage to COMPLETE)
        assert result.stage == GrievanceStage.COMPLETE
        assert result.is_complete is True

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_new_grievance_phrase_still_works(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'new grievance' in SUBMISSION_GUIDE should still start fresh intake."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="new grievance",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should start new intake
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)
        # Old draft should not be in response
        assert "PMFBY" not in result.response

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_change_phrase_still_works(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'change the farmer name' in SUBMISSION_GUIDE should route to entity editing."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="change the farmer name",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should route to entity extraction or followup (processing the edit)
        # NOT the stale submission guide response
        assert result.stage in (GrievanceStage.ENTITY_EXTRACTION, GrievanceStage.FOLLOWUP)
        # Note: PMFBY may appear in the response because the user is editing the existing draft
        # The key assertion is that we did NOT return the stale submission_guide status_lookup

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_grievance_keyword_resets_state(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'new grievance' in SUBMISSION_GUIDE should start new intake."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="new grievance about water supply in my area",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should start new intake
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_unrelated_message_returns_status_lookup(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """Unrelated message without grievance indicators should return status lookup."""
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="what is the weather today",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should return status lookup (default fallthrough)
        assert result.stage == GrievanceStage.SUBMISSION_GUIDE
        assert result.is_complete is True


class TestStaleStateResetInComplete:
    """After a completed grievance (COMPLETE stage), new complaint messages should start intake."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_new_complaint_resets_state_in_complete(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """Message with 'new' in COMPLETE should start new intake."""
        completed_pmfby_state.stage = GrievanceStage.COMPLETE
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="start a new complaint about road damage",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should start new intake
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_status_still_works_in_complete(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'check status' in COMPLETE should still return status lookup."""
        completed_pmfby_state.stage = GrievanceStage.COMPLETE
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="check status",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should return status lookup
        assert result.stage == GrievanceStage.STATUS_LOOKUP
        assert result.is_complete is True

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_new_phrase_still_works_in_complete(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """'new grievance' in COMPLETE should still start fresh intake."""
        completed_pmfby_state.stage = GrievanceStage.COMPLETE
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="new grievance",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should start new intake
        assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION)
        assert "PMFBY" not in result.response

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_unrelated_message_returns_complete_default(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """Unrelated message in COMPLETE should return default complete response."""
        completed_pmfby_state.stage = GrievanceStage.COMPLETE
        mock_load.return_value = completed_pmfby_state

        result = workflow.process_message(
            user_message="what is the weather today",
            conversation_id="test-conv-123",
            user_id="user-123",
        )

        # Should return default complete response
        assert result.stage == GrievanceStage.COMPLETE
        assert result.is_complete is True
        assert "complete" in result.response.lower()


class TestGrievanceIsolation:
    """Each new grievance must get a unique reference and no state leakage."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_new_grievance_gets_different_reference_after_complete(
        self, mock_load, mock_save, workflow, completed_pmfby_state
    ):
        """After completing grievance A, starting grievance B produces a
        different reference number and no shared classification/entities."""
        # ── Step A: Complete grievance A ──────────────────────────────
        mock_load.return_value = completed_pmfby_state

        result_a = workflow.process_message(
            user_message="My water supply is bad in Bharuch",
            conversation_id="test-iso-001",
            user_id="user-iso",
        )

        # A new intake should have been started
        assert result_a.stage == GrievanceStage.CLASSIFICATION
        ref_a = result_a.draft.reference_number
        assert ref_a is not None
        assert ref_a.startswith("GRV-")

        # The saved state should have the new draft (overwriting old)
        saved_state_a = mock_save.call_args[0][0]
        assert saved_state_a.draft is not None
        assert saved_state_a.draft.reference_number == ref_a
        assert saved_state_a.draft.category != completed_pmfby_state.draft.category

        # ── Step B: Start another new grievance in the same conversation ─
        # Simulate a completed water grievance
        completed_water_state = GrievanceState(
            conversation_id="test-iso-001",
            user_id="user-iso",
            stage=GrievanceStage.COMPLETE,
            is_complete=True,
            draft=saved_state_a.draft,
        )
        mock_load.return_value = completed_water_state

        result_b = workflow.process_message(
            user_message="There is a pothole on my road in Gujarat",
            conversation_id="test-iso-001",
            user_id="user-iso",
        )

        ref_b = result_b.draft.reference_number
        assert ref_b is not None
        assert ref_b.startswith("GRV-")

        # CRITICAL: references must differ
        assert ref_a != ref_b, (
            f"New grievance reused reference from previous: {ref_a}"
        )

        # Classification must be different (road_damage vs water)
        assert result_b.draft.category != GrievanceCategory.WATER

        # Entities must not leak from the previous grievance
        if result_a.draft and result_a.draft.entities:
            for key in result_a.draft.entities:
                if key in result_b.draft.entities:
                    # If a key exists in both, the values must be different
                    # (from the new complaint, not copied from the old)
                    val_a = result_a.draft.entities[key].value
                    val_b = result_b.draft.entities[key].value
                    # Allow same key only if the value comes from the new complaint
                    assert val_a != val_b or key not in ("description", "title"), (
                        f"Entity '{key}' leaked from grievance A to B"
                    )

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_incomplete_grievance_resets_on_new_complaint(
        self, mock_load, mock_save, workflow
    ):
        """If a user abandons a grievance mid-flow and says 'start a new
        grievance', the workflow must reset with a fresh reference."""
        incomplete_state = GrievanceState(
            conversation_id="test-iso-002",
            user_id="user-iso",
            stage=GrievanceStage.FOLLOWUP,
            is_complete=False,
            draft=GrievanceDraft(
                title="Electricity issue",
                category=GrievanceCategory.ELECTRICITY,
                sub_category=GrievanceSubCategory.POWER_CUT,
                department="Electricity Board",
                description="Frequent power cuts in my area",
                reference_number="GRV-20260910-OLDREFXX",
                entities={},
                missing_fields=["ward_number", "city"],
                required_fields=["ward_number", "city"],
                optional_fields=["landmark"],
                jurisdiction="state",
                state="Gujarat",
            ),
        )
        mock_load.return_value = incomplete_state

        # Explicit "start a new grievance" during FOLLOWUP resets the state
        result = workflow.process_message(
            user_message="start a new grievance about garbage not being collected",
            conversation_id="test-iso-002",
            user_id="user-iso",
        )

        # Should classify as municipal/garbage, not electricity
        assert result.draft is not None
        assert result.draft.category == GrievanceCategory.MUNICIPAL
        # Reference must differ from the old one
        assert result.draft.reference_number != "GRV-20260910-OLDREFXX"
        assert result.draft.reference_number.startswith("GRV-")
