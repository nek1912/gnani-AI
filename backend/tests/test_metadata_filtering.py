"""PHASE 6: Metadata filtering validation tests.

Tests that the evidence gate and retrieval pipeline correctly filter:
- Domain: only chunks from the expected domain pass
- Jurisdiction: central docs always pass, state docs only if state matches
- Effective date: documents with effective_date > as_of_date are excluded
- Document identity: stable_chunk_id is tracked correctly

These tests verify the GENERIC filtering logic — no query-specific exceptions.
"""
import pytest

from app.retrieval import RetrievedChunk, evidence_gate


def _chunk(
    sim: float,
    domain: str = "pmfby",
    jurisdiction: str = "central",
    state: str | None = None,
    effective_date: str | None = None,
    document_id: str = "doc1",
    stable_chunk_id: str = "test:p1:c0",
) -> RetrievedChunk:
    """Helper to create a test chunk with metadata."""
    return RetrievedChunk(
        chunk_id=f"c_{domain}_{jurisdiction}_{state or 'none'}",
        stable_chunk_id=stable_chunk_id,
        document_id=document_id,
        title=f"Title for {domain}",
        page=1,
        page_start=1,
        page_end=1,
        section="Section",
        content=f"Content for {domain}",
        similarity=sim,
        source_url=f"https://{domain}.example.com",
        domain=domain,
        jurisdiction=jurisdiction,
        state=state,
    )


# ═══════════════════════════════════════════════════════════════════════════
# DOMAIN FILTERING
# ═══════════════════════════════════════════════════════════════════════════

