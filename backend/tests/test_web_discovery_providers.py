"""Discovery-level tests for multi-provider WebDiscoveryService behavior.

Covers the Tavily + SerpApi complementary-provider contract using
deterministic fakes (no network, no credentials):

- A. both providers contribute to the candidate pool
- B. Tavily failure still lets SerpApi results through
- C. SerpApi failure still lets Tavily results through
- D/E/F. merge + URL dedup keeps first-provider order, drops dupes
- G. only_official filtering preserved
- H. providers execute concurrently (a slow first provider cannot
     starve a healthy second provider)
- call-arg parity: each provider receives the discovery query args
"""

from __future__ import annotations

import threading
from typing import Any


class FakeProvider:
    def __init__(
        self,
        results: list[dict] | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
        on_call: Any = None,
    ):
        self._results = results or []
        self._exc = exc
        self._delay = delay
        self._on_call = on_call
        self.calls: list[dict] = []

    def search(self, query: str, **kwargs: Any) -> dict:
        import time

        self.calls.append({"query": query, **kwargs})
        if self._on_call is not None:
            self._on_call()
        if self._delay:
            time.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return {"results": list(self._results)}


def _item(url: str, title: str = "t") -> dict:
    return {"url": url, "title": title, "content": "content about schemes"}


def _service(*providers: FakeProvider):
    from app.web_rag.service import WebDiscoveryService

    disc = WebDiscoveryService.__new__(WebDiscoveryService)
    disc.search_providers = list(providers)
    return disc


class TestCandidatePool:
    def test_both_providers_contribute(self):
        tavily = FakeProvider(
            [_item("https://a.gov.in/1"), _item("https://b.gov.in/2"), _item("https://c.gov.in/3")]
        )
        serpapi = FakeProvider(
            [_item("https://d.gov.in/4"), _item("https://e.gov.in/5"), _item("https://f.gov.in/6")]
        )
        merged = _service(tavily, serpapi)._search_all("query")
        assert [i["url"] for i in merged] == [
            "https://a.gov.in/1",
            "https://b.gov.in/2",
            "https://c.gov.in/3",
            "https://d.gov.in/4",
            "https://e.gov.in/5",
            "https://f.gov.in/6",
        ]

    def test_duplicate_url_kept_once_first_provider_wins(self):
        tavily = FakeProvider([_item("https://a.gov.in/1"), _item("https://dup.gov.in/x")])
        serpapi = FakeProvider([_item("https://dup.gov.in/x"), _item("https://c.gov.in/3")])
        merged = _service(tavily, serpapi)._search_all("query")
        assert [i["url"] for i in merged] == [
            "https://a.gov.in/1",
            "https://dup.gov.in/x",
            "https://c.gov.in/3",
        ]

    def test_unique_results_not_discarded(self):
        tavily = FakeProvider([_item("https://only-tavily.gov.in/1")])
        serpapi = FakeProvider([_item("https://only-serpapi.gov.in/2")])
        merged = _service(tavily, serpapi)._search_all("query")
        assert len(merged) == 2

    def test_items_without_url_skipped(self):
        tavily = FakeProvider([{"title": "no url"}, _item("https://ok.gov.in/1")])
        merged = _service(tavily)._search_all("query")
        assert [i["url"] for i in merged] == ["https://ok.gov.in/1"]


class TestFailureIsolation:
    def test_tavily_failure_serpapi_results_survive(self):
        tavily = FakeProvider(exc=RuntimeError("tavily down"))
        serpapi = FakeProvider([_item("https://s.gov.in/1")])
        merged = _service(tavily, serpapi)._search_all("query")
        assert [i["url"] for i in merged] == ["https://s.gov.in/1"]

    def test_serpapi_failure_tavily_results_survive(self):
        tavily = FakeProvider([_item("https://t.gov.in/1")])
        serpapi = FakeProvider(exc=RuntimeError("serpapi down"))
        merged = _service(tavily, serpapi)._search_all("query")
        assert [i["url"] for i in merged] == ["https://t.gov.in/1"]

    def test_both_fail_returns_empty(self):
        merged = _service(
            FakeProvider(exc=RuntimeError("a")),
            FakeProvider(exc=RuntimeError("b")),
        )._search_all("query")
        assert merged == []


class TestOfficialFilter:
    def test_only_official_keeps_gov_drops_other(self):
        p = FakeProvider(
            [
                _item("https://pmfby.gov.in/g"),
                _item("https://example.com/x"),
                _item("https://blog.example.org/y"),
            ]
        )
        merged = _service(p)._search_all("query", only_official=True)
        assert [i["url"] for i in merged] == ["https://pmfby.gov.in/g"]

    def test_without_flag_all_kept(self):
        p = FakeProvider([_item("https://pmfby.gov.in/g"), _item("https://example.com/x")])
        assert len(_service(p)._search_all("query")) == 2


class TestCallArgs:
    def test_providers_receive_discovery_args(self):
        a = FakeProvider()
        b = FakeProvider()
        _service(a, b)._search_all(
            "q",
            domain="pmfby",
            state="gujarat",
            max_results=7,
            chunks_per_source=2,
        )
        for p in (a, b):
            assert p.calls[0]["query"] == "q"
            assert p.calls[0]["domain"] == "pmfby"
            assert p.calls[0]["state"] == "gujarat"
            assert p.calls[0]["max_results"] == 7
            assert p.calls[0]["chunks_per_source"] == 2


class TestConcurrency:
    def test_slow_first_provider_does_not_starve_second(self):
        """First provider blocks until the second provider is invoked.

        Sequential execution would deadlock here (test fails via timeout);
        concurrent fan-out passes deterministically.
        """
        second_started = threading.Event()

        def unblock() -> None:
            second_started.set()

        first = FakeProvider(
            results=[_item("https://slow.gov.in/1")],
            on_call=lambda: assert_event_set(second_started),
        )
        second = FakeProvider(results=[_item("https://fast.gov.in/2")], on_call=unblock)
        merged = _service(first, second)._search_all("query")
        # Provider order preserved in merged output despite concurrency.
        assert [i["url"] for i in merged] == [
            "https://slow.gov.in/1",
            "https://fast.gov.in/2",
        ]


def assert_event_set(event: threading.Event, timeout: float = 10.0) -> None:
    assert event.wait(timeout), "second provider was never invoked concurrently"


class TestErrorSanitization:
    def test_api_key_redacted_from_provider_error(self):
        """SerpApi failures embed the request URL incl. api_key — logs must not."""
        from app.web_rag.service import _sanitize_provider_error

        exc = RuntimeError(
            "RESPX: <Request('GET', 'https://serpapi.com/search.json?engine=google"
            "&q=crop+insurance&num=10&api_key=deadbeef1234&gl=in')> not mocked!"
        )
        out = _sanitize_provider_error(exc)
        assert "deadbeef1234" not in out
        assert "api_key=[REDACTED]" in out
        assert "serpapi.com" in out  # reason stays debuggable

    def test_clean_error_passes_through(self):
        from app.web_rag.service import _sanitize_provider_error

        out = _sanitize_provider_error(RuntimeError("connection reset by peer"))
        assert out == "connection reset by peer"

    def test_failing_provider_does_not_leak_key_to_logs(self, caplog):
        """End-to-end: a failing provider's api_key must not appear in logs."""
        import logging

        bad = FakeProvider(exc=RuntimeError("boom api_key=supersecret123&q=x"))
        with caplog.at_level(logging.WARNING, logger="app.web_rag.service"):
            assert _service(bad)._search_all("query") == []
        assert "supersecret123" not in caplog.text
