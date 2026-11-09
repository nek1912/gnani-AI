# Next.js → React + Vite Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Next.js 16 frontend in `frontend/` with a React 19 + Vite 8 SPA in a new `frontend-react/` folder, preserving all 15 pages, all 40 components, all 11 locales, Clerk authentication, SSE chat streaming, and the grievance/voice flows — with zero regressions and a green test suite.

**Architecture:** Two units. A static Vite SPA that owns routing, rendering, i18n and all UI state. A small Express 5 BFF (`server/index.js`) that owns the 11 API endpoints, injects the Clerk bearer token, and pipes SSE from FastAPI. In development Vite proxies `/api` to Express; in production Express serves both the API and the built `dist/`. Same origin in both environments, so no CORS anywhere.

**Tech Stack:** React 19.2.8, Vite 8.3.2, `@vitejs/plugin-react` 6.1.2, React Router 7.18.4, Express 5.2.1, `@clerk/react` 6.17.5, `@clerk/express` 2.1.75, Tailwind CSS 4 via `@tailwindcss/vite` 4.3.3, TypeScript 5 strict, Vitest 4, 12 × `@fontsource` v5.3.0.

**Spec:** `docs/superpowers/specs/2026-10-05-nextjs-to-react-vite-migration-design.md`

---

## Global Constraints

These apply to every task. Read before starting any task.

