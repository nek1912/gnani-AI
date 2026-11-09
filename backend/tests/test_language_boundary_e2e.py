"""E2E integration test — 4-message Gujarati complaint flow.

Proves the clean language-boundary architecture end-to-end:
  1. User sends Gujarati complaint → translated to English → workflow
  2. User confirms classification → translated to English → workflow
  3. User provides ward → translated to English → workflow
  4. User provides area+city → translated to English → workflow → canonical JSON

Verifies:
  - Input translation occurs before workflow
  - Output translation occurs after workflow
  - Canonical JSON has original Gujarati description
  - English workflow sees only English text throughout
  - No translation regressions
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceStage,
    GrievanceSubCategory,
    SubmissionRoute,
)


# ── Mock factory for workflow results ──────────────────────────────────────

def _make_result(
    stage: GrievanceStage,
    response: str,
    draft: GrievanceDraft | None = None,
    submission_route: SubmissionRoute | None = None,
):
    result = MagicMock()
    result.stage = stage
    result.response = response
    result.draft = draft
    result.submission_route = submission_route
    return result


# ── Canonical draft factory ────────────────────────────────────────────────

def _make_draft(
    description: str = "Garbage in my area",
    original_description: str | None = None,
    category: GrievanceCategory = GrievanceCategory.MUNICIPAL,
    sub_category: GrievanceSubCategory = GrievanceSubCategory.GARBAGE,
    ward: str | None = None,
    area: str | None = None,
    city: str | None = None,
    state: str | None = "Gujarat",
):
    entities = {}
    if ward:
        entities["ward_number"] = GrievanceEntity(
            name="ward_number", value=ward, confidence=0.9, source_text=f"ward {ward}",
        )
    if area:
        entities["area_name"] = GrievanceEntity(
            name="area_name", value=area, confidence=0.9, source_text=area,
        )
    if city:
        entities["city_name"] = GrievanceEntity(
            name="city_name", value=city, confidence=0.9, source_text=city,
        )
    return GrievanceDraft(
        category=category,
        sub_category=sub_category,
        title="Garbage complaint",
        description=description,
        entities=entities,
        missing_fields=[],
        required_fields=[],
        optional_fields=[],
        jurisdiction="state",
        state=state,
        department="Municipal Corporation",
        original_description=original_description,
    )


# ── Translation maps for mock ──────────────────────────────────────────────

_GU_TO_EN = {
    "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.": "There is a lot of garbage in my area. Every morning filth spreads.",
    "હા, આ મારી ફરિયાદ છે": "Yes, this is my complaint",
    "ward 12": "ward 12",
    "નવા પાલડી, સુરત": "Nanapaldi, Surat",
}

_EN_TO_GU = {
    "Please confirm if this is your complaint.": "કૃપા કરીને પુષ્ટિ કરો કે આ તમારી ફરિયાદ છે.",
    "Thank you. What is your ward number?": "આભાર. તમારો વોર્ડ નંબર શું છે?",
    "Got ward 12. What is the area name and city?": "વોર્ડ 12 મળ્યો. વિસ્તારનું નામ અને શહેર શું છે?",
    "Complaint draft ready.": "ફરિયાદ ડ્રાફ્ટ તૈયાર છે.",
}


def _mock_translate_to_english(text: str, lang: str, settings) -> str:
    if lang == "gu":
        return _GU_TO_EN.get(text, f"[translated from gu] {text}")
    return text


def _mock_translate_from_english(text: str, lang: str, settings) -> str:
    if lang == "gu":
        # Exact match first, then prefix match for multi-line responses
        if text in _EN_TO_GU:
            return _EN_TO_GU[text]
        for en_key, gu_val in _EN_TO_GU.items():
            if text.startswith(en_key):
                return gu_val
        return f"[translated to gu] {text}"
    return text


# ── Full 4-message E2E flow ────────────────────────────────────────────────

class TestGujaratiComplaintFlowE2E:
    """Simulates a complete Gujarati complaint through all 4 messages."""

    def test_full_flow(self):
        session_id = "e2e-gujarati-flow"
        settings = MagicMock()

        # ── Message 1: User describes complaint in Gujarati ───────────
        with patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat.ensure_conversation"), \
             patch("app.routes.chat._get_grievance_workflow") as mock_wf, \
             patch("app.routes.chat._translate_to_english", side_effect=_mock_translate_to_english), \
             patch("app.routes.chat._translate_from_english", side_effect=_mock_translate_from_english), \
             patch("app.routes.chat._has_active_grievance", return_value=False):

            wf = MagicMock()
            mock_wf.return_value = wf

            # Step 1: complaint → classification prompt
            wf.process_message.return_value = _make_result(
                stage=GrievanceStage.CLASSIFICATION,
                response="Please confirm if this is your complaint.",
                draft=_make_draft(
                    description="Garbage complaint",
                    original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.",
                ),
            )

            from app.routes.chat import _process_grievance_message

            result1 = _process_grievance_message(
                question="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.",
                session_id=session_id,
                input_lang="gu",
                settings=settings,
            )

            # ── Verify message 1 ─────────────────────────────────────
            # A. Input was translated to English
            wf_call_args = wf.process_message.call_args
            passed_message = wf_call_args.kwargs.get("user_message") or wf_call_args[0][0]
            assert passed_message == "There is a lot of garbage in my area. Every morning filth spreads."

            # B. Output was translated to Gujarati
            assert result1.text == "કૃપા કરીને પુષ્ટિ કરો કે આ તમારી ફરિયાદ છે."

            # C. Canonical JSON has original Gujarati description
            assert result1.grievance is not None
            assert result1.grievance["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે."
            assert result1.grievance["description"]["normalized"] == "Garbage complaint"

        # ── Message 2: User confirms classification ───────────────────
        with patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat.ensure_conversation"), \
             patch("app.routes.chat._get_grievance_workflow") as mock_wf, \
             patch("app.routes.chat._translate_to_english", side_effect=_mock_translate_to_english), \
             patch("app.routes.chat._translate_from_english", side_effect=_mock_translate_from_english), \
             patch("app.routes.chat._has_active_grievance", return_value=True):

            wf = MagicMock()
            mock_wf.return_value = wf

            wf.process_message.return_value = _make_result(
                stage=GrievanceStage.MISSING_FIELDS,
                response="Thank you. What is your ward number?",
                draft=_make_draft(
                    description="Garbage complaint",
                    original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.",
                ),
            )

            result2 = _process_grievance_message(
                question="હા, આ મારી ફરિયાદ છે",
                session_id=session_id,
                input_lang="gu",
                settings=settings,
            )

            # Verify workflow received English
            wf_call_args = wf.process_message.call_args
            passed_message = wf_call_args.kwargs.get("user_message") or wf_call_args[0][0]
            assert passed_message == "Yes, this is my complaint"

            # Verify output translated
            assert result2.text == "આભાર. તમારો વોર્ડ નંબર શું છે?"

            # Canonical still has original
            assert result2.grievance["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે."

        # ── Message 3: User provides ward number ──────────────────────
        with patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat.ensure_conversation"), \
             patch("app.routes.chat._get_grievance_workflow") as mock_wf, \
             patch("app.routes.chat._translate_to_english", side_effect=_mock_translate_to_english), \
             patch("app.routes.chat._translate_from_english", side_effect=_mock_translate_from_english), \
             patch("app.routes.chat._has_active_grievance", return_value=True):

            wf = MagicMock()
            mock_wf.return_value = wf

            wf.process_message.return_value = _make_result(
                stage=GrievanceStage.MISSING_FIELDS,
                response="Got ward 12. What is the area name and city?",
                draft=_make_draft(
                    description="Garbage complaint",
                    original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.",
                    ward="12",
                ),
            )

            result3 = _process_grievance_message(
                question="ward 12",
                session_id=session_id,
                input_lang="gu",
                settings=settings,
            )

            # Verify workflow received English (ward 12 is same in both)
            wf_call_args = wf.process_message.call_args
            passed_message = wf_call_args.kwargs.get("user_message") or wf_call_args[0][0]
            assert passed_message == "ward 12"

            # Verify output translated
            assert result3.text == "વોર્ડ 12 મળ્યો. વિસ્તારનું નામ અને શહેર શું છે?"

        # ── Message 4: User provides area + city → draft ready ────────
        with patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat.ensure_conversation"), \
             patch("app.routes.chat._get_grievance_workflow") as mock_wf, \
             patch("app.routes.chat._translate_to_english", side_effect=_mock_translate_to_english), \
             patch("app.routes.chat._translate_from_english", side_effect=_mock_translate_from_english), \
             patch("app.routes.chat._has_active_grievance", return_value=True):

            wf = MagicMock()
            mock_wf.return_value = wf

            submission = SubmissionRoute(
                portal_name="PG Portal",
                portal_url="https://pgportal.gov.in/",
                department="Municipal Corporation",
                level="state",
                steps=["Visit portal", "Fill form", "Submit"],
                required_documents=["Aadhaar", "Photo"],
                estimated_timeline="7 days",
            )

            wf.process_message.return_value = _make_result(
                stage=GrievanceStage.DRAFT_READY,
                response="Complaint draft ready.",
                draft=_make_draft(
                    description="Garbage complaint",
                    original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે.",
                    ward="12",
                    area="નવા પાલડી",
                    city="Surat",
                ),
                submission_route=submission,
            )

            result4 = _process_grievance_message(
                question="નવા પાલડી, સુરત",
                session_id=session_id,
                input_lang="gu",
                settings=settings,
            )

            # Verify workflow received English
            wf_call_args = wf.process_message.call_args
            passed_message = wf_call_args.kwargs.get("user_message") or wf_call_args[0][0]
            assert passed_message == "Nanapaldi, Surat"

            # Verify output translated with URL preserved
            assert result4.text == "ફરિયાદ ડ્રાફ્ટ તૈયાર છે."

            # Verify canonical JSON is complete
            g = result4.grievance
            assert g is not None
            assert g["category"] == "Municipal"
            assert g["sub_category"] == "Garbage"
            assert g["jurisdiction"] == "State"
            assert g["location"]["ward_number"] == "12"
            assert g["location"]["area"] == "નવા પાલડી"
            assert g["location"]["city"] == "Surat"
            assert g["location"]["state"] == "Gujarat"
            assert g["submission"]["portal_name"] == "PG Portal"
            assert g["submission"]["portal_url"] == "https://pgportal.gov.in/"
            assert g["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે. રોજ સવેરે ગંદકી ફેલાય છે."
            assert g["description"]["normalized"] == "Garbage complaint"


# ── URL protection through translation ─────────────────────────────────────

class TestURLProtectionThroughTranslation:
    """Verify URLs survive the translate-back step."""

    def test_url_not_corrupted(self):
        from app.routes.chat import _translate_grievance_response_back
        settings = MagicMock()
        text = "Submit at https://pgportal.gov.in/ or call 1800-180-1551"
        result = _translate_grievance_response_back(text, "gu", settings)
        assert "https://pgportal.gov.in/" in result
        assert "1800-180-1551" in result

    def test_multiple_urls_preserved(self):
        from app.routes.chat import _translate_grievance_response_back
        settings = MagicMock()
        text = "Visit https://pgportal.gov.in/ and https://example.com for info"
        result = _translate_grievance_response_back(text, "gu", settings)
        assert "https://pgportal.gov.in/" in result
        assert "https://example.com" in result


# ── Original description survives full flow ────────────────────────────────

class TestOriginalDescriptionSurvivesFlow:
    """Verify user's original Gujarati text is preserved in canonical JSON."""

    def test_gujarati_preserved_in_canonical(self):
        draft = _make_draft(
            description="Garbage complaint",
            original_description="મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["description"]["original"] == "મારી આસપાસના વિસ્તારમાં ખૂબ જ કચરો છે"

    def test_hindi_preserved_in_canonical(self):
        draft = _make_draft(
            description="Road pothole",
            original_description="मेरे क्षेत्र में सड़क में गड्ढा है",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["description"]["original"] == "मेरे क्षेत्र में सड़क में गड्ढा है"

    def test_bengali_preserved_in_canonical(self):
        draft = _make_draft(
            description="Water supply issue",
            original_description="আমার এলাকায় পানির সরবরাহ সমস্যা",
        )
        canonical = draft.to_canonical_dict()
        assert canonical["description"]["original"] == "আমার এলাকায় পানির সরবরাহ সমস্যা"
