# Facet-Aware Retrieval + Coverage Selection — Design Spec

Date: 2026-10-07
Scope: multi-intent decomposition + facet-aware retrieval + coverage selection, plus separately tracked domain-gate fall-through fix and sessions.user_id migration check.
Status: draft for review (option C approved — hybrid fast-path + facet path).

## 1. Problem

Compound queries (e.g. PM-KISAN + PMFBY + Farmer Registry + Gujarat + land-record issue) are classified to a single domain (`backend/app/domains.py:23-35` returns first keyword hit with 1.0). `effective_domain` (`backend/app/web_rag/query_classifier.py:797-815`) then forces both pipelines onto that domain. Merge (`backend/app/services/rag_orchestrator.py:743-790`) ranks by score and caps to 6+6, with no notion of question coverage. Confidence averages retrieval bands, not facet coverage. Result: `abstained=False, confidence=0.65/medium` while entire facets lack evidence, and the LLM fills gaps from parametric knowledge.

Existing machinery is unused on the main path: `ScenarioPlanner` / `ScenarioReasoningEngine.retrieve_per_requirement` (`backend/app/scenario_reasoning.py:510-582`) and bounded web facets (`backend/app/web_rag/facets.py:1-40`, max 2 branches, advisory-only).

## 2. Constraints (frozen, must not change)

- WebDiscovery: `ThreadPoolExecutor` fan-out, `MAX_BRANCHES=8`, provider timeout 5s, `web_rag_timeout_s=30.0`. No asyncio inside WebDiscovery, no new executors, no wider pools.
- `WebRAGService.retrieve(deadline)` cooperative deadline: orchestrator passes `started + web_rag_timeout_s` on both web paths; no NEW recovery round starts past it. `MAX_RECOVERY_ROUNDS=2`.
- Reranker stays off (`RERANKER_ENABLED=false`).
- No new search providers. SerpApi Search Index stays rejected.
- Thresholds untouched: `TOP1_THRESHOLD=0.25`, relevance 40.0, RRF/BM25/verifier/branches unchanged.
- RAGResponse contract unchanged (additive `coverage` metadata only; existing clients ignore unknown keys).

## 3. Architecture

Single-domain fast-path preserved exactly. Multi-signal queries take a bounded facet path:

```
english_query + anchor hits + classification
  -> FacetRouter (deterministic)
    -> single facet -> current RAGOrchestrator.run() unchanged
    -> multi facet (max 3) -> per-facet static + selective web
      -> coverage-aware merge (max 12, min 2 per supported facet)
      -> per-facet grounding + coverage-adjusted confidence
      -> LLM with facet-scoped prompt
```

## 4. Components

### 4.1 FacetRouter (`app/facets.py`, new, ~80 lines, deterministic only)

Input: `english_query`, all AnchorStore keyword hits (not just first), `QueryClassification`, `QueryComplexity`.
Output: `list[Facet{facet_id, domain, query, state}]`.

- Collect every domain whose keyword list hits (word-boundary rules from `domains.py`), plus scheme-code identifiers (`pmfby`, `pm-kisan`, `pmkisan`, `farmer registry`, `farmer id`).
- Normalize via existing maps: `static_rag._DOMAIN_MAP` for static, `SUPPORTED_DOMAINS` for web. `agriculture -> pmfby` static mapping retained; web keeps `agriculture` distinct.
- Router triggers multi-facet only when: >=2 distinct domains/scheme codes hit, OR complexity in (`MULTI_CONDITION`, `COMPARISON`, `MULTI_HOP`) with >=2 conjunctions/questions, OR explicit enumeration of schemes.
- Otherwise returns single facet `{domain=current effective_domain, query=english_query, state=resolved_state}` — behavior identical to today.
- Max 3 facets; priority: explicit scheme codes > AnchorStore hits > classifier domain. Extra signals dropped with `metadata["dropped_facets"]` logged. Each facet query = deterministic slice: the matched scheme/domain keywords plus up to 8 surrounding words from the original English query plus the explicit state word if present. No added `site:` restrictions beyond existing per-domain logic, no synonym expansion.

### 4.2 Facet-aware retrieval (orchestrator change, bounded)

- Static: per-facet `StaticRAGService.retrieve` with `k=10` (down from 25; total <=30 rows, still cheap pgvector). Reuses single query embedding per facet query — requires re-embed per facet (Jina). Cache embeddings via existing `_cached_embedding`.
- Web: per-facet `WebRAGService.retrieve` only for facets needing current/external evidence (`requires_dynamic` or domain in `schemes/agriculture/pmfby` with state/jurisdiction terms, or web-only intent). Single-facet path keeps one web call as today. Multi-facet path: max 2 web facets (mirrors `MAX_FACET_BRANCHES=2`), sequential `to_thread` calls sharing the single outer `deadline`; no new thread pools.
- Budgets: static unbounded within ms; web total still bounded by `web_rag_timeout_s` + `wait_for`. If deadline passes, remaining facets marked `unsupported (timeout)` — never extend the deadline.
- Single-facet requests execute byte-identical code paths to today (same k=25, same web call).

### 4.3 Coverage-aware selector (replaces score-only top-N on multi-facet path)

