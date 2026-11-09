# Final Execution Plan

**Date:** 2026-08-28
**Mode:** Plan mode (READ-ONLY) - execute after user approval
**Approach:** MVP-first, voice providers created but disabled

---

## Phase 1: Core Pipeline Fixes (30 min)

### Step 1.1: Wire evidence_gate_v2
**File:** `backend/app/routes/chat.py`
**Change:**
```python
# Line 82: Change FROM:
gate = evidence_gate(chunks, expected_domain=domain, expected_state=resolved_state)

# TO:
gate = evidence_gate_v2(chunks, expected_domain=domain, expected_state=resolved_state)
```
**Why:** v2 has typed AbstentionReason, defense-in-depth checks

### Step 1.2: Wire reranker
**File:** `backend/app/routes/chat.py`
**Change:**
```python
# Add import:
from app.providers.reranker import JinaReranker

# After line 78 (after retrieve_hybrid), add:
reranker = JinaReranker()
if settings.RERANKER_ENABLED:
    chunks = reranker.rerank(req.question, chunks)
```
**File:** `backend/app/config.py`
**Add:**
```python
RERANKER_ENABLED: bool = False  # Feature flag, disabled by default
```

### Step 1.3: Apply migration 0005
**Command:** `supabase db push`
**Verify:** Tables created (embedding_profiles, corpus_versions, etc.)

---

## Phase 2: Jina Task-Type Differentiation (15 min)

### Step 2.1: Add task parameter
**File:** `backend/app/providers/embeddings.py`
**Change:**
```python
# Update embed_texts signature:
def embed_texts(self, texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:

# Update JSON payload in _embed_batch:
json={
    "model": self._model,
    "input": texts,
    "dimensions": EMBED_DIMS,
    "task": task,  # Add this line
}
```

### Step 2.2: Update callers
**File:** `backend/app/routes/chat.py`
**Change:**
```python
# Line 66: Change FROM:
embedding = provider.embed_texts([req.question])[0]

# TO:
embedding = provider.embed_texts([req.question], task="retrieval.query")[0]
```

---

## Phase 3: Voice Providers (2-3 hours)

### Step 3.1: Azure voice provider
**File:** `backend/app/providers/azure_voice.py` (CREATE)
```python
"""Azure Cognitive Services voice provider (primary)."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AzureVoiceProvider:
    """Azure Speech Services for STT and TTS."""

    def __init__(self):
        self.speech_key = os.getenv("AZURE_SPEECH_KEY", "")
        self.speech_region = os.getenv("AZURE_SPEECH_REGION", "centralindia")
        self.enabled = bool(self.speech_key)

        if not self.enabled:
            logger.info("Azure voice disabled: AZURE_SPEECH_KEY not set")

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Convert speech to text."""
        if not self.enabled:
            raise RuntimeError("Azure voice not configured")

        # TODO: Implement when AZURE_SPEECH_KEY is provided
        # Use azure-cognitiveservices-speech SDK
        raise NotImplementedError("Azure STT not yet implemented")

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to speech."""
        if not self.enabled:
            raise RuntimeError("Azure voice not configured")

        # TODO: Implement when AZURE_SPEECH_KEY is provided
        raise NotImplementedError("Azure TTS not yet implemented")
```

### Step 3.2: Sarvam voice provider
**File:** `backend/app/providers/sarvam_voice.py` (CREATE)
```python
"""Sarvam AI voice provider (fallback for Indian languages)."""

import os
import logging

logger = logging.getLogger(__name__)


class SarvamVoiceProvider:
    """Sarvam AI for Indian language STT and TTS."""

    def __init__(self):
        self.api_key = os.getenv("SARVAM_API_KEY", "")
        self.base_url = "https://api.sarvam.ai"
        self.enabled = bool(self.api_key)

        if not self.enabled:
            logger.info("Sarvam voice disabled: SARVAM_API_KEY not set")

    async def speech_to_text(self, audio_bytes: bytes, language: str = "hi") -> str:
        """Convert speech to text."""
        if not self.enabled:
            raise RuntimeError("Sarvam voice not configured")

        # TODO: Implement when SARVAM_API_KEY is provided
        raise NotImplementedError("Sarvam STT not yet implemented")

    async def text_to_speech(self, text: str, language: str = "hi") -> bytes:
        """Convert text to speech."""
        if not self.enabled:
            raise RuntimeError("Sarvam voice not configured")

        # TODO: Implement when SARVAM_API_KEY is provided
        raise NotImplementedError("Sarvam TTS not yet implemented")
```

