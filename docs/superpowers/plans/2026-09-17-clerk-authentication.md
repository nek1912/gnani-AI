# Clerk Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Clerk authentication with Google OAuth and email login, protecting `/chat` and `/grievance` routes, with backend JWT verification and Supabase user sync.

**Architecture:** Clerk Next.js SDK on frontend (middleware for route protection, pre-built `<SignIn/>`/`<SignUp/>` components, `<UserButton/>` in TopNav). Backend verifies Clerk session JWTs via JWKS. Clerk webhooks sync user data to Supabase `users` table.

**Tech Stack:** `@clerk/nextjs`, `python-jose[cryptography]`, `svix`, Supabase Postgres

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/src/middleware.ts` | Clerk route protection middleware |
| Create | `frontend/src/app/sign-in/[[...sign-in]]/page.tsx` | Sign-in page |
| Create | `frontend/src/app/sign-up/[[...sign-up]]/page.tsx` | Sign-up page |
| Create | `backend/app/auth.py` | JWT verification + `require_auth` dependency |
| Create | `backend/app/routes/webhooks.py` | Clerk webhook handler |
| Modify | `frontend/src/app/layout.tsx` | Wrap with `ClerkProvider` |
| Modify | `frontend/src/components/layout/TopNav.tsx` | Add `UserButton` / Sign In link |
| Modify | `frontend/.env` | Add Clerk env vars |
| Modify | `frontend/.env.example` | Document Clerk env vars |
| Modify | `frontend/next.config.ts` | Add Clerk `images.remotePatterns` for avatar |
| Modify | `backend/app/config.py` | Add Clerk settings |
| Modify | `backend/app/main.py` | Register webhooks router |
| Modify | `backend/schema.sql` | Add `users` table |
| Modify | `frontend/src/lib/i18n/dictionaries.ts` | Add auth i18n keys (11 languages) |
| Modify | `frontend/src/components/layout/ConditionalNavs.tsx` | Hide nav on sign-in/sign-up pages |

---

## Task 1: Backend — JWT Verification Module

**Files:**
- Create: `backend/app/auth.py`
- Modify: `backend/app/config.py:1-131` (add 3 settings)

**Interfaces:**
- Produces: `require_auth(request: Request) -> str` (FastAPI dependency, returns `user_id`)
- Produces: `verify_clerk_token(request: Request) -> str | None` (returns `user_id` or `None`)

- [ ] **Step 1: Add Clerk settings to config**

In `backend/app/config.py`, add these fields to the `Settings` class (after `grievance_gemini_model`):

```python
    # Clerk authentication
    clerk_secret_key: str = ""
    clerk_webhook_secret: str = ""
    clerk_issuer: str = ""  # e.g. "https://clerk.your-app.com"
```

- [ ] **Step 2: Install dependencies**

```bash
cd backend && pip install "python-jose[cryptography]>=3.3.0" "svix>=1.0.0"
```

- [ ] **Step 3: Create auth module**

Create `backend/app/auth.py`:

```python
"""Clerk JWT verification for FastAPI."""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx
from fastapi import Request, HTTPException
from jose import jwt, JWTError

from app.config import get_settings

logger = logging.getLogger(__name__)

_CLERK_JWKS_CACHE: dict = {}
_CLERK_JWKS_URL_CACHE: str = ""


def _get_jwks() -> dict:
    """Fetch and cache Clerk's JWKS keys."""
    global _CLERK_JWKS_CACHE, _CLERK_JWKS_URL_CACHE
    s = get_settings()
    if not s.clerk_issuer:
        return {}
    url = f"{s.clerk_issuer}/.well-known/jwks.json"
    if url == _CLERK_JWKS_URL_CACHE and _CLERK_JWKS_CACHE:
        return _CLERK_JWKS_CACHE
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        _CLERK_JWKS_CACHE = resp.json()
        _CLERK_JWKS_URL_CACHE = url
        return _CLERK_JWKS_CACHE
    except Exception:
        logger.exception("Failed to fetch Clerk JWKS")
        return _CLERK_JWKS_CACHE


