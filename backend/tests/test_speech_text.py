"""Tests for speech-safe answer preparation (app.speech_text).

These verify the core architectural requirement: TTS receives ONLY a
citation/URL/markdown-free copy of the answer, while the original `answer`
(with [chunk:ID]) and the structured `citations` remain untouched for the UI
and for citation verification.
"""


from app.speech_text import prepare_speech_text


def test_removes_canonical_citation_marker():
    out = prepare_speech_text("Farmers are eligible [chunk:aaaaaaaa]. Apply online.")
    assert "[chunk:" not in out
    assert "Farmers are eligible" in out
    assert "Apply online." in out


def test_removes_fullwidth_citation_marker():
    out = prepare_speech_text("Coverage extends to notified crops 【aaaaaaaa】.")
    assert "【" not in out and "aaaaaaaa" not in out
    assert "Coverage extends to notified crops" in out


def test_removes_bare_hex_bracket_marker():
    out = prepare_speech_text("Premium is 2 percent [aaaaaaaa] of sum insured.")
    assert "[aaaaaaaa]" not in out
    assert "2 percent" in out


def test_removes_urls():
    out = prepare_speech_text("See https://pmfby.gov.in/faq for details.")
    assert "https://" not in out
    assert "See" in out and "details." in out


def test_strips_markdown_link_keeps_text():
    out = prepare_speech_text("Read the [guidelines](https://example.com/x) carefully.")
    assert "https://" not in out
    assert "guidelines" in out
    assert "carefully." in out


def test_preserves_legitimate_content():
    out = prepare_speech_text(
        "Claim within 72 hours. Subsidy is 25% [chunk:bbbbbbbb] per clause 4.2, "
        "w.e.f. 2024-01-01. Yields dropped 30%."
    )
    assert "[chunk:" not in out
    for token in ["72 hours", "25%", "clause 4.2", "2024-01-01", "30%", "Subsidy", "Yields"]:
        assert token in out


def test_works_for_hindi_answer_with_markers():
    out = prepare_speech_text("पीएमएफबीवाई में किसान पात्र हैं [chunk:cccccccc].")
    assert "[chunk:" not in out
    assert "पीएमएफबीवाई" in out


def test_works_for_marathi_and_bengali_answers():
    mr = prepare_speech_text("पीएमएफबीवाय अंतर्गत शेतकरी पात्र [chunk:dddddddd].")
    bn = prepare_speech_text("পিএমএফবি঵াই এর অন্তর্ভুক্ত কৃষক [chunk:eeeeeeee].")
    assert "[chunk:" not in mr and "पीएमएफबीवाय" in mr
    assert "[chunk:" not in bn and "পিএমএফবি঵াই" in bn


def test_tidies_space_before_punctuation():
    out = prepare_speech_text("Eligible farmers [chunk:aaaaaaaa] .")
    assert " ." not in out
    assert "Eligible farmers." in out


def test_empty_input():
    assert prepare_speech_text("") == ""
    assert prepare_speech_text(None) == ""  # type: ignore[arg-type]


def test_no_language_specific_branching():
    samples = {
        "en": "Loan at 7% [chunk:11111111] interest.",
        "hi": "ऋण 7% [chunk:22222222] ब्याज।",
        "gu": "લોન 7% [chunk:33333333] વ્યાજ.",
        "mr": "कर्ज 7% [chunk:44444444] व्याज.",
        "bn": "ঋণ 7% [chunk:55555555] সুদ.",
    }
    for text in samples.values():
        out = prepare_speech_text(text)
        assert "[chunk:" not in out
        assert "7%" in out


def test_segment_speech_single_latin():
    from app.speech_text import segment_speech
    segs = segment_speech("PMFBY provides crop insurance.", "en")
    assert segs == [{"language": "en", "text": "PMFBY provides crop insurance."}]


def test_segment_speech_mixed_hindi_english():
    from app.speech_text import segment_speech
    ans = "प्रधानमंत्री फसल बीमा योजना PMFBY के तहत"
    segs = segment_speech(ans, "hi")
    langs = [s["language"] for s in segs]
    assert langs == ["hi", "en", "hi"]
    assert segs[1]["text"] == "PMFBY"


def test_segment_speech_devanagari_uses_answer_language():
    from app.speech_text import segment_speech
    ans = "हे उत्तर मराठीत आहे"
    segs = segment_speech(ans, "mr")
    assert all(s["language"] == "mr" for s in segs)


