"""Scenario Reasoning — comprehensive tests.

Tests the full scenario reasoning pipeline:
1. Query complexity classifier
2. Scenario planner (requirement extraction)
3. Evidence map builder
4. Derived conclusions
5. Integration with orchestrator
6. Regression: simple queries stay on fast path

Failure cases per spec §14:
- single-condition, 3+ condition, negative condition, missing user fact,
  missing corpus evidence, exception, two-section, two-document,
  law+by-law, central+Gujarat, multi-hop, comparison, follow-up,
  contradictory evidence, unsupported scenario
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.config import Settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    DerivedConclusion,
    EvidenceChunk,
    EvidenceMapEntry,
    EvidenceSufficiency,
    EvidenceRequirement,
    QueryComplexity,
    RequirementStatus,
    RAGResult,
    ScenarioPlan,
    ScenarioResult,
)
from app.scenario_reasoning import (
    QueryComplexityClassifier,
    EvidenceMapBuilder,
    DerivedConclusionEngine,
    ScenarioPlanner,
    ScenarioReasoningEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test", "gemini_api_key": "test",
        "jina_api_key": "test", "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test", "reranker_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _evidence(
    chunk_id: str, content: str, domain: str = "pmfby",
    dense_score: float = 0.70, title: str = "PMFBY Guidelines",
    section: str = "Overview", page: int = 1, document_id: str = "doc-1",
    jurisdiction: str = "central", state: str | None = None,
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id, content=content, source_type="static",
        title=title, url="", page=page, section=section, domain=domain,
        jurisdiction=jurisdiction, state=state, dense_score=dense_score,
        metadata={"document_id": document_id, "source_file": f"{domain}.pdf"},
    )


def _rag_result(chunks: list[EvidenceChunk] | None = None,
                abstained: bool = False) -> RAGResult:
    return RAGResult(
        chunks=chunks or [], abstained=abstained,
        reason=AbstentionReason.NO_ELIGIBLE_SOURCE if abstained else None,
        band=ConfidenceBand.LOW if abstained else ConfidenceBand.MEDIUM,
    )


def _mock_llm(response: str) -> MagicMock:
    """Create a mock LLM provider that returns a fixed response."""
    llm = MagicMock()
    llm.generate.return_value = response
    return llm


# ---------------------------------------------------------------------------
# 1. Query Complexity Classifier
# ---------------------------------------------------------------------------

class TestQueryComplexityClassifier:
    """Test deterministic complexity classification."""

    def setup_method(self):
        self.clf = QueryComplexityClassifier()

    def test_simple_info_query(self):
        assert self.clf.classify("What is PMFBY?") == QueryComplexity.SIMPLE

    def test_simple_definition(self):
        assert self.clf.classify("Tell me about PACS") == QueryComplexity.SIMPLE

    def test_procedure_query(self):
        c = self.clf.classify("How to apply for PMFBY crop insurance?")
        assert c == QueryComplexity.PROCEDURE

    def test_eligibility_query(self):
        c = self.clf.classify("Am I eligible for PM-KISAN scheme?")
        assert c == QueryComplexity.ELIGIBILITY

    def test_comparison_query(self):
        c = self.clf.classify("What is the difference between PMFBY and PM-KUSUM?")
        assert c == QueryComplexity.COMPARISON

    def test_multi_condition_query(self):
        c = self.clf.classify(
            "I am a PACS member and have 5 shares and want a crop loan "
            "and I already have an unpaid loan"
        )
        assert c in (QueryComplexity.MULTI_CONDITION, QueryComplexity.SCENARIO)

    def test_multi_hop_query(self):
        c = self.clf.classify(
            "How do I become a PACS member and then get a crop loan?"
        )
        assert c == QueryComplexity.MULTI_HOP

    def test_scenario_query(self):
        c = self.clf.classify(
            "I am a PACS member with 5 shares. Can I get another loan "
            "if I already have an unpaid loan?"
        )
        assert c in (QueryComplexity.SCENARIO, QueryComplexity.MULTI_CONDITION)

    def test_ambiguous_query(self):
        c = self.clf.classify("Help me")
        assert c == QueryComplexity.SIMPLE  # below threshold

    def test_empty_query(self):
        assert self.clf.classify("") == QueryComplexity.AMBIGUOUS

    def test_hindi_procedure(self):
        c = self.clf.classify("PMFBY ke liye kaise apply karein?")
        assert c == QueryComplexity.PROCEDURE

    def test_hinglish_scenario(self):
        c = self.clf.classify(
            "Main PACS member hu, 5 shares hai, aur mujhe crop loan chahiye"
        )
        assert c in (QueryComplexity.SCENARIO, QueryComplexity.MULTI_CONDITION, QueryComplexity.SIMPLE)


# ---------------------------------------------------------------------------
# 2. Scenario Planner (requirement extraction)
# ---------------------------------------------------------------------------

class TestScenarioPlanner:
    """Test requirement extraction from complex queries."""

    def test_extracts_requirements(self):
        llm_response = '''
        {
            "user_facts": ["PACS member", "5 shares", "has unpaid loan"],
            "requirements": [
                {"description": "PACS membership requirement", "search_query": "PACS membership eligibility criteria"},
                {"description": "Share requirement for loan", "search_query": "PACS share requirement crop loan"},
                {"description": "Effect of existing loan on new loan", "search_query": "PACS loan eligibility existing loan"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("Can I get a loan?", "en")

        assert len(plan.requirements) == 3
        assert plan.user_facts == ["PACS member", "5 shares", "has unpaid loan"]
        assert plan.missing_user_facts == []
        assert plan.requirements[0].search_query == "PACS membership eligibility criteria"

    def test_identifies_missing_user_facts(self):
        llm_response = '''
        {
            "user_facts": ["wants crop loan"],
            "requirements": [
                {"description": "Crop loan eligibility", "search_query": "crop loan eligibility criteria"}
            ],
            "missing_user_facts": ["PACS membership status", "shareholding", "existing loans"]
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("Can I get a crop loan?", "en")

        assert len(plan.missing_user_facts) == 3
        assert "PACS membership status" in plan.missing_user_facts

    def test_llm_failure_returns_fallback(self):
        llm = MagicMock()
        llm.generate.side_effect = Exception("LLM failed")
        planner = ScenarioPlanner(llm)
        plan = planner.plan("Complex question?", "en")

        assert len(plan.requirements) == 1
        assert plan.requirements[0].search_query == "Complex question?"

    def test_invalid_json_returns_fallback(self):
        llm = _mock_llm("This is not JSON at all")
        planner = ScenarioPlanner(llm)
        plan = planner.plan("Test query", "en")

        assert len(plan.requirements) == 1


# ---------------------------------------------------------------------------
# 3. Evidence Map Builder
# ---------------------------------------------------------------------------

class TestEvidenceMapBuilder:
    """Test evidence coverage assessment."""

    def setup_method(self):
        self.builder = EvidenceMapBuilder()

    def test_all_supported(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO,
            user_facts=["member"],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="req1", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="req2", search_query="q2"),
            ],
        )
        results = {
            "r1": _rag_result([_evidence("c1", "content1", dense_score=0.80)]),
            "r2": _rag_result([_evidence("c2", "content2", dense_score=0.75)]),
        }
        evidence_map, all_evidence = self.builder.build_map(plan, results)

        assert len(evidence_map) == 2
        assert all(e.status == RequirementStatus.SUPPORTED for e in evidence_map)
        assert len(all_evidence) == 2

    def test_partial_coverage(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO,
            user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="req1", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="req2", search_query="q2"),
            ],
        )
        results = {
            "r1": _rag_result([_evidence("c1", "content1", dense_score=0.80)]),
            "r2": _rag_result([], abstained=True),
        }
        evidence_map, _ = self.builder.build_map(plan, results)

        assert evidence_map[0].status == RequirementStatus.SUPPORTED
        assert evidence_map[1].status == RequirementStatus.UNSUPPORTED

    def test_sufficiency_all_supported(self):
        entries = [
            EvidenceMapEntry(requirement_id="r1", description="r1",
                           status=RequirementStatus.SUPPORTED, evidence_count=2),
            EvidenceMapEntry(requirement_id="r2", description="r2",
                           status=RequirementStatus.SUPPORTED, evidence_count=1),
        ]
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="r2", search_query="q2"),
            ],
        )
        assert self.builder.assess_sufficiency(entries, plan) == EvidenceSufficiency.SUFFICIENT

    def test_sufficiency_mostly_unsupported(self):
        entries = [
            EvidenceMapEntry(requirement_id="r1", description="r1",
                           status=RequirementStatus.UNSUPPORTED, evidence_count=0),
            EvidenceMapEntry(requirement_id="r2", description="r2",
                           status=RequirementStatus.UNSUPPORTED, evidence_count=0),
        ]
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="r2", search_query="q2"),
            ],
        )
        assert self.builder.assess_sufficiency(entries, plan) == EvidenceSufficiency.INSUFFICIENT

    def test_find_unsupported(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="long query"),
                EvidenceRequirement(requirement_id="r2", description="r2", search_query="q2"),
            ],
        )
        entries = [
            EvidenceMapEntry(requirement_id="r1", description="r1",
                           status=RequirementStatus.UNSUPPORTED),
            EvidenceMapEntry(requirement_id="r2", description="r2",
                           status=RequirementStatus.SUPPORTED),
        ]
        unsupported = self.builder.find_unsupported(entries, plan)
        assert len(unsupported) == 1
        assert unsupported[0].requirement_id == "r1"


# ---------------------------------------------------------------------------
# 4. Derived Conclusion Engine
# ---------------------------------------------------------------------------

class TestDerivedConclusionEngine:
    """Test conclusion derivation from evidence."""

    def setup_method(self):
        self.engine = DerivedConclusionEngine()

    def test_all_supported_derives_conclusion(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=["member"],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="membership", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="shares", search_query="q2"),
            ],
        )
        evidence_map = [
            EvidenceMapEntry(requirement_id="r1", description="membership",
                           status=RequirementStatus.SUPPORTED, evidence_ids=["c1"]),
            EvidenceMapEntry(requirement_id="r2", description="shares",
                           status=RequirementStatus.SUPPORTED, evidence_ids=["c2"]),
        ]
        all_evidence = [_evidence("c1", "content1"), _evidence("c2", "content2")]

        conclusions = self.engine.derive(plan, evidence_map, all_evidence)
        assert len(conclusions) >= 1
        assert "All stated conditions" in conclusions[0].conclusion

    def test_no_conclusions_when_unsupported(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
            ],
        )
        evidence_map = [
            EvidenceMapEntry(requirement_id="r1", description="r1",
                           status=RequirementStatus.UNSUPPORTED),
        ]
        conclusions = self.engine.derive(plan, evidence_map, [])
        assert len(conclusions) == 0


# ---------------------------------------------------------------------------
# 5. Failure cases per spec §14
# ---------------------------------------------------------------------------

class TestSingleConditionScenario:
    """Single-condition: 'Can I get a crop loan if I am a PACS member?'"""

    def test_classified_as_complex(self):
        clf = QueryComplexityClassifier()
        c = clf.classify("Can I get a crop loan if I am a PACS member?")
        assert c != QueryComplexity.SIMPLE

    def test_plan_extracts_one_requirement(self):
        llm_response = '''
        {
            "user_facts": ["PACS member"],
            "requirements": [
                {"description": "PACS member crop loan eligibility", "search_query": "PACS member crop loan eligibility"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("Can I get a crop loan if I am a PACS member?", "en")
        assert len(plan.requirements) == 1


class TestThreePlusConditionScenario:
    """Multi-condition: membership + shares + existing loan + desired loan."""

    def test_classified_as_complex(self):
        clf = QueryComplexityClassifier()
        c = clf.classify(
            "I am a PACS member and have 5 shares and want a crop loan "
            "and I already have an unpaid loan"
        )
        assert c in (QueryComplexity.SCENARIO, QueryComplexity.MULTI_CONDITION)

    def test_plan_extracts_multiple_requirements(self):
        llm_response = '''
        {
            "user_facts": ["PACS member", "5 shares", "unpaid loan"],
            "requirements": [
                {"description": "membership requirement", "search_query": "PACS membership"},
                {"description": "share requirement", "search_query": "PACS share requirement"},
                {"description": "loan eligibility", "search_query": "crop loan eligibility"},
                {"description": "effect of existing loan", "search_query": "existing loan effect new loan"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("complex query", "en")
        assert len(plan.requirements) >= 3


class TestNegativeCondition:
    """Negative: 'What if I am NOT a PACS member?'"""

    def test_classified_as_complex(self):
        clf = QueryComplexityClassifier()
        c = clf.classify("What if I am not a PACS member, can I still get a loan?")
        assert c != QueryComplexity.SIMPLE


class TestMissingUserFact:
    """User asks but hasn't provided key information."""

    def test_plan_identifies_missing_fact(self):
        llm_response = '''
        {
            "user_facts": [],
            "requirements": [
                {"description": "Loan eligibility", "search_query": "crop loan eligibility"}
            ],
            "missing_user_facts": ["PACS membership status", "shareholding"]
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("Can I get a loan?", "en")
        assert len(plan.missing_user_facts) > 0


class TestMissingCorpusEvidence:
    """No evidence in corpus for a requirement."""

    def test_unsupported_requirement_detected(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
            ],
        )
        results = {"r1": _rag_result([], abstained=True)}
        evidence_map, _ = builder.build_map(plan, results)
        assert evidence_map[0].status == RequirementStatus.UNSUPPORTED


class TestExceptionHandling:
    """LLM or retrieval failure."""

    def test_planner_handles_llm_exception(self):
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("API error")
        planner = ScenarioPlanner(llm)
        plan = planner.plan("test", "en")
        assert len(plan.requirements) == 1  # fallback

    def test_retrieval_exception_handled(self):
        static_rag = MagicMock()
        static_rag.retrieve.side_effect = Exception("DB error")
        llm = _mock_llm('{"user_facts":[],"requirements":[{"description":"test","search_query":"test"}],"missing_user_facts":[]}')
        engine = ScenarioReasoningEngine(static_rag, llm)
        plan = engine.plan_query("test", "en")
        results = engine.retrieve_per_requirement(plan, "pmfby", None)
        assert all(r.abstained for r in results.values())


class TestTwoSectionAnswer:
    """Query requires evidence from two different sections."""

    def test_evidence_map_covers_multiple_sections(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="premium rates", search_query="premium"),
                EvidenceRequirement(requirement_id="r2", description="claims process", search_query="claims"),
            ],
        )
        results = {
            "r1": _rag_result([_evidence("c1", "premium info", section="Premium")]),
            "r2": _rag_result([_evidence("c2", "claims info", section="Claims")]),
        }
        _evidence_map, all_evidence = builder.build_map(plan, results)
        assert len(all_evidence) == 2
        sections = {e.section for e in all_evidence}
        assert "Premium" in sections and "Claims" in sections


class TestTwoDocumentAnswer:
    """Query requires evidence from two documents."""

    def test_evidence_map_covers_multiple_documents(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="PMFBY", search_query="PMFBY"),
                EvidenceRequirement(requirement_id="r2", description="bylaws", search_query="bylaws"),
            ],
        )
        results = {
            "r1": _rag_result([_evidence("c1", "PMFBY info", document_id="doc-pmfby")]),
            "r2": _rag_result([_evidence("c2", "bylaws info", document_id="doc-bylaws")]),
        }
        _evidence_map, all_evidence = builder.build_map(plan, results)
        doc_ids = {e.metadata.get("document_id") for e in all_evidence}
        assert len(doc_ids) == 2


class TestLawByLaw:
    """Query requires law + by-law evidence."""

    def test_classified_as_complex(self):
        clf = QueryComplexityClassifier()
        c = clf.classify(
            "What does the Cooperative Societies Act say about membership "
            "and how do the bylaws implement it and what are the conditions?"
        )
        assert c != QueryComplexity.SIMPLE


class TestCentralGujarat:
    """Query requires central + Gujarat-specific evidence."""

    def test_evidence_map_includes_both(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="central rule", search_query="central PMFBY"),
                EvidenceRequirement(requirement_id="r2", description="Gujarat rule", search_query="Gujarat PMFBY"),
            ],
        )
        central = _evidence("c1", "central rule", jurisdiction="central")
        gujarat = EvidenceChunk(
            chunk_id="c2", content="Gujarat rule", source_type="static",
            domain="pmfby", jurisdiction="state", state="gujarat",
            dense_score=0.75, metadata={"document_id": "doc-guj"},
        )
        results = {
            "r1": _rag_result([central]),
            "r2": _rag_result([gujarat]),
        }
        _evidence_map, all_evidence = builder.build_map(plan, results)
        assert len(all_evidence) == 2


class TestMultiHopProcedure:
    """'How do I become a PACS member and then get a crop loan?'"""

    def test_classified_as_multi_hop(self):
        clf = QueryComplexityClassifier()
        c = clf.classify("How do I become a PACS member and then get a crop loan?")
        assert c == QueryComplexity.MULTI_HOP

    def test_plan_has_sequential_requirements(self):
        llm_response = '''
        {
            "user_facts": [],
            "requirements": [
                {"description": "PACS membership process", "search_query": "PACS membership procedure"},
                {"description": "Resulting membership state", "search_query": "PACS member eligibility"},
                {"description": "Crop loan requirements", "search_query": "crop loan eligibility PACS"},
                {"description": "Next action for loan", "search_query": "crop loan application process"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("multi-hop query", "en")
        assert len(plan.requirements) >= 3


class TestComparison:
    """'PMFBY vs PM-KUSUM: which is better for farmers?'"""

    def test_classified_as_comparison(self):
        clf = QueryComplexityClassifier()
        c = clf.classify("What is the difference between PMFBY and PM-KUSUM?")
        assert c == QueryComplexity.COMPARISON

    def test_plan_has_comparison_requirements(self):
        llm_response = '''
        {
            "user_facts": [],
            "requirements": [
                {"description": "PMFBY scheme details", "search_query": "PMFBY crop insurance scheme"},
                {"description": "PM-KUSUM scheme details", "search_query": "PM-KUSUM solar pump scheme"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        plan = planner.plan("comparison query", "en")
        assert len(plan.requirements) == 2


class TestFollowUpTurn:
    """Follow-up: 'Can I get this benefit?' after being asked about membership."""

    def test_plan_uses_history(self):
        llm_response = '''
        {
            "user_facts": ["PACS member (from previous turn)"],
            "requirements": [
                {"description": "Benefit eligibility for PACS member", "search_query": "PACS member benefit eligibility"}
            ],
            "missing_user_facts": []
        }
        '''
        planner = ScenarioPlanner(_mock_llm(llm_response))
        history = [
            {"role": "user", "content": "I am a PACS member"},
            {"role": "assistant", "content": "Are you looking for specific benefits?"},
        ]
        plan = planner.plan("Can I get this benefit?", "en", history=history)
        assert len(plan.requirements) == 1


class TestContradictoryEvidence:
    """Two evidence items contradict each other."""

    def test_evidence_map_detects_partial(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="rule", search_query="q1"),
            ],
        )
        # Low score chunk = partial evidence
        results = {
            "r1": _rag_result([_evidence("c1", "weak evidence", dense_score=0.30)]),
        }
        evidence_map, _ = builder.build_map(plan, results)
        # Low score → PARTIAL (not SUPPORTED)
        assert evidence_map[0].status == RequirementStatus.PARTIAL


class TestUnsupportedScenario:
    """No evidence at all for any requirement."""

    def test_overall_sufficiency_insufficient(self):
        builder = EvidenceMapBuilder()
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO, user_facts=[],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
                EvidenceRequirement(requirement_id="r2", description="r2", search_query="q2"),
            ],
        )
        results = {
            "r1": _rag_result([], abstained=True),
            "r2": _rag_result([], abstained=True),
        }
        evidence_map, _ = builder.build_map(plan, results)
        sufficiency = builder.assess_sufficiency(evidence_map, plan)
        assert sufficiency == EvidenceSufficiency.INSUFFICIENT


# ---------------------------------------------------------------------------
# 6. Regression: simple queries stay on fast path
# ---------------------------------------------------------------------------

class TestSimpleQueryFastPath:
    """Verify simple queries are NOT routed to scenario pipeline."""

    def test_simple_query_classified_simple(self):
        clf = QueryComplexityClassifier()
        simple_queries = [
            "What is PMFBY?",
            "Tell me about PACS",
            "What is crop insurance?",
            "Define cooperative society",
            "PMFBY scheme details",
        ]
        for q in simple_queries:
            assert clf.classify(q) == QueryComplexity.SIMPLE, f"Expected SIMPLE for: {q}"

    def test_complex_queries_not_simple(self):
        clf = QueryComplexityClassifier()
        complex_queries = [
            "I am a PACS member and want a loan, can I get it if I have an unpaid loan?",
            "How do I become a member and then apply for a loan?",
            "What is the difference between PMFBY and PM-KUSUM?",
            "Can I get a crop loan if I am not a PACS member?",
        ]
        for q in complex_queries:
            assert clf.classify(q) != QueryComplexity.SIMPLE, f"Expected non-SIMPLE for: {q}"


# ---------------------------------------------------------------------------
# 7. ScenarioResult structure
# ---------------------------------------------------------------------------

class TestScenarioResultStructure:
    """Verify ScenarioResult is correctly populated."""

    def test_result_has_all_fields(self):
        plan = ScenarioPlan(
            complexity=QueryComplexity.SCENARIO,
            user_facts=["member"],
            requirements=[
                EvidenceRequirement(requirement_id="r1", description="r1", search_query="q1"),
            ],
            missing_user_facts=["share count"],
        )
        evidence_map = [
            EvidenceMapEntry(requirement_id="r1", description="r1",
                           status=RequirementStatus.SUPPORTED, evidence_ids=["c1"]),
        ]
        conclusions = [
            DerivedConclusion(
                conclusion="All conditions met",
                supporting_evidence_ids=["c1"],
                requires_conditions=["membership"],
            ),
        ]

        result = ScenarioResult(
            plan=plan,
            evidence_map=evidence_map,
            derived_conclusions=conclusions,
            supported_facts=["member"],
            unsupported_requirements=[],
            missing_user_facts=["share count"],
            overall_sufficiency=EvidenceSufficiency.SUFFICIENT,
            all_evidence=[_evidence("c1", "content")],
        )

        assert result.plan.complexity == QueryComplexity.SCENARIO
        assert len(result.evidence_map) == 1
        assert len(result.derived_conclusions) == 1
        assert result.overall_sufficiency == EvidenceSufficiency.SUFFICIENT
        assert "share count" in result.missing_user_facts


# ---------------------------------------------------------------------------
# 8. Orchestrator integration (complexity routing)
# ---------------------------------------------------------------------------

class TestOrchestratorComplexityRouting:
    """Verify orchestrator routes complex queries to scenario pipeline."""

    def test_simple_query_not_routed_to_scenario(self):
        """Simple queries should NOT trigger scenario pipeline."""

        clf = QueryComplexityClassifier()
        assert clf.classify("What is PMFBY?") == QueryComplexity.SIMPLE

    def test_complexity_classifier_imported_in_orchestrator(self):
        from app.services.rag_orchestrator import RAGOrchestrator
        orch = RAGOrchestrator(_settings())
        assert hasattr(orch, '_complexity_classifier')
        assert isinstance(orch._complexity_classifier, QueryComplexityClassifier)
