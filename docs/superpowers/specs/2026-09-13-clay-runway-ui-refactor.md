# Design Spec: Clay + Runway UI Refactor

**Date:** 2026-09-13
**Scope:** Full UI refactor — tokens, components, landing page, all 12 routes, navigation, footer
**Design System:** Clay (cream canvas, 6-color saturated cards, Space Grotesk display)
**Hero Layout:** Runway-style (big text left, chat UI mockup right)

---

## 1. Design Foundation

### 1.1 Color Palette

Replace the current Zapier warm-editorial palette entirely.

**Canvas & Surfaces:**
- `--canvas`: #fffaf0 (cream-tinted white page floor)
- `--surface-soft`: #faf5e8 (footer background, CTA bands)
- `--surface-card`: #f5f0e0 (cream feature cards, testimonials)
- `--surface-strong`: #ebe6d6 (emphasized bands, rare)
- `--surface-dark`: #0a1a1a (dark teal-tinted near-black, rare)
- `--surface-dark-elevated`: #1a2a2a (elevated dark cards)

**Primary & Interactive:**
- `--primary`: #0a0a0a (all primary CTAs, headlines)
- `--on-primary`: #ffffff (text on primary buttons + dark feature cards)

**Brand Colors (Feature Card Surfaces):**
- `--brand-pink`: #ff4d8b — text: #ffffff — outbound/sequencer feature cards
- `--brand-teal`: #1a3a3a — text: #ffffff — enterprise/featured pricing tier
- `--brand-lavender`: #b8a4ed — text: #0a0a0a — AI-agent feature cards
- `--brand-peach`: #ffb084 — text: #0a0a0a — general warmth feature cards
- `--brand-ochre`: #e8b94a — text: #0a0a0a — community/experts feature cards
- `--brand-mint`: #a4d4c5 — text: #0a0a0a — illustration accents, badges
- `--brand-coral`: #ff6b5a — text: #ffffff — highlight accents

**Text Ramp:**
- `--ink`: #0a0a0a (headlines, primary text)
- `--body-strong`: #1a1a1a (emphasized body, lead paragraphs)
- `--body`: #3a3a3a (default running text)
- `--muted`: #6a6a6a (sub-headings, breadcrumbs, footer body)
- `--muted-soft`: #9a9a9a (captions, fine-print)
- `--on-dark`: #ffffff (text on dark feature cards)

**Borders & State:**
- `--hairline`: #e5e5e5 (1px borders on cards, inputs)
- `--success`: #22c55e
- `--warning`: #f59e0b
- `--error`: #ef4444

**Removed Tokens:**
- `--accent-primary` (orange) replaced by `--primary` (near-black)
- `--accent-hover`, `--accent-active`, `--accent-contrast` no longer needed
- `--accent-tint-soft`, `--accent-tint-strong` replaced by brand color tints
- `--ask-glow`, `--focus-glow` replaced by ink focus ring
- `--deco-*` palette replaced by brand colors for category distinction

### 1.2 Typography

**Font Family:**
- Display: Space Grotesk weight 500 (fallback: var(--font-script), system-ui)
- Body: Inter weights 400/500/600 (fallback: var(--font-script), system-ui)
- Mono: Geist Mono weight 400
- Answer: Georgia, "Times New Roman" (fallback: var(--font-script), serif)

**Type Scale:**
- `display-xl`: 72px, weight 500, line-height 1.0, letter-spacing -0.04em — Homepage h1
- `display-lg`: 56px, weight 500, line-height 1.05, letter-spacing -0.035em — Section heads
- `display-md`: 40px, weight 500, line-height 1.1, letter-spacing -0.025em — Sub-section heads
- `display-sm`: 32px, weight 500, line-height 1.15, letter-spacing -0.015em — CTA-band heads
- `title-lg`: 24px, weight 600, line-height 1.3, letter-spacing -0.012em — Plan names
- `title-md`: 18px, weight 600, line-height 1.4 — Card titles, intro paragraphs
- `title-sm`: 16px, weight 600, line-height 1.4 — Small card titles
- `body-md`: 16px, weight 400, line-height 1.55 — Default running text
- `body-sm`: 14px, weight 400, line-height 1.55 — Footer body, fine-print
- `caption`: 13px, weight 500, line-height 1.4 — Badge labels
- `caption-upper`: 12px, weight 600, line-height 1.4, letter-spacing 1.5px — Section labels
- `button`: 14px, weight 600, line-height 1.0 — Button labels
- `nav-link`: 14px, weight 500, line-height 1.4 — Top-nav menu items

**Rule:** Space Grotesk at weight 500 + negative letter-spacing IS the brand voice. Never go to weight 700.

### 1.3 Spacing

Base unit: 4px.
- `xxs`: 4px — tight inline gaps
- `xs`: 8px — small gaps
- `sm`: 12px — card internal small gaps
- `md`: 16px — standard gaps
- `lg`: 24px — card padding (content cards)
- `xl`: 32px — card padding (feature cards)
- `xxl`: 48px — section sub-spacing
- `section`: 96px — between major editorial bands

### 1.4 Border Radius

- `xs`: 6px — small badges, dropdown items
- `sm`: 8px — small buttons
- `md`: 12px — standard CTA buttons, text inputs
- `lg`: 16px — content cards, testimonial cards
- `xl`: 24px — feature cards (saturated brand-color cards)
- `pill`: 9999px — category tabs, badge pills, nav sign-up
- `full`: 50% — avatars, icon buttons

### 1.5 Elevation & Depth

No heavy shadows. Depth comes from saturated color contrast.

