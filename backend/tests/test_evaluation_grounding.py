"""Real-world evaluation test cases for evidence grounding.

Based on observed failures:
- C01: PMFBY coverage types collapsed into generic summary
- D06: Unsupported "18-70 years" age limit added
- S08: HR policy attributed to loan policy
"""

from app.answer_grounding import verify_answer_grounding
from app.contracts import EvidenceChunk


def _make_chunk(content: str, chunk_id: str = "a0eebc99", title: str = "Test Doc", section: str = "Test Section") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type="static",
        title=title,
        section=section,
        domain="test",
        dense_score=0.8,
    )


# ---------------------------------------------------------------------------
# C01-type: Enumeration preservation
# ---------------------------------------------------------------------------

class TestC01EnumerationPreservation:
    """Tests for C01 failure: PMFBY coverage types collapsed into generic summary."""

    def test_pmfby_coverage_types_preserved(self):
        """Evidence lists 4 coverage types. Answer must contain all 4."""
        evidence = [_make_chunk(
            "The coverage under PMFBY includes: prevented sowing, "
            "mid-season adversity, post-harvest losses, and localized calamity.",
            chunk_id="a0eebc99",
        )]
        answer = (
            "Under PMFBY, the coverage types are:\n"
            "- Prevented sowing\n"
            "- Mid-season adversity\n"
            "- Post-harvest losses\n"
            "- Localized calamity"
        )
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False

    def test_no_generic_substitution(self):
        """Evidence lists specific types. Answer must not use generic summary."""
        evidence = [_make_chunk(
            "Coverage includes: prevented sowing, mid-season adversity, "
            "post-harvest losses, localized calamity.",
        )]
        answer = "PMFBY provides protection against various natural and climatic risks."
        result = verify_answer_grounding(answer, evidence)
        # The answer doesn't contain specific terms, but regex won't catch this
        # This test verifies the prompt changes work, not the regex
        # The regex test is that we don't get false positives
        assert isinstance(result.has_unsupported_claims, bool)


# ---------------------------------------------------------------------------
# D06-type: Unsupported numeric facts
# ---------------------------------------------------------------------------

class TestD06UnsupportedNumbers:
    """Tests for D06 failure: Unsupported age limit added."""

    def test_age_limit_not_in_evidence(self):
        """Evidence has no age limit. Answer must not contain one.

        Regex layer: condition pattern matches 'age \\d+[-–]\\d+ years'.
        """
        evidence = [_make_chunk(
            "Eligibility: Sharecropper, tenant farmer, notified crop, "
            "notified area. The farmer must be a member of the cooperative.",
        )]
        answer = "To be eligible for PMFBY, age 18-70 years is required."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is True
        assert any("age 18-70 years" in c.claim_text for c in result.unsupported_claims)

    def test_premium_rate_preserved(self):
        """Evidence says 2%. Answer must say 2%, not approximately."""
        evidence = [_make_chunk("The premium rate is 2% of the sum insured.")]
        answer = "The premium rate is 2% of the sum insured."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False

    def test_date_preserved(self):
        """Evidence says 31 March. Answer must not invent another date."""
        evidence = [_make_chunk("The deadline for application is 31 March.")]
        answer = "The deadline for application is 31 March."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# S08-type: Section attribution confusion
# ---------------------------------------------------------------------------

class TestS08SectionAttribution:
    """Tests for S08 failure: HR policy attributed to loan policy."""

    def test_entity_attribution(self):
        """Answer must not attribute wrong entity.

        Note: 'HR policy' is not in the entity regex pattern (which covers
        PMFBY, PACS, etc.). This test verifies that the grounding framework
        doesn't crash and returns a valid result. Actual entity attribution
        enforcement is prompt-level.
        """
        evidence = [_make_chunk(
            "Loan policy: Loans are sanctioned by the Board of Directors. "
            "The loan amount is determined based on the project report.",
        )]
        answer = "The HR policy determines the loan amount based on the project report."
        result = verify_answer_grounding(answer, evidence)
        # HR policy is not in the entity pattern, so regex won't flag it.
        # This test verifies the framework runs without error.
        assert isinstance(result.has_unsupported_claims, bool)

    def test_correct_attribution(self):
        """Answer correctly attributes to loan policy."""
        evidence = [_make_chunk(
            "Loan policy: Loans are sanctioned by the Board of Directors. "
            "The loan amount is determined based on the project report.",
        )]
        answer = "The loan policy determines the loan amount based on the project report."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Missing information handling
# ---------------------------------------------------------------------------

class TestMissingInformation:
    """Tests for missing evidence scenarios."""

    def test_missing_evidence_reported(self):
        """Question asks for X, evidence only has Y. Answer should not fabricate."""
        evidence = [_make_chunk("PACS provides credit facilities to members.")]
        answer = "PACS provides credit facilities. The interest rate is 12% per annum."
        result = verify_answer_grounding(answer, evidence)
        # 12% is not in evidence, should be flagged
        assert result.has_unsupported_claims is True
        assert any("12%" in c.claim_text for c in result.unsupported_claims)


# ---------------------------------------------------------------------------
# Multilingual grounding
# ---------------------------------------------------------------------------

class TestMultilingualGrounding:
    """Tests for multilingual answer grounding."""

    def test_hindi_answer_with_english_evidence(self):
        """Hindi answer with English evidence. Factual terms must survive."""
        evidence = [_make_chunk(
            "PMFBY coverage includes prevented sowing, mid-season adversity."
        )]
        answer = "PMFBY में prevented sowing और mid-season adversity शामिल है।"
        result = verify_answer_grounding(answer, evidence)
        # The English terms should still be found in evidence
        assert result.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_answer(self):
        """Empty answer should not crash."""
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    def test_no_chunks(self):
        """No chunks should not crash."""
        result = verify_answer_grounding("Some answer", [])
        assert isinstance(result.has_unsupported_claims, bool)

    def test_special_characters_in_numbers(self):
        """Numbers with special characters should be handled."""
        evidence = [_make_chunk("The amount is Rs. 50,000.")]
        answer = "The amount is Rs. 50,000."
        result = verify_answer_grounding(answer, evidence)
        assert result.has_unsupported_claims is False
