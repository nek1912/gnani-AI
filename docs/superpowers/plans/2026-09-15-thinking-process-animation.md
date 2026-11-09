# Thinking Process Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simple `ThinkingBubble` with a detailed step-by-step thinking process indicator that shows real pipeline reasoning, auto-collapses on answer, and re-expands via dropdown icon.

**Architecture:** Backend emits new structured `step` SSE events via an `on_step` callback in `RAGOrchestrator.run()`. Frontend renders a `ThinkingProcess` component that accumulates steps, auto-collapses when tokens arrive, and shows a dropdown chevron to re-expand.

**Tech Stack:** Python FastAPI (SSE), Next.js 16 + React 19, Tailwind CSS 4, Vitest + Testing Library, pytest + pytest-asyncio

## Global Constraints

- Python ≥3.11, type hints everywhere, Pydantic models for request/response
- No bare `except`, structured logs, never log API keys
- Existing `thinking` SSE events remain (backward compatible)
- `on_step` defaults to `None` — non-breaking change
- 6 languages: EN, HI, GU, MR, BN, TA
- No GSAP — CSS transitions only for step animations
- No new external dependencies

---

## File Map

| File | Change | Task |
|---|---|---|
| `backend/app/services/rag_orchestrator.py` | Add `on_step` callback param + emit calls | Task 1 |
| `backend/app/routes/chat.py` | Add `_STEP_LABELS`, `make_step_emitter()`, wire callback | Task 2 |
| `backend/tests/test_services_rag_orchestrator.py` | Add tests for `on_step` callback | Task 3 |
| `backend/tests/test_chat_route_refactored.py` | Add tests for `step` SSE events in stream | Task 4 |
| `frontend/src/lib/api.ts` | Add `StepEvent` interface, `"step"` to `StreamEvent` | Task 5 |
| `frontend/src/components/ui/Icons.tsx` | Add `IconChevronDown` | Task 6 |
| `frontend/src/components/chat/ThinkingProcess.tsx` | New component | Task 7 |
| `frontend/src/components/ChatWindow.tsx` | Add state, handle `step` event, render `ThinkingProcess` | Task 8 |
| `frontend/src/components/FloatingChatWidget.tsx` | Same as ChatWindow | Task 9 |
| `frontend/src/components/chat/__tests__/ThinkingProcess.test.tsx` | Component tests | Task 10 |
| `frontend/src/components/__tests__/ChatWindow.test.tsx` | Update existing tests | Task 11 |

---

### Task 1: Add `on_step` callback to RAGOrchestrator

**Files:**
- Modify: `backend/app/services/rag_orchestrator.py:85-267`
- Test: `backend/tests/test_services_rag_orchestrator.py`

**Interfaces:**
- Consumes: existing `run()` method signature
- Produces: `on_step` callback parameter `(dict) -> None` with keys `id`, `detail`, `status`

- [ ] **Step 1: Add `on_step` parameter to `run()`**

In `rag_orchestrator.py`, add `on_step: Callable[[dict], None] | None = None` parameter after `model_override`:

```python
from typing import Any, Callable

async def run(
    self,
    query: str,
    english_query: str,
    embedding: list[float],
    domain: str,
    state: str | None,
    classification: QueryClassification | None,
    history: list[dict] | None,
    lang: str,
    session_id: str,
    language_mix: dict[str, float] | None = None,
    model_override: str | None = None,
    on_step: Callable[[dict], None] | None = None,
) -> RAGResponse:
```

- [ ] **Step 2: Emit step events at each pipeline stage**

Add emits inside `run()` at the following locations:

After line 137 (after `self._run_pipelines` returns, before the abstention check):
```python
if on_step:
    static_count = len(static_result.chunks) if not static_result.abstained else 0
    web_count = len(web_result.chunks) if not web_result.abstained else 0
    if static_count > 0:
        on_step({"id": "static_done", "detail": f"Found {static_count} chunks from official documents", "status": "completed"})
    if web_count > 0:
        on_step({"id": "web_done", "detail": f"Found {web_count} results from web sources", "status": "completed"})
```

