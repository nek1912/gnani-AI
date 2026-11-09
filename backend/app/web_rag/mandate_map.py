"""P0-3 mandate map: data-driven, question-relative authority.

The JSON file (mandate_map.json, same directory) is DATA ONLY. This
module contains the small deterministic helpers that read it:

- anchors_for_domain(): subject + jurisdiction scoped anchor domains
  for the jurisdiction-first retrieval branch.
- mandate_fit(): publisher-competence ranking signal (0.0 - 0.30).
- document_role(): minimal instrument/implementation/explainer/
  secondary classification from conservative URL/title cues.

Authority scoring itself (source_tier, trust scores, gates) is NOT
replaced — these helpers only add question-relative signals.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MAP_PATH = Path(__file__).with_name("mandate_map.json")

MAX_ANCHORS = 15

# Query domain -> mandate subjects (controlled vocabulary from the map).
DOMAIN_SUBJECTS: dict[str, set[str]] = {
    "cooperative": {"cooperative", "disputes", "audit", "law", "mscs"},
    "pacs": {"pacs", "cooperative", "credit"},
    "pacs_governance": {"pacs", "cooperative", "credit"},
    "pacs_computerization": {"pacs", "cooperative"},
    "pmfby": {"crop_insurance", "crop_relief"},
    "agriculture": {"agriculture", "subsidy", "irrigation", "msp", "advisory", "crop_relief", "crop_insurance"},
    "schemes": {"welfare", "subsidy", "agriculture", "livelihood"},
    "finlit": {"credit", "banking", "insurance"},
    "financial_inclusion": {"credit", "banking", "insurance"},
    "grievance": {"grievance", "fraud", "consumer", "banking", "insurance"},
    "driving_licence": set(),
    "general": set(),
}

_MSCS_SUBJECTS = {"mscs", "cooperative"}

# Conservative document-role cues (English URL/title vocabulary only in
# P0; Gujarati document-type words join via the P0-4 lexicon extension).
# P2 audit fix: short cues ("act", "sop") match as substrings inside
# ordinary words ("contact" contains "act") — they now require word
# boundaries, while len>=4 cues keep substring matching (so "egazette"
# still matches "gazette"). "GR" uses the standalone-token regex below.
_INSTRUMENT_PATH_CUES = [
    "act", "rules", "gazette", "resolution",
    "order", "sop", "margdarshika", "direction",
]

_SHORT_PATH_CUES = {"act", "sop"}

_INSTRUMENT_BLOB_CUES = [
    "gazette", "notification", "circular", "guidelines",
    "margdarshika", "master direction", "ombudsman scheme",
    "bye-law", "byelaw", "bye-laws",
]

_IMPLEMENTATION_PORTALS = {
    "pmfby.gov.in",
    "ikhedut.gujarat.gov.in",
    "digitalgujarat.gov.in",
    "fasalrin.gov.in",
    "gjfr.agristack.gov.in",
    "bimabharosa.irdai.gov.in",
    "pgportal.gov.in",
    "cpgrams.gov.in",
    "cybercrime.gov.in",
    "myscheme.gov.in",
    "anyror.gujarat.gov.in",
    "swagat.gujarat.gov.in",
    "onlinerti.gujarat.gov.in",
    "ggrc.co.in",
    "pmkusum.guvnl.com",
}

_IMPLEMENTATION_PATH_CUES = [
    "apply", "application", "register", "registration", "portal",
    "login", "sign-in", "signin", "status", "track", "tracking",
    "form", "forms", "online", "how-to", "enroll", "enrollment",
]

_ANNOUNCEMENT_CUES = [
    "press", "pressrelease", "press-release", "pib", "news",
    "announcement", "prid", "note", "factsheet",
]


def _extend_cues_with_lexicon() -> None:
    """Add lexicon-verified Gujarati/Hindi document-type words to the
    instrument cues (P0-4). Verified terms only — the lexicon file is
    the single source; failures leave English cues untouched.

    Short ASCII terms (e.g. "GR") are SKIPPED: as substring cues they
    misfire inside ordinary words ("grievance", "agreement"). The
    standalone-GR case is covered by the word-boundary regex in
    document_role instead.
    """
    try:
        from app.web_rag.lexicon import document_type_terms

        for language in ("gu", "hi"):
            for term in document_type_terms(language):
                lowered = term.lower()
                if (
                    lowered not in _INSTRUMENT_BLOB_CUES
                    and len(lowered) >= 4
                ):
                    _INSTRUMENT_BLOB_CUES.append(term)
    except Exception:
        logger.warning("Lexicon doc-type extension skipped", exc_info=True)


_extend_cues_with_lexicon()


@lru_cache(maxsize=1)
def load_mandate_map() -> list[dict]:
    """Load the mandate map data file (cached). Returns org entries."""
    try:
        with open(_MAP_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        logger.warning("Mandate map unavailable at %s", _MAP_PATH)
        return []

    orgs = data.get("organisations", [])
    return [o for o in orgs if isinstance(o, dict)]


@lru_cache(maxsize=1)
def _domain_index() -> dict[str, dict]:
    """Map normalized domain -> owning org entry (first owner wins)."""
    index: dict[str, dict] = {}
    for org in load_mandate_map():
        for domain in org.get("domains", []):
            key = str(domain).lower().strip()
            if key and key not in index:
                index[key] = org
    return index


def _normalize_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        netloc = netloc.split("@")[-1].split(":")[0]
        return netloc.removeprefix("www.").rstrip(".")
    except Exception:
        return ""


def find_org(domain_or_url: str) -> dict | None:
    """Find the owning org for a domain or URL (exact-or-suffix match)."""
    text = str(domain_or_url or "").lower().strip()
    if "://" in text:
        domain = _normalize_domain(text)
    else:
        domain = text.removeprefix("www.").rstrip(".")

    if not domain:
        return None

    index = _domain_index()

    if domain in index:
        return index[domain]

    for known, org in index.items():
        if domain.endswith("." + known):
            return org

    return None


def query_subjects(
    domain: str | None,
    society_type: str | None = None,
) -> set[str]:
    """Mandate subjects relevant to a query's domain and society type."""
    subjects = set(DOMAIN_SUBJECTS.get(domain or "general", set()))
    if society_type == "mscs":
        subjects |= _MSCS_SUBJECTS
    return subjects