- Group merged chunks by facet (domain match + keyword overlap with facet query).
- Keep best 2-3 per facet by existing score order (static cosine, web rerank — never cross-compare scales beyond current per-source caps).
- Global cap 12 (6 static + 6 web preserved). Fill order: round-robin across supported facets, then score order.
- Emit `coverage: {facet_id: {status: supported|partial|unsupported, chunk_ids: [...]}}`. `supported` = >=1 chunk with dense>=0.40 or web relevance>=40 and gate pass; `partial` = chunks present but below bar; `unsupported` = abstained/empty/timeout.
- Single-facet path keeps current `_merge_evidence` untouched.

### 4.4 Prompt + grounding (per-facet partial answers)

- Evidence section grouped by facet header (`== FACET: pmfby ==`), each with its chunks. Uncovered facets get explicit `No evidence retrieved for this facet.` block.
- Instruction delta (minimal): answer each facet under its own bold sub-heading; for unsupported facets output exactly `Evidence insufficient for [facet] — not answered. Consult the concerned government office.` No parametric fill. Existing rules 2, 5, 8, 10 (evidence-first, no invented numbers, citation format with full web IDs) unchanged.
- Citation verification unchanged (must map to retrieved IDs or ABSTAIN). Grounding check (`verify_answer_grounding`) unchanged and still enforcing with repair-then-abstain.
- Confidence: start from existing `_calculate_confidence`, then multiply by `0.5 + 0.5 * (supported_facets / total_facets)` and cap repaired answers at MEDIUM as today. Zero facets supported -> full abstain path (existing `_abstain_response` + referral).

### 4.5 Domain-gate fall-through fix (separate, small)

- Add regression tests: PACS query must not accept `pmfby/schemes` chunks and vice versa. Audit `_DOMAIN_ALIASES` (`backend/app/evidence_gate.py:20-28`): `schemes<->pmfby` and `agriculture<->pmfby` aliasing is the suspect. Fix: exact-match gate for `pacs_governance/pacs_computerization` vs `pmfby/schemes/agriculture`; retain `agriculture->pmfby` static retrieval map (corpus gap) but gate on retrieved chunk domain strictly. No threshold changes.

### 4.6 Sessions user_id migration (separate, ops + hardening)

- Verify `supabase/migrations/20261007_sessions_user_id.sql` applied in prod (column + index exist).
- Add startup check in `session_store`: if `user_id` column missing, log error once (existing warn) and keep quarantine semantics (legacy NULL rows inaccessible). Do not fail open ownership: `is_session_owner` already returns False for legacy/missing; `_is_chat_session_foreign` treats legacy as foreign. No RLS change, no data deletion.
- Acceptance: with migration applied, cross-user session read returns empty history + None state; without migration, warning fires once and ownership checks stay disabled but visible.

## 5. Data flow (multi-facet example)

PM-KISAN + PMFBY + Farmer Registry (Gujarat) -> router emits 3 facets (schemes/pm-kisan, pmfby, schemes/farmer-registry, all state=Gujarat) -> static x3 (k=10) + web x2 (pmfby + registry, shared deadline) -> coverage `{pmfby: supported(3), pm-kisan: unsupported, registry: partial(1)}` -> prompt with 2 evidence groups + 1 insufficient block -> answer covers PMFBY + partial registry, marks PM-KISAN insufficient -> confidence penalized (e.g. 0.7 -> 0.52 MEDIUM).

## 6. Error handling

- Facet split failure -> fall back to single-facet current path (never crash the request).
- Per-facet retrieval exception -> facet `unsupported (provider_unavailable)`, other facets continue.
- Web timeout -> remaining facets `unsupported (timeout)`; static evidence still answers.
- LLM/planner never used for splitting (deterministic), so no extra provider failure mode. Optional LLM refinement explicitly out of scope for this spec.

## 7. Testing

- Unit: router (single PMFBY unchanged; triple-scheme splits to 3; PACS+PM-KISAN splits to 2; Gujarati single stays single); selector (round-robin coverage beats score-only on crafted chunks); confidence penalty math.
- Integration (mocked providers + Supabase): the 4 acceptance cases from the report — (1) single PMFBY byte-similar evidence set, (2) triple query yields 3 evidence paths with coverage 3/3 or explicit partials, (3) PACS+PM-KISAN neither domain suppresses the other, (4) Gujarati single no-split and no latency regression (web calls == 1).
- Regression: full existing suites for orchestrator/recovery/WebRAG/deadline/facets/gate must stay green; gate alias tests added.
- Manual: latency probe — multi-facet p50 within existing 30s budget; timeout case marks facets unsupported instead of hanging.

## 8. Risks and non-goals

- Non-goal: general RAG rewrite, new rerankers, new search providers, query-expansion tuning, evidence-cap tuning alone.
- Risk: per-facet re-embedding adds Jina calls (max 3 vs 1). Mitigation: cache + k=10 reduction + web facet cap 2.
- Risk: deterministic splitter misses paraphrases with no keyword. Accepted: fallback is current single-domain behavior (no worse than today); LLM refinement deferred.
- Gate alias tightening requires a PACS reproduction test first (plan must add the failing test before changing `_DOMAIN_ALIASES`). Startup migration check default: keep existing `session_store` warn-once plus add a `main.py` lifespan check that logs error when the column is missing; no fail-open ownership change.

## 9. Acceptance

Single-domain behavior and latency unchanged; multi-domain queries retrieve per-facet, select by coverage, answer supported facets while explicitly marking unsupported ones; gate and migration fixes verified independently.