- Flat: no shadow, no border — body sections, hero
- Soft hairline: 1px hairline border — inputs, small content cards
- Saturated card: brand color fill, no shadow — feature cards
- Cream card: surface-card bg, no shadow — testimonials, secondary cards

---

## 2. Landing Page

### 2.1 Hero — Runway-Style Split

Layout: 7-column left / 5-column right on desktop. Single column on mobile.

**Left side:**
- Eyebrow: caption-upper style — section label
- h1: display-xl (72px desktop, 36px mobile) — big bold headline
- Subtitle: body-md — description paragraph
- Two CTAs: Primary (near-black bg) + Secondary (cream bg, hairline border)
- Trust text: caption style

**Right side:**
- Cream rounded card (surface-card bg, rounded.xl 24px)
- Inside: styled chat UI mockup showing sample query + cited response
- Mockup is static (not interactive) — purely visual
- Sits on a subtle cream-soft background shape

**Mobile:** Single column, h1 shrinks to 36px, mockup stacks below CTAs.

### 2.2 Stats Band

Below hero. Surface-soft background (#faf5e8). 3-column grid:
- Schemes count, services count, library docs count
- Large display numbers (display-md), muted label below

### 2.3 Saturated Feature Cards

3-column grid (2-up tablet, 1-up mobile). Cards cycle through brand colors:
1. Brand Pink — Multilingual Support (white text)
2. Brand Teal — Evidence-Backed Answers (white text)
3. Brand Lavender — Voice Enabled (ink text)
4. Brand Peach — 6 Languages (ink text)
5. Brand Ochre — Grievance Support (ink text)
6. Surface Card (cream) — Document Library (ink text)

Each card: rounded.xl (24px), padding xl (32px), h3 in title-md, body description, small product UI fragment.

### 2.4 How It Works

3 numbered steps. Large display numbers (display-lg, muted). Title + description below each.

### 2.5 CTA Band

Surface-soft background. Rounded.xl container. display-md headline + primary CTA button.

### 2.6 Cream Footer

Surface-soft background (#faf5e8). 4-column link grid. Logo + copyright at bottom. NO dark sections.

---

## 3. Navigation

### 3.1 Top Nav (Desktop)

- 64px tall, canvas background, sticky
- Logo left (JanSayah + orange accent underline — kept from current)
- Nav links center: Inter 14px/500, active = ink text + 2px bottom border
- Right cluster: Language switcher + "Chat" pill button (near-black bg, white text, full pill radius)
- Links: Schemes, Services, Library, Legal, FAQ

### 3.2 Mobile Nav

- Hamburger icon top-right
- Slide-out panel from right: all links + language switcher + chat CTA
- NO bottom tab bar (removed)

---

## 4. Component Restyling

### 4.1 Button

- **Primary:** bg #0a0a0a, text #ffffff, radius 12px, height 44px, Inter 14px/600. Hover: slightly lighter.
- **Secondary:** bg canvas, text ink, 1px hairline border, radius 12px. Hover: cream bg.
- **On-color:** white bg, ink text — used on saturated feature cards.
- **Ghost:** transparent bg, ink text. Hover: cream bg.

### 4.2 Card

- **Feature:** 24px radius, 32px padding, saturated brand color fill. Text white on pink/teal, ink on lavender/peach/ochre/cream.
- **Content:** 16px radius, hairline border, canvas bg.
- **Cream:** surface-card bg, 16px radius.

### 4.3 Input

- 12px radius, hairline border, canvas bg, 44px height. Focus: ink border.

### 4.4 Badge/Pill

- Full pill radius (9999px), 13px/500, cream-2 bg.

### 4.5 Stepper

- Updated radius tokens. Same 3-step logic. Cream progress indicator.

---

## 5. Route Treatments

All routes use rail-frame page-container with Clay tokens.

- `/` — Full rebuild (Runway hero + Clay sections)
- `/chat` — Full-page, no nav. ChatWindow gets new token colors. 16px radius bubbles.
- `/schemes` — Same layout, new tokens. Brand colors for category chips.
- `/schemes/[slug]` — Cream card layout, brand-colored section headers.
- `/services` — Same as schemes.
- `/services/[slug]` — Same treatment.
- `/library` — 16px radius cards, new icon colors.
- `/legal` — Same pattern as library.
- `/legal/[slug]` — Serif answer font, cream card wrapper.
- `/grievance` — New button/input styles, cream progress indicator.
- `/grievance/status` — New badge/stepper styles.
- `/faq` — New radius, brand-colored category chips.

---

## 6. Responsive Behavior

- Mobile (< 768px): hamburger nav, hero h1 72->36px, hero mockup stacks below, feature grids 1-up, pricing 1-up
- Tablet (768-1024px): top nav tightens, feature cards 2-up
- Desktop (1024-1440px): full nav, 3-up feature cards
- Touch targets: minimum 44x44px for buttons and inputs

---

## 7. Accessibility

- Contrast 4.5:1 for body text, 3:1 for large display text
- All interactive elements have visible focus states (ink outline)
- prefers-reduced-motion guard on all animations
- Keyboard navigation throughout
- Aria labels on icon-only buttons

---

## 8. Implementation Order

1. globals.css — replace all tokens, update @theme inline
2. TopNav + MobileNav (hamburger) — restyle, remove bottom tab bar
3. Button, Card, Input, Badge, Stepper — restyle components
4. Landing page — full rebuild
5. Routes — apply new tokens and component styles
6. Chat interface — update colors and radius
7. Footer — add cream footer component
8. Responsive testing and polish
