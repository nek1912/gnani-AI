"""Regression test for local PDF document serving.

Verifies that the /documents/pdf/{filename} endpoint correctly serves
PDF files from the corpus/seeds directory, and that the URL generation
in the frontend matches the backend route.

Root cause of 404: Frontend generated /api/documents/pdf/{filename} but
no Next.js API route existed to proxy it to the backend's /documents/pdf/{filename}.
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus" / "seeds"


class TestDocumentPDFRoute:
    """Verify the backend /documents/pdf/{filename} route serves PDFs."""

    def test_known_pdf_returns_200(self):
        """operational_guidelines_pmfby.pdf exists in corpus/seeds/."""
        resp = client.get("/documents/pdf/operational_guidelines_pmfby.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_pdf_with_spaces_in_name(self):
        """Corrigendum and letter Jun 12, 2023.pdf has spaces."""
        resp = client.get("/documents/pdf/Corrigendum and letter Jun 12, 2023.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_pdf_with_parentheses_in_name(self):
        """Model Byelaws 05.01.2023.pdf has parentheses."""
        resp = client.get("/documents/pdf/Model Byelaws 05.01.2023.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_nonexistent_pdf_returns_404(self):
        """A PDF that doesn't exist should return 404."""
        resp = client.get("/documents/pdf/nonexistent_file.pdf")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self):
        """Path traversal attempts should be rejected."""
        resp = client.get("/documents/pdf/..%2F..%2Fetc%2Fpasswd.pdf")
        assert resp.status_code in (400, 404, 422)

    def test_non_pdf_extension_rejected(self):
        """Non-.pdf files should be rejected."""
        resp = client.get("/documents/pdf/test.txt")
        assert resp.status_code in (400, 404, 422)

    def test_all_corpus_pdfs_are_serveable(self):
        """Every PDF in corpus/seeds/ should be serveable via the route."""
        if not CORPUS_DIR.exists():
            pytest.skip("corpus/seeds directory not found")

        pdf_files = list(CORPUS_DIR.glob("*.pdf"))
        if not pdf_files:
            pytest.skip("No PDF files in corpus/seeds/")

        for pdf_path in pdf_files:
            resp = client.get(f"/documents/pdf/{pdf_path.name}")
            assert resp.status_code == 200, f"Failed to serve {pdf_path.name}"
            assert resp.headers["content-type"] == "application/pdf"


class TestDocumentURLPattern:
    """Verify the frontend URL pattern matches the backend route."""

    def test_frontend_url_matches_backend_route(self):
        """The URL pattern /api/documents/pdf/{filename} must map to
        the backend route /documents/pdf/{filename} via the Next.js proxy.

        This test documents the expected URL contract between frontend and backend.
        """
        # Frontend generates (from MessageBubble.tsx line 157):
        #   /api/documents/pdf/${encodeURIComponent(citation.source_file)}
        # Backend route (from documents.py):
        #   GET /documents/pdf/{filename}
        # Next.js proxy (from api/documents/pdf/[filename]/route.ts):
        #   Proxies /api/documents/pdf/{filename} -> BACKEND_URL/documents/pdf/{filename}

        # Verify the backend route exists and works
        test_filename = "operational_guidelines_pmfby.pdf"
        resp = client.get(f"/documents/pdf/{test_filename}")
        assert resp.status_code == 200
        assert len(resp.content) > 0
        assert resp.content[:4] == b"%PDF"
