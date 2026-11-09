"""Tests for narrative grievance classification.

Verifies that the GrievanceClassifier correctly handles narrative
complaints without explicit keyword matches. Regression tests for
the 7 failing examples from the classifier audit.
"""

import pytest
from app.grievance.classifier import GrievanceClassifier
from app.grievance.models import GrievanceCategory, GrievanceSubCategory


@pytest.fixture
def classifier():
    return GrievanceClassifier()


class TestNarrativeClassification:
    """Narrative complaints must be classified correctly."""

    def test_waste_piling_up(self, classifier):
        """'waste' should classify as MUNICIPAL/GARBAGE."""
        result = classifier.classify(
            "The waste is piling up in our neighborhood and it smells terrible"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.GARBAGE
        assert result.confidence >= 0.5

    def test_streetlight_not_working(self, classifier):
        """'streetlight' should classify as MUNICIPAL/STREET_LIGHT."""
        result = classifier.classify(
            "Streetlight on my road is not working for weeks"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.STREET_LIGHT
        assert result.confidence >= 0.5

    def test_drainage_blocked(self, classifier):
        """'drainage blocked' should classify as MUNICIPAL/DRAINAGE."""
        result = classifier.classify(
            "Drainage is blocked and water is logging everywhere"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.DRAINAGE
        assert result.confidence >= 0.5

    def test_potholes_on_road(self, classifier):
        """'potholes' should classify as MUNICIPAL/ROAD_DAMAGE."""
        result = classifier.classify(
            "There are potholes everywhere on the road, cars are getting damaged"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.ROAD_DAMAGE
        assert result.confidence >= 0.5

    def test_road_condition_terrible(self, classifier):
        """'road condition' should classify as MUNICIPAL/ROAD_DAMAGE."""
        result = classifier.classify(
            "The road condition is terrible, full of cracks and holes"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.ROAD_DAMAGE
        assert result.confidence >= 0.5

    def test_water_not_draining(self, classifier):
        """'not draining' should classify as MUNICIPAL/DRAINAGE."""
        result = classifier.classify(
            "Water is not draining from the street after rain"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.DRAINAGE
        assert result.confidence >= 0.5

    def test_garbage_collection_stopped(self, classifier):
        """'garbage collection' should classify as MUNICIPAL/GARBAGE."""
        result = classifier.classify(
            "Garbage collection has stopped in our area"
        )
        assert result.category == GrievanceCategory.MUNICIPAL
        assert result.sub_category == GrievanceSubCategory.GARBAGE
        assert result.confidence >= 0.5


class TestWordBoundaryMatching:
    """Short keywords (<=3 chars) must use word-boundary matching."""

    def test_rti_not_in_starting(self, classifier):
        """'rti' should not match inside 'starting'."""
        result = classifier.classify("I am starting my new job next week")
        assert result.category == GrievanceCategory.OTHER
        assert result.sub_category == GrievanceSubCategory.OTHER

    def test_fir_not_in_first(self, classifier):
        """'fir' should not match inside 'first'."""
        result = classifier.classify("This is the first time I am doing this")
        assert result.category != GrievanceCategory.POLICE

    def test_rti_matches_standalone(self, classifier):
        """'rti' should match when it's a standalone word."""
        result = classifier.classify("I filed an RTI application last month")
        assert result.category == GrievanceCategory.PUBLIC_SERVICE
        assert result.sub_category == GrievanceSubCategory.RTI_DELAY


class TestInsuranceNotAgriculture:
    """Live B6 regression: a general insurance-ombudsman complaint must NOT
    route to AGRICULTURE/PMFBY_CLAIM_DELAY merely for containing the bare
    words "insurance"/"claim". Gemini is disabled here to test the
    deterministic keyword layer in isolation."""

    def test_general_insurance_not_pmfby(self, classifier, monkeypatch):
        monkeypatch.setattr(classifier, "_gemini_enabled", False)
        result = classifier.classify(
            "The insurance company rejected my claim. Where can I complain "
            "now, and can I approach the insurance ombudsman?"
        )
        assert result.category != GrievanceCategory.AGRICULTURE
        assert result.sub_category != GrievanceSubCategory.PMFBY_CLAIM_DELAY
        # Low confidence routes to clarification, never a confident wrong authority.
        assert result.confidence < 0.5

    def test_pmfby_claim_still_agriculture(self, classifier):
        result = classifier.classify("My PMFBY crop insurance claim is delayed")
        assert result.category == GrievanceCategory.AGRICULTURE
        assert result.sub_category == GrievanceSubCategory.PMFBY_CLAIM_DELAY
        assert result.confidence >= 0.5

    def test_crop_insurance_claim_still_agriculture(self, classifier):
        result = classifier.classify("My crop insurance claim is delayed")
        assert result.category == GrievanceCategory.AGRICULTURE
        assert result.sub_category == GrievanceSubCategory.PMFBY_CLAIM_DELAY
