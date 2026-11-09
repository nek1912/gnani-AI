# Workflow: Failure Injection Loop

**Purpose:** Deliberately break every external dependency to verify that the system fails safely, deterministically, and without data loss.

**Status:** PARTIALLY IMPLEMENTED as pytest suites (see note)

> **Current state (code-grounded):** there is no `tests/failure_injection/` directory and no mock provider server. The scenarios below are instead covered by `backend/tests/test_llm_failure_injection.py` (fallback/abstain), `test_llm_fallback.py`, `test_embedding_retry.py`, and `test_contract.py` (422 validation). Supabase/filesystem fault scenarios have no dedicated tests. Treat the body below as the design record plus the pytest mapping above.

---

## Trigger

**Event:** Pre-release gate OR after any provider integration change

**Schedule:** None — event-driven only. Runs before releases, not continuously.

**Entry point:** `pytest tests/failure_injection/ -v` from project root

---

## Inputs

| Input | Source | Required | Validation |
|-------|--------|----------|------------|
| Running backend | FastAPI server on localhost | Yes | `/health` endpoint must respond |
| Mock provider server | Local mock for Jina/Groq/Gemini | Yes | Must be able to inject faults |
| Supabase credentials | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` env vars | Yes | Must be non-empty |
| Test corpus | Ingested documents in Supabase | Yes | At least 1 document per domain |

---

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Failure injection report | stdout + `eval/failure_injection_report.json` | JSON with per-scenario results |
| Safe failure cases | `eval/safe_failures.json` | JSON with scenarios that failed safely |
| Unsafe failure cases | `eval/unsafe_failures.json` | JSON with scenarios that failed unsafely (BLOCKING) |

---

## Injection Scenarios

### Embedding Provider Failures

| Scenario | Injection | Expected Behavior | Blocking If Unsafe |
|----------|-----------|-------------------|-------------------|
| Jina timeout | Mock Jina to hang >30s | Retry 3x, then abstain | Yes |
| Jina 429 | Mock Jina to return 429 | Retry with backoff, then abstain | Yes |
| Jina 500 | Mock Jina to return 500 | Retry 3x, then abstain | Yes |
| Jina malformed response | Mock Jina to return invalid JSON | Reject, abstain | Yes |
| Jina wrong dimension | Mock Jina to return 512-dim vector | Reject before DB insertion | Yes |
| Jina null embedding | Mock Jina to return null | Reject before DB insertion | Yes |

### LLM Provider Failures

| Scenario | Injection | Expected Behavior | Blocking If Unsafe |
|----------|-----------|-------------------|-------------------|
| Groq timeout | Mock Groq to hang >30s | Fallback to Gemini | Yes |
| Groq 429 | Mock Groq to return 429 | Fallback to Gemini | Yes |
| Groq 5xx | Mock Groq to return 500 | Fallback to Gemini | Yes |
| Both providers fail | Mock both to fail | Abstain with error message | Yes |
| Groq malformed output | Mock Groq to return invalid JSON | Fallback to Gemini | Yes |
| Groq empty output | Mock Groq to return empty string | Fallback to Gemini | Yes |
| Groq hallucinated citations | Mock Groq to return fake chunk IDs | Abstain (citation verification catches) | Yes |

### Supabase Failures

| Scenario | Injection | Expected Behavior | Blocking If Unsafe |
|----------|-----------|-------------------|-------------------|
| Connection failure | Block Supabase connections | Abstain, no crash | Yes |
| Timeout | Mock Supabase to hang | Abstain with timeout error | Yes |
| RPC failure | Mock `match_chunks` to fail | Abstain, log error | Yes |
| Transaction failure | Mock insert to fail mid-batch | Old data preserved | Yes |

### Filesystem Failures

| Scenario | Injection | Expected Behavior | Blocking If Unsafe |
|----------|-----------|-------------------|-------------------|
| Missing file | Delete a seed file | Ingestion skips source, preserves others | Yes |
| Permission error | Make file read-only | Ingestion skips source | Yes |
| Corrupt PDF | Write garbage to PDF file | Extraction fails, source skipped | Yes |

### API Input Failures

| Scenario | Injection | Expected Behavior | Blocking If Unsafe |
|----------|-----------|-------------------|-------------------|
| Empty query | POST /chat with empty string | 422 validation error | Yes |
| Whitespace query | POST /chat with "   " | 422 validation error | Yes |
| Very long query | POST /chat with 10000 chars | 422 validation error | Yes |
| Malformed JSON | POST invalid JSON | 422 validation error | Yes |
| Missing language | POST without language field | 422 validation error | Yes |
| Invalid language | POST with language="xyz" | 422 validation error | Yes |
| Prompt injection | Query with "Ignore instructions..." | Normal response, no instruction following | Yes |

---

## Invariants

1. **No stack traces in responses.** Every failure returns a structured error, not a Python traceback.

2. **No secret leakage.** Error messages must not contain API keys, database credentials, or internal paths.

3. **No data corruption.** A failed operation must not leave partial data in the database.

4. **No silent failures.** Every failure must be logged with enough context to diagnose.

5. **Graceful degradation.** If one provider fails, the system should try alternatives before giving up.

6. **Deterministic behavior.** Given the same injection, the system should fail the same way every time.

---

## Failure Behavior

| Failure Point | Behavior | Recovery |
|---------------|----------|----------|
| Mock server won't start | Abort test suite. Cannot inject faults without mock. | Fix mock server, re-run |
| Injection doesn't trigger | Test fails — injection was supposed to happen | Fix injection mechanism, re-run |
| System crashes instead of failing safely | **BLOCKING FAILURE.** Report crash scenario. | Fix error handling, re-run |
| Secret appears in error message | **BLOCKING FAILURE.** Report leaked secret. | Fix error message, re-run |
| Data corruption detected | **BLOCKING FAILURE.** Report corrupted records. | Fix transaction handling, re-run |

---

## Checkpoint

**None.** This workflow runs autonomously. Failures produce reports, not human prompts.

If blocking failure triggered, exit non-zero and log the specific unsafe scenarios.

---

## Brief (Post-Run Summary)

```
FAILURE INJECTION COMPLETE
  Scenarios tested: N
  Safe failures: N
  Unsafe failures: N (target: 0)
  Duration: Ns
  Verdict: PASS / FAIL
  
  Unsafe scenarios: [list with details]
  Recommendations: [list]
```

---

## CI Integration

**Trigger:** Pre-release gate OR after provider integration changes.

**Steps:**
1. Start mock provider server
2. Run failure injection tests
3. Check for unsafe failures — if any, CI fails
4. Stop mock provider server

**Exit codes:**
- 0: All failures are safe
- 1: One or more unsafe failures detected
- 2: Mock server couldn't start

---

## Acceptance Criteria

- [ ] All embedding provider failures result in abstention, not crash
- [ ] All LLM provider failures trigger fallback or abstention
- [ ] All Supabase failures result in abstention, not crash
- [ ] All filesystem failures are isolated to the affected source
- [ ] All API input failures return 422, not 500
- [ ] No stack traces appear in any response
- [ ] No secrets appear in any error message
- [ ] No data corruption from any failure scenario
