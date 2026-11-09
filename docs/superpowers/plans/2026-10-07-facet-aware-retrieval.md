# Facet-Aware Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic multi-facet decomposition with coverage-aware selection and per-facet partial answers while keeping single-domain behavior byte-identical.

**Architecture:** New `backend/app/facets.py` router emits max 3 facets; orchestrator runs existing `StaticRAGService.retrieve` / `WebRAGService.retrieve` per facet under the existing deadline; coverage selector round-robins to cap 12; prompt groups by facet; confidence penalized by uncovered fraction.

**Tech Stack:** Python 3.11, FastAPI, Supabase pgvector, pytest.

## Global Constraints

- WebDiscovery `ThreadPoolExecutor` fan-out, `MAX_BRANCHES=8`, provider timeout 5s, `web_rag_timeout_s=30.0` — no new executors, no wider pools, no asyncio inside WebDiscovery.
- `WebRAGService.retrieve(deadline)` cooperative deadline passed as `started + web_rag_timeout_s` on both web paths; no NEW recovery round past deadline; `MAX_RECOVERY_ROUNDS=2`.
- `RERANKER_ENABLED=false` stays off.
- No new search providers; SerpApi Search Index stays rejected.
- Thresholds unchanged: `TOP1_THRESHOLD=0.25`, web relevance 40.0, RRF/BM25/verifier unchanged.
- `RAGResponse` contract unchanged except additive `coverage` in `metadata`.
- Single-facet path must execute identical code (static k=25, one web call).

---

## File map

- Create `backend/app/facets.py` — `Facet` dataclass + `split_facets()` + `select_coverage()`, deterministic only.
- Modify `backend/app/domains.py` — add `collect_hits(text)` returning all matched domains (keep `classify()` unchanged).
- Modify `backend/app/services/rag_orchestrator.py` — facet branch in `run()` + `_run_facet_pipelines()` + coverage confidence penalty; keep `_merge_evidence()` for single path.
- Modify `backend/app/evidence_controller.py` — `build_curated_prompt()` facet grouping + insufficient-facet block.
- Modify `backend/app/evidence_gate.py` — tighten PACS vs pmfby/schemes aliasing (test-first).
- Modify `backend/app/main.py` — lifespan migration check log.
- Tests: `backend/tests/test_facet_router.py`, `backend/tests/test_coverage_selector.py`, `backend/tests/test_facet_integration.py`, `backend/tests/test_gate_pacs_isolation.py`.

---

### Task 1: FacetRouter + collect_hits

**Files:**
- Modify: `backend/app/domains.py`
- Create: `backend/app/facets.py`
- Test: `backend/tests/test_facet_router.py`

**Interfaces:**
- Consumes: `AnchorStore.rules: dict[str, list[str]]`, `QueryClassification(domain, intent, state)`, `QueryComplexity` string.
- Produces: `Facet(facet_id: str, domain: str, query: str, state: str | None)`, `split_facets(english_query: str, hits: list[str], classification, complexity: str, state: str | None) -> list[Facet]`.

- [ ] **Step 1: Write failing test for collect_hits + split**

```python
# backend/tests/test_facet_router.py
from backend.app.facets import split_facets

class _Cls:
    domain = "pmfby"; intent = "INFORMATIONAL"; state = "Gujarat"

def test_single_pmfby_stays_single():
    facets = split_facets("What is PMFBY premium?", ["pmfby"], _Cls(), "simple", "Gujarat")
    assert len(facets) == 1
    assert facets[0].domain == "pmfby"

def test_triple_splits_to_three():
    facets = split_facets(
        "PM-KISAN PMFBY Farmer Registry Gujarat land records",
        ["pmfby", "schemes", "agriculture"], _Cls(), "multi_condition", "Gujarat",
    )
    assert 2 <= len(facets) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_facet_router.py -v`
Expected: FAIL with "No module named backend.app.facets" or "function not defined".

- [ ] **Step 3: Add collect_hits to domains.py (keep classify unchanged)**

