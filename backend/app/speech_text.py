"""Speech-safe text preparation.

The RAG ``answer`` intentionally carries ``[chunk:ID]`` citation markers: they
are required for citation verification (app.citation_verifier) and for the UI
to render source links. But those markers, URLs, and markdown syntax must NEVER
reach a text-to-speech engine — otherwise the assistant reads out chunk IDs and
URLs instead of the answer.

This module produces a speech-only representation of an answer that has ALREADY
passed citation verification. Verification still operates on the original
``answer`` (with markers); only the *speech copy* is cleaned. The same generic
transform is applied to every supported language — there is deliberately no
language-specific branching here.

It also provides ``build_grievance_speech_text`` which derives TTS text from the
canonical structured grievance dict (the same data driving the Table/Card UI)
rather than from the old ``format_draft_for_display`` prose.

Order matters: clean AFTER verification, never before.
"""

from __future__ import annotations

import re

# Canonical half-width markers produced by the LLM / normalised by the verifier.
_CITE = re.compile(r"\[chunk:[0-9a-fA-F]{8,}\]")
# Full-width 【ID】 / 【chunk:ID】 variants the LLM sometimes emits.
_FULLWIDTH_CITE = re.compile(r"【\s*(?:chunk:)?\s*[0-9a-fA-F]{8,}\s*】")
# Bare half-width hex bracket [ID] (missing the `chunk:` prefix).
_BARE_HEX_CITE = re.compile(r"\[\s*[0-9a-fA-F]{8,}\s*\]")
# Markdown links [text](url) — keep the visible text, drop the URL.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((\s*https?://\S+)\)")
# Standalone URLs (never speakable, and the verifier flags fabricated ones).
_URL = re.compile(r"https?://\S+")
# Collapse runs of whitespace and tidy spacing before punctuation.
_WS = re.compile(r"[ \t]{2,}")
_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_MANY_NL = re.compile(r"\n{3,}")


