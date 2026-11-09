"""Voice I/O route — Sarvam (primary) → Azure (fallback) → text-only.

The voice route is a thin adapter around the same RAG pipeline used by /chat.
It does NOT duplicate retrieval, generation, or evidence gating logic.

STT/TTS are delegated to the voice_service layer (app.services.voice_service),
which owns the provider fallback chain (Azure → Sarvam → unavailable). The route
only adapts HTTP I/O and error policy.
"""
import base64
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel

from app.auth import require_auth
from app.routes.chat import chat as chat_handler
from app.routes.chat import ChatRequest
from app.services.voice_service import VoiceService, VoiceUnavailableError

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

voice_service = VoiceService()


class TranscribeRequest(BaseModel):
    audio: str
    language: str = "en"


class SpeakRequest(BaseModel):
    text: str = ""
    language: str = "en"
    segments: list["SpeechSegment"] | None = None


class SpeechSegment(BaseModel):
    text: str
    language: str


class VoiceChatRequest(BaseModel):
    audio: str
    language: str = "en-IN"
    session_id: str = ""
    state: str | None = None


def _lang_short(lang: str) -> str:
    """'hi-IN' → 'hi', 'en-IN' → 'en'."""
    return lang.split("-")[0] if "-" in lang else lang


@router.post("/transcribe")
async def transcribe_audio(req: TranscribeRequest, authed_user_id: str = Depends(require_auth)) -> dict:
    """STT: Convert uploaded audio (base64) to text.

    This is a pure STT endpoint — no RAG, no generation.
    Delegates to the voice_service provider fallback chain.
    Requires Clerk auth (AGENTS.md contract) so anonymous callers
    cannot burn STT/TTS provider quota.
    """
    if not req.audio or not req.audio.strip():
        return {"text": "", "language": req.language}

    try:
        audio_bytes = base64.b64decode(req.audio)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 audio payload") from exc

    try:
        text = await voice_service.speech_to_text(audio_bytes, req.language)
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"text": text, "language": req.language}


@router.post("/speak")
async def speak_text(req: SpeakRequest, authed_user_id: str = Depends(require_auth)) -> dict:
    """TTS: Convert text to speech audio (hex-encoded bytes).

    This is a pure TTS endpoint — no RAG, no generation.
    Delegates to the voice_service provider fallback chain.
    Requires Clerk auth (AGENTS.md contract) so anonymous callers
    cannot burn STT/TTS provider quota.
    """
    try:
        if req.segments:
            audio_bytes = await voice_service.text_to_speech_segments(
                [s.model_dump() for s in req.segments]
            )
            language = req.segments[0].language
        else:
            audio_bytes = await voice_service.text_to_speech(req.text, req.language)
            language = req.language
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"audio": audio_bytes.hex(), "language": language}


@router.post("")
async def voice_chat(
    audio: UploadFile = File(...),  # noqa: B008
    language: str = Form(default="hi"),
    session_id: str = Form(default=""),
    state: str | None = Form(default=None),
    user_id: str = Depends(require_auth),
) -> dict:
    """Full voice pipeline: audio → STT → RAG → TTS → audio.

    One RAG core (same as /chat), no separate voice RAG.
    Pipeline: STT (voice_service) → chat handler → TTS (voice_service)
    """
    audio_bytes = await audio.read()
    try:
        transcribed = await voice_service.speech_to_text(audio_bytes, language)
    except VoiceUnavailableError:
        return {
            "answer": "Voice input is not configured.",
            "transcribed_text": "",
            "audio_base64": None,
            "error": "No voice providers available",
        }

    if not transcribed:
        return {
            "answer": "Could not understand the audio. Please try again.",
            "transcribed_text": "",
            "audio_base64": None,
            "error": "no_speech",
        }

    chat_request = ChatRequest(
        question=transcribed,
        language=_lang_short(language),
        session_id=session_id,
        state=state,
    )
    # Same ownership boundary as /chat: bind the continuation to the
    # authenticated Clerk sub (client session_id alone is not trusted).
    rag_result = await chat_handler(chat_request, user_id)

    answer_text = rag_result.get("answer", "")
    # TTS must consume the citation-stripped speech copy, never the raw answer
    # (which carries [chunk:ID] markers). speech_text is produced post-verification.
    speech_text = rag_result.get("speech_text") or answer_text
    audio_b64 = None
    try:
        answer_audio = await voice_service.text_to_speech(
            speech_text, _lang_short(language)
        )
        if answer_audio:
            audio_b64 = base64.b64encode(answer_audio).decode("ascii")
    except VoiceUnavailableError:
        audio_b64 = None

    return {
        "answer": answer_text,
        "transcribed_text": transcribed,
        "audio_base64": audio_b64,
        "language": rag_result.get("language", language),
        "domain": rag_result.get("domain", "unknown"),
        "confidence": rag_result.get("confidence", 0.0),
        "confidence_level": rag_result.get("confidence_level", "none"),
        "citations": rag_result.get("citations", []),
        "abstained": rag_result.get("abstained", False),
        "error": None,
    }
