
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import GrievanceEntity, GrievanceSubCategory


@dataclass
class ExtractionResult:
    """Result of entity extraction."""

    entities: dict[str, GrievanceEntity]
    raw_extractions: dict[str, list[str]]


class GrievanceEntityExtractor:
    """Extracts structured entities from grievance description."""

    PATTERNS = {
        "date": [
            r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
            r"\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})\b",
            r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4})\b",
            r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})\b",
        ],
        "reference_number": [
            r"\b([A-Z]{2,5}[-/]\d{4,10})\b",
            r"\b(\d{10,15})\b",
            r"\b([A-Z]{1,3}\d{6,12})\b",
        ],
        "phone": [
            r"\b(\+91[\s-]?\d{10})\b",
            r"\b(\d{10})\b",
        ],
        "email": [
            r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b",
        ],
        "aadhaar": [
            r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b",
        ],
        "pan": [
            r"\b([A-Z]{5}\d{4}[A-Z]{1})\b",
        ],
        "account_number": [
            r"\b(?:account|a/c|ac)\s*(?:no|number|#)?[:\s]*(\d{9,18})\b",
        ],
        "consumer_number": [
            r"\bconsumer\s*(?:no\.?|number|#|id)?\s*(?:is\s*)?[:\-]?\s*([A-Za-z0-9\-/]{4,20})\b",
        ],
        "meter_number": [
            r"\bmeter\s*(?:no\.?|number|#|id)?\s*(?:is\s*)?[:\-]?\s*([A-Za-z0-9\-/]{4,20})\b",
        ],
        "ifsc": [
            r"\b([A-Z]{4}0[A-Z0-9]{6})\b",
        ],
        "pincode": [
            r"\b(\d{6})\b",
        ],
        "amount": [
            r"(?:rs\.?|inr|₹)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
            r"(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:rupees|rs\.?|inr|₹)",
        ],
    }

    SUBCATEGORY_ENTITIES = {
        GrievanceSubCategory.RTI_DELAY: {
            "required": ["rti_application_number", "date_of_application", "department"],
            "optional": ["applicant_name", "address", "phone", "email"],
        },
        GrievanceSubCategory.CERTIFICATE_DELAY: {
            "required": ["certificate_type", "application_number", "date_of_application", "issuing_authority"],
            "optional": ["applicant_name", "address", "phone"],
        },
        GrievanceSubCategory.PENSION_DELAY: {
            "required": ["pension_type", "ppo_number", "bank_account", "bank_name"],
            "optional": ["pensioner_name", "aadhaar", "phone", "address"],
        },
        GrievanceSubCategory.SCHEME_BENEFIT_DENIED: {
            "required": ["scheme_name", "application_id", "date_of_application"],
            "optional": ["beneficiary_name", "aadhaar", "phone", "address", "bank_account"],
        },
        GrievanceSubCategory.FIR_REFUSAL: {
            "required": ["police_station", "date_of_incident", "incident_description"],
            "optional": ["complainant_name", "accused_details", "witnesses", "evidence"],
        },
        GrievanceSubCategory.HARASSMENT: {
            "required": ["police_station", "officer_details", "incident_description", "date_of_incident"],
            "optional": ["complainant_name", "witnesses", "evidence", "medical_report"],
        },
        GrievanceSubCategory.INACTION: {
            "required": ["police_station", "complaint_number", "date_of_complaint", "incident_description"],
            "optional": ["complainant_name", "accused_details", "followup_dates"],
        },
        GrievanceSubCategory.CORRUPTION: {
            "required": ["department", "officer_name", "incident_description", "date_of_incident", "amount_involved"],
            "optional": ["complainant_name", "evidence", "witnesses"],
        },
        GrievanceSubCategory.LAND_RECORD_ERROR: {
            "required": ["district", "tehsil", "village", "survey_number", "error_description"],
            "optional": ["owner_name", "khata_number", "patta_number", "document_reference"],
        },
        GrievanceSubCategory.MUTATION_DELAY: {
            "required": ["district", "tehsil", "village", "survey_number", "application_number", "date_of_application"],
            "optional": ["applicant_name", "previous_owner", "mutation_type"],
        },
        GrievanceSubCategory.COMPENSATION_DELAY: {
            "required": ["project_name", "district", "village", "survey_number", "award_amount"],
            "optional": ["land_owner_name", "award_date", "bank_account"],
        },
        GrievanceSubCategory.GARBAGE: {
            "required": ["ward_number", "city", "locality", "issue_description"],
            "optional": ["municipality", "zone", "landmark", "photos"],
        },
        GrievanceSubCategory.DRAINAGE: {
            "required": ["ward_number", "city", "locality", "issue_description"],
            "optional": ["municipality", "zone", "landmark", "duration"],
        },
        GrievanceSubCategory.STREET_LIGHT: {
            "required": ["ward_number", "city", "locality", "pole_number_or_location"],
            "optional": ["municipality", "zone", "duration"],
        },
        GrievanceSubCategory.BUILDING_PERMIT: {
            "required": ["municipality", "ward_number", "plot_number", "application_number", "date_of_application"],
            "optional": ["applicant_name", "building_type", "architect_name"],
        },
        GrievanceSubCategory.PROPERTY_TAX: {
            "required": ["municipality", "ward_number", "property_id", "assessment_year"],
            "optional": ["owner_name", "property_address", "amount_paid", "payment_date"],
        },
        GrievanceSubCategory.ROAD_DAMAGE: {
            "required": ["ward_number", "city", "locality", "issue_description"],
            "optional": ["municipality", "zone", "landmark", "photos"],
        },
        GrievanceSubCategory.BILLING_DISPUTE: {
            "required": ["consumer_number", "billing_month", "disputed_amount", "discom_name"],
            "optional": ["consumer_name", "address", "meter_number", "previous_bill_amount"],
        },
        GrievanceSubCategory.METER_FAULT: {
            "required": ["consumer_number", "meter_number", "discom_name", "fault_description"],
            "optional": ["consumer_name", "address", "date_noticed"],
        },
        GrievanceSubCategory.NEW_CONNECTION_DELAY: {
            "required": ["application_number", "date_of_application", "discom_name", "connection_type"],
            "optional": ["applicant_name", "address", "load_required", "category"],
        },
        GrievanceSubCategory.POWER_CUT: {
            "required": ["consumer_number", "area", "discom_name", "frequency", "duration"],
            "optional": ["consumer_name", "feeder_name", "complaint_number"],
        },
        GrievanceSubCategory.SUPPLY_ISSUE: {
            "required": ["consumer_number", "area", "water_board_name", "issue_description"],
            "optional": ["consumer_name", "address", "duration", "timing"],
        },
        GrievanceSubCategory.QUALITY_ISSUE: {
            "required": ["consumer_number", "area", "water_board_name", "quality_description"],
            "optional": ["consumer_name", "address", "lab_report", "date_noticed"],
        },
        GrievanceSubCategory.BILLING_DISPUTE_WATER: {
            "required": ["consumer_number", "billing_month", "disputed_amount", "water_board_name"],
            "optional": ["consumer_name", "address", "meter_number"],
        },
        GrievanceSubCategory.NEW_CONNECTION_DELAY_WATER: {
            "required": ["application_number", "date_of_application", "water_board_name", "connection_type"],
            "optional": ["applicant_name", "address", "category"],
        },
        GrievanceSubCategory.LICENCE_DELAY: {
            "required": ["rto_office", "application_number", "date_of_application", "licence_type"],
            "optional": ["applicant_name", "learner_licence_number", "test_date"],
        },
        GrievanceSubCategory.PERMIT_ISSUE: {
            "required": ["rto_office", "vehicle_number", "permit_type", "application_number"],
            "optional": ["owner_name", "vehicle_type", "route"],
        },
        GrievanceSubCategory.BUS_SERVICE: {
            "required": ["depot", "route_number", "issue_description", "date_time"],
            "optional": ["bus_number", "driver_conductor_details", "ticket_number"],
        },
        GrievanceSubCategory.HOSPITAL_NEGLIGENCE: {
            "required": ["hospital_name", "date_of_incident", "incident_description", "department"],
            "optional": ["patient_name", "doctor_name", "medical_records", "witnesses"],
        },
        GrievanceSubCategory.MEDICINE_SHORTAGE: {
            "required": ["hospital_name", "medicine_name", "date_noticed"],
            "optional": ["patient_name", "prescription", "alternative_suggested"],
        },
        GrievanceSubCategory.AMBULANCE_DELAY: {
            "required": ["ambulance_number_or_service", "date_time", "pickup_location", "destination"],
            "optional": ["patient_name", "call_number", "response_time"],
        },
        GrievanceSubCategory.ADMISSION_DENIED: {
            "required": ["school_name", "class_applied", "date_of_application", "reason_given"],
            "optional": ["student_name", "parent_name", "rte_category", "address"],
        },
        GrievanceSubCategory.SCHOLARSHIP_DELAY: {
            "required": ["scheme_name", "application_id", "institute_name", "academic_year"],
            "optional": ["student_name", "aadhaar", "bank_account", "course"],
        },
        GrievanceSubCategory.MID_DAY_MEAL: {
            "required": ["school_name", "date", "issue_description"],
            "optional": ["student_name", "class", "meal_type"],
        },
        GrievanceSubCategory.RATION_CARD_DELAY: {
            "required": ["application_number", "date_of_application", "district", "card_type"],
            "optional": ["applicant_name", "family_members", "address", "aadhaar"],
        },
        GrievanceSubCategory.QUANTITY_SHORTAGE: {
            "required": ["fps_code", "fps_name", "commodity", "date", "entitled_quantity", "received_quantity"],
            "optional": ["ration_card_number", "beneficiary_name", "dealer_name"],
        },
        GrievanceSubCategory.QUALITY_COMPLAINT: {
            "required": ["fps_code", "fps_name", "commodity", "date", "quality_issue"],
            "optional": ["ration_card_number", "beneficiary_name", "sample_available"],
        },
        GrievanceSubCategory.PENSION_NOT_RECEIVED: {
            "required": ["pension_type", "ppo_number", "bank_account", "bank_name", "month_not_received"],
            "optional": ["pensioner_name", "aadhaar", "phone", "address"],
        },
        GrievanceSubCategory.SCHEME_EXCLUSION: {
            "required": ["scheme_name", "application_id", "date_of_application", "reason_for_exclusion"],
            "optional": ["applicant_name", "aadhaar", "category", "income_certificate"],
        },
        GrievanceSubCategory.WAGE_DISPUTE: {
            "required": ["employer_name", "employee_name", "period", "amount_claimed", "wage_type"],
            "optional": ["employer_address", "pf_number", "esi_number", "appointment_letter"],
        },
        GrievanceSubCategory.UNFAIR_TERMINATION: {
            "required": ["employer_name", "employee_name", "date_of_termination", "reason_given"],
            "optional": ["appointment_letter", "notice_period", "compensation_claimed", "witnesses"],
        },
        GrievanceSubCategory.SAFETY_VIOLATION: {
            "required": ["factory_name", "location", "violation_description", "date"],
            "optional": ["employee_name", "department", "injury_details", "inspection_report"],
        },
        GrievanceSubCategory.MEMBER_RIGHTS: {
            "required": ["society_name", "registration_number", "member_id", "issue_description"],
            "optional": ["member_name", "share_amount", "dividend_due", "meeting_date"],
        },
        GrievanceSubCategory.ELECTION_DISPUTE: {
            "required": ["society_name", "registration_number", "election_date", "dispute_description"],
            "optional": ["candidate_name", "voter_id", "returning_officer", "evidence"],
        },
        GrievanceSubCategory.FUND_MISUSE: {
            "required": ["society_name", "registration_number", "amount_involved", "description"],
            "optional": ["accused_office_bearer", "period", "audit_report", "evidence"],
        },
        GrievanceSubCategory.PMFBY_CLAIM_DELAY: {
            "required": ["farmer_name", "application_id", "crop", "season", "year", "insurance_company", "bank_name"],
            "optional": ["survey_number", "village", "block", "district", "sum_insured", "premium_paid"],
        },
        GrievanceSubCategory.SUBSIDY_DELAY: {
            "required": ["scheme_name", "application_id", "farmer_name", "component", "amount"],
            "optional": ["bank_account", "district", "block", "village", "date_of_application"],
        },
        GrievanceSubCategory.SEED_QUALITY: {
            "required": ["seed_name", "variety", "lot_number", "dealer_name", "issue_description"],
            "optional": ["farmer_name", "purchase_date", "bill_number", "certification_agency"],
        },
        GrievanceSubCategory.LOAN_REJECTION: {
            "required": ["bank_name", "branch", "application_number", "loan_type", "rejection_reason"],
            "optional": ["applicant_name", "loan_amount", "cibil_score", "income_proof"],
        },
        GrievanceSubCategory.FRAUD: {
            "required": ["bank_name", "account_number", "transaction_date", "amount", "fraud_type"],
            "optional": ["account_holder_name", "transaction_id", "merchant_name", "police_complaint"],
        },
        GrievanceSubCategory.SERVICE_DEFICIENCY: {
            "required": ["bank_name", "branch", "account_number", "service_type", "issue_description"],
            "optional": ["account_holder_name", "date", "reference_number", "officer_name"],
        },
    }

    def extract(self, text: str, sub_category: GrievanceSubCategory) -> ExtractionResult:
        """Extract entities from grievance text."""
        entities = {}
        raw_extractions = {}

        for entity_type, patterns in self.PATTERNS.items():
            matches = []
            for pattern in patterns:
                found = re.findall(pattern, text, re.IGNORECASE)
                matches.extend(found)
            if matches:
                raw_extractions[entity_type] = matches
                entities[entity_type] = GrievanceEntity(
                    name=entity_type,
                    value=matches[0],
                    confidence=0.8,
                    source_text=text[:200],
                )

        name_cue_pattern = (
            r"\b(?:my name is|name is|name:|i am|i'm|myself|"
            r"complainant(?:'s)? name is|applicant(?:'s)? name is)\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
        )
        name_match = re.search(name_cue_pattern, text, re.IGNORECASE)
        if name_match and "name" not in entities:
            value = name_match.group(1)
            entities["person_name"] = GrievanceEntity(
                name="person_name",
                value=value,
                confidence=0.75,
                source_text=text[:200],
            )

        location_keywords = ["district", "tehsil", "taluk", "block", "village", "city", "ward", "locality", "area", "colony", "sector"]
        dept_keywords = ["department", "office", "board", "corporation", "authority", "discom", "rto", "hospital", "school", "college", "university", "bank", "society", "company", "factory"]
        for keyword in location_keywords + dept_keywords:
            value = self._extract_keyword_value(keyword, text)
            if value:
                entities[f"{keyword}_name"] = GrievanceEntity(
                    name=f"{keyword}_name",
                    value=value,
                    confidence=0.7,
                    source_text=text[:200],
                )

        return ExtractionResult(entities=entities, raw_extractions=raw_extractions)

    # Generic continuation words that must never be treated as a real
    _GENERIC_FILLER_WORDS = {
        "number", "name", "is", "the", "a", "an", "of", "no", "not",
        "known", "unknown", "not sure", "not known",
    }

    # Words that signal a new location field starts here; extraction
    # must never swallow them into the value of a prior keyword.
    _LOCATION_BOUNDARY_WORDS = frozenset({
        "city", "town", "state", "district", "zone", "ward",
        "pincode", "locality", "landmark", "block", "village",
        "tehsil", "taluk", "colony", "sector",
        # Conjunctions / clause boundaries — extraction must stop before
        # these so "area name Modi Garden and city Bharuch" yields
        # "Modi Garden" not "Modi Garden and city Bharuch".
        "and", "or", "plus", "with",
        "અને",  # Gujarati "and"
    })

    def _extract_keyword_value(self, keyword: str, text: str) -> str | None:
        """Return the value following ``keyword`` in ``text`` if -- and
        only if -- the text actually gives one. See the comment above
        this method's call site for why the naive always-capture regex
        was replaced."""
        match = re.search(rf"\b{keyword}\s*(?:is|:|-)\s*([A-Za-z0-9][A-Za-z0-9\s]{{0,40}})", text, re.IGNORECASE)
        value = match.group(1).strip() if match else None

        if not value:
            match = re.search(rf"\b{keyword}\s+([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)", text)
            value = match.group(1).strip() if match else None

        if not value:
            return None

        # Stop at location-boundary words so "area name Modi Garden
        # and city Bharuch" yields "name Modi Garden and" (or after
        # filler-word removal, "Modi Garden and") rather than
        # swallowing the city portion.
        words = value.split()
        truncated: list[str] = []
        for w in words:
            if w.lower() in self._LOCATION_BOUNDARY_WORDS:
                break
            truncated.append(w)
        if truncated:
            value = " ".join(truncated)

        # Strip leading filler words (e.g. "name" from "name Modi Garden")
        while value:
            first = value.split()[0].lower()
            if first in self._GENERIC_FILLER_WORDS:
                value = value[len(value.split()[0]):].strip()
            else:
                break

        if value.lower() in self._GENERIC_FILLER_WORDS:
            return None
        return value

    def get_required_fields(self, sub_category: GrievanceSubCategory) -> list[str]:
        """Get required fields for a sub-category."""
        return self.SUBCATEGORY_ENTITIES.get(sub_category, {}).get("required", [])

    def get_optional_fields(self, sub_category: GrievanceSubCategory) -> list[str]:
        """Get optional fields for a sub-category."""
        return self.SUBCATEGORY_ENTITIES.get(sub_category, {}).get("optional", [])

    def get_all_fields(self, sub_category: GrievanceSubCategory) -> list[str]:
        """Get all fields (required + optional) for a sub-category."""
        config = self.SUBCATEGORY_ENTITIES.get(sub_category, {})
        return config.get("required", []) + config.get("optional", [])
