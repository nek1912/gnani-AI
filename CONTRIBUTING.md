# Contributing Guide

## Overview

This project is a 4-person, 10-day hackathon build. Contributions are welcome
but must respect the frozen specs, non-negotiable principles, and scope discipline
defined in `CLAUDE.md`.

## Rules (Non-Negotiable)

1. **The LLM is never the source of truth.** Every factual answer must be grounded
   in retrieved official documents with verifiable citations.
2. **Never fabricate facts, citations, dates, deadlines, legal clauses, or contacts.**
3. **If retrieval confidence is low, abstain.** Do not guess.
4. **Grievances are PROTOTYPE references only.** Always return
   `is_official_submission: false`. Never claim real government submission.
5. **Central and state law can differ.** Always attach jurisdiction + effective-date
   metadata. Never present national/model rules as universally applicable.
6. **Every citation must map to a chunk ID that was actually retrieved in that request.**
7. **Never put API keys in frontend code, commit them, or expose them via
   non-`VITE_` variables (only `VITE_`-prefixed vars reach the browser bundle).**

## Development Workflow

1. **Read `PROJECT_STATUS.md` first.** It tells you what's actually built, what's
   stubbed, what's broken, and what the next action is.
2. **Branch from `main`.** Use descriptive branch names: `feat/...`, `fix/...`, `docs/...`.
3. **Follow TDD.** Write failing tests first, implement, verify tests pass.
4. **Commit frequently.** Small, focused commits with clear messages.
5. **Update `PROJECT_STATUS.md`** at the end of every work session.
6. **Log deviations in `DECISIONS.md`** if you deviate from frozen specs.

## Code Style

### Python (Backend)

- Type hints everywhere
- Pydantic models for all request/response bodies
- No bare `except` — use specific exception types
- Every external provider call goes through an adapter with explicit timeout
  and fallback handling
- Structured logs — never log API keys, auth tokens, or full grievance PII

### TypeScript (Frontend)

- Follow existing patterns in `frontend/src/`
- Use the existing `lib/api.ts` for API calls
- Evidence bands (not raw percentages) for confidence display

### Testing

- Backend: `pytest` + `pytest-asyncio`, providers mocked with `respx`
- Frontend: `vitest` + React Testing Library
- CI: `ruff` (Python lint) + `pytest` + `vitest` on every push

## Test Areas (Required)

Per `CLAUDE.md`, write tests for:
- Domain routing
- Jurisdiction filtering
- Retrieval
- Citation validity
- Abstention
- Grievance workflow
- Provider fallback
- API failure handling

## Commit Messages

Use conventional commits:
```
feat: add new feature
fix: bug fix
docs: documentation update
test: add or update tests
refactor: code restructuring
chore: maintenance tasks
```

## Pull Requests

1. PR description should explain **what** and **why**, not **how**
2. All tests must pass
3. No secrets or API keys in the diff
4. Update `PROJECT_STATUS.md` if your change affects component status
5. Log any spec deviation in `DECISIONS.md`

## Architecture Decisions

Significant architectural or design decisions must be:
1. Discussed with the team
2. Logged in `DECISIONS.md` with: what changed, why, what it replaced, who/when
3. Reflected in the relevant spec file (`architecture.md`, `design.md`, etc.)

## Scope Discipline

Read `PRD.md` for full scope. Summary:

**MVP (Tier 1 & Tier 2):** 11-language (EN, HI, GU, MR, BN, TA, TE, KN, PA, OR, ML — expanded from the original 6) text + Sarvam voice chat, central cooperative info + Gujarat
rules, 8-15 curated schemes, PMFBY, agriculture workflows, RBI/PMJDY financial
literacy, 9-stage grievance workflow (text + status lookup), citations, confidence, abstention, responsive static SPA (React + Vite, not a PWA).

**Do NOT add before core is stable:** native apps, WhatsApp, blockchain, custom
model training, self-hosted GPU, multi-agent frameworks, complex auth, analytics
dashboard, real government grievance submission, nationwide legal coverage.

If you're asked to build something on this "do not add" list, push back and point
to `CLAUDE.md` rather than silently doing it.

## Provider Accounts

| Provider | Purpose | Free Tier |
|---|---|---|
| Supabase | Database + pgvector | 500MB, 50K MAU |
| Jina | Primary embeddings (jina-embeddings-v3, 768d) | Rate limited |
| Groq | Primary LLM (openai/gpt-oss-120b) | Rate limited |
| Gemini | Fallback LLM + reranker | Rate limited |
| Sarvam AI | Primary STT, TTS, translation | Rate limited |
| Tavily | Primary web search | Rate limited |
| Firecrawl | Web crawl / scrape fallback | Rate limited |
| Azure Cognitive Services | Fallback STT only | Rate limited |
| Render | Backend hosting | Sleeps on inactivity |
| Static host/CDN | Frontend hosting (`npm run build` → `dist/`) | Hobby tier |

See `docs/runbooks/provider-setup.md` for setup instructions.

## Questions?

Open an issue or reach out to the team.
