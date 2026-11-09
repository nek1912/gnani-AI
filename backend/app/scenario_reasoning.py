"""Scenario Reasoning — controlled multi-condition, multi-hop, comparison reasoning.

Classifies query complexity, extracts structured requirements, retrieves
per-requirement, builds evidence maps, derives conclusions, and generates
grounded answers.

Architecture:
  1. QueryComplexityClassifier (deterministic) → SIMPLE | COMPLEX
  2. ScenarioPlanner (LLM) → ScenarioPlan with requirements
  3. Per-requirement retrieval → EvidenceMap
  4. Controlled follow-up retrieval (max 1 retry)
  5. Derived conclusions from multi-fact combinations
  6. Structured answer generation with grounding enforcement

CORE RULE: The LLM must never invent missing facts.
It may reason only over facts explicitly stated by the user or retrieved
from authoritative evidence.
"""

from __future__ import annotations

import json
import logging
import re

from app.contracts import (
    AbstentionReason,
    DerivedConclusion,
    EvidenceChunk,
    EvidenceMapEntry,
    EvidenceSufficiency,
    QueryComplexity,
    RequirementStatus,
    EvidenceRequirement,
    RAGResult,
    ScenarioPlan,
)
from app.llm_fallback import AllProvidersFailedError, grounded_answer
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Deterministic Query Complexity Classifier
# ---------------------------------------------------------------------------

# Pattern indicators for each complexity type
_COMPARISON_MARKERS = re.compile(
    r"\b(vs|versus|compared?\s+to|difference\s+between|which\s+(is\s+)?better|"
    r"compare|advantage|disadvantage|pros?\s+and\s+cons?)\b",
    re.IGNORECASE,
)

_CONDITIONAL_MARKERS = re.compile(
    r"\b(if|when|provided|assuming|suppose|in\s+case|condition|eligib|"
    r"qualify|criteria|require|must\s+have|prerequisite|满足)\b",
    re.IGNORECASE,
)

_MULTI_CONDITION_MARKERS = re.compile(
    r"\b(and|also|additionally|moreover|furthermore|both|all\s+of|"
    r"each|every|combined|together)\b",
    re.IGNORECASE,
)

_PROCEDURE_MARKERS = re.compile(
    r"\b(how\s+to|how\s+do\s+i|steps?\s+to|process|procedure|"
    r"apply|application|register|enrollment|form|document|submit|"
    r"documents?\s+required|what\s+do\s+i\s+need)\b",
    re.IGNORECASE,
)

_ELIGIBILITY_MARKERS = re.compile(
    r"\b(who\s+can|am\s+i\s+eligible|can\s+i\s+(get|apply|join|avail)|"
    r"eligib|qualify|criteria|entitled|eligible)\b",
    re.IGNORECASE,
)

_MULTI_HOP_MARKERS = re.compile(
    r"\b(and\s+then|after\s+that|once\s+.+,\s*(then|can|i)|"
    r"first\s+.+\s+then|step\s+\d|followed\s+by|subsequently|"
    r"become\s+.+\s+and|join\s+.+\s+and|register\s+.+\s+then)\b",
    re.IGNORECASE,
)

_AMBIGUOUS_MARKERS = re.compile(
    r"\b(tell\s+me\s+about|what\s+do\s+you\s+know|information|"
    r"details?|general|overview|help)\b",
    re.IGNORECASE,
)


