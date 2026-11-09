# Product Requirements Document

## Product

Multilingual, voice-capable, evidence-grounded citizen-assistance SPA (static
single-page app, not a PWA) for cooperative governance, PMFBY crop insurance,
financial inclusion, and grievance redressal in India.

The system answers questions strictly from official sources with citations,
abstains when evidence is insufficient, supports voice interaction (Sarvam AI),
and provides a prototype grievance intake workflow.

---

## Goals

1. Provide trustworthy, cited information about: cooperative law/by-laws, PACS,
   Ministry of Cooperation schemes, PMFBY, financial literacy.
2. Support 11 languages: English, Hindi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Punjabi, Odia, Malayalam (text + voice I/O).
3. Provide 9-stage grievance intake → entity extraction → follow-up → prototype reference → status lookup.
4. Deploy entirely in the cloud, no personal GPU, zero monetary cost for the demo.

---

## Non-goals (MVP)

Native Android, native iOS, WhatsApp integration, blockchain, custom model
training, self-hosted GPU inference, autonomous multi-agent systems, complex
authentication, analytics dashboard, real government grievance submission
(no public CPGRAMS API exists), nationwide legal coverage.

---

## Target users

Cooperative members, farmers, and rural stakeholders seeking official guidance
in English, Hindi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Punjabi,
Odia, or Malayalam.

---

## Core requirements (all implemented)

1. Multilingual text chat (EN, HI, GU, MR, BN, TA, TE, KN, PA, OR, ML).
2. Central cooperative info + PACS info + Gujarat state rules. Mandatory metadata
   on every legal/cooperative answer: `jurisdiction, state, effective_date, verified_date`.
3. PMFBY: FAQ, eligibility guidance, process guidance.
4. Financial literacy: NSFI 2025-30 content.
5. Grievance: 9-stage workflow (classify → extract entities → detect missing info
   → follow-up → create prototype reference → status lookup).
6. Voice: Sarvam AI STT + TTS (primary) → Azure Speech STT (fallback) → text-only.
7. Domain routing + parallel static & web RAG orchestration + grounded generation.
8. Citations, confidence, explicit abstention on every factual answer.
9. Responsive static SPA (React + Vite, desktop + mobile browsers; not a PWA).
10. Demonstrably deployed in the cloud.

---

## API contracts

```
POST /chat
  Body: { question, session_id, language, ui_language_explicit?, state?, as_of_date?, history?, mode? }
  language: "en" | "hi" | "gu" | "mr" | "bn" | "ta" | "te" | "kn" | "pa" | "or" | "ml"

POST /chat/stream
  Same body; returns SSE events: thinking | token | metadata | done

POST /voice
  Multipart: audio (file), language (form), session_id (form), state? (form)

POST /voice/transcribe
  Body: { audio: base64_string, language }

POST /voice/speak
  Body: { text, language, segments? }

POST /grievance
GET  /conversations/{session_id}
GET  /evidence/{...}
GET  /health
GET  /health/providers
```

**Chat response:** `answer, language, domain, intent, entities, confidence,
confidence_level, citations[{chunk_id, title, source, source_label, url, page?, section?}],
abstained, speech_text, speech_segments, follow_up_question, mode, conversation_id`

Response modes: `dual_rag | static | web | grievance`

---

## Safety & trust requirements

1. Never fabricate facts, citations, or capabilities.
2. Every citation must map to a chunk retrieved in that request.
3. Low retrieval confidence forces abstention — not an LLM judgment call.
4. Never present national/model rules as universally applicable across states.
5. Grievances are prototypes, never official submissions (`is_official_submission: false`).
6. Never expose provider API credentials.
7. Avoid sending real personal grievance data to free-tier LLM providers.

---

## Success metrics (internal)

Groundedness, factual correctness, citation accuracy, latency, abstention
correctness, domain classification accuracy, jurisdiction accuracy, provider
fallback success. Three flagship demos run end-to-end without failure:

1. Hindi PMFBY voice query
2. Cooperative/PACS state-filtered question
3. Grievance intake + status lookup

---

## Constraints

Cloud-only, free tiers only, no personal GPU. Free tiers have quotas, cold starts,
and inactivity pauses — the architecture tolerates all three.

## Risks

- Free-tier limits: Groq/Gemini have rate limits, Render sleeps on inactivity,
  Supabase free projects may pause after inactivity.
- Legal coverage: central + Gujarat only. Must be stated clearly in demo.
- Agriculture corpus: not yet ingested. Static retrieval maps `agriculture` → `pmfby` corpus; the web path serves `agriculture` fully. It does NOT route to `out_of_scope`.

---

## Definition of done

✅ **Achieved.** Deployed static SPA where text questions in 11 languages flow through
domain routing → hybrid RAG (static pgvector + web) → grounded, cited answers,
with correct abstention on unsupported questions, and grievances can be created
with multi-turn intake + status lookup guidance. Voice (STT/TTS) working via
Sarvam AI.

> **Post-MVP current state (2026-10-06, see PROJECT_STATUS.md):** 11 languages
> (EN, HI, GU, MR, BN, TA, TE, KN, PA, OR, ML); SerpApi Google live alongside
> Tavily; bounded WebDiscovery recovery (≤2 rounds) with cooperative deadline;
> mandatory Clerk auth on chat/voice/grievance-write. PRD above is the frozen
> MVP contract; code truth lives in `AGENTS.md` + `PROJECT_STATUS.md`.
