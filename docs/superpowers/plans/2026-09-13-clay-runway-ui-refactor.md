# Clay + Runway UI Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the entire Zapier warm-editorial design system with Clay's cream/6-color palette and rebuild the landing page with a Runway-style bold split hero, restyling all 17 components and 12 routes.

**Architecture:** Token-first approach — replace all CSS custom properties in globals.css, then restyle components that consume those tokens, then rebuild layouts. The Clay design system uses cream canvas (#fffaf0), near-black primary (#0a0a0a), 6 saturated brand colors for feature cards, Space Grotesk 500 display type with aggressive negative letter-spacing, and 96px section spacing.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS v4 (CSS custom properties via `@theme inline`), GSAP ScrollTrigger, Space Grotesk + Inter fonts.

## Global Constraints

- Canvas background: #fffaf0 (cream-tinted white) — non-negotiable
- Primary CTA color: #0a0a0a (near-black) — replaces orange accent
- Display font: Space Grotesk weight 500, never bolder than 500
- Border radius: md=12px buttons/inputs, lg=16px content cards, xl=24px feature cards
- Section spacing: 96px between major bands
- No heavy shadows — depth from saturated color contrast only
- Cream footer (#faf5e8) — NO dark footer sections
- Bottom mobile tab bar REMOVED — hamburger menu only
- All existing i18n, GSAP animations, and API routes remain untouched
- Indic script font fallback chain preserved (var(--font-script))

---

## File Map

| Task | Files Created | Files Modified |
|---|---|---|
| 1. Design Tokens | — | `src/app/globals.css` |
| 2. Layout + Nav | `src/components/layout/HamburgerMenu.tsx`, `src/components/layout/Footer.tsx` | `src/app/layout.tsx`, `src/components/layout/TopNav.tsx`, `src/components/layout/ConditionalNavs.tsx` |
| 3. UI Components | — | `Button.tsx`, `Card.tsx`, `Input.tsx`, `Badge.tsx`, `Chips.tsx`, `Stepper.tsx`, `Alert.tsx`, `EmptyState.tsx`, `Skeleton.tsx` |
| 4. Landing Page | — | `src/app/page.tsx` |
| 5. Content Routes | — | `schemes/page.tsx`, `schemes/[slug]/page.tsx`, `services/page.tsx`, `services/[slug]/page.tsx`, `library/page.tsx`, `legal/page.tsx`, `legal/[slug]/page.tsx` |
| 6. Grievance + FAQ | — | `grievance/page.tsx`, `grievance/status/page.tsx`, `faq/page.tsx` |
| 7. Chat Interface | — | `ChatWindow.tsx`, `chat/MessageBubble.tsx`, `chat/ThinkingBubble.tsx`, `EvidenceBand.tsx` |
| 8. Polish & Test | — | Various (responsive fixes, token cleanup) |

---

### Task 1: Design Tokens — globals.css

**Files:**
- Modify: `A:\MSU\frontend\src\app\globals.css`

**This is the foundation.** Every subsequent task depends on these tokens being correct. Do this first.

- [ ] **Step 1: Read current globals.css**

Read `A:\MSU\frontend\src\app\globals.css` to understand the full current token set (410 lines).

- [ ] **Step 2: Replace the `:root` block**

Replace the entire `:root { ... }` block (lines 4-130) with the new Clay token system:

```css
:root {
  color-scheme: light;

  /* --------------------------------------------------------------------
     Clay design system — cream canvas, 6-color saturated cards,
     near-black primary, Space Grotesk display.
     -------------------------------------------------------------------- */

  /* Canvas & surfaces */
  --background: #fffaf0;
  --foreground: #0a0a0a;
  --ink: #0a0a0a;

  --surface-base: #fffaf0;
  --surface-underlay: #faf5e8;
  --surface-elevated: #fffaf0;
  --surface-overlay: #f5f0e0;

  /* Canonical surface names */
  --canvas: #fffaf0;
  --cream: #faf5e8;
  --cream-2: #f5f0e0;
  --dark: #0a1a1a;
  --surface-soft: #faf5e8;
  --surface-card: #f5f0e0;
  --surface-strong: #ebe6d6;
  --surface-dark: #0a1a1a;
  --surface-dark-elevated: #1a2a2a;

  /* Primary — near-black, replaces orange */
  --primary: #0a0a0a;
  --on-primary: #ffffff;

  /* Brand colors — saturated feature card surfaces */
  --brand-pink: #ff4d8b;
  --brand-pink-text: #ffffff;
  --brand-teal: #1a3a3a;
  --brand-teal-text: #ffffff;
  --brand-lavender: #b8a4ed;
  --brand-lavender-text: #0a0a0a;
  --brand-peach: #ffb084;
  --brand-peach-text: #0a0a0a;
  --brand-ochre: #e8b94a;
  --brand-ochre-text: #0a0a0a;
  --brand-mint: #a4d4c5;
  --brand-mint-text: #0a0a0a;
  --brand-coral: #ff6b5a;
  --brand-coral-text: #ffffff;

  /* Text — warm ink ramp */
  --text-primary: #0a0a0a;
  --text-body: #3a3a3a;
  --text-secondary: #3a3a3a;
  --text-tertiary: #6a6a6a;
  --text-faint: #9a9a9a;
  --text-inverse: #ffffff;
  --on-dark: #ffffff;
  --on-dark-strong: #ffffff;
  --on-dark-muted: #c5c0b1;
  --body-strong: #1a1a1a;
  --body: #3a3a3a;
  --muted: #6a6a6a;
  --muted-soft: #9a9a9a;

  /* Accent tint (for subtle backgrounds) */
  --accent-tint-soft: rgba(10, 10, 10, 0.05);
  --accent-tint-strong: rgba(10, 10, 10, 0.10);

  /* Borders */
  --hairline: #e5e5e5;
  --border-default: #e5e5e5;
  --border-medium: #e5e5e5;
  --border-hover: #9a9a9a;
  --border-focus: #0a0a0a;
  --border-soft: #e5e5e5;

  /* State */
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
  --state-error: #ef4444;
  --state-success: #22c55e;
  --state-warning: #f59e0b;

  /* Typography - Font Family */
  --font-primary: var(--font-inter), var(--font-script), ui-sans-serif, system-ui, sans-serif;
  --font-display: var(--font-display-latin), var(--font-script), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, SFMono-Regular, monospace;
  --font-answer: Georgia, "Times New Roman", var(--font-script), ui-serif, serif;

  /* Typography - Font Size */
  --text-xs: 12px;
  --text-sm: 14px;
  --text-base: 16px;
  --text-lg: 18px;
  --text-xl: 20px;
  --text-2xl: 24px;
  --text-3xl: 30px;
  --text-4xl: 40px;
  --text-5xl: 72px;

  /* Typography - Line Height */
  --leading-tight: 1.0;
  --leading-snug: 1.1;
  --leading-normal: 1.5;
  --leading-relaxed: 1.55;

  /* Typography - Font Weight */
  --font-normal: 400;
  --font-medium: 500;
  --font-semibold: 600;
  --font-bold: 600;

  /* Spacing */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
  --space-section: 96px;

  /* Border Radius */
  --radius-xs: 6px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --radius-full: 9999px;
  --radius-pill: 9999px;
  --radius-cta: 12px;

  /* Motion easing */
  --ease-out-cubic: cubic-bezier(0.33, 1, 0.68, 1);
  --ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
  --ease-out-soft: cubic-bezier(0.36, 1.3, 0.64, 1);
}
```

- [ ] **Step 3: Replace the `@theme inline` block**

Replace the `@theme inline { ... }` block (lines 132-170) with:

```css
@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --font-sans: var(--font-primary);
  --font-display: var(--font-display);
  --font-answer: var(--font-answer);
  --font-mono: var(--font-mono);

  /* Surface */
  --color-surface-base: var(--surface-base);
  --color-surface-elevated: var(--surface-elevated);
  --color-surface-overlay: var(--surface-overlay);
  --color-surface-soft: var(--surface-soft);
  --color-surface-card: var(--surface-card);

  /* Text */
  --color-text-primary: var(--text-primary);
  --color-text-secondary: var(--text-secondary);
  --color-text-tertiary: var(--text-tertiary);
  --color-text-inverse: var(--text-inverse);
  --color-ink: var(--ink);
  --color-body: var(--body);
  --color-muted: var(--muted);

  /* Primary */
  --color-primary: var(--primary);
  --color-on-primary: var(--on-primary);

  /* Brand */
  --color-brand-pink: var(--brand-pink);
  --color-brand-teal: var(--brand-teal);
  --color-brand-lavender: var(--brand-lavender);
  --color-brand-peach: var(--brand-peach);
  --color-brand-ochre: var(--brand-ochre);
  --color-brand-mint: var(--brand-mint);
  --color-brand-coral: var(--brand-coral);

  /* Border */
  --color-hairline: var(--hairline);
  --color-border-default: var(--border-default);
  --color-border-hover: var(--border-hover);
  --color-border-focus: var(--border-focus);

  /* State */
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-error: var(--error);
}
```

- [ ] **Step 4: Update CSS utility classes**

Replace the `.display` class (line 221-225) with:

```css
.display {
  font-family: var(--font-display);
  font-weight: var(--font-medium);
  letter-spacing: -0.02em;
}
```

Replace the `.eyebrow` class (line 228-235) with:

```css
.eyebrow {
  font-family: var(--font-primary);
  font-size: 12px;
  font-weight: var(--font-semibold);
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--muted);
}
```

Replace the `.rail-frame` class (line 239-242) — remove it entirely (no border rails in Clay):

```css
.rail-frame {
  position: relative;
}
```

Replace `.page-container` padding to use the larger Clay spacing:

```css
.page-container {
  width: 100%;
  margin-left: auto;
  margin-right: auto;
  max-width: 1280px;
  padding-left: 1.5rem;
  padding-right: 1.5rem;
  padding-top: 2rem;
  padding-bottom: 3rem;
}

@media (min-width: 640px) {
  .page-container {
    padding-left: 2rem;
    padding-right: 2rem;
    padding-top: 2.5rem;
    padding-bottom: 4rem;
  }
}

@media (min-width: 1024px) {
  .page-container {
    padding-left: 3rem;
    padding-right: 3rem;
    padding-top: 3rem;
    padding-bottom: 5rem;
  }
}
```

- [ ] **Step 5: Remove the ask-glow and focus-glow custom properties**

Remove or replace the `.ask-input-wrap` glow effect. Replace with a simple ink focus ring:

```css
.ask-input-wrap {
  transition:
    border-color 0.35s var(--ease-out-soft);
}
.ask-input-wrap:focus-within {
  border-color: var(--ink);
}
```

- [ ] **Step 6: Update the input floating label focus color**

Replace all references to `var(--accent-primary)` in the input styles with `var(--ink)`:

```css
.input-field:focus + .input-label,
.input-field:not(:placeholder-shown) + .input-label {
  top: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
}

.input-field:focus + .input-label + .input-highlight {
  width: 100%;
  background-color: var(--ink);
}
```

- [ ] **Step 7: Verify all CSS compiles**

Run: `cd A:\MSU\frontend && npm run build`
Expected: Build succeeds with no CSS errors. Some TypeScript errors may exist (components reference old token names) — those will be fixed in subsequent tasks.

- [ ] **Step 8: Commit**

```bash
git add src/app/globals.css
git commit -m "feat: replace Zapier tokens with Clay design system"
```

---

### Task 2: Navigation — TopNav + Hamburger + Footer

**Files:**
- Create: `A:\MSU\frontend\src\components\layout\HamburgerMenu.tsx`
- Create: `A:\MSU\frontend\src\components\layout\Footer.tsx`
- Modify: `A:\MSU\frontend\src\components\layout\TopNav.tsx`
- Modify: `A:\MSU\frontend\src\components\layout\ConditionalNavs.tsx`
- Delete: `A:\MSU\frontend\src\components\layout\MobileNav.tsx` (replaced by hamburger)
- Delete: `A:\MSU\frontend\src\components\layout\MoreSheet.tsx` (replaced by hamburger)

**Interfaces:**
- Consumes: tokens from globals.css, `useI18n()` hook, `LanguageSwitcher` component
- Produces: `<TopNav>`, `<HamburgerMenu>`, `<Footer>` components used by layout.tsx

- [ ] **Step 1: Rewrite TopNav.tsx**

Replace the full file with Clay-styled nav:

```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/lib/i18n/provider";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { HamburgerMenu } from "./HamburgerMenu";

const LINKS = [
  { href: "/schemes", key: "nav.schemes" },
  { href: "/services", key: "nav.services" },
  { href: "/library", key: "nav.library" },
  { href: "/legal", key: "nav.legal" },
  { href: "/faq", key: "nav.faq" },
] as const;

export function TopNav() {
  const { t } = useI18n();
  const pathname = usePathname();
  const active = (href: string) => pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-20 border-b border-[var(--hairline)] bg-[var(--canvas)]">
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center justify-between gap-4 px-4 md:px-6">
        <Link href="/" className="group flex shrink-0 flex-col leading-none">
          <span className="display text-xl text-[var(--ink)]">JanSayah</span>
          <span
            className="mt-0.5 h-[2px] w-[22px] bg-[var(--brand-coral)] transition-all duration-[250ms] ease-[var(--ease-out-cubic)] group-hover:w-9"
            aria-hidden="true"
          />
        </Link>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
          {LINKS.map((l) => {
            const isActive = active(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={isActive ? "page" : undefined}
                className={`flex h-16 items-center border-b-2 px-3 text-[14px] font-medium transition-colors duration-[200ms] ${
                  isActive
                    ? "border-[var(--ink)] text-[var(--ink)]"
                    : "border-transparent text-[var(--muted)] hover:text-[var(--ink)]"
                }`}
              >
                {t(l.key)}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-3">
          <LanguageSwitcher />
          <Link
            href="/chat"
            className="hidden items-center rounded-[var(--radius-pill)] bg-[var(--primary)] px-5 py-2 text-[14px] font-semibold text-[var(--on-primary)] transition-colors duration-[200ms] hover:bg-[#1a1a1a] md:inline-flex"
          >
            {t("nav.chat")}
          </Link>
          <HamburgerMenu />
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Create HamburgerMenu.tsx**

Create the hamburger menu component for mobile:

```tsx
"use client";
import Link from "next/link";
import { useState, useEffect } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { LanguageSwitcher } from "./LanguageSwitcher";

const LINKS = [
  { href: "/schemes", key: "nav.schemes" },
  { href: "/services", key: "nav.services" },
  { href: "/library", key: "nav.library" },
  { href: "/legal", key: "nav.legal" },
  { href: "/faq", key: "nav.faq" },
  { href: "/grievance", key: "nav.grievance" },
] as const;

export function HamburgerMenu() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] text-[var(--ink)] lg:hidden"
        aria-label="Open menu"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 5h14M3 10h14M3 15h14" />
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-30 bg-[var(--ink)]/40"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            className="fixed inset-y-0 right-0 z-40 w-full max-w-sm bg-[var(--canvas)] shadow-xl"
          >
            <div className="flex items-center justify-between border-b border-[var(--hairline)] px-6 py-4">
              <span className="display text-lg text-[var(--ink)]">Menu</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] text-[var(--ink)]"
                aria-label="Close menu"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M5 5l10 10M15 5L5 15" />
                </svg>
              </button>
            </div>
            <nav className="px-6 py-4" aria-label="Mobile navigation">
              {LINKS.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className="block border-b border-[var(--hairline)] py-3 text-[16px] font-medium text-[var(--ink)] hover:text-[var(--muted)]"
                >
                  {t(l.key)}
                </Link>
              ))}
            </nav>
            <div className="px-6 py-4">
              <LanguageSwitcher />
            </div>
            <div className="px-6 py-4">
              <Link
                href="/chat"
                onClick={() => setOpen(false)}
                className="flex items-center justify-center rounded-[var(--radius-pill)] bg-[var(--primary)] px-5 py-3 text-[14px] font-semibold text-[var(--on-primary)]"
              >
                {t("nav.chat")}
              </Link>
            </div>
          </div>
        </>
      )}
    </>
  );
}
```

- [ ] **Step 3: Update ConditionalNavs.tsx**

Remove MobileNav import, keep TopNav only:

```tsx
"use client";
import { usePathname } from "next/navigation";
import { TopNav } from "./TopNav";