Before line 158 (before `build_bundle`):
```python
if on_step:
    on_step({"id": "evidence_merge", "detail": "Merging and ranking evidence from both sources", "status": "active"})
```

Before line 195 (before `grounded_answer`):
```python
if on_step:
    on_step({"id": "llm_generate", "detail": "Generating grounded response from retrieved evidence", "status": "active"})
```

After line 231 (after `verify_citations`):
```python
if on_step:
    verified_count = len([c for c in all_chunks if c.chunk_id in [v for v in all_chunk_ids]])
    on_step({"id": "citation_verify", "detail": f"Verified {len(all_chunks)} citations against source documents", "status": "completed"})
```

- [ ] **Step 3: Write tests for on_step callback**

In `test_services_rag_orchestrator.py`, add a new test class:

```python
class TestOnStepCallback:
    async def test_on_step_called_with_retrieval_events(self):
        orch = RAGOrchestrator(settings)
        steps = []
        with patch.object(orch._static_rag, "retrieve", return_value=static_result), \
             patch.object(orch._web_rag, "retrieve", return_value=web_result), \
             patch.object(orch._evidence_controller, "build_bundle", return_value=bundle), \
             patch.object(orch._evidence_controller, "assess_evidence", return_value=assessment), \
             patch.object(orch._evidence_controller, "build_curated_prompt", return_value=(sys_prompt, user_prompt)), \
             patch("app.services.rag_orchestrator.grounded_answer", return_value="Answer [chunk:abc123]"), \
             patch("app.services.rag_orchestrator.verify_citations", return_value=VerificationResult(is_valid=True, invalid_prefixes=[], reason=None)), \
             patch("app.services.rag_orchestrator.strip_citations", return_value=("Answer", ["chunk:abc123"])):
            await orch.run(
                query="test", english_query="test", embedding=[0.5]*768,
                domain="pmfby", state=None, classification=None,
                history=[], lang="en", session_id="s1",
                on_step=lambda s: steps.append(s),
            )
        step_ids = [s["id"] for s in steps]
        assert "static_done" in step_ids or "web_done" in step_ids
        assert "evidence_merge" in step_ids
        assert "llm_generate" in step_ids
        assert "citation_verify" in step_ids

    async def test_on_step_none_does_not_crash(self):
        orch = RAGOrchestrator(settings)
        with patch.object(orch._static_rag, "retrieve", return_value=static_result), \
             patch.object(orch._web_rag, "retrieve", return_value=web_result), \
             patch.object(orch._evidence_controller, "build_bundle", return_value=bundle), \
             patch.object(orch._evidence_controller, "assess_evidence", return_value=assessment), \
             patch.object(orch._evidence_controller, "build_curated_prompt", return_value=(sys_prompt, user_prompt)), \
             patch("app.services.rag_orchestrator.grounded_answer", return_value="Answer [chunk:abc123]"), \
             patch("app.services.rag_orchestrator.verify_citations", return_value=VerificationResult(is_valid=True, invalid_prefixes=[], reason=None)), \
             patch("app.services.rag_orchestrator.strip_citations", return_value=("Answer", ["chunk:abc123"])):
            resp = await orch.run(
                query="test", english_query="test", embedding=[0.5]*768,
                domain="pmfby", state=None, classification=None,
                history=[], lang="en", session_id="s1",
            )
        assert resp.answer == "Answer"
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest backend/tests/test_services_rag_orchestrator.py -v`
Expected: All tests pass including new `TestOnStepCallback` tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_orchestrator.py backend/tests/test_services_rag_orchestrator.py
git commit -m "feat(backend): add on_step callback to RAGOrchestrator for step events"
```

---

### Task 2: Wire step events in chat.py SSE stream

**Files:**
- Modify: `backend/app/routes/chat.py:1030-1265`
- Test: `backend/tests/test_chat_route_refactored.py`

**Interfaces:**
- Consumes: `on_step` callback from Task 1
- Produces: `_STEP_LABELS` dict, `make_step_emitter()` function, SSE `step` events on wire

- [ ] **Step 1: Add `_STEP_LABELS` dict and `make_step_emitter()`**

After line 1037 (after `_THINKING_MESSAGES`), add:

```python
_STEP_LABELS = {
    "en": {
        "retrieval_start": "Searching sources",
        "static_done": "Document search complete",
        "web_done": "Web search complete",
        "evidence_merge": "Merging evidence",
        "llm_generate": "Generating response",
        "citation_verify": "Verifying citations",
    },
    "hi": {
        "retrieval_start": "स्रोत खोज रहे हैं",
        "static_done": "दस्तावेज़ खोज पूर्ण",
        "web_done": "वेब खोज पूर्ण",
        "evidence_merge": "साक्ष्य मर्ज कर रहे हैं",
        "llm_generate": "उत्तर तैयार कर रहे हैं",
        "citation_verify": "उद्धरण सत्यापित कर रहे हैं",
    },
    "gu": {
        "retrieval_start": "સ્ત્રોતો શોધી રહ્યા છીએ",
        "static_done": "દસ્તાવેજ શોધ પૂર્ણ",
        "web_done": "વેબ શોધ પૂર્ણ",
        "evidence_merge": "પુરાવા મર્જ કરી રહ્યા છીએ",
        "llm_generate": "જવાબ તૈયાર કરી રહ્યા છીએ",
        "citation_verify": "સંदર્ભો ચકાસી રહ્યા છીએ",
    },
    "mr": {
        "retrieval_start": "स्रोत शोधत आहोत",
        "static_done": "दस्तावेज शोध पूर्ण",
        "web_done": "वेब शोध पूर्ण",
        "evidence_merge": "पुरावे मर्ज करत आहोत",
        "llm_generate": "उत्तर तयार करत आहोत",
        "citation_verify": "संदर्भ तपासत आहोत",
    },
    "bn": {
        "retrieval_start": "উৎস খুঁজছি",
        "static_done": "নথি অনুসন্ধান সম্পূর্ণ",
        "web_done": "ওয়েব অনুসন্ধান সম্পূর্ণ",
        "evidence_merge": "প্রমাণ মার্জ করছি",
        "llm_generate": "উত্তর তৈরি করছি",
        "citation_verify": "উদ্ধৃতি যাচাই করছি",
    },
    "ta": {
        "retrieval_start": "ஆதாரங்களை தேடுகிறோம்",
        "static_done": "ஆவண தேடல் நிறைவடைந்தது",
        "web_done": "வலை தேடல் நிறைவடைந்தது",
        "evidence_merge": "சான்றுகளை இணைக்கிறோம்",
        "llm_generate": "பதிலை உருவாக்குகிறோம்",
        "citation_verify": "மேற்கோள்களை சரிபார்க்கிறோம்",
    },
}