def verify_clerk_token(request: Request) -> str | None:
    """Extract and verify Clerk session JWT. Returns user_id or None."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    s = get_settings()
    if not s.clerk_issuer or not s.clerk_secret_key:
        return None
    try:
        jwks = _get_jwks()
        if not jwks:
            return None
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            issuer=s.clerk_issuer,
        )
        return payload.get("sub")
    except JWTError:
        return None


async def require_auth(request: Request) -> str:
    """FastAPI dependency — returns user_id or raises 401."""
    user_id = verify_clerk_token(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/auth.py backend/app/config.py
git commit -m "feat: add Clerk JWT verification module"
```

---

## Task 2: Backend — Webhook Handler

**Files:**
- Create: `backend/app/routes/webhooks.py`
- Modify: `backend/app/main.py:31-37` (register router)

**Interfaces:**
- Consumes: Clerk webhook events (`user.created`, `user.updated`, `user.deleted`)
- Produces: Upserts to Supabase `users` table

- [ ] **Step 1: Create webhook route**

Create `backend/app/routes/webhooks.py`:

```python
"""Clerk webhook handler — syncs user data to Supabase."""

from __future__ import annotations

import hashlib
import hmac
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
    from app.config import get_settings
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


async def _delete_user(user_id: str) -> None:
    """Delete user from Supabase users table."""
    from app.config import get_settings
    import httpx

    s = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{s.supabase_url}/rest/v1/users?id=eq.{user_id}",
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}",
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("Failed to delete user: %s %s", resp.status_code, resp.text)


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

    import json
    payload = json.loads(body)
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
```

- [ ] **Step 2: Register webhook router in main.py**

In `backend/app/main.py`, add import and registration:

```python
from app.routes.webhooks import router as webhooks_router
```

After the last `app.include_router(...)` line, add:

```python
app.include_router(webhooks_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/webhooks.py backend/app/main.py
git commit -m "feat: add Clerk webhook handler for user sync"
```

---

## Task 3: Backend — Add Users Table to Schema

**Files:**
- Modify: `backend/schema.sql` (add `users` table)

- [ ] **Step 1: Add users table to schema.sql**

Append to `backend/schema.sql`:

```sql
-- 8. Users table (Clerk sync)
create table if not exists users (
  id            text primary key,
  email         text,
  full_name     text,
  preferred_language text default 'en',
  state         text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- Auto-update updated_at on users
create or replace function update_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists users_updated_at on users;
create trigger users_updated_at
  before update on users
  for each row
  execute function update_updated_at();
```

- [ ] **Step 2: Run schema in Supabase SQL Editor**

Go to Supabase Dashboard → SQL Editor → paste the new SQL → Run.

- [ ] **Step 3: Commit**

```bash
git add backend/schema.sql
git commit -m "feat: add users table for Clerk sync"
```

---

## Task 4: Backend — Add Auth to Protected Routes

**Files:**
- Modify: `backend/app/routes/chat.py` (add `require_auth` dependency)
- Modify: `backend/app/routes/grievance.py` (add `require_auth` dependency)
- Modify: `backend/app/routes/voice.py` (add `require_auth` dependency)

**Interfaces:**
- Consumes: `require_auth` from `app.auth`

- [ ] **Step 1: Add auth to chat route**

In `backend/app/routes/chat.py`, add import at top:

```python
from app.auth import require_auth
```

Find the `/chat` endpoint function signature and add the dependency. The exact line varies — look for `@router.post("/chat")` and its handler:

```python
@router.post("/chat")
async def chat(request: Request, user_id: str = Depends(require_auth)):
```

For `/chat/stream`:

```python
@router.post("/chat/stream")
async def chat_stream(request: Request, user_id: str = Depends(require_auth)):
```

- [ ] **Step 2: Add auth to grievance route**

In `backend/app/routes/grievance.py`, add import:

```python
from fastapi import APIRouter, HTTPException, Depends, Request
from app.auth import require_auth
```

Add `user_id: str = Depends(require_auth)` to each grievance endpoint handler:
- `/grievances/fields`
- `/grievances/answer`
- `/grievances/clarify`
- `/grievances/finalize`

- [ ] **Step 3: Add auth to voice route**

In `backend/app/routes/voice.py`, add import and dependency to `/voice` endpoint:

```python
from app.auth import require_auth

@router.post("/voice")
async def voice(request: Request, user_id: str = Depends(require_auth)):
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/chat.py backend/app/routes/grievance.py backend/app/routes/voice.py
git commit -m "feat: add auth dependency to protected routes"
```

---

## Task 5: Frontend — Install Clerk SDK and Configure

**Files:**
- Modify: `frontend/.env` (add Clerk keys)
- Modify: `frontend/.env.example` (document keys)
- Modify: `frontend/next.config.ts` (avatar images)

- [ ] **Step 1: Install Clerk**

```bash
cd frontend && npm install @clerk/nextjs
```

- [ ] **Step 2: Add env vars to frontend/.env**

Append to `frontend/.env`:

```env
# Clerk Authentication
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_YOUR_KEY_HERE
CLERK_SECRET_KEY=sk_test_YOUR_KEY_HERE
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
```

- [ ] **Step 3: Update frontend/.env.example**

Append:

```env
# Clerk Authentication (https://dashboard.clerk.com)
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_publishable_key
CLERK_SECRET_KEY=sk_test_your_secret_key
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
```

- [ ] **Step 4: Update next.config.ts for Clerk avatar images**

In `frontend/next.config.ts`:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "img.clerk.com",
      },
    ],
  },
};

export default nextConfig;
```

- [ ] **Step 5: Commit**

```bash
git add frontend/.env frontend/.env.example frontend/next.config.ts frontend/package.json frontend/package-lock.json
git commit -m "feat: install @clerk/nextjs and configure env"
```

---

## Task 6: Frontend — ClerkProvider in Root Layout

**Files:**
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Wrap layout with ClerkProvider**

In `frontend/src/app/layout.tsx`, add import:

```tsx
import { ClerkProvider } from "@clerk/nextjs";
```

Wrap the return content. The current structure is:

```tsx
<html ...>
  <body ...>
    <a ...>Skip to content</a>
    <LanguageProvider>
      <ConditionalNavs>{children}</ConditionalNavs>
    </LanguageProvider>
  </body>
</html>
```

Change to:

```tsx
<ClerkProvider>
  <html ...>
    <body ...>
      <a ...>Skip to content</a>
      <LanguageProvider>
        <ConditionalNavs>{children}</ConditionalNavs>
      </LanguageProvider>
    </body>
  </html>
</ClerkProvider>
```

Note: `ClerkProvider` must be the outermost wrapper (outside `<html>`) per Clerk docs.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/layout.tsx
git commit -m "feat: wrap root layout with ClerkProvider"
```

---

## Task 7: Frontend — Middleware for Route Protection

**Files:**
- Create: `frontend/src/middleware.ts`

- [ ] **Step 1: Create middleware**

Create `frontend/src/middleware.ts`:

```ts
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isPublicRoute = createRouteMatcher([
  "/",
  "/schemes(.*)",
  "/services(.*)",
  "/legal(.*)",
  "/faq(.*)",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/api(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublicRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
```

This protects `/chat` and `/grievance` (and any future routes not in the public list). Sign-in/sign-up pages are public so users can reach them.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/middleware.ts
git commit -m "feat: add Clerk middleware for route protection"
```

---

## Task 8: Frontend — Sign-in and Sign-up Pages

**Files:**
- Create: `frontend/src/app/sign-in/[[...sign-in]]/page.tsx`
- Create: `frontend/src/app/sign-up/[[...sign-up]]/page.tsx`

- [ ] **Step 1: Create sign-in page**

```bash
mkdir -p "frontend/src/app/sign-in/[[...sign-in]]"
```

Create `frontend/src/app/sign-in/[[...sign-in]]/page.tsx`:

```tsx
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <SignIn routing="path" path="/sign-in" />
    </div>
  );
}
```

- [ ] **Step 2: Create sign-up page**

```bash
mkdir -p "frontend/src/app/sign-up/[[...sign-up]]"
```

Create `frontend/src/app/sign-up/[[...sign-up]]/page.tsx`:

```tsx
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <SignUp routing="path" path="/sign-up" />
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/sign-in" "frontend/src/app/sign-up"
git commit -m "feat: add Clerk sign-in and sign-up pages"
```

---

## Task 9: Frontend — TopNav User Button

**Files:**
- Modify: `frontend/src/components/layout/TopNav.tsx`

**Interfaces:**
- Consumes: `useAuth`, `UserButton` from `@clerk/nextjs`

- [ ] **Step 1: Add UserButton to TopNav**

In `frontend/src/components/layout/TopNav.tsx`, add imports:

```tsx
import { UserButton, useAuth } from "@clerk/nextjs";
```

Inside the `TopNav` component, after the existing hooks:

```tsx
const { isSignedIn } = useAuth();
```

Find the Right section (after `<LanguageSwitcher />`). Replace the static "Chat" CTA link with conditional rendering:

```tsx
<LanguageSwitcher />

{isSignedIn ? (
  <UserButton
    afterSignOutUrl="/"
    appearance={{
      elements: {
        avatarBox: "h-9 w-9",
      },
    }}
  />
) : (
  <>
    <Link
      href="/sign-in"
      className="hidden h-10 items-center justify-center rounded-full px-4 text-[14px] font-medium text-[var(--body)] transition-colors duration-150 hover:text-[var(--ink)] md:inline-flex"
    >
      {t("nav.signIn")}
    </Link>
    <Link
      href="/chat"
      className="hidden h-10 items-center justify-center rounded-full bg-[var(--primary)] px-5 text-[14px] font-semibold text-[var(--on-primary)] transition-colors duration-150 hover:bg-[#1a1a1a] md:inline-flex"
    >
      {t("nav.chat")}
    </Link>
  </>
)}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/layout/TopNav.tsx
git commit -m "feat: add UserButton to TopNav with sign-in fallback"
```

---

## Task 10: Frontend — i18n Keys for Auth

**Files:**
- Modify: `frontend/src/lib/i18n/dictionaries.ts`

- [ ] **Step 1: Add auth keys to all 11 language dictionaries**

In `frontend/src/lib/i18n/dictionaries.ts`, add these keys to each language's dictionary object. Add them right after the `nav.faq` / `nav.chat` keys:

**English (`en`):**
```ts
"nav.signIn": "Sign In",
"nav.signUp": "Sign Up",
"auth.signInTitle": "Sign in to JanSahay",
"auth.signUpTitle": "Create your account",
"auth.required": "Please sign in to continue",
"auth.error": "Authentication error. Please try again.",
```

**Hindi (`hi`):**
```ts
"nav.signIn": "साइन इन करें",
"nav.signUp": "साइन अप करें",
"auth.signInTitle": "JanSahay में साइन इन करें",
"auth.signUpTitle": "अपना खाता बनाएं",
"auth.required": "जारी रखने के लिए कृपया साइन इन करें",
"auth.error": "प्रमाणीकरण त्रुटि। कृपया पुनः प्रयास करें।",
```

**Gujarati (`gu`):**
```ts
"nav.signIn": "સાઇન ઇન કરો",
"nav.signUp": "સાઇન અપ કરો",
"auth.signInTitle": "JanSahay માં સાઇન ઇન કરો",
"auth.signUpTitle": "તમારું ખાતું બનાવો",
"auth.required": "ચાલુ રાખવા માટે કૃપા કરીને સાઇન ઇન કરો",
"auth.error": "પ્રમાણીકરણ ભૂલ. કૃપા કરીને ફરી પ્રયાસ કરો.",
```

**Marathi (`mr`):**
```ts
"nav.signIn": "साइन इन करा",
"nav.signUp": "साइन अप करा",
"auth.signInTitle": "JanSahay मध्ये साइन इन करा",
"auth.signUpTitle": "तुमचे खाते तयार करा",
"auth.required": "सुरू ठेवण्यासाठी कृपया साइन इन करा",
"auth.error": "प्रमाणीकरण त्रुटी. कृपया पुन्हा प्रयत्न करा.",
```

**Bengali (`bn`):**
```ts
"nav.signIn": "সাইন ইন করুন",
"nav.signUp": "সাইন আপ করুন",
"auth.signInTitle": "JanSahay-এ সাইন ইন করুন",
"auth.signUpTitle": "আপনার অ্যাকাউন্ট তৈরি করুন",
"auth.required": "চালিয়ে যেতে সাইন ইন করুন",
"auth.error": "প্রমাণীকরণ ত্রুটি। আবার চেষ্টা করুন।",
```

**Tamil (`ta`):**
```ts
"nav.signIn": "உள்நுழைக",
"nav.signUp": "பதிவு செய்",
"auth.signInTitle": "JanSahay-இல் உள்நுழைக",
"auth.signUpTitle": "உங்கள் கணக்கை உருவாக்கு",
"auth.required": "தொடர உள்நுழையவும்",
"auth.error": "அங்கீகார பிழை. மீண்டும் முயற்சிக்கவும்.",
```

**Telugu (`te`):**
```ts
"nav.signIn": "సైన్ ఇన్ చేయండి",
"nav.signUp": "సైన్ అప్ చేయండి",
"auth.signInTitle": "JanSahayలో సైన్ ఇన్ చేయండి",
"auth.signUpTitle": "మీ ఖాతాను సృష్టించండి",
"auth.required": "కొనసాగించడానికి సైన్ ఇన్ చేయండి",
"auth.error": "ధృవీకరణ లోపం. దయచేసి మళ్ళీ ప్రయత్నించండి.",
```

**Kannada (`kn`):**
```ts
"nav.signIn": "ಸೈನ್ ಇನ್ ಮಾಡಿ",
"nav.signUp": "ಸೈನ್ ಅಪ್ ಮಾಡಿ",
"auth.signInTitle": "JanSahay ನಲ್ಲಿ ಸೈನ್ ಇನ್ ಮಾಡಿ",
"auth.signUpTitle": "ನಿಮ್ಮ ಖಾತೆಯನ್ನು ರಚಿಸಿ",
"auth.required": "ಮುಂದುವರಿಯಲು ಸೈನ್ ಇನ್ ಮಾಡಿ",
"auth.error": "ದೃಢೀಕರಣ ದೋಷ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
```

**Punjabi (`pa`):**
```ts
"nav.signIn": "ਸਾਇਨ ਇਨ ਕਰੋ",
"nav.signUp": "ਸਾਇਨ ਅੱਪ ਕਰੋ",
"auth.signInTitle": "JanSahay ਵਿੱਚ ਸਾਇਨ ਇਨ ਕਰੋ",
"auth.signUpTitle": "ਆਪਣਾ ਖਾਤਾ ਬਣਾਓ",
"auth.required": "ਜਾਰੀ ਰੱਖਣ ਲਈ ਕਿਰਪਾ ਕਰਕੇ ਸਾਇਨ ਇਨ ਕਰੋ",
"auth.error": "ਪ੍ਰਮਾਣੀਕਰਨ ਗਲਤੀ. ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ.",
```

**Odia (`or`):**
```ts
"nav.signIn": "ସାଇନ୍ ଇନ୍ କରନ୍ତୁ",
"nav.signUp": "ସାଇନ୍ ଅପ୍ କରନ୍ତୁ",
"auth.signInTitle": "JanSahay ରେ ସାଇନ୍ ଇନ୍ କରନ୍ତୁ",
"auth.signUpTitle": "ଆପଣଙ୍କ ଆକାଉଣ୍ଟ ସୃଷ୍ଟି କରନ୍ତୁ",
"auth.required": "ଜାରି ରଖିବାକୁ ଦୟାକରି ସାଇନ୍ ଇନ୍ କରନ୍ତୁ",
"auth.error": "ପ୍ରମାଣୀକରଣ ତ୍ରୁଟି. ଦୟାକରି ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ.",
```

**Malayalam (`ml`):**
```ts
"nav.signIn": "സൈൻ ഇൻ ചെയ്യുക",
"nav.signUp": "സൈൻ അപ്പ് ചെയ്യുക",
"auth.signInTitle": "JanSahay-യിൽ സൈൻ ഇൻ ചെയ്യുക",
"auth.signUpTitle": "നിങ്ങളുടെ അക്കൗണ്ട് സൃഷ്ടിക്കുക",
"auth.required": "തുടരാൻ സൈൻ ഇൻ ചെയ്യുക",
"auth.error": "സാക്ഷ്യപ്പെടുത്തൽ പിശക്. വീണ്ടും ശ്രമിക്കുക.",
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/i18n/dictionaries.ts
git commit -m "feat: add auth i18n keys for 11 languages"
```

---

## Task 11: Frontend — Hide Nav on Auth Pages

**Files:**
- Modify: `frontend/src/components/layout/ConditionalNavs.tsx`

- [ ] **Step 1: Hide nav/footer on sign-in/sign-up pages**

In `frontend/src/components/layout/ConditionalNavs.tsx`, update the condition:

```tsx
const isChat = pathname.startsWith("/chat");
const isAuth = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");
const hideNav = isChat || isAuth;
```

Then replace `!isChat` with `!hideNav`:

```tsx
return (
  <>
    {!hideNav && <TopNav />}
    <main id="content">{children}</main>
    {!hideNav && <Footer />}
    {!hideNav && <FloatingChatWidget />}
  </>
);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/layout/ConditionalNavs.tsx
git commit -m "feat: hide nav on sign-in/sign-up pages"
```

---

## Task 12: End-to-End Verification

- [ ] **Step 1: Create Clerk account and get keys**

1. Go to https://dashboard.clerk.com
2. Create new application
3. Enable Google and Email providers
4. Copy Publishable Key and Secret Key
5. Copy Webhook Signing Secret (from Webhooks settings)
6. Set webhook endpoint URL to `https://your-backend.onrender.com/webhooks/clerk`
7. Subscribe to `user.created`, `user.updated`, `user.deleted` events

- [ ] **Step 2: Set environment variables**

Frontend `.env`:
```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
```

Backend `.env`:
```
CLERK_SECRET_KEY=sk_test_...
CLERK_WEBHOOK_SECRET=whsec_...
CLERK_ISSUER=https://clerk.your-app.com
```

- [ ] **Step 3: Run frontend dev server**

```bash
cd frontend && npm run dev
```

Test:
- Visit `http://localhost:3000` → should load homepage (public)
- Visit `http://localhost:3000/chat` → should redirect to `/sign-in`
- Sign in with Google → should redirect to `/`
- TopNav should show avatar (UserButton)
- Visit `/chat` → should load (authenticated)
- Sign out → TopNav shows "Sign In" link
- Visit `/chat` → redirects to `/sign-in`

- [ ] **Step 4: Run backend server**

```bash
cd backend && uvicorn app.main:app --reload
```

Test:
- `curl http://localhost:8000/health` → 200 (public)
- `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"question":"test"}'` → 401 (no auth)
- With valid Clerk JWT in Authorization header → 200

- [ ] **Step 5: Test webhook**

Trigger a test webhook from Clerk dashboard → verify user appears in Supabase `users` table.

- [ ] **Step 6: Run lint and typecheck**

```bash
cd frontend && npm run lint && npx tsc --noEmit
```

- [ ] **Step 7: Commit final state**

```bash
git add -A
git commit -m "feat: complete Clerk authentication integration"
```
