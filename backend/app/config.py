from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str:
    """
    Locate the real .env regardless of the directory uvicorn was launched from.

    pydantic-settings resolves a relative `env_file` against the process CWD, so
    `env_file=".env"` silently picked up a DIFFERENT file depending on whether
    you ran `uvicorn app.main:app` from backend/ or `uvicorn app.main:app
    --app-dir backend` from the repo root.

    backend/.env is the single source of truth for backend configuration,
    resolved by absolute path — never relative to CWD. A repo-root .env, if
    present, is NOT read; it is reported loudly so two files with conflicting
    keys can never silently disagree.
    """
    here = Path(__file__).resolve()
    backend_local = here.parent.parent / ".env"      # backend/.env (authoritative)
    repo_root = here.parent.parent.parent / ".env"  # NOT read for backend config

    if repo_root.exists() and repo_root != backend_local:
        import warnings

        warnings.warn(
            f"Ignoring {repo_root}. Backend configuration is read only from "
            f"{backend_local}. Move any backend keys into backend/.env, "
            "otherwise the two files will disagree.",
            RuntimeWarning,
            stacklevel=2,
        )

    return str(backend_local)


class Settings(BaseSettings):
    # Absolute path to backend/.env — never relative to CWD.
    model_config = SettingsConfigDict(env_file=_env_file(), extra="ignore")
    groq_api_key: str
    gemini_api_key: str = ""
    jina_api_key: str = ""
    jina_api_key_2: str = ""
    supabase_url: str
    supabase_service_key: str
    # NOTE: default ":3000" predates the Vite dev server on :5173 — a fresh
    # checkout needs ALLOWED_ORIGINS overridden or browser calls CORS-fail.
    allowed_origins: str = "http://localhost:3000"
    # NOTE (P1): the former `selected_state` field was removed — it had
    # zero readers (dead duplicate of session state). Jurisdiction comes
    # from req.state -> session state ("selected_state" key in the
    # sessions-row JSON, see session_store.py) -> explicit query words.
    # Do not reintroduce another global default state here.
    # Model IDs loaded directly from environment (.env)
    groq_model: str = ""
    groq_fallback_model: str = ""
    gemini_model: str = ""
    gemini_fallback_model: str = ""
    embed_model: str = ""  # Gemini embedding model id, e.g. "gemini-embedding-2".
    # WARNING: EMBED_MODEL (Gemini) vs EMBEDDING_MODEL (Jina) — different
    # providers, different vars (see note below). The production .env sets
    # EMBEDDING_MODEL but NOT EMBED_MODEL, so the Gemini embedding fallback
    # path raises until EMBED_MODEL is set. Jina is primary when configured.
    embedding_model: str = "jina-embeddings-v3"
    jina_embed_model: str = ""
    # NOTE: three vars for one concept (legacy). Precedence in
    # embeddings.py: jina_embed_model > embedding_model > built-in default.
    # embed_model is the GEMINI embedding model id (different provider).
    reranker_model: str = ""  # DEAD: no consumer (Jina reranker has no model id).
    # WARNING — RERANKER_ENABLED gates TWO independent rerankers, not one:
    #   * static RAG Jina rerank (static_rag.py), AND
    #   * WebRAG Gemini pre+final ranking (gemini_reranker.py degrades to
    #     passthrough when False). Do not read it as "Jina reranker only".
    reranker_enabled: bool = False
    retrieval_strategy: str = "dense"  # DEAD: no consumer (strategy is fixed hybrid+RRF).

    @property
    def groq_model_list(self) -> list[str]:
        models = []
        if self.groq_model:
            models.append(self.groq_model)
        if self.groq_fallback_model:
            models.extend([m.strip() for m in self.groq_fallback_model.split(",") if m.strip()])
        return list(dict.fromkeys(models))

    @property
    def gemini_model_list(self) -> list[str]:
        models = []
        if self.gemini_model:
            models.append(self.gemini_model)
        if self.gemini_fallback_model:
            models.extend([m.strip() for m in self.gemini_fallback_model.split(",") if m.strip()])
        return list(dict.fromkeys(models))
    # Azure Speech Services (PHASE 13 — voice I/O)
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    # Azure Translator (Phase 10 — multilingual query normalization)
    azure_translator_key: str = ""
    azure_translator_region: str = ""
    azure_translator_endpoint: str = ""
    # TTS voice names per language — configurable, not hardcoded
    # Voice IDs are the documented Azure neural voices for each locale; verify
    # against the live Azure Speech voice list before relying on a specific ID.
    azure_tts_voices: str = (
        "en:en-IN-NeerjaNeural,hi:hi-IN-SwaraNeural,gu:gu-IN-DhwaniNeural,"
        "mr:mr-IN-AarohiNeural,bn:bn-IN-TanishaaNeural"
    )
    # BCP-47 recognition/synthesis locale per language — configurable, not hardcoded
    azure_speech_locales: str = "en:en-IN,hi:hi-IN,gu:gu-IN,mr:mr-IN,bn:bn-IN"
    # Sarvam AI (STT, TTS, Translation — Indian languages)
    sarvam_api_key: str = ""
    sarvam_api_key_2: str = ""
    sarvam_chat_model: str = "sarvam-105b-conversations"
    sarvam_chat_url: str = "https://api.sarvam.ai/v1/chat/completions"

    # Gnani AI Vachana (STT Prisma v3.0 + TTS Timbre v3.0 — Indian languages)
    # Env var: GNANI_API_KEY (server-side only, never exposed to frontend).
    gstn_api_key: str = Field(default="", validation_alias="GNANI_API_KEY")
    gstn_stt_model: str = "prisma-v3.0"
    gstn_tts_model: str = "timbre-v3.0"
    gstn_tts_voice: str = "Shivani"
    gstn_stt_timeout_s: float = 30.0
    gstn_tts_timeout_s: float = 30.0
    gstn_stt_output_format: str = "verbatim"
    gstn_stt_auto_detect: bool = True

    # Groq LLM (primary) — multiple keys for rotation
    groq_api_key_1: str = ""
    groq_api_key_2: str = ""

    # Web search providers
    tavily_api_key_1: str = ""
    tavily_api_key_2: str = ""
    firecrawl_api_key: str = ""
    firecrawl_api_url: str = "https://api.firecrawl.dev/v1"
    serpapi_api_key_1: str = ""
    serpapi_api_key_2: str = ""
    # Single source of truth for provider selection together with the
    # SEARCH_PROVIDERS env var: web_rag/providers.py resolves as
    # explicit arg > os.getenv("SEARCH_PROVIDERS") > this setting >
    # DEFAULT_PROVIDERS, and logs the source plus the effective set.
    search_providers: str = "tavily"

    # Grievance & evidence
    # NOTE: despite the name, this model id is ALSO the Gemini reranker
    # model (gemini_reranker.py reads grievance_gemini_model, not
    # gemini_model). Renaming it requires touching the reranker too.
    grievance_gemini_model: str = "gemini-3.5-flash-lite"

    # Clerk authentication
    clerk_secret_key: str = ""
    clerk_webhook_secret: str = ""
    clerk_issuer: str = ""  # e.g. "https://clerk.your-app.com"

    # Answer grounding
    answer_grounding_llm_enabled: bool = False  # Enable LLM verification layer

    # Web RAG latency budgets
    # NOTE: google-genai rejects manually-set deadlines below 10s with
    # 400 INVALID_ARGUMENT, so this default must stay >= 10.0.
    gemini_reranker_timeout_s: float = 10.0
    jina_reranker_timeout_s: float = 5.0
    web_rag_timeout_s: float = 90.0

    @property
    def tts_voices(self) -> dict[str, str]:
        """Parse azure_tts_voices into a dict."""
        result: dict[str, str] = {}
        for pair in self.azure_tts_voices.split(","):
            if ":" in pair:
                lang, voice = pair.split(":", 1)
                result[lang.strip()] = voice.strip()
        return result

    @property
    def speech_locales(self) -> dict[str, str]:
        """Parse azure_speech_locales into a dict {language: BCP-47 locale}."""
        result: dict[str, str] = {}
        for pair in self.azure_speech_locales.split(","):
            if ":" in pair:
                lang, loc = pair.split(":", 1)
                result[lang.strip()] = loc.strip()
        return result

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def sarvam_keys(self) -> list[str]:
        """Return all non-empty Sarvam API keys for rotation."""
        keys = [k for k in [self.sarvam_api_key, self.sarvam_api_key_2] if k]
        return keys

    @property
    def groq_keys(self) -> list[str]:
        """Return all non-empty Groq API keys for rotation."""
        keys = [k for k in [self.groq_api_key, self.groq_api_key_1, self.groq_api_key_2] if k]
        return keys

    @property
    def jina_keys(self) -> list[str]:
        """Return all non-empty Jina API keys for rotation."""
        keys = [k for k in [self.jina_api_key, self.jina_api_key_2] if k]
        return keys

    @property
    def gstn_keys(self) -> list[str]:
        """Return all non-empty Gnani API keys for rotation."""
        keys = [k for k in [self.gstn_api_key] if k]
        return keys

EMBED_DIMS = 768
REQUEST_TIMEOUT_S = 30.0

# Generation limits (transplanted from eGovAssistant proven defaults)
GENERATION_MAX_TOKENS = 3500
GENERATION_TEMPERATURE = 0.0
MAX_CHARS_PER_CHUNK = 1500

# Retrieval gate thresholds (spec §2.4)
TOP1_THRESHOLD = 0.25
SECONDARY_THRESHOLD = 0.30
MIN_CHUNKS_ABOVE_SECONDARY = 2

@lru_cache
def get_settings() -> Settings:
    return Settings()
