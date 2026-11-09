# IMPORTANT:

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse


VERIFIED = "verified"
PARTIALLY_VERIFIED = "partially_verified"
UNVERIFIED = "unverified"


AUTHORITY_TIERS = {
    1: "Primary / Official",
    2: "Institutional",
    3: "Secondary",
    4: "Unknown / Unverified",
}


SOURCE_WEB = "web"
SOURCE_DOCUMENT = "document"
SOURCE_USER_UPLOAD = "user_upload"
SOURCE_UNKNOWN = "unknown"


KNOWN_SOURCES = {


    "government_of_india": {

        "patterns": [
            "government of india",
            "govt of india",
            "govt. of india",
            "ministry of",
            "department of",
            "भारत सरकार",
        ],

        "issuer_patterns": [
            "government of india",
            "govt of india",
            "ministry of",
            "department of",
        ],

        "domains": [
            "gov.in",
            "nic.in",
            "mygov.in",
            "india.gov.in",
        ],

        "authority_tier": 1,

        "authority_label": (
            "Primary / Official"
        ),
    },


    "pmfby": {

        "patterns": [
            "pmfby",
            "pradhan mantri fasal bima yojana",
            "pradhan mantri fasal bima yojna",
            "operational guidelines",
        ],

        "issuer_patterns": [
            "ministry of agriculture",
            "agriculture & farmers welfare",
            "agriculture and farmers welfare",
            "government of india",
            "department of agriculture",
        ],

        "domains": [
            "pmfby.gov.in",
            "gov.in",
            "nic.in",
        ],

        "authority_tier": 1,

        "authority_label": (
            "Primary / Official"
        ),
    },


    "nabard": {

        "patterns": [
            "nabard",
            "national bank for agriculture "
            "and rural development",
        ],

        "issuer_patterns": [
            "nabard",
            "national bank for agriculture "
            "and rural development",
        ],

        "domains": [
            "nabard.org",
        ],

        "authority_tier": 1,

        "authority_label": (
            "Primary / Official"
        ),
    },


    "irdai": {

        "patterns": [
            "irdai",
            "insurance regulatory and "
            "development authority",
            "insurance regulatory and "
            "development authority of india",
        ],

        "issuer_patterns": [
            "irdai",
            "insurance regulatory and "
            "development authority",
            "insurance regulatory and "
            "development authority of india",
        ],

        "domains": [
            "irdai.gov.in",
        ],

        "authority_tier": 1,

        "authority_label": (
            "Primary / Official"
        ),
    },
}


OFFICIAL_DOMAIN_SUFFIXES = (
    ".gov.in",
    ".nic.in",
    ".gov",
)


INSTITUTIONAL_DOMAIN_SUFFIXES = (
    ".edu",
    ".ac.in",
    ".org.in",
)


def _clean(
    value: Any,
) -> str:
    """
    Normalize arbitrary metadata into text.
    """

    if value is None:
        return ""

    return str(value).strip()


def _lower(
    value: Any,
) -> str:

    return _clean(value).lower()


def _first_non_empty(
    data: dict,
    keys: list[str],
) -> Any:
    """
    Return the first non-empty value from
    candidate keys.
    """

    for key in keys:

        value = data.get(key)

        if (
            value is not None
            and str(value).strip()
        ):

            return value

    return None


def _contains_any(
    text: str,
    patterns: list[str],
) -> bool:
    """
    Return True if text contains any supplied pattern.
    """

    text = text.lower()

    return any(
        pattern.lower() in text
        for pattern in patterns
    )


def normalize_domain(
    source_url: Any,
) -> str:
    """
    Extract and normalize the hostname from a URL.
    """

    url = _clean(source_url)

    if not url:
        return ""

    try:

        parsed = urlparse(url)

        hostname = (
            parsed.hostname
            or ""
        )

        hostname = hostname.lower().strip()

        hostname = hostname.removeprefix("www.")

        return hostname

    except Exception:
        return ""


