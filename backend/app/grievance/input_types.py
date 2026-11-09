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


import re
from datetime import datetime

_PHONE_FIELDS: frozenset[str] = frozenset(
    {"mobile_number", "phone_number", "contact_number", "mobile", "phone"}
)

_DATE_PATTERNS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
]


def get_input_type(field_name: str) -> str:
    """Return one of "int", "date", or "text" for a given field name."""
    name = field_name.lower()
    if "date" in name:
        return "date"
    if name in NUMERIC_FIELDS:
        return "int"
    return "text"


def validate_field_value(field_name: str, value: str) -> None:
    """Validate user-submitted field values, raising ValueError on invalid input."""
    val = value.strip()
    if not val:
        raise ValueError(f"Field '{field_name}' cannot be empty")

    name = field_name.lower()
    input_type = get_input_type(name)

    # 1. Numeric validation
    if input_type == "int":
        clean = val.replace(",", "")
        if not (clean.isdigit() or (clean.startswith("-") and clean[1:].isdigit())):
            raise ValueError(f"Field '{field_name}' must be a whole number")

    # 2. Date validation
    elif input_type == "date":
        parsed = None
        for fmt in _DATE_PATTERNS:
            try:
                parsed = datetime.strptime(val, fmt)
                break
            except ValueError:
                continue
        if not parsed:
            raise ValueError(
                f"Field '{field_name}' must be a valid date in YYYY-MM-DD or DD/MM/YYYY format"
            )
        if ("incident" in name or "applied" in name or "dob" in name or "birth" in name) and parsed > datetime.now():
            raise ValueError(f"Field '{field_name}' cannot be in the future")

    # 3. Phone validation
    if name in _PHONE_FIELDS or "mobile" in name or "phone" in name:
        digits = re.sub(r"[\s\-\(\)]", "", val)
        if digits.startswith("+91"):
            digits = digits[3:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        if not (len(digits) == 10 and digits.isdigit() and digits[0] in "6789"):
            raise ValueError(
                f"Field '{field_name}' must be a valid 10-digit Indian mobile number"
            )

    # 4. Length check
    if len(val) > 500:
        raise ValueError(f"Field '{field_name}' value exceeds maximum permitted length")
