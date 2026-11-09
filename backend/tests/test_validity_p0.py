"""P0-2 validity-aware freshness tests.

Covers: extraction conservatism (no invented values), effective-from/to,
season/FY, instrument IDs, revision/corrigendum, supersession direction,
provider dates, case-date resolution, validity precedence in ranking,
historical as_of_date behavior, legacy recency-tiebreak fallback.
"""

from types import SimpleNamespace

from app.web_rag.retrieval_scorer import freshness_bonus, rescore
from app.web_rag.validity import (
    AMENDED,
    CURRENT,
    SUPERSEDED,
    UNKNOWN_STATUS,
    extract_validity,
    resolve_case_date,
    validity_preference,
)


def _cls(intent="STATUS", **overrides):
    params = {
        "intent": intent,
        "state": "Gujarat",
        "case_year": None,
        "season": None,
    }
    params.update(overrides)
    return SimpleNamespace(**params)


def _result(url, title, text, validity=None, bm25=1.0):
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
        "validity": validity,
    }


class TestExtractValidity:
    def test_empty_text_is_unknown(self):
        v = extract_validity("Some general information about farming practices.")
        assert v["published_date"] is None
        assert v["effective_from"] is None
        assert v["effective_to"] is None
        assert v["season"] is None
        assert v["fy"] is None
        assert v["instrument_id"] is None
        assert v["revision_label"] is None
        assert v["supersession_status"] == UNKNOWN_STATUS
        assert v["validity_source"] == "unknown"

    def test_bare_year_is_not_a_date(self):
        # A year mentioned in passing must not become a validity signal.
        v = extract_validity("The scheme started in 2020 and covers many farmers.")
        assert v["effective_from"] is None
        assert v["validity_source"] == "unknown"

    def test_effective_from(self):
        v = extract_validity(
            "The Integrated Ombudsman Scheme, 2026 shall come into force "
            "on 1 July 2026 for all regulated entities."
        )
        assert v["effective_from"] == "2026-07-01"
        assert v["validity_source"] == "stated"

    def test_effective_from_wef(self):
        v = extract_validity(
            "These directions apply to loans sanctioned from 1 January 2027 "
            "w.e.f. 01/01/2027."
        )
        assert v["effective_from"] == "2027-01-01"

    def test_effective_to(self):
        v = extract_validity(
            "Applications are valid till 24 October 2026 under this notice."
        )
        assert v["effective_to"] == "2026-10-24"

    def test_season_specific(self):
        v = extract_validity(
            "Operational guidelines effective from Kharif 2023 season."
        )
        assert v["season"] == "kharif"
        assert v["season_year"] == "2023"

    def test_season_hindi(self):
        v = extract_validity("रबी 2025 के लिए बीमा कवर")
        assert v["season"] == "rabi"
        assert v["season_year"] == "2025"

    def test_fy_specific(self):
        v = extract_validity("Interest subvention for FY 2025-26 under MISS.")
        assert v["fy"] == "2025-26"

    def test_rbi_reference(self):
        v = extract_validity(
            "As per RBI circular DOR.MCS.REC.59/01.01.003/2025-26, banks shall..."
        )
        assert v["instrument_id"] is not None
        assert "DOR" in v["instrument_id"]

    def test_circular_number(self):
        v = extract_validity("See circular No. 42/2024 dated 3 March 2024.")
        assert v["instrument_id"] == "42/2024"

    def test_revision_corrigendum(self):
        v = extract_validity(
            "Corrigendum to the revised operational guidelines issued earlier."
        )
        assert v["revision_label"] == "corrigendum"

    def test_superseded_by(self):
        v = extract_validity(
            "The 2021 scheme has been superseded by the 2026 scheme."
        )
        assert v["supersession_status"] == SUPERSEDED

    def test_revoked(self):
        v = extract_validity("This notification stands revoked.")
        assert v["supersession_status"] == SUPERSEDED

    def test_amended_by(self):
        v = extract_validity(
            "The Act as amended by the 2024 Amendment Act governs elections."
        )
        assert v["supersession_status"] == AMENDED

    def test_successor_is_current(self):
        v = extract_validity(
            "This scheme supersedes the earlier 2021 framework entirely."
        )
        assert v["supersession_status"] == CURRENT

    def test_newer_text_does_not_imply_supersession(self):
        v = extract_validity(
            "The 2026 guidelines describe the claim process in detail."
        )
        assert v["supersession_status"] == UNKNOWN_STATUS

    def test_provider_date(self):
        v = extract_validity(
            "General scheme overview.", provider_date="2026-09-09"
        )
        assert v["published_date"] == "2026-09-09"
        assert v["validity_source"] == "provider"

    def test_bad_provider_date_ignored(self):
        v = extract_validity("General overview.", provider_date="not-a-date")
        assert v["published_date"] is None


class TestResolveCaseDate:
    def test_as_of_wins(self):
        case = resolve_case_date("2024-05-01", case_year=2026)
        assert case["case_date"] == "2024-05-01"

    def test_case_year_fallback(self):
        case = resolve_case_date(None, case_year=2024, season="rabi")
        assert case["case_date"] == "2024-00-00"
        assert case["case_season"] == "rabi"

    def test_season_only(self):
        case = resolve_case_date(None, season="kharif")
        assert case["case_date"] is None
        assert case["case_season"] == "kharif"

    def test_no_anchor(self):
        assert resolve_case_date(None) == {}


