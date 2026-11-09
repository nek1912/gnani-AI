"""P0-4 Gujarati/Hindi retrieval branch tests.

Covers: lexicon-verified branch construction, branch execution inside
discover(), English-branch preservation, merge dedup, Hindi gating
(central/assumed only, never explicit-state), and the
no-unverified-term property.
"""

from unittest.mock import patch

from app.web_rag.lexicon import (
    all_gu_terms,
    all_hi_terms,
    document_type_terms,
    gujarati_branch_query,
    hindi_branch_query,
    load_lexicon,
    matched_concepts,
)
from app.web_rag.service import WebDiscoveryService


def _item(url, title, text):
    return {
        "url": url,
        "title": title,
        "content": text,
        "raw_content": text,
        "score": 0.9,
        "favicon": None,
    }


_FIXTURES = [
    _item(
        "https://pmfby.gov.in/guidelines",
        "PMFBY crop insurance Gujarat guidelines",
        "PMFBY crop insurance Gujarat guidelines for notified crops. " * 10,
    ),
    _item(
        "https://agri.gujarat.gov.in/gr/pak-vimo-2026",
        "પાક વીમા સરકારી ઠરાવ 2026",
        "પાક વીમો કૃષિ રાહત પેકેજ સહાય ગુજરાત ખેડૂત. " * 10,
    ),
]


class TestLexicon:
    def test_loads_concepts(self):
        assert len(load_lexicon()) >= 15
    def test_no_empty_concept_without_reason(self):
        # Concepts may lack gu/hi ONLY when no verified term exists.
        for concept in load_lexicon():
            assert concept.get("en"), concept["id"]

    def test_doc_type_terms_verified(self):
        terms = document_type_terms("gu")
        assert "ઠરાવ" in terms
        assert "પરિપત્ર" in terms
        assert "જાહેરનામું" in terms
        assert "ક્રમાંક" in terms


class TestBranchBuilders:
    def test_gujarati_branch_for_crop_insurance(self):
        q = gujarati_branch_query("Crop insurance claim in Gujarat", "Gujarat")
        assert q is not None
        assert "પાકવીમો" in q or "પાક વીમો" in q
        assert "ગુજરાત" in q

    def test_gujarati_branch_for_subsidy(self):
        q = gujarati_branch_query("Tell me the subsidy rate in Gujarat", "Gujarat")
        assert q is not None
        assert "સબસિડી" in q

    def test_gujarati_branch_none_without_concepts(self):
        assert gujarati_branch_query("My electricity bill is wrong.", None) is None

    def test_gujarati_branch_none_without_gu_terms(self):
        # KCC has no verified Gujarati term: no blind translation.
        assert gujarati_branch_query("KCC loan rules", "Gujarat") is None

    def test_gujarati_branch_adds_doc_terms_for_procedure(self):
        q = gujarati_branch_query(
            "How to apply for crop insurance", "Gujarat", intent="APPLICATION"
        )
        assert q is not None
        assert "ઠરાવ" in q or "પરિપત્ર" in q or "જાહેરનામું" in q

    def test_gujarati_branch_romanised_input(self):
        q = gujarati_branch_query("pak vimo sahay Gujarat", "Gujarat")
        assert q is not None
        assert "સહાય" in q or "પાકવીમો" in q

    def test_hindi_branch_for_central_scheme(self):
        q = hindi_branch_query("What is PMFBY crop insurance?", "pmfby")
        assert q is not None
        assert "फसल बीमा" in q

    def test_hindi_branch_wrong_domain(self):
        assert hindi_branch_query("How do I apply for a driving licence?", "driving_licence") is None
        assert hindi_branch_query("My electricity bill is wrong.", "general") is None

    def test_hindi_branch_none_without_terms(self):
        assert hindi_branch_query("Random unmapped words xyzzy", "pmfby") is None

    def test_matched_concepts(self):
        ids = {c["id"] for c in matched_concepts("crop insurance claim")}
        assert "crop_insurance" in ids


