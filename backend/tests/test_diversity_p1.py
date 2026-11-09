"""P1-3 role diversification (MMR-lite) tests.

Covers: complementary roles surface, authority-first preservation,
same-family stability, determinism, empty/singleton safety, and the
retrieve-level reorder-only integration (gate multiset unchanged).
"""

from unittest.mock import patch

from app.web_rag.diversity import diversify
from app.services.web_rag import WebRAGService


def _result(url, role, tier, score, chunk_id):
    return {
        "chunk_id": chunk_id,
        "source_url": url,
        "url": url,
        "title": f"{role} document",
        "text": "evidence text",
        "rerank_score": score,
        "source_tier": tier,
        "document_role": role,
    }


def _instrument_farm(n=6, tier=4, base=90.0):
    return [
        _result(
            f"https://agri.gujarat.gov.in/gr/doc-{i}",
            "instrument", tier, base - i, f"web_inst{i:02d}_c101",
        )
        for i in range(n)
    ]


class TestDiversify:
    def test_complementary_roles_surface(self):
        """Adversarial #6: 8 same-family instruments + 2 complementary."""
        pool = _instrument_farm(8) + [
            _result("https://ikhedut.gujarat.gov.in/apply", "implementation", 6, 82.0, "web_impl_c101"),
            _result("https://pib.gov.in/release", "explainer", 4, 81.0, "web_expl_c101"),
        ]
        ordered = diversify(pool)
        assert len(ordered) == 10
        # Top relevance preserved first.
        assert ordered[0]["chunk_id"] == "web_inst00_c101"
        # Complementary roles move into the top half.
        positions = {r["chunk_id"]: i for i, r in enumerate(ordered)}
        assert positions["web_impl_c101"] < 5
        assert positions["web_expl_c101"] < 6
        # Nothing dropped, same multiset.
        assert sorted(r["chunk_id"] for r in ordered) == sorted(r["chunk_id"] for r in pool)

    def test_top_relevance_always_first(self):
        pool = _instrument_farm(4, base=70.0) + [
            _result("https://other.gov.in/top", "instrument", 4, 99.0, "web_top_c101"),
        ]
        ordered = diversify(pool)
        assert ordered[0]["chunk_id"] == "web_top_c101"

    def test_uniform_pool_stable(self):
        pool = _instrument_farm(4)
        first = [r["chunk_id"] for r in diversify(pool)]
        second = [r["chunk_id"] for r in diversify([dict(r) for r in pool])]
        assert first == second == [r["chunk_id"] for r in pool]

    def test_empty_and_singleton(self):
        assert diversify([]) == []
        single = _instrument_farm(1)
        assert diversify(single) == single
        assert single[0]["mmr_penalty"] == 0.0

    def test_top_k_slice(self):
        pool = _instrument_farm(6)
        assert len(diversify(pool, top_k=3)) == 3

    def test_mmr_penalty_stamped(self):
        pool = _instrument_farm(3) + [
            _result("https://ikhedut.gujarat.gov.in/apply", "implementation", 6, 80.0, "web_impl_c101"),
        ]
        ordered = diversify(pool)
        assert ordered[0]["mmr_penalty"] == 0.0
        assert all("mmr_penalty" in r for r in ordered)

    def test_general_family_not_penalized_against_official(self):
        pool = [
            _result("https://agri.gujarat.gov.in/gr/a", "instrument", 4, 90.0, "web_a_c101"),
            _result("https://blog.example/b", "secondary", 0, 89.0, "web_b_c101"),
        ]
        ordered = diversify(pool)
        assert [r["chunk_id"] for r in ordered] == ["web_a_c101", "web_b_c101"]


class TestRetrieveIntegration:
    def test_retrieve_preserves_gate_multiset(self):
        service = WebRAGService()
        sources = _instrument_farm(6) + [
            _result("https://ikhedut.gujarat.gov.in/apply", "implementation", 6, 82.0, "web_impl_c101"),
            _result("https://pib.gov.in/release", "explainer", 4, 81.0, "web_expl_c101"),
        ]
        for source in sources:
            source.update({
                "title": source["title"], "web_title": source["title"],
                "content": source["text"], "official": True,
                "trusted_secondary": False, "bm25_score": 1.0,
                "gemini_score": source["rerank_score"],
                "rerank_applicable": True,
            })

        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {
                "results": sources,
                "classification": {"domain": "agriculture", "jurisdiction": "state", "state": "Gujarat"},
            }
            mock_bm25.return_value = sources
            mock_final.return_value = list(sources)
            mock_verify.return_value = {
                "accepted_sources": sources,
                "rejected_sources": [],
                "summary": {},
            }
            result = service.retrieve(query="Crop relief Gujarat")

        assert result.abstained is False
        assert len(result.chunks) == 8
        # Complementary implementation evidence surfaces in cited chunks.
        roles = [c.metadata.get("document_role") for c in result.chunks]
        assert "implementation" in roles
