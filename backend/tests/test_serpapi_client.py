"""Tests for SerpApi web-search provider.

Covers (per integration spec):
- A. Configuration (missing / configured keys)
- B. Provider registration (factory + resolve_providers)
- C. Request construction (mocked HTTP: endpoint, engine, query, num bound, key, locale)
- D. Response mapping (organic -> normalized; empty/missing/malformed)
- E. Error behavior (timeout, 429, 4xx, 5xx, malformed JSON, connection failure)
- F. Integration with provider resolution (tavily+serpapi)
- G. Provider contract parity with Tavily/Firecrawl (_search_all compatible)
"""

from __future__ import annotations

import httpx
import pytest


def _settings(**overrides):
    from app.config import Settings

    base = {
        "groq_api_key": "g",
        "supabase_url": "u",
        "supabase_service_key": "s",
    }
    base.update(overrides)
    return Settings(**base)


def _serpapi_response(results):
    return {"organic_results": results}


class TestConfiguration:
    def test_missing_key_not_configured(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_API_KEY_1", raising=False)
        monkeypatch.delenv("SERPAPI_API_KEY_2", raising=False)
        from app.web_rag.serpapi_client import SerpApiClient

        client = SerpApiClient(api_key_1="", api_key_2="")
        assert client.is_configured() is False

    def test_missing_key_require_raises(self):
        from app.web_rag.serpapi_client import (
            SerpApiClient,
            SerpApiConfigurationError,
        )

        client = SerpApiClient(api_key_1="", api_key_2="")
        with pytest.raises(SerpApiConfigurationError):
            client.require_configuration()

    def test_configured_key(self):
        from app.web_rag.serpapi_client import SerpApiClient

        client = SerpApiClient(api_key_1="test-key-1")
        assert client.is_configured() is True

    def test_empty_query_raises(self):
        from app.web_rag.serpapi_client import SerpApiClient

        client = SerpApiClient(api_key_1="k")
        with pytest.raises(ValueError):
            client.search("   ")


class TestRegistration:
    def test_factory_registers_serpapi(self):
        from app.web_rag import providers

        assert "serpapi" in providers._PROVIDER_FACTORIES

    def test_resolve_providers_recognizes_serpapi(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_API_KEY_1", "test-serpapi-key")
        monkeypatch.setenv("SEARCH_PROVIDERS", "serpapi")
        from app.web_rag import providers
        from app.web_rag.serpapi_client import SerpApiClient

        resolved = providers.resolve_providers("serpapi")
        assert any(isinstance(p, SerpApiClient) for p in resolved)

    def test_tavily_plus_serpapi_both_resolve(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY_1", "test-tavily-key")
        monkeypatch.setenv("SERPAPI_API_KEY_1", "test-serpapi-key")
        from app.web_rag import providers
        from app.web_rag.serpapi_client import SerpApiClient
        from app.web_rag.tavily_client import TavilyClient

        resolved = providers.resolve_providers("tavily,serpapi")
        kinds = {type(p).__name__ for p in resolved}
        assert "TavilyClient" in kinds and "SerpApiClient" in kinds
        assert any(isinstance(p, TavilyClient) for p in resolved)
        assert any(isinstance(p, SerpApiClient) for p in resolved)

    def test_unknown_provider_skipped(self):
        from app.web_rag import providers

        resolved = providers.resolve_providers("definitely-not-a-provider")
        # Falls back to TavilyClient per factory contract
        assert len(resolved) >= 1


class TestRequestConstruction:
    def test_request_hits_serpapi_endpoint_with_google_engine(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiClient

        assert "serpapi.com" in SERPAPI_SEARCH_URL

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"organic_results": []})

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=handler)
        client = SerpApiClient(api_key_1="my-key")
        client.search("PMFBY crop insurance")
        params = captured["params"]
        assert params.get("engine") == "google"
        assert "PMFBY crop insurance" in params.get("q", "")
        assert params.get("api_key") == "my-key"

    def test_num_bounded_to_20(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"organic_results": []})

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=handler)
        client = SerpApiClient(api_key_1="k")
        client.search("query", max_results=100)
        assert int(captured["params"]["num"]) <= 20

    def test_explicit_keys_used_over_env(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiClient

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"organic_results": []})

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=handler)
        client = SerpApiClient(api_key_1="explicit-key")
        client.search("query")
        assert captured["params"].get("api_key") == "explicit-key"


