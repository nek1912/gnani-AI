"""P0-1 jurisdiction resolution + jurisdiction-first branch tests.

Covers: explicit Gujarat, Gujarati Gujarat query, district query, MSCS
query, Gujarat state-cooperative query, no-jurisdiction query, inherited
session state, conflicting signals, branch execution, anchor selection,
and jurisdiction metadata recording.
"""

from unittest.mock import patch

from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.service import WebDiscoveryService

_classifier = QueryClassifier()


def _item(url, title, text):
    return {
        "url": url,
        "title": title,
        "content": text,
        "raw_content": text,
        "score": 0.9,
        "favicon": None,
    }


_PMFBY_ITEMS = [
    _item(
        "https://pmfby.gov.in/guidelines",
        "PMFBY crop insurance Gujarat guidelines",
        "PMFBY crop insurance Gujarat guidelines for notified crops "
        "and premium subsidy. " * 10,
    ),
    _item(
        "https://agri.gujarat.gov.in/schemes",
        "Gujarat agriculture crop insurance schemes",
        "Gujarat agriculture crop insurance schemes and relief packages "
        "for farmers in Gujarat. " * 10,
    ),
]


class TestJurisdictionResolution:
    def test_gujarat_explicit(self):
        cls = _classifier.classify("Crop insurance in Gujarat for farmers")
        assert cls.state == "Gujarat"
        assert cls.jurisdiction == "state"
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_gujarati_gujarat_query(self):
        cls = _classifier.classify("ગુજરાતમાં પાક વીમા યોજના")
        assert cls.state == "Gujarat"
        assert cls.jurisdiction == "state"
        assert cls.jurisdiction_source == "explicit"

    def test_district_query(self):
        cls = _classifier.classify(
            "Crop insurance claim rejected in Junagadh, whom to complain?"
        )
        assert cls.district == "Junagadh"
        # District implies Gujarat even without the state word (subject default).
        assert cls.state == "Gujarat"
        assert cls.jurisdiction == "state"

    def test_district_gujarati_script(self):
        cls = _classifier.classify("જૂનાગઢમાં પાક નુકસાન સહાય")
        assert cls.district == "Junagadh"
        assert cls.state == "Gujarat"

    def test_mscs_query(self):
        cls = _classifier.classify(
            "My society works in two states; who is the registrar?"
        )
        assert cls.society_type == "mscs"
        # MSCS has no state anchor.
        assert cls.state is None
        assert cls.jurisdiction == "central"

    def test_mscs_gets_no_subject_default(self):
        # Multi-state societies are central-jurisdiction by definition:
        # the safe subject default must not localize them to Gujarat.
        cls = _classifier.classify(
            "Multi-state cooperative society election rules"
        )
        assert cls.society_type == "mscs"
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.jurisdiction_source == "none"
        assert cls.assumed_state is False

    def test_mscs_keyword_query(self):
        cls = _classifier.classify(
            "How to register a multi-state cooperative society with CRCS?"
        )
        assert cls.society_type == "mscs"

    def test_gujarat_state_cooperative_query(self):
        # P1: a generic society-type cue with no state signal invents no
        # state — callers prefer abstention semantics over a guessed
        # Gujarat. The society-type signal itself is preserved.
        cls = _classifier.classify(
            "How do I file a dispute with the Board of Nominees?"
        )
        assert cls.society_type == "state_society"
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.jurisdiction_source == "none"
        assert cls.assumed_state is False

    def test_no_jurisdiction_general_query(self):
        cls = _classifier.classify("My electricity bill is wrong.")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.jurisdiction_source == "none"
        assert cls.assumed_state is False

    def test_no_signal_state_competent_subject_default(self):
        # P1: removed — an unspecified state no longer acquires Gujarat
        # merely because the domain is Gujarat-competent. No-signal
        # queries resolve to central jurisdiction with no invented
        # state (see test_jurisdiction_consistency_p1.py).
        cls = _classifier.classify("What is PMFBY?")
        assert cls.state is None
        assert cls.jurisdiction == "central"
        assert cls.jurisdiction_source == "none"
        assert cls.assumed_state is False

    def test_inherited_session_state(self):
        cls = _classifier.classify(
            "What is PMFBY?", default_state="Maharashtra"
        )
        assert cls.state == "Maharashtra"
        assert cls.jurisdiction == "state"
        assert cls.jurisdiction_source == "session"
        assert cls.assumed_state is True

    def test_explicit_beats_session_state(self):
        cls = _classifier.classify(
            "Crop insurance in Gujarat", default_state="Maharashtra"
        )
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"
        assert cls.assumed_state is False

    def test_conflicting_signals_first_wins(self):
        cls = _classifier.classify(
            "Compare Gujarat and Maharashtra crop insurance schemes"
        )
        # Deterministic first-match on STATE_KEYWORDS order.
        assert cls.state == "Gujarat"
        assert cls.jurisdiction_source == "explicit"

    def test_case_year_and_season(self):
        cls = _classifier.classify("KCC rules for 2026 kharif season")
        assert cls.case_year == 2026
        assert cls.season == "kharif"

    def test_no_case_time(self):
        cls = _classifier.classify("What is PMFBY?")
        assert cls.case_year is None
        assert cls.season is None