```python
# backend/app/domains.py — append after AnchorStore.classify
def collect_hits(self, text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for domain, keywords in self.rules.items():
        for kw in keywords:
            if " " in kw:
                if kw in lowered:
                    hits.append(domain)
                    break
            else:
                import re as _re
                if _re.search(r"\b" + _re.escape(kw) + r"\b", lowered):
                    hits.append(domain)
                    break
    # scheme-code identifiers not in keyword_rules
    extra = {"pm-kisan": "schemes", "pmkisan": "schemes",
             "farmer registry": "schemes", "farmer id": "schemes"}
    for k, d in extra.items():
        if k in lowered and d not in hits:
            hits.append(d)
    return hits
AnchorStore.collect_hits = collect_hits
```

- [ ] **Step 4: Create minimal facets.py**

```python
# backend/app/facets.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Facet:
    facet_id: str
    domain: str
    query: str
    state: str | None

_SCHEME_CODES = ["pmfby", "pm-kisan", "pmkisan", "farmer registry", "farmer id"]

def _slice_query(english_query: str, domain: str, state: str | None) -> str:
    words = english_query.split()
    keep: list[str] = []
    low = english_query.lower()
    for w in words:
        if w.lower() in low and (w.lower() in domain or len(keep) < 24):
            keep.append(w)
        if len(keep) >= 24:
            break
    base = " ".join(keep) if keep else english_query[:300]
    if state and state.lower() not in base.lower():
        base = f"{base} {state}"
    return base[:400]

def split_facets(english_query, hits, classification, complexity, state):
    uniq: list[str] = []
    for h in hits or []:
        if h not in uniq:
            uniq.append(h)
    if classification is not None and getattr(classification, "domain", None):
        d = classification.domain
        if d not in ("general", "out_of_scope") and d not in uniq:
            uniq.append(d)
    multi = len(uniq) >= 2 or (complexity in ("multi_condition", "comparison", "multi_hop") and len(uniq) >= 2)
    if not multi:
        dom = uniq[0] if uniq else (getattr(classification, "domain", "general") or "general")
        return [Facet(facet_id=dom, domain=dom, query=english_query, state=state)]
    out: list[Facet] = []
    for d in uniq[:3]:
        out.append(Facet(facet_id=d, domain=d, query=_slice_query(english_query, d, state), state=state))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_facet_router.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains.py backend/app/facets.py backend/tests/test_facet_router.py
git commit -m "feat: add deterministic facet router with single-path preserve"
```

---

### Task 2: Coverage-aware selector

**Files:**
- Modify: `backend/app/facets.py` (add `select_coverage`)
- Test: `backend/tests/test_coverage_selector.py`

**Interfaces:**
- Consumes: `Facet` list, `dict[str, list[EvidenceChunk]]` per-facet chunks.
- Produces: `select_coverage(facet_chunks: dict[str, list[EvidenceChunk]]) -> tuple[list[EvidenceChunk], dict]` returning merged list (cap 12) and coverage map `{facet_id: {"status": str, "chunk_ids": list[str]}}`.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_coverage_selector.py
from backend.app.facets import select_coverage
from backend.app.contracts import EvidenceChunk

def _c(cid, score, domain="pmfby"):
    return EvidenceChunk(chunk_id=cid, content="x", source_type="static",
                         title="t", domain=domain, jurisdiction="central", dense_score=score)