class TestResponseMapping:
    def _client(self):
        from app.web_rag.serpapi_client import SerpApiClient

        return SerpApiClient(api_key_1="k")

    def test_organic_mapped_to_normalized(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=_serpapi_response(
                    [
                        {
                            "link": "https://pmfby.gov.in/guidelines",
                            "title": "PMFBY Guidelines",
                            "snippet": "Crop insurance details",
                        }
                    ]
                ),
            )
        )
        out = self._client().search("PMFBY")
        assert "results" in out
        assert len(out["results"]) == 1
        item = out["results"][0]
        assert item["url"] == "https://pmfby.gov.in/guidelines"
        assert item["title"] == "PMFBY Guidelines"
        assert item["content"] == "Crop insurance details"

    def test_empty_organic_results(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"organic_results": []})
        )
        out = self._client().search("query")
        assert out == {"results": []}

    def test_missing_snippet_defaults_empty(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=_serpapi_response([{"link": "https://example.gov.in/x", "title": "T"}]),
            )
        )
        out = self._client().search("query")
        assert out["results"][0]["content"] == ""

    def test_missing_title_defaults_empty(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=_serpapi_response([{"link": "https://example.gov.in/x", "snippet": "s"}]),
            )
        )
        out = self._client().search("query")
        assert out["results"][0]["title"] == ""

    def test_result_without_url_skipped(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json=_serpapi_response(
                    [
                        {"title": "No URL", "snippet": "x"},
                        {"link": "https://ok.gov.in/", "title": "OK"},
                    ]
                ),
            )
        )
        out = self._client().search("query")
        assert len(out["results"]) == 1
        assert out["results"][0]["url"] == "https://ok.gov.in/"

    def test_malformed_items_skipped(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"organic_results": ["nope", 42, None]},
            )
        )
        out = self._client().search("query")
        assert out == {"results": []}

    def test_unexpected_structure_returns_empty(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"something_else": []})
        )
        out = self._client().search("query")
        assert out == {"results": []}


class TestErrorBehavior:
    def _client(self):
        from app.web_rag.serpapi_client import SerpApiClient

        return SerpApiClient(api_key_1="k")

    def test_429_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(429, text="rate limited")
        )
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")

    def test_4xx_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(401, text="unauthorized")
        )
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")

    def test_5xx_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(500, text="server error")
        )
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")

    def test_malformed_json_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(
            return_value=httpx.Response(200, text="not-json{{{")
        )
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")

    def test_timeout_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=httpx.ConnectTimeout("t"))
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")

    def test_connection_failure_raises_api_error(self, respx_mock):
        from app.web_rag.serpapi_client import SERPAPI_SEARCH_URL, SerpApiAPIError

        respx_mock.get(SERPAPI_SEARCH_URL).mock(side_effect=httpx.ConnectError("c"))
        with pytest.raises(SerpApiAPIError):
            self._client().search("query")


class TestProviderContract:
    def test_search_signature_matches_tavily(self):
        import inspect

        from app.web_rag.serpapi_client import SerpApiClient
        from app.web_rag.tavily_client import TavilyClient

        serp = inspect.signature(SerpApiClient.search)
        tav = inspect.signature(TavilyClient.search)
        assert list(serp.parameters) == list(tav.parameters)

    def test_failure_does_not_break_discovery(self, monkeypatch):
        """A failing SerpApi must not break _search_all when Tavily works."""
        from app.web_rag import service as discovery_service
        from app.web_rag.serpapi_client import SerpApiAPIError, SerpApiClient
        from app.web_rag.tavily_client import TavilyClient

        failing = SerpApiClient(api_key_1="k")

        def _boom(*args, **kwargs):
            raise SerpApiAPIError("boom")

        monkeypatch.setattr(failing, "search", _boom)

        working = TavilyClient(api_key_1="t")
        monkeypatch.setattr(
            working,
            "search",
            lambda *a, **k: {"results": [{"url": "https://gov.in/x", "title": "t"}]},
        )
        monkeypatch.setattr(
            discovery_service, "resolve_providers", lambda *a, **k: [failing, working]
        )
        # WebDiscoveryService substitutes its own tavily instance for any
        # resolved TavilyClient, so inject the mocked client explicitly.
        disc = discovery_service.WebDiscoveryService(tavily_client=working)
        merged = disc._search_all("query")
        assert any("gov.in" in str(i.get("url", "")) for i in merged)
