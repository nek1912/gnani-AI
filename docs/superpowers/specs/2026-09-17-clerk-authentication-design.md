# Design Spec: Clerk Authentication Integration

**Date:** 2026-09-17
**Status:** Approved
**Approach:** Clerk Next.js SDK + Backend JWT Verification

---

## Summary

Integrate Clerk authentication into the JanSahay project with Google OAuth and email-based login. Protect `/chat` and `/grievance` routes. Verify Clerk session tokens in the FastAPI backend. Sync user data to Supabase via webhooks.

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Protected routes | `/chat` + `/grievance` | Core interactive features; schemes/services/legal/FAQ stay public |
| Auth UI | Clerk pre-built `<SignIn/>` / `<SignUp/>` | Fast to ship, handles OAuth flows, MFA, rate limiting |
| Backend auth | JWT verification via Clerk JWKS | No Clerk Python SDK needed; `python-jose` handles RS256 |
| User data | Local Supabase `users` table | Enables state/language filtering without extra Clerk API calls |
| SDK | `@clerk/nextjs` | Official SDK, middleware support, `auth()` helper |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Frontend (Next.js 16)                          │
│                                                 │
│  ClerkProvider (wraps root layout)              │
│       │                                         │
│       ├── middleware.ts → protects /chat, /grievance
│       │                                         │
│       ├── /sign-in/[[...sign-in]] → <SignIn/>   │
│       ├── /sign-up/[[...sign-up]] → <SignUp/>   │
│       │                                         │
│       ├── TopNav → <UserButton/> (avatar menu)  │
│       │                                         │
│       └── API calls → Authorization: Bearer JWT │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  Backend (FastAPI)                              │
│                                                 │
│  /webhooks/clerk → user sync to Supabase        │
│  Protected routes verify JWT via Clerk JWKS     │
│  /chat, /voice, /grievance → X-User-Id header   │
└─────────────────────────────────────────────────┘
```

---

## Frontend Changes

### 1. Root Layout (`frontend/src/app/layout.tsx`)

Wrap existing `<LanguageProvider>` with `<ClerkProvider>`:

```tsx
import { ClerkProvider } from "@clerk/nextjs";

export default function RootLayout({ children }) {
  return (
    <ClerkProvider>
      <html>
        <body>
          <LanguageProvider>
            <ConditionalNavs>{children}</ConditionalNavs>
          </LanguageProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
```

### 2. Middleware (`frontend/src/middleware.ts`) — NEW FILE

```ts
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher(["/chat(.*)", "/grievance(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
```

### 3. Sign-in Page (`frontend/src/app/sign-in/[[...sign-in]]/page.tsx`) — NEW FILE

```tsx
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)]">
      <SignIn routing="path" path="/sign-in" />
    </div>
  );
}
```

### 4. Sign-up Page (`frontend/src/app/sign-up/[[...sign-up]]/page.tsx`) — NEW FILE

```tsx
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)]">
      <SignUp routing="path" path="/sign-up" />
    </div>
  );
}
```

### 5. TopNav Updates (`frontend/src/components/layout/TopNav.tsx`)

Add `UserButton` from Clerk after the language switcher. When signed out, show "Sign In" link:

```tsx
import { UserButton, useAuth } from "@clerk/nextjs";

// Inside component:
const { isSignedIn } = useAuth();

// In the Right section, after <LanguageSwitcher />:
{isSignedIn ? (
  <UserButton afterSignOutUrl="/" />
) : (
  <Link href="/sign-in" className="...">
    {t("nav.signIn")}
  </Link>
)}
```

### 6. Environment Variables (`frontend/.env`)

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
```

### 7. Package Dependencies

```bash
npm install @clerk/nextjs
```

---

## Backend Changes

### 1. JWT Verification (`backend/app/auth.py`) — NEW FILE

```python
import httpx
from functools import lru_cache
from jose import jwt, JWTError
from fastapi import Request, HTTPException

CLERK_ISSUER = "https://clerk.your-app.com"
CLERK_JWKS_URL = f"{CLERK_ISSUER}/.well-known/jwks.json"

@lru_cache
def get_jwks() -> dict:
    resp = httpx.get(CLERK_JWKS_URL, timeout=10)
    return resp.json()

def verify_clerk_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        jwks = get_jwks()
        payload = jwt.decode(token, jwks, algorithms=["RS256"], issuer=CLERK_ISSUER)
        return payload.get("sub")
    except JWTError:
        return None

async def require_auth(request: Request) -> str:
    user_id = verify_clerk_token(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id
```

### 2. Webhook Handler (`backend/app/routes/webhooks.py`) — NEW FILE

Handles Clerk webhook events (`user.created`, `user.updated`, `user.deleted`) and upserts to Supabase `users` table. Verifies Svix signature for security.

### 3. Users Table (`backend/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT,
    full_name TEXT,
    preferred_language TEXT DEFAULT 'en',
    state TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 4. Protected Routes

Add `require_auth` dependency to:
- `backend/app/routes/chat.py` — `/chat` and `/chat/stream`
- `backend/app/routes/grievance.py` — `/grievance` and `/grievances/*`
- `backend/app/routes/voice.py` — `/voice`

Non-protected routes remain open: `/health`, `/health/providers`, `/evidence/*`, `/documents/*`, `/conversations/*`.

### 5. Environment Variables (`backend/.env`)

```env
CLERK_SECRET_KEY=sk_test_...
CLERK_WEBHOOK_SECRET=whsec_...
CLERK_ISSUER=https://clerk.your-app.com
```

### 6. Dependencies

```
python-jose[cryptography]>=3.3.0
svix>=1.0.0
```

---

## Data Flow

### Sign-in Flow
1. User clicks "Sign In" → redirected to `/sign-in`
2. Clerk handles Google OAuth / email+password / email OTP
3. On success → redirected to `/`
4. `ClerkProvider` sets session → `useAuth()` returns user
5. TopNav shows `<UserButton/>` with avatar

### Protected API Call Flow
1. Frontend gets Clerk session JWT via `getToken()`
2. Passes as `Authorization: Bearer <jwt>` header
3. FastAPI `require_auth` verifies JWT via Clerk JWKS
4. Returns `user_id` → route handler uses it

### Webhook Flow
1. Clerk sends `user.created` / `user.updated` / `user.deleted`
2. FastAPI `/webhooks/clerk` verifies Svix signature
3. Upserts to Supabase `users` table
4. Returns 200

---

## i18n Additions

New keys for all 11 languages:
- `nav.signIn` — "Sign In"
- `auth.signInTitle` — "Sign in to JanSahay"
- `auth.signUpTitle` — "Create your account"
- `auth.required` — "Please sign in to continue"
- `auth.error` — "Authentication error. Please try again."

---

## Error Handling

| Error | Handling |
|-------|----------|
| Missing/invalid JWT | 401 → frontend shows sign-in prompt |
| Webhook signature invalid | 400 → logged, not retried |
| Clerk outage | Middleware fails open (availability priority) |
| Network error on JWKS fetch | Cached key used; first request may fail |

---

## Testing

1. **Manual:** Sign in with Google, sign in with email, sign up, sign out
2. **Middleware:** Verify `/chat` redirects to `/sign-in` when unauthenticated
3. **Backend:** Verify 401 on protected routes without token
4. **Webhook:** Test user.created event creates Supabase row
5. **i18n:** Verify sign-in/sign-up pages render in all 11 languages
6. **TopNav:** Verify UserButton appears when signed in, Sign In link when signed out
