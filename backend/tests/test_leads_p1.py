"""P1-1 lead-following tests.

Covers: identifier/portal extraction, lead-source gating, hard bounds
(<=3 leads, one round, no recursion), official-scoped follow-up,
has-instrument skip, pool preservation on failure, lead tagging, and
the citation bar (build/auto-append/verification IDs).
"""

from unittest.mock import patch

from app.contracts import EvidenceChunk
from app.services.rag_orchestrator import RAGOrchestrator
from app.web_rag.leads import (
    MAX_LEADS,
    build_lead_branches,
    extract_leads,
    find_portal_mentions,
    is_lead_source,
    select_leads,
    tag_lead_sources,
)
from app.web_rag.service import OFFICIAL_DOMAINS, WebDiscoveryService
from app.web_rag.validity import find_instrument_mentions


def _item(url, title, text, official=False):
    return {
        "url": url,
        "title": title,
        "content": text,
        "raw_content": text,
        "score": 0.9,
        "favicon": None,
    }


_SECONDARY_WITH_GR = _item(
    "https://gujarat-news.example/krushi-rahat-2025",
    "Krushi Rahat Package 2025 village list",
    "The state announced relief under GR No. KRP/2025/1145 dated "
    "3 March 2025. Farmers must apply via i-Khedut portal. " * 6,
)

_OFFICIAL_GR = _item(
    "https://agri.gujarat.gov.in/gr/krp-2025-1145",
    "Krushi Rahat GR 2025",
    "Government Resolution No. KRP/2025/1145 dated 3 March 2025 "
    "relief package for farmers with effect from 1 April 2025. " * 6,
    official=True,
)


class TestLeadExtraction:
    def test_instrument_mentions(self):
        ids = find_instrument_mentions(
            "See circular No. 42/2024 and GR No. KRP/2025/1145 for details."
        )
        assert "42/2024" in ids
        assert "KRP/2025/1145" in ids

    def test_bare_tokens_ignored(self):
        assert find_instrument_mentions("KRP 2025 package announced") == []
        assert find_instrument_mentions("reference 42 updated") == []

    def test_rbi_reference(self):
        ids = find_instrument_mentions(
            "As per RBI reference DOR.MCS.REC.59/01.01.003/2025-26 banks shall"
        )
        assert any("DOR" in i for i in ids)

    def test_portal_mentions(self):
        mentions = find_portal_mentions("Apply via the i-Khedut portal online.")
        assert mentions and mentions[0]["domains"] == ["ikhedut.gujarat.gov.in"]

    def test_unknown_portal_ignored(self):
        assert find_portal_mentions("Apply via the KRP portal app.") == []

    def test_is_lead_source(self):
        assert is_lead_source({"official": False, "trusted_secondary": False}) is True
        assert is_lead_source({"official": True, "trusted_secondary": False}) is False
        assert is_lead_source({"official": False, "trusted_secondary": True}) is False

    def test_extract_leads_skips_official(self):
        official = dict(_OFFICIAL_GR)
        official["official"] = True
        assert extract_leads([official]) == []

    def test_extract_leads_from_secondary(self):
        leads = extract_leads([_SECONDARY_WITH_GR])
        kinds = [lead["kind"] for lead in leads]
        assert "instrument_id" in kinds
        assert "portal" in kinds
        # Instrument IDs sort before portal mentions.
        assert kinds.index("instrument_id") < kinds.index("portal")

    def test_select_leads_hard_bound(self):
        many = [{"kind": "instrument_id", "value": f"ID/{i}"} for i in range(10)]
        assert len(select_leads(many)) == MAX_LEADS
        assert MAX_LEADS == 3

    def test_tag_lead_sources(self):
        chunk = dict(_SECONDARY_WITH_GR)
        leads = extract_leads([chunk])
        assert tag_lead_sources([chunk], leads) == 1
        assert chunk["lead_only"] is True

    def test_tag_skips_non_lead_chunks(self):
        official = dict(_OFFICIAL_GR)
        official["official"] = True
        leads = extract_leads([dict(_SECONDARY_WITH_GR)])
        assert tag_lead_sources([official], leads) == 0
        assert "lead_only" not in official


