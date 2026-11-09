# JanSahay frontend agent notes

- Browser → backend only via `src/app/api/*` proxy routes (Clerk JWT attached
  server-side). `BACKEND_API_URL` is the backend BASE (`http://localhost:8000`,
  no `/chat` suffix); restart `npm run dev` after changing `.env.local`.
- 11-language i18n lives in `src/lib/i18n/`; main chat UI is
  `src/components/ChatWindow.tsx`. See `CLAUDE.md` (this folder) for details.
- Do not remove the Next.js block below — it is managed by `next dev`.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
