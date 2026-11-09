"""Tests for Grievance Status Lookup and Field Validation enhancements."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.grievance.input_types import validate_field_value
from app.grievance.models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceSubCategory,
)
from app.grievance.status_lookup import GrievanceStatusLookup
from app.main import app


client = TestClient(app)


def test_status_lookup_with_string_reference():
    lookup = GrievanceStatusLookup()
    result = lookup.get_status_lookup("GRV-20261109-1234ABCD")
    assert result is not None
    assert "CPGRAMS" in result.portal_name
    assert "reference_number" in result.lookup_method
    assert "JanSahay" in result.disclaimer


def test_status_lookup_with_category_string():
    lookup = GrievanceStatusLookup()
    result = lookup.get_status_lookup("agriculture")
    assert result is not None
    assert "PMFBY" in result.portal_name


def test_status_lookup_with_draft_object():
    lookup = GrievanceStatusLookup()
    draft = GrievanceDraft(
        category=GrievanceCategory.COOPERATIVE,
        sub_category=GrievanceSubCategory.MEMBER_RIGHTS,
        title="PACS Dispute",
        description="Dispute over PACS membership",
        entities={},
        missing_fields=[],
        required_fields=[],
        optional_fields=[],
        jurisdiction="state",
        state="Maharashtra",
        department="Cooperation Department",
    )
    result = lookup.get_status_lookup(draft)
    assert result is not None
    assert "Registrar of Cooperative Societies" in result.portal_name


def test_grievance_status_endpoint():
    response = client.get("/grievances/GRV-20261109-TEST1234")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["is_official_submission"] is False
    assert "result" in data
    assert "CPGRAMS" in data["result"]["portal_name"]


def test_validate_field_numeric():
    # Valid numeric
    validate_field_value("ward_number", "42")
    validate_field_value("disputed_amount", "10,500")

    # Invalid numeric
    with pytest.raises(ValueError, match="must be a whole number"):
        validate_field_value("ward_number", "forty-two")


def test_validate_field_date():
    # Valid date
    validate_field_value("incident_date", "2024-05-15")
    validate_field_value("date_of_incident", "15/05/2024")

    # Invalid date format
    with pytest.raises(ValueError, match="valid date"):
        validate_field_value("incident_date", "yesterday")

    # Future incident date
    with pytest.raises(ValueError, match="cannot be in the future"):
        validate_field_value("date_of_incident", "2099-01-01")


def test_validate_field_phone():
    # Valid phones
    validate_field_value("mobile_number", "9876543210")
    validate_field_value("phone_number", "+91 9876543210")
    validate_field_value("contact_number", "09876543210")

    # Invalid phone (starts with 1)
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_field_value("mobile_number", "1234567890")

    # Invalid phone (wrong length)
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_field_value("mobile_number", "98765")