def _make_step_emitter(lang: str):
    """Return a function that yields SSE step events for use in generate()."""
    labels = _STEP_LABELS.get(lang, _STEP_LABELS["en"])
    _collected: list[str] = []

    def _collect(step_data: dict) -> None:
        _collected.append(step_data.get("id", ""))

    def _get_collected() -> list[str]:
        return list(_collected)

    return _collect, _get_collected
```

- [ ] **Step 2: Wire callback into orchestrator.run() in chat_stream**

In the `generate()` function, around line 1224 (before `orchestrator.run()`), create the emitter and pass it:

```python
# Before orchestrator.run()
step_collector, get_collected_steps = _make_step_emitter(ctx.lang)
yield _sse_event("step", {"id": "retrieval_start", "label": _STEP_LABELS.get(ctx.lang, _STEP_LABELS["en"])["retrieval_start"], "detail": "Querying document store and web sources", "status": "active"})

rag_response = await orchestrator.run(
    query=req.question,
    english_query=ctx.english_query,
    embedding=ctx.embedding,
    domain=ctx.domain,
    state=ctx.resolved_state,
    classification=ctx.classification,
    history=ctx.history,
    lang=ctx.lang,
    session_id=req.session_id,
    language_mix=ctx.language_mix,
    on_step=step_collector,
)
```

Then, after `orchestrator.run()` returns (around line 1239), emit the collected steps as SSE events:

```python
# Emit completed steps from orchestrator
labels = _STEP_LABELS.get(ctx.lang, _STEP_LABELS["en"])
for step_id in get_collected_steps():
    if step_id in labels:
        yield _sse_event("step", {"id": step_id, "label": labels[step_id], "detail": "", "status": "completed"})
```

- [ ] **Step 3: Write tests for step SSE events**

In `test_chat_route_refactored.py`, add to `TestChatStreamEndpoint`:

```python
def test_stream_emits_step_events(self, mock_detect, mock_resolve, ...):
    mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response())
    resp = client.post("/chat/stream", json={...})
    text = resp.text
    assert "event: step" in text
    assert "retrieval_start" in text
    assert "evidence_merge" in text or "llm_generate" in text
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest backend/tests/test_chat_route_refactored.py::TestChatStreamEndpoint -v`
Expected: All stream tests pass including new step event test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/chat.py backend/tests/test_chat_route_refactored.py
git commit -m "feat(backend): emit step SSE events in chat stream with localized labels"
```

---

### Task 3: Add `StepEvent` type and `"step"` to frontend API types

**Files:**
- Modify: `frontend/src/lib/api.ts:233-240`

**Interfaces:**
- Consumes: none
- Produces: `StepEvent` interface, `"step"` in `StreamEvent` union

- [ ] **Step 1: Add StepEvent interface and update StreamEvent**

In `api.ts`, find the `StreamEvent` type (around line 234) and add:

```typescript
export interface StepEvent {
  id: string;
  label: string;
  detail: string;
  status: "active" | "completed" | "pending";
}

export type StreamEvent =
  | { event: "thinking"; data: { text: string } }
  | { event: "step"; data: StepEvent }
  | { event: "token"; data: { text: string } }
  | { event: "metadata"; data: Record<string, unknown> }
  | { event: "done"; data: Record<string, unknown> }
  | { event: "error"; data: { message: string } };
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add StepEvent type and step to StreamEvent union"
```

---

### Task 4: Add `IconChevronDown` to Icons.tsx

**Files:**
- Modify: `frontend/src/components/ui/Icons.tsx:60-66`

**Interfaces:**
- Consumes: `IconProps` type from same file
- Produces: `IconChevronDown` component

- [ ] **Step 1: Add IconChevronDown component**

After `IconChevronRight` (line 66), add:

```typescript
export function IconChevronDown({ className = "w-5 h-5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ui/Icons.tsx
git commit -m "feat(frontend): add IconChevronDown component"
```

---

### Task 5: Create ThinkingProcess component

**Files:**
- Create: `frontend/src/components/chat/ThinkingProcess.tsx`
- Test: `frontend/src/components/chat/__tests__/ThinkingProcess.test.tsx`

**Interfaces:**
- Consumes: `StepEvent` from Task 3, `IconChevronDown` from Task 4
- Produces: `ThinkingProcess` component

- [ ] **Step 1: Create ThinkingProcess.tsx**