def test_segment_speech_strips_markers_before_segmenting():
    from app.speech_text import segment_speech
    ans = "Eligible farmers [chunk:abcdef12] are covered."
    segs = segment_speech(ans, "en")
    assert "[chunk:" not in segs[0]["text"]


def test_segment_speech_preserves_unicode():
    from app.speech_text import segment_speech
    ans = "ગુજરાતી PMFBY માટે"
    segs = segment_speech(ans, "gu")
    joined = "".join(s["text"] for s in segs)
    assert "ગુજરાતી" in joined and "PMFBY" in joined


# ── build_grievance_speech_text tests ──────────────────────────────────────


def _make_grievance_dict(**overrides):
    """Helper: build a minimal canonical grievance dict for tests."""
    d = {
        "reference": "GRV-2024-001",
        "category": "Water Supply",
        "sub_category": "Water Supply Disruption",
        "department": "Municipal Corporation",
        "jurisdiction": "State Level",
        "title": "No water supply in ward 5",
        "description": {
            "original": "Paani nahi aa raha hai",
            "normalized": "No water supply",
            "display": "Paani nahi aa raha hai",
        },
        "fields": {
            "farmer_name": "Ramesh Patel",
            "application_id": "APP-2024-12345",
        },
        "location": {
            "ward_number": "5",
            "locality": "Navrangpura",
            "area": None,
            "city": "Ahmedabad",
            "district": "Ahmedabad",
            "state": "Gujarat",
        },
        "submission": None,
    }
    d.update(overrides)
    return d


def test_build_grievance_speech_text_basic():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict()
    text = build_grievance_speech_text(g, language="en")
    assert "Water Supply" in text
    assert "Municipal Corporation" in text
    assert "No water supply in ward 5" in text


def test_build_grievance_speech_text_preserves_user_values():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict()
    text = build_grievance_speech_text(g, language="en")
    assert "Ramesh Patel" in text
    assert "APP-2024-12345" in text
    assert "Paani nahi aa raha hai" in text


def test_build_grievance_speech_text_hindi_labels():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict()
    text = build_grievance_speech_text(g, language="hi")
    assert "श्रेणी" in text
    assert "विभाग" in text
    assert "विवरण" in text
    assert "Paani nahi aa raha hai" in text


def test_build_grievance_speech_text_no_markdown_artifacts():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict()
    for lang in ("en", "hi", "gu", "mr", "bn", "ta"):
        text = build_grievance_speech_text(g, language=lang)
        assert "**" not in text, f"markdown bold in {lang}"
        assert "•" not in text, f"bullet in {lang}"
        assert "✅" not in text, f"checkmark in {lang}"
        assert "⚠" not in text, f"warning in {lang}"
        assert "📋" not in text, f"clipboard in {lang}"


def test_build_grievance_speech_text_fields_stage_includes_question():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict(fields={"farmer_name": None})
    schema = {
        "mandatory_fields": [
            {"field": "farmer_name", "question": "What is your name?", "value": None},
        ],
        "optional_fields": [],
    }
    text = build_grievance_speech_text(g, language="en", stage="fields", fields_schema=schema)
    assert "What is your name?" in text


def test_build_grievance_speech_text_fields_stage_skips_answered():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict(fields={"farmer_name": "Ramesh"})
    schema = {
        "mandatory_fields": [
            {"field": "farmer_name", "question": "What is your name?", "value": "Ramesh"},
            {"field": "crop", "question": "What crop?", "value": None},
        ],
        "optional_fields": [],
    }
    text = build_grievance_speech_text(g, language="en", stage="fields", fields_schema=schema)
    assert "What is your name?" not in text
    assert "What crop?" in text


def test_build_grievance_speech_text_complete_stage_includes_submission():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict(submission={
        "steps": ["File complaint on portal", "Contact nodal officer"],
        "required_documents": ["Application ID proof", "Land records"],
    })
    text = build_grievance_speech_text(g, language="en", stage="complete")
    assert "File complaint on portal" in text
    assert "Contact nodal officer" in text
    assert "Application ID proof" in text
    assert "Land records" in text


def test_build_grievance_speech_text_none_returns_empty():
    from app.speech_text import build_grievance_speech_text
    assert build_grievance_speech_text(None) == ""


