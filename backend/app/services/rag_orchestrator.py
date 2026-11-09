"""RAG Orchestrator — async dual-pipeline RAG with evidence bundle.

Runs static RAG (Supabase pgvector) and web RAG (Tavily/Firecrawl) in
parallel via asyncio.gather, merges evidence chunks into an EvidenceBundle,
builds a curated source-priority prompt, generates an answer via LLM with
provider fallback, verifies citations, calculates confidence,
and returns a typed RAGResponse.

Architecture:
  1. asyncio.gather runs both pipelines concurrently (return_exceptions=True)
  2. EvidenceController builds an EvidenceBundle + curated prompt
  3. LLM generates answer (Groq primary, Gemini fallback)
  4. Citations are verified
  5. Confidence is calculated
  6. RAGResponse is returned
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable

from app.answer_grounding import verify_answer_grounding
from app.citation_verifier import (
    normalize_citation_markers,
    short_citation_id,
    verify_citations,
)
from app.config import Settings, get_settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
    EvidenceSufficiency,
    RAGResponse,
    RAGResult,
)
from app.domains import get_anchor_store
from app.facets import Facet, select_coverage, split_facets
from app.evidence_controller import EvidenceController, QueryRequirementClassifier, strip_citations, clean_answer
from app.llm_fallback import AllProvidersFailedError, grounded_answer
from app.scenario_reasoning import QueryComplexityClassifier
from app.providers.gemini_llm import GeminiLLMProvider
from app.providers.groq_llm import GroqLLMProvider
from app.providers.sarvam_chat import SarvamChatProvider
from app.services.static_rag import StaticRAGService
from app.services.web_rag import WebRAGService
from app.speech_text import prepare_speech_text, segment_speech
from app.ui import get_abstain_text
from app.web_rag.query_classifier import (
    QueryClassification,
    effective_domain,
    resolve_expected_state,
)
from app.web_rag.referrals import build_referral

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RAGOrchestrator implementation
# ---------------------------------------------------------------------------

_BAND_TO_CONFIDENCE: dict[str, float] = {
    "high": 0.9,
    "medium": 0.7,
    "low": 0.4,
}


def fix_broken_tables(answer: str) -> str:
    """Detect and fix broken markdown table formatting.
    
    The LLM sometimes outputs pipe-separated text that isn't valid
    markdown table syntax. This function:
    1. Identifies lines that look like broken tables (have | but no proper header/separator)
    2. Attempts to reconstruct them as proper tables
    3. Falls back to stripping pipe characters if reconstruction fails
    
    A table is considered valid if it has:
    - A header row (line starting and ending with |, containing text)
    - At least one data row (line starting and ending with |, containing text)
    - Optionally a separator row (|---|---|)
    
    Tables missing only the separator row are preserved as-is since
    react-markdown/remark-gfm can still render them. Only truly broken
    tables (pipe characters used as inline text separators, not table
    structure) are converted to bullet lists.
    """
    lines = answer.split('\n')
    result = []
    i = 0
    
    # Pattern for a table header or data row: starts with |, has cells, ends with |
    _TABLE_ROW_RE = re.compile(r'^\s*\|[^\n|]+\|(?:[^\n|]+\|)*\s*$')
    # Pattern for a separator row: |---|---| etc.
    _SEPARATOR_RE = re.compile(r'^\s*\|[\s\-:|]+\|\s*$')
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line starts a potential table (or is an inline broken table)
        if '|' in line:
            # Collect consecutive lines with |
            table_lines = []
            j = i
            while j < len(lines) and '|' in lines[j]:
                table_lines.append(lines[j])
                j += 1
            
            # Check if it's a valid table:
            # - Has at least 2 rows that look like table rows (header + data)
            # - OR has a separator row with at least 2 other rows
            header_or_data_rows = [tl for tl in table_lines if _TABLE_ROW_RE.match(tl)]
            has_separator = any(_SEPARATOR_RE.match(tl) for tl in table_lines)
            
            if (len(header_or_data_rows) >= 2) or (has_separator and len(table_lines) >= 2):
                # Valid table structure — keep as is
                # If missing separator row but has header + data, insert one
                if not has_separator and len(header_or_data_rows) >= 2:
                    # Insert separator row after the first header row
                    first_row = table_lines[0]
                    num_cols = first_row.count('|') - 1  # pipes between cells
                    separator = "|" + "---|" * num_cols
                    result.append(first_row)
                    result.append(separator)
                    result.extend(table_lines[1:])
                else:
                    result.extend(table_lines)
            else:
                # Broken table — pipe characters used as inline text separators
                # Convert to bullet list preserving content
                for tl in table_lines:
                    cleaned = tl.replace('|', ' ').strip()
                    cleaned = re.sub(r'\s+', ' ', cleaned)
                    if cleaned and cleaned != '---':
                        result.append(f"- {cleaned}")
            
            i = j
        else:
            result.append(line)
            i += 1
    
    return '\n'.join(result)


class RAGOrchestrator:
    """Runs async dual-pipeline RAG with evidence bundling and claim verification.

    Usage:
        orchestrator = RAGOrchestrator(settings)
        response = await orchestrator.run(
            query="What is PMFBY?",
            english_query="What is PMFBY?",
            embedding=[0.1] * 768,
            domain="pmfby",
            state="gujarat",
            classification=classification,
            history=[],
            lang="en",
            session_id="sess-123",
        )
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._static_rag = StaticRAGService(self._settings)
        self._web_rag = WebRAGService()
        self._evidence_controller = EvidenceController()
        self._query_classifier = QueryRequirementClassifier()
        self._complexity_classifier = QueryComplexityClassifier()

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
        pipeline_mode: str | None = None,
        on_step: Callable[[dict], None] | None = None,
        as_of_date: str | None = None,
    ) -> RAGResponse:
        """Execute the full async dual-pipeline RAG flow.

        Args:
            query: Original user query (may be non-English).
            english_query: Translated English query for retrieval.
            embedding: Query embedding vector.
            domain: Detected domain from AnchorStore.
            state: Resolved state for jurisdiction filtering.
            classification: Query classification from QueryClassifier.
            history: Conversation history turns.
            lang: Response language code.
            session_id: Session identifier.
            language_mix: Optional dict mapping language codes to their
                proportion in the mixed-language query.
            model_override: Optional LLM model name to override the default.
            on_step: Optional callback invoked with progress dicts
                (``{"id": ..., "detail": ..., "status": ...}``) at each major
                pipeline stage so callers can stream step-by-step updates.

        Returns:
            RAGResponse with answer, citations, confidence, and speech data.
        """
        # NOTE: no per-request state is stored on self — the singleton is
        # shared across concurrent requests. `lang`/`session_id` travel as
        # explicit arguments only.
        logger.info(
            "RAGOrchestrator.run: domain=%s state=%s lang=%s session=%s",
            domain, state, lang, session_id,
        )

        if classification is None:
            classification = self._web_rag.web_discovery.classifier.classify(english_query, default_state=state)

        # P1: single effective-domain rule (shared with WebRAGService):
        # the AnchorStore domain wins when specific; the classifier only
        # fills in for empty/general anchors. Both pipelines then plan
        # and filter on the same domain for the same query.
        domain = effective_domain(domain, classification)
        # P1: an explicit state word in the query beats an inherited
        # session value for evidence filtering (static and web alike).
        state = resolve_expected_state(state, classification)

        # Facet-aware retrieval: decompose multi-domain queries into
        # per-domain facets. A single facet proceeds exactly as today
        # (same _run_pipelines, same _merge_evidence, same static k=25).
        try:
            _hits = get_anchor_store().collect_hits(english_query)
        except Exception:
            logger.exception("Facet anchor lookup failed; falling back to single domain")
            _hits = [domain]
        try:
            _complexity = self._complexity_classifier.classify(english_query, lang).value
        except Exception:
            logger.exception("Complexity classification failed; assuming simple")
            _complexity = "simple"
        _facets = split_facets(english_query, _hits, classification, _complexity, state)
        _facet_merged: list[EvidenceChunk] | None = None
        _facet_coverage: dict | None = None

        # Step 1: Classify query requirements
        query_requirements = self._query_classifier.classify(query, lang)

        if on_step:
            on_step({
                "id": "retrieval_start",
                "label": "Searching Knowledge Base",
                "detail": f"Querying official corpus for {domain} in {state or 'All-India'}",
                "status": "active",
            })

        # Step 2: Run pipelines based on mode
        if len(_facets) == 1:
            static_result, web_result = await self._run_pipelines(
                english_query=english_query,
                embedding=embedding,
                domain=domain,
                state=state,
                classification=classification,
                mode=pipeline_mode or "rag_web",
                as_of_date=as_of_date,
            )
        else:
            static_result, web_result, _facet_merged, _facet_coverage = await self._run_facet_pipelines(
                facets=_facets,
                embedding=embedding,
                classification=classification,
                mode=pipeline_mode or "rag_web",
                as_of_date=as_of_date,
            )
        web_total_ms = float(web_result.metadata.get("web_total_ms", 0.0))

        if on_step:
            static_count = len(static_result.chunks) if not static_result.abstained else 0
            web_count = len(web_result.chunks) if not web_result.abstained else 0
            if static_count > 0:
                on_step({"id": "static_done", "label": "Official Documents Retrieved", "detail": f"Found {static_count} chunks from official documents", "status": "completed"})
            if web_count > 0:
                on_step({"id": "web_done", "label": "Web Sources Retrieved", "detail": f"Found {web_count} results from web sources", "status": "completed"})

        has_static = not static_result.abstained and len(static_result.chunks) > 0
        has_web = not web_result.abstained and len(web_result.chunks) > 0

        logger.info(
            "Pipeline results: static=%d chunks (abstained=%s), web=%d chunks (abstained=%s)",
            len(static_result.chunks), static_result.abstained,
            len(web_result.chunks), web_result.abstained,
        )

        # Step 3: Proceed with evidence bundle & answer generation for all queries
        # (Even when retrieved evidence is minimal/empty, the LLM will generate an answer)


        # Step 4: Build evidence bundle
        if on_step:
            on_step({"id": "retrieval_start", "label": "Retrieval Complete", "detail": "Retrieval complete", "status": "completed"})
            on_step({"id": "evidence_merge", "label": "Merging Evidence", "detail": "Merging and ranking evidence from both sources", "status": "active"})
        bundle = self._evidence_controller.build_bundle(
            static_result, web_result, query_requirements, query,
        )
        # I1: wire facet groups + coverage into the bundle/prompt so the
        # merged list (citations/grounding) and the prompt stay consistent.
        # Single-facet path leaves these None → legacy flat prompt.
        _prompt_facet_groups: dict | None = None
        if _facet_coverage is not None:
            _raw_groups = web_result.metadata.get("facet_groups")
            if isinstance(_raw_groups, dict) and _facet_merged is not None:
                _merged_ids_by_facet: dict[str, set[str]] = {}
                for _fid, _chunks in _raw_groups.items():
                    try:
                        _merged_ids_by_facet[_fid] = {c.chunk_id for c in (_chunks or [])}
                    except Exception:
                        _merged_ids_by_facet[_fid] = set()
                _prompt_facet_groups = {}
                for _fid in _raw_groups.keys():
                    _ids = _merged_ids_by_facet.get(_fid, set())
                    _prompt_facet_groups[_fid] = [c for c in _facet_merged if c.chunk_id in _ids]
                # Preserve facets with zero merged chunks (unsupported → sentinel).
                for _fid in _raw_groups.keys():
                    _prompt_facet_groups.setdefault(_fid, [])
            elif isinstance(_raw_groups, dict):
                _prompt_facet_groups = _raw_groups
            try:
                bundle.facet_groups = _prompt_facet_groups
                bundle.facet_coverage = _facet_coverage
            except Exception:
                logger.exception("Failed to attach facet groups to bundle")

        # Step 5: Assess evidence
        assessment = self._evidence_controller.assess_evidence(
            static_result, web_result, query_requirements,
        )

        # Step 6: Build curated prompt with source-priority rules
        # Pass the real response language so the LLM writes directly in
        # the user's language (translation in chat.py is only a safety
        # net). Hard-coding "en" here forced every non-English answer
        # through Sarvam→Azure, turning any translation outage into a
        # user-facing English leak.
        _t_prompt_start = time.monotonic()
        system_prompt, user_prompt = self._evidence_controller.build_curated_prompt(
            bundle, english_query, history, lang,
            language_mix=language_mix,
            assessment=assessment,
            facet_groups=_prompt_facet_groups,
            facet_coverage=_facet_coverage,
        )
        _t_prompt_ready = time.monotonic()
        prompt_build_ms = (_t_prompt_ready - _t_prompt_start) * 1000

        # Step 7: Generate answer via LLM (Groq primary → Gemini fallback → Sarvam tertiary)
        # Always use the primary model; the provider's own fallback iteration
        # handles model list traversal (GPT-OSS → Qwen → Gemini → Sarvam).
        if on_step:
            on_step({"id": "evidence_merge", "label": "Evidence Merged", "detail": "Evidence merged", "status": "completed"})
            on_step({"id": "llm_generate", "label": "Generating Response", "detail": "Generating grounded response from retrieved evidence", "status": "active"})
        model_name = model_override or self._settings.groq_model

        mode = "groq"
        try:
            primary_provider = GroqLLMProvider(self._settings)
            primary_provider._model = model_name  # Override for model_override support

            tertiary_provider = None
            try:
                if self._settings.sarvam_keys:
                    tertiary_provider = SarvamChatProvider(self._settings)
            except Exception as e:
                logger.warning("Could not initialize SarvamChatProvider for fallback: %s", e)

            _t_groq_start = time.monotonic()
            answer = grounded_answer(
                primary_provider,
                GeminiLLMProvider(self._settings),
                system_prompt,
                user_prompt,
                tertiary=tertiary_provider,
            )
            _t_groq_done = time.monotonic()
            answer = answer.replace("【", "[").replace("】", "]")
            # Normalize format variants (full-width brackets, bare [ID])
            # into canonical [chunk:ID] BEFORE verification so repair and
            # verification operate on the same marker set. Validity is still
            # decided against retrieved evidence, so this weakens nothing.
            answer = normalize_citation_markers(answer)
        except AllProvidersFailedError:
            logger.exception(
                "All LLM providers failed: retrieval had static=%d (band=%s) web=%d (band=%s) domain=%s lang=%s — abstaining PROVIDER_UNAVAILABLE",
                len(static_result.chunks), static_result.band,
                len(web_result.chunks), web_result.band, domain, lang,
            )
            return self._abstain_response(
                lang=lang,
                reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                domain=domain,
                session_id=session_id,
            )

        # Step 8: Auto-append citations if missing and clean non-citation markers.
        # Only gate-passing pipelines contribute citable evidence: chunks
        # from an abstained pipeline failed domain/jurisdiction/count/
        # score checks and must not become citable downstream.
        usable_static = static_result.chunks if not static_result.abstained else []
        usable_web = web_result.chunks if not web_result.abstained else []
        if _facet_merged is not None:
            all_chunks = _facet_merged
        else:
            all_chunks = self._merge_evidence(usable_static, usable_web)
        answer = self._auto_append_citations(answer, all_chunks)

        # Step 9: Verify citations against evidence, with auto-repair.
        # P1-1/P1-6: lead-only and quarantined chunks are not citable —
        # their IDs are excluded so LLM markers pointing at them fail
        # verification and are repaired away like any invalid prefix.
        all_chunk_ids = [
            chunk.chunk_id
            for chunk in all_chunks
            if not (chunk.metadata or {}).get("lead_only")
            and not (
                isinstance((chunk.metadata or {}).get("impersonation"), dict)
                and (chunk.metadata or {}).get("impersonation", {}).get(
                    "suspicious"
                )
            )
        ]
        # URLs taken verbatim from retrieved evidence are not fabricated:
        # allowlist them so a correct answer naming the official portal
        # does not fail verification. Non-evidence URLs still fail.
        allowed_urls = {chunk.url for chunk in all_chunks if chunk.url}
        try:
            citation_verification = verify_citations(
                answer, all_chunk_ids, allowed_urls=allowed_urls,
            )
        except Exception:
            logger.exception(
                "Citation verification crashed: retrieval had static=%d web=%d domain=%s lang=%s — abstaining CITATION_FAILURE",
                len(static_result.chunks), len(web_result.chunks), domain, lang,
            )
            return self._abstain_response(
                lang=lang,
                reason=AbstentionReason.CITATION_FAILURE,
                domain=domain,
                session_id=session_id,
            )
        if not citation_verification.is_valid:
            logger.warning(
                "Citation verification failed: reason=%s invalid_prefixes=%s static=%d web=%d domain=%s lang=%s — performing auto-repair",
                citation_verification.reason, citation_verification.invalid_prefixes,
                len(static_result.chunks), len(web_result.chunks), domain, lang,
            )
            # Repair invalid prefixes if present
            for prefix in citation_verification.invalid_prefixes:
                answer = re.sub(rf"\[chunk:\s*{prefix}[0-9a-fA-F]*\]", "", answer)
            
            # Re-ensure valid citations from retrieved chunks
            answer = self._auto_append_citations(answer, all_chunks, force=True)
            try:
                citation_verification = verify_citations(
                    answer, all_chunk_ids, allowed_urls=allowed_urls,
                )
            except Exception:
                logger.exception(
                    "Citation re-verification crashed: static=%d web=%d domain=%s lang=%s — abstaining CITATION_FAILURE",
                    len(static_result.chunks), len(web_result.chunks), domain, lang,
                )
                return self._abstain_response(
                    lang=lang,
                    reason=AbstentionReason.CITATION_FAILURE,
                    domain=domain,
                    session_id=session_id,
                )

            # Persistent citation failure is a safe failure even when chunks
            # exist: the generated markers do not map to retrieved evidence.
            if not citation_verification.is_valid:
                logger.warning(
                    "Persistent citation failure: reason=%s static=%d (band=%s) web=%d (band=%s) domain=%s lang=%s — abstaining",
                    citation_verification.reason,
                    len(static_result.chunks), static_result.band,
                    len(web_result.chunks), web_result.band, domain, lang,
                )
                return self._abstain_response(
                    lang=lang,
                    reason=citation_verification.reason or AbstentionReason.CITATION_FAILURE,
                    domain=domain,
                    session_id=session_id,
                )

        # Step 9.5: Post-generation grounding check (enforcing, not advisory).
        # Unsupported factual claims must not survive into a HIGH-confidence
        # answer: deterministically repair using existing evidence, re-verify,
        # and safe-abstain if claims persist or nothing supportable remains.
        # Verifier crashes fail closed — never a substantive answer.
        _t_grounding_start = time.monotonic()
        grounding_repaired = False
        try:
            grounding_result = verify_answer_grounding(
                answer,
                all_chunks,
                use_llm_verification=self._settings.answer_grounding_llm_enabled,
                settings=self._settings,
            )
        except Exception:
            logger.exception(
                "Answer grounding verification crashed: static=%d web=%d domain=%s lang=%s — abstaining INSUFFICIENT_EVIDENCE",
                len(static_result.chunks), len(web_result.chunks), domain, lang,
            )
            return self._abstain_response(
                lang=lang,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                domain=domain,
                session_id=session_id,
            )
        if grounding_result.has_unsupported_claims:
            logger.warning(
                "Grounding check found %d unsupported claims: %s static=%d (band=%s) web=%d (band=%s) domain=%s lang=%s",
                len(grounding_result.unsupported_claims),
                [c.claim_text for c in grounding_result.unsupported_claims],
                len(static_result.chunks), static_result.band,
                len(web_result.chunks), web_result.band, domain, lang,
            )
            try:
                repaired = self._repair_unsupported_claims(
                    answer, grounding_result.unsupported_claims,
                )
                recheck = verify_answer_grounding(
                    repaired,
                    all_chunks,
                    use_llm_verification=self._settings.answer_grounding_llm_enabled,
                    settings=self._settings,
                )
            except Exception:
                logger.exception(
                    "Grounding re-verification crashed: static=%d web=%d domain=%s lang=%s — abstaining INSUFFICIENT_EVIDENCE",
                    len(static_result.chunks), len(web_result.chunks), domain, lang,
                )
                return self._abstain_response(
                    lang=lang,
                    reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                    domain=domain,
                    session_id=session_id,
                )
            if recheck.has_unsupported_claims:
                logger.warning(
                    "Grounding repair incomplete, %d claim(s) still unsupported: %s static=%d web=%d domain=%s lang=%s — abstaining INSUFFICIENT_EVIDENCE",
                    len(recheck.unsupported_claims),
                    [c.claim_text for c in recheck.unsupported_claims],
                    len(static_result.chunks), len(web_result.chunks), domain, lang,
                )
                return self._abstain_response(
                    lang=lang,
                    reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                    domain=domain,
                    session_id=session_id,
                )
            cleaned_repaired, _ = strip_citations(repaired)
            if cleaned_repaired.strip():
                answer = repaired
                logger.info(
                    "Grounding repair removed unsupported claim(s); retained supported sentences",
                )
            else:
                logger.warning(
                    "Grounding repair stripped all text; abstaining INSUFFICIENT_EVIDENCE",
                )
                return self._abstain_response(
                    lang=lang,
                    reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                    domain=domain,
                    session_id=session_id,
                )
            grounding_result = recheck
            grounding_repaired = True
        grounding_ms = (time.monotonic() - _t_grounding_start) * 1000

        if on_step:
            on_step({"id": "llm_generate", "label": "Response Generated", "detail": "Response generated", "status": "completed"})
            on_step({"id": "citation_verify", "label": "Verifying Citations", "detail": f"Verified {len(all_chunks)} citations against source documents", "status": "completed"})
        _t_citation_done = time.monotonic()

        # Step 10: Strip internal citation markers and fix formatting
        stripped_answer, _extracted_ids = strip_citations(answer)
        answer = clean_answer(stripped_answer)
        answer = fix_broken_tables(answer)

        # Step 11: Calculate confidence
        # Grounding repair caps the user-facing confidence: retrieval may be
        # HIGH but the final answer lost content, so it must not claim HIGH.
        # Answerability from the evidence assessment keeps retrieval confidence
        # from leaking into a high answer rating when evidence is insufficient.
        confidence, confidence_band = self._calculate_confidence(
            static_result, web_result, has_static, has_web,
            [],  # No claim verifications
            grounding_repaired=grounding_repaired,
            answerability=assessment.sufficiency if assessment else None,
        )
        # Facet coverage penalty: scale confidence by the fraction of
        # supported facets. Fully supported coverage leaves confidence
        # unchanged; fully unsupported halves it.
        if _facet_coverage:
            confidence = self._apply_facet_coverage_penalty(confidence, _facet_coverage)

        # Step 12: Build citations list
        # Include chunks actually cited in the answer
        citations = self._build_citations(
            all_chunks, cited_chunk_ids=set(_extracted_ids)
        )
        # Ensure that if verified web sources were retrieved, they are included in citations
        # so the user can see and inspect the web sources in the drawer
        if usable_web and not any(c.get("source") == "web" for c in citations):
            web_citations = self._build_citations(usable_web[:3], cited_chunk_ids=None)
            citations.extend(web_citations)
        if usable_static and not any(c.get("source") == "static" for c in citations):
            static_citations = self._build_citations(usable_static[:3], cited_chunk_ids=None)
            citations.extend(static_citations)

        # Step 13: Prepare speech text
        speech_text = prepare_speech_text(answer)
        speech_segments = segment_speech(answer, lang)

        # Step 14: Determine mode
        if has_static and has_web:
            mode = "dual_rag"
        elif has_static:
            mode = "static"
        else:
            mode = "web"

        # Generation latency instrumentation
        _t_gen_end = time.monotonic()
        groq_http_ms = (_t_groq_done - _t_groq_start) * 1000
        citation_validation_ms = (_t_citation_done - _t_groq_done) * 1000
        generation_total_ms = (_t_gen_end - _t_prompt_start) * 1000

        # Prompt token estimation (~4 chars per token)
        _input_chars = len(system_prompt) + len(user_prompt)
        _input_tokens_est = _input_chars // 4
        _output_tokens_est = len(answer) // 4

        logger.info(
            "Generation timing: prompt_build=%.0fms groq_http=%.0fms citation_val=%.0fms total=%.0fms | "
            "model=%s input_chars=%d input_tokens~%d output_tokens~%d llm_calls=1 | "
            "citations=%d abstained=False",
            prompt_build_ms, groq_http_ms, citation_validation_ms, generation_total_ms,
            model_name, _input_chars, _input_tokens_est, _output_tokens_est,
            len(citations),
        )
        logger.info(
            "RAG timing: static_retrieval_ms=%.0f web_total_ms=%.0f generation_ms=%.0f grounding_ms=%.0f",
            float(static_result.metadata.get("retrieval_ms", 0.0)),
            web_total_ms,
            generation_total_ms,
            grounding_ms,
        )

        logger.info(
            "RAGOrchestrator response: confidence=%.2f band=%s mode=%s citations=%d",
            confidence, confidence_band.value, mode, len(citations),
        )

        return RAGResponse(
            answer=answer,
            language=lang,
            domain=domain,
            confidence=confidence,
            confidence_level=confidence_band,
            citations=citations,
            abstained=False,
            speech_text=speech_text,
            speech_segments=speech_segments,
            follow_up_question=None,
            mode=mode,
            conversation_id=session_id,
        )

    async def _run_pipelines(
        self,
        english_query: str,
        embedding: list[float],
        domain: str,
        state: str | None,
        classification: QueryClassification | None,
        mode: str | None = None,
        as_of_date: str | None = None,
    ) -> tuple[RAGResult, RAGResult]:
        """Run static and/or web RAG pipelines based on mode.

        Modes:
          - "static": Static RAG only (no web search)
          - "web": Web RAG only (no static retrieval)
          - "rag_web" or None: Both pipelines in parallel (default)
        """
        abstain = RAGResult(
            chunks=[], abstained=True,
            reason=AbstentionReason.NO_ELIGIBLE_SOURCE, domain=domain,
        )

        # Static-only mode (V1)
        if mode == "static":
            started = time.monotonic()
            try:
                static_result = await asyncio.to_thread(
                    self._static_rag.retrieve,
                    embedding=embedding, query=english_query,
                    domain=domain, state=state,
                    as_of_date=as_of_date,
                )
            except Exception:
                logger.exception("Static RAG pipeline failed")
                static_result = RAGResult(
                    chunks=[], abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE, domain=domain,
                )
            static_result.metadata["retrieval_ms"] = (time.monotonic() - started) * 1000
            return static_result, abstain

        # Web-only mode (V2)
        if mode == "web":
            started = time.monotonic()
            # Cooperative deadline (see _web_with_timeout below): the sync
            # WebRAG worker cannot be preempted on timeout, so it gets the
            # absolute budget to stop starting new recovery rounds in time.
            deadline = started + self._settings.web_rag_timeout_s
            try:
                web_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._web_rag.retrieve,
                        query=english_query, domain=domain,
                        state=state, classification=classification,
                        as_of_date=as_of_date,
                        deadline=deadline,
                    ),
                    timeout=self._settings.web_rag_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("Web RAG timed out after %.1fs", self._settings.web_rag_timeout_s)
                web_result = RAGResult(
                    chunks=[], abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE, domain=domain,
                )
            except Exception:
                logger.exception("Web RAG pipeline failed")
                web_result = RAGResult(
                    chunks=[], abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE, domain=domain,
                )
            web_result.metadata["web_total_ms"] = (time.monotonic() - started) * 1000
            return abstain, web_result

        # Dual mode (V3) — both pipelines in parallel
        async def _static_with_timing() -> RAGResult:
            started = time.monotonic()
            result = await asyncio.to_thread(
                self._static_rag.retrieve,
                embedding=embedding, query=english_query,
                domain=domain, state=state,
                as_of_date=as_of_date,
            )
            result.metadata["retrieval_ms"] = (time.monotonic() - started) * 1000
            return result

        static_coro = _static_with_timing()

        # Keep Web RAG optional: static evidence must continue within a bounded budget.
        async def _web_with_timeout() -> RAGResult:
            started = time.monotonic()
            # Cooperative deadline for the sync WebRAG worker: cancelling
            # the asyncio task on timeout does NOT stop the to_thread
            # worker (it keeps running recovery rounds in the background
            # and its late result is discarded). Handing it the absolute
            # budget lets it stop STARTING new recovery rounds once the
            # caller has given up, instead of computing a phantom success.
            deadline = started + self._settings.web_rag_timeout_s
            web_coro = asyncio.to_thread(
                self._web_rag.retrieve,
                query=english_query, domain=domain,
                state=state, classification=classification,
                as_of_date=as_of_date,
                deadline=deadline,
            )
            try:
                web_task = asyncio.create_task(web_coro)
                try:
                    result = await asyncio.wait_for(web_task, timeout=self._settings.web_rag_timeout_s)
                    result.metadata["web_total_ms"] = (time.monotonic() - started) * 1000
                    return result
                except asyncio.TimeoutError:
                    web_task.cancel()
                    await asyncio.gather(web_task, return_exceptions=True)
                    raise
            except asyncio.TimeoutError:
                logger.warning(
                    "Web RAG timed out after %.1fs — using static only",
                    self._settings.web_rag_timeout_s,
                )
                result = RAGResult(
                    chunks=[],
                    abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                    domain=domain,
                )
                result.metadata["web_total_ms"] = (time.monotonic() - started) * 1000
                return result

        results = await asyncio.gather(static_coro, _web_with_timeout(), return_exceptions=True)

        static_result: RAGResult
        web_result: RAGResult

        if isinstance(results[0], Exception):
            logger.exception("Static RAG pipeline failed: %s", results[0])
            static_result = RAGResult(
                chunks=[],
                abstained=True,
                reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                domain=domain,
            )
        else:
            static_result = results[0]

        if isinstance(results[1], Exception):
            logger.exception("Web RAG pipeline failed: %s", results[1])
            web_result = RAGResult(
                chunks=[],
                abstained=True,
                reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                domain=domain,
            )
        else:
            web_result = results[1]

        return static_result, web_result

    async def _run_facet_pipelines(
        self,
        facets: list[Facet],
        embedding: list[float],
        classification: QueryClassification | None,
        mode: str | None = None,
        as_of_date: str | None = None,
    ) -> tuple[RAGResult, RAGResult, list[EvidenceChunk], dict]:
        """Run per-facet static (+ bounded web) retrieval with coverage selection.

        Each facet calls the existing ``StaticRAGService.retrieve``
        sequentially (``k=10``). At most 2 facets with no usable static
        evidence get a web call, all sharing one outer deadline
        (``started + web_rag_timeout_s``). Per-facet failures yield empty
        chunk lists (unsupported facet), never a pipeline-wide exception.
        Only gate-passing (non-abstained) facet results contribute usable
        chunks, mirroring the single-path ``usable_*`` semantics. No new
        executors; sync services run via ``asyncio.to_thread`` like the
        legacy path.
        """
        from app.providers.embeddings import get_embedding_provider

        started = time.monotonic()
        facet_deadline = started + self._settings.web_rag_timeout_s

        # Facet query embeddings, cached per distinct facet query (max 3
        # calls). Falls back to the original query embedding on failure so
        # a transient embedding error does not orphan the facet.
        _emb_cache: dict[str, list[float]] = {}

        def _facet_embedding(facet_query: str) -> list[float]:
            if facet_query not in _emb_cache:
                try:
                    vecs = get_embedding_provider().embed_texts([facet_query])
                    _emb_cache[facet_query] = list(vecs[0])
                except Exception:
                    logger.exception("Facet embedding failed; reusing query embedding")
                    _emb_cache[facet_query] = list(embedding)
            return _emb_cache[facet_query]

        per_facet_usable_static: dict[str, list[EvidenceChunk]] = {}
        per_facet_usable_web: dict[str, list[EvidenceChunk]] = {}
        # Cache per identical (domain, query, state): overlapping facet
        # slices otherwise run duplicate static retrievals.
        _static_cache: dict[tuple, list[EvidenceChunk]] = {}
        static_usable: list[EvidenceChunk] = []
        web_usable: list[EvidenceChunk] = []
        static_bands: list[ConfidenceBand] = []
        web_bands: list[ConfidenceBand] = []
        static_reason: AbstentionReason | None = None
        web_reason: AbstentionReason | None = None

        for facet in facets:
            fid = facet.facet_id
            if mode == "web":
                per_facet_usable_static[fid] = []
                continue
            # Skip retrieval when an identical (domain, query, state) facet
            # already ran: overlapping facet slices otherwise double the
            # static calls and feed duplicate chunks into coverage.
            _dup_key = (facet.domain, facet.query, facet.state)
            if _dup_key in _static_cache:
                _dup = _static_cache[_dup_key]
                per_facet_usable_static[fid] = list(_dup)
                static_usable.extend(_dup)
                if _dup:
                    static_bands.append(ConfidenceBand.HIGH)
                continue
            try:
                res = await asyncio.to_thread(
                    self._static_rag.retrieve,
                    embedding=_facet_embedding(facet.query),
                    query=facet.query,
                    domain=facet.domain,
                    state=facet.state,
                    k=10,
                    as_of_date=as_of_date,
                )
            except Exception:
                logger.exception("Facet static retrieval failed: facet=%s", fid)
                res = RAGResult(
                    chunks=[], abstained=True,
                    reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                    domain=facet.domain,
                )
            usable = list(res.chunks) if not res.abstained else []
            _static_cache[_dup_key] = usable
            per_facet_usable_static[fid] = usable
            static_usable.extend(usable)
            if usable and res.band is not None:
                static_bands.append(res.band)
            if static_reason is None and res.reason is not None:
                static_reason = res.reason

        if mode != "static":
            needing_web = [f for f in facets if not per_facet_usable_static.get(f.facet_id)]
            if len(needing_web) < 2:
                for f in facets:
                    if f not in needing_web:
                        needing_web.append(f)
                    if len(needing_web) >= 2:
                        break
            for facet in needing_web:
                fid = facet.facet_id
                remaining = facet_deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning(
                        "Facet web budget exhausted; facet=%s left unsupported", fid,
                    )
                    per_facet_usable_web[fid] = []
                    continue
                try:
                    wres = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._web_rag.retrieve,
                            query=facet.query,
                            domain=facet.domain,
                            state=facet.state,
                            classification=classification,
                            as_of_date=as_of_date,
                            deadline=facet_deadline,
                        ),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Facet web timed out: facet=%s", fid)
                    wres = RAGResult(
                        chunks=[], abstained=True,
                        reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                        domain=facet.domain,
                    )
                except Exception:
                    logger.exception("Facet web retrieval failed: facet=%s", fid)
                    wres = RAGResult(
                        chunks=[], abstained=True,
                        reason=AbstentionReason.PROVIDER_UNAVAILABLE,
                        domain=facet.domain,
                    )
                usable = list(wres.chunks) if not wres.abstained else []
                per_facet_usable_web[fid] = usable
                web_usable.extend(usable)
                if usable and wres.band is not None:
                    web_bands.append(wres.band)
                if web_reason is None and wres.reason is not None:
                    web_reason = wres.reason
        for facet in facets:
            per_facet_usable_web.setdefault(facet.facet_id, [])

        facet_chunks = {
            f.facet_id: per_facet_usable_static.get(f.facet_id, [])
            + per_facet_usable_web.get(f.facet_id, [])
            for f in facets
        }
        merged, coverage = select_coverage(facet_chunks)

        static_result = RAGResult(
            chunks=static_usable,
            abstained=len(static_usable) == 0,
            reason=None if static_usable else (static_reason or AbstentionReason.NO_ELIGIBLE_SOURCE),
            band=self._best_band(static_bands),
            domain=facets[0].domain if facets else "",
        )
        static_result.metadata["retrieval_ms"] = (time.monotonic() - started) * 1000
        web_result = RAGResult(
            chunks=web_usable,
            abstained=len(web_usable) == 0,
            reason=None if web_usable else (web_reason or AbstentionReason.NO_ELIGIBLE_SOURCE),
            band=self._best_band(web_bands),
            domain=facets[0].domain if facets else "",
        )
        web_result.metadata["web_total_ms"] = (time.monotonic() - started) * 1000
        web_result.metadata["facet_coverage"] = coverage
        # I1: keep per-facet groups for prompt wiring (citations keep merged).
        web_result.metadata["facet_groups"] = facet_chunks
        return static_result, web_result, merged, coverage

    @staticmethod
    def _best_band(bands: list[ConfidenceBand]) -> ConfidenceBand | None:
        """Return the highest confidence band, or None when empty."""
        order = {"low": 0, "medium": 1, "high": 2}
        best: ConfidenceBand | None = None
        for b in bands:
            if b is None:
                continue
            if best is None or order.get(getattr(b, "value", ""), -1) > order.get(
                getattr(best, "value", ""), -1
            ):
                best = b
        return best

    @staticmethod
    def _apply_facet_coverage_penalty(confidence: float, coverage: dict) -> float:
        """Scale confidence by the fraction of supported facets.

        ``confidence * (0.5 + 0.5 * supported / total)``, rounded to 2
        decimals. Fully supported coverage is a no-op; fully unsupported
        halves the confidence.
        """
        total = len(coverage)
        if total == 0:
            return confidence
        supported = sum(
            1 for v in coverage.values()
            if isinstance(v, dict) and v.get("status") == "supported"
        )
        return round(confidence * (0.5 + 0.5 * supported / total), 2)

    def _merge_evidence(
        self,
        static_chunks: list[EvidenceChunk],
        web_chunks: list[EvidenceChunk],
    ) -> list[EvidenceChunk]:
        """Merge evidence from both pipelines with cross-source ranking.

        Static chunks (official documents) get an authority boost.
        Weak web results cannot displace stronger static evidence.
        Deduplicates by chunk_id.

        Cap is top 6 static + top 6 web = max 12: retrieval fetches
        25 static + 8 web for recall, but only the best per-source
        chunks become citable downstream. Per-source caps also avoid
        cross-scale sorting (static cosine 0-1 vs web rerank 0-100)
        letting one source dominate the merged list.
        """
        AUTHORITY_BOOST_STATIC = 0.05
        MAX_PER_SOURCE = 6
        MAX_MERGED = 12

        # Per-source top-N (retrieval order is already ranked).
        top_static = list(static_chunks[:MAX_PER_SOURCE])
        top_web = list(web_chunks[:MAX_PER_SOURCE])

        # Deduplicate by chunk_id, keeping the best score
        seen: dict[str, EvidenceChunk] = {}
        for chunk in top_static:
            scored = (chunk.dense_score or 0) + AUTHORITY_BOOST_STATIC
            existing = seen.get(chunk.chunk_id)
            if not existing or scored > ((existing.dense_score or 0) + AUTHORITY_BOOST_STATIC):
                seen[chunk.chunk_id] = chunk
        for chunk in top_web:
            existing = seen.get(chunk.chunk_id)
            if not existing or (chunk.dense_score or 0) > (existing.dense_score or 0):
                seen[chunk.chunk_id] = chunk

        # Sort by effective score descending
        merged = sorted(
            seen.values(),
            key=lambda c: -(c.dense_score or 0),
        )[:MAX_MERGED]

        logger.info(
            "Merged evidence: %d static + %d web = %d total (after dedup+rank, capped to %d)",
            len(static_chunks), len(web_chunks), len(merged), MAX_MERGED,
        )
        return merged

    def _auto_append_citations(
        self,
        answer: str,
        chunks: list[EvidenceChunk],
        force: bool = False,
    ) -> str:
        """Auto-append citation markers if omitted, and clean non-citation bracket markers."""
        # Clean loose non-citation brackets like [1], [Note], [Source]
        answer = re.sub(r"\[(?!\s*chunk:)(?!\s*web_)[A-Za-z0-9\s]+\]", "", answer)

        has_citation = bool(re.search(r"\[chunk:", answer))
        has_web_citation = bool(re.search(r"\[chunk:web_", answer))
        web_chunks = [c for c in chunks if getattr(c, "source_type", "") == "web" or c.chunk_id.startswith("web_")]

        if not has_citation or force:
            seen: set[str] = set()
            citation_parts: list[str] = []
            for chunk in chunks[:3]:
                metadata = chunk.metadata or {}
                if metadata.get("lead_only"):
                    continue
                impersonation = metadata.get("impersonation")
                if isinstance(impersonation, dict) and impersonation.get(
                    "suspicious"
                ):
                    continue
                short_id = short_citation_id(chunk.chunk_id)
                if short_id not in seen:
                    seen.add(short_id)
                    citation_parts.append(f"[chunk:{short_id}]")

            # Also ensure web citations if web chunks exist
            if web_chunks and not any(cid.startswith("web_") for cid in seen):
                for wc in web_chunks[:2]:
                    wid = short_citation_id(wc.chunk_id)
                    if wid not in seen:
                        seen.add(wid)
                        citation_parts.append(f"[chunk:{wid}]")

            if citation_parts:
                answer = answer.rstrip() + " " + " ".join(citation_parts)
            return answer

        # When answer has static citations but lacks web citations while web chunks exist,
        # attach top web chunk citation so web sources are included in the sources drawer.
        if web_chunks and not has_web_citation:
            web_parts: list[str] = []
            for wc in web_chunks[:2]:
                metadata = wc.metadata or {}
                if metadata.get("lead_only"):
                    continue
                impersonation = wc.metadata.get("impersonation") if wc.metadata else None
                if isinstance(impersonation, dict) and impersonation.get("suspicious"):
                    continue
                wid = short_citation_id(wc.chunk_id)
                web_parts.append(f"[chunk:{wid}]")
            if web_parts:
                answer = answer.rstrip() + " " + " ".join(web_parts)

        static_chunks = [c for c in chunks if getattr(c, "source_type", "") == "static" or not c.chunk_id.startswith("web_")]
        has_static_citation = bool(re.search(r"\[chunk:(?!web_)", answer))
        if static_chunks and not has_static_citation:
            static_parts: list[str] = []
            for sc in static_chunks[:2]:
                metadata = sc.metadata or {}
                if metadata.get("lead_only"):
                    continue
                impersonation = sc.metadata.get("impersonation") if sc.metadata else None
                if isinstance(impersonation, dict) and impersonation.get("suspicious"):
                    continue
                sid = short_citation_id(sc.chunk_id)
                static_parts.append(f"[chunk:{sid}]")
            if static_parts:
                answer = answer.rstrip() + " " + " ".join(static_parts)

        return answer

    @staticmethod
    def _repair_unsupported_claims(answer: str, unsupported_claims: list) -> str:
        """Deterministically remove sentences containing unsupported claims.

        Reuses the pre-existing sentence-removal repair (no LLM call).
        Operates on the actual extracted claims, not arbitrary words.
        No ``\\b`` word-boundary anchors: claims such as ``12%`` or
        ``Rs.750`` end in non-word characters, where ``\\b`` never matches
        and the sentence silently survived repair.

        Matches sentences terminated by ``.``, ``!``, or ``?``, and also
        handles the final sentence when it has no trailing punctuation.
        """
        for claim in unsupported_claims:
            claim_text = getattr(claim, "claim_text", str(claim))
            if not claim_text.strip():
                continue
            escaped = re.escape(claim_text)
            # Remove sentence ending with ., !, or ?
            answer = re.sub(
                rf"[^.!?]*{escaped}[^.!?]*[.!?]",
                "",
                answer,
            )
            # Remove final sentence without trailing punctuation (if the
            # claim is in the last sentence and there is no terminator).
            answer = re.sub(
                rf"[^.!?]*{escaped}[^.!?]*$",
                "",
                answer,
            )
        # Clean up extra spaces and trailing punctuation artifacts
        answer = re.sub(r"  +", " ", answer).strip()
        answer = re.sub(r"[.!?]+$\s*", "", answer).strip()
        return answer

    def _build_citations(
        self,
        chunks: list[EvidenceChunk],
        cited_chunk_ids: set[str] | None = None,
    ) -> list[dict]:
        """Build the citations list for the API response.

        P1-1/P1-6: chunks tagged ``lead_only`` (secondary leads) or
        quarantined by impersonation screening are never authoritative
        evidence and are excluded here. Everything else is unchanged.

        When ``cited_chunk_ids`` is provided, only chunks whose chunk_id
        appears in that set are included — the response shows sources that
        were actually cited in the answer, not every retrieved chunk.
        When ``cited_chunk_ids`` is None (legacy path), all eligible
        chunks are included for backward compatibility.
        """
        citations: list[dict] = []
        seen: set[str] = set()

        for chunk in chunks:
            metadata = chunk.metadata or {}

            if metadata.get("lead_only"):
                continue

            impersonation = metadata.get("impersonation")
            if isinstance(impersonation, dict) and impersonation.get(
                "suspicious"
            ):
                continue

            # When cited_chunk_ids is provided, only include chunks that were
            # actually cited in the answer — not every retrieved chunk.
            if cited_chunk_ids is not None:
                short_id = short_citation_id(chunk.chunk_id)
                if short_id not in cited_chunk_ids:
                    continue
            else:
                short_id = short_citation_id(chunk.chunk_id)

            if short_id in seen:
                continue
            seen.add(short_id)

            citation: dict[str, Any] = {
                "chunk_id": short_id,
                "title": chunk.title,
                "source": chunk.source_type,
                "source_label": "Official Document" if chunk.source_type == "static" else "Web Source",
                "url": chunk.url,
                "content": chunk.content,
            }
            if chunk.page is not None:
                citation["page"] = chunk.page
            if chunk.section:
                citation["section"] = chunk.section
            source_file = chunk.metadata.get("source_file", "") if chunk.metadata else ""
            if source_file:
                citation["source_file"] = source_file

            citations.append(citation)

        return citations

    def _calculate_confidence(
        self,
        static_result: RAGResult,
        web_result: RAGResult,
        has_static: bool,
        has_web: bool,
        claim_verifications: list | None = None,
        grounding_repaired: bool = False,
        answerability: EvidenceSufficiency | None = None,
    ) -> tuple[float, ConfidenceBand]:
        """Compute claim-level confidence score and band from evidence.

        Combines retrieval confidence (from evidence gate bands) with
        answerability (from EvidenceController assessment) so that a
        high retrieval score alone cannot produce a high answer confidence.

        Retrieval confidence and answerability are tracked separately:
        - retrieval_conf/conflict_band: how well the chunks scored
        - answerability: whether the assessment says evidence can answer

        When answerability is INSUFFICIENT or EMPTY, the answer confidence
        is capped below HIGH regardless of retrieval band — an answer that
        explicitly disclaims evidence cannot claim HIGH.

        grounding_repaired caps a repaired-but-supportable answer at MEDIUM:
        retrieval may be HIGH, but the final answer lost unsupported content,
        so the user-facing confidence must not claim HIGH. MEDIUM/LOW pass
        through unchanged (never upgraded).
        """
        # Static confidence from evidence gate band
        static_band = static_result.band
        static_conf = _BAND_TO_CONFIDENCE.get(
            getattr(static_band, "value", ""), 0.4
        )

        # Web confidence from evidence gate band
        web_band = web_result.band
        web_conf = _BAND_TO_CONFIDENCE.get(
            getattr(web_band, "value", ""), 0.4
        )

        if has_static and has_web:
            # Dual-source: average with a small boost
            base = (static_conf + web_conf) / 2.0
            confidence = min(base + 0.10, 1.0)
        elif has_static:
            confidence = static_conf
        elif has_web:
            confidence = web_conf
        else:
            confidence = 0.0

        # Answerability cap: when the evidence assessment says evidence is
        # insufficient or empty, the answer confidence must not reach HIGH
        # regardless of retrieval band. This prevents a high retrieval score
        # from masking an answer that itself disclaims evidence.
        if answerability is not None and answerability in (
            EvidenceSufficiency.INSUFFICIENT,
            EvidenceSufficiency.EMPTY,
        ):
            # Cap at MEDIUM boundary (below 0.7 HIGH threshold).
            # Fully unsupported evidence cannot support a HIGH answer.
            if confidence > 0.6:
                confidence = 0.6
            if band == ConfidenceBand.HIGH:
                band = ConfidenceBand.MEDIUM

        # Adjust confidence based on claim verification results
        if claim_verifications is not None and len(claim_verifications) > 0:
            unsupported = sum(1 for v in claim_verifications if not v.is_supported)
            total_verified = len(claim_verifications)
            if total_verified > 0:
                # Each unsupported claim reduces confidence by a factor
                unsupported_ratio = unsupported / total_verified
                penalty = unsupported_ratio * 0.3  # up to 30% penalty
                confidence = max(confidence - penalty, 0.0)

        # Map to band
        if confidence >= 0.7:
            band = ConfidenceBand.HIGH
        elif confidence >= 0.5:
            band = ConfidenceBand.MEDIUM
        else:
            band = ConfidenceBand.LOW

        # Grounding repair invariant: a repaired answer must not retain HIGH.
        # Cap at 0.6 / MEDIUM (below the 0.7 HIGH threshold); leave
        # MEDIUM/LOW untouched so no upgrade can occur.
        if grounding_repaired and band == ConfidenceBand.HIGH:
            confidence = min(confidence, 0.6)
            band = ConfidenceBand.MEDIUM

        return round(confidence, 2), band

    def _abstain_response(
        self,
        lang: str,
        reason: AbstentionReason,
        domain: str,
        session_id: str,
        referral: dict | None = None,
    ) -> RAGResponse:
        """Build a standardized fallback response."""
        answer = get_abstain_text(lang)
        return RAGResponse(
            answer=answer,
            language=lang,
            domain=domain,
            confidence=0.0,
            confidence_level=ConfidenceBand.LOW,
            citations=[],
            abstained=True,
            speech_text=prepare_speech_text(answer),
            speech_segments=[],
            follow_up_question=None,
            mode="dual_rag",
            conversation_id=session_id,
            referral=referral,
        )

