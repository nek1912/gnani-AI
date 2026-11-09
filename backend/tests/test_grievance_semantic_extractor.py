
from __future__ import annotations

from unittest.mock import patch

from app.grievance.semantic_extractor import (
    GrievanceSemanticExtractor,
    SemanticExtractionResult,
)


def _make_extractor() -> GrievanceSemanticExtractor:
    return GrievanceSemanticExtractor(use_gemini=False)


class TestGeminiHeuristicFallback:
    """Tests for the Gemini → heuristic fallback when Gemini does not
    capture the requested target field."""

    def test_gemini_wrong_field_falls_back_to_heuristic(self):
        """When Gemini returns {"description": "2026"} for
        current_field="year", the heuristic must run and produce
        {"year": "2026"} — the incorrect Gemini description must
        not survive."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={"description": "2026"},
            invalid=False,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field="year",
                        user_message="2026",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )

        assert result.extracted_fields == {"year": "2026"}
        assert "description" not in result.extracted_fields
        assert not result.invalid
        assert not result.unrelated

    def test_gemini_wrong_field_year_wording(self):
        """When Gemini returns {"description": "Year 2026"} for
        current_field="year", the heuristic must produce year."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={"description": "Year 2026"},
            invalid=False,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field="year",
                        user_message="Year 2026",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )

        assert "year" in result.extracted_fields
        assert "description" not in result.extracted_fields

    def test_gemini_correct_target_preserved(self):
        """When Gemini correctly returns the target field, the heuristic
        must NOT be invoked."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={"ward_number": "Ward 12"},
            invalid=False,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ) as mock_gemini:
                    result = ext.extract(
                        current_field="ward_number",
                        user_message="Ward 12",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="municipal",
                        sub_category="garbage",
                        department="Municipal",
                    )

        assert result.extracted_fields == {"ward_number": "Ward 12"}
        mock_gemini.assert_called_once()

    def test_current_field_none_preserves_old_behavior(self):
        """When current_field is None, a non-empty Gemini result must be
        preserved — the new fallback must not discard it."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={"description": "Some text"},
            invalid=False,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field=None,
                        user_message="Some text",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="other",
                        sub_category="other",
                        department="Other",
                    )

        assert result.extracted_fields == {"description": "Some text"}

    def test_gemini_invalid_falls_back_to_heuristic(self):
        """When Gemini marks the result as invalid with no extracted fields
        and a current_field is set, the heuristic IS invoked so it can
        attempt field-specific extraction (e.g. 'season', 'year')."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={},
            invalid=True,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ) as mock_gemini:
                    result = ext.extract(
                        current_field="year",
                        user_message="2025",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )

        mock_gemini.assert_called_once()
        assert result.extracted_fields == {"year": "2025"}

    def test_gemini_unrelated_with_current_field_falls_back(self):
        """When Gemini marks the result as unrelated but a current_field
        is set, the heuristic IS invoked because Gemini cannot express
        non-schema fields (season, year, crop, etc.) via structured output."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={},
            invalid=False,
            unrelated=True,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ) as mock_gemini:
                    result = ext.extract(
                        current_field="year",
                        user_message="2026",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )

        mock_gemini.assert_called_once()
        assert result.extracted_fields == {"year": "2026"}


class TestHeuristicPathDirect:
    """Direct tests of the heuristic extraction for year fields."""

    def test_heuristic_bare_year(self):
        ext = _make_extractor()
        result = ext.extract(
            current_field="year",
            user_message="2026",
            known_fields=set(),
            required_fields=[],
            optional_fields=[],
            missing_fields=[],
            original_complaint="test",
            category="agriculture",
            sub_category="pmfby_claim_delay",
            department="Agriculture",
        )
        assert result.extracted_fields == {"year": "2026"}

    def test_heuristic_year_wording(self):
        ext = _make_extractor()
        result = ext.extract(
            current_field="year",
            user_message="Year 2026",
            known_fields=set(),
            required_fields=[],
            optional_fields=[],
            missing_fields=[],
            original_complaint="test",
            category="agriculture",
            sub_category="pmfby_claim_delay",
            department="Agriculture",
        )
        assert "year" in result.extracted_fields
        assert "description" not in result.extracted_fields

    def test_heuristic_season_extraction(self):
        """Regression: 'Rabi' must extract to season, not description,
        when current_field='season'."""
        ext = _make_extractor()
        result = ext.extract(
            current_field="season",
            user_message="Rabi",
            known_fields=set(),
            required_fields=[],
            optional_fields=[],
            missing_fields=[],
            original_complaint="test",
            category="agriculture",
            sub_category="pmfby_claim_delay",
            department="Agriculture",
        )
        assert result.extracted_fields == {"season": "Rabi"}
        assert "description" not in result.extracted_fields

    def test_gemini_invalid_season_falls_back(self):
        """Regression: when Gemini returns invalid=True for a non-schema
        field like 'season', the heuristic must still extract the value."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={},
            invalid=True,
            unrelated=False,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field="season",
                        user_message="Rabi",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )
        assert result.extracted_fields == {"season": "Rabi"}

    def test_gemini_unrelated_season_falls_back(self):
        """Regression: when Gemini returns unrelated=True for a non-schema
        field like 'season', the heuristic must still extract the value."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={},
            invalid=False,
            unrelated=True,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field="season",
                        user_message="Rabi",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="agriculture",
                        sub_category="pmfby_claim_delay",
                        department="Agriculture",
                    )
        assert result.extracted_fields == {"season": "Rabi"}

    def test_gemini_unrelated_no_current_field_stays_unrelated(self):
        """When current_field is None and Gemini says unrelated=True,
        the result must remain unrelated — no heuristic fallback."""
        ext = _make_extractor()
        gemini_result = SemanticExtractionResult(
            extracted_fields={},
            invalid=False,
            unrelated=True,
        )
        with patch.object(ext, "_gemini_enabled", True):
            with patch.object(ext, "_api_key", "fake"):
                with patch.object(
                    ext, "_extract_via_gemini", return_value=gemini_result
                ):
                    result = ext.extract(
                        current_field=None,
                        user_message="some unrelated text",
                        known_fields=set(),
                        required_fields=[],
                        optional_fields=[],
                        missing_fields=[],
                        original_complaint="test",
                        category="other",
                        sub_category="other",
                        department="Other",
                    )
        assert result.unrelated is True
        assert result.extracted_fields == {}

    def test_genuinely_unrelated_not_turned_into_season(self):
        """A question-like message that is genuinely unrelated must NOT
        be extracted as a season value, even when current_field='season'."""
        ext = _make_extractor()
        result = ext.extract(
            current_field="season",
            user_message="What is the weather today?",
            known_fields=set(),
            required_fields=[],
            optional_fields=[],
            missing_fields=[],
            original_complaint="test",
            category="agriculture",
            sub_category="pmfby_claim_delay",
            department="Agriculture",
        )
        assert "season" not in result.extracted_fields