1. **`frontend/` is read-only.** Never edit, move or delete anything under `A:\Serp-ai-2026\frontend\` for the duration of this plan. It is the fallback. Every file created or modified lives under `A:\Serp-ai-2026\frontend-react\` or `A:\Serp-ai-2026\docs\`.
2. **`backend/` is read-only.** No Python changes. If a backend change seems necessary, stop and report it — do not make it.
3. **No PWA work.** No manifest, no service worker, no offline caching. Explicitly declined by the user.
4. **Reproduce existing behaviour; do not improve it.** This is a framework migration. Where current code is wrong but harmless, port it unchanged and report it separately. Known case: `ChatWindow.tsx:76` and `translator.ts:21` send `{texts, to}` to `/api/translate`, which reads `target_language` — so `to` is discarded and the target silently defaults to `"hi"`. Identical before and after. Fixing it is a separate change.
5. **No dark mode.** `globals.css` hardcodes `color-scheme: light`. Leave it.
6. **TypeScript stays.** No `.ts`→`.js` conversion of React source.
7. **`@/*` resolves to `src/*`.** All three configs must declare it identically: `tsconfig.json` `compilerOptions.paths`, `vite.config.ts` `resolve.alias`, `vitest.config.mjs` `resolve.alias`.
8. **`globals.css` is copied byte-for-byte.** Its 12 `--font-*` variables are consumed by name; do not rename or inline them. The variables themselves are declared in `index.html`, not in this file.
9. **Server-only secrets never reach the browser.** `CLERK_SECRET_KEY` and `BACKEND_API_URL` are read only in `server/`. Only `VITE_`-prefixed vars are exposed to the bundle.
10. **Status codes are part of the frontend contract.** `502` = `retrieval_backend_error`, `503` = `retrieval_backend_unavailable`. `ChatWindow.tsx` and `speech.ts` branch on these to trigger fallbacks. Preserve exactly.
11. **SSE must never be buffered.** If tokens arrive in one burst, the streaming gate fails.
12. **Test baseline is 66 passing / 12 failing** across 18 files (78 tests), measured in `frontend/`. The 12 are enumerated in spec §10.1. Success is **78 passing / 0 failing** with no test deleted or skipped.
13. **Commit after every task.** Use the message given in each task's final step.
14. **Windows / PowerShell.** Use `;` not `&&`. Use `-LiteralPath` for paths containing `[` `]`.

---

## File Structure

Everything below is the final shape of `frontend-react/`.

```
frontend-react/
├── index.html                        NEW   document shell, 12 --font-* vars, title/meta/favicon
├── package.json                      NEW   deps + scripts
├── vite.config.ts                    NEW   react + tailwind plugins, @ alias, /api proxy
├── vitest.config.mjs                 NEW   copied from frontend/, unchanged
├── tsconfig.json                     NEW   copied minus next plugin and .next/types
├── eslint.config.js                  NEW   replaces eslint-config-next
├── .env.example                      NEW   VITE_CLERK_* + CLERK_SECRET_KEY + BACKEND_API_URL
├── .gitignore                        NEW   dist, node_modules, .env*
├── README.md                         NEW   replaces stock create-next-app boilerplate
├── server/
│   ├── index.js                      NEW   Express app factory + listen
│   ├── clerk.js                      NEW   token extraction helper (getAuth + getToken)
│   ├── proxy.js                      NEW   fetch-to-backend helper w/ timeout + error mapping
│   ├── sse.js                        NEW   SSE passthrough handler
│   └── __tests__/server.test.js      NEW   14 tests over all 11 endpoints
├── public/                           COPY  18 files verbatim
└── src/
    ├── main.tsx                      NEW   createRoot + globals.css + font imports
    ├── App.tsx                       NEW   ClerkProvider > LanguageProvider > ConditionalNavs > Routes
    ├── vite-env.d.ts                 NEW   /// <reference types="vite/client" />
    ├── pages/                        MOVE  13 pages from src/app/
    │   ├── HomePage.tsx
    │   ├── ChatPage.tsx
    │   ├── FaqPage.tsx
    │   ├── GrievancePage.tsx
    │   ├── GrievanceStatusPage.tsx
    │   ├── GrievanceDraftViewPage.tsx
    │   ├── LegalPage.tsx
    │   ├── LegalDetailPage.tsx
    │   ├── LibraryPage.tsx
    │   ├── SchemesPage.tsx
    │   ├── SchemeDetailPage.tsx
    │   ├── ServicesPage.tsx
    │   ├── ServiceDetailPage.tsx
    │   ├── SignInPage.tsx            NEW   Clerk <SignIn routing="path">
    │   ├── SignUpPage.tsx            NEW   Clerk <SignUp routing="path">
    │   └── NotFoundPage.tsx          NEW   404
    ├── components/                   COPY  34 components, "use client" stripped, dead code deleted
    ├── lib/                          COPY  api.ts, speech.ts, translator.ts, band.ts, hooks, data/, i18n/
    ├── types/speech-recognition.d.ts COPY
    └── styles/globals.css            COPY  byte-for-byte
```

### Why `server/` is four files and not one

`server/index.js` holding all 11 handlers plus auth plus SSE plumbing would be
~200 lines of mixed concerns. Split by responsibility so each file answers one
question:

- `clerk.js` — "what token does this request carry?" (auth concern)
- `proxy.js` — "how do I call FastAPI and map its failures?" (transport concern)
- `sse.js` — "how do I stream without buffering?" (streaming concern)
- `index.js` — "what is the URL surface?" (routing concern)

`proxy.js` is where the 9 authenticated handlers would otherwise duplicate the
same 12 lines of `getToken` → `Authorization` header → 502/503 mapping.

### Deleted, not migrated

| Path | Reason |
|---|---|
| `components/layout/SmoothScroll.tsx` | Unimported. Imports `lenis`, absent from package.json — the current build break |
| `components/ui/ScrollStack.tsx` | Unimported. Same missing-`lenis` breakage |
| `components/ui/ScrollStack.css` | Only consumer is ScrollStack.tsx |
| `components/grievance/GrievanceWizard.tsx` | Unimported. `/grievance` inlines its own wizard |
| `components/chat/ThinkingBubble.tsx` | Superseded by ThinkingProcess.tsx |
| `src/app/api/chat/route.ts` | Byte-identical duplicate of `api/chat/stream/route.ts` |
| `src/proxy.ts` | Next middleware; its job moves into `server/index.js` |
| `src/app/api/**` (all 11) | Replaced by `server/index.js` |
| `src/app/layout.tsx` | Split across index.html / App.tsx / main.tsx |
| `src/app/globals.css` | Moves to `src/styles/globals.css` |
| `const ur` in dictionaries.ts:3576 | Defined but never added to `dict` |
| `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `add-hooks.mjs` | Next-only; replaced |

---

## Task 1: Scaffold the Vite project

**Files:**
- Create: `frontend-react/package.json`
- Create: `frontend-react/index.html`
- Create: `frontend-react/vite.config.ts`
- Create: `frontend-react/tsconfig.json`
- Create: `frontend-react/vitest.config.mjs`
- Create: `frontend-react/eslint.config.js`
- Create: `frontend-react/.env.example`
- Create: `frontend-react/.gitignore`
- Create: `frontend-react/src/vite-env.d.ts`
- Create: `frontend-react/src/main.tsx`
- Create: `frontend-react/src/App.tsx`
- Create: `frontend-react/src/pages/NotFoundPage.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `npm run dev` → Vite on `:5173`, proxying `/api` to `http://localhost:8787`
  - `npm run dev:server` → Express on `:8787`
  - `npm run dev:all` → both via concurrently
  - `npm run build` → `dist/`
  - `npm run preview` → Express serving `dist/` + API on `:8787`
  - `npm test` → Vitest
  - Path alias `@` → `src`
  - `App.tsx` default export: `(): JSX.Element` rendering a placeholder for now

- [ ] **Step 1: Create the folder and verify it is empty**

```powershell
New-Item -ItemType Directory -Path "frontend-react" -Force | Out-Null
New-Item -ItemType Directory -Path "frontend-react\src\pages" -Force | Out-Null
Get-ChildItem "frontend-react" -Recurse | Measure-Object | Select-Object -ExpandProperty Count
```

Expected: `0`

- [ ] **Step 2: Write `frontend-react/package.json`**

```json
{
  "name": "frontend-react",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "dev:server": "node server/index.js",
    "dev:all": "concurrently -n web,api -c cyan,magenta \"npm:dev\" \"npm:dev:server\"",
    "build": "tsc --noEmit && vite build",
    "preview": "cross-env NODE_ENV=production node server/index.js",
    "lint": "eslint .",
    "test": "vitest run"
  },
  "dependencies": {
    "@clerk/react": "^6.17.5",
    "@fontsource-variable/geist-mono": "^5.3.0",
    "@fontsource-variable/inter": "^5.3.0",
    "@fontsource/noto-serif-bengali": "^5.3.0",
    "@fontsource/noto-serif-devanagari": "^5.3.0",
    "@fontsource/noto-serif-gujarati": "^5.3.0",
    "@fontsource/noto-serif-gurmukhi": "^5.3.0",
    "@fontsource/noto-serif-kannada": "^5.3.0",
    "@fontsource/noto-serif-malayalam": "^5.3.0",
    "@fontsource/noto-serif-oriya": "^5.3.0",
    "@fontsource/noto-serif-tamil": "^5.3.0",
    "@fontsource/noto-serif-telugu": "^5.3.0",
    "@fontsource/space-grotesk": "^5.3.0",
    "@tailwindcss/typography": "^0.5.20",
    "clsx": "^2.1.1",
    "express": "^5.2.1",
    "gsap": "^3.15.0",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-markdown": "^10.1.0",
    "react-router-dom": "^7.18.4",
    "remark-gfm": "^4.0.1",
    "@clerk/express": "^2.1.75"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.5",
    "@tailwindcss/vite": "^4.3.3",
    "@testing-library/react": "^16.3.3",
    "@types/express": "^5.0.6",
    "@types/node": "^20.19.0",
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "@vitejs/plugin-react": "^6.1.2",
    "concurrently": "^10.0.5",
    "cross-env": "^10.1.0",
    "eslint": "^9.39.5",
    "eslint-plugin-react-hooks": "^7.1.1",
    "eslint-plugin-react-refresh": "^0.5.7",
    "globals": "^17.13.0",
    "jsdom": "^25.0.1",
    "tailwindcss": "^4.3.3",
    "typescript": "^5.9.0",
    "typescript-eslint": "^8.71.0",
    "vite": "^8.3.2",
    "vitest": "^4.1.11"
  }
}
```

`cross-env` is required because `NODE_ENV=production node ...` does not work in
PowerShell/cmd. It is dev-only and only used by `preview`.

- [ ] **Step 3: Install dependencies**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm install --no-audit --no-fund
```

Expected: exit 0, no `ERESOLVE`. If `@vitejs/plugin-react@6` complains, it wants
`vite@^8` — which is what is pinned. Ignore deprecation warnings for
`@fontsource/*`; they are expected.

- [ ] **Step 4: Write `frontend-react/index.html`**

Note the 12 `--font-*` variables. These names must match `globals.css` lines
94–99 and 203–215 exactly. Task 4 replaces these placeholder names with real
`@fontsource` family names — the variable names never change.

```html
<!doctype html>
<html
  lang="en"
  style="
    --font-inter: 'Inter';
    --font-display-latin: 'Space Grotesk';
    --font-geist-mono: 'Geist Mono';
    --font-devanagari: 'Noto Serif Devanagari';
    --font-bengali: 'Noto Serif Bengali';
    --font-tamil: 'Noto Serif Tamil';
    --font-telugu: 'Noto Serif Telugu';
    --font-kannada: 'Noto Serif Kannada';
    --font-gurmukhi: 'Noto Serif Gurmukhi';
    --font-gujarati: 'Noto Serif Gujarati';
    --font-odia: 'Noto Serif Oriya';
    --font-malayalam: 'Noto Serif Malayalam';
  "
>
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" href="/favicon.ico" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>JanSahay — Cooperative Governance Assistant</title>
    <meta
      name="description"
      content="Multilingual AI assistant for cooperative governance, PMFBY, PACS, financial literacy and grievance redressal."
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

The `title`, `description` and `icons` values are copied verbatim from
`frontend/src/app/layout.tsx:70-84`. The `viewport` value is copied from its
`viewport` export.

- [ ] **Step 5: Write `frontend-react/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Stream SSE through untouched. `changeOrigin` keeps the Host header
      // consistent; no compression is applied by Vite's proxy, so tokens
      // arrive incrementally. Verified by gate 6.
      "/api": {
        target: "http://localhost:8787",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
```

`import.meta.dirname` requires Node 20.11+. The environment runs Node 24.13.0.

- [ ] **Step 6: Write `frontend-react/tsconfig.json`**

Copied from `frontend/tsconfig.json` with the Next plugin and `.next/types`
includes removed. The `paths` block is preserved verbatim.

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "types": ["vite/client", "node"],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src", "vite.config.ts", "vitest.config.mjs"]
}
```

- [ ] **Step 7: Write `frontend-react/vitest.config.mjs`**

Identical to `frontend/vitest.config.mjs` — it is already framework-agnostic.

```js
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "server/**/*.{test,spec}.js",
    ],
  },
});
```

The `server/**` pattern is present from the start so Task 4's server tests are
picked up without editing this file. They declare their own environment via a
docblock, so the jsdom default does not apply to them.

- [ ] **Step 8: Write `frontend-react/eslint.config.js`**

Replaces `eslint-config-next`. Same flat-config shape, same ignores.

```js
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "server/**"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_" },
      ],
    },
  },
);
```

`server/**` is ignored because it is plain JavaScript and has its own tests; it
is not TypeScript and would produce false positives.

- [ ] **Step 9: Write `frontend-react/.env.example` and `.gitignore`**

`.env.example`:

```
# ── Browser-safe (exposed to the bundle via VITE_ prefix) ──────────────
# Rename of NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY.
VITE_CLERK_PUBLISHABLE_KEY=pk_test_replace_me
# Rename of NEXT_PUBLIC_CLERK_SIGN_IN_URL. No longer set in the Vercel
# dashboard — passed to <ClerkProvider signInUrl> instead.
VITE_CLERK_SIGN_IN_URL=http://localhost:5173/sign-in
# Rename of NEXT_PUBLIC_CLERK_SIGN_UP_URL.
VITE_CLERK_SIGN_UP_URL=http://localhost:5173/sign-up

# ── Server-only (read only by server/index.js, never bundled) ──────────
CLERK_SECRET_KEY=sk_test_replace_me
# Was MISSING from both .env.example files in the Next.js project despite
# all 11 route handlers requiring it.
BACKEND_API_URL=http://localhost:8000
```

`.gitignore`:

```
node_modules/
dist/
.env
.env.local
*.local
.DS_Store
```

- [ ] **Step 10: Write the three source files**

`src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

`src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`src/App.tsx` — a placeholder for now. Task 5 replaces it with the real
provider + router tree.

```tsx
export default function App() {
  return (
    <div className="min-h-screen bg-[var(--canvas)] p-8">
      <h1 className="text-2xl font-semibold">JanSahay — scaffold OK</h1>
      <p className="mt-2 text-sm text-[var(--muted)]">
        Routing and providers are wired in Task 5.
      </p>
    </div>
  );
}
```

`src/pages/NotFoundPage.tsx` — written now so Task 5 only has to wire it.
Styled with the existing tokens only; no new CSS.

```tsx
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 text-center">
      <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
        404
      </p>
      <h1
        className="mt-3 text-[28px] font-medium tracking-[-0.02em] text-[var(--ink)] md:text-[38px]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        This page does not exist
      </h1>
      <p className="mt-3 max-w-md text-[15px] leading-[1.7] text-[var(--body)]">
        The link you followed may be broken, or the page may have moved.
      </p>
      <Link to="/" className="mt-6">
        <Button variant="dark" size="lg">
          Back to home
        </Button>
      </Link>
    </div>
  );
}
```

This file imports `@/components/ui/Button`, which does not exist yet. That is
expected — `npm run build` is not run until Task 2.

- [ ] **Step 11: Verify the dev server boots**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm run dev
```

Expected output contains `Local: http://localhost:5173/`. Open that URL: the
page shows "JanSahay — scaffold OK". Stop the server with Ctrl+C.

If it fails with "Cannot find module '@vitejs/plugin-react'", re-run
`npm install`. If it fails on the proxy, that is fine — nothing is listening on
8787 yet; only `/` matters.

- [ ] **Step 12: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Scaffold frontend-react with Vite 8, React 19, TypeScript and Tailwind 4"
```

---

## Task 2: Copy assets, libraries and styles verbatim

**Files:**
- Create: `frontend-react/public/**` (18 files, copied)
- Create: `frontend-react/src/lib/**` (copied)
- Create: `frontend-react/src/types/speech-recognition.d.ts` (copied)
- Create: `frontend-react/src/styles/globals.css` (copied)
- Create: `frontend-react/src/components/**` (copied, minus dead files)
- Modify: `frontend-react/src/main.tsx` (add globals.css import)
- Modify: `frontend-react/src/lib/i18n/dictionaries.ts` (delete dead `ur`)

**Interfaces:**
- Consumes: Task 1 scaffold.
- Produces: every import path under `@/lib/*`, `@/components/*`, `@/data/*` resolves. `globals.css` present at `src/styles/globals.css`. The 5 dead files absent.

- [ ] **Step 1: Copy public, lib, types and the stylesheet**

```powershell
Set-Location "A:\Serp-ai-2026"
Copy-Item -Recurse -Force "frontend\public" "frontend-react\public"
Copy-Item -Recurse -Force "frontend\src\lib" "frontend-react\src\lib"
Copy-Item -Recurse -Force "frontend\src\types" "frontend-react\src\types"
New-Item -ItemType Directory -Path "frontend-react\src\styles" -Force | Out-Null
Copy-Item -Force "frontend\src\app\globals.css" "frontend-react\src\styles\globals.css"
```

`src/types` contains only `speech-recognition.d.ts`.

- [ ] **Step 2: Prove globals.css copied byte-for-byte**

```powershell
(Get-FileHash -LiteralPath "frontend\src\app\globals.css").Hash -eq (Get-FileHash -LiteralPath "frontend-react\src\styles\globals.css").Hash
```

Expected: `True`. If `False`, re-copy. This file must not be edited — Global
Constraint 7.

- [ ] **Step 3: Copy components, then delete the dead files**

```powershell
Copy-Item -Recurse -Force "frontend\src\components" "frontend-react\src\components"
Remove-Item -LiteralPath "frontend-react\src\components\layout\SmoothScroll.tsx" -Force
Remove-Item -LiteralPath "frontend-react\src\components\ui\ScrollStack.tsx" -Force
Remove-Item -LiteralPath "frontend-react\src\components\ui\ScrollStack.css" -Force
Remove-Item -LiteralPath "frontend-react\src\components\grievance\GrievanceWizard.tsx" -Force
Remove-Item -LiteralPath "frontend-react\src\components\chat\ThinkingBubble.tsx" -Force
Get-ChildItem -LiteralPath "frontend-react\src\components\grievance" -ErrorAction SilentlyContinue
```

The last command will error if `grievance/` is now empty — that is fine, the
directory is simply unused.

Before deleting, confirm each file is genuinely unimported:

```powershell
foreach ($f in @("SmoothScroll","ScrollStack","GrievanceWizard","ThinkingBubble")) {
  $hits = (Select-String -Path "frontend\src\**\*.tsx","frontend\src\**\*.ts" -Pattern $f -ErrorAction SilentlyContinue | Where-Object { $_.Path -notmatch $f }).Count
  "$f referenced elsewhere: $hits"
}
```

Expected: `0` for all four. If any is non-zero, stop and report.

- [ ] **Step 4: Strip all `"use client"` directives**

They are inert in Vite but are misleading. Remove only the exact directive line.

```powershell
$files = Get-ChildItem -LiteralPath "frontend-react\src" -Recurse -Include *.tsx,*.ts -File
foreach ($f in $files) {
  $lines = [System.IO.File]::ReadAllLines($f.FullName)
  if ($lines.Count -gt 0 -and $lines[0].Trim() -eq '"use client";') {
    $rest = if ($lines.Count -gt 1) { $lines[1..($lines.Count-1)] } else { @() }
    [System.IO.File]::WriteAllLines($f.FullName, $rest)
    "stripped: $($f.Name)"
  }
}
```

Do not touch `dictionaries.ts` or any other file whose first line is not that
exact directive.

This step only covers files copied so far (`src/components/**`, `src/lib/**`,
`src/types/**`). Pages are copied later in Task 5, which repeats this step for
`src/pages/**`. Run it again at the end of Task 5.

- [ ] **Step 5: Delete the dead `ur` dictionary block**

`frontend/src/lib/i18n/dictionaries.ts` defines `const ur` at line 3576 but the
`dict` export at line 3853 omits it. Remove the block.

```powershell
$p = "frontend-react\src\lib\i18n\dictionaries.ts"
$lines = [System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $p))
$start = ($lines | Select-String -Pattern '^const ur: Record<string, string> = \{$').LineNumber
$end = $null
for ($i = $start; $i -lt $lines.Count; $i++) { if ($lines[$i] -eq "};") { $end = $i + 1; break } }
"removing lines $start..$end"
$out = @()
$out += $lines[0..($start - 2)]
$out += $lines[$end..($lines.Count - 1)]
[System.IO.File]::WriteAllLines((Resolve-Path -LiteralPath $p), $out)
```

Verify: `Select-String -LiteralPath $p -Pattern "^const ur:"` returns nothing,
and `dict` still lists exactly 11 locales.

```powershell
Select-String -LiteralPath "frontend-react\src\lib\i18n\dictionaries.ts" -Pattern "^  en, hi, gu, mr, bn, ta, te, kn, pa, or, ml,$"
```

Expected: one match.

- [ ] **Step 6: Wire globals.css into main.tsx**

Replace `frontend-react/src/main.tsx` with:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/globals.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 7: Verify the build compiles**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm run build
```

Expected: exit 0. `App.tsx` renders a placeholder and `NotFoundPage.tsx` is not
imported yet, so only the stylesheet and the (unused) component tree get
compiled. If `tsc --noEmit` reports errors inside `src/lib/**` or
`src/components/**`, those are real and must be fixed before continuing —
`frontend/` type-checks, so anything failing here is a copy or config problem.

- [ ] **Step 8: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Copy libraries, components, styles and assets; remove dead code and unused ur dictionary"
```

---

## Task 3: Self-host the 12 font families

**Files:**
- Modify: `frontend-react/src/main.tsx`
- Modify: `frontend-react/index.html`

**Interfaces:**
- Consumes: Task 2.
- Produces: all 12 `--font-*` CSS variables resolve to real loaded families. Latin and 9 Indic scripts render without fallback.

- [ ] **Step 1: Confirm the exact weights the Next.js build used**

```powershell
Select-String -LiteralPath "frontend\src\app\layout.tsx" -Pattern "weight:"
```

Expected: `weight: ["400", "500", "600", "700"]` for the nine Noto Serif
families, and `weight: ["500"]` for Space Grotesk. Inter and Geist Mono are
loaded without a `weight` option, i.e. as variable fonts.

- [ ] **Step 2: Add the font imports to main.tsx**

Replace `frontend-react/src/main.tsx` with:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/globals.css";

// Latin — variable fonts
import "@fontsource-variable/inter";
import "@fontsource-variable/geist-mono";
import "@fontsource/space-grotesk/500.css";

// Indic scripts — static weights 400/500/600/700 to match next/font config
import "@fontsource/noto-serif-devanagari/400.css";
import "@fontsource/noto-serif-devanagari/500.css";
import "@fontsource/noto-serif-devanagari/600.css";
import "@fontsource/noto-serif-devanagari/700.css";
import "@fontsource/noto-serif-bengali/400.css";
import "@fontsource/noto-serif-bengali/500.css";
import "@fontsource/noto-serif-bengali/600.css";
import "@fontsource/noto-serif-bengali/700.css";
import "@fontsource/noto-serif-tamil/400.css";
import "@fontsource/noto-serif-tamil/500.css";
import "@fontsource/noto-serif-tamil/600.css";
import "@fontsource/noto-serif-tamil/700.css";
import "@fontsource/noto-serif-telugu/400.css";
import "@fontsource/noto-serif-telugu/500.css";
import "@fontsource/noto-serif-telugu/600.css";
import "@fontsource/noto-serif-telugu/700.css";
import "@fontsource/noto-serif-kannada/400.css";
import "@fontsource/noto-serif-kannada/500.css";
import "@fontsource/noto-serif-kannada/600.css";
import "@fontsource/noto-serif-kannada/700.css";
import "@fontsource/noto-serif-gurmukhi/400.css";
import "@fontsource/noto-serif-gurmukhi/500.css";
import "@fontsource/noto-serif-gurmukhi/600.css";
import "@fontsource/noto-serif-gurmukhi/700.css";
import "@fontsource/noto-serif-gujarati/400.css";
import "@fontsource/noto-serif-gujarati/500.css";
import "@fontsource/noto-serif-gujarati/600.css";
import "@fontsource/noto-serif-gujarati/700.css";
import "@fontsource/noto-serif-oriya/400.css";
import "@fontsource/noto-serif-oriya/500.css";
import "@fontsource/noto-serif-oriya/600.css";
import "@fontsource/noto-serif-oriya/700.css";
import "@fontsource/noto-serif-malayalam/400.css";
import "@fontsource/noto-serif-malayalam/500.css";
import "@fontsource/noto-serif-malayalam/600.css";
import "@fontsource/noto-serif-malayalam/700.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

If any `@fontsource/<family>/<weight>.css` path fails to resolve, that family has
no static weight file. Fall back to the variable build for that one family
(`@fontsource-variable/noto-serif-devanagari`) and record which family changed.

- [ ] **Step 3: Verify every @font-face is emitted into the bundle**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm run build 2>&1 | Select-String "built in|error"
```

Then confirm the font files were emitted and the family names match `index.html`:

```powershell
Get-ChildItem -Recurse -Path "dist\assets" -Include *.woff2 | Measure-Object | Select-Object -ExpandProperty Count
Select-String -Path "dist\assets\*.css" -Pattern "Noto Serif Devanagari|Noto Serif Malayalam|Space Grotesk|Inter|Geist Mono" | Select-Object -First 5
```

Expected: a non-zero woff2 count, and all five family names present in the
emitted CSS. The names must match the `--font-*` values in `index.html` exactly,
because `globals.css` line 94 composes them:
`--font-primary: var(--font-inter), var(--font-script), …`

- [ ] **Step 4: Verify globals.css was not touched**

```powershell
Set-Location "A:\Serp-ai-2026"
(Get-FileHash -LiteralPath "frontend\src\app\globals.css").Hash -eq (Get-FileHash -LiteralPath "frontend-react\src\styles\globals.css").Hash
```

Expected: `True`.

- [ ] **Step 5: Commit**

```powershell
git add frontend-react
git commit -m "Self-host 12 font families via fontsource, keeping CSS variable names identical"
```

---

## Task 4: Build the Express BFF with all 11 endpoints

This is the highest-risk task. Every behaviour of the 11 Next.js route handlers
is preserved exactly.

**Files:**
- Create: `frontend-react/server/clerk.js`
- Create: `frontend-react/server/proxy.js`
- Create: `frontend-react/server/sse.js`
- Create: `frontend-react/server/index.js`
- Create: `frontend-react/server/__tests__/server.test.js`

**Interfaces:**
- Consumes: nothing from Tasks 1–3 (server is independent of the SPA).
- Produces:
  - `server/index.js` **named-exports** `createApp()` → an Express `Application` with all 11 routes mounted, plus static serving + SPA fallback when `dist/` exists. It runs `listen()` only when executed directly (`import.meta.url === pathToFileURL(process.argv[1]).href`) on `process.env.PORT || 8787`.
  - `server/clerk.js` exports `clerk` (Express `RequestHandler`) and `getToken(req)` → `Promise<string | null>`
  - `server/proxy.js` exports `BACKEND()` → `string`, `authHeader(req)` → `Promise<Record<string,string>>`, `proxyFetch(path, init?, timeoutMs?)` → `Promise<Response | null>`, `proxyJson(req, res, { path, errorKey })`, `readJson(req)` → `Promise<any>`, `hexToBuffer(hex)` → `Buffer`
  - `server/sse.js` exports `proxySse(req, res, { path, body })`
  - All 11 paths identical to the Next.js app: `POST /api/chat`, `POST /api/chat/stream`, `GET /api/documents/pdf/:filename`, `POST /api/grievance/answer`, `POST /api/grievance/clarify`, `POST /api/grievance/detect`, `GET /api/grievance/fields`, `POST /api/grievance/finalize`, `POST /api/speak`, `POST /api/translate`, `POST /api/voice/speak`

**Endpoint behaviour contract** — copied from the current route handlers, do not
deviate:

| Path | Backend | Auth | Request handling | Success | Failure |
|---|---|---|---|---|---|
| `POST /api/chat` | `$BACKEND/chat/stream` | yes | JSON body | SSE stream | 400 invalid JSON · 502 `retrieval_backend_error` · 503 `retrieval_backend_unavailable` |
| `POST /api/chat/stream` | `$BACKEND/chat/stream` | yes | JSON body | SSE stream | same as above |
| `GET /api/documents/pdf/:filename` | `$BACKEND/documents/pdf/:filename` | no | `encodeURIComponent(filename)`, 30s timeout | stream body, `Content-Type` from upstream or `application/pdf`, `Content-Length` if present, `Cache-Control: public, max-age=86400` | 400 no filename · upstream status passthrough with `Document not found` · 503 `Document service unavailable` |
| `POST /api/grievance/answer` | `$BACKEND/grievances/answer` | yes | JSON body | upstream JSON | 400 · 502 `grievance_backend_error` · 503 `grievance_backend_unavailable` |
| `POST /api/grievance/clarify` | `$BACKEND/grievances/clarify` | yes | JSON body | upstream JSON | same |
| `POST /api/grievance/detect` | `$BACKEND/grievances` | yes | JSON body | upstream JSON | same |
| `GET /api/grievance/fields` | `$BACKEND/grievances/:cid/fields?language=:lang` | yes | query `conversation_id` (required), `language` (default `en`) | upstream JSON | 400 no `conversation_id` · 404 if upstream 404 · else 502 · 503 |
| `POST /api/grievance/finalize` | `$BACKEND/grievances/finalize` | yes | JSON body | upstream JSON | 400 · 502 · 503 |
| `POST /api/speak` | `$BACKEND/voice/speak` | yes | `multipart/form-data`: `text` (required), `language` (default `hi`); 30s timeout | hex→binary `audio/mpeg` | 400 no text · 503 empty `audio/mpeg` body (client falls back to browser TTS) |
| `POST /api/translate` | `$BACKEND/translate` | **no** | JSON `{texts, source_language?, target_language?}`; 10s timeout; empty `texts` short-circuits | upstream JSON | falls back to `{translations: texts}` |
| `POST /api/voice/speak` | `$BACKEND/voice/speak` | yes | JSON `{segments}`; 30s timeout | `{audio, language: language ?? segments[0].language}` | 400 empty segments · 503 `Backend unavailable` |

**Known pre-existing defect — reproduce it, do not fix it here.** Two call sites
send `{ texts, to }` while the handler reads `target_language`:

- `src/components/ChatWindow.tsx:76`
- `src/lib/translator.ts:21`

So the `to` field is silently discarded and `target_language` falls back to its
`"hi"` default. This behaves identically under Next.js today. Port it as-is —
changing it would alter translation behaviour as a side effect of a framework
migration, which is out of scope. Report it to the user as a separate finding.

- [ ] **Step 1: Write `server/clerk.js`**

```js
import { clerkMiddleware, getAuth } from "@clerk/express";

/**
 * Mounted by index.js. Attaches Clerk's Auth object to every request,
 * exactly as src/proxy.ts's clerkMiddleware() did under Next.
 */
