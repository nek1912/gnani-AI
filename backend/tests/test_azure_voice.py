"""Tests for AzureVoiceProvider multi-voice SSML TTS (text_to_speech_segments).

All provider calls route through a fake speechsdk injected via monkeypatch on
``_sdk`` — no real Azure SDK required in the test environment.
"""
import pytest
from unittest.mock import MagicMock

from app.providers.azure_voice import AzureVoiceProvider


_COMPLETED = "SynthesizingAudioCompleted"
_CANCELED = "Canceled"


def _make_fake_speechsdk():
    captured = {}

    class _Result:
        reason = _COMPLETED
        audio_data = b"WAV"

    class _Synthesizer:
        def __init__(self, speech_config=None, audio_config=None):
            captured["config"] = speech_config

        def speak_ssml_async(self, ssml):
            captured["ssml"] = ssml

            class _Future:
                def get(self):
                    return _Result()

            return _Future()

    class _SpeechConfig:
        def __init__(self, subscription=None, region=None):
            pass

    class _ResultReason:
        SynthesizingAudioCompleted = _COMPLETED
        Canceled = _CANCELED

    class _SDK:
        ResultReason = _ResultReason
        SpeechConfig = _SpeechConfig
        SpeechSynthesizer = _Synthesizer
        audio = MagicMock()

    return _SDK, captured


class _SettingsStub:
    azure_speech_key = "x"
    azure_speech_region = "centralindia"
    speech_locales = {}
    tts_voices = {}


@pytest.mark.asyncio
async def test_azure_tts_segments_builds_ssml():
    provider = AzureVoiceProvider()
    provider._settings = _SettingsStub()
    provider.speech_key = "x"
    provider.enabled = True
    fake, captured = _make_fake_speechsdk()
    provider._sdk = lambda: fake

    result = await provider.text_to_speech_segments(
        [{"text": "hi", "language": "en"}, {"text": "नमस्ते", "language": "hi"}]
    )

    assert result == b"WAV"
    ssml = captured["ssml"]
    assert ssml.count("<voice") == 2
    assert "xml:lang" in ssml
    assert "<speak" in ssml and "xml:lang=" in ssml.split(">", 1)[0]


@pytest.mark.asyncio
async def test_azure_tts_segments_empty_raises():
    provider = AzureVoiceProvider()
    provider._settings = _SettingsStub()
    provider.speech_key = "x"
    provider.enabled = True

    with pytest.raises(RuntimeError):
        await provider.text_to_speech_segments([])


@pytest.mark.asyncio
async def test_azure_tts_segments_not_configured_raises():
    provider = AzureVoiceProvider()
    provider._settings = _SettingsStub()
    provider.speech_key = ""
    provider.enabled = False

    with pytest.raises(RuntimeError):
        await provider.text_to_speech_segments([{"text": "hi", "language": "en"}])
