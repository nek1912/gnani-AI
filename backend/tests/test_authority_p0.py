"""P0-3 mandate map + question-relative authority tests.

Covers: map integrity (provenance, unique domains), anchor selection
(subject + jurisdiction scoped, MSCS central-only), mandate_fit levels,
document_role conservatism, allow_domains filtering, and
question-relative ranking (RBI wins banking questions; Gujarat Agri
wins Gujarat crop-relief questions).
"""

from types import SimpleNamespace

from app.web_rag.mandate_map import (
    anchors_for_domain,
    document_role,
    find_org,
    load_mandate_map,
    mandate_fit,
    query_subjects,
)
from app.web_rag.retrieval_scorer import rescore
from app.web_rag.service import WebDiscoveryService


def _cls(domain, state=None, society_type=None, intent="INFORMATIONAL"):
    return SimpleNamespace(
        domain=domain,
        state=state,
        society_type=society_type,
        intent=intent,
        case_year=None,
        season=None,
    )


def _result(url, title, text="evidence text", bm25=1.0):
    return {
        "chunk_id": "web_abc_c1",
        "source_url": url,
        "url": url,
        "title": title,
        "web_title": title,
        "text": text,
        "content": text,
        "bm25_score": bm25,
        "official": True,
        "trusted_secondary": False,
    }


class TestMandateMapIntegrity:
    def test_loads_orgs(self):
        orgs = load_mandate_map()
        assert len(orgs) >= 30

    def test_domains_unique(self):
        domains = [d for o in load_mandate_map() for d in o["domains"]]
        assert len(domains) == len(set(domains))

    def test_all_entries_have_provenance(self):
        for org in load_mandate_map():
            assert org.get("provenance") in ("R", "C", "R+C"), org["organisation"]
            assert org["jurisdiction"] in ("central", "gujarat", "institutional")
            assert org["mandate_subjects"]
            assert org["roles_served"]

    def test_key_publishers_present(self):
        for domain, expected_org in [
            ("rbi.org.in", "Reserve Bank of India"),
            ("dicgc.org.in", "DICGC"),
            ("ncdc.in", "NCDC"),
            ("crcs.gov.in", "CRCS"),
            ("rcs.gujarat.gov.in", "Gujarat RCS"),
            ("agri.gujarat.gov.in", "Gujarat Agriculture"),
            ("ggrc.co.in", "GGRC"),
            ("pmkusum.guvnl.com", "GUVNL"),
            ("egazette.gujarat.gov.in", "Gujarat eGazette"),
        ]:
            org = find_org(f"https://{domain}/x")
            assert org is not None, domain
            assert org["organisation"].startswith(expected_org.split(" /")[0].split(" (")[0][:12])

    def test_no_unverified_lynchpins(self):
        # Omitted-by-design hosts must NOT appear (KRP/e-Daakhil/CSC).
        domains = {d for o in load_mandate_map() for d in o["domains"]}
        assert "krp.gujarat.gov.in" not in domains
        assert "csc.gov.in" not in domains


class TestAnchors:
    def test_pmfby_gujarat_anchors(self):
        anchors = anchors_for_domain("pmfby", "Gujarat")
        assert anchors is not None
        assert "pmfby.gov.in" in anchors
        assert any("gujarat" in d for d in anchors)
        assert len(anchors) <= 15

    def test_mscs_anchors_are_central_only(self):
        anchors = anchors_for_domain("cooperative", None, society_type="mscs")
        assert anchors is not None
        assert "crcs.gov.in" in anchors
        assert "cooperation.gov.in" in anchors
        assert not any("gujarat" in d for d in anchors)

    def test_out_of_scope_domains_have_no_anchors(self):
        assert anchors_for_domain("driving_licence", "Gujarat") is None
        assert anchors_for_domain("general", None) is None

    def test_subjects_include_society_type(self):
        base = query_subjects("cooperative", None)
        assert "mscs" in base  # cooperative domain covers MSCS sources
        assert query_subjects("cooperative", "mscs") >= base


