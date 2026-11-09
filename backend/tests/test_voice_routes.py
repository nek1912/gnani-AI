"""Tests for voice routes (transcribe and speak)."""

from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.voice_service import VoiceUnavailableError

client = TestClient(app)


def test_voice_routes_import():
    """Test that voice routes can be imported without errors."""
    from app.routes.voice import router, voice_service
    assert router is not None
    assert voice_service is not None


def test_transcribe_returns_503_when_no_providers():
    """Test that /voice/transcribe returns 503 when no voice providers are configured."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.speech_to_text = AsyncMock(side_effect=VoiceUnavailableError("No voice providers available"))
        r = client.post("/voice/transcribe", json={"audio": "dGVzdA==", "language": "en"})
        assert r.status_code == 503
        body = r.json()
        assert "No voice providers available" in body["detail"]


def test_speak_returns_503_when_no_providers():
    """Test that /voice/speak returns 503 when no voice providers are configured."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech = AsyncMock(side_effect=VoiceUnavailableError("No voice providers available"))
        r = client.post("/voice/speak", json={"text": "Hello world", "language": "en"})
        assert r.status_code == 503
        body = r.json()
        assert "No voice providers available" in body["detail"]


def test_transcribe_returns_503_when_all_providers_fail():
    """Test that /voice/transcribe returns 503 when all providers fail."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.speech_to_text = AsyncMock(side_effect=VoiceUnavailableError("No voice providers available"))
        r = client.post("/voice/transcribe", json={"audio": "dGVzdA==", "language": "en"})
        assert r.status_code == 503
        assert "No voice providers available" in r.json()["detail"]


def test_speak_returns_503_when_all_providers_fail():
    """Test that /voice/speak returns 503 when all providers fail."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech = AsyncMock(side_effect=VoiceUnavailableError("No voice providers available"))
        r = client.post("/voice/speak", json={"text": "Hello world", "language": "en"})
        assert r.status_code == 503
        assert "No voice providers available" in r.json()["detail"]


def test_transcribe_returns_text_on_success():
    """Test that /voice/transcribe returns transcribed text on success."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.speech_to_text = AsyncMock(return_value="recognized text")
        r = client.post("/voice/transcribe", json={"audio": "dGVzdA==", "language": "en"})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "recognized text"
        assert body["language"] == "en"


def test_speak_returns_audio_on_success():
    """Test that /voice/speak returns audio hex on success."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech = AsyncMock(return_value=b"\x00\x01\x02")
        r = client.post("/voice/speak", json={"text": "Hello world", "language": "en"})
        assert r.status_code == 200
        body = r.json()
        assert body["audio"] == "000102"
        assert body["language"] == "en"


def test_transcribe_default_language():
    """Test that /voice/transcribe defaults language to 'en'."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.speech_to_text = AsyncMock(return_value="text")
        r = client.post("/voice/transcribe", json={"audio": "dGVzdA=="})
        assert r.status_code == 200
        assert r.json()["language"] == "en"


def test_speak_default_language():
    """Test that /voice/speak defaults language to 'en'."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech = AsyncMock(return_value=b"\x00")
        r = client.post("/voice/speak", json={"text": "Hello"})
        assert r.status_code == 200
        assert r.json()["language"] == "en"


def test_speak_segments_endpoint():
    """POST /voice/speak with segments uses the multi-voice TTS path."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech_segments = AsyncMock(return_value=b"\x01audio")
        mock_vs.text_to_speech = AsyncMock(return_value=b"\x00")
        r = client.post(
            "/voice/speak",
            json={
                "text": "",
                "language": "en",
                "segments": [
                    {"text": "hello", "language": "en"},
                    {"text": "नमस्ते", "language": "hi"},
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["audio"] == b"\x01audio".hex()
        assert body["language"] == "en"
        mock_vs.text_to_speech_segments.assert_awaited_once()
        mock_vs.text_to_speech.assert_not_called()


def test_speak_plain_text_still_uses_single_voice():
    """A plain text POST still hits the single-voice text_to_speech path."""
    with patch("app.routes.voice.voice_service") as mock_vs:
        mock_vs.text_to_speech = AsyncMock(return_value=b"\x00\x01")
        mock_vs.text_to_speech_segments = AsyncMock(return_value=b"\x99")
        r = client.post("/voice/speak", json={"text": "Hello world", "language": "en"})
        assert r.status_code == 200
        assert r.json()["audio"] == "0001"
        mock_vs.text_to_speech.assert_awaited_once()
        mock_vs.text_to_speech_segments.assert_not_called()


def test_voice_chat_passes_speech_text_not_answer_to_tts():
    """The full voice pipeline must hand the citation-stripped speech_text to
    TTS, never the raw answer (which carries [chunk:ID] markers)."""
    captured = {}

    async def fake_tts(text, language):
        captured["text"] = text
        captured["language"] = language
        return b"\x01\x02"

    async def fake_stt(audio, language):
        return "Who is eligible under PMFBY?"

    with patch("app.routes.voice.chat_handler") as mock_chat, patch(
        "app.routes.voice.voice_service"
    ) as mock_vs:
        mock_chat.return_value = {
            "answer": "Farmers are eligible [chunk:aaaaaaaa].",
            "language": "en",
            "domain": "pmfby",
            "speech_text": "Farmers are eligible.",
            "abstained": False,
        }
        mock_vs.speech_to_text = AsyncMock(side_effect=fake_stt)
        mock_vs.text_to_speech = AsyncMock(side_effect=fake_tts)
        r = client.post(
            "/voice",
            files={"audio": ("a.wav", b"dummy", "audio/wav")},
            data={"language": "en-IN"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["audio_base64"] == "AQI="
    # TTS received the clean speech copy, NOT the marker-bearing answer.
    assert captured["text"] == "Farmers are eligible."
    assert "[chunk:" not in captured["text"]
    assert body["answer"] == "Farmers are eligible [chunk:aaaaaaaa]."
