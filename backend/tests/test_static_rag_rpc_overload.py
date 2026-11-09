"""P0-1 regression tests: overloaded match_chunks RPC (PGRST203).

Live failure: POST /rest/v1/rpc/match_chunks with 4 keys matches both the
legacy 4-arg overload and the newer 6-arg overload
(query_embedding, match_domain, match_state, match_count, as_of_date,
match_entity_id) -> HTTP 300 PGRST203, which disabled static RAG entirely.

The fix: static RAG always sends all 6 keys so PostgREST unambiguously
selects the 6-arg overload (null extras = no filtering = legacy behavior).

These tests use a fake Supabase client that reproduces the live PGRST203
condition (raises on any 4-key call) and succeeds on 6-key calls.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import retrieval as retrieval_module
from app.config import Settings
from app.services import static_rag as static_rag_module
from app.services.static_rag import StaticRAGService, _dense_retrieve


LEGACY_KEYS = {"query_embedding", "match_domain", "match_state", "match_count"}
FULL_KEYS = {
    "query_embedding",
    "match_domain",
    "match_state",
    "match_count",
    "as_of_date",
    "match_entity_id",
}


class FakePostgrestAPIError(Exception):
    """Mimics postgrest.exceptions.APIError (message + code)."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class _FakeRPCBuilder:
    def __init__(self, outer: FakeSupabase, fn: str, params: dict) -> None:
        self._outer = outer
        self._fn = fn
        self._params = params

    def execute(self):
        self._outer.rpc_calls.append((self._fn, dict(self._params)))
        if self._fn == "match_chunks" and set(self._params.keys()) == LEGACY_KEYS:
            raise FakePostgrestAPIError(
                "PGRST203: Could not choose the best candidate function between "
                "public.match_chunks(query_embedding => public.vector, "
                "match_domain => text, match_state => text, match_count => integer) "
                "and public.match_chunks(query_embedding => public.vector, "
                "match_domain => text, match_state => text, match_count => integer, "
                "as_of_date => date, match_entity_id => text)",
                code="PGRST203",
            )
        return SimpleNamespace(data=list(self._outer.rpc_rows))


