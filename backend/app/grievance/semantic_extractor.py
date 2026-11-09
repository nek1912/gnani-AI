
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

import httpx


logger = logging.getLogger(__name__)


@dataclass
class SemanticExtractionResult:
    """Structured result of interpreting one user reply."""

    extracted_fields: dict[str, str] = field(default_factory=dict)

    invalid: bool = False

    unrelated: bool = False

    needs_clarification: bool = False


_NUMERIC_HINT_TOKENS = (
    "number",
    "amount",
    "pincode",
    "aadhaar",
    "phone",
    "id",
    "cibil_score",
    "load_required",
    "sum_insured",
    "premium_paid",
)


def _is_numeric_expecting_field(field_name: str) -> bool:
    fl = field_name.lower()
    return any(tok in fl for tok in _NUMERIC_HINT_TOKENS)


_NEGATIVE_PATTERNS = re.compile(
    r"\b(i\s+)?(don'?t|do not)\s+know\b|"
    r"\bnot\s+sure\b|"
    r"\bno\s+idea\b|"
    r"\bunknown\b|"
    r"\bnot\s+applicable\b|"
    r"\bn/?a\b|"
    r"\bcan'?t\s+recall\b|"
    r"\bdo not\s+remember\b|"
    r"\bdon'?t\s+remember\b",
    re.IGNORECASE,
)


_INFORMATIONAL_STARTERS = (
    "what is",
    "what are",
    "how does",
    "how do",
    "how to",
    "explain",
    "tell me about",
    "define",
    "meaning of",
    "who is",
    "why",
)


_CONFIRMATION_WORDS = {
    "yes",
    "yeah",
    "yep",
    "correct",
    "right",
    "ok",
    "okay",
    "confirm",
    "confirmed",
    "proceed",
    "continue",
    "sure",
    "no",
    "nope",
    "wrong",
    "incorrect",
}


def _looks_unrelated(text: str) -> bool:
    stripped = text.strip().rstrip(".!").lower()

    if not stripped:
        return True

    words = stripped.replace(",", " ").split()

    if words and all(w in _CONFIRMATION_WORDS for w in words):
        return True

    if text.strip().endswith("?") and any(
        stripped.startswith(s) for s in _INFORMATIONAL_STARTERS
    ):
        return True

    return False


_WARD_NUMBER_RE = re.compile(
    r"\bward\s*(?:no\.?|number)?\s*[:#\-]?\s*(\d+)\b",
    re.IGNORECASE,
)

_LANDMARK_CUE_RE = re.compile(
    r"\blandmark\s+(?:is|:|-)\s*(.+)",
    re.IGNORECASE,
)

_NEAR_CUE_RE = re.compile(
    r"\b(?:near|nearby|close to)\s+(.+)",
    re.IGNORECASE,
)

_LOCALITY_CUE_RE = re.compile(
    r"\blocality\s*(?:is\s*[:\-]?\s*|:\s*|-\s*)?(.+?)(?:\s+(?:city|town|state|district|zone|ward|pincode|landmark)\b|\s*$)",
    re.IGNORECASE,
)

_CITY_CUE_RE = re.compile(
    r"(?<!\w)(?:city|town)\s*(?:(?:is\s*[:\-]?\s*|:\s*|-\s*))?([A-Za-z][A-Za-z\s,]*?)(?:\s+(?:state|district|zone|ward|pincode|locality|landmark)\b|\s*$)",
    re.IGNORECASE,
)

_CITY_SUFFIX_RE = re.compile(
    r"^(?!.*(?:locality|ward|landmark|state|district|zone|pincode))(.+?)\s+(?:city|town)$",
    re.IGNORECASE,
)


def _generic_cue_re(field_name: str) -> re.Pattern:
    alias = field_name.replace("_", " ")
    return re.compile(
        rf"\b{re.escape(alias)}\s+(?:is\s*[:\-]?\s*|:\s*|-\s*)(.+)",
        re.IGNORECASE,
    )


_CITY_TAIL_RE = re.compile(
    r"([A-Za-z][A-Za-z.\s]*?)\s+(?:city|town)\b\s*[.!]?\s*$",
    re.IGNORECASE,
)

