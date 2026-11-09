"""Voice service with provider fallback chain.

STT: Gnani Prisma v3.0 → Sarvam → Azure → text-only
TTS: Gnani Timbre v3.0 (priority) → Sarvam → Azure → error

Each provider has a strict timeout to prevent slow responses from causing chaos.
Providers are called sequentially — never simultaneously.

Language support: Gnani supports 10 Indic/English languages (bn, en, gu, hi,
kn, ml, mr, pa, ta, te). Odia ("or") is NOT supported by Gnani; TTS will fall
through to Sarvam/Azure for unsupported languages.
"""

import asyncio
import logging

from app.providers.gnani_voice import GnaniSTTProvider, GnaniTTSProvider, GnaniError
from app.providers.sarvam_voice import SarvamSTTProvider, SarvamTTSProvider
from app.providers.azure_voice import AzureVoiceProvider

logger = logging.getLogger(__name__)

# Strict timeouts per provider (seconds)
_STT_TIMEOUT = 15
_TTS_TIMEOUT = 45


class VoiceService:
    """Manages voice providers with sequential fallback and strict timeouts."""

    def __init__(self):
        # Gnani is tried first when configured and the language is supported.
        self._gnani_stt = GnaniSTTProvider()
        self._gnani_tts = GnaniTTSProvider()
        self._sarvam_stt = SarvamSTTProvider()
        self._sarvam_tts = SarvamTTSProvider()
        self._azure_stt = AzureVoiceProvider()
        self._azure_tts = AzureVoiceProvider()

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Convert speech to text. Gnani → Sarvam → Azure → error."""
        if not audio_bytes:
            return ""

        empty_result_obtained = False

        # Try Gnani first (best Prisma v3.0 Indic-language STT)
        if self._gnani_stt.enabled:
            try:
                result = await asyncio.wait_for(
                    self._gnani_stt.transcribe(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    logger.info("STT provider: Gnani")
                    return result
                logger.info("Gnani STT returned empty transcript (no speech detected)")
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Gnani STT timed out after %ds", _STT_TIMEOUT)
            except GnaniError as e:
                # GnaniError includes unsupported-language → fall through to Sarvam
                logger.warning("Gnani STT failed: %s", e)
            except Exception as e:
                logger.warning("Gnani STT failed: %s", e)

        # Try Sarvam second (existing primary, best for Indian languages)
        if self._sarvam_stt.enabled:
            try:
                result = await asyncio.wait_for(
                    self._sarvam_stt.transcribe(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    return result
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Sarvam STT timed out after %ds", _STT_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam STT failed: %s", e)

        # Fallback to Azure STT
        if self._azure_stt.enabled:
            try:
                result = await asyncio.wait_for(
                    self._azure_stt.speech_to_text(audio_bytes, language),
                    timeout=_STT_TIMEOUT,
                )
                if result:
                    return result
                empty_result_obtained = True
            except asyncio.TimeoutError:
                logger.warning("Azure STT timed out after %ds", _STT_TIMEOUT)
            except Exception as e:
                logger.warning("Azure STT failed: %s", e)

        if empty_result_obtained:
            return ""

        raise VoiceUnavailableError("No voice providers available. Please type your question.")

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to speech. Gnani Timbre v3.0 (priority) → Sarvam → Azure."""
        if not text or not text.strip():
            return b""

        # 1. Gnani first (priority)
        if self._gnani_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._gnani_tts.synthesize(text, language),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Gnani")
                    return result
                logger.warning("Gnani TTS returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Gnani TTS timed out after %ds", _TTS_TIMEOUT)
            except GnaniError as e:
                logger.warning("Gnani TTS failed: %s", e)
            except Exception as e:
                logger.warning("Gnani TTS failed: %s", e)

        # 2. Sarvam fallback
        if self._sarvam_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._sarvam_tts.synthesize(text, language),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Sarvam")
                    return result
                logger.warning("Sarvam TTS returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Sarvam TTS timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam TTS failed: %s", e)

        # 3. Azure fallback
        logger.info("Sarvam TTS failed; falling back to Azure")
        if self._azure_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._azure_tts.text_to_speech(text, language),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Azure fallback")
                    return result
                logger.warning("Azure TTS returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Azure TTS timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Azure TTS failed: %s", e)

        raise VoiceUnavailableError(
            "Text-to-speech unavailable. Gnani, Sarvam and Azure all failed."
        )

    async def text_to_speech_segments(self, segments: list[dict]) -> bytes:
        """Convert text segments to multi-voice speech. Gnani → Sarvam → Azure."""
        if not segments or not any(s.get("text", "").strip() for s in segments):
            return b""

        # 1. Gnani first (priority)
        if self._gnani_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._gnani_tts.text_to_speech_segments(segments),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Gnani")
                    return result
                logger.warning("Gnani TTS segments returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Gnani TTS segments timed out after %ds", _TTS_TIMEOUT)
            except GnaniError as e:
                logger.warning("Gnani TTS segments failed: %s", e)
            except Exception as e:
                logger.warning("Gnani TTS segments failed: %s", e)

        # 2. Sarvam fallback
        if self._sarvam_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._sarvam_tts.text_to_speech_segments(segments),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Sarvam fallback")
                    return result
                logger.warning("Sarvam TTS segments returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Sarvam TTS segments timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Sarvam TTS segments failed: %s", e)

        # 3. Azure fallback
        logger.info("Sarvam TTS segments failed; falling back to Azure")
        if self._azure_tts.enabled:
            try:
                result = await asyncio.wait_for(
                    self._azure_tts.text_to_speech_segments(segments),
                    timeout=_TTS_TIMEOUT,
                )
                if result:
                    logger.info("TTS provider: Azure fallback segments")
                    return result
                logger.warning("Azure TTS segments returned empty audio")
            except asyncio.TimeoutError:
                logger.warning("Azure TTS segments timed out after %ds", _TTS_TIMEOUT)
            except Exception as e:
                logger.warning("Azure TTS segments failed: %s", e)

        raise VoiceUnavailableError(
            "Text-to-speech unavailable. Gnani, Sarvam and Azure all failed."
        )


class VoiceUnavailableError(Exception):
    """Raised when all voice providers fail."""
