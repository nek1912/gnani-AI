"""Gnani AI voice provider — Prisma v3.0 STT + Timbre v3.0 TTS.

Gnani Vachana API (https://api.vachana.ai) provides speech intelligence for
Indian languages.  This module is a drop-in provider for JanSahay's voice
fallback chain:

    STT:   Gnani Prisma v3.0 → Sarvam → Azure → VoiceUnavailableError
    TTS:   Gnani Timbre v3.0 → Sarvam → VoiceUnavailableError

Provider responsibilities are limited to speech↔text conversion.  No
retrieval, evidence, citation, or answer logic lives here — Gnani never
generates factual claims.

Authentication: ``X-API-Key-ID`` header carrying ``GNANI_API_KEY``.
The key is read server-side only and is never logged or exposed to the
frontend.

STT (Prisma v3.0)
    POST https://api.vachana.ai/stt/v3
    multipart/form-data: audio_file, model=prisma-v3.0, language_code
    → JSON {success, transcript, model, detected_language_code, processing_time, ...}
    Max audio: 30 seconds.  10 languages (bn, en, gu, hi, kn, ml, mr, pa, ta, te — no Odia).

TTS (Timbre v3.0)
    POST https://api.vachana.ai/api/v1/tts/inference
    JSON body {text, voice, model=timbre-v3.0, language, speed, audio_config}
    → raw binary audio (WAV).  Same 10 languages, no Odia.

Language codes map JanSahay's short codes (en/hi/gu/…) to Gnani's BCP-47
codes (en-IN/hi-IN/gu-IN/…).  ``indic-auto`` enables automatic language
detection on STT.  When the requested language is unsupported by Gnani
(Odia), the provider reports itself as unavailable so the existing fallback
chain handles it.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import os
import re
import struct
import time
import uuid
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Gnani Vachana API endpoints ──────────────────────────────────────────
_GNANI_STT_URL = "https://api.vachana.ai/stt/v3"
_GNANI_TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

# ── Models ───────────────────────────────────────────────────────────────
STT_MODEL = "prisma-v3.0"
TTS_MODEL = "timbre-v3.0"

# ── Defaults (overridable via Settings) ──────────────────────────────────
_DEFAULT_TTS_VOICE = "Shivani"
_DEFAULT_TTS_SPEED = 1.0
_DEFAULT_TTS_SAMPLE_RATE = 22050
_DEFAULT_STT_FORMAT = "verbatim"

# ── Gnani-supported language codes (BCP-47) ──────────────────────────────
# JanSahay short code → Gnani BCP-47 code.  Odia ("or") is intentionally
# absent: Gnani Timbre/Prisma do not support Odia, so it falls back to
# Sarvam/Azure through VoiceService.
_GNANI_LANG_MAP: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "gu": "gu-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "pa": "pa-IN",
    "ml": "ml-IN",
}

# Timbre v3.0 voices — each speaks all 10 Gnani languages.
_GNANI_TTS_VOICES_V30 = {
    "Avinash", "Shivani", "Lakshmi", "Kalpana", "Shubham", "Prakash",
    "Devansh", "Yashraj", "Chetana", "Vasudha", "Riyaa", "Tarika", "Harshad",
}

# Timbre v2.5 voices — standard catalog.
_GNANI_TTS_VOICES_V25 = {
    "Nalini", "Bhavna", "Yashvi", "Urmila", "Jwala", "Chitra", "Ambuja",
    "Deepak", "Roopesh", "Vikrant", "Hemraj", "Jalaj", "Omkar", "Kaveri",
    "Trupti", "Devika", "Pranav", "Shlok", "Girish", "Asmita", "Trisha",
    "Brinda", "Vedika", "Noopur", "Suhana", "Lehara", "Lavanya", "Yukti",
    "Varuni", "Saanvi", "Kavin", "Reshma", "Riyaan", "Zahira", "Ishaan",
    "Kirra", "Dhruva", "Falak", "Veera", "Mehuli", "Zayan", "Poorvi",
}

_GNANI_TTS_VOICES = _GNANI_TTS_VOICES_V30 | _GNANI_TTS_VOICES_V25

# ── In-memory LRU audio cache for TTS (<1ms instant replay) ───────────────
_TTS_CACHE_MAX_SIZE = 256
_tts_cache: OrderedDict[str, bytes] = OrderedDict()
_tts_cache_lock = asyncio.Lock()

# Gnani API explicitly enforces strictly 1 active in-flight request per API key.
# A global request lock ensures requests are never sent concurrently, preventing HTTP 429:
# "Only 1 active request is allowed at a time. Wait for your current request to finish before sending another."
_gnani_tts_request_lock = asyncio.Lock()


def _get_cache_key(text: str, language: str, voice: str, speed: float) -> str:
    key_str = f"{text.strip().lower()}:{language.strip().lower()}:{voice}:{speed:.2f}"
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def clear_tts_cache() -> None:
    """Clear in-memory TTS audio cache."""
    _tts_cache.clear()

# ── WAV format & text chunking helpers ───────────────────────────────────
_WAV_HEADER_SIZE = 44


def _strip_wav_header(data: bytes) -> bytes:
    """Strip the RIFF/WAV header if present, returning only raw PCM samples."""
    if len(data) > _WAV_HEADER_SIZE and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        data_pos = data.find(b"data")
        if data_pos != -1 and data_pos + 8 <= len(data):
            return data[data_pos + 8 :]
        return data[_WAV_HEADER_SIZE:]
    return data


def _build_wav_header(
    pcm_size: int,
    sample_rate: int = 22050,
    num_channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Construct a standard 44-byte RIFF/WAV header for PCM audio."""
    byte_rate = sample_rate * num_channels * sample_width
    block_align = num_channels * sample_width
    bits_per_sample = sample_width * 8
    total_size = 36 + pcm_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        total_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        pcm_size,
    )


