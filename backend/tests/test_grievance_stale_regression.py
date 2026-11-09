"""Regression test for stale grievance classification.

Verifies that when a user clarifies a garbage grievance to road damage,
the classification changes correctly without leaving stale state.
"""

import pytest
from unittest.mock import patch
from app.grievance.models import (
    GrievanceStage,
    GrievanceCategory,
    GrievanceSubCategory,
)
from app.grievance.workflow import GrievanceWorkflow, GrievanceState


@pytest.fixture
def workflow():
    return GrievanceWorkflow()


class TestStaleGrievanceRegression:
    """Garbage → clarify → road damage must not leave stale classification."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_garbage_to_road_damage_classification_changes(
        self, mock_load, mock_save, workflow,
    ):
        """When user clarifies garbage to road damage, classification must change."""
        conv_id = "test-stale-1"
        user_id = "user-1"
        mock_load.return_value = None

        # Turn 1: User reports garbage issue
        r1 = workflow.process_message(
            user_message="There is garbage piling up in my area",
            conversation_id=conv_id,
            user_id=user_id,
        )
        assert r1.stage == GrievanceStage.CLASSIFICATION
        assert r1.draft.category == GrievanceCategory.MUNICIPAL
        assert r1.draft.sub_category == GrievanceSubCategory.GARBAGE

        # Simulate saved state after turn 1
        saved = GrievanceState(conversation_id=conv_id, user_id=user_id)
        saved.stage = GrievanceStage.CLASSIFICATION
        saved.draft = r1.draft
        saved.current_field = None
        mock_load.return_value = saved

        # Turn 2: User clarifies that it's actually road damage
        r2 = workflow.process_message(
            user_message="Actually, it's not garbage. The road is damaged with potholes",
            conversation_id=conv_id,
            user_id=user_id,
        )

        # Classification should change to ROAD_DAMAGE
        assert r2.draft is not None
        assert r2.draft.sub_category == GrievanceSubCategory.ROAD_DAMAGE

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_classification_changes_on_clarification(
        self, mock_load, mock_save, workflow,
    ):
        """When user provides clarification that changes the category,
        the new classification should be reflected in the draft."""
        conv_id = "test-stale-2"
        user_id = "user-1"
        mock_load.return_value = None

        # Turn 1: User reports drainage issue
        r1 = workflow.process_message(
            user_message="The drainage is blocked and water is logging",
            conversation_id=conv_id,
            user_id=user_id,
        )
        assert r1.stage == GrievanceStage.CLASSIFICATION
        assert r1.draft.sub_category == GrievanceSubCategory.DRAINAGE

        # Simulate saved state
        saved = GrievanceState(conversation_id=conv_id, user_id=user_id)
        saved.stage = GrievanceStage.CLASSIFICATION
        saved.draft = r1.draft
        saved.current_field = None
        mock_load.return_value = saved

        # Turn 2: User clarifies it's actually street light issue
        r2 = workflow.process_message(
            user_message="No, the streetlight on my road is not working",
            conversation_id=conv_id,
            user_id=user_id,
        )

        # Classification should change to STREET_LIGHT
        assert r2.draft is not None
        assert r2.draft.sub_category == GrievanceSubCategory.STREET_LIGHT
