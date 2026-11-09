# Design: Migrate JanSahay Frontend from Next.js to React + Vite

- **Date:** 2026-10-05
- **Status:** Approved
- **Scope:** `frontend/` only. No changes to `backend/`, `corpus/`, `supabase/`, or `workflows/`.

---

## 1. Problem

The frontend is a Next.js 16.3.3 App Router application in `frontend/`. It is
already almost entirely client-rendered — 103 TypeScript files, of which every one
of the 13 non-Clerk pages and 38 components carry `"use client"`. There is no
`next/image`, no `getServerSideProps`, no `getStaticProps`, no `generateMetadata`,
and no `next/dynamic`. The framework is providing very little beyond two things:

1. File-based routing (15 pages).
2. **11 API Route Handlers that form a backend-for-frontend (BFF)** — these proxy
   every request to the Python FastAPI service and attach a Clerk bearer token.

Item 2 is load-bearing for authentication. Item 1 is a solved problem. The
migration is therefore mostly a packaging change, with one genuinely hard
sub-problem: **a Vite SPA has no server, so the BFF must be re-homed.**

### 1.1 Current state, verified

| Item | Finding |
|---|---|
| Framework | Next.js 16.3.3 (pinned), React 19.2.8, TypeScript `strict: true` |
| Language | TypeScript throughout; `@/*` path alias used by 94 files |
| Styling | Tailwind v4 CSS-first, no `tailwind.config.js`. Whole design system lives in `globals.css` (464 lines) as CSS custom properties |
| Routing | App Router. 15 pages, 11 route handlers, 1 root layout |
| Server logic | 9 of 11 handlers call Clerk `auth()` + `getToken()` and forward `Authorization: Bearer <token>` to FastAPI |
| Streaming | `/api/chat` and `/api/chat/stream` are byte-identical; both pipe SSE through to the browser |
| Tests | Vitest 4, 18 files / 78 tests. **Measured baseline on 2026-10-05: 12 tests failing across 5 files, 66 passing.** See §10.1 |
| Build | **Currently broken.** `SmoothScroll.tsx` and `ScrollStack.tsx` import `lenis`, which is absent from `package.json` and `package-lock.json`. Both files are unimported dead code |
| PWA | **Does not exist.** No manifest, no service worker, no offline caching — despite `README.md`, `CLAUDE.md`, `PRD.md` and `architecture.md` all claiming PWA support |
| Dark mode | Does not exist. `globals.css` hardcodes `color-scheme: light` |
| Languages | Code supports **11** locales (`en hi gu mr bn ta te kn pa or ml`), not the 6 the docs claim. `formatQuery.ts` covers only 6 |

### 1.2 Goals

1. Replace Next.js with React 19 + Vite 7 + React Router 7. No behavioural change.
2. Keep Clerk sign-in, sign-up and the user button fully working.
3. Keep all 15 pages, all 34 components, all i18n, all chat/grievance/voice flows working.
4. `npm run build`, `npm run lint`, `npm test` and `tsc --noEmit` all pass clean.
5. Leave `frontend/` untouched and runnable as a fallback until the new app is proven.

### 1.3 Non-goals

- **No PWA work.** Explicitly declined. Docs will be corrected to stop claiming it.
- **No dark mode.**
- **No backend changes.** Not one line of Python changes.
- **No TypeScript→JavaScript conversion.** Types stay.
- **No new features, no redesign, no visual changes.**

---

## 2. Target architecture

Approach **A** (chosen): one folder, two processes in development, one process in
production.

```
A:\Serp-ai-2026\
├── frontend\               ← UNTOUCHED. Remains runnable as fallback.
├── frontend-react\         ← NEW
│   ├── index.html
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   ├── tsconfig.json
│   ├── eslint.config.js
│   ├── .env.example
│   ├── server\
│   │   └── index.js        ← BFF: the 11 API routes, plain JS + Express
│   ├── public\             ← copied verbatim from frontend/public (18 files)
│   └── src\
│       ├── main.tsx
│       ├── App.tsx
│       ├── pages\          ← the 15 page.tsx files
│       ├── components\     ← copied as-is
│       ├── lib\            ← copied as-is
│       ├── types\
│       └── styles\globals.css
└── backend\                ← UNTOUCHED
```