class QueryComplexityClassifier:
    """Deterministic classifier for query structural complexity.

    Classifies queries into one of:
      SIMPLE, PROCEDURE, ELIGIBILITY, SCENARIO, MULTI_CONDITION,
      MULTI_HOP, COMPARISON, AMBIGUOUS

    Uses pattern matching only — no LLM call.
    """

    def classify(self, query: str, lang: str = "en") -> QueryComplexity:
        q = query.strip()
        if not q:
            return QueryComplexity.AMBIGUOUS

        # Count indicator matches
        scores: dict[QueryComplexity, int] = {c: 0 for c in QueryComplexity}

        # Comparison markers
        if _COMPARISON_MARKERS.search(q):
            scores[QueryComplexity.COMPARISON] += 3

        # Procedure markers
        if _PROCEDURE_MARKERS.search(q):
            scores[QueryComplexity.PROCEDURE] += 2

        # Eligibility markers
        if _ELIGIBILITY_MARKERS.search(q):
            scores[QueryComplexity.ELIGIBILITY] += 2

        # Multi-hop markers (sequential steps)
        if _MULTI_HOP_MARKERS.search(q):
            scores[QueryComplexity.MULTI_HOP] += 3

        # Multi-condition markers (conjunction density)
        conjunctions = len(re.findall(r"\b(and|also|additionally|moreover)\b", q, re.IGNORECASE))
        if conjunctions >= 2:
            scores[QueryComplexity.MULTI_CONDITION] += 2
        elif conjunctions >= 1:
            scores[QueryComplexity.MULTI_CONDITION] += 1

        # Conditional markers
        if _CONDITIONAL_MARKERS.search(q):
            scores[QueryComplexity.SCENARIO] += 2

        # Scenario: has both conditions AND personal state
        personal_indicators = re.findall(
            r"\b(i\s+am|i\s+have|i\s+want|my|i\s+already|currently\s+have|"
            r"i\s+hold|i\s+own|i\s+belong|i\s+live)\b",
            q, re.IGNORECASE,
        )
        if personal_indicators and _CONDITIONAL_MARKERS.search(q):
            scores[QueryComplexity.SCENARIO] += 2

        # Question mark count (multiple questions = more complex)
        question_marks = q.count("?")
        if question_marks >= 2:
            scores[QueryComplexity.MULTI_CONDITION] += 1

        # Find winner
        best = max(scores, key=lambda k: scores[k])
        best_score = scores[best]

        # Minimum threshold: need at least 2 points to be complex
        if best_score < 2:
            # Check if it's just a simple info request
            if _AMBIGUOUS_MARKERS.search(q) and best_score == 0:
                return QueryComplexity.SIMPLE
            return QueryComplexity.SIMPLE

        return best


# ---------------------------------------------------------------------------
# 2. Scenario Planner (LLM-based requirement extraction)
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = """You are a requirement extraction engine for a government information system.

Given a user query, extract:
1. What the user has stated about themselves (user_facts)
2. What needs to be checked/verified to answer (requirements)
3. What information the user has NOT provided but is needed (missing_user_facts)

Output STRICTLY valid JSON with this schema:
{
  "user_facts": ["fact1", "fact2"],
  "requirements": [
    {
      "description": "what needs to be checked",
      "search_query": "english search query for retrieval"
    }
  ],
  "missing_user_facts": ["what user hasn't told us"]
}

RULES:
- Do NOT claim what the rules are. Only extract what must be checked.
- search_query must be a clear English retrieval query.
- Each requirement must be independently searchable.
- missing_user_facts: only include facts that are REQUIRED to answer but NOT stated.
- Do NOT include speculative requirements.
- Keep requirements atomic: one condition per requirement.
"""


class ScenarioPlanner:
    """Extracts structured requirements from complex queries using LLM."""

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    def plan(
        self,
        query: str,
        lang: str,
        history: list[dict] | None = None,
    ) -> ScenarioPlan:
        """Extract requirements from a complex query.

        Args:
            query: The user's original query (may be non-English).
            lang: Language code.
            history: Conversation history for context.

        Returns:
            ScenarioPlan with structured requirements.
        """
        # Build context from history
        history_text = ""
        if history:
            recent = history[-4:] if len(history) > 4 else history
            turns = "\n".join(
                f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
                for h in recent if isinstance(h, dict)
            )
            if turns:
                history_text = f"\nPrevious conversation:\n{turns}\n"

        user_prompt = (
            f"User language: {lang}\n"
            f"{history_text}\n"
            f"User query: {query}\n\n"
            f"Extract requirements as JSON."
        )

        try:
            raw = self._llm.generate(_PLANNER_SYSTEM, user_prompt, temperature=0.0)
            # Extract JSON from response (may be wrapped in markdown)
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                logger.warning("Planner returned no JSON: %s", raw[:200])
                return self._fallback_plan(query)

            data = json.loads(json_match.group())
            return self._parse_plan(data, query)

        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.warning("Planner failed: %s — using fallback", e)
            return self._fallback_plan(query)

    def _parse_plan(self, data: dict, query: str) -> ScenarioPlan:
        """Parse LLM output into ScenarioPlan."""
        requirements = []
        for i, req in enumerate(data.get("requirements", [])):
            requirements.append(EvidenceRequirement(
                requirement_id=f"req_{i}",
                description=req.get("description", ""),
                search_query=req.get("search_query", ""),
                source="inferred",
            ))

        return ScenarioPlan(
            complexity=QueryComplexity.SCENARIO,
            user_facts=data.get("user_facts", []),
            requirements=requirements,
            missing_user_facts=data.get("missing_user_facts", []),
            original_query=query,
        )

    def _fallback_plan(self, query: str) -> ScenarioPlan:
        """Fallback when LLM fails: create a single requirement from the query."""
        return ScenarioPlan(
            complexity=QueryComplexity.SCENARIO,
            user_facts=[],
            requirements=[EvidenceRequirement(
                requirement_id="req_0",
                description=query,
                search_query=query,
                source="inferred",
            )],
            missing_user_facts=[],
            original_query=query,
        )


