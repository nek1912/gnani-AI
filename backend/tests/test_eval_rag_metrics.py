"""Unit tests for RAG V3 evaluation metrics computation.

Verifies:
- Recall@1, Recall@3, Recall@5, MRR
- Domain accuracy
- Jurisdiction accuracy and wrong-jurisdiction rate
- Citation precision and recall
- Answer groundedness
- Abstention precision and recall
"""

import pytest
from tests.eval_rag_v3 import CaseResult, EvalCase, measure


def test_measure_ir_and_grounding_metrics():
    eval_cases = [
        EvalCase(id="T01", category="direct", subcategory="def", question="q1", lang="en", domain="pmfby", required_evidence_docs=["DocA"]),
        EvalCase(id="T02", category="direct", subcategory="def", question="q2", lang="en", domain="pmfby", required_evidence_docs=["DocB"]),
        EvalCase(id="T03", category="direct", subcategory="gap", question="q3", lang="en", domain="pmfby", expected_abstain=True),
    ]

    retrieval_results = [
        # T01: found at rank 1
        CaseResult(
            case_id="T01", category="direct", subcategory="def", question="q1", lang="en",
            retrieved_chunks=3, required_docs_found=["DocA"],
            recall_at_1=True, recall_at_3=True, recall_at_5=True, mrr=1.0,
            domain_match=True, jurisdiction_match=True, wrong_jurisdiction_count=0,
        ),
        # T02: found at rank 3
        CaseResult(
            case_id="T02", category="direct", subcategory="def", question="q2", lang="en",
            retrieved_chunks=3, required_docs_found=["DocB"],
            recall_at_1=False, recall_at_3=True, recall_at_5=True, mrr=1.0 / 3.0,
            domain_match=True, jurisdiction_match=True, wrong_jurisdiction_count=0,
        ),
        # T03: expected abstain, 0 chunks
        CaseResult(
            case_id="T03", category="direct", subcategory="gap", question="q3", lang="en",
            retrieved_chunks=0, abstained=True,
        ),
    ]

    answers = [
        # T01: answered correctly, 2 citations (all valid), no unsupported claims
        CaseResult(
            case_id="T01", category="direct", subcategory="def", question="q1", lang="en",
            answer_correct=True, citation_count=2, citations_valid=True,
        ),
        # T02: answered correctly, 2 citations (1 invalid), no unsupported claims
        CaseResult(
            case_id="T02", category="direct", subcategory="def", question="q2", lang="en",
            answer_correct=True, citation_count=2, citations_valid=False,
        ),
        # T03: abstained correctly
        CaseResult(
            case_id="T03", category="direct", subcategory="gap", question="q3", lang="en",
            answer_correct=True, abstained=True,
        ),
    ]

    # Patch EVAL_SET in eval_rag_v3 temporarily for measure()
    import tests.eval_rag_v3 as eval_module
    old_eval_set = eval_module.EVAL_SET
    eval_module.EVAL_SET = eval_cases
    try:
        metrics = measure(retrieval_results, answers)
        assert metrics["recall_at_1"] == 0.5  # 1 out of 2 non-abstain cases
        assert metrics["recall_at_3"] == 1.0  # 2 out of 2 non-abstain cases
        assert metrics["recall_at_5"] == 1.0
        assert metrics["mean_reciprocal_rank"] == pytest.approx((1.0 + 1.0 / 3.0) / 2.0)
        assert metrics["domain_accuracy"] == 1.0
        assert metrics["wrong_jurisdiction_rate"] == 0.0
        assert metrics["citation_precision"] == 0.5  # 2 valid of 4 total citations
        assert metrics["answer_groundedness"] == 1.0
        assert metrics["abstention_precision"] == 1.0
        assert metrics["abstention_recall"] == 1.0
    finally:
        eval_module.EVAL_SET = old_eval_set

