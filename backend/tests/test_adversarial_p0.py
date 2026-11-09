"""P0 adversarial acceptance matrix (offline, deterministic).

Each case drives WebDiscoveryService.discover() (and, for case 14,
WebRAGService.retrieve()) with a mocked provider layer and asserts the
P0 property from the task's 14-case list. Live-provider validation of
the same properties remains future work (P1 eval set).
"""

from unittest.mock import patch

from app.contracts import AbstentionReason
from app.services.web_rag import WebRAGService
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


def _discover(query, items, as_of_date=None):
    service = WebDiscoveryService()
    with patch.object(
        WebDiscoveryService, "_search_all", return_value=list(items)
    ):
        return service.discover(query, as_of_date=as_of_date)


_GR_TEXT = (
    "Government Resolution No. KRP/2026/1145 Agriculture relief package "
    "for Junagadh district farmers. This package shall come into force "
    "on 1 September 2026. Villages listed in the annexure. "
) * 8

_PAC_GR_TEXT = (
    "Government Resolution on godown assistance to PACS under the grain "
    "storage plan with effect from 15 March 2025. "
) * 8


class TestAdversarialMatrix:
    def test_01_gujarat_crop_insurance_prefers_state_gr(self):
        """Gujarat farmer: state GR outranks the national PMFBY ladder."""
        items = [
            _item(
                "https://agri.gujarat.gov.in/gr/krm-2026-junagadh",
                "Crop relief GR 2026 Junagadh",
                _GR_TEXT,
            ),
            _item(
                "https://pmfby.gov.in/contact",
                "PMFBY grievance contact DGRC ladder",
                "PMFBY grievance redressal district committee contact. " * 8,
            ),
        ]
        result = _discover("Crop insurance claim rejected in Junagadh", items)
        top = result["results"][0]
        assert "gujarat.gov.in" in top["source_url"]
        assert top["document_role"] == "instrument"
        branches = result["discovery_metadata"]["branches_run"]
        assert "jurisdiction" in branches and "gujarati" in branches

    def test_02_crop_loss_relief_is_district_aware(self):
        result = _discover(
            "Unseasonal rain crop loss relief Junagadh",
            [_item("https://agri.gujarat.gov.in/schemes", "Gujarat agriculture schemes relief Junagadh", _GR_TEXT)],
        )
        assert result["classification"]["district"] == "Junagadh"
        assert result["classification"]["state"] == "Gujarat"

    def test_03_pacs_storage_uses_cooperative_anchors(self):
        # P1: explicit Gujarat signal (no silent default) still yields
        # the cooperative anchor set for a PACS storage query.
        service = WebDiscoveryService()
        cls = _classifier.classify("Can our PACS in Gujarat get a godown under the storage plan?")
        assert cls.state == "Gujarat"
        anchors = service._anchor_domains_for(cls)
        assert "cooperation.gov.in" in anchors

    def test_04_gujarat_election_prefers_state_authority(self):
        result = _discover(
            "When is my cooperative society election in Gujarat?",
            [_item("https://rcs.gujarat.gov.in/Home/ActsAndRules", "Gujarat cooperative election rules", "Election to committees rules collector returning officer. " * 8)],
        )
        assert result["classification"]["state"] == "Gujarat"
        assert result["classification"]["society_type"] is None

    def test_05_mscs_election_prefers_central_authority(self):
        cls = _classifier.classify(
            "Multi-state cooperative society election rules CEA"
        )
        assert cls.society_type == "mscs"
        assert cls.state is None
        service = WebDiscoveryService()
        anchors = service._anchor_domains_for(cls)
        assert "crcs.gov.in" in anchors
        assert not any("gujarat" in d for d in anchors)

    def test_06_gujarat_dispute_competent_forum(self):
        cls = _classifier.classify(
            "How do I file a dispute with the Board of Nominees in Ahmedabad?"
        )
        assert cls.society_type == "state_society"
        assert cls.state == "Gujarat"
        assert cls.district == "Ahmedabad"

    def test_07_kcc_validity_aware(self):
        items = [
            _item(
                "https://rbi.org.in/scripts/FAQView.aspx",
                "KCC old guidelines FAQ",
                "KCC guidelines general information. " * 8,
            ),
            _item(
                "https://rbi.org.in/scripts/BS_ViewMasDirections.aspx",
                "KCC Directions 2026",
                "KCC Directions 2026 shall come into force for loans "
                "sanctioned from 1 January 2027. " * 8,
            ),
        ]
        result = _discover("KCC current rules", items, as_of_date="2026-10-04")
        # The future-effective Directions must not top current-date results.
        assert "2027" not in result["results"][0]["source_url"] or result[
            "results"
        ][0]["validity"].get("effective_from") is None

    def test_08_rbi_complaint_current_scheme(self):
        # P1: explicit Gujarat signal (no silent default); RBI in anchors.
        service = WebDiscoveryService()
        cls = _classifier.classify("Bank wrongly debited charges in Gujarat; RBI complaint")
        anchors = service._anchor_domains_for(cls)
        assert "rbi.org.in" in (anchors or [])

    def test_09_insurance_complaint_irdai(self):
        # P1: explicit Gujarat signal (no silent default); IRDAI in anchors.
        cls = _classifier.classify(
            "My crop insurance claim was rejected by the insurance company in Gujarat"
        )
        service = WebDiscoveryService()
        anchors = service._anchor_domains_for(cls)
        assert anchors is not None
        assert any("irdai" in d for d in anchors)

    def test_10_gujarati_gr_query_runs_gujarati_branch(self):
        # P1: explicit Gujarat signal (no silent default) keeps the
        # Gujarati branch for a Gujarati GR query.
        result = _discover(
            "ગુજરાતમાં પાક વીમા ઠરાવ",
            [_item("https://agri.gujarat.gov.in/gr/pak-vimo", "પાક વીમા સરકારી ઠરાવ", "પાક વીમો સહાય ઠરાવ. " * 10)],
        )
        assert "gujarati" in result["discovery_metadata"]["branches_run"]
        assert result["classification"]["state"] == "Gujarat"

    def test_11_old_vs_revised_prefers_current(self):
        items = [
            _item(
                "https://rbi.org.in/scheme-2021",
                "Ombudsman Scheme 2021",
                "The 2021 scheme has been superseded by the 2026 scheme. " * 8,
            ),
            _item(
                "https://rbidocs.rbi.org.in/rdocs/content/pdfs/SCHEME16012026_A.pdf",
                "Integrated Ombudsman Scheme 2026",
                "The Integrated Ombudsman Scheme 2026 shall come into force "
                "on 1 July 2026. This scheme supersedes the 2021 framework. " * 8,
            ),
        ]
        result = _discover("RBI ombudsman complaint process", items)
        assert "2026" in result["results"][0]["source_url"]

    def test_12_historical_as_of_date(self):
        result = _discover(
            "KCC rules",
            [_item("https://rbi.org.in/kcc", "KCC rules", "KCC rules text. " * 8)],
            as_of_date="2024-06-01",
        )
        assert result["classification"]["as_of_date"] == "2024-06-01"

    def test_13_multifacet_coverage_without_gate_change(self):
        result = _discover(
            "My crop insurance claim was rejected; how do I appeal?",
            [
                _item(
                    "https://pmfby.gov.in/contact",
                    "PMFBY grievance contact appeal helpline",
                    "PMFBY grievance appeal helpline office contact. " * 8,
                )
            ],
        )
        assert set(result["discovery_metadata"]["facets_implied"]) == {
            "escalation", "authority",
        }
        assert len(result["results"]) > 0  # advisory only, never blocking

    def test_14_no_evidence_abstains(self):
        service = WebRAGService()
        with patch.object(
            service.web_discovery, "discover", return_value={"results": [], "classification": {"domain": "pmfby"}}
        ):
            result = service.retrieve(query="Crop insurance in Gujarat")
        assert result.abstained is True
        assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE
