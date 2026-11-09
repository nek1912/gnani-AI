# RAG Architecture Redesign

**Date:** 2026-09-03
**Status:** Approved
**Scope:** Dual-pipeline RAG cleanup — modular services, unified evidence format, thin chat route

## Problem Statement

The current RAG architecture has grown organically into a 1053-line `chat.py` with:
- Duplicated evidence merging logic (static + web context built twice)
- Inconsistent citation formats (`[chunk:ID]` vs `[static:ID]` vs `[EVIDENCE N]`)
- Two separate evidence gates with different scoring scales (2.5 vs 60.0)
- Web RAG pipeline not matching eGovAssistant's proven 10-step architecture
- Reranker disabled because it degrades recall (0.85 → 0.50)
- Chat route handling classification, retrieval, merging, generation, verification, translation, and session management

## Design Decisions

1. **Dual parallel kept** — both static + web RAG run concurrently, evidence merged with equal priority
2. **Modular services** — `StaticRAGService`, `WebRAGService`, `RAGOrchestrator` replace scattered logic
3. **eGovAssistant-style web pipeline** — 10-step retrieval (discovery → BM25 → Gemini pre-rank → RRF → Gemini final rerank → relevance gate → source verify → evidence threshold → context build → return evidence)
4. **Unified evidence format** — `EvidenceChunk` model used by both pipelines
5. **Single evidence gate** — replaces both `evidence_gate_v2` and `_check_evidence_relevance`
6. **Web RAG returns evidence only** — orchestrator handles answer generation from merged evidence

## Architecture

### Service Layer

```
backend/app/
├── services/
│   ├── __init__.py
│   ├── static_rag.py          # StaticRAGService
│   ├── web_rag.py             # WebRAGService (eGovAssistant-style 10-step)
│   └── rag_orchestrator.py    # RAGOrchestrator (parallel + merge + generate)
├── rag/
│   ├── context_builder.py     # Shared
│   ├── prompt_builder.py      # Shared (add build_merged())
│   └── answer_generator.py    # Shared
├── retrieval/
│   ├── __init__.py            # RetrievedChunk stays for DB rows
│   ├── bm25_retriever.py      # Stays
│   ├── gemini_reranker.py     # Stays (align thresholds)
│   └── rrf.py                 # Stays
├── web_rag/
│   ├── service.py             # WebDiscoveryService stays
│   ├── tavily_client.py       # Stays
│   ├── firecrawl_client.py    # Stays
│   └── ...                    # Other modules stay
├── evidence_gate.py           # Unified evidence gate
├── contracts.py               # Expanded with EvidenceChunk
└── routes/
    └── chat.py                # Thin (~200 lines)
```

### Unified EvidenceChunk

```python
class EvidenceChunk(BaseModel):
    chunk_id: str
    content: str
    source_type: str           # "static" | "web"
    title: str
    url: str | None
    page: int | None
    section: str | None
    domain: str
    jurisdiction: str
    state: str | None
    dense_score: float
    bm25_score: float | None
    rerank_score: float | None
    trust_score: float | None
    metadata: dict

class RAGResult(BaseModel):
    """Return type from both StaticRAGService and WebRAGService."""
    chunks: list[EvidenceChunk]
    abstained: bool
    reason: AbstentionReason | None
    band: ConfidenceBand | None
    domain: str
    metadata: dict = {}       # Pipeline-specific extras (discovery info, etc.)

class RAGResponse(BaseModel):
    """Return type from RAGOrchestrator."""
    answer: str
    language: str
    domain: str
    confidence: float
    confidence_level: str     # "high" | "moderate" | "low" | "none"
    citations: list[dict]
    abstained: bool
    speech_text: str
    speech_segments: list[dict]
    follow_up_question: str | None
    mode: str                 # "static" | "web" | "dual_rag"
    conversation_id: str
```

### Unified Evidence Gate

```python
def evidence_gate(
    chunks: list[EvidenceChunk],
    expected_domain: str,
    expected_state: str | None,
    min_chunks: int = 2,
    min_confidence: float = 0.25,
) -> tuple[bool, AbstentionReason | None, ConfidenceBand | None]:
```

Single gate replaces both `evidence_gate_v2` (static) and `_check_evidence_relevance` (web).

### StaticRAGService

```python
class StaticRAGService:
    def retrieve(
        self, embedding, query, domain, state, k=25
    ) -> RAGResult:
        """Supabase pgvector hybrid retrieval → evidence gate → EvidenceChunks."""
        # 1. Hybrid retrieval (dense + lexical, RRF fusion)
        # 2. Optional reranker (if enabled)
        # 3. Evidence gate (unified)
        # 4. Return EvidenceChunks + metadata
```

Encapsulates: `retrieve_hybrid()`, `JinaReranker`, `evidence_gate_v2`.

### WebRAGService

```python
class WebRAGService:
    def retrieve(
        self, query, classification
    ) -> RAGResult:
        """eGovAssistant-style 10-step web retrieval → EvidenceChunks."""
        # Step 1: Domain scope gate
        # Step 2: Web discovery (Tavily/Firecrawl)
        # Step 3: BM25 ranking
        # Step 4: Gemini pre-ranking
        # Step 5: RRF fusion
        # Step 6: Gemini final reranking
        # Step 7: Relevance gate (threshold 60.0)
        # Step 8: Source verification
        # Step 9: Evidence threshold check
        # Step 10: Return EvidenceChunks (no answer generation)
```

Adapted from eGovAssistant's `rag/pipeline.py` steps 1-9. Returns evidence only.

### RAGOrchestrator

```python
class RAGOrchestrator:
    def run(
        self, query, english_query, embedding, domain, state, classification, history
    ) -> RAGResponse:
        """Parallel dual-pipeline → merge → generate → verify."""
        # 1. Run both pipelines in parallel (ThreadPoolExecutor)
        # 2. Merge evidence (consistent format)
        # 3. Build merged prompt
        # 4. LLM generation (Groq primary, Gemini fallback)
        # 5. Citation verification
        # 6. Confidence calculation
        # 7. Return RAGResponse
```

### Chat Route (Thin)

```python
@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    # Language detection + translation (10 lines)
    # Domain classification (5 lines)
    # Out-of-scope check (5 lines)
    # Call orchestrator (5 lines)
    # Handle abstention (5 lines)
    # Translate answer back (5 lines)
    # Save session + return (15 lines)
    # Total: ~60 lines for /chat
```

Same pattern for `/chat/stream` — thin wrapper yielding SSE events.

## File Changes

### New Files
| File | Purpose | Lines (est.) |
|---|---|---|
| `services/__init__.py` | Package init | 5 |
| `services/static_rag.py` | StaticRAGService | ~120 |
| `services/web_rag.py` | WebRAGService | ~200 |
| `services/rag_orchestrator.py` | RAGOrchestrator | ~250 |

### Modified Files
| File | Changes |
|---|---|
| `contracts.py` | Add `EvidenceChunk`, `RAGResult`, `RAGResponse` models |
| `evidence_gate.py` | Refactor to accept `EvidenceChunk` list |
| `rag/prompt_builder.py` | Add `build_merged()` method |
| `routes/chat.py` | Replace 1053 lines with ~200 lines delegating to orchestrator |

### Unchanged Files
| File | Reason |
|---|---|
| `retrieval/bm25_retriever.py` | Already works |
| `retrieval/gemini_reranker.py` | Already works (align thresholds) |
| `retrieval/rrf.py` | Already works |
| `web_rag/service.py` | Already works |
| `web_rag/tavily_client.py` | Already works |
| `web_rag/firecrawl_client.py` | Already works |
| `rag/context_builder.py` | Already works |
| `rag/answer_generator.py` | Already works |
| `security/source_verifier.py` | Already works |

### Files to Delete After Migration
| File | Reason |
|---|---|
| `rag/pipeline.py` | Replaced by `WebRAGService` + `RAGOrchestrator` |
| `hybrid_retrieval.py` | Absorbed into `StaticRAGService` |
| `retrieval_strategies.py` | Absorbed into `StaticRAGService` |
| `generation.py` | Absorbed into `RAGOrchestrator` + `AnswerGenerator` |

## Evidence Flow

```
User Query
    ↓
Language Detection + Translation
    ↓
Domain Classification
    ↓
┌─────────────────┬─────────────────┐
│ Static RAG      │ Web RAG         │
│ (Supabase)      │ (Tavily/FC)     │
│                 │                 │
│ Hybrid Retrieve │ 10-Step Pipeline│
│ → Evidence Gate │ → Relevance Gate│
│ → EvidenceChunks│ → EvidenceChunks│
└────────┬────────┴────────┬────────┘
         │                 │
         └────────┬────────┘
                  ↓
         Merge EvidenceChunks
                  ↓
         Build Merged Prompt
                  ↓
         LLM Generation
                  ↓
         Citation Verification
                  ↓
         Answer + Citations + Confidence
```

## Citation Format

Unified to `[chunk:ID]` everywhere. No more `[static:ID]` or `[EVIDENCE N]`.

Static chunks: `[chunk:pmfby_00012]`
Web chunks: `[chunk:web_abc123]`

## Relevance Thresholds

| Gate | Current | New | Source |
|---|---|---|---|
| Static evidence gate | 0.25 (TOP1_THRESHOLD) | 0.25 | Kept |
| Web relevance gate | 2.5 | 60.0 | eGovAssistant alignment |
| Source trust score | 35.0 | 35.0 | Kept |

## Testing Strategy

1. Unit tests for each service class
2. Integration test: static RAG returns EvidenceChunks
3. Integration test: web RAG returns EvidenceChunks
4. Integration test: orchestrator merges correctly
5. Integration test: chat route delegates properly
6. Regression: all 417 existing tests still pass
7. Eval: run retrieval eval to confirm no quality regression

## Migration Plan

1. Create `services/` package with new service classes
2. Add `EvidenceChunk` to `contracts.py`
3. Refactor `evidence_gate.py` to accept `EvidenceChunk`
4. Build `StaticRAGService` (wrap existing hybrid retrieval)
5. Build `WebRAGService` (adapt eGovAssistant 10-step pipeline)
6. Build `RAGOrchestrator` (parallel + merge + generate)
7. Refactor `chat.py` to use orchestrator
8. Update streaming endpoint
9. Remove old files (`rag/pipeline.py`, `hybrid_retrieval.py`, etc.)
10. Run full test suite + eval