def is_official_domain(
    source_url: Any,
) -> bool:
    """
    Determine whether a URL belongs to a known
    Indian government / official namespace.
    """

    domain = normalize_domain(
        source_url
    )

    if not domain:
        return False

    if domain in {
        "gov.in",
        "nic.in",
        "mygov.in",
        "india.gov.in",
    }:
        return True

    return domain.endswith(
        OFFICIAL_DOMAIN_SUFFIXES
    )


def is_institutional_domain(
    source_url: Any,
) -> bool:
    """
    Determine whether a URL appears to belong
    to an institutional domain.
    """

    domain = normalize_domain(
        source_url
    )

    if not domain:
        return False

    return domain.endswith(
        INSTITUTIONAL_DOMAIN_SUFFIXES
    )


def detect_source_type(
    result: dict,
    identity: dict,
) -> str:
    """
    Determine whether the evidence originates from:
        - web
        - uploaded document
        - unknown source
    """

    explicit_type = _lower(
        _first_non_empty(
            result,
            [
                "source_type",
                "document_type",
                "evidence_type",
                "type",
            ],
        )
    )

    if explicit_type in {
        "web",
        "website",
        "webpage",
        "url",
    }:
        return SOURCE_WEB

    if explicit_type in {
        "user_upload",
        "uploaded_pdf",
        "upload",
        "pdf",
        "document",
    }:

        if (
            result.get("uploaded")
            or result.get("user_uploaded")
            or result.get("upload_document_id")
        ):
            return SOURCE_USER_UPLOAD

        return SOURCE_DOCUMENT

    source_url = identity.get(
        "source_url"
    )

    if source_url:
        return SOURCE_WEB

    if (
        result.get("uploaded")
        or result.get("user_uploaded")
        or result.get("upload_document_id")
        or result.get("file_name")
        or result.get("filename")
    ):
        return SOURCE_USER_UPLOAD

    if (
        identity.get("document_id")
        or identity.get("file_hash")
        or identity.get("page")
    ):
        return SOURCE_DOCUMENT

    return SOURCE_UNKNOWN


def calculate_sha256(
    file_path: str,
) -> str:
    """
    Calculate SHA-256 for a local source file.

    This creates a deterministic document fingerprint.
    It does not by itself prove authenticity.
    """

    sha256 = hashlib.sha256()

    with open(
        file_path,
        "rb",
    ) as file:

        for chunk in iter(
            lambda: file.read(
                1024 * 1024
            ),
            b"",
        ):

            sha256.update(chunk)

    return sha256.hexdigest()


def extract_source_identity(
    result: dict,
) -> dict:
    """
    Normalize source metadata from a retrieved result.

    Supports aliases used by:
        - web discovery
        - FAISS
        - BM25
        - PDF ingestion
        - uploaded document storage
    """

    chunk_id = _first_non_empty(
        result,
        [
            "chunk_id",
            "id",
            "document_chunk_id",
            "metadata_id",
        ],
    )

    document_id = _first_non_empty(
        result,
        [
            "document_id",
            "doc_id",
            "source_id",
            "upload_document_id",
        ],
    )

    title = _first_non_empty(
        result,
        [
            "title",
            "document_title",
            "source_title",
            "file_name",
            "filename",
        ],
    )

    issuer = _first_non_empty(
        result,
        [
            "issuer",
            "organization",
            "organisation",
            "publisher",
            "issuing_authority",
            "authority",
        ],
    )

    year = _first_non_empty(
        result,
        [
            "year",
            "publication_year",
            "document_year",
        ],
    )

    version = _first_non_empty(
        result,
        [
            "version",
            "document_version",
        ],
    )

    source_url = _first_non_empty(
        result,
        [
            "source_url",
            "url",
            "document_url",
            "official_url",
            "source",
        ],
    )

    file_hash = _first_non_empty(
        result,
        [
            "file_hash",
            "sha256",
            "sha256_hash",
            "document_hash",
        ],
    )

    section = _first_non_empty(
        result,
        [
            "section",
            "section_title",
            "heading",
        ],
    )

    page = _first_non_empty(
        result,
        [
            "page",
            "page_number",
            "pdf_page",
        ],
    )

    text = _first_non_empty(
        result,
        [
            "text",
            "content",
            "chunk_text",
        ],
    )

    file_name = _first_non_empty(
        result,
        [
            "file_name",
            "filename",
            "original_filename",
        ],
    )

    return {

        "chunk_id": chunk_id,

        "document_id": document_id,

        "title": title,

        "issuer": issuer,

        "year": year,

        "version": version,

        "source_url": source_url,

        "file_hash": file_hash,

        "section": section,

        "page": page,

        "text": text,

        "file_name": file_name,
    }


