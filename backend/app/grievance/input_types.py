"""Heuristic input-type classification for grievance draft fields.

Purely additive helper used by the structured Grievance UI to decide
which HTML input control a field should render with (int / date /
text). This module does not alter any existing extraction,
classification, or drafting logic — it only maps a field *name* to a
presentation input type.
"""

from __future__ import annotations

# Fields whose value is always a whole number (counts, years, amounts
# expressed as plain numbers, scores). Deliberately conservative: many
# "*_number" fields (e.g. ppo_number, khata_number, vehicle_number)
# are alphanumeric identifiers, not integers, so they are left as text.
NUMERIC_FIELDS: frozenset[str] = frozenset(
    {
        "ward_number",
        "family_members",
        "assessment_year",
        "year",
        "load_required",
        "cibil_score",
        "disputed_amount",
        "loan_amount",
        "amount_claimed",
        "sum_insured",
        "premium_paid",
        "compensation_claimed",
        "amount",
        "share_amount",
        "dividend_due",
        "amount_involved",
        "amount_paid",
        "previous_bill_amount",
        "entitled_quantity",
        "received_quantity",
        "award_amount",
    }
)


def get_input_type(field_name: str) -> str:
    """Return one of "int", "date", or "text" for a given field name."""
    name = field_name.lower()
    if "date" in name:
        return "date"
    if name in NUMERIC_FIELDS:
        return "int"
    return "text"