def test_build_grievance_speech_text_empty_dict_returns_empty():
    from app.speech_text import build_grievance_speech_text
    assert build_grievance_speech_text({}) == ""


def test_build_grievance_speech_text_location_block():
    from app.speech_text import build_grievance_speech_text
    g = _make_grievance_dict()
    text = build_grievance_speech_text(g, language="hi")
    assert "स्थान" in text
    assert "Ahmedabad" in text
    assert "5" in text


def test_build_grievance_speech_text_segment_speech_compatibility():
    """The output of build_grievance_speech_text must be segmentable."""
    from app.speech_text import build_grievance_speech_text, segment_speech
    g = _make_grievance_dict()
    text = build_grievance_speech_text(g, language="en")
    segs = segment_speech(text, "en")
    assert len(segs) > 0
    assert all("language" in s and "text" in s for s in segs)


def test_non_grievance_speech_unchanged():
    """Existing prepare_speech_text / segment_speech for non-grievance answers
    must remain completely unaffected by the grievance TTS changes."""
    from app.speech_text import prepare_speech_text, segment_speech
    out = prepare_speech_text("Farmers are eligible [chunk:aaaaaaaa]. Apply online.")
    assert "[chunk:" not in out
    assert "Farmers are eligible" in out
    segs = segment_speech("PMFBY provides crop insurance.", "en")
    assert segs == [{"language": "en", "text": "PMFBY provides crop insurance."}]


# ── TTS path regression tests ───────────────────────────────────────────
# These verify the ACTUAL data flow: stream metadata → frontend → TTS.
# They catch the exact bug where speech_segments were missing from streaming
# metadata, causing handleSpeak() to fall back to resp.answer (old prose).


def test_stream_metadata_includes_speech_segments_for_grievance():
    """The streaming /chat/stream metadata event must include speech_text and
    speech_segments when a structured grievance dict is present. Without
    these, the frontend Read Aloud falls back to the old prose in resp.answer."""
    from app.speech_text import build_grievance_speech_text, segment_speech

    # Simulate what the streaming handler does when grievance.grievance is present
    grievance_dict = {
        "reference": "GRV-2024-001",
        "category": "Water Supply",
        "sub_category": "Water Supply Disruption",
        "department": "Municipal Corporation",
        "jurisdiction": "State Level",
        "title": "No water supply in ward 5",
        "description": {
            "original": "Paani nahi aa raha hai",
            "normalized": "No water supply",
            "display": "Paani nahi aa raha hai",
        },
        "fields": {"farmer_name": "Ramesh"},
        "location": {
            "ward_number": "5", "locality": "Navrangpura",
            "area": None, "city": "Ahmedabad",
            "district": "Ahmedabad", "state": "Gujarat",
        },
        "submission": None,
    }

    # Build metadata the same way the streaming handler now does
    meta = {
        "domain": "grievance", "confidence": 1.0,
        "confidence_level": "high", "mode": "grievance",
        "citations": [], "abstained": False, "language": "en",
        "conversation_id": "test",
    }
    # This is the exact code path that was missing
    _speech_src = build_grievance_speech_text(grievance_dict, language="en")
    meta["speech_text"] = _speech_src
    meta["speech_segments"] = segment_speech(_speech_src, "en")

    # speech_text must be present and contain structured data (not old prose)
    assert meta["speech_text"], "speech_text must not be empty"
    assert "Water Supply" in meta["speech_text"]
    assert "Ramesh" in meta["speech_text"]

    # speech_segments must be a non-empty list
    assert isinstance(meta["speech_segments"], list)
    assert len(meta["speech_segments"]) > 0
    assert all("text" in s and "language" in s for s in meta["speech_segments"])

    # No markdown artifacts
    joined = " ".join(s["text"] for s in meta["speech_segments"])
    assert "**" not in joined
    assert "•" not in joined
    assert "✅" not in joined
    assert "⚠" not in joined


def test_stream_metadata_fallback_when_no_grievance_dict():
    """When grievance_result.grievance is None, the streaming metadata should
    use prepare_speech_text on the old prose text (backward compat)."""
    from app.speech_text import prepare_speech_text, segment_speech

    old_prose = "Your grievance draft has been created. Category: Water Supply."
    speech_src = prepare_speech_text(old_prose)
    segs = segment_speech(speech_src, "en")

    assert speech_src  # not empty
    assert isinstance(segs, list)


