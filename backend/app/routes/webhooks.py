"""Clerk webhook handler — syncs user data to Supabase."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ClerkUser(BaseModel):
    id: str
    email_addresses: list[dict] = []
    first_name: str | None = None
    last_name: str | None = None


def _verify_svix_signature(payload: bytes, headers: dict, secret: str) -> bool:
    """Verify Svix webhook signature."""
    try:
        import svix
        wh = svix.Webhook(secret)
        wh.verify(payload, headers)
        return True
    except Exception:
        logger.warning("Svix signature verification failed")
        return False


def _get_email(user: dict) -> str:
    """Extract primary email from Clerk user object."""
    for addr in user.get("email_addresses", []):
        if addr.get("id") == user.get("primary_email_address_id"):
            return addr.get("email_address", "")
    if user.get("email_addresses"):
        return user["email_addresses"][0].get("email_address", "")
    return ""


async def _upsert_user(user: dict) -> None:
    """Upsert user to Supabase users table."""
    import httpx

    s = get_settings()
    user_data = {
        "id": user["id"],
        "email": _get_email(user),
        "full_name": " ".join(
            filter(None, [user.get("first_name"), user.get("last_name")])
        ),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{s.supabase_url}/rest/v1/users",
            json=user_data,
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("Failed to upsert user: %s %s", resp.status_code, resp.text)
            raise HTTPException(status_code=500, detail="Failed to upsert user")


async def _delete_user(user_id: str) -> None:
    """Delete user from Supabase users table."""
    import httpx

    s = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{s.supabase_url}/rest/v1/users?id=eq.{user_id}",
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("Failed to delete user: %s %s", resp.status_code, resp.text)
            raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/clerk")
async def clerk_webhook(request: Request):
    """Handle Clerk webhook events."""
    s = get_settings()
    body = await request.body()
    headers = dict(request.headers)

    # Verify signature if webhook secret is configured
    if s.clerk_webhook_secret:
        if not _verify_svix_signature(body, headers, s.clerk_webhook_secret):
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    event_type = payload.get("type", "")
    data = payload.get("data", {})

    logger.info("Clerk webhook: type=%s", event_type)

    if event_type == "user.created":
        await _upsert_user(data)
    elif event_type == "user.updated":
        await _upsert_user(data)
    elif event_type == "user.deleted":
        user_id = data.get("id")
        if user_id:
            await _delete_user(user_id)

    return {"status": "ok"}
