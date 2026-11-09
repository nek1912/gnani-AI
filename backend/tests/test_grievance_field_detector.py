
from __future__ import annotations


from app.grievance.field_detector import is_field_satisfied
from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceSubCategory,
)


def _make_draft(
    sub_category: GrievanceSubCategory = GrievanceSubCategory.PMFBY_CLAIM_DELAY,
    description: str = "Test complaint",
) -> GrievanceDraft:
    return GrievanceDraft(
        category=GrievanceCategory.AGRICULTURE,
        sub_category=sub_category,
        title="Test",
        description=description,
        entities={},
        missing_fields=[],
        required_fields=[],
        optional_fields=[],
        jurisdiction="state",
        state="Gujarat",
        department="Agriculture",
    )


class TestReferenceFieldEquivalence:
    """Tests that the _REFERENCE_FIELDS equivalence remains intact."""

    def test_application_id_satisfied_by_reference_number(self):
        """application_id is in _REFERENCE_FIELDS, so reference_number
        in extracted_keys should satisfy it."""
        draft = _make_draft()
        result = is_field_satisfied(
            "application_id",
            {"reference_number"},
            draft,
        )
        assert result is True

    def test_application_id_not_satisfied_by_pincode(self):
        """pincode is NOT a reference field, so it should not satisfy
        application_id."""
        draft = _make_draft()
        result = is_field_satisfied(
            "application_id",
            {"pincode"},
            draft,
        )
        assert result is False

    def test_application_number_satisfied_by_reference_number(self):
        """application_number is also in _REFERENCE_FIELDS."""
        draft = _make_draft()
        result = is_field_satisfied(
            "application_number",
            {"reference_number"},
            draft,
        )
        assert result is True

    def test_reference_number_not_satisfied_by_application_id_alone(self):
        """The equivalence is one-way: reference_number is only satisfied
        by reference_number or account_number, not by application_id.
        application_id is a more specific field that satisfies reference-like
        fields, but not vice versa."""
        draft = _make_draft()
        result = is_field_satisfied(
            "reference_number",
            {"application_id"},
            draft,
        )
        assert result is False

    def test_complaint_number_satisfied_by_reference_number(self):
        """complaint_number is in _REFERENCE_FIELDS."""
        draft = _make_draft()
        result = is_field_satisfied(
            "complaint_number",
            {"reference_number"},
            draft,
        )
        assert result is True

    def test_registration_number_satisfied_by_account_number(self):
        """account_number is also in the reference set."""
        draft = _make_draft()
        result = is_field_satisfied(
            "registration_number",
            {"account_number"},
            draft,
        )
        assert result is True

    def test_exact_field_match_takes_priority(self):
        """If the exact field name is in extracted_keys, it should be
        satisfied regardless of other logic."""
        draft = _make_draft()
        result = is_field_satisfied(
            "application_id",
            {"application_id"},
            draft,
        )
        assert result is True

    def test_description_satisfied_by_nonempty_description(self):
        """description fields are satisfied when draft.description exists."""
        draft = _make_draft(description="My PMFBY claim was not processed")
        result = is_field_satisfied(
            "incident_description",
            set(),
            draft,
        )
        assert result is True

    def test_description_not_satisfied_when_empty(self):
        """description fields should NOT be satisfied when draft.description
        is empty."""
        draft = _make_draft(description="")
        result = is_field_satisfied(
            "incident_description",
            set(),
            draft,
        )
        assert result is False

    def test_person_name_satisfied_by_person_name(self):
        """Complainant name should be satisfied by generic person_name."""
        draft = _make_draft()
        result = is_field_satisfied(
            "complainant_name",
            {"person_name"},
            draft,
        )
        assert result is True

    def test_location_field_satisfied(self):
        """district should be satisfied by district_name."""
        draft = _make_draft()
        result = is_field_satisfied(
            "district",
            {"district_name"},
            draft,
        )
        assert result is True

    def test_unknown_field_not_satisfied(self):
        """An unrecognized field with no matching extracted keys should
        NOT be satisfied."""
        draft = _make_draft()
        result = is_field_satisfied(
            "some_unknown_field_xyz",
            {"unrelated_key"},
            draft,
        )
        assert result is False
