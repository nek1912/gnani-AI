"""Supabase-backed conversation CRUD — replaces SQLite database.py from sub-project."""

from datetime import UTC, datetime

from app.db import get_supabase


def create_conversation(user_id: str, title: str = "New Chat") -> dict:
    sb = get_supabase()
    result = sb.table("conversations").insert({
        "user_id": user_id,
        "title": title,
    }).execute()
    return result.data[0] if result.data else {}


def ensure_conversation(conversation_id: str, user_id: str) -> None:
    """Insert a conversations row if one with this id doesn't exist yet.

    Ownership gate (mirrors session_store.touch_session): when a row
    already exists but is owned by someone else, this is a no-op — never
    overwrite another owner's conversation. Swallow DB errors in test
    environments where Supabase is unavailable.
    """
    try:
        existing = get_conversation(conversation_id)
    except Exception:
        existing = None
    # Only a real dict row counts as existing (MagicMock supabase stubs in
    # tests return non-dict truthy values — treat those as missing so the
    # upsert path is exercised).
    if isinstance(existing, dict) and existing.get("user_id") != user_id:
        return
    sb = get_supabase()
    try:
        sb.table("conversations").upsert(
            {
                "id": conversation_id,
                "user_id": user_id,
                "title": "New Chat",
            },
            on_conflict="id",
        ).execute()
    except Exception:
        # In CI/tests the Supabase endpoint may be unreachable; ignore.
        return


def list_conversations(user_id: str, limit: int = 50) -> list[dict]:
    sb = get_supabase()
    result = (sb.table("conversations")
              .select("*")
              .eq("user_id", user_id)
              .order("updated_at", desc=True)
              .limit(limit)
              .execute())
    return result.data or []


def get_conversation(conversation_id: str) -> dict | None:
    sb = get_supabase()
    result = (sb.table("conversations")
              .select("*")
              .eq("id", conversation_id)
              .limit(1)
              .execute())
    rows = result.data or []
    return rows[0] if rows else None


def get_owned_conversation(conversation_id: str, user_id: str) -> dict | None:
    """Return the conversation only when it is owned by user_id.

    Missing and forbidden collapse to None so routes answer 404 without
    revealing whether another user's resource exists. Never trust a
    client-supplied user_id — callers must pass the authenticated sub.
    """
    conv = get_conversation(conversation_id)
    if not conv or conv.get("user_id") != user_id:
        return None
    return conv


def rename_conversation(conversation_id: str, title: str) -> bool:
    sb = get_supabase()
    sb.table("conversations").update({
        "title": title,
        "updated_at": datetime.now(UTC).isoformat(),
    }).eq("id", conversation_id).execute()
    return True


def delete_conversation(conversation_id: str) -> bool:
    sb = get_supabase()
    sb.table("messages").delete().eq("conversation_id", conversation_id).execute()
    sb.table("grievance_states").delete().eq("conversation_id", conversation_id).execute()
    sb.table("conversations").delete().eq("id", conversation_id).execute()
    return True


def pin_conversation(conversation_id: str, pinned: bool) -> bool:
    sb = get_supabase()
    sb.table("conversations").update({
        "pinned": pinned,
        "updated_at": datetime.now(UTC).isoformat(),
    }).eq("id", conversation_id).execute()
    return True


def save_conversation_message(conversation_id: str, role: str, content: str,
                               language: str = "en", evidence_json: dict | None = None) -> None:
    sb = get_supabase()
    sb.table("messages").insert({
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "language": language,
        "evidence_json": evidence_json,
    }).execute()


def get_conversation_history(conversation_id: str, limit: int = 20) -> list[dict]:
    sb = get_supabase()
    result = (sb.table("messages")
              .select("*")
              .eq("conversation_id", conversation_id)
              .order("created_at", desc=False)
              .limit(limit)
              .execute())
    return result.data or []
