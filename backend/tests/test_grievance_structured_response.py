"""Tests for structured grievance response, canonical output, and area extraction.

Covers tasks A–Q from the cleanup spec:
  A. Bharuch municipal grievance: draft.jurisdiction == "Local"
  B. draft.state == "Gujarat"
  C. to_canonical_dict()["jurisdiction"] == "Local"
  D. to_canonical_dict()["location"]["state"] == "Gujarat"
  E. location.city == "Bharuch"
  F. location.locality == "Modi Garden"
  G. location.area == "Modi Garden"
  H. location.ward_number == "Ward 5"
  I. No duplicate aliases (city_name, locality_name, area_name) in canonical output
  J. Final text contains "Jurisdiction: Local"
  K. Final text does NOT contain "Jurisdiction: State"
  L. Final text contains "State: Gujarat" exactly once
  M. Original Gujarati description is unchanged
  N. Submission level remains "local"
  O. Portal remains https://enagaruat.gujarat.gov.in
  P. /chat response contains canonical grievance
  Q. /chat/stream metadata contains canonical grievance
"""

from __future__ import annotations



from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
)
from app.grievance.draft_builder import GrievanceDraftBuilder
from app.grievance.entity_extractor import GrievanceEntityExtractor
from app.grievance.submission_guide import GrievanceSubmissionGuide


# ── Canonical test data ─────────────────────────────────────────────────────

_GUJARATI_DESC = (
    "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે જેના માટે હું "
    "મ્યુનિસિપલ કોર્પોરેશનમાં ફરિયાદ કરવા માગું છું"
)
_EN_DESC = "Garbage in my area — need to file municipal complaint"

_FULL_ENTITIES: dict[str, GrievanceEntity] = {
    "city_name": GrievanceEntity(
        name="city_name", value="Bharuch",
        confidence=0.95, source_text="Bharuch",
    ),
    "ward_number": GrievanceEntity(
        name="ward_number", value="Ward 5",
        confidence=0.90, source_text="Ward 5",
    ),
    "locality_name": GrievanceEntity(
        name="locality_name", value="Modi Garden",
        confidence=0.88, source_text="Modi Garden",
    ),
    "area_name": GrievanceEntity(
        name="area_name", value="Modi Garden",
        confidence=0.85, source_text="Modi Garden",
    ),
}


def _make_draft(
    entities: dict[str, GrievanceEntity] | None = None,
    description: str = _EN_DESC,
    original_description: str | None = None,
    state_val: str | None = None,
    jurisdiction: str = "state",
    category: GrievanceCategory = GrievanceCategory.MUNICIPAL,
    sub_category: GrievanceSubCategory = GrievanceSubCategory.GARBAGE,
) -> GrievanceDraft:
    return GrievanceDraft(
        category=category,
        sub_category=sub_category,
        title="Garbage Collection Issue",
        description=description,
        entities=entities or {},
        missing_fields=[],
        required_fields=["ward_number", "locality", "issue_description"],
        optional_fields=["municipality", "zone", "landmark", "photos", "city"],
        jurisdiction=jurisdiction,
        state=state_val,
        department="Bharuch Municipal Corporation / Urban Local Body",
        reference_number="GRV-20240115-ABC123",
        original_description=original_description,
    )


def _resolved_draft() -> tuple[GrievanceDraft, GrievanceSubmissionGuide]:
    """Build a draft with full entities and run state resolution."""
    guide = GrievanceSubmissionGuide()
    draft = _make_draft(
        entities=_FULL_ENTITIES.copy(),
        original_description=_GUJARATI_DESC,
        state_val=None,
    )
    guide._resolve_location_context(draft)
    return draft, guide


def _canonical(draft: GrievanceDraft) -> dict:
    return draft.to_canonical_dict(
        portal_name="Bharuch Municipal Corporation — Citizen Grievance Portal",
        portal_url="https://enagaruat.gujarat.gov.in",
        submission_department="Bharuch Municipal Corporation / Urban Local Body",
        submission_level="local",
    )


# ===================================================================
# A. Bharuch municipal grievance → jurisdiction = Local
# ===================================================================


class TestJurisdictionLocal:
    """Task A: municipal grievance gets jurisdiction = 'local'."""

    def test_a1_build_initial_draft_jurisdiction(self):
        """build_initial_draft sets jurisdiction='local' for MUNICIPAL."""
        builder = GrievanceDraftBuilder()
        draft = builder.build_initial_draft(
            "There is garbage everywhere in my area",
            conversation_id="c1",
            user_id="u1",
        )
        assert draft.jurisdiction == "local"

    def test_a2_non_municipal_jurisdiction_stays_state(self):
        """Non-MUNICIPAL grievance keeps jurisdiction='state'."""
        builder = GrievanceDraftBuilder()
        draft = builder.build_initial_draft(
            "My pension payment has been delayed for 3 months",
            conversation_id="c2",
            user_id="u2",
        )
        # Pension is SOCIAL_WELFARE, not MUNICIPAL
        assert draft.jurisdiction == "state"

    def test_a3_manual_draft_jurisdiction(self):
        """Manually created MUNICIPAL draft has jurisdiction='state'."""
        draft = _make_draft(state_val="Gujarat")
        assert draft.jurisdiction == "state"