def identify_known_source(
    identity: dict,
) -> dict:
    """
    Identify known authoritative sources.

    Matching considers:
        - title
        - issuer
        - document ID
        - chunk ID
        - text
        - URL domain
    """

    title = _lower(
        identity.get("title")
    )

    issuer = _lower(
        identity.get("issuer")
    )

    document_id = _lower(
        identity.get("document_id")
    )

    chunk_id = _lower(
        identity.get("chunk_id")
    )

    text = _lower(
        identity.get("text")
    )

    source_url = identity.get(
        "source_url"
    )

    domain = normalize_domain(
        source_url
    )

    combined = " ".join(  # noqa: FLY002
        [
            title,
            issuer,
            document_id,
            chunk_id,
            text,
        ]
    ).strip()

    matches = []

    for source_id, source in KNOWN_SOURCES.items():

        pattern_match = _contains_any(
            combined,
            source["patterns"],
        )

        domain_match = False

        for known_domain in source.get(
            "domains",
            [],
        ):

            if (
                domain == known_domain
                or domain.endswith(
                    "." + known_domain
                )
            ):

                domain_match = True
                break

        if (
            pattern_match
            or domain_match
        ):

            issuer_match = False

            if issuer:

                issuer_match = _contains_any(
                    issuer,
                    source["issuer_patterns"],
                )

            matches.append(
                {
                    "source_id": source_id,

                    "pattern_match": (
                        pattern_match
                    ),

                    "domain_match": (
                        domain_match
                    ),

                    "issuer_match": (
                        issuer_match
                    ),

                    "authority_tier": source[
                        "authority_tier"
                    ],

                    "authority_label": source[
                        "authority_label"
                    ],
                }
            )

    if not matches:

        return {

            "known_source": False,

            "source_matches": [],

            "authority_tier": 4,

            "authority_label": (
                AUTHORITY_TIERS[4]
            ),

            "issuer_match": False,

            "domain_match": False,
        }

    matches.sort(
        key=lambda item: (
            item["authority_tier"],
            not item["domain_match"],
            not item["issuer_match"],
            not item["pattern_match"],
        )
    )

    best = matches[0]

    return {

        "known_source": True,

        "source_matches": matches,

        "authority_tier": best[
            "authority_tier"
        ],

        "authority_label": best[
            "authority_label"
        ],

        "issuer_match": best[
            "issuer_match"
        ],

        "domain_match": best[
            "domain_match"
        ],
    }


def evaluate_authority(
    identity: dict,
    source_type: str,
) -> dict:
    """
    Evaluate source authority.

    Official domains receive primary authority even when
    the page itself does not explicitly contain issuer metadata.
    """

    known = identify_known_source(
        identity
    )

    source_url = identity.get(
        "source_url"
    )

    official_domain = is_official_domain(
        source_url
    )

    institutional_domain = (
        is_institutional_domain(
            source_url
        )
    )

    authority_tier = known.get(
        "authority_tier",
        4,
    )

    authority_label = known.get(
        "authority_label",
        AUTHORITY_TIERS[4],
    )

    domain_match = known.get(
        "domain_match",
        False,
    )

    issuer_match = known.get(
        "issuer_match",
        False,
    )

    reasons = []


    if official_domain:

        authority_tier = 1

        authority_label = (
            "Primary / Official"
        )

        reasons.append(
            "Source URL belongs to an official "
            "government domain."
        )


    elif known.get(
        "known_source",
        False,
    ):

        reasons.append(
            "Source matches a recognized "
            "authoritative source."
        )


    elif institutional_domain:

        authority_tier = 2

        authority_label = (
            "Institutional"
        )

        reasons.append(
            "Source URL belongs to an "
            "institutional domain."
        )


    elif (
        source_type == SOURCE_WEB
        and bool(
            normalize_domain(
                source_url
            )
        )
    ):

        authority_tier = 3

        authority_label = (
            "Secondary"
        )

        reasons.append(
            "Source is a general secondary web source "
            "with a resolvable domain but no recognized "
            "official or institutional authority signal."
        )


    if source_type == SOURCE_USER_UPLOAD:

        authority_tier = 4

        authority_label = (
            "User Provided"
        )

        reasons.append(
            "Document was provided by the user; "
            "authority must come from document provenance."
        )

    return {

        "known_source": known.get(
            "known_source",
            False,
        ),

        "source_matches": known.get(
            "source_matches",
            [],
        ),

        "authority_tier": authority_tier,

        "authority_label": authority_label,

        "issuer_match": issuer_match,

        "domain_match": domain_match,

        "official_domain": official_domain,

        "institutional_domain": (
            institutional_domain
        ),

        "reasons": reasons,
    }


