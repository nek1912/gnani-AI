# Sarvam-105B LLM Migration & Language Pipeline Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Groq with Sarvam-105B as the primary LLM, eliminate output translation, fix chunk ID leakage, add evidence assessment, and support mixed-language queries.

**Architecture:** Sarvam-105B generates directly in the user's language (no output translation). Input translation kept for Jina v3 embedding. Backend strips `[chunk:ID]` markers before sending to client. Evidence assessment uses source-role rules (not raw scores) to prioritize static vs web evidence.

**Tech Stack:** Python/FastAPI backend, Next.js/React frontend, Sarvam AI chat completions API, Supabase pgvector, Jina v3 embeddings

## Global Constraints

- Python: type hints everywhere, Pydantic models for all request/response bodies, no bare `except`
- Every external provider call goes through an adapter with explicit timeout and fallback handling
- Never put API keys in frontend code or expose via `NEXT_PUBLIC_*`
- Structured logs, never log API keys or full grievance PII
- Backend guarantees `answer` field contains no `[chunk:xxx]` patterns before sending to client
- Citation validation is set-membership only (verifies IDs exist in evidence, not semantic claim support)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/config.py` | Modify | Add `sarvam_chat_model`, `sarvam_chat_url` settings |
| `backend/app/providers/sarvam_chat.py` | **Create** | Sarvam chat completions adapter (OpenAI-compatible) |
| `backend/app/contracts.py` | Modify | Add `SourceRole`, `EvidenceSufficiency`, `EvidenceAssessment` models |
| `backend/app/language.py` | Modify | Add `language_mix` to `detect_query_languages()` return |
| `backend/app/evidence_controller.py` | Modify | Rewrite prompt, add `EvidenceController.assess_evidence()`, add `strip_citations()` |
| `backend/app/services/rag_orchestrator.py` | Modify | Use SarvamChatProvider, accept `language_mix`, use `EvidenceAssessment` |
| `backend/app/routes/chat.py` | Modify | Remove output translation, pass `language_mix` to orchestrator |
| `frontend/src/components/chat/MessageBubble.tsx` | Modify | Expand `cleanAnswerText()` regex |
| `tests/providers/test_sarvam_chat.py` | **Create** | SarvamChatProvider unit tests |
| `tests/test_language_mix.py` | **Create** | Mixed language detection tests |
| `tests/test_evidence_assessment.py` | **Create** | Evidence assessment tests |
| `tests/test_strip_citations.py` | **Create** | Citation extraction tests |

---

### Task 1: Add Sarvam Chat Settings to Config

**Files:**
- Modify: `backend/app/config.py:6-58` (fields section)

**Interfaces:**
- Consumes: existing `Settings` class
- Produces: `Settings.sarvam_chat_model`, `Settings.sarvam_chat_url` fields

- [ ] **Step 1: Add new fields to Settings**

In `backend/app/config.py`, add after the existing `sarvam_api_key_2` field (around line 42):

```python
sarvam_chat_model: str = "sarvam-105b"
sarvam_chat_url: str = "https://api.sarvam.ai/v1/chat/completions"
```

- [ ] **Step 2: Verify existing sarvam_keys property works**

The existing `sarvam_keys` property (line ~85) already aggregates `sarvam_api_key` + `sarvam_api_key_2`. No change needed.

- [ ] **Step 3: Run existing config tests to verify no regression**

Run: `cd backend && python -m pytest tests/ -k "settings or config" -v`
Expected: All existing tests PASS (no config-related test failures)

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): add sarvam_chat_model and sarvam_chat_url settings"
```

---

### Task 2: Create SarvamChatProvider

**Files:**
- Create: `backend/app/providers/sarvam_chat.py`
- Test: `tests/providers/test_sarvam_chat.py`

