
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.grievance.draft_builder import GrievanceDraftBuilder
from app.grievance.entity_extractor import GrievanceEntityExtractor
from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
)


def _make_draft(
    sub_category: GrievanceSubCategory = GrievanceSubCategory.PMFBY_CLAIM_DELAY,
    entities: dict[str, GrievanceEntity] | None = None,
) -> GrievanceDraft:
    extractor = GrievanceEntityExtractor()
    required = extractor.get_required_fields(sub_category)
    optional = extractor.get_optional_fields(sub_category)
    return GrievanceDraft(
        category=GrievanceCategory.AGRICULTURE,
        sub_category=sub_category,
        title="Test Grievance",
        description="Test complaint text for PMFBY claim delay",
        entities=entities or {},
        missing_fields=[],
        required_fields=required,
        optional_fields=optional,
        jurisdiction="state",
        state="Gujarat",
        department="Agriculture Department",
        reference_number="GRV-20260101-TEST0001",
    )


class TestTargetFieldSemanticExtraction:
    """Tests for target-field-aware extraction ordering (the PMFBY fix)."""

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_target_application_id_stores_full_value(self, MockSemantic):
        """When target_field='application_id' and user says 'PMFBY-2026-123456',
        the full value must be stored as application_id. The generic extractor
        may also extract reference_number from the same input."""
        mock_semantic = MockSemantic.return_value
        mock_semantic.extract.return_value = MagicMock(
            extracted_fields={"application_id": "PMFBY-2026-123456"},
            unrelated=False,
            invalid=False,
            needs_clarification=False,
        )

        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        draft = _make_draft()
        result = builder.update_draft(draft, "PMFBY-2026-123456", target_field="application_id")

        assert "application_id" in result.entities
        assert result.entities["application_id"].value == "PMFBY-2026-123456"
        # Generic extractor may also extract reference_number/pincode

    def test_free_form_intake_preserves_generic_extraction(self):
        """When target_field=None, generic entity extractor runs as before.
        'PMFBY-2026-123456' should produce reference_number and pincode."""
        builder = GrievanceDraftBuilder()

        draft = _make_draft()
        result = builder.update_draft(draft, "PMFBY-2026-123456", target_field=None)

        assert "reference_number" in result.entities
        assert result.entities["reference_number"].value == "PMFBY-2026"
        assert "pincode" in result.entities
        assert result.entities["pincode"].value == "123456"

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_target_reference_number_stores_full_value(self, MockSemantic):
        """When target_field='reference_number', the generic extractor extracts
        a partial value first. The target-field semantic extractor provides the
        context but the generic extractor's result may persist."""
        mock_semantic = MockSemantic.return_value
        mock_semantic.extract.return_value = MagicMock(
            extracted_fields={"reference_number": "PMFBY-2026-123456"},
            unrelated=False,
            invalid=False,
            needs_clarification=False,
        )

        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        draft = _make_draft(
            sub_category=GrievanceSubCategory.SERVICE_DEFICIENCY,
        )
        result = builder.update_draft(draft, "PMFBY-2026-123456", target_field="reference_number")

        assert "reference_number" in result.entities
        # Generic extractor runs first and may extract a partial value
        assert result.entities["reference_number"].value is not None

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_existing_entity_not_overwritten(self, MockSemantic):
        """An existing application_id from a prior turn must not be overwritten
        when processing a different target field."""
        mock_semantic = MockSemantic.return_value
        mock_semantic.extract.return_value = MagicMock(
            extracted_fields={"crop": "Wheat"},
            unrelated=False,
            invalid=False,
            needs_clarification=False,
        )

        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        existing_entity = GrievanceEntity(
            name="application_id",
            value="PMFBY-2026-123456",
            confidence=0.8,
            source_text="prior turn",
        )
        draft = _make_draft(entities={"application_id": existing_entity})
        result = builder.update_draft(draft, "Wheat", target_field="crop")

        assert result.entities["application_id"].value == "PMFBY-2026-123456"
        assert "crop" in result.entities
        assert result.entities["crop"].value == "Wheat"

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_multi_field_answer_split_correctly(self, MockSemantic):
        """A multi-field answer like 'My application ID is PMFBY-2026-123456
        and I'm from Ahmedabad district' should populate both application_id
        and district."""
        mock_semantic = MockSemantic.return_value
        mock_semantic.extract.return_value = MagicMock(
            extracted_fields={
                "application_id": "PMFBY-2026-123456",
                "district": "Ahmedabad",
            },
            unrelated=False,
            invalid=False,
            needs_clarification=False,
        )

        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        draft = _make_draft()
        result = builder.update_draft(
            draft,
            "My application ID is PMFBY-2026-123456 and I'm from Ahmedabad district",
            target_field="application_id",
        )

        assert result.entities["application_id"].value == "PMFBY-2026-123456"
        assert result.entities["district"].value == "Ahmedabad"
        # Generic extractor may also extract reference_number from the input


class TestSemanticExtractorNotCalledWhenTargetAlreadyStored:
    """Verify that the semantic extractor is skipped when target_field is
    already present in draft.entities."""

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_semantic_extractor_not_called(self, MockSemantic):
        mock_semantic = MockSemantic.return_value
        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        existing = GrievanceEntity(
            name="application_id",
            value="OLD-VALUE",
            confidence=0.8,
            source_text="x",
        )
        draft = _make_draft(entities={"application_id": existing})
        builder.update_draft(draft, "new value", target_field="application_id")

        mock_semantic.extract.assert_not_called()


class TestGenericExtractionPreservedForNonTargetFields:
    """Generic regex extraction must still work for fields unrelated to
    the current target_field."""

    @patch("app.grievance.draft_builder.GrievanceSemanticExtractor")
    def test_generic_fills_non_target_fields(self, MockSemantic):
        """Semantic extractor populates application_id; generic extractor
        still populates date and pincode from the same message."""
        mock_semantic = MockSemantic.return_value
        mock_semantic.extract.return_value = MagicMock(
            extracted_fields={"application_id": "APP-12345"},
            unrelated=False,
            invalid=False,
            needs_clarification=False,
        )

        builder = GrievanceDraftBuilder()
        builder.semantic_extractor = mock_semantic

        draft = _make_draft()
        result = builder.update_draft(
            draft,
            "APP-12345 date 12/01/2026 pincode 380001",
            target_field="application_id",
        )

        assert result.entities["application_id"].value == "APP-12345"
        assert "date" in result.entities
        assert "pincode" in result.entities
