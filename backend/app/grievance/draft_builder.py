
from __future__ import annotations

import uuid
from datetime import datetime

from .models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
    _normalize_ward,
    _normalize_city,
    _normalize_locality,
    _normalize_area,
)
from .classifier import GrievanceClassifier
from .entity_extractor import GrievanceEntityExtractor
from .field_detector import is_field_satisfied
from .semantic_extractor import GrievanceSemanticExtractor


_CONFIRMATION_WORDS = {
    "yes", "yeah", "yep", "correct", "right", "ok", "okay", "confirm",
    "confirmed", "proceed", "continue", "sure", "no", "nope", "wrong",
    "incorrect",
}

_INFORMATIONAL_STARTERS = (
    "what is", "what are", "how does", "how do", "how to",
    "explain", "tell me about", "define", "meaning of", "who is", "why",
)


def _looks_like_confirmation_or_unrelated(text: str) -> bool:
    """
    Heuristic guard used only for the "attribute raw answer to the field
    the workflow just asked about" fallback in ``update_draft``. Keeps a
    bare confirmation ("Yes", "No, that's wrong") or an unrelated
    informational question ("What is PMFBY?") from being stored as a
    field's value.
    """
    stripped = text.strip().rstrip(".!").lower()
    if not stripped:
        return True
    words = stripped.replace(",", " ").split()
    if words and all(w in _CONFIRMATION_WORDS for w in words):
        return True
    if text.strip().endswith("?") and any(
        stripped.startswith(s) for s in _INFORMATIONAL_STARTERS
    ):
        return True
    return False


