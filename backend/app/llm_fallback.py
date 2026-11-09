import httpx

from app.providers.base import LLMProvider


class AllProvidersFailedError(Exception): ...


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503, 504)


import logging

logger = logging.getLogger(__name__)

def grounded_answer(
    primary: LLMProvider,
    fallback: LLMProvider,
    system: str,
    user: str,
    tertiary: LLMProvider | None = None,
) -> str:
    providers = [("groq", primary), ("gemini", fallback)]
    if tertiary:
        providers.append(("sarvam", tertiary))

    errors: list[str] = []
    for name, provider in providers:
        try:
            logger.info(f"Calling LLM provider: {name}")
            return provider.generate(system, user)
        except Exception as exc:
            logger.warning(f"{name} failed, falling back: {exc!r}")
            errors.append(f"{name}: {exc!r}")
    raise AllProvidersFailedError("; ".join(errors))
