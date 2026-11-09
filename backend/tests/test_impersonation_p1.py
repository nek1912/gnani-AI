"""P1-6 impersonation / look-alike detection tests.

Covers: government look-alikes, bank look-alikes, regulator
look-alikes, punycode, gov-token abuse, legitimate institutional
domains (no false blocks), quarantine stamping + citation exclusion,
and the rescore demotion.
"""

from app.web_rag.impersonation import assess_impersonation, screen_result
from app.web_rag.retrieval_scorer import rescore
from types import SimpleNamespace


def _cls(**overrides):
    params = {
        "intent": "INFORMATIONAL", "state": "Gujarat", "domain": "agriculture",
        "society_type": None, "case_year": None, "season": None,
    }
    params.update(overrides)
    return SimpleNamespace(**params)


class TestLookalikes:
    def test_anyror_lookalike(self):
        """Adversarial #12 (part): fake AnyRoR domain never authoritative."""
        verdict = assess_impersonation("https://anyror-gujarat.in/land-record")
        assert verdict["suspicious"] is True

    def test_gujaratgr_lookalike(self):
        verdict = assess_impersonation("https://gujaratgr.in/gr-2026")
        assert verdict["suspicious"] is True

    def test_pmkisan_lookalike(self):
        verdict = assess_impersonation("https://pmkisan-yojana.com/apply")
        assert verdict["suspicious"] is True

    def test_bank_lookalike(self):
        verdict = assess_impersonation("https://sbi-bank-offer.in/login")
        assert verdict["suspicious"] is True

    def test_regulator_lookalike(self):
        verdict = assess_impersonation("https://irdai-claims.org.in/settle")
        assert verdict["suspicious"] is True

    def test_rbi_phishing_subdomain(self):
        verdict = assess_impersonation("https://rbi-customercare.top/verify")
        assert verdict["suspicious"] is True

    def test_punycode(self):
        verdict = assess_impersonation("https://xn--pib-gov-abc.in/release")
        assert verdict["suspicious"] is True
        assert verdict["reason"] == "punycode"

    def test_gov_token_abuse(self):
        verdict = assess_impersonation("https://gujarat-sarkari.org/schemes")
        assert verdict["suspicious"] is True
        assert verdict["reason"] == "gov_token_unverified"

    def test_empty_url_safe(self):
        assert assess_impersonation("") == {"suspicious": False, "reason": None}


class TestLegitimateDomains:
    """Adversarial #13: legitimate institutional domains not blocked."""

    def test_official_gov_in(self):
        assert assess_impersonation("https://rcs.gujarat.gov.in/Home/ActsAndRules")["suspicious"] is False
        assert assess_impersonation("https://crcs.gov.in/public/")["suspicious"] is False
        assert assess_impersonation("https://vadodara.nic.in/service/swagat/")["suspicious"] is False

    def test_org_in_regulators(self):
        assert assess_impersonation("https://rbi.org.in/scripts/test.aspx")["suspicious"] is False
        assert assess_impersonation("https://www.dicgc.org.in/guide")["suspicious"] is False
        assert assess_impersonation("https://www.nabard.org/about")["suspicious"] is False

    def test_bank_in(self):
        assert assess_impersonation("https://gsc.bank.in/about-us/")["suspicious"] is False

    def test_university_sau(self):
        assert assess_impersonation("https://www.jau.in/kvks")["suspicious"] is False

    def test_cooperative_institutional(self):
        assert assess_impersonation("https://www.amuldairy.com/dairyvisit.php")["suspicious"] is False

    def test_reputable_secondary(self):
        assert assess_impersonation("https://prsindia.org/billtrack")["suspicious"] is False
        assert assess_impersonation("https://vikaspedia.in/agriculture")["suspicious"] is False

    def test_plain_unknown_not_flagged(self):
        # Unknown without impersonation signals: quality is ranking's
        # job; this module judges impersonation only.
        assert assess_impersonation("https://randomblog.example/post")["suspicious"] is False
        assert assess_impersonation("https://gujarat-news.example/package")["suspicious"] is False


class TestQuarantine:
    def test_screen_tags_and_quarantines(self):
        chunk = {
            "source_url": "https://anyror-gujarat.in/land-record",
            "url": "https://anyror-gujarat.in/land-record",
            "title": "AnyRoR 7/12",
            "official": False, "trusted_secondary": False,
        }
        verdict = screen_result(chunk)
        assert verdict["suspicious"] is True
        assert chunk["impersonation"]["suspicious"] is True
        assert chunk["lead_only"] is True

    def test_screen_clean_passes_through(self):
        chunk = {
            "source_url": "https://rcs.gujarat.gov.in/acts",
            "url": "https://rcs.gujarat.gov.in/acts",
            "title": "Acts",
            "official": True, "trusted_secondary": False,
        }
        assert screen_result(chunk)["suspicious"] is False
        assert "lead_only" not in chunk

    def test_quarantined_demoted_in_rescore(self):
        official = {
            "chunk_id": "web_off_c101", "source_url": "https://anyror.gujarat.gov.in/record",
            "url": "https://anyror.gujarat.gov.in/record", "title": "AnyRoR record",
            "web_title": "AnyRoR record", "text": "land record", "content": "land record",
            "bm25_score": 1.0, "official": True, "trusted_secondary": False,
        }
        fake = {
            "chunk_id": "web_fk_c101", "source_url": "https://anyror-gujarat.in/record",
            "url": "https://anyror-gujarat.in/record", "title": "AnyRoR record",
            "web_title": "AnyRoR record", "text": "land record", "content": "land record",
            "bm25_score": 1.0, "official": False, "trusted_secondary": False,
            "impersonation": {"suspicious": True, "reason": "brand_lookalike:anyror"},
            "lead_only": True,
        }
        ranked = rescore("7/12 land record", [fake, official], _cls())
        assert ranked[0]["source_url"] == "https://anyror.gujarat.gov.in/record"
        assert ranked[1]["suspicion_penalty"] == 1.50

    def test_quarantined_excluded_from_citations(self):
        from app.contracts import EvidenceChunk
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator.__new__(RAGOrchestrator)
        chunks = [
            EvidenceChunk(
                chunk_id="q" * 8 + "uarantined-id", content="t",
                source_type="web", title="t",
                url="https://anyror-gujarat.in/x",
                metadata={"impersonation": {"suspicious": True, "reason": "x"}},
            ),
            EvidenceChunk(
                chunk_id="o" * 8 + "fficial-id", content="t",
                source_type="web", title="t",
                url="https://anyror.gujarat.gov.in/x", metadata={},
            ),
        ]
        citations = orch._build_citations(chunks)
        assert [c["chunk_id"] for c in citations] == ["o" * 8]
