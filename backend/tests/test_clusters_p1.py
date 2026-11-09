"""P1-2 version/mirror clustering tests.

Covers: URL normalization, same-URL merge, cross-domain mirror merge
(title + instrument), title-only non-merge, version splits (revision
label, effective date, season year, supersession conflict, differing
instrument IDs), canonical preference, provenance preservation
(nothing deleted/reordered), and discover() integration.
"""

from app.web_rag.clusters import (
    _same_document,
    cluster_results,
    normalize_title,
    normalize_url,
)


def _chunk(chunk_id, url, title, text, validity=None, official=True, role=None, fit=None):
    chunk = {
        "chunk_id": chunk_id,
        "source_url": url,
        "url": url,
        "title": title,
        "web_title": title,
        "text": text,
        "content": text,
        "official": official,
        "trusted_secondary": False,
    }
    if validity is not None:
        chunk["validity"] = validity
    if role is not None:
        chunk["document_role"] = role
    if fit is not None:
        chunk["mandate_fit"] = fit
    return chunk


_GUIDELINE_TEXT = "Operational guidelines for the crop insurance scheme covering notified crops. " * 10


class TestNormalize:
    def test_tracking_params_dropped(self):
        assert normalize_url(
            "https://pmfby.gov.in/guidelines?utm_source=x&fbclid=y"
        ) == normalize_url("https://PMFBY.gov.in/guidelines/")

    def test_functional_params_preserved(self):
        assert normalize_url(
            "https://pib.gov.in/PressReleasePage.aspx?PRID=1"
        ) != normalize_url("https://pib.gov.in/PressReleasePage.aspx?PRID=2")

    def test_title_normalization(self):
        assert normalize_title("Operational Guidelines — PMFBY (2023)") == \
            normalize_title("operational guidelines  pmfby  2023")


class TestSameDocument:
    def test_same_url_merges(self):
        a = _chunk("a", "https://x.gov.in/doc.pdf?a=1", "Doc", _GUIDELINE_TEXT)
        b = _chunk("b", "https://x.gov.in/doc.pdf?a=1&utm_source=z", "Doc", _GUIDELINE_TEXT)
        assert _same_document(a, b) is True

    def test_cross_domain_mirror_merges(self):
        validity = {"instrument_id": "OG-2023", "supersession_status": "unknown"}
        a = _chunk("a", "https://pmfby.gov.in/og.pdf", "Operational Guidelines PMFBY", _GUIDELINE_TEXT, validity)
        b = _chunk("b", "https://agri.odisha.gov.in/og-copy.pdf", "Operational Guidelines PMFBY", _GUIDELINE_TEXT, validity)
        assert _same_document(a, b) is True

    def test_title_only_does_not_merge(self):
        a = _chunk("a", "https://x.gov.in/schemes", "Schemes", "Content about wheat support. " * 10)
        b = _chunk("b", "https://y.gov.in/list", "Schemes", "Content about dairy subsidy rates. " * 10)
        assert _same_document(a, b) is False

    def test_different_revision_splits(self):
        va = {"revision_label": "v5", "supersession_status": "unknown"}
        vb = {"revision_label": "v6", "supersession_status": "unknown"}
        a = _chunk("a", "https://x.gov.in/ncp-v5.pdf", "National Cooperation Policy", _GUIDELINE_TEXT, va)
        b = _chunk("b", "https://x.gov.in/ncp-v6.pdf", "National Cooperation Policy", _GUIDELINE_TEXT, vb)
        assert _same_document(a, b) is False

    def test_supersession_conflict_splits(self):
        va = {"supersession_status": "superseded"}
        vb = {"supersession_status": "current"}
        a = _chunk("a", "https://x.gov.in/scheme-2021", "Ombudsman Scheme", _GUIDELINE_TEXT, va)
        b = _chunk("b", "https://x.gov.in/scheme-2026", "Ombudsman Scheme", _GUIDELINE_TEXT, vb)
        assert _same_document(a, b) is False

    def test_effective_date_split(self):
        va = {"effective_from": "2020-01-01", "supersession_status": "unknown"}
        vb = {"effective_from": "2027-01-01", "supersession_status": "unknown"}
        a = _chunk("a", "https://x.gov.in/dir", "KCC Directions", _GUIDELINE_TEXT, va)
        b = _chunk("b", "https://x.gov.in/dir", "KCC Directions", _GUIDELINE_TEXT, vb)
        assert _same_document(a, b) is False

    def test_differing_instrument_ids_split(self):
        va = {"instrument_id": "42/2024", "supersession_status": "unknown"}
        vb = {"instrument_id": "43/2024", "supersession_status": "unknown"}
        a = _chunk("a", "https://x.gov.in/a.pdf", "Circular", _GUIDELINE_TEXT, va)
        b = _chunk("b", "https://y.gov.in/b.pdf", "Circular", _GUIDELINE_TEXT, vb)
        assert _same_document(a, b) is False