def evaluate_metadata(
    identity: dict,
    source_type: str,
) -> dict:
    """
    Evaluate metadata completeness.

    Web evidence:
        URL + chunk/title are sufficient.

    Document evidence:
        document ID + chunk ID + page/section are important.
    """

    fields = {

        "title": bool(
            identity.get("title")
        ),

        "issuer": bool(
            identity.get("issuer")
        ),

        "year": bool(
            identity.get("year")
        ),

        "version": bool(
            identity.get("version")
        ),

        "source_url": bool(
            identity.get("source_url")
        ),

        "file_hash": bool(
            identity.get("file_hash")
        ),

        "page": (
            identity.get("page")
            is not None
        ),

        "section": bool(
            identity.get("section")
        ),

        "document_id": bool(
            identity.get("document_id")
        ),

        "chunk_id": bool(
            identity.get("chunk_id")
        ),

        "file_name": bool(
            identity.get("file_name")
        ),
    }

    if source_type == SOURCE_WEB:

        required_fields = {
            "source_url",
            "chunk_id",
        }

    elif source_type in {
        SOURCE_DOCUMENT,
        SOURCE_USER_UPLOAD,
    }:

        required_fields = {
            "document_id",
            "chunk_id",
        }


    else:

        required_fields = {
            "chunk_id",
        }

    available = sum(
        1
        for value in fields.values()
        if value
    )

    total = len(fields)

    required_available = sum(
        1
        for field in required_fields
        if fields.get(field)
    )

    required_total = len(
        required_fields
    )

    completeness = (
        required_available
        / required_total
        if required_total
        else 0.0
    )

    return {

        "fields": fields,

        "available_fields": available,

        "total_fields": total,

        "completeness": round(
            completeness,
            3,
        ),

        "required_fields": sorted(
            required_fields
        ),

        "required_fields_available": (
            required_available
        ),

        "required_fields_total": (
            required_total
        ),
    }


def evaluate_integrity(
    identity: dict,
) -> dict:
    """
    Evaluate available integrity information.

    A SHA-256 value is an integrity signal.
    It does not prove authenticity without a trusted reference.
    """

    file_hash = _clean(
        identity.get("file_hash")
    )

    if not file_hash:

        return {

            "available": False,

            "verified": False,

            "status": "not_available",

            "message": (
                "No document hash is available."
            ),
        }

    normalized_hash = (
        file_hash.lower()
    )

    valid_sha256 = bool(
        re.fullmatch(
            r"[a-f0-9]{64}",
            normalized_hash,
        )
    )

    if not valid_sha256:

        return {

            "available": True,

            "verified": False,

            "status": "invalid_format",

            "message": (
                "A hash was provided, but it "
                "is not a valid SHA-256 value."
            ),
        }

    return {

        "available": True,

        "verified": False,

        "status": "recorded",

        "message": (
            "A SHA-256 document hash is recorded. "
            "A trusted reference hash is required "
            "for cryptographic verification."
        ),
    }


