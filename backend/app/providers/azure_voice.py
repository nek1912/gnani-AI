"""Azure Cognitive Services voice provider (primary).

Implements STT + TTS using the Azure Speech SDK. This is the provider actually
wired into ``app.services.voice_service.VoiceService`` (one RAG core, no
separate voice RAG — voice.py delegates to the same /chat path).

Language handling is deliberately limited to *locale/voice selection*: the
language → Azure locale → Azure voice mapping is config-driven (see
app.config speech_locales / tts_voices). No citation, retrieval, or answer
logic is language-specific here.

Graceful failure: when unconfigured or when the SDK is missing, methods raise
RuntimeError, which VoiceService catches and uses to fall back to the next
provider in the chain (never inventing an answer).
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_LOCALES = {"en": "en-IN", "hi": "hi-IN", "gu": "gu-IN", "mr": "mr-IN", "bn": "bn-IN"}


def _xml_escape(text: str) -> str:
    """Escape a string for safe inclusion in SSML markup."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class AzureVoiceProvider:
    """Azure Speech Services for STT and TTS."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self.speech_key = getattr(self._settings, "azure_speech_key", "")
        self.speech_region = getattr(self._settings, "azure_speech_region", "centralindia")
        self.enabled = bool(self.speech_key)
        if not self.enabled:
            logger.info("Azure voice disabled: AZURE_SPEECH_KEY not set")

    # ---- locale / voice selection (language-aware, config-driven) ----
    def _locale(self, language: str) -> str:
        return self._settings.speech_locales.get(language, _DEFAULT_LOCALES.get(language, "en-IN"))

    def _voice(self, language: str) -> str:
        return self._settings.tts_voices.get(language, "en-IN-NeerjaNeural")

    @staticmethod
    def _sdk():
        import importlib

        try:
            return importlib.import_module("azure.cognitiveservices.speech")
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("azure-cognitiveservices-speech SDK not installed") from exc

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe audio to text. Returns '' on no-match; raises on error."""
        if not self.enabled:
            raise RuntimeError("Azure voice not configured")
        speechsdk = self._sdk()
        try:
            config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
            config.speech_recognition_language = self._locale(language)
            stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=stream)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=config, audio_config=audio_config
            )
            stream.write(audio_bytes)
            stream.close()
            # recognize_once() blocks the calling thread — run it off the
            # event loop so one slow STT call cannot stall all requests.
            result = await asyncio.to_thread(recognizer.recognize_once)
        except Exception as exc:
            logger.warning("Azure STT failed: %r", exc)
            raise RuntimeError("Azure STT failed") from exc
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text
        if result.reason == speechsdk.ResultReason.Canceled:
            logger.warning("Azure STT canceled: %s", result.cancellation_details)
        return ""

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Synthesize speech audio (WAV). Returns b'' on failure/cancel."""
        if not self.enabled:
            raise RuntimeError("Azure voice not configured")
        speechsdk = self._sdk()
        try:
            config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
            config.speech_synthesis_voice_name = self._voice(language)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            # .get() blocks the calling thread — wait for it off the loop.
            future = synthesizer.speak_text_async(text)
            result = await asyncio.to_thread(future.get)
        except Exception as exc:
            logger.warning("Azure TTS failed: %r", exc)
            raise RuntimeError("Azure TTS failed") from exc
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return result.audio_data
        if result.reason == speechsdk.ResultReason.Canceled:
            logger.warning("Azure TTS canceled: %s", result.cancellation_details)
            raise RuntimeError("Azure TTS canceled")
        raise RuntimeError("Azure TTS canceled")

    async def text_to_speech_segments(self, segments: list[dict]) -> bytes:
        """Synthesize one multi-voice SSML document from contiguous segment runs.

        Each segment renders as one ``<voice>`` block so the document mixes
        voices/locales. Returns the WAV bytes on success; raises RuntimeError on
        cancel/empty so the fallback chain triggers (never returns b"").
        """
        if not self.enabled:
            raise RuntimeError("Azure voice not configured")
        if not segments:
            raise RuntimeError("Azure TTS segments empty")
        speechsdk = self._sdk()
        root_locale = self._locale(segments[0].get("language", "en"))
        voice_blocks: list[str] = []
        for seg in segments:
            language = seg.get("language", "en")
            text = seg.get("text", "")
            locale = self._locale(language)
            voice = self._voice(language)
            voice_blocks.append(
                f'<voice name="{_xml_escape(voice)}">'
                f'<lang xml:lang="{_xml_escape(locale)}">{_xml_escape(text)}</lang>'
                f"</voice>"
            )
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="{_xml_escape(root_locale)}">'
            + "".join(voice_blocks)
            + "</speak>"
        )
        try:
            config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.speech_region)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            # .get() blocks the calling thread — wait for it off the loop.
            future = synthesizer.speak_ssml_async(ssml)
            result = await asyncio.to_thread(future.get)
        except Exception as exc:
            logger.warning("Azure TTS segments failed: %r", exc)
            raise RuntimeError("Azure TTS failed") from exc
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return result.audio_data
        if result.reason == speechsdk.ResultReason.Canceled:
            logger.warning("Azure TTS segments canceled: %s", result.cancellation_details)
        raise RuntimeError("Azure TTS canceled")
