# Workflow: End-to-End Release Gate Loop

**Purpose:** Orchestrate all specialized loops into a single pass/fail gate that determines whether the foundation is safe to build on.

**Status:** SPEC SUPERSEDED — release gating is the pytest suite + PROJECT_STATUS baselines (see note)

> **Current state (code-grounded):** this loop was never built as specified — there is no `python -m eval.run_gate2`, no `eval/gate2_config.yaml`, and no `eval/gold_cases.yaml` (live variants with different names exist under `eval/`). In practice the release gate is the full backend pytest suite compared against the PROJECT_STATUS baseline (currently 1434 passed / 83 pre-existing failures) plus ruff. Treat the body below as the design record, not the implementation.

---

## Trigger

**Event:** Pre-release OR after any significant code change OR manual invocation

**Schedule:** None — event-driven only. This is the final gate before declaring foundation complete.

**Entry point:** `python -m eval.run_gate2` from project root

---

## Inputs

| Input | Source | Required | Validation |
|-------|--------|----------|------------|
| MVP manifest | `corpus/manifests/mvp_sources.yaml` | Yes | Must parse as valid YAML |
| Seed/MD files | `corpus/seeds/*.md` | Yes | Every manifest path must resolve |
| Gold evaluation set | `eval/gold_cases.yaml` | Yes | Must have ≥1 answerable cases per domain |
| Supabase credentials | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` env vars | Yes | Must be non-empty |
| Embedding provider | `JINA_API_KEY` env var | Yes | Must be non-empty |
| LLM providers | `GROQ_API_KEY`, `GEMINI_API_KEY` env vars | Yes | At least one must be non-empty |

---

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Gate report | stdout + `eval/gate_report.json` | JSON with pass/fail per gate |
| Final verdict | stdout | PASS / FAIL / PASS WITH DEFERRED RISKS |
| Release artifact | `eval/release_baseline.json` | JSON with corpus snapshot, metrics, commit |

---

## Pipeline Stages (Sequential)

```
GATE 0: Environment check
    ↓
GATE 1: Corpus validation
    ↓
GATE 2: Ingestion
    ↓
GATE 3: Database integrity
    ↓
GATE 4: Retrieval evaluation
    ↓
GATE 5: Jurisdiction evaluation
    ↓
GATE 6: Evidence/abstention evaluation
    ↓
GATE 7: Generation + citation evaluation
    ↓
GATE 8: API E2E tests
    ↓
GATE 9: Security checks
    ↓
GATE 10: Regression suite
    ↓
