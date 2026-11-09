"""Task 3: orchestrator facet branch + confidence penalty (no network).

- Characterization: single-facet path keeps using _run_pipelines/_merge_evidence.
- Mock tests: multi-facet path calls static retrieve per facet (k=10) and caps
  web at 2 facets under one shared deadline.
- Unit tests: coverage confidence penalty scaling.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
    RAGResult,
)
from app.facets import Facet
from app.services import rag_orchestrator as ro
from app.services.rag_orchestrator import RAGOrchestrator
from app.web_rag.query_classifier import QueryClassification


def _settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq-key",
        "gemini_api_key": "test-gemini-key",
        "jina_api_key": "test-jina-key",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "reranker_enabled": False,
        "sarvam_api_key": "",
        "sarvam_api_key_2": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _chunk(
    cid: str,
    score: float,
    domain: str = "pmfby",
    source: str = "static",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=cid,
        content="Evidence content for facet test.",
        source_type=source,
        title="t",
        domain=domain,
        jurisdiction="central",
        dense_score=score,
    )


def _classification(**overrides) -> QueryClassification:
    base = {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "intent": "INFORMATIONAL",
        "confidence": 0.9,
    }
    base.update(overrides)
    return QueryClassification(**base)


# ---------------------------------------------------------------------------
# Characterization: single path keeps legacy hooks
# ---------------------------------------------------------------------------

def test_single_path_uses_legacy_merge():
    assert hasattr(ro.RAGOrchestrator, "run")
    # router single facet must call _run_pipelines once (no per-facet fan-out)
    assert hasattr(ro.RAGOrchestrator, "_merge_evidence")


async def test_single_facet_delegates_to_run_pipelines():
    """Single facet → _run_pipelines once, _merge_evidence used, no facet path."""
    orch = RAGOrchestrator(_settings())
    english_query = "What is PMFBY premium rate?"
    single = [Facet(facet_id="pmfby", domain="pmfby", query=english_query, state=None)]
    static_res = RAGResult(
        chunks=[_chunk("static-pmfby-001", 0.8)],
        abstained=False,
        band=ConfidenceBand.HIGH,
        domain="pmfby",
    )
    web_res = RAGResult(
        chunks=[], abstained=True,
        reason=AbstentionReason.NO_ELIGIBLE_SOURCE, domain="pmfby",
    )

    fake_store = MagicMock()
    fake_store.collect_hits.return_value = ["pmfby"]

    with (
        patch.object(ro, "get_anchor_store", return_value=fake_store),
        patch.object(ro, "split_facets", return_value=single) as split_spy,
        patch.object(
            orch, "_run_pipelines",
            new=AsyncMock(return_value=(static_res, web_res)),
        ) as pipelines_mock,
        patch.object(
            orch, "_run_facet_pipelines",
            side_effect=AssertionError("facet path must not run for a single facet"),
        ),
        patch.object(orch, "_merge_evidence", wraps=orch._merge_evidence) as merge_spy,
        patch.object(orch._evidence_controller, "build_bundle", return_value=MagicMock()),
        patch.object(orch._evidence_controller, "assess_evidence", return_value=MagicMock()),
        patch.object(
            orch._evidence_controller, "build_curated_prompt",
            return_value=("sys prompt", "user prompt"),
        ),
        patch.object(ro, "grounded_answer", return_value="PMFBY premium is 2 percent."),
        patch.object(
            ro, "verify_citations",
            return_value=SimpleNamespace(is_valid=True, reason=None, invalid_prefixes=[]),
        ),
        patch.object(
            ro, "verify_answer_grounding",
            return_value=SimpleNamespace(has_unsupported_claims=False),
        ),
    ):
        resp = await orch.run(
            query=english_query,
            english_query=english_query,
            embedding=[0.1] * 8,
            domain="pmfby",
            state=None,
            classification=_classification(),
            history=[],
            lang="en",
            session_id="sess-facet-single",
        )

    split_spy.assert_called_once()
    pipelines_mock.assert_awaited_once()
    merge_spy.assert_called_once()
    assert resp.abstained is False
    assert resp.confidence == 0.9  # no coverage penalty on the single path


# ---------------------------------------------------------------------------
# Multi-facet: per-facet static retrieve, bounded web, coverage metadata
# ---------------------------------------------------------------------------

def test_multi_facet_calls_static_per_facet():
    orch = RAGOrchestrator(_settings())
    facets = [
        Facet(facet_id="pmfby", domain="pmfby", query="PMFBY premium Gujarat", state="Gujarat"),
        Facet(facet_id="schemes", domain="schemes", query="PM-KISAN Gujarat", state="Gujarat"),
    ]
    static_calls: list[dict] = []
    web_calls: list[dict] = []

    def fake_static(**kwargs):
        static_calls.append(kwargs)
        if kwargs["domain"] == "pmfby":
            return RAGResult(
                chunks=[_chunk("static-pmfby-001", 0.8)],
                abstained=False, band=ConfidenceBand.MEDIUM, domain="pmfby",
            )
        return RAGResult(
            chunks=[], abstained=True,
            reason=AbstentionReason.NO_ELIGIBLE_SOURCE, domain="schemes",
        )

    def fake_web(**kwargs):
        web_calls.append(kwargs)
        return RAGResult(
            chunks=[_chunk("web-schemes-001", 67.2, domain="schemes", source="web")],
            abstained=False, band=ConfidenceBand.MEDIUM, domain="schemes",
        )

    fake_provider = MagicMock()
    fake_provider.embed_texts.side_effect = lambda texts: [[0.5] * 8 for _ in texts]

    with (
        patch.object(orch._static_rag, "retrieve", side_effect=fake_static),
        patch.object(orch._web_rag, "retrieve", side_effect=fake_web),
        patch(
            "app.providers.embeddings.get_embedding_provider",
            return_value=fake_provider,
        ),
    ):
        static_result, web_result, merged, coverage = asyncio.run(
            orch._run_facet_pipelines(
                facets=facets,
                embedding=[0.1] * 8,
                classification=_classification(),
                mode="rag_web",
            )
        )

    # static called once per facet with k=10 and the facet query/domain
    assert len(static_calls) == 2
    assert all(c["k"] == 10 for c in static_calls)
    assert {c["domain"] for c in static_calls} == {"pmfby", "schemes"}
    # one embedding per distinct facet query (cached)
    assert fake_provider.embed_texts.call_count == 2
    # only the facet without static evidence needed web, sharing one deadline
    assert len(web_calls) == 1
    assert web_calls[0]["domain"] == "schemes"
    assert web_calls[0]["deadline"] is not None
    # merged evidence covers both facets; coverage stored on web metadata
    merged_ids = {c.chunk_id for c in merged}
    assert {"static-pmfby-001", "web-schemes-001"} <= merged_ids
    assert coverage["pmfby"]["status"] == "supported"
    assert coverage["schemes"]["status"] == "supported"
    assert web_result.metadata["facet_coverage"] == coverage
    assert static_result.abstained is False
    assert web_result.abstained is False


def test_multi_facet_web_capped_at_two():
    orch = RAGOrchestrator(_settings())
    facets = [
        Facet(facet_id="pmfby", domain="pmfby", query="PMFBY premium", state=None),
        Facet(facet_id="schemes", domain="schemes", query="PM-KISAN", state=None),
        Facet(facet_id="agriculture", domain="agriculture", query="land records", state=None),
    ]

    def fake_empty_static(**kwargs):
        return RAGResult(
            chunks=[], abstained=True,
            reason=AbstentionReason.NO_ELIGIBLE_SOURCE, domain=kwargs["domain"],
        )

    def fake_web(**kwargs):
        return RAGResult(
            chunks=[_chunk(f"web-{kwargs['domain']}-001", 70.0,
                           domain=kwargs["domain"], source="web")],
            abstained=False, band=ConfidenceBand.MEDIUM, domain=kwargs["domain"],
        )

    fake_provider = MagicMock()
    fake_provider.embed_texts.side_effect = lambda texts: [[0.5] * 8 for _ in texts]

    with (
        patch.object(orch._static_rag, "retrieve", side_effect=fake_empty_static),
        patch.object(orch._web_rag, "retrieve", side_effect=fake_web) as web_mock,
        patch(
            "app.providers.embeddings.get_embedding_provider",
            return_value=fake_provider,
        ),
    ):
        static_result, web_result, _merged, coverage = asyncio.run(
            orch._run_facet_pipelines(
                facets=facets,
                embedding=[0.1] * 8,
                classification=_classification(),
                mode="rag_web",
            )
        )

    assert web_mock.call_count == 2  # at most 2 facets get web
    assert len(coverage) == 3
    statuses = [coverage[f.facet_id]["status"] for f in facets]
    assert statuses.count("unsupported") == 1
    assert static_result.abstained is True
    assert web_result.metadata["facet_coverage"] == coverage


# ---------------------------------------------------------------------------
# Confidence penalty scaling
# ---------------------------------------------------------------------------

def test_coverage_penalty_all_supported_is_noop():
    cov = {"a": {"status": "supported"}, "b": {"status": "supported"}}
    assert RAGOrchestrator._apply_facet_coverage_penalty(0.9, cov) == 0.9


def test_coverage_penalty_scales_with_supported_fraction():
    cov = {"a": {"status": "supported"}, "b": {"status": "unsupported"}}
    assert RAGOrchestrator._apply_facet_coverage_penalty(0.8, cov) == round(0.8 * 0.75, 2)
    cov_none = {"a": {"status": "unsupported"}, "b": {"status": "partial"}}
    assert RAGOrchestrator._apply_facet_coverage_penalty(0.8, cov_none) == round(0.8 * 0.5, 2)


def test_coverage_penalty_empty_coverage_is_noop():
    assert RAGOrchestrator._apply_facet_coverage_penalty(0.7, {}) == 0.7


# ---------------------------------------------------------------------------
# Task 4: facet-grouped prompt (I1 wiring)
# ---------------------------------------------------------------------------

def _bundle_for_prompt(static_chunks=None, web_chunks=None) -> object:
    from app.contracts import (
        DynamicEvidence,
        EvidenceBundle,
        QueryRequirements,
        StaticEvidence,
    )

    static_chunks = static_chunks or []
    web_chunks = web_chunks or []
    return EvidenceBundle(
        static=StaticEvidence(
            available=len(static_chunks) > 0,
            chunks=static_chunks,
            summary=f"{len(static_chunks)} chunks",
        ),
        dynamic=DynamicEvidence(
            available=len(web_chunks) > 0,
            chunks=web_chunks,
        ),
        query_requirements=QueryRequirements(
            temporal_scope="general",
            geographic_scope="none",
            required_specificity="general",
            requires_dynamic=False,
        ),
        query="PMFBY premium and PM-KISAN",
    )


def test_prompt_groups_by_facet():
    from app.evidence_controller import EvidenceController

    ec = EvidenceController()
    assert hasattr(ec, "build_curated_prompt")

    static_pmfby = _chunk("static-pmfby-001", 0.8, domain="pmfby", source="static")
    web_schemes = _chunk("web-schemes-001", 67.2, domain="schemes", source="web")
    bundle = _bundle_for_prompt(
        static_chunks=[static_pmfby],
        web_chunks=[web_schemes],
    )
    facet_groups = {
        "pmfby": [static_pmfby],
        "schemes": [web_schemes],
    }
    _, user_prompt = ec.build_curated_prompt(
        bundle,
        "PMFBY premium and PM-KISAN",
        [],
        "en",
        facet_groups=facet_groups,
        facet_coverage={"pmfby": {"status": "supported"}, "schemes": {"status": "supported"}},
    )
    assert "FACET:" in user_prompt
    assert "== FACET: pmfby ==" in user_prompt
    assert "== FACET: schemes ==" in user_prompt
    assert "Answer each facet under its own bold sub-heading" in user_prompt
    assert "Evidence insufficient for [facet]" in user_prompt


def test_prompt_facet_empty_group_renders_sentinel():
    from app.evidence_controller import EvidenceController

    ec = EvidenceController()
    static_pmfby = _chunk("static-pmfby-001", 0.8, domain="pmfby", source="static")
    bundle = _bundle_for_prompt(static_chunks=[static_pmfby], web_chunks=[])
    facet_groups = {"pmfby": [static_pmfby], "schemes": []}
    _, user_prompt = ec.build_curated_prompt(
        bundle, "PMFBY premium and PM-KISAN", [], "en",
        facet_groups=facet_groups,
    )
    assert "== FACET: schemes ==" in user_prompt
    assert "No evidence retrieved for this facet." in user_prompt


def test_prompt_single_path_unchanged_when_absent():
    from app.evidence_controller import EvidenceController

    ec = EvidenceController()
    static_pmfby = _chunk("static-pmfby-001", 0.8, domain="pmfby", source="static")
    bundle = _bundle_for_prompt(static_chunks=[static_pmfby], web_chunks=[])

    _, prompt_a = ec.build_curated_prompt(bundle, "What is PMFBY premium?", [], "en")
    _, prompt_b = ec.build_curated_prompt(bundle, "What is PMFBY premium?", [], "en")
    assert prompt_a == prompt_b  # deterministic
    assert "FACET:" not in prompt_a
    assert "Answer each facet under its own bold sub-heading" not in prompt_a
    # Explicit None facet_groups matches the implicit single-path output.
    _, prompt_c = ec.build_curated_prompt(
        bundle, "What is PMFBY premium?", [], "en",
        facet_groups=None, facet_coverage=None,
    )
    assert prompt_c == prompt_a
    # Bundle-carried groups also trigger facet mode (orchestrator I1 path).
    bundle.facet_groups = {"pmfby": [static_pmfby]}
    _, prompt_d = ec.build_curated_prompt(bundle, "What is PMFBY premium?", [], "en")
    assert "FACET:" in prompt_d


async def test_orchestrator_run_wires_facet_groups_to_prompt():
    """I1: multi-facet run() must pass facet groups into the prompt build."""
    orch = RAGOrchestrator(_settings())
    english_query = "PMFBY premium and PM-KISAN Gujarat"
    facets = [
        Facet(facet_id="pmfby", domain="pmfby", query="PMFBY premium Gujarat", state="Gujarat"),
        Facet(facet_id="schemes", domain="schemes", query="PM-KISAN Gujarat", state="Gujarat"),
    ]
    static_pmfby = _chunk("static-pmfby-001", 0.8, domain="pmfby", source="static")
    web_schemes = _chunk("web-schemes-001", 67.2, domain="schemes", source="web")
    facet_chunks = {"pmfby": [static_pmfby], "schemes": [web_schemes]}
    merged = [static_pmfby, web_schemes]
    coverage = {"pmfby": {"status": "supported"}, "schemes": {"status": "supported"}}
    static_result = RAGResult(
        chunks=[static_pmfby], abstained=False,
        band=ConfidenceBand.MEDIUM, domain="pmfby",
    )
    web_result = RAGResult(
        chunks=[web_schemes], abstained=False,
        band=ConfidenceBand.MEDIUM, domain="schemes",
        metadata={"facet_groups": facet_chunks, "facet_coverage": coverage},
    )

    fake_store = MagicMock()
    fake_store.collect_hits.return_value = ["pmfby", "schemes"]

    captured: dict = {}

    def fake_build_prompt(bundle, eq, history, lang, **kwargs):
        captured["facet_groups"] = kwargs.get("facet_groups")
        captured["bundle_groups"] = getattr(bundle, "facet_groups", None)
        return ("sys", "user")

    with (
        patch.object(ro, "get_anchor_store", return_value=fake_store),
        patch.object(ro, "split_facets", return_value=facets),
        patch.object(
            orch, "_run_facet_pipelines",
            new=AsyncMock(return_value=(static_result, web_result, merged, coverage)),
        ),
        patch.object(
            orch._evidence_controller, "build_bundle",
            wraps=orch._evidence_controller.build_bundle,
        ),
        patch.object(
            orch._evidence_controller, "build_curated_prompt",
            side_effect=fake_build_prompt,
        ),
        patch.object(ro, "grounded_answer", return_value="answer"),
        patch.object(
            ro, "verify_citations",
            return_value=SimpleNamespace(is_valid=True, reason=None, invalid_prefixes=[]),
        ),
        patch.object(
            ro, "verify_answer_grounding",
            return_value=SimpleNamespace(has_unsupported_claims=False),
        ),
    ):
        await orch.run(
            query=english_query,
            english_query=english_query,
            embedding=[0.1] * 8,
            domain="pmfby",
            state="Gujarat",
            classification=_classification(),
            history=[],
            lang="en",
            session_id="sess-facet-wire",
        )

    assert captured["facet_groups"] is not None
    assert set(captured["facet_groups"].keys()) == {"pmfby", "schemes"}
    assert captured["bundle_groups"] is not None