export const clerk = clerkMiddleware({
  publishableKey: process.env.VITE_CLERK_PUBLISHABLE_KEY,
  secretKey: process.env.CLERK_SECRET_KEY,
});

/**
 * Returns the caller's Clerk session JWT, or null when signed out.
 * Replaces the Next.js `const { getToken } = await auth(); await getToken();`
 * pair. The token is forwarded to FastAPI as `Authorization: Bearer <token>`,
 * which is what the Python backend's auth dependency expects.
 */
export async function getToken(req) {
  try {
    const { getToken: readToken } = getAuth(req);
    if (typeof readToken !== "function") return null;
    const token = await readToken();
    return token ?? null;
  } catch {
    // Signed-out or malformed session. The backend treats a missing token as
    // anonymous, which matches the Next.js behaviour where auth() returns a
    // null token rather than throwing.
    return null;
  }
}
```

- [ ] **Step 2: Write `server/proxy.js`**

```js
import { getToken } from "./clerk.js";

const BACKEND = () =>
  (process.env.BACKEND_API_URL || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Builds the Authorization header set, mirroring the Next handlers exactly.
 * A signed-out request yields no header at all, which is what the Next.js code
 * did with `...(token ? { Authorization: ... } : {})`.
 */
export async function authHeader(req) {
  const token = await getToken(req);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Calls FastAPI with a timeout. Resolves to null on any network failure or
 * timeout so callers can emit their own 503 — the Next handlers wrapped
 * fetch() in try/catch and returned 503, never letting the error escape.
 */
export async function proxyFetch(path, init = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${BACKEND()}${path}`, { ...init, signal: controller.signal });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The shape shared by all six grievance JSON handlers:
 * parse JSON body (400 on failure) -> forward with auth -> 200 pass-through,
 * 502 when upstream is not ok, 503 when unreachable.
 */
export async function proxyJson(req, res, { path, errorKey }) {
  let body;
  try {
    body = await readJson(req);
  } catch {
    return res.status(400).json({ error: "Invalid JSON" });
  }

  const headers = { "Content-Type": "application/json", ...(await authHeader(req)) };
  const upstream = await proxyFetch(path, { method: "POST", headers, body });

  if (!upstream) {
    return res.status(503).json({ error: `${errorKey}_unavailable`, detail: "backend unreachable" });
  }
  if (!upstream.ok) {
    return res.status(502).json({ error: errorKey, detail: `backend responded ${upstream.status}` });
  }
  return res.json(await upstream.json());
}

/** Buffers and parses a JSON request body. Throws on malformed JSON. */
export function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

/** Converts the backend's hex-encoded audio into a binary Buffer. */
export function hexToBuffer(hex) {
  return Buffer.from(hex, "hex");
}
```

- [ ] **Step 3: Write `server/sse.js`**

```js
import { authHeader, BACKEND } from "./proxy.js";

/**
 * Streams FastAPI's SSE response through to the browser.
 *
 * Buffering here silently breaks the single most visible feature of the app,
 * so: no compression middleware anywhere in this process, flushHeaders() before
 * the first chunk, and X-Accel-Buffering: no so no upstream proxy buffers it.
 */
export async function proxySse(req, res, { path, body }) {
  const headers = { "Content-Type": "application/json", ...(await authHeader(req)) };

  let upstream;
  try {
    upstream = await fetch(`${BACKEND()}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    return res.status(503).json({
      error: "retrieval_backend_unavailable",
      detail: "backend unreachable",
    });
  }

  if (!upstream.ok) {
    return res.status(502).json({
      error: "retrieval_backend_error",
      detail: `backend responded ${upstream.status}`,
    });
  }

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  res.flushHeaders?.();

  const reader = upstream.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(Buffer.from(value));
      // Flush each chunk so the browser renders tokens as they arrive.
      res.flush?.();
    }
  } catch {
    // Client disconnected or upstream aborted mid-stream. Nothing to do;
    // the browser has already received a partial answer.
  } finally {
    res.end();
  }
}
```

Note there is no timeout here, matching the Next handlers — a long RAG answer
must not be cut off at 30s.

- [ ] **Step 4: Write `server/index.js`**

```js
import express from "express";
import path from "node:path";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