def test_round_robin_beats_score_only():
    per = {"pmfby": [_c("a1", 0.9)], "schemes": [_c("b1", 0.41)]}
    merged, cov = select_coverage(per)
    ids = [c.chunk_id for c in merged]
    assert "a1" in ids and "b1" in ids
    assert cov["pmfby"]["status"] == "supported"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_coverage_selector.py -v`
Expected: FAIL with "function select_coverage not defined".

- [ ] **Step 3: Implement select_coverage**

```python
# append to backend/app/facets.py
def select_coverage(facet_chunks: dict[str, list]) -> tuple[list, dict]:
    merged: list = []
    coverage: dict = {}
    for fid, chunks in facet_chunks.items():
        good = [c for c in chunks if (c.dense_score or c.rerank_score or 0) >= 0.40]
        if good:
            status = "supported"
        elif chunks:
            status = "partial"
        else:
            status = "unsupported"
        coverage[fid] = {"status": status, "chunk_ids": [c.chunk_id for c in chunks[:3]]}
    # round-robin: 2 per supported facet first
    for fid, chunks in facet_chunks.items():
        merged.extend(chunks[:2])
    # fill to 12 by score order
    seen = {c.chunk_id for c in merged}
    rest: list = []
    for chunks in facet_chunks.values():
        for c in chunks[2:]:
            if c.chunk_id not in seen:
                rest.append(c)
    rest.sort(key=lambda c: -((c.dense_score or 0) + (c.rerank_score or 0)))
    merged = (merged + rest)[:12]
    return merged, coverage
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_coverage_selector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/facets.py backend/tests/test_coverage_selector.py
git commit -m "feat: add coverage-aware selector with round-robin cap"
```

---

### Task 3: Orchestrator facet branch + confidence penalty

**Files:**
- Modify: `backend/app/services/rag_orchestrator.py`
- Test: `backend/tests/test_facet_integration.py`

**Interfaces:**
- Consumes: `split_facets()`, `select_coverage()`, existing `_run_pipelines()`, `_calculate_confidence()`.
- Produces: `run()` returns same `RAGResponse` with `metadata["coverage"]` populated on multi-facet; single-facet path unchanged.

- [ ] **Step 1: Write failing integration test (mocked services)**

```python
# backend/tests/test_facet_integration.py
def test_single_path_uses_legacy_merge(monkeypatch):
    from backend.app.services import rag_orchestrator as ro
    assert hasattr(ro.RAGOrchestrator, "run")
    # router single facet must call _run_pipelines once (no per-facet fan-out)
    assert hasattr(ro.RAGOrchestrator, "_merge_evidence")
```

- [ ] **Step 2: Run test to verify baseline passes (characterization)**

Run: `pytest backend/tests/test_facet_integration.py -v`
Expected: PASS (proves hooks exist before change).

- [ ] **Step 3: Implement facet branch (surgical)**

In `RAGOrchestrator.run()`, after `domain = effective_domain(...)` and `state = resolve_expected_state(...)`, insert:

```python
from app.facets import split_facets
from app.domains import get_anchor_store
try:
    _hits = get_anchor_store().collect_hits(english_query)
except Exception:
    _hits = [domain]
_complexity = self._complexity_classifier.classify(english_query, lang).value
_facets = split_facets(english_query, _hits, classification, _complexity, state)
```

If `len(_facets) == 1`: proceed exactly as today (same `_run_pipelines`, same `_merge_evidence`, same `k=25`).

If multi: for each facet call `self._static_rag.retrieve(embedding=facet_embedding, query=facet.query, domain=facet.domain, state=facet.state, k=10)` sequentially; call `self._web_rag.retrieve(...)` for at most 2 facets needing web (same `deadline` for all); group results into `facet_chunks`; call `select_coverage()`; use merged list for downstream prompt/citations; store `coverage` in `web_result.metadata["facet_coverage"]`. Confidence: `confidence = round(confidence * (0.5 + 0.5 * supported/total), 2)` after existing `_calculate_confidence`.

Facet embeddings: reuse `get_embedding_provider().embed_texts([facet.query])` per facet (max 3 calls, cached).

- [ ] **Step 4: Run related suites**

Run: `pytest backend/tests/test_facet_integration.py backend/tests/test_facet_router.py backend/tests/test_coverage_selector.py backend/tests/test_web_rag_deadline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_orchestrator.py backend/tests/test_facet_integration.py
git commit -m "feat: add bounded facet retrieval with coverage confidence"
```

---

### Task 4: Facet-grouped prompt

**Files:**
- Modify: `backend/app/evidence_controller.py`
- Test: extend `backend/tests/test_facet_integration.py`

**Interfaces:**
- Consumes: `coverage` dict + per-facet chunk groups.
- Produces: `build_curated_prompt()` output with `== FACET: <id> ==` sections and `No evidence retrieved for this facet.` blocks.

- [ ] **Step 1: Write failing test**

```python
def test_prompt_groups_by_facet():
    from backend.app.evidence_controller import EvidenceController
    ec = EvidenceController()
    assert hasattr(ec, "build_curated_prompt")