def evaluate_provenance(
    identity: dict,
    source_type: str,
) -> dict:
    """
    Evaluate traceability.

    Web:
        URL + chunk/title = strong

    Document:
        document identity + page/section = strong
        document identity only = partial
    """

    has_document_identity = bool(
        identity.get("document_id")
        or identity.get("title")
        or identity.get("file_name")
        or identity.get("chunk_id")
    )

    has_url = bool(
        identity.get("source_url")
    )

    has_location = bool(
        identity.get("page")
        or identity.get("section")
    )


    if source_type == SOURCE_WEB:

        if (
            has_url
            and identity.get("chunk_id")
        ) or has_url and has_document_identity:

            status = "strong"

        elif has_url:

            status = "partial"

        else:

            status = "weak"


    else:

        if (
            has_document_identity
            and has_location
        ):

            status = "strong"

        elif has_document_identity:

            status = "partial"

        else:

            status = "weak"

    return {

        "status": status,

        "traceable": status in {
            "strong",
            "partial",
        },

        "has_document_identity": (
            has_document_identity
        ),

        "has_url": has_url,

        "has_location": has_location,

        "source_type": source_type,
    }


def calculate_trust_score(
    identity: dict,
    authority: dict,
    metadata: dict,
    integrity: dict,
    provenance: dict,
    source_type: str,
) -> tuple[float, list[str]]:
    """
    Calculate deterministic trust score.

    Maximum:
        100
    """

    score = 0.0

    reasons = []

    authority_tier = authority.get(
        "authority_tier",
        4,
    )


    if authority_tier == 1:

        score += 45

        reasons.append(
            "Source is recognized as primary / official."
        )

    elif authority_tier == 2:

        score += 30

        reasons.append(
            "Source is recognized as institutional."
        )

    elif authority_tier == 3:

        score += 15

        reasons.append(
            "Source appears to be secondary."
        )

    else:

        reasons.append(
            "Source authority could not be established."
        )


    if authority.get(
        "official_domain",
        False,
    ):

        score += 15

        reasons.append(
            "Official URL domain provides strong provenance."
        )


    if authority.get(
        "issuer_match",
        False,
    ):

        score += 10

        reasons.append(
            "Issuer metadata agrees with the recognized source."
        )


    if provenance.get(
        "status"
    ) == "strong":

        score += 20

        if source_type == SOURCE_WEB:

            reasons.append(
                "Web URL and evidence chunk provenance "
                "are available."
            )

        else:

            reasons.append(
                "Document and page/section provenance "
                "are available."
            )

    elif provenance.get(
        "status"
    ) == "partial":

        score += 10

        reasons.append(
            "Source provenance is partially traceable."
        )

    else:

        reasons.append(
            "Source provenance is weak."
        )


    metadata_score = (
        metadata.get(
            "completeness",
            0.0,
        )
        * 10
    )

    score += metadata_score

    if metadata.get(
        "completeness",
        0.0,
    ) >= 0.8:

        reasons.append(
            "Source metadata is sufficiently complete."
        )

    elif metadata.get(
        "completeness",
        0.0,
    ) >= 0.5:

        reasons.append(
            "Source metadata is partially complete."
        )

    else:

        reasons.append(
            "Source metadata is incomplete."
        )


    if integrity.get(
        "status"
    ) == "recorded":

        score += 5

        reasons.append(
            "A SHA-256 document hash is recorded."
        )


    if source_type == SOURCE_USER_UPLOAD:


        if authority_tier == 4:

            reasons.append(
                "User-provided document is not treated "
                "as an official authority by itself."
            )


    score = max(
        0.0,
        min(
            100.0,
            score,
        ),
    )

    return (
        round(score, 2),
        reasons,
    )


def determine_status(
    authority: dict,
    provenance: dict,
    metadata: dict,
    trust_score: float,
    source_type: str,
) -> str:
    """
    Determine verification status.

    VERIFIED means the evidence has sufficiently strong
    deterministic provenance and authority signals.

    It does NOT mean cryptographic authenticity.
    """

    authority_tier = authority.get(
        "authority_tier",
        4,
    )


    if (
        source_type == SOURCE_WEB
        and authority.get(
            "official_domain",
            False,
        )
        and provenance.get(
            "status"
        ) == "strong"
        and metadata.get(
            "completeness",
            0.0,
        ) >= 0.5
        and trust_score >= 70
    ):

        return VERIFIED


    if (
        source_type != SOURCE_WEB
        and authority_tier == 1
        and (
            authority.get(
                "issuer_match",
                False,
            )
            or authority.get(
                "domain_match",
                False,
            )
        )
        and provenance.get(
            "status"
        ) == "strong"
        and trust_score >= 70
    ):

        return VERIFIED


    if (
        authority_tier <= 2
        and provenance.get(
            "traceable",
            False,
        )
        and trust_score >= 45
    ):

        return PARTIALLY_VERIFIED


    if (
        authority_tier == 3
        and provenance.get(
            "traceable",
            False,
        )
        and trust_score >= 55
    ):

        return PARTIALLY_VERIFIED

    return UNVERIFIED


