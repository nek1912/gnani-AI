"""Tests for area_name boundary fix and city→state resolution.

Covers:
  1. Entity extractor: area_name doesn't swallow city portion
  2. Entity extractor: city still extracts correctly
  3. Entity extractor: area with colon format still works
  4. _resolve_location_context: state resolves from city when draft.state is None
  5. _resolve_location_context: draft.state takes precedence over city mapping
  6. Locality+city extraction still works ("locality is Buder Park city Bharuch")
  7. Ward extraction still works
  8. Original description preservation still works
  9. URL placeholder restoration still works
  10. End-to-end: full Gujarati flow with city but no state
  11. End-to-end: full flow where state IS provided
  12. No GRVURL leak
  13. No malformed area_name in submission guide
  14. state=Bharuch must never appear (city is not state)
  15. area_name doesn't contain "city" keyword
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.grievance.entity_extractor import GrievanceEntityExtractor
from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
)
from app.grievance.submission_guide import GrievanceSubmissionGuide, _CITY_TO_STATE
from app.grievance.semantic_extractor import GrievanceSemanticExtractor


def _make_extractor() -> GrievanceSemanticExtractor:
    return GrievanceSemanticExtractor(use_gemini=False)


def _make_draft(
    entities: dict[str, GrievanceEntity] | None = None,
    description: str = "Test complaint about garbage",
    original_description: str | None = None,
    state_val: str | None = None,
) -> GrievanceDraft:
    return GrievanceDraft(
        category=GrievanceCategory.MUNICIPAL,
        sub_category=GrievanceSubCategory.GARBAGE,
        title="Test",
        description=description,
        entities=entities or {},
        missing_fields=[],
        required_fields=["ward_number", "locality", "issue_description"],
        optional_fields=["municipality", "zone", "landmark", "photos", "city"],
        jurisdiction="local",
        state=state_val,
        department="Municipal Corporation / Urban Local Body",
        original_description=original_description,
    )


# ===================================================================
# ENTITY EXTRACTOR TESTS (1–5)
# ===================================================================


class TestAreaNameBoundary:
    """Tests 1–5: area_name extraction stops at location boundaries."""

    def test_1_area_does_not_swallow_city(self):
        """Test 1: 'area name Modi Garden and city Bharuch' → no area_name with city."""
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value(
            "area", "area name Modi Garden and city Bharuch"
        )
        # Should either be None or NOT contain "city"
        if v is not None:
            assert "city" not in v.lower().split()

    def test_2_city_still_extracts(self):
        """Test 2: city extracts 'Bharuch' from same input."""
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value(
            "city", "area name Modi Garden and city Bharuch"
        )
        assert v == "Bharuch"

    def test_3_area_with_colon_still_works(self):
        """Test 3: 'area: Modi Garden' → area = 'Modi Garden'."""
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value("area", "area: Modi Garden")
        assert v == "Modi Garden"

    def test_4_area_with_ward_boundary(self):
        """Test 4: 'area Green Park ward 5' → area stops at ward."""
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value("area", "area Green Park ward 5")
        if v is not None:
            assert "ward" not in v.lower().split()

    def test_5_full_extract_no_malformed_area(self):
        """Test 5: full extract doesn't create area_name with city text."""
        ext = GrievanceEntityExtractor()
        result = ext.extract(
            "area name Modi Garden and city Bharuch",
            GrievanceSubCategory.GARBAGE,
        )
        area_entity = result.entities.get("area_name")
        if area_entity is not None:
            assert "city" not in area_entity.value.lower().split()


# ===================================================================
# STATE RESOLUTION TESTS (6–9)
# ===================================================================


