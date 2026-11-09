# Frontend — JanSahay Next.js 16 PWA

Read `../AGENTS.md`, `../CLAUDE.md`, and `../PROJECT_STATUS.md` first for
system-wide rules and current state. This file covers frontend-only conventions.

## Proxy convention (do not bypass)

- The browser never talks to the backend directly. All calls go through
  `src/app/api/*` proxy routes, which attach the Clerk JWT server-side.
- `BACKEND_API_URL` is the backend BASE (e.g. `http://localhost:8000`, no
  `/chat` suffix). Mapping: `/api/chat`→`{base}/chat`,
  `/api/chat/stream`→`{base}/chat/stream`, `/api/grievance/*`→`{base}/grievances/*`,
  `/api/translate`→`{base}/translate`. Restart `npm run dev` after changing
  `frontend/.env.local`.
- A **503** from a proxy route means the backend is unreachable; **502** means
  it answered non-OK; **401** means the user is not signed in.

## Key files

- `src/app/api/chat/route.ts`, `src/app/api/chat/stream/route.ts` — chat proxies (JSON + SSE)
- `src/app/api/grievance/{detect,fields,answer,finalize,clarify}/route.ts` — grievance proxies
- `src/app/api/translate/route.ts` — Azure-only utility translation proxy
- `src/lib/api.ts` — `sendChat` / `sendChatStream` client
- `src/components/ChatWindow.tsx` — main chat UI (`thinking/token/metadata/done` SSE, voice, citations; `sessionId` is a `useRef` reset on new-chat/load/delete)
- `src/lib/i18n/` — 11-language dictionaries (`en hi gu mr bn ta te kn pa or ml`)

## Rules

- Never put backend keys in the browser and never use `NEXT_PUBLIC_*` for secrets
  (only `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is public by design).
- Display confidence as evidence bands, not raw percentages.
- Grievance UI renders backend-provided `field_label` values; user-entered values
  are shown verbatim, never re-translated client-side.
- See `README.md` (this folder) for setup.