export function ConditionalNavs({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isChat = pathname.startsWith("/chat");

  return (
    <>
      {!isChat && <TopNav />}
      <main>{children}</main>
    </>
  );
}
```

- [ ] **Step 4: Create Footer.tsx**

```tsx
"use client";
import Link from "next/link";
import { useI18n } from "@/lib/i18n/provider";

const COLUMNS = [
  {
    title: "footer.schemes",
    links: [
      { href: "/schemes", key: "nav.schemes" },
      { href: "/services", key: "nav.services" },
      { href: "/library", key: "nav.library" },
    ],
  },
  {
    title: "footer.legal",
    links: [
      { href: "/legal", key: "nav.legal" },
      { href: "/faq", key: "nav.faq" },
      { href: "/grievance", key: "nav.grievance" },
    ],
  },
];

export function Footer() {
  const { t } = useI18n();

  return (
    <footer className="bg-[var(--surface-soft)] border-t border-[var(--hairline)]">
      <div className="mx-auto max-w-[1280px] px-4 py-16 md:px-6 lg:px-8">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Link href="/" className="group inline-flex flex-col leading-none">
              <span className="display text-xl text-[var(--ink)]">JanSayah</span>
              <span className="mt-0.5 h-[2px] w-[22px] bg-[var(--brand-coral)]" aria-hidden="true" />
            </Link>
            <p className="mt-4 text-[14px] leading-relaxed text-[var(--muted)]">
              Government assistance for Indian cooperatives.
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h3 className="text-[12px] font-semibold uppercase tracking-[1.5px] text-[var(--muted)]">
                {t(col.title)}
              </h3>
              <ul className="mt-4 space-y-2">
                {col.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-[14px] text-[var(--body)] hover:text-[var(--ink)] transition-colors"
                    >
                      {t(link.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div>
            <h3 className="text-[12px] font-semibold uppercase tracking-[1.5px] text-[var(--muted)]">
              {t("footer.contact")}
            </h3>
            <ul className="mt-4 space-y-2">
              <li className="text-[14px] text-[var(--body)]">
                {t("nav.chat")}
              </li>
            </ul>
          </div>
        </div>
        <div className="mt-12 border-t border-[var(--hairline)] pt-6 text-center text-[13px] text-[var(--muted-soft)]">
          &copy; 2026 JanSayah. Built for Indian cooperatives.
        </div>
      </div>
    </footer>
  );
}
```

- [ ] **Step 5: Update layout.tsx to include Footer**

Add `Footer` import and render it after `{children}` in the root layout. Read `A:\MSU\frontend\src\app\layout.tsx` first, then add the import and component.

- [ ] **Step 6: Delete MobileNav.tsx and MoreSheet.tsx**

Remove these files since they're replaced by HamburgerMenu.

- [ ] **Step 7: Verify navigation compiles**

Run: `cd A:\MSU\frontend && npm run build`
Expected: No import errors for deleted files. TypeScript passes.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: restyle navigation with Clay top nav + hamburger menu + cream footer"
```

---

### Task 3: UI Component Restyling

**Files:**
- Modify: `A:\MSU\frontend\src\components\ui\Button.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Card.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Input.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Badge.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Chips.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Stepper.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\Alert.tsx`
- Modify: `A:\MSU\frontend\src\components\ui\EmptyState.tsx`

**Interfaces:**
- Consumes: tokens from globals.css
- Produces: restyled components used by all routes

- [ ] **Step 1: Restyle Button.tsx**

Replace the STYLES record and SIZE record:

```tsx
const STYLES: Record<Variant, string> = {
  primary:
    "bg-[var(--primary)] text-[var(--on-primary)] border border-[var(--primary)] hover:bg-[#1a1a1a] hover:border-[#1a1a1a] active:bg-[#0a0a0a]",
  secondary:
    "bg-[var(--canvas)] text-[var(--ink)] border border-[var(--hairline)] hover:bg-[var(--cream)] hover:border-[var(--border-hover)] active:bg-[var(--cream-2)]",
  dark:
    "bg-[var(--surface-dark)] text-[var(--on-primary)] border border-[var(--surface-dark)] hover:bg-[var(--surface-dark-elevated)]",
  ghost:
    "bg-transparent text-[var(--ink)] border border-transparent hover:bg-[var(--cream)] active:bg-[var(--cream-2)]",
  icon: "bg-transparent text-[var(--ink)] border border-transparent hover:bg-[var(--cream)] active:bg-[var(--cream-2)]",
};

const SIZE: Record<Size, string> = {
  sm: "h-9 px-3.5 text-[var(--text-sm)]",
  md: "h-11 px-5 text-[var(--text-base)]",
  lg: "h-12 px-6 text-[var(--text-lg)]",
};
```

Update the button className to use `rounded-[var(--radius-md)]` (12px) instead of `rounded-[var(--radius-cta)]`.

- [ ] **Step 2: Restyle Card.tsx**

Add a `brand` variant for saturated feature cards:

```tsx
type Fill = "canvas" | "cream" | "brand-pink" | "brand-teal" | "brand-lavender" | "brand-peach" | "brand-ochre";

const FILL_STYLES: Record<Fill, string> = {
  canvas: "bg-[var(--canvas)] border border-[var(--hairline)]",
  cream: "bg-[var(--cream-2)] border border-[var(--cream-2)]",
  "brand-pink": "bg-[var(--brand-pink)] text-[var(--brand-pink-text)]",
  "brand-teal": "bg-[var(--brand-teal)] text-[var(--brand-teal-text)]",
  "brand-lavender": "bg-[var(--brand-lavender)] text-[var(--brand-lavender-text)]",
  "brand-peach": "bg-[var(--brand-peach)] text-[var(--brand-peach-text)]",
  "brand-ochre": "bg-[var(--brand-ochre)] text-[var(--brand-ochre-text)]",
};
```

Brand cards use `rounded-[var(--radius-xl)]` (24px) and `p-8` (32px). Canvas/cream cards use `rounded-[var(--radius-lg)]` (16px) and `p-6` (24px).

- [ ] **Step 3: Restyle Input.tsx**

Update border-radius from `var(--radius-cta)` to `var(--radius-md)` (12px). Update focus border to `var(--ink)`. Read the current file first, then update the class references.

- [ ] **Step 4: Restyle Badge.tsx**

Update to pill shape: `rounded-[var(--radius-pill)]`. Update font to `text-[13px] font-medium`. Update colors to use new token names.

- [ ] **Step 5: Restyle Chips.tsx**

Update to pill shape: `rounded-[var(--radius-pill)]`. Active chip: `bg-[var(--primary)] text-[var(--on-primary)]`. Inactive: `bg-[var(--cream-2)] text-[var(--body)]`.

- [ ] **Step 6: Restyle Stepper.tsx**

Update circle radius to `rounded-full`. Active: `bg-[var(--primary)] text-[var(--on-primary)]`. Done: `bg-[var(--success)] text-white`. Update connecting line colors.

- [ ] **Step 7: Restyle Alert.tsx**

Update border-radius to `var(--radius-md)` (12px). Update token references from old names to new.

- [ ] **Step 8: Update EmptyState.tsx**

Minimal changes — just update token references if any are broken.

- [ ] **Step 9: Verify all components compile**

Run: `cd A:\MSU\frontend && npm run build`
Expected: All component imports resolve, no broken token references.

- [ ] **Step 10: Commit**

```bash
git add src/components/ui/
git commit -m "feat: restyle all UI components with Clay tokens"
```

---

### Task 4: Landing Page — Full Rebuild

**Files:**
- Modify: `A:\MSU\frontend\src\app\page.tsx`

**Interfaces:**
- Consumes: Button, Badge, Icons, Reveal, Stagger, useI18n, data
- Produces: Complete landing page with Runway hero + Clay sections

- [ ] **Step 1: Read current page.tsx**

Read `A:\MSU\frontend\src\app\page.tsx` (198 lines) to understand the current structure.

- [ ] **Step 2: Rewrite the full landing page**

Replace the entire file with the new Runway-style hero + Clay sections. The key structural changes:

1. Hero: 7-5 grid split (left text, right chat mockup)
2. Stats: surface-soft bg, 3-column
3. Feature cards: 6 saturated brand-color cards in 3-col grid
4. How it works: 3 numbered steps
5. CTA band: surface-soft bg
6. No dark/inverted sections (remove the dark stats band and dark CTA)

The new page structure:

```tsx
"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useI18n } from "@/lib/i18n/provider";
import { Button } from "@/components/ui/Button";
import { Reveal } from "@/components/motion/Reveal";
import { Stagger } from "@/components/motion/Stagger";
import { schemes as rawSchemes, services as rawServices, libraryDocs as rawLibraryDocs } from "@/lib/data";
import { IconChat, IconMic, IconDoc, IconGlobe, IconChevronRight } from "@/components/ui/Icons";

const FEATURES = [
  { color: "brand-pink" as const, icon: <IconGlobe className="w-6 h-6" />, title: "landing.f1title", text: "landing.f1text" },
  { color: "brand-teal" as const, icon: <IconDoc className="w-6 h-6" />, title: "landing.f2title", text: "landing.f2text" },
  { color: "brand-lavender" as const, icon: <IconMic className="w-6 h-6" />, title: "landing.f3title", text: "landing.f3text" },
];
const HOW = [
  { title: "landing.how1title", text: "landing.how1text" },
  { title: "landing.how2title", text: "landing.how2text" },
  { title: "landing.how3title", text: "landing.how3text" },
];

export default function HomePage() {
  const router = useRouter();
  const { t } = useI18n();

  const stats = [
    { n: rawSchemes.length, label: t("nav.schemes") },
    { n: rawServices.length, label: t("nav.services") },
    { n: rawLibraryDocs.length, label: t("nav.library") },
  ];

  return (
    <div className="page-container">
      {/* Hero — Runway-style 7-5 split */}
      <section className="flex flex-col gap-10 pb-12 md:pb-16 lg:flex-row lg:items-center lg:gap-12">
        <Reveal trigger="load" className="flex max-w-2xl flex-col items-start">
          <p className="eyebrow">{t("landing.badge")}</p>
          <h1 className="mt-6 text-[36px] font-medium leading-[1.0] tracking-[-0.04em] text-[var(--ink)] md:text-[72px]"
              style={{ fontFamily: "var(--font-display)" }}>
            {t("landing.tagline").split("—")[0].trim()}
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-[var(--body)]">
            {t("landing.f1text")}
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/chat">
              <Button size="lg">{t("landing.ctaChat")} <IconChevronRight className="w-4 h-4" /></Button>
            </Link>
            <Link href="/schemes">
              <Button size="lg" variant="secondary">{t("landing.ctaSchemes")}</Button>
            </Link>
          </div>
          <p className="mt-5 text-[13px] font-medium text-[var(--muted)]">{t("landing.trustText")}</p>
        </Reveal>

        {/* Chat UI mockup — static visual */}
        <Reveal trigger="load" delay={0.1} className="lg:flex-1">
          <div className="rounded-[var(--radius-xl)] bg-[var(--surface-card)] p-6">
            <div className="rounded-[var(--radius-lg)] bg-[var(--canvas)] border border-[var(--hairline)] p-5">
              {/* Mock user message */}
              <div className="flex justify-end mb-4">
                <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--cream)] px-4 py-3 text-[14px] text-[var(--ink)]">
                  What crop insurance schemes are available?
                </div>
              </div>
              {/* Mock assistant message */}
              <div className="flex justify-start">
                <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--primary)] px-4 py-3 text-[14px] text-[var(--on-primary)]">
                  <p>PMFBY provides crop insurance for farmers. Key benefits include...</p>
                  <div className="mt-2 flex gap-2">
                    <span className="inline-flex items-center rounded-full bg-[var(--on-primary)]/20 px-2 py-0.5 text-[11px] font-medium text-[var(--on-primary)]">
                      PMFBY Guidelines
                    </span>
                    <span className="inline-flex items-center rounded-full bg-[var(--on-primary)]/20 px-2 py-0.5 text-[11px] font-medium text-[var(--on-primary)]">
                      State Agriculture Dept
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* Stats — soft surface band */}
      <Reveal className="rounded-[var(--radius-xl)] bg-[var(--surface-soft)] px-4 py-10 md:px-6 md:py-12">
        <div className="grid grid-cols-3 gap-6">
          {stats.map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-[30px] font-medium leading-tight tracking-tight text-[var(--ink)] md:text-[40px]"
                 style={{ fontFamily: "var(--font-display)" }}>
                {s.n}
              </p>
              <p className="mt-1 text-[14px] text-[var(--muted)]">{s.label}</p>
            </div>
          ))}
        </div>
      </Reveal>

      {/* Saturated feature cards */}
      <section className="mt-24">
        <Reveal>
          <p className="eyebrow">Features</p>
          <h2 className="mt-3 text-[30px] font-medium tracking-tight text-[var(--ink)] md:text-[40px]"
              style={{ fontFamily: "var(--font-display)" }}>
            Everything you need
          </h2>
        </Reveal>
        <Stagger className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className={`rounded-[var(--radius-xl)] p-8 ${
                f.color === "brand-pink" ? "bg-[var(--brand-pink)] text-[var(--brand-pink-text)]" :
                f.color === "brand-teal" ? "bg-[var(--brand-teal)] text-[var(--brand-teal-text)]" :
                "bg-[var(--brand-lavender)] text-[var(--brand-lavender-text)]"
              }`}
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white/20">
                {f.icon}
              </div>
              <h3 className="mt-4 text-[18px] font-semibold">{t(f.title)}</h3>
              <p className="mt-2 text-[14px] leading-relaxed opacity-90">{t(f.text)}</p>
            </div>
          ))}
        </Stagger>
      </section>

      {/* How it works */}
      <section className="mt-24">
        <Reveal>
          <h2 className="text-[30px] font-medium tracking-tight text-[var(--ink)] md:text-[40px]"
              style={{ fontFamily: "var(--font-display)" }}>
            {t("landing.howTitle")}
          </h2>
        </Reveal>
        <Stagger className="mt-10 grid gap-8 md:grid-cols-3 md:gap-12">
          {HOW.map((h, i) => (
            <div key={h.title} className="relative">
              <span className="text-[56px] font-medium text-[var(--hairline)]" style={{ fontFamily: "var(--font-display)" }}
                    aria-hidden="true">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-3 font-medium text-[var(--ink)]">{t(h.title)}</h3>
              <p className="mt-2 max-w-sm text-[14px] leading-relaxed text-[var(--body)]">{t(h.text)}</p>
            </div>
          ))}
        </Stagger>
      </section>

      {/* CTA band */}
      <Reveal className="mt-24 rounded-[var(--radius-xl)] bg-[var(--surface-soft)] px-4 py-16 text-center md:px-6 md:py-20">
        <p className="eyebrow">{t("landing.badge")}</p>
        <h2 className="mx-auto mt-4 max-w-2xl text-[30px] font-medium leading-tight tracking-tight text-[var(--ink)] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}>
          {t("landing.ctaChat")}
        </h2>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link href="/chat">
            <Button size="lg">{t("landing.ctaChat")}</Button>
          </Link>
          <Link href="/grievance">
            <Button size="lg" variant="secondary">{t("nav.grievance")}</Button>
          </Link>
        </div>
      </Reveal>
    </div>
  );
}
```

- [ ] **Step 3: Verify landing page compiles**

Run: `cd A:\MSU\frontend && npm run build`
Expected: Page compiles, no broken imports.

- [ ] **Step 4: Commit**

```bash
git add src/app/page.tsx
git commit -m "feat: rebuild landing page with Runway hero + Clay sections"
```

---

### Task 5: Content Routes — Schemes, Services, Library, Legal

**Files:**
- Modify: `A:\MSU\frontend\src\app\schemes\page.tsx`
- Modify: `A:\MSU\frontend\src\app\schemes\[slug]\page.tsx`
- Modify: `A:\MSU\frontend\src\app\services\page.tsx`
- Modify: `A:\MSU\frontend\src\app\services\[slug]\page.tsx`
- Modify: `A:\MSU\frontend\src\app\library\page.tsx`
- Modify: `A:\MSU\frontend\src\app\legal\page.tsx`
- Modify: `A:\MSU\frontend\src\app\legal\[slug]\page.tsx`

**Interfaces:**
- Consumes: restyled Card, Badge, Input, Chips, Button, Reveal, Stagger, useI18n, data
- Produces: all content listing and detail pages with Clay styling

- [ ] **Step 1: Update schemes/page.tsx**

Read the file, then update:
- Replace `rail-frame` class with plain div
- Update display heading to use `style={{ fontFamily: "var(--font-display)" }}` with tighter tracking
- Update Card usage — no changes needed (Card component was already restyled)
- Update Badge usage — no changes needed
- The main change is removing `rail-frame` and ensuring token references work

- [ ] **Step 2: Update schemes/[slug]/page.tsx**

Read the file, then update:
- Remove `rail-frame`
- Update display heading style
- Update token references

- [ ] **Step 3: Update services/page.tsx**

Same pattern as schemes — remove `rail-frame`, update heading styles.

- [ ] **Step 4: Update services/[slug]/page.tsx**

Same pattern as schemes/[slug].

- [ ] **Step 5: Update library/page.tsx**

Read the file, then update:
- Remove `rail-frame`
- The domain filter buttons need updating — currently use inline styles with old token names. Replace with new tokens.
- Update heading style

- [ ] **Step 6: Update legal/page.tsx**

Same pattern as library.

- [ ] **Step 7: Update legal/[slug]/page.tsx**

Same pattern as schemes/[slug].

- [ ] **Step 8: Verify all routes compile**

Run: `cd A:\MSU\frontend && npm run build`
Expected: All routes compile without errors.

- [ ] **Step 9: Commit**

```bash
git add src/app/schemes/ src/app/services/ src/app/library/ src/app/legal/
git commit -m "feat: update content routes with Clay design tokens"
```

---

### Task 6: Grievance + FAQ Routes

**Files:**
- Modify: `A:\MSU\frontend\src\app\grievance\page.tsx`
- Modify: `A:\MSU\frontend\src\app\grievance\status\page.tsx`
- Modify: `A:\MSU\frontend\src\app\faq\page.tsx`

**Interfaces:**
- Consumes: restyled Button, Input, Stepper, Badge, Card, Chips, Reveal, Stagger
- Produces: grievance wizard, status page, and FAQ with Clay styling

- [ ] **Step 1: Update grievance/page.tsx**

Read the file, then update:
- Remove `rail-frame`
- Update heading style
- The wizard card already uses Card component — will pick up new styles automatically
- Update any inline token references

- [ ] **Step 2: Update grievance/status/page.tsx**

Read the file, then update:
- Remove `rail-frame`
- Update heading style
- Update token references

- [ ] **Step 3: Update faq/page.tsx**

Read the file, then update:
- Remove `rail-frame`
- Update heading style
- The FAQ accordion uses inline classes with old token names — update those
- The "Ask in chat" button in each accordion item uses inline classes — update to use Button component or new tokens

- [ ] **Step 4: Verify grievance and FAQ compile**

Run: `cd A:\MSU\frontend && npm run build`
Expected: All three pages compile.

- [ ] **Step 5: Commit**

```bash
git add src/app/grievance/ src/app/faq/
git commit -m "feat: update grievance and FAQ routes with Clay tokens"
```

---

### Task 7: Chat Interface

**Files:**
- Modify: `A:\MSU\frontend\src\components\ChatWindow.tsx`
- Modify: `A:\MSU\frontend\src\components\chat\MessageBubble.tsx`
- Modify: `A:\MSU\frontend\src\components\chat\ThinkingBubble.tsx`
- Modify: `A:\MSU\frontend\src\components\EvidenceBand.tsx`

**Interfaces:**
- Consumes: restyled Button, Skeleton, Icons, band, speech, api, i18n
- Produces: chat interface with Clay styling

- [ ] **Step 1: Read ChatWindow.tsx**

Read the full file (987 lines) to understand the structure. Key areas to update:
- Sidebar background colors (cream-2)
- Message bubble radius (16px)
- Input composer radius (12px)
- Token references throughout

- [ ] **Step 2: Update ChatWindow.tsx token references**

Search and replace:
- `var(--cream)` → `var(--surface-soft)` (sidebar bg)
- `var(--cream-2)` → `var(--surface-card)` (sidebar items)
- `var(--border-soft)` → `var(--hairline)` (borders)
- `var(--accent-primary)` → `var(--ink)` (focus states, accents)
- `var(--accent-hover)` → `var(--ink)` (hover states)
- `var(--text-body)` → `var(--body)` (text)
- `var(--text-faint)` → `var(--muted-soft)` (placeholder text)
- `var(--ink)` stays as-is
- Update bubble radius to `rounded-[var(--radius-lg)]` (16px)
- Update input radius to `rounded-[var(--radius-md)]` (12px)

- [ ] **Step 3: Update MessageBubble.tsx token references**

Same pattern of search-and-replace for old token names. Update bubble radius.

- [ ] **Step 4: Update ThinkingBubble.tsx**

Minimal changes — just token references if any are broken.

- [ ] **Step 5: Update EvidenceBand.tsx**

Update token references. The band component uses `--band-color` which is set by the band utility — ensure it maps to new tokens.

- [ ] **Step 6: Verify chat compiles**

Run: `cd A:\MSU\frontend && npm run build`
Expected: ChatWindow and related components compile.

- [ ] **Step 7: Commit**

```bash
git add src/components/ChatWindow.tsx src/components/chat/ src/components/EvidenceBand.tsx
git commit -m "feat: update chat interface with Clay design tokens"
```

---

### Task 8: Responsive Polish & Final Verification

**Files:**
- Various (responsive fixes across all pages)

**Interfaces:**
- Consumes: all restyled components and pages
- Produces: fully working, responsive Clay-styled application

- [ ] **Step 1: Run full build**

Run: `cd A:\MSU\frontend && npm run build`
Expected: Clean build, no errors.

- [ ] **Step 2: Run lint**

Run: `cd A:\MSU\frontend && npm run lint`
Expected: No lint errors.

- [ ] **Step 3: Run tests**

Run: `cd A:\MSU\frontend && npm test`
Expected: Existing tests pass (ChatWindow, MessageBubble tests may need token updates).

- [ ] **Step 4: Fix any test failures**

If tests reference old token names or classes, update them.

- [ ] **Step 5: Check for any remaining references to old tokens**

Run: `grep -r "accent-primary\|accent-hover\|accent-active\|accent-contrast\|deco-teal\|deco-blue\|ask-glow\|focus-glow" src/`
Expected: No matches (all old tokens removed).

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete Clay + Runway UI refactor"
```