### 2.1 Why the BFF cannot be deleted

Nine of the eleven route handlers perform this sequence:

```js
const { getToken } = await auth();      // Clerk, server-side
const token = await getToken();
await fetch(`${BACKEND_API_URL}/...`, {
  headers: { Authorization: `Bearer ${token}` },
});
```

`CLERK_SECRET_KEY` cannot be placed in a browser bundle, and a Clerk token cannot
be minted without it. So any architecture that removes the server also removes
authentication. Since keeping login is a hard requirement (§1.2.2), the server
stays — it simply changes language and location.

### 2.2 Request flow

**Development**
```
Browser :5173  ──►  Vite dev server
                     ├─ /api/*  ──proxy──►  Express :8787 ──►  FastAPI :8000
                     │                        (adds Clerk Bearer token)
                     └─ /*     ──serves──►  src/ via Vite
```

**Production**
```
Browser ──►  Express (single process)
              ├─ /api/*  ──►  FastAPI   (+ Clerk Bearer token)
              └─ /*      ──►  dist/index.html  (SPA fallback)
```

Same origin in both environments, so no CORS configuration is required anywhere.

---

## 3. Server design — `server/index.js`

Plain JavaScript, Express 5. One file, ~200 lines. **Every path is byte-identical
to today, so `src/lib/api.ts` requires zero changes.**

| Method | Path | Backend target | Auth | Notes |
|---|---|---|---|---|
| POST | `/api/chat` | `$BACKEND/chat/stream` | yes | Body parsed as JSON. Invalid JSON → 400 |
| POST | `/api/chat/stream` | `$BACKEND/chat/stream` | yes | SSE passthrough |
| GET | `/api/documents/pdf/:filename` | `$BACKEND/documents/pdf/:filename` | no | `encodeURIComponent` the filename; forward `content-type` + `content-length`; `Cache-Control: public, max-age=86400`; 30s timeout |
| POST | `/api/grievance/answer` | `$BACKEND/grievances/answer` | yes | |
| POST | `/api/grievance/clarify` | `$BACKEND/grievances/clarify` | yes | |
| POST | `/api/grievance/detect` | `$BACKEND/grievances` | yes | |
| GET | `/api/grievance/fields` | `$BACKEND/grievances/:conversation_id/fields` | yes | Reads `conversation_id` + `language` query params; 400 if `conversation_id` missing; backend 404 → 404, else 502 |
| POST | `/api/grievance/finalize` | `$BACKEND/grievances/finalize` | yes | |
| POST | `/api/speak` | `$BACKEND/voice/speak` | yes | Reads `multipart/form-data` (`text`, `language`); **converts the returned hex string to binary `audio/mpeg`**; 30s timeout; on failure returns empty body with 503 so the client falls back to browser TTS |
| POST | `/api/translate` | `$BACKEND/translate` | no | |
| POST | `/api/voice/speak` | `$BACKEND/voice/speak` | yes | Reads `{ segments }`; 400 if empty; 30s timeout; returns `{ audio, language }` |

### 3.1 Behaviours that must be preserved exactly

**a. The `/chat` → `/chat/stream` rewrite.**
`frontend/src/app/api/chat/route.ts:21` does
`BACKEND_API_URL.replace(/\/chat$/, "/chat/stream")`. Both handlers resolve to
the streaming endpoint this way. Preserved.

**b. SSE must not be buffered.**
The Express handler must call `res.flushHeaders()`, set
`Content-Type: text/event-stream`, `Cache-Control: no-cache` and
`X-Accel-Buffering: no`, then pipe the upstream `ReadableStream` straight to
`res`. Any buffering breaks token-by-token streaming, which is the single most
visible feature of the app.

**c. Status codes are part of the frontend contract.**
`ChatWindow.tsx` and `speech.ts` branch on 502 (`retrieval_backend_error`) and
503 (`retrieval_backend_unavailable`) to trigger fallbacks. These codes and error
body shapes are preserved exactly.

**d. 30-second timeouts** via `AbortController` on the four handlers that use them.

### 3.2 Clerk token acquisition