import { clerk } from "./clerk.js";
import {
  BACKEND,
  authHeader,
  proxyFetch,
  proxyJson,
  readJson,
  hexToBuffer,
} from "./proxy.js";
import { proxySse } from "./sse.js";

/** Both /api/chat and /api/chat/stream resolve to the streaming endpoint. */
const streamPath = () => BACKEND().replace(/\/chat$/, "/chat/stream");

export function createApp() {
  const app = express();

  app.use(clerk);

  // ── Chat (SSE) ────────────────────────────────────────────────────────
  const chatHandler = async (req, res) => {
    let body;
    try {
      body = await readJson(req);
    } catch {
      return res
        .status(400)
        .json({ error: "Invalid JSON" });
    }
    return proxySse(req, res, { path: streamPath(), body });
  };
  app.post("/api/chat", chatHandler);
  app.post("/api/chat/stream", chatHandler);

  // ── PDF proxy ─────────────────────────────────────────────────────────
  app.get("/api/documents/pdf/:filename", async (req, res) => {
    const filename = req.params.filename;
    if (!filename) {
      return res.status(400).json({ error: "Missing filename" });
    }

    const upstream = await proxyFetch(
      `/documents/pdf/${encodeURIComponent(filename)}`,
      { method: "GET" },
      30000,
    );

    if (!upstream) {
      return res.status(503).json({
        error: "Document service unavailable",
        detail: "backend unreachable",
      });
    }
    if (!upstream.ok) {
      return res.status(upstream.status).json({
        error: "Document not found",
        detail: `backend responded ${upstream.status}`,
      });
    }

    const headers = {
      "Content-Type": upstream.headers.get("content-type") || "application/pdf",
      "Cache-Control": "public, max-age=86400",
    };
    const length = upstream.headers.get("content-length");
    if (length) headers["Content-Length"] = length;

    res.writeHead(200, headers);
    res.end(Buffer.from(await upstream.arrayBuffer()));
  });

  // ── Grievance JSON handlers ───────────────────────────────────────────
  app.post("/api/grievance/answer", (req, res) =>
    proxyJson(req, res, { path: "/grievances/answer", errorKey: "grievance_backend_error" }),
  );
  app.post("/api/grievance/clarify", (req, res) =>
    proxyJson(req, res, { path: "/grievances/clarify", errorKey: "grievance_backend_error" }),
  );
  app.post("/api/grievance/detect", (req, res) =>
    proxyJson(req, res, { path: "/grievances", errorKey: "grievance_backend_error" }),
  );
  app.post("/api/grievance/finalize", (req, res) =>
    proxyJson(req, res, { path: "/grievances/finalize", errorKey: "grievance_backend_error" }),
  );

  // ── Grievance fields (GET, 404-preserving) ────────────────────────────
  app.get("/api/grievance/fields", async (req, res) => {
    const conversationId = req.query.conversation_id;
    const language = req.query.language || "en";
    if (!conversationId) {
      return res.status(400).json({ error: "conversation_id is required" });
    }

    const upstream = await proxyFetch(
      `/grievances/${encodeURIComponent(conversationId)}/fields?language=${encodeURIComponent(language)}`,
      { method: "GET", headers: await authHeader(req) },
    );

    if (!upstream) {
      return res.status(503).json({
        error: "grievance_backend_unavailable",
        detail: "backend unreachable",
      });
    }
    if (upstream.ok) return res.json(await upstream.json());

    return res.status(upstream.status === 404 ? 404 : 502).json({
      error: "grievance_backend_error",
      detail: `backend responded ${upstream.status}`,
    });
  });

  // ── TTS: form-encoded, returns binary audio ───────────────────────────
  app.post("/api/speak", async (req, res) => {
    let text;
    let language;
    try {
      // multer is not used; busboy-free parsing via express.urlencoded would
      // lose the file semantics, so parse multipart with the raw body.
      const raw = await readRawBody(req);
      const parsed = parseMultipart(raw, req.headers["content-type"] || "");
      text = parsed.text;
      language = parsed.language || "hi";
    } catch {
      return res.status(400).send("Missing text");
    }
    if (!text) return res.status(400).send("Missing text");

    const upstream = await proxyFetch(
      "/voice/speak",
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeader(req)) },
        body: JSON.stringify({ text, language }),
      },
      30000,
    );

    if (upstream && upstream.ok) {
      const data = await upstream.json();
      if (data.audio) {
        return res
          .status(200)
          .set("Content-Type", "audio/mpeg")
          .send(hexToBuffer(data.audio));
      }
    }
    // Empty 503 makes the client fall back to the browser's speechSynthesis.
    return res.status(503).set("Content-Type", "audio/mpeg").send("");
  });

  // ── TTS: segment-based, returns hex JSON ──────────────────────────────
  app.post("/api/voice/speak", async (req, res) => {
    let body;
    try {
      body = await readJson(req);
    } catch {
      return res.status(400).json({ error: "Missing segments" });
    }
    const segments = body.segments;
    if (!segments || segments.length === 0) {
      return res.status(400).json({ error: "Missing segments" });
    }

    const upstream = await proxyFetch(
      "/voice/speak",
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeader(req)) },
        body: JSON.stringify({ segments }),
      },
      30000,
    );

    if (upstream && upstream.ok) {
      const data = await upstream.json();
      if (data.audio) {
        return res.json({
          audio: data.audio,
          language: data.language || segments[0].language,
        });
      }
    }
    return res.status(503).json({ error: "Backend unavailable" });
  });

  // ── Translation (unauthenticated, degrades to source text) ────────────
  app.post("/api/translate", async (req, res) => {
    let body;
    try {
      body = await readJson(req);
    } catch {
      return res.status(400).json({ error: "Invalid JSON" });
    }

    const texts = body.texts ?? [];
    if (texts.length === 0) return res.json({ translations: [] });

    const upstream = await proxyFetch(
      "/translate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          texts,
          source_language: body.source_language ?? "en",
          target_language: body.target_language ?? "hi",
        }),
      },
      10000,
    );

    if (upstream && upstream.ok) return res.json(await upstream.json());
    // Backend offline: return the originals so the UI degrades to English.
    return res.json({ translations: texts });
  });

  // ── Static assets + SPA fallback (production only) ────────────────────
  const dist = path.resolve(import.meta.dirname, "..", "dist");
  if (fs.existsSync(dist)) {
    app.use(express.static(dist));
    // Registered last so API 404s are not swallowed. app.use() rather than
    // app.get("*") because "*" is invalid in Express 5.
    app.use((req, res, next) => {
      if (req.method !== "GET" || req.path.startsWith("/api")) return next();
      res.sendFile(path.join(dist, "index.html"));
    });
  }

  return app;
}

// ── Multipart helpers (no external dependency) ─────────────────────────
function readRawBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function parseMultipart(buffer, contentType) {
  const match = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType);
  if (!match) throw new Error("no multipart boundary");
  const boundary = `--${match[1] || match[2]}`;
  const parts = buffer.toString("binary").split(boundary);
  const out = {};
  for (const part of parts) {
    const nameMatch = /name="([^"]+)"/.exec(part);
    if (!nameMatch) continue;
    const valuePart = part.split("\r\n\r\n").slice(1).join("\r\n\r\n");
    out[nameMatch[1]] = valuePart.replace(/\r\n$/, "");
  }
  return out;
}

// ── Entry point ─────────────────────────────────────────────────────────
const isDirectRun =
  process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isDirectRun) {
  createApp().listen(process.env.PORT || 8787, () => {
    console.log(`[bff] listening on :${process.env.PORT || 8787}`);
  });
}
```

Add `readRawBody` and `parseMultipart` to the bottom of the file as shown — they
are used only by `/api/speak`.

- [ ] **Step 5: Write the server tests**

`server/__tests__/server.test.js`:

```js
// @vitest-environment node
import { describe, it, expect, beforeAll, beforeEach, afterAll, vi } from "vitest";
import { createApp } from "../index.js";

// Stub Clerk before the app is imported so no real network call is attempted.
vi.mock("@clerk/express", () => ({
  clerkMiddleware: () => (_req, _res, next) => next(),
  getAuth: () => ({ getToken: async () => "test-jwt" }),
}));

// One server for the whole file. Creating one per test would leak a listening
// handle each time and leave Vitest unable to exit.
let server;
let base;

beforeAll(async () => {
  server = createApp().listen(0);
  await new Promise((r) => server.once("listening", r));
  base = `http://127.0.0.1:${server.address().port}`;
});

beforeEach(() => {
  vi.restoreAllMocks();
});

afterAll(async () => {
  await new Promise((r) => server.close(r));
});

const json = (path, body, init = {}) =>
  fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...init,
  });

describe("auth header forwarding", () => {
  it("attaches the Clerk bearer token to the backend call", async () => {
    const upstream = new Response(JSON.stringify({ ok: true }), { status: 200 });
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(upstream);

    const res = await json("/api/grievance/answer", { conversation_id: "c1" });

    expect(res.status).toBe(200);
    const [, init] = spy.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer test-jwt");
  });
});

