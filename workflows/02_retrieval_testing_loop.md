# Workflow: Retrieval Testing Loop

**Purpose:** Measure and validate retrieval quality — Recall@k, MRR, domain routing accuracy, and jurisdiction contamination — against a gold-standard evaluation set.

**Status:** SPEC SUPERSEDED — implemented differently (see note)

> **Current state (code-grounded):** this loop was never built as specified — there is no `python -m eval.run_retrieval_eval`, no `eval/gold_cases.yaml` or `eval/gate2_config.yaml` (the `eval/` dir holds live-probe variants: `run_live_retrieval_eval.py`, `gold_cases_live.yaml`), and no `backend/app/routes/retrieval.py`. Actual retrieval eval is `backend/tests/eval_rag_v3.py` plus the pytest suites (`test_retrieval*.py`, `test_evaluation_grounding.py`, `test_citation_*`). Treat the body below as the design record, not the implementation.

---

## Trigger

**Event:** Code change to retrieval pipeline (`backend/app/routes/retrieval.py`, `backend/app/domains.py`, `backend/app/providers/embeddings.py`) OR ingestion completion (workflow 1)

**Schedule:** None — event-driven only.

**Entry point:** `python -m eval.run_retrieval_eval` from project root

---

## Inputs

| Input | Source | Required | Validation |
|-------|--------|----------|------------|
| Gold evaluation set | `eval/gold_cases.yaml` | Yes | Must have ≥1 answerable cases per domain, each with `relevant_chunk_ids` |
| Ingested corpus | Supabase `documents` + `chunks` tables | Yes | Must have ≥1 document per domain |
| Thresholds config | `eval/gate2_config.yaml` | Yes | Must define Recall@k, MRR, contamination thresholds |
| Embedding provider | Read from `backend/app/providers/embeddings.py` | Yes | Auto-detect provider/model/dimension from code |
| Domain anchors | `backend/data/domain_anchors.json` | Yes | Must have anchor for each domain |
| Keyword rules | `backend/data/keyword_rules.json` | Yes | Must have rules for each domain |

---

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Retrieval metrics | stdout + `eval/retrieval_report.json` | JSON with Recall@1, Recall@3, Recall@5, MRR |
| Domain routing report | stdout + `eval/domain_report.json` | JSON with per-domain accuracy (diagnostic) |
| Jurisdiction contamination report | stdout + `eval/jurisdiction_report.json` | JSON with wrong-state hits |
| Failed cases | `eval/failed_cases.json` | JSON with case ID, query, expected, actual |

---

## Metrics Definitions

**Recall@k:** Fraction of answerable gold cases where ≥1 **gold-relevant chunk** (from `relevant_chunk_ids`) appears in the top-k retrieved chunks. This is the primary retrieval quality metric.

**Source-level Recall@k (diagnostic):** Fraction of answerable gold cases where ≥1 chunk from a gold-relevant source (from `relevant_source_ids`) appears in top-k. Reported separately as a diagnostic metric — useful for distinguishing "retrieval failed" from "wrong chunk within right source."

**MRR (Mean Reciprocal Rank):** Average of 1/rank where rank is the position of the first gold-relevant chunk.

**Domain routing accuracy (diagnostic):** Fraction of queries classified to the correct domain. Not a hard gate — see thresholds.

**Jurisdiction contamination:** Number of queries where a wrong-state chunk appears in retrieved results. Hard blocker at 0.

---

## Gold Case Schema

Every answerable gold case must include:

```yaml
- id: "case_001"
  query: "What are the eligibility criteria for PMFBY?"
  answerable: true
  domain: "pmfby"
  jurisdiction: "central"
  state: null
  relevant_source_ids:
    - "pmfby_operational_guidelines"
  relevant_chunk_ids:
    - "chunk_abc123"  # specific chunk IDs that contain the answer
    - "chunk_def456"
  required: true  # must be answerable in final system
```

**Evaluation is against `relevant_chunk_ids`, not merely `relevant_source_ids`.**

Source-level recall is reported as a diagnostic metric but is not the primary measure.

---

## Pipeline Stages

```
gold cases loaded
    ↓
thresholds loaded from eval/gate2_config.yaml
    ↓
embedding provider auto-detected from code
    ↓
for each gold case:
    ↓
    embed query (auto-detected provider)
    ↓
    classify domain (keyword rules → cosine anchors)
    ↓
    retrieve top-k chunks (match_chunks RPC)
    ↓
    apply jurisdiction filter
    ↓
    compare retrieved chunk_ids against gold relevant_chunk_ids
    ↓
    record: hit/miss, rank, domain, jurisdiction
    ↓
aggregate metrics
    ↓
generate report
    ↓
check against thresholds from config
    ↓
PASS / FAIL
```

---

## Invariants

1. **Gold labels are not modified to improve scores.** If retrieval fails, investigate root cause — don't change gold data.

2. **Domain classification is measured independently.** Don't conflate keyword-only accuracy with embedding-anchor accuracy.

3. **Jurisdiction filtering is measured separately from retrieval quality.** A query may retrieve correct chunks but wrong jurisdiction — that's a contamination bug, not a retrieval bug.

4. **Every retrieved chunk resolves to an existing document.** No phantom chunks.

5. **Every gold case has a verdict.** No case is silently skipped.

6. **Thresholds are read from config, not hardcoded.** `eval/gate2_config.yaml` is the single source of truth for pass/fail thresholds.