FINAL VERDICT: PASS / FAIL / PASS WITH DEFERRED RISKS
```

---

## Gate Definitions

### GATE 0: Environment Check
- Supabase reachable
- Embedding provider reachable
- At least one LLM provider reachable
- All env vars present

**Failure:** ABORT — cannot proceed without working providers.

### GATE 1: Corpus Validation
- All MVP files on disk
- Manifest valid
- No placeholder content

**Failure:** ABORT — cannot ingest invalid corpus.

### GATE 2: Ingestion
- All 11 sources ingested
- No ingestion errors

**Failure:** ABORT — cannot evaluate empty corpus.

### GATE 3: Database Integrity
- Zero orphan chunks
- Zero duplicate source_ids
- Zero null embeddings
- Zero wrong-dimension embeddings
- All documents have valid metadata

**Failure:** BLOCKING — corrupted data invalidates all downstream tests.

### GATE 4: Retrieval Evaluation
- All thresholds read from `eval/gate2_config.yaml`
- Recall@k, MRR must meet minimums from config
- Jurisdiction contamination = 0 (hard blocker from config)

**Failure:** BLOCKING — poor retrieval means poor answers.

### GATE 5: Jurisdiction Evaluation
- Domain accuracy reported (diagnostic, not blocking per config)
- Jurisdiction contamination = 0 (hard blocker)

**Failure:** BLOCKING if contamination > 0 — wrong-state results are a safety violation. Domain accuracy below threshold is a warning, not a blocker.

### GATE 6: Evidence/Abstention Evaluation
- unsafe_answer_rate = 0%
- Abstention rate reasonable (not 100%, not 0%)
- False abstention rate < 20%

**Failure:** BLOCKING — unsafe answers are unacceptable.

### GATE 7: Generation + Citation Evaluation
- All citations resolve to existing chunks
- No hallucinated citations
- No citations to wrong jurisdiction
- Citation provenance accuracy = 100%

**Failure:** BLOCKING — unverified citations undermine trust.

### GATE 8: API E2E Tests
- All response schemas valid
- No stack traces in responses
- No secret leakage
- Session isolation works
- Language detection works

**Failure:** BLOCKING — API contract violations break clients.

### GATE 9: Security Checks
- Prompt injection resisted
- Instruction injection in documents resisted
- No .env exposure
- No NEXT_PUBLIC secret exposure
- No path traversal

**Failure:** BLOCKING — security violations are non-negotiable.

### GATE 10: Regression Suite
- Zero newly introduced failures compared to baseline
- All critical foundation tests pass (domain routing, retrieval, evidence gate, citation verification, API contract)
- No test silently swallowing failures (no `assert True`, no bare `except`, no `pass` in except blocks)

**Failure:** BLOCKING — regressions undermine confidence.

**Note:** Test counts are derived dynamically from the current test inventory, not hardcoded. The baseline is established at gate startup by running the full suite and recording pass/fail counts. Regression means: no test that passed in the baseline now fails.

---

## Invariants

1. **Gates are sequential.** If Gate N fails, Gate N+1 does not run. This saves time and prevents cascading false results.

2. **Hard gates are non-negotiable.** Gates 3-9 are hard gates. If any fails, the verdict is FAIL. No exceptions. Domain accuracy is diagnostic (not blocking) per config.

3. **Soft gates allow deferral.** Gate 10 (regression) can have deferred risks if the failing test is non-critical and documented. The baseline is captured at gate startup, not hardcoded.

4. **Metrics are measured, not gamed.** If a metric fails, investigate root cause. Do not weaken thresholds, modify gold labels, or skip tests.

5. **Thresholds are config-driven.** `eval/gate2_config.yaml` is the single source of truth for all pass/fail thresholds. Hardcoded values in workflow specs are documentation only.

6. **The gate is the single source of truth.** If the gate says PASS, the foundation is safe. If it says FAIL, it's not. No overrides without explicit human approval.

---

## Failure Behavior

| Failure Point | Behavior | Recovery |
|---------------|----------|----------|
| Gate 0 fails | ABORT. Cannot proceed. | Fix environment, re-run from Gate 0 |
| Gate 1 fails | ABORT. Cannot ingest. | Fix corpus, re-run from Gate 1 |
| Gate 2 fails | ABORT. Cannot evaluate. | Fix ingestion, re-run from Gate 2 |
| Gates 3-9 fail | BLOCKING FAIL. Report specific violations. | Fix issue, re-run from failed gate |
| Gate 10 fails | SOFT FAIL. Report regressions. | Fix regression or document deferral |

---

## Checkpoint

**Yes — one checkpoint at the end.**

After all gates complete, present a brief to the human:

```
RELEASE GATE VERDICT: [PASS / FAIL / PASS WITH DEFERRED RISKS]

Gates passed: N/11
Gates failed: N
Hard gate failures: N

Corpus: N documents, N chunks
Retrieval: Recall@5 = 0.XX, MRR = 0.XX
Jurisdiction: contamination = N
Abstention: unsafe_rate = 0.XX%
Citations: accuracy = 0.XX%
Security: N violations
Regression: N failures

Deferred risks: [list if any]

Recommendation: [proceed / fix before proceeding]
```

The human reads this brief and decides whether to proceed.

---

## Brief (Post-Run Summary)

Same as the checkpoint brief above. This IS the brief.

---

## CI Integration

**Trigger:** Pre-release tag OR manual invocation.

**Steps:**
1. Run all 11 gates sequentially
2. If any hard gate fails, CI fails — no release
3. If all hard gates pass, CI passes — release candidate ready
4. Store release artifact for future regression comparison

**Exit codes:**
- 0: All gates pass (or PASS WITH DEFERRED RISKS)
- 1: One or more hard gates fail
- 2: Environment check fails (cannot proceed)

---

## Acceptance Criteria

- [ ] All 11 gates defined with explicit pass/fail criteria
- [ ] Hard gates (3-9) are non-negotiable
- [ ] Sequential execution — no gate runs if previous failed
- [ ] Human checkpoint at end with decision-ready brief
- [ ] Release artifact generated for reproducibility
- [ ] CI integration defined
- [ ] This workflow orchestrates workflows 1-4, does not replace them