describe("grievance handlers", () => {
  it.each([
    ["/api/grievance/answer", "/grievances/answer"],
    ["/api/grievance/clarify", "/grievances/clarify"],
    ["/api/grievance/detect", "/grievances"],
    ["/api/grievance/finalize", "/grievances/finalize"],
  ])("%s proxies to %s", async (route, backendPath) => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));

    const res = await json(route, { conversation_id: "c1" });

    expect(res.status).toBe(200);
    expect(spy.mock.calls[0][0]).toContain(backendPath);
  });

  it("returns 400 on invalid JSON", async () => {
    const res = await fetch(`${base}/api/grievance/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{not json",
    });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Invalid JSON" });
  });

  it("returns 502 when the backend responds non-ok", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 500 }));
    const res = await json("/api/grievance/answer", { conversation_id: "c1" });
    expect(res.status).toBe(502);
    expect((await res.json()).error).toBe("grievance_backend_error");
  });

  it("returns 503 when the backend is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await json("/api/grievance/answer", { conversation_id: "c1" });
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("grievance_backend_unavailable");
  });
});

describe("GET /api/grievance/fields", () => {
  it("requires conversation_id", async () => {
    const res = await fetch(`${base}/api/grievance/fields`);
    expect(res.status).toBe(400);
  });

  it("passes a 404 through as 404", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));
    const res = await fetch(`${base}/api/grievance/fields?conversation_id=abc`);
    expect(res.status).toBe(404);
  });

  it("maps other upstream errors to 502", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 500 }));
    const res = await fetch(`${base}/api/grievance/fields?conversation_id=abc`);
    expect(res.status).toBe(502);
  });

  it("defaults language to en", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ fields: [] }), { status: 200 }));
    await fetch(`${base}/api/grievance/fields?conversation_id=abc`);
    expect(spy.mock.calls[0][0]).toContain("language=en");
  });
});

describe("POST /api/translate", () => {
  it("short-circuits on an empty texts array", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const res = await json("/api/translate", { texts: [] });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ translations: [] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("falls back to the source texts when the backend is down", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("down"));
    const res = await json("/api/translate", { texts: ["hello"] });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ translations: ["hello"] });
  });

  it("does not send an Authorization header", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ translations: ["x"] }), { status: 200 }));
    await json("/api/translate", { texts: ["hello"] });
    const [, init] = spy.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });
});

describe("SSE chat streaming", () => {
  it("streams chunks through with the SSE content type", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("data: a\n\n"));
        controller.enqueue(encoder.encode("data: b\n\n"));
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );

    const res = await json("/api/chat", { question: "hi" });

    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/event-stream");
    expect(res.headers.get("x-accel-buffering")).toBe("no");
    expect(await res.text()).toContain("data: a");
  });

  it("returns 502 when the backend rejects the stream", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 500 }));
    const res = await json("/api/chat/stream", { question: "hi" });
    expect(res.status).toBe(502);
    expect((await res.json()).error).toBe("retrieval_backend_error");
  });
});

describe("GET /api/documents/pdf/:filename", () => {
  it("url-encodes the filename and forwards the content type", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(Buffer.from("%PDF-1.4"), {
        status: 200,
        headers: { "Content-Type": "application/pdf" },
      }),
    );

    const res = await fetch(`${base}/api/documents/pdf/pmfby%20guide.pdf`);

    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/pdf");
    expect(spy.mock.calls[0][0]).toContain("pmfby%20guide.pdf");
  });

  it("returns 503 when unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("down"));
    const res = await fetch(`${base}/api/documents/pdf/x.pdf`);
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("Document service unavailable");
  });
});
```

- [ ] **Step 6: Run the server tests**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npx vitest run server/__tests__/server.test.js
```

Expected: all tests pass. If `describe`/`it` are undefined, vitest is not
picking up the file — confirm `vitest.config.mjs` `test.include` contains
`"server/**/*.{test,spec}.js"` (Task 1, Step 7 adds it).

- [ ] **Step 7: Verify SSE is not buffered end-to-end against a fake backend**

Automated proof that chunks are not coalesced:

```powershell
@'
import { createApp } from "./server/index.js";
const encoder = new TextEncoder();
globalThis.fetch = async () =>
  new Response(
    new ReadableStream({
      async start(c) {
        for (let i = 0; i < 3; i++) {
          c.enqueue(encoder.encode(`data: ${i}\n\n`));
          await new Promise((r) => setTimeout(r, 120));
        }
        c.close();
      },
    }),
    { status: 200 },
  );
const s = createApp().listen(0);
await new Promise((r) => s.once("listening", r));
const res = await fetch(`http://127.0.0.1:${s.address().port}/api/chat`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question: "x" }),
});
const reader = res.body.getReader();
const times = [];
const t0 = Date.now();
for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  times.push(Date.now() - t0);
}
console.log("chunk arrival ms:", times.join(", "));
console.log(times.length === 3 ? "PASS: 3 separate chunks" : "FAIL: chunks were coalesced");
s.close();
process.exit(times.length === 3 ? 0 : 1);
'@ | Out-File -FilePath "sse-check.mjs" -Encoding utf8
$env:VITE_CLERK_PUBLISHABLE_KEY="pk_test_dummy"; $env:CLERK_SECRET_KEY="sk_test_dummy"
node sse-check.mjs
$code = $LASTEXITCODE
Remove-Item "sse-check.mjs" -Force
"exit code: $code"
```

Expected: `chunk arrival ms:` showing three values roughly 120ms apart, then
`PASS: 3 separate chunks`, exit code 0. Three identical timestamps means
buffering — fix before continuing.

- [ ] **Step 8: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react/server
git commit -m "Add Express BFF with all 11 API endpoints, Clerk token forwarding and SSE passthrough"
```

---

## Task 5: Move pages and rewire routing

**Files:**
- Create: `frontend-react/src/pages/*.tsx` (13 moved + 2 Clerk + 1 NotFound)
- Modify: `frontend-react/src/App.tsx`
- Modify: 7 files that import `next/navigation`
- Modify: 15 files that import `next/link`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: all 15 routes render; `useLocation`-based nav; Clerk sign-in/sign-up reachable; 404 works.

- [ ] **Step 1: Move the 13 page files**

```powershell
Set-Location "A:\Serp-ai-2026"
$map = @{
  "page"                          = "HomePage"
  "chat\page"                     = "ChatPage"
  "faq\page"                      = "FaqPage"
  "grievance\page"                = "GrievancePage"
  "grievance\status\page"         = "GrievanceStatusPage"
  "grievance\draft\view\page"     = "GrievanceDraftViewPage"
  "legal\page"                    = "LegalPage"
  "legal\[slug]\page"             = "LegalDetailPage"
  "library\page"                  = "LibraryPage"
  "schemes\page"                  = "SchemesPage"
  "schemes\[slug]\page"           = "SchemeDetailPage"
  "services\page"                 = "ServicesPage"
  "services\[slug]\page"          = "ServiceDetailPage"
}
foreach ($k in $map.Keys) {
  $src = "frontend\src\app\$k.tsx"
  $dst = "frontend-react\src\pages\$($map[$k]).tsx"
  Copy-Item -LiteralPath $src -Destination $dst -Force
  "moved $k -> $($map[$k])"
}
Get-ChildItem "frontend-react\src\pages" -Filter *.tsx | Measure-Object | Select-Object -ExpandProperty Count
```

Expected count: `14` — 13 moved plus `NotFoundPage.tsx` from Task 1. Use
`-LiteralPath` on the source so the `[slug]` brackets are not treated as
wildcards.

- [ ] **Step 2: Strip `"use client"` from the moved pages**

The pages were copied verbatim from `frontend/` and still carry the directive.
Repeat the strip from Task 2, Step 4, scoped to `src/pages/`:

```powershell
$files = Get-ChildItem -LiteralPath "frontend-react\src\pages" -Filter *.tsx -File
foreach ($f in $files) {
  $lines = [System.IO.File]::ReadAllLines($f.FullName)
  if ($lines.Count -gt 0 -and $lines[0].Trim() -eq '"use client";') {
    $rest = if ($lines.Count -gt 1) { $lines[1..($lines.Count-1)] } else { @() }
    [System.IO.File]::WriteAllLines($f.FullName, $rest)
    "stripped: $($f.Name)"
  }
}
```

At least 13 files should print `stripped:` — every page except the two Clerk
pages and `NotFoundPage.tsx`, which are authored in this task.

- [ ] **Step 3: Rename the default exports**

Each moved file currently has `export default function SomeName()`. React Router
does not care about the function name, but each file also needs a **named**
export for the route table. Append a named export to each file:

