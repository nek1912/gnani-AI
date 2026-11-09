"""Conservative validity-signal extraction for web discovery results.

P0-2: replaces the URL-year recency proxy with validity-aware metadata.

EXTRACTION CONTRACT (strict):
- Only explicit, stated signals are extracted. Anything ambiguous is
  recorded as None/"unknown".
- NEVER infer supersession from newness: a document is "superseded"
  only when it (or a retrieved peer description of it) explicitly says
  it is replaced/superseded/revoked/withdrawn.
- NEVER guess dates: a bare year mentioned in passing is not a
  publication date. ``published_date`` comes from the provider-supplied
  date only.
- All returned values are JSON-safe (ISO date strings or short labels).

Validity precedence used by retrieval_scorer.freshness_bonus:
    valid for case date  >  unknown validity  >  explicitly superseded.
Recency is only a tiebreaker among otherwise comparable valid results.
"""

from __future__ import annotations

import re
from datetime import date

SUPERSEDED = "superseded"
AMENDED = "amended"
CURRENT = "current"
UNKNOWN_STATUS = "unknown"

_MONTHS = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december"
)

_MONTH_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Explicit effective-from language (English only — verified vocabulary).
_EFFECTIVE_FROM_RES = [
    re.compile(
        r"(?:with effect from|w\.e\.f\.|shall come into force|"
        r"effective from|applicable from|applies from|"
        r"sanctioned from|sanctioned on or after|"
        r"comes into force on|commencement on)\s+"
        r"(.{0,60}?)"
        r"(?=[.;\n]|$)",
        re.IGNORECASE,
    ),
]

# Explicit effective-to / expiry language (tight set, not deadlines).
_EFFECTIVE_TO_RES = [
    re.compile(
        r"(?:valid till|valid until|valid upto|valid up to|"
        r"effective till|effective until|in force till|in force until)\s+"
        r"(.{0,60}?)"
        r"(?=[.;\n]|$)",
        re.IGNORECASE,
    ),
]

# Standalone date shapes (Arabic numerals only; Gujarati/Devanagari
# numerals are intentionally unsupported in P0).
_DATE_RES = [
    # 12 August 2026 / 12th August, 2026
    re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTHS + r")[,]?\s+(19\d{2}|20\d{2})\b",
        re.IGNORECASE,
    ),
    # August 12, 2026
    re.compile(
        r"\b(" + _MONTHS + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(19\d{2}|20\d{2})\b",
        re.IGNORECASE,
    ),
    # 12/08/2026, 12-08-2026, 12.08.2026
    re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](19\d{2}|20\d{2})\b"),
    # 2026-08-12 (ISO)
    re.compile(r"\b(19\d{2}|20\d{2})-(\d{1,2})-(\d{1,2})\b"),
]

_SEASON_RES = [
    re.compile(r"\b(kharif)\b", re.IGNORECASE),
    re.compile(r"\b(rabi)\b", re.IGNORECASE),
    re.compile(r"\b(zaid)\b", re.IGNORECASE),
    re.compile(r"(खरीफ)", re.UNICODE),
    re.compile(r"(रबी)", re.UNICODE),
    re.compile(r"(जायद)", re.UNICODE),
]