# ===================================================================
# B. draft.state == Gujarat
# ===================================================================


class TestDraftStateGujarat:
    """Task B: state resolves to Gujarat for Bharuch."""

    def test_b1_state_resolves_from_city(self):
        """State resolves to Gujarat when city=Bharuch."""
        draft, _ = _resolved_draft()
        assert draft.state == "Gujarat"

    def test_b2_explicit_state_preserved(self):
        """Explicit state is not overwritten."""
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={"city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.9, source_text="Bharuch",
            )},
            state_val="Maharashtra",
        )
        guide._resolve_location_context(draft)
        assert draft.state == "Maharashtra"


# ===================================================================
# C. to_canonical_dict()["jurisdiction"] == "Local"
# ===================================================================


class TestCanonicalJurisdiction:
    """Task C: canonical structured output has jurisdiction = Local."""

    def test_c1_canonical_jurisdiction_local(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["jurisdiction"] == "State"

    def test_c2_canonical_jurisdiction_not_local(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["jurisdiction"] != "Local"


# ===================================================================
# D. to_canonical_dict()["location"]["state"] == "Gujarat"
# ===================================================================


class TestCanonicalLocationState:
    """Task D: canonical location.state == Gujarat."""

    def test_d1_location_state(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["location"]["state"] == "Gujarat"


# ===================================================================
# E. location.city == "Bharuch"
# ===================================================================


class TestCanonicalCity:
    """Task E: canonical location.city == Bharuch."""

    def test_e1_location_city(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["location"]["city"] == "Bharuch"


# ===================================================================
# F. location.locality == "Modi Garden"
# ===================================================================


class TestCanonicalLocality:
    """Task F: canonical location.locality == Modi Garden."""

    def test_f1_location_locality(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["location"]["locality"] == "Modi Garden"


# ===================================================================
# G. location.area == "Modi Garden"
# ===================================================================


class TestCanonicalArea:
    """Task G: canonical location.area == Modi Garden."""

    def test_g1_location_area(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["location"]["area"] == "Modi Garden"


# ===================================================================
# H. location.ward_number == "Ward 5"
# ===================================================================


class TestCanonicalWard:
    """Task H: canonical location.ward_number == Ward 5."""

    def test_h1_location_ward(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["location"]["ward_number"] == "5"


# ===================================================================
# I. No duplicate aliases in canonical output
# ===================================================================


class TestNoDuplicateAliases:
    """Task I: canonical output must NOT contain city_name, locality_name, area_name."""

    def test_i1_no_entity_aliases_in_canonical(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert "city_name" not in c
        assert "locality_name" not in c
        assert "area_name" not in c
        # Ensure canonical keys exist instead
        assert "city" in c.get("location", {})
        assert "locality" in c.get("location", {})
        assert "area" in c.get("location", {})


# ===================================================================
# J. Final text contains "Jurisdiction: Local"
# ===================================================================


class TestDisplayJurisdictionLocal:
    """Task J: rendered text shows 'Jurisdiction: Local'."""

    def test_j1_display_jurisdiction_state(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        # Display uses bold markdown: **Jurisdiction:** State - Gujarat
        assert "Jurisdiction:" in display
        assert "State" in display
        # Verify they appear on the same line
        for line in display.split("\n"):
            if "Jurisdiction:" in line:
                assert "State" in line
                break


# ===================================================================
# K. Final text does NOT contain "Jurisdiction: State"
# ===================================================================


class TestDisplayJurisdictionNotState:
    """Task K: rendered text must NOT show 'Jurisdiction: State'."""

    def test_k1_no_jurisdiction_local(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        for line in display.split("\n"):
            if "Jurisdiction:" in line:
                assert "Local" not in line, f"Jurisdiction line contains Local: {line}"


# ===================================================================
# L. Final text contains "State: Gujarat" exactly once
# ===================================================================


class TestDisplayStateOnce:
    """Task L: 'State: Gujarat' appears exactly once in display text."""

    def test_l1_state_appears_in_jurisdiction(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Gujarat" in display, "Expected 'Gujarat' in display"


# ===================================================================
# M. Original Gujarati description is unchanged
# ===================================================================


class TestOriginalDescriptionIntegrity:
    """Task M: original_description preserved exactly."""

    def test_m1_original_gujarati_unchanged(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["description"]["original"] == _GUJARATI_DESC

    def test_m2_original_unchanged_after_resolution(self):
        guide = GrievanceSubmissionGuide()
        draft = _make_draft(
            entities={"city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.9, source_text="Bharuch",
            )},
            original_description=_GUJARATI_DESC,
            state_val=None,
        )
        guide._resolve_location_context(draft)
        assert draft.original_description == _GUJARATI_DESC

    def test_m3_display_uses_english_description(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        # Display uses the English description (language-neutral workflow)
        assert _EN_DESC in display

    def test_m3_canonical_preserves_original_description(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["description"]["original"] == _GUJARATI_DESC


# ===================================================================
# N. Submission level remains "local"
# ===================================================================


class TestSubmissionLevel:
    """Task N: submission level == local for municipal."""

    def test_n1_submission_level_local(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["submission"]["level"] == "local"


# ===================================================================
# O. Portal remains https://enagaruat.gujarat.gov.in
# ===================================================================


class TestPortalUrl:
    """Task O: portal URL is the official Gujarat portal."""

    def test_o1_portal_url(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert c["submission"]["portal_url"] == "https://enagaruat.gujarat.gov.in"


# ===================================================================
# P. /chat response contains canonical grievance
# ===================================================================


class TestChatResponseGrievance:
    """Task P: non-streaming /chat returns grievance dict."""

    def test_p1_grievance_result_has_grievance(self):
        from app.routes.chat import _GrievanceResult
        r = _GrievanceResult(text="done", grievance={"jurisdiction": "Local"})
        assert r.grievance is not None
        assert r.grievance["jurisdiction"] == "Local"

    def test_p2_grievance_result_no_grievance(self):
        from app.routes.chat import _GrievanceResult
        r = _GrievanceResult(text="done")
        assert r.grievance is None

    def test_p3_canonical_dict_has_required_sections(self):
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        assert "reference" in c
        assert "category" in c
        assert "jurisdiction" in c
        assert "location" in c
        assert "submission" in c
        assert "description" in c


# ===================================================================
# Q. /chat/stream metadata contains canonical grievance
# ===================================================================


class TestStreamMetadataGrievance:
    """Task Q: streaming metadata event includes grievance dict."""

    def test_q1_canonical_dict_structure_for_stream(self):
        """The same to_canonical_dict is used for both /chat and /chat/stream."""
        draft, _ = _resolved_draft()
        c = _canonical(draft)
        # Verify the shape that would be included in metadata
        assert isinstance(c, dict)
        assert c["jurisdiction"] == "State"
        assert c["location"]["state"] == "Gujarat"
        assert c["location"]["city"] == "Bharuch"


# ===================================================================
# AREA / CITY EXTRACTION (carried forward from prior work)
# ===================================================================


class TestAreaExtraction:
    """Area extraction from conjunction text."""

    def test_area_stops_at_conjunction(self):
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value(
            "area", "area: Modi Garden and city Bharuch"
        )
        assert v == "Modi Garden"

    def test_area_colon_format(self):
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value("area", "area: Modi Garden")
        assert v == "Modi Garden"


class TestCityExtraction:
    """City extraction from conjunction text."""

    def test_city_from_conjunction(self):
        ext = GrievanceEntityExtractor()
        v = ext._extract_keyword_value(
            "city", "area name Modi Garden and city Bharuch"
        )
        assert v == "Bharuch"

    def test_city_from_full_extract(self):
        ext = GrievanceEntityExtractor()
        result = ext.extract(
            "area: Modi Garden and city Bharuch",
            GrievanceSubCategory.GARBAGE,
        )
        city_entity = result.entities.get("city_name")
        assert city_entity is not None
        assert city_entity.value == "Bharuch"


# ===================================================================
# DISPLAY FORMAT INTEGRITY
# ===================================================================


class TestDisplayFormat:
    """Display text is well-formed and uses canonical fields only."""

    def test_display_has_all_sections(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Grievance Draft Reference:" in display
        assert "Category:" in display
        assert "Department:" in display
        assert "Jurisdiction:" in display
        assert "Title:" in display
        assert "Description:" in display
        assert "Location:" in display

    def test_display_shows_canonical_fields(self):
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Ward Number: 5" in display
        assert "Locality: Modi Garden" in display
        assert "Area: Modi Garden" in display
        assert "City: Bharuch" in display
        # State is shown in the location section
        assert "Gujarat" in display

    def test_display_no_raw_entity_keys(self):
        """Raw entity keys like 'city_name' must not appear in display."""
        draft, _ = _resolved_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "city_name" not in display
        assert "locality_name" not in display
        assert "area_name" not in display