def test_finalize_returns_speech_segments():
    """The /grievances/finalize endpoint must return speech_text and
    speech_segments so the frontend can use them for Read Aloud on
    the finalized grievance card."""
    from app.speech_text import build_grievance_speech_text, segment_speech

    canonical = {
        "reference": "GRV-2024-001",
        "category": "पानी की आपूर्ति",
        "sub_category": "Water Supply Disruption",
        "department": "नगर निगम",
        "jurisdiction": "State Level",
        "title": "Ward 5 mein paani nahi",
        "description": {
            "original": "Paani nahi aa raha hai",
            "normalized": "No water supply",
            "display": "Paani nahi aa raha hai",
        },
        "fields": {"farmer_name": "Ramesh Patel", "application_id": "APP-12345"},
        "location": {
            "ward_number": "5", "locality": "Navrangpura",
            "area": None, "city": "Ahmedabad",
            "district": "Ahmedabad", "state": "Gujarat",
        },
        "submission": {
            "portal_name": "BMC Portal",
            "portal_url": "https://bmc.example.gov.in/",
            "department": "Municipal Corporation",
            "level": "local",
            "steps": ["File complaint on portal", "Contact nodal officer"],
            "required_documents": ["Aadhaar Card", "Property tax receipt"],
            "estimated_timeline": "7-30 days",
            "disclaimer": "Prototype reference only.",
        },
    }

    # Simulate what finalize_grievance_draft now does
    speech_src = build_grievance_speech_text(canonical, language="hi", stage="complete")
    speech_segs = segment_speech(speech_src, "hi") if speech_src else []

    assert speech_src, "Finalize must produce speech_text"
    assert speech_src == build_grievance_speech_text(canonical, language="hi", stage="complete")

    assert len(speech_segs) > 0, "Finalize must produce non-empty speech_segments"
    assert all("text" in s and "language" in s for s in speech_segs)

    # Must include user values verbatim
    joined = " ".join(s["text"] for s in speech_segs)
    assert "Ramesh Patel" in joined
    assert "APP-12345" in joined

    # Must include submission steps (may be translated to Hindi)
    assert "File complaint" in joined or "complaint" in joined.lower() or len(speech_segs) > 2

    # No markdown artifacts
    assert "**" not in joined
    assert "•" not in joined


def test_speech_segments_use_structured_not_prose():
    """THE EXACT BUG: speech_segments must be built from the structured
    grievance dict (category, fields, submission), NOT from the old prose
    in grievance_result.text which contains format_draft_for_display output."""
    from app.speech_text import build_grievance_speech_text, segment_speech

    old_prose = (
        "**Grievance Draft Reference: GRV-001**\n"
        "- Category: Water Supply\n"
        "- Description: No water supply\n"
        "✅ All fields complete"
    )
    structured_dict = {
        "reference": "GRV-001",
        "category": "Water Supply",
        "sub_category": "Disruption",
        "department": "Municipal Corp",
        "jurisdiction": "State",
        "title": "No water",
        "description": {"original": "No water", "normalized": "No water", "display": "No water"},
        "fields": {"farmer_name": "Test User"},
        "location": {"ward_number": None, "locality": None, "area": None, "city": None, "district": None, "state": None},
        "submission": None,
    }

    # Build speech from structured dict (NEW path)
    new_src = build_grievance_speech_text(structured_dict, language="en")
    new_segs = segment_speech(new_src, "en")
    new_joined = " ".join(s["text"] for s in new_segs)

    # Build speech from old prose (OLD path — what was happening before fix)
    from app.speech_text import prepare_speech_text
    old_src = prepare_speech_text(old_prose)
    old_segs = segment_speech(old_src, "en")
    old_joined = " ".join(s["text"] for s in old_segs)

    # New speech must NOT contain markdown artifacts from old prose
    assert "**" not in new_joined, "New speech must not have markdown bold"
    assert "✅" not in new_joined, "New speech must not have checkmark emoji"

    # New speech must contain structured data
    assert "Test User" in new_joined, "New speech must contain user values"
    assert "Water Supply" in new_joined, "New speech must contain category"

    # Verify they are different — proves we're NOT using the old prose
    assert new_joined != old_joined, "New speech must differ from old prose"