def anchors_for_domain(
    domain: str | None,
    state: str | None,
    society_type: str | None = None,
    jurisdiction: str | None = None,
) -> list[str] | None:
    """Subject + jurisdiction scoped anchor domains (cap MAX_ANCHORS).

    Returns None when the map yields no anchors (caller falls back to
    existing behavior). MSCS questions scope to central cooperative
    anchors only — never Gujarat RCS sources.
    """
    subjects = query_subjects(domain, society_type)

    if not subjects:
        return None

    state_l = (state or "").lower()
    mscs_only = society_type == "mscs"

    ranked: list[tuple[int, str]] = []

    for org in load_mandate_map():
        org_subjects = set(org.get("mandate_subjects", []))
        overlap = subjects & org_subjects

        if not overlap:
            continue

        org_jurisdiction = str(org.get("jurisdiction", "")).lower()

        if mscs_only and org_jurisdiction not in ("central", "institutional"):
            continue

        if (
            org_jurisdiction == "gujarat"
            and state_l
            and state_l != "gujarat"
        ):
            continue

        # Rank: jurisdiction match first, then central, then institutional.
        if org_jurisdiction == state_l and state_l:
            rank = 0
        elif org_jurisdiction == "central":
            rank = 1
        elif org_jurisdiction == "institutional":
            rank = 2
        elif org_jurisdiction == "gujarat" and not state_l:
            rank = 1
        else:
            rank = 3

        for publisher in org.get("domains", []):
            ranked.append((rank, str(publisher)))

    if not ranked:
        return None

    seen: set[str] = set()
    anchors: list[str] = []

    for _, publisher in sorted(ranked, key=lambda item: item[0]):
        if publisher not in seen:
            seen.add(publisher)
            anchors.append(publisher)

        if len(anchors) >= MAX_ANCHORS:
            break

    return anchors or None