# ---------------------------------------------------------------------------
# 3. Evidence Map Builder
# ---------------------------------------------------------------------------

class EvidenceMapBuilder:
    """Builds and maintains the evidence coverage map."""

    def build_map(
        self,
        plan: ScenarioPlan,
        retrieval_results: dict[str, RAGResult],
    ) -> tuple[list[EvidenceMapEntry], list[EvidenceChunk]]:
        """Build evidence map from retrieval results.

        Args:
            plan: The scenario plan with requirements.
            retrieval_results: Dict mapping requirement_id → RAGResult.

        Returns:
            (evidence_map, all_evidence_chunks)
        """
        evidence_map: list[EvidenceMapEntry] = []
        all_evidence: list[EvidenceChunk] = []

        for req in plan.requirements:
            result = retrieval_results.get(req.requirement_id)
            if result is None or result.abstained or not result.chunks:
                evidence_map.append(EvidenceMapEntry(
                    requirement_id=req.requirement_id,
                    description=req.description,
                    status=RequirementStatus.UNSUPPORTED,
                    evidence_count=0,
                ))
                continue

            # Check quality of evidence
            high_score_chunks = [
                c for c in result.chunks
                if (c.dense_score or 0) >= 0.40
            ]

            if high_score_chunks:
                status = RequirementStatus.SUPPORTED
                req.status = RequirementStatus.SUPPORTED
                req.evidence_ids = [c.chunk_id for c in high_score_chunks]
            elif result.chunks:
                status = RequirementStatus.PARTIAL
                req.status = RequirementStatus.PARTIAL
                req.evidence_ids = [c.chunk_id for c in result.chunks[:3]]
            else:
                status = RequirementStatus.UNSUPPORTED

            evidence_map.append(EvidenceMapEntry(
                requirement_id=req.requirement_id,
                description=req.description,
                status=status,
                evidence_count=len(result.chunks),
                evidence_ids=req.evidence_ids,
            ))
            all_evidence.extend(result.chunks)

        return evidence_map, all_evidence

    def assess_sufficiency(
        self,
        evidence_map: list[EvidenceMapEntry],
        plan: ScenarioPlan,
    ) -> EvidenceSufficiency:
        """Assess overall evidence sufficiency from the evidence map."""
        if not evidence_map:
            return EvidenceSufficiency.EMPTY

        supported = sum(1 for e in evidence_map if e.status == RequirementStatus.SUPPORTED)
        partial = sum(1 for e in evidence_map if e.status == RequirementStatus.PARTIAL)
        total = len(evidence_map)
        len(plan.missing_user_facts)

        # All requirements supported
        if supported == total:
            return EvidenceSufficiency.SUFFICIENT

        # Most supported (>= 70%)
        if supported >= total * 0.7:
            return EvidenceSufficiency.PARTIAL

        # Some support but gaps remain
        if supported + partial >= total * 0.5:
            return EvidenceSufficiency.PARTIAL

        # Mostly unsupported
        if supported == 0 and partial == 0:
            return EvidenceSufficiency.INSUFFICIENT

        return EvidenceSufficiency.PARTIAL

    def find_unsupported(
        self,
        evidence_map: list[EvidenceMapEntry],
        plan: ScenarioPlan,
    ) -> list[EvidenceRequirement]:
        """Find requirements that lack evidence and need retry."""
        unsupported = []
        for req in plan.requirements:
            entry = next(
                (e for e in evidence_map if e.requirement_id == req.requirement_id),
                None,
            )
            if entry and entry.status in (RequirementStatus.UNSUPPORTED, RequirementStatus.PARTIAL):
                # Only retry if we have a meaningful search query
                if req.search_query and len(req.search_query) > 5:
                    unsupported.append(req)
        return unsupported