def verify_source(
    result: dict,
) -> dict:
    """
    Verify one source and return complete verification data.
    """

    identity = extract_source_identity(
        result
    )

    source_type = detect_source_type(
        result,
        identity,
    )

    authority = evaluate_authority(
        identity,
        source_type,
    )

    metadata = evaluate_metadata(
        identity,
        source_type,
    )

    integrity = evaluate_integrity(
        identity
    )

    provenance = evaluate_provenance(
        identity,
        source_type,
    )

    trust_score, reasons = (
        calculate_trust_score(
            identity=identity,
            authority=authority,
            metadata=metadata,
            integrity=integrity,
            provenance=provenance,
            source_type=source_type,
        )
    )

    status = determine_status(
        authority=authority,
        provenance=provenance,
        metadata=metadata,
        trust_score=trust_score,
        source_type=source_type,
    )

    return {

        "status": status,

        "verification_status": status,

        "trust_score": trust_score,

        "source_type": source_type,

        "identity": identity,

        "authority": authority,

        "authority_tier": authority.get(
            "authority_tier",
            4,
        ),

        "authority_label": authority.get(
            "authority_label",
            AUTHORITY_TIERS[4],
        ),

        "provenance": provenance,

        "metadata": metadata,

        "integrity": integrity,

        "reasons": (
            authority.get(
                "reasons",
                [],
            )
            + reasons
        ),
    }


def verify_sources(
    results: list[dict],
) -> list[dict]:
    """
    Verify and enrich multiple retrieved sources.
    """

    verified_results = []

    for result in results:

        verification = verify_source(
            result
        )

        enriched = dict(
            result
        )

        enriched["verification"] = (
            verification
        )


        enriched["verification_status"] = (
            verification["status"]
        )

        enriched["trust_score"] = (
            verification["trust_score"]
        )

        enriched["source_type"] = (
            verification["source_type"]
        )

        enriched["authority_tier"] = (
            verification["authority_tier"]
        )

        enriched["authority_label"] = (
            verification["authority_label"]
        )

        verified_results.append(
            enriched
        )

    return verified_results


def filter_sources(
    results: list[dict],
    minimum_trust_score: float = 35.0,
) -> tuple[list[dict], list[dict]]:
    """
    Separate accepted and rejected evidence.

    A source is accepted when:

        1. Trust score >= threshold
        AND
        2. Provenance is traceable

    Official web sources therefore do not need a PDF page.
    """

    accepted = []

    rejected = []

    for result in results:

        verification = result.get(
            "verification"
        )

        if verification is None:

            verification = verify_source(
                result
            )

        trust_score = float(
            verification.get(
                "trust_score",
                0.0,
            )
        )

        enriched = dict(
            result
        )

        enriched["verification"] = (
            verification
        )

        enriched["verification_status"] = (
            verification.get(
                "status",
                UNVERIFIED,
            )
        )

        enriched["trust_score"] = (
            trust_score
        )

        provenance = verification.get(
            "provenance",
            {},
        )

        traceable = provenance.get(
            "traceable",
            False,
        )

        if (
            trust_score >= minimum_trust_score
            and traceable
        ):

            accepted.append(
                enriched
            )

        else:

            rejected.append(
                enriched
            )

    return accepted, rejected


