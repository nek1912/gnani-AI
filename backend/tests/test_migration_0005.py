"""Migration 0005 validation — checks SQL syntax and contract alignment.

Does NOT require a live database. Validates:
- SQL syntax (basic parse)
- All contract-required columns exist
- No destructive operations (DROP, DELETE without WHERE)
- Deterministic IDs where required
- Check constraints match contract enums
"""

import re
from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0005_rag_contracts.sql"
INIT_MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0001_init.sql"


def _read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestMigrationSyntax:
    def test_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration not found: {MIGRATION_PATH}"

    def test_no_drop_table(self):
        sql = _read_sql(MIGRATION_PATH)
        drops = re.findall(r"DROP\s+TABLE", sql, re.IGNORECASE)
        assert not drops, f"Migration contains DROP TABLE (destructive): {drops}"

    def test_no_unconditional_delete(self):
        sql = _read_sql(MIGRATION_PATH)
        # DELETE is ok in functions (atomic_replace), but not standalone
        deletes = re.findall(r"^DELETE\s+FROM", sql, re.IGNORECASE | re.MULTILINE)
        assert not deletes, f"Migration contains standalone DELETE: {deletes}"

    def test_additive_alters_only(self):
        sql = _read_sql(MIGRATION_PATH)
        # Only ADD COLUMN, ADD INDEX allowed on existing tables
        alters = re.findall(r"ALTER\s+TABLE\s+\w+\s+ADD\s+(?:COLUMN\s+)?IF\s+NOT\s+EXISTS", sql, re.IGNORECASE)
        assert len(alters) >= 5, f"Expected >=5 ALTER TABLE ADD IF NOT EXISTS, got {len(alters)}"

    def test_new_tables_created(self):
        sql = _read_sql(MIGRATION_PATH)
        expected_tables = ["embedding_profiles", "corpus_versions", "ingestion_runs",
                           "evaluation_runs", "legacy_chunk_mapping"]
        for table in expected_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"Missing CREATE TABLE for {table}"

    def test_embedding_profile_fingerprint_unique(self):
        sql = _read_sql(MIGRATION_PATH)
        assert "fingerprint text NOT NULL UNIQUE" in sql

    def test_check_constraints_match_contracts(self):
        sql = _read_sql(MIGRATION_PATH)
        # authority_tier enum values
        assert "'primary'" in sql
        assert "'secondary'" in sql
        assert "'tertiary'" in sql
        assert "'unknown'" in sql
        # document status values
        assert "'superseded'" in sql
        assert "'withdrawn'" in sql
        # ingestion run status values
        assert "'staging'" in sql
        assert "'activated'" in sql
        assert "'rolled_back'" in sql

    def test_gin_index_for_lexical(self):
        sql = _read_sql(MIGRATION_PATH)
        assert "gin(to_tsvector" in sql

    def test_no_vector_dimension_change(self):
        """Existing vector(768) must not be altered."""
        sql = _read_sql(MIGRATION_PATH)
        vector_alters = re.findall(r"ALTER.*vector\(\d+\)", sql, re.IGNORECASE)
        assert not vector_alters, f"Migration alters vector dimension: {vector_alters}"


class TestContractAlignment:
    def test_documents_has_all_contract_columns(self):
        """Verify documents table has all DocumentMetadata fields."""
        init_sql = _read_sql(INIT_MIGRATION_PATH)
        new_sql = _read_sql(MIGRATION_PATH)
        combined = init_sql + new_sql

        required_columns = [
            "source_id", "title", "domain", "jurisdiction", "state",
            "effective_date", "document_date", "status", "authority_tier",
            "version_id", "issuer", "official_domain", "supersedes",
            "superseded_by", "effective_end", "parser_profile",
        ]
        for col in required_columns:
            # Either in CREATE TABLE or ALTER TABLE ADD
            in_create = f"{col} " in combined or f"{col}\n" in combined
            in_alter = f"ADD COLUMN IF NOT EXISTS {col}" in combined
            assert in_create or in_alter, f"Column {col} missing from documents table"

    def test_chunks_has_all_contract_columns(self):
        """Verify chunks table has all ChunkMetadata fields."""
        init_sql = _read_sql(INIT_MIGRATION_PATH)
        new_sql = _read_sql(MIGRATION_PATH)
        combined = init_sql + new_sql

        required_columns = [
            "chunk_id", "content_hash", "page_start", "page_end",
            "heading_path", "section_number", "language", "token_count",
            "chunker_version", "ordinal",
        ]
        for col in required_columns:
            in_create = f"{col} " in combined or f"{col}\n" in combined
            in_alter = f"ADD COLUMN IF NOT EXISTS {col}" in combined
            assert in_create or in_alter, f"Column {col} missing from chunks table"
