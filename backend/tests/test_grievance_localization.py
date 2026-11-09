"""Tests for grievance localization: field prompts, followup prefixes,
submission steps, workflow prefixes, and translate_field_prompt().

Covers:
- Category A: FIELD_PROMPTS map and translate_field_prompt()
- Category B: Missing PMFBY submission steps
- Category C: Followup question prefix translations
- Category E: Workflow response prefix translations
"""


from app.grievance.translations import (
    FIELD_PROMPTS,
    FOLLOWUP_PREFIX,
    WORKFLOW_PREFIX,
    SUBMISSION_STEPS,
    translate_field_prompt,
    translate_grievance_string,
)


# ── Category A: FIELD_PROMPTS ──────────────────────────────────────────


class TestFieldPrompts:
    """Verify FIELD_PROMPTS map has correct translations for key prompts."""

    def test_farmer_name_prompt_hindi(self):
        prompt = "Farmer's name?"
        assert FIELD_PROMPTS[prompt]["hi"] == "किसान का नाम?"
        assert FIELD_PROMPTS[prompt]["gu"] == "ખેડૂતનું નામ?"
        assert FIELD_PROMPTS[prompt]["mr"] == "शेतकऱ्याचे नाव?"
        assert FIELD_PROMPTS[prompt]["bn"] == "কৃষকের নাম?"
        assert FIELD_PROMPTS[prompt]["ta"] == "விவசாயியின் பெயர்?"

    def test_crop_prompt_hindi(self):
        prompt = "Crop name?"
        assert FIELD_PROMPTS[prompt]["hi"] == "फसल का नाम?"

    def test_season_prompt_hindi(self):
        prompt = "Season? (Kharif, Rabi, Summer)"
        assert FIELD_PROMPTS[prompt]["hi"] == "मौसम? (खरीफ, रबी, ग्रीष्म)"

    def test_insurance_company_prompt_hindi(self):
        prompt = "Insurance company name?"
        assert FIELD_PROMPTS[prompt]["hi"] == "बीमा कंपनी का नाम?"

    def test_bank_name_prompt_hindi(self):
        prompt = "What is the bank name?"
        assert FIELD_PROMPTS[prompt]["hi"] == "बैंक का नाम क्या है?"

    def test_rti_prompt_hindi(self):
        prompt = "What is your RTI application number?"
        assert FIELD_PROMPTS[prompt]["hi"] == "आपका आरटीआई आवेदन संख्या क्या है?"

    def test_police_station_prompt_hindi(self):
        prompt = "Which police station?"
        assert FIELD_PROMPTS[prompt]["hi"] == "कौन सा पुलीस स्टेशन?"

    def test_all_prompts_have_all_languages(self):
        """Every prompt in FIELD_PROMPTS must have all 6 language keys."""
        required_langs = {"en", "hi", "gu", "mr", "bn", "ta"}
        for prompt, langs in FIELD_PROMPTS.items():
            assert set(langs.keys()) == required_langs, (
                f"Prompt '{prompt}' missing languages: {required_langs - set(langs.keys())}"
            )


class TestTranslateFieldPrompt:
    """Verify translate_field_prompt() uses the static map."""

    def test_known_prompt_hindi(self):
        result = translate_field_prompt("farmer_name", "hi", "Farmer's name?")
        assert result == "किसान का नाम?"

    def test_known_prompt_gujarati(self):
        result = translate_field_prompt("crop", "gu", "Crop name?")
        assert result == "પાકનું નામ?"

    def test_known_prompt_marathi(self):
        result = translate_field_prompt("season", "mr", "Season? (Kharif, Rabi, Summer)")
        assert result == "हंगाम? (खरीप, रबी, उन्हाळा)"

    def test_known_prompt_bengali(self):
        result = translate_field_prompt("insurance_company", "bn", "Insurance company name?")
        assert result == "বীমা কোম্পানির নাম?"

    def test_known_prompt_tamil(self):
        result = translate_field_prompt("bank_name", "ta", "What is the bank name?")
        assert result == "வங்கியின் பெயர் என்ன?"

    def test_english_returns_original(self):
        result = translate_field_prompt("farmer_name", "en", "Farmer's name?")
        assert result == "Farmer's name?"

    def test_unknown_prompt_returns_english(self):
        """Unknown prompts should fall back to English."""
        result = translate_field_prompt("unknown_field", "hi", "Some unknown prompt?")
        assert result == "Some unknown prompt?"