class TestClusterResults:
    def test_mirrors_clustered_provenance_kept(self):
        """Adversarial #4: same PDF on multiple domains clusters, kept."""
        validity = {"instrument_id": "OG-2023", "supersession_status": "unknown"}
        chunks = [
            _chunk("a", "https://pmfby.gov.in/og.pdf", "Operational Guidelines", _GUIDELINE_TEXT, validity),
            _chunk("b", "https://mirror.example/og.pdf", "Operational Guidelines", _GUIDELINE_TEXT, validity, official=False),
            _chunk("c", "https://other.gov.in/unrelated", "Unrelated Doc", "Totally different content here. " * 10),
        ]
        summary = cluster_results(chunks)
        assert chunks[0]["cluster_id"] == chunks[1]["cluster_id"]
        assert chunks[0]["cluster_id"] != chunks[2]["cluster_id"]
        assert summary["mirrored_chunks"] == 2
        # Nothing deleted, order preserved.
        assert [c["chunk_id"] for c in chunks] == ["a", "b", "c"]
        # Canonical prefers the official copy.
        assert chunks[0]["canonical_in_cluster"] is True
        assert chunks[1]["canonical_in_cluster"] is False

    def test_distinct_revisions_stay_separate(self):
        """Adversarial #5: genuinely different revisions remain separate."""
        chunks = [
            _chunk("a", "https://x.gov.in/ncp.pdf", "Policy", _GUIDELINE_TEXT,
                   {"revision_label": "v5", "supersession_status": "unknown"}),
            _chunk("b", "https://x.gov.in/ncp.pdf", "Policy", _GUIDELINE_TEXT,
                   {"revision_label": "v6", "supersession_status": "unknown"}),
        ]
        cluster_results(chunks)
        assert chunks[0]["cluster_id"] != chunks[1]["cluster_id"]

    def test_singletons_get_own_cluster(self):
        chunks = [_chunk("a", "https://x.gov.in/a", "A", "Text A " * 20)]
        summary = cluster_results(chunks)
        assert chunks[0]["cluster_id"]
        assert chunks[0]["canonical_in_cluster"] is True
        assert summary["mirrored_chunks"] == 0

    def test_deterministic_ids(self):
        def run():
            chunks = [
                _chunk("a", "https://x.gov.in/a.pdf", "Doc", _GUIDELINE_TEXT),
                _chunk("b", "https://y.gov.in/a.pdf", "Doc", _GUIDELINE_TEXT),
            ]
            cluster_results(chunks)
            return [c["cluster_id"] for c in chunks]
        assert run() == run()


class TestDiscoverIntegration:
    def test_discover_reports_clustering(self):
        from unittest.mock import patch

        from app.web_rag.service import WebDiscoveryService

        items = [
            {
                "url": "https://pmfby.gov.in/og.pdf?utm_source=x",
                "title": "Operational Guidelines PMFBY crop insurance",
                "content": "Operational guidelines crop insurance PMFBY. " * 20,
                "raw_content": "",
                "score": 0.9,
            },
            {
                "url": "https://pmfby.gov.in/og.pdf",
                "title": "Operational Guidelines PMFBY crop insurance",
                "content": "Operational guidelines crop insurance PMFBY. " * 20,
                "raw_content": "",
                "score": 0.8,
            },
        ]
        service = WebDiscoveryService()
        with patch.object(
            WebDiscoveryService, "_search_all", return_value=list(items)
        ):
            result = service.discover("PMFBY operational guidelines")
        assert result["discovery_metadata"]["clustering"]["mirrored_chunks"] == 2
        for chunk in result["results"]:
            assert chunk.get("cluster_id")
            assert "canonical_in_cluster" in chunk
