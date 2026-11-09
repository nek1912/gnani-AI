import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.chat import router as chat_router
from app.routes.voice import router as voice_router
from app.routes.conversations import router as conversations_router
from app.routes.evidence import router as evidence_router
from app.routes.grievance import router as grievance_router
from app.routes.documents import router as documents_router
from app.routes.translate import router as translate_router
from app.routes.webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO,
                    format='{"level":"%(levelname)s","msg":"%(message)s"}')


@asynccontextmanager
async def lifespan(_: FastAPI):
    # P1: verify sessions.user_id migration applied at startup.
    # The migration (supabase/migrations/20261007_sessions_user_id.sql)
    # adds user_id TEXT + index; without it, session ownership checks
    # stay disabled but visible (legacy NULL rows quarantined).
    try:
        from app.db import get_supabase
        get_supabase().table("sessions").select("session_id,user_id").limit(1).execute()
    except Exception as e:
        if "user_id" in str(e):
            logging.getLogger(__name__).error(
                "sessions.user_id column missing — run supabase/migrations/20261007_sessions_user_id.sql"
            )
        else:
            logging.getLogger(__name__).exception("Startup database check failed")
    yield


app = FastAPI(title="Sahayak API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware,
                   allow_origins=get_settings().origins,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(conversations_router)
app.include_router(evidence_router)
app.include_router(grievance_router)
app.include_router(documents_router)
app.include_router(translate_router)
app.include_router(webhooks_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/health/providers")
def health_providers() -> dict:
    s = get_settings()
    return {
        "groq": "configured" if s.groq_api_key else "missing",
        "gemini": "configured" if s.gemini_api_key else "missing",
        "jina": "configured" if s.jina_api_key else "missing",
        "supabase": "configured" if s.supabase_url else "missing",
        # "bhashini" is a legacy key kept for contract stability; the system
        # never integrated Bhashini (translation is Sarvam → Azure).
        "bhashini": "stub",
        "sarvam": "configured" if s.sarvam_api_key else "missing",
        "azure_speech": "configured" if s.azure_speech_key else "missing",
        "gnani": "configured" if s.gstn_api_key else "missing",
        "tavily": "configured" if s.tavily_api_key_1 else "missing",
        "serpapi": "configured" if s.serpapi_api_key_1 else "missing",
        "firecrawl": "configured" if s.firecrawl_api_key else "missing",
        "clerk": "configured" if s.clerk_secret_key else "missing",
        # The secret key alone proves nothing: auth.py verifies tokens against the
        # ISSUER's JWKS, so a wrong/missing issuer 401s every request while this
        # endpoint still reports "configured". Surface the value that actually
        # decides auth so a mismatch is diagnosable without a browser.
        "clerk_issuer": s.clerk_issuer or "MISSING",
    }
