"""Grievance workflow endpoint — 9-stage multi-turn workflow.

The three endpoints below (`/fields`, `/answer`, `/finalize`) are
additive support for the structured, tab-based Grievance UI. They
read/write the same `GrievanceState`/`GrievanceDraft` objects the
9-stage conversational workflow already uses (via
`load_grievance_state` / `save_grievance_state`), but they do not
call, alter, or bypass any of the classification / extraction /
answer-generation stage handlers. They only (a) describe which
fields exist and what input control they need, and (b) write
already-confirmed field values directly onto the draft.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth import require_auth
from app.config import get_settings
from app.conversation_store import ensure_conversation, get_conversation
from app.grievance.field_detector import GrievanceFieldDetector
from app.grievance.input_types import get_input_type
from app.grievance.language_check import detect_mixed_language
from app.grievance.models import GrievanceEntity, GrievanceStage
from app.grievance.workflow import (
    GrievanceWorkflow,
    load_grievance_state,
    save_grievance_state,
)

router = APIRouter(prefix="/grievances", tags=["grievances"])

_workflow = GrievanceWorkflow()
_field_detector = GrievanceFieldDetector()


def _translate(text: str, target_lang: str) -> str:
    """Best-effort localisation using static map first, then API.

    The static map guarantees correct translations for known grievance
    strings.  API is only a fallback for dynamic/free-form text.
    """
    if not text or target_lang == "en":
        return text

    # 1. Try static map (guaranteed, offline, fast)
    from app.grievance.translations import translate_grievance_string
    result = translate_grievance_string(text, target_lang)
    if result != text:
        return result

    # 2. Fallback: API translation
    try:
        from app.routes.chat import _translate_from_english
        translated = _translate_from_english(text, target_lang, get_settings())
        if translated != text:
            return translated
    except Exception:
        pass

    import logging
    logging.getLogger(__name__).warning(
        "TRANSLATION LEAK in grievance.py: no translation for '%s' (lang=%s)",
        text[:80], target_lang,
    )
    return text


def _translate_list(items: list[str] | None, target_lang: str) -> list[str] | None:
    """Translate a list of English strings (e.g. submission steps, required documents)."""
    if not items or target_lang == "en":
        return items
    return [_translate(item, target_lang) for item in items]


class GrievanceRequest(BaseModel):
    message: str
    conversation_id: str
    # Legacy clients send a locally generated id here; it is ignored —
    # grievance-state ownership always binds to the authenticated sub.
    user_id: str | None = None


def _existing_conversation(conversation_id: str) -> dict | None:
    """Best-effort lookup; None when missing or the DB is unreachable.

    A DB outage must not change offline/test behavior (the stores already
    fail open on DB errors); ownership is enforced whenever the DB answers.
    """
    try:
        return get_conversation(conversation_id)
    except Exception:
        return None


def _require_grievance_owner(state, user_id: str, detail: str) -> None:
    """404 when the grievance state is owned by someone else.

    Ownership model: GrievanceState.user_id must equal the authenticated
    Clerk sub. The 404 detail matches the endpoint's own missing-state
    message so another user's resource existence is never revealed.
    """
    if getattr(state, "user_id", None) != user_id:
        raise HTTPException(status_code=404, detail=detail)


@router.post("")
def handle_grievance(req: GrievanceRequest, authed_user_id: str = Depends(require_auth)) -> dict:
    # Ownership, not just authentication: the conversation being continued
    # must belong to the caller (or be new). req.user_id is never trusted.
    existing = _existing_conversation(req.conversation_id)
    if existing is not None and existing.get("user_id") != authed_user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_conversation(req.conversation_id, authed_user_id)
    result = _workflow.process_message(
        user_message=req.message,
        conversation_id=req.conversation_id,
        user_id=authed_user_id,
    )
    return {
        "status": "ok",
        "response": result.response,
        "stage": result.stage.value if hasattr(result.stage, "value") else str(result.stage),
        "draft": result.draft,
        "is_complete": result.is_complete,
        "submission_route": result.submission_route,
        "evidence": result.evidence,
    }


@router.get("/{reference}")
def get_grievance_status(reference: str) -> dict:
    from app.grievance.status_lookup import GrievanceStatusLookup
    lookup = GrievanceStatusLookup()
    result = lookup.get_status_lookup(reference)
    return {"status": "ok", "result": result}


# ---------------------------------------------------------------------------
# Structured Grievance UI support endpoints (additive)
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/fields")
def get_grievance_fields(conversation_id: str, language: str = "en", user_id: str = Depends(require_auth)) -> dict:
    """Return the mandatory/optional field schema for the draft that is
    already attached to this conversation (created by the normal
    `POST /grievances` detection call), each tagged with the input
    control type (int / date / text) and, where already known, the
    value already extracted from the citizen's free-text complaint.
    """
    state = load_grievance_state(conversation_id)
    if not state or not state.draft:
        raise HTTPException(status_code=404, detail="No grievance draft for this conversation yet")
    _require_grievance_owner(
        state, user_id, "No grievance draft for this conversation yet"
    )

    draft = state.draft
    prompts = _field_detector.get_field_prompts(draft.sub_category)
    field_labels = _field_detector.get_field_labels()

    def _build(field_names: list[str], mandatory: bool) -> list[dict]:
        items = []
        for name in field_names:
            entity = draft.entities.get(name)
            items.append(
                {
                    "field": name,
                    "field_label": _translate(field_labels.get(name, name.replace("_", " ").title()), language),
                    "question": _translate(prompts.get(name, f"Please provide {name.replace('_', ' ')}."), language),
                    "input_type": get_input_type(name),
                    "mandatory": mandatory,
                    "value": entity.value if entity else None,
                }
            )
        return items

    return {
        "status": "ok",
        "category": draft.category.value,
        "sub_category": draft.sub_category.value,
        "mandatory_fields": _build(draft.required_fields, True),
        "optional_fields": _build(draft.optional_fields, False),
    }


class GrievanceAnswerRequest(BaseModel):
    conversation_id: str
    field: str
    value: str


@router.post("/answer")
def submit_grievance_field_answer(req: GrievanceAnswerRequest, user_id: str = Depends(require_auth)) -> dict:
    """Record one confirmed field answer from the tab-based wizard onto
    the draft. Does not re-run classification/extraction — the field
    name and value are already known/confirmed by the user at this
    point.
    """
    state = load_grievance_state(req.conversation_id)
    if not state or not state.draft:
        raise HTTPException(status_code=404, detail="No grievance draft for this conversation yet")
    _require_grievance_owner(
        state, user_id, "No grievance draft for this conversation yet"
    )

    # Reject mutations after finalization
    if state.is_complete:
        raise HTTPException(status_code=409, detail="Grievance already finalized - mutations rejected")

    value = req.value.strip()

    # Validate integer fields
    input_type = get_input_type(req.field)
    if input_type == "int":
        if not value.isdigit():
            raise HTTPException(status_code=422, detail=f"Field '{req.field}' must be a whole number")

    state.draft.entities[req.field] = GrievanceEntity(
        name=req.field, value=value, confidence=1.0, source_text=value,
    )
    if req.field in state.draft.missing_fields:
        state.draft.missing_fields = [f for f in state.draft.missing_fields if f != req.field]
    save_grievance_state(state)
    return {"status": "ok"}


class GrievanceFinalizeRequest(BaseModel):
    conversation_id: str
    language: str = "en"


@router.post("/finalize")
def finalize_grievance_draft(req: GrievanceFinalizeRequest, user_id: str = Depends(require_auth)) -> dict:
    """Build the final read-only draft table: canonical grievance
    object (same shape as the chat-mode `grievance` field, so the
    existing GrievanceCard-style rendering can be reused), plus a
    `mixed_language` flag for the multi-language notice.
    """
    state = load_grievance_state(req.conversation_id)
    if not state or not state.draft:
        raise HTTPException(status_code=404, detail="No grievance draft for this conversation yet")
    _require_grievance_owner(
        state, user_id, "No grievance draft for this conversation yet"
    )

    # Reject if already finalized
    if state.is_complete:
        raise HTTPException(status_code=409, detail="Grievance already finalized")

    draft = state.draft
    # Resolve the submission route once in English — this becomes both the
    # English mirror's submission block AND the basis for the localized
    # display version below.
    submission_route = _workflow.submission_guide.get_submission_route(draft, language="en")

    localized_description = None
    if req.language != "en":
        localized_description = _translate(draft.description, req.language)

    all_values = [draft.original_description or draft.description] + [
        e.value for e in draft.entities.values()
    ]
    mixed_language = detect_mixed_language(*all_values)

    # Build the pure-English mirror BEFORE any translation happens, so the
    # frontend's "Show English draft" toggle (GrievanceCard.tsx reads
    # `grievance.english`) always has a real, untranslated copy to show —
    # matching the same mirror chat-mode grievances get in
    # app/routes/chat.py::_process_grievance_message.
    from app.grievance.models import (
        _normalize_ward, _normalize_city,
        _normalize_locality, _normalize_area,
    )

    def _mirror_alias(entity_keys: list[str]) -> str | None:
        for k in entity_keys:
            e = draft.entities.get(k)
            if e and hasattr(e, "value") and isinstance(e.value, str) and e.value.strip():
                return e.value.strip()
        return None

    raw_city = _mirror_alias(["city", "city_name"]) or ""
    raw_locality = _mirror_alias(["locality", "locality_name"]) or ""
    raw_area = _mirror_alias(["area", "area_name"]) or ""
    raw_ward = _mirror_alias(["ward_number", "ward_name"]) or ""
    mirror_city = _normalize_city(raw_city) if isinstance(raw_city, str) else ""
    mirror_locality = _normalize_locality(raw_locality) if isinstance(raw_locality, str) else ""
    mirror_area = _normalize_area(raw_area) if isinstance(raw_area, str) else ""
    mirror_ward = _normalize_ward(raw_ward) if isinstance(raw_ward, str) else ""
    mirror_district = _mirror_alias(["district"])

    # Build structured fields for the mirror — same exclusion set as
    # models.py to_canonical_dict() so both canonical and english mirror
    # carry identical field data.
    _MIRROR_LOCATION_KEYS = {
        "ward_number", "ward_name", "locality", "locality_name",
        "colony_name", "area", "area_name", "city", "city_name",
        "district", "district_name", "tehsil", "tehsil_name",
        "taluk", "taluk_name", "village", "village_name",
        "block", "block_name", "zone", "sector_name", "location",
    }
    mirror_fields = {
        k: v.value.strip()
        for k, v in draft.entities.items()
        if k not in _MIRROR_LOCATION_KEYS
        and k != "state"
        and v.value
        and v.value.strip()
    }

    english_mirror = {
        "category": draft.category.value.replace("_", " ").title(),
        "sub_category": draft.sub_category.value.replace("_", " ").title(),
        "department": draft.department,
        "jurisdiction": draft.jurisdiction.title(),
        "title": draft.title,
        "description": draft.description,
        "fields": mirror_fields or None,
        "location": {
            "ward_number": mirror_ward or None,
            "locality": mirror_locality or None,
            "area": mirror_area or None,
            "city": mirror_city or None,
            "district": mirror_district,
            "state": draft.state,
        },
        "submission": {
            "portal_name": submission_route.portal_name if submission_route else None,
            "portal_url": submission_route.portal_url if submission_route else None,
            "department": submission_route.department if submission_route else None,
            "level": submission_route.level if submission_route else None,
            "steps": submission_route.steps if submission_route else [],
            "required_documents": submission_route.required_documents if submission_route else [],
            "estimated_timeline": submission_route.estimated_timeline if submission_route else None,
            "disclaimer": submission_route.disclaimer if submission_route else None,
        } if submission_route else None,
    }

    # DISPLAY submission info — localized for the user's language below.
    # portal_url is never translated (must stay a real URL or null).
    s_portal_name = submission_route.portal_name if submission_route else None
    s_portal_url = submission_route.portal_url if submission_route else None
    s_dept = submission_route.department if submission_route else None
    s_level = submission_route.level if submission_route else None
    s_steps = submission_route.steps if submission_route else None
    s_docs = submission_route.required_documents if submission_route else None
    s_timeline = submission_route.estimated_timeline if submission_route else None
    s_disclaimer = submission_route.disclaimer if submission_route else None

    if req.language != "en" and submission_route:
        s_portal_name = _translate(s_portal_name, req.language)
        s_dept = _translate(s_dept, req.language)
        s_level = _translate(s_level, req.language)
        s_steps = _translate_list(s_steps, req.language)
        s_docs = _translate_list(s_docs, req.language)
        s_timeline = _translate(s_timeline, req.language)
        s_disclaimer = _translate(s_disclaimer, req.language)
        # s_portal_url is intentionally never translated — stays a real
        # URL or None.

    canonical = draft.to_canonical_dict(
        portal_name=s_portal_name,
        portal_url=s_portal_url,
        submission_department=s_dept,
        submission_level=s_level,
        submission_steps=s_steps,
        submission_required_documents=s_docs,
        submission_estimated_timeline=s_timeline,
        submission_disclaimer=s_disclaimer,
        localized_description=localized_description,
        english_mirror=english_mirror,
    )

    # Localize the top-level display fields too — the pure-English values
    # are preserved separately in canonical["english"] (the mirror above).
    if req.language != "en":
        canonical["category"] = _translate(canonical["category"], req.language)
        canonical["sub_category"] = _translate(canonical["sub_category"], req.language)
        canonical["department"] = _translate(canonical["department"], req.language)
        canonical["jurisdiction"] = _translate(canonical["jurisdiction"], req.language)
        canonical["title"] = _translate(canonical["title"], req.language)

    # Build speech data from the finalized canonical grievance dict so
    # the frontend Read-Aloud speaks the current structured representation.
    from app.speech_text import build_grievance_speech_text, segment_speech
    speech_src = build_grievance_speech_text(canonical, language=req.language, stage="complete")
    speech_segs = segment_speech(speech_src, req.language) if speech_src else []

    # Mark state as finalized - this is authoritative
    state.is_complete = True
    state.stage = GrievanceStage.COMPLETE
    save_grievance_state(state)

    return {"status": "ok", "grievance": canonical, "mixed_language": mixed_language, "speech_text": speech_src, "speech_segments": speech_segs}


class GrievanceClarifyRequest(BaseModel):
    conversation_id: str
    complaint: str
    language: str = "en"


@router.post("/clarify")
def clarify_grievance(req: GrievanceClarifyRequest, user_id: str = Depends(require_auth)) -> dict:
    """Reclassify a grievance after the citizen provides clarification.

    This replaces the old grievance draft with a fresh one built from
    the new complaint text, then runs the full classification pipeline.
    The citizen must explicitly confirm the new classification before
    the workflow advances to field collection.
    """
    state = load_grievance_state(req.conversation_id)
    if not state:
        raise HTTPException(status_code=404, detail="No grievance state for this conversation")
    _require_grievance_owner(
        state, user_id, "No grievance state for this conversation"
    )

    from app.grievance.classifier import GrievanceClassifier
    from app.grievance.draft_builder import GrievanceDraftBuilder
    from app.grievance.models import GrievanceStage

    classifier = GrievanceClassifier()
    draft_builder = GrievanceDraftBuilder()

    # Build a completely fresh draft from the new complaint text
    new_draft = draft_builder.build_initial_draft(
        req.complaint, state.conversation_id, state.user_id
    )
    state.draft = new_draft
    state.stage = GrievanceStage.CLASSIFICATION
    state.current_field = None
    save_grievance_state(state)

    # Classify the new complaint
    classifier.classify(req.complaint)

    # Build field schema for the new classification
    field_detector = GrievanceFieldDetector()
    prompts = field_detector.get_field_prompts(new_draft.sub_category)
    fld_labels = field_detector.get_field_labels()

    # Translate prompts if needed
    def _translate_label(text: str) -> str:
        if req.language == "en" or not text:
            return text
        try:
            from app.routes.chat import _translate_from_english
            return _translate_from_english(text, req.language, get_settings())
        except Exception:
            return text

    fields_schema = {
        "mandatory_fields": [
            {
                "field": f,
                "field_label": _translate_label(fld_labels.get(f, f.replace("_", " ").title())),
                "question": _translate_label(prompts.get(f, f"Please provide {f.replace('_', ' ')}. ")),
                "input_type": get_input_type(f),
                "mandatory": True,
                "value": new_draft.entities[f].value if f in new_draft.entities else None,
            }
            for f in new_draft.required_fields
        ],
        "optional_fields": [
            {
                "field": f,
                "field_label": _translate_label(fld_labels.get(f, f.replace("_", " ").title())),
                "question": _translate_label(prompts.get(f, f"Please provide {f.replace('_', ' ')}. ")),
                "input_type": get_input_type(f),
                "mandatory": False,
                "value": new_draft.entities[f].value if f in new_draft.entities else None,
            }
            for f in new_draft.optional_fields
        ],
    }

    # Build draft summary for frontend
    draft_summary = {
        "category": new_draft.category.value.replace("_", " ").title(),
        "sub_category": new_draft.sub_category.value.replace("_", " ").title(),
        "jurisdiction": new_draft.jurisdiction.title(),
        "title": new_draft.title,
        "description": new_draft.description,
        "department": new_draft.department,
    }

    # Translate draft summary to user's language
    if req.language != "en":
        draft_summary["category"] = _translate(draft_summary["category"], req.language)
        draft_summary["sub_category"] = _translate(draft_summary["sub_category"], req.language)
        draft_summary["jurisdiction"] = _translate(draft_summary["jurisdiction"], req.language)
        draft_summary["title"] = _translate(draft_summary["title"], req.language)
        draft_summary["description"] = _translate(draft_summary["description"], req.language)
        draft_summary["department"] = _translate(draft_summary["department"], req.language)

    return {
        "status": "ok",
        "stage": "classification",
        "draft_summary": draft_summary,
        "fields_schema": fields_schema,
    }
