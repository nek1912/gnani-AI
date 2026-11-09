import pytest


@pytest.mark.integration
def test_documents_has_document_date_column():
    """Verify document_date column exists in documents table."""
    from app.db import get_supabase
    supabase = get_supabase()
    result = supabase.table("documents").select("document_date").limit(1).execute()
    assert result.data is not None


@pytest.mark.integration
def test_documents_has_source_type_column():
    """Verify source_type column exists in documents table."""
    from app.db import get_supabase
    supabase = get_supabase()
    result = supabase.table("documents").select("source_type").limit(1).execute()
    assert result.data is not None
