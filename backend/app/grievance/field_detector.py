
from __future__ import annotations


from .models import GrievanceDraft, GrievanceSubCategory
from .entity_extractor import GrievanceEntityExtractor


_PERSON_NAME_TOKENS = (
    "complainant", "applicant", "consumer", "pensioner", "owner",
    "beneficiary", "account_holder", "student", "parent", "candidate",
    "member", "employee", "farmer", "patient", "doctor", "land_owner",
)

_LOCATION_FIELDS = {
    "district": {"district_name"},
    "tehsil": {"tehsil_name"},
    "taluk": {"taluk_name"},
    "village": {"village_name"},
    "area": {"area_name"},
    "locality": {"locality_name", "colony_name", "area_name"},
    "ward_number": {"ward_name"},
    "block": {"block_name"},
    "zone": {"sector_name"},
    "city": {"city_name"},
    "location": {
        "district_name", "tehsil_name", "taluk_name", "village_name",
        "area_name", "locality_name", "ward_name", "block_name",
        "colony_name", "city_name", "sector_name",
    },
}

_REFERENCE_FIELDS = {
    "application_number", "application_id", "reference_number",
    "complaint_number", "ppo_number", "registration_number", "member_id",
    "survey_number", "khata_number", "patta_number", "lot_number",
    "transaction_id", "rti_application_number", "learner_licence_number",
    "account_number", "fps_code", "property_id", "case_number",
}

_AMOUNT_FIELDS = {
    "disputed_amount", "amount_involved", "award_amount", "loan_amount",
    "amount_claimed", "sum_insured", "premium_paid",
    "compensation_claimed", "amount",
}

_LOCATION_ENTITY_KEYS = {
    "district_name", "tehsil_name", "taluk_name", "village_name",
    "area_name", "locality_name", "ward_name", "block_name",
    "colony_name", "city_name", "sector_name",
}


def is_field_satisfied(
    field: str,
    extracted_keys: set[str],
    draft: GrievanceDraft,
) -> bool:
    """
    Determine whether a required/optional field is effectively
    covered by what has already been extracted.

    The entity extractor produces generic entity types (e.g. "date",
    "person_name", "reference_number") while each grievance sub-category
    defines its own specific field names (e.g. "date_of_incident",
    "complainant_name", "application_number"). This helper bridges the
    two so the workflow doesn't get stuck asking for information that
    has, in substance, already been provided.
    """
    if field in extracted_keys:
        return True

    fl = field.lower()

    if fl.endswith("_description") or fl == "description":
        return bool(draft.description and draft.description.strip())

    if "date" in fl or fl in {"billing_month", "month_not_received", "period"}:
        return "date" in extracted_keys

    if fl.endswith("_name") and any(tok in fl for tok in _PERSON_NAME_TOKENS):
        return "person_name" in extracted_keys

    if fl == "police_station":
        if "police_station_name" in extracted_keys:
            return True
        return "police station" in (draft.description or "").lower()

    if fl.endswith("_name") or fl in {"municipality", "insurance_company"}:
        if any(k.endswith("_name") for k in extracted_keys):
            return True
        return bool(draft.department)

    if fl in _LOCATION_FIELDS:
        return bool(extracted_keys & _LOCATION_FIELDS[fl])

    if fl in _REFERENCE_FIELDS:
        return bool(extracted_keys & {"reference_number", "account_number"})

    if fl in _AMOUNT_FIELDS:
        return "amount" in extracted_keys

    return False