class TestValidityPreference:
    def test_precedence_order(self):
        current = {"supersession_status": CURRENT}
        unknown = {"supersession_status": UNKNOWN_STATUS}
        old = {"supersession_status": SUPERSEDED}
        assert validity_preference(current, {}) > validity_preference(unknown, {})
        assert validity_preference(unknown, {}) > validity_preference(old, {})

    def test_old_but_valid_not_suppressed(self):
        # Unknown validity + old provider date scores exactly like new
        # unknown validity: age alone never demotes.
        old_unknown = {
            "supersession_status": UNKNOWN_STATUS,
            "published_date": "2020-03-01",
        }
        new_unknown = {
            "supersession_status": UNKNOWN_STATUS,
            "published_date": "2026-09-01",
        }
        assert validity_preference(old_unknown, {}) == validity_preference(
            new_unknown, {}
        ) == 0.0

    def test_future_effective_penalized(self):
        v = {"supersession_status": CURRENT, "effective_from": "2027-01-01"}
        assert validity_preference(v, {"case_date": "2026-10-04"}) == -1.20

    def test_expired_penalized(self):
        v = {"supersession_status": CURRENT, "effective_to": "2024-03-31"}
        assert validity_preference(v, {"case_date": "2026-10-04"}) == -1.00

    def test_superseded_beats_bm25_noise(self):
        # Penalties are scaled past BM25 min-max noise (up to 1.0), so a
        # stated supersession always demotes below comparable peers.
        assert (
            validity_preference({"supersession_status": SUPERSEDED}, {})
            < -1.0
        )

    def test_query_year_affinity_dampens(self):
        v = {
            "supersession_status": SUPERSEDED,
            "published_date": "2021-05-01",
        }
        full = validity_preference(v, {"query_years": set()})
        dampened = validity_preference(v, {"query_years": {"2021"}})
        assert full == -1.20
        assert dampened == -1.20 * 0.3
        assert dampened < 0.0  # still demoted, just less

    def test_valid_range_bonus(self):
        v = {
            "supersession_status": CURRENT,
            "effective_from": "2026-07-01",
        }
        assert validity_preference(v, {"case_date": "2026-10-04"}) > 0.0

    def test_coarse_year_anchor(self):
        # P2 audit: "Kharif 2024" anchors "2024-00-00"; a same-year
        # instrument is in force, a later-year one is future.
        same_year = {
            "supersession_status": CURRENT,
            "effective_from": "2024-10-01",
        }
        later_year = {
            "supersession_status": CURRENT,
            "effective_from": "2025-04-01",
        }
        case = {"case_date": "2024-00-00", "case_season": "kharif"}
        assert validity_preference(same_year, case) > 0.0
        assert validity_preference(later_year, case) == -1.20

    def test_season_match_bonus(self):
        v = {"supersession_status": UNKNOWN_STATUS, "season": "kharif"}
        match = validity_preference(v, {"case_season": "kharif"})
        nomatch = validity_preference(v, {})
        assert match > nomatch


class TestFreshnessIntegration:
    def test_superseded_demoted_in_rescore(self):
        current = _result(
            "https://rbi.org.in/scheme-2026",
            "Integrated Ombudsman Scheme 2026",
            "scheme text",
            validity={"supersession_status": CURRENT},
            bm25=1.0,
        )
        superseded = _result(
            "https://rbi.org.in/scheme-2021",
            "Integrated Ombudsman Scheme 2021",
            "scheme text",
            validity={"supersession_status": SUPERSEDED},
            bm25=1.0,
        )
        ranked = rescore("RBI ombudsman complaint", [superseded, current], _cls())
        assert ranked[0]["source_url"] == "https://rbi.org.in/scheme-2026"
        assert ranked[0]["validity_status"] == CURRENT
        assert ranked[1]["validity_status"] == SUPERSEDED

    def test_historical_as_of_date_flips_ranking(self):
        old_valid = _result(
            "https://example.gov.in/guidelines-2020",
            "Scheme guidelines 2020",
            "scheme text",
            validity={
                "supersession_status": CURRENT,
                "effective_from": "2020-01-01",
                "effective_to": "2024-12-31",
            },
            bm25=1.0,
        )
        future = _result(
            "https://example.gov.in/guidelines-2027",
            "Scheme guidelines 2027",
            "scheme text",
            validity={
                "supersession_status": CURRENT,
                "effective_from": "2027-01-01",
            },
            bm25=1.0,
        )
        historical = rescore(
            "scheme guidelines", [future, old_valid], _cls(), as_of_date="2024-06-01"
        )
        assert historical[0]["source_url"] == "https://example.gov.in/guidelines-2020"
        current = rescore(
            "scheme guidelines", [future, old_valid], _cls(), as_of_date="2028-06-01"
        )
        assert current[0]["source_url"] == "https://example.gov.in/guidelines-2027"

    def test_legacy_year_tiebreak_preserved(self):
        # No validity record: legacy URL-year behavior unchanged.
        new_url = _result(
            "https://example.gov.in/scheme/2026/details",
            "Scheme details",
            "scheme text",
            validity=None,
            bm25=1.0,
        )
        old_url = _result(
            "https://example.gov.in/scheme/details",
            "Scheme details",
            "scheme text",
            validity=None,
            bm25=1.0,
        )
        assert freshness_bonus(new_url["source_url"], "STATUS", "status") == 0.08
        assert freshness_bonus(old_url["source_url"], "STATUS", "status") == 0.0

    def test_unknown_validity_never_penalized(self):
        assert (
            freshness_bonus(
                "https://example.gov.in/old-page",
                "INFORMATIONAL",
                "what is this scheme",
                validity={"supersession_status": UNKNOWN_STATUS},
                case={"case_date": "2026-10-04"},
            )
            == 0.0
        )
