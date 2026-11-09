"""Tests for voice service — Gnani-first STT and TTS, Sarvam/Azure fallback."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch
from app.services.voice_service import VoiceService, VoiceUnavailableError
from app.providers.gnani_voice import GnaniError


def test_voice_service_import():
    """Test that voice service can be imported without errors."""
    from app.services.voice_service import VoiceService, VoiceUnavailableError
    assert VoiceService is not None
    assert VoiceUnavailableError is not None


def test_voice_service_initialization():
    """Test that voice service initializes with provider objects."""
    service = VoiceService()
    assert hasattr(service, "_gnani_stt")
    assert hasattr(service, "_gnani_tts")
    assert hasattr(service, "_sarvam_stt")
    assert hasattr(service, "_sarvam_tts")
    assert hasattr(service, "_azure_stt")
    assert hasattr(service, "_azure_tts")


@pytest.mark.asyncio
async def test_stt_fallback_raises_when_all_providers_disabled():
    """Test that STT raises VoiceUnavailableError when all providers fail."""
    service = VoiceService()

    with patch.object(service._sarvam_stt, 'enabled', False):
        with patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock, side_effect=RuntimeError("Azure failed")):
            with pytest.raises(VoiceUnavailableError) as exc_info:
                await service.speech_to_text(b"test audio", "en")

            assert "No voice providers available" in str(exc_info.value)


@pytest.mark.asyncio
async def test_tts_raises_when_all_providers_disabled():
    """Test that TTS raises VoiceUnavailableError when all providers are disabled."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', False):
        with patch.object(service._sarvam_tts, 'enabled', False):
            with patch.object(service._azure_tts, 'enabled', False):
                with pytest.raises(VoiceUnavailableError) as exc_info:
                    await service.text_to_speech("Hello world", "en")

                assert "all failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_tts_gnani_priority_skips_sarvam_and_azure():
    """Test that TTS uses Gnani when it succeeds, skipping Sarvam and Azure."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, return_value=b"gnani audio"):
            with patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock) as mock_sarvam:
                with patch.object(service._azure_tts, 'text_to_speech', new_callable=AsyncMock) as mock_azure:
                    result = await service.text_to_speech("Hello world", "en")

                    assert result == b"gnani audio"
                    mock_sarvam.assert_not_called()
                    mock_azure.assert_not_called()


@pytest.mark.asyncio
async def test_tts_gnani_fails_falls_to_sarvam():
    """Test that TTS falls back to Sarvam when Gnani fails."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")):
            with patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, return_value=b"sarvam audio"):
                with patch.object(service._azure_tts, 'text_to_speech', new_callable=AsyncMock) as mock_azure:
                    result = await service.text_to_speech("Hello world", "en")

                    assert result == b"sarvam audio"
                    mock_azure.assert_not_called()


@pytest.mark.asyncio
async def test_tts_gnani_empty_falls_to_sarvam():
    """Test that TTS falls back to Sarvam when Gnani returns empty audio."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, return_value=b""):
            with patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, return_value=b"sarvam audio"):
                result = await service.text_to_speech("Hello world", "en")

                assert result == b"sarvam audio"


@pytest.mark.asyncio
async def test_tts_gnani_and_sarvam_fail_falls_to_azure():
    """Test that TTS falls back to Azure when Gnani and Sarvam fail."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")):
            with patch.object(service._sarvam_tts, 'enabled', True):
                with patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam failed")):
                    with patch.object(service._azure_tts, 'text_to_speech', new_callable=AsyncMock, return_value=b"azure audio"):
                        result = await service.text_to_speech("Hello world", "en")

                        assert result == b"azure audio"