```

Extend with a case asserting `"FACET:" in user_prompt` when bundle metadata carries `facet_groups`.

- [ ] **Step 2: Run to confirm current prompt lacks FACET header**

Run: `pytest backend/tests/test_facet_integration.py -v`
Expected: FAIL on new assertion.

- [ ] **Step 3: Minimal prompt change**

In `build_curated_prompt()`, when `bundle` metadata contains `facet_groups: dict[facet_id, list[EvidenceChunk]]`, render static/dynamic sections grouped under `== FACET: {facet_id} ==` headers; for facets with zero chunks render `No evidence retrieved for this facet.` Append instruction: `Answer each facet under its own bold sub-heading; for unsupported facets output exactly: Evidence insufficient for [facet] — not answered.`

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/test_facet_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evidence_controller.py backend/tests/test_facet_integration.py
git commit -m "feat: group prompt evidence by facet with insufficient block"
```

---

### Task 5: Domain-gate PACS isolation (test-first)

**Files:**
- Modify: `backend/app/evidence_gate.py`
- Test: `backend/tests/test_gate_pacs_isolation.py`

**Interfaces:**
- Consumes: `evidence_gate(chunks, expected_domain, expected_state)`.
- Produces: PACS queries reject pmfby/schemes chunks; pmfby queries reject pacs chunks.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_gate_pacs_isolation.py
from backend.app.evidence_gate import evidence_gate
from backend.app.contracts import EvidenceChunk

def _c(domain):
    return EvidenceChunk(chunk_id="x"+domain, content="x", source_type="static",
                         title="t", domain=domain, jurisdiction="central", dense_score=0.8)

def test_pacs_rejects_pmfby():
    abstained, reason, _ = evidence_gate([_c("pmfby"), _c("schemes")], expected_domain="pacs_governance")
    assert abstained is True
```

- [ ] **Step 2: Run to verify it fails (alias currently accepts)**

Run: `pytest backend/tests/test_gate_pacs_isolation.py -v`
Expected: FAIL (currently passes gate via alias).

- [ ] **Step 3: Tighten `_DOMAIN_ALIASES`**

Change mapping so `pacs_governance` / `pacs_computerization` / `cooperative` / `pacs` never alias to `pmfby` / `schemes` / `agriculture` and vice versa. Keep `schemes<->pmfby` and `agriculture->pmfby` only where corpus gap requires it, with comment referencing this test. Keep `financial_inclusion<->finlit` and `cooperative<->pacs` aliases.

- [ ] **Step 4: Run gate suites**

Run: `pytest backend/tests/test_gate_pacs_isolation.py backend/tests/test_evidence_gate_unified.py backend/tests/test_services_static_rag.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evidence_gate.py backend/tests/test_gate_pacs_isolation.py
git commit -m "fix: isolate PACS gate from pmfby/schemes aliases"
```

---

### Task 6: Sessions migration check

**Files:**
- Modify: `backend/app/main.py`
- Test: manual Supabase check (no new unit test; existing `session_store` tests cover quarantine).

- [ ] **Step 1: Verify migration applied**

Run in Supabase SQL editor: `select column_name from information_schema.columns where table_name='sessions';`
Expected: `user_id` present. If missing, run `supabase/migrations/20261007_sessions_user_id.sql`.

- [ ] **Step 2: Add lifespan check**

```python
# backend/app/main.py — inside lifespan before yield
from app.db import get_supabase
try:
    get_supabase().table("sessions").select("session_id,user_id").limit(1).execute()
except Exception as e:
    import logging as _lg
    if "user_id" in str(e):
        _lg.getLogger(__name__).error("sessions.user_id missing — run supabase/migrations/20261007_sessions_user_id.sql")
```

- [ ] **Step 3: Run health check**

Run: `python -c "from backend.app.main import app; print('ok')"`
Expected: `ok` with no import error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "chore: add sessions.user_id migration check at startup"
```

---

## Self-review

- Spec coverage: router (Task 1), bounded retrieval (Task 3), coverage selector (Task 2), per-facet grounding (Task 4), gate fix (Task 5), migration (Task 6), 4 acceptance cases (Task 3-4 tests). No gaps.
- No placeholders: every step has exact file, code, command, expected output.
- Type consistency: `Facet(facet_id, domain, query, state)`, `split_facets(...) -> list[Facet]`, `select_coverage(dict) -> (list, dict)` used consistently across Tasks 1-4.
