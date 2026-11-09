"""Regression tests for Bug 3: PMFBY structured field values absent from final draft.

Verifies that user-entered field values (farmer_name, application_id, crop,
season, year, insurance_company, bank_name) survive the /answer → persisted
state → /finalize → canonical output pipeline, appear in the canonical
``fields`` dict with exact user-entered values, and are also present in the
english_mirror.
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


def _make_pmfby_draft_with_fields():
    """Build a draft mimicking a completed PMFBY grievance with user-entered field values."""
    entities = {
        "farmer_name": GrievanceEntity(
            name="farmer_name", value="Rahul Kumar", confidence=1.0, source_text="Rahul Kumar",
        ),
        "application_id": GrievanceEntity(
            name="application_id", value="ABC123456", confidence=1.0, source_text="ABC123456",
        ),
        "crop": GrievanceEntity(
            name="crop", value="Cotton", confidence=1.0, source_text="Cotton",
        ),
        "season": GrievanceEntity(
            name="season", value="Kharif", confidence=1.0, source_text="Kharif",
        ),
        "year": GrievanceEntity(
            name="year", value="2026", confidence=1.0, source_text="2026",
        ),
        "insurance_company": GrievanceEntity(
            name="insurance_company", value="National Insurance Co.", confidence=1.0,
            source_text="National Insurance Co.",
        ),
        "bank_name": GrievanceEntity(
            name="bank_name", value="State Bank of India", confidence=1.0,
            source_text="State Bank of India",
        ),
        "state": GrievanceEntity(
            name="state", value="Gujarat", confidence=1.0, source_text="Gujarat",
        ),
    }
    return GrievanceDraft(
        category=GrievanceCategory.AGRICULTURE,
        sub_category=GrievanceSubCategory.PMFBY_CLAIM_DELAY,
        title="PMFBY Crop Insurance Claim Delay",
        description="My PMFBY crop insurance claim is delayed",
        entities=entities,
        missing_fields=[],
        required_fields=["farmer_name", "application_id", "crop", "season", "year", "insurance_company", "bank_name"],
        optional_fields=[],
        jurisdiction="state",
        state="Gujarat",
        department="Agriculture Department / Insurance Company (PMFBY)",
        reference_number="GRV-20260912-TEST0001",
        original_description="My PMFBY crop insurance claim is delayed",
    )


def _make_draft_with_no_structured_fields():
    """Build a draft with only location entities — no structured fields."""
    entities = {
        "ward_number": GrievanceEntity(
            name="ward_number", value="17", confidence=1.0, source_text="ward 17",
        ),
        "city": GrievanceEntity(
            name="city", value="Bharuch", confidence=1.0, source_text="Bharuch",
        ),
        "state": GrievanceEntity(
            name="state", value="Gujarat", confidence=1.0, source_text="Gujarat",
        ),
    }
    return GrievanceDraft(
        category=GrievanceCategory.MUNICIPAL,
        sub_category=GrievanceSubCategory.GARBAGE,
        title="Garbage Collection Delay",
        description="Garbage has not been collected for 9 days near the community hall.",
        entities=entities,
        missing_fields=[],
        required_fields=["ward_number", "locality", "city"],
        optional_fields=["area", "district", "state"],
        jurisdiction="local",
        state="Gujarat",
        department="Municipal Corporation",
        reference_number="GRV-20260912-TEST0002",
        original_description="Garbage has not been collected for 9 days near the community hall.",
    )


_MOCK_SUBMISSION = MagicMock(
    portal_name="PMFBY Portal",
    portal_url="https://pmfby.gov.in/",
    department="Agriculture Department",
    level="state",
    steps=["Login to portal", "File complaint"],
    required_documents=["Aadhaar Card", "Policy Number"],
    estimated_timeline="30 days",
    disclaimer="Prototype reference only.",
)


class TestStructuredFieldsCanonical:
    """Bug 3 regression: to_canonical_dict must include user-entered field values."""

    def test_canonical_contains_fields_with_pmfby_values(self):
        """The canonical dict must include a 'fields' key with exact user-entered values."""
        draft = _make_pmfby_draft_with_fields()
        canonical = draft.to_canonical_dict(
            portal_name="PMFBY Portal",
            portal_url="https://pmfby.gov.in/",
        )
        assert "fields" in canonical, "canonical dict must contain 'fields' key"
        fields = canonical["fields"]
        assert fields is not None, "fields must not be None for a draft with structured entities"
        assert fields["farmer_name"] == "Rahul Kumar"
        assert fields["application_id"] == "ABC123456"
        assert fields["crop"] == "Cotton"
        assert fields["season"] == "Kharif"
        assert fields["year"] == "2026"
        assert fields["insurance_company"] == "National Insurance Co."
        assert fields["bank_name"] == "State Bank of India"

    def test_canonical_fields_excludes_location_entities(self):
        """Location entities must NOT appear in the fields dict."""
        draft = _make_pmfby_draft_with_fields()
        canonical = draft.to_canonical_dict()
        fields = canonical["fields"]
        assert "state" not in fields, "state must not be in fields"
        assert "city" not in fields, "city must not be in fields"
        assert "ward_number" not in fields, "ward_number must not be in fields"

    def test_canonical_fields_excludes_empty_values(self):
        """Entities with empty/whitespace values must be excluded from fields."""
        entities = {
            "farmer_name": GrievanceEntity(
                name="farmer_name", value="Rahul", confidence=1.0, source_text="Rahul",
            ),
            "application_id": GrievanceEntity(
                name="application_id", value="  ", confidence=1.0, source_text="  ",
            ),
        }
        draft = GrievanceDraft(
            category=GrievanceCategory.AGRICULTURE,
            sub_category=GrievanceSubCategory.PMFBY_CLAIM_DELAY,
            title="Test",
            description="Test complaint",
            entities=entities,
            missing_fields=[],
            required_fields=["farmer_name", "application_id"],
            optional_fields=[],
            jurisdiction="state",
            state="Gujarat",
            department="Agriculture",
        )
        canonical = draft.to_canonical_dict()
        fields = canonical["fields"]
        assert "farmer_name" in fields
        assert "application_id" not in fields, "empty value entity must be excluded"

    def test_canonical_location_unchanged(self):
        """Location in canonical dict must remain unchanged."""
        draft = _make_pmfby_draft_with_fields()
        canonical = draft.to_canonical_dict()
        assert "location" in canonical
        assert canonical["location"]["state"] == "Gujarat"

    def test_canonical_description_unchanged(self):
        """Description in canonical dict must remain unchanged."""
        draft = _make_pmfby_draft_with_fields()
        canonical = draft.to_canonical_dict()
        desc = canonical["description"]
        assert desc["original"] == "My PMFBY crop insurance claim is delayed"
        assert desc["normalized"] == "My PMFBY crop insurance claim is delayed"
        assert desc["display"] == "My PMFBY crop insurance claim is delayed"

    def test_no_structured_fields_yields_null_fields(self):
        """A draft with only location entities must have fields=None."""
        draft = _make_draft_with_no_structured_fields()
        canonical = draft.to_canonical_dict()
        assert canonical["fields"] is None, "fields must be None when no structured entities exist"


class TestStructuredFieldsFinalizeEndpoint:
    """Verify /finalize endpoint returns fields in canonical response."""

    def test_finalize_includes_fields_in_response(self):
        """The /finalize endpoint must include fields in the grievance dict."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_pmfby_draft_with_fields()
        state = GrievanceState(
            conversation_id="test-conv-fields",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=_MOCK_SUBMISSION,
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-fields", language="en")
            result = finalize_grievance_draft(req, user_id="test-user")

        grievance = result["grievance"]
        assert "fields" in grievance, "finalize response must contain 'fields'"
        fields = grievance["fields"]
        assert fields is not None
        assert fields["farmer_name"] == "Rahul Kumar"
        assert fields["application_id"] == "ABC123456"
        assert fields["crop"] == "Cotton"
        assert fields["season"] == "Kharif"
        assert fields["year"] == "2026"
        assert fields["insurance_company"] == "National Insurance Co."
        assert fields["bank_name"] == "State Bank of India"

    def test_finalize_english_mirror_includes_fields(self):
        """The english_mirror must carry the same field values as the canonical dict."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_pmfby_draft_with_fields()
        state = GrievanceState(
            conversation_id="test-conv-mirror-fields",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=_MOCK_SUBMISSION,
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-mirror-fields", language="hi")
            result = finalize_grievance_draft(req, user_id="test-user")

        english = result["grievance"].get("english")
        assert english is not None, "english_mirror must be present"
        assert "fields" in english, "english_mirror must contain 'fields'"
        mirror_fields = english["fields"]
        assert mirror_fields is not None
        # Values must be identical — verbatim preservation
        assert mirror_fields["farmer_name"] == "Rahul Kumar"
        assert mirror_fields["application_id"] == "ABC123456"
        assert mirror_fields["crop"] == "Cotton"
        assert mirror_fields["season"] == "Kharif"
        assert mirror_fields["year"] == "2026"
        assert mirror_fields["insurance_company"] == "National Insurance Co."
        assert mirror_fields["bank_name"] == "State Bank of India"

    def test_finalize_no_fields_yields_null(self):
        """A draft with no structured fields must have fields=None in both canonical and mirror."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_draft_with_no_structured_fields()
        state = GrievanceState(
            conversation_id="test-conv-no-fields",
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
            req = GrievanceFinalizeRequest(conversation_id="test-conv-no-fields", language="en")
            result = finalize_grievance_draft(req, user_id="test-user")

        assert result["grievance"]["fields"] is None

    def test_finalize_location_and_description_unchanged(self):
        """Existing location and description output must not be affected."""
        from app.routes.grievance import finalize_grievance_draft, GrievanceFinalizeRequest

        draft = _make_pmfby_draft_with_fields()
        state = GrievanceState(
            conversation_id="test-conv-loc-desc",
            user_id="test-user",
            stage=GrievanceStage.COMPLETE,
            draft=draft,
        )

        with patch("app.routes.grievance.load_grievance_state", return_value=state), \
             patch("app.routes.grievance.save_grievance_state"), \
             patch.object(
                 GrievanceSubmissionGuide, "get_submission_route",
                 return_value=_MOCK_SUBMISSION,
             ):
            req = GrievanceFinalizeRequest(conversation_id="test-conv-loc-desc", language="en")
            result = finalize_grievance_draft(req, user_id="test-user")

        g = result["grievance"]
        assert g["location"]["state"] == "Gujarat"
        assert g["description"]["original"] == "My PMFBY crop insurance claim is delayed"
        assert g["description"]["normalized"] == "My PMFBY crop insurance claim is delayed"
        assert g["description"]["display"] == "My PMFBY crop insurance claim is delayed"