Use `@clerk/express` (v2.1.75, peer-compatible with Express 5), which is Clerk's
first-party Express integration. It provides `clerkMiddleware()` — the direct
analogue of the `clerkMiddleware()` currently in `src/proxy.ts` — plus
`getAuth(req)`, which returns an `AuthObject` whose `getToken()` resolves to the
session JWT. That is the exact pair needed to replace
`await auth()` → `await getToken()` in all nine authenticated handlers.

`@clerk/express` depends on `@clerk/backend` ^3.22.0, the same package
`@clerk/nextjs` uses internally, and re-exports its entire API. No direct
`@clerk/backend` import is required; if one is needed it comes through
`@clerk/express`.

Note: `@clerk/clerk-react` is **deprecated** ("no longer supported, use
`@clerk/react`"). The client package is `@clerk/react` ^6.17.5 — which is
precisely what `@clerk/nextjs@7` depends on internally, so it is the same code
path Next is running today.

### 3.3 Static serving and SPA fallback

In production the same Express process serves `dist/`:

- `express.static(dist)` for hashed assets, `index.html` for `/`.
- A catch-all `app.use()` (not `app.get('*')`, which is invalid in Express 5)
  returns `dist/index.html` for any unmatched non-`/api` GET, so client-side
  routes such as `/chat` and `/grievance/status` survive a hard refresh.
- Registered **after** the `/api` routes, so API 404s are not swallowed.

### 3.4 `src/proxy.ts` is deleted

`frontend/src/proxy.ts` is Next 16's renamed `middleware.ts`. It exists only to
run `clerkMiddleware()` in front of the API routes. Those routes now live in
Express and do their own auth, so it has no purpose and no equivalent.

---

## 4. Routing

React Router 7 (`react-router-dom`). 15 routes, declared with the JSX element API
in `src/App.tsx`. Route matching order matters: static segments before dynamic,
and `/grievance/status` and `/grievance/draft/view` before any `/grievance/*`
splat (none is needed, but the ordering is stated so it is not changed later).

| Route | Source file | Change required |
|---|---|---|
| `/` | `app/page.tsx` | import swap only |
| `/chat` | `app/chat/page.tsx` | import swap + remove `<Suspense>` wrapper |
| `/faq` | `app/faq/page.tsx` | import swap only |
| `/grievance` | `app/grievance/page.tsx` | import swap only |
| `/grievance/status` | `app/grievance/status/page.tsx` | import swap only |
| `/grievance/draft/view` | `app/grievance/draft/view/page.tsx` | import swap only |
| `/legal` | `app/legal/page.tsx` | import swap only |
| `/legal/:slug` | `app/legal/[slug]/page.tsx` | import swap only |
| `/library` | `app/library/page.tsx` | import swap only |
| `/schemes` | `app/schemes/page.tsx` | import swap only |
| `/schemes/:slug` | `app/schemes/[slug]/page.tsx` | import swap only |
| `/services` | `app/services/page.tsx` | import swap only |
| `/services/:slug` | `app/services/[slug]/page.tsx` | import swap only |
| `/sign-in/*` | `app/sign-in/[[...sign-in]]/page.tsx` | replaced by Clerk `<SignIn routing="path" path="/sign-in" />` |
| `/sign-up/*` | `app/sign-up/[[...sign-up]]/page.tsx` | replaced by Clerk `<SignUp routing="path" path="/sign-up" />` |
| `*` | **new** | 404 page, styled to match the existing design tokens |

### 4.1 Import replacements

Verified by grep: **15 files** import `next/link`; **7 files** import
`next/navigation` across **8 call sites**.

| Next.js | React Router | Sites |
|---|---|---|
| `import Link from "next/link"` | `import { Link } from "react-router-dom"` | 15 files. `<Link href className>` is identical — no JSX changes |
| `usePathname()` | `useLocation().pathname` | `ConditionalNavs.tsx:8`, `TopNav.tsx:23` |
| `useSearchParams()` | `useSearchParams()` | `ChatWindow.tsx:120`. Same shape |
| `useRouter()` | `useNavigate()` | `ChatWindow.tsx:116`, `GrievanceCard.tsx:52`. `.back()` → `navigate(-1)`; `.push(x)` → `navigate(x)` |
| `useParams<T>()` | `useParams<T>()` | `legal/[slug]:29`, `schemes/[slug]:42`, `services/[slug]:30`. Identical API |

`ConditionalNavs.tsx` is rewritten to take `location.pathname` from
`useLocation()`; its `hideNav` logic is unchanged.

### 4.2 `src/app/layout.tsx` → `index.html` + `App.tsx` + `main.tsx`

`layout.tsx` renders `<html>`, `<body>`, `ClerkProvider`, `LanguageProvider`,
`ConditionalNavs` and a skip link. In Vite there is no server-rendered document,
so this splits three ways:

- **`index.html`** — `<html lang="en">`, `<body>`, `<title>JanSahay — Cooperative
  Governance Assistant</title>`, the description meta tag, `<link rel="icon"
  href="/favicon.ico">`, `<meta name="viewport" content="width=device-width,
  initial-scale=1">`, and the 12 `--font-*` custom properties. The `metadata` and
  `viewport` exports are entirely static, so they move to HTML as-is. **No
  react-helmet dependency is added.**
- **`App.tsx`** — `<ClerkProvider>` wrapping `<LanguageProvider>` wrapping
  `<ConditionalNavs>` wrapping `<Routes>`. Body classes
  (`min-h-full flex flex-col font-sans bg-[var(--canvas)]`) and the skip link
  are preserved.
- **`main.tsx`** — `createRoot().render(<App />)` plus `import "./styles/globals.css"`.

The `"use client"` directives become inert comments and are removed by a
codemod. They are not errors in Vite; removing them is cosmetic hygiene.

---

## 5. Dependencies

### 5.1 Removed

| Package | Reason |
|---|---|
| `next` 16.3.3 | The framework being removed |
| `@clerk/nextjs` | Next-specific bindings |
| `eslint-config-next` | Next-specific lint rules |
| `@tailwindcss/postcss` | Replaced by the Vite plugin |

### 5.2 Added

| Package | Purpose |
|---|---|
| `react-router-dom` ^7.18.4 | Routing |
| `@clerk/react` ^6.17.5 | `ClerkProvider`, `useAuth`, `UserButton`, `SignIn`, `SignUp`. Same package `@clerk/nextjs` uses internally |
| `@clerk/express` ^2.1.75 | Server-side `clerkMiddleware()` + `getAuth(req)`. Peer-compatible with Express 5 |
| `express` ^5.2.1 | The BFF |
| `@fontsource/inter` (variable) | `--font-inter` |
| `@fontsource/space-grotesk` (weight 500) | `--font-display-latin` |
| `@fontsource/geist-mono` (variable) | `--font-geist-mono` |
| `@fontsource/noto-serif-{devanagari,bengali,tamil,telugu,kannada,gurmukhi,gujarati,oriya,malayalam}` (weights 400/500/600/700) | The 9 script fonts |
| `@tailwindcss/vite` ^4.3.3 | Tailwind in Vite |
| `vite` ^8.3.2, `@vitejs/plugin-react` ^6.1.2 | Build tooling |
| `concurrently` ^10.0.5 (dev) | Runs Vite + Express together |
| `typescript-eslint` ^8.71, `eslint-plugin-react-hooks` ^7.1.1, `eslint-plugin-react-refresh` ^0.5.7, `globals` ^17.13 (dev) | Replaces `eslint-config-next` |
| `@types/express` ^5.0.6 (dev) | Types for the server |

All versions above were verified against the npm registry on 2026-10-05.

### 5.3 Unchanged

`react` 19.2.8, `react-dom` 19.2.8, `typescript` ^5, `tailwindcss` ^4,
`@tailwindcss/typography` ^0.5.20, `gsap` ^3.15.0, `react-markdown` ^10.1.0,
`remark-gfm` ^4.0.1, `vitest` ^4, `@testing-library/react` ^16.3.3, `jsdom` ^25.

---

## 6. Fonts

`next/font/google` in `layout.tsx` downloads fonts at build time and injects a
class per family that defines one CSS variable. Vite has no equivalent, so the
same 12 families are self-hosted via `@fontsource`, imported for side-effect CSS
in `main.tsx`, and each family name is bound to the **same variable name used
today**:

| Variable | Family | Weights (from `layout.tsx`) |
|---|---|---|
| `--font-inter` | Inter | variable (latin) |
| `--font-display-latin` | Space Grotesk | 500 (latin) |
| `--font-geist-mono` | Geist Mono | variable (latin) |
| `--font-devanagari` | Noto Serif Devanagari | 400 500 600 700 |
| `--font-bengali` | Noto Serif Bengali | 400 500 600 700 |
| `--font-tamil` | Noto Serif Tamil | 400 500 600 700 |
| `--font-telugu` | Noto Serif Telugu | 400 500 600 700 |
| `--font-kannada` | Noto Serif Kannada | 400 500 600 700 |
| `--font-gurmukhi` | Noto Serif Gurmukhi | 400 500 600 700 |
| `--font-gujarati` | Noto Serif Gujarati | 400 500 600 700 |
| `--font-odia` | Noto Serif Oriya | 400 500 600 700 |
| `--font-malayalam` | Noto Serif Malayalam | 400 500 600 700 |

Because the variable names are unchanged, **all 12 mappings in `globals.css`
lines 94–99 and the `html[data-locale="…"]` script switching at lines 203–215
work with zero edits**, and no component that references a font variable changes.

The 12 variables are declared on the `<html>` element in `index.html` (the same
element Next attached them to), each holding a quoted family name — for example
`--font-inter: 'Inter';` and `--font-devanagari: 'Noto Serif Devanagari';`. They
are declared in `index.html` rather than in `globals.css` so that
`globals.css` stays byte-for-byte identical to the original, which makes it
trivial to prove the design system was not disturbed. Because `globals.css`
declares `--font-primary: var(--font-inter), …` on `:root`, and `<html>` **is**
`:root`, the cascade resolves correctly. The later
`html[data-locale="bn"] { --font-script: … }` rules override on the same element
and are unaffected.

If a `@fontsource` package does not exist for one of these families, that family
falls back to its system equivalent and the change is reported — it does not
block the migration.

---

## 7. Styling

`src/styles/globals.css` is copied **verbatim** (all 464 lines). It contains:

- `@import "tailwindcss"` and `@plugin "@tailwindcss/typography"` — both
  supported by `@tailwindcss/vite`; the PostCSS file is deleted.
- `:root` design tokens (lines 9–151) — unchanged.
- `@theme inline` Tailwind mappings (153–200) — unchanged.
- Per-locale script font switching (203–215) — unchanged.
- `@layer base` resets, hidden scrollbars, iOS zoom guard, focus rings (217–276) —
  unchanged.
- Hand-rolled classes: `.display`, `.eyebrow`, `.skip-link`, `.input-container`,
  `.marquee-track`, reduced-motion block, etc. (279–464) — unchanged.

`src/components/ui/ScrollStack.css` is deleted along with its dead consumer.

No `tailwind.config.js` exists or is needed — this project is already on
Tailwind v4's CSS-first configuration.

---

## 8. Configuration

| File | Action |
|---|---|
| `next.config.ts` | **Deleted.** Only held `devIndicators: false` (a Next-only setting) and `images.remotePatterns` (unused — the project uses plain `<img>`, not `next/image`) |
| `postcss.config.mjs` | **Deleted.** Tailwind moves into `vite.config.ts` via `@tailwindcss/vite` |
| `vite.config.ts` | **New.** React plugin, Tailwind plugin, `resolve.alias` for `@` → `./src`, `server.proxy` for `/api` → `http://localhost:8787` |
| `tsconfig.json` | Copy, minus the `next` plugin and the `.next/types/**` includes. **`paths: { "@/*": ["./src/*"] }` is kept** |
| `vitest.config.mjs` | Copied nearly verbatim — it is already framework-agnostic. jsdom and the `@` alias carry over unchanged |
| `eslint.config.mjs` | Replaced: flat config with `typescript-eslint`, `react-hooks`, `react-refresh`, `globals.browser` |
| `.env.example` | Rewritten (see §8.1) |
| `.gitignore` | Rewritten for Vite (`dist/`, `node_modules/`, `.env*`) |
| `README.md` | Rewritten. The current one is stock `create-next-app` boilerplate referencing Geist and Next |
| `add-hooks.mjs` | **Deleted.** One-shot codegen for `dictionaries.ts`; already run |

### 8.1 Environment variables

| Old | New | Read by |
|---|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `VITE_CLERK_PUBLISHABLE_KEY` | Clerk browser SDK |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `VITE_CLERK_SIGN_IN_URL` | Clerk browser SDK |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | `VITE_CLERK_SIGN_UP_URL` | Clerk browser SDK |
| `CLERK_SECRET_KEY` | `CLERK_SECRET_KEY` (unchanged) | `server/index.js` **only** |
| `BACKEND_API_URL` | `BACKEND_API_URL` (unchanged) | `server/index.js` **only** |
| `AZURE_TRANSLATOR_KEY` / `_REGION` / `_ENDPOINT` | **Removed** | Dead — referenced nowhere in `src/`; translation is proxied through FastAPI |

`BACKEND_API_URL` was **missing from both `.env.example` files** despite being
required by all 11 handlers. It is now documented, defaulting to
`http://localhost:8000`.

Clerk redirect URLs move from the Vercel dashboard into
`ClerkProvider`'s `signInUrl` / `signUpUrl` props, because in a Vite SPA there is
no framework-level URL rewrite to rely on.

---

## 9. Dead code removed

| Path | Why |
|---|---|
| `src/components/layout/SmoothScroll.tsx` | Unimported. **Imports `lenis`, which is not in `package.json` — this is what breaks the current production build** |
| `src/components/ui/ScrollStack.tsx` | Unimported. Same missing-`lenis` breakage |
| `src/components/ui/ScrollStack.css` | Only consumed by `ScrollStack.tsx` |
| `src/components/grievance/GrievanceWizard.tsx` | Unimported. `/grievance` inlines its own 4-step wizard |
| `src/components/chat/ThinkingBubble.tsx` | Superseded by `ThinkingProcess.tsx` |
| `src/app/api/chat/route.ts` | Byte-identical duplicate of `api/chat/stream/route.ts` |
| `const ur` in `dictionaries.ts:3576` | Defined but never added to the `dict` export |

Deleting the first two also removes the missing-dependency build failure.

Not removed, but noted: `public/` holds ~10.8 MB of PNGs (~2 MB each) served as
plain `<img>` with no resizing. Out of scope, but worth revisiting for users on
slow connections.

---

## 10. Migration sequence

Each step leaves the app in a runnable state.

1. **Scaffold** `frontend-react/` — package.json, configs, `index.html`,
   `src/main.tsx`, empty `App.tsx`. Verify `npm run dev` boots.
2. **Copy verbatim** — `public/`, `src/components/`, `src/lib/`, `src/types/`,
   `src/styles/globals.css`. Delete the dead components from §9. Verify build
   compiles (routing is not wired yet, so nothing renders — expected).
3. **Fonts** — install the 12 `@fontsource` packages, import them in `main.tsx`,
   define the 12 variables in `index.html`. Verify text renders in all 11
   locales with correct scripts.
4. **Server** — write `server/index.js`. Verify each of the 11 endpoints against
   a running backend with `curl`, checking status codes and, for `/api/speak`,
   that the response is binary `audio/mpeg`.
5. **Move pages** — `src/app/**/page.tsx` → `src/pages/**`, flatten Clerk pages.
6. **Rewire routing** — `App.tsx` with all 15 routes + 404. Replace the 21
   `next/link` / `next/navigation` imports.
7. **Port tests** — copy `vitest.config.mjs` and the 18 test files; delete the
   `vi.mock("next/navigation")` blocks and wrap affected components in
   `<MemoryRouter>` instead.
8. **Fix the 12 baseline failures** per §10.1 — 3 source bugs and 9 test
   expectations, each with its own red-green cycle.
9. **Docs** — correct `PROJECT_STATUS.md` (including the stale "7 failures" and
   the PWA claim) and the stack table in `CLAUDE.md`.

### 10.1 Pre-existing test failures

`PROJECT_STATUS.md:139` claims 7 failures. That is **stale**. Measured on
2026-10-05 after `npm ci` (the repo had no `node_modules`, so no baseline had ever
been run in this checkout):

```
Test Files  5 failed | 13 passed (18)
     Tests  12 failed | 66 passed (78)
```

All 12 are genuine defects that predate the migration. Root causes, verified by
reading the source:

| # | File | Failing test(s) | Root cause | Kind |
|---|---|---|---|---|
| 1 | `src/lib/i18n/dictionaries.test.ts` | every locale defines every key that en defines | **Real i18n gap.** `en` has 374 keys. Missing counts: hi 4, mr 4, ta 50, gu 48, bn 130, te/kn/pa/or/ml 111 each. `translate()` already falls back to `en`, so the app works; the test asserts total coverage that does not exist | Test asserts an untrue invariant |
| 2 | `src/lib/i18n/i18n.test.ts` | root layout example translations resolve | Copy changed from `"Chat now"` to `"Ask JanSahay →"`; assertion is stale | Stale test |
| 3 | `src/lib/__tests__/speech.test.ts` | uses Azure for each language run | Implementation deliberately **batches** all runs into one `fetchVoiceSpeak(runs)` call (`speech.ts:211`). Test expects one call per language run | Stale test |
| 4 | `src/lib/__tests__/speech.test.ts` | settles the in-flight Azure promise when a newer call cancels it | **Real bug.** `speakBackendSegments` (`speech.ts:179`) reads `const token = _speakToken` *after* awaiting the fetch. A call cancelled mid-fetch re-reads the *current* token, passes the guard in `playBackendAudio`, and creates audio whose `onended` never fires — leaving the caller's promise pending forever | Source bug |
| 5 | `src/lib/__tests__/speech.test.ts` | settles the in-flight Azure promise when stopSpeaking is called | Same root cause as #4 | Source bug |
| 6 | `src/components/chat/__tests__/EvidencePanel.test.tsx` | static evidence shows Open Document link | Component renders `t("chat.viewDocument")` = **"View document"** (MessageBubble.tsx:157), not "Open Document". Additionally the static-citation link only renders when `citation.source_file` is set; the fixture omits it | Stale test + incomplete fixture |
| 7 | same | web evidence shows Open Source link after expanding | Same: component renders "View source" | Stale test |
| 8 | same | document links open in new tab with noopener | Same | Stale test |
| 9 | same | URLs remain unchanged after language switching | Same | Stale test |
| 10 | same | evidence card toggle is a keyboard-focusable button | Expects accessible name `"Official Document PMFBY Guidelines p.5"`; actual name is composed of `t("chat.viewDocument")` + title + `Page 5` | Stale test |
| 11 | `src/components/chat/__tests__/GrievanceCard.test.tsx` | renders structured field values when fields are present | **Real bug.** `GrievanceCard.tsx:193` title-cases `application_id` to `"Application Id"`. English requires `"Application ID"` | Source bug |
| 12 | same | renders field labels as title-cased snake_case keys | Same root cause as #11 | Source bug |

Summary: **3 source bugs** (#4/#5 speech token threading, #11/#12 acronym casing),
**8 stale test expectations**, **1 i18n coverage gap**.

#### 10.1.1 Fix strategy

**Source bugs (3) — fix the code.** These are real defects that affect users, so
the tests are correct and the code is wrong.

- #4/#5: thread the caller's token into `speakBackendSegments(segments, token)`
  instead of re-reading the module-level `_speakToken` after the await, and
  return early if the token is stale. This is the dangling-promise bug the test
  was written to catch; it means a cancelled speech request currently leaks a
  pending promise and keeps an `Audio` element alive.
- #11/#12: replace the naive title-caser in `GrievanceCard.tsx` with an
  acronym-aware version that upper-cases a fixed set of initialisms
  (`id`, `url`, `upi`, `ifsc`, `pan`, `kcc`, `aadhaar`) and title-cases the rest.
  `"application_id"` → `"Application ID"`.

**Stale test expectations (8) — fix the tests.** In each case the component
behaviour is intentional and better than what the test asserts. Tests are updated
to match, and the EvidencePanel static-citation fixture gains a `source_file` so
the document-link branch is actually exercised.

**i18n coverage gap (1) — fix the test, not 776 translations.** The test encodes
an aspiration, not a requirement. `translate()` (`dictionaries.ts:3863`) already
implements `table[key] ?? en[key] ?? key`, so a missing key degrades to English
rather than breaking. The test is rewritten to assert the invariant that actually
matters:

1. `en` is complete and non-empty.
2. No locale defines a key that `en` does not (catches typos and stale keys).
3. `translate()` falls back to English for a key a locale lacks.
4. Every locale translates `nav.home` to a non-empty string.

This does **not** reduce translation quality — the 776 untranslated strings remain
visible in the report produced by step 2 of that task, so the gap stays
discoverable. Machine-translating them is a content decision outside this
migration's scope and is not done here.

---

## 11. Verification

Success is defined by evidence, not by inspection. All seven gates must pass
before `frontend/` is deleted or any deploy config is touched.

| # | Gate | Command / method |
|---|---|---|
| 1 | Production build clean | `npm run build` — zero errors, zero warnings about unresolved imports |
| 2 | Lint clean | `npm run lint` |
| 3 | Types clean | `npx tsc --noEmit` under `strict: true` |
| 4 | Tests pass | `npm test` — every test green: 78 passing, 0 failing (baseline is 66 passing / 12 failing) |
| 5 | Every page renders | Start both servers, request all 15 routes plus one deliberately bad URL. Each real route must return HTTP 200 and contain its expected heading text; the bad URL must return the 404 page |
| 6 | Chat streams end-to-end | Type a real question in the browser; confirm tokens arrive incrementally from FastAPI, not in one burst. Check the BFF logs show no buffering |
| 7 | Auth + grievance intact | Sign in and out via Clerk; complete a grievance through `finalize` |

Gate 6 gets a timing check as well: measure the interval between the first and
second streamed token. If they arrive in the same tick, the SSE pipe is
buffering and gate 6 fails.

**`frontend/` is not deleted and `render.yaml` / Vercel config are not touched
until all seven gates pass.** Git history provides an additional rollback path.

---

## 12. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| SSE buffering in Express silently breaks streaming | Medium | Explicit `flushHeaders()`, no compression middleware, `X-Accel-Buffering: no`. Verified by gate 6's inter-token timing check |
| Clerk token acquisition differs between `@clerk/nextjs` and Express | Medium | Uses the same `@clerk/backend` primitive Next uses internally. Verified by gate 7 |
| Vite dev proxy interferes with SSE | Low | `http-proxy` streams natively; no compression by default in Vite. Covered by gate 6 run against the dev server as well as production build |
| `@fontsource` missing a family | Low | System fallback per family; reported, not blocking (§6) |
| `globals.css` behaves differently outside Next | Low | The file contains no Next-specific at-rules. Copied verbatim and verified in gate 5 |
| Path alias breaks in one of the three configs | Low | `@` is declared identically in `tsconfig.json`, `vite.config.ts` and `vitest.config.mjs`, and checked by gates 1, 3 and 4 |
| Hidden coupling to Next in a file not yet inspected | Low | A repo-wide grep for `next/`, `NextResponse`, `useRouter`, `usePathname`, `useSearchParams`, `useParams`, `metadata` export must return zero hits in `frontend-react/` after the migration. This grep is part of gate 1 |
| The 776 untranslated dictionary strings get silently "fixed" by test rewriting | Medium | §10.1.1 fixes the *test*, not the data. A coverage report is emitted by that task listing every missing key per locale, so the gap stays visible and is never mistaken for solved |

---

## 13. Definition of done

- `frontend-react/` builds, lints, typechecks and tests clean.
- All 15 pages render; 404 works.
- Chat streams token-by-token from the real backend.
- Clerk sign-in, sign-up and user button work.
- Grievance flow reaches `finalize`.
- All 11 locales render in the correct script.
- Zero remaining references to Next.js in `frontend-react/`.
- `frontend/` still runs, untouched, until the user confirms the swap.
- `PROJECT_STATUS.md` and the stack table in `CLAUDE.md` are updated.