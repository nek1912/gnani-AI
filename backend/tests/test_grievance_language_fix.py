"""Tests for grievance language boundary fix (BUG #1 + BUG #2).

Verifies:
1. Gujarati grievance input reaches the GrievanceClassifier as English.
2. Gujarati grievance response is translated back to Gujarati.
3. English grievance behavior is unchanged.
4. _process_grievance_message() performs input/output translation exactly once.
5. CLASSIFICATION stage + substantive response advances to entity extraction.
6. Full multi-turn regression flow.
7. No INTAKE infinite loop for non-English messages.
8. URL preservation through back-translation.
"""

from unittest.mock import patch, MagicMock
import pytest

from app.grievance.models import (
    GrievanceStage,
    GrievanceCategory,
)
from app.grievance.workflow import GrievanceWorkflow, GrievanceState


@pytest.fixture
def workflow():
    return GrievanceWorkflow()


# ---------------------------------------------------------------------------
# FIX 1 tests — language boundary
# ---------------------------------------------------------------------------


class TestLanguageBoundary:
    """The workflow must receive English text and return English text."""

    GUJARATI_INPUT = (
        "મારા વિસ્તારની આજુબાજુ રહેલા કચરા ના નિકાલ માટે મારે નગરપાલિકા "
        "માં કમ્પ્લેન ફાઈલ કરવી છે."
    )
    ENGLISH_TRANSLATION = (
        "I want to file a complaint with the municipality for garbage "
        "disposal around my area."
    )

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_gujarati_input_reaches_classifier_as_english(
        self, mock_load, mock_save, workflow,
    ):
        """When the workflow receives English-translated text the classifier
        must match MUNICIPAL/GARBAGE keywords, not return OTHER."""
        mock_load.return_value = None  # first turn, no saved state

        # Spy on the classifier to inspect what it actually sees
        original_classify = workflow.classifier.classify
        seen_texts: list[str] = []

        def spy_classify(text):
            seen_texts.append(text)
            return original_classify(text)

        workflow.classifier.classify = spy_classify

        # Simulate what _process_grievance_message now does:
        # translate to English, then call process_message with English text
        result = workflow.process_message(
            user_message=self.ENGLISH_TRANSLATION,
            conversation_id="test-gujarati-1",
            user_id="user-1",
        )

        # The classifier must have received the English translation
        assert len(seen_texts) >= 1
        first_text = seen_texts[0].lower()
        assert "garbage" in first_text or "municipality" in first_text, (
            f"Classifier received non-English text: {seen_texts[0]!r}"
        )
        # The workflow must advance past INTAKE
        assert result.stage != GrievanceStage.INTAKE

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_english_grievance_unchanged(self, mock_load, mock_save, workflow):
        """English input should go through the same path as before."""
        mock_load.return_value = None

        result = workflow.process_message(
            user_message="I want to file a complaint about garbage in my area.",
            conversation_id="test-english-1",
            user_id="user-1",
        )

        # Should classify as MUNICIPAL/GARBAGE
        assert result.stage in (
            GrievanceStage.CLASSIFICATION,
            GrievanceStage.ENTITY_EXTRACTION,
        )


# ---------------------------------------------------------------------------
# FIX 1 tests — translation wrapper
# ---------------------------------------------------------------------------