**Key design decisions (from official Sarvam docs):**
- Auth: `api-subscription-key` header only (no `Authorization: Bearer` needed)
- Model: `sarvam-105b` (128K context, NOT `sarvam-105b-conversations` which is 32K for voice)
- Reasoning: `reasoning_effort=None` for latency-sensitive RAG path (reasoning is on by default)
- Streaming: optional, NOT part of MVP correctness path (can't guarantee no chunk ID leakage during streaming)
- Error handling: 403 = credential failure, 429 = rate limit, 5xx/timeout = provider failure, 422 = bad request (do NOT rotate keys on 422)

**Interfaces:**
- Consumes: `Settings` (for `sarvam_keys`, `sarvam_chat_model`, `sarvam_chat_url`)
- Produces: `SarvamChatProvider.generate(system, user, temperature) -> str`, `.generate_stream(...) -> Generator[str, None, None]`

- [ ] **Step 1: Write failing tests**

Create `tests/providers/test_sarvam_chat.py`:

```python
"""Tests for SarvamChatProvider."""
import httpx
import pytest
from unittest.mock import MagicMock, patch

from app.providers.sarvam_chat import SarvamChatProvider, SarvamProviderError
from app.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq",
        "gemini_api_key": "test-gemini",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "sarvam_api_key": "sk_test_sarvam_1",
        "sarvam_api_key_2": "sk_test_sarvam_2",
        "sarvam_chat_model": "sarvam-105b",
        "sarvam_chat_url": "https://api.sarvam.ai/v1/chat/completions",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestSarvamChatProvider:
    def test_generate_returns_content(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "नमस्ते, मैं आपकी मदद कर सकता हूँ।"}}]
        }
        with patch("httpx.post", return_value=mock_response):
            result = provider.generate("System prompt", "User question")
        assert result == "नमस्ते, मैं आपकी मदद कर सकता हूँ।"

    def test_generate_rotates_keys_on_429_with_backoff(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        # 429 on key1, success on key2
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "rate limited"
        resp_429.json.return_value = {"error": {"message": "rate limited"}}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Success on key 2"}}]
        }
        with patch("httpx.post", side_effect=[resp_429, resp_200]):
            with patch("time.sleep"):  # Skip actual backoff in tests
                result = provider.generate("System", "User")
        assert result == "Success on key 2"

    def test_422_does_not_rotate_keys(self):
        """422 = bad request, not bad key. Rotating won't help."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "invalid parameters"
        mock_response.json.return_value = {"error": {"message": "invalid"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError) as exc_info:
                provider.generate("System", "User")
            assert exc_info.value.retryable is False

    def test_403_invalid_key_rotates(self):
        """403 + invalid_api_key → try next key."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "forbidden"
        resp_403.json.return_value = {"error": {"code": "invalid_api_key", "message": "bad key"}}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Success on key 2"}}]
        }
        with patch("httpx.post", side_effect=[resp_403, resp_200]):
            result = provider.generate("System", "User")
        assert result == "Success on key 2"

    def test_403_other_forbidden_does_not_rotate(self):
        """403 + other forbidden error → non-retryable, propagate."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "forbidden"
        mock_response.json.return_value = {"error": {"code": "permission_denied", "message": "no access"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError) as exc_info:
                provider.generate("System", "User")
            assert exc_info.value.retryable is False

    def test_generate_sends_correct_headers_and_body(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        with patch("httpx.post", return_value=mock_response) as mock_post:
            provider.generate("System prompt", "User msg", temperature=0.5)
            call_kwargs = mock_post.call_args
            headers = call_kwargs[1].get("headers", call_kwargs.kwargs.get("headers", {}))
            assert "api-subscription-key" in headers
            assert headers["api-subscription-key"] == "sk_test_sarvam_1"
            assert "Authorization" not in headers
            body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert body["model"] == "sarvam-105b"
            assert body["messages"][0]["content"] == "System prompt"
            assert body["temperature"] == 0.5
            assert body["reasoning_effort"] is None
            assert body["stream"] is False

    def test_all_keys_fail_raises_provider_error(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "server error"
        mock_response.json.return_value = {"error": {"message": "server error"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError):
                provider.generate("System", "User")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/providers/test_sarvam_chat.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.sarvam_chat'`

- [ ] **Step 3: Implement SarvamChatProvider**

Create `backend/app/providers/sarvam_chat.py`:

```python
"""Sarvam AI chat completions provider (OpenAI-compatible API)."""
from __future__ import annotations

import httpx
import logging
import time
from typing import Generator

from app.config import Settings
from app.key_rotator import KeyRotator

logger = logging.getLogger(__name__)


class SarvamProviderError(Exception):
    """Dedicated exception for Sarvam provider failures.

    Subclasses distinguish retryable from non-retryable errors:
    - Retryable: 403 (invalid_api_key), 429, 500, 503, timeout
    - Non-retryable: 400, 422, malformed response, programming errors
    """

    def __init__(self, message: str, status_code: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SarvamChatProvider:
    """Sarvam-105B chat completions adapter.

    Uses the OpenAI-compatible endpoint at api.sarvam.ai.
    Auth: ``api-subscription-key: <key>`` header only.
    Reasoning is disabled (reasoning_effort=None) for latency-sensitive RAG.
    """

    def __init__(self, settings: Settings) -> None:
        keys = settings.sarvam_keys
        if not keys:
            raise ValueError("No Sarvam API keys configured")
        self._rotator = KeyRotator(keys, name="sarvam")
        self._model = settings.sarvam_chat_model
        self._url = settings.sarvam_chat_url

    def generate(
        self, system: str, user: str, temperature: float = 0.1
    ) -> str:
        """Non-streaming generation. Primary MVP path."""
        last_error: SarvamProviderError | None = None
        keys = self._rotator._keys  # noqa: SLF001
        for key in keys:
            try:
                return self._call_api(key, system, user, temperature)
            except SarvamProviderError as exc:
                last_error = exc
                if not exc.retryable:
                    raise  # 400, 422 — don't rotate keys
                # 429 → bounded backoff before trying next key
                if exc.status_code == 429:
                    time.sleep(1.0)
                continue
        raise last_error  # type: ignore[misc]

    def _call_api(
        self,
        key: str,
        system: str,
        user: str,
        temperature: float,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": key,
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "reasoning_effort": None,
            "max_tokens": 2048,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=(30.0, 120.0)) as client:
                resp = client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SarvamProviderError(f"Timeout: {exc}", retryable=True) from exc

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices or not choices[0].get("message", {}).get("content"):
                raise SarvamProviderError("Empty response from Sarvam", retryable=False)
            return choices[0]["message"]["content"]

        # Classify error
        if resp.status_code == 422:
            raise SarvamProviderError(
                f"Invalid request (422): {resp.text[:200]}", status_code=422, retryable=False
            )
        if resp.status_code == 400:
            raise SarvamProviderError(
                f"Bad request (400): {resp.text[:200]}", status_code=400, retryable=False
            )
        if resp.status_code == 403:
            # 403 can mean invalid key OR other forbidden error
            # Inspect error.code if available
            try:
                err_body = resp.json()
                err_code = err_body.get("error", {}).get("code", "")
                if err_code == "invalid_api_key":
                    raise SarvamProviderError(
                        f"Invalid API key (403)", status_code=403, retryable=True
                    )
            except (ValueError, KeyError):
                pass
            raise SarvamProviderError(
                f"Forbidden (403): {resp.text[:200]}", status_code=403, retryable=False
            )
        if resp.status_code in (429, 500, 503):
            raise SarvamProviderError(
                f"Provider error ({resp.status_code}): {resp.text[:200]}",
                status_code=resp.status_code,
                retryable=True,
            )
        raise SarvamProviderError(
            f"Unexpected status {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
            retryable=False,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/providers/test_sarvam_chat.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/sarvam_chat.py tests/providers/test_sarvam_chat.py
git commit -m "feat(provider): add SarvamChatProvider with key rotation and streaming"
```

---

### Task 3: Add EvidenceAssessment Models to Contracts

**Files:**
- Modify: `backend/app/contracts.py` (add after `QueryRequirements` model, around line 149)
- Test: `tests/test_evidence_assessment.py`

**Interfaces:**
- Consumes: existing `QueryRequirements` model
- Produces: `SourceRole`, `EvidenceSufficiency`, `EvidenceAssessment` models

- [ ] **Step 1: Write failing tests**

Create `tests/test_evidence_assessment.py`:

```python
"""Tests for EvidenceAssessment models."""
from app.contracts import SourceRole, EvidenceSufficiency, EvidenceAssessment


def test_source_role_values():
    assert SourceRole.STATIC_PRIMARY.value == "static_primary"
    assert SourceRole.WEB_PRIMARY.value == "web_primary"
    assert SourceRole.BALANCED.value == "balanced"


def test_evidence_sufficiency_values():
    assert EvidenceSufficiency.SUFFICIENT.value == "sufficient"
    assert EvidenceSufficiency.PARTIAL.value == "partial"
    assert EvidenceSufficiency.INSUFFICIENT.value == "insufficient"
    assert EvidenceSufficiency.EMPTY.value == "empty"


def test_evidence_assessment_model():
    assessment = EvidenceAssessment(
        source_role=SourceRole.WEB_PRIMARY,
        sufficiency=EvidenceSufficiency.PARTIAL,
        static_quality="low",
        web_quality="high",
        assessment_text="Dynamic evidence is stronger.",
    )
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency == EvidenceSufficiency.PARTIAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_evidence_assessment.py -v`
Expected: FAIL with `ImportError: cannot import name 'SourceRole'`

- [ ] **Step 3: Add models to contracts.py**

In `backend/app/contracts.py`, add after the `QueryRequirements` class (around line 149):

```python
class SourceRole(Enum):
    """Which evidence source should be primary for this query."""
    STATIC_PRIMARY = "static_primary"    # General policy/rules/definitions
    WEB_PRIMARY = "web_primary"          # Current/local/notification/value
    BALANCED = "balanced"                # Both relevant


class EvidenceSufficiency(Enum):
    """How much evidence is available to answer the query."""
    SUFFICIENT = "sufficient"      # Enough quality evidence to answer
    PARTIAL = "partial"            # Some evidence, gaps remain
    INSUFFICIENT = "insufficient"  # Not enough to answer properly
    EMPTY = "empty"                # No evidence found


class EvidenceAssessment(BaseModel):
    """Assessment of evidence quality and sufficiency for a query."""
    source_role: SourceRole
    sufficiency: EvidenceSufficiency
    static_quality: Literal["high", "medium", "low"]
    web_quality: Literal["high", "medium", "low"]
    assessment_text: str  # Human-readable, injected into prompt
```

Note: `Enum` and `Literal` imports — verify `Enum` is imported from `enum` and `Literal` from `typing` at the top of contracts.py. Add if missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_evidence_assessment.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full test suite to check no regression**

Run: `cd backend && python -m pytest tests/ -v --timeout=30`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts.py tests/test_evidence_assessment.py
git commit -m "feat(contracts): add SourceRole, EvidenceSufficiency, EvidenceAssessment models"
```

---

### Task 4: Extend Language Detection for Mixed Language

**Files:**
- Modify: `backend/app/language.py:113-152` (detect_query_languages function)
- Test: `tests/test_language_mix.py`

**Interfaces:**
- Consumes: existing `_script_ratios()` helper
- Produces: `detect_query_languages()` now returns `language_mix: dict[str, float] | None`

- [ ] **Step 1: Write failing tests**

Create `tests/test_language_mix.py`:

```python
"""Tests for mixed language detection."""
from app.language import detect_query_languages


def test_english_only():
    result = detect_query_languages("What is the premium rate?")
    assert result["dominant"] == "en"
    assert result["language_mix"] is None


def test_hindi_only():
    result = detect_query_languages("पीएमएफबीवाई योजना क्या है?")
    assert result["dominant"] == "hi"
    assert result["language_mix"] is None


def test_hindi_english_script_mix_detected():
    """Script-detectable mix: Devanagari + Latin."""
    result = detect_query_languages("PMFBY योजना kya hai")
    assert result["dominant"] in ("hi", "en")
    assert result["language_mix"] is not None
    assert "hi" in result["language_mix"] or "en" in result["language_mix"]


def test_pure_latin_not_detected_as_mix():
    """Romanized Hindi/Gujarati in Latin script — script analysis can't detect mix.
    Sarvam-105B handles this natively through the prompt instruction."""
    result = detect_query_languages("PMFBY scheme kya hai")
    # Entirely Latin script — language_mix should be None
    # (Sarvam handles Romanized code-mixing via prompt, not via language_mix signal)
    assert result["language_mix"] is None


def test_gujarati_only():
    result = detect_query_languages("ગુજરાત સહકાર યોજના")
    assert result["dominant"] == "gu"
    assert result["language_mix"] is None


def test_mixed_returns_dict():
    result = detect_query_languages("Cooperative society ka rules")
    assert isinstance(result, dict)
    assert "languages" in result
    assert "dominant" in result
    assert "language_mix" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_language_mix.py -v`
Expected: FAIL — `language_mix` key not in return dict

- [ ] **Step 3: Modify detect_query_languages()**

In `backend/app/language.py`, modify the `detect_query_languages()` function (lines 113-152).

Add `language_mix` to the return dict. After the existing `dominant` calculation (around line 147), add:

```python
# Calculate language mix when multiple scripts detected
language_mix = None
if len(languages) > 1:
    ratios = _script_ratios(text)
    # Map script names to language codes
    script_to_lang = {
        "devanagari": "hi",  # Default; disambiguation happens via dominant
        "gujarati": "gu",
        "bengali": "bn",
        "tamil": "ta",
        "telugu": "te",
        "kannada": "kn",
        "gurmukhi": "pa",
        "odia": "or",
        "malayalam": "ml",
        "latin": "en",
    }
    mix = {}
    for script, ratio in ratios.items():
        if ratio >= 0.15:  # At least 15% of alphabetic chars
            lang_code = script_to_lang.get(script)
            if lang_code:
                mix[lang_code] = round(ratio, 2)
    if len(mix) >= 2:
        language_mix = mix
```

Update the return statement:

```python
return {
    "languages": languages,
    "dominant": dominant,
    "explicit_request": _detect_explicit_request(text),
    "language_mix": language_mix,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_language_mix.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run existing language tests for regression**

Run: `cd backend && python -m pytest tests/ -k "language" -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/language.py tests/test_language_mix.py
git commit -m "feat(language): add language_mix detection for code-mixed queries"
```

---

### Task 5: Add strip_citations() Function

**Files:**
- Modify: `backend/app/evidence_controller.py` (add as module-level function)
- Test: `tests/test_strip_citations.py`

**Interfaces:**
- Consumes: none (pure function)
- Produces: `strip_citations(answer: str) -> tuple[str, list[str]]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_strip_citations.py`:

```python
"""Tests for strip_citations function."""
from app.evidence_controller import strip_citations


def test_strips_hex_chunk_ids():
    answer = "The scheme requires [chunk:a0eebc99] registration."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert "registration" in clean
    assert ids == ["a0eebc99"]


def test_strips_web_chunk_ids():
    answer = "According to [chunk:web_a1b2c3d4e5f6_c102] the premium is ₹2000."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert "web_a1b2c3d4e5f6_c102" in ids


def test_strips_empty_id():
    """Empty ID [chunk:] should still be stripped."""
    answer = "Edge case [chunk:] mention."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert ids == []


def test_preserves_markdown_structure():
    """stripping must not destroy markdown formatting."""
    answer = (
        "- Point one [chunk:abc12345]\n"
        "- Point two [chunk:def67890]\n\n"
        "**Important** [chunk:abc12345]\n\n"
        "Paragraph two."
    )
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    # Markdown structure preserved (newlines intact, not collapsed to single line)
    assert "- Point one" in clean
    assert "- Point two" in clean
    assert "**Important**" in clean
    assert "Paragraph two" in clean


def test_no_citations_unchanged():
    answer = "This is a plain answer with no citations."
    clean, ids = strip_citations(answer)
    assert clean == answer
    assert ids == []


def test_strips_multiple_formats():
    answer = "Static [chunk:a0eebc99] and web [chunk:web_abc123def456_c42] evidence."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert len(ids) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_strip_citations.py -v`
Expected: FAIL with `ImportError: cannot import name 'strip_citations'`

- [ ] **Step 3: Implement strip_citations()**

In `backend/app/evidence_controller.py`, add as a module-level function before the `EvidenceController` class (around line 230):

```python
def strip_citations(answer: str) -> tuple[str, list[str]]:
    """Extract [chunk:ID] markers from LLM output.

    Returns (clean_answer, extracted_ids).
    Backend guarantee: clean_answer contains no [chunk:xxx] patterns.

    Actual chunk-ID formats in this RAG system:
    - Static: 8-char hex prefix of UUID (e.g., 'a0eebc99')
    - Web: 'web_{hex12}_c{N}' prefix (e.g., 'web_a1b2c3d4e5f6_c102')

    Preserves surrounding Markdown structure (newlines, bullets, bold).
    Handles empty IDs [chunk:] and any characters inside the brackets.
    """
    import re
    pattern = r'\[chunk:([^\]]*)\]'
    ids = re.findall(pattern, answer)
    clean = re.sub(pattern, '', answer)
    # Remove only double-spaces left behind, NOT newlines or markdown structure
    clean = re.sub(r'  +', ' ', clean).strip()
    return clean, ids
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_strip_citations.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/evidence_controller.py tests/test_strip_citations.py
git commit -m "feat(evidence): add strip_citations() to extract chunk IDs at LLM boundary"
```

---

### Task 6: Add Evidence Assessment Logic

**Files:**
- Modify: `backend/app/evidence_controller.py` (add methods to EvidenceController)
- Test: `tests/test_evidence_assessment.py` (extend existing)

**Interfaces:**
- Consumes: `RAGResult`, `QueryRequirements`, `SourceRole`, `EvidenceSufficiency`
- Produces: `EvidenceController.assess_evidence()` returns `EvidenceAssessment`

- [ ] **Step 1: Add tests for assess_evidence()**

Append to `tests/test_evidence_assessment.py`:

```python
from app.evidence_controller import EvidenceController
from app.contracts import (
    RAGResult, EvidenceChunk, QueryRequirements,
    SourceRole, EvidenceSufficiency,
)


def _make_chunks(source_type: str, count: int, scores: list[float] | None = None) -> list[EvidenceChunk]:
    chunks = []
    for i in range(count):
        score = scores[i] if scores else 0.5
        chunks.append(EvidenceChunk(
            chunk_id=f"{source_type}_{i:05d}",
            content=f"Content {i}",
            source_type=source_type,
            title=f"Source {i}",
            dense_score=score,
        ))
    return chunks


def test_assess_web_primary_for_current_query():
    controller = EvidenceController()
    static_result = RAGResult(chunks=_make_chunks("static", 5, [0.8, 0.7, 0.6, 0.5, 0.4]))
    web_result = RAGResult(chunks=_make_chunks("web", 3, [0.9, 0.8, 0.7]))
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (EvidenceSufficiency.SUFFICIENT, EvidenceSufficiency.PARTIAL)


def test_assess_static_primary_for_policy_query():
    controller = EvidenceController()
    static_result = RAGResult(chunks=_make_chunks("static", 8, [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]))
    web_result = RAGResult(chunks=_make_chunks("web", 1, [0.3]))
    query_req = QueryRequirements(
        temporal_scope="general",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.STATIC_PRIMARY


def test_assess_empty_when_no_chunks():
    controller = EvidenceController()
    static_result = RAGResult(chunks=[], abstained=True)
    web_result = RAGResult(chunks=[], abstained=True)
    query_req = QueryRequirements(
        temporal_scope="general",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.sufficiency == EvidenceSufficiency.EMPTY


def test_current_query_with_no_dynamic_evidence.prevents_incorrect_static_answer():
    """CRITICAL REGRESSION TEST.

    Historical bug: current/local query + dynamic=EMPTY + static=AVAILABLE
    → static evidence was used to answer as if current, producing wrong answer.

    This test verifies:
    1. Source role is WEB_PRIMARY (current query)
    2. Sufficiency is INSUFFICIENT (no dynamic evidence)
    3. Prompt explicitly says current/local fact cannot be established
    """
    controller = EvidenceController()
    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="General PMFBY rules",
                      source_type="static", title="PMFBY Guidelines", dense_score=0.8),
    ])
    web_result = RAGResult(chunks=[], abstained=True)  # No dynamic evidence
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)

    # Must NOT be SUFFICIENT — dynamic evidence is missing for current query
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (
        EvidenceSufficiency.INSUFFICIENT,
        EvidenceSufficiency.PARTIAL,
        EvidenceSufficiency.EMPTY,
    )
    assert assessment.sufficiency != EvidenceSufficiency.SUFFICIENT
    # Assessment text must warn that current/local facts cannot be established
    assert "current" in assessment.assessment_text.lower() or "dynamic" in assessment.assessment_text.lower()


def test_historical_query_prefers_period_matching_evidence():
    """Historical queries should prefer evidence matching the requested period."""
    controller = EvidenceController()
    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="2023 rules",
                      source_type="static", title="2023 Guidelines", dense_score=0.8),
    ])
    web_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="web_001", content="2024 notification",
                      source_type="web", title="2024 Update", dense_score=0.7),
    ])
    query_req = QueryRequirements(
        temporal_scope="2023",
        geographic_scope="none",
        required_specificity="general",
        requires_dynamic=False,
    )
    assessment = controller.assess_evidence(static_result, web_result, query_req)
    # Should prefer static (2023 matches historical query)
    assert assessment.source_role in (SourceRole.STATIC_PRIMARY, SourceRole.BALANCED)
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_evidence_assessment.py -v`
Expected: FAIL — `assess_evidence` method doesn't exist

- [ ] **Step 3: Implement assess_evidence() on EvidenceController**

In `backend/app/evidence_controller.py`, add to the `EvidenceController` class (after `build_curated_prompt`):

```python
def assess_evidence(
    self,
    static_result: RAGResult,
    web_result: RAGResult,
    query_requirements: QueryRequirements,
) -> "EvidenceAssessment":
    """Assess evidence quality and determine source priority.

    Source-role rules override raw retrieval scores.
    """
    from app.contracts import SourceRole, EvidenceSufficiency, EvidenceAssessment

    # 1. Determine source-role match based on query requirements
    source_role = self._determine_source_role(query_requirements)

    # 2. Score quality: count chunks above retrieval threshold
    static_quality = self._score_quality(static_result.chunks)
    web_quality = self._score_quality(web_result.chunks)

    # 3. Check sufficiency
    sufficiency = self._check_sufficiency(static_result, web_result, source_role)

    # 4. Generate human-readable assessment text
    assessment_text = self._generate_assessment_text(
        source_role, sufficiency, static_quality, web_quality
    )

    return EvidenceAssessment(
        source_role=source_role,
        sufficiency=sufficiency,
        static_quality=static_quality,
        web_quality=web_quality,
        assessment_text=assessment_text,
    )

def _determine_source_role(self, qr: QueryRequirements) -> SourceRole:
    """Which source SHOULD have the answer based on query type."""
    from app.contracts import SourceRole

    if qr.requires_dynamic and qr.temporal_scope in ("current",):
        return SourceRole.WEB_PRIMARY
    if qr.temporal_scope == "general" and not qr.requires_dynamic:
        return SourceRole.STATIC_PRIMARY
    if qr.temporal_scope == "historical":
        # Historical queries: prefer evidence matching the requested period
        # Static documents with dated content are preferred over generic web results
        return SourceRole.STATIC_PRIMARY
    return SourceRole.BALANCED

def _score_quality(self, chunks: list) -> str:
    """Score evidence quality based on retrieval scores."""
    if not chunks:
        return "low"
    high_scores = sum(1 for c in chunks if (c.dense_score or 0) >= 0.7)
    ratio = high_scores / len(chunks) if chunks else 0
    if ratio >= 0.5:
        return "high"
    if ratio >= 0.2:
        return "medium"
    return "low"

def _check_sufficiency(
    self,
    static_result: RAGResult,
    web_result: RAGResult,
    source_role: SourceRole,
) -> EvidenceSufficiency:
    """Check if evidence is sufficient to answer the query.

    Considers: source-role match, retrieval quality, chunk count.
    Two irrelevant chunks are NOT sufficient. One highly authoritative
    chunk can be more useful than five generic ones.
    """
    from app.contracts import EvidenceSufficiency

    static_count = len(static_result.chunks)
    web_count = len(web_result.chunks)
    total = static_count + web_count

    if total == 0:
        return EvidenceSufficiency.EMPTY

    # Count high-quality chunks (dense_score >= 0.5)
    static_high = sum(1 for c in static_result.chunks if (c.dense_score or 0) >= 0.5)
    web_high = sum(1 for c in web_result.chunks if (c.dense_score or 0) >= 0.5)

    if source_role == SourceRole.WEB_PRIMARY:
        if web_high >= 2:
            return EvidenceSufficiency.SUFFICIENT
        if web_high >= 1 or web_count >= 1:
            return EvidenceSufficiency.PARTIAL
        return EvidenceSufficiency.INSUFFICIENT

    if source_role == SourceRole.STATIC_PRIMARY:
        if static_high >= 2:
            return EvidenceSufficiency.SUFFICIENT
        if static_high >= 1 or static_count >= 1:
            return EvidenceSufficiency.PARTIAL
        return EvidenceSufficiency.INSUFFICIENT

    # BALANCED
    if (static_high + web_high) >= 3:
        return EvidenceSufficiency.SUFFICIENT
    if total >= 2:
        return EvidenceSufficiency.PARTIAL
    return EvidenceSufficiency.INSUFFICIENT

def _generate_assessment_text(
    self,
    source_role: SourceRole,
    sufficiency: EvidenceSufficiency,
    static_quality: str,
    web_quality: str,
) -> str:
    """Generate human-readable assessment for the prompt."""
    from app.contracts import SourceRole, EvidenceSufficiency

    role_text = {
        SourceRole.STATIC_PRIMARY: "Static evidence (official documents) is the primary source for this query.",
        SourceRole.WEB_PRIMARY: "Dynamic evidence (web sources) is the primary source for this query.",
        SourceRole.BALANCED: "Both static and dynamic evidence are relevant.",
    }

    sufficiency_text = {
        EvidenceSufficiency.SUFFICIENT: "Evidence is sufficient to answer.",
        EvidenceSufficiency.PARTIAL: "Evidence partially covers the query. Fill gaps carefully.",
        EvidenceSufficiency.INSUFFICIENT: "Limited evidence available. Answer only what is directly supported.",
        EvidenceSufficiency.EMPTY: "No relevant evidence found. Do not generate a general knowledge answer.",
    }

    return f"{role_text[source_role]} {sufficiency_text[sufficiency]}"
```

Note: Import `RAGResult`, `EvidenceChunk` at the top of the file if not already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_evidence_assessment.py -v`
Expected: All tests PASS (old + new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/evidence_controller.py tests/test_evidence_assessment.py
git commit -m "feat(evidence): add assess_evidence() with source-role rules and sufficiency check"
```

---

### Task 7: Rewrite Prompt for Sarvam + Rural Audience

**Files:**
- Modify: `backend/app/evidence_controller.py:173-226` (replace `_SOURCE_PRIORITY_PROMPT`)
- Modify: `backend/app/evidence_controller.py:266-332` (update `build_curated_prompt()`)

**Interfaces:**
- Consumes: `EvidenceBundle`, `EvidenceAssessment`, `language_mix`
- Produces: `(system_prompt, user_prompt)` tuple

- [ ] **Step 1: Replace _SOURCE_PRIORITY_PROMPT**

In `backend/app/evidence_controller.py`, replace the `_SOURCE_PRIORITY_PROMPT` constant (lines 173-226) with:

```python
_SOURCE_PRIORITY_PROMPT = """You are a helpful government information assistant for Indian citizens,
especially those in rural areas.

CRITICAL RULES:

1. Language: Respond in the user's language. If the question mixes languages
   (e.g., Hindi + English), respond naturally in that same style. Preserve the
   user's language and code-switching style naturally. Do not force everything
   into one language.

2. Evidence: Use the evidence provided to answer.
   - STATIC EVIDENCE (official documents): Rules, definitions, policy,
     procedures, eligibility criteria. Always in English.
   - DYNAMIC EVIDENCE (web sources): Current facts, notifications,
     availability, current values. May be in any language.
   Use both when relevant. Prioritize evidence based on relevance,
   authority, specificity, and freshness. Do not use weaker evidence
   when it conflicts with stronger evidence. Do not infer current or
   local facts from static evidence alone.

3. Citations: After each factual statement, add [chunk:ID] markers.
   These are for internal tracking and will be extracted by the system.
   You must include them for every factual claim.

4. When evidence is limited:
   - Answer only what is directly supported by the available evidence
   - Add ONE brief note at the END if important context is missing
   - Do NOT repeat disclaimers. Do NOT refuse to answer what evidence supports.

5. When evidence is insufficient:
   - Answer only what is directly supported
   - Explain what information is missing
   - Suggest what type of official source the user should consult
     (e.g., district cooperative office, block development officer)

6. When no evidence is found:
   - Explain that no relevant evidence was found
   - Suggest the type of official source the user should consult
   - Do NOT generate a general knowledge answer

7. Tone: Simple, clear, helpful. Use short sentences. Explain technical
   terms (like PMFBY, PACS) briefly when first mentioned. Be kind and
   patient — the user may be asking for the first time.

8. Formatting:
   - Use bullet points for lists
   - Bold important terms or document names
   - Keep paragraphs short (2-3 sentences)
   - Use markdown for readability
"""
```

- [ ] **Step 2: Update build_curated_prompt() signature**

Change the method signature to accept `language_mix` and `assessment`:

```python
def build_curated_prompt(
    self,
    bundle: EvidenceBundle,
    english_query: str,
    history: list[dict] | None,
    lang: str,
    language_mix: dict[str, float] | None = None,
    assessment: "EvidenceAssessment | None" = None,
) -> tuple[str, str]:
```

- [ ] **Step 3: Update prompt construction to inject assessment and language_mix**

In the `build_curated_prompt()` method, update the user_prompt construction:

Replace the evidence availability section (around lines 312-329) with:

```python
# Build assessment text
assessment_text = ""
if assessment:
    assessment_text = f"\n== EVIDENCE ASSESSMENT ==\n{assessment.assessment_text}\n"

# Build language context
lang_context = f"User language: {lang}"
if language_mix:
    lang_context += f" (code-mixed: {language_mix})"

user_prompt = (
    f"{hist_text}"
    f"Question: {english_query}\n\n"
    f"{lang_context}\n\n"
    f"== STATIC EVIDENCE (official documents — may not reflect current status) ==\n"
    f"{static_section}\n\n"
    f"== DYNAMIC EVIDENCE (web sources — current information) ==\n"
    f"{dynamic_section}\n\n"
    f"{assessment_text}"
    f"INSTRUCTIONS:\n"
    f"1. Respond in the user's language. Match their code-switching style naturally.\n"
    f"2. Answer using the evidence provided. Prioritize based on relevance and authority.\n"
    f"3. Include [chunk:ID] citations for every factual claim.\n"
    f"4. If evidence is limited, answer only what is directly supported.\n"
    f"5. Use simple, clear language for ordinary citizens.\n"
)
```

- [ ] **Step 4: Run existing evidence controller tests**

Run: `cd backend && python -m pytest tests/ -k "evidence" -v`
Expected: All existing tests PASS (with updated signatures)

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/evidence_controller.py
git commit -m "feat(evidence): rewrite prompt for Sarvam + rural audience, inject assessment"
```

---

### Task 8: Update Orchestrator to Use Sarvam + Evidence Assessment

**Files:**
- Modify: `backend/app/services/rag_orchestrator.py:74-235`
- Test: extend existing orchestrator tests

**Interfaces:**
- Consumes: `SarvamChatProvider`, `EvidenceAssessment`, `language_mix`
- Produces: `RAGResponse` with clean answer (no chunk IDs)

- [ ] **Step 1: Update run() signature**

In `backend/app/services/rag_orchestrator.py`, add `language_mix` parameter to `run()`:

```python
async def run(
    self,
    query: str,
    english_query: str,
    embedding: list[float],
    domain: str,
    state: str | None,
    classification: QueryClassification | None,
    history: list[dict] | None,
    lang: str,
    session_id: str,
    language_mix: dict[str, float] | None = None,  # NEW
) -> RAGResponse:
```

- [ ] **Step 2: Initialize SarvamChatProvider once in __init__**

In `__init__` (line 74-80), add SarvamChatProvider initialization. Do NOT create a new provider per `run()` call:

```python
def __init__(self, settings: Settings | None = None) -> None:
    self._settings = settings or get_settings()
    self._static_rag = StaticRAGService(self._settings)
    self._web_rag = WebRAGService()
    self._evidence_controller = EvidenceController()
    self._query_classifier = QueryRequirementClassifier()
    self._claim_verifier = ClaimVerifier()
    # Initialize Sarvam provider once, reuse across requests
    try:
        from app.providers.sarvam_chat import SarvamChatProvider
        self._sarvam = SarvamChatProvider(self._settings)
    except (ValueError, ImportError):
        self._sarvam = None  # Will fall back to Groq+Gemini
```

- [ ] **Step 3: Replace grounded_answer() with Sarvam + fallback**

In the `run()` method, replace the `grounded_answer()` call (lines 157-172) with:

```python
from app.providers.groq_llm import GroqLLMProvider
from app.providers.gemini_llm import GeminiLLMProvider
from app.llm_fallback import grounded_answer

# Sarvam is primary. Fallback to Groq+Gemini only on provider failure.
# Do NOT fall back because citation check fails — that's semantic verification
# which is out of scope for MVP.
if self._sarvam is not None:
    try:
        answer = self._sarvam.generate(system_prompt, user_prompt)
    except SarvamProviderError as exc:
        # Only provider failures (403, 429, 5xx, timeout) reach here
        # Programming errors (KeyError, ValueError, etc.) propagate naturally
        import logging
        logging.warning("Sarvam provider failed, falling back to Groq: %s", exc)
        answer = grounded_answer(
            GroqLLMProvider(self._settings),
            GeminiLLMProvider(self._settings),
            system_prompt,
            user_prompt,
        )
        mode = "groq_fallback"
else:
    answer = grounded_answer(
        GroqLLMProvider(self._settings),
        GeminiLLMProvider(self._settings),
        system_prompt,
        user_prompt,
    )
    mode = "groq_fallback"
```

- [ ] **Step 3: Add evidence assessment before prompt construction**

Before the `build_curated_prompt()` call, add:

```python
# Assess evidence
assessment = self._evidence_controller.assess_evidence(
    static_result, web_result, query_requirements
)

# Build prompt with assessment
system_prompt, user_prompt = self._evidence_controller.build_curated_prompt(
    bundle, english_query, history, lang,
    language_mix=language_mix,
    assessment=assessment,
)
```

- [ ] **Step 4: Add strip_citations() call after LLM generation**

After the LLM generates `answer`, add:

```python
from app.evidence_controller import strip_citations

# Strip internal citation markers from visible answer
clean_answer, extracted_ids = strip_citations(answer)
answer = clean_answer
```

- [ ] **Step 5: Verify citation verification still works**

The existing `verify_citations()` call (line 179-191) should still work because it extracts `[chunk:xxx]` from the answer. Since we strip them before verification, we need to move the strip call AFTER verification, or adjust verification to work on the original answer.

**Correct order:**
```python
# 1. LLM generates answer with [chunk:ID] markers
answer = self._sarvam.generate(system_prompt, user_prompt)

# 2. Verify citations (needs original answer with markers)
# This only checks set-membership (do cited IDs exist in evidence?)
# It does NOT verify semantic claim support — that's out of scope for MVP
verify_citations(answer, all_chunk_ids)

# 3. Strip markers for client delivery
clean_answer, _ = strip_citations(answer)
answer = clean_answer
```

**Important:** Citation verification failure does NOT trigger Groq fallback. The verifier only checks set-membership. A citation pointing to a valid but irrelevant chunk is not grounds for provider fallback — that would require semantic verification which is out of scope.

- [ ] **Step 6: Run orchestrator tests**

Run: `cd backend && python -m pytest tests/ -k "orchestrator" -v`
Expected: Tests PASS (may need mock updates for SarvamChatProvider)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/rag_orchestrator.py
git commit -m "feat(orchestrator): use SarvamChatProvider, add evidence assessment, strip citations"
```

---

### Task 9: Remove Output Translation from Chat Route

**Files:**
- Modify: `backend/app/routes/chat.py:94-123,300-324,407-424`
- Modify: `backend/app/routes/chat.py:159-170` (_ChatContext)

**Interfaces:**
- Consumes: `language_mix` from `detect_query_languages()`
- Produces: `RAGResponse` without output translation

- [ ] **Step 1: Add language_mix to _ChatContext**

In `backend/app/routes/chat.py`, add `language_mix` to the `_ChatContext` dataclass (around line 159):

```python
@dataclass
class _ChatContext:
    lang: str
    english_query: str
    embedding: list[float]
    domain: str
    resolved_state: str | None
    classification: QueryClassification | None
    history: list[dict]
    settings: Settings
    language_mix: dict[str, float] | None = None  # NEW
```

- [ ] **Step 2: Update _resolve_context() to compute language_mix**

In `_resolve_context()` (around line 178), add `language_mix` to the detection:

```python
detected = detect_query_languages(req.question)
lang = detected["dominant"] or "en"
language_mix = detected.get("language_mix")  # NEW
```

And add `language_mix=language_mix` to the `_ChatContext` construction.

- [ ] **Step 3: Pass language_mix to orchestrator.run()**

In the `orchestrator.run()` call (lines 300-311), add:

```python
language_mix=ctx.language_mix,
```

- [ ] **Step 4: Remove output translation (non-streaming)**

Delete or comment out lines 314-317:

```python
# REMOVED: Sarvam generates directly in user's language
# if ctx.lang != "en":
#     rag_response.answer = _translate_from_english(rag_response.answer, ctx.lang, ctx.settings)
#     rag_response.speech_text = prepare_speech_text(rag_response.answer)
#     rag_response.speech_segments = segment_speech(rag_response.answer, ctx.lang)
```

Keep the `speech_text` and `speech_segments` generation (just remove the translation):

```python
rag_response.speech_text = prepare_speech_text(rag_response.answer)
rag_response.speech_segments = segment_speech(rag_response.answer, ctx.lang)
```

- [ ] **Step 5: Remove output translation (streaming)**

Same change for the streaming endpoint (lines 421-424).

- [ ] **Step 6: Add fallback translation for Groq path**

If the orchestrator falls back to Groq, the answer will be in English. Add a check:

```python
# If orchestrator used Groq fallback (answer in English), translate back
if rag_response.mode == "groq_fallback" and ctx.lang != "en":
    rag_response.answer = _translate_from_english(rag_response.answer, ctx.lang, ctx.settings)

rag_response.speech_text = prepare_speech_text(rag_response.answer)
rag_response.speech_segments = segment_speech(rag_response.answer, ctx.lang)
```

Note: The orchestrator should set `mode` to indicate which provider was used, or the chat route should detect this. Simplest: add a `provider_used` field to RAGResponse or check if the orchestrator raises a specific flag.

- [ ] **Step 7: Run chat route tests**

Run: `cd backend && python -m pytest tests/ -k "chat" -v`
Expected: Tests PASS

- [ ] **Step 8: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/chat.py
git commit -m "feat(chat): remove output translation, pass language_mix to orchestrator"
```

---

### Task 10: Update Frontend Chunk ID Regex

**Files:**
- Modify: `frontend/src/components/chat/MessageBubble.tsx:25-55` (cleanAnswerText)

**Interfaces:**
- Consumes: answer text from backend (should already be clean)
- Produces: UI-only defense regex

- [ ] **Step 1: Expand cleanAnswerText() regex**

In `frontend/src/components/chat/MessageBubble.tsx`, update the `cleanAnswerText()` function:

```typescript
function cleanAnswerText(text: string): string {
  if (!text) return text;
  let cleaned = text;

  // Remove ALL chunk citation patterns (any format, case-insensitive)
  // Matches: [chunk:xxx], (chunk:xxx), [Chunk:xxx], [CHUNK:xxx]
  // where xxx can be any characters (hex, web_ prefix, UUIDs, empty, etc.)
  cleaned = cleaned.replace(/\[chunk:[^\]]*\]/gi, '');
  cleaned = cleaned.replace(/\(chunk:[^\)]*\)/gi, '');

  cleaned = cleaned.replace(/\s+/g, ' ').trim();
  return cleaned;
}
```

**Note:** No hardcoded disclaimer patterns. Response quality is handled by the backend prompt and evidence controller — not by frontend string matching.

- [ ] **Step 2: Verify citations panel doesn't show chunk_id**

Check the citations panel rendering (lines 227-254) — it should only show `c.title`, `c.page`, `c.source_label`, `c.url`. Verify `c.chunk_id` is NOT rendered anywhere in the panel.

- [ ] **Step 3: Build frontend to verify no TypeScript errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chat/MessageBubble.tsx
git commit -m "fix(frontend): expand chunk ID regex to match any format (UI-only defense)"
```

