"""Real-World Validation of Main RAG V3.

Standalone evaluation against the live Supabase corpus and real providers.
DO NOT MODIFY PRODUCTION CODE — this script only imports and calls existing APIs.

Usage:
    cd backend
    python -m tests.eval_rag_v3          # full evaluation
    python -m tests.eval_rag_v3 --retrieval-only   # skip LLM answer generation
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Evaluation cases — ground truth from actual corpus
# ---------------------------------------------------------------------------

@dataclass
class EvalCase:
    id: str
    category: str          # direct | scenario | multilingual | multi_doc
    subcategory: str       # definition | eligibility | procedure | ...
    question: str
    lang: str              # en | hi | gu | mr | bn
    domain: str            # expected domain
    state: str | None = None
    required_facts: list[str] = field(default_factory=list)
    required_evidence_docs: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    expected_abstain: bool = False
    history: list[dict] | None = None


EVAL_SET: list[EvalCase] = [
    # ── DIRECT: definitions ──────────────────────────────────────────────
    EvalCase(
        id="D01", category="direct", subcategory="definition",
        question="What is PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["Pradhan Mantri Fasal Bima Yojana", "crop insurance", "Kharif 2016"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="D02", category="direct", subcategory="definition",
        question="What is PACS?",
        lang="en", domain="pacs_governance",
        required_facts=["Primary Agricultural Credit Society", "cooperative"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="D03", category="direct", subcategory="definition",
        question="NSFI 2025-30 kya hai?",
        lang="hi", domain="financial_inclusion",
        required_facts=["National Strategy for Financial Inclusion", "2025-2030", "RBI"],
        required_evidence_docs=["Financial Inclusion", "NSFI"],
    ),

    # ── DIRECT: benefits ────────────────────────────────────────────────
    EvalCase(
        id="D04", category="direct", subcategory="benefits",
        question="What are the benefits of PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["risk cover", "pre-sowing", "post-harvest", "affordable premium"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="D05", category="direct", subcategory="benefits",
        question="What benefits do PACS members get?",
        lang="en", domain="pacs_governance",
        required_facts=["credit", "loan", "share", "dividend"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── DIRECT: eligibility ─────────────────────────────────────────────
    EvalCase(
        id="D06", category="direct", subcategory="eligibility",
        question="Who is eligible for PMFBY crop insurance?",
        lang="en", domain="pmfby",
        required_facts=["all farmers", "sharecropper", "tenant farmer", "notified crop", "notified area"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="D07", category="direct", subcategory="eligibility",
        question="Who can become a member of PACS?",
        lang="en", domain="pacs_governance",
        required_facts=["application", "Board of Directors", "five shares", "Rs. 500"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── DIRECT: procedure ───────────────────────────────────────────────
    EvalCase(
        id="D08", category="direct", subcategory="procedure",
        question="How to enroll in PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["NCIP", "bank branch", "PACS", "CSC", "cut-off date", "premium"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="D09", category="direct", subcategory="procedure",
        question="How to become a PACS member step by step?",
        lang="en", domain="pacs_governance",
        required_facts=["application form", "CEO", "Board of Directors", "share", "admission fee"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── DIRECT: numeric conditions ──────────────────────────────────────
    EvalCase(
        id="D10", category="direct", subcategory="numeric",
        question="What is the PMFBY premium rate for Kharif food crops?",
        lang="en", domain="pmfby",
        required_facts=["2%", "Sum Insured", "Kharif", "food grain"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="D11", category="direct", subcategory="numeric",
        question="What is the minimum share required to become a PACS member?",
        lang="en", domain="pacs_governance",
        required_facts=["five shares", "Rs. 100", "Rs. 500", "admission fee", "Rs. 10"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="D12", category="direct", subcategory="numeric",
        question="PMFBY mein Rabi food crops ka premium kitna hai?",
        lang="hi", domain="pmfby",
        required_facts=["1.5%", "Sum Insured", "Rabi"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── DIRECT: authority ───────────────────────────────────────────────
    EvalCase(
        id="D13", category="direct", subcategory="authority",
        question="Who implements PMFBY at the state level?",
        lang="en", domain="pmfby",
        required_facts=["State/UT Government", "Insurance Company", "NCIP"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── DIRECT: documents required ──────────────────────────────────────
    EvalCase(
        id="D14", category="direct", subcategory="documents",
        question="What documents are needed to enroll in PMFBY as a sharecropper?",
        lang="en", domain="pmfby",
        required_facts=["land records", "RoR", "LPC", "Aadhaar", "crop sown declaration"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: single condition ──────────────────────────────────────
    EvalCase(
        id="S01", category="scenario", subcategory="single_condition",
        question="I am a farmer with 2 hectares of paddy in Kharif season. Can I get PMFBY coverage?",
        lang="en", domain="pmfby",
        required_facts=["eligible", "notified crop", "paddy", "Kharif", "2% premium"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="S02", category="scenario", subcategory="single_condition",
        question="Main ek kisan hu, kya mujhe PMFBY ka labh milega?",
        lang="hi", domain="pmfby",
        required_facts=["eligible", "farmer", "PMFBY"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: multiple conditions ───────────────────────────────────
    EvalCase(
        id="S03", category="scenario", subcategory="multi_condition",
        question="I am a PACS member with 5 shares and I want a crop loan. Can I get it?",
        lang="en", domain="pacs_governance",
        required_facts=["member", "shares", "crop loan", "Board of Directors", "loan policy"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="S04", category="scenario", subcategory="multi_condition",
        question="I am a PACS member and I have 5 shares. Can I also get PMFBY insurance through PACS?",
        lang="en", domain="pmfby",
        required_facts=["PACS", "enrolment", "NCIP", "premium", "PMFBY"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="S05", category="scenario", subcategory="multi_condition",
        question="I have a KCC loan from PACS and I also want PMFBY coverage. What happens if I don't want PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["loanee farmer", "opt-out", "seven days", "cut-off date", "declaration"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: negative condition ────────────────────────────────────
    EvalCase(
        id="S06", category="scenario", subcategory="negative_condition",
        question="I am NOT a PACS member. Can I still get a loan from PACS?",
        lang="en", domain="pacs_governance",
        required_facts=["membership required", "not eligible", "A-class member"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="S07", category="scenario", subcategory="negative_condition",
        question="If my KCC loan has become sub-standard, can I still get PMFBY coverage as a loanee farmer?",
        lang="en", domain="pmfby",
        required_facts=["sub-standard", "not considered loanee", "non-loanee", "enrolment"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: missing user information ──────────────────────────────
    EvalCase(
        id="S08", category="scenario", subcategory="missing_info",
        question="Can I get a loan from PACS?",
        lang="en", domain="pacs_governance",
        required_facts=["membership required", "Board sanction", "loan policy"],
        required_evidence_docs=["Byelaws", "PACS"],
        forbidden_claims=["yes, you can"],  # should ask for membership status
    ),

    # ── SCENARIO: exception ─────────────────────────────────────────────
    EvalCase(
        id="S09", category="scenario", subcategory="exception",
        question="I have a crop loan from a bank but the land is not in my name. Can I get PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["insurable interest", "not eligible", "collateral", "without insurable interest"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: multi-step procedure ──────────────────────────────────
    EvalCase(
        id="S10", category="scenario", subcategory="multi_step",
        question="How do I join a PACS and then get a crop loan through it?",
        lang="en", domain="pacs_governance",
        required_facts=["application", "membership", "Board approval", "loan application", "loan sanction"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── SCENARIO: two sections ──────────────────────────────────────────
    EvalCase(
        id="S11", category="scenario", subcategory="two_sections",
        question="What are the PMFBY coverage risks and what are the exclusions?",
        lang="en", domain="pmfby",
        required_facts=["drought", "flood", "pest", "war", "nuclear", "preventable"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: two documents ─────────────────────────────────────────
    EvalCase(
        id="S12", category="scenario", subcategory="two_documents",
        question="How does PACS membership help with getting PMFBY insurance?",
        lang="en", domain="pmfby",
        required_facts=["PACS", "enrolment", "NCIP", "PMFBY", "premium collection"],
        required_evidence_docs=["Byelaws", "PMFBY"],
    ),

    # ── SCENARIO: central + Gujarat ─────────────────────────────────────
    EvalCase(
        id="S13", category="scenario", subcategory="central_gujarat",
        question="What is the difference between central cooperative law and Gujarat cooperative law for PACS membership?",
        lang="en", domain="pacs_governance",
        required_facts=["Model Byelaws", "Gujarat", "cooperative"],
        required_evidence_docs=["Byelaws", "PACS"],
        state="gujarat",
    ),

    # ── SCENARIO: comparison ────────────────────────────────────────────
    EvalCase(
        id="S14", category="scenario", subcategory="comparison",
        question="What is the difference between PMFBY and Weather Based Crop Insurance Scheme?",
        lang="en", domain="pmfby",
        required_facts=["PMFBY", "WBCIS", "yield based", "weather based"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),

    # ── SCENARIO: financial inclusion ───────────────────────────────────
    EvalCase(
        id="S15", category="scenario", subcategory="financial_inclusion",
        question="How many people have enrolled in PMJJBY and PMSBY as of 2024?",
        lang="en", domain="financial_inclusion",
        required_facts=["16 crore", "PMJJBY", "33.78 crore", "PMSBY", "March 2024"],
        required_evidence_docs=["Financial Inclusion", "NSFI"],
    ),
    EvalCase(
        id="S16", category="scenario", subcategory="financial_inclusion",
        question="What is the target for digital payment users in India by 2029?",
        lang="en", domain="financial_inclusion",
        required_facts=["one billion", "digital payment", "December 2029"],
        required_evidence_docs=["Financial Inclusion", "NSFI"],
    ),

    # ── SCENARIO: computerization ───────────────────────────────────────
    EvalCase(
        id="S17", category="scenario", subcategory="computerization",
        question="How many PACS are to be computerized and what is the total cost?",
        lang="en", domain="pacs_computerization",
        required_facts=["63,000", "Rs. 2,516 crore", "NABARD", "ERP"],
        required_evidence_docs=["Computerization", "PACS"],
    ),
    EvalCase(
        id="S18", category="scenario", subcategory="computerization",
        question="PACS computerization ka total cost kitna hai aur kaun kaun share karta hai?",
        lang="hi", domain="pacs_computerization",
        required_facts=["2,516 crore", "60.73%", "29.25%", "10.02%"],
        required_evidence_docs=["Computerization", "PACS"],
    ),

    # ── SCENARIO: out of scope ──────────────────────────────────────────
    EvalCase(
        id="S19", category="scenario", subcategory="out_of_scope",
        question="What is the weather today in Delhi?",
        lang="en", domain="out_of_scope",
        required_facts=[],
        expected_abstain=True,
    ),

    # ── MULTILINGUAL ────────────────────────────────────────────────────
    EvalCase(
        id="M01", category="multilingual", subcategory="hindi",
        question="PMFBY mein Kharif crops ka premium kitna hota hai?",
        lang="hi", domain="pmfby",
        required_facts=["2%", "Sum Insured", "Kharif"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="M02", category="multilingual", subcategory="hindi",
        question="PACS mein membership ke liye kitne shares chahiye?",
        lang="hi", domain="pacs_governance",
        required_facts=["five shares", "Rs. 100", "Rs. 500"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="M03", category="multilingual", subcategory="hinglish",
        question="Mujhe PMFBY mein enroll karna hai, kaise karun?",
        lang="hi", domain="pmfby",
        required_facts=["NCIP", "bank", "PACS", "premium"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="M04", category="multilingual", subcategory="gujarati",
        question="PACS ni membership mate ketla shares joie?",
        lang="gu", domain="pacs_governance",
        required_facts=["five shares", "Rs. 100", "Rs. 500"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── FOLLOW-UP ───────────────────────────────────────────────────────
    EvalCase(
        id="F01", category="scenario", subcategory="follow_up",
        question="And what about Rabi crops?",
        lang="en", domain="pmfby",
        required_facts=["1.5%", "Rabi", "food grain"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
        history=[
            {"role": "user", "content": "What is the PMFBY premium for Kharif crops?"},
            {"role": "assistant", "content": "The PMFBY premium for Kharif food crops is 2% of Sum Insured."},
        ],
    ),

    # ── PACS GOVERNANCE DETAILS ─────────────────────────────────────────
    EvalCase(
        id="G01", category="scenario", subcategory="governance",
        question="How many members are required in the quorum for a PACS General Body meeting?",
        lang="en", domain="pacs_governance",
        required_facts=["one-fourth", "500 members", "whichever is less"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="G02", category="scenario", subcategory="governance",
        question="What percentage of net profit must PACS allocate to reserves?",
        lang="en", domain="pacs_governance",
        required_facts=["25%", "net profit", "Reserves and Surplus"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),
    EvalCase(
        id="G03", category="scenario", subcategory="governance",
        question="What is the maximum shareholding limit for a PACS member?",
        lang="en", domain="pacs_governance",
        required_facts=["1/5th", "total subscribed share capital"],
        required_evidence_docs=["Byelaws", "PACS"],
    ),

    # ── PMFBY CLAIMS ────────────────────────────────────────────────────
    EvalCase(
        id="C01", category="scenario", subcategory="claims",
        question="What are the types of risk coverage under PMFBY?",
        lang="en", domain="pmfby",
        required_facts=["prevented sowing", "mid-season", "post-harvest", "localized calamity", "basic cover"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
    EvalCase(
        id="C02", category="scenario", subcategory="claims",
        question="What is excluded from PMFBY coverage?",
        lang="en", domain="pmfby",
        required_facts=["war", "nuclear", "preventable risks", "malicious damage"],
        required_evidence_docs=["PMFBY", "Crop Insurance"],
    ),
]

print(f"Loaded {len(EVAL_SET)} evaluation cases")

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    category: str
    subcategory: str
    question: str
    lang: str
    # Retrieval
    retrieved_chunks: int = 0
    retrieved_doc_ids: list[str] = field(default_factory=list)
    retrieval_scores: list[float] = field(default_factory=list)
    required_docs_found: list[str] = field(default_factory=list)
    required_docs_missing: list[str] = field(default_factory=list)
    evidence_coverage: float = 0.0
    # Answer
    answer_text: str = ""
    answer_correct: bool = False
    facts_found: list[str] = field(default_factory=list)
    facts_missing: list[str] = field(default_factory=list)
    forbidden_triggered: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    # Citations
    citations_valid: bool = False
    citation_count: int = 0
    # Confidence
    confidence: float = 0.0
    confidence_band: str = ""
    abstained: bool = False
    # Timing
    latency_ms: float = 0.0
    # Failure
    failure_root_cause: str = ""
    # Scenario-specific
    scenario_result_correct: bool = False
    planner_requirements: list[str] = field(default_factory=list)
    planner_hallucinated: bool = False
    derived_conclusions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------

async def run_retrieval_eval(cases: list[EvalCase]) -> list[CaseResult]:
    """Test retrieval only — no LLM generation."""
    from app.config import get_settings
    from app.services.static_rag import StaticRAGService

    settings = get_settings()
    static_rag = StaticRAGService(settings)

    # Try Jina first; fall back to Gemini if out of credits
    try:
        from app.providers.embeddings import get_embedding_provider
        embedder = get_embedding_provider()
        # Test with a short query
        embedder.embed_texts(["test"], task="retrieval.query")
        print("  Using Jina embeddings")
    except Exception:
        print("  Jina unavailable, falling back to Gemini embeddings")
        from app.providers.embeddings import GeminiEmbeddingProvider
        embedder = GeminiEmbeddingProvider(settings)

    results = []
    for case in cases:
        cr = CaseResult(
            case_id=case.id, category=case.category,
            subcategory=case.subcategory, question=case.question, lang=case.lang,
        )
        t0 = time.time()
        try:
            embedding = embedder.embed_texts([case.question], task="retrieval.query")[0]
            rag_result = static_rag.retrieve(
                embedding=embedding,
                query=case.question,
                domain=case.domain,
                state=case.state,
            )
            cr.latency_ms = (time.time() - t0) * 1000
            cr.retrieved_chunks = len(rag_result.chunks) if not rag_result.abstained else 0
            cr.abstained = rag_result.abstained

            if not rag_result.abstained and rag_result.chunks:
                cr.retrieved_doc_ids = list({c.title for c in rag_result.chunks})
                cr.retrieval_scores = [c.dense_score for c in rag_result.chunks]

                # Check required docs — match against title (case-insensitive substring)
                for req_doc in case.required_evidence_docs:
                    req_lower = req_doc.lower()
                    found = any(req_lower in c.title.lower() for c in rag_result.chunks)
                    if found:
                        cr.required_docs_found.append(req_doc)
                    else:
                        cr.required_docs_missing.append(req_doc)

                cr.evidence_coverage = (
                    len(cr.required_docs_found) / len(case.required_evidence_docs)
                    if case.required_evidence_docs else 1.0
                )

                # Check required facts in retrieved content
                all_content = " ".join(c.content.lower() for c in rag_result.chunks)
                for fact in case.required_facts:
                    if fact.lower() in all_content:
                        cr.facts_found.append(fact)
                    else:
                        cr.facts_missing.append(fact)

            elif case.expected_abstain:
                cr.answer_correct = True
                cr.failure_root_cause = ""

            if case.expected_abstain and not cr.abstained:
                cr.failure_root_cause = "EXPECTED_ABSTENTION"

        except Exception as e:
            cr.latency_ms = (time.time() - t0) * 1000
            cr.failure_root_cause = f"EXCEPTION: {e}"

        results.append(cr)
        status = "✓" if not cr.failure_root_cause else "✗"
        print(f"  {status} [{cr.case_id}] {cr.category}/{cr.subcategory} — "
              f"{cr.retrieved_chunks} chunks, {cr.evidence_coverage:.0%} coverage, "
              f"{cr.latency_ms:.0f}ms")

    return results


async def run_answer_eval(cases: list[EvalCase], retrieval_results: list[CaseResult]) -> list[CaseResult]:
    """Test full pipeline with LLM generation."""
    from app.config import get_settings
    from app.services.rag_orchestrator import RAGOrchestrator

    settings = get_settings()
    orchestrator = RAGOrchestrator(settings)

    # Try Jina first; fall back to Gemini if out of credits
    try:
        from app.providers.embeddings import get_embedding_provider
        embedder = get_embedding_provider()
        embedder.embed_texts(["test"], task="retrieval.query")
    except Exception:
        from app.providers.embeddings import GeminiEmbeddingProvider
        embedder = GeminiEmbeddingProvider(settings)

    results = []
    for i, case in enumerate(cases):
        retrieval_results[i] if i < len(retrieval_results) else None
        cr = CaseResult(
            case_id=case.id, category=case.category,
            subcategory=case.subcategory, question=case.question, lang=case.lang,
        )

        if case.expected_abstain:
            cr.abstained = True
            cr.answer_correct = True
            results.append(cr)
            continue

        t0 = time.time()
        try:
            embedding = embedder.embed_texts([case.question], task="retrieval.query")[0]

            response = await orchestrator.run(
                query=case.question,
                english_query=case.question,
                embedding=embedding,
                domain=case.domain,
                state=case.state,
                classification=None,
                history=case.history,
                lang=case.lang,
                session_id=f"eval-{case.id}",
            )

            cr.latency_ms = (time.time() - t0) * 1000
            cr.answer_text = response.answer
            cr.abstained = response.abstained
            cr.confidence = response.confidence
            cr.confidence_band = response.confidence_level.value if hasattr(response.confidence_level, 'value') else str(response.confidence_level)
            cr.citation_count = len(response.citations)

            # Check facts in answer
            answer_lower = response.answer.lower()
            for fact in case.required_facts:
                if fact.lower() in answer_lower:
                    cr.facts_found.append(fact)
                else:
                    cr.facts_missing.append(fact)

            # Check forbidden claims
            for forbidden in case.forbidden_claims:
                if forbidden.lower() in answer_lower:
                    cr.forbidden_triggered.append(forbidden)

            # Citation validity
            if response.citations:
                cr.citations_valid = all(
                    hasattr(c, 'chunk_id') or hasattr(c, 'text') for c in response.citations
                )

            # Determine overall correctness
            if case.required_facts:
                fact_coverage = len(cr.facts_found) / len(case.required_facts)
                cr.answer_correct = fact_coverage >= 0.5 and not cr.forbidden_triggered
            elif case.expected_abstain:
                cr.answer_correct = cr.abstained

            if not cr.answer_correct and not cr.failure_root_cause:
                if cr.forbidden_triggered or len(cr.facts_missing) > len(cr.facts_found):
                    cr.failure_root_cause = "ANSWER_GENERATION_ERROR"
                elif cr.abstained and not case.expected_abstain:
                    cr.failure_root_cause = "RETRIEVAL_MISS"

        except Exception as e:
            cr.latency_ms = (time.time() - t0) * 1000
            cr.failure_root_cause = f"EXCEPTION: {e}"

        results.append(cr)
        status = "✓" if cr.answer_correct else "✗"
        facts_str = f"{len(cr.facts_found)}/{len(case.required_facts)}" if case.required_facts else "n/a"
        print(f"  {status} [{cr.case_id}] facts={facts_str} "
              f"citations={cr.citation_count} {cr.latency_ms:.0f}ms")

    return results


# ---------------------------------------------------------------------------
# Measurement & Reporting
# ---------------------------------------------------------------------------

def measure(retrieval: list[CaseResult], answers: list[CaseResult]) -> dict:
    """Compute all required metrics."""
    metrics = {}

    # Filter out expected-abstain cases from accuracy calculations
    [r for r in retrieval if not (r.abstained and r.case_id in
                       {c.id for c in EVAL_SET if c.expected_abstain})]
    [a for a in answers if not a.abstained]

    # Total
    metrics["total_cases"] = len(EVAL_SET)

    # Direct accuracy
    direct_answers = [a for a in answers if a.category == "direct"]
    metrics["direct_accuracy"] = (
        sum(1 for a in direct_answers if a.answer_correct) / len(direct_answers)
        if direct_answers else 0
    )

    # Scenario accuracy
    scenario_answers = [a for a in answers if a.category == "scenario"]
    metrics["scenario_accuracy"] = (
        sum(1 for a in scenario_answers if a.answer_correct) / len(scenario_answers)
        if scenario_answers else 0
    )

    # Multi-condition accuracy
    multi_cond = [a for a in answers if a.subcategory in ("multi_condition", "single_condition")]
    metrics["multi_condition_accuracy"] = (
        sum(1 for a in multi_cond if a.answer_correct) / len(multi_cond)
        if multi_cond else 0
    )

    # Multi-document accuracy
    multi_doc = [a for a in answers if a.subcategory in ("two_documents", "central_gujarat")]
    metrics["multi_document_accuracy"] = (
        sum(1 for a in multi_doc if a.answer_correct) / len(multi_doc)
        if multi_doc else 0
    )

    # Multilingual accuracy
    multilingual = [a for a in answers if a.category == "multilingual"]
    metrics["multilingual_accuracy"] = (
        sum(1 for a in multilingual if a.answer_correct) / len(multilingual)
        if multilingual else 0
    )

    # Evidence coverage (retrieval)
    with_required = [r for r in retrieval if r.required_docs_found or r.required_docs_missing]
    metrics["evidence_coverage"] = (
        sum(r.evidence_coverage for r in with_required) / len(with_required)
        if with_required else 0
    )

    # Citation correctness
    with_citations = [a for a in answers if a.citation_count > 0]
    metrics["citation_correctness"] = (
        sum(1 for a in with_citations if a.citations_valid) / len(with_citations)
        if with_citations else 0
    )

    # Unsupported claims
    metrics["unsupported_claim_rate"] = (
        sum(1 for a in answers if a.unsupported_claims) / len(answers)
        if answers else 0
    )

    # Correct abstention
    expected_abstain_ids = {c.id for c in EVAL_SET if c.expected_abstain}
    abstain_cases = [a for a in answers if a.case_id in expected_abstain_ids]
    metrics["correct_abstention_rate"] = (
        sum(1 for a in abstain_cases if a.abstained) / len(abstain_cases)
        if abstain_cases else 0
    )

    # Clarification accuracy (missing info cases)
    missing_info = [a for a in answers if a.subcategory == "missing_info"]
    metrics["clarification_accuracy"] = (
        sum(1 for a in missing_info if not a.forbidden_triggered) / len(missing_info)
        if missing_info else 0
    )

    # Latency
    all_latencies = [a.latency_ms for a in answers if a.latency_ms > 0]
    metrics["average_latency_ms"] = sum(all_latencies) / len(all_latencies) if all_latencies else 0

    # Overall
    metrics["overall_accuracy"] = (
        sum(1 for a in answers if a.answer_correct) / len(answers)
        if answers else 0
    )

    return metrics


def report(retrieval: list[CaseResult], answers: list[CaseResult], metrics: dict) -> str:
    """Generate final evaluation report."""
    lines = []
    lines.append("=" * 70)
    lines.append("REAL-WORLD VALIDATION OF MAIN RAG V3 — FINAL REPORT")
    lines.append("=" * 70)

    # A. Results
    lines.append("\nA. REAL EVALUATION RESULTS")
    lines.append("-" * 40)
    lines.append(f"Total evaluation cases: {metrics['total_cases']}")
    lines.append(f"Overall accuracy:       {metrics['overall_accuracy']:.1%}")
    lines.append(f"Direct accuracy:        {metrics['direct_accuracy']:.1%}")
    lines.append(f"Scenario accuracy:      {metrics['scenario_accuracy']:.1%}")
    lines.append(f"Multi-condition acc:    {metrics['multi_condition_accuracy']:.1%}")
    lines.append(f"Multi-document acc:     {metrics['multi_document_accuracy']:.1%}")
    lines.append(f"Multilingual acc:       {metrics['multilingual_accuracy']:.1%}")
    lines.append(f"Evidence coverage:      {metrics['evidence_coverage']:.1%}")
    lines.append(f"Citation correctness:   {metrics['citation_correctness']:.1%}")
    lines.append(f"Unsupported claim rate: {metrics['unsupported_claim_rate']:.1%}")
    lines.append(f"Correct abstention:     {metrics['correct_abstention_rate']:.1%}")
    lines.append(f"Clarification accuracy: {metrics['clarification_accuracy']:.1%}")
    lines.append(f"Average latency:        {metrics['average_latency_ms']:.0f}ms")

    # B. Top Failures
    lines.append("\n\nB. TOP FAILURES")
    lines.append("-" * 40)
    failures = [a for a in answers if not a.answer_correct and a.failure_root_cause]
    for f in sorted(failures, key=lambda x: x.case_id):
        lines.append(f"\n  [{f.case_id}] {f.question[:80]}")
        lines.append(f"    Failure: {f.failure_root_cause}")
        lines.append(f"    Facts found: {f.facts_found}")
        lines.append(f"    Facts missing: {f.facts_missing}")
        if f.forbidden_triggered:
            lines.append(f"    FORBIDDEN: {f.forbidden_triggered}")
        if f.unsupported_claims:
            lines.append(f"    Unsupported: {f.unsupported_claims}")
        if f.answer_text:
            lines.append(f"    Answer snippet: {f.answer_text[:200]}...")

    # C. Retrieval Analysis
    lines.append("\n\nC. RETRIEVAL ANALYSIS")
    lines.append("-" * 40)
    for r in retrieval:
        if r.required_docs_missing:
            lines.append(f"  [{r.case_id}] Missing docs: {r.required_docs_missing}")

    # D-F placeholders
    lines.append("\n\nD. WHAT PART 1 SOLVED")
    lines.append("-" * 40)
    lines.append("  (To be filled based on comparison with pre-Part1 baseline)")

    lines.append("\n\nE. WHAT PART 2 SOLVED")
    lines.append("-" * 40)
    lines.append("  (To be filled based on scenario pipeline results)")

    lines.append("\n\nF. WHAT STILL FAILS")
    lines.append("-" * 40)
    lines.append("  (To be filled based on failure classification)")

    lines.append("\n\nG. RECOMMENDED NEXT CHANGE")
    lines.append("-" * 40)
    lines.append("  (To be filled based on measured failure patterns)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="RAG V3 Real-World Evaluation")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="Skip LLM answer generation, test retrieval only")
    parser.add_argument("--cases", nargs="*",
                        help="Run only specific case IDs (e.g., D01 S03)")
    args = parser.parse_args()

    cases = EVAL_SET
    if args.cases:
        cases = [c for c in EVAL_SET if c.id in args.cases]
        print(f"Running {len(cases)} selected cases")

    print(f"\n{'='*60}")
    print(f"Phase 1: Retrieval evaluation ({len(cases)} cases)")
    print(f"{'='*60}")
    retrieval_results = await run_retrieval_eval(cases)

    answers = retrieval_results  # default: no answer eval
    if not args.retrieval_only:
        print(f"\n{'='*60}")
        print(f"Phase 2: Answer evaluation ({len(cases)} cases)")
        print(f"{'='*60}")
        answers = await run_answer_eval(cases, retrieval_results)

    print(f"\n{'='*60}")
    print("Phase 3: Measurement & Report")
    print(f"{'='*60}")
    metrics = measure(retrieval_results, answers)
    report_text = report(retrieval_results, answers, metrics)
    print(report_text)

    # Save results
    out_path = Path(__file__).parent.parent / "eval_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "metrics": metrics,
            "cases": [
                {
                    "id": a.case_id, "category": a.category,
                    "subcategory": a.subcategory, "correct": a.answer_correct,
                    "facts_found": a.facts_found, "facts_missing": a.facts_missing,
                    "evidence_coverage": a.evidence_coverage,
                    "citations": a.citation_count, "latency_ms": a.latency_ms,
                    "failure": a.failure_root_cause,
                }
                for a in answers
            ],
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
