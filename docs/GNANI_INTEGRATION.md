# Gnani AI Integration — JanSahay Voice Pipeline

Gnani AI (Vachana API) is the **primary** speech intelligence provider for JanSahay,
sitting first in both the STT and TTS fallback chains:

```
STT:   Gnani Prisma v3.0  →  Sarvam  →  Azure  →  VoiceUnavailableError
TTS:   Gnani Timbre v3.0  →  Sarvam  →  Azure  →  VoiceUnavailableError
```

> **Important architectural boundary:** Gnani AI is strictly responsible for speech intelligence (STT and TTS). Reasoning, retrieval, evidence gating, and answer synthesis are handled by Groq/Gemini against verified corpus chunks. Gnani never generates factual claims.

---

## Provider Files

| File | Contents |
|---|---|
| `backend/app/providers/gnani_voice.py` | `GnaniSTTProvider`, `GnaniTTSProvider`, `STTResult`, `TTSResult`, exceptions, language normalization |
| `backend/app/services/voice_service.py` | Sequential fallback chain (Gnani → Sarvam → Azure) with monotonic timing and audio duration guard |
| `backend/app/routes/voice.py` | HTTP routes (`/voice/transcribe`, `/voice/speak`, `/voice`) exposing observability metadata |
| `backend/app/config.py` | `gstn_api_key`/`gstn_keys` + Gnani configuration settings |
| `backend/.env.example` | Server-side environment variables |
| `backend/app/main.py` | `gnani` in `/health/providers` status |
| `backend/tests/test_gnani_voice.py` | Respx-mocked unit tests and optional live smoke test |
| `backend/tests/test_voice_service.py` | Multi-provider fallback and timeout orchestration tests |
| `backend/tests/test_voice_routes.py` | Route-level contract and metadata verification tests |

---

## API Endpoints

### STT (Prisma v3.0) — `POST https://api.vachana.ai/stt/v3`
- `multipart/form-data`: `audio_file`, `model=prisma-v3.0`, `language_code`, `format`
- Header: `X-API-Key-ID: <GNANI_API_KEY>`
- Returns JSON: `{success, transcript, model, detected_language_code, processing_time, ...}`
- Max audio: 30 seconds (durations > 30s are automatically pre-routed to Sarvam STT)
- 10 supported languages: bn, en, gu, hi, kn, ml, mr, pa, ta, te (no Odia)
- Language auto-detection: `indic-auto` or `auto` detects language and returns `detected_language`
- Client Web Audio Pipeline:
  - `AudioContext` autoplay resumption: explicitly awaits `resume()` to avoid silent capture in Chromium browsers.
  - Zero-gain destination routing: routes `source -> processor -> muteGain(0.0) -> destination` to prevent mic audio playback into speakers which triggers WebRTC AEC self-cancelling.
  - Strict 16kHz downsampling: decimation with box-car anti-aliasing (`downsampleTo16k`) normalizes 44.1kHz / 48kHz audio to 16,000 Hz 16-bit mono PCM.
  - Realistic VAD: 0.005 RMS threshold with 1.6s conversational silence timeout and immediate manual stop transcription.

### TTS (Timbre v3.0) — `POST https://api.vachana.ai/api/v1/tts/inference`
- JSON body: `{text, voice, model=timbre-v3.0, language, speed, audio_config}`
- Header: `X-API-Key-ID: <GNANI_API_KEY>`
- Returns raw binary WAV audio
- Concurrency guard: `_gnani_tts_request_lock = asyncio.Lock()` serializes calls to strictly adhere to Gnani's 1-active-request limit, eliminating HTTP 429 errors.
- Fast-response caching: in-memory LRU cache (`_tts_cache`) returns previously synthesized audio in `<1ms`.
- Voice answer summarization: `summarize_for_speech(answer, max_chars=400)` bounds voice synthesis to concise, natural 2–3 sentence answers, reducing latency from ~30s to ~1.8s.
- Clean text preprocessing: markdown syntax (tables, bold/italics, bullet points, headers) is stripped before synthesis.
- Supports custom voice selection (`Avinash`, `Shivani`, `Lakshmi`, `Kalpana`, etc.) validated against official catalog.
- Supports validated speed scaling: `0.5` to `2.0` (default: `1.0`).
- Same 10 languages; Odia cleanly routes to Sarvam/Azure.

---

## Observability & Metadata Contract

API routes `/voice/transcribe` and `/voice/speak` return rich telemetry while preserving 100% backward compatibility:

### Transcribe Response (`POST /voice/transcribe`)
```json
{
  "text": "પ્રધાનમંત્રી ફસલ બીમા યોજના શું છે?",
  "language": "gu",
  "requested_language": "gu",
  "detected_language": "gu",
  "provider": "gnani",
  "model": "prisma-v3.0",
  "duration_ms": 142.5,
  "fallback_occurred": false
}
```

### Speak Response (`POST /voice/speak`)
```json
{
  "audio": "<hex_encoded_wav>",
  "language": "hi",
  "provider": "gnani",
  "model": "timbre-v3.0",
  "voice": "Shivani",
  "duration_ms": 218.4,
  "audio_format": "wav",
  "fallback_occurred": false
}
```

---

## Language Support

Gnani natively supports 10 Indic/English languages. Odia (`or`) is intentionally absent from the Gnani catalog and automatically falls through to Sarvam or Azure:

| JanSahay code | Gnani BCP-47 | Supported by Gnani | Fallback on Unsupported |
|---|---|---|---|
| `en` | `en-IN` | Yes | N/A |
| `hi` | `hi-IN` | Yes | N/A |
| `gu` | `gu-IN` | Yes | N/A |
| `mr` | `mr-IN` | Yes | N/A |
| `bn` | `bn-IN` | Yes | N/A |
| `ta` | `ta-IN` | Yes | N/A |
| `te` | `te-IN` | Yes | N/A |
| `kn` | `kn-IN` | Yes | N/A |
| `pa` | `pa-IN` | Yes | N/A |
| `ml` | `ml-IN` | Yes | N/A |
| `or` | *(none)* | No | Clean fallback to Sarvam/Azure |

---

## Exception Hierarchy

```
GnaniError (RuntimeError)
├── GnaniAuthenticationError          # 401/403 — invalid or missing API key
├── GnaniRateLimitedError             # 429 — rate limited with exponential backoff
├── GnaniServiceUnavailableError      # 503 — provider temporarily down
├── GnaniTimeoutError                 # Request exceeded timeout limit
└── GnaniAudioDurationExceededError   # Audio exceeds 30-second ceiling
```

---

## Testing

Run the voice test suite (87 unit & route tests, all mocked with respx):

```bash
cd backend
pytest tests/test_gnani_voice.py tests/test_voice_service.py tests/test_voice_routes.py -v
```

An optional live provider test runs only when explicitly requested:
```bash
RUN_LIVE_TESTS=1 GNANI_API_KEY="<key>" pytest tests/test_gnani_voice.py -k test_live_gnani_smoke_test
```