@pytest.mark.asyncio
async def test_tts_all_providers_fail_raises_error():
    """Test that TTS raises VoiceUnavailableError when all fail."""
    service = VoiceService()

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'synthesize', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")):
            with patch.object(service._sarvam_tts, 'enabled', True):
                with patch.object(service._sarvam_tts, 'synthesize', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam failed")):
                    with patch.object(service._azure_tts, 'text_to_speech', new_callable=AsyncMock, side_effect=RuntimeError("Azure failed")):
                        with pytest.raises(VoiceUnavailableError) as exc_info:
                            await service.text_to_speech("Hello world", "en")

                        assert "all failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_tts_segments_gnani_priority():
    """Test that TTS segments uses Gnani when it succeeds."""
    service = VoiceService()
    segments = [{"text": "Hello", "language": "en"}]

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'text_to_speech_segments', new_callable=AsyncMock, return_value=b"gnani audio"):
            with patch.object(service._sarvam_tts, 'text_to_speech_segments', new_callable=AsyncMock) as mock_sarvam:
                with patch.object(service._azure_tts, 'text_to_speech_segments', new_callable=AsyncMock) as mock_azure:
                    result = await service.text_to_speech_segments(segments)

                    assert result == b"gnani audio"
                    mock_sarvam.assert_not_called()
                    mock_azure.assert_not_called()


@pytest.mark.asyncio
async def test_tts_segments_gnani_fails_falls_to_sarvam():
    """Test that TTS segments falls back to Sarvam when Gnani fails."""
    service = VoiceService()
    segments = [{"text": "Hello", "language": "en"}]

    with patch.object(service._gnani_tts, 'enabled', True):
        with patch.object(service._gnani_tts, 'text_to_speech_segments', new_callable=AsyncMock, side_effect=GnaniError("Gnani down")):
            with patch.object(service._sarvam_tts, 'text_to_speech_segments', new_callable=AsyncMock, return_value=b"sarvam audio"):
                result = await service.text_to_speech_segments(segments)

                assert result == b"sarvam audio"


@pytest.mark.asyncio
async def test_stt_sarvam_success_skips_azure():
    """Test that STT uses Sarvam when it succeeds, skipping Azure."""
    service = VoiceService()

    with patch.object(service._sarvam_stt, 'enabled', True):
        with patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock, return_value="sarvam result"):
            with patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock) as mock_azure:
                result = await service.speech_to_text(b"test audio", "en")

                assert result == "sarvam result"
                mock_azure.assert_not_called()


@pytest.mark.asyncio
async def test_stt_sarvam_fails_falls_back_to_azure():
    """Test that STT falls back to Azure when Sarvam fails."""
    service = VoiceService()

    with patch.object(service._sarvam_stt, 'enabled', True):
        with patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam failed")):
            with patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock, return_value="azure result"):
                result = await service.speech_to_text(b"test audio", "en")

                assert result == "azure result"


@pytest.mark.asyncio
async def test_stt_sarvam_disabled_falls_back_to_azure():
    """Test that STT falls back to Azure when Sarvam is disabled."""
    service = VoiceService()

    with patch.object(service._sarvam_stt, 'enabled', False):
        with patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock, return_value="azure result"):
            result = await service.speech_to_text(b"test audio", "en")

            assert result == "azure result"


@pytest.mark.asyncio
async def test_stt_all_providers_fail():
    """Test that STT raises VoiceUnavailableError when all providers fail."""
    service = VoiceService()

    with patch.object(service._sarvam_stt, 'enabled', True):
        with patch.object(service._sarvam_stt, 'transcribe', new_callable=AsyncMock, side_effect=RuntimeError("Sarvam failed")):
            with patch.object(service._azure_stt, 'speech_to_text', new_callable=AsyncMock, side_effect=RuntimeError("Azure failed")):
                with pytest.raises(VoiceUnavailableError) as exc_info:
                    await service.speech_to_text(b"test audio", "en")

                assert "No voice providers available" in str(exc_info.value)


def test_voice_unavailable_error_is_exception():
    """Test that VoiceUnavailableError is a proper exception."""
    error = VoiceUnavailableError("test message")
    assert isinstance(error, Exception)
    assert str(error) == "test message"