class TestAnchorDomains:
    def test_gujarat_anchors(self):
        cls = _classifier.classify("Crop insurance in Gujarat")
        anchors = WebDiscoveryService._anchor_domains_for(cls)
        assert anchors is not None
        assert "gov.in" in anchors
        assert "nic.in" in anchors
        assert any("gujarat" in d for d in anchors)

    def test_mscs_anchors_are_central(self):
        cls = _classifier.classify(
            "My society works in two states; who is the registrar?"
        )
        anchors = WebDiscoveryService._anchor_domains_for(cls)
        assert anchors is not None
        assert "crcs.gov.in" in anchors
        assert "cooperation.gov.in" in anchors
        assert not any("gujarat" in d for d in anchors)

    def test_general_query_has_no_jurisdiction_branch(self):
        cls = _classifier.classify("My electricity bill is wrong.")
        assert WebDiscoveryService._anchor_domains_for(cls) is None


class TestJurisdictionBranch:
    def _run_discover(self, query, classification=None):
        service = WebDiscoveryService()
        calls = []

        def fake_search_all(
            q, *, domain=None, state=None, max_results=20,
            chunks_per_source=3, include_domains=None,
            search_depth="advanced", include_raw_content=True,
            only_official=False, allow_domains=None, **kwargs,
        ):
            calls.append(
                {
                    "query": q,
                    "include_domains": include_domains,
                    "only_official": only_official,
                    "max_results": max_results,
                }
            )
            return list(_PMFBY_ITEMS)

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover(query, classification=classification)
        return result, calls

    def test_gujarat_query_runs_two_branches(self):
        result, calls = self._run_discover("Crop insurance in Gujarat")
        stage1 = [c for c in calls if c["only_official"] is True]
        # Primary + jurisdiction always; language branches may add more.
        assert len(stage1) >= 2
        primary, jurisdiction = stage1[0], stage1[1]
        assert len(primary["include_domains"]) > 15  # full OFFICIAL_DOMAINS
        assert primary["only_official"] is True
        assert any("gujarat" in d for d in jurisdiction["include_domains"])
        assert jurisdiction["only_official"] is True
        assert jurisdiction["max_results"] <= 20
        assert result["discovery_metadata"]["branches_run"][:2] == [
            "primary", "jurisdiction",
        ]
        assert set(result["discovery_metadata"]["branch_counts"]) >= {
            "primary", "jurisdiction",
        }

    def test_general_query_runs_single_branch(self):
        result, calls = self._run_discover("My electricity bill is wrong.")
        stage1 = [c for c in calls if c["only_official"] is True]
        assert len(stage1) == 1
        assert result["discovery_metadata"]["branches_run"] == ["primary"]

    def test_mscs_query_uses_central_anchors(self):
        result, calls = self._run_discover(
            "My society works in two states; who is the registrar?"
        )
        stage1 = [c for c in calls if c["only_official"] is True]
        assert len(stage1) == 2
        jurisdiction = stage1[1]
        assert "crcs.gov.in" in jurisdiction["include_domains"]
        assert "jurisdiction" in result["discovery_metadata"]["branches_run"]

    def test_branch_merge_dedups_urls(self):
        # Both branches return the same items; merged pool keeps one copy.
        result, _ = self._run_discover("Crop insurance in Gujarat")
        urls = [r.get("source_url") for r in result["results"]]
        assert len(urls) == len(set(urls))

    def test_jurisdiction_metadata_recorded(self):
        result, _ = self._run_discover(
            "Crop insurance claim in Junagadh district"
        )
        meta = result["discovery_metadata"]["jurisdiction"]
        assert meta["state"] == "Gujarat"
        assert meta["district"] == "Junagadh"
        assert meta["source"] in ("explicit", "session", "subject_default")
        assert "assumed" in meta
        assert result["classification"]["district"] == "Junagadh"
        for chunk in result["results"]:
            assert chunk["district"] == "Junagadh"
            assert "jurisdiction_assumed" in chunk

    def test_per_source_jurisdiction_truthful(self):        # P1 audit correction: per-source jurisdiction comes from the
        # publisher (mandate map), not from blanket classification
        # stamping. Central publishers stay central even for state
        # queries; Gujarat publishers stay Gujarat. Blanket stamping
        # made wrong-state evidence indistinguishable and the
        # gate/recovery jurisdiction checks vacuous.
        result, _ = self._run_discover(
            "Crop insurance claim in Junagadh district"
        )
        by_url = {c.get("source_url"): c for c in result["results"]}
        pmfby = by_url.get("https://pmfby.gov.in/guidelines")
        gujarat = by_url.get("https://agri.gujarat.gov.in/schemes")
        assert pmfby is not None and gujarat is not None
        assert pmfby["jurisdiction"] == "central"
        assert pmfby["state"] is None
        assert gujarat["jurisdiction"] == "state"
        assert gujarat["state"] == "Gujarat"

    def test_district_word_does_not_hijack_domain(self):
        # Audit fix: the "ict" substring inside "district" used to route
        # any district query to the unsupported pacs_computerization
        # domain, causing wrong abstentions.
        cls = _classifier.classify(
            "No response from the district agriculture office for 3 months"
        )
        assert cls.domain == "agriculture"
        assert cls.district is None or isinstance(cls.district, str)

    def test_branch_failure_isolated(self):
        service = WebDiscoveryService()
        real_items = list(_PMFBY_ITEMS)

        def fake_search_all(q, **kwargs):
            include = kwargs.get("include_domains") or []
            if "gujaratindia.gov.in" in include:
                raise RuntimeError("jurisdiction provider boom")
            return list(real_items)

        with patch.object(
            WebDiscoveryService, "_search_all", side_effect=fake_search_all
        ):
            result = service.discover("Crop insurance in Gujarat")
        # Primary branch evidence survives the jurisdiction branch failure.
        assert len(result["results"]) > 0