class GrievanceFieldDetector:
    """Detects missing required fields in grievance draft."""

    def __init__(self):
        self.entity_extractor = GrievanceEntityExtractor()

    def detect_missing_fields(
        self,
        draft: GrievanceDraft,
        user_message: str = "",
    ) -> tuple[list[str], list[str]]:
        """
        Detect missing required and optional fields.

        Returns:
            tuple: (missing_required, missing_optional)
        """
        required_fields = self.entity_extractor.get_required_fields(draft.sub_category)
        optional_fields = self.entity_extractor.get_optional_fields(draft.sub_category)

        extracted_keys = set(draft.entities.keys())

        if user_message:
            new_extractions = self.entity_extractor.extract(user_message, draft.sub_category)
            extracted_keys.update(new_extractions.entities.keys())

        missing_required = [
            f for f in required_fields
            if not is_field_satisfied(f, extracted_keys, draft)
        ]
        missing_optional = [
            f for f in optional_fields
            if not is_field_satisfied(f, extracted_keys, draft)
        ]

        return missing_required, missing_optional

    # Human-readable labels for field names (used as tab labels in the UI).
    # Keys are snake_case field identifiers; values are short English labels
    # that can be translated by the chat route before reaching the frontend.
    FIELD_LABELS: dict[str, str] = {
        "rti_application_number": "RTI Application Number",
        "date_of_application": "Application Date",
        "department": "Department",
        "applicant_name": "Applicant Name",
        "address": "Address",
        "phone": "Phone",
        "email": "Email",
        "certificate_type": "Certificate Type",
        "application_number": "Application Number",
        "issuing_authority": "Issuing Authority",
        "pension_type": "Pension Type",
        "ppo_number": "PPO Number",
        "bank_account": "Bank Account",
        "bank_name": "Bank Name",
        "pensioner_name": "Pensioner Name",
        "aadhaar": "Aadhaar Number",
        "scheme_name": "Scheme Name",
        "application_id": "Application ID",
        "police_station": "Police Station",
        "date_of_incident": "Incident Date",
        "incident_description": "Incident Description",
        "complainant_name": "Complainant Name",
        "accused_details": "Accused Details",
        "witnesses": "Witnesses",
        "evidence": "Evidence",
        "followup_dates": "Follow-up Dates",
        "officer_details": "Officer Details",
        "medical_report": "Medical Report",
        "district": "District",
        "tehsil": "Tehsil",
        "village": "Village",
        "error_description": "Error Description",
        "khata_number": "Khata Number",
        "patta_number": "Patta Number",
        "document_reference": "Document Reference",
        "previous_owner": "Previous Owner",
        "mutation_type": "Mutation Type",
        "project_name": "Project Name",
        "award_amount": "Award Amount",
        "land_owner_name": "Land Owner Name",
        "award_date": "Award Date",
        "ward_number": "Ward Number",
        "city": "City",
        "locality": "Locality",
        "issue_description": "Issue Description",
        "municipality": "Municipality",
        "zone": "Zone",
        "landmark": "Landmark",
        "photos": "Photos",
        "plot_number": "Plot Number",
        "building_type": "Building Type",
        "architect_name": "Architect Name",
        "property_id": "Property ID",
        "assessment_year": "Assessment Year",
        "amount_paid": "Amount Paid",
        "payment_date": "Payment Date",
        "consumer_number": "Consumer Number",
        "billing_month": "Billing Month",
        "disputed_amount": "Disputed Amount",
        "discom_name": "DISCOM Name",
        "consumer_name": "Consumer Name",
        "meter_number": "Meter Number",
        "previous_bill_amount": "Previous Bill Amount",
        "fault_description": "Fault Description",
        "date_noticed": "Date Noticed",
        "connection_type": "Connection Type",
        "load_required": "Required Load",
        "area": "Area",
        "frequency": "Frequency",
        "duration": "Duration",
        "feeder_name": "Feeder Name",
        "complaint_number": "Complaint Number",
        "water_board_name": "Water Board",
        "quality_description": "Quality Description",
        "lab_report": "Lab Report",
        "timing": "Timing",
        "rto_office": "RTO Office",
        "licence_type": "Licence Type",
        "learner_licence_number": "Learner Licence Number",
        "test_date": "Test Date",
        "vehicle_number": "Vehicle Number",
        "permit_type": "Permit Type",
        "owner_name": "Owner Name",
        "vehicle_type": "Vehicle Type",
        "route": "Route",
        "depot": "Depot",
        "route_number": "Route Number",
        "date_time": "Date & Time",
        "bus_number": "Bus Number",
        "driver_conductor_details": "Driver/Conductor Details",
        "ticket_number": "Ticket Number",
        "hospital_name": "Hospital Name",
        "patient_name": "Patient Name",
        "doctor_name": "Doctor Name",
        "medical_records": "Medical Records",
        "medicine_name": "Medicine Name",
        "prescription": "Prescription",
        "alternative_suggested": "Alternative Suggested",
        "ambulance_number_or_service": "Ambulance Service",
        "pickup_location": "Pickup Location",
        "destination": "Destination",
        "call_number": "Call Number",
        "response_time": "Response Time",
        "school_name": "School Name",
        "class_applied": "Class Applied",
        "reason_given": "Reason Given",
        "student_name": "Student Name",
        "parent_name": "Parent Name",
        "rte_category": "RTE Category",
        "institute_name": "Institute Name",
        "academic_year": "Academic Year",
        "course": "Course",
        "class": "Class",
        "meal_type": "Meal Type",
        "card_type": "Card Type",
        "family_members": "Family Members",
        "fps_code": "FPS Code",
        "fps_name": "FPS Name",
        "commodity": "Commodity",
        "entitled_quantity": "Entitled Quantity",
        "received_quantity": "Received Quantity",
        "ration_card_number": "Ration Card Number",
        "beneficiary_name": "Beneficiary Name",
        "quality_issue": "Quality Issue",
        "sample_available": "Sample Available",
        "month_not_received": "Month Not Received",
        "reason_for_exclusion": "Reason for Exclusion",
        "category": "Category",
        "income_certificate": "Income Certificate",
        "employer_name": "Employer Name",
        "employee_name": "Employee Name",
        "amount_claimed": "Amount Claimed",
        "wage_type": "Wage Type",
        "employer_address": "Employer Address",
        "pf_number": "PF Number",
        "esi_number": "ESI Number",
        "appointment_letter": "Appointment Letter",
        "date_of_termination": "Termination Date",
        "notice_period": "Notice Period",
        "compensation_claimed": "Compensation Claimed",
        "factory_name": "Factory Name",
        "location": "Location",
        "violation_description": "Violation Description",
        "injury_details": "Injury Details",
        "inspection_report": "Inspection Report",
        "society_name": "Society Name",
        "registration_number": "Registration Number",
        "member_id": "Member ID",
        "member_name": "Member Name",
        "share_amount": "Share Amount",
        "dividend_due": "Dividend Due",
        "meeting_date": "Meeting Date",
        "election_date": "Election Date",
        "dispute_description": "Dispute Description",
        "candidate_name": "Candidate Name",
        "voter_id": "Voter ID",
        "returning_officer": "Returning Officer",
        "accused_office_bearer": "Accused Office Bearer",
        "period": "Period",
        "audit_report": "Audit Report",
        "amount_involved": "Amount Involved",
        "farmer_name": "Farmer Name",
        "crop": "Crop",
        "season": "Season",
        "year": "Year",
        "insurance_company": "Insurance Company",
        "survey_number": "Survey Number",
        "block": "Block",
        "sum_insured": "Sum Insured",
        "premium_paid": "Premium Paid",
        "component": "Component",
        "seed_name": "Seed Name",
        "variety": "Variety",
        "lot_number": "Lot Number",
        "dealer_name": "Dealer Name",
        "purchase_date": "Purchase Date",
        "bill_number": "Bill Number",
        "certification_agency": "Certification Agency",
        "description": "Description",
        "title": "Title",
    }

    def get_field_labels(self) -> dict[str, str]:
        """Get human-readable labels for all known fields."""
        return dict(self.FIELD_LABELS)

    def get_field_prompts(self, sub_category: GrievanceSubCategory) -> dict[str, str]:
        """Get user-friendly prompts for each field."""
        prompts = {
            "rti_application_number": "What is your RTI application number?",
            "date_of_application": "When did you submit the application? (date)",
            "department": "Which government department/office is this regarding?",
            "applicant_name": "What is the applicant's full name?",
            "address": "What is the complete address?",
            "phone": "What is the contact phone number?",
            "email": "What is the email address?",

            "certificate_type": "What type of certificate? (caste, income, domicile, birth, death, etc.)",
            "application_number": "What is the application/reference number?",
            "issuing_authority": "Which office/department issues this certificate?",

            "pension_type": "What type of pension? (old age, widow, disability, etc.)",
            "ppo_number": "What is the PPO (Pension Payment Order) number?",
            "bank_account": "What is the bank account number?",
            "bank_name": "What is the bank name?",
            "pensioner_name": "What is the pensioner's name?",
            "aadhaar": "What is the Aadhaar number?",

            "scheme_name": "What is the name of the government scheme?",
            "application_id": "What is the application/registration ID?",

            "police_station": "Which police station?",
            "date_of_incident": "When did the incident occur? (date)",
            "incident_description": "Please describe what happened.",
            "complainant_name": "What is your full name?",
            "accused_details": "Do you have details of the accused person(s)?",
            "witnesses": "Are there any witnesses?",
            "evidence": "Do you have any evidence (photos, documents, etc.)?",
            "followup_dates": "When did you follow up?",
            "officer_details": "Can you describe the officer (name, rank, badge number)?",
            "medical_report": "Is there a medical report?",

            "district": "Which district?",
            "tehsil": "Which tehsil/taluk?",
            "village": "Which village?",
            "error_description": "What is the error in the land record?",
            "khata_number": "What is the khata number?",
            "patta_number": "What is the patta number?",
            "document_reference": "Any document reference number?",
            "previous_owner": "Who was the previous owner?",
            "mutation_type": "What type of mutation? (inheritance, sale, gift, etc.)",
            "project_name": "What is the project name (for land acquisition)?",
            "award_amount": "What is the compensation award amount?",
            "land_owner_name": "What is the land owner's name?",
            "award_date": "What is the award date?",

            "ward_number": "What is the ward number?",
            "city": "Which city?",
            "locality": "What is the locality/area name?",
            "issue_description": "Please describe the issue.",
            "municipality": "Which municipality/corporation?",
            "zone": "Which zone?",
            "landmark": "Any nearby landmark?",
            "photos": "Do you have photos of the issue?",
            "plot_number": "What is the plot number?",
            "building_type": "What type of building? (residential, commercial, etc.)",
            "architect_name": "Architect/engineer name?",
            "property_id": "What is the property ID/assessment number?",
            "assessment_year": "Which assessment year?",
            "amount_paid": "How much have you paid?",
            "payment_date": "When did you pay?",

            "consumer_number": "What is your consumer/account number?",
            "billing_month": "Which billing month is this for? (e.g., January 2024)",
            "disputed_amount": "What is the disputed amount?",
            "discom_name": "Which electricity distribution company (DISCOM)?",
            "consumer_name": "Consumer name on the bill?",
            "meter_number": "What is the meter number?",
            "previous_bill_amount": "What was the previous bill amount?",
            "fault_description": "Describe the meter fault.",
            "date_noticed": "When did you first notice this?",
            "connection_type": "What type of connection? (domestic, commercial, agricultural, industrial)",
            "load_required": "What is the required load (kW)?",
            "area": "Which area/locality?",
            "frequency": "How frequent are the power cuts? (daily, weekly, etc.)",
            "duration": "How long does each power cut last?",
            "feeder_name": "Do you know the feeder name?",
            "complaint_number": "Any previous complaint number?",

            "water_board_name": "Which water board/supply authority?",
            "quality_description": "Describe the water quality issue (color, smell, taste).",
            "lab_report": "Do you have a lab report?",
            "timing": "What time does supply usually come?",

            "rto_office": "Which RTO office?",
            "licence_type": "What type of licence? (learner, permanent, renewal, etc.)",
            "learner_licence_number": "What is the learner licence number?",
            "test_date": "When was/will be the driving test?",
            "vehicle_number": "What is the vehicle registration number?",
            "permit_type": "What type of permit?",
            "owner_name": "Vehicle owner's name?",
            "vehicle_type": "Vehicle type? (goods, passenger, etc.)",
            "route": "Route/permit area?",
            "depot": "Which bus depot?",
            "route_number": "Which route number?",
            "date_time": "Date and time of the issue?",
            "bus_number": "Bus number (if known)?",
            "driver_conductor_details": "Driver/conductor details?",
            "ticket_number": "Ticket number?",

            "hospital_name": "Which hospital/health center?",
            "patient_name": "Patient's name?",
            "doctor_name": "Doctor's name?",
            "medical_records": "Do you have medical records/reports?",
            "medicine_name": "Which medicine is unavailable?",
            "prescription": "Do you have a prescription?",
            "alternative_suggested": "Was any alternative suggested?",
            "ambulance_number_or_service": "Ambulance number or service (108, 102, private)?",
            "pickup_location": "Pickup location?",
            "destination": "Destination hospital?",
            "call_number": "Call reference number?",
            "response_time": "How long did it take?",

            "school_name": "Which school/college?",
            "class_applied": "Which class/grade?",
            "reason_given": "What reason was given for denial?",
            "student_name": "Student's name?",
            "parent_name": "Parent/guardian name?",
            "rte_category": "RTE category? (EWS, DG, CWSN, etc.)",
            "institute_name": "Institute name?",
            "academic_year": "Academic year?",
            "course": "Course name?",
            "class": "Class/standard?",
            "meal_type": "Meal type? (breakfast, lunch)",

            "card_type": "What type of ration card? (APL, BPL, AAY, PHH)",
            "family_members": "Number of family members on card?",
            "fps_code": "Fair Price Shop (FPS) code?",
            "fps_name": "FPS dealer name/shop name?",
            "commodity": "Which commodity? (wheat, rice, sugar, kerosene, etc.)",
            "entitled_quantity": "What is your entitled quantity?",
            "received_quantity": "What quantity did you receive?",
            "ration_card_number": "Ration card number?",
            "beneficiary_name": "Beneficiary name on card?",
            "quality_issue": "Describe the quality issue.",
            "sample_available": "Do you have a sample?",

            "month_not_received": "Which month's pension not received?",
            "reason_for_exclusion": "What reason was given for exclusion?",
            "category": "Category? (SC, ST, OBC, General, etc.)",
            "income_certificate": "Do you have income certificate?",

            "employer_name": "Employer/company name?",
            "employee_name": "Employee name?",
            "amount_claimed": "Amount claimed?",
            "wage_type": "Type of wages? (basic, overtime, bonus, etc.)",
            "employer_address": "Employer address?",
            "pf_number": "PF account number?",
            "esi_number": "ESI number?",
            "appointment_letter": "Do you have appointment letter?",
            "date_of_termination": "Date of termination?",
            "notice_period": "Notice period given?",
            "compensation_claimed": "Compensation amount claimed?",
            "factory_name": "Factory/establishment name?",
            "location": "Location of factory?",
            "violation_description": "Describe the safety violation.",
            "injury_details": "Any injury details?",
            "inspection_report": "Any inspection report?",

            "society_name": "Cooperative society name?",
            "registration_number": "Society registration number?",
            "member_id": "Your member ID?",
            "member_name": "Member name?",
            "share_amount": "Share capital amount?",
            "dividend_due": "Dividend amount due?",
            "meeting_date": "Meeting date?",
            "election_date": "Election date?",
            "dispute_description": "Describe the election dispute.",
            "candidate_name": "Candidate name?",
            "voter_id": "Voter ID?",
            "returning_officer": "Returning officer name?",
            "accused_office_bearer": "Accused office bearer name/position?",
            "period": "Period of alleged misuse?",
            "audit_report": "Any audit report?",
            "amount_involved": "Amount involved?",

            "farmer_name": "Farmer's name?",
            "crop": "Crop name?",
            "season": "Season? (Kharif, Rabi, Summer)",
            "year": "Crop year?",
            "insurance_company": "Insurance company name?",
            "survey_number": "Survey number?",
            "block": "Block name?",
            "sum_insured": "Sum insured amount?",
            "premium_paid": "Premium paid?",
            "component": "Subsidy component?",
            "seed_name": "Seed name?",
            "variety": "Variety?",
            "lot_number": "Lot/batch number?",
            "dealer_name": "Dealer/shop name?",
            "purchase_date": "Purchase date?",
            "bill_number": "Bill/invoice number?",
            "certification_agency": "Certification agency?",

            "branch": "Bank branch name?",
            "loan_type": "Loan type? (home, personal, vehicle, agriculture, etc.)",
            "rejection_reason": "Reason given for rejection?",
            "loan_amount": "Loan amount applied for?",
            "cibil_score": "CIBIL score?",
            "income_proof": "Income proof submitted?",
            "account_number": "Bank account number?",
            "transaction_date": "Transaction date?",
            "amount": "Transaction amount?",
            "fraud_type": "Type of fraud? (UPI, card, net banking, ATM, etc.)",
            "account_holder_name": "Account holder name?",
            "transaction_id": "Transaction ID/reference?",
            "merchant_name": "Merchant name?",
            "police_complaint": "Police complaint filed?",
            "service_type": "Service type? (account, loan, card, locker, etc.)",
            "reference_number": "Reference/complaint number?",
            "officer_name": "Bank officer name?",
        }

        all_fields = self.entity_extractor.get_all_fields(sub_category)
        return {field: prompts.get(field, f"Please provide {field.replace('_', ' ')}.") for field in all_fields}