def build_verification_summary(
    results: list[dict],
) -> dict:
    """
    Build aggregate verification statistics.
    """

    if not results:

        return {

            "total_sources": 0,

            "verified_sources": 0,

            "partially_verified_sources": 0,

            "unverified_sources": 0,

            "average_trust_score": 0.0,

            "highest_trust_score": 0.0,

            "lowest_trust_score": 0.0,
        }

    scores = []

    verified = 0

    partial = 0

    unverified = 0

    for result in results:

        verification = result.get(
            "verification",
            {},
        )

        score = float(
            verification.get(
                "trust_score",
                0.0,
            )
        )

        scores.append(
            score
        )

        status = verification.get(
            "status"
        )

        if status == VERIFIED:

            verified += 1

        elif status == PARTIALLY_VERIFIED:

            partial += 1

        else:

            unverified += 1

    return {

        "total_sources": len(
            results
        ),

        "verified_sources": verified,

        "partially_verified_sources": partial,

        "unverified_sources": unverified,

        "average_trust_score": round(
            sum(scores) / len(scores),
            2,
        ),

        "highest_trust_score": round(
            max(scores),
            2,
        ),

        "lowest_trust_score": round(
            min(scores),
            2,
        ),
    }


class SourceVerifier:
    """
    Object-oriented interface used by RAGPipeline.
    """

    def __init__(
        self,
        minimum_trust_score: float = 35.0,
    ):

        self.minimum_trust_score = (
            minimum_trust_score
        )

        print(
            "Source verification layer ready."
        )


    def verify_source(
        self,
        result: dict,
    ) -> dict:

        return verify_source(
            result
        )


    def verify_sources(
        self,
        results: list[dict],
    ) -> dict:
        """
        Verify, filter, and summarize sources.

        This is the pipeline-facing API.
        """

        verified_sources = (
            verify_sources(
                results
            )
        )

        accepted_sources, rejected_sources = (
            filter_sources(
                verified_sources,
                minimum_trust_score=(
                    self.minimum_trust_score
                ),
            )
        )

        summary = (
            build_verification_summary(
                verified_sources
            )
        )

        return {

            "sources": verified_sources,

            "verified_sources": (
                verified_sources
            ),

            "accepted_sources": (
                accepted_sources
            ),

            "rejected_sources": (
                rejected_sources
            ),

            "summary": summary,
        }


    def filter_sources(
        self,
        results: list[dict],
        minimum_trust_score: float | None = None,
    ) -> tuple[list[dict], list[dict]]:

        threshold = (
            self.minimum_trust_score
            if minimum_trust_score is None
            else minimum_trust_score
        )

        return filter_sources(
            results,
            minimum_trust_score=threshold,
        )


    def build_verification_summary(
        self,
        results: list[dict],
    ) -> dict:

        return build_verification_summary(
            results
        )


    def build_summary(
        self,
        results: list[dict],
    ) -> dict:

        return build_verification_summary(
            results
        )


    def verify_and_filter(
        self,
        results: list[dict],
        minimum_trust_score: float | None = None,
    ) -> dict:
        """
        Verify sources, filter weak evidence, and return
        a complete security-layer result.
        """

        threshold = (
            self.minimum_trust_score
            if minimum_trust_score is None
            else minimum_trust_score
        )

        verified_results = (
            verify_sources(
                results
            )
        )

        accepted, rejected = (
            filter_sources(
                verified_results,
                minimum_trust_score=threshold,
            )
        )

        summary = (
            build_verification_summary(
                verified_results
            )
        )

        return {

            "sources": verified_results,

            "verified_sources": (
                verified_results
            ),

            "accepted_sources": accepted,

            "rejected_sources": rejected,

            "summary": summary,
        }


__all__ = [

    "VERIFIED",

    "PARTIALLY_VERIFIED",

    "UNVERIFIED",

    "AUTHORITY_TIERS",

    "SOURCE_WEB",

    "SOURCE_DOCUMENT",

    "SOURCE_USER_UPLOAD",

    "SOURCE_UNKNOWN",

    "calculate_sha256",

    "extract_source_identity",

    "identify_known_source",

    "detect_source_type",

    "normalize_domain",

    "is_official_domain",

    "is_institutional_domain",

    "verify_source",

    "verify_sources",

    "filter_sources",

    "build_verification_summary",

    "SourceVerifier",
]
