"""Gemini reranker — uses Gemini API to score candidate relevance.

Two-stage reranking:
1. Pre-ranking: Quick semantic scoring to filter candidates
2. Final reranking: Detailed relevance scoring for top candidates

Structured JSON output via response_schema for reliable parsing.
Jurisdiction-aware scoring prevents cross-country evidence contamination.
"""

from __future__ import annotations

import json
import logging

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger(__name__)


PRE_RANK_MAX_CANDIDATES = 50
PRE_RANK_TOP_K = 15
FINAL_TOP_K = 8
MAX_TEXT_CHARS = 1800

# google-genai rejects manually-set deadlines below 10s with
# 400 INVALID_ARGUMENT ("Minimum allowed deadline is 10s").
GEMINI_MIN_DEADLINE_S = 10.0


class GeminiReranker:

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        if not settings.reranker_enabled:
            logger.info("Reranker is disabled in config, using passthrough scoring")
            self._enabled = False
            self.client = None
        elif not self._api_key:
            logger.warning("Gemini API key not set, reranker will use passthrough scores")
            self._enabled = False
            self.client = None
        else:
            self._enabled = True
            self.model = getattr(settings, "grievance_gemini_model", settings.gemini_model)
            # Clamp to the API minimum so an explicit env override below 10s
            # cannot reintroduce the 400 INVALID_ARGUMENT failure.
            self._timeout_s = max(GEMINI_MIN_DEADLINE_S, float(settings.gemini_reranker_timeout_s))
            self.client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(self._timeout_s * 1000)),
            )
            logger.info("Gemini reranker initialized with model=%s", self.model)

    def _call_gemini(
        self,
        query: str,
        candidates: list[dict],
        classification: dict,
    ) -> dict | None:
        """Make a structured Gemini API call with response_schema.
        
        Falls back to Jina reranker when Gemini fails (503, rate limit, etc.).
        """
        if not self._enabled or not self.client:
            return None

        self._last_gemini_error = None
        try:
            result = self._try_gemini(query, candidates, classification)
        except Exception as exc:
            self._last_gemini_error = exc
            result = None
            logger.warning("Gemini reranking failed: %s", exc)
        if result is not None:
            result = dict(result)
            result["reranker_used"] = "gemini"
            logger.info("Gemini reranking complete")
            return result

        reason = self._gemini_failure_reason()
        logger.info("Gemini reranking unavailable; falling back to Jina (%s)", reason)
        try:
            result = self._try_jina_fallback(query, candidates)
        except Exception as exc:
            logger.warning("Jina fallback reranking failed: %s", exc)
            result = None
        if result is None:
            return None
        result = dict(result)
        result["reranker_used"] = "jina"
        result["reranker_fallback_reason"] = reason
        logger.info("Jina reranking complete (Gemini fallback)")
        return result

    def _gemini_failure_reason(self) -> str:
        """Return a stable provider reason for structured fallback telemetry."""
        error = getattr(self, "_last_gemini_error", None)
        if isinstance(error, TimeoutError) or "timeout" in str(error).lower():
            return "gemini_timeout"
        message = str(error).lower()
        for status in ("429", "500", "502", "503"):
            if status in message:
                return f"gemini_{status}"
        if "connection" in message or "connect" in message:
            return "gemini_connection_error"
        return "gemini_unavailable"
    
    def _try_gemini(
        self,
        query: str,
        candidates: list[dict],
        classification: dict,
    ) -> dict | None:
        """Attempt Gemini reranking."""
        try:
            domain = classification.get("domain")
            jurisdiction = classification.get("jurisdiction")
            state = classification.get("state")

            candidate_payload = self._build_candidate_payload(candidates)
            system_prompt = self._build_system_prompt(domain, jurisdiction, state)

            user_prompt = f"""
USER QUERY:
{query}

QUERY CLASSIFICATION:
{json.dumps({"domain": domain, "jurisdiction": jurisdiction, "state": state}, ensure_ascii=False, indent=2)}

DOCUMENT CANDIDATES:

{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}
"""

            response = self.client.models.generate_content(
                model=self.model,
                contents=[system_prompt, user_prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True,
                    ),
                    response_schema={
                        "type": "object",
                        "properties": {
                            "ranked_chunks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "chunk_id": {"type": "string"},
                                        "relevance_score": {"type": "number"},
                                        "applicable": {"type": "boolean"},
                                        "applicability_reason": {"type": "string"},
                                    },
                                    "required": ["chunk_id", "relevance_score", "applicable", "applicability_reason"],
                                },
                            },
                            "merge_groups": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "chunk_ids": {"type": "array", "items": {"type": "string"}},
                                        "reason": {"type": "string"},
                                    },
                                    "required": ["chunk_ids"],
                                },
                            },
                        },
                        "required": ["ranked_chunks", "merge_groups"],
                    },
                ),
            )
            text = response.text
            logger.info("Gemini reranker raw response (first 500 chars): %s", str(text)[:500])
            return json.loads(text)
        except Exception as e:
            self._last_gemini_error = e
            logger.warning("Gemini reranking call failed: %s", e)
            return None
    
    def _try_jina_fallback(
        self,
        query: str,
        candidates: list[dict],
    ) -> dict | None:
        """Use Jina reranker as fallback when Gemini fails."""
        try:
            from app.providers.reranker import JinaReranker
            jina = JinaReranker()
            
            # Prepare documents for Jina
            docs = []
            for c in candidates:
                text = str(c.get("text", c.get("content", "")))
                if len(text) > MAX_TEXT_CHARS:
                    text = text[:MAX_TEXT_CHARS] + "..."
                docs.append({"text": text, "chunk_id": c.get("chunk_id")})
            
            # Call Jina reranker
            reranked = jina.rerank(query=query, documents=docs, top_n=len(docs))
            
            # Convert Jina results to Gemini format
            ranked_chunks = []
            for r in reranked:
                score = r.get("reranker_score", 0.0) * 100  # Jina returns 0-1, convert to 0-100
                ranked_chunks.append({
                    "chunk_id": r.get("chunk_id"),
                    "relevance_score": score,
                    "applicable": score >= 20,  # Threshold for applicability
                    "applicability_reason": f"Jina reranker score: {score:.1f}",
                })
            
            return {
                "ranked_chunks": ranked_chunks,
                "merge_groups": [],
            }
        except Exception as e:
            logger.warning(f"Jina fallback reranking failed: {e}")
            return None

    @staticmethod
    def _build_candidate_payload(candidates: list[dict]) -> list[dict]:
        payload = []
        for index, candidate in enumerate(candidates, start=1):
            text = str(candidate.get("text", ""))
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "..."
            payload.append({
                "candidate_number": index,
                "chunk_id": candidate.get("chunk_id"),
                "document_id": candidate.get("document_id"),
                "source_url": candidate.get("source_url"),
                "source_title": candidate.get("title", candidate.get("source_title")),
                "section_id": candidate.get("section_id"),
                "section_title": candidate.get("section_title"),
                "section_type": candidate.get("section_type"),
                "page": candidate.get("page"),
                "text_preview": text,
            })
        return payload

    @staticmethod
    def _build_system_prompt(domain, jurisdiction, state) -> str:
        system_prompt = """
You are the evidence-ranking layer of eGovAssist.

You are NOT answering the user's question.

You must inspect ALL provided document candidates.

Your task is to determine which candidates are actually
applicable evidence for the user's exact question.

============================================================
IMPORTANT: SEMANTIC MATCH IS NOT ENOUGH
============================================================

Do NOT reward a candidate merely because it contains words
such as:

- grievance
- committee
- complaint
- redressal
- procedure
- disposal

A document is useful only when its actual meaning and legal,
governmental, institutional, or procedural context apply to
the question.

A question about Indian central-government grievance
redressal must NOT be supported by an unrelated foreign
regulation merely because it contains similar terminology.

Likewise, attorney disciplinary grievance procedures, private
organization complaint processes, and unrelated foreign
regulations must not be treated as evidence for a government
grievance question.

============================================================
JURISDICTION
============================================================

Expected jurisdiction:
__JURISDICTION__

Expected state:
__STATE__

Expected domain:
__DOMAIN__

When jurisdiction information is available:

- Prefer candidates that clearly belong to that jurisdiction.
- Penalize candidates from a different country or legal system.
- A foreign regulation is NOT relevant merely because its
  terminology resembles the question.
- If a candidate is clearly from the wrong jurisdiction and
  cannot directly answer the user's question, mark it
  applicable=false.

Do not invent jurisdiction information.

============================================================
DOMAIN AND INSTITUTIONAL CONTEXT
============================================================

The expected domain is:

__DOMAIN__

Determine whether the candidate actually belongs to the
same substantive domain.

For government grievance questions, distinguish between:

- government public grievance redressal
- CPGRAMS / DARPG
- government departments
- statutory grievance mechanisms

AND unrelated concepts such as:

- attorney grievance committees
- legal-assistance grievance procedures
- private-company complaints
- foreign grievance systems
- disciplinary grievance systems

Similar vocabulary does not establish applicability.

============================================================
QUESTION INTENT
============================================================

Determine what the user is actually asking for.

Examples:

"How long does X have to dispose of a complaint?"
    -> Need an applicable deadline/time limit.

"Who can file X?"
    -> Need applicable eligibility rules.

"How do I appeal X?"
    -> Need applicable appeal procedure.

"What documents are required?"
    -> Need applicable document requirements.

A candidate that merely discusses the general topic but
does not help answer the actual requested fact should receive
a low score.

============================================================
EVIDENCE QUALITY
============================================================

Prefer:

- official government sources
- statutes and regulations
- official orders
- official department pages
- official scheme documents
- authoritative institutional sources

But authority alone is NOT sufficient.

A highly authoritative document from the wrong jurisdiction
is still irrelevant evidence for the user's question.

============================================================
APPLICABILITY DECISION
============================================================

For EVERY candidate determine:

applicable = true
or
applicable = false

Set applicable=false when:

- it belongs to a clearly different jurisdiction and is not
  applicable to the user's question;
- it concerns a materially different institution or legal
  system;
- it discusses the same words but a different substantive
  process;
- it cannot reasonably support the answer to the exact query.

Set applicable=true only when the candidate can legitimately
be used as evidence for the user's question.

============================================================
RANKING
============================================================

Rank ALL supplied candidates according to actual usefulness.

Prefer:

100 = directly answers the question in the correct context
90-99 = extremely strong directly applicable evidence
80-89 = highly relevant supporting evidence
60-79 = useful supporting evidence
40-59 = somewhat relevant but limited
20-39 = weak evidence
1-19 = effectively irrelevant
0 = clearly inapplicable

IMPORTANT:

If applicable=false, relevance_score MUST be 0-10.

Do not give a high score to an inapplicable document.

============================================================
NO OUTSIDE KNOWLEDGE
============================================================

Do NOT use outside knowledge to answer the question.

Do NOT invent:

- laws
- deadlines
- authorities
- jurisdictions
- procedures
- exceptions

Judge only the supplied candidates and the supplied query
context.

============================================================
MERGING
============================================================

Some retrieved chunks may be fragments of the same underlying
piece of evidence.

Suggest merging chunks when:

- they clearly continue the same passage;
- they belong to the same document;
- they belong to the same section or closely related section;
- they are on the same or adjacent pages;
- presenting them separately would create a fragmented or
  half-cut evidence passage.

Do NOT suggest merging unrelated chunks merely because they
discuss the same general topic.

Do NOT rewrite, summarize, or modify source text.

Every chunk may belong to at most one merge group.

A merge group containing only one chunk is unnecessary and
should not be returned.

============================================================
OUTPUT
============================================================

Return JSON only.

ranked_chunks must contain ALL candidates exactly once.

Each ranked chunk MUST contain:

- chunk_id
- relevance_score
- applicable
- applicability_reason

merge_groups contains only groups of two or more chunk IDs
that should be presented together.

Example structure:

{
  "ranked_chunks": [
    {
      "chunk_id": "chunk_a",
      "relevance_score": 96,
      "applicable": true,
      "applicability_reason": "Directly applicable evidence."
    }
  ],
  "merge_groups": []
}

Every supplied candidate must appear exactly once.
"""

        system_prompt = system_prompt.replace("__DOMAIN__", str(domain or "unknown"))
        system_prompt = system_prompt.replace("__JURISDICTION__", str(jurisdiction or "unknown"))
        system_prompt = system_prompt.replace("__STATE__", str(state or "none"))

        return system_prompt

    def _build_ranked_results(
        self,
        candidates: list[dict],
        data: dict,
    ) -> tuple[list[dict], list[dict]]:
        """Build ranked results from structured Gemini response."""
        candidate_map = {
            candidate.get("chunk_id"): candidate
            for candidate in candidates
            if candidate.get("chunk_id")
        }

        ranked_results = []
        seen = set()

        for item in data.get("ranked_chunks", []):
            if not isinstance(item, dict):
                continue

            chunk_id = item.get("chunk_id")
            if not chunk_id or chunk_id in seen or chunk_id not in candidate_map:
                continue

            try:
                score = float(item.get("relevance_score", 0.0))
            except (TypeError, ValueError):
                score = 0.0

            score = max(0.0, min(100.0, score))

            applicable = item.get("applicable", False)
            if not isinstance(applicable, bool):
                applicable = str(applicable).lower() == "true"

            reason = str(item.get("applicability_reason", "")).strip()

            if not applicable:
                score = min(score, 10.0)

            result = dict(candidate_map[chunk_id])
            result["gemini_score"] = score
            result["rerank_score"] = score
            result["reranker"] = "gemini"
            result["rerank_applicable"] = applicable
            result["applicability_reason"] = reason

            ranked_results.append(result)
            seen.add(chunk_id)

        for candidate in candidates:
            chunk_id = candidate.get("chunk_id")
            if not chunk_id or chunk_id in seen:
                continue

            result = dict(candidate)
            result["gemini_score"] = 0.0
            result["rerank_score"] = 0.0
            result["reranker"] = "gemini_completion_fallback"
            result["rerank_applicable"] = False
            result["applicability_reason"] = "Gemini did not return a ranking decision for this candidate."
            ranked_results.append(result)
            seen.add(chunk_id)

        ranked_results.sort(
            key=lambda item: float(item.get("rerank_score", 0.0)),
            reverse=True,
        )

        valid_merge_groups = []
        used_merge_chunks = set()

        for group in data.get("merge_groups", []):
            if not isinstance(group, dict):
                continue
            chunk_ids = group.get("chunk_ids", [])
            if not isinstance(chunk_ids, list):
                continue

            clean_ids = []
            for chunk_id in chunk_ids:
                if chunk_id not in candidate_map:
                    continue
                if chunk_id in clean_ids or chunk_id in used_merge_chunks:
                    continue
                clean_ids.append(chunk_id)

            if len(clean_ids) < 2:
                continue

            valid_merge_groups.append({
                "chunk_ids": clean_ids,
                "reason": group.get("reason", ""),
            })
            used_merge_chunks.update(clean_ids)

        merge_map: dict[str, list[int]] = {}
        for group_index, group in enumerate(valid_merge_groups, start=1):
            for chunk_id in group["chunk_ids"]:
                merge_map.setdefault(chunk_id, []).append(group_index)

        for result in ranked_results:
            chunk_id = result.get("chunk_id")
            result["gemini_merge_groups"] = merge_map.get(chunk_id, [])

        return ranked_results, valid_merge_groups

    def pre_rank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = PRE_RANK_TOP_K,
        classification: dict | None = None,
    ) -> list[dict]:
        """Stage 1 Gemini ranking on discovery candidate pool."""
        if not self._enabled or not candidates:
            return self._passthrough_pre_rank(query, candidates, top_k)

        query = str(query or "").strip()
        if not query or top_k <= 0:
            return []

        if classification is None:
            classification = {}

        candidates = candidates[:PRE_RANK_MAX_CANDIDATES]
        logger.info(f"Gemini pre-ranking {len(candidates)} candidates...")

        data = self._call_gemini(query=query, candidates=candidates, classification=classification)

        if not data:
            return self._passthrough_pre_rank(query, candidates, top_k)

        ranked_results, _merge_groups = self._build_ranked_results(candidates, data)

        final_results = []
        for rank, result in enumerate(ranked_results[:top_k], start=1):
            result = dict(result)
            result["gemini_pre_rank"] = rank
            result["reranker"] = data.get("reranker_used", "gemini")
            if data.get("reranker_fallback_reason"):
                result["reranker_fallback_reason"] = data["reranker_fallback_reason"]
            final_results.append(result)

        applicable_count = sum(1 for r in final_results if r.get("rerank_applicable", False))
        logger.info(f"Gemini pre-ranking complete: {len(final_results)} returned, {applicable_count} applicable")

        return final_results

    def _passthrough_pre_rank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """Fallback passthrough scoring when Gemini is unavailable."""
        scored = []
        for i, c in enumerate(candidates):
            result = dict(c)
            result["gemini_score"] = float(c.get("bm25_score", 100.0 - i))
            result["rerank_applicable"] = True
            result["reranker"] = "passthrough"
            scored.append(result)
        scored.sort(key=lambda x: x["gemini_score"], reverse=True)
        return scored[:top_k]

    def final_rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = FINAL_TOP_K,
        classification: dict | None = None,
    ) -> list[dict]:
        """Stage 2 Gemini ranking on RRF fused pool."""
        if not self._enabled or not candidates:
            return self._passthrough_final_rerank(query, candidates, top_k)

        query = str(query or "").strip()
        if not query or top_k <= 0:
            return []

        if classification is None:
            classification = {}

        logger.info(f"Gemini final reranking {len(candidates)} fused candidates...")

        data = self._call_gemini(query=query, candidates=candidates, classification=classification)

        if not data:
            return self._passthrough_final_rerank(query, candidates, top_k)

        ranked_results, _merge_groups = self._build_ranked_results(candidates, data)

        final_results = []
        for rank, result in enumerate(ranked_results, start=1):
            if len(final_results) >= top_k:
                break
            if not result.get("rerank_applicable", False):
                continue
            result = dict(result)
            result["gemini_final_rank"] = rank
            result["reranker"] = data.get("reranker_used", "gemini_final")
            if data.get("reranker_fallback_reason"):
                result["reranker_fallback_reason"] = data["reranker_fallback_reason"]
            final_results.append(result)

        logger.info(
            "%s final reranking complete: %d final chunks",
            "Jina reranking (Gemini fallback)" if data.get("reranker_used") == "jina" else "Gemini",
            len(final_results),
        )
        return final_results

    def _passthrough_final_rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """Fallback passthrough scoring when Gemini is unavailable."""
        scored = []
        max_rrf = 2.0 / 61.0  # Max possible RRF score for 2 lists (k=60)
        for i, c in enumerate(candidates):
            result = dict(c)
            if "rrf_score" in c:
                rrf_score = float(c.get("rrf_score", 0.0))
                normalized = min(100.0, (rrf_score / max_rrf) * 100.0)
                result["rerank_score"] = round(normalized, 2)
                result["gemini_score"] = round(normalized, 2)
            else:
                result["rerank_score"] = float(c.get("gemini_score", c.get("bm25_score", 100.0 - i)))
            result["rerank_applicable"] = True
            result["reranker"] = "passthrough"
            scored.append(result)
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
        classification: dict | None = None,
    ) -> list[dict]:
        """Backward-compatible method."""
        return self.final_rerank(query=query, candidates=candidates, top_k=top_k, classification=classification)


_reranker = None


def pre_rank(query: str, candidates: list[dict], top_k: int = 15, classification: dict | None = None) -> list[dict]:
    global _reranker
    if _reranker is None:
        _reranker = GeminiReranker()
    return _reranker.pre_rank(query=query, candidates=candidates, top_k=top_k, classification=classification)


def final_rerank(query: str, candidates: list[dict], top_k: int = 8, classification: dict | None = None) -> list[dict]:
    global _reranker
    if _reranker is None:
        _reranker = GeminiReranker()
    return _reranker.final_rerank(query=query, candidates=candidates, top_k=top_k, classification=classification)


def rerank(query: str, candidates: list[dict], top_k: int = 5, classification: dict | None = None) -> list[dict]:
    global _reranker
    if _reranker is None:
        _reranker = GeminiReranker()
    return _reranker.rerank(query=query, candidates=candidates, top_k=top_k, classification=classification)
