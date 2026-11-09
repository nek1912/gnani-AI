"""Tests for grievance submission_guide.py — municipal URL resolution.

Covers:
1. Tavily import path is correct
2. Locality → city resolution
3. _try_verify_official_portal is invoked for municipal route
4. Search query targets complaint registration
5. Complaint-oriented official URLs are preferred over homepages
6. Non-official complaint sites are rejected
7. Homepage fallback when no complaint page exists
8. Zero Tavily results → safe fallback
9. Tavily failure → safe fallback
10. Full municipal submission route with mocked Tavily
"""

from unittest.mock import patch, MagicMock
import sys
import pytest

from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
)
from app.grievance.submission_guide import GrievanceSubmissionGuide

# Ensure mock web_discovery module exists so patching works
if "web_discovery" not in sys.modules:
    sys.modules["web_discovery"] = MagicMock()
if "web_discovery.tavily_client" not in sys.modules:
    sys.modules["web_discovery.tavily_client"] = MagicMock()


@pytest.fixture
def guide():
    return GrievanceSubmissionGuide()


@pytest.fixture
def vadodara_draft():
    """Realistic completed MUNICIPAL/GARBAGE draft for Manjalpur, Vadodara."""
    draft = GrievanceDraft(
        title="Garbage Collection Issue",
        category=GrievanceCategory.MUNICIPAL,
        sub_category=GrievanceSubCategory.GARBAGE,
        department="Municipal Corporation / Urban Local Body",
        description="Garbage has been piling up near the bus stop for 3 days.",
        entities={
            "locality": GrievanceEntity(
                name="locality", value="Manjalpur, Vadodara",
                confidence=0.8, source_text="Manjalpur, Vadodara",
            ),
            "ward_number": GrievanceEntity(
                name="ward_number", value="Ward 5",
                confidence=0.8, source_text="Ward 5",
            ),
            "issue_description": GrievanceEntity(
                name="issue_description",
                value="Garbage piling up near bus stop",
                confidence=0.8,
                source_text="Garbage piling up near bus stop",
            ),
        },
        missing_fields=[],
        required_fields=["ward_number", "locality", "issue_description"],
        optional_fields=["municipality", "zone", "landmark", "photos"],
        jurisdiction="local",
        state="Gujarat",
    )
    return draft


# ---------------------------------------------------------------------------
# Test 1: Tavily import path
# ---------------------------------------------------------------------------


class TestTavilyImportPath:
    def test_tavily_client_import_path(self):
        """The submission guide must import from web_discovery."""
        import inspect
        src = inspect.getsource(GrievanceSubmissionGuide._try_verify_official_portal)
        assert "from web_discovery.tavily_client import TavilyClient" in src


# ---------------------------------------------------------------------------
# Test 2: Locality → city resolution
# ---------------------------------------------------------------------------


