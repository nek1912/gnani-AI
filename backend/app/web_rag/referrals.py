"""P1-5 structured referral on unresolved abstention.

When no sufficient authoritative evidence exists, the abstain response
carries a ``referral`` payload: what is missing, the known
jurisdiction, and — only when confidently known from the mandate map —
the competent authority and its official channel.

ANTI-FABRICATION RULES (enforced by construction, tested):
- Authority names and channel domains come ONLY from mandate_map.json.
- No phone numbers (the map carries none, so none can be emitted).
- No deep URLs: channels are bare verified domains, never links.
- No offices/addresses/deadlines/procedures are stated.
- When nothing is confidently known, authority/channel are None and
  the summary says so — never a guess.
- Referrals attach ONLY to abstained responses; the evidence gate is
  never bypassed (the gate already abstained before this runs).
"""

from __future__ import annotations

import logging

from app.web_rag.mandate_map import load_mandate_map, query_subjects

logger = logging.getLogger(__name__)

_MISSING_PHRASING = {
    "NO": "sufficient authoritative evidence",
    "WEAK": "sufficient authoritative evidence",
    "CONFLICTING": "consistent authoritative evidence",
    "WRONG_JURISDICTION": "jurisdiction-matching authoritative evidence",
    "OUTDATED": "current, in-force authoritative evidence",
    "PARTIAL": "complete evidence for all parts of the question",
    "VALID_BUT_LOW_SCORE": "strongly matching authoritative evidence",
    "TERMINAL": "sufficient authoritative evidence",
    "SUFFICIENT": "sufficient authoritative evidence",
}


# Sectoral subjects owned by regulators, not by general grievance
# bodies: a banking/insurance/credit complaint must refer to RBI/IRDAI
# even when a state grievance body also matches "grievance".
_SECTORAL_SUBJECTS = {"banking", "insurance", "credit", "fraud", "consumer"}


def _rank_orgs(
    subjects: set[str],
    state: str | None,
    society_type: str | None = None,
) -> list[dict]:
    """Mandate orgs ranked for referral.

    Overlap dominates: the most competent publisher wins. Jurisdiction
    breaks ties (assumed state is weak evidence, so equal-overlap
    contests still prefer the home publisher), then grievance-mandate
    in complaint context.
    """
    state_l = (state or "").lower()
    complaint_context = bool(subjects & {"grievance", "fraud", "consumer"})
    ranked: list[tuple[int, int, int, dict]] = []

    for org in load_mandate_map():
        jurisdiction = str(org.get("jurisdiction", "")).lower()

        # MSCS questions are central-jurisdiction by definition: state
        # orgs are never competent referral targets.
        if society_type == "mscs" and jurisdiction not in (
            "central", "institutional",
        ):
            continue

        overlap = set(org.get("mandate_subjects", [])) & subjects
        if not overlap:
            continue
        if jurisdiction == state_l and state_l:
            place = 0
        elif jurisdiction == "central":
            place = 1
        elif jurisdiction == "institutional":
            place = 2
        elif jurisdiction == "gujarat" and not state_l:
            place = 1
        else:
            continue

        # Sectoral complaints belong to sectoral regulators: a generic
        # grievance-body match on "grievance" alone deprioritizes.
        if (subjects & _SECTORAL_SUBJECTS) and not (
            overlap & _SECTORAL_SUBJECTS
        ):
            place += 10

        # In complaint context, ties break toward orgs holding a
        # grievance mandate (regulators over member banks).
        org_subjects = set(org.get("mandate_subjects", []))
        grievance_gap = 0
        if complaint_context and not (
            org_subjects & {"grievance", "fraud", "consumer"}
        ):
            grievance_gap = 1

        ranked.append((place, -len(overlap), grievance_gap, org))

    ranked.sort(key=lambda item: (item[1], item[0], item[2]))
    return [org for _, _, _, org in ranked]


def build_referral(
    classification,
    evidence_state: str | None = None,
    uncovered_facets: list[str] | None = None,
) -> dict | None:
    """Build a structured referral, or None when nothing is confident.

    Returns {"summary", "jurisdiction": {"state", "district"} | None,
    "authority": org-name | None, "channel": domain | None,
    "missing": [...], "evidence_state": str} — all values are either
    classification facts or mandate-map facts.
    """
    if classification is None:
        return None

    domain = getattr(classification, "domain", None) or "general"
    subjects = query_subjects(
        domain, getattr(classification, "society_type", None)
    )
    state = getattr(classification, "state", None)
    district = getattr(classification, "district", None)

    if not subjects and not state:
        return None

    state_key = (evidence_state or "WEAK").upper()
    missing = [_MISSING_PHRASING.get(state_key, _MISSING_PHRASING["WEAK"])]
    for facet in uncovered_facets or []:
        if isinstance(facet, str) and facet:
            missing.append(f"details on: {facet}")

    jurisdiction = None
    if state or district:
        jurisdiction = {"state": state, "district": district}

    authority = None
    channel = None
    for org in _rank_orgs(
        subjects, state, getattr(classification, "society_type", None)
    ):
        domains = [d for d in org.get("domains", []) if d]
        if not domains:
            continue
        authority = org.get("organisation")
        channel = domains[0]
        break

    parts = [f"Could not establish {missing[0]}."]
    if district and state:
        parts.append(f"Jurisdiction on record: {district} district, {state}.")
    elif state:
        parts.append(f"Jurisdiction on record: {state}.")
    if authority:
        parts.append(f"Competent authority to approach: {authority}.")
        if channel:
            parts.append(f"Official channel: {channel}.")
    else:
        parts.append("No single competent authority could be confidently identified.")

    return {
        "summary": " ".join(parts),
        "jurisdiction": jurisdiction,
        "authority": authority,
        "channel": channel,
        "missing": missing,
        "evidence_state": state_key,
    }
