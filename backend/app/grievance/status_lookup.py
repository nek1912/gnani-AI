
from __future__ import annotations


from .models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceSubCategory,
    StatusLookupResult,
)


class GrievanceStatusLookup:
    """Provides status lookup guidance (prototype)."""

    LOOKUP_MAP = {
        GrievanceCategory.PUBLIC_SERVICE: {
            "default": StatusLookupResult(
                portal_name="CPGRAMS Status Tracking",
                portal_url="https://pgportal.gov.in/ViewGrievanceStatus.aspx",
                lookup_method="reference_number",
                required_fields=["Grievance Registration Number", "Mobile Number / Email"],
            ),
            GrievanceSubCategory.RTI_DELAY: StatusLookupResult(
                portal_name="CIC Online / RTI Portal",
                portal_url="https://rti.india.gov.in/ / https://cic.gov.in/",
                lookup_method="reference_number",
                required_fields=["Appeal/Complaint Number", "Applicant Name"],
            ),
        },
        GrievanceCategory.POLICE: {
            "default": StatusLookupResult(
                portal_name="State Police Citizen Portal / FIR Status",
                portal_url="Varies by state (e.g., https://police.gov.in/, state police websites)",
                lookup_method="reference_number",
                required_fields=["FIR Number / Complaint Number", "Police Station", "Date"],
            ),
        },
        GrievanceCategory.REVENUE: {
            "default": StatusLookupResult(
                portal_name="State Land Records Portal (Bhoomi/Bhulekh/Meebhoomi)",
                portal_url="Varies by state",
                lookup_method="reference_number",
                required_fields=["Application Number / Mutation Number", "District", "Tehsil", "Village", "Survey Number"],
            ),
        },
        GrievanceCategory.MUNICIPAL: {
            "default": StatusLookupResult(
                portal_name="Municipal Corporation Complaint Tracking",
                portal_url="City municipal corporation website",
                lookup_method="reference_number",
                required_fields=["Complaint Reference Number", "Mobile Number"],
            ),
        },
        GrievanceCategory.ELECTRICITY: {
            "default": StatusLookupResult(
                portal_name="DISCOM Consumer Portal / CGRF Status",
                portal_url="Respective DISCOM website",
                lookup_method="reference_number",
                required_fields=["Consumer Number", "Complaint/Docket Number"],
            ),
        },
        GrievanceCategory.WATER: {
            "default": StatusLookupResult(
                portal_name="Water Board Consumer Portal",
                portal_url="State water board website",
                lookup_method="reference_number",
                required_fields=["Consumer Number", "Complaint Reference Number"],
            ),
        },
        GrievanceCategory.TRANSPORT: {
            "default": StatusLookupResult(
                portal_name="Parivahan Sewa / State RTO Status",
                portal_url="https://parivahan.gov.in/ / State RTO website",
                lookup_method="reference_number",
                required_fields=["Application Number / Licence Number", "Date of Birth"],
            ),
        },
        GrievanceCategory.HEALTH: {
            "default": StatusLookupResult(
                portal_name="State Health Grievance Portal",
                portal_url="State health department website",
                lookup_method="reference_number",
                required_fields=["Complaint Reference Number", "Mobile Number"],
            ),
        },
        GrievanceCategory.EDUCATION: {
            "default": StatusLookupResult(
                portal_name="State Education Grievance Portal / NCPCR",
                portal_url="State education website / http://ncpcr.gov.in/",
                lookup_method="reference_number",
                required_fields=["Complaint Reference Number", "Student Name"],
            ),
        },
        GrievanceCategory.FOOD_CIVIL_SUPPLIES: {
            "default": StatusLookupResult(
                portal_name="State Food Commission / FCS Portal",
                portal_url="State FCS department website",
                lookup_method="reference_number",
                required_fields=["Complaint Reference Number", "Ration Card Number"],
            ),
        },
        GrievanceCategory.SOCIAL_WELFARE: {
            "default": StatusLookupResult(
                portal_name="NSAP Portal / State Social Welfare Portal",
                portal_url="https://nsap.nic.in/ / State social welfare website",
                lookup_method="reference_number",
                required_fields=["PPO Number / Application Number", "Aadhaar / Bank Account"],
            ),
        },
        GrievanceCategory.LABOUR: {
            "default": StatusLookupResult(
                portal_name="State Labour Portal / EPFO EPFiGMS / ESIC",
                portal_url="State labour website / https://epfigms.gov.in/ / ESIC portal",
                lookup_method="reference_number",
                required_fields=["Complaint/Application Number", "PF/ESI Number (if applicable)"],
            ),
        },
        GrievanceCategory.COOPERATIVE: {
            "default": StatusLookupResult(
                portal_name="Registrar of Cooperative Societies Portal",
                portal_url="State RCS website",
                lookup_method="reference_number",
                required_fields=["Complaint Number", "Society Registration Number"],
            ),
        },
        GrievanceCategory.AGRICULTURE: {
            "default": StatusLookupResult(
                portal_name="PMFBY Portal / State Agriculture Portal",
                portal_url="https://pmfby.gov.in/ / State agriculture website",
                lookup_method="reference_number",
                required_fields=["Application/Enrollment ID", "Farmer Name", "Season/Year"],
            ),
        },
        GrievanceCategory.BANKING: {
            "default": StatusLookupResult(
                portal_name="RBI CMS / Banking Ombudsman / Bank Portal",
                portal_url="https://cms.rbi.org.in/ / Bank's website",
                lookup_method="reference_number",
                required_fields=["Complaint Reference Number", "Bank Name", "Account Number"],
            ),
        },
    }

    def get_status_lookup(self, draft: GrievanceDraft) -> StatusLookupResult:
        """Get status lookup guidance for a grievance draft."""
        category_map = self.LOOKUP_MAP.get(draft.category, {})
        lookup = category_map.get(draft.sub_category, category_map.get("default"))

        if lookup is None:
            return StatusLookupResult(
                portal_name="CPGRAMS Status Tracking",
                portal_url="https://pgportal.gov.in/ViewGrievanceStatus.aspx",
                lookup_method="reference_number",
                required_fields=["Grievance Registration Number", "Mobile Number / Email"],
            )

        return lookup

    def format_lookup_for_display(self, lookup: StatusLookupResult) -> str:
        """Format status lookup guidance for user display."""
        lines = [
            "**🔍 Status Lookup Guidance (Prototype Reference)**",
            "",
            f"**Portal:** {lookup.portal_name}",
            f"**URL:** {lookup.portal_url}",
            f"**Lookup Method:** {lookup.lookup_method.replace('_', ' ').title()}",
            "",
            "**Required Information to Check Status:**",
        ]

        for field in lookup.required_fields:
            lines.append(f"  • {field}")

        lines.append("")
        lines.append(f"⚠ **Disclaimer:** {lookup.disclaimer}")

        return "\n".join(lines)