class TestNoUnverifiedTerms:
    """Every Gujarati/Hindi token emitted must come from the lexicon."""

    def _assert_covered(self, branch_query, terms):
        remaining = branch_query
        for term in sorted(terms, key=len, reverse=True):
            remaining = remaining.replace(term, " ")
        leftover = "".join(remaining.split())
        assert leftover == "", f"unverified tokens remain: {leftover!r}"

    def test_gu_queries_use_verified_terms_only(self):
        queries = [
            "Crop insurance claim in Gujarat",
            "How do I file a dispute against my cooperative society?",
            "When is my society election and who can vote?",
            "Land record 7/12 mutation in Junagadh",
            "Tar fencing subsidy rate",
            "pak vimo sahay Gujarat",
            "KCC loan rules",
            "My electricity bill is wrong.",
        ]
        for query in queries:
            q = gujarati_branch_query(query, "Gujarat", intent="APPLICATION")
            if q is None:
                continue
            self._assert_covered(q, all_gu_terms())

    def test_hi_queries_use_verified_terms_only(self):
        queries = [
            "What is PMFBY crop insurance?",
            "KCC loan interest complaint",
            "How to apply for a cooperative loan",
        ]
        for query in queries:
            q = hindi_branch_query(query, "pmfby")
            if q is None:
                continue
            self._assert_covered(q, all_hi_terms())


class TestLanguageBranchesExecute:
    def _run_discover(self, query, classification=None):
        service = WebDiscoveryService()
        calls = []

        def fake_search_all(q, **kwargs):
            calls.append({"query": q, "name": kwargs.get("include_domains")})
            return list(_FIXTURES)

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover(query, classification=classification)
        return result, calls

    def test_gujarati_branch_executes_for_gujarat(self):
        from app.web_rag.query_classifier import QueryClassifier

        cls = QueryClassifier().classify("Crop insurance in Gujarat")
        service = WebDiscoveryService()
        branches = service._build_stage1_branches(
            "Crop insurance in Gujarat", cls, "Crop insurance in Gujarat"
        )
        names = [b["name"] for b in branches]
        assert "primary" in names
        assert "jurisdiction" in names
        assert "gujarati" in names
        gu_branch = next(b for b in branches if b["name"] == "gujarati")
        assert any(
            "\u0a80" <= ch <= "\u0aff" for ch in gu_branch["query"]
        ), "branch query must carry Gujarati script"

    def test_english_primary_preserved(self):
        from app.web_rag.query_classifier import QueryClassifier

        cls = QueryClassifier().classify("Crop insurance in Gujarat")
        service = WebDiscoveryService()
        branches = service._build_stage1_branches("Crop insurance", cls, "Crop insurance")
        primary = next(b for b in branches if b["name"] == "primary")
        assert "Crop insurance" in primary["query"]

    def test_hindi_branch_for_assumed_state(self):
        # P1: no-signal PMFBY is central (no invented state); the Hindi
        # branch still fires for central-scheme questions.
        from app.web_rag.query_classifier import QueryClassifier

        cls = QueryClassifier().classify("What is PMFBY?")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        service = WebDiscoveryService()
        branches = service._build_stage1_branches("What is PMFBY?", cls, "What is PMFBY?")
        assert "hindi" in [b["name"] for b in branches]

    def test_no_hindi_branch_for_explicit_state(self):
        from app.web_rag.query_classifier import QueryClassifier

        cls = QueryClassifier().classify("Crop insurance in Gujarat")
        assert cls.jurisdiction_source == "explicit"
        service = WebDiscoveryService()
        branches = service._build_stage1_branches(
            "Crop insurance in Gujarat", cls, "Crop insurance in Gujarat"
        )
        assert "hindi" not in [b["name"] for b in branches]

    def test_general_query_has_no_language_branch(self):
        from app.web_rag.query_classifier import QueryClassifier

        cls = QueryClassifier().classify("My electricity bill is wrong.")
        service = WebDiscoveryService()
        branches = service._build_stage1_branches(
            "My electricity bill is wrong.", cls, "My electricity bill is wrong."
        )
        assert [b["name"] for b in branches] == ["primary"]

    def test_branch_results_merge_without_duplicates(self):
        result, _ = self._run_discover("Crop insurance in Gujarat")
        urls = [r.get("source_url") for r in result["results"]]
        assert len(urls) == len(set(urls))
        assert set(result["discovery_metadata"]["branches_run"]) >= {
            "primary", "jurisdiction", "gujarati",
        }

    def test_gujarati_role_cues(self):
        from app.web_rag.mandate_map import document_role

        assert (
            document_role(
                "https://agri.gujarat.gov.in/gr/crop-relief-2026",
                "પાક વીમા સરકારી ઠરાવ 2026",
                True,
                False,
            )
            == "instrument"
        )