### Step 3.3: Voice service with fallback
**File:** `backend/app/services/voice_service.py` (CREATE)
```python
"""Voice service with provider fallback chain."""

import logging
from typing import Optional
from app.providers.azure_voice import AzureVoiceProvider
from app.providers.sarvam_voice import SarvamVoiceProvider

logger = logging.getLogger(__name__)


class VoiceService:
    """Manages voice providers with fallback chain.

    Fallback order: Azure → Sarvam → text-only
    """

    def __init__(self):
        self.providers = [
            ("azure", AzureVoiceProvider()),
            ("sarvam", SarvamVoiceProvider()),
        ]

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Convert speech to text with fallback."""
        for name, provider in self.providers:
            try:
                return await provider.speech_to_text(audio_bytes, language)
            except Exception as e:
                logger.warning(f"{name} STT failed: {e}")
                continue

        raise VoiceUnavailableError("No voice providers available. Please type your question.")

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to speech with fallback."""
        for name, provider in self.providers:
            try:
                return await provider.text_to_speech(text, language)
            except Exception as e:
                logger.warning(f"{name} TTS failed: {e}")
                continue

        raise VoiceUnavailableError("No voice providers available.")


class VoiceUnavailableError(Exception):
    """Raised when all voice providers fail."""
    pass
```

### Step 3.4: Voice routes
**File:** `backend/app/routes/voice.py` (CREATE)
```python
"""Voice routes for STT and TTS."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.voice_service import VoiceService, VoiceUnavailableError

router = APIRouter()
voice_service = VoiceService()


class TranscribeRequest(BaseModel):
    audio: bytes
    language: str = "en"


class SpeakRequest(BaseModel):
    text: str
    language: str = "en"


@router.post("/voice/transcribe")
async def transcribe(req: TranscribeRequest) -> dict:
    """Convert speech to text."""
    try:
        text = await voice_service.speech_to_text(req.audio, req.language)
        return {"text": text, "language": req.language}
    except VoiceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/voice/speak")
async def speak(req: SpeakRequest) -> dict:
    """Convert text to speech."""
    try:
        audio = await voice_service.text_to_speech(req.text, req.language)
        return {"audio": audio.hex(), "language": req.language}
    except VoiceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
```

### Step 3.5: Register voice routes
**File:** `backend/app/main.py`
**Change:**
```python
# Add import:
from app.routes import voice

# Add after other router includes:
app.include_router(voice.router)
```

---

## Phase 4: Confidence Calibration (30 min)

### Step 4.1: Replace heuristic
**File:** `backend/app/evidence_gate.py`
**Change:**
```python
# Replace compute_confidence function:

def compute_confidence(
    chunks: list,
    top1_score: float,
    domain_match: bool,
) -> float:
    """Compute confidence based on retrieval signals.

    Returns float between 0.0 and 1.0.
    """
    if not chunks:
        return 0.0

    # Base from top retrieval score
    base = top1_score * 0.6

    # Supporting evidence bonus
    supporting = sum(1 for c in chunks if getattr(c, 'score', 0) > 0.3)
    coverage = min(supporting / 3, 1.0) * 0.3

    # Domain match bonus
    domain = 0.1 if domain_match else 0.0

    confidence = base + coverage + domain

    # Hard cap for low-relevance
    if top1_score < 0.3:
        confidence = min(confidence, 0.4)

    return round(confidence, 2)
```

---

## Phase 5: Run Ingestion (30 min)

### Step 5.1: Run ingestion on existing MD files
**Command:**
```bash
cd D:\Downloads\New folder
python -m ingestion.ingest
```
**Verify:** Chunk count increases from 226

---

## Files to Create/Modify

| File | Action | Phase |
|------|--------|-------|
| `backend/app/routes/chat.py` | MODIFY | 1 |
| `backend/app/config.py` | MODIFY | 1 |
| `backend/app/providers/embeddings.py` | MODIFY | 2 |
| `backend/app/providers/azure_voice.py` | CREATE | 3 |
| `backend/app/providers/sarvam_voice.py` | CREATE | 3 |
| `backend/app/services/voice_service.py` | CREATE | 3 |
| `backend/app/routes/voice.py` | CREATE | 3 |
| `backend/app/main.py` | MODIFY | 3 |
| `backend/app/evidence_gate.py` | MODIFY | 4 |

---

## Environment Variables

```env
# Voice (disabled until keys provided)
AZURE_SPEECH_KEY=          # Leave empty to disable
AZURE_SPEECH_REGION=centralindia
SARVAM_API_KEY=            # Leave empty to disable

# Existing (already set)
JINA_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

---

## Verification Checklist

After execution, verify:

- [ ] All 183 tests pass (no regressions)
- [ ] PMFBY question → answer with citations
- [ ] Hindi question → answer in Hindi
- [ ] Out-of-scope question → abstention
- [ ] Voice endpoints return 503 (disabled) with helpful message
- [ ] `python -m ingestion.ingest` completes successfully
