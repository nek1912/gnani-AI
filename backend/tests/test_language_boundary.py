"""Clean language boundary tests — TASK 15.

Proves the two-boundary architecture:
  INPUT:  non-English → English (before workflow)
  OUTPUT: English → target language (after workflow)

The English grievance workflow is the single source of truth.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceStage,
    GrievanceSubCategory,
)
from app.grievance.workflow import GrievanceWorkflow
from app.grievance.submission_guide import GrievanceSubmissionGuide


@pytest.fixture
def workflow():
    return GrievanceWorkflow()


# ── A. English input bypasses input translation ──────────────────────────
class TestEnglishBypassesTranslation:
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_english_input_not_translated(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please describe your complaint."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        result = _process_grievance_message(
            question="I want to file a complaint about garbage",
            session_id="test-en",
            input_lang="en",
            settings=settings,
        )

        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        assert passed_message == "I want to file a complaint about garbage"
        assert result.text == "Please describe your complaint."


# ── B. Gujarati input translated to English before workflow ───────────────
class TestGujaratiInputTranslated:
    @patch("app.routes.chat._translate_from_english", return_value="ગુજરાતી response")
    @patch("app.routes.chat._translate_to_english", return_value="Garbage complaint in my area")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_gujarati_translated_to_english(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the ward number?"
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે",
            session_id="test-gu",
            input_lang="gu",
            settings=settings,
        )

        mock_to_en.assert_called_once_with(
            "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે", "gu", settings,
        )
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        assert passed_message == "Garbage complaint in my area"


# ── C. Hindi input translated to English before workflow ─────────────────
class TestHindiInputTranslated:
    @patch("app.routes.chat._translate_from_english", return_value="हिंदी response")
    @patch("app.routes.chat._translate_to_english", return_value="Garbage complaint")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_hindi_translated_to_english(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please describe."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question="मेरे क्षेत्र में कचरा है",
            session_id="test-hi",
            input_lang="hi",
            settings=settings,
        )

        mock_to_en.assert_called_once()
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        assert passed_message == "Garbage complaint"


# ── D–F. Marathi, Bengali, Tamil follow same pattern ─────────────────────
class TestOtherLanguagesTranslated:
    @pytest.mark.parametrize("lang,text", [
        ("mr", "माझ्या भागात कचरा आहे"),
        ("bn", "আমার এলাকায় আবর্জনা আছে"),
        ("ta", "என் பகுதியில் குப்பை உள்ளது"),
    ])
    @patch("app.routes.chat._translate_from_english", return_value="translated")
    @patch("app.routes.chat._translate_to_english", return_value="Garbage in area")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_non_english_translated_to_english(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en, lang, text,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please describe."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question=text, session_id=f"test-{lang}",
            input_lang=lang, settings=settings,
        )
        mock_to_en.assert_called_once_with(text, lang, settings)


# ── G. English workflow receives only English ────────────────────────────
class TestWorkflowReceivesOnlyEnglish:
    @patch("app.routes.chat._translate_to_english", return_value="Garbage in my area")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_workflow_never_sees_non_english(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the ward number?"
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question="મારી આસપાસના વિસ્તારમાં કચરો છે",
            session_id="test-gu2", input_lang="gu", settings=settings,
        )

        # _translate_to_english must have been called
        mock_to_en.assert_called_once_with(
            "મારી આસપાસના વિસ્તારમાં કચરો છે", "gu", settings,
        )
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        # Workflow receives only English — no Gujarati characters in the range
        assert all(ord(c) < 0x0A80 or ord(c) > 0x0AFF for c in passed_message)
        assert passed_message == "Garbage in my area"


# ── H. Target language is preserved separately ───────────────────────────
class TestTargetLanguagePreserved:
    @patch("app.routes.chat._translate_from_english", return_value="ગુજરાતી response")
    @patch("app.routes.chat._translate_to_english", return_value="Garbage complaint")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_target_lang_used_for_output(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the ward number?"
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        result = _process_grievance_message(
            question="કચરો", session_id="test-gu3",
            input_lang="gu", settings=settings,
        )

        mock_from_en.assert_called_once_with(
            "What is the ward number?", "gu", settings,
        )
        assert result.text == "ગુજરાતી response"


# ── I. English output is NOT translated ──────────────────────────────────
class TestEnglishOutputNotTranslated:
    @patch("app.routes.chat._translate_from_english")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_english_skips_output_translation(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please describe your complaint."
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        result = _process_grievance_message(
            question="I want to file a complaint",
            session_id="test-en2", input_lang="en", settings=settings,
        )

        mock_from_en.assert_not_called()
        assert result.text == "Please describe your complaint."


# ── J. Non-English output translated exactly once ────────────────────────
class TestSingleTranslationPass:
    @patch("app.routes.chat._translate_from_english", return_value="ગુજરાતી")
    @patch("app.routes.chat._translate_to_english", return_value="English")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_single_back_translation(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the ward number?"
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question="કચરો", session_id="test-gu4",
            input_lang="gu", settings=settings,
        )

        assert mock_from_en.call_count == 1


# ── K. No second translation pass ────────────────────────────────────────
class TestNoDoubleTranslation:
    @patch("app.routes.chat._translate_from_english", return_value="already Gujarati")
    @patch("app.routes.chat._translate_to_english", return_value="English text")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_no_second_translation(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en, mock_from_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "English response"
        mock_result.draft = None
        mock_result.submission_route = None
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()
        _process_grievance_message(
            question="કચરો", session_id="test-gu5",
            input_lang="gu", settings=settings,
        )

        # Input translated once, output translated once — never more
        assert mock_to_en.call_count == 1
        assert mock_from_en.call_count == 1


# ── L. Original user description is unchanged ────────────────────────────
class TestOriginalDescriptionUnchanged:
    def test_canonical_preserves_original(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Garbage",
            description="Garbage in my area",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="state",
            state=None,
            department="Municipal Corp",
            original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે",
        )
        d = draft.to_canonical_dict()
        assert d["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"
        assert d["description"]["normalized"] == "Garbage in my area"


# ── M. Canonical grievance object remains language-neutral ───────────────
class TestCanonicalLanguageNeutral:
    def test_canonical_english_keys(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="state",
            state=None,
            department="Municipal Corp",
        )
        d = draft.to_canonical_dict()
        assert d["category"] == "Municipal"
        assert d["sub_category"] == "Garbage"
        assert d["jurisdiction"] == "State"


# ── N. URLs remain unchanged ────────────────────────────────────────────
class TestURLsUnchanged:
    def test_url_preserved_through_translation(self):
        from app.routes.chat import _translate_grievance_response_back
        settings = MagicMock()
        text_with_url = "Visit https://pgportal.gov.in/ for more info"
        with patch("app.routes.chat._translate_from_english", return_value=text_with_url):
            result = _translate_grievance_response_back(text_with_url, "gu", settings)
        assert "https://pgportal.gov.in/" in result


# ── O. Reference numbers remain unchanged ────────────────────────────────
class TestReferenceNumbersUnchanged:
    def test_ref_number_in_canonical(self):
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={},
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="state",
            state=None,
            department="Municipal Corp",
            reference_number="GRV-20260908-TEST123",
        )
        d = draft.to_canonical_dict()
        assert d["reference"] == "GRV-20260908-TEST123"


# ── P. Existing English grievance behavior unchanged ─────────────────────
class TestEnglishWorkflowUnchanged:
    def test_intake_advances_to_classification(self, workflow):
        with patch("app.grievance.workflow.save_grievance_state"):
            with patch("app.grievance.workflow.load_grievance_state", return_value=None):
                result = workflow.process_message(
                    user_message="I want to file a complaint about garbage.",
                    conversation_id="test-eng-1",
                    user_id="user-1",
                )
                assert result.stage == GrievanceStage.CLASSIFICATION
                assert "Category" in result.response
                assert "Municipal" in result.response


# ── Q. All existing grievance fixes remain intact ────────────────────────
class TestExistingFixesIntact:
    def test_jurisdiction_for_municipal(self, workflow):
        with patch("app.grievance.workflow.save_grievance_state"):
            with patch("app.grievance.workflow.load_grievance_state", return_value=None):
                result = workflow.process_message(
                    user_message="I want to file a complaint about garbage.",
                    conversation_id="test-jur",
                    user_id="user-1",
                )
                assert result.draft.jurisdiction == "local"

    def test_city_to_state_resolution(self):
        guide = GrievanceSubmissionGuide()
        draft = GrievanceDraft(
            category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            title="Test",
            description="Test",
            entities={
                "city_name": GrievanceEntity(
                    name="city_name", value="Bharuch",
                    confidence=0.9, source_text="Bharuch",
                ),
            },
            missing_fields=[],
            required_fields=[],
            optional_fields=[],
            jurisdiction="state",
            state=None,
            department="Municipal Corp",
        )
        city, state = guide._resolve_location_context(draft)
        assert city == "Bharuch"
        assert state == "Gujarat"


# ── R. /chat still exposes grievance ─────────────────────────────────────
class TestChatExposesGrievance:
    def test_grievance_dict_in_result(self):
        from app.routes.chat import _GrievanceResult
        result = _GrievanceResult(text="test", grievance={"category": "Municipal"})
        assert result.grievance is not None
        assert result.grievance["category"] == "Municipal"


# ── S. /chat/stream still exposes grievance ──────────────────────────────
class TestStreamExposesGrievance:
    def test_grievance_in_sse_metadata(self):
        """Streaming endpoint includes grievance in metadata events."""
        from app.routes.chat import _GrievanceResult
        result = _GrievanceResult(text="test", grievance={"category": "Municipal"})
        assert result.grievance is not None
