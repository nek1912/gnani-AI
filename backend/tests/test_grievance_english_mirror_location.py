"""Regression tests for Bug 2: English full-page draft missing user-entered fields.

Verifies that the english_mirror built by the /finalize endpoint includes
a complete location block with ward_number, locality, area, city, district,
and state — matching the canonical grievance's location.

Also verifies that user-entered values (ward 17, locality Shaktinagar West
Block, city Bharuch) are preserved exactly in the english_mirror.
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
from app.grievance.submission_guide import GrievanceSubmissionGuide


def _make_draft_with_location():
    """Build a draft mimicking a completed municipal grievance with user-entered location fields."""
    entities = {
        "ward_number": GrievanceEntity(
            name="ward_number", value="17", confidence=1.0, source_text="ward 17",
        ),
        "locality": GrievanceEntity(
            name="locality", value="Shaktinagar West Block", confidence=1.0,
            source_text="Shaktinagar West Block",
        ),
        "city": GrievanceEntity(
            name="city", value="Bharuch", confidence=1.0, source_text="Bharuch",
        ),
        "district": GrievanceEntity(
            name="district", value="Bharuch", confidence=1.0, source_text="Bharuch",
        ),
        "description": GrievanceEntity(
            name="description",
            value="Garbage has not been collected for exactly 9 days near the community hall.",
            confidence=1.0,
            source_text="Garbage has not been collected for exactly 9 days near the community hall.",
        ),
    }
    return GrievanceDraft(
        category=GrievanceCategory.MUNICIPAL,
        sub_category=GrievanceSubCategory.GARBAGE,
        title="Garbage Collection Delay",
        description="Garbage has not been collected for exactly 9 days near the community hall.",
        entities=entities,
        missing_fields=[],
        required_fields=["ward_number", "locality", "city"],
        optional_fields=["area", "district", "state"],
        jurisdiction="local",
        state="Gujarat",
        department="Municipal Corporation",
        reference_number="GRV-20260911-TEST0001",
        original_description="Garbage has not been collected for exactly 9 days near the community hall.",
    )


class TestEnglishMirrorLocation:
    """Bug 2 regression: english_mirror must include complete location data."""

    def test_finalize_english_mirror_has_location(self):
        """The english_mirror in /finalize response must include a location block."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_draft_with_location()
        state = GrievanceState(
            conversation_id="test-conv-location",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=MagicMock(
                     portal_name="Bharuch Municipal Corporation",
                     portal_url="https://bharuch.example.gov.in/",
                     department="Municipal Corporation",
                     level="local",
                     steps=["Visit portal", "Fill form"],
                     required_documents=["Aadhaar Card"],
                     estimated_timeline="7 days",
                     disclaimer="Prototype reference only.",
                 ),
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-location", language="gu")
            result = finalize_grievance_draft(req, user_id="test-user")

        english = result["grievance"].get("english")
        assert english is not None, "english_mirror must be present"
        assert "location" in english, "english_mirror must include location block"

        loc = english["location"]
        assert loc["ward_number"] == "17", f"ward_number must be '17', got {loc['ward_number']!r}"
        assert loc["locality"] == "Shaktinagar West Block", (
            f"locality must be 'Shaktinagar West Block', got {loc['locality']!r}"
        )
        assert loc["city"] == "Bharuch", f"city must be 'Bharuch', got {loc['city']!r}"
        assert loc["district"] == "Bharuch", f"district must be 'Bharuch', got {loc['district']!r}"
        assert loc["state"] == "Gujarat", f"state must be 'Gujarat', got {loc['state']!r}"

    def test_finalize_english_mirror_preserves_user_description(self):
        """User-entered description must be preserved exactly in english_mirror."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_draft_with_location()
        state = GrievanceState(
            conversation_id="test-conv-desc",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=MagicMock(
                     portal_name="Portal", portal_url=None,
                     department="Dept", level="local",
                     steps=[], required_documents=[],
                     estimated_timeline=None, disclaimer=None,
                 ),
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-desc", language="gu")
            result = finalize_grievance_draft(req, user_id="test-user")

        english = result["grievance"]["english"]
        expected_desc = "Garbage has not been collected for exactly 9 days near the community hall."
        assert english["description"] == expected_desc, (
            "english_mirror description must match user input exactly"
        )

    def test_finalize_english_mirror_has_submission(self):
        """english_mirror must include submission route data."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_draft_with_location()
        state = GrievanceState(
            conversation_id="test-conv-sub",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=MagicMock(
                     portal_name="Bharuch Municipal Corporation",
                     portal_url="https://bharuch.example.gov.in/",
                     department="Municipal Corporation",
                     level="local",
                     steps=["Visit portal", "Fill form"],
                     required_documents=["Aadhaar Card"],
                     estimated_timeline="7 days",
                     disclaimer="Prototype reference only.",
                 ),
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-sub", language="gu")
            result = finalize_grievance_draft(req, user_id="test-user")

        english = result["grievance"]["english"]
        assert english["submission"] is not None
        assert english["submission"]["portal_name"] == "Bharuch Municipal Corporation"
        assert english["submission"]["portal_url"] == "https://bharuch.example.gov.in/"
        assert english["submission"]["steps"] == ["Visit portal", "Fill form"]
        assert english["submission"]["required_documents"] == ["Aadhaar Card"]