_SEASON_YEAR_RE = re.compile(
    r"\b(kharif|rabi|zaid|खरीफ|रबी|जायद)\s*(?:season\s*)?(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

_FY_RE = re.compile(
    r"\b(?:f\.?y\.?|financial year)?\s*(20\d{2})\s*[-–/]\s*(\d{2})\b",
    re.IGNORECASE,
)

# Conservative instrument identifiers. Each pattern must carry its own
# label word so a bare code-like token is never captured alone.
_INSTRUMENT_RES = [
    re.compile(
        r"\bRBI\s+(?:reference|circular|notification)\s*(?:no\.?|number)?\s*:?\s*"
        r"([A-Z]{2,}(?:\.[A-Z0-9]+)+\.[0-9/\-.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bDOR\.[A-Z.]*[0-9][A-Z0-9./\-]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:circular|notification|office memorandum|memorandum)\s+"
        r"(?:no\.?|number)\s*:?\s*([A-Za-z0-9][A-Za-z0-9/\-.]{2,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:GR|G\.R\.|government resolution)\s+"
        r"(?:no\.?|number)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9/\-.]{2,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bF\.?\s*No\.?\s*([A-Za-z0-9][A-Za-z0-9/\-.]{2,40})",
    ),
    # Gujarati instrument labels (lexicon-verified: ઠરાવ/સરકારી ઠરાવ,
    # ક્રમાંક). Digits may be Arabic (normalized) or Gujarati script.
    re.compile(
        r"(?:સરકારી\s+)?ઠરાવ\s+(?:નં\.?|ક્રમાંક)?\s*:?\s*"
        r"([A-Za-z0-9\u0A80-\u0AFF][A-Za-z0-9\u0A80-\u0AFF/\-.]{2,40})",
    ),
    re.compile(
        r"ક્રમાંક\s*:?\s*([0-9\u0A80-\u0AFF][0-9\u0A80-\u0AFF/\-.]{2,40})",
    ),
    # Hindi instrument labels (lexicon-verified: परिपत्र, क्रमांक;
    # अधिसूचना from the classifier intent vocabulary).
    re.compile(
        r"परिपत्र\s+(?:सं(?:ख्या)?\.?|No\.?)?\s*:?\s*"
        r"([A-Za-z0-9\u0900-\u097F][A-Za-z0-9\u0900-\u097F/\-.]{2,40})",
    ),
    re.compile(
        r"क्रमांक\s*:?\s*([0-9\u0900-\u097F][0-9\u0900-\u097F/\-.]{2,40})",
    ),
    re.compile(
        r"अधिसूचना\s+(?:सं(?:ख्या)?\.?|No\.?)?\s*:?\s*"
        r"([A-Za-z0-9\u0900-\u097F][A-Za-z0-9\u0900-\u097F/\-.]{2,40})",
    ),
]

_REVISION_CUES = [
    "corrigendum",
    "addendum",
    "revised",
    "revamped",
    "amendment",
    "amended",
    "updated version",
    "final version",
]

# Standalone version labels (v5, v6, Final): a different label on two
# otherwise identical documents forces version separation in clustering
# and counts as revision evidence here.
_VERSION_LABEL_RE = re.compile(r"\bv(\d+)\b", re.IGNORECASE)

# Explicit supersession language. Direction matters:
# - "X superseded by Y" / "X replaced by Y" / "X revoked/withdrawn" -> X is superseded.
# - "this supersedes X" / "replaces X" (self as successor) -> current.
_SUPERSEDED_SELF_RES = [
    re.compile(
        r"\b(?:superseded by|replaced by|revoked|withdrawn|"
        r"no longer (?:in force|valid|applicable|operative))\b",
        re.IGNORECASE,
    ),
]

_AMENDED_SELF_RES = [
    re.compile(r"\bamended by\b", re.IGNORECASE),
]

_SUCCESSOR_SELF_RES = [
    re.compile(
        r"\bthis\b.{0,40}?\b(?:supersedes|replaces|replacing)\b",
        re.IGNORECASE,
    ),
    # "version v6 ... replacing the v5 draft": two version labels joined
    # by a replace verb names this document the successor. Conservative:
    # both version tokens AND the verb are required in one sentence.
    re.compile(
        r"\bv\d+\b[^.]{0,80}?\breplac(?:e|ing)\b[^.]{0,80}?\bv\d+\b",
        re.IGNORECASE,
    ),
]


def _parse_date_fragment(fragment: str) -> str | None:
    """Parse the first recognizable full date in a text fragment.

    Returns an ISO "YYYY-MM-DD" string, else None. Year-only or
    month-year fragments are NOT full dates (returned as None here;
    callers record coarser granularity separately if needed).
    """
    text = fragment.strip()

    for rx in _DATE_RES:
        match = rx.search(text)
        if not match:
            continue
        groups = match.groups()
        try:
            if rx is _DATE_RES[0]:
                day, month_name, year = groups
                return date(int(year), _MONTH_NUM[month_name.lower()], int(day)).isoformat()
            if rx is _DATE_RES[1]:
                month_name, day, year = groups
                return date(int(year), _MONTH_NUM[month_name.lower()], int(day)).isoformat()
            if rx is _DATE_RES[2]:
                day, month, year = groups
                return date(int(year), int(month), int(day)).isoformat()
            if rx is _DATE_RES[3]:
                year, month, day = groups
                return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue

    return None


def _clean_identifier(raw: str) -> str | None:
    cleaned = raw.strip().strip(".,;:()[]\"'").strip()
    if len(cleaned) < 3 or len(cleaned) > 48:
        return None
    if not re.search(r"[A-Za-z0-9]", cleaned):
        return None
    # P1 audit fix: a bare "GR <word>" match (e.g. "GR land") is prose,
    # not an identifier. Real instrument IDs carry digits or separators.
    if not re.search(r"[0-9/\-]", cleaned):
        return None
    return cleaned


def find_instrument_mentions(text: str) -> list[str]:
    """Find explicitly labeled instrument identifiers in text.

    Reuses the conservative labeled patterns (circular/notification/GR
    numbers, RBI references, F. No.). Bare code-like tokens are never
    captured. Order-preserving, deduplicated.
    """
    found: list[str] = []
    seen: set[str] = set()
    blob = str(text or "")

    for rx in _INSTRUMENT_RES:
        for match in rx.finditer(blob):
            group = match.group(1) if match.lastindex else match.group(0)
            cleaned = _clean_identifier(group)
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                found.append(cleaned)

    return found


def extract_validity(
    text: str,
    url: str = "",
    provider_date: str | None = None,
) -> dict:
    """Extract a conservative validity record from a discovery result.

    Args:
        text: cleaned result text (title + body slice is sufficient).
        url: result URL (used only for the legacy year tiebreak input,
            NOT as a validity signal by itself).
        provider_date: provider-supplied publication date, if any.

    Returns a dict with keys: published_date, effective_from,
    effective_to, season, season_year, fy, instrument_id,
    revision_label, supersession_status, validity_source.

    P1-7: Gujarati/Devanagari digits are normalized to Arabic for
    EXTRACTION only — the stored evidence text is never rewritten.
    """
    from app.web_rag.identifiers import normalize_numerals

    blob = normalize_numerals(str(text or ""))
    record: dict = {
        "published_date": None,
        "effective_from": None,
        "effective_to": None,
        "season": None,
        "season_year": None,
        "fy": None,
        "instrument_id": None,
        "revision_label": None,
        "supersession_status": UNKNOWN_STATUS,
        "validity_source": "unknown",
    }

    stated = False

    if provider_date:
        parsed = _parse_date_fragment(str(provider_date))
        if parsed:
            record["published_date"] = parsed
            record["validity_source"] = "provider"

    for rx in _EFFECTIVE_FROM_RES:
        match = rx.search(blob)
        if match:
            parsed = _parse_date_fragment(match.group(1))
            if parsed:
                record["effective_from"] = parsed
                stated = True
                break

    for rx in _EFFECTIVE_TO_RES:
        match = rx.search(blob)
        if match:
            parsed = _parse_date_fragment(match.group(1))
            if parsed:
                record["effective_to"] = parsed
                stated = True
                break

    season_match = _SEASON_YEAR_RE.search(blob)
    if season_match:
        word, year = season_match.group(1), season_match.group(2)
        record["season"] = _canonical_season(word)
        record["season_year"] = year
        stated = True
    else:
        for rx in _SEASON_RES:
            match = rx.search(blob)
            if match:
                record["season"] = _canonical_season(match.group(1))
                stated = True
                break

    fy_match = _FY_RE.search(blob)
    if fy_match:
        century, suffix = fy_match.group(1), fy_match.group(2)
        record["fy"] = f"{century}-{suffix}"
        stated = True

    for rx in _INSTRUMENT_RES:
        match = rx.search(blob)
        if match:
            group = match.group(1) if match.lastindex else match.group(0)
            cleaned = _clean_identifier(group)
            if cleaned:
                record["instrument_id"] = cleaned
                stated = True
                break

    blob_lower = blob.lower()
    for cue in _REVISION_CUES:
        if cue in blob_lower:
            record["revision_label"] = cue
            stated = True
            break

    if record["revision_label"] is None:
        version_match = _VERSION_LABEL_RE.search(blob)
        if version_match:
            record["revision_label"] = f"v{version_match.group(1)}"
            stated = True

    if any(rx.search(blob) for rx in _SUPERSEDED_SELF_RES):
        record["supersession_status"] = SUPERSEDED
        stated = True
    elif any(rx.search(blob) for rx in _AMENDED_SELF_RES):
        record["supersession_status"] = AMENDED
        stated = True
    elif any(rx.search(blob) for rx in _SUCCESSOR_SELF_RES):
        record["supersession_status"] = CURRENT
        stated = True

    if stated and record["validity_source"] == "unknown":
        record["validity_source"] = "stated"

    return record


def _canonical_season(word: str) -> str:
    lowered = word.lower()
    if lowered in ("kharif", "खरीफ"):
        return "kharif"
    if lowered in ("rabi", "रबी"):
        return "rabi"
    if lowered in ("zaid", "जायद"):
        return "zaid"
    return lowered


def _as_comparable(value: str | None) -> str | None:
    """Normalize an ISO-ish date string for lexicographic comparison.

    Accepts "YYYY-MM-DD", "YYYY-MM", "YYYY". Returns None when the
    value does not look like a date.
    """
    if not value or not isinstance(value, str):
        return None
    if re.fullmatch(r"(19\d{2}|20\d{2}|2100)-\d{2}-\d{2}", value):
        return value
    if re.fullmatch(r"(19\d{2}|20\d{2}|2100)-\d{2}", value):
        return value + "-00"
    if re.fullmatch(r"(19\d{2}|20\d{2}|2100)", value):
        return value + "-00-00"
    return None


def resolve_case_date(
    as_of_date: str | None,
    case_year: int | None = None,
    season: str | None = None,
) -> dict:
    """Resolve the user's case date for validity comparison.

    Priority: explicit as_of_date > classifier case_year/season >
    no case date (empty dict — validity then ranks without a case anchor).
    Never invents "today": without an explicit anchor, unknown-validity
    results are NOT penalized for age.
    """
    if as_of_date:
        comparable = _as_comparable(str(as_of_date).strip()[:10])
        if comparable:
            return {"case_date": comparable, "case_season": season}

    if case_year:
        return {
            "case_date": f"{int(case_year):04d}-00-00",
            "case_season": season,
        }

    if season:
        return {"case_date": None, "case_season": season}

    return {}


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|2100)\b")