---

### Task 11: Integration Test — End-to-End Flow

**Files:**
- Create: `tests/test_integration_sarvam.py`

**Interfaces:**
- Tests the full flow: query → language detection → translation → retrieval → Sarvam → strip citations → clean answer

- [ ] **Step 1: Write integration test**

Create `tests/test_integration_sarvam.py`:

```python
"""Integration test for Sarvam LLM migration end-to-end flow."""
import pytest
from unittest.mock import patch, MagicMock

from app.evidence_controller import EvidenceController, strip_citations
from app.contracts import (
    RAGResult, EvidenceChunk, QueryRequirements,
    SourceRole, EvidenceSufficiency,
)


def test_strip_citations_removes_all_formats():
    """Verify backend guarantee: no [chunk:xxx] in answer after stripping."""
    answers = [
        "Scheme requires [chunk:a0eebc99] registration.",
        "Premium is [chunk:web_a1b2c3d4e5f6_c102] ₹2000.",
        "Multiple [chunk:abc12345] and [chunk:web_xyz789_c42] citations.",
        "No citations here.",
        "Edge case: [chunk:] empty id.",
    ]
    for answer in answers:
        clean, ids = strip_citations(answer)
        assert "[chunk:" not in clean, f"Chunk ID leaked in: {clean}"
        assert "(chunk:" not in clean, f"Chunk ID leaked in: {clean}"


def test_evidence_assessment_flow():
    """Test the full assessment flow from RAGResult to prompt text."""
    controller = EvidenceController()

    static_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="static_001", content="Policy text", source_type="static",
                      title="PMFBY Guidelines", dense_score=0.8),
        EvidenceChunk(chunk_id="static_002", content="Rules text", source_type="static",
                      title="Eligibility Criteria", dense_score=0.7),
    ])
    web_result = RAGResult(chunks=[
        EvidenceChunk(chunk_id="web_abc123_c1", content="Current premium", source_type="web",
                      title="Current Rates", url="https://example.com", dense_score=0.9),
    ])
    query_req = QueryRequirements(
        temporal_scope="current",
        geographic_scope="state",
        required_specificity="state",
        requires_dynamic=True,
    )

    assessment = controller.assess_evidence(static_result, web_result, query_req)
    assert assessment.source_role == SourceRole.WEB_PRIMARY
    assert assessment.sufficiency in (EvidenceSufficiency.SUFFICIENT, EvidenceSufficiency.PARTIAL)
    assert "Dynamic evidence" in assessment.assessment_text or "web" in assessment.assessment_text.lower()
```

- [ ] **Step 2: Run integration tests**

Run: `cd backend && python -m pytest tests/test_integration_sarvam.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_sarvam.py
git commit -m "test: add integration tests for Sarvam migration end-to-end flow"
```

---

## Summary

After completing all 11 tasks:

1. **Sarvam-105B** is the primary LLM with 3-tier fallback (Sarvam × 2 → Groq → abstain)
2. **Output translation eliminated** — Sarvam generates directly in user's language
3. **Input translation kept** — Jina v3 needs English embeddings
4. **Mixed language support** — `language_mix` detection + prompt instruction to preserve code-switching
5. **Chunk IDs stripped** — backend guarantee via `strip_citations()`, frontend UI-only defense
6. **Evidence assessment** — source-role rules override raw scores, sufficiency check prevents bad evidence reaching LLM
7. **Prompt rewritten** — rural-friendly tone, clear evidence roles, citation requirements
8. **No extra model calls** — set-membership citation validation only, no semantic verification

**Remaining after this plan:**
- Provider account setup (Sarvam API keys in `.env`)
- Deploy to production (Render + Vercel)
- Curate real gold answer spans for evaluation
