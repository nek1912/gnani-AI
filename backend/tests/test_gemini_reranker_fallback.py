"""Regression tests for bounded Gemini reranking and fallback provenance."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import Settings
from app.retrieval import gemini_reranker as gr_module
from app.retrieval.gemini_reranker import GEMINI_MIN_DEADLINE_S, GeminiReranker


CANDIDATES = [
    {"chunk_id": "web_a", "text": "PMFBY evidence", "rrf_score": 0.03},
    {"chunk_id": "web_b", "text": "Other evidence", "rrf_score": 0.02},
]


def _reranker() -> GeminiReranker:
    reranker = GeminiReranker.__new__(GeminiReranker)
    reranker._enabled = True
    reranker.client = Mock()
    reranker.model = "test-model"
    return reranker


def _gemini_result() -> dict:
    return {
        "ranked_chunks": [
            {
                "chunk_id": "web_a",
                "relevance_score": 90,
                "applicable": True,
                "applicability_reason": "direct",
            }
        ],
        "merge_groups": [],
    }


def test_gemini_success_is_authoritative() -> None:
    reranker = _reranker()

    with patch.object(reranker, "_try_gemini", return_value=_gemini_result()) as gemini, patch.object(
        reranker, "_try_jina_fallback"
    ) as jina:
        result = reranker._call_gemini("query", CANDIDATES, {})

    assert result["reranker_used"] == "gemini"
    assert "reranker_fallback_reason" not in result
    gemini.assert_called_once()
    jina.assert_not_called()


def test_gemini_503_uses_jina_and_records_reason() -> None:
    reranker = _reranker()
    jina_result = {
        "ranked_chunks": [],
        "merge_groups": [],
    }

    with patch.object(reranker, "_try_gemini", side_effect=RuntimeError("503 Service Unavailable")), patch.object(
        reranker, "_try_jina_fallback", return_value=jina_result
    ) as jina:
        result = reranker._call_gemini("query", CANDIDATES, {})

    assert result["reranker_used"] == "jina"
    assert result["reranker_fallback_reason"] == "gemini_503"
    jina.assert_called_once()


def test_gemini_timeout_uses_jina() -> None:
    reranker = _reranker()
    with patch.object(reranker, "_try_gemini", side_effect=TimeoutError("timed out")), patch.object(
        reranker,
        "_try_jina_fallback",
        return_value={"ranked_chunks": [], "merge_groups": []},
    ) as jina:
        result = reranker._call_gemini("query", CANDIDATES, {})

    assert result["reranker_used"] == "jina"
    assert result["reranker_fallback_reason"] == "gemini_timeout"
    jina.assert_called_once()


# ---------------------------------------------------------------------------
# Deadline validity (live 400 INVALID_ARGUMENT: "Minimum allowed deadline is 10s")
# ---------------------------------------------------------------------------


def _settings_for(timeout_s: float) -> SimpleNamespace:
    return SimpleNamespace(
        reranker_enabled=True,
        gemini_api_key="test-key",
        gemini_model="test-model",
        grievance_gemini_model="test-model",
        gemini_reranker_timeout_s=timeout_s,
    )


def _init_client_timeout_ms(timeout_s: float) -> int:
    """Run the real __init__ with mocked settings/client; return HttpOptions timeout (ms)."""
    with patch.object(gr_module, "get_settings", return_value=_settings_for(timeout_s)), \
        patch.object(gr_module.genai, "Client") as mock_client:
        GeminiReranker()
    http_options = mock_client.call_args.kwargs["http_options"]
    return int(http_options.timeout)


def test_settings_default_deadline_satisfies_api_minimum() -> None:
    assert GEMINI_MIN_DEADLINE_S == 10.0
    assert Settings().gemini_reranker_timeout_s >= GEMINI_MIN_DEADLINE_S


def test_sub_minimum_config_is_clamped_to_api_minimum() -> None:
    """An explicit 8s override must not reach Gemini (was live 400 INVALID_ARGUMENT)."""
    assert _init_client_timeout_ms(8.0) == 10000


def test_valid_configured_deadline_is_preserved() -> None:
    """Timeout protection stays intact for compliant values."""
    assert _init_client_timeout_ms(15.0) == 15000
    assert _init_client_timeout_ms(10.0) == 10000