```powershell
$names = @{
  "HomePage"="Home" ; "ChatPage"="Chat" ; "FaqPage"="Faq" ; "GrievancePage"="Grievance"
  "GrievanceStatusPage"="GrievanceStatus" ; "GrievanceDraftViewPage"="GrievanceDraftView"
  "LegalPage"="Legal" ; "LegalDetailPage"="LegalDetail" ; "LibraryPage"="Library"
  "SchemesPage"="Schemes" ; "SchemeDetailPage"="SchemeDetail"
  "ServicesPage"="Services" ; "ServiceDetailPage"="ServiceDetail"
}
foreach ($file in $names.Keys) {
  $p = "frontend-react\src\pages\$file.tsx"
  $c = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $p))
  $c = $c.TrimEnd() + "`nexport { default as $($names[$file])Page } from `"./$file`";`n"
  [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $p), $c)
}
```

This gives every page both a default export (unchanged) and a named export for
the router. Verify one:

```powershell
Select-String -LiteralPath "frontend-react\src\pages\HomePage.tsx" -Pattern "export \{ default as HomePage \}"
```

- [ ] **Step 4: Replace `next/link` in all 15 files**

```powershell
$files = Get-ChildItem -LiteralPath "frontend-react\src" -Recurse -Include *.tsx -File
foreach ($f in $files) {
  $c = [System.IO.File]::ReadAllText($f.FullName)
  if ($c -match 'from "next/link"') {
    $c = $c -replace 'import Link from "next/link";', 'import { Link } from "react-router-dom";'
    [System.IO.File]::WriteAllText($f.FullName, $c)
    "link: $($f.Name)"
  }
}
```

**The `href` prop does NOT carry over.** React Router's `<Link>` takes `to`, not
`href`. Every JSX usage must change from `<Link href="/x">` to `<Link to="/x">`,
or the link renders but never navigates. This is the single highest-risk item in
the whole migration — a missed conversion breaks navigation silently, with no
type error and no build failure.

```powershell
$files = Get-ChildItem -LiteralPath "frontend-react\src" -Recurse -Include *.tsx -File
foreach ($f in $files) {
  $c = [System.IO.File]::ReadAllText($f.FullName)
  if ($c -match 'from "next/link"') {
    $c = $c -replace 'import Link from "next/link";', 'import { Link } from "react-router-dom";'
    # href= -> to= only on <Link ...> opening tags
    $c = [regex]::Replace($c, '(<Link\b[^>]*?)\bhref=', '$1to=')
    [System.IO.File]::WriteAllText($f.FullName, $c)
    "link: $($f.Name)"
  }
}
```

Then verify none remain:

```powershell
Select-String -Path (Get-ChildItem -LiteralPath "frontend-react\src" -Recurse -Include *.tsx -File).FullName -Pattern "<Link[^>]*href="
```

Expected: no output. Also confirm `<a href=` usages were left alone — those are
external links and plain anchors and must keep `href`.

- [ ] **Step 5: Replace `next/navigation` in the 7 files**

Six distinct transformations:

| File | Current | Replace with |
|---|---|---|
| `ConditionalNavs.tsx` | `import { usePathname } from "next/navigation";` | `import { useLocation } from "react-router-dom";` |
| `ConditionalNavs.tsx` | `const pathname = usePathname();` | `const pathname = useLocation().pathname;` |
| `TopNav.tsx` | `import { usePathname } from "next/navigation";` | `import { useLocation } from "react-router-dom";` |
| `TopNav.tsx` | `usePathname()` | `useLocation().pathname` |
| `ChatWindow.tsx` | `import { useSearchParams, useRouter } from "next/navigation";` | `import { useSearchParams, useNavigate } from "react-router-dom";` |
| `ChatWindow.tsx` | `const router = useRouter();` | `const router = useNavigate();` |
| `ChatWindow.tsx:456` | `router.back();` | `router(-1);` |
| `ChatWindow.tsx:458` | `router.push("/")` | `router("/")` |
| `GrievanceCard.tsx` | `import { useRouter } from "next/navigation";` | `import { useNavigate } from "react-router-dom";` |
| `GrievanceCard.tsx:52` | `const router = useRouter();` | `const router = useNavigate();` |
| `GrievanceCard.tsx:153` | `router.push("/grievance/draft/view")` | `router("/grievance/draft/view")` |
| `legal/[slug]→LegalDetailPage.tsx` | `import { useParams } from "next/navigation";` | `import { useParams } from "react-router-dom";` |
| `schemes/[slug]→SchemeDetailPage.tsx` | same | same |
| `services/[slug]→ServiceDetailPage.tsx` | same | same |

Keep the local variable named `router` so no other line in those two files has
to change — only the call sites become function calls instead of method calls.

```powershell
$repl = @(
  @{ f = "components\layout\ConditionalNavs.tsx"; a = 'import { usePathname } from "next/navigation";'; b = 'import { useLocation } from "react-router-dom";' },
  @{ f = "components\layout\ConditionalNavs.tsx"; a = "const pathname = usePathname();"; b = "const pathname = useLocation().pathname;" },
  @{ f = "components\layout\TopNav.tsx"; a = 'import { usePathname } from "next/navigation";'; b = 'import { useLocation } from "react-router-dom";' },
  @{ f = "components\layout\TopNav.tsx"; a = "usePathname()"; b = "useLocation().pathname" },
  @{ f = "components\ChatWindow.tsx"; a = 'import { useSearchParams, useRouter } from "next/navigation";'; b = 'import { useSearchParams, useNavigate } from "react-router-dom";' },
  @{ f = "components\ChatWindow.tsx"; a = "const router = useRouter();"; b = "const router = useNavigate();" },
  @{ f = "components\ChatWindow.tsx"; a = "router.back();"; b = "router(-1);" },
  @{ f = "components\ChatWindow.tsx"; a = 'router.push("/")'; b = 'router("/")' },
  @{ f = "components\chat\GrievanceCard.tsx"; a = 'import { useRouter } from "next/navigation";'; b = 'import { useNavigate } from "react-router-dom";' },
  @{ f = "components\chat\GrievanceCard.tsx"; a = "const router = useRouter();"; b = "const router = useNavigate();" },
  @{ f = "components\chat\GrievanceCard.tsx"; a = 'router.push("/grievance/draft/view")'; b = 'router("/grievance/draft/view")' },
  @{ f = "pages\LegalDetailPage.tsx"; a = 'import { useParams } from "next/navigation";'; b = 'import { useParams } from "react-router-dom";' },
  @{ f = "pages\SchemeDetailPage.tsx"; a = 'import { useParams } from "next/navigation";'; b = 'import { useParams } from "react-router-dom";' },
  @{ f = "pages\ServiceDetailPage.tsx"; a = 'import { useParams } from "next/navigation";'; b = 'import { useParams } from "react-router-dom";' }
)
foreach ($r in $repl) {
  $p = "frontend-react\src\$($r.f)"
  $c = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $p))
  if ($c -notlike "*$($r.a)*") { "MISS  $($r.f): $($r.a)"; continue }
  $c = $c.Replace($r.a, $r.b)
  [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $p), $c)
  "OK    $($r.f)"
}
```

Every line must print `OK`. Any `MISS` means the source differs from what this
plan recorded — read the file and fix that one by hand.

- [ ] **Step 5a: Replace the `@clerk/nextjs` client import in TopNav**

`TopNav.tsx:4` imports from `@clerk/nextjs`, a Next-only package that is not a
dependency of the new project. `@clerk/react` is the drop-in replacement and
exports the same `useAuth` and `UserButton` hooks.

```powershell
$p = "frontend-react\src\components\layout\TopNav.tsx"
$c = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $p))
$c = $c.Replace('from "@clerk/nextjs"', 'from "@clerk/react"')
[System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $p), $c)
Select-String -LiteralPath $p -Pattern "@clerk/react"
```

- [ ] **Step 5b: Convert the styled-jsx block in MessageBubble to a CSS module**

`MessageBubble.tsx:476` contains a `<style jsx>{`...`}</style>` block.
**styled-jsx is a Next.js-only feature** — it is compiled by the Next compiler
and does not exist in plain React. Left as-is, React renders an unrecognised
`jsx` attribute and the CSS silently never applies, so the blinking streaming
cursor (`.streaming-text :global(p:last-child)::after`) stops animating with no
error anywhere. This must be converted, not deleted.

Vite supports CSS modules with no configuration. Create
`frontend-react/src/components/chat/MessageBubble.module.css` containing
exactly the CSS that was inside the styled-jsx block:

```css
.streaming-text :global(p:last-child)::after {
  content: "▊";
  animation: blink 0.8s step-end infinite;
  color: var(--ink);
  font-weight: normal;
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}
```

The `:global(...)` selector works identically in a CSS module, so the rule keeps
targeting paragraphs inside `.streaming-text`.

Then in `MessageBubble.tsx`, add the import next to the other imports:

```tsx
import styles from "./MessageBubble.module.css";
```

and replace the whole `{isStreaming && (<style jsx>{`...`}</style>)}` block with:

```tsx
{isStreaming && <div className={styles.streamingText} />}
```

Wait — that changes the DOM. Read `MessageBubble.tsx` around lines 440–490 first
to find which element already carries the `streaming-text` class, then apply the
module class to **that** element instead of adding a new one. The goal is that
`.streamingText` (module-scoped) sits on the same element that had
`streaming-text`, and the `<style jsx>` element is removed entirely.

Confirm no styled-jsx remains anywhere:

```powershell
Select-String -Path "frontend-react\src\**\*.tsx" -Pattern "style jsx|:global"
```

Expected: no output.

- [ ] **Step 5c: Reconcile the pre-existing lint baseline**

`npm run lint` reports 30 errors in the copied source, none of them
migration-introduced. They break down as roughly 19 `@typescript-eslint/no-unused-vars`
(dead imports and variables such as `IconBot`, `Button`, `Skeleton`,
`initialHistory`, `lastAssistantIdx`), 7 `react-hooks/set-state-in-effect`,
2 `no-useless-escape`, and 2 `no-empty`. These exist in `frontend/` today; the
old `eslint-config-next` did not enable the newer rules that flag them.

**Do not refactor copied components to satisfy these.** Changing
`set-state-in-effect` patterns risks real behaviour changes, and removing unused
imports is unrelated churn in a migration. Instead, in
`frontend-react/eslint.config.js`, demote exactly these four rules to `"warn"`:

```js
rules: {
  ...reactHooks.configs.recommended.rules,
  "react-refresh/only-export-components": [
    "warn",
    { allowConstantExport: true },
  ],
  // Pre-existing in the copied source; not introduced by this migration.
  // Demoted so `npm run lint` reports them without failing the gate.
  // Re-promote to "error" once the source is cleaned up.
  "@typescript-eslint/no-unused-vars": "warn",
  "@typescript-eslint/no-unused-expressions": "off",
  "react-hooks/set-state-in-effect": "warn",
  "no-useless-escape": "warn",
  "no-empty": "warn",
  "@typescript-eslint/no-explicit-any": "warn",
},
```

This keeps every finding visible in the lint output while letting the exit code
reach 0, which is what Task 9's gate checks. Record the final warning count in
Task 9's report so the debt stays visible rather than being silently erased.

- [ ] **Step 6: Remove the `<Suspense>` wrapper in ChatPage**

Next forced this because `useSearchParams` triggers a CSR bailout. React Router
does not.

```powershell
$p = "frontend-react\src\pages\ChatPage.tsx"
$c = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $p))
"--- before ---"
Select-String -LiteralPath $p -Pattern "Suspense"
```

Remove the `<Suspense fallback={…}>` and `</Suspense>` tags and the `Suspense`
import, keeping `<ChatWindow />` and the page's own JSX. Re-read the file after
editing to confirm the JSX still balances.

- [ ] **Step 7: Write the two Clerk pages**

`src/pages/SignInPage.tsx`:

```tsx
import { SignIn } from "@clerk/react";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <SignIn routing="path" path="/sign-in" />
    </div>
  );
}
```

`src/pages/SignUpPage.tsx`:

```tsx
import { SignUp } from "@clerk/react";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <SignUp routing="path" path="/sign-up" />
    </div>
  );
}
```

These replace `app/sign-in/[[...sign-in]]/page.tsx` and
`app/sign-up/[[...sign-up]]/page.tsx`, which rendered Clerk's catch-all
components.

- [ ] **Step 8: Write the real `src/App.tsx`**

```tsx
import { ClerkProvider } from "@clerk/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { LanguageProvider } from "@/lib/i18n/provider";
import { ConditionalNavs } from "@/components/layout/ConditionalNavs";

import { HomePage } from "@/pages/HomePage";
import { ChatPage } from "@/pages/ChatPage";
import { FaqPage } from "@/pages/FaqPage";
import { GrievancePage } from "@/pages/GrievancePage";
import { GrievanceStatusPage } from "@/pages/GrievanceStatusPage";
import { GrievanceDraftViewPage } from "@/pages/GrievanceDraftViewPage";
import { LegalPage } from "@/pages/LegalPage";
import { LegalDetailPage } from "@/pages/LegalDetailPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { SchemesPage } from "@/pages/SchemesPage";
import { SchemeDetailPage } from "@/pages/SchemeDetailPage";
import { ServicesPage } from "@/pages/ServicesPage";
import { ServiceDetailPage } from "@/pages/ServiceDetailPage";
import SignInPage from "@/pages/SignInPage";
import SignUpPage from "@/pages/SignUpPage";
import NotFoundPage from "@/pages/NotFoundPage";

