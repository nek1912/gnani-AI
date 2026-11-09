"""Tests for Gnani AI voice provider (Prisma v3.0 STT + Timbre v3.0 TTS).

All HTTP calls are mocked with respx — no real Gnani credentials required.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from app.config import Settings
from app.providers.gnani_voice import (
    GnaniSTTProvider,
    GnaniTTSProvider,
    GnaniAuthenticationError,
    GnaniRateLimitedError,
    GnaniServiceUnavailableError,
    GnaniTimeoutError,
    GnaniError,
    STT_MODEL,
    TTS_MODEL,
    _gnani_lang_code,
    _gnani_supports_language,
)


# ── Helpers ───────────────────────────────────────────────────────────────


def _settings(gstn_api_key: str = "test-gnani-key") -> Settings:
    return Settings(
        gstn_api_key=gstn_api_key,
        groq_api_key="test-groq",
        supabase_url="http://testsupa",
        supabase_service_key="test-supabase",
    )


def _stt_success_response(transcript: str, language: str = "hi-IN") -> dict:
    return {
        "success": True,
        "request_id": "req-123",
        "transcript": transcript,
        "model": STT_MODEL,
        "detected_language_code": language,
        "processing_time": 0.62,
    }


# ── GnaniSTTProvider tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stt_successful_hindi_transcription():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json=_stt_success_response("मेरा खाता नंबर 12345 है", "hi-IN"))
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"fake-audio-bytes", "hi")
        assert transcript == "मेरा खाता नंबर 12345 है"
        assert respx.calls
        body = respx.calls[0].request.content.decode()
        assert "prisma-v3.0" in body
        assert "indic-auto" in body or "hi-IN" in body


@pytest.mark.asyncio
async def test_stt_successful_gujarati_transcription():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json=_stt_success_response("મારું ખાતું નંબર 12345 છે", "gu-IN"))
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"fake-audio", "gu")
        assert transcript == "મારું ખાતું નંબર 12345 છે"


@pytest.mark.asyncio
async def test_stt_successful_english_transcription():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json=_stt_success_response("My account number is 12345", "en-IN"))
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"fake-audio", "en")
        assert transcript == "My account number is 12345"


@pytest.mark.asyncio
async def test_stt_language_auto_detection():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json=_stt_success_response("नमस्ते", "hi-IN"))
        )
        provider = GnaniSTTProvider(settings=_settings())
        await provider.transcribe(b"fake-audio", "hi")
        assert respx.calls
        body = respx.calls[0].request.content.decode()
        assert "indic-auto" in body


@pytest.mark.asyncio
async def test_stt_code_mixed_transcription():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json=_stt_success_response("कल थ्री फिफ्टी पीएम को पाँच सौ रुपये transfer करना है", "hi-IN"))
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"fake-audio", "hi")
        assert "transfer" in transcript
        assert "रुपये" in transcript


@pytest.mark.asyncio
async def test_stt_empty_transcription_is_not_error():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json={
                "success": True, "request_id": "req-empty", "transcript": "",
                "model": STT_MODEL, "processing_time": 0.1,
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"silence-audio", "hi")
        assert transcript == ""


@pytest.mark.asyncio
async def test_stt_unsupported_odia_raises():
    provider = GnaniSTTProvider(settings=_settings())
    with pytest.raises(GnaniError, match="does not support language"):
        await provider.transcribe(b"fake-audio", "or")


@pytest.mark.asyncio
async def test_stt_audio_longer_than_30_seconds():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(400, json={
                "success": False,
                "error": {"type": "MAX_AUDIO_DURATION_EXCEEDED",
                          "message": "Audio duration exceeds maximum allowed duration of 30 seconds"},
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniError):
            await provider.transcribe(b"long-audio" * 1000, "hi")


@pytest.mark.asyncio
async def test_stt_invalid_api_key():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(401, json={"detail": {"error_code": "INVALID_API_KEY", "message": "Unauthorized", "status_code": 401}})
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniAuthenticationError):
            await provider.transcribe(b"fake-audio", "hi")


@pytest.mark.asyncio
async def test_stt_missing_api_key():
    with patch.dict(os.environ, {"GNANI_API_KEY": ""}):
        provider = GnaniSTTProvider(settings=_settings(gstn_api_key=""))
    assert not provider.enabled


@pytest.mark.asyncio
async def test_stt_rate_limit():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "Too many requests", "status_code": 429}})
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniRateLimitedError):
            await provider.transcribe(b"fake-audio", "hi")


@pytest.mark.asyncio
async def test_stt_service_unavailable():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(503, json={
                "success": False, "error": {"type": "SERVICE_UNAVAILABLE", "message": "Service temporarily unavailable"},
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniServiceUnavailableError):
            await provider.transcribe(b"fake-audio", "hi")


@pytest.mark.asyncio
async def test_stt_timeout():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            side_effect=TimeoutError("read timeout")
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniTimeoutError):
            await provider.transcribe(b"fake-audio", "hi")


@pytest.mark.asyncio
async def test_stt_malformed_response():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, content=b"not json at all")
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniError, match="malformed JSON"):
            await provider.transcribe(b"fake-audio", "hi")


@pytest.mark.asyncio
async def test_stt_success_false():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json={
                "success": False,
                "error": {"type": "INVALID_LANGUAGE_CODE", "message": "Unsupported language"},
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        with pytest.raises(GnaniError, match="does not support language"):
            await provider.transcribe(b"fake-audio", "xx")


@pytest.mark.asyncio
async def test_stt_truncated_transcript():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json={
                "success": True, "request_id": "req-trunc", "transcript": "…",
                "model": STT_MODEL, "truncated": True, "processing_time": 1.4,
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        transcript = await provider.transcribe(b"fake-audio", "hi")
        assert transcript == "…"


# ── GnaniTTSProvider tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tts_successful_audio_generation():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(200, content=b"RIFF....WAVEfake-audio-bytes")
        )
        provider = GnaniTTSProvider(settings=_settings())
        audio = await provider.synthesize("नमस्ते, आप कैसे हैं?", "hi")
        assert audio == b"RIFF....WAVEfake-audio-bytes"
        assert len(audio) > 0


@pytest.mark.asyncio
async def test_tts_correct_language_and_voice_mapping():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return Response(200, content=b"fake-wav-audio")

    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings())
        await provider.synthesize("Hello world", "en")
        assert respx.calls
        assert captured["body"]["language"] == "en-IN"
        assert captured["body"]["voice"] == "Shivani"
        assert captured["body"]["model"] == TTS_MODEL
        assert captured["body"]["text"] == "Hello world"
        assert captured["body"]["audio_config"]["container"] == "wav"


@pytest.mark.asyncio
async def test_tts_binary_audio_handling():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(200, content=b"\x00\x01\x02\x03binary-audio")
        )
        provider = GnaniTTSProvider(settings=_settings())
        audio = await provider.synthesize("test", "hi")
        assert isinstance(audio, bytes)
        assert audio == b"\x00\x01\x02\x03binary-audio"


@pytest.mark.asyncio
async def test_tts_unsupported_odia_raises():
    provider = GnaniTTSProvider(settings=_settings())
    with pytest.raises(GnaniError, match="does not support language"):
        await provider.synthesize("ନମସ୍କାର", "or")


@pytest.mark.asyncio
async def test_tts_invalid_api_key():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(401, json={"detail": {"error_code": "INVALID_API_KEY", "message": "Unauthorized", "status_code": 401}})
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniAuthenticationError):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_rate_limit():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "Too many requests", "status_code": 429}})
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniRateLimitedError):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_service_unavailable():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(503, json={
                "success": False, "error": {"type": "SERVICE_UNAVAILABLE", "message": "TTS unavailable"},
            })
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniServiceUnavailableError):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_timeout():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            side_effect=TimeoutError("read timeout")
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniTimeoutError):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_empty_audio_raises():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(200, content=b"")
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniError, match="empty audio"):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_400_bad_request():
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(
            return_value=Response(400, json={
                "success": False, "message": "Invalid request: voice is required", "status_code": 400,
            })
        )
        provider = GnaniTTSProvider(settings=_settings())
        with pytest.raises(GnaniError):
            await provider.synthesize("test", "hi")


@pytest.mark.asyncio
async def test_tts_provider_disabled_without_key():
    with patch.dict(os.environ, {"GNANI_API_KEY": ""}):
        provider = GnaniTTSProvider(settings=_settings(gstn_api_key=""))
    assert not provider.enabled


# ── Language mapping tests ───────────────────────────────────────────────


@pytest.mark.parametrize("short,bcp", [
    ("en", "en-IN"), ("hi", "hi-IN"), ("gu", "gu-IN"), ("mr", "mr-IN"),
    ("bn", "bn-IN"), ("ta", "ta-IN"), ("te", "te-IN"), ("kn", "kn-IN"),
    ("pa", "pa-IN"), ("ml", "ml-IN"),
])
def test_gnani_lang_code_mapping(short, bcp):
    assert _gnani_lang_code(short) == bcp


def test_gnani_supports_language_odia_is_false():
    assert not _gnani_supports_language("or")


def test_gnani_supports_language_hindi_is_true():
    assert _gnani_supports_language("hi")


# ── VoiceService integration tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_voice_service_stt_gnani_first_then_sarvam():
    from app.services.voice_service import VoiceService
    service = VoiceService()
    with patch.object(service._gnani_stt, 'enabled', True), \
            patch.object(service._gnani_stt, 'transcribe', new_callable=AsyncMock, return_value="नमस्ते"), \
            patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock) as sarvam_mock:
        result = await service.speech_to_text(b"audio", "hi")
        assert result == "नमस्ते"
        sarvam_mock.assert_not_called()


@pytest.mark.asyncio
async def test_voice_service_stt_gnani_fails_falls_to_sarvam():
    from app.services.voice_service import VoiceService
    service = VoiceService()
    with patch.object(service._gnani_stt, 'enabled', True), \
            patch.object(service._gnani_stt, 'transcribe', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")), \
            patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock, return_value="sarvam text"), \
            patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock) as azure_mock:
        result = await service.speech_to_text(b"audio", "hi")
        assert result == "sarvam text"
        azure_mock.assert_not_called()


@pytest.mark.asyncio
async def test_voice_service_stt_all_fail_raises():
    from app.services.voice_service import VoiceService
    from app.services.voice_service import VoiceUnavailableError
    service = VoiceService()
    with patch.object(service._gnani_stt, 'enabled', True), \
            patch.object(service._gnani_stt, 'transcribe', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")), \
            patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam down")), \
            patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock, side_effect=RuntimeError("Azure down")):
        with pytest.raises(VoiceUnavailableError):
            await service.speech_to_text(b"audio", "hi")


@pytest.mark.asyncio
async def test_voice_service_tts_gnani_first_then_sarvam():
    from app.services.voice_service import VoiceService
    service = VoiceService()
    with patch.object(service._gnani_tts, 'enabled', True), \
            patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, return_value=b"gnani-audio"), \
            patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock) as sarvam_mock:
        result = await service.text_to_speech("नमस्ते", "hi")
        assert result == b"gnani-audio"
        sarvam_mock.assert_not_called()


@pytest.mark.asyncio
async def test_voice_service_tts_gnani_fails_falls_to_sarvam():
    from app.services.voice_service import VoiceService
    service = VoiceService()
    with patch.object(service._gnani_tts, 'enabled', True), \
            patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")), \
            patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, return_value=b"sarvam-audio"):
        result = await service.text_to_speech("नमस्ते", "hi")
        assert result == b"sarvam-audio"


@pytest.mark.asyncio
async def test_voice_service_tts_odia_falls_to_sarvam():
    from app.services.voice_service import VoiceService
    service = VoiceService()
    with patch.object(service._gnani_tts, 'enabled', True), \
            patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Odia unsupported")) as gnani_mock, \
            patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, return_value=b"sarvam-odia-audio"):
        result = await service.text_to_speech("ନମସ୍କାର", "or")
        assert result == b"sarvam-odia-audio"
        gnani_mock.assert_called_once()


@pytest.mark.asyncio
async def test_voice_service_tts_all_fail_raises():
    from app.services.voice_service import VoiceService
    from app.services.voice_service import VoiceUnavailableError
    service = VoiceService()
    with patch.object(service._gnani_tts, 'enabled', True), \
            patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")), \
            patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam down")), \
            patch.object(service._azure_tts, 'text_to_speech', new_callable=AsyncMock, side_effect=RuntimeError("Azure down")):
        with pytest.raises(VoiceUnavailableError):
            await service.text_to_speech("test", "hi")


# ── Provider initialization without key ─────────────────────────────────


def test_gnani_providers_init_without_key():
    with patch.dict(os.environ, {"GNANI_API_KEY": ""}):
        settings = Settings(
            gstn_api_key="",
            groq_api_key="test",
            supabase_url="http://testsupa",
            supabase_service_key="test",
        )
    stt = GnaniSTTProvider(settings=settings)
    tts = GnaniTTSProvider(settings=settings)
    assert not stt.enabled
    assert not tts.enabled


# ── Robustness: retry on 503, chunking, and segments ─────────────────────


@pytest.mark.asyncio
async def test_tts_retry_on_503_recovers():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(503, json={"error": {"message": "temporary overload"}})
        return Response(200, content=b"RIFF....WAVEfake-audio")

    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings())
        audio = await provider.synthesize("test", "hi")
        assert audio == b"RIFF....WAVEfake-audio"
        assert call_count == 2


@pytest.mark.asyncio
async def test_tts_empty_text_returns_empty():
    provider = GnaniTTSProvider(settings=_settings())
    assert await provider.synthesize("", "hi") == b""
    assert await provider.synthesize("   ", "hi") == b""
    assert await provider.text_to_speech_segments([]) == b""
    assert await provider.text_to_speech_segments([{"text": "  "}]) == b""


@pytest.mark.asyncio
async def test_tts_chunking_and_stitching():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        from app.providers.gnani_voice import _build_wav_header
        hdr = _build_wav_header(4, sample_rate=22050)
        return Response(200, content=hdr + b"\x01\x02\x03\x04")

    long_text = "यह पहला वाक्य है। " * 40  # ~760 characters -> exceeds 500 max_chars
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings())
        audio = await provider.synthesize(long_text, "hi")
        assert len(captured) >= 2
        assert len(audio) > 44
        assert audio[:4] == b"RIFF"
        assert audio[8:12] == b"WAVE"


@pytest.mark.asyncio
async def test_tts_segments_mixed_language():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        from app.providers.gnani_voice import _build_wav_header
        hdr = _build_wav_header(4, sample_rate=22050)
        return Response(200, content=hdr + b"\x00\x00\x00\x00")

    segments = [
        {"text": "Hello world", "language": "en"},
        {"text": "नमस्ते भारत", "language": "hi"},
    ]
    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings())
        audio = await provider.text_to_speech_segments(segments)
        assert len(captured) == 2
        assert captured[0]["language"] == "en-IN"
        assert captured[1]["language"] == "hi-IN"
        assert audio[:4] == b"RIFF"


# ── Area A Improvements: Observability, Voice Customization & 30s Fallback ──


@pytest.mark.asyncio
async def test_stt_result_metadata_and_observability():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json={
                "success": True,
                "transcript": "नमस्ते जनसहाय",
                "model": "prisma-v3.0",
                "detected_language_code": "hi-IN",
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        result = await provider.transcribe(b"fake-wav-bytes", "hi")
        assert result == "नमस्ते जनसहाय"
        assert result.provider == "gnani"
        assert result.model == "prisma-v3.0"
        assert result.detected_language == "hi"
        assert result.requested_language == "hi"
        assert result.language == "hi"
        assert result.duration_ms >= 0.0
        assert result.fallback_occurred is False
        d = result.to_dict()
        assert d["provider"] == "gnani"
        assert d["detected_language"] == "hi"


@pytest.mark.asyncio
async def test_stt_auto_detect_effective_language():
    with respx.mock:
        respx.post("https://api.vachana.ai/stt/v3").mock(
            return_value=Response(200, json={
                "success": True,
                "transcript": "નમસ્તે",
                "model": "prisma-v3.0",
                "detected_language_code": "gu-IN",
            })
        )
        provider = GnaniSTTProvider(settings=_settings())
        # With auto_detect or 'auto', effective language should be resolved to 'gu'
        result = await provider.transcribe(b"fake-wav-bytes", "auto")
        assert result == "નમસ્તે"
        assert result.detected_language == "gu"
        assert result.language == "gu"


@pytest.mark.asyncio
async def test_tts_custom_voice_and_speed_validation():
    captured = []

    def handler(request):
        data = json.loads(request.content)
        captured.append(data)
        from app.providers.gnani_voice import _build_wav_header
        hdr = _build_wav_header(4, sample_rate=22050)
        return Response(200, content=hdr + b"\x01\x02\x03\x04")

    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings())

        # Valid custom voice and speed
        result = await provider.synthesize("परीक्षण", "hi", voice="Avinash", speed=1.2)
        assert len(result) > 44
        assert result.voice == "Avinash"
        assert result.speed == 1.2
        assert result.provider == "gnani"
        assert result.audio_format == "wav"
        assert captured[0]["voice"] == "Avinash"
        assert captured[0]["speed"] == 1.2

        # Invalid voice raises GnaniError
        with pytest.raises(GnaniError, match="Unsupported voice"):
            await provider.synthesize("परीक्षण", "hi", voice="NonExistentVoice999")

        # Invalid speed raises GnaniError
        with pytest.raises(GnaniError, match="Speed must be between 0.5 and 2.0"):
            await provider.synthesize("परीक्षण", "hi", speed=3.5)


@pytest.mark.asyncio
async def test_voice_service_audio_duration_fallback_to_sarvam():
    from app.services.voice_service import VoiceService
    from app.providers.gnani_voice import _build_wav_header
    service = VoiceService()

    # Construct WAV header indicating 35 seconds of audio:
    # 16000 Hz, 1 channel, 16-bit (2 bytes per sample) -> 32000 bytes/sec
    # 35 seconds = 35 * 32000 = 1,120,000 PCM bytes
    pcm_len = 35 * 32000
    hdr = _build_wav_header(pcm_len, sample_rate=16000, num_channels=1, sample_width=2)
    long_audio = hdr + b"\x00" * 1000  # header indicates 35s

    with patch.object(service._gnani_stt, 'enabled', True), \
         patch.object(service._gnani_stt, 'transcribe', new_callable=AsyncMock) as gnani_mock, \
         patch.object(service._sarvam_stt, 'enabled', True), \
         patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock) as sarvam_mock:
        sarvam_mock.return_value = "sarvam long audio text"
        res = await service.speech_to_text(long_audio, "hi")
        assert res == "sarvam long audio text"
        assert res.provider == "sarvam"
        assert res.fallback_occurred is True
        # Gnani should have been bypassed due to pre-flight 30s guard
        gnani_mock.assert_not_called()


@pytest.mark.asyncio
async def test_tts_in_memory_caching():
    from app.providers.gnani_voice import clear_tts_cache
    clear_tts_cache()

    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return Response(200, content=b"RIFF....WAVEcached-audio-payload")

    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings(), use_cache=True)

        # Call 1: Misses cache, calls API
        audio1 = await provider.synthesize("नमस्कार मित्रांनो", "mr")
        assert audio1 == b"RIFF....WAVEcached-audio-payload"
        assert call_count == 1

        # Call 2: Hits in-memory cache, NO network call
        audio2 = await provider.synthesize("नमस्कार मित्रांनो", "mr")
        assert audio2 == b"RIFF....WAVEcached-audio-payload"
        assert call_count == 1  # Network was NOT called a second time!
        assert audio2.duration_ms < 50.0  # Instantaneous memory lookup

    clear_tts_cache()


@pytest.mark.asyncio
async def test_tts_concurrent_multi_chunk_synthesis():
    from app.providers.gnani_voice import _build_wav_header
    calls = []

    def handler(request):
        import json
        body = json.loads(request.content)
        calls.append(body["text"])
        hdr = _build_wav_header(100, sample_rate=22050, num_channels=1, sample_width=2)
        return Response(200, content=hdr + b"\x01" * 100)

    # 3 sentences that exceed 500 characters
    long_text = ("पहला लंबा वाक्य जो सरकार के नियमों की जानकारी देता है। " * 10) + ("दूसरा वाक्य जो सहायता करता है। " * 10)

    with respx.mock:
        respx.post("https://api.vachana.ai/api/v1/tts/inference").mock(side_effect=handler)
        provider = GnaniTTSProvider(settings=_settings(), use_cache=False)
        audio = await provider.synthesize(long_text, "hi")

        assert len(audio) > 44
        assert audio[:4] == b"RIFF"
        assert len(calls) > 1  # Multiple chunks synthesized


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS") or not os.getenv("GNANI_API_KEY"),
    reason="Live Gnani test requires RUN_LIVE_TESTS=1 and GNANI_API_KEY",
)
async def test_live_gnani_smoke_test():
    """Optional smoke test against real Gnani API when explicitly enabled."""
    provider = GnaniTTSProvider()
    if provider.enabled:
        audio = await provider.synthesize("नमस्ते जनसहाय", "hi")
        assert len(audio) > 44
        assert audio[:4] == b"RIFF"