class TestLeadBranches:
    def test_branches_bounded_and_scoped(self):
        from app.web_rag.query_classifier import QueryClassification

        classification = QueryClassification(
            domain="agriculture", jurisdiction="state", state="Gujarat",
            intent="STATUS", confidence=0.8,
        )
        leads = extract_leads([_SECONDARY_WITH_GR])
        branches = build_lead_branches(
            leads, classification,
            ["agri.gujarat.gov.in", "gov.in"],
            fallback_domains=OFFICIAL_DOMAINS,
        )
        assert 1 <= len(branches) <= MAX_LEADS
        for branch in branches:
            assert branch["name"].startswith("lead:")
            assert branch["only_official"] is True
            assert branch["allow_domains"]
            assert branch["max_results"] <= 8

    def test_branch_query_carries_identifier(self):
        from app.web_rag.query_classifier import QueryClassification

        classification = QueryClassification(
            domain="agriculture", jurisdiction="state", state="Gujarat",
            intent="STATUS", confidence=0.8,
        )
        leads = extract_leads([_SECONDARY_WITH_GR])
        branches = build_lead_branches(leads, classification, None,
                                        fallback_domains=OFFICIAL_DOMAINS)
        assert any("KRP/2025/1145" in b["query"] for b in branches)


class TestLeadRoundIntegration:
    def test_secondary_lead_retrieves_official_instrument(self):
        """Adversarial #1: article -> official notification becomes evidence."""
        service = WebDiscoveryService()
        calls = []

        def fake_search_all(query, **kwargs):
            calls.append(query)
            if "KRP/2025/1145" in query:
                return [_OFFICIAL_GR]
            return [_SECONDARY_WITH_GR]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("Krushi Rahat Package 2025 Gujarat")

        urls = [r.get("source_url") for r in result["results"]]
        assert "https://agri.gujarat.gov.in/gr/krp-2025-1145" in urls
        assert any("lead:" in b for b in result["discovery_metadata"]["branches_run"]) or \
            result["discovery_metadata"]["lead_following"]["leads_followed"] >= 1
        # The article itself is tagged lead-only.
        article = next(
            r for r in result["results"]
            if r.get("source_url") == "https://gujarat-news.example/krushi-rahat-2025"
        )
        assert article.get("lead_only") is True

    def test_dead_lead_preserves_pool(self):
        """Adversarial #2: dead/wrong document -> pool preserved, lead tagged."""
        service = WebDiscoveryService()

        def fake_search_all(query, **kwargs):
            return [_SECONDARY_WITH_GR]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("Krushi Rahat Package 2025 Gujarat")

        assert len(result["results"]) > 0
        article = next(
            r for r in result["results"]
            if "gujarat-news.example" in (r.get("source_url") or "")
        )
        assert article.get("lead_only") is True

    def test_has_instrument_skips_lead_round(self):
        service = WebDiscoveryService()
        branch_calls = []

        real_search_branches = WebDiscoveryService._search_branches

        def counting_branches(self, branches):
            branch_calls.append([b["name"] for b in branches])
            return real_search_branches(self, branches)

        def fake_search_all(query, **kwargs):
            return [_OFFICIAL_GR]

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ), patch.object(
            WebDiscoveryService, "_search_branches", counting_branches
        ):
            service.discover("Krushi Rahat Package 2025 Gujarat")

        assert branch_calls, "expected at least the stage-1 branch run"
        assert not any(
            name.startswith("lead:") for names in branch_calls for name in names
        )


class TestCitationBar:
    def _chunk(self, chunk_id, lead_only=False):
        return EvidenceChunk(
            chunk_id=chunk_id, content="text", source_type="web",
            title="t", url="https://example.gov.in/x",
            metadata={"lead_only": lead_only} if lead_only else {},
        )

    def test_build_citations_excludes_leads(self):
        orch = RAGOrchestrator.__new__(RAGOrchestrator)
        citations = orch._build_citations(
            [self._chunk("a" * 8 + "full-id-a"), self._chunk("b" * 8 + "full-id-b", lead_only=True)]
        )
        assert [c["chunk_id"] for c in citations] == ["a" * 8]

    def test_auto_append_skips_leads(self):
        orch = RAGOrchestrator.__new__(RAGOrchestrator)
        answer = orch._auto_append_citations(
            "Some answer without markers",
            [self._chunk("b" * 8 + "full-id-b", lead_only=True)],
        )
        assert "[chunk:" not in answer

    def test_auto_append_uses_citable_chunks(self):
        orch = RAGOrchestrator.__new__(RAGOrchestrator)
        answer = orch._auto_append_citations(
            "Some answer without markers",
            [self._chunk("b" * 8 + "full-id-b", lead_only=True),
             self._chunk("a" * 8 + "full-id-a")],
        )
        assert "[chunk:aaaaaaaa]" in answer
        assert "[chunk:bbbbbbbb]" not in answer
