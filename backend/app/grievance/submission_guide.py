
from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from .models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceSubCategory,
    SubmissionRoute,
)


_LOCATION_IN_TEXT_RE = re.compile(
    r"\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*,\s*"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)"
)


_CITY_TO_STATE: dict[str, str] = {
    "bharuch": "Gujarat",
    "vadodara": "Gujarat",
    "ahmedabad": "Gujarat",
    "surat": "Gujarat",
    "rajkot": "Gujarat",
    "mumbai": "Maharashtra",
    "pune": "Maharashtra",
    "nagpur": "Maharashtra",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "bangalore": "Karnataka",
    "bengaluru": "Karnataka",
    "chennai": "Tamil Nadu",
    "kolkata": "West Bengal",
    "hyderabad": "Telangana",
    "jaipur": "Rajasthan",
    "lucknow": "Uttar Pradesh",
    "patna": "Bihar",
    "bhopal": "Madhya Pradesh",
    "thiruvananthapuram": "Kerala",
    "chandigarh": "Chandigarh",
}


class GrievanceSubmissionGuide:
    """Provides official submission route references (prototype)."""

    PORTAL_MAP = {
        GrievanceCategory.PUBLIC_SERVICE: {
            "default": SubmissionRoute(
                portal_name="Centralized Public Grievance Redress and Monitoring System (CPGRAMS)",
                portal_url="https://pgportal.gov.in/",
                department="Department of Administrative Reforms and Public Grievances (DARPG)",
                level="central",
                steps=[
                    "Visit https://pgportal.gov.in/",
                    "Click 'Lodge Grievance' or 'Register Grievance'",
                    "Fill in personal details and grievance description",
                    "Select Ministry/Department from dropdown",
                    "Attach supporting documents",
                    "Submit and note down the registration number",
                ],
                required_documents=[
                    "Identity proof (Aadhaar/PAN/Voter ID)",
                    "Supporting documents related to grievance",
                    "Previous correspondence (if any)",
                ],
                estimated_timeline="30-45 days for initial response",
            ),
            GrievanceSubCategory.RTI_DELAY: SubmissionRoute(
                portal_name="RTI Online Portal / CPGRAMS",
                portal_url="https://rtionline.gov.in/ / https://pgportal.gov.in/",
                department="Public Authority concerned / DARPG",
                level="central",
                steps=[
                    "First appeal to First Appellate Authority (FAA) within 30 days",
                    "If no response, second appeal to Central Information Commission (CIC)",
                    "File online at https://rti.india.gov.in/ or via CPGRAMS",
                ],
                required_documents=[
                    "RTI application copy",
                    "Proof of fee payment",
                    "FAA order (for second appeal)",
                ],
                estimated_timeline="30 days for FAA, 90 days for CIC",
            ),
        },
        GrievanceCategory.POLICE: {
            "default": SubmissionRoute(
                portal_name="State Police Citizen Portal / CPGRAMS",
                portal_url="Varies by state (e.g., https://police.gov.in/ for central)",
                department="State Police Department",
                level="state",
                steps=[
                    "Visit your state police citizen portal",
                    "Or visit the nearest police station",
                    "File written complaint with details",
                    "Get acknowledgment/receipt",
                    "Follow up with Superintendent of Police if no action",
                ],
                required_documents=[
                    "Identity proof",
                    "Written complaint",
                    "Supporting evidence (photos, videos, documents)",
                ],
                estimated_timeline="FIR registration immediate, investigation 90 days",
            ),
            GrievanceSubCategory.FIR_REFUSAL: SubmissionRoute(
                portal_name="Superintendent of Police / CPGRAMS / State Human Rights Commission",
                portal_url="State police website / https://pgportal.gov.in/",
                department="State Police / SHRC",
                level="state",
                steps=[
                    "Submit written complaint to Superintendent of Police (SP) by post or in person",
                    "If SP doesn't act, approach Magistrate under CrPC Section 156(3)",
                    "File complaint with State Human Rights Commission",
                    "Also lodge on CPGRAMS selecting 'Police' category",
                ],
                required_documents=[
                    "Copy of complaint given to police station",
                    "Proof of submission (receipt/postal receipt)",
                    "Identity proof",
                ],
                estimated_timeline="SP must act within 15 days; Magistrate directs FIR registration",
            ),
        },
        GrievanceCategory.REVENUE: {
            "default": SubmissionRoute(
                portal_name="State Revenue Department Portal / Bhoomi / Bhulekh",
                portal_url="Varies by state (e.g., https://bhoomi.karnataka.gov.in/, https://upbhulekh.gov.in/)",
                department="State Revenue Department",
                level="state",
                steps=[
                    "Visit state land records portal (Bhoomi/Bhulekh/Meebhoomi etc.)",
                    "Or visit Tehsildar/Taluk office",
                    "Submit application for correction/mutation",
                    "Track status online with application number",
                ],
                required_documents=[
                    "Land ownership documents",
                    "Identity proof",
                    "Application form",
                    "Supporting evidence",
                ],
                estimated_timeline="30-90 days depending on state",
            ),
        },
        GrievanceCategory.MUNICIPAL: {
            "default": SubmissionRoute(
                portal_name="Municipal Corporation / Urban Local Body Citizen Portal",
                portal_url="Resolved per-request from the citizen's actual location",
                department="Urban Local Body / Municipal Corporation",
                level="local",
                steps=[
                    "Visit your city's municipal corporation website",
                    "Look for 'Grievance', 'Complaint', or 'Citizen Services' section",
                    "Register complaint with ward number and details",
                    "Get complaint reference number",
                    "Track status online",
                ],
                required_documents=[
                    "Property tax receipt / ownership proof",
                    "Identity proof",
                    "Photos of issue (for garbage, drainage, street lights)",
                ],
                estimated_timeline="7-30 days depending on issue type",
            ),
        },
        GrievanceCategory.ELECTRICITY: {
            "default": SubmissionRoute(
                portal_name="DISCOM Consumer Grievance Portal / CGRF / Ombudsman",
                portal_url="Respective DISCOM website (e.g., https://www.bsesdelhi.com/, https://www.mahadiscom.in/)",
                department="Electricity Distribution Company / CGRF / Electricity Ombudsman",
                level="state",
                steps=[
                    "First: Lodge complaint on DISCOM consumer portal or call 1912",
                    "Get complaint/docket number",
                    "If not resolved in 30 days: Approach Consumer Grievance Redressal Forum (CGRF)",
                    "If still unresolved: Approach Electricity Ombudsman",
                ],
                required_documents=[
                    "Consumer number",
                    "Latest electricity bill",
                    "Identity proof",
                    "Supporting documents for dispute",
                ],
                estimated_timeline="DISCOM: 30 days, CGRF: 45 days, Ombudsman: 60 days",
            ),
        },
        GrievanceCategory.WATER: {
            "default": SubmissionRoute(
                portal_name="Water Board / Jal Nigam / PHED Portal",
                portal_url="State water board website (e.g., https://delhijalboard.nic.in/, https://www.mahawater.gov.in/)",
                department="Water Supply & Sanitation Department / Jal Nigam",
                level="state",
                steps=[
                    "Lodge complaint on water board consumer portal",
                    "Or call water board helpline",
                    "Get complaint reference number",
                    "Escalate to higher authorities if needed",
                ],
                required_documents=[
                    "Consumer number / connection number",
                    "Latest water bill",
                    "Identity proof",
                    "Photos (for quality issues)",
                ],
                estimated_timeline="15-30 days",
            ),
        },
        GrievanceCategory.TRANSPORT: {
            "default": SubmissionRoute(
                portal_name="Parivahan Sewa / State RTO Portal",
                portal_url="https://parivahan.gov.in/ / State RTO website",
                department="Regional Transport Office / State Transport Department",
                level="state",
                steps=[
                    "Visit https://parivahan.gov.in/ for licence-related services",
                    "For complaints: Use 'Grievance' section on Parivahan or state RTO portal",
                    "Submit application with details",
                    "Track status with application number",
                ],
                required_documents=[
                    "Application reference number",
                    "Learner's licence / driving licence details",
                    "Identity and address proof",
                ],
                estimated_timeline="15-30 days for licence; varies for permits",
            ),
        },
        GrievanceCategory.HEALTH: {
            "default": SubmissionRoute(
                portal_name="State Health Department Portal / NHM Grievance / CPGRAMS",
                portal_url="State health department website / https://pgportal.gov.in/",
                department="State Health Department / NHM",
                level="state",
                steps=[
                    "Complain to Hospital Medical Superintendent first",
                    "Then to Chief Medical Officer (CMO) of district",
                    "Then to State Health Department / NHM grievance portal",
                    "Also available on CPGRAMS under 'Health' category",
                ],
                required_documents=[
                    "Medical records / prescriptions",
                    "Identity proof",
                    "Hospital bills / receipts",
                    "Written complaint",
                ],
                estimated_timeline="15-60 days",
            ),
        },
        GrievanceCategory.EDUCATION: {
            "default": SubmissionRoute(
                portal_name="State Education Department Portal / CPGRAMS / NCPCR",
                portal_url="State education department website / https://pgportal.gov.in/ / http://ncpcr.gov.in/",
                department="State Education Department / NCPCR (for child rights)",
                level="state",
                steps=[
                    "Complain to School/College Principal first",
                    "Then to District Education Officer (DEO)",
                    "Then to State Education Department / Directorate",
                    "For RTE/child rights: NCPCR portal",
                ],
                required_documents=[
                    "Admission application / receipt",
                    "Identity proof (student & parent)",
                    "Caste/income certificate (for RTE/EWS)",
                    "Correspondence with school",
                ],
                estimated_timeline="15-60 days",
            ),
        },
        GrievanceCategory.FOOD_CIVIL_SUPPLIES: {
            "default": SubmissionRoute(
                portal_name="State Food & Civil Supplies Portal / CPGRAMS",
                portal_url="State FCS department website / https://pgportal.gov.in/",
                department="Food & Civil Supplies Department",
                level="state",
                steps=[
                    "Complain to FPS dealer first",
                    "Then to District Supply Officer / Assistant Supply Officer",
                    "Then to State Food Commission / FCS Department",
                    "Also on CPGRAMS under 'Food & Public Distribution'",
                ],
                required_documents=[
                    "Ration card copy",
                    "Identity proof",
                    "FPS details",
                    "Photos (for quality issues)",
                ],
                estimated_timeline="15-30 days",
            ),
        },
        GrievanceCategory.SOCIAL_WELFARE: {
            "default": SubmissionRoute(
                portal_name="State Social Welfare Portal / NSAP Portal / CPGRAMS",
                portal_url="https://nsap.nic.in/ / State social welfare website / https://pgportal.gov.in/",
                department="Social Welfare Department / Ministry of Rural Development (NSAP)",
                level="central/state",
                steps=[
                    "Verify status on NSAP portal (for central schemes)",
                    "Complain to Block Development Officer (BDO)",
                    "Then to District Social Welfare Officer",
                    "Then to State Social Welfare Department",
                ],
                required_documents=[
                    "Pension PPO number / application number",
                    "Aadhaar and bank passbook copy",
                    "Identity proof",
                    "Life certificate (if applicable)",
                ],
                estimated_timeline="30-60 days",
            ),
        },
        GrievanceCategory.LABOUR: {
            "default": SubmissionRoute(
                portal_name="State Labour Department Portal / CPGRAMS / EPFO Grievance",
                portal_url="State labour department website / https://pgportal.gov.in/ / https://epfigms.gov.in/",
                department="Labour Department / EPFO / ESIC",
                level="state",
                steps=[
                    "Approach Labour Commissioner / Assistant Labour Commissioner",
                    "For PF: EPFO Grievance Portal (EPFiGMS)",
                    "For ESI: ESIC Grievance Portal",
                    "File claim in Labour Court if needed",
                ],
                required_documents=[
                    "Employment proof (appointment letter, ID card)",
                    "Salary slips / bank statements",
                    "PF/ESI number",
                    "Identity proof",
                ],
                estimated_timeline="60-180 days (Labour Court longer)",
            ),
        },
        GrievanceCategory.COOPERATIVE: {
            "default": SubmissionRoute(
                portal_name="Registrar of Cooperative Societies (State) / CPGRAMS",
                portal_url="State RCS website / https://pgportal.gov.in/",
                department="Registrar of Cooperative Societies",
                level="state",
                steps=[
                    "File complaint with Society Secretary/Chairman first",
                    "Then approach Registrar of Cooperative Societies (District/State)",
                    "Appeal to Cooperative Tribunal if needed",
                ],
                required_documents=[
                    "Society membership proof",
                    "Share certificate",
                    "Written complaint",
                    "Society registration number",
                ],
                estimated_timeline="60-120 days",
            ),
        },
        GrievanceCategory.AGRICULTURE: {
            "default": SubmissionRoute(
                portal_name="PMFBY Portal / State Agriculture Department / CPGRAMS",
                portal_url="https://pmfby.gov.in/ / State agriculture website / https://pgportal.gov.in/",
                department="Agriculture Department / Insurance Company / Ministry of Agriculture",
                level="central/state",
                steps=[
                    "For PMFBY: Lodge complaint on https://pmfby.gov.in/ 'Grievance' section",
                    "Contact insurance company nodal officer",
                    "Escalate to State Agriculture Department / District Agriculture Officer",
                    "Also on CPGRAMS under 'Agriculture'",
                ],
                required_documents=[
                    "PMFBY application / enrollment ID",
                    "Land records (7/12 extract, khatauni)",
                    "Bank passbook (for premium debit proof)",
                    "Crop cutting experiment report (if available)",
                    "Identity proof",
                ],
                estimated_timeline="PMFBY: 30-45 days for claim; Subsidy: 60-90 days",
            ),
        },
        GrievanceCategory.BANKING: {
            "default": SubmissionRoute(
                portal_name="Bank Internal Grievance / Banking Ombudsman / RBI CMS",
                portal_url="Bank's website / https://cms.rbi.org.in/ / https://bankingombudsman.rbi.org.in/",
                department="Bank / RBI Banking Ombudsman",
                level="central",
                steps=[
                    "First: Write to bank's grievance redressal officer (email/branch)",
                    "Wait 30 days for bank response",
                    "Then: File complaint with Banking Ombudsman (RBI)",
                    "Online at https://cms.rbi.org.in/ (Complaint Management System)",
                ],
                required_documents=[
                    "Bank complaint reference number",
                    "Bank's reply (or proof of 30-day wait)",
                    "Account statement",
                    "Identity proof",
                    "Supporting transaction documents",
                ],
                estimated_timeline="Bank: 30 days; Ombudsman: 60-90 days",
            ),
        },
    }

    def get_submission_route(self, draft: GrievanceDraft, language: str = "en") -> SubmissionRoute:
        """Get the official submission route for a grievance draft."""
        category_map = self.PORTAL_MAP.get(draft.category, {})
        route = category_map.get(draft.sub_category, category_map.get("default"))

        if route is None:
            return SubmissionRoute(
                portal_name="CPGRAMS (Centralized Public Grievance Redressal)",
                portal_url="https://pgportal.gov.in/",
                department="Department of Administrative Reforms and Public Grievances",
                level="central",
                steps=[
                    "Visit https://pgportal.gov.in/",
                    "Register and lodge grievance",
                    "Select appropriate Ministry/Department",
                    "Submit with supporting documents",
                ],
                required_documents=[
                    "Identity proof",
                    "Grievance details",
                    "Supporting documents",
                ],
                estimated_timeline="30-45 days",
            )

        if draft.category == GrievanceCategory.MUNICIPAL:
            route = self._localize_municipal_route(route, draft, language)

        return route

    def _resolve_location_context(self, draft: GrievanceDraft) -> tuple[str | None, str | None]:
        """Best-effort extraction of the citizen's actual city and state.

        Municipal jurisdiction is local, so it must be resolved from
        what the citizen actually said -- never from a fixed example
        city. Returns (city, state); either may be ``None`` if it
        couldn't be determined from the draft.

        The grievance schema stores this as a single free-text
        ``locality`` entity (e.g. "Manjalpur, Vadodara") rather than
        separate locality/city/district fields. Rather than changing
        that schema (which would ripple through entity extraction,
        field detection and the UI), this normalizes it internally:
        the LAST comma-separated segment is treated as the governing
        city/town, since citizens consistently give locality first and
        city second ("<locality>, <city>").

        The city can end up split across THREE different places
        depending on how the conversation unfolded, so all three are
        checked, in order of how directly they name the city:

          1. A comma inside the ``locality`` entity itself
             ("Manjalpur, Vadodara" answered in one go).
          2. A separate ``district``/``city`` entity, when the
             semantic extraction layer already split the city out
             on its own (e.g. from "Ward 5. Zadeshwar, Bharuch.").
          3. The citizen's ORIGINAL complaint narrative. If the
             locality follow-up question is later answered with just
             the locality name alone ("Manjalpur", no city), the city
             named earlier in the very first message ("...in
             Manjalpur, Vadodara.") must not be discarded -- it is
             recovered from ``draft.description`` rather than
             re-extracted or guessed.
        """
        city = None
        locality_entity = draft.entities.get("locality") if draft.entities else None
        locality_value = (locality_entity.value or "").strip() if locality_entity else ""
        if locality_value:
            parts = [p.strip() for p in locality_value.split(",") if p.strip()]
            if parts:
                city = parts[-1] if len(parts) > 1 else None

        if not city:
            for key in ("district", "city", "city_name"):
                entity = draft.entities.get(key) if draft.entities else None
                if entity and entity.value and entity.value.strip():
                    city = entity.value.strip()
                    break

        municipality_entity = draft.entities.get("municipality") if draft.entities else None
        if not city and municipality_entity and municipality_entity.value:
            city = municipality_entity.value.strip()

        if not city and draft.description:
            match = _LOCATION_IN_TEXT_RE.search(draft.description)
            if match:
                city = match.group(2).strip()

        resolved_state = self._resolve_state(city, draft.state)
        if draft.state is None and resolved_state is not None:
            draft.state = resolved_state
        # Persist city into draft entities so to_canonical_dict can find it.
        if city and draft.entities is not None:
            existing_city = draft.entities.get("city_name") or draft.entities.get("city")
            if not existing_city or not (existing_city.value or "").strip():
                draft.entities["city_name"] = GrievanceEntity(
                    name="city_name",
                    value=city,
                    confidence=0.85,
                    source_text="resolved from locality",
                )
        return city, resolved_state

    def _resolve_state(self, city: str | None, draft_state: str | None) -> str | None:
        """Return the best-available state.

        If the draft already has a valid state, use it.  Otherwise, if we
        know the city, look it up in the small ``_CITY_TO_STATE``
        mapping.  Returns ``None`` only when neither source provides a
        state.
        """
        if draft_state:
            return draft_state
        if city:
            return _CITY_TO_STATE.get(city.lower())
        return None

    def _resolve_local_authority(self, city: str) -> str:
        """Resolve the governing local body's name for a city/town.

        This is a naming convention, not a guessed URL: Indian ``.gov.in``/
        ``.nic.in`` civic bodies are consistently named "<City> Municipal
        Corporation" (or Nagar Palika/Nagar Parishad for smaller towns).
        We don't have population/tier data to pick between those, so we
        use the common "Municipal Corporation" form and hedge it with
        "/ Urban Local Body" so the name is not overly specific for a
        town that is actually governed by a Nagar Palika/Panchayat --
        this never invents a URL, only a plain-language authority label.
        """
        return f"{city} Municipal Corporation / Urban Local Body"

    def _try_verify_official_portal(self, city: str, state: str | None) -> str | None:
        """Best-effort attempt to find a verified official (.gov.in/.nic.in)
        portal for the resolved local authority, reusing the project's
        existing Tavily web-discovery client rather than building a
        second lookup system.

        This NEVER fabricates a URL: it only returns a link that Tavily
        actually surfaced and that resolves to an official government
        domain. Any failure (no API key configured, network disabled,
        no matching official-domain result, or any other exception) is
        swallowed and treated as "could not verify" -- this method is
        purely an optional enhancement and must never break grievance
        routing if web discovery is unavailable.
        """
        try:
            from web_discovery.tavily_client import TavilyClient
        except Exception:
            return None

        official_suffixes = (".gov.in", ".nic.in")

        try:
            client = TavilyClient()

            if not client.is_configured():
                return None

            query = f"{city} municipal corporation official website"
            if state:
                query = f"{city} {state} municipal corporation official website"

            result = client.search(
                query,
                max_results=5,
                include_domains=["gov.in", "nic.in"],
                include_raw_content=False,
            )

            for item in (result or {}).get("results", []):
                url = (item or {}).get("url", "")
                host = urlparse(url).netloc.lower()
                if host and any(host == d or host.endswith("." + d) for d in ("gov.in", "nic.in")):
                    return url
                if any(suffix in url.lower() for suffix in official_suffixes):
                    return url

        except Exception:
            return None

        return None

    def _localize_municipal_route(self, route: SubmissionRoute, draft: GrievanceDraft, language: str = "en") -> SubmissionRoute:
        """Rewrite a municipal route so it points at the citizen's
        ACTUAL governing local authority, resolved from
        locality -> city -> state, instead of either a generic
        placeholder or (the previous bug) a hardcoded Mumbai/MCGM
        example.

        The locality itself (e.g. "Manjalpur", "Zadeshwar") is never
        treated as the authority -- it is a neighbourhood inside a
        city, and the authority is resolved one level up the
        hierarchy. If the city can't be determined at all, this says
        so honestly rather than guessing.

        All user-facing strings are built via localized templates so
        they are NEVER in English when the user's language is non-English.
        """
        from app.grievance.translations import translate_template

        city, state = self._resolve_location_context(draft)

        if not city:
            # Use localized templates for the generic fallback
            portal_name = translate_template(
                "portal_municipal_with_authority", language,
                authority=translate_template(
                    "department_municipal_with_authority", language, city="",
                ) if language != "en" else "Municipal Corporation / Urban Local Body",
            ) if language != "en" else "Municipal Corporation / Urban Local Body Citizen Portal"
            department = route.department  # "Urban Local Body / Municipal Corporation"
            portal_url = (
                "The official portal URL could not be automatically "
                "verified. Please visit the Municipal Corporation / "
                "Urban Local Body website directly."
            )
            first_step = translate_template(
                "step_identify_municipal_authority", language,
            )
        else:
            authority = self._resolve_local_authority(city)
            location_label = f"{city}, {state}" if state else city

            if language != "en":
                portal_name = translate_template(
                    "portal_municipal_with_authority", language,
                    authority=authority,
                )
                department = translate_template(
                    "department_municipal_with_city", language,
                    city=city,
                )
                first_step = translate_template(
                    "step_visit_authority_for_location", language,
                    authority=authority,
                    location=location_label,
                )
            else:
                portal_name = f"{authority} — Citizen Grievance Portal"
                department = authority
                first_step = f"Visit the official {authority} website for {location_label}"

            verified_url = self._try_verify_official_portal(city, state)
            if verified_url:
                portal_url = verified_url
            else:
                portal_url = (
                    f"The official portal URL for {location_label} "
                    "could not be automatically verified. "
                    f"Please visit the {authority} website directly."
                )

        # must never replace the resolved local authority just because
        escalation_step = translate_template(
            "step_escalation_cpgrams_municipal", language,
        )

        new_steps = [first_step] + list(route.steps[1:]) + [escalation_step]

        return replace(
            route,
            portal_name=portal_name,
            portal_url=portal_url,
            department=department,
            steps=new_steps,
        )

    def format_route_for_display(self, route: SubmissionRoute) -> str:
        """Format submission route for user display."""
        lines = [
            "**📋 Official Submission Route (Prototype Reference)**",
            "",
            f"**Portal:** {route.portal_name}",
            f"**URL:** {route.portal_url}",
            f"**Department:** {route.department}",
            f"**Level:** {route.level.title()}",
            "",
            "**Steps to Submit:**",
        ]

        for i, step in enumerate(route.steps, 1):
            lines.append(f"  {i}. {step}")

        lines.append("")
        lines.append("**Required Documents:**")
        for doc in route.required_documents:
            lines.append(f"  • {doc}")

        lines.append("")
        lines.append(f"**Estimated Timeline:** {route.estimated_timeline}")
        lines.append("")
        lines.append(f"⚠ **Disclaimer:** {route.disclaimer}")

        return "\n".join(lines)
