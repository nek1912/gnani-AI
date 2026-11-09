"""Voice service with provider fallback chain and observability.

STT: Gnani Prisma v3.0 → Sarvam → Azure → error
TTS: Gnani Timbre v3.0 (priority) → Sarvam → Azure → error

Each provider has a strict timeout to prevent slow responses from causing chaos.
Providers are called sequentially — never simultaneously.

Language support: Gnani supports 10 Indic/English languages (bn, en, gu, hi,
kn, ml, mr, pa, ta, te). Odia ("or") is NOT supported by Gnani; TTS will fall
through to Sarvam/Azure for unsupported languages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.providers.gnani_voice import (
    GnaniSTTProvider,
    GnaniTTSProvider,
    GnaniError,
    GnaniAudioDurationExceededError,
    STTResult,
    TTSResult,
    _estimate_audio_duration_s,
)
from app.providers.sarvam_voice import SarvamSTTProvider, SarvamTTSProvider
from app.providers.azure_voice import AzureVoiceProvider

logger = logging.getLogger(__name__)

# Strict timeouts per provider (seconds)
_STT_TIMEOUT = 15
_TTS_TIMEOUT = 45


class VoiceService:
    """Manages voice providers with sequential fallback, strict timeouts, and observability."""

    def __init__(self):
        # Gnani is tried first when configured and the language is supported.
        self._gnani_stt = GnaniSTTProvider()
        self._gnani_tts = GnaniTTSProvider()
        self._sarvam_stt = SarvamSTTProvider()
        self._sarvam_tts = SarvamTTSProvider()
        self._azure_stt = AzureVoiceProvider()
        self._azure_tts = AzureVoiceProvider()

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> STTResult:
        """Convert speech to text. Gnani → Sarvam → Azure → error.

        Returns STTResult (subclass of str) containing transcript and rich metadata
        (provider, model, duration_ms, detected_language, fallback_occurred).
        """
        if not audio_bytes:
            return STTResult(
                "",
                language=language,
                requested_language=language,
                detected_language=None,
                provider="none",
                model=None,
                duration_ms=0.0,
                fallback_occurred=False,
            )

        t0 = time.perf_counter()
        empty_result_obtained = False
        fallback_occurred = False

        # Pre-flight audio duration guard for Gnani (30s limit)
        audio_dur = _estimate_audio_duration_s(audio_bytes)
        skip_gnani_due_to_duration = audio_dur > 30.0
        if skip_gnani_due_to_duration:
            logger.info(
                "Audio duration (%.1fs) exceeds Gnani 30s limit; skipping directly to Sarvam",
                audio_dur,
            )
            fallback_occurred = True

        # 1. Try Gnani first (best Prisma v3.0 Indic-language STT)
        if self._gnani_stt.enabled and not skip_gnani_due_to_duration:
            try:
                result = await asyncio.wait_for(
                    self._gnani_stt.transcribe(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("STT provider: Gnani (%.1fms)", duration_ms)
                    return STTResult(
                        result,
                        language=getattr(result, "language", language),
                        requested_language=language,
                        detected_language=getattr(result, "detected_language", None),
                        provider="gnani",
                        model=getattr(result, "model", "prisma-v3.0"),
                        duration_ms=duration_ms,
                        fallback_occurred=False,
                    )
                logger.info("Gnani STT returned empty transcript (no speech detected)")
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Gnani STT timed out after %ds", _STT_TIMEOUT)
                fallback_occurred = True
            except GnaniAudioDurationExceededError as e:
                logger.warning("Gnani STT audio too long, falling back to Sarvam: %s", e)
                fallback_occurred = True
            except GnaniError as e:
                # GnaniError includes unsupported-language → fall through to Sarvam
                logger.warning("Gnani STT failed: %s", e)
                fallback_occurred = True
            except Exception as e:
                logger.warning("Gnani STT failed: %s", e)
                fallback_occurred = True

        # 2. Try Sarvam second (existing primary, best for Indian languages)
        if self._sarvam_stt.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._sarvam_stt.transcribe(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("STT provider: Sarvam fallback (%.1fms)", duration_ms)
                    return STTResult(
                        result,
                        language=language,
                        requested_language=language,
                        detected_language=language,
                        provider="sarvam",
                        model="sarvam-stt",
                        duration_ms=duration_ms,
                        fallback_occurred=True,
                    )
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Sarvam STT timed out after %ds", _STT_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam STT failed: %s", e)

        # 3. Fallback to Azure STT
        if self._azure_stt.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._azure_stt.speech_to_text(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("STT provider: Azure fallback (%.1fms)", duration_ms)
                    return STTResult(
                        result,
                        language=language,
                        requested_language=language,
                        detected_language=language,
                        provider="azure",
                        model="azure-stt",
                        duration_ms=duration_ms,
                        fallback_occurred=True,
                    )
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Azure STT timed out after %ds", _STT_TIMEOUT)
            except Exception as e:
                logger.warning("Azure STT failed: %s", e)

        if empty_result_obtained:
            return STTResult(
                "",
                language=language,
                requested_language=language,
                detected_language=None,
                provider="empty",
                model=None,
                duration_ms=(time.perf_counter() - t0) * 1000,
                fallback_occurred=fallback_occurred,
            )

        raise VoiceUnavailableError("No voice providers available. Please type your question.")

    async def text_to_speech(
        self,
        text: str,
        language: str = "en",
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> TTSResult:
        """Convert text to speech. Gnani Timbre v3.0 (priority) → Sarvam → Azure."""
        if not text or not text.strip():
            return TTSResult(
                b"",
                language=language,
                provider="none",
                model=None,
                voice=voice,
                speed=speed,
                duration_ms=0.0,
                fallback_occurred=False,
            )

        t0 = time.perf_counter()
        fallback_occurred = False

        # 1. Gnani first (priority)
        if self._gnani_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._gnani_tts.synthesize(text, language, voice=voice, speed=speed),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Gnani (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=language,
                        provider="gnani",
                        model=getattr(result, "model", "timbre-v3.0"),
                        voice=getattr(result, "voice", voice or self._gnani_tts.voice),
                        speed=getattr(result, "speed", speed or self._gnani_tts.speed),
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=False,
                    )
                logger.warning("Gnani TTS returned empty audio")
                fallback_occurred = True
            except asyncio.TimeoutError:
                logger.warning("Gnani TTS timed out after %ds", _TTS_TIMEOUT)
                fallback_occurred = True
            except GnaniError as e:
                logger.warning("Gnani TTS failed: %s", e)
                fallback_occurred = True
            except Exception as e:
                logger.warning("Gnani TTS failed: %s", e)
                fallback_occurred = True

        # 2. Sarvam fallback (never pass Gnani voice to Sarvam)
        if self._sarvam_tts.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._sarvam_tts.synthesize(text, language),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Sarvam fallback (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=language,
                        provider="sarvam",
                        model="sarvam-tts",
                        voice="sarvam-default",
                        speed=1.0,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=True,
                    )
                logger.warning("Sarvam TTS returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Sarvam TTS timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam TTS failed: %s", e)

        # 3. Azure fallback
        logger.info("Sarvam TTS failed; falling back to Azure")
        if self._azure_tts.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._azure_tts.text_to_speech(text, language),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Azure fallback (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=language,
                        provider="azure",
                        model="azure-tts",
                        voice="azure-default",
                        speed=1.0,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=True,
                    )
                logger.warning("Azure TTS returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Azure TTS timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Azure TTS failed: %s", e)

        raise VoiceUnavailableError(
            "Text-to-speech unavailable. Gnani, Sarvam and Azure all failed."
        )

    async def text_to_speech_segments(
        self,
        segments: list[dict],
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> TTSResult:
        """Convert text segments to multi-voice speech. Gnani → Sarvam → Azure."""
        if not segments or not any(s.get("text", "").strip() for s in segments):
            return TTSResult(
                b"",
                language="hi",
                provider="none",
                model=None,
                voice=voice,
                speed=speed,
                duration_ms=0.0,
                fallback_occurred=False,
            )

        t0 = time.perf_counter()
        fallback_occurred = False

        # 1. Gnani first (priority)
        if self._gnani_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._gnani_tts.text_to_speech_segments(segments, voice=voice, speed=speed),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Gnani segments (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=getattr(result, "language", segments[0].get("language", "hi")),
                        provider="gnani",
                        model=getattr(result, "model", "timbre-v3.0"),
                        voice=getattr(result, "voice", voice or self._gnani_tts.voice),
                        speed=getattr(result, "speed", speed or self._gnani_tts.speed),
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=False,
                    )
                logger.warning("Gnani TTS segments returned empty audio")
                fallback_occurred = True
            except asyncio.TimeoutError:
                logger.warning("Gnani TTS segments timed out after %ds", _TTS_TIMEOUT)
                fallback_occurred = True
            except GnaniError as e:
                logger.warning("Gnani TTS segments failed: %s", e)
                fallback_occurred = True
            except Exception as e:
                logger.warning("Gnani TTS segments failed: %s", e)
                fallback_occurred = True

        # 2. Sarvam fallback
        if self._sarvam_tts.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._sarvam_tts.text_to_speech_segments(segments),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Sarvam fallback segments (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=segments[0].get("language", "hi"),
                        provider="sarvam",
                        model="sarvam-tts",
                        voice="sarvam-default",
                        speed=1.0,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=True,
                    )
                logger.warning("Sarvam TTS segments returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Sarvam TTS segments timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam TTS failed: %s", e)

        # 3. Azure fallback
        logger.info("Sarvam TTS segments failed; falling back to Azure")
        if self._azure_tts.enabled:
            fallback_occurred = True
            try:
                result = await asyncio.wait_for(
                    self._azure_tts.text_to_speech_segments(segments),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    logger.info("TTS provider: Azure fallback segments (%.1fms)", duration_ms)
                    return TTSResult(
                        result,
                        language=segments[0].get("language", "hi"),
                        provider="azure",
                        model="azure-tts",
                        voice="azure-default",
                        speed=1.0,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=True,
                    )
                logger.warning("Azure TTS segments returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Azure TTS segments timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Azure TTS failed: %s", e)

        raise VoiceUnavailableError(
            "Text-to-speech unavailable. Gnani, Sarvam and Azure all failed."
        )


class VoiceUnavailableError(Exception):
    """Raised when all voice providers fail."""