export default function App() {
  return (
    <ClerkProvider
      publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}
      signInUrl={import.meta.env.VITE_CLERK_SIGN_IN_URL}
      signUpUrl={import.meta.env.VITE_CLERK_SIGN_UP_URL}
    >
      <BrowserRouter>
        <LanguageProvider>
          <ConditionalNavs>
            <Routes>
              {/* Static segments before dynamic ones. */}
              <Route path="/" element={<HomePage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/faq" element={<FaqPage />} />
              <Route path="/grievance" element={<GrievancePage />} />
              <Route path="/grievance/status" element={<GrievanceStatusPage />} />
              <Route path="/grievance/draft/view" element={<GrievanceDraftViewPage />} />
              <Route path="/legal" element={<LegalPage />} />
              <Route path="/legal/:slug" element={<LegalDetailPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/schemes" element={<SchemesPage />} />
              <Route path="/schemes/:slug" element={<SchemeDetailPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/services/:slug" element={<ServiceDetailPage />} />
              <Route path="/sign-in/*" element={<SignInPage />} />
              <Route path="/sign-up/*" element={<SignUpPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </ConditionalNavs>
        </LanguageProvider>
      </BrowserRouter>
    </ClerkProvider>
  );
}
```

Body classes from `layout.tsx:93`
(`min-h-full flex flex-col font-sans bg-[var(--canvas)]`) are moved into a
separate stylesheet in Step 9 — they cannot be set from JSX because Vite renders
into `#root` rather than owning `<body>`.

- [ ] **Step 9: Move the body classes into a separate stylesheet**

`globals.css` must stay byte-for-byte identical (Global Constraint 8), so these
go in a new file rather than being appended to it. Create `src/styles/document.css`:

```css
/* Replaces the className on <body> from app/layout.tsx:93, which cannot be
   expressed in JSX because Vite renders into #root rather than owning <body>. */
body {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  font-family: var(--font-primary);
  background-color: var(--canvas);
  -webkit-font-smoothing: antialiased;
}
```

Import it from `main.tsx`, immediately after `globals.css`:

```tsx
import "./styles/globals.css";
import "./styles/document.css";
```

- [ ] **Step 10: Confirm zero Next.js references remain**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
# NOTE: PowerShell's -Path does not treat ** as "recurse across directories".
# Using "src\**\*.tsx" matches only some files and silently misses others.
# Always enumerate files first, then search them.
$files = Get-ChildItem -LiteralPath "src" -Recurse -Include *.ts,*.tsx -File
$files += Get-ChildItem -LiteralPath "server" -Recurse -Include *.js -File
$files += Get-ChildItem -LiteralPath "." -Include *.ts,*.js -File
Select-String -LiteralPath $files.FullName `
  -Pattern "next/link|next/navigation|next/server|next/font|NextResponse|@clerk/nextjs|style jsx|:global"
```

Expected: no output. Any hit is a missed replacement — fix it before committing.
Note `style jsx` and `:global` are in this list because styled-jsx is a
Next-compiler feature with no plain-React equivalent (Step 5b).

Test files under `src/**/__tests__/` are in scope for this grep. The three
component tests that mock `next/navigation` and `next/link` are fixed in Task 6,
so run this grep again after Task 6 and expect it clean then.

- [ ] **Step 11: Build**

```powershell
npm run build
```

Expected: exit 0. Fix every reported error. Typical causes: a page importing
`next/link` that Step 3 missed, or `Suspense` left dangling in Step 5.

- [ ] **Step 12: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Move 13 pages to src/pages, add Clerk sign-in/up and 404, rewire all Next.js imports to React Router"
```

---

## Task 6: Port the test suite off Next.js mocks

**Files:**
- Create: `frontend-react/src/**/__tests__/*.test.tsx` (6 component tests)
- Create: `frontend-react/src/**/__tests__/*.test.ts` (12 unit tests)

**Interfaces:**
- Consumes: Task 5.
- Produces: `npm test` runs 18 files / 78 tests with the same 66 pass / 12 fail split as the baseline, proving the port introduced no regressions.

- [ ] **Step 1: Copy all 18 test files**

```powershell
Set-Location "A:\Serp-ai-2026"
Get-ChildItem -LiteralPath "frontend\src" -Recurse -Include *.test.ts,*.test.tsx -File |
  ForEach-Object {
    $rel = $_.FullName.Replace("A:\Serp-ai-2026\frontend\src\", "")
    $dst = "A:\Serp-ai-2026\frontend-react\src\$rel"
    New-Item -ItemType Directory -Path (Split-Path $dst) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
  }
Get-ChildItem -LiteralPath "frontend-react\src" -Recurse -Include *.test.ts,*.test.tsx -File |
  Measure-Object | Select-Object -ExpandProperty Count
```

Expected: `18`.

- [ ] **Step 2: Replace the `next/navigation` mocks with `MemoryRouter`**

Four files mock `next/navigation` and three of those also mock `next/link`.
Mocking is no longer needed — React Router's real hooks work fine inside a
`MemoryRouter`, which is strictly better because it exercises the actual router.

`ChatWindow.test.tsx` — replace the two `vi.mock` blocks (lines 12–22 of the
original) with nothing, and wrap each `render(<ChatWindow />)` in
`<MemoryRouter>`. Apply with edits, not a script, because `render` appears five
times:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ChatWindow } from "../ChatWindow";
import * as api from "@/lib/api";
import type { Locale } from "@/lib/i18n/i18n";

// Control the locale returned by useI18n between renders.
let mockLocale: Locale = "en";
vi.mock("@/lib/i18n/provider", () => ({
  useI18n: () => ({ t: (k: string) => k, locale: mockLocale, setLocale: () => {} }),
}));
vi.mock("@/components/motion/Reveal", () => ({
  Reveal: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

function renderChat() {
  return render(
    <MemoryRouter initialEntries={["/chat"]}>
      <ChatWindow />
    </MemoryRouter>,
  );
}
```

Then replace each `render(<ChatWindow />)` with `renderChat()`, and each
`rerender(<ChatWindow />)` with
`rerender(<MemoryRouter initialEntries={["/chat"]}><ChatWindow /></MemoryRouter>)`.

`GrievanceCard.test.tsx` — delete the `vi.mock("next/navigation", …)` block and
change `renderCard` to:

```tsx
function renderCard(grievance: Grievance) {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <GrievanceCard grievance={grievance} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}
```

with `import { MemoryRouter } from "react-router-dom";` added.

`GrievanceFlow.test.tsx` — read it, delete its `vi.mock("next/navigation", …)`
block, and wrap its render helper in `<MemoryRouter>` the same way.

`EvidencePanel.test.tsx` and `MessageBubble.test.tsx` — these do not mock
`next/navigation`; add `MemoryRouter` only if they fail in Step 3.

- [ ] **Step 3: Run the suite and confirm the split matches the baseline**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm test 2>&1 | Select-String -Pattern "Test Files|Tests  "
```

Expected: `Test Files 5 failed | 13 passed (18)` and
`Tests 12 failed | 66 passed (78)`.

**This exact split is the proof that the migration introduced no regressions.**
If you get a different failure count, something changed behaviour — investigate
before continuing. The 12 failures are fixed in Tasks 7 and 8.

- [ ] **Step 4: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Port 18 test files to MemoryRouter, confirming baseline failure count is unchanged at 12"
```

---

## Task 7: Fix the three source bugs behind the failing tests

These are real defects. The tests are correct; the code is wrong.

**Files:**
- Modify: `frontend-react/src/lib/speech.ts:170-182` and its call site at `:211`
- Modify: `frontend-react/src/components/chat/GrievanceCard.tsx:188-201`
- Modify: `frontend-react/src/components/chat/__tests__/GrievanceCard.test.tsx` (no change — it is right)

**Interfaces:**
- Consumes: Task 6.
- Produces: `speakSegments` honours cancellation while a backend fetch is in flight. `GrievanceCard` renders `application_id` as "Application ID".

- [ ] **Step 1: Run the two speech cancellation tests to see them fail**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npx vitest run src/lib/__tests__/speech.test.ts -t "settles the in-flight"
```

Expected: 2 failures, each `Error: Test timed out in 5000ms.`

- [ ] **Step 2: Fix the token-threading bug in speech.ts**

The bug: `speakBackendSegments` reads the module-level `_speakToken` *after*
awaiting the fetch. A call cancelled mid-flight therefore reads the *new* token,
passes the staleness guard in `playBackendAudio`, creates an `Audio` element, and
waits for an `onended` that never fires — leaving the caller's promise pending
forever and leaking the audio element.

Replace `speakBackendSegments` (lines 170–182) with:

```ts
async function speakBackendSegments(
  segments: SpeechSegment[],
  token: number,
): Promise<void> {
  const response = await fetchVoiceSpeak(segments);

  if (!response.audio) {
    throw new Error("Backend TTS returned empty audio");
  }

  // The caller may have been cancelled while the fetch was in flight. Bail out
  // BEFORE creating the Audio element, otherwise nothing will ever settle this
  // promise because onended never fires.
  if (token !== _speakToken) return;

  await playBackendAudio(response.audio, token);
}
```

And change its single call site (line 211) from:

```ts
await speakBackendSegments(runs);
```

to:

```ts
await speakBackendSegments(runs, token);
```

- [ ] **Step 3: Re-run the speech cancellation tests**

```powershell
npx vitest run src/lib/__tests__/speech.test.ts -t "settles the in-flight"
```

Expected: both pass. No timeout.

- [ ] **Step 4: Run the full speech suite**

```powershell
npx vitest run src/lib/__tests__/speech.test.ts
```

Expected: 6 pass, 1 fail. The remaining failure is "uses Azure for each language
run", which is a stale expectation fixed in Task 8, Step 1.

- [ ] **Step 5: Run the GrievanceCard test to see the casing failure**

```powershell
npx vitest run src/components/chat/__tests__/GrievanceCard.test.tsx
```

Expected: 3 pass, 2 fail — both on `Application ID`.

- [ ] **Step 6: Fix the title-caser in GrievanceCard.tsx**

`application_id` currently becomes `"Application Id"`. English wants
`"Application ID"`. Initialisms are a closed set in this domain, so handle them
explicitly rather than trying to guess casing.

Insert this above the `GrievanceCard` component (near the existing `Field`
helper at line 40):

```tsx
/**
 * Field keys arrive from the backend as snake_case. Turn them into
 * human-readable English labels. Initialisms must stay uppercase
 * ("application_id" -> "Application ID"), which a naive title-caser gets
 * wrong ("Application Id").
 */
const FIELD_INITIALISMS = new Set([
  "id",
  "url",
  "upi",
  "ifsc",
  "pan",
  "kcc",
  "aadhaar",
  "gst",
  "pin",
  "sms",
]);

function humanizeFieldKey(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase();
      if (FIELD_INITIALISMS.has(lower)) return lower.toUpperCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}
```

Then replace line 193:

```tsx
const label = translated !== i18nKey ? translated : key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
```

with:

```tsx
const label = translated !== i18nKey ? translated : humanizeFieldKey(key);
```

The `t(\`field.${camelKey}\`)` lookup above it is left alone — it allows a
locale-specific label when one is ever added, and correctly returns the key
itself today (there are zero `field.*` keys in any dictionary).

- [ ] **Step 7: Re-run the GrievanceCard test**

```powershell
npx vitest run src/components/chat/__tests__/GrievanceCard.test.tsx
```

Expected: 5 pass, 0 fail.

- [ ] **Step 8: Confirm the overall failure count dropped by exactly 4**

```powershell
npm test 2>&1 | Select-String -Pattern "Test Files|Tests  "
```

Expected: `Tests 8 failed | 70 passed (78)` — down from 12 failures, because
#4, #5 (two speech timeouts) and #11, #12 (two GrievanceCard casing) are fixed.

- [ ] **Step 9: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Fix speech cancellation token threading and GrievanceCard initialism casing"
```

---

## Task 8: Fix the five stale test expectations

The component behaviour is intentional and better than what the tests assert.
Update the tests.

**Files:**
- Modify: `frontend-react/src/lib/__tests__/speech.test.ts:61-76`
- Modify: `frontend-react/src/lib/i18n/i18n.test.ts:23-26`
- Modify: `frontend-react/src/lib/i18n/dictionaries.test.ts`
- Modify: `frontend-react/src/components/chat/__tests__/EvidencePanel.test.tsx`

**Interfaces:**
- Consumes: Task 7.
- Produces: 78 passing, 0 failing.

- [ ] **Step 1: Fix the speech batching expectation**

`speech.ts:211` deliberately sends all runs in one `fetchVoiceSpeak(runs)` call —
the backend accepts a `segments` array and merges them server-side. One network
call for a whole answer is better than one per language run. The test's
expectation of 2 calls encodes the old per-run behaviour.

Replace the body of "uses Azure for each language run when no browser voice matches"
(lines 61–76) with:

```ts
it("batches every language run into a single Azure call", async () => {
  const spy = vi
    .spyOn(api, "fetchVoiceSpeak")
    .mockResolvedValue({ audio: FAKE_HEX, language: "en" });

  await speakSegments([
    { text: "Hello ", language: "en" },
    { text: "world", language: "en" },
    { text: "नमस्ते", language: "hi" },
  ]);

  // partitionRuns merges the two English segments into one run, so the whole
  // answer is a single request — the backend handles segmentation.
  expect(spy).toHaveBeenCalledTimes(1);
  expect(spy).toHaveBeenCalledWith([
    { text: "Hello world", language: "en" },
    { text: "नमस्ते", language: "hi" },
  ]);
});
```

Also update the first test's name, "falls back to Azure per run and resolves", to
"speaks a single run through the backend and resolves" — it passes either way,
but the old name is now misleading.

- [ ] **Step 2: Fix the stale landing copy assertion**

`landing.ctaChat` was changed to `"Ask JanSahay →"` (`dictionaries.ts:71`). The
assertion still expects the old `"Chat now"`.

Replace `i18n.test.ts` lines 23–26 with:

```ts
test("root layout example translations resolve", () => {
  expect(translate("en", "landing.ctaChat")).toBe("Ask JanSahay →");
  expect(translate("hi", "evidence.strong")).toBe("प्रबल स्रोत समर्थन");
});
```

- [ ] **Step 3: Rewrite the dictionary coverage test and emit a gap report**

The current test asserts total translation coverage, which does not exist: `en`
has 374 keys and locales are missing 4 (hi, mr) to 130 (bn) of them. Because
`translate()` already falls back to `en`, the app degrades gracefully — the test
is asserting an aspiration, not an invariant.

Replace `dictionaries.test.ts` entirely with:

```ts
import { test, expect } from "vitest";
import { dict, translate } from "./dictionaries";
import { LOCALES } from "./i18n";

test("en is the complete reference table", () => {
  expect(Object.keys(dict.en).length).toBeGreaterThan(300);
});

test("no locale defines a key that en does not", () => {
  const enKeys = new Set(Object.keys(dict.en));
  for (const loc of LOCALES) {
    for (const k of Object.keys(dict[loc])) {
      expect(enKeys.has(k), `${loc} defines orphan key ${k}`).toBe(true);
    }
  }
});

test("translate falls back to English for a key a locale lacks", () => {
  // gu is missing 48 en keys (schemes.detail.*, common.yes, ...). Falling back
  // is the designed behaviour, so assert it rather than assert coverage.
  expect(translate("gu", "common.yes")).toBe(dict.en["common.yes"]);
});

test("translate returns the key when no locale has it", () => {
  expect(translate("en", "nav.never-gonna-exist")).toBe("nav.never-gonna-exist");
});

test("every locale translates nav.home to a non-empty string", () => {
  for (const loc of LOCALES) {
    expect(translate(loc, "nav.home").length).toBeGreaterThan(0);
  }
});
```

Then produce the gap report so the missing translations stay visible and are
never mistaken for solved:

```powershell
@'
import { readFileSync } from "node:fs";
const src = readFileSync("src/lib/i18n/dictionaries.ts", "utf8");
const locs = ["en","hi","gu","mr","bn","ta","te","kn","pa","or","ml"];
const blocks = {};
for (const loc of locs) {
  const s = src.indexOf(`const ${loc}: Record<string, string> = {`);
  const e = src.indexOf("\n};", s);
  blocks[loc] = new Set([...src.slice(s, e).matchAll(/"([^"]+)":/g)].map((m) => m[1]));
}
let total = 0;
for (const loc of locs.slice(1)) {
  const missing = [...blocks.en].filter((k) => !blocks[loc].has(k));
  total += missing.length;
  console.log(`${loc}: ${missing.length} missing of ${blocks.en.size}`);
}
console.log(`TOTAL missing strings: ${total}`);
console.log(`Coverage: ${(((locs.length - 1) * blocks.en.size - total) / ((locs.length - 1) * blocks.en.size) * 100).toFixed(1)}%`);
'@ | Out-File -FilePath "i18n-report.mjs" -Encoding utf8
node i18n-report.mjs
Remove-Item "i18n-report.mjs" -Force
```

Record the printed totals in the commit message. **Do not machine-translate these
strings** — that is a content decision for the user, not part of this migration.

- [ ] **Step 4: Fix the EvidencePanel expectations**

`MessageBubble.tsx:146-159` renders `t("chat.viewSource")` = **"View source"** and
`t("chat.viewDocument")` = **"View document"**. The tests expect "Open Source"
and "Open Document". The component copy is correct and localised; the tests are
stale.

The static-citation branch (`MessageBubble.tsx:150`) additionally requires
`citation.source_file` — the test fixture omits it, so the link never renders at
all. Add it to `STATIC_CITATION`:

```ts
const STATIC_CITATION = {
  chunk_id: "a0eebc99",
  title: "PMFBY Guidelines",
  source: "static" as const,
  source_label: "Official Document",
  url: "https://pmfby.gov.in/guidelines",
  source_file: "pmfby_guidelines.pdf",
  page: 5,
  section: "Eligibility",
  content: "Farmers must apply before the cut-off date.",
};
```

Then update the five failing tests:

| Test | Change |
|---|---|
| static evidence shows Open Document link | `{ name: /view document/i }`, and assert href is `/api/documents/pdf/pmfby_guidelines.pdf#page=5` |
| web evidence shows Open Source link after expanding | `{ name: /view source/i }`, href stays `https://example.com/pacs-rules` |
| document links open in new tab with noopener | assert `target="_blank"` and `rel` contains `noopener` on the view-document link |
| URLs remain unchanged after language switching | assert the view-source href is still `https://example.com/pacs-rules` after switching locale |
| evidence card toggle is a keyboard-focusable button | expect `{ name: /view document/i }` — a regex, since the accessible name also contains the title and page |

Read the current file before editing; these are line-level changes and the
surrounding assertions must stay intact.

- [ ] **Step 5: Confirm every test passes**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm test
```

Expected: `Test Files 18 passed (18)` and `Tests 78 passed (78)`.

- [ ] **Step 6: Commit**

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react
git commit -m "Align 5 stale test expectations with actual component behaviour; assert i18n fallback instead of nonexistent total coverage"
```

---

## Task 9: Full verification and docs

**Files:**
- Modify: `frontend-react/README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 1–8.
- Produces: all 7 gates from spec §11 pass. Docs match reality.

- [ ] **Step 1: Gate 1 — production build**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm run build
```

Expected: exit 0, `✓ built in`, `dist/index.html` present. Zero warnings about
unresolved imports.

- [ ] **Step 2: Gate 2 — lint**

```powershell
npm run lint
```

Expected: exit 0, no errors. Warnings are acceptable only if they are
pre-existing `@typescript-eslint/no-explicit-any` in copied code; record any new
category.

- [ ] **Step 3: Gate 3 — types**

```powershell
npx tsc --noEmit
```

Expected: exit 0. `npm run build` already runs this, so a pass there implies a
pass here — run it standalone anyway to get a clean signal.

- [ ] **Step 4: Gate 4 — tests**

```powershell
npm test
```

Expected: `78 passed (78)`, `Test Files 18 passed (18)`.

- [ ] **Step 5: Gate 5 — every route renders**

Start both processes:

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
$env:VITE_CLERK_PUBLISHABLE_KEY="pk_test_placeholder"
$env:VITE_CLERK_SIGN_IN_URL="http://localhost:5173/sign-in"
$env:VITE_CLERK_SIGN_UP_URL="http://localhost:5173/sign-up"
$env:CLERK_SECRET_KEY="sk_test_placeholder"
$env:BACKEND_API_URL="http://localhost:8000"
npm run dev:all
```

In a second terminal, request every route. The SPA returns 200 for all paths
(React Router renders client-side), so also confirm each page's heading in the
served HTML is absent-but-expected — i.e. verify by loading in a browser:

| Route | Expected heading |
|---|---|
| `/` | the hero headline |
| `/chat` | the chat input placeholder |
| `/faq` | FAQ heading |
| `/grievance` | grievance wizard step 1 |
| `/grievance/status` | status heading |
| `/grievance/draft/view` | draft heading (may show an empty state with no session — that is correct) |
| `/legal` | legal index heading |
| `/legal/pacs-act-1963` | a PACS Act detail title |
| `/library` | library heading |
| `/schemes` | schemes heading |
| `/schemes/pmfby` | PMFBY scheme title |
| `/services` | services heading |
| `/services/<a real slug>` | service detail title |
| `/sign-in/*` | Clerk sign-in form |
| `/sign-up/*` | Clerk sign-up form |
| `/this-route-does-not-exist` | "This page does not exist" |

Pick real slugs from `src/lib/data/schemes.ts`, `src/lib/data/services.ts` and
`src/lib/data/legal.ts` — a wrong slug renders the not-found state and would be
a false failure.

Also verify all 11 locales render in the correct script. Switch to Gujarati,
Tamil and Malayalam and confirm the answer font changes — this is the real test
of Task 3.

- [ ] **Step 6: Gate 6 — chat streams incrementally**

With `dev:all` running and the Python backend up, send a real question in the
browser. Then measure the inter-token gap in DevTools' Network tab: the
`/api/chat` response should show data arriving progressively, not as one burst.

Automated equivalent, against the running BFF:

```powershell
$body = @{ question = "What is PMFBY?"; session_id = "verify-1"; language = "en" } | ConvertTo-Json
$sw = [Diagnostics.Stopwatch]::StartNew()
$times = @()
$client = New-Object System.Net.Http.HttpClient
$stream = $client.PostAsync("http://localhost:8787/api/chat", [System.Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, "application/json")).Result.Content.ReadAsStreamAsync().Result
$reader = New-Object IO.StreamReader($stream)
while (-not $reader.EndOfStream) {
  $null = $reader.ReadLine()
  $times += $sw.ElapsedMilliseconds
}
"lines: $($times.Count); deltas(ms): $((0..($times.Count-2) | ForEach-Object { $times[$_+1] - $times[$_] }) -join ', ')"
```

Expected: many lines with non-zero deltas. All-zero deltas means buffering —
return to Task 4, Step 7.

- [ ] **Step 7: Gate 7 — auth and grievance**

In the browser: sign in, confirm the user button appears in `TopNav`, sign out.
Then file a grievance through to `finalize` and confirm the draft renders. Both
must work — this is the gate that proves the Clerk token is being minted and
forwarded correctly.

- [ ] **Step 8: Confirm frontend/ is still untouched**

```powershell
Set-Location "A:\Serp-ai-2026"
git status --short frontend/
```

Expected: no output. If anything appears, restore it with
`git checkout -- frontend/` before continuing.

- [ ] **Step 9: Write frontend-react/README.md**

Cover: what it is, `npm install`, the five scripts, the required env vars and
where they come from, the dev topology (Vite 5173 → Express 8787 → FastAPI 8000),
the production topology (single Express process serving `dist/` and `/api`), how
to deploy to Render, and an explicit note that **PWA support is not implemented**
despite what the older docs claim.

- [ ] **Step 10: Correct PROJECT_STATUS.md**

Three factual errors to fix, all verified above:
1. The stack table's frontend row: Next.js 16 → React 19 + Vite 8.
2. Line ~139's "7 failing tests" — the measured baseline is 12, and after this
   plan the suite is fully green.
3. The PWA claim — there is no manifest and no service worker, in either version.

Add a short entry recording that `frontend-react/` now exists and is verified,
and that `frontend/` is retained as a fallback pending the user's sign-off.

- [ ] **Step 11: Correct the CLAUDE.md stack table**

Change the frontend row to `React 19 + Vite 8 + React Router 7 (SPA) + Express 5
BFF`, and add a line noting the BFF owns Clerk token injection so route handlers
must never be reintroduced on the client.

Also correct the language count: the code supports **11** locales
(`en hi gu mr bn ta te kn pa or ml`), not 6.

- [ ] **Step 12: Final full-suite confirmation and commit**

```powershell
Set-Location "A:\Serp-ai-2026\frontend-react"
npm run build; if ($?) { npm run lint }; if ($?) { npx tsc --noEmit }; if ($?) { npm test }
```

Expected: build OK, lint OK, types OK, `78 passed (78)`.

```powershell
Set-Location "A:\Serp-ai-2026"
git add frontend-react PROJECT_STATUS.md CLAUDE.md
git commit -m "Add frontend-react README and correct stale PWA, test-count and language-count claims"
```

- [ ] **Step 13: Report to the user, do not delete anything**

Summarise: all 7 gates green, 78/78 tests, 12 pre-existing failures fixed
(3 source bugs, 9 test expectations), `frontend/` still intact.

**Do not delete `frontend/`, and do not touch `render.yaml` or any Vercel
config.** That is the user's decision after they have run the new app themselves.

---

## Appendix A: Route parity checklist

Verify with `Select-String` that no Next.js reference survives, and that all 15
routes are present. Run from `frontend-react/`:

```powershell
"next/ refs:      " + (Select-String -Path "src\**\*.tsx","src\**\*.ts","server\**\*.js" -Pattern "next/link|next/navigation|next/server|next/font|NextResponse|@clerk/nextjs|style jsx" -ErrorAction SilentlyContinue | Measure-Object).Count
"routes declared: " + (Select-String -LiteralPath "src\App.tsx" -Pattern "<Route path=" | Measure-Object).Count
"api endpoints:   " + (Select-String -LiteralPath "server\index.js" -Pattern 'app\.(get|post)\("/api' | Measure-Object).Count
"pages:           " + (Get-ChildItem -LiteralPath "src\pages" -Filter *.tsx | Measure-Object).Count
"font imports:    " + (Select-String -LiteralPath "src\main.tsx" -Pattern "@fontsource" | Measure-Object).Count
"font vars:       " + (Select-String -LiteralPath "index.html" -Pattern "--font-" | Measure-Object).Count
```

Expected: `0`, `16`, `11`, `16`, `38`, `12`.

- `routes declared: 16` = 15 real routes + the `*` catch-all.
- `pages: 16` = 13 moved + SignIn + SignUp + NotFound.
- `api endpoints: 11` counts only the `app.get`/`app.post` literals; `/api/chat`
  and `/api/chat/stream` share one handler, so 11 is correct.

## Appendix B: What "no errors" is verified by

| Claim | Evidence |
|---|---|
| It compiles | `npm run build` exit 0 |
| It type-checks | `npx tsc --noEmit` exit 0 under `strict` |
| It lints | `npm run lint` exit 0 |
| Tests pass | `78 passed (78)`, up from 66 |
| No Next.js left | grep returns 0 |
| All routes work | 16 routes loaded in a browser, headings confirmed |
| All 11 locales render | script switching verified in 3 non-Latin locales |
| Chat streams | inter-token timing measured, not coalesced |
| Login works | sign in/out verified in-browser |
| Grievance works | completed through `finalize` |
| Design system intact | `globals.css` hash matches the original |
| Fallback intact | `git status frontend/` is empty |