def mandate_fit(
    url: str,
    subjects: set[str] | None,
    state: str | None,
    society_type: str | None = None,
) -> float:
    """Publisher-competence signal for question-relative authority.

    0.40: MSCS question + publisher holding an MSCS mandate (CRCS/CEA).
    0.30: known publisher whose mandate covers the query subject in a
        compatible jurisdiction (central/institutional publishers are
        compatible everywhere; state publishers only at home).
    0.10: known publisher, subject outside its mandate (adjacent).
    0.00: unknown publisher; state publisher out of jurisdiction; or
        state publisher for an MSCS question (no competence over
        multi-state societies).
    """
    if not subjects:
        return 0.0

    org = find_org(url)

    if org is None:
        return 0.0

    state_l = (state or "").lower()
    org_jurisdiction = str(org.get("jurisdiction", "")).lower()
    org_subjects = set(org.get("mandate_subjects", []))

    if society_type == "mscs":
        if org_jurisdiction not in ("central", "institutional"):
            return 0.0
        if "mscs" in org_subjects and "mscs" in (subjects or set()):
            return 0.40

    if org_jurisdiction not in ("central", "institutional"):
        if state_l and org_jurisdiction != state_l:
            return 0.0
        if not state_l and org_jurisdiction not in ("central", "institutional"):
            return 0.0

    if subjects & org_subjects:
        return 0.30

    return 0.10


def document_role(
    url: str,
    title: str,
    official: bool = False,
    trusted_secondary: bool = False,
) -> str:
    """Minimal document-role classification.

    instrument: the rule itself (Act/Rules/Gazette/GR/circular/
        guidelines/directions/ombudsman scheme).
    implementation: the apply/track/status/portal page.
    explainer: official communication that explains but does not
        create rules (press/PIB/announcements).
    secondary: everything else (non-official without cues).

    Conservative by design: cues must match; an opaque official PDF
    with no cue words is "explainer", never a guessed instrument.
    """
    try:
        path = (urlparse(url).path or "").lower()
    except Exception:
        path = ""

    title_l = str(title or "").lower()
    blob = path + " " + title_l
    domain = _normalize_domain(url)

    if any(cue in path for cue in _INSTRUMENT_PATH_CUES
           if cue not in _SHORT_PATH_CUES):
        return "instrument"

    if any(
        re.search(r"\b" + re.escape(cue) + r"\b", path)
        for cue in _SHORT_PATH_CUES
    ):
        return "instrument"

    if any(cue in blob for cue in _INSTRUMENT_BLOB_CUES):
        return "instrument"

    # Standalone "GR" token (Gujarat government-resolution convention,
    # e.g. /gr/... paths or "Crop relief GR 2026" titles). Word-boundary
    # matched so "agreement"/"growing" never trigger it.
    if re.search(r"\bgr\b", blob):
        return "instrument"

    if domain in _IMPLEMENTATION_PORTALS:
        return "implementation"

    if any(cue in blob for cue in _IMPLEMENTATION_PATH_CUES):
        return "implementation"

    if (official or trusted_secondary) and any(
        cue in blob for cue in _ANNOUNCEMENT_CUES
    ):
        return "explainer"

    if official or trusted_secondary:
        return "explainer"

    return "secondary"


def role_bonus(role: str, intent: str) -> float:
    """Additive ranking bonus for document role (inspectable)."""
    if role == "instrument":
        return 0.25
    if role == "implementation":
        return 0.10
    return 0.0


# P1 audit: demotion for publisher/query jurisdiction incompatibility.
# Wrong-forum evidence stays retrievable and citable (no filtering),
# but can no longer outrank competent publishers on BM25 noise alone.
# Only EXPLICIT jurisdiction signals trigger it — assumed state never
# penalizes (assumptions are disclosed, not enforced).
_JURISDICTION_PENALTY = -0.80


def jurisdiction_penalty(
    url: str,
    state: str | None,
    society_type: str | None,
    jurisdiction_source: str | None,
) -> float:
    """Demotion for demonstrably incompetent forums.

    - MSCS question + state-registrar publisher (e.g. Gujarat RCS for
      a multi-state society dispute): the forum lacks competence.
    - Explicit query state X + publisher mandated to another state:
      wrong-state authority.
    Central/institutional publishers are compatible everywhere; unknown
    publishers and assumed states never trigger.
    """
    org = find_org(url)
    if org is None:
        return 0.0

    org_jurisdiction = str(org.get("jurisdiction", "")).lower()

    if society_type == "mscs" and org_jurisdiction not in (
        "central", "institutional",
    ):
        return _JURISDICTION_PENALTY

    if (
        (jurisdiction_source or "none") == "explicit"
        and state
        and org_jurisdiction not in ("central", "institutional")
        and org_jurisdiction != state.lower()
    ):
        return _JURISDICTION_PENALTY

    return 0.0
