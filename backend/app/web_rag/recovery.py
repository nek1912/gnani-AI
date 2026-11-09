"""P1-4 bounded recovery: explicit evidence states, one axis per round.

The existing Stage-2 fallback becomes an explicit loop of at most
MAX_RECOVERY_ROUNDS (2) refinement rounds, each changing exactly one
retrieval axis. The evidence gate (and the relevance/trust gates) are
the sensors; their verdicts are never altered here.

Evidence states (conservative):
    TERMINAL             -> never retry (domain mismatch, empty pool,
                            exceptions, exhausted rounds, no-op axis).
    WRONG_JURISDICTION   -> widen jurisdiction (drop assumed state).
    OUTDATED             -> validity axis (revised/corrigendum/current).
    CONFLICTING          -> authority axis (instrument-first anchors).
    WEAK                 -> language axis (missing GU/HI branch) else
                            authority axis.
    PARTIAL              -> facet axis, uncovered high-value facets only.
    VALID_BUT_LOW_SCORE  -> authority axis, ONLY when authoritative
                            chunks are present but below threshold.
    SUFFICIENT           -> unused by the loop (pass-through marker).

No round lowers any threshold. DOMAIN_MISMATCH never retries. Rounds
never recurse (recovery discovers run the standard single lead round
at most).
"""

from __future__ import annotations

import logging
from dataclasses import replace

logger = logging.getLogger(__name__)

MAX_RECOVERY_ROUNDS = 2
MAX_RECOVERY_BRANCHES = 3

TERMINAL = "TERMINAL"
NO = "NO"
WEAK = "WEAK"
CONFLICTING = "CONFLICTING"
WRONG_JURISDICTION = "WRONG_JURISDICTION"
OUTDATED = "OUTDATED"
PARTIAL = "PARTIAL"
VALID_BUT_LOW_SCORE = "VALID_BUT_LOW_SCORE"
SUFFICIENT = "SUFFICIENT"

# Facets worth a targeted recovery round when uncovered but implied.
HIGH_VALUE_FACETS = {"deadline", "escalation", "procedure"}

# Recovery validity-axis terms (explicit revision/current language).
VALIDITY_AXIS_TERMS = [
    "revised", "corrigendum", "amendment", "latest", "current",
]

# Recovery authority-axis terms (instrument-first emphasis).
AUTHORITY_AXIS_TERMS = [
    "guidelines", "notification", "circular", "GR",
]


def _pool_stats(pool: list[dict]) -> dict:
    """Cheap validity/authority/jurisdiction summary of a result pool."""
    stats = {
        "has_official": False,
        "has_authoritative": False,
        "has_superseded_top": False,
        "has_future_top": False,
        "has_general_only": True,
        "tiers": set(),
        "states": set(),
        "jurisdictions": set(),
    }

    for result in pool[:10]:
        if not isinstance(result, dict):
            continue
        official = bool(result.get("official", False))
        tier = result.get("source_tier", 0)
        try:
            tier = int(tier)
        except (TypeError, ValueError):
            tier = 0

        try:
            fit = float(result.get("mandate_fit") or 0.0)
        except (TypeError, ValueError):
            fit = 0.0

        role = str(result.get("document_role") or "")
        stats["tiers"].add(tier)
        if result.get("state"):
            stats["states"].add(str(result.get("state")).lower())
        if result.get("jurisdiction"):
            stats["jurisdictions"].add(str(result.get("jurisdiction")).lower())

        if official:
            stats["has_official"] = True
        if tier >= 4 or fit >= 0.30 or (official and role == "instrument"):
            stats["has_authoritative"] = True
        if tier >= 3 or official:
            stats["has_general_only"] = False

        validity = result.get("validity")
        status = (
            validity.get("supersession_status")
            if isinstance(validity, dict)
            else None
        )
        if (status or "").lower() == "superseded":
            stats["has_superseded_top"] = True
        effective_from = validity.get("effective_from") if isinstance(validity, dict) else None
        if effective_from and len(str(effective_from)) >= 4:
            stats.setdefault("effective_dates", []).append(str(effective_from))

    return stats