# ---------------------------------------------------------------------------
# 4. Derived Conclusion Engine
# ---------------------------------------------------------------------------

class DerivedConclusionEngine:
    """Derives conclusions from multiple evidence items."""

    def derive(
        self,
        plan: ScenarioPlan,
        evidence_map: list[EvidenceMapEntry],
        all_evidence: list[EvidenceChunk],
    ) -> list[DerivedConclusion]:
        """Derive conclusions from the evidence map.

        Rules for derivation:
        - All material requirements must be SUPPORTED
        - Conclusions must cite specific evidence IDs
        - Never derive rules not present in evidence
        """
        conclusions: list[DerivedConclusion] = []

        supported_entries = [
            e for e in evidence_map if e.status == RequirementStatus.SUPPORTED
        ]

        # If all requirements are supported, derive overall conclusion
        if len(supported_entries) == len(plan.requirements) and plan.requirements:
            all_ids = []
            for e in supported_entries:
                all_ids.extend(e.evidence_ids)

            conclusions.append(DerivedConclusion(
                conclusion="All stated conditions have supporting evidence",
                supporting_evidence_ids=list(set(all_ids)),
                requires_conditions=[e.description for e in supported_entries],
            ))

        # Derive conditional conclusions for partial coverage
        partial_entries = [
            e for e in evidence_map if e.status == RequirementStatus.PARTIAL
        ]
        if partial_entries and supported_entries:
            supported_ids = []
            for e in supported_entries:
                supported_ids.extend(e.evidence_ids)
            partial_ids = []
            for e in partial_entries:
                partial_ids.extend(e.evidence_ids)

            conclusions.append(DerivedConclusion(
                conclusion="Partial evidence available — some conditions verified, others need clarification",
                supporting_evidence_ids=list(set(supported_ids + partial_ids)),
                requires_conditions=[e.description for e in partial_entries],
            ))

        return conclusions


# ---------------------------------------------------------------------------
# 5. Scenario Reasoning Engine (orchestrates the full flow)
# ---------------------------------------------------------------------------

_SCENARIO_ANSWER_SYSTEM = """You are a government information assistant for Indian citizens.

You are answering a complex scenario question. You have been provided with:
- The user's stated facts
- Structured evidence organized by requirement
- Evidence coverage status for each requirement
- Any derived conclusions

CRITICAL RULES:

1. RESPOND in the USER LANGUAGE specified below.

2. Answer ONLY based on the evidence provided. Each factual claim MUST have
   a [chunk:ID] citation from the evidence.

3. For each requirement, state clearly:
   - What the evidence says (with citation)
   - Whether the user's condition is met based on the evidence

4. If a requirement is UNSUPPORTED:
   - State that the information is not available in the provided documents
   - Suggest what type of official source to consult
   - Do NOT guess or use general knowledge

5. If user facts are MISSING:
   - Ask the user for the specific missing information
   - Do NOT assume the answer

6. For derived conclusions:
   - State the conclusion
   - List ALL supporting evidence IDs
   - Explain the reasoning chain

7. Structure your answer:
   - Brief summary answer
   - Condition-by-condition breakdown with citations
   - Missing information requests (if any)
   - Next steps or official sources (if needed)

8. NEVER fabricate rules, thresholds, dates, fees, or eligibility criteria.
"""