# ── Category B: Missing PMFBY submission steps ──────────────────────────


class TestPMFBYSubmissionSteps:
    """Verify missing PMFBY submission step strings exist in SUBMISSION_STEPS."""

    def test_pmfby_lodge_complaint_step(self):
        key = "For PMFBY: Lodge complaint on https://pmfby.gov.in/ 'Grievance' section"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_insurance_nodal_officer_step(self):
        key = "Contact insurance company nodal officer"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_escalation_step(self):
        key = "Escalate to State Agriculture Department / District Agriculture Officer"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_cpgrams_step(self):
        key = "Also on CPGRAMS under 'Agriculture'"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_application_id_doc(self):
        key = "PMFBY application / enrollment ID"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_land_records_doc(self):
        key = "Land records (7/12 extract, khatauni)"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_bank_passbook_doc(self):
        key = "Bank passbook (for premium debit proof)"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key

    def test_pmfby_crop_cutting_doc(self):
        key = "Crop cutting experiment report (if available)"
        assert key in SUBMISSION_STEPS
        assert SUBMISSION_STEPS[key]["hi"] != key


# ── Category C: Followup prefix translations ────────────────────────────


class TestFollowupPrefix:
    """Verify followup question prefix strings are translated."""

    def test_single_question_prefix_hindi(self):
        key = "To help you better, I need one more detail:\n\n"
        assert key in FOLLOWUP_PREFIX
        assert FOLLOWUP_PREFIX[key]["hi"] == "आपकी बेहतर मदद के लिए मुझे एक और जानकारी चाहिए:\n\n"

    def test_multi_question_prefix_hindi(self):
        key = "To complete your grievance draft, I need a few more details:\n\n"
        assert key in FOLLOWUP_PREFIX
        assert FOLLOWUP_PREFIX[key]["hi"] != key

    def test_suffix_hindi(self):
        key = "You can answer them one by one or provide multiple details at once."
        assert key in FOLLOWUP_PREFIX
        assert FOLLOWUP_PREFIX[key]["hi"] != key

    def test_all_followup_prefixes_have_all_languages(self):
        required_langs = {"en", "hi", "gu", "mr", "bn", "ta"}
        for key, langs in FOLLOWUP_PREFIX.items():
            assert set(langs.keys()) == required_langs, (
                f"Followup prefix '{key[:40]}...' missing languages"
            )

    def test_translate_grievance_string_finds_followup_prefix(self):
        """translate_grievance_string() should find followup prefixes."""
        result = translate_grievance_string(
            "To help you better, I need one more detail:\n\n",
            "hi",
            "followup_prefix",
        )
        assert result != "To help you better, I need one more detail:\n\n"


# ── Category E: Workflow prefix translations ────────────────────────────


class TestWorkflowPrefix:
    """Verify workflow response prefix strings are translated."""

    def test_workflow_prefix_hindi(self):
        key = "Thank you. I've updated your grievance draft."
        assert key in WORKFLOW_PREFIX
        assert WORKFLOW_PREFIX[key]["hi"] == "धन्यवाद। मैंने आपकी शिकायत का मसौदा अपडेट कर दिया है।"

    def test_workflow_prefix_gujarati(self):
        key = "Thank you. I've updated your grievance draft."
        assert WORKFLOW_PREFIX[key]["gu"] != key

    def test_workflow_prefix_marathi(self):
        key = "Thank you. I've updated your grievance draft."
        assert WORKFLOW_PREFIX[key]["mr"] != key

    def test_workflow_prefix_bengali(self):
        key = "Thank you. I've updated your grievance draft."
        assert WORKFLOW_PREFIX[key]["bn"] != key

    def test_workflow_prefix_tamil(self):
        key = "Thank you. I've updated your grievance draft."
        assert WORKFLOW_PREFIX[key]["ta"] != key

    def test_translate_grievance_string_finds_workflow_prefix(self):
        """translate_grievance_string() should find workflow prefixes."""
        result = translate_grievance_string(
            "Thank you. I've updated your grievance draft.",
            "hi",
            "workflow_prefix",
        )
        assert result != "Thank you. I've updated your grievance draft."
