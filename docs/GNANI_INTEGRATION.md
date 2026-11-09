# Gnani AI Integration — JanSahay Voice Pipeline

Gnani AI (Vachana API) is the **primary** voice provider for JanSahay,
sitting first in both the STT and TTS fallback chains:

```
STT:   Gnani Prisma v3.0  →  Sarvam  →  Azure  →  VoiceUnavailableError
TTS:   Gnani Timbre v3.0  →  Sarvam  →  VoiceUnavailableError  (Azure excluded)
```

## Provider files

| File | Contents |
|---|---|
| `backend/app/providers/gnani_voice.py` | `GnaniSTTProvider`, `GnaniTTSProvider`, exceptions, language mapping |
| `backend/app/services/voice_service.py` | Fallback chain orchestration (Gnani first) |
| `backend/app/config.py` | `gstn_api_key`/`gstn_keys` + Gnani settings fields |
| `backend/.env.example` | Gnani env var placeholders |
| `backend/app/main.py` | `gnani` in `/health/providers` response |
| `backend/tests/test_gnani_voice.py` | 47 tests, all respx-mocked |

## API endpoints

**STT (Prisma v3.0)** — `POST https://api.vachana.ai/stt/v3`
- `multipart/form-data`: `audio_file`, `model=prisma-v3.0`, `language_code`, `format`
- Header: `X-API-Key-ID: <GNANI_API_KEY>`
- Returns JSON: `{success, transcript, model, detected_language_code, processing_time, ...}`
- Max audio: 30 seconds
- 10 languages: bn, en, gu, hi, kn, ml, mr, pa, ta, te (no Odia)

**TTS (Timbre v3.0)** — `POST https://api.vachana.ai/api/v1/tts/inference`
- JSON body: `{text, voice, model=timbre-v3.0, language, speed, audio_config}`
- Header: `X-API-Key-ID: <GNANI_API_KEY>`
- Returns raw binary WAV audio (not JSON)
- Same 10 languages, no Odia

## Configuration (`backend/.env`)

| Variable | Default | Description |
|---|---|---|
| `GNANI_API_KEY` | *(required)* | Gnani API key ID |
| `GNANI_STT_MODEL` | `prisma-v3.0` | STT model name |
| `GNANI_TTS_MODEL` | `timbre-v3.0` | TTS model name |
| `GNANI_TTS_VOICE` | `Shivani` | Default TTS voice |
| `GNANI_STT_TIMEOUT_S` | `30` | STT request timeout (seconds) |
| `GNANI_TTS_TIMEOUT_S` | `30` | TTS request timeout (seconds) |
| `GNANI_STT_OUTPUT_FORMAT` | `verbatim` | STT output format |
| `GNANI_STT_AUTO_DETECT` | `true` | Use `indic-auto` language detection on STT |

The config field `gstn_api_key` maps to env var `GNANI_API_KEY` (pydantic
auto-uppercases). `gstn_keys` property returns all Gnani-related settings.

## Language support

Gnani supports 10 Indic/English languages. Odia (`or`) is **not** supported —
when Odia is requested, Gnani raises `GnaniError` and VoiceService falls
through to Sarvam/Azure automatically.

| JanSahay code | Gnani BCP-47 | Supported |
|---|---|---|
| `en` | `en-IN` | Yes |
| `hi` | `hi-IN` | Yes |
| `gu` | `gu-IN` | Yes |
| `mr` | `mr-IN` | Yes |
| `bn` | `bn-IN` | Yes |
| `ta` | `ta-IN` | Yes |
| `te` | `te-IN` | Yes |
| `kn` | `kn-IN` | Yes |
| `pa` | `pa-IN` | Yes |
| `ml` | `ml-IN` | Yes |
| `or` | *(none)* | No → Sarvam/Azure |

## Exception hierarchy

```
GnaniError (RuntimeError)
├─ GnaniAuthenticationError   # 401/403 — invalid API key
├─ GnaniRateLimitedError      # 429 — too many requests
├─ GnaniServiceUnavailableError  # 503 — provider down
└─ GnaniTimeoutError          # Request timed out
```

All `GnaniError` subclasses are caught by VoiceService and trigger fallback to
the next provider in the chain.

## Health endpoint

`GET /health/providers` includes `gnani` status (configured / not configured
based on presence of `GNANI_API_KEY`).

## Testing

Run `backend/tests/test_gnani_voice.py` — 47 tests, all respx-mocked (no real
Gnani credentials needed):

```bash
cd backend
uv run pytest tests/test_gnani_voice.py -v
```

Existing voice tests (`test_voice_service.py`, 15 tests) continue to pass with
Gnani first in the fallback chain.

## Fallback behavior without credentials

If `GNANI_API_KEY` is not set, `GnaniSTTProvider.enabled` and
`GnaniTTSProvider.enabled` are both `False`. VoiceService skips Gnani entirely
and proceeds directly to Sarvam → Azure, preserving existing behavior exactly.