class ScenarioReasoningEngine:
    """Orchestrates the full scenario reasoning flow.

    Usage:
        engine = ScenarioReasoningEngine(settings)
        result = await engine.reason(
            plan=plan,
            english_query="...",
            domain="pacs_governance",
            state="gujarat",
            lang="en",
        )
    """

    def __init__(
        self,
        static_rag,
        llm_provider: LLMProvider,
    ) -> None:
        self._static_rag = static_rag
        self._llm = llm_provider
        self._planner = ScenarioPlanner(llm_provider)
        self._evidence_map_builder = EvidenceMapBuilder()
        self._conclusion_engine = DerivedConclusionEngine()

    def plan_query(
        self,
        query: str,
        lang: str,
        history: list[dict] | None = None,
    ) -> ScenarioPlan:
        """Phase 1: Extract requirements from the query."""
        return self._planner.plan(query, lang, history)

    def retrieve_per_requirement(
        self,
        plan: ScenarioPlan,
        domain: str,
        state: str | None,
        embedding: list[float] | None = None,
    ) -> dict[str, RAGResult]:
        """Phase 2: Retrieve evidence for each requirement independently.

        Uses the requirement's search_query for retrieval.
        Falls back to embedding-based retrieval if available.
        """
        results: dict[str, RAGResult] = {}

        for req in plan.requirements:
            try:
                # Use search_query for retrieval
                query_embedding = embedding  # Reuse original embedding if available

                result = self._static_rag.retrieve(
                    embedding=query_embedding or [0.0] * 768,
                    query=req.search_query,
                    domain=domain,
                    state=state,
                )
                results[req.requirement_id] = result
                logger.info(
                    "Retrieved for %s: %d chunks (abstained=%s)",
                    req.requirement_id, len(result.chunks), result.abstained,
                )
            except Exception:
                logger.exception("Retrieval failed for %s", req.requirement_id)
                results[req.requirement_id] = RAGResult(
                    chunks=[], abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                    domain=domain,
                )

        return results

    def build_evidence_map(
        self,
        plan: ScenarioPlan,
        retrieval_results: dict[str, RAGResult],
    ) -> tuple[list[EvidenceMapEntry], list[EvidenceChunk]]:
        """Phase 3: Build the evidence coverage map."""
        return self._evidence_map_builder.build_map(plan, retrieval_results)

    def retry_unsupported(
        self,
        plan: ScenarioPlan,
        evidence_map: list[EvidenceMapEntry],
        domain: str,
        state: str | None,
        embedding: list[float] | None = None,
        max_retries: int = 1,
    ) -> tuple[dict[str, RAGResult], list[EvidenceMapEntry], list[EvidenceChunk]]:
        """Phase 4: Controlled follow-up retrieval for unsupported requirements.

        Maximum 1 retry round. Stops when all material requirements are
        supported or evidence cannot be found.
        """
        for retry_round in range(max_retries):
            unsupported = self._evidence_map_builder.find_unsupported(
                evidence_map, plan,
            )
            if not unsupported:
                break

            logger.info(
                "Retry round %d: %d unsupported requirements",
                retry_round + 1, len(unsupported),
            )

            retry_results: dict[str, RAGResult] = {}
            for req in unsupported:
                try:
                    # Broaden the query slightly for retry
                    broadened = req.search_query + " eligibility criteria requirements"
                    result = self._static_rag.retrieve(
                        embedding=embedding or [0.0] * 768,
                        query=broadened,
                        domain=domain,
                        state=state,
                    )
                    retry_results[req.requirement_id] = result
                except Exception:
                    logger.exception("Retry retrieval failed for %s", req.requirement_id)

            if retry_results:
                # Rebuild evidence map with new results
                retrieval_results = retry_results
                evidence_map, all_evidence = self._evidence_map_builder.build_map(
                    plan, retrieval_results,
                )
                return retry_results, evidence_map, all_evidence

        return {}, evidence_map, []

    def generate_answer(
        self,
        query: str,
        plan: ScenarioPlan,
        evidence_map: list[EvidenceMapEntry],
        derived_conclusions: list[DerivedConclusion],
        all_evidence: list[EvidenceChunk],
        lang: str,
        history: list[dict] | None = None,
    ) -> str:
        """Phase 6: Generate the grounded answer.

        Uses structured evidence map to enforce grounding.
        """
        # Build structured evidence context
        evidence_context = self._build_evidence_context(
            plan, evidence_map, derived_conclusions, all_evidence,
        )

        # Build history
        hist_text = ""
        if history:
            recent = history[-3:] if len(history) > 3 else history
            turns = "\n".join(
                f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
                for h in recent if isinstance(h, dict)
            )
            if turns:
                hist_text = f"Previous conversation:\n{turns}\n\n"

        _LANG_NAMES = {
            "en": "English", "hi": "Hindi (Devanagari script)",
            "gu": "Gujarati (Gujarati script)", "mr": "Marathi (Devanagari script)",
            "bn": "Bengali (Bengali script)", "ta": "Tamil (Tamil script)",
        }
        lang_name = _LANG_NAMES.get(lang, lang)

        user_prompt = (
            f"USER LANGUAGE: {lang_name}\n"
            f"{hist_text}"
            f"User query: {query}\n\n"
            f"== USER'S STATED FACTS ==\n"
            f"{chr(10).join('- ' + f for f in plan.user_facts) or 'None stated'}\n\n"
            f"== EVIDENCE BY REQUIREMENT ==\n"
            f"{evidence_context}\n\n"
            f"== EVIDENCE COVERAGE STATUS ==\n"
            f"{self._build_coverage_summary(evidence_map)}\n\n"
            f"== DERIVED CONCLUSIONS ==\n"
            f"{self._build_conclusion_summary(derived_conclusions)}\n\n"
            f"== MISSING USER INFORMATION ==\n"
            f"{chr(10).join('- ' + f for f in plan.missing_user_facts) or 'None'}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Write your ENTIRE response in {lang_name}.\n"
            f"2. For each requirement, state what the evidence says with [chunk:ID] citations.\n"
            f"3. If a requirement is unsupported, say so clearly and suggest an official source.\n"
            f"4. If user information is missing, ask for it specifically.\n"
            f"5. Structure: Summary → Condition breakdown → Missing info → Next steps.\n"
            f"6. Do NOT fabricate rules, thresholds, or eligibility criteria.\n"
        )

        try:
            answer = grounded_answer(self._llm, self._llm, _SCENARIO_ANSWER_SYSTEM, user_prompt)
            return answer.replace("\u3010", "[").replace("\u3011", "]")
        except AllProvidersFailedError:
            logger.exception("All LLM providers failed for scenario answer")
            return ""

    def _build_evidence_context(
        self,
        plan: ScenarioPlan,
        evidence_map: list[EvidenceMapEntry],
        derived_conclusions: list[DerivedConclusion],
        all_evidence: list[EvidenceChunk],
    ) -> str:
        """Build structured evidence context for the prompt."""
        parts: list[str] = []

        for req in plan.requirements:
            entry = next(
                (e for e in evidence_map if e.requirement_id == req.requirement_id),
                None,
            )
            status_str = entry.status.value if entry else "unsupported"

            parts.append(f"### Requirement: {req.description}")
            parts.append(f"Status: {status_str.upper()}")

            if entry and entry.evidence_ids:
                # Find matching evidence chunks
                for eid in entry.evidence_ids[:3]:
                    chunk = next((c for c in all_evidence if c.chunk_id == eid), None)
                    if chunk:
                        short_id = chunk.chunk_id[:8]
                        meta = chunk.title
                        if chunk.section:
                            meta += f" — {chunk.section}"
                        parts.append(f"[chunk:{short_id}] ({meta})")
                        parts.append(chunk.content[:500])
                        parts.append("")

            if status_str == "unsupported":
                parts.append("No supporting evidence found in corpus.")
            parts.append("")

        return "\n".join(parts)

    def _build_coverage_summary(self, evidence_map: list[EvidenceMapEntry]) -> str:
        lines = []
        for e in evidence_map:
            lines.append(f"- {e.description}: {e.status.value} ({e.evidence_count} chunks)")
        return "\n".join(lines) if lines else "No requirements assessed."

    def _build_conclusion_summary(self, conclusions: list[DerivedConclusion]) -> str:
        if not conclusions:
            return "No derived conclusions."
        lines = []
        for c in conclusions:
            lines.append(f"- {c.conclusion}")
            lines.append(f"  Evidence: {', '.join(c.supporting_evidence_ids[:5])}")
        return "\n".join(lines)
