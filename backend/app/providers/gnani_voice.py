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
import json
import logging
import re
import struct
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
        logger.info(
            "Gnani STT (Prisma v3.0) %s",
            "enabled" if self.enabled else "disabled (no GNANI_API_KEY)",
        )

    async def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe audio bytes to text.

        Returns the transcript string.  Raises GnaniError on provider
        failure so VoiceService can fall through to Sarvam/Azure.
        """
        if not self.enabled:
            raise GnaniError("Gnani STT not configured (missing GNANI_API_KEY)")

        if not audio_bytes:
            return ""

        lang_code = _gnani_lang_code(language)
        if not lang_code:
            # Language not supported by Gnani (e.g. Odia) — signal unavailability
            # so the fallback chain tries Sarvam/Azure instead.
            raise GnaniError(f"Gnani STT does not support language: {language}")

        request_lang = "indic-auto" if self.auto_detect else lang_code
        timeout = httpx.Timeout(self.timeout_s)

        max_attempts = 3
        for attempt in range(max_attempts):
            request_id = str(uuid.uuid4())
            headers = {
                "X-API-Key-ID": self.api_key,
                "X-API-Request-ID": request_id,
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
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
                        raise GnaniError(
                            f"Gnani STT returned success=false: "
                            f"type={err.get('type', 'unknown')} "
                            f"message={err.get('message', 'no message')}"
                        )

                    transcript = data.get("transcript", "") or ""
                    detected = data.get("detected_language_code")
                    model = data.get("model", STT_MODEL)
                    logger.info(
                        "Gnani STT success: model=%s detected_lang=%s transcript_len=%d",
                        model, detected, len(transcript),
                    )
                    return transcript
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

    def __init__(self, settings=None, api_key: Optional[str] = None):
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
        logger.info(
            "Gnani TTS (%s) %s — voice=%s speed=%s container=%s",
            self.model,
            "enabled" if self.enabled else "disabled (no GNANI_API_KEY)",
            self.voice,
            self.speed,
            self.container,
        )

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def _synthesize_chunk(
        self, client: httpx.AsyncClient, text: str, lang_code: str
    ) -> bytes:
        """Synthesize a single text chunk with exponential backoff for transient 503/500/502/504/429 errors."""
        payload = {
            "text": text,
            "voice": self.voice,
            "model": self.model,
            "language": lang_code,
            "speed": self.speed,
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
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
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

                # Rate limiting (429) backoff
                if resp.status_code == 429:
                    if attempt < max_retries - 1:
                        backoff = 0.5 * (2**attempt)
                        logger.warning(
                            "Gnani TTS HTTP 429 on attempt %d/%d; retrying in %.2fs...",
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

    async def synthesize(self, text: str, language: str = "hi") -> bytes:
        """Synthesize text to speech audio bytes.

        Returns raw audio bytes (WAV format). Raises GnaniError on failure.
        """
        if not self.enabled:
            raise GnaniError("Gnani TTS not configured (missing GNANI_API_KEY)")

        text = text.strip()
        if not text:
            return b""

        lang_code = _gnani_lang_code(language)
        if not lang_code:
            raise GnaniError(f"Gnani TTS does not support language: {language}")

        if self.voice not in _GNANI_TTS_VOICES:
            logger.warning(
                "Gnani TTS voice %r not in known catalog; "
                "sending anyway and letting the API validate.",
                self.voice,
            )

        chunks = _chunk_text_for_gnani(text, max_chars=500)
        if not chunks:
            return b""

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if len(chunks) == 1:
                audio = await self._synthesize_chunk(client, chunks[0], lang_code)
                logger.info(
                    "Gnani TTS success: lang=%s voice=%s audio_bytes=%d",
                    lang_code,
                    self.voice,
                    len(audio),
                )
                return audio

            # Multiple chunks: synthesize sequentially to avoid hitting Gnani's concurrency rate limit (429)
            pcm_parts: list[bytes] = []
            for ch in chunks:
                chunk_audio = await self._synthesize_chunk(client, ch, lang_code)
                pcm_parts.append(_strip_wav_header(chunk_audio))

            full_pcm = b"".join(pcm_parts)
            header = _build_wav_header(
                len(full_pcm),
                sample_rate=self.sample_rate,
                num_channels=1,
                sample_width=2,
            )
            stitched_audio = header + full_pcm
            logger.info(
                "Gnani TTS multi-chunk success: chunks=%d lang=%s voice=%s audio_bytes=%d",
                len(chunks),
                lang_code,
                self.voice,
                len(stitched_audio),
            )
            return stitched_audio

    async def text_to_speech_segments(self, segments: list[dict]) -> bytes:
        """Synthesize multiple text segments into one audio blob.

        Preserves each segment's language, chunks if necessary, and stitches
        cleanly into a single WAV audio.
        """
        if not segments:
            return b""

        valid_segments = [s for s in segments if s.get("text", "").strip()]
        if not valid_segments:
            return b""

        # Partition runs of same language
        runs: list[dict] = []
        for s in valid_segments:
            lang = s.get("language", "hi")
            text = s.get("text", "").strip()
            if runs and runs[-1]["language"] == lang:
                runs[-1]["text"] += " " + text
            else:
                runs.append({"language": lang, "text": text})

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            pcm_parts: list[bytes] = []
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
                    chunk_audio = await self._synthesize_chunk(client, ch, lang_code)
                    pcm_parts.append(_strip_wav_header(chunk_audio))

            full_pcm = b"".join(pcm_parts)
            if not full_pcm:
                return b""

            header = _build_wav_header(
                len(full_pcm),
                sample_rate=self.sample_rate,
                num_channels=1,
                sample_width=2,
            )
            return header + full_pcm


# ── Helpers ──────────────────────────────────────────────────────────────


def _log_gnani_error(status: int, body: str, service: str) -> None:
    """Log Gnani error response without leaking the API key."""
    safe = body.replace("X-API-Key-ID", "REDACTED")[:300]
    logger.warning("Gnani %s error: HTTP %d — %s", service, status, safe)
