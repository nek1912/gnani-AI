"""Sessions ownership migration validation — static SQL/schema checks.

Does NOT require a live database. Validates the additive
`sessions.user_id` migration against the ownership contract:
- valid additive SQL, safe to re-run against an existing table
- nullable owner (legacy NULL rows preserved, never backfilled)
- no RLS, no destructive ops, no triggers/functions touched
- backend/schema.sql and session_store.py agree on names/types
"""

import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "supabase" / "migrations" / "20261007_sessions_user_id.sql"
)
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
STORE_PATH = Path(__file__).resolve().parent.parent / "app" / "session_store.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestMigrationValidity:
    def test_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration not found: {MIGRATION_PATH}"

    def test_adds_nullable_user_id(self):
        sql = _read(MIGRATION_PATH)
        assert re.search(
            r"ALTER\s+TABLE\s+sessions\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+user_id\s+TEXT",
            sql,
            re.IGNORECASE,
        ), "Migration must add sessions.user_id TEXT idempotently"
        # Legacy rows must stay NULL: no NOT NULL, no DEFAULT, no backfill.
        assert "NOT NULL" not in sql.upper()
        assert re.search(r"\bUPDATE\b", sql, re.IGNORECASE) is None

    def test_index_defined(self):
        sql = _read(MIGRATION_PATH)
        assert re.search(
            r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+idx_sessions_user_id\s+ON\s+sessions\s*\(\s*user_id\s*\)",
            sql,
            re.IGNORECASE,
        )

    def test_no_destructive_ops(self):
        sql = _read(MIGRATION_PATH)
        assert re.search(r"DROP\s+TABLE", sql, re.IGNORECASE) is None
        assert re.search(r"^DELETE\s+FROM", sql, re.IGNORECASE | re.MULTILINE) is None
        assert re.search(r"DROP\s+COLUMN", sql, re.IGNORECASE) is None

    def test_no_rls_implied(self):
        sql = _read(MIGRATION_PATH)
        for kw in ("ROW LEVEL SECURITY", "CREATE POLICY", "ENABLE RLS", "FORCE RLS"):
            assert kw not in sql.upper(), f"Migration must not imply RLS: {kw}"

    def test_no_function_trigger_changes(self):
        sql = _read(MIGRATION_PATH)
        assert "purge_expired_sessions" not in sql.lower()
        assert "trigger" not in sql.lower()


class TestSchemaAppConsistency:
    def test_schema_sessions_has_user_id(self):
        schema = _read(SCHEMA_PATH)
        m = re.search(
            r"create\s+table\s+if\s+not\s+exists\s+sessions\s*\((.*?)\);",
            schema,
            re.IGNORECASE | re.DOTALL,
        )
        assert m, "sessions table missing from backend/schema.sql"
        assert re.search(r"\buser_id\s+text\b", m.group(1), re.IGNORECASE)
        assert "idx_sessions_user_id" in schema

    def test_store_queries_agree(self):
        store = _read(STORE_PATH)
        assert "user_id" in store
        assert '"session_id,user_id,state"' in store or "'session_id,user_id,state'" in store
        assert '"user_id": user_id' in store or "'user_id': user_id" in store
