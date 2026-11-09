
from __future__ import annotations

import pytest

from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
    _normalize_ward,
    _normalize_city,
    _normalize_locality,
    _normalize_area,
)
from app.grievance.draft_builder import GrievanceDraftBuilder
from app.grievance.entity_extractor import GrievanceEntityExtractor
from app.grievance.semantic_extractor import (
    GrievanceSemanticExtractor,
    _LOCALITY_CUE_RE,
    _CITY_CUE_RE,
    _CITY_SUFFIX_RE,
    _split_clauses,
)


def _make_municipal_draft(
    entities: dict[str, GrievanceEntity] | None = None,
    **extra,
) -> GrievanceDraft:
    extractor = GrievanceEntityExtractor()
    sub = GrievanceSubCategory.GARBAGE
    required = extractor.get_required_fields(sub)
    optional = extractor.get_optional_fields(sub)
    defaults = {
        "category": GrievanceCategory.MUNICIPAL,
        "sub_category": sub,
        "title": "Test Municipal Grievance",
        "description": "Garbage not collected in my area",
        "entities": entities or {},
        "missing_fields": [],
        "required_fields": required,
        "optional_fields": optional,
        "jurisdiction": "local",
        "state": "Gujarat",
        "department": "Municipal Corporation",
        "reference_number": "GRV-20260908-TEST0001",
    }
    defaults.update(extra)
    return GrievanceDraft(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# TASK 1 — Ward value normalisation
# ═══════════════════════════════════════════════════════════════════════

class TestWardNormalization:
    """Canonical ward_number must be digits only."""

    def test_ward_number_5(self):
        assert _normalize_ward("Ward Number 5") == "5"

    def test_ward_12(self):
        assert _normalize_ward("Ward 12") == "12"

    def test_ward_no_3(self):
        assert _normalize_ward("Ward No. 3") == "3"

    def test_ward_digits_only(self):
        assert _normalize_ward("5") == "5"

    def test_gujarati_ward(self):
        assert _normalize_ward("વોર્ડ નંબર 5") == "5"

    def test_hindi_ward(self):
        assert _normalize_ward("वार्ड नंबर 5") == "5"

    def test_marathi_ward(self):
        assert _normalize_ward("वॉर्ड क्रमांक 5") == "5"

    def test_ward_empty(self):
        assert _normalize_ward("") == ""

    def test_ward_none_passthrough(self):
        """_normalize_ward receives str, not None; but empty string is safe."""
        assert _normalize_ward("") == ""


# ═══════════════════════════════════════════════════════════════════════
# TASK 2 — Location value normalisation
# ═══════════════════════════════════════════════════════════════════════

class TestLocationNormalization:
    """Canonical location values must not contain field labels."""

    def test_city_strips_suffix(self):
        assert _normalize_city("Bharuch City") == "Bharuch"

    def test_city_strips_town_suffix(self):
        assert _normalize_city("Vadodara Town") == "Vadodara"

    def test_city_clean(self):
        assert _normalize_city("Bharuch") == "Bharuch"

    def test_city_strips_prefix(self):
        assert _normalize_city("City is Bharuch") == "Bharuch"

    def test_locality_strips_prefix(self):
        assert _normalize_locality("Locality is: Near J.B. Modi Garden") == "Near J.B. Modi Garden"

    def test_locality_clean(self):
        assert _normalize_locality("Near J.B. Modi Garden") == "Near J.B. Modi Garden"

    def test_area_strips_prefix(self):
        assert _normalize_area("Area name is Modi Garden") == "Modi Garden"

    def test_area_clean(self):
        assert _normalize_area("Modi Garden") == "Modi Garden"


# ═══════════════════════════════════════════════════════════════════════
# TASK 4 — Canonical location contract in to_canonical_dict
# ═══════════════════════════════════════════════════════════════════════

class TestCanonicalLocationContract:
    """to_canonical_dict must return clean semantic values."""

    def test_ward_canonical_digits(self):
        draft = _make_municipal_draft(entities={
            "ward_number": GrievanceEntity(
                name="ward_number", value="Ward Number 5",
                confidence=0.9, source_text="Ward Number 5"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["ward_number"] == "5"

    def test_ward_from_ward_name_key(self):
        """Entity extractor stores under 'ward_name'; canonical must find it."""
        draft = _make_municipal_draft(entities={
            "ward_name": GrievanceEntity(
                name="ward_name", value="5",
                confidence=0.7, source_text="ward 5"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["ward_number"] == "5"

    def test_city_strips_suffix_in_canonical(self):
        draft = _make_municipal_draft(entities={
            "city_name": GrievanceEntity(
                name="city_name", value="Bharuch City",
                confidence=0.85, source_text="city Bharuch City"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["city"] == "Bharuch"

    def test_locality_strips_prefix_in_canonical(self):
        draft = _make_municipal_draft(entities={
            "locality": GrievanceEntity(
                name="locality", value="Locality is: Near Modi Garden",
                confidence=0.8, source_text="locality is Near Modi Garden"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["locality"] == "Near Modi Garden"

    def test_area_strips_prefix_in_canonical(self):
        draft = _make_municipal_draft(entities={
            "area_name": GrievanceEntity(
                name="area_name", value="Area name is Modi Garden",
                confidence=0.8, source_text="area name is Modi Garden"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["area"] == "Modi Garden"

    def test_municipal_jurisdiction_local(self):
        draft = _make_municipal_draft()
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["jurisdiction"] == "Local"

    def test_state_not_in_jurisdiction(self):
        draft = _make_municipal_draft()
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert "Gujarat" not in canonical["jurisdiction"]
        assert canonical["location"]["state"] == "Gujarat"


# ═══════════════════════════════════════════════════════════════════════
# TASK 6 — Presentation template structure
# ═══════════════════════════════════════════════════════════════════════

class TestPresentationTemplate:
    """format_draft_for_display must use canonical field names and clean values."""

    def test_no_ward_label_duplication(self):
        """Must never print 'Ward Number: Ward Number 5'."""
        draft = _make_municipal_draft(entities={
            "ward_number": GrievanceEntity(
                name="ward_number", value="Ward Number 5",
                confidence=0.9, source_text="Ward Number 5"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Ward Number: Ward Number 5" not in display
        assert "Ward Number: 5" in display

    def test_no_city_label_duplication(self):
        """Must never print 'City: City is Bharuch'."""
        draft = _make_municipal_draft(entities={
            "city_name": GrievanceEntity(
                name="city_name", value="City is Bharuch",
                confidence=0.85, source_text="city is Bharuch"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "City: City is Bharuch" not in display
        assert "City: Bharuch" in display

    def test_no_area_label_prefix(self):
        """Must never print 'Area: Area name is Modi Garden'."""
        draft = _make_municipal_draft(entities={
            "area_name": GrievanceEntity(
                name="area_name", value="Area name is Modi Garden",
                confidence=0.8, source_text="area name is Modi Garden"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Area: Area name is" not in display
        assert "Area: Modi Garden" in display

    def test_location_section_present(self):
        draft = _make_municipal_draft(entities={
            "ward_number": GrievanceEntity(
                name="ward_number", value="5",
                confidence=0.9, source_text="ward 5"),
            "city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.85, source_text="city Bharuch"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "**Location:**" in display
        assert "Ward Number: 5" in display
        assert "City: Bharuch" in display

    def test_jurisdiction_shown_once(self):
        draft = _make_municipal_draft()
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert display.count("Jurisdiction") == 1

    def test_state_shown_once(self):
        draft = _make_municipal_draft(entities={
            "city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.85, source_text="city Bharuch"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert display.count("State: Gujarat") == 1

    def test_ward_name_key_resolves(self):
        """Entity extractor stores ward as 'ward_name'; display must resolve it."""
        draft = _make_municipal_draft(entities={
            "ward_name": GrievanceEntity(
                name="ward_name", value="5",
                confidence=0.7, source_text="ward 5"),
        })
        builder = GrievanceDraftBuilder()
        display = builder.format_draft_for_display(draft)
        assert "Ward Number: 5" in display


# ═══════════════════════════════════════════════════════════════════════
# TASK 9 — Proper names preserved
# ═══════════════════════════════════════════════════════════════════════

class TestProperNamesPreserved:
    """Canonical values must preserve proper names unchanged."""

    def test_city_bharuch_not_translated(self):
        draft = _make_municipal_draft(entities={
            "city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.85, source_text="city Bharuch"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["city"] == "Bharuch"

    def test_locality_proper_name(self):
        draft = _make_municipal_draft(entities={
            "locality": GrievanceEntity(
                name="locality", value="Near J.B. Modi Garden",
                confidence=0.8, source_text="locality Near J.B. Modi Garden"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["location"]["locality"] == "Near J.B. Modi Garden"


# ═══════════════════════════════════════════════════════════════════════
# TASK 10 — URL and reference safety
# ═══════════════════════════════════════════════════════════════════════

class TestUrlReferenceSafety:
    """URLs and reference numbers must pass through unchanged."""

    def test_portal_url_preserved(self):
        draft = _make_municipal_draft()
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["submission"]["portal_url"] == "https://enagaruat.gujarat.gov.in"

    def test_reference_preserved(self):
        draft = _make_municipal_draft(reference_number="GRV-20260908-ABC12345")
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["reference"] == "GRV-20260908-ABC12345"


# ═══════════════════════════════════════════════════════════════════════
# TASK 3 — Original description preserved
# ═══════════════════════════════════════════════════════════════════════

class TestOriginalDescriptionPreserved:
    """description.original must be exactly the user's original text."""

    def test_gujarati_original_preserved(self):
        original = "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે જેના માટે હું મ્યુનિસિપલ કોર્પોરેશનમાં ફરિયાદ કરવા માગું છું"
        draft = _make_municipal_draft(
            description="There is a lot of garbage in my area...",
            original_description=original,
        )
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["description"]["original"] == original

    def test_english_original_preserved(self):
        original = "My area has a lot of garbage and I want to file a complaint."
        draft = _make_municipal_draft(
            description=original,
            original_description=original,
        )
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert canonical["description"]["original"] == original


# ═══════════════════════════════════════════════════════════════════════
# TASK 15 — Structured API contract
# ═══════════════════════════════════════════════════════════════════════

class TestStructuredAPIContract:
    """Canonical grievance object must match the expected contract."""

    def test_canonical_structure_keys(self):
        draft = _make_municipal_draft(entities={
            "ward_number": GrievanceEntity(
                name="ward_number", value="5",
                confidence=0.9, source_text="ward 5"),
            "city_name": GrievanceEntity(
                name="city_name", value="Bharuch",
                confidence=0.85, source_text="city Bharuch"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        assert "reference" in canonical
        assert "category" in canonical
        assert "sub_category" in canonical
        assert "jurisdiction" in canonical
        assert "location" in canonical
        assert "submission" in canonical
        assert "ward_number" in canonical["location"]
        assert "city" in canonical["location"]
        assert "state" in canonical["location"]

    def test_no_presentation_text_in_canonical(self):
        draft = _make_municipal_draft(entities={
            "ward_number": GrievanceEntity(
                name="ward_number", value="Ward Number 5",
                confidence=0.9, source_text="Ward Number 5"),
        })
        canonical = draft.to_canonical_dict(
            portal_name="eNagarpalika",
            portal_url="https://enagaruat.gujarat.gov.in",
            submission_level="local",
        )
        # Canonical must not contain label text in values
        assert "Ward Number" not in canonical["location"]["ward_number"]
        assert canonical["location"]["ward_number"] == "5"


# ═══════════════════════════════════════════════════════════════════════
# TASK 9 — English path: regex extraction edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestLocalityCueRegex:
    """_LOCALITY_CUE_RE must handle all separator variants."""

    def test_is_colon_space(self):
        m = _LOCALITY_CUE_RE.search("Locality is: Near J.B. Modi Garden, Bharuch City")
        assert m is not None
        assert "Near J.B. Modi Garden" in m.group(1)

    def test_colon_only(self):
        m = _LOCALITY_CUE_RE.search("Locality: Manjalpur, Vadodara")
        assert m is not None
        assert m.group(1).startswith("Manjalpur")

    def test_is_space(self):
        m = _LOCALITY_CUE_RE.search("locality is Manjalpur")
        assert m is not None
        assert m.group(1) == "Manjalpur"

    def test_no_separator(self):
        m = _LOCALITY_CUE_RE.search("locality Manjalpur")
        assert m is not None
        assert m.group(1) == "Manjalpur"

    def test_is_dash_space(self):
        m = _LOCALITY_CUE_RE.search("locality - Manjalpur")
        assert m is not None
        assert m.group(1) == "Manjalpur"


class TestCityCueRegex:
    """_CITY_CUE_RE must handle all separator variants."""

    def test_bare_keyword(self):
        m = _CITY_CUE_RE.search("city Bharuch")
        assert m is not None
        assert m.group(1) == "Bharuch"

    def test_colon_space(self):
        m = _CITY_CUE_RE.search("city: Vadodara")
        assert m is not None
        assert m.group(1) == "Vadodara"

    def test_is_space(self):
        m = _CITY_CUE_RE.search("city is Ahmedabad")
        assert m is not None
        assert m.group(1) == "Ahmedabad"

    def test_not_in_locality_tail(self):
        """'city' in '...Bharuch City' must not be matched by _CITY_CUE_RE."""
        m = _CITY_CUE_RE.search("Locality is: Near J.B. Modi Garden, Bharuch City")
        assert m is None


class TestCitySuffixRegex:
    """_CITY_SUFFIX_RE must NOT match full sentences containing field keywords."""

    def test_simple_city_name(self):
        m = _CITY_SUFFIX_RE.match("Manjalpur, Vadodara City")
        assert m is not None
        assert m.group(1) == "Manjalpur, Vadodara"

    def test_rejects_locality_keyword(self):
        m = _CITY_SUFFIX_RE.match("Locality is: Near J.B. Modi Garden, Bharuch City")
        assert m is None

    def test_rejects_ward_keyword(self):
        m = _CITY_SUFFIX_RE.match("Ward 5 locality Manjalpur City")
        assert m is None


class TestSplitClausesAbbreviations:
    """_split_clauses must NOT split on periods in abbreviations like J.B."""

    def test_jb_not_split(self):
        parts = _split_clauses("Locality is: Near J.B. Modi Garden, Bharuch City.")
        assert len(parts) == 1
        assert "J.B." in parts[0]

    def test_dr_not_split(self):
        parts = _split_clauses("Dr. Smith lives here.")
        assert len(parts) == 1

    def test_real_sentences_still_split(self):
        parts = _split_clauses("My name is John. I live in Mumbai.")
        assert len(parts) == 2

    def test_and_still_splits(self):
        parts = _split_clauses("Ward 5 and locality Manjalpur")
        assert len(parts) == 2

    def test_semicolon_still_splits(self):
        parts = _split_clauses("City: Vadodara; State Gujarat")
        assert len(parts) == 2


# ═══════════════════════════════════════════════════════════════════════
# TASK 10 — End-to-end semantic extraction
# ═══════════════════════════════════════════════════════════════════════

class TestSemanticExtractionEndToEnd:
    """Full extraction pipeline for English inputs."""

    @pytest.fixture()
    def extractor(self):
        return GrievanceSemanticExtractor()

    def test_locality_is_colon_extracts_city(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="Locality is: Near J.B. Modi Garden, Bharuch City.",
        )
        assert result.extracted_fields.get("locality") is not None
        assert "Modi Garden" in result.extracted_fields["locality"]
        assert result.extracted_fields.get("city") == "Bharuch"

    def test_locality_colon_comma_extracts_city(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="Locality: Manjalpur, Vadodara",
        )
        assert result.extracted_fields.get("locality") == "Manjalpur, Vadodara"
        assert result.extracted_fields.get("city") == "Vadodara"

    def test_city_bare_keyword(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="city Bharuch",
        )
        assert result.extracted_fields.get("city") == "Bharuch"

    def test_city_colon(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="city: Vadodara",
        )
        assert result.extracted_fields.get("city") == "Vadodara"

    def test_city_is(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="city is Ahmedabad",
        )
        assert result.extracted_fields.get("city") == "Ahmedabad"

    def test_ward_locality_city_combined(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="ward 5 locality is Manjalpur city Vadodara",
        )
        fields = result.extracted_fields
        assert fields.get("ward_number") == "5"
        assert fields.get("locality") == "Manjalpur"
        assert fields.get("city") == "Vadodara"

    def test_ward_city_gujarat(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="ward number 5 city Bharuch Gujarat",
        )
        fields = result.extracted_fields
        assert fields.get("ward_number") == "5"
        assert "Bharuch" in fields.get("city", "")

    def test_dr_ward_locality(self, extractor):
        result = extractor._extract_heuristic(
            current_field=None,
            user_message="Dr. Smith ward 5 locality Manjalpur",
        )
        fields = result.extracted_fields
        assert fields.get("ward_number") == "5"
        assert fields.get("locality") == "Manjalpur"
