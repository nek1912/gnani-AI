"""P1-7 identifier-aware search + numeral normalization tests.

Covers: Gujarati/Devanagari numeral normalization, identifier
extraction (instrument/section/article/Act/Rule), bounded variants,
identifier branch gating (fires on script change, not on plain
English IDs), identifier ranking bonus levels, and branch-count
safety across languages.
"""

from app.web_rag.identifiers import (
    MAX_VARIANTS,
    extract_query_identifiers,
    has_non_arabic_numerals,
    identifier_match_score,
    identifier_variants,
    normalize_numerals,
)
from app.web_rag.service import WebDiscoveryService
from app.web_rag.query_classifier import QueryClassifier

_classifier = QueryClassifier()


class TestNumerals:
    def test_gujarati_numerals(self):
        assert normalize_numerals("અકત/૧૦૮૭/૧૪૧૫/જ") == "અકત/1087/1415/જ"

    def test_gujarati_year(self):
        assert normalize_numerals("૧૯૬૧") == "1961"

    def test_devanagari_numerals(self):
        assert normalize_numerals("२०२४") == "2024"

    def test_arabic_untouched(self):
        assert normalize_numerals("KRP/2025/1145") == "KRP/2025/1145"

    def test_detection(self):
        assert has_non_arabic_numerals("૧૯૬૧") is True
        assert has_non_arabic_numerals("1961") is False


class TestExtraction:
    def test_section_and_article(self):
        ids = extract_query_identifiers("What does Section 96 say? Article 243 applies.")
        assert "Section 96" in ids
        assert "Article 243" in ids

    def test_act_and_rules_year(self):
        ids = extract_query_identifiers("Gujarat Act 1961 and Rules 1965 apply.")
        assert "1961 Act" in ids
        assert "Rules 1965" in ids

    def test_instrument_ids(self):
        ids = extract_query_identifiers("See circular No. 42/2024 for rates.")
        assert "42/2024" in ids

    def test_bare_numbers_ignored(self):
        assert extract_query_identifiers("I have 2 societies.") == []

    def test_bounded(self):
        ids = extract_query_identifiers(
            "Circular No. 1/2020, 2/2021, 3/2022, 4/2023, 5/2024, 6/2025, 7/2026"
        )
        assert len(ids) <= 5


class TestVariants:
    def test_english_unchanged_single(self):
        assert identifier_variants("circular No. 42/2024") == ["circular No. 42/2024"]

    def test_numeral_variant_added(self):
        variants = identifier_variants("GR ક્રમાંક ૧૦૮૭")
        assert len(variants) == 2
        assert variants[0] == "GR ક્રમાંક ૧૦૮૭"
        assert "1087" in variants[1]

    def test_bounded_three(self):
        assert len(identifier_variants("GR tharav ૧૦૮૭ test")) <= MAX_VARIANTS
        assert MAX_VARIANTS == 3


class TestMatchScore:
    def test_exact(self):
        assert identifier_match_score(["KRP/2025/1145"], {"instrument_id": "KRP/2025/1145"}) == 0.60

    def test_case_insensitive(self):
        assert identifier_match_score(["krp/2025/1145"], {"instrument_id": "KRP/2025/1145"}) == 0.60

    def test_near_exact_separators(self):
        """Adversarial: same digits, different separators still match."""
        assert identifier_match_score(["42/2024"], {"instrument_id": "42-2024"}) == 0.45

    def test_different_id_no_match(self):
        assert identifier_match_score(["42/2024"], {"instrument_id": "43/2024"}) == 0.0

    def test_year_only_no_match(self):
        assert identifier_match_score(["2024"], {"instrument_id": "42/2024"}) == 0.0

    def test_no_validity_no_match(self):
        assert identifier_match_score(["42/2024"], None) == 0.0
        assert identifier_match_score([], {"instrument_id": "42/2024"}) == 0.0


class TestIdentifierBranch:
    def _branches(self, query):
        cls = _classifier.classify(query)
        service = WebDiscoveryService()
        return service._build_stage1_branches(query, cls, query)

    def test_plain_english_id_no_extra_branch(self):
        """No explosion: the English primary already searches the ID."""
        branches = self._branches("See circular No. 42/2024 for rates.")
        assert "identifier" not in [b["name"] for b in branches]

    def test_gujarati_numeral_query_adds_branch(self):
        """Adversarial #14: Gujarati numerals normalized for retrieval."""
        branches = self._branches("પરિપત્ર ક્રમાંક અકત/૧૦૮૭/૧૪૧૫/જ")
        names = [b["name"] for b in branches]
        assert "identifier" in names
        branch = next(b for b in branches if b["name"] == "identifier")
        assert "1087" in branch["query"]
        assert branch["only_official"] is True
        assert branch["max_results"] <= 8

    def test_identifier_bonus_in_rescore(self):
        from types import SimpleNamespace

        from app.web_rag.retrieval_scorer import rescore

        classification = SimpleNamespace(
            intent="INFORMATIONAL", state="Gujarat", domain="agriculture",
            society_type=None, case_year=None, season=None,
        )

        def result(url, validity):
            return {
                "chunk_id": "web_x_c101", "source_url": url, "url": url,
                "title": "Circular", "web_title": "Circular",
                "text": "circular text", "content": "circular text",
                "bm25_score": 1.0, "official": True, "trusted_secondary": False,
                "validity": validity,
            }

        pool = [
            result("https://x.gov.in/other", {"instrument_id": "99/2024"}),
            result("https://x.gov.in/target", {"instrument_id": "42/2024"}),
        ]
        ranked = rescore("circular No. 42/2024", pool, classification)
        assert ranked[0]["source_url"] == "https://x.gov.in/target"
        assert ranked[0]["identifier_bonus"] == 0.60

    def test_branch_cap_holds_with_identifier(self):
        branches = self._branches("પરિપત્ર ક્રમાંક અકત/૧૦૮૭/૧૪૧૫/જ deadline appeal Gujarat")
        assert len(branches) <= WebDiscoveryService.MAX_BRANCHES