_CITY_TAIL_EXCLUDED_WORDS = {
    "locality",
    "ward",
    "landmark",
    "state",
    "district",
    "zone",
    "pincode",
}


def _backfill_city_from_locality(message: str, extracted: dict[str, str]) -> None:
    """Deterministically recover ``city`` from an explicit "<name> City/Town"
    suffix in the raw message whenever ``locality`` was extracted but
    ``city`` was not.

    This runs once per ``extract()`` call, regardless of which engine
    (Gemini or the heuristic fallback) produced ``extracted`` -- Gemini can
    correctly resolve ``locality`` from a sentence like "Locality is: Near
    J.B. Modi Garden, Bharuch City." while treating "Bharuch City" as part
    of the place name rather than emitting a separate ``city`` field. When
    that happens, ``current_field == "locality"`` is already satisfied, so
    the Gemini result is accepted and the heuristic fallback (which knows
    how to split "<name> City" into locality + city) never runs.

    Only fills ``city`` when one is explicitly found via a trailing
    "<name> City"/"<name> Town" cue in the raw message; never invents a
    value and never overwrites a city the extractor already found. Works
    directly off the raw message rather than the (possibly differently
    worded) ``locality`` value the engine returned, so it can't silently
    drift from what the message actually says. No-op for non-English text,
    since the cue is the English words "city"/"town".
    """

    if "locality" not in extracted or "city" in extracted:
        return

    for clause in _split_clauses(message) or [message]:
        tail_match = _CITY_TAIL_RE.search(clause)

        if not tail_match:
            continue

        name_part = tail_match.group(1).strip(" ,")

        if not name_part:
            continue

        # "Near J.B. Modi Garden, Bharuch City" -> the city is the last
        # comma-separated segment immediately before "City"/"Town".
        segments = [s.strip() for s in name_part.split(",") if s.strip()]
        candidate = segments[-1] if segments else name_part

        if candidate and candidate.lower() not in _CITY_TAIL_EXCLUDED_WORDS:
            extracted["city"] = _clean_value(candidate)

        return


def _split_clauses(text: str) -> list[str]:
    """Split on conjunctions/sentence boundaries, but NOT bare commas.

    Commas are frequently part of a legitimate locality/value such as:
    'Manjalpur, Vadodara'.

    Period splits require ≥2 lowercase letters before the period
    to avoid breaking abbreviations like 'J.B.', 'Dr.', 'Mr.'.
    """
    parts = re.split(
        r"\s+and\s+|;\s+|(?<=[a-z]{2})[.!?]\s+(?=[A-Z])",
        text.strip(),
    )

    return [
        p.strip(" .")
        for p in parts
        if p.strip(" .")
    ]


def _clean_value(value: str) -> str:
    return value.strip(" .,")


_GEMINI_FIELD_PROPERTIES = {
    "ward_number": {
        "type": "string",
        "description": "Ward number as digits only, e.g. '12'.",
    },
    "locality": {
        "type": "string",
        "description": "Locality or area name.",
    },
    "city": {
        "type": "string",
        "description": "City or town name, if explicitly provided.",
    },
    "zone": {
        "type": "string",
        "description": "Municipal zone, if explicitly provided.",
    },
    "landmark": {
        "type": "string",
        "description": "Nearby landmark, if explicitly provided.",
    },
    "person_name": {
        "type": "string",
        "description": "Person's name, only if explicitly provided.",
    },
    "description": {
        "type": "string",
        "description": "Complaint description, only when explicitly requested/appropriate.",
    },
    "address": {
        "type": "string",
        "description": "Address, if explicitly provided.",
    },
    "village": {
        "type": "string",
        "description": "Village name, if explicitly provided.",
    },
    "district": {
        "type": "string",
        "description": "District name, if explicitly provided.",
    },
    "state": {
        "type": "string",
        "description": "State name, if explicitly provided.",
    },
    "pincode": {
        "type": "string",
        "description": "PIN/pincode, if explicitly provided.",
    },
    "phone": {
        "type": "string",
        "description": "Phone number, if explicitly provided.",
    },
}


