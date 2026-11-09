"""P1-1 bounded lead-following: secondary mentions -> primary retrieval.

A low-authority/secondary result may MENTION the evidence we need (a GR
number, a circular reference, a portal name) without BEING evidence.
Lead-following extracts at most MAX_LEADS identifiers and runs ONE
bounded official-targeted round through the existing branch/search
infrastructure. No recursion: lead results never spawn further rounds.
No crawling, no URL traversal — only provider search with anchor
scoping.

Lead chunks are tagged ``lead_only`` and are never authoritative
evidence (shared exclusion with P1-6 quarantine in _build_citations).
"""

from __future__ import annotations

import logging
import re

from app.web_rag.validity import find_instrument_mentions

logger = logging.getLogger(__name__)

MAX_LEADS = 3
LEAD_MAX_RESULTS = 8

# Portal mention -> verified anchor domains (mandate-map domains only;
# unverified hosts such as the KRP portal or PM-KISAN host are never
# targeted directly — subject anchors cover them).
PORTAL_MENTIONS: dict[str, list[str]] = {
    "i-khedut": ["ikhedut.gujarat.gov.in"],
    "ikhedut": ["ikhedut.gujarat.gov.in"],
    "digital gujarat": ["digitalgujarat.gov.in"],
    "anyror": ["anyror.gujarat.gov.in"],
    "any ror": ["anyror.gujarat.gov.in"],
    "7/12": ["anyror.gujarat.gov.in"],
    "swagat": ["swagat.gujarat.gov.in"],
    "pmfby": ["pmfby.gov.in"],
    "fasal rin": ["fasalrin.gov.in"],
    "kisan rin": ["fasalrin.gov.in"],
    "bima bharosa": ["bimabharosa.irdai.gov.in"],
    "rbi cms": ["rbi.org.in"],
    "cms portal": ["rbi.org.in"],
    "cpgrams": ["pgportal.gov.in", "cpgrams.gov.in"],
    "cpgram": ["pgportal.gov.in", "cpgrams.gov.in"],
    "cybercrime": ["cybercrime.gov.in"],
    "1930": ["cybercrime.gov.in"],
    "sachet": ["sachet.rbi.org.in"],
    "myscheme": ["myscheme.gov.in"],
    "farmer registry": ["gjfr.agristack.gov.in"],
    "agristack": ["gjfr.agristack.gov.in"],
    "ggrc": ["ggrc.co.in"],
    "green revolution company": ["ggrc.co.in"],
}

_PORTAL_RES = [
    (re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE), domains)
    for name, domains in PORTAL_MENTIONS.items()
]


def find_portal_mentions(text: str) -> list[dict]:
    """Portal mentions with verified target domains (deduped, ordered)."""
    blob = str(text or "")
    found: list[dict] = []
    seen: set[str] = set()

    for rx, domains in _PORTAL_RES:
        if rx.search(blob):
            key = ",".join(domains)
            if key not in seen:
                seen.add(key)
                found.append({"kind": "portal", "value": rx.pattern.strip("\\b"), "domains": list(domains)})

    return found


def is_lead_source(result: dict) -> bool:
    """A result is a lead source (never evidence) when it is neither
    official nor trusted-secondary."""
    return not bool(result.get("official", False)) and not bool(
        result.get("trusted_secondary", False)
    )


def extract_leads(results: list[dict]) -> list[dict]:
    """Extract leads from lead-source results.

    Each lead: {"kind": "instrument_id"|"portal", "value": str,
    "domains": [...], "source_url": str}. Instrument IDs sort before
    portal mentions (more targeted). No lead is extracted from
    official/trusted chunks — those are evidence already.
    """
    leads: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for result in results:
        if not isinstance(result, dict) or not is_lead_source(result):
            continue

        title = result.get("web_title") or result.get("title") or ""
        text = result.get("text") or result.get("content") or ""
        blob = f"{title}\n{text[:4000]}"
        source_url = result.get("source_url") or result.get("url") or ""

        for identifier in find_instrument_mentions(blob):
            key = ("instrument_id", identifier.lower())
            if key not in seen:
                seen.add(key)
                leads.append(
                    {
                        "kind": "instrument_id",
                        "value": identifier,
                        "domains": [],
                        "source_url": source_url,
                    }
                )

        for portal in find_portal_mentions(blob):
            key = ("portal", ",".join(portal["domains"]))
            if key not in seen:
                seen.add(key)
                leads.append(
                    {
                        "kind": "portal",
                        "value": portal["value"],
                        "domains": portal["domains"],
                        "source_url": source_url,
                    }
                )

    leads.sort(key=lambda lead: 0 if lead["kind"] == "instrument_id" else 1)
    return leads


def select_leads(leads: list[dict], limit: int = MAX_LEADS) -> list[dict]:
    """Keep at most `limit` highest-value leads (hard bound)."""
    return list(leads[: max(0, limit)])


def tag_lead_sources(results: list[dict], leads: list[dict]) -> int:
    """Tag lead-source chunks that produced leads with ``lead_only``.

    Returns the number tagged. Tagging is metadata-only; nothing is
    deleted or reordered here. The citation layer excludes tagged
    chunks from authoritative evidence.
    """
    lead_sources = {lead.get("source_url") for lead in leads if lead.get("source_url")}
    tagged = 0

    for result in results:
        if not isinstance(result, dict):
            continue
        result_url = result.get("source_url") or result.get("url")
        if is_lead_source(result) and result_url in lead_sources:
            if not result.get("lead_only"):
                result["lead_only"] = True
                tagged += 1

    return tagged


def build_lead_branches(
    leads: list[dict],
    classification,
    anchors: list[str] | None,
    fallback_domains: list[str] | None = None,
) -> list[dict]:
    """One targeted official branch per selected lead (hard-bounded).

    The branch query is the identifier plus subject/state context —
    never the lead article's claims. Scoped to mandate anchors (or the
    fallback official set) with the allow_domains mechanism, so only
    official-or-anchor results survive.
    """
    branches: list[dict] = []
    state = getattr(classification, "state", None)
    domain = getattr(classification, "domain", None)
    scoped = anchors or fallback_domains

    for index, lead in enumerate(select_leads(leads)):
        value = str(lead.get("value") or "").strip()
        if not value:
            continue

        context_parts = [value]
        if domain and domain != "general":
            context_parts.append(domain)
        if state:
            context_parts.append(state)

        lead_domains = list(lead.get("domains") or [])
        for anchor in scoped or []:
            if anchor not in lead_domains:
                lead_domains.append(anchor)

        branches.append(
            {
                "name": f"lead:{lead.get('kind')}:{index}",
                "query": " ".join(context_parts),
                "domain": domain,
                "state": state,
                "max_results": LEAD_MAX_RESULTS,
                "chunks_per_source": 3,
                "include_domains": lead_domains or scoped,
                "search_depth": "advanced",
                "include_raw_content": True,
                "only_official": True,
                "allow_domains": lead_domains or scoped,
            }
        )

    return branches