class GrievanceDraftBuilder:
    """Builds structured grievance draft from conversation."""

    def __init__(self):
        self.classifier = GrievanceClassifier()
        self.entity_extractor = GrievanceEntityExtractor()
        self.semantic_extractor = GrievanceSemanticExtractor()

    def build_initial_draft(
        self,
        user_message: str,
        conversation_id: str,
        user_id: str,
    ) -> GrievanceDraft:
        """Build initial draft from first user message."""
        classification = self.classifier.classify(user_message)

        extraction = self.entity_extractor.extract(user_message, classification.sub_category)

        reference_number = f"GRV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        title = self._generate_title(classification.sub_category, user_message)

        required_fields = self.entity_extractor.get_required_fields(classification.sub_category)
        optional_fields = self.entity_extractor.get_optional_fields(classification.sub_category)

        department = self._get_department(classification.category, classification.sub_category)
        jurisdiction = "local" if classification.category == GrievanceCategory.MUNICIPAL else "state"
        state = self._extract_state(user_message)

        draft = GrievanceDraft(
            category=classification.category,
            sub_category=classification.sub_category,
            title=title,
            description=user_message,
            entities=extraction.entities,
            missing_fields=[],
            required_fields=required_fields,
            optional_fields=optional_fields,
            jurisdiction=jurisdiction,
            state=state,
            department=department,
            reference_number=reference_number,
            created_at=datetime.now().isoformat(),
        )

        return draft

    def update_draft(
        self,
        draft: GrievanceDraft,
        user_message: str,
        target_field: str | None = None,
    ) -> GrievanceDraft:
        """Update draft with new information from user message.

        NOTE: this intentionally does NOT overwrite ``draft.description``.
        The description holds the citizen's *original* complaint narrative,
        captured once at intake (see ``build_initial_draft``). Later turns
        in the conversation (confirmations, field answers, corrections)
        must never replace it -- doing so previously caused the original
        complaint to be lost, and confirmation replies such as "Yes" to be
        stored as the complaint description.

        ``target_field`` is the specific field the workflow is currently
        asking the user about (one-field-at-a-time). When provided, the
        user's reply is passed through the semantic extraction/validation
        layer (``GrievanceSemanticExtractor``) rather than being stored
        verbatim -- this is what lets a natural-language reply like "I
        live in Ward 12, near the old bus stand" be correctly split into
        ``ward_number = "Ward 12"`` and ``landmark = "Near the old bus
        stand"`` instead of the raw sentence being dumped into whichever
        field the workflow happened to be asking about.
        """
        extraction = self.entity_extractor.extract(user_message, draft.sub_category)

        for key, entity in extraction.entities.items():
            if key not in draft.entities or entity.confidence > draft.entities[key].confidence:
                draft.entities[key] = entity

        # must still be *interpreted*, not stored as-is. The semantic
        if target_field and target_field not in draft.entities:
            value = user_message.strip()
            if value and not _looks_like_confirmation_or_unrelated(value):
                semantic_result = self.semantic_extractor.extract(
                    current_field=target_field,
                    user_message=user_message,
                    known_fields=set(draft.entities.keys()),
                    required_fields=draft.required_fields,
                    optional_fields=draft.optional_fields,
                    missing_fields=draft.missing_fields,
                    original_complaint=draft.description,
                    category=draft.category.value,
                    sub_category=draft.sub_category.value,
                    department=draft.department,
                )

                if not semantic_result.unrelated:
                    for field_name, extracted_value in semantic_result.extracted_fields.items():
                        clean_value = (extracted_value or "").strip()
                        if not clean_value:
                            continue
                        if (
                            field_name not in draft.entities
                            or draft.entities[field_name].confidence < 0.8
                        ):
                            draft.entities[field_name] = GrievanceEntity(
                                name=field_name,
                                value=clean_value,
                                confidence=0.8,
                                source_text=user_message[:200],
                            )

        missing_required, missing_optional = self._detect_missing(draft)
        draft.missing_fields = missing_required + missing_optional

        return draft

    def _detect_missing(self, draft: GrievanceDraft) -> tuple[list[str], list[str]]:
        """Detect missing required and optional fields."""
        extracted_keys = set(draft.entities.keys())
        missing_required = [
            f for f in draft.required_fields
            if not is_field_satisfied(f, extracted_keys, draft)
        ]
        missing_optional = [
            f for f in draft.optional_fields
            if not is_field_satisfied(f, extracted_keys, draft)
        ]
        return missing_required, missing_optional

    def _generate_title(self, sub_category: GrievanceSubCategory, user_message: str) -> str:
        """Generate a concise title for the grievance."""
        titles = {
            GrievanceSubCategory.RTI_DELAY: "RTI Application Delay",
            GrievanceSubCategory.CERTIFICATE_DELAY: "Certificate Issuance Delay",
            GrievanceSubCategory.PENSION_DELAY: "Pension Payment Delay",
            GrievanceSubCategory.SCHEME_BENEFIT_DENIED: "Government Scheme Benefit Denied",
            GrievanceSubCategory.FIR_REFUSAL: "Police Refusal to Register FIR",
            GrievanceSubCategory.HARASSMENT: "Police Harassment Complaint",
            GrievanceSubCategory.INACTION: "Police Inaction on Complaint",
            GrievanceSubCategory.CORRUPTION: "Corruption/Bribery Complaint",
            GrievanceSubCategory.LAND_RECORD_ERROR: "Land Record Error",
            GrievanceSubCategory.MUTATION_DELAY: "Land Mutation Delay",
            GrievanceSubCategory.COMPENSATION_DELAY: "Land Acquisition Compensation Delay",
            GrievanceSubCategory.GARBAGE: "Garbage Collection Issue",
            GrievanceSubCategory.DRAINAGE: "Drainage/Sewage Problem",
            GrievanceSubCategory.STREET_LIGHT: "Street Light Not Working",
            GrievanceSubCategory.BUILDING_PERMIT: "Building Permit Delay",
            GrievanceSubCategory.PROPERTY_TAX: "Property Tax Issue",
            GrievanceSubCategory.ROAD_DAMAGE: "Damaged Road / Pothole Complaint",
            GrievanceSubCategory.BILLING_DISPUTE: "Electricity Billing Dispute",
            GrievanceSubCategory.METER_FAULT: "Electricity Meter Fault",
            GrievanceSubCategory.NEW_CONNECTION_DELAY: "New Electricity Connection Delay",
            GrievanceSubCategory.POWER_CUT: "Frequent Power Cuts",
            GrievanceSubCategory.SUPPLY_ISSUE: "Water Supply Issue",
            GrievanceSubCategory.QUALITY_ISSUE: "Water Quality Complaint",
            GrievanceSubCategory.BILLING_DISPUTE_WATER: "Water Billing Dispute",
            GrievanceSubCategory.NEW_CONNECTION_DELAY_WATER: "New Water Connection Delay",
            GrievanceSubCategory.LICENCE_DELAY: "Driving Licence Delay",
            GrievanceSubCategory.PERMIT_ISSUE: "Vehicle Permit Issue",
            GrievanceSubCategory.BUS_SERVICE: "Bus Service Complaint",
            GrievanceSubCategory.HOSPITAL_NEGLIGENCE: "Hospital/Medical Negligence",
            GrievanceSubCategory.MEDICINE_SHORTAGE: "Medicine Shortage at Hospital",
            GrievanceSubCategory.AMBULANCE_DELAY: "Ambulance Delay",
            GrievanceSubCategory.ADMISSION_DENIED: "School/College Admission Denied",
            GrievanceSubCategory.SCHOLARSHIP_DELAY: "Scholarship Payment Delay",
            GrievanceSubCategory.MID_DAY_MEAL: "Mid-Day Meal Issue",
            GrievanceSubCategory.RATION_CARD_DELAY: "Ration Card Delay",
            GrievanceSubCategory.QUANTITY_SHORTAGE: "Ration Quantity Shortage",
            GrievanceSubCategory.QUALITY_COMPLAINT: "Ration Quality Complaint",
            GrievanceSubCategory.PENSION_NOT_RECEIVED: "Pension Not Received",
            GrievanceSubCategory.SCHEME_EXCLUSION: "Exclusion from Welfare Scheme",
            GrievanceSubCategory.WAGE_DISPUTE: "Wage/Salary Dispute",
            GrievanceSubCategory.UNFAIR_TERMINATION: "Unfair Termination",
            GrievanceSubCategory.SAFETY_VIOLATION: "Workplace Safety Violation",
            GrievanceSubCategory.MEMBER_RIGHTS: "Cooperative Member Rights Violation",
            GrievanceSubCategory.ELECTION_DISPUTE: "Cooperative Election Dispute",
            GrievanceSubCategory.FUND_MISUSE: "Cooperative Fund Misuse",
            GrievanceSubCategory.PMFBY_CLAIM_DELAY: "PMFBY Crop Insurance Claim Delay",
            GrievanceSubCategory.SUBSIDY_DELAY: "Agriculture Subsidy Delay",
            GrievanceSubCategory.SEED_QUALITY: "Seed Quality Complaint",
            GrievanceSubCategory.LOAN_REJECTION: "Bank Loan Rejection",
            GrievanceSubCategory.FRAUD: "Banking Fraud Complaint",
            GrievanceSubCategory.SERVICE_DEFICIENCY: "Banking Service Deficiency",
        }

        base_title = titles.get(sub_category, "Grievance Complaint")

        return base_title

    def _get_department(self, category: GrievanceCategory, sub_category: GrievanceSubCategory) -> str:
        """Get the responsible department for the grievance."""
        dept_map = {
            GrievanceCategory.PUBLIC_SERVICE: "Department of Administrative Reforms / Relevant Department",
            GrievanceCategory.POLICE: "Police Department / State Police",
            GrievanceCategory.REVENUE: "Revenue Department / Land Records",
            GrievanceCategory.MUNICIPAL: "Municipal Corporation / Urban Local Body",
            GrievanceCategory.ELECTRICITY: "Electricity Distribution Company (DISCOM) / State Electricity Regulatory Commission",
            GrievanceCategory.WATER: "Water Supply Board / Jal Nigam / PHED",
            GrievanceCategory.TRANSPORT: "Regional Transport Office (RTO) / State Transport Department",
            GrievanceCategory.HEALTH: "Health Department / Hospital Administration",
            GrievanceCategory.EDUCATION: "Education Department / School/College Administration",
            GrievanceCategory.FOOD_CIVIL_SUPPLIES: "Food & Civil Supplies Department / FCI",
            GrievanceCategory.SOCIAL_WELFARE: "Social Welfare Department",
            GrievanceCategory.LABOUR: "Labour Department / Labour Commissioner",
            GrievanceCategory.COOPERATIVE: "Registrar of Cooperative Societies",
            GrievanceCategory.AGRICULTURE: "Agriculture Department / Insurance Company (PMFBY)",
            GrievanceCategory.BANKING: "Bank / Banking Ombudsman / RBI",
        }
        return dept_map.get(category, "Relevant Government Department")

    def _extract_state(self, text: str) -> str | None:
        """Extract state from text."""
        states = [
            "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
            "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand",
            "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
            "meghalaya", "mizoram", "nagaland", "odisha", "punjab",
            "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
            "uttar pradesh", "uttarakhand", "west bengal",
            "delhi", "jammu and kashmir", "ladakh", "chandigarh",
            "dadra and nagar haveli", "daman and diu", "lakshadweep", "puducherry",
        ]
        text_lower = text.lower()
        for state in states:
            if state in text_lower:
                return state.title()
        return None

    def format_draft_for_display(self, draft: GrievanceDraft) -> str:
        """Format draft as human-readable text for display.

        Uses canonical field names and normalised values so the
        presentation never contains raw entity keys or label-prefixed
        values like ``Ward Number: Ward Number 5``.
        """
        # --- resolve canonical location values with normalisation ---
        def _alias(keys: list[str]) -> str | None:
            for k in keys:
                e = draft.entities.get(k)
                if e and e.value and e.value.strip():
                    return e.value.strip()
            return None

        ward = _normalize_ward(_alias(["ward_number", "ward_name"]) or "")
        locality = _normalize_locality(_alias(["locality", "locality_name"]) or "")
        area = _normalize_area(_alias(["area", "area_name"]) or "")
        city = _normalize_city(_alias(["city", "city_name"]) or "")

        lines = [
            f"**Grievance Draft Reference: {draft.reference_number}**",
            f"**Category:** {draft.category.value.replace('_', ' ').title()}",
            f"**Sub-category:** {draft.sub_category.value.replace('_', ' ').title()}",
            f"**Department:** {draft.department}",
            f"**Jurisdiction:** {draft.jurisdiction.title()}",
            "",
            f"**Title:** {draft.title}",
            f"**Description:** {draft.description}",
        ]

        # --- location section ---
        location_lines = []
        if ward:
            location_lines.append(f"  • Ward Number: {ward}")
        if locality:
            location_lines.append(f"  • Locality: {locality}")
        if area:
            location_lines.append(f"  • Area: {area}")
        if city:
            location_lines.append(f"  • City: {city}")
        if draft.state:
            location_lines.append(f"  • State: {draft.state}")

        if location_lines:
            lines.append("")
            lines.append("**Location:**")
            lines.extend(location_lines)

        # --- other extracted entities (skip location keys already shown) ---
        _shown = {"ward_number", "ward_name", "locality", "locality_name",
                  "area", "area_name", "city", "city_name"}
        other = {k: v for k, v in (draft.entities or {}).items() if k not in _shown}
        if other:
            lines.append("")
            lines.append("**Other Extracted Information:**")
            for key, entity in other.items():
                label = key.replace("_", " ").title()
                lines.append(f"  • {label}: {entity.value}")

        missing_required, missing_optional = self._detect_missing(draft)

        if missing_required:
            lines.append("")
            lines.append("**⚠ Missing Required Information:**")
            for field in missing_required:
                lines.append(f"  • {field.replace('_', ' ').title()}")

        if missing_optional:
            lines.append("")
            lines.append("**Optional Information (helpful but not required):**")
            for field in missing_optional:
                lines.append(f"  • {field.replace('_', ' ').title()}")

        if not missing_required and not missing_optional:
            lines.append("")
            lines.append("✅ **All required information collected. Draft is ready.**")

        return "\n".join(lines)
