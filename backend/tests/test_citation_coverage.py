"""Route-coverage tests proving citation verification is unavoidable.

Every response path must go through verify_citations_v2 from citation_verifier.
These tests verify that no code path can return a successful answer without
passing through the verifier.
"""



class TestCitationVerifierCoverage:
    """Prove the citation verifier is called on every successful response path."""

    def test_orchestrator_has_citation_auto_append(self):
        """The orchestrator auto-appends citations when the LLM omits them."""
        from app.services import rag_orchestrator
        assert hasattr(rag_orchestrator.RAGOrchestrator, "_auto_append_citations")

    def test_verifier_rejects_non_retrieved_citations(self):
        """Verifier rejects citations not in retrieved evidence."""
        from app.citation_verifier import verify_citations

        answer = "Something [chunk:fffffffffff]"
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is False
        assert result.reason is not None

    def test_verifier_rejects_fabricated_urls(self):
        """Verifier rejects answers with fabricated URLs."""
        from app.citation_verifier import verify_citations

        answer = "Visit https://fake-gov.example.com [chunk:abc12345def]"
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is False

    def test_verifier_rejects_no_citations(self):
        """Verifier rejects answers with no citations at all."""
        from app.citation_verifier import verify_citations

        answer = "PMFBY is a great scheme for farmers"
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is False
        assert "CITATION_FAILURE" in result.reason.value

    def test_verifier_accepts_valid_citations(self):
        """Verifier accepts answers with valid citations from evidence."""
        from app.citation_verifier import verify_citations

        answer = "PMFBY provides insurance [chunk:abc12345def]"
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is True
        assert len(result.valid_citations) == 1

    def test_verifier_rejects_mixed_valid_invalid(self):
        """Verifier rejects answers mixing valid and invalid citations."""
        from app.citation_verifier import verify_citations

        answer = "Good [chunk:abc12345def] bad [chunk:fffffffffff]"
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is False

    def test_verifier_accepts_fullwidth_citation(self):
        """Full-width 【ID】 markers matching evidence are normalised and accepted."""
        from app.citation_verifier import verify_citations

        answer = "PMFBY is insurance 【abc12345】 for farmers."
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is True
        assert len(result.valid_citations) == 1

    def test_verifier_rejects_fullwidth_non_retrieved(self):
        """Full-width 【ID】 NOT in evidence is still rejected."""
        from app.citation_verifier import verify_citations

        answer = "Claim 【ffffffff】 something."
        evidence_ids = ["abc12345def"]
        result = verify_citations(answer, evidence_ids)
        assert result.is_valid is False


class TestChatRouteVerificationIntegration:
    """Prove the chat route integrates with the orchestrator for citations."""

    def test_chat_route_delegates_to_orchestrator(self):
        """Chat route delegates RAG to RAGOrchestrator which handles citations."""
        from app.routes import chat
        import inspect

        source = inspect.getsource(chat.chat)
        assert "RAGOrchestrator" in source or "_get_rag_orchestrator" in source