def prepare_speech_text(answer: str) -> str:
    """Return a TTS-safe copy of an already-verified answer.

    Removes citation markers (all recognised variants), markdown link syntax,
    and URLs. Legitimate content — percentages, dates, clause/section numbers,
    scheme names, amounts — is preserved verbatim. The input is expected to have
    already passed citation verification; this function only changes presentation.
    """
    if not answer:
        return ""

    text = _FULLWIDTH_CITE.sub("", answer)
    text = _BARE_HEX_CITE.sub("", text)
    text = _CITE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)

    text = _WS.sub(" ", text)
    text = _BEFORE_PUNCT.sub(r"\1", text)
    text = _MANY_NL.sub("\n\n", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _char_script(ch: str, answer_language: str) -> str | None:
    """Map a character to a language bucket for segmentation.

    Gujarati/Bengali/Latin are script-unique. Devanagari is mapped to the
    *already resolved* answer language (NOT guessed) — this is answer-side only.
    Punctuation/spaces return None (attach to the current run).
    """
    cp = ord(ch)
    if 0x0A80 <= cp <= 0x0AFF:
        return "gu"
    if 0x0980 <= cp <= 0x09FF:
        return "bn"
    if 0x0900 <= cp <= 0x097F:
        return answer_language
    if ch.isascii() and (ch.isalpha() or ch.isdigit()):
        return "en"
    return None


def segment_speech(answer: str, answer_language: str) -> list[dict]:
    """Split a verified answer into language-tagged segments by script run.

    Generic — no per-language hardcoding. Devanagari runs take the resolved
    ``answer_language`` so Hindi/Marathi answers segment correctly. Marker
    envelopes are removed generically before segmenting (never spoken).
    """
    if not answer:
        return []
    answer = prepare_speech_text(answer)
    text = answer
    segments: list[dict] = []
    current_lang: str | None = None
    current_text: list[str] = []
    for ch in text:
        lang = _char_script(ch, answer_language)
        if lang is None:
            if current_lang is not None:
                current_text.append(ch)
            continue
        if lang != current_lang:
            if current_lang is not None:
                seg = "".join(current_text).strip()
                if seg:
                    segments.append({"language": current_lang, "text": seg})
            current_lang = lang
            current_text = [ch]
        else:
            current_text.append(ch)
    if current_lang is not None:
        seg = "".join(current_text).strip()
        if seg:
            segments.append({"language": current_lang, "text": seg})
    return segments


# ── Section-level label translations for grievance TTS ────────────────────
# Localised labels for the top-level canonical grievance dict keys.
# Used by ``build_grievance_speech_text`` to produce speech-friendly text
# that mirrors the Table/Card UI, replacing the old ``format_draft_for_display``
# prose which contained markdown artifacts.
_GRIEVE_SECTION_LABELS: dict[str, dict[str, str]] = {
    "category":       {"en": "Category",      "hi": "श्रेणी",      "gu": "શ્રેણી",     "mr": "श्रेणी",     "bn": "বিভাগ",    "ta": "வகை"},
    "sub_category":   {"en": "Sub-category",   "hi": "उप-श्रेणी",   "gu": "ઉપ-શ્રેણી",  "mr": "उप-श्रेणी",  "bn": "উপ-বিভাগ",  "ta": "துணை வகை"},
    "department":     {"en": "Department",     "hi": "विभाग",       "gu": "વિભાગ",      "mr": "विभाग",      "bn": "বিভাগ",    "ta": "துறை"},
    "jurisdiction":   {"en": "Jurisdiction",   "hi": "क्षेत्राधिकार", "gu": "અધિકારક્ષેત્ર", "mr": "अधिकारक्षेत्र", "bn": "অধিকারক্ষেত্র", "ta": "அதிகார எல்லை"},
    "title":          {"en": "Title",          "hi": "शीर्षक",       "gu": "શીર્ષક",      "mr": "शीर्षक",      "bn": "শিরোনাম",  "ta": "தலைப்பு"},
    "description":    {"en": "Description",    "hi": "विवरण",       "gu": "વર્ણન",      "mr": "वर्णन",      "bn": "বিবরণ",    "ta": "விளக்கம்"},
    "location":       {"en": "Location",       "hi": "स्थान",       "gu": "સ્થળ",       "mr": "स्थान",      "bn": "অবস্থান",  "ta": "இடம்"},
}


def _grievance_label(key: str, lang: str) -> str:
    """Return a localised section label for a grievance dict key."""
    entry = _GRIEVE_SECTION_LABELS.get(key)
    if entry:
        return entry.get(lang, entry.get("en", key))
    return key.replace("_", " ").title()


def build_grievance_speech_text(
    grievance_dict: dict | None,
    language: str = "en",
    stage: str | None = None,
    fields_schema: dict | None = None,
) -> str:
    """Build clean TTS text from the structured grievance representation.

    Produces speech-friendly text from the same canonical ``grievance_dict``
    that drives the Table/Card UI, replacing the old ``format_draft_for_display``
    prose which contained markdown artifacts (**bold**, bullet markers,
    emoji).

    * System-generated labels are localised via ``_GRIEVE_SECTION_LABELS``
      and ``translate_field_label()``.
    * User-entered values (farmer_name, crop, description, etc.) are
      preserved **verbatim** — never translated, truncated, or rewritten.
    * URLs are preserved correctly.
    * No markdown artifacts (``**``, ``•``, ``✅``, ``⚠``, ``📋``) are
      included.
    """
    if not grievance_dict:
        return ""

    lang = language or "en"
    lines: list[str] = []

    def _add(key: str, value: str | None) -> None:
        if value and str(value).strip():
            lines.append(f"{_grievance_label(key, lang)}: {value}")

    _add("category", grievance_dict.get("category"))
    _add("sub_category", grievance_dict.get("sub_category"))
    _add("department", grievance_dict.get("department"))
    _add("jurisdiction", grievance_dict.get("jurisdiction"))
    _add("title", grievance_dict.get("title"))

    # description may be a dict {original, normalized, display} or a string
    desc = grievance_dict.get("description")
    if isinstance(desc, dict):
        desc_text = desc.get("display") or desc.get("original") or desc.get("normalized")
    else:
        desc_text = desc
    _add("description", desc_text)

    # Structured fields — user-entered key/value pairs
    fields = grievance_dict.get("fields")
    if fields:
        from app.grievance.translations import translate_field_label
        for key, value in fields.items():
            if value and str(value).strip():
                label = translate_field_label(key, lang)
                lines.append(f"{label}: {value}")

    # Location block
    loc = grievance_dict.get("location")
    if loc:
        loc_parts: list[str] = []
        for loc_key in ("ward_number", "locality", "area", "city", "district", "state"):
            val = loc.get(loc_key)
            if val and str(val).strip():
                loc_parts.append(str(val).strip())
        if loc_parts:
            lines.append(f"{_grievance_label('location', lang)}: {', '.join(loc_parts)}")

    # Fields-stage follow-up question
    if stage == "fields" and fields_schema:
        mandatory = fields_schema.get("mandatory_fields") or []
        for field in mandatory:
            q = field.get("question")
            if q and not field.get("value"):
                lines.append(str(q))
                break

    # Complete-stage submission steps
    if stage == "complete":
        submission = grievance_dict.get("submission")
        if submission:
            steps = submission.get("steps") or []
            for step in steps:
                lines.append(str(step))
            docs = submission.get("required_documents") or []
            if docs:
                for doc in docs:
                    lines.append(str(doc))

    return "\n".join(lines)
