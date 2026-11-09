"""Sarvam AI translation provider — Mayura v1 translation model.

Sarvam supports translation between Indian languages and English.
This is used as primary translator for Indian languages, with Azure as fallback.

Supports multiple API keys via KeyRotator — tries each key on failure.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import REQUEST_TIMEOUT_S, get_settings
from app.key_rotator import KeyRotator

logger = logging.getLogger(__name__)

_SARVAM_BASE = "https://api.sarvam.ai"

# Sarvam API character limit (approximate, with safety margin)
_SARVAM_CHAR_LIMIT = 900

# Translation model version — must match the active Sarvam API model
_TRANSLATION_MODEL_VERSION = "mayura:v1"

# Sarvam language code mapping
_SARVAM_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "gu": "gu-IN",
    "bn": "bn-IN",
    "mr": "mr-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "od": "od-IN",
    "pa": "pa-IN",
    "as": "as-IN",
    "ur": "ur-IN",
    "ne": "ne-IN",
}


def _to_sarvam_lang(lang: str) -> str:
    """Convert short code to Sarvam BCP-47 format."""
    if lang in _SARVAM_LANG_MAP:
        return _SARVAM_LANG_MAP[lang]
    if lang in _SARVAM_LANG_MAP.values():
        return lang
    return "hi-IN"


class SarvamTranslatorError(RuntimeError):
    pass


_translate_cache: dict[tuple[str, str, str, str], str] = {}
# Bound the process-wide cache: translation keys hold full answer text and
# would otherwise grow with every unique query (memory leak under traffic).
_TRANSLATE_CACHE_MAX = 2000


def _cache_store(key: tuple[str, str, str, str], value: str) -> None:
    """Insert into the translation cache, evicting oldest entries first."""
    if key not in _translate_cache and len(_translate_cache) >= _TRANSLATE_CACHE_MAX:
        for _oldest in list(_translate_cache)[: len(_translate_cache) - _TRANSLATE_CACHE_MAX + 1]:
            del _translate_cache[_oldest]
    _translate_cache[key] = value


def _raw_translate(
    api_key: str,
    text: str,
    source_lang: str,
    target_lang: str,
    translation_stage: str = "other",
) -> str:
    """Make a single Sarvam translate API call. Raises on failure."""
    payload = {
        "input": text,
        "source_language_code": _to_sarvam_lang(source_lang),
        "target_language_code": _to_sarvam_lang(target_lang),
        "model": _TRANSLATION_MODEL_VERSION,
        "numerals_format": "native",
        "mode": "modern-colloquial",  # Use modern-colloquial for user-facing content
    }

    with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
        resp = client.post(
            f"{_SARVAM_BASE}/translate",
            headers={
                "api-subscription-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = data.get("translated_text", "")
        logger.info(
            "translation_stage=%s provider=sarvam source=%s target=%s input_chars=%d output_chars=%d "
            "translation_calls_total=1 translation_calls_query=%d translation_calls_final=%d",
            translation_stage, source_lang, target_lang, len(text), len(translated),
            int(translation_stage == "input_query"),
            int(translation_stage == "final_answer"),
        )
        return translated if translated else text


def _split_text_for_translation(text: str, max_chars: int = _SARVAM_CHAR_LIMIT) -> list[str]:
    """Split text into chunks that respect sentence boundaries and character limits."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current_chunk = ""

    # Split by sentence-ending punctuation or newlines
    sentences = re.split(r'(?<=[.!?\n])\s+', text)

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk = (current_chunk + " " + sentence).strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # If single sentence exceeds limit, split by word boundary
            if len(sentence) > max_chars:
                words = sentence.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= max_chars:
                        current_chunk = (current_chunk + " " + word).strip()
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = word
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text]


class SarvamTranslator:
    """Sarvam Mayura v1 translator for Indian languages with key rotation."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        keys = self.settings.sarvam_keys
        self._rotator = KeyRotator(keys, name="sarvam") if keys else None

    @property
    def configured(self) -> bool:
        return self._rotator is not None

    def _translate_chunk(
        self,
        text: str,
        source: str,
        target: str,
        translation_stage: str,
    ) -> str:
        """Translate a single chunk of text."""
        if not text.strip():
            return text
        return self._rotator.try_keys(  # type: ignore[union-attr]
            lambda key: _raw_translate(key, text, source, target, translation_stage)
        )

    def translate(
        self,
        text: str,
        to: str = "en",
        source: str | None = None,
        translation_stage: str = "other",
    ) -> str:
        if not self.configured or not text.strip():
            logger.debug("Sarvam translate skipped: configured=%s, text_empty=%s",
                        self.configured, not text.strip())
            return text
        target = "en" if to in ("en", "en-IN") else to
        source = source or "hi"

        # Skip if source == target
        if source == target or (source == "en" and target == "en"):
            return text

        cache_key = (_TRANSLATION_MODEL_VERSION, text, source, target)
        if cache_key in _translate_cache:
            logger.debug("Sarvam translate cache hit")
            return _translate_cache[cache_key]

        try:
            logger.info("Sarvam translating: %s -> %s (len=%d)", source, target, len(text))

            # Split text into chunks if too long
            chunks = _split_text_for_translation(text)

            if len(chunks) == 1:
                # Short text, translate directly
                result = self._translate_chunk(text, source, target, translation_stage)
            else:
                # Long text, translate each chunk and rejoin.
                # If ANY chunk fails, the entire translation fails so
                # the caller's Azure fallback can handle the full text.
                logger.info("Sarvam: splitting into %d chunks for translation", len(chunks))
                translated_chunks = []
                for i, chunk in enumerate(chunks):
                    translated_chunk = self._translate_chunk(
                        chunk, source, target, translation_stage,
                    )
                    translated_chunks.append(translated_chunk)
                    logger.debug("Sarvam chunk %d/%d translated: len %d -> %d",
                               i + 1, len(chunks), len(chunk), len(translated_chunk))
                # Preserve the answer's markdown/newline structure. Joining
                # translated blocks with spaces collapses bullets and paragraphs.
                result = "\n\n".join(translated_chunks)

            # Validate translation actually changed the text
            if result == text and source != target:
                logger.warning("Sarvam returned unchanged text - possible translation failure")

            _cache_store(cache_key, result)
            logger.info("Sarvam translation successful: len %d -> %d", len(text), len(result))
            return result
        except Exception as e:
            logger.warning("Sarvam translation failed with all keys: %s", e)
            raise