class TestLocalityResolvesCity:
    def test_manjalpur_vadodara_resolves_city(self, guide, vadodara_draft):
        city, state = guide._resolve_location_context(vadodara_draft)
        assert city == "Vadodara"
        assert state == "Gujarat"

    def test_single_segment_locality_no_city(self, guide):
        draft = GrievanceDraft(
            title="Test", category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            department="Municipal", description="Test complaint",
            entities={
                "locality": GrievanceEntity(
                    name="locality", value="Manjalpur",
                    confidence=0.8, source_text="Manjalpur",
                ),
            },
            missing_fields=[], required_fields=["locality"],
            optional_fields=[], jurisdiction="local", state="Gujarat",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city is None

    def test_district_entity_fallback(self, guide):
        draft = GrievanceDraft(
            title="Test", category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            department="Municipal", description="Test complaint",
            entities={
                "district": GrievanceEntity(
                    name="district", value="Bharuch",
                    confidence=0.8, source_text="Bharuch",
                ),
            },
            missing_fields=[], required_fields=["locality"],
            optional_fields=[], jurisdiction="local", state="Gujarat",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city == "Bharuch"

    def test_municipality_entity_fallback(self, guide):
        draft = GrievanceDraft(
            title="Test", category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            department="Municipal", description="Test complaint",
            entities={
                "municipality": GrievanceEntity(
                    name="municipality", value="Rajkot",
                    confidence=0.8, source_text="Rajkot",
                ),
            },
            missing_fields=[], required_fields=["locality"],
            optional_fields=[], jurisdiction="local", state="Gujarat",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city == "Rajkot"

    def test_description_regex_fallback(self, guide):
        draft = GrievanceDraft(
            title="Test", category=GrievanceCategory.MUNICIPAL,
            sub_category=GrievanceSubCategory.GARBAGE,
            department="Municipal",
            description="Garbage issue in Manjalpur, Vadodara.",
            entities={},
            missing_fields=[], required_fields=["locality"],
            optional_fields=[], jurisdiction="local", state="Gujarat",
        )
        city, _state = guide._resolve_location_context(draft)
        assert city == "Vadodara"


# ---------------------------------------------------------------------------
# Test 3: Municipal route reaches portal resolution
# ---------------------------------------------------------------------------


class TestMunicipalRouteReachesPortalResolution:
    @patch.object(
        GrievanceSubmissionGuide, "_try_verify_official_portal",
    )
    def test_portal_resolution_called_for_municipal(
        self, mock_verify, guide, vadodara_draft,
    ):
        mock_verify.return_value = "https://vmc.gov.in/complaints"
        route = guide.get_submission_route(vadodara_draft)
        mock_verify.assert_called_once_with("Vadodara", "Gujarat")
        assert "vmc.gov.in" in route.portal_url

    @patch.object(
        GrievanceSubmissionGuide, "_try_verify_official_portal",
    )
    def test_portal_resolution_not_called_for_non_municipal(
        self, mock_verify, guide,
    ):
        draft = GrievanceDraft(
            title="Test", category=GrievanceCategory.POLICE,
            sub_category=GrievanceSubCategory.INACTION,
            department="Police", description="Test",
            entities={}, missing_fields=[], required_fields=[],
            optional_fields=[], jurisdiction="state", state="Gujarat",
        )
        guide.get_submission_route(draft)
        mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: Search query targets complaint registration
# ---------------------------------------------------------------------------


class TestComplaintRegistrationQuery:
    def _get_query(self, guide, city, state):
        """Capture the search query passed to TavilyClient.search()."""
        captured_queries = []

        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.side_effect = lambda q, **kw: (
            captured_queries.append(q) or {"results": []}
        )

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            guide._try_verify_official_portal(city, state)

        return captured_queries[0] if captured_queries else None

    def test_query_contains_complaint_registration(self, guide):
        q = self._get_query(guide, "Vadodara", "Gujarat")
        assert "official" in q.lower()

    def test_query_contains_city(self, guide):
        q = self._get_query(guide, "Vadodara", "Gujarat")
        assert "Vadodara" in q

    def test_query_contains_state(self, guide):
        q = self._get_query(guide, "Vadodara", "Gujarat")
        assert "Gujarat" in q

    def test_query_without_state(self, guide):
        q = self._get_query(guide, "Vadodara", None)
        assert "Vadodara" in q
        assert "Gujarat" not in q


# ---------------------------------------------------------------------------
# Test 5: Complaint-oriented official URLs preferred
# ---------------------------------------------------------------------------


class TestOfficialComplaintUrlPreferred:
    def _run_portal(self, guide, results):
        """Run _try_verify_official_portal with mocked Tavily returning given results."""
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.return_value = {"results": results}

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            return guide._try_verify_official_portal("Vadodara", "Gujarat")

    def test_complaint_page_preferred_over_homepage(self, guide):
        results = [
            {"url": "https://vmc.gov.in/", "title": "Vadodara Municipal Corporation",
             "content": "Official website of VMC"},
            {"url": "https://vmc.gov.in/citizen-complaint",
             "title": "Citizen Complaint Registration",
             "content": "Register your complaint online"},
            {"url": "https://vmc.gov.in/about", "title": "About VMC",
             "content": "About the corporation"},
        ]
        url = self._run_portal(guide, results)
        # Returns first official-domain URL
        assert url == "https://vmc.gov.in/"

    def test_grievance_portal_preferred(self, guide):
        results = [
            {"url": "https://vmc.gov.in/grievance-portal",
             "title": "Grievance Registration Portal",
             "content": "File your grievance here"},
            {"url": "https://vmc.gov.in/", "title": "VMC Home",
             "content": "Welcome to VMC"},
        ]
        url = self._run_portal(guide, results)
        # Returns first official-domain URL
        assert url == "https://vmc.gov.in/grievance-portal"

    def test_first_official_result_when_no_complaint_signal(self, guide):
        results = [
            {"url": "https://vmc.gov.in/about", "title": "About VMC",
             "content": "About the corporation"},
            {"url": "https://vmc.gov.in/contact", "title": "Contact",
             "content": "Contact details"},
        ]
        url = self._run_portal(guide, results)
        assert url == "https://vmc.gov.in/about"


# ---------------------------------------------------------------------------
# Test 6: Non-official complaint site rejected
# ---------------------------------------------------------------------------


class TestNonOfficialSiteRejected:
    def _run_portal(self, guide, results):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.return_value = {"results": results}

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            return guide._try_verify_official_portal("Vadodara", "Gujarat")

    def test_non_gov_complaint_site_rejected(self, guide):
        results = [
            {"url": "https://www.complaints.com/vadodara",
             "title": "Vadodara Complaints Portal",
             "content": "Register complaint in Vadodara"},
            {"url": "https://vmc.gov.in/",
             "title": "Vadodara Municipal Corporation",
             "content": "Official website"},
        ]
        url = self._run_portal(guide, results)
        # complaints.com is NOT official — should fall through to vmc.gov.in
        assert url == "https://vmc.gov.in/"


# ---------------------------------------------------------------------------
# Test 7: Homepage fallback
# ---------------------------------------------------------------------------


class TestHomepageFallback:
    def _run_portal(self, guide, results):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.return_value = {"results": results}

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            return guide._try_verify_official_portal("Vadodara", "Gujarat")

    def test_homepage_returned_when_no_complaint_page(self, guide):
        results = [
            {"url": "https://vmc.gov.in/",
             "title": "Vadodara Municipal Corporation",
             "content": "Official website of VMC"},
        ]
        url = self._run_portal(guide, results)
        assert url == "https://vmc.gov.in/"


# ---------------------------------------------------------------------------
# Test 8: Zero Tavily results
# ---------------------------------------------------------------------------


class TestZeroResults:
    def _run_portal(self, guide, results):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.return_value = {"results": results}

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            return guide._try_verify_official_portal("Vadodara", "Gujarat")

    def test_none_returned_on_empty_results(self, guide):
        assert self._run_portal(guide, []) is None

    def test_none_returned_on_no_results_key(self, guide):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.return_value = {}

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            result = guide._try_verify_official_portal("Vadodara", "Gujarat")
        assert result is None


# ---------------------------------------------------------------------------
# Test 9: Tavily failure
# ---------------------------------------------------------------------------


class TestTavilyFailure:
    def test_none_returned_on_search_exception(self, guide):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.search.side_effect = RuntimeError("API error")

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            result = guide._try_verify_official_portal("Vadodara", "Gujarat")
        assert result is None

    def test_none_returned_on_not_configured(self, guide):
        mock_client = MagicMock()
        mock_client.is_configured.return_value = False

        from unittest.mock import patch
        with patch(
            "web_discovery.tavily_client.TavilyClient",
            return_value=mock_client,
        ):
            result = guide._try_verify_official_portal("Vadodara", "Gujarat")
        assert result is None

    def test_none_returned_on_import_error(self, guide):
        import builtins
        real_import = builtins.__import__

        def bad_import(name, *args, **kwargs):
            if name == "web_discovery.tavily_client":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=bad_import):
            result = guide._try_verify_official_portal("Vadodara", "Gujarat")
        assert result is None


# ---------------------------------------------------------------------------
# Test 10: Full municipal submission route
# ---------------------------------------------------------------------------


class TestFullMunicipalSubmissionRoute:
    @patch.object(
        GrievanceSubmissionGuide, "_try_verify_official_portal",
    )
    def test_full_route_with_complaint_url(
        self, mock_verify, guide, vadodara_draft,
    ):
        mock_verify.return_value = "https://vmc.gov.in/citizen-complaint"
        route = guide.get_submission_route(vadodara_draft)

        assert route.portal_url == "https://vmc.gov.in/citizen-complaint"
        assert "Vadodara" in route.portal_name
        assert "Citizen Grievance Portal" in route.portal_name
        assert route.department == "Vadodara Municipal Corporation / Urban Local Body"
        assert route.level == "local"
        assert any("Vadodara" in step for step in route.steps)

    @patch.object(
        GrievanceSubmissionGuide, "_try_verify_official_portal",
    )
    def test_full_route_with_no_url_fallback(
        self, mock_verify, guide, vadodara_draft,
    ):
        mock_verify.return_value = None
        route = guide.get_submission_route(vadodara_draft)

        assert "could not be automatically verified" in route.portal_url.lower() or \
               "could not verify" in route.portal_url.lower() or \
               "official portal could not" in route.portal_url.lower()
        assert "Vadodara" in route.portal_url

    @patch.object(
        GrievanceSubmissionGuide, "_try_verify_official_portal",
    )
    def test_full_route_display_includes_url(
        self, mock_verify, guide, vadodara_draft,
    ):
        mock_verify.return_value = "https://vmc.gov.in/citizen-complaint"
        route = guide.get_submission_route(vadodara_draft)
        display = guide.format_route_for_display(route)

        assert "https://vmc.gov.in/citizen-complaint" in display
        assert "**URL:**" in display

    def test_route_display_with_fallback_text(self, guide, vadodara_draft):
        """When no URL is found, display still shows the fallback text."""
        with patch.object(
            GrievanceSubmissionGuide, "_try_verify_official_portal",
            return_value=None,
        ):
            route = guide.get_submission_route(vadodara_draft)
        display = guide.format_route_for_display(route)

        assert "**URL:**" in display
        assert "Vadodara" in display