```tsx
"use client";

import { useState } from "react";
import { IconChevronDown } from "@/components/ui/Icons";
import type { StepEvent } from "@/lib/api";

interface ThinkingProcessProps {
  steps: StepEvent[];
  lang?: string;
  isStreaming: boolean;
}

const STEP_ORDER = ["retrieval_start", "static_done", "web_done", "evidence_merge", "llm_generate", "citation_verify"];

function Spinner() {
  return (
    <svg className="h-3.5 w-3.5 animate-spin text-[var(--primary)]" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-3.5 w-3.5 text-[var(--success, #22c55e)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function sortSteps(steps: StepEvent[]): StepEvent[] {
  return [...steps].sort((a, b) => {
    const ai = STEP_ORDER.indexOf(a.id);
    const bi = STEP_ORDER.indexOf(b.id);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

export function ThinkingProcess({ steps, isStreaming }: ThinkingProcessProps) {
  const [expanded, setExpanded] = useState(true);
  const sorted = sortSteps(steps);
  const allComplete = sorted.length > 0 && sorted.every((s) => s.status === "completed");
  const completedCount = sorted.filter((s) => s.status === "completed").length;

  if (sorted.length === 0) return null;

  const summaryText = allComplete
    ? `${completedCount} steps complete`
    : sorted.find((s) => s.status === "active")?.label || "Processing...";

  return (
    <div className="flex gap-3">
      <div className="flex flex-col gap-1 min-w-0">
        <div className="rounded-2xl bg-[var(--surface-card)] px-4 py-3">
          {/* Collapsed summary */}
          {isStreaming && !expanded && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="flex items-center gap-2 w-full text-left group"
            >
              <CheckIcon />
              <span className="text-sm font-medium text-[var(--body)] truncate">{summaryText}</span>
              <IconChevronDown className="h-3.5 w-3.5 text-[var(--muted-soft)] transition-transform duration-200 group-hover:text-[var(--body)]" />
            </button>
          )}

          {/* Expanded step list */}
          {(!isStreaming || expanded) && (
            <div className="flex flex-col gap-1.5">
              {sorted.map((step) => (
                <div key={step.id} className="flex items-start gap-2 animate-in fade-in slide-in-from-top-1 duration-300">
                  <span className="mt-0.5 shrink-0">
                    {step.status === "active" && <Spinner />}
                    {step.status === "completed" && <CheckIcon />}
                    {step.status === "pending" && (
                      <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--muted-soft)] opacity-40" />
                    )}
                  </span>
                  <div className="flex flex-col min-w-0">
                    <span className="text-sm font-medium text-[var(--body)]">{step.label}</span>
                    {step.detail && (
                      <span className="text-xs text-[var(--muted-soft)] truncate">{step.detail}</span>
                    )}
                  </div>
                </div>
              ))}

              {/* Collapse button when streaming */}
              {isStreaming && (
                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  className="flex items-center gap-1 mt-1 text-xs text-[var(--muted-soft)] hover:text-[var(--body)] transition-colors self-start"
                >
                  <IconChevronDown className="h-3 w-3 rotate-180" />
                  <span>Collapse</span>
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write ThinkingProcess tests**

Create `frontend/src/components/chat/__tests__/ThinkingProcess.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThinkingProcess } from "../ThinkingProcess";
import type { StepEvent } from "@/lib/api";

const makeSteps = (overrides: Partial<StepEvent>[] = []): StepEvent[] => [
  { id: "retrieval_start", label: "Searching sources", detail: "Querying document store", status: "completed", ...overrides[0] },
  { id: "static_done", label: "Document search complete", detail: "Found 12 chunks", status: "completed", ...overrides[1] },
  { id: "llm_generate", label: "Generating response", detail: "Generating grounded response", status: "active", ...overrides[2] },
];

