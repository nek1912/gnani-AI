"""P2-1 constrained terminology expansion + P2-1/P2-2 scheme exceptions.

Expansion: bounded synonym tables (terminology_expansion.json) scoped by
classification domain/subject, with an optional per-rule `when.require_any`
query-text gate (rule fires only if the query mentions a trigger term;
absent gate = legacy domain/subject scoping). Terms append to DERIVED
English branch queries only — the user query is never rewritten, and
applied rules are recorded in discovery metadata (original + canonical
preserved).

Exceptions: explicit opt-out data (scheme_exceptions.json). Demotion-only,
instrument-preserving, single-state-scoped. PMFBY is never globally
treated as Gujarat insurance: outside Gujarat the exception is inert.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.web_rag.mandate_map import query_subjects

logger = logging.getLogger(__name__)

_EXPANSION_PATH = Path(__file__).with_name("terminology_expansion.json")
_EXCEPTIONS_PATH = Path(__file__).with_name("scheme_exceptions.json")


@lru_cache(maxsize=1)
def load_expansion() -> dict:
    try:
        with open(_EXPANSION_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        logger.warning("Terminology expansion unavailable")
        return {"rules": []}


@lru_cache(maxsize=1)
def load_exceptions() -> dict:
    try:
        with open(_EXCEPTIONS_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        logger.warning("Scheme exceptions unavailable")
        return {"exceptions": []}


def assumed_dampen_factor(subjects: set[str] | None, assumed: bool) -> float:
    """P2-2 assumed-state dampening factor (data-driven).

    Returns 0.5 when the state was merely assumed (not explicit) and the
    query subjects intersect the dampened set (national schemes with
    known opt-out behavior); 1.0 otherwise. Applied to geo and
    mandate-fit influence in ranking — branches are preserved, only
    their influence shrinks.
    """
    if not assumed or not subjects:
        return 1.0
    data = load_exceptions()
    dampened = set(data.get("assumed_dampen_subjects", []) or [])
    if not (dampened & set(subjects)):
        return 1.0
    try:
        return float(data.get("assumed_dampen_factor", 0.5))
    except (TypeError, ValueError):
        return 0.5


def _rule_matches(
    rule: dict,
    domain: str | None,
    subjects: set[str],
    query_lower: str = "",
) -> bool:
    when = rule.get("when", {}) if isinstance(rule, dict) else {}
    domains = when.get("domains") or []
    wanted = set(when.get("subjects") or [])
    if domains and (domain or "general") not in domains:
        return False
    if wanted and not (wanted & subjects):
        return False
    # Optional query-text gate: the rule fires only when the query itself
    # mentions at least one trigger term. Subjects are domain-derived
    # (e.g. every agriculture query carries crop_insurance/crop_relief),
    # so without this gate a registry/portal query gets unrelated relief
    # synonyms appended. Absent require_any preserves legacy behavior.
    require_any = when.get("require_any") or []
    if require_any:
        lowered = query_lower or ""
        if not any(
            isinstance(t, str) and t and t.lower() in lowered
            for t in require_any
        ):
            return False
    return True


def expansion_terms(query: str, classification) -> tuple[list[str], dict]:
    """Bounded expansion terms for English branch queries.

    Returns (terms, applied) where applied maps rule_id -> appended terms.
    Terms already present in the query are skipped. At most
    max_rules_per_query rules fire, max_terms_per_rule terms each.
    """
    data = load_expansion()
    rules = data.get("rules", []) if isinstance(data, dict) else []
    max_rules = int(data.get("max_rules_per_query", 2) or 2)
    max_terms = int(data.get("max_terms_per_rule", 6) or 6)

    domain = getattr(classification, "domain", None)
    subjects = query_subjects(
        domain, getattr(classification, "society_type", None)
    )
    lowered = str(query or "").lower()

    terms: list[str] = []
    applied: dict[str, list[str]] = {}

    for rule in rules:
        if len(applied) >= max_rules:
            break
        if not _rule_matches(rule, domain, subjects, lowered):
            continue
        append = rule.get("append", {}) if isinstance(rule, dict) else {}
        candidates: list[str] = []
        for lang_terms in append.values():
            for term in lang_terms or []:
                if term and term.lower() not in lowered and term not in terms:
                    candidates.append(term)
                if len(candidates) >= max_terms:
                    break
            if len(candidates) >= max_terms:
                break
        if candidates:
            applied[str(rule.get("id", "rule"))] = candidates
            terms.extend(candidates)

    return terms, applied


def home_evidence_present(results: list[dict], state: str | None) -> bool:
    """True when the pool holds official instrument evidence for the state.

    Used as the conditional gate for opt-out demotion: the national
    ladder is demoted only when home-state primary evidence exists.
    Publisher jurisdiction comes from the mandate map (rescore runs
    before annotation stamping), never from query-derived fields.
    """
    state_l = (state or "").lower()
    if not state_l:
        return False
    try:
        from app.web_rag.mandate_map import document_role, find_org
    except Exception:
        return False
    for result in results or []:
        if not isinstance(result, dict):
            continue
        if not result.get("official", False):
            continue
        url = result.get("source_url") or result.get("url") or ""
        title = result.get("web_title") or result.get("title") or ""
        try:
            role = document_role(
                url, title, True, bool(result.get("trusted_secondary", False))
            )
            org = find_org(url)
        except Exception:
            continue
        if role != "instrument":
            continue
        if org is not None and str(org.get("jurisdiction", "")).lower() == state_l:
            return True
    return False


def exception_demotion(
    url: str,
    role: str,
    subjects: set[str] | None,
    state: str | None,
    home_evidence_present: bool = False,
) -> float:
    """Scheme opt-out demotion (data-driven, demotion-only).

    Returns the penalty when a result matches an exception:
    opt-out state + subject overlap + demote-domain + demotable role.
    Instruments are never demoted; other jurisdictions never affected.
    When the exception requires home evidence, the penalty applies only
    if Gujarat relief/instrument evidence is present in the pool —
    conditional preference, never blind suppression.
    """
    data = load_exceptions()
    exceptions = data.get("exceptions", []) if isinstance(data, dict) else []
    subjects = subjects or set()
    state_l = (state or "").lower()

    try:
        from urllib.parse import urlparse

        domain = urlparse(str(url or "")).netloc.lower()
        domain = domain.split("@")[-1].split(":")[0].removeprefix("www.").rstrip(".")
    except Exception:
        return 0.0

    for exc in exceptions:
        if not isinstance(exc, dict):
            continue
        if state_l != str(exc.get("opt_out_state", "")).lower() or not state_l:
            continue
        if exc.get("subject") not in subjects:
            continue
        if exc.get("requires_home_evidence") and not home_evidence_present:
            continue
        demote = [str(d).lower() for d in (exc.get("demote_domains") or [])]
        if not any(domain == d or domain.endswith("." + d) for d in demote):
            continue
        roles = exc.get("demote_roles") or []
        if roles and str(role or "") not in roles:
            continue
        try:
            return float(exc.get("penalty", 0.0))
        except (TypeError, ValueError):
            return 0.0

    return 0.0