def query_years(query: str) -> set[str]:
    """Explicit 4-digit years mentioned in the query (affinity signal)."""
    return set(_YEAR_RE.findall(str(query or "")))


def _document_years(validity: dict) -> set[str]:
    """Years the validity record itself states (never inferred)."""
    years: set[str] = set()
    for key in ("published_date", "effective_from", "effective_to"):
        value = validity.get(key)
        if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
            years.add(value[:4])
    season_year = validity.get("season_year")
    if isinstance(season_year, str) and season_year.isdigit():
        years.add(season_year)
    return years


def validity_preference(
    validity: dict | None,
    case: dict | None,
) -> float:
    """Score a validity record against the resolved case date.

    Precedence: explicitly valid-for-case-date > unknown (0.0) >
    expired / explicitly superseded / future-effective (strong
    penalties). Penalties are scaled to exceed BM25 min-max noise
    (which can contribute a full 1.0 of composite score), so a stated
    supersession always demotes below comparable valid peers.

    Query-year affinity: when the query explicitly mentions the
    document's own year ("What did IOS 2021 say?"), penalties are
    dampened — the user is asking about the old instrument itself.
    Recency remains a tiebreaker only, handled by the legacy fallback
    in freshness_bonus when validity is unknown.
    """
    if not validity:
        return 0.0

    status = (validity.get("supersession_status") or UNKNOWN_STATUS).lower()
    case = case or {}
    case_date = case.get("case_date")
    case_season = (case.get("case_season") or "").lower() or None

    affinity = bool(
        set(case.get("query_years", set())) & _document_years(validity)
    )
    dampen = 0.3 if affinity else 1.0

    if status == SUPERSEDED:
        return -1.20 * dampen
    if status == AMENDED:
        base = 0.05
    elif status == CURRENT:
        base = 0.10
    else:
        base = 0.0

    effective_from = _as_comparable(validity.get("effective_from"))
    effective_to = _as_comparable(validity.get("effective_to"))

    # P2 audit fix: year-granularity case anchors ("Kharif 2024" ->
    # "2024-00-00") compare at year granularity, so a same-year
    # instrument is never misread as future-effective/expired.
    case_coarse = (
        case_date[:4] if case_date and case_date[4:] == "-00-00" else None
    )

    if case_date:
        if effective_from:
            if case_coarse and len(effective_from) >= 4:
                if effective_from[:4] > case_coarse:
                    # Future-effective: must not be presented as the current rule.
                    return -1.20 * dampen
            elif effective_from > case_date:
                # Future-effective: must not be presented as the current rule.
                return -1.20 * dampen
        if effective_to:
            if case_coarse and len(effective_to) >= 4:
                if effective_to[:4] < case_coarse:
                    return -1.00 * dampen
            elif effective_to < case_date:
                return -1.00 * dampen
        if effective_from or effective_to:
            # Explicitly in force for the case date.
            base += 0.25

    result_season = (validity.get("season") or "").lower() or None
    if case_season and result_season:
        if result_season == case_season:
            season_year = validity.get("season_year")
            case_year = case_date[:4] if case_date else None
            if season_year and case_year and season_year != case_year:
                return base - 0.15
            base += 0.08
        # A different named season with no year anchor is weak evidence
        # of invalidity (could be general guidance), so no penalty.

    return base
