"""Conversation CRUD endpoints — Supabase-backed, Clerk-authenticated.

Ownership model: a conversation row's `user_id` must equal the
authenticated Clerk `sub`. Client-supplied user ids are never trusted.
Missing and forbidden both answer 404 so one user's resource existence
is never revealed to another.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import conversation_store
from app.auth import require_auth

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    # Legacy clients send a locally generated id here; it is ignored —
    # the row owner is always the authenticated Clerk sub.
    user_id: str | None = None
    title: str = "New Chat"


class ConversationTitleRequest(BaseModel):
    user_id: str | None = None
    title: str


class ConversationPinRequest(BaseModel):
    user_id: str | None = None
    pinned: bool


@router.post("")
def create_conversation(
    req: CreateConversationRequest,
    user_id: str = Depends(require_auth),
) -> dict:
    conv = conversation_store.create_conversation(user_id, req.title)
    return {"status": "ok", "conversation": conv}


@router.get("")
def list_conversations(user_id: str = Depends(require_auth)) -> dict:
    convs = conversation_store.list_conversations(user_id)
    return {"status": "ok", "conversations": convs}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user_id: str = Depends(require_auth),
) -> dict:
    conv = conversation_store.get_owned_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    history = conversation_store.get_conversation_history(conversation_id)
    return {"status": "ok", "conversation": conv, "messages": history}


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    req: ConversationTitleRequest,
    user_id: str = Depends(require_auth),
) -> dict:
    if not conversation_store.get_owned_conversation(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_store.rename_conversation(conversation_id, req.title)
    return {"status": "ok"}


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(require_auth),
) -> dict:
    if not conversation_store.get_owned_conversation(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_store.delete_conversation(conversation_id)
    return {"status": "ok"}


@router.post("/{conversation_id}/pin")
def pin_conversation(
    conversation_id: str,
    req: ConversationPinRequest,
    user_id: str = Depends(require_auth),
) -> dict:
    if not conversation_store.get_owned_conversation(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_store.pin_conversation(conversation_id, req.pinned)
    return {"status": "ok"}