class TestMandateFit:
    def test_competent_publisher_full_fit(self):
        assert mandate_fit("https://rbi.org.in/a", {"banking"}, "Gujarat") == 0.30

    def test_known_publisher_wrong_subject_adjacent(self):
        assert mandate_fit("https://rbi.org.in/a", {"crop_relief"}, "Gujarat") == 0.10

    def test_state_publisher_out_of_jurisdiction(self):
        assert (
            mandate_fit("https://agri.gujarat.gov.in/a", {"crop_relief"}, "Maharashtra")
            == 0.0
        )

    def test_unknown_publisher_zero(self):
        assert mandate_fit("https://randomblog.example/a", {"banking"}, None) == 0.0

    def test_no_subjects_zero(self):
        assert mandate_fit("https://rbi.org.in/a", set(), "Gujarat") == 0.0

    def test_mscs_prefers_crcs_over_state_rcs(self):
        # P1 audit: society-aware competence. Gujarat RCS has no
        # competence over multi-state societies.
        crcs = mandate_fit(
            "https://crcs.gov.in/public/", {"cooperative", "mscs"},
            None, society_type="mscs",
        )
        rcs = mandate_fit(
            "https://rcs.gujarat.gov.in/Home/ActsAndRules",
            {"cooperative", "mscs"}, None, society_type="mscs",
        )
        assert crcs == 0.40
        assert rcs == 0.0
        assert crcs > rcs

    def test_jurisdiction_penalty_mscs_forum(self):
        from app.web_rag.mandate_map import jurisdiction_penalty

        assert jurisdiction_penalty(
            "https://rcs.gujarat.gov.in/Home/ActsAndRules",
            None, "mscs", "none",
        ) == -0.80
        assert jurisdiction_penalty(
            "https://crcs.gov.in/public/", None, "mscs", "none",
        ) == 0.0

    def test_jurisdiction_penalty_explicit_state_only(self):
        from app.web_rag.mandate_map import jurisdiction_penalty

        # Explicit Maharashtra + Gujarat publisher: wrong forum.
        assert jurisdiction_penalty(
            "https://agri.gujarat.gov.in/gr/x", "Maharashtra", None, "explicit",
        ) == -0.80
        # Assumed state never penalizes (disclosed, not enforced).
        assert jurisdiction_penalty(
            "https://agri.gujarat.gov.in/gr/x", "Maharashtra", None, "subject_default",
        ) == 0.0
        # Unknown publishers can never be judged.
        assert jurisdiction_penalty(
            "https://randomblog.example/x", "Maharashtra", None, "explicit",
        ) == 0.0


class TestDocumentRole:
    def test_gr_path_is_instrument(self):
        assert (
            document_role(
                "https://agri.gujarat.gov.in/gr/crop-relief-2026",
                "Crop relief GR 2026",
                True,
                False,
            )
            == "instrument"
        )

    def test_rbi_scheme_pdf_is_instrument(self):
        assert (
            document_role(
                "https://rbidocs.rbi.org.in/rdocs/content/pdfs/SCHEME16012026_A.pdf",
                "Integrated Ombudsman Scheme 2026",
                True,
                False,
            )
            == "instrument"
        )

    def test_pib_release_is_explainer(self):
        assert (
            document_role(
                "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1",
                "PIB press release on PACS",
                True,
                False,
            )
            == "explainer"
        )

    def test_portal_page_is_implementation(self):
        assert (
            document_role(
                "https://ikhedut.gujarat.gov.in/Public/Home.aspx",
                "i-Khedut portal",
                True,
                False,
            )
            == "implementation"
        )

    def test_blog_is_secondary(self):
        assert (
            document_role("https://randomblog.example/x", "some post", False, False)
            == "secondary"
        )

    def test_opaque_official_pdf_is_not_guessed_instrument(self):
        assert (
            document_role(
                "https://dept.gov.in/sites/default/files/USQ_1606.pdf",
                "USQ 1606",
                True,
                False,
            )
            == "explainer"
        )

    def test_agreement_does_not_trigger_gr(self):
        assert (
            document_role(
                "https://example.gov.in/about-agreement",
                "User agreement",
                True,
                False,
            )
            != "instrument"
        )


class TestAllowDomainsFilter:
    def test_allow_domains_admits_mandate_anchor(self):
        # dicgc.org.in is NOT in OFFICIAL_DOMAINS (verified gap).
        assert WebDiscoveryService.is_official_url("https://www.dicgc.org.in/guide") is False
        assert (
            WebDiscoveryService._domain_in_set(
                "https://www.dicgc.org.in/guide", {"dicgc.org.in"}
            )
            is True
        )

    def test_allow_domains_suffix_match(self):
        assert (
            WebDiscoveryService._domain_in_set(
                "https://pmkusum.guvnl.com/GJ/landing.html",
                {"pmkusum.guvnl.com"},
            )
            is True
        )
        assert (
            WebDiscoveryService._domain_in_set(
                "https://evil-pmkusum.guvnl.com.evil.example/x",
                {"pmkusum.guvnl.com"},
            )
            is False
        )


class TestQuestionRelativeRanking:
    def test_rbi_wins_banking_question(self):
        rbi = _result(
            "https://rbi.org.in/commonperson/FAQs.aspx",
            "RBI Integrated Ombudsman Scheme FAQs",
        )
        generic = _result(
            "https://example.gov.in/banking-info",
            "Banking information page",
        )
        ranked = rescore("bank complaint RBI ombudsman", [generic, rbi], _cls("finlit"))
        assert ranked[0]["source_url"].startswith("https://rbi.org.in")
        assert ranked[0]["mandate_fit"] == 0.30

    def test_gujarat_agri_wins_gujarat_relief_question(self):
        rbi = _result(
            "https://rbi.org.in/commonperson/FAQs.aspx",
            "RBI crop loan FAQs",
        )
        agri_gr = _result(
            "https://agri.gujarat.gov.in/gr/crop-relief-2026",
            "Crop relief GR 2026",
        )
        ranked = rescore(
            "crop loss relief Gujarat",
            [rbi, agri_gr],
            _cls("agriculture", state="Gujarat"),
        )
        assert ranked[0]["source_url"].startswith("https://agri.gujarat.gov.in")
        assert ranked[0]["document_role"] == "instrument"
        # RBI is competent for banking, adjacent (not incompetent) here.
        rbi_entry = next(r for r in ranked if "rbi.org.in" in r["source_url"])
        assert rbi_entry["mandate_fit"] == 0.10