class GrievanceSemanticExtractor:
    """Semantic extraction/validation layer for the Grievance workflow.

    This class interprets one user reply.

    It NEVER owns workflow transitions and NEVER directly mutates
    grievance state.
    """

    def __init__(self, use_gemini: bool | None = None):
        from app.config import get_settings
        settings = get_settings()
        self.model = os.getenv(
            "GRIEVANCE_GEMINI_MODEL",
            settings.grievance_gemini_model,
        )

        api_key = os.getenv("GEMINI_API_KEY")

        self._gemini_enabled = (
            bool(api_key)
            if use_gemini is None
            else bool(use_gemini)
        )

        self._api_key = api_key
        self._client = None

        if self._gemini_enabled and api_key:
            try:
                logger.info(
                    "Grievance semantic extraction: Gemini enabled "
                    "(model=%s)",
                    self.model,
                )
            except Exception:
                logger.exception(
                    "Failed to initialize Gemini for grievance "
                    "semantic extraction; using heuristic fallback."
                )
                self._gemini_enabled = False
        else:
            logger.info(
                "Grievance semantic extraction: Gemini disabled; "
                "using deterministic heuristic fallback."
            )

        self._cache: dict[
            tuple[str | None, str],
            SemanticExtractionResult,
        ] = {}

    def extract(
        self,
        *,
        current_field: str | None,
        user_message: str,
        known_fields: set[str],
        required_fields: list[str],
        optional_fields: list[str],
        missing_fields: list[str],
        original_complaint: str,
        category: str,
        sub_category: str,
        department: str,
    ) -> SemanticExtractionResult:
        """Interpret user_message using the existing grievance context.

        Does NOT mutate grievance state.
        """

        message = (user_message or "").strip()

        if not message:
            return SemanticExtractionResult(unrelated=True)

        cache_key = (current_field, message)

        if cache_key in self._cache:
            return self._cache[cache_key]

        if _looks_unrelated(message):
            result = SemanticExtractionResult(unrelated=True)
            self._cache[cache_key] = result
            return result

        result: SemanticExtractionResult | None = None

        if self._gemini_enabled and self._api_key:
            try:
                result = self._extract_via_gemini(
                    current_field=current_field,
                    user_message=message,
                    known_fields=known_fields,
                    required_fields=required_fields,
                    optional_fields=optional_fields,
                    missing_fields=missing_fields,
                    original_complaint=original_complaint,
                    category=category,
                    sub_category=sub_category,
                    department=department,
                )

                # Defensive: pincode must be numeric even from Gemini.
                if result is not None and "pincode" in result.extracted_fields:
                    if not any(
                        ch.isdigit()
                        for ch in result.extracted_fields["pincode"]
                    ):
                        del result.extracted_fields["pincode"]

                if (
                    result is not None
                    and (
                        result.invalid
                        or (
                            not result.unrelated
                            and not result.extracted_fields
                        )
                        or (
                            current_field
                            and current_field not in result.extracted_fields
                        )
                        or (
                            current_field
                            and result.unrelated
                        )
                    )
                ):
                    logger.warning(
                        "Gemini returned no/incorrect fields for "
                        "current_field=%r (got %s, invalid=%s, "
                        "unrelated=%s); falling back to heuristic.",
                        current_field,
                        sorted(result.extracted_fields)
                        if result.extracted_fields
                        else [],
                        result.invalid,
                        result.unrelated,
                    )
                    result = None

            except Exception:
                logger.exception(
                    "Gemini grievance extraction failed for "
                    "current_field=%r; falling back to heuristic.",
                    current_field,
                )
                result = None

        if result is None:
            result = self._extract_heuristic(
                current_field=current_field,
                user_message=message,
            )

        # Deterministic backfill: run regardless of which engine produced
        # `result` -- Gemini's success (locality resolved, current_field
        # satisfied) must not suppress the same city recovery the heuristic
        # fallback already knows how to do. See docstring for details.
        if result is not None and not result.unrelated and not result.invalid:
            _backfill_city_from_locality(message, result.extracted_fields)

        logger.debug(
            "Grievance semantic extraction result: "
            "current_field=%r extracted_fields=%r invalid=%s "
            "unrelated=%s needs_clarification=%s",
            current_field,
            result.extracted_fields,
            result.invalid,
            result.unrelated,
            result.needs_clarification,
        )

        self._cache[cache_key] = result
        return result

    def _extract_via_gemini(
        self,
        *,
        current_field: str | None,
        user_message: str,
        known_fields: set[str],
        required_fields: list[str],
        optional_fields: list[str],
        missing_fields: list[str],
        original_complaint: str,
        category: str,
        sub_category: str,
        department: str,
    ) -> SemanticExtractionResult:

        system_prompt = (
            "You are the semantic field-extraction layer of "
            "eGovAssist's Grievance workflow.\n\n"
            "You do NOT control the workflow.\n"
            "You do NOT decide whether a grievance is complete.\n"
            "You do NOT submit a grievance.\n"
            "You only interpret the citizen's latest message and "
            "return structured information that is actually present.\n\n"
            "IMPORTANT:\n"
            "The latest user message is NOT automatically the value "
            "of the currently requested field.\n\n"
            "Analyze the message semantically.\n"
            "Extract only information that is actually present.\n\n"
            "Rules:\n"
            "1. If the user directly provides the requested field, "
            "extract only its value.\n"
            "2. If the user provides additional known information "
            "in the same message, extract those values under their "
            "own field names as well.\n"
            "3. Never copy an entire narrative sentence into a field "
            "when only part of the sentence represents the value.\n"
            "4. Never invent values.\n"
            "5. If the user says they do not know, are unsure, "
            "cannot remember, or otherwise cannot provide a value, "
            "do NOT extract a value for that field.\n"
            "6. If the answer is clearly nonsensical for the requested "
            "field, set invalid=true and do not extract that value.\n"
            "7. If the message is unrelated to the current field, "
            "set unrelated=true.\n"
            "8. Never extract a person's name unless a person's name "
            "is explicitly present.\n"
            "9. Preserve the original complaint. Never rewrite or "
            "replace it with the latest field response.\n"
            "10. Return only structured field values using the allowed "
            "field names.\n"
        )

        user_prompt = json.dumps(
            {
                "original_complaint": original_complaint,
                "category": category,
                "sub_category": sub_category,
                "department": department,
                "required_fields": required_fields,
                "optional_fields": optional_fields,
                "already_collected_fields": sorted(known_fields),
                "missing_fields": missing_fields,
                "current_requested_field": current_field,
                "latest_user_message": user_message,
            },
            ensure_ascii=False,
            indent=2,
        )

        logger.debug(
            "Calling Gemini grievance semantic extraction: "
            "current_field=%r message=%r",
            current_field,
            user_message,
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self._api_key}"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "extracted_fields": {
                            "type": "OBJECT",
                            "properties": _GEMINI_FIELD_PROPERTIES,
                        },
                        "invalid": {
                            "type": "BOOLEAN",
                        },
                        "unrelated": {
                            "type": "BOOLEAN",
                        },
                        "needs_clarification": {
                            "type": "BOOLEAN",
                        },
                    },
                    "required": [
                        "extracted_fields",
                        "invalid",
                        "unrelated",
                    ],
                },
            },
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        data = response.json()
        content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")

        if not content:
            raise RuntimeError(
                "Gemini returned an empty extraction response."
            )

        parsed = json.loads(content)

        raw_extracted = parsed.get("extracted_fields") or {}

        if not isinstance(raw_extracted, dict):
            raise RuntimeError(
                "Gemini returned an invalid extracted_fields object."
            )

        extracted: dict[str, str] = {}

        for key, value in raw_extracted.items():
            if value is None:
                continue

            value_text = str(value).strip()

            if not value_text:
                continue

            extracted[str(key)] = value_text

        # Defensive: pincode must be numeric; reject non-numeric values
        # that Gemini may have incorrectly assigned (e.g. "Bharuch city").
        if "pincode" in extracted and not any(
            ch.isdigit() for ch in extracted["pincode"]
        ):
            del extracted["pincode"]

        logger.debug(
            "Gemini grievance extraction parsed: "
            "current_field=%r extracted_fields=%r invalid=%r "
            "unrelated=%r needs_clarification=%r",
            current_field,
            extracted,
            parsed.get("invalid", False),
            parsed.get("unrelated", False),
            parsed.get("needs_clarification", False),
        )

        return SemanticExtractionResult(
            extracted_fields=extracted,
            invalid=bool(parsed.get("invalid", False)),
            unrelated=bool(parsed.get("unrelated", False)),
            needs_clarification=bool(
                parsed.get("needs_clarification", False)
            ),
        )

    def _extract_heuristic(
        self,
        *,
        current_field: str | None,
        user_message: str,
    ) -> SemanticExtractionResult:

        message = user_message.strip()

        if _NEGATIVE_PATTERNS.search(message):
            return SemanticExtractionResult()

        extracted: dict[str, str] = {}

        clauses = _split_clauses(message)

        if not clauses:
            clauses = [message]

        for clause in clauses:

            if "ward_number" not in extracted:
                ward_match = _WARD_NUMBER_RE.search(clause)

                if ward_match:
                    extracted["ward_number"] = ward_match.group(1)

            if "landmark" not in extracted:

                landmark_match = _LANDMARK_CUE_RE.search(clause)

                if landmark_match:
                    extracted["landmark"] = _clean_value(
                        landmark_match.group(1)
                    )

                else:
                    near_match = _NEAR_CUE_RE.search(clause)

                    if near_match:
                        extracted["landmark"] = (
                            "Near "
                            + _clean_value(
                                near_match.group(1)
                            )
                        )

            if "locality" not in extracted:

                locality_match = _LOCALITY_CUE_RE.search(clause)

                if locality_match:
                    raw_locality = _clean_value(
                        locality_match.group(1)
                    )
                    extracted["locality"] = raw_locality
                    # If locality contains a comma, extract city from
                    # the last segment (e.g. "Manjalpur, Vadodara"
                    # → city="Vadodara").
                    if "city" not in extracted and "," in raw_locality:
                        parts = [p.strip() for p in raw_locality.split(",")]
                        if len(parts) >= 2:
                            extracted["city"] = parts[-1]

                    # If locality stopped at city/town, extract city from
                    # tail (shared with the Gemini-path backfill above).
                    if "city" not in extracted:
                        _backfill_city_from_locality(clause, extracted)

                        # Canonical values must not repeat the city inside
                        # locality (e.g. locality should read "Near J.B.
                        # Modi Garden", not "Near J.B. Modi Garden,
                        # Bharuch") once city has been split out.
                        if "city" in extracted:
                            city_value = extracted["city"]
                            loc_value = extracted["locality"]
                            suffix = f", {city_value}"
                            if loc_value.lower().endswith(suffix.lower()):
                                extracted["locality"] = loc_value[
                                    : -len(suffix)
                                ].strip()

            if "city" not in extracted:

                city_match = _CITY_CUE_RE.search(clause)

                if city_match:
                    extracted["city"] = _clean_value(
                        city_match.group(1)
                    )
                else:
                    suffix_match = _CITY_SUFFIX_RE.match(clause.strip())
                    if suffix_match:
                        extracted["city"] = _clean_value(
                            suffix_match.group(1)
                        )

            if current_field and current_field not in extracted:

                generic_match = _generic_cue_re(
                    current_field
                ).search(clause)

                if generic_match:
                    extracted[current_field] = _clean_value(
                        generic_match.group(1)
                    )

        if current_field and current_field not in extracted:

            words = message.split()

            starts_narrative = (
                message.lower().split(" ", 1)[0]
                in (
                    "i",
                    "i'm",
                    "we",
                    "we're",
                    "my",
                    "our",
                )
            )

            looks_like_question = (
                message.strip().endswith("?")
            )

            if (
                words
                and len(words) <= 6
                and not starts_narrative
                and not looks_like_question
            ):

                candidate = _clean_value(message)

                if (
                    _is_numeric_expecting_field(current_field)
                    and not any(
                        ch.isdigit()
                        for ch in candidate
                    )
                ):
                    return SemanticExtractionResult(
                        invalid=True
                    )

                if candidate:
                    extracted[current_field] = candidate

        if not extracted:
            return SemanticExtractionResult(
                needs_clarification=True
            )

        # Defensive: pincode must be numeric; reject non-numeric values
        # that were incorrectly assigned (e.g. "Bharuch city" into pincode).
        if "pincode" in extracted and not any(
            ch.isdigit() for ch in extracted["pincode"]
        ):
            del extracted["pincode"]

        return SemanticExtractionResult(
            extracted_fields=extracted
        )
