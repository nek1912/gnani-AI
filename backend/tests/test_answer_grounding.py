"""Tests for evidence-grounding verification."""

from app.answer_grounding import verify_answer_grounding, GroundingResult, UnsupportedClaim
from app.contracts import EvidenceChunk
from app.evidence_controller import detect_enumeration_question
from app.services.rag_orchestrator import RAGOrchestrator


def _make_chunk(content: str, chunk_id: str = "a0eebc99") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type="static",
        title="Test Document",
        section="Test Section",
        domain="test",
        dense_score=0.8,
    )


class TestRegexExtraction:
    def test_extracts_numbers(self):
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        result = verify_answer_grounding(
            "The premium rate is 5% of the sum insured.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("5%" in c.claim_text for c in result.unsupported_claims)

    def test_extracts_dates(self):
        chunk = _make_chunk("The deadline is 31 March 2025.")
        result = verify_answer_grounding(
            "The deadline is 15 April 2025.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("15 April" in c.claim_text for c in result.unsupported_claims)

    def test_preserves_correct_numbers(self):
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        result = verify_answer_grounding(
            "The premium rate is 2% of the sum insured.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_extracts_named_entities(self):
        chunk = _make_chunk("Apply to the District Magistrate.")
        result = verify_answer_grounding(
            "Apply to the Block Development Officer.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("Block Development Officer" in c.claim_text for c in result.unsupported_claims)

    def test_no_false_positives_for_common_words(self):
        chunk = _make_chunk("The farmer must be a member of the PACS.")
        result = verify_answer_grounding(
            "The farmer must be a member of the PACS.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_bare_number_not_flagged_as_claim(self):
        """A bare number in a date context should not be flagged as unsupported."""
        chunk = _make_chunk("The deadline is 31 March 2025.")
        result = verify_answer_grounding(
            "The deadline is 31 March 2025.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_bare_number_in_sentence_not_flagged(self):
        """A bare number embedded in prose should not be extracted."""
        chunk = _make_chunk("The scheme has 5 categories and a 2% premium.")
        result = verify_answer_grounding(
            "The scheme has 5 categories and a 2% premium.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_currency_number_flagged(self):
        """A currency-prefixed number should still be extracted."""
        chunk = _make_chunk("The premium is Rs.500.")
        result = verify_answer_grounding(
            "The premium is Rs.750.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("Rs.750" in c.claim_text for c in result.unsupported_claims)


class TestConditionExtraction:
    def test_extracts_conditions(self):
        """Positive test: conditions present in answer but not in evidence."""
        chunk = _make_chunk("Premium rates are 2%.")
        result = verify_answer_grounding(
            "Applicants must be members of a PACS. The age 18-65 years is required.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any("age 18-65 years" in c.claim_text for c in result.unsupported_claims)
        assert any(c.claim_type == "condition" for c in result.unsupported_claims)

    def test_conditions_present_in_evidence(self):
        """Negative test: conditions present in both answer and evidence."""
        chunk = _make_chunk("The applicant must be a member of a PACS. Age 18-65 years required.")
        result = verify_answer_grounding(
            "The applicant must be a member of a PACS. Age 18-65 years required.",
            [chunk],
        )
        assert result.has_unsupported_claims is False

    def test_extracts_minimum_condition(self):
        """Positive test: minimum condition not in evidence."""
        chunk = _make_chunk("Premium rates are 2%.")
        result = verify_answer_grounding(
            "minimum 21 years is required.",
            [chunk],
        )
        assert result.has_unsupported_claims is True
        assert any(c.claim_type == "condition" for c in result.unsupported_claims)

    def test_no_conditions_in_text(self):
        """No conditions extracted when text has none."""
        chunk = _make_chunk("The premium is 2% of the sum insured.")
        result = verify_answer_grounding(
            "The premium is 2% of the sum insured.",
            [chunk],
        )
        assert result.has_unsupported_claims is False


class TestGroundingResult:
    def test_empty_answer(self):
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    def test_no_chunks(self):
        result = verify_answer_grounding("Some answer", [])
        # No chunks means we can't verify, but shouldn't crash
        assert isinstance(result, GroundingResult)


class TestEnumerationDetector:
    def test_types_question(self):
        assert detect_enumeration_question("What are the types of risk coverage under PMFBY?") is True

    def test_categories_question(self):
        assert detect_enumeration_question("What are the categories of loans available?") is True

    def test_eligibility_question(self):
        assert detect_enumeration_question("Who is eligible for PMFBY?") is True

    def test_requirements_question(self):
        assert detect_enumeration_question("What documents are required?") is True

    def test_benefits_question(self):
        assert detect_enumeration_question("What are the benefits of PACS membership?") is True

    def test_coverage_question(self):
        assert detect_enumeration_question("What is covered under the scheme?") is True

    def test_steps_question(self):
        assert detect_enumeration_question("What are the steps to apply?") is True

    def test_exclusions_question(self):
        assert detect_enumeration_question("What are the exclusions?") is True

    def test_normal_question(self):
        assert detect_enumeration_question("How do I apply for a loan?") is False

    def test_factual_question(self):
        assert detect_enumeration_question("What is PMFBY?") is False

    def test_hindi_enumeration(self):
        assert detect_enumeration_question("PMFBY के तहत कवरेज के प्रकार क्या हैं?") is True

    def test_gujarati_enumeration(self):
        assert detect_enumeration_question("PMFBY હેઠળ કવરેજના પ્રકારો શું છે?") is True


class TestCurrencyClaimExtraction:
    """Regression: currency amounts with Unicode thin space (U+202F) must be

    extracted and flagged as unsupported when not in evidence, and repaired
    out of the answer by the grounding repair path.
    """

    def test_thin_space_currency_extracted(self):
        """Rupee amount with thin space (U+202F) is extracted as a number claim."""
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        # LLM hallucinates a specific rupee amount with thin-space formatting
        answer = "The premium is ₹ 2 for kharif crops."
        result = verify_answer_grounding(answer, [chunk])
        assert result.has_unsupported_claims is True
        assert any("₹ 2" in c.claim_text for c in result.unsupported_claims)
        assert any(c.claim_type == "number" for c in result.unsupported_claims)

    def test_thin_space_currency_unsupported(self):
        """Rupee amount not in evidence is correctly flagged unsupported."""
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        answer = "The compensation is ₹ 1 per hectare."
        result = verify_answer_grounding(answer, [chunk])
        assert result.has_unsupported_claims is True
        assert any("₹ 1" in c.claim_text for c in result.unsupported_claims)

    def test_currency_in_evidence_supported(self):
        """Rupee amount present in evidence is NOT flagged."""
        chunk = _make_chunk("The premium is ₹2 per acre.")
        answer = "The premium is ₹2 per acre."
        result = verify_answer_grounding(answer, [chunk])
        assert result.has_unsupported_claims is False

    def test_regular_space_currency_extracted(self):
        """Rupee amount with regular space is also extracted."""
        chunk = _make_chunk("The premium rate is 2%.")
        answer = "The premium is ₹ 2 for farmers."
        result = verify_answer_grounding(answer, [chunk])
        assert result.has_unsupported_claims is True
        assert any("₹ 2" in c.claim_text for c in result.unsupported_claims)

    def test_multiple_currency_claims_both_flagged(self):
        """Two different unsupported currency amounts are both flagged."""
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        answer = (
            "The premium is ₹ 2 for kharif crops. "
            "The deductible is ₹ 1 per hectare."
        )
        result = verify_answer_grounding(answer, [chunk])
        assert result.has_unsupported_claims is True
        claim_texts = [c.claim_text for c in result.unsupported_claims]
        assert any("₹ 2" in t for t in claim_texts)
        assert any("₹ 1" in t for t in claim_texts)


class TestGroundingRepair:
    """Regression: grounding repair must remove sentences with unsupported

    currency claims, including final sentences without trailing punctuation.
    """

    def test_repair_removes_thin_space_currency_sentence(self):
        """Repair removes the sentence containing a thin-space rupee amount."""
        chunk = _make_chunk("The premium rate is 2% of the sum insured.")
        answer = "The premium is ₹ 2 for kharif crops. The scheme covers paddy."
        unsupported = [
            UnsupportedClaim(
                claim_text="₹ 2",
                claim_type="number",
                evidence_chunk_ids=[chunk.chunk_id],
            )
        ]
        repaired = RAGOrchestrator._repair_unsupported_claims(answer, unsupported)
        assert "₹ 2" not in repaired
        assert "covers paddy" in repaired or "paddy" in repaired.lower()

    def test_repair_removes_final_sentence_no_punctuation(self):
        """Repair removes final sentence even when it has no trailing punctuation."""
        chunk = _make_chunk("The premium rate is 2%.")
        answer = "The scheme covers paddy. The premium is ₹ 1"
        unsupported = [
            UnsupportedClaim(
                claim_text="₹ 1",
                claim_type="number",
                evidence_chunk_ids=[chunk.chunk_id],
            )
        ]
        repaired = RAGOrchestrator._repair_unsupported_claims(answer, unsupported)
        assert "₹ 1" not in repaired
        assert "covers paddy" in repaired

    def test_repair_removes_both_currency_claims(self):
        """Repair removes both unsupported currency amounts from separate sentences."""
        chunk = _make_chunk("The premium rate is 2%.")
        answer = (
            "The premium is ₹ 2 for kharif. "
            "The deductible is ₹ 1 per hectare."
        )
        unsupported = [
            UnsupportedClaim(
                claim_text="₹ 2",
                claim_type="number",
                evidence_chunk_ids=[chunk.chunk_id],
            ),
            UnsupportedClaim(
                claim_text="₹ 1",
                claim_type="number",
                evidence_chunk_ids=[chunk.chunk_id],
            ),
        ]
        repaired = RAGOrchestrator._repair_unsupported_claims(answer, unsupported)
        assert "₹ 2" not in repaired
        assert "₹ 1" not in repaired
        assert len(repaired) == 0  # both sentences removed

    def test_repair_preserves_supported_content(self):
        """Repair only removes the sentence with the unsupported claim."""
        chunk = _make_chunk("The premium rate is 2%.")
        answer = "PMFBY covers food crops. The premium is ₹ 2. Enrollment is online."
        unsupported = [
            UnsupportedClaim(
                claim_text="₹ 2",
                claim_type="number",
                evidence_chunk_ids=[chunk.chunk_id],
            )
        ]
        repaired = RAGOrchestrator._repair_unsupported_claims(answer, unsupported)
        assert "₹ 2" not in repaired
        assert "PMFBY covers food crops" in repaired
        assert "Enrollment is online" in repaired


class TestGroundingResult:
    def test_empty_answer(self):
        result = verify_answer_grounding("", [])
        assert result.has_unsupported_claims is False

    def test_no_chunks(self):
        result = verify_answer_grounding("Some answer", [])
        # No chunks means we can't verify, but shouldn't crash
        assert isinstance(result, GroundingResult)
