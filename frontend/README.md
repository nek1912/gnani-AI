# JanSahay Frontend — React + Vite

Multilingual citizen-assistance frontend for cooperative governance, PMFBY, PACS,
financial literacy and grievance redressal.

React 19 + Vite 8 single-page app. The browser talks **directly** to the Python
FastAPI backend and attaches Clerk's own session token to every request. There is
no proxy server and no second port.

---

## Requirements

- **Node 20.19+ or 22.12+** (Vite 8 engine floor; developed on 24.13)
- A running Python backend (default `http://localhost:8000`)
- A Clerk application with a publishable key

## Setup

```bash
npm install
cp .env.example .env    # then fill in the values
```

| Variable | Scope | Purpose |
|---|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | browser | Clerk session in the browser |
| `VITE_CLERK_SIGN_IN_URL` | browser | Sign-in redirect target |
| `VITE_CLERK_SIGN_UP_URL` | browser | Sign-up redirect target |
| `VITE_BACKEND_API_URL` | browser | FastAPI base URL, e.g. `http://localhost:8000` |
| `VITE_PORT` | dev only | Vite dev-server port (default 5173) |

Only `VITE_`-prefixed variables reach the browser bundle. `CLERK_SECRET_KEY` is
never needed here; it lives in `backend/.env` (the backend's only config source)
and stays inside the backend.

Add your sign-in and sign-up URLs as **redirect URLs** in the Clerk dashboard.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server on `:5173` (set `VITE_PORT`) |
| `npm run build` | Type-check, then emit static assets to `dist/` |
| `npm run lint` | ESLint over `src/` |
| `npm test` | Vitest — 94 tests across 18 files |
| `npm run i18n:coverage` | Report per-locale translation coverage |

## Architecture

```
Browser :5173
   |
   |-- Clerk session token (Authorization: Bearer)
   |
   +-- POST /chat/stream  (SSE)  -----------------------> FastAPI :8000
   +-- POST /grievances/*                            ---> FastAPI
   +-- POST /voice/speak, /translate, /documents/pdf/* ---> FastAPI
```

Two ports only: the dev server and FastAPI. Cross-origin, so the backend's
`ALLOWED_ORIGINS` must list this dev server's origin.

`src/lib/backend.ts` owns the whole conversation with FastAPI: the base URL, the
`/api/*` → FastAPI path mapping, and the bearer header. `App.tsx` hands Clerk's
`useAuth().getToken` to it once at mount, because `api.ts` and `speech.ts` are
plain modules that cannot call hooks.

### Authentication

The browser holds a Clerk **session token** only. `CLERK_SECRET_KEY` never leaves
the backend, where Clerk's own JWKS verification lives in `app/auth.py`.

Because the browser signs its own requests, the frontend's Clerk instance and the
backend's `CLERK_ISSUER` **must be the same Clerk application**. If they diverge,
every authenticated call returns 401 while the app appears to work.

## Deploying

This is a pure static bundle. Serve `dist/` from any static host or CDN.

```bash
npm ci && npm run build
```

`render.yaml` at the repo root configures only the Python backend and has **not**
been updated for this frontend.

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ChatWindow.tsx              # Main chat interface with live SSE streaming, voice & persistence
│   │   ├── FloatingChatWidget.tsx      # Quick-access floating drawer widget
│   │   ├── EvidenceBand.tsx            # Confidence visualizer band
│   │   ├── chat/
│   │   │   ├── ThinkingProcess.tsx     # Claude & ChatGPT-style thinking animation (AG-UI & A2UI)
│   │   │   ├── ThinkingProcess.module.css # Shimmer sweep, ambient sparkle pulse & timeline track
│   │   │   ├── MessageBubble.tsx       # Markdown answer renderer, citations, read-aloud TTS
│   │   │   ├── GrievanceFlow.tsx       # 9-stage interactive grievance redressal state machine UI
│   │   │   ├── GrievanceCard.tsx       # Structured grievance summary card with copy & PDF draft
│   │   │   ├── GrievanceClassificationPanel.tsx
│   │   │   ├── GrievanceFieldPanel.tsx
│   │   │   └── EvidencePanel.tsx       # Slide-out drawer with chunk source provenance
│   │   ├── layout/
│   │   │   ├── Header.tsx / TopNav.tsx # Navigation & language selector
│   │   │   └── Footer.tsx
│   │   ├── motion/
│   │   │   ├── Reveal.tsx / Stagger.tsx# Smooth scroll & reveal animations
│   │   └── ui/                         # Clay design system primitives (Button, Badge, Card, Alert, Modal, etc.)
│   ├── lib/
│   │   ├── api.ts                      # Backend API client with SSE streaming reader & grievance calls
│   │   ├── backend.ts                  # Centralized FastAPI base URL & Clerk Authorization header injection
│   │   ├── speech.ts                   # Web audio recording & Gnani / Sarvam / Azure voice services
│   │   ├── translator.ts               # Translation helper utilities
│   │   ├── band.ts                     # Confidence band categorization
│   │   ├── i18n/                       # 11-language translation dictionaries & provider
│   │   └── data/                       # Curated schemes, services, legal details, and FAQs
│   ├── pages/                          # Routed views: HomePage, ChatPage, GrievancePage, SchemesPage, etc.
│   ├── styles/
│   │   ├── globals.css                 # Clay design system tokens, Tailwind v4 theme, fonts & colors
│   │   └── document.css
│   ├── App.tsx                         # Root router & Clerk authentication wrapper
│   └── main.tsx                        # Application mount
├── index.html                          # Entry HTML with Google & Indic font declarations
└── vite.config.ts                      # Vite 8 configuration with path aliases
```

## Thinking Animation (AG-UI & A2UI)

The chat interface includes an advanced, real-time reasoning and thinking UI (`ThinkingProcess.tsx`):
- **Live Elapsed Timer**: Real-time counter (`Thinking (3s)...`) that locks upon token generation.
- **Dynamic Micro-Thoughts Ticker**: Contextually cycles active micro-steps every 2.2s so the interface never feels frozen or static.
- **Ambient Sparkle & Shimmer Sweep**: Glowing radial pulse (`.sparkleGlow`) and linear gradient sweep (`.shimmerText`) in the website's brand teal (`#1a3a3a`).
- **4-Stage Pipeline Progress**: Tracks `Searching sources` → `Merging evidence` → `Generating response` → `Verifying citations`.
- **Persistent Summary Pill**: Seamlessly collapses into `Thought for X seconds • N steps complete ▾` during answer streaming, and remains permanently anchored above completed answers with click-to-expand timeline support.

## Known limitations

- **Not a PWA.** No web app manifest and no service worker.
- **No dark mode.** The palette is light-only.
- **Translation coverage is incomplete.** 11 locales are wired up, but 791 of
  3,740 possible strings are untranslated (78.9%; `bn` lowest at 65.2%). Missing
  keys fall back to English. Run `npm run i18n:coverage`.
- **The main JS bundle is ~1.5 MB** (~400 kB gzipped), mostly `gsap`,
  `react-markdown` and Clerk. Not code-split.

## Conventions

- `@/` resolves to `src/` in `tsconfig.json`, `vite.config.ts` and
  `vitest.config.mjs`. All three must stay in agreement.
- `src/styles/globals.css` is the design system and is kept byte-identical to
  the original. Its 12 `--font-*` variables are declared in `index.html`;
  `globals.css` composes font stacks from them by name — do not rename them.
- Components carry no `"use client"` directive; there is no such thing in a Vite
  SPA.
- ESLint reports 46 warnings, all pre-existing in the copied source. They are
  demoted to `warn` rather than refactored, so the debt stays visible.