describe("ThinkingProcess", () => {
  it("renders nothing when steps are empty", () => {
    const { container } = render(<ThinkingProcess steps={[]} isStreaming={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders all steps when not streaming", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    expect(screen.getByText("Searching sources")).toBeTruthy();
    expect(screen.getByText("Document search complete")).toBeTruthy();
    expect(screen.getByText("Generating response")).toBeTruthy();
  });

  it("shows spinner for active step", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    const spinners = document.querySelectorAll("svg.animate-spin");
    expect(spinners.length).toBe(1);
  });

  it("shows checkmark for completed steps", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    const checks = document.querySelectorAll("svg.text-\\[var\\(--success\\,\\#22c55e\\)\\]");
    expect(checks.length).toBe(2);
  });

  it("auto-collapses to summary when streaming starts", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={true} />);
    expect(screen.getByText("2 steps complete")).toBeTruthy();
    expect(screen.queryByText("Searching sources")).toBeNull();
  });

  it("expands on dropdown click", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={true} />);
    fireEvent.click(screen.getByText("2 steps complete"));
    expect(screen.getByText("Searching sources")).toBeTruthy();
  });

  it("shows detail text when expanded", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    expect(screen.getByText("Querying document store")).toBeTruthy();
    expect(screen.getByText("Found 12 chunks")).toBeTruthy();
  });

  it("sorts steps in pipeline order", () => {
    const unsorted: StepEvent[] = [
      { id: "llm_generate", label: "Generating", detail: "", status: "completed" },
      { id: "retrieval_start", label: "Searching", detail: "", status: "completed" },
    ];
    render(<ThinkingProcess steps={unsorted} isStreaming={false} />);
    const items = screen.getAllByText(/(Searching|Generating)/);
    expect(items[0].textContent).toBe("Searching");
    expect(items[1].textContent).toBe("Generating");
  });
});
```

- [ ] **Step 3: Run tests to verify**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/ThinkingProcess.test.tsx`
Expected: All 8 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chat/ThinkingProcess.tsx frontend/src/components/chat/__tests__/ThinkingProcess.test.tsx
git commit -m "feat(frontend): add ThinkingProcess component with step list and auto-collapse"
```

---

### Task 6: Wire ThinkingProcess into ChatWindow

**Files:**
- Modify: `frontend/src/components/ChatWindow.tsx:11,370-431,949-952`

**Interfaces:**
- Consumes: `ThinkingProcess` from Task 5, `StepEvent` from Task 3
- Produces: updated ChatWindow with step state management

- [ ] **Step 1: Update import**

Replace line 11:
```typescript
import { ThinkingBubble } from "./chat/ThinkingBubble";
```
With:
```typescript
import { ThinkingProcess } from "./chat/ThinkingProcess";
import type { StepEvent } from "@/lib/api";
```

- [ ] **Step 2: Add state variables**

Find the existing state declarations (around line 180-200) and add after `thinkingText`:

```typescript
const [thinkingSteps, setThinkingSteps] = useState<StepEvent[]>([]);
const [thinkingExpanded, setThinkingExpanded] = useState(true);
```

- [ ] **Step 3: Handle `step` SSE event**

In the `ask()` function's event handler (around line 377), add a new branch before the `thinking` check:

```typescript
if (event.event === "step") {
  const step = event.data as StepEvent;
  setThinkingSteps((prev) => {
    const idx = prev.findIndex((s) => s.id === step.id);
    if (idx >= 0) {
      const next = [...prev];
      next[idx] = step;
      return next;
    }
    return [...prev, step];
  });
} else if (event.event === "thinking") {
  setThinkingText(event.data.text as string);
} else if (event.event === "token") {
  setThinkingText("");
  setThinkingExpanded(false); // auto-collapse
  // ... existing token logic
```

- [ ] **Step 4: Reset state on stream end**

In the `finally` block (around line 423), add:

```typescript
setThinkingSteps([]);
setThinkingExpanded(true);
```

- [ ] **Step 5: Render ThinkingProcess instead of ThinkingBubble**

Replace lines 950-952:
```tsx
{isStreaming && thinkingText && !streamingAnswer && (
  <ThinkingBubble thinkingText={thinkingText} lang={lang} />
)}
```
With:
```tsx
{isStreaming && thinkingSteps.length > 0 && !streamingAnswer && (
  <ThinkingProcess
    steps={thinkingSteps}
    lang={lang}
    isStreaming={!!streamingAnswer}
  />
)}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ChatWindow.tsx
git commit -m "feat(frontend): wire ThinkingProcess into ChatWindow with step SSE handling"
```

---

### Task 7: Wire ThinkingProcess into FloatingChatWidget

**Files:**
- Modify: `frontend/src/components/FloatingChatWidget.tsx`

**Interfaces:**
- Consumes: `ThinkingProcess` from Task 5, `StepEvent` from Task 3
- Produces: updated FloatingChatWidget with step state

- [ ] **Step 1: Update imports**

Add at top:
```typescript
import { ThinkingProcess } from "./chat/ThinkingProcess";
import type { StepEvent } from "@/lib/api";
```

- [ ] **Step 2: Add state variables**

After existing state declarations, add:
```typescript
const [thinkingSteps, setThinkingSteps] = useState<StepEvent[]>([]);
```

- [ ] **Step 3: Handle `step` SSE event**

In the `ask()` event handler (around line 95), add before the `token` check:
```typescript
if (event.event === "step") {
  const step = event.data as StepEvent;
  setThinkingSteps((prev) => {
    const idx = prev.findIndex((s) => s.id === step.id);
    if (idx >= 0) {
      const next = [...prev];
      next[idx] = step;
      return next;
    }
    return [...prev, step];
  });
} else if (event.event === "token") {
```

- [ ] **Step 4: Reset state in finally block**

After `setTyping(false)` in finally, add:
```typescript
setThinkingSteps([]);
```

- [ ] **Step 5: Render ThinkingProcess**

In the rendering section, where the typing indicator is shown (around line 160), add ThinkingProcess above the answer bubble:

```tsx
{typing && thinkingSteps.length > 0 && (
  <ThinkingProcess steps={thinkingSteps} lang={lang} isStreaming={false} />
)}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/FloatingChatWidget.tsx
git commit -m "feat(frontend): wire ThinkingProcess into FloatingChatWidget"
```

---

### Task 8: Update existing ChatWindow tests

**Files:**
- Modify: `frontend/src/components/__tests__/ChatWindow.test.tsx`

**Interfaces:**
- Consumes: updated ChatWindow from Task 6
- Produces: passing existing tests

- [ ] **Step 1: Add mock for step events in sendChatStream**

In the existing `vi.mock("@/lib/api")` block, update `sendChatStream` to emit a step event:

```typescript
sendChatStream: vi.fn().mockImplementation(async (_payload, onEvent) => {
  onEvent({ event: "step", data: { id: "retrieval_start", label: "Searching", detail: "Querying", status: "active" } });
  onEvent({ event: "step", data: { id: "retrieval_start", label: "Searching", detail: "Querying", status: "completed" } });
  onEvent({ event: "token", data: { text: "ok " } });
  onEvent({ event: "metadata", data: { domain: "unknown", confidence: 0 } });
}),
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd frontend && npx vitest run src/components/__tests__/ChatWindow.test.tsx`
Expected: All existing tests pass (minus pre-existing failures noted in PROJECT_STATUS.md).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/__tests__/ChatWindow.test.tsx
git commit -m "test(frontend): update ChatWindow tests for step event handling"
```

---

### Task 9: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run backend lint**

Run: `cd backend && python -m ruff check app/services/rag_orchestrator.py app/routes/chat.py`
Expected: No lint errors.

- [ ] **Step 2: Run backend tests**

Run: `cd backend && pytest tests/test_services_rag_orchestrator.py tests/test_chat_route_refactored.py -v`
Expected: All tests pass.

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npx next lint`
Expected: No new lint errors.

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All tests pass (minus pre-existing failures).

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address lint and test issues for thinking process feature"
```

---

### Task 10: Update PROJECT_STATUS.md

**Files:**
- Modify: `PROJECT_STATUS.md`

- [ ] **Step 1: Add thinking process feature to component status**

Add a row to the component status table:

```
| Thinking Process UI | `frontend/src/components/chat/ThinkingProcess.tsx` | working | Step-by-step reasoning display with auto-collapse and dropdown re-expand; replaces ThinkingBubble |
```

Update the "Last updated" section with today's date and a brief description.

- [ ] **Step 2: Commit**

```bash
git add PROJECT_STATUS.md
git commit -m "docs: update PROJECT_STATUS.md with thinking process feature"
```
