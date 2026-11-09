"""Tests for table formatting and answer cleaning."""

import re
from app.evidence_controller import clean_answer, strip_citations
from app.services.rag_orchestrator import fix_broken_tables

def is_valid_table(text: str) -> bool:
    return "|---" in text

class TestBrokenTables:
    def test_valid_table_passes_through(self):
        input_text = "**Eligibility**\n\n| Criteria | Details |\n|---|---|\n| Age | Above 18 years |\n| Membership | Not a member elsewhere |"
        expected = input_text
        result = fix_broken_tables(input_text)
        assert result == expected

    def test_broken_pipe_separated_text_fixed(self):
        input_text = "**Eligibility**\n\nEligibility criteria | Criteria | Details |---|---| Residence | Must live in village |"
        result = fix_broken_tables(input_text)
        # Should convert to bullet list or proper table
        assert '|' not in result or is_valid_table(result)
        
    def test_table_without_separator_row_preserved(self):
        """Test that tables with header + data rows but no separator are preserved.
        
        This is the common case with LLM-generated tables in Indian languages
        where the separator row (|---|) is often omitted.
        """
        input_text = (
            "**મુખ્ય ઘટકો**\n\n"
            "| ઘટક | વર્તન | સંબંધિત પુરાવો |\n"
            "| નાણાકીય જ્ઞાન | નાણાકીય ઉત્પાદનો વિશે મૂળભૂત જ્ઞાન | બેંકિંગ, વીમા |\n"
            "| નાણાકીય વર્તન | બજેટ બનાવવું, બચત કરવી | નિયમિત બચત |\n"
        )
        result = fix_broken_tables(input_text)
        # Should preserve the table structure (not convert to bullet list)
        assert "| ઘટક | વર્તન | સંબંધિત પુરાવો |" in result
        assert "| નાણાકીય જ્ઞાન" in result
        assert "| નાણાકીય વર્તન" in result
        # Should have added a separator row
        assert "|---|" in result or "|---|" in result.replace(" ", "")
        
    def test_single_pipe_line_converted_to_bullet(self):
        """Test that a single line with pipes (not a table) is converted to bullet."""
        input_text = "Precaution | What to do | Why important"
        result = fix_broken_tables(input_text)
        # Should be converted to bullet since it's not a proper table
        assert "- " in result
        assert "|" not in result
        
    def test_two_consecutive_pipe_lines_preserved(self):
        """Test that two consecutive lines with pipes (header + data) are preserved."""
        input_text = (
            "| Criteria | Details |\n"
            "| Age | Above 18 years |"
        )
        result = fix_broken_tables(input_text)
        # Should preserve as table with added separator
        assert "| Criteria | Details |" in result
        assert "| Age | Above 18 years |" in result
        assert "|---|" in result.replace(" ", "")
        
class TestCleanAnswer:
    """Tests for the clean_answer post-processor."""

    def test_br_tag_stripped(self):
        result = clean_answer("Line 1<br>Line 2")
        assert "<br>" not in result
        assert "Line 1" in result
        assert "Line 2" in result

    def test_br_self_closing_stripped(self):
        result = clean_answer("Line 1<br/>Line 2")
        assert "<br" not in result

    def test_horizontal_rule_removed(self):
        result = clean_answer("Text\n\n---\n\nMore text")
        assert "---" not in result
        assert "Text" in result
        assert "More text" in result

    def test_triple_star_hr_removed(self):
        result = clean_answer("Text\n\n***\n\nMore text")
        assert "***" not in result

    def test_heading_markers_removed(self):
        result = clean_answer("### Eligibility criteria")
        assert result == "Eligibility criteria"

    def test_h2_heading_removed(self):
        result = clean_answer("## How to apply")
        assert result == "How to apply"

    def test_collapse_blank_lines(self):
        result = clean_answer("A\n\n\n\nB")
        assert result == "A\n\nB"

    def test_valid_table_preserved(self):
        table = (
            "| Criteria | Details |\n"
            "|---|---|\n"
            "| Age | Above 18 years |"
        )
        result = clean_answer(table)
        assert "| Criteria | Details |" in result
        assert "|---|---|" in result
        assert "| Age | Above 18 years |" in result

    def test_mixed_content(self):
        input_text = (
            "Direct answer: You can join.<br><br>"
            "### Eligibility\n\n"
            "| Criteria | Details |\n"
            "|---|---|\n"
            "| Residence | Must live in village |\n\n"
            "---\n\n"
            "More info here."
        )
        result = clean_answer(input_text)
        assert "<br" not in result
        assert "###" not in result
        # Standalone --- HR removed, but table separator |---|---| preserved
        lines = result.split("\n")
        standalone_hrs = [l for l in lines if l.strip() in ("---", "***", "___")]
        assert len(standalone_hrs) == 0
        assert "|---|---|" in result  # Table separator preserved
        assert "| Criteria | Details |" in result


class TestStripCitations:
    """Tests for citation marker extraction."""

    def test_basic_citation(self):
        answer, ids = strip_citations("Fact [chunk:abc12345] is true.")
        assert "Fact is true." in answer
        assert "abc12345" in ids

    def test_multiple_citations(self):
        answer, ids = strip_citations(
            "Fact [chunk:aaa11111] and [chunk:bbb22222] are true."
        )
        assert "aaa11111" in ids
        assert "bbb22222" in ids
        assert "[chunk:" not in answer

    def test_web_citation(self):
        answer, ids = strip_citations(
            "Source [chunk:web_a1b2c3d4e5f6_c102] says so."
        )
        assert "web_a1b2c3d4e5f6_c102" in ids

    def test_empty_answer_preserved(self):
        answer, ids = strip_citations("No citations here.")
        assert answer == "No citations here."
        assert ids == []