class TestStateResolution:
    """Tests 6–9: city→state resolution in _resolve_location_context."""

    def test_6_state_resolves_from_city(self):
        """Test 6: city=Bharuch, state=None → state='Gujarat'."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="test",
                ),
            },
            state_val=None,
        )
        city, state = guide._resolve_location_context(draft)
        assert city == "Bharuch"
        assert state == "Gujarat"

    def test_7_draft_state_takes_precedence(self):
        """Test 7: draft.state='Maharashtra' stays even if city maps to Gujarat."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="test",
                ),
            },
            state_val="Maharashtra",
        )
        _city, state = guide._resolve_location_context(draft)
        assert state == "Maharashtra"

    def test_8_unknown_city_returns_none(self):
        """Test 8: unknown city with no draft.state → state=None."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Xyznonexistent",
                    confidence=0.9, source_text="test",
                ),
            },
            state_val=None,
        )
        city, state = guide._resolve_location_context(draft)
        assert city == "Xyznonexistent"
        assert state is None

    def test_9_city_to_state_mapping_covers_bharuch(self):
        """Test 9: Bharuch is in the _CITY_TO_STATE mapping (lowercase key)."""
        assert _CITY_TO_STATE.get("bharuch") == "Gujarat"
        assert _CITY_TO_STATE.get("vadodara") == "Gujarat"


# ===================================================================
# LOCALITY/CITY PRESERVATION TESTS (10–11)
# ===================================================================


class TestLocalityCityPreservation:
    """Tests 10–11: previous locality fix still works."""

    def test_10_locality_is_buder_park_city_bharuch(self):
        """Test 10: 'locality is Buder Park city Bharuch' still works."""
        ext = _make_extractor()
        result = ext._extract_heuristic(
            current_field="locality",
            user_message="locality is Buder Park city Bharuch",
        )
        assert result.extracted_fields.get("locality") == "Buder Park"
        assert result.extracted_fields.get("city") == "Bharuch"

    def test_11_ward_extraction_unchanged(self):
        """Test 11: ward number extraction still works."""
        ext = _make_extractor()
        result = ext._extract_heuristic(
            current_field="ward_number",
            user_message="ward 5 near the old bus stand",
        )
        assert result.extracted_fields.get("ward_number") == "5"


# ===================================================================
# END-TO-END TESTS (12–15)
# ===================================================================


class TestEndToEnd:
    """Tests 12–15: full grievance flow with city but no state."""

    def test_12_gujarati_flow_city_no_state(self):
        """Test 12: city=Bharuch, state=None → state resolves to Gujarat."""
        guide = GrievanceSubmissionGuide()
        gujarati_desc = "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        draft = _make_draft(
            description="Garbage in my area",
            original_description=gujarati_desc,
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
                "ward_number": GrievanceEntity(
                    name="ward_number", value="Ward 5",
                    confidence=0.8, source_text="Ward 5",
                ),
                "locality_name": GrievanceEntity(
                    name="locality_name", value="Modi Garden",
                    confidence=0.8, source_text="Modi Garden",
                ),
            },
            state_val=None,
        )
        city, state = guide._resolve_location_context(draft)
        assert city == "Bharuch"
        assert state == "Gujarat"

    def test_13_state_provided_not_overridden(self):
        """Test 13: explicit state='Gujarat' is preserved."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val="Gujarat",
        )
        _city, state = guide._resolve_location_context(draft)
        assert state == "Gujarat"

    def test_14_state_never_bharuch(self):
        """Test 14: state must never be 'Bharuch' (city is not state)."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val=None,
        )
        _, state = guide._resolve_location_context(draft)
        assert state != "Bharuch"

    def test_15_no_malformed_area_in_draft_display(self):
        """Test 15: format_draft_for_display produces clean English output."""
        from app.grievance.draft_builder import GrievanceDraftBuilder
        builder = GrievanceDraftBuilder()
        gujarati_desc = "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        draft = _make_draft(
            description="Garbage in my area",
            original_description=gujarati_desc,
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
                "ward_number": GrievanceEntity(
                    name="ward_number", value="Ward 5",
                    confidence=0.8, source_text="Ward 5",
                ),
                "locality_name": GrievanceEntity(
                    name="locality_name", value="Modi Garden",
                    confidence=0.8, source_text="Modi Garden",
                ),
            },
            state_val="Gujarat",
        )
        display = builder.format_draft_for_display(draft)
        # English display shows English labels
        assert "Category" in display
        assert "Municipal" in display
        # State shown correctly
        assert "Gujarat" in display
        # Original description preserved in canonical dict
        d = draft.to_canonical_dict()
        assert d["description"]["original"] == gujarati_desc

    def test_15b_no_grvurl_in_output(self):
        """Test 15b: translation boundary preserves original description."""
        from app.routes.chat import _translate_grievance_response_back
        from app.grievance.draft_builder import GrievanceDraftBuilder

        settings = MagicMock()
        builder = GrievanceDraftBuilder()
        gujarati_desc = "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        draft = _make_draft(
            description="Garbage in my area",
            original_description=gujarati_desc,
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val="Gujarat",
        )
        guide = GrievanceSubmissionGuide()
        route = guide.get_submission_route(draft)
        response = (
            "✅ **Your grievance draft is complete!**\n\n"
            + builder.format_draft_for_display(draft)
            + "\n\n"
            + guide.format_route_for_display(route)
        )
        with patch("app.routes.chat._translate_from_english", return_value=response):
            result = _translate_grievance_response_back(response, "gu", settings)
        assert "GRVURL" not in result
        # Original description is preserved through translation
        d = draft.to_canonical_dict()
        assert d["description"]["original"] == gujarati_desc


# ===================================================================
# CITY→STATE MAPPING COMPLETENESS (16)
# ===================================================================


class TestCityStateMapping:
    """Test 16: mapping covers cities seen in production."""

    def test_16_gujarat_cities_mapped(self):
        """Test 16: key Gujarat cities are in the mapping."""
        gujarat_cities = ["bharuch", "vadodara", "ahmedabad", "surat", "rajkot"]
        for city in gujarat_cities:
            assert city in _CITY_TO_STATE, f"{city} missing from _CITY_TO_STATE"
            assert _CITY_TO_STATE[city] == "Gujarat"


# ===================================================================
# FOCUSED TESTS: STATE PERSISTENCE + CANONICAL OUTPUT (17–22)
# ===================================================================


class TestStatePersistence:
    """Tests 17–18: inferred state is persisted to draft.state."""

    def test_17_none_state_persists_resolved_state(self):
        """Test 17: draft.state=None + city=Bharuch → draft.state becomes Gujarat."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val=None,
        )
        assert draft.state is None
        guide._resolve_location_context(draft)
        assert draft.state == "Gujarat"

    def test_18_explicit_state_not_overwritten(self):
        """Test 18: explicit state='Maharashtra' is preserved, not overwritten by Bharuch→Gujarat."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val="Maharashtra",
        )
        guide._resolve_location_context(draft)
        assert draft.state == "Maharashtra"


class TestDisplayShowsState:
    """Test 19: format_draft_for_display shows State: Gujarat."""

    def test_19_display_contains_state_gujarat(self):
        """Test 19: jurisdiction line shows Gujarat when draft.state is set."""
        from app.grievance.draft_builder import GrievanceDraftBuilder
        builder = GrievanceDraftBuilder()
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
                "ward_number": GrievanceEntity(
                    name="ward_number", value="Ward 5",
                    confidence=0.8, source_text="Ward 5",
                ),
                "locality_name": GrievanceEntity(
                    name="locality_name", value="Modi Garden",
                    confidence=0.8, source_text="Modi Garden",
                ),
            },
            state_val=None,
        )
        guide._resolve_location_context(draft)
        display = builder.format_draft_for_display(draft)
        assert "Gujarat" in display
        assert "Bharuch" not in display.split("Jurisdiction")[1].split("\n")[0]


class TestCanonicalToDict:
    """Tests 20–21: to_dict() canonical structured output."""

    def test_20_to_dict_has_canonical_location_fields(self):
        """Test 20: to_dict() exposes city, locality, area, ward_number, state."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
                "ward_number": GrievanceEntity(
                    name="ward_number", value="Ward 5",
                    confidence=0.8, source_text="Ward 5",
                ),
                "locality_name": GrievanceEntity(
                    name="locality_name", value="Modi Garden",
                    confidence=0.8, source_text="Modi Garden",
                ),
                "area_name": GrievanceEntity(
                    name="area_name", value="Modi Garden",
                    confidence=0.8, source_text="Modi Garden",
                ),
            },
            state_val=None,
        )
        guide._resolve_location_context(draft)
        d = draft.to_dict()
        assert d.get("city") == "Bharuch"
        assert d.get("state") == "Gujarat"
        assert d.get("locality") == "Modi Garden"
        assert d.get("area") == "Modi Garden"
        assert d.get("ward_number") == "5"

    def test_21_to_dict_no_duplicate_aliases(self):
        """Test 21: to_dict() does not expose city_name as a separate top-level key."""
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val="Gujarat",
        )
        d = draft.to_dict()
        assert "city_name" not in d
        assert "city" in d


class TestOriginalDescriptionPreserved:
    """Test 22: original Gujarati description unchanged."""

    def test_22_original_description_unchanged_after_state_resolution(self):
        """Test 22: resolving state does not alter original_description."""
        guide = GrievanceSubmissionGuide()
        gujarati_desc = "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        draft = _make_draft(
            description="Garbage in my area",
            original_description=gujarati_desc,
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val=None,
        )
        guide._resolve_location_context(draft)
        assert draft.original_description == gujarati_desc


class TestSubmissionPortalUrl:
    """Test 23: Bharuch municipal portal URL unchanged."""

    def test_23_bharuch_portal_url(self):
        """Test 23: Bharuch municipal submission route is generated."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            state_val=None,
        )
        guide._resolve_location_context(draft)
        route = guide.get_submission_route(draft)
        # Portal URL may or may not be verified depending on network
        assert route.portal_url is not None
        assert "Bharuch" in route.portal_name