def _chunk_text_for_gnani(text: str, max_chars: int = 500) -> list[str]:
    """Split text into sentence-aware chunks of max_chars length.

    Gnani API inference nodes can fail or return 500/503 on texts exceeding
    ~1500-2000 chars. Chunking ensures each request stays within safe limits.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts = re.split(r"([.?!|\n।]+)", text)
    chunks: list[str] = []
    current_chunk = ""

    i = 0
    while i < len(parts):
        piece = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2
        sentence = piece + sep
        if not sentence.strip():
            continue

        if len(current_chunk) + len(sentence) <= max_chars:
            current_chunk += sentence
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            if len(sentence) > max_chars:
                words = sentence.split(" ")
                sub_chunk = ""
                for w in words:
                    if len(sub_chunk) + len(w) + 1 <= max_chars:
                        sub_chunk += (" " if sub_chunk else "") + w
                    else:
                        if sub_chunk.strip():
                            chunks.append(sub_chunk.strip())
                        sub_chunk = w
                current_chunk = sub_chunk
            else:
                current_chunk = sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text[:max_chars]]



def _gnani_lang_code(language: str) -> str:
    """Map JanSahay short code ('hi') → Gnani BCP-47 ('hi-IN')."""
    if language in _GNANI_LANG_MAP:
        return _GNANI_LANG_MAP[language]
    if language in _GNANI_LANG_MAP.values():
        return language
    # Unknown language — caller must treat Gnani as unavailable.
    return ""


def _gnani_supports_language(language: str) -> bool:
    """True when Gnani can handle the given JanSahay language code."""
    return _gnani_lang_code(language) != ""


def _normalize_lang_short(code: str) -> str:
    """Normalize language code ('hi-IN', 'hi', etc.) to JanSahay short code ('hi')."""
    if not code:
        return "en"
    clean = code.strip().lower()
    if "-" in clean:
        clean = clean.split("-")[0]
    return clean


def _normalize_lang_bcp47(code: str) -> str:
    """Normalize JanSahay short code ('hi') or BCP-47 to standard BCP-47 ('hi-IN')."""
    if not code:
        return "en-IN"
    clean = code.strip()
    if clean in _GNANI_LANG_MAP:
        return _GNANI_LANG_MAP[clean]
    if clean in _GNANI_LANG_MAP.values():
        return clean
    if "-" not in clean and len(clean) == 2:
        return f"{clean}-IN"
    return clean


def _estimate_audio_duration_s(audio_bytes: bytes) -> float:
    """Estimate audio duration in seconds from WAV header or byte length."""
    if len(audio_bytes) >= 44 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        try:
            byte_rate = struct.unpack("<I", audio_bytes[28:32])[0]
            if byte_rate > 0:
                data_pos = audio_bytes.find(b"data")
                if data_pos != -1 and data_pos + 8 <= len(audio_bytes):
                    declared_size = struct.unpack("<I", audio_bytes[data_pos + 4 : data_pos + 8])[0]
                    pcm_len = declared_size if declared_size > 0 else (len(audio_bytes) - (data_pos + 8))
                else:
                    pcm_len = len(audio_bytes) - 44
                return pcm_len / float(byte_rate)
        except Exception:
            pass
    # Fallback heuristic: 16kHz, 16-bit, mono = 32000 bytes/sec
    return len(audio_bytes) / 32000.0


# ── Exceptions ───────────────────────────────────────────────────────────


class GnaniError(RuntimeError):
    """Base error for Gnani provider failures."""


class GnaniAuthenticationError(GnaniError):
    """401/403 — invalid or missing API key."""


class GnaniRateLimitedError(GnaniError):
    """429 — too many requests."""


class GnaniServiceUnavailableError(GnaniError):
    """503 — provider temporarily unavailable."""


class GnaniTimeoutError(GnaniError):
    """Request timed out."""


class GnaniAudioDurationExceededError(GnaniError):
    """Audio duration exceeds the 30-second Gnani limit."""


# ── Result Contracts with Metadata & Drop-In Compatibility ──────────────────


class STTResult(str):
    """Transcribed text string with attached provider & observability metadata.

    Subclasses str so existing code expecting `str` works without changes
    (`isinstance(res, str) is True`, `res == "text"`), while also exposing
    rich metadata attributes (`res.provider`, `res.detected_language`, etc.).
    """

    text: str
    language: str
    requested_language: str
    detected_language: Optional[str]
    provider: str
    model: Optional[str]
    duration_ms: float
    fallback_occurred: bool
    error_category: Optional[str]

    def __new__(
        cls,
        text: str,
        language: str = "en",
        requested_language: str = "en",
        detected_language: Optional[str] = None,
        provider: str = "gnani",
        model: Optional[str] = None,
        duration_ms: float = 0.0,
        fallback_occurred: bool = False,
        error_category: Optional[str] = None,
    ):
        instance = super().__new__(cls, text)
        instance.text = text
        instance.language = language
        instance.requested_language = requested_language
        instance.detected_language = detected_language
        instance.provider = provider
        instance.model = model
        instance.duration_ms = duration_ms
        instance.fallback_occurred = fallback_occurred
        instance.error_category = error_category
        return instance

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "requested_language": self.requested_language,
            "detected_language": self.detected_language,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": round(self.duration_ms, 2),
            "fallback_occurred": self.fallback_occurred,
            "error_category": self.error_category,
        }


class TTSResult(bytes):
    """Synthesized audio bytes with attached provider & observability metadata.

    Subclasses bytes so existing code expecting `bytes` works without changes
    (`isinstance(res, bytes) is True`, `res.hex()`), while also exposing
    rich metadata attributes (`res.provider`, `res.voice`, `res.speed`, etc.).
    """

    audio: bytes
    language: str
    provider: str
    model: Optional[str]
    voice: Optional[str]
    speed: Optional[float]
    duration_ms: float
    audio_format: str
    fallback_occurred: bool
    error_category: Optional[str]

    def __new__(
        cls,
        audio: bytes,
        language: str = "en",
        provider: str = "gnani",
        model: Optional[str] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        duration_ms: float = 0.0,
        audio_format: str = "wav",
        fallback_occurred: bool = False,
        error_category: Optional[str] = None,
    ):
        instance = super().__new__(cls, audio)
        instance.audio = audio
        instance.language = language
        instance.provider = provider
        instance.model = model
        instance.voice = voice
        instance.speed = speed
        instance.duration_ms = duration_ms
        instance.audio_format = audio_format
        instance.fallback_occurred = fallback_occurred
        instance.error_category = error_category
        return instance

    def to_dict(self) -> dict:
        return {
            "audio": self.hex(),
            "language": self.language,
            "provider": self.provider,
            "model": self.model,
            "voice": self.voice,
            "speed": self.speed,
            "duration_ms": round(self.duration_ms, 2),
            "audio_format": self.audio_format,
            "fallback_occurred": self.fallback_occurred,
            "error_category": self.error_category,
        }


# ── Providers ────────────────────────────────────────────────────────────


class GnaniSTTProvider:
    """Gnani Prisma v3.0 speech-to-text provider.

    Uses ``indic-auto`` language detection when no explicit language is
    supported, falling back to the caller's language code otherwise.
    Returns the transcript string (empty string when no speech detected).
    """

    def __init__(self, settings=None, api_key: Optional[str] = None):
        self._settings = settings or get_settings()
        self.api_key = api_key or self._settings.gstn_api_key
        self.enabled = bool(self.api_key)
        self.timeout_s = float(self._settings.gstn_stt_timeout_s or 30.0)
        self.output_format = self._settings.gstn_stt_output_format or _DEFAULT_STT_FORMAT
        self.auto_detect = bool(self._settings.gstn_stt_auto_detect)
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(
            "Gnani STT (Prisma v3.0) %s",
            "enabled" if self.enabled else "disabled (no GNANI_API_KEY)",
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Return persistent HTTP client with keep-alive connection pooling to eliminate TCP/TLS latency."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=60.0,
            )
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s),
                limits=limits,
            )
        return self._client

    async def aclose(self):
        """Clean up underlying HTTP connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def transcribe(self, audio_bytes: bytes, language: str = "en") -> STTResult:
        """Transcribe audio bytes to text with observability metadata.

        Returns STTResult (subclass of str) containing the transcript string,
        detected language, provider, model, latency (ms), and fallback status.
        Raises GnaniError on provider failure so VoiceService can fall through.
        """
        if not self.enabled:
            raise GnaniError("Gnani STT not configured (missing GNANI_API_KEY)")

        if not audio_bytes:
            return STTResult(
                "",
                language=language,
                requested_language=language,
                detected_language=None,
                provider="gnani",
                model=STT_MODEL,
                duration_ms=0.0,
                fallback_occurred=False,
            )

        if language in ("auto", "indic-auto"):
            request_lang = "indic-auto"
        else:
            lang_code = _gnani_lang_code(language)
            if not lang_code:
                # Language not supported by Gnani (e.g. Odia) — signal unavailability
                # so the fallback chain tries Sarvam/Azure instead.
                raise GnaniError(f"Gnani STT does not support language: {language}")
            request_lang = "indic-auto" if self.auto_detect else lang_code

        start_time = time.perf_counter()
        max_attempts = 3
        client = self._get_client()
        for attempt in range(max_attempts):
            request_id = str(uuid.uuid4())
            headers = {
                "X-API-Key-ID": self.api_key,
                "X-API-Request-ID": request_id,
            }
            try:
                resp = await client.post(
                    _GNANI_STT_URL,
                    headers=headers,
                    data={
                        "model": STT_MODEL,
                        "language_code": request_lang,
                        "format": self.output_format,
                    },
                    files={"audio_file": ("audio.wav", audio_bytes, "audio/wav")},
                )
                body = resp.text

                # ── Retry transient errors ──
                if resp.status_code in (500, 502, 503, 504, 429) and attempt < max_attempts - 1:
                    backoff = 0.25 * (2**attempt)
                    logger.warning(
                        "Gnani STT transient HTTP %d on attempt %d/%d (req=%s); retrying in %.2fs",
                        resp.status_code,
                        attempt + 1,
                        max_attempts,
                        request_id,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                # ── Authentication / rate-limit errors (flat envelope) ──
                if resp.status_code in (401, 403, 429):
                    _log_gnani_error(resp.status_code, body, "STT")
                    if resp.status_code == 429:
                        raise GnaniRateLimitedError(
                            f"Gnani STT rate limited (HTTP {resp.status_code})"
                        )
                    raise GnaniAuthenticationError(
                        f"Gnani STT authentication failed (HTTP {resp.status_code})"
                    )

                if resp.status_code == 503:
                    _log_gnani_error(resp.status_code, body, "STT")
                    raise GnaniServiceUnavailableError(
                        f"Gnani STT unavailable (HTTP {resp.status_code})"
                    )

                if resp.status_code >= 400:
                    _log_gnani_error(resp.status_code, body, "STT")
                    try:
                        err_data = json.loads(body)
                        err_type = err_data.get("error", {}).get("type", "")
                        if err_type == "MAX_AUDIO_DURATION_EXCEEDED" or "exceeds maximum allowed duration" in body:
                            raise GnaniAudioDurationExceededError(
                                f"Gnani STT audio duration exceeded: {body[:200]}"
                            )
                    except (json.JSONDecodeError, ValueError):
                        pass
                    raise GnaniError(
                        f"Gnani STT request failed (HTTP {resp.status_code}): {body[:200]}"
                    )

                if resp.status_code != 200:
                    _log_gnani_error(resp.status_code, body, "STT")
                    raise GnaniError(
                        f"Gnani STT unexpected status {resp.status_code}: {body[:200]}"
                    )

                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise GnaniError(
                        f"Gnani STT malformed JSON response: {exc}"
                    ) from exc

                if not data.get("success", False):
                    err = data.get("error", {})
                    err_type = err.get("type", "unknown")
                    if err_type == "MAX_AUDIO_DURATION_EXCEEDED":
                        raise GnaniAudioDurationExceededError(
                            f"Gnani STT audio duration exceeded: {err.get('message', '')}"
                        )
                    raise GnaniError(
                        f"Gnani STT returned success=false: "
                        f"type={err_type} "
                        f"message={err.get('message', 'no message')}"
                    )

                duration_ms = (time.perf_counter() - start_time) * 1000
                transcript = data.get("transcript", "") or ""
                detected = data.get("detected_language_code")
                norm_detected = _normalize_lang_short(detected) if detected else None
                model = data.get("model", STT_MODEL)

                # When auto-detect is enabled or requested, use detected language
                effective_lang = (
                    norm_detected
                    if (self.auto_detect or language in ("auto", "indic-auto")) and norm_detected
                    else _normalize_lang_short(language)
                )

                logger.info(
                    "Gnani STT success: model=%s req_lang=%s detected_lang=%s eff_lang=%s duration_ms=%.1f transcript_len=%d",
                    model,
                    language,
                    norm_detected,
                    effective_lang,
                    duration_ms,
                    len(transcript),
                )
                if not transcript:
                    logger.info(
                        "Gnani STT returned empty transcript (no speech detected): model=%s req_lang=%s eff_lang=%s raw_resp=%s",
                        model,
                        language,
                        effective_lang,
                        body[:150],
                    )
                return STTResult(
                    transcript,
                    language=effective_lang,
                    requested_language=language,
                    detected_language=norm_detected,
                    provider="gnani",
                    model=model,
                    duration_ms=duration_ms,
                    fallback_occurred=False,
                )
            except (GnaniAuthenticationError, GnaniRateLimitedError, GnaniServiceUnavailableError, GnaniError):
                raise
            except asyncio.TimeoutError as exc:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.25)
                    continue
                raise GnaniTimeoutError(
                    f"Gnani STT timed out after {self.timeout_s}s"
                ) from exc
            except httpx.RequestError as exc:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.25)
                    continue
                raise GnaniError(f"Gnani STT network error: {exc}") from exc


