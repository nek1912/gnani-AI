# Design: Thinking Process Animation

**Date:** 2026-09-15
**Status:** Approved
**Feature:** Real-time thinking process visualization in chat

## Goal

Replace the current simple `ThinkingBubble` (rotating words + dots) with a detailed, step-by-step thinking process indicator that shows what the chatbot is doing internally — similar to ChatGPT/Claude's reasoning dropdown.

## User Experience

### During pipeline (expanded)
```
🔄 Searching sources...
  Querying document store and web...
```
Steps appear one by one as the pipeline progresses. Active step shows a spinner, completed steps show a checkmark.

### On token arrival (auto-collapse)
```
✓ Research complete              [▼]
```
Collapses to a single summary line. Dropdown chevron icon to re-expand.

### Re-expanded
```
✓ Research complete              [▲]
  ├─ ✓ Searching sources — Found 12 chunks from PMFBY guidelines
  ├─ ✓ Web search — Found 3 results from government portals
  ├─ ✓ Merging evidence — Combined 15 chunks from 2 sources
  └─ ✓ Generating response — Verified 5 citations
```

## Architecture

### New SSE event type: `step`

```json
{
  "id": "static_done",
  "label": "Document Search",
  "detail": "Found 12 chunks from PMFBY guidelines (top score: 0.87)",
  "status": "completed"
}
```

- `id`: pipeline stage identifier
- `label`: short human-readable name (localized server-side)
- `detail`: real reasoning text (generated in user's language)
- `status`: `"active"` | `"completed"` | `"pending"`

### Pipeline stages

| Stage | Step ID | When emitted |
|---|---|---|
| Pipeline start | `retrieval_start` | Before `orchestrator.run()` |
| Static RAG done | `static_done` | After `asyncio.gather` returns |
| Web RAG done | `web_done` | After `asyncio.gather` returns |
| Evidence merge | `evidence_merge` | Before `build_bundle()` |
| LLM generate | `llm_generate` | Before `grounded_answer()` |
| Citation verify | `citation_verify` | After `verify_citations()` |

### Backend changes

**`rag_orchestrator.py`:**
- Add optional `on_step: Callable | None = None` parameter to `run()`
- Emit step events at each pipeline stage via callback
- Non-breaking: default `None` preserves existing callers

**`chat.py`:**
- Add `_STEP_LABELS` dict (6 languages × 6 step IDs)
- Create `make_step_emitter(lang)` that yields SSE `step` events
- Pass callback to `orchestrator.run(on_step=emit)`
- Existing `thinking` events remain as fallback

### Frontend changes

**New component: `ThinkingProcess.tsx`**
- Replaces `ThinkingBubble.tsx`
- Renders step list with spinner/checkmark per step
- Auto-collapses on first token event
- Dropdown chevron icon to re-expand
- Localized labels from server

**`ChatWindow.tsx`:**
- New state: `thinkingSteps: StepEvent[]`, `thinkingExpanded: boolean`
- Handle `step` SSE event — append/update steps array
- Auto-collapse: `setThinkingExpanded(false)` on first token
- Render `ThinkingProcess` instead of `ThinkingBubble`

**`FloatingChatWidget.tsx`:**
- Same pattern as ChatWindow

**`lib/api.ts`:**
- Add `"step"` to `StreamEvent` union type
- Add `StepEvent` interface

### Localization

Labels localized server-side in `_STEP_LABELS`:
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
    "hi": { ... },
    "gu": { ... },
    "mr": { ... },
    "bn": { ... },
    "ta": { ... },
}
```

Detail text is generated in user's language via existing translation layer — no additional frontend translation needed.

### Animation

- New steps fade in with slide-down (CSS transitions)
- Completed steps get checkmark with brief scale-pop
- Collapse/expand is instant (no animation)
- No GSAP — lightweight CSS only

## Files to modify

| File | Change |
|---|---|
| `backend/app/services/rag_orchestrator.py` | Add `on_step` callback to `run()` |
| `backend/app/routes/chat.py` | Add `_STEP_LABELS`, `make_step_emitter`, wire callback |
| `frontend/src/lib/api.ts` | Add `StepEvent` type, `"step"` to `StreamEvent` |
| `frontend/src/components/chat/ThinkingProcess.tsx` | New component (replaces `ThinkingBubble`) |
| `frontend/src/components/ChatWindow.tsx` | Add state, handle `step` event, render `ThinkingProcess` |
| `frontend/src/components/FloatingChatWidget.tsx` | Same as ChatWindow |

## Non-goals

- No external state library (stays in local component state)
- No GSAP animations (CSS transitions sufficient)
- No change to existing `thinking` events (backward compatible)
- No new API endpoints