class _FakeTableChain:
    """Supports .table().select().in_().limit().execute() -> empty data."""

    def select(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakeSupabase:
    """Fake Supabase client reproducing the live overloaded-RPC behavior."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rpc_calls: list[tuple[str, dict]] = []
        self.rpc_rows: list[dict] = rows or []

    def rpc(self, fn: str, params: dict):
        return _FakeRPCBuilder(self, fn, params)

    def table(self, name: str):
        return _FakeTableChain()


def _make_settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq-key",
        "gemini_api_key": "test-gemini-key",
        "jina_api_key": "test-jina-key",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "reranker_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _dense_row(
    chunk_id: str = "11111111-1111-1111-1111-111111111111",
    similarity: float = 0.80,
    domain: str = "pmfby",
    state: str | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "stable_chunk_id": f"stable-{chunk_id[:8]}",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "title": "PMFBY Guidelines",
        "page": 1,
        "page_start": 1,
        "page_end": 1,
        "section": "Overview",
        "subsection": "",
        "clause": "",
        "content": "PMFBY provides crop insurance to farmers.",
        "similarity": similarity,
        "source_url": "https://pmfby.gov.in",
        "source_file": "pmfby.pdf",
        "domain": domain,
        "jurisdiction": "central",
        "state": state,
    }


def _good_rows() -> list[dict]:
    return [
        _dense_row("11111111-1111-1111-1111-111111111111", 0.80),
        _dense_row("33333333-3333-3333-3333-333333333333", 0.60),
        _dense_row("44444444-4444-4444-4444-444444444444", 0.50),
    ]


# ---------------------------------------------------------------------------
# PGRST203 reproduction + unambiguous invocation
# ---------------------------------------------------------------------------


class TestOverloadedRPC:
    def test_four_key_call_reproduces_pgrst203(self):
        """The fake reproduces the live failure: 4 keys -> PGRST203."""
        fake = FakeSupabase()
        with pytest.raises(FakePostgrestAPIError, match="PGRST203"):
            fake.rpc("match_chunks", {
                "query_embedding": [0.1] * 8,
                "match_domain": "pmfby",
                "match_state": None,
                "match_count": 6,
            }).execute()

    def test_dense_retrieve_sends_all_six_keys(self):
        """_dense_retrieve must call the intended RPC unambiguously."""
        fake = FakeSupabase(rows=_good_rows())
        chunks = _dense_retrieve(
            fake, [0.1] * 8, "pmfby", "gujarat", k=6,
        )
        assert len(chunks) == 3
        assert fake.rpc_calls, "expected at least one RPC call"
        fn, params = fake.rpc_calls[0]
        assert fn == "match_chunks"
        assert set(params.keys()) == FULL_KEYS
        assert params["match_domain"] == "pmfby"
        assert params["match_state"] == "gujarat"
        assert params["match_count"] == 6
        assert params["as_of_date"] is None
        assert params["match_entity_id"] is None

    def test_dense_retrieve_threads_as_of_date(self):
        """as_of_date must reach the RPC for SQL-level effective-date filtering."""
        fake = FakeSupabase(rows=_good_rows())
        _dense_retrieve(
            fake, [0.1] * 8, "pmfby", None, k=6, as_of_date="2026-10-04",
        )
        _, params = fake.rpc_calls[0]
        assert set(params.keys()) == FULL_KEYS
        assert params["as_of_date"] == "2026-10-04"

    def test_retrieval_module_sends_all_six_keys(self):
        """The legacy retrieval.retrieve twin must also disambiguate."""
        fake = FakeSupabase(rows=_good_rows())
        chunks = retrieval_module.retrieve(
            fake, [0.1] * 8, domain="pmfby", state="gujarat", k=6,
        )
        assert len(chunks) == 3
        fn, params = fake.rpc_calls[0]
        assert fn == "match_chunks"
        assert set(params.keys()) == FULL_KEYS

    def test_fallback_to_legacy_on_pgrst202(self):
        """DBs with only the legacy overload still work (PGRST202 -> retry 4-key)."""

        class _LegacyOnlySupabase(FakeSupabase):
            def rpc(self, fn: str, params: dict):
                outer = self

                class _Builder:
                    def execute(self):
                        outer.rpc_calls.append((fn, dict(params)))
                        if set(params.keys()) == FULL_KEYS:
                            raise FakePostgrestAPIError(
                                "PGRST202: Could not find the function "
                                "public.match_chunks with 6 args",
                                code="PGRST202",
                            )
                        return SimpleNamespace(data=list(outer.rpc_rows))

                return _Builder()

        fake = _LegacyOnlySupabase(rows=_good_rows())
        chunks = _dense_retrieve(fake, [0.1] * 8, "pmfby", None, k=6)
        assert len(chunks) == 3
        # First attempt used 6 keys, fallback retried with 4 keys.
        assert [set(p.keys()) for _, p in fake.rpc_calls] == [FULL_KEYS, LEGACY_KEYS]


# ---------------------------------------------------------------------------
# End-to-end through StaticRAGService.retrieve (filters + behavior preserved)
# ---------------------------------------------------------------------------


class TestServiceRetrievalPreserved:
    def _run_retrieve(self, fake: FakeSupabase, **kwargs):
        service = StaticRAGService(_make_settings())
        with patch.object(static_rag_module, "get_supabase", return_value=fake):
            return service.retrieve(
                embedding=[0.1] * 768,
                query=kwargs.pop("query", "What is PMFBY?"),
                domain=kwargs.pop("domain", "pmfby"),
                state=kwargs.pop("state", "gujarat"),
                k=kwargs.pop("k", 6),
                **kwargs,
            )

    def test_normal_static_retrieval_succeeds(self):
        """Static RAG no longer fails with PGRST203; returns gated chunks."""
        fake = FakeSupabase(rows=_good_rows())
        result = self._run_retrieve(fake)
        assert result.abstained is False
        assert len(result.chunks) == 3
        assert result.domain == "pmfby"
        assert all(c.source_type == "static" for c in result.chunks)

    def test_domain_filtering_preserved(self):
        fake = FakeSupabase(rows=_good_rows())
        self._run_retrieve(fake, domain="pmfby")
        _, params = fake.rpc_calls[0]
        assert params["match_domain"] == "pmfby"

    def test_domain_map_preserved(self):
        """Raw 'pacs' still maps to the canonical retrieval domain."""
        fake = FakeSupabase(rows=[])
        result = self._run_retrieve(fake, domain="pacs")
        assert result.domain == "pacs_governance"
        _, params = fake.rpc_calls[0]
        assert params["match_domain"] == "pacs_governance"

    def test_state_filtering_preserved(self):
        fake = FakeSupabase(rows=_good_rows())
        self._run_retrieve(fake, state="gujarat")
        _, params = fake.rpc_calls[0]
        assert params["match_state"] == "gujarat"

    def test_none_state_preserved(self):
        """Central-only retrieval still sends an explicit null state."""
        fake = FakeSupabase(rows=_good_rows())
        self._run_retrieve(fake, state=None)
        _, params = fake.rpc_calls[0]
        assert "match_state" in params
        assert params["match_state"] is None

    def test_as_of_date_threaded_end_to_end(self):
        fake = FakeSupabase(rows=_good_rows())
        result = self._run_retrieve(fake, as_of_date="2026-10-04")
        _, params = fake.rpc_calls[0]
        assert params["as_of_date"] == "2026-10-04"
        assert result.abstained is False