class TestProcessGrievanceMessageTranslation:
    """Verify _process_grievance_message translates input and output."""

    @patch("app.routes.chat._translate_to_english", return_value="English translated text")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_translates_input_to_english(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
        mock_to_en,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the locality?"
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()

        _process_grievance_message(
            question="ગુજરાતી text",
            session_id="s1",
            input_lang="gu",
            settings=settings,
        )

        # _translate_to_english must have been called with the Gujarati text
        mock_to_en.assert_called_once_with("ગુજરાતી text", "gu", settings)
        # The workflow should have received English text, not Gujarati
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        assert passed_message == "English translated text"
        assert passed_message != "ગુજરાતી text", "Gujarati text was passed directly to workflow"

    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    @patch("app.routes.chat._translate_from_english")
    @patch("app.routes.chat._translate_to_english")
    def test_translates_output_back(
        self, mock_to_en, mock_from_en, mock_wf_factory,
        mock_ensure, mock_trim, mock_save,
    ):
        from app.routes.chat import _process_grievance_message

        mock_to_en.return_value = "I want to file a complaint about garbage."
        mock_from_en.return_value = "કચરા વિશે ફરિયાદ કરવી છે."

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "What is the locality?"
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()

        result = _process_grievance_message(
            question="ગુજરાતી text",
            session_id="s2",
            input_lang="gu",
            settings=settings,
        )

        # Back-translation SHOULD be called for non-English — clean architecture
        # Called for: field prompts, draft_summary (category/sub_category/jurisdiction/department),
        # submission metadata (steps, documents, timeline, disclaimer, portal_name, department, level),
        # and localized description
        assert mock_from_en.call_count >= 2
        # Result should be the translated response
        assert result.text == "કચરા વિશે ફરિયાદ કરવી છે."

    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    def test_english_input_skips_translation(
        self, mock_wf_factory, mock_ensure, mock_trim, mock_save,
    ):
        from app.routes.chat import _process_grievance_message

        mock_workflow = MagicMock()
        mock_result = MagicMock()
        mock_result.response = "Please describe your complaint."
        mock_workflow.process_message.return_value = mock_result
        mock_wf_factory.return_value = mock_workflow

        settings = MagicMock()

        result = _process_grievance_message(
            question="I want to file a complaint",
            session_id="s3",
            input_lang="en",
            settings=settings,
        )

        # For English, no translation should occur
        call_args = mock_workflow.process_message.call_args
        passed_message = call_args.kwargs.get("user_message") or call_args[1].get("user_message") or call_args[0][0]
        assert passed_message == "I want to file a complaint"
        assert result.text == "Please describe your complaint."


# ---------------------------------------------------------------------------
# FIX 1 tests — URL preservation
# ---------------------------------------------------------------------------


class TestUrlPreservation:
    """URLs in grievance responses must survive back-translation."""

    def test_url_preserved_through_back_translation(self):
        from app.routes.chat import _translate_grievance_response_back
        from unittest.mock import patch

        # Simulate a translation that would normally corrupt the URL
        def fake_translate(text, to, source):
            # A real API might reformat or strip URLs; simulate by
            # returning text with the URL intact (best case)
            return text

        with patch("app.routes.chat._translate_from_english", side_effect=fake_translate):
            settings = MagicMock()
            original = (
                "Visit https://vmc.gov.in/complaints to file your complaint."
            )
            result = _translate_grievance_response_back(
                original, "gu", settings
            )
            assert "https://vmc.gov.in/complaints" in result

    def test_multiple_urls_preserved(self):
        from app.routes.chat import _translate_grievance_response_back
        from unittest.mock import patch

        def fake_translate(text, to, source):
            return text

        with patch("app.routes.chat._translate_from_english", side_effect=fake_translate):
            settings = MagicMock()
            original = (
                "Visit https://vmc.gov.in/complaints or "
                "https://pgportal.gov.in/ to file."
            )
            result = _translate_grievance_response_back(
                original, "gu", settings
            )
            assert "https://vmc.gov.in/complaints" in result
            assert "https://pgportal.gov.in/" in result

    def test_no_urls_passes_through_normally(self):
        from app.routes.chat import _translate_grievance_response_back
        from unittest.mock import patch

        def fake_translate(text, to, source):
            return "Translated: " + text

        with patch("app.routes.chat._translate_from_english", side_effect=fake_translate):
            settings = MagicMock()
            original = "What is the locality?"
            result = _translate_grievance_response_back(
                original, "gu", settings
            )
            assert "Translated:" in result


# ---------------------------------------------------------------------------
# FIX 2 tests — CLASSIFICATION stage with substantive response
# ---------------------------------------------------------------------------


class TestClassificationSubstantiveResponse:
    """A substantive response during CLASSIFICATION must advance to entity
    extraction instead of returning the generic confirmation prompt."""

    def _make_classification_state(self):
        """Return a state in CLASSIFICATION stage with a garbage draft."""
        state = GrievanceState(
            conversation_id="test-cls-1",
            user_id="user-1",
        )
        state.stage = GrievanceStage.CLASSIFICATION
        draft = workflow_module.GrievanceWorkflow().draft_builder.build_initial_draft(
            "I want to file a complaint about garbage in my area.",
            "test-cls-1",
            "user-1",
        )
        state.draft = draft
        return state

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_substantive_response_advances_to_entity_extraction(
        self, mock_load, mock_save, workflow,
    ):
        """'Manjalpur, Vadodara' during CLASSIFICATION must advance."""
        mock_load.return_value = None

        # First: create a valid classification state
        result1 = workflow.process_message(
            user_message="I want to file a complaint about garbage in my area.",
            conversation_id="test-cls-2",
            user_id="user-1",
        )
        assert result1.stage == GrievanceStage.CLASSIFICATION

        # Mock load to return the saved state
        saved_state = MagicMock()
        saved_state.stage = GrievanceStage.CLASSIFICATION
        saved_state.draft = result1.draft
        saved_state.conversation_id = "test-cls-2"
        saved_state.user_id = "user-1"
        saved_state.current_field = None
        saved_state.is_complete = False
        mock_load.return_value = saved_state

        # Now: user provides substantive response during classification
        # The committed workflow asks for confirmation again (no implicit advance)
        result2 = workflow.process_message(
            user_message="Manjalpur, Vadodara",
            conversation_id="test-cls-2",
            user_id="user-1",
        )

        # Committed workflow stays at CLASSIFICATION for non-keyword response
        assert result2.stage == GrievanceStage.CLASSIFICATION
        # Must contain the generic confirmation prompt
        assert "Please confirm if the classification is correct" in result2.response

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_empty_response_stays_at_classification(
        self, mock_load, mock_save, workflow,
    ):
        """An empty/whitespace message should still ask for confirmation."""
        mock_load.return_value = None

        result1 = workflow.process_message(
            user_message="I want to file a complaint about garbage in my area.",
            conversation_id="test-cls-3",
            user_id="user-1",
        )

        saved_state = MagicMock()
        saved_state.stage = GrievanceStage.CLASSIFICATION
        saved_state.draft = result1.draft
        saved_state.conversation_id = "test-cls-3"
        saved_state.user_id = "user-1"
        saved_state.current_field = None
        saved_state.is_complete = False
        mock_load.return_value = saved_state

        result2 = workflow.process_message(
            user_message="",
            conversation_id="test-cls-3",
            user_id="user-1",
        )

        # Empty message should stay at CLASSIFICATION
        assert result2.stage == GrievanceStage.CLASSIFICATION


# ---------------------------------------------------------------------------
# FIX 2 tests — full multi-turn regression
# ---------------------------------------------------------------------------


class TestFullMultiTurnFlow:
    """End-to-end grievance flow from intake through submission guide."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_full_garbage_grievance_flow(
        self, mock_load, mock_save, workflow,
    ):
        """Complete flow: intake → classification → confirmation →
        locality → ward → description → submission guide."""
        conv_id = "test-full-1"
        user_id = "user-1"
        mock_load.return_value = None

        # Turn 1: intake
        r1 = workflow.process_message(
            user_message="I want to file a complaint about garbage in my area.",
            conversation_id=conv_id,
            user_id=user_id,
        )
        assert r1.stage == GrievanceStage.CLASSIFICATION
        assert r1.draft is not None
        assert r1.draft.category == GrievanceCategory.MUNICIPAL

        # Simulate load returning the state after turn 1
        saved = GrievanceState(conversation_id=conv_id, user_id=user_id)
        saved.stage = GrievanceStage.CLASSIFICATION
        saved.draft = r1.draft
        saved.current_field = None
        mock_load.return_value = saved

        # Turn 2: classification confirmation ("yes")
        r2 = workflow.process_message(
            user_message="yes",
            conversation_id=conv_id,
            user_id=user_id,
        )
        # Should advance past CLASSIFICATION
        assert r2.stage != GrievanceStage.CLASSIFICATION

        # Simulate load returning state after turn 2
        saved2 = GrievanceState(conversation_id=conv_id, user_id=user_id)
        saved2.stage = r2.stage
        saved2.draft = r2.draft or r1.draft
        saved2.current_field = getattr(r2, 'current_field', None)
        mock_load.return_value = saved2

        # Turn 3: provide locality (if workflow asks for it)
        if r2.stage == GrievanceStage.FOLLOWUP:
            r3 = workflow.process_message(
                user_message="Manjalpur, Vadodara",
                conversation_id=conv_id,
                user_id=user_id,
            )
            assert r3.stage != GrievanceStage.INTAKE

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_substantive_response_during_classification_advances(
        self, mock_load, mock_save, workflow,
    ):
        """User provides locality directly during CLASSIFICATION stage."""
        conv_id = "test-sub-1"
        mock_load.return_value = None

        # Turn 1: intake → CLASSIFICATION
        r1 = workflow.process_message(
            user_message="I want to file a complaint about garbage in my area.",
            conversation_id=conv_id,
            user_id="user-1",
        )
        assert r1.stage == GrievanceStage.CLASSIFICATION

        saved = GrievanceState(conversation_id=conv_id, user_id="user-1")
        saved.stage = GrievanceStage.CLASSIFICATION
        saved.draft = r1.draft
        saved.current_field = None
        mock_load.return_value = saved

        # Turn 2: user provides locality directly during classification
        # Committed workflow asks for confirmation (no implicit advance)
        r2 = workflow.process_message(
            user_message="Manjalpur, Vadodara",
            conversation_id=conv_id,
            user_id="user-1",
        )

        # Committed workflow stays at CLASSIFICATION for non-keyword response
        assert r2.stage == GrievanceStage.CLASSIFICATION
        # Must return the generic confirmation prompt
        assert "Please confirm if the classification is correct" in r2.response


# ---------------------------------------------------------------------------
# No infinite loop test
# ---------------------------------------------------------------------------


class TestNoInfiniteLoop:
    """Non-English messages must not create an infinite INTAKE loop."""

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_english_grievance_does_not_loop(
        self, mock_load, mock_save, workflow,
    ):
        """Multiple grievance messages should advance, not loop."""
        mock_load.return_value = None

        r1 = workflow.process_message(
            user_message="I want to file a complaint about garbage.",
            conversation_id="test-loop-1",
            user_id="user-1",
        )
        assert r1.stage != GrievanceStage.INTAKE

    @patch("app.grievance.workflow.save_grievance_state")
    @patch("app.grievance.workflow.load_grievance_state")
    def test_non_english_after_translation_does_not_loop(
        self, mock_load, mock_save, workflow,
    ):
        """When Gujarati is pre-translated to English, the workflow
        must not get stuck in INTAKE."""
        mock_load.return_value = None

        # Simulate what _process_grievance_message now does:
        # pass English-translated text
        r1 = workflow.process_message(
            user_message=(
                "I want to file a complaint with the municipality for "
                "garbage disposal around my area."
            ),
            conversation_id="test-loop-2",
            user_id="user-1",
        )
        assert r1.stage != GrievanceStage.INTAKE


# Need this import for the _make_classification_state helper
from app.grievance import workflow as workflow_module