def assess_evidence_state(
    discovered: list[dict],
    accepted: list[dict],
    relevance: dict | None,
    gate_reason: str | None,
    classification,
    coverage: dict | None,
) -> tuple[str, str]:
    """Classify a pipeline failure into (evidence_state, recovery_axis).

    Axis is one of: jurisdiction | validity | authority | language |
    facet:<name>,facet:<name> | none. Pure function — no I/O, no
    retries, fully unit-testable.
    """
    relevance = relevance or {}
    coverage = coverage or {}
    relevance_ok = bool(relevance.get("relevant", False))

    if gate_reason == "DOMAIN_MISMATCH":
        return TERMINAL, "none"

    state = getattr(classification, "state", None)
    expected = (state or "").lower() or None

    # Jurisdiction signal first: the most harmful failure mode.
    pool_states = set()
    for result in list(discovered or [])[:15]:
        if isinstance(result, dict) and result.get("state"):
            pool_states.add(str(result.get("state")).lower())
    if gate_reason == "JURISDICTION_MISMATCH" or (
        expected and pool_states and expected not in pool_states
    ):
        return WRONG_JURISDICTION, "jurisdiction"

    stats = _pool_stats(list(discovered or []))

    if stats["has_superseded_top"] or (
        not relevance_ok and stats.get("effective_dates")
    ):
        return OUTDATED, "validity"

    if not accepted and stats["tiers"] and min(stats["tiers"]) == 0 and max(stats["tiers"]) >= 4:
        return CONFLICTING, "authority"

    if accepted and gate_reason in ("BELOW_TOP1_THRESHOLD", "INSUFFICIENT_SUPPORTING_CHUNKS"):
        if stats["has_authoritative"]:
            return VALID_BUT_LOW_SCORE, "authority"
        return TERMINAL, "none"

    # PARTIAL is pool-based (not accepted-based): with web min_chunks=1
    # the gate rarely abstains while holding accepted chunks, so facet
    # gaps are read from discover-level coverage over the fused pool.
    if coverage:
        uncovered = [
            facet
            for facet, entry in coverage.items()
            if isinstance(entry, dict)
            and not entry.get("supported", True)
            and facet in HIGH_VALUE_FACETS
        ]
        if uncovered:
            return PARTIAL, "facet:" + ",".join(sorted(uncovered)[:2])

    if not relevance_ok or not accepted:
        branches_hint = "language"
        return WEAK, branches_hint

    return TERMINAL, "none"


def modify_for_axis(classification, axis: str, branches_run: list[str] | None = None):
    """Copy a classification for one recovery axis (None -> terminal).

    Only the jurisdiction axis mutates jurisdiction fields; every other
    axis returns an equal copy (branch hints travel in the recovery
    dict, not in the classification).
    """
    if classification is None:
        return None

    if axis == "jurisdiction":
        if getattr(classification, "jurisdiction", "central") == "central":
            return None
        try:
            return replace(
                classification,
                state=None,
                district=None,
                jurisdiction="central",
                jurisdiction_source="recovery",
                assumed_state=True,
            )
        except Exception:
            logger.warning("Recovery classification copy failed", exc_info=True)
            return None

    return classification


def recovery_hint(axis: str, branches_run: list[str] | None = None, coverage: dict | None = None) -> dict:
    """Branch-builder hint for a recovery axis (data only)."""
    branches_run = branches_run or []

    if axis == "language":
        missing = []
        if "gujarati" not in branches_run:
            missing.append("gujarati")
        if "hindi" not in branches_run:
            missing.append("hindi")
        return {"axis": "language", "languages": missing[:2]}

    if axis.startswith("facet:"):
        names = [name for name in axis.split(":", 1)[1].split(",") if name]
        return {"axis": "facet", "facets": names[:2]}

    return {"axis": axis}