class GnaniTTSProvider:
    """Gnani Timbre v3.0 / v2.5 text-to-speech provider.

    Returns raw binary audio bytes (WAV).  Raises GnaniError on
    failure so VoiceService falls through to Sarvam.
    """

    def __init__(
        self,
        settings=None,
        api_key: Optional[str] = None,
        use_cache: Optional[bool] = None,
    ):
        self._settings = settings or get_settings()
        self.api_key = api_key or self._settings.gstn_api_key
        self.enabled = bool(self.api_key)
        self.timeout_s = float(self._settings.gstn_tts_timeout_s or 30.0)
        self.model = getattr(self._settings, "gstn_tts_model", TTS_MODEL) or TTS_MODEL
        self.voice = self._settings.gstn_tts_voice or _DEFAULT_TTS_VOICE
        self.speed = float(
            getattr(self._settings, "gstn_tts_speed", _DEFAULT_TTS_SPEED)
            or _DEFAULT_TTS_SPEED
        )
        self.sample_rate = _DEFAULT_TTS_SAMPLE_RATE
        self.container = "wav"
        self._client: Optional[httpx.AsyncClient] = None
        self.use_cache = (
            use_cache
            if use_cache is not None
            else (not bool(os.environ.get("PYTEST_CURRENT_TEST")))
        )
        logger.info(
            "Gnani TTS (%s) %s — voice=%s speed=%s container=%s use_cache=%s",
            self.model,
            "enabled" if self.enabled else "disabled (no GNANI_API_KEY)",
            self.voice,
            self.speed,
            self.container,
            self.use_cache,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Return persistent HTTP client with keep-alive connection pooling to eliminate TCP/TLS latency."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=60.0,
            )
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s),
                limits=limits,
            )
        return self._client

    async def aclose(self):
        """Clean up underlying HTTP connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def _synthesize_chunk(
        self,
        client: httpx.AsyncClient,
        text: str,
        lang_code: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> bytes:
        """Synthesize a single text chunk with exponential backoff for transient 503/500/502/504/429 errors."""
        selected_voice = voice or self.voice
        selected_speed = float(speed if speed is not None else self.speed)
        payload = {
            "text": text,
            "voice": selected_voice,
            "model": self.model,
            "language": lang_code,
            "speed": selected_speed,
            "audio_config": {
                "sample_rate": self.sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": self.container,
            },
        }

        headers = {
            "X-API-Key-ID": self.api_key,
            "Content-Type": "application/json",
            "X-API-Request-ID": str(uuid.uuid4()),
        }

        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with _gnani_tts_request_lock:
                    resp = await client.post(
                        _GNANI_TTS_URL, headers=headers, json=payload
                    )
                body = resp.content

                # Transient server errors: 503 (Service Unavailable), 502, 504, 500
                # Official Gnani docs recommend exponential backoff.
                if resp.status_code in (500, 502, 503, 504):
                    if attempt < max_retries - 1:
                        backoff = 0.25 * (2**attempt)
                        logger.warning(
                            "Gnani TTS HTTP %d on attempt %d/%d; retrying in %.2fs...",
                            resp.status_code,
                            attempt + 1,
                            max_retries,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                # Rate limiting (429) backoff: Gnani API allows only 1 active request at a time.
                # If an external request is in-flight, wait at least 1.25s for it to finish.
                if resp.status_code == 429:
                    if attempt < max_retries - 1:
                        backoff = 1.25 * (2**attempt)
                        logger.warning(
                            "Gnani TTS HTTP 429 on attempt %d/%d; waiting %.2fs for active request to finish...",
                            attempt + 1,
                            max_retries,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    try:
                        err = json.loads(body)
                        msg = err.get("detail", {}).get("message", "")
                    except (json.JSONDecodeError, ValueError):
                        msg = body.decode("utf-8", errors="replace")[:200]
                    _log_gnani_error(resp.status_code, msg, "TTS")
                    raise GnaniRateLimitedError(
                        f"Gnani TTS rate limited (HTTP {resp.status_code})"
                    )

                # Authentication errors (401, 403)
                if resp.status_code in (401, 403):
                    try:
                        err = json.loads(body)
                        msg = err.get("detail", {}).get("message", "")
                    except (json.JSONDecodeError, ValueError):
                        msg = body.decode("utf-8", errors="replace")[:200]
                    _log_gnani_error(resp.status_code, msg, "TTS")
                    raise GnaniAuthenticationError(
                        f"Gnani TTS authentication failed (HTTP {resp.status_code})"
                    )

                # Service unavailable (503) after retries exhausted
                if resp.status_code == 503:
                    try:
                        err = json.loads(body)
                        msg = err.get("error", {}).get("message", str(body[:200]))
                    except (json.JSONDecodeError, ValueError):
                        msg = body.decode("utf-8", errors="replace")[:200]
                    _log_gnani_error(resp.status_code, msg, "TTS")
                    raise GnaniServiceUnavailableError(
                        f"Gnani TTS unavailable (HTTP {resp.status_code})"
                    )

                if resp.status_code >= 400:
                    try:
                        err = json.loads(body)
                        msg = err.get("message", str(body[:200]))
                    except (json.JSONDecodeError, ValueError):
                        msg = body.decode("utf-8", errors="replace")[:200]
                    _log_gnani_error(resp.status_code, msg, "TTS")
                    raise GnaniError(
                        f"Gnani TTS request failed (HTTP {resp.status_code}): {msg}"
                    )

                if resp.status_code != 200:
                    _log_gnani_error(
                        resp.status_code,
                        body.decode("utf-8", errors="replace")[:200],
                        "TTS",
                    )
                    raise GnaniError(
                        f"Gnani TTS unexpected status {resp.status_code}"
                    )

                audio_bytes = bytes(body)
                if not audio_bytes:
                    raise GnaniError("Gnani TTS returned empty audio")

                return audio_bytes

            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                if attempt < max_retries - 1:
                    backoff = 0.25 * (2**attempt)
                    logger.warning(
                        "Gnani TTS timeout on attempt %d/%d; retrying in %.2fs...",
                        attempt + 1,
                        max_retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise GnaniTimeoutError(
                    f"Gnani TTS timed out after {self.timeout_s}s"
                ) from exc
            except httpx.RequestError as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.25)
                    continue
                raise GnaniError(f"Gnani TTS network error: {exc}") from exc

        raise GnaniServiceUnavailableError("Gnani TTS unavailable after retries")

    async def synthesize(
        self,
        text: str,
        language: str = "hi",
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> TTSResult:
        """Synthesize text to speech audio bytes with observability metadata.

        Returns TTSResult (subclass of bytes) in WAV format with attached
        metadata (provider, model, voice, speed, duration_ms). Raises GnaniError on failure.
        """
        if not self.enabled:
            raise GnaniError("Gnani TTS not configured (missing GNANI_API_KEY)")

        selected_voice = voice or self.voice
        if selected_voice not in _GNANI_TTS_VOICES:
            raise GnaniError(
                f"Unsupported voice '{selected_voice}'. Supported voices: {sorted(_GNANI_TTS_VOICES)}"
            )

        selected_speed = float(speed if speed is not None else self.speed)
        if not (0.5 <= selected_speed <= 2.0):
            raise GnaniError(f"Speed must be between 0.5 and 2.0, got {selected_speed}")

        text = text.strip()
        if not text:
            return TTSResult(
                b"",
                language=language,
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        lang_code = _gnani_lang_code(language)
        if not lang_code:
            raise GnaniError(f"Gnani TTS does not support language: {language}")

        chunks = _chunk_text_for_gnani(text, max_chars=500)
        if not chunks:
            return TTSResult(
                b"",
                language=language,
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        start_time = time.perf_counter()

        # ── Check in-memory LRU audio cache for instant (<1ms) replay ──
        cache_key = _get_cache_key(text, language, selected_voice, selected_speed)
        if self.use_cache:
            async with _tts_cache_lock:
                cached_audio = _tts_cache.get(cache_key)
                if cached_audio is not None:
                    _tts_cache.move_to_end(cache_key)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        "Gnani TTS cache hit: lang=%s voice=%s duration_ms=%.2f bytes=%d",
                        language,
                        selected_voice,
                        duration_ms,
                        len(cached_audio),
                    )
                    return TTSResult(
                        cached_audio,
                        language=language,
                        provider="gnani",
                        model=self.model,
                        voice=selected_voice,
                        speed=selected_speed,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=False,
                    )

        client = self._get_client()
        # Cap chunks to max 2 (~1000 chars) to prevent excessive sequential latency on large answers
        if len(chunks) > 2:
            logger.info("Gnani TTS bounding %d chunks to 2 for voice playback latency", len(chunks))
            chunks = chunks[:2]

        if len(chunks) == 1:
            audio = await self._synthesize_chunk(
                client, chunks[0], lang_code, voice=selected_voice, speed=selected_speed
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Gnani TTS success: lang=%s voice=%s speed=%.1f duration_ms=%.1f audio_bytes=%d",
                lang_code,
                selected_voice,
                selected_speed,
                duration_ms,
                len(audio),
            )
            stitched_audio = audio
        else:
            # Gnani API strictly enforces 1 active in-flight request at a time.
            # Multi-chunks are synthesized sequentially to respect this limit and prevent HTTP 429.
            pcm_parts: list[bytes] = []
            for ch in chunks:
                raw = await self._synthesize_chunk(
                    client, ch, lang_code, voice=selected_voice, speed=selected_speed
                )
                pcm_parts.append(_strip_wav_header(raw))

            full_pcm = b"".join(pcm_parts)
            header = _build_wav_header(
                len(full_pcm),
                sample_rate=self.sample_rate,
                num_channels=1,
                sample_width=2,
            )
            stitched_audio = header + full_pcm
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Gnani TTS multi-chunk success: chunks=%d lang=%s voice=%s speed=%.1f duration_ms=%.1f audio_bytes=%d",
                len(chunks),
                lang_code,
                selected_voice,
                selected_speed,
                duration_ms,
                len(stitched_audio),
            )

        # Store in LRU cache
        if self.use_cache:
            async with _tts_cache_lock:
                if len(_tts_cache) >= _TTS_CACHE_MAX_SIZE:
                    _tts_cache.popitem(last=False)
                _tts_cache[cache_key] = stitched_audio

        return TTSResult(
            stitched_audio,
            language=language,
            provider="gnani",
            model=self.model,
            voice=selected_voice,
            speed=selected_speed,
            duration_ms=duration_ms,
            audio_format="wav",
            fallback_occurred=False,
        )

    async def text_to_speech_segments(
        self,
        segments: list[dict],
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> TTSResult:
        """Synthesize multiple text segments into one audio blob with metadata.

        Preserves each segment's language, chunks if necessary, and stitches
        cleanly into a single WAV audio.
        """
        selected_voice = voice or self.voice
        if selected_voice not in _GNANI_TTS_VOICES:
            raise GnaniError(
                f"Unsupported voice '{selected_voice}'. Supported voices: {sorted(_GNANI_TTS_VOICES)}"
            )
        selected_speed = float(speed if speed is not None else self.speed)
        if not (0.5 <= selected_speed <= 2.0):
            raise GnaniError(f"Speed must be between 0.5 and 2.0, got {selected_speed}")

        if not segments:
            return TTSResult(
                b"",
                language="hi",
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        valid_segments = [s for s in segments if s.get("text", "").strip()]
        if not valid_segments:
            return TTSResult(
                b"",
                language="hi",
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        start_time = time.perf_counter()

        # Check LRU cache first for instant retrieval (<1ms)
        cache_key = (
            tuple((s.get("language", "hi"), s.get("text", "").strip()) for s in valid_segments),
            selected_voice,
            round(selected_speed, 2),
        )
        if self.use_cache:
            async with _tts_cache_lock:
                if cache_key in _tts_cache:
                    cached_audio = _tts_cache[cache_key]
                    _tts_cache.move_to_end(cache_key)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        "Gnani TTS segments cache hit: segments=%d duration_ms=%.1f",
                        len(valid_segments),
                        duration_ms,
                    )
                    return TTSResult(
                        cached_audio,
                        language=valid_segments[0].get("language", "hi"),
                        provider="gnani",
                        model=self.model,
                        voice=selected_voice,
                        speed=selected_speed,
                        duration_ms=duration_ms,
                        audio_format="wav",
                        fallback_occurred=False,
                    )

        # Partition runs of same language
        runs: list[dict] = []
        for s in valid_segments:
            lang = s.get("language", "hi")
            text = s.get("text", "").strip()
            if runs and runs[-1]["language"] == lang:
                runs[-1]["text"] += " " + text
            else:
                runs.append({"language": lang, "text": text})

        client = self._get_client()
        tasks: list[tuple[str, str]] = []  # (chunk_text, lang_code)
        for run in runs:
            lang_code = _gnani_lang_code(run["language"])
            if not lang_code:
                logger.warning(
                    "Gnani unsupported language %s in segment; defaulting to hi-IN",
                    run["language"],
                )
                lang_code = "hi-IN"

            chunks = _chunk_text_for_gnani(run["text"], max_chars=500)
            for ch in chunks:
                tasks.append((ch, lang_code))

        if not tasks:
            return TTSResult(
                b"",
                language=runs[0]["language"] if runs else "hi",
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        # Cap tasks to max 2 chunks (~1000 chars) to prevent excessive sequential latency on large answers
        if len(tasks) > 2:
            logger.info("Gnani TTS bounding %d tasks to 2 for voice playback latency", len(tasks))
            tasks = tasks[:2]

        if len(tasks) == 1:
            ch, lc = tasks[0]
            raw = await self._synthesize_chunk(
                client, ch, lc, voice=selected_voice, speed=selected_speed
            )
            full_pcm = _strip_wav_header(raw)
        else:
            # Gnani API strictly enforces 1 active in-flight request at a time.
            # Multi-tasks are synthesized sequentially to respect this limit and prevent HTTP 429.
            pcm_parts: list[bytes] = []
            for ch, lc in tasks:
                raw = await self._synthesize_chunk(
                    client, ch, lc, voice=selected_voice, speed=selected_speed
                )
                pcm_parts.append(_strip_wav_header(raw))
            full_pcm = b"".join(pcm_parts)

        if not full_pcm:
            return TTSResult(
                b"",
                language=runs[0]["language"] if runs else "hi",
                provider="gnani",
                model=self.model,
                voice=selected_voice,
                speed=selected_speed,
                duration_ms=0.0,
            )

        header = _build_wav_header(
            len(full_pcm),
            sample_rate=self.sample_rate,
            num_channels=1,
            sample_width=2,
        )
        stitched = header + full_pcm
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Store in LRU cache
        if self.use_cache:
            async with _tts_cache_lock:
                if len(_tts_cache) >= _TTS_CACHE_MAX_SIZE:
                    _tts_cache.popitem(last=False)
                _tts_cache[cache_key] = stitched

        return TTSResult(
            stitched,
            language=runs[0]["language"] if runs else "hi",
            provider="gnani",
            model=self.model,
            voice=selected_voice,
            speed=selected_speed,
            duration_ms=duration_ms,
            audio_format="wav",
            fallback_occurred=False,
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _log_gnani_error(status: int, body: str, service: str) -> None:
    """Log Gnani error response without leaking the API key."""
    safe = body.replace("X-API-Key-ID", "REDACTED")[:300]
    logger.warning("Gnani %s error: HTTP %d — %s", service, status, safe)
