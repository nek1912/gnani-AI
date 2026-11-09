"""P1-2 version / mirror clustering metadata.

Same-document mirrors, duplicate publications, and revised versions are
grouped WITHOUT deleting anything: every result keeps full provenance
and gains ``cluster_id`` + ``canonical_in_cluster`` annotations.

Merge requires conservative multi-signal agreement — titles alone never
merge. Distinct versions are preserved: differing revision labels,
effective dates, season years, or conflicting supersession status always
split clusters, even when URLs and titles agree.

Canonical pick (advisory only, ranking untouched): official first, then
instrument role, then mandate fit, then latest effective date.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import parse_qsl, urlparse, urlunparse

logger = logging.getLogger(__name__)

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "fbclid", "gclid", "igshid", "mc_cid", "mc_eid",
}

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def normalize_url(url: str) -> str:
    """Canonical URL form for same-document comparison.

    Lowercases scheme/host, drops www, trailing slashes, fragments,
    and tracking query params. Tracking params are the ONLY query
    params dropped — functional params (?id=, ?PRID=) are preserved
    because they address distinct documents.
    """
    try:
        parts = urlparse(str(url or "").strip())
    except Exception:
        return str(url or "").strip().lower()

    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    host = host.removeprefix("www.").rstrip(".")

    try:
        query_pairs = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        query_pairs.sort()
        query = "&".join(f"{k}={v}" for k, v in query_pairs)
    except Exception:
        query = parts.query

    path = parts.path.rstrip("/") or "/"

    try:
        return urlunparse(("https", host, path, "", query, "")).lower()
    except Exception:
        return str(url or "").strip().lower()


def normalize_title(title: str) -> str:
    """Canonical title form: lowercase, punctuation/whitespace collapsed.

    Unicode-aware: Indic scripts survive (only separators collapse).
    """
    text = str(title or "").lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def _validity_of(result: dict) -> dict:
    validity = result.get("validity")
    return validity if isinstance(validity, dict) else {}


def _version_splits(a: dict, b: dict) -> bool:
    """True when revision evidence forces distinct versions apart."""
    va, vb = _validity_of(a), _validity_of(b)

    ra = (va.get("revision_label") or "").lower() or None
    rb = (vb.get("revision_label") or "").lower() or None
    if ra and rb and ra != rb:
        return True

    ea = va.get("effective_from") or None
    eb = vb.get("effective_from") or None
    if ea and eb and ea != eb:
        return True

    sa = va.get("season_year") or None
    sb = vb.get("season_year") or None
    if sa and sb and sa != sb:
        return True

    sta = (va.get("supersession_status") or "unknown").lower()
    stb = (vb.get("supersession_status") or "unknown").lower()
    if sta != stb and "unknown" not in (sta, stb):
        return True

    ia = (va.get("instrument_id") or "").lower() or None
    ib = (vb.get("instrument_id") or "").lower() or None
    if ia and ib and ia != ib:
        return True

    return False


def _same_document(a: dict, b: dict) -> bool:
    """Conservative same-version predicate (all conditions required)."""
    url_a = normalize_url(a.get("source_url") or a.get("url") or "")
    url_b = normalize_url(b.get("source_url") or b.get("url") or "")

    if url_a and url_a == url_b:
        same = True
    else:
        title_a = normalize_title(a.get("web_title") or a.get("title") or "")
        title_b = normalize_title(b.get("web_title") or b.get("title") or "")

        if not title_a or title_a != title_b:
            return False

        va, vb = _validity_of(a), _validity_of(b)
        ia = (va.get("instrument_id") or "").lower() or None
        ib = (vb.get("instrument_id") or "").lower() or None

        if ia and ib:
            same = ia == ib
        else:
            text_a = re.sub(r"\s+", " ", str(a.get("text") or a.get("content") or "").lower()).strip()[:300]
            text_b = re.sub(r"\s+", " ", str(b.get("text") or b.get("content") or "").lower()).strip()[:300]
            same = bool(text_a) and text_a == text_b

    if not same:
        return False

    return not _version_splits(a, b)


def _canonical_key(members: list[dict]) -> str:
    seeds: list[str] = []
    for member in members:
        url = normalize_url(member.get("source_url") or member.get("url") or "")
        if url:
            seeds.append(url)
        validity = _validity_of(member)
        instrument = (validity.get("instrument_id") or "").lower()
        if instrument:
            seeds.append(f"id:{instrument}")
        chunk_id = member.get("chunk_id")
        if chunk_id:
            seeds.append(f"chunk:{chunk_id}")
    seeds = sorted(set(seeds)) or ["singleton"]
    digest = hashlib.sha1("|".join(seeds).encode("utf-8")).hexdigest()[:12]
    return f"mirror_{digest}"


def _canonical_rank(result: dict) -> tuple:
    """Higher sorts first: official, instrument role, fit, latest date."""
    official = 1 if result.get("official", False) else 0
    role = result.get("document_role") or ""
    role_rank = 2 if role == "instrument" else 1 if role == "implementation" else 0
    try:
        fit = float(result.get("mandate_fit") or 0.0)
    except (TypeError, ValueError):
        fit = 0.0
    validity = _validity_of(result)
    effective = validity.get("effective_from") or ""
    return (official, role_rank, fit, str(effective))


def cluster_results(results: list[dict]) -> dict:
    """Group likely mirrors/versions; annotate in place (additive only).

    Returns {"clusters": {cluster_id: [chunk_ids]}, "mirrored_chunks": int}.
    Every result gains ``cluster_id`` (singletons get their own) and
    ``canonical_in_cluster``. Nothing is removed or reordered.
    """
    items = [r for r in (results or []) if isinstance(r, dict)]

    groups: list[list[dict]] = []
    for item in items:
        placed = False
        for group in groups:
            if _same_document(item, group[0]):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    clusters: dict[str, list[str]] = {}
    mirrored = 0

    for group in groups:
        cluster_id = _canonical_key(group)
        ordered = sorted(
            group,
            key=lambda r: (
                _canonical_rank(r),
                str(r.get("chunk_id") or ""),
            ),
            reverse=True,
        )
        canonical_id = ordered[0].get("chunk_id") if ordered else None

        chunk_ids: list[str] = []
        for member in group:
            member["cluster_id"] = cluster_id
            member["canonical_in_cluster"] = member.get("chunk_id") == canonical_id
            if member.get("chunk_id"):
                chunk_ids.append(member["chunk_id"])

        clusters[cluster_id] = chunk_ids
        if len(group) > 1:
            mirrored += len(group)

    return {"clusters": clusters, "mirrored_chunks": mirrored}
