"""Voice I/O route — Gnani (primary) → Sarvam (fallback) → Azure (fallback).

The voice route is a thin adapter around the same RAG pipeline used by /chat.
It does NOT duplicate retrieval, generation, or evidence gating logic.

STT/TTS are delegated to the voice_service layer (app.services.voice_service),
which owns the provider fallback chain (Gnani → Sarvam → Azure → unavailable).
The route adapts HTTP I/O, error policy, and observability metadata.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel

from app.auth import require_auth
from app.providers.gnani_voice import GnaniError
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
    voice: str | None = None
    speed: float | None = None


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
async def transcribe_audio(
    req: TranscribeRequest, authed_user_id: str = Depends(require_auth)
) -> dict:
    """STT: Convert uploaded audio (base64) to text with observability metadata.

    This is a pure STT endpoint — no RAG, no generation.
    Delegates to the voice_service provider fallback chain.
    Requires Clerk auth (AGENTS.md contract) so anonymous callers
    cannot burn STT/TTS provider quota.
    """
    if not req.audio or not req.audio.strip():
        return {
            "text": "",
            "language": req.language,
            "requested_language": req.language,
            "detected_language": None,
            "provider": "none",
            "model": None,
            "duration_ms": 0.0,
            "fallback_occurred": False,
        }

    try:
        audio_bytes = base64.b64decode(req.audio)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 audio payload") from exc

    approx_sec = (len(audio_bytes) - 44) / 32000.0 if len(audio_bytes) > 44 else len(audio_bytes) / 32000.0
    _log.info(
        "STT /voice/transcribe: payload=%d bytes (approx %.2fs at 16kHz mono), requested_lang=%s",
        len(audio_bytes),
        max(0.0, approx_sec),
        req.language,
    )

    try:
        result = await voice_service.speech_to_text(audio_bytes, req.language)
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    text_val = str(result)
    lang_val = getattr(result, "language", req.language)
    req_lang = getattr(result, "requested_language", req.language)
    detected_lang = getattr(result, "detected_language", None)
    provider_val = getattr(result, "provider", "unknown")
    model_val = getattr(result, "model", None)
    duration_val = getattr(result, "duration_ms", 0.0)
    fallback_val = getattr(result, "fallback_occurred", False)

    return {
        "text": text_val,
        "language": lang_val,
        "requested_language": req_lang,
        "detected_language": detected_lang,
        "provider": provider_val,
        "model": model_val,
        "duration_ms": round(duration_val, 2),
        "fallback_occurred": fallback_val,
    }


@router.post("/speak")
async def speak_text(
    req: SpeakRequest, authed_user_id: str = Depends(require_auth)
) -> dict:
    """TTS: Convert text to speech audio (hex-encoded bytes) with observability metadata.

    Supports custom voice selection and speech speed when valid.
    Delegates to the voice_service provider fallback chain.
    """
    try:
        if req.segments:
            result = await voice_service.text_to_speech_segments(
                [s.model_dump() for s in req.segments],
                voice=req.voice,
                speed=req.speed,
            )
            language = req.segments[0].language
        else:
            result = await voice_service.text_to_speech(
                req.text,
                req.language,
                voice=req.voice,
                speed=req.speed,
            )
            language = req.language
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (ValueError, GnaniError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    audio_bytes = bytes(result) if isinstance(result, (bytes, bytearray)) else b""
    provider_val = getattr(result, "provider", "unknown")
    model_val = getattr(result, "model", None)
    voice_val = getattr(result, "voice", req.voice)
    duration_val = getattr(result, "duration_ms", 0.0)
    audio_format_val = getattr(result, "audio_format", "wav")
    fallback_val = getattr(result, "fallback_occurred", False)

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else ""

    return {
        "audio": audio_bytes.hex(),
        "audio_base64": audio_b64,
        "language": language,
        "provider": provider_val,
        "model": model_val,
        "voice": voice_val,
        "duration_ms": round(duration_val, 2),
        "audio_format": audio_format_val,
        "fallback_occurred": fallback_val,
    }


@router.post("")
async def voice_chat(
    audio: UploadFile = File(...),  # noqa: B008
    language: str = Form(default="hi"),
    session_id: str = Form(default=""),
    state: str | None = Form(default=None),
    user_id: str = Depends(require_auth),
) -> dict:
    """Full voice pipeline: audio → STT → RAG → TTS → audio with metadata.

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

    transcribed_text = str(transcribed)
    stt_provider = getattr(transcribed, "provider", "unknown")
    detected_lang = getattr(transcribed, "detected_language", None)
    stt_duration_ms = getattr(transcribed, "duration_ms", 0.0)

    if not transcribed_text:
        return {
            "answer": "Could not understand the audio. Please try again.",
            "transcribed_text": "",
            "audio_base64": None,
            "error": "no_speech",
            "stt_provider": stt_provider,
        }

    # Use detected language if available and automatic detection was requested
    effective_chat_lang = (
        detected_lang
        if language in ("auto", "indic-auto") and detected_lang
        else _lang_short(language)
    )

    chat_request = ChatRequest(
        question=transcribed_text,
        language=effective_chat_lang,
        session_id=session_id,
        state=state,
    )
    # Same ownership boundary as /chat: bind continuation to authenticated Clerk sub
    rag_result = await chat_handler(chat_request, user_id)

    answer_text = rag_result.get("answer", "")
    speech_text = rag_result.get("speech_text") or answer_text
    audio_b64 = None
    tts_provider = None
    tts_duration_ms = 0.0

    try:
        answer_audio = await voice_service.text_to_speech(
            speech_text, effective_chat_lang
        )
        if answer_audio:
            audio_b64 = base64.b64encode(answer_audio).decode("ascii")
            tts_provider = getattr(answer_audio, "provider", "unknown")
            tts_duration_ms = getattr(answer_audio, "duration_ms", 0.0)
    except VoiceUnavailableError:
        audio_b64 = None

    return {
        "answer": answer_text,
        "transcribed_text": transcribed_text,
        "audio_base64": audio_b64,
        "language": rag_result.get("language", effective_chat_lang),
        "detected_language": detected_lang,
        "stt_provider": stt_provider,
        "tts_provider": tts_provider,
        "duration_ms": round(stt_duration_ms + tts_duration_ms, 2),
        "domain": rag_result.get("domain", "unknown"),
        "confidence": rag_result.get("confidence", 0.0),
        "confidence_level": rag_result.get("confidence_level", "none"),
        "citations": rag_result.get("citations", []),
        "abstained": rag_result.get("abstained", False),
        "error": None,
    }