7. **Embedding provider is auto-detected.** The evaluator reads the provider, model, and dimension from the actual configured implementation — not from a hardcoded string.

---

## Thresholds

**All thresholds are read from `eval/gate2_config.yaml`.** The values below are documentation of expected ranges — the config file is authoritative.

```yaml
# eval/gate2_config.yaml
retrieval:
  recall_at_1:
    minimum: 0.40
    target: 0.70
    blocker: true
  recall_at_3:
    minimum: 0.60
    target: 0.85
    blocker: true
  recall_at_5:
    minimum: 0.80
    target: 0.95
    blocker: true
  mrr:
    minimum: 0.50
    target: 0.75
    blocker: true

jurisdiction:
  contamination:
    maximum: 0
    blocker: true  # HARD BLOCKER — any wrong-state result is a failure

domain:
  accuracy:
    minimum: 0.85
    target: 0.95
    blocker: false  # DIAGNOSTIC — not a hard gate initially
```

**Hard blockers:** Recall@k thresholds, MRR, jurisdiction contamination.
**Diagnostic:** Domain accuracy (reported but not blocking initially).

---

## Failure Behavior

| Failure Point | Behavior | Recovery |
|---------------|----------|----------|
| Gold cases file missing | Abort. Cannot evaluate without gold data. | Create gold cases, re-run |
| Gold cases empty | Abort. Nothing to evaluate. | Add cases, re-run |
| Gold case missing `relevant_chunk_ids` | Abort. Schema invalid. | Fix gold case, re-run |
| Config file missing | Abort. Cannot determine thresholds. | Create config, re-run |
| Supabase unreachable | Abort. Cannot measure retrieval against empty DB. | Fix connectivity, re-run |
| Embedding provider fails | Abort. Cannot embed queries. | Fix provider, re-run |
| Recall@k below threshold | FAIL verdict. Report failed cases. | Fix retrieval, re-run |
| MRR below threshold | FAIL verdict. Report failed cases. | Fix retrieval ranking, re-run |
| Domain accuracy below threshold | WARN verdict. Report misclassified cases. | Fix domain classifier (non-blocking) |
| Jurisdiction contamination > 0 | **HARD FAIL.** Report contaminated cases immediately. | Fix jurisdiction filter, re-run |

---

## Jurisdiction Contamination Test Cases

Construct adversarial queries:

1. "According to Gujarat cooperative law..." — must not return Maharashtra results
2. "Under Maharashtra PACS rules..." — must not return Gujarat results
3. "Can Gujarat PACS use Maharashtra provisions?" — must not cross-contaminate
4. "What are the central government guidelines?" — central sources allowed
5. "What is the Gujarat state policy on PMFBY?" — Gujarat + central allowed, Maharashtra forbidden

This workflow tests **retrieval** jurisdiction contamination only. Generation output is evaluated in workflow 05 (release gate) and the grounding/citation pytest suites (`test_evaluation_grounding.py`, `test_citation_*`). (There is no workflow 07 file.)

---

## Checkpoint

**None.** This workflow runs autonomously. Failures produce reports, not human prompts.

If hard blocker triggered (jurisdiction contamination), exit non-zero and log the specific contaminated cases.

---

## Brief (Post-Run Summary)

```
RETRIEVAL EVALUATION COMPLETE
  Gold cases: N
  Provider: {auto-detected} ({model}, {dim}d)
  
  Recall@1: 0.XX (min: from config)
  Recall@3: 0.XX (min: from config)
  Recall@5: 0.XX (min: from config)
  MRR: 0.XX (min: from config)
  
  Source-level Recall@5: 0.XX (diagnostic)
  Domain accuracy: 0.XX (diagnostic)
  Jurisdiction contamination: N (target: 0)
  
  Duration: Ns
  Verdict: PASS / FAIL
  
  Failed cases: N
  Top failure category: [insufficient corpus | poor ranking | jurisdiction leak | embedding quality]
```

---

## CI Integration

**PR (retrieval/embedding/domain code changes):**
1. Run against mock/local embedding provider (no real API calls)
2. Run against mock/local Supabase (no real DB writes)
3. Verify logic changes don't break test structure
4. No live evaluation — keeps CI fast and deterministic

**Corpus/ingestion changes (`corpus/` or `ingestion/` directories):**
1. Run ingestion loop (workflow 1) against staging Supabase
2. Run DB integrity loop (workflow 3)
3. Run this retrieval evaluation against staging
4. Check thresholds — if any blocker fails, CI fails

**Release gate (manual or tag-triggered):**
1. Run full ingestion against production Supabase
2. Run full retrieval evaluation against production
3. All hard blockers must pass

**Exit codes:**
- 0: All metrics above thresholds
- 1: One or more metrics below thresholds
- 2: Hard blocker (jurisdiction contamination)

---

## Acceptance Criteria

- [ ] Recall@5 ≥ threshold from `eval/gate2_config.yaml`
- [ ] MRR ≥ threshold from config
- [ ] Jurisdiction contamination = 0 (hard blocker)
- [ ] Domain accuracy reported as diagnostic (not blocking)
- [ ] All gold cases have `relevant_chunk_ids` and receive verdicts
- [ ] Thresholds read from config, not hardcoded
- [ ] Embedding provider auto-detected from code
- [ ] Failed cases are actionable (not just "it failed")
- [ ] CI uses mock for PRs, staging for corpus changes, production for release
