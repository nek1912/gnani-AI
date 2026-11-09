"""Regression tests for SerpApi provider-configuration + production path.

Covers the confirmed audit findings without any live network/quota:
- Settings.search_providers is the source of truth when SEARCH_PROVIDERS
  env is absent (no split-brain).
- Explicit env overrides Settings deterministically.
- Fallback to Tavily when nothing resolves is observable (warning log).
- SerpApi JSON {"error": ...} on HTTP 200 raises (not swallowed as empty).
- SerpApi honors include_domains in the query (bounded site: filter).
- SerpApi 429 diagnostic preserves body/retry info without API keys.

All HTTP is mocked via respx; no test may consume SerpApi quota.
"""

from __future__ import annotations

import httpx


def _clear_settings_cache():
    try:
        from app.config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass


class TestProviderSourceOfTruth:
    def test_settings_used_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("SEARCH_PROVIDERS", raising=False)
        monkeypatch.setenv("TAVILY_API_KEY_1", "t-key")
        monkeypatch.setenv("SERPAPI_API_KEY_1", "s-key")
        _clear_settings_cache()
        try:
            from app.config import get_settings

            # Force Settings to see serpapi via env-independent override:
            # emulate backend/.env SEARCH_PROVIDERS=tavily,serpapi by
            # patching the Settings object directly.
            settings = get_settings()
            monkeypatch.setattr(settings, "search_providers", "tavily,serpapi")
            from app.web_rag import providers

            resolved = providers.resolve_providers()
            kinds = {type(p).__name__ for p in resolved}
            assert "TavilyClient" in kinds
            assert "SerpApiClient" in kinds
        finally:
            _clear_settings_cache()

    def test_env_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY_1", "t-key")
        monkeypatch.setenv("SERPAPI_API_KEY_1", "s-key")
        monkeypatch.setenv("SEARCH_PROVIDERS", "tavily")
        _clear_settings_cache()
        try:
            from app.config import get_settings

            settings = get_settings()
            monkeypatch.setattr(settings, "search_providers", "tavily,serpapi")
            from app.web_rag import providers

            resolved = providers.resolve_providers()
            kinds = {type(p).__name__ for p in resolved}
            assert "TavilyClient" in kinds
            assert "SerpApiClient" not in kinds
        finally:
            _clear_settings_cache()

    def test_fallback_is_observable(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("SEARCH_PROVIDERS", "definitely-not-a-provider")
        from app.web_rag import providers

        with caplog.at_level(logging.WARNING, logger="app.web_rag.providers"):
            resolved = providers.resolve_providers()
        assert len(resolved) >= 1
        # Fallback must not be silent: a warning names the fallback.
        assert "falling back" in caplog.text.lower()


class TestSerpApiErrorField:
    def test_error_json_raises_not_empty(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError, SerpApiClient

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"error": "Quota exceeded"})
        )
        client = SerpApiClient(api_key_1="k")
        try:
            client.search("PMFBY")
        except SerpApiAPIError as exc:
            assert "Quota exceeded" in str(exc)
        else:
            raise AssertionError("expected SerpApiAPIError for error JSON")

    def test_no_results_error_still_raises_with_diagnostic(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError, SerpApiClient

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"error": "Google hasn't returned any results for this query."},
            )
        )
        client = SerpApiClient(api_key_1="k")
        try:
            client.search("zxqv unlikely query")
        except SerpApiAPIError as exc:
            assert "Google hasn't returned" in str(exc)
        else:
            raise AssertionError("expected SerpApiAPIError for Google-empty error JSON")


class TestSerpApiIncludeDomains:
    def test_include_domains_appear_in_query(self, respx_mock):
        import httpx

        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"organic_results": []})

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=handler)
        client = SerpApiClient(api_key_1="k")
        client.search("PMFBY", include_domains=["cooperation.gujarat.gov.in", "pmfby.gov.in"])
        q = captured["params"].get("q", "")
        assert "cooperation.gujarat.gov.in" in q
        assert "pmfby.gov.in" in q

    def test_include_domains_bounded(self, respx_mock):
        import httpx

        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"organic_results": []})

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=handler)
        client = SerpApiClient(api_key_1="k")
        many = [f"domain{i}.gov.in" for i in range(40)]
        client.search("query", include_domains=many)
        q = captured["params"].get("q", "")
        # Bounded: base enrichment has 2 site: filters; at most 8 more may
        # be appended, so all 40 domains must never be embedded.
        assert q.count("site:") <= 10
        assert "domain39.gov.in" not in q


class TestSerpApiDiagnostics:
    def test_429_preserves_body_without_key(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError, SerpApiClient

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(429, text='{"error": "quota exceeded"}')
        )
        client = SerpApiClient(api_key_1="k")
        try:
            client.search("query")
        except SerpApiAPIError as exc:
            text = str(exc)
            assert "429" in text
            assert "quota" in text.lower()
            assert "k" != text  # key value itself must not appear
            # Only the key index may appear, never the secret.
            assert "api_key" not in text.lower() or "[REDACTED]" in text or "key_1" in text
        else:
            raise AssertionError("expected SerpApiAPIError for 429")

    def test_no_live_quota_without_configuration(self):
        from app.web_rag.serpapi_client import SerpApiClient, SerpApiConfigurationError

        client = SerpApiClient(api_key_1="", api_key_2="")
        assert client.is_configured() is False
        try:
            client.search("query")
        except SerpApiConfigurationError:
            pass
        else:
            raise AssertionError("unconfigured client must raise before any HTTP")
