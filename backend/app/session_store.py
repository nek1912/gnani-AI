import logging
from datetime import UTC, datetime, timedelta

from app.db import get_supabase

logger = logging.getLogger(__name__)

# Warn-once flag for the pre-migration schema fallback below. Repeated
# per-request warnings would flood the logs; one warning per process is
# enough to tell the operator to run the migration.
_WARNED_LEGACY_SESSIONS_SCHEMA = False


def _warn_legacy_sessions_schema_once(detail: str) -> None:
    global _WARNED_LEGACY_SESSIONS_SCHEMA
    if not _WARNED_LEGACY_SESSIONS_SCHEMA:
        _WARNED_LEGACY_SESSIONS_SCHEMA = True
        logger.warning(
            "sessions.user_id unavailable (%s) — supabase/migrations/20261007_sessions_user_id.sql "
            "likely not applied; using legacy columns so sessions still persist (ownership checks "
            "disabled). Run the migration to restore ownership.",
            detail,
        )


def _is_missing_user_id_error(exc: Exception) -> bool:
    """True when a DB error names the user_id column (pre-migration schema)."""
    return "user_id" in str(exc)


def get_session(session_id: str) -> dict | None:
    """Return the raw sessions row, or None when missing/unreachable.

    Best-effort: None on DB errors (offline/test) so callers fail open like
    the pre-ownership code. Ownership is enforced whenever the DB answers.
    On a pre-migration schema (no user_id column) falls back to legacy
    columns with user_id None (legacy/quarantined semantics).
    """
    try:
        rows = (get_supabase().table("sessions").select("session_id,user_id,state")
                .eq("session_id", session_id).limit(1).execute().data or [])
    except Exception as e:
        if _is_missing_user_id_error(e):
            _warn_legacy_sessions_schema_once(str(e)[:200])
            try:
                rows = (get_supabase().table("sessions").select("session_id,state")
                        .eq("session_id", session_id).limit(1).execute().data or [])
            except Exception:
                return None
            if not rows:
                return None
            row = rows[0]
            row.setdefault("user_id", None)
            return row
        return None
    if not rows:
        return None
    return rows[0]


def is_session_owner(session_id: str, user_id: str) -> bool:
    """True only when the sessions row exists and is owned by user_id.

    Missing, legacy (user_id NULL), foreign, and DB-error cases all return
    False — callers collapse them to the missing-session behavior so no
    existence oracle is created. Never trust a client-supplied user_id;
    callers must pass the authenticated Clerk sub.
    """
    row = get_session(session_id)
    if not row:
        return False
    return row.get("user_id") == user_id


def _owns_session(session_id: str, user_id: str | None) -> bool:
    """Owner check used by reads/writes. user_id=None preserves the legacy
    offline/test path (no check)."""
    if user_id is None:
        return True
    return is_session_owner(session_id, user_id)


def get_state(session_id: str, user_id: str | None = None) -> str | None:
    """Session is authoritative for jurisdiction (spec §2.3, P1-7): a request
    with state=null continues in the session's previously selected state.

    When user_id (authenticated Clerk sub) is given, foreign/legacy/missing
    sessions collapse to None — the same observable as a fresh session.
    """
    if user_id is not None and not _owns_session(session_id, user_id):
        return None
    try:
        rows = (get_supabase().table("sessions").select("state")
                .eq("session_id", session_id).limit(1).execute().data or [])
    except Exception:
        return None
    if not rows:
        return None
    return (rows[0].get("state") or {}).get("selected_state")


def touch_session(session_id: str, selected_state: str | None, language: str,
                  user_id: str | None = None) -> None:
    sb = get_supabase()
    try:
        sb.rpc("purge_expired_sessions", {}).execute()
    except Exception:
        pass
    expires = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    if user_id is not None:
        # Ownership gate: missing → claim for the caller; foreign/legacy →
        # no-op (never overwrite another owner, never guess legacy).
        # DB errors fail open (get_session returns None → claim path) so
        # offline/test behavior is unchanged.
        row = get_session(session_id)
        if row is not None and row.get("user_id") != user_id:
            return
        try:
            sb.table("sessions").upsert({
                "session_id": session_id,
                "user_id": user_id,
                "state": {"selected_state": selected_state, "language": language},
                "expires_at": expires,
            }, on_conflict="session_id").execute()
        except Exception as e:
            if _is_missing_user_id_error(e):
                _warn_legacy_sessions_schema_once(str(e)[:200])
                try:
                    sb.table("sessions").upsert({
                        "session_id": session_id,
                        "state": {"selected_state": selected_state, "language": language},
                        "expires_at": expires,
                    }, on_conflict="session_id").execute()
                except Exception:
                    pass  # Missing table — silently skip
            # else: missing table etc. — silently skip (legacy fail-open)
        return
    try:
        sb.table("sessions").upsert({
            "session_id": session_id,
            "state": {"selected_state": selected_state, "language": language},
            "expires_at": expires,
        }, on_conflict="session_id").execute()
    except Exception:
        pass  # Non-UUID session IDs or missing table — silently skip


def save_message(session_id: str, role: str, content: str,
                 user_id: str | None = None) -> None:
    """Insert a message into the messages table.

    Messages inherit ownership through the session relationship (no owner
    column on messages). When user_id is given, writes to foreign/legacy
    sessions are dropped; writes to missing sessions are allowed (first
    use — touch_session claims the session row separately).
    """
    if user_id is not None:
        row = get_session(session_id)
        if row is not None and row.get("user_id") != user_id:
            return
    try:
        get_supabase().table("messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
        }).execute()
    except Exception:
        pass  # Non-UUID session IDs or missing table — silently skip


def get_history(session_id: str, limit: int = 8,
                user_id: str | None = None) -> list[dict]:
    """Retrieve the last N messages for a session, oldest first.

    When user_id is given, foreign/legacy/missing sessions return [] —
    identical to a fresh session, so no existence oracle is created.
    """
    if user_id is not None and not _owns_session(session_id, user_id):
        return []
    try:
        resp = (
            get_supabase().table("messages")
            .select("role", "content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        rows.reverse()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception:
        return []


def trim_messages(session_id: str, keep: int = 50,
                  user_id: str | None = None) -> None:
    """Delete messages beyond the most recent `keep` for a session."""
    if user_id is not None and not _owns_session(session_id, user_id):
        return
    try:
        resp = (
            get_supabase().table("messages")
            .select("id")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .range(keep, 10000)
            .execute()
        )
        ids = [r["id"] for r in (resp.data or [])]
        if ids:
            get_supabase().table("messages").delete().in_("id", ids).execute()
    except Exception:
        pass