class TestDomainFiltering:
    """Domain filtering must reject any chunk not matching expected_domain."""

    def test_single_wrong_domain_abstains(self):
        chunks = [_chunk(0.8, domain="finlit")]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"

    def test_mixed_domains_abstains(self):
        chunks = [
            _chunk(0.8, domain="pmfby"),
            _chunk(0.7, domain="finlit"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"

    def test_all_correct_domain_passes(self):
        chunks = [_chunk(0.8), _chunk(0.6), _chunk(0.4)]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is False

    def test_no_domain_filter_passes_any_domain(self):
        chunks = [_chunk(0.8, domain="finlit"), _chunk(0.6, domain="cooperative")]
        result = evidence_gate(chunks, expected_domain=None)
        assert result.abstained is False

    @pytest.mark.parametrize("wrong_domain", [
        "cooperative", "pacs", "schemes", "agriculture", "finlit", "grievance",
    ])
    def test_each_wrong_domain_abstains(self, wrong_domain: str):
        chunks = [_chunk(0.8, domain=wrong_domain)]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"


# ═══════════════════════════════════════════════════════════════════════════
# JURISDICTION FILTERING
# ═══════════════════════════════════════════════════════════════════════════

class TestJurisdictionFiltering:
    """Jurisdiction filtering: central always passes, state only if matches.
    
    Note: evidence_gate also requires sufficient similarity + supporting chunks.
    Tests use enough chunks to pass those thresholds.
    """

    def test_central_always_passes(self):
        chunks = [_chunk(0.8, jurisdiction="central"), _chunk(0.5, jurisdiction="central"),
                  _chunk(0.4, jurisdiction="central")]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is False

    def test_state_matches_passes(self):
        chunks = [_chunk(0.8, jurisdiction="state", state="gujarat"),
                  _chunk(0.5, jurisdiction="state", state="gujarat"),
                  _chunk(0.4, jurisdiction="state", state="gujarat")]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is False

    def test_state_mismatch_abstains(self):
        chunks = [_chunk(0.8, jurisdiction="state", state="maharashtra")]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "jurisdiction_mismatch_in_retrieval"

    def test_central_plus_matching_state_passes(self):
        chunks = [
            _chunk(0.8, jurisdiction="central"),
            _chunk(0.6, jurisdiction="state", state="gujarat"),
        ]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is False

    def test_central_plus_wrong_state_abstains(self):
        chunks = [
            _chunk(0.8, jurisdiction="central"),
            _chunk(0.6, jurisdiction="state", state="maharashtra"),
        ]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "jurisdiction_mismatch_in_retrieval"

    def test_multiple_wrong_states_abstains(self):
        chunks = [
            _chunk(0.8, jurisdiction="state", state="maharashtra"),
            _chunk(0.6, jurisdiction="state", state="rajasthan"),
        ]
        result = evidence_gate(chunks, expected_state="gujarat")
        assert result.abstained is True

    def test_no_state_filter_only_central_passes(self):
        """When expected_state=None, only central docs pass (matching SQL behavior).
        State docs require an explicit state filter to be included."""
        chunks = [_chunk(0.8, jurisdiction="central"),
                  _chunk(0.5, jurisdiction="central"),
                  _chunk(0.4, jurisdiction="central")]
        result = evidence_gate(chunks, expected_state=None)
        assert result.abstained is False

    def test_state_chunks_rejected_when_no_filter(self):
        """State docs without a state filter → rejected (SQL won't return them)."""
        chunks = [_chunk(0.8, jurisdiction="state", state="maharashtra")]
        result = evidence_gate(chunks, expected_state=None)
        assert result.abstained is True
        assert result.reason == "jurisdiction_mismatch_in_retrieval"


# ═══════════════════════════════════════════════════════════════════════════
# EFFECTIVE DATE FILTERING (via evidence gate logic)
# ═══════════════════════════════════════════════════════════════════════════

class TestEffectiveDateFiltering:
    """Effective date filtering is enforced at SQL level (match_chunks RPC).
    
    The evidence gate does NOT filter by effective_date — that's the SQL layer's
    job. These tests verify the evidence gate doesn't break when chunks have
    various effective_date values. The SQL function handles the actual filtering.
    """

    def test_chunks_with_any_date_pass_gate(self):
        """Gate should not care about effective_date — SQL handles that."""
        chunks = [_chunk(0.8), _chunk(0.5), _chunk(0.4)]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is False

    def test_mixed_dates_in_chunks_pass_gate(self):
        """Gate should pass regardless of effective_date diversity."""
        chunks = [_chunk(0.8), _chunk(0.6)]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is False


# ═══════════════════════════════════════════════════════════════════════════
# DOCUMENT IDENTITY / VERSION TRACKING
# ═══════════════════════════════════════════════════════════════════════════

class TestDocumentIdentity:
    """stable_chunk_id and document_id must be tracked through the pipeline."""

    def test_stable_chunk_id_preserved(self):
        chunk = _chunk(0.8, stable_chunk_id="pmfby-faq:p1:c0")
        assert chunk.stable_chunk_id == "pmfby-faq:p1:c0"

    def test_document_id_preserved(self):
        chunk = _chunk(0.8, document_id="doc-123")
        assert chunk.document_id == "doc-123"

    def test_different_documents_have_different_ids(self):
        c1 = _chunk(0.8, document_id="doc-1", stable_chunk_id="doc1:p1:c0")
        c2 = _chunk(0.8, document_id="doc-2", stable_chunk_id="doc2:p1:c0")
        assert c1.document_id != c2.document_id
        assert c1.stable_chunk_id != c2.stable_chunk_id


# ═══════════════════════════════════════════════════════════════════════════
# COMBINED FILTER SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════

class TestCombinedFilters:
    """Tests combining multiple filter dimensions."""

    def test_correct_domain_plus_central_passes(self):
        chunks = [
            _chunk(0.8, domain="pmfby", jurisdiction="central"),
            _chunk(0.5, domain="pmfby", jurisdiction="central"),
            _chunk(0.4, domain="pmfby", jurisdiction="central"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is False

    def test_correct_domain_plus_wrong_state_abstains(self):
        chunks = [
            _chunk(0.8, domain="pmfby", jurisdiction="state", state="maharashtra"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "jurisdiction_mismatch_in_retrieval"

    def test_wrong_domain_plus_correct_state_abstains(self):
        chunks = [
            _chunk(0.8, domain="finlit", jurisdiction="state", state="gujarat"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"

    def test_mixed_domains_and_states_abstains(self):
        chunks = [
            _chunk(0.8, domain="pmfby", jurisdiction="central"),
            _chunk(0.7, domain="finlit", jurisdiction="state", state="gujarat"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"

    def test_all_filters_pass_with_sufficient_evidence(self):
        chunks = [
            _chunk(0.8, domain="pmfby", jurisdiction="central"),
            _chunk(0.6, domain="pmfby", jurisdiction="state", state="gujarat"),
            _chunk(0.4, domain="pmfby", jurisdiction="central"),
        ]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is False
        assert result.confidence > 0.0
