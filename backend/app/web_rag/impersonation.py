"""P1-6 impersonation / look-alike detection (conservative).

A result is quarantined (never authoritative evidence, may remain a
lead) ONLY on structural impersonation signals. No giant blacklist:
the mandate map + official suffixes define known-good, and a small
brand list (~35 entries) plus structural rules catch the rest.

Signals (any one quarantines):
  punycode                 e.g. xn--pib-gov-abc.in
  gov_token_unverified     gov/govt/nic/sarkari/sarkar tokens on a
                           domain outside verified government suffixes
  brand_lookalike          authority/scheme/regulator brand in the
                           domain whose verified owner is someone else

Known-good early returns (never flagged): mandate-map owners,
gov.in/nic.in (+s3waas) suffixes, trusted secondaries, .bank.in
(regulated banks), .ac.in/.edu (accredited), and unknown domains
without any signal (ranking handles quality; this module judges
impersonation only).

Effect: ``screen_result`` stamps {"suspicious", "reason"}; rescore
applies a strong penalty (fraud risk outranks staleness); the shared
citation bar excludes quarantined chunks via lead_only.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from app.web_rag.mandate_map import find_org

logger = logging.getLogger(__name__)

# Verified government suffixes (GIGW rule: restricted to government).
_VERIFIED_GOV_SUFFIXES = ("gov.in", "nic.in")

# Trusted non-government suffixes with external accreditation.
_TRUSTED_SUFFIXES = (".bank.in", ".ac.in", ".edu")

# Trustworthy secondary hosts carried over from the existing pipeline.
_TRUSTED_HOSTS = {
    "prsindia.org",
    "indiacode.nic.in",
    "sci.gov.in",
    "niti.gov.in",
}

# Government-brand tokens for unverified-domain detection. Geographic
# names and generic words (yojana, sahay, portal, sarkar-variants are
# covered by the gov-token rule) are deliberately excluded.
_GOV_TOKENS = {"gov", "govt", "nic", "sarkari", "sarkar"}

_BRANDS = {
    "anyror", "gujaratgr", "gazette", "pib", "pmo", "pmkisan",
    "pmfby", "ikhedut", "digitalgujarat", "swagat", "rcs", "crcs",
    "cea", "rbi", "irdai", "dicgc", "nabard", "ncdc", "myscheme",
    "eshram", "cpgrams", "cpgram", "sachet", "cybercrime",
    "bimabharosa", "bima", "uidai", "aadhaar", "aadhar",
    "incometax", "sbi", "pnb", "canara", "unionbank", "npci",
    "jansuraksha", "pfms", "digilocker",
}

# TLDs that upgrade an unbounded brand-substring match to suspicious.
_SUSPICIOUS_TLDS = {
    "xyz", "top", "click", "online", "site", "store", "app",
    "vip", "live", "fun", "work",
}


def _domain(url: str) -> str:
    try:
        netloc = urlparse(str(url or "")).netloc.lower()
        netloc = netloc.split("@")[-1].split(":")[0]
        return netloc.removeprefix("www.").rstrip(".")
    except Exception:
        return ""


def _is_known_good(domain: str) -> bool:
    if not domain:
        return False
    if find_org(domain) is not None:
        return True
    if domain in _TRUSTED_HOSTS:
        return True
    if any(
        domain == suffix.lstrip(".") or domain.endswith("." + suffix.lstrip("."))
        for suffix in _VERIFIED_GOV_SUFFIXES
    ):
        return True
    if any(domain.endswith(suffix) for suffix in _TRUSTED_SUFFIXES):
        return True
    return False


def _labels(domain: str) -> list[str]:
    return [label for label in re.split(r"[.\-]+", domain) if label]


def assess_impersonation(url: str, title: str = "") -> dict:
    """Assess impersonation risk. Returns {"suspicious": bool, "reason"}."""
    domain = _domain(url)

    if not domain:
        return {"suspicious": False, "reason": None}

    if _is_known_good(domain):
        return {"suspicious": False, "reason": None}

    if domain.startswith("xn--") or ".xn--" in domain:
        return {"suspicious": True, "reason": "punycode"}

    tokens = set(_labels(domain))

    if tokens & _GOV_TOKENS:
        return {"suspicious": True, "reason": "gov_token_unverified"}

    for brand in sorted(_BRANDS):
        if brand in tokens:
            return {"suspicious": True, "reason": f"brand_lookalike:{brand}"}

    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if tld in _SUSPICIOUS_TLDS:
        compact = re.sub(r"[.\-0-9]+", "", domain)
        for brand in sorted(_BRANDS):
            if brand in compact:
                return {"suspicious": True, "reason": f"brand_lookalike:{brand}"}

    return {"suspicious": False, "reason": None}


def screen_result(result: dict) -> dict:
    """Stamp a normalized chunk with impersonation screening.

    Quarantined chunks gain ``lead_only=True`` (shared citation bar)
    but are never deleted — they may still yield leads.
    """
    if not isinstance(result, dict):
        return {"suspicious": False, "reason": None}

    url = result.get("source_url") or result.get("url") or ""
    title = result.get("web_title") or result.get("title") or ""
    verdict = assess_impersonation(url, title)
    result["impersonation"] = verdict

    if verdict.get("suspicious") and not result.get("lead_only"):
        result["lead_only"] = True

    return verdict
