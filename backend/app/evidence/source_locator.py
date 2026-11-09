
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.db import get_supabase


DEFAULT_MODEL = (
    "gemini-3.5-flash-lite"
)

MAX_CHUNK_TEXT = 5000

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta"
)


class SourceLocator:

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
    ):

        print(
            "Initializing exact source locator..."
        )

        settings = get_settings()

        api_key = settings.gemini_api_key

        if not api_key:

            raise RuntimeError(
                "GEMINI_API_KEY is not set."
            )

        self.api_key = api_key

        self.model = model

        self.client = httpx.Client(
            timeout=60.0,
        )

        print(
            "Exact source locator ready."
        )

        print(
            f"Model: {self.model}"
        )


    @staticmethod
    def _cache_key(
        source_url: str,
        chunk_id: str | None,
        source_text: str,
    ) -> str:

        normalized_url = (
            str(
                source_url or ""
            )
            .strip()
            .rstrip("/")
        )

        normalized_chunk = str(
            chunk_id or ""
        ).strip()

        normalized_text = re.sub(
            r"\s+",
            " ",
            str(
                source_text or ""
            ),
        ).strip()

        raw = (
            normalized_url
            + "\n"
            + normalized_chunk
            + "\n"
            + normalized_text
        )

        return hashlib.sha256(
            raw.encode(
                "utf-8"
            )
        ).hexdigest()


    @staticmethod
    def _detect_source_type(
        source_url: str,
        source_type: str | None = None,
    ) -> str:

        if source_type:

            normalized = (
                str(
                    source_type
                )
                .strip()
                .lower()
            )

            if normalized in {
                "pdf",
                "article",
                "web",
                "html",
            }:

                if normalized in {
                    "html",
                    "web",
                }:

                    return "article"

                return normalized

        url = (
            str(
                source_url or ""
            )
            .lower()
        )

        if (
            ".pdf"
            in url
            or "pdf"
            in url.split("?")[0]
        ):

            return "pdf"

        return "article"


    @staticmethod
    def _normalize_text(
        text: str,
    ) -> str:

        text = re.sub(
            r"\s+",
            " ",
            str(
                text or ""
            ),
        ).strip()

        return text


    def _get_cache(
        self,
        cache_key: str,
    ) -> dict | None:
        """
        Retrieve cached locator result from Supabase.
        """

        try:

            supabase = get_supabase()

            response = (
                supabase.table(
                    "evidence_source_cache"
                )
                .select("locator")
                .eq("cache_key", cache_key)
                .limit(1)
                .execute()
            )

            rows = (
                response.data or []
            )

            if rows:

                locator = rows[0].get("locator")

                if isinstance(locator, str):

                    try:

                        locator = json.loads(
                            locator
                        )

                    except json.JSONDecodeError:

                        locator = None

                return locator

        except Exception:

            print(
                "Supabase cache read failed."
            )

        return None


    def _save_cache(
        self,
        cache_key: str,
        source_url: str,
        locator: dict,
        chunk_id: str | None,
        source_title: str | None,
        source_type: str,
        source_text: str,
    ) -> None:
        """
        Save locator result to Supabase cache.
        """

        try:

            supabase = get_supabase()

            supabase.table(
                "evidence_source_cache"
            ).insert(
                {
                    "cache_key": cache_key,
                    "source_url": source_url,
                    "locator": json.dumps(
                        locator
                    ),
                    "chunk_id": chunk_id,
                    "source_title": source_title,
                    "source_type": source_type,
                    "source_text": source_text[
                        :5000
                    ],
                }
            ).execute()

        except Exception:

            print(
                "Supabase cache write failed."
            )


    def _call_gemini(
        self,
        source_url: str,
        source_text: str,
        source_title: str | None,
        source_type: str,
        page_hint: Any = None,
    ) -> dict[str, Any]:

        page_hint_text = (
            str(page_hint)
            if page_hint is not None
            else "unknown"
        )

        prompt = f"""
You are the exact source-location layer of eGovAssist.

Your task is NOT to answer the user's question.

You must locate the supplied evidence passage inside the
original source URL.

============================================================
SOURCE
============================================================

URL:
{source_url}

TITLE:
{source_title or "Unknown"}

SOURCE TYPE:
{source_type}

============================================================
RETRIEVED EVIDENCE CHUNK
============================================================

{source_text}

============================================================
KNOWN RETRIEVAL PAGE HINT
============================================================

{page_hint_text}

============================================================
TASK
============================================================

Open and inspect the supplied source URL.

Find the exact location where the retrieved evidence passage
comes from.

The evidence chunk may be:

- clipped at the beginning
- clipped at the end
- split across chunks
- missing some surrounding words
- a paragraph fragment
- a section fragment

You must identify the original source location rather than
guessing from the chunk metadata.

============================================================
WEB ARTICLE
============================================================

For an HTML/web article:

- identify the exact relevant paragraph or section
- provide the section heading when available
- provide a useful direct URL
- do NOT invent line numbers
- do NOT invent page numbers

============================================================
PDF
============================================================

For a PDF:

- identify the exact PDF page containing the passage
- distinguish PDF page number from printed page number when
  possible
- provide the PDF URL
- provide a fragment of the original surrounding passage
- if the passage spans multiple pages, return all relevant
  page numbers

============================================================
IMPORTANT
============================================================

Do NOT rewrite the source passage.

Do NOT summarize it.

Do NOT use outside knowledge.

Do NOT guess a page number.

If the exact location cannot be established, set found to
false and return null for page, section_title,
paragraph_text, and matched_text.

============================================================
OUTPUT
============================================================

Return JSON only.

Use this structure:

{{
  "found": true,
  "source_type": "pdf",
  "page": 12,
  "pages": [12],
  "section_title": "Example Section",
  "paragraph_text": "Exact surrounding paragraph from source.",
  "matched_text": "Exact portion matching the evidence chunk.",
  "source_url": "{source_url}",
  "direct_url": "{source_url}",
  "confidence": 0.98,
  "location_reason": "The supplied passage was found on PDF page 12."
}}

If not found:

{{
  "found": false,
  "source_type": "{source_type}",
  "page": null,
  "pages": [],
  "section_title": null,
  "paragraph_text": null,
        "matched_text": null,
  "source_url": "{source_url}",
  "direct_url": "{source_url}",
  "confidence": 0.0,
  "location_reason": "The exact passage could not be established."
}}

Confidence must be between 0 and 1.
"""

        url = (
            f"{GEMINI_API_URL}/models/"
            f"{self.model}:generateContent"
            f"?key={self.api_key}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": (
                    "application/json"
                ),
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "found": {
                            "type": "BOOLEAN",
                        },
                        "source_type": {
                            "type": "STRING",
                        },
                        "page": {
                            "type": "INTEGER",
                        },
                        "pages": {
                            "type": "ARRAY",
                            "items": {
                                "type": "INTEGER",
                            },
                        },
                        "section_title": {
                            "type": "STRING",
                        },
                        "paragraph_text": {
                            "type": "STRING",
                        },
                        "matched_text": {
                            "type": "STRING",
                        },
                        "source_url": {
                            "type": "STRING",
                        },
                        "direct_url": {
                            "type": "STRING",
                        },
                        "confidence": {
                            "type": "NUMBER",
                        },
                        "location_reason": {
                            "type": "STRING",
                        },
                    },
                    "required": [
                        "found",
                        "source_type",
                        "pages",
                        "source_url",
                        "direct_url",
                        "confidence",
                        "location_reason",
                    ],
                },
            },
        }

        response = self.client.post(
            url,
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

        candidates = data.get(
            "candidates",
            [],
        )

        if not candidates:

            raise RuntimeError(
                "Gemini returned no candidates."
            )

        content = (
            candidates[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )

        if not content:

            raise RuntimeError(
                "Gemini returned an empty source-location response."
            )

        try:

            result = json.loads(
                content
            )

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                "Gemini returned invalid JSON during source location."
            ) from exc

        if not isinstance(
            result,
            dict,
        ):

            raise RuntimeError(
                "Gemini returned an invalid source-location object."
            )

        return result


    @staticmethod
    def _sanitize_result(
        result: dict[str, Any],
        source_url: str,
        source_type: str,
    ) -> dict[str, Any]:

        found = bool(
            result.get(
                "found",
                False,
            )
        )

        pages = result.get(
            "pages",
            [],
        )

        if not isinstance(
            pages,
            list,
        ):

            pages = []

        clean_pages = []

        for page in pages:

            try:

                page_number = int(
                    page
                )

            except (
                TypeError,
                ValueError,
            ):

                continue

            if page_number <= 0:
                continue

            if page_number not in clean_pages:

                clean_pages.append(
                    page_number
                )

        page = result.get(
            "page"
        )

        try:

            if page is not None:

                page = int(
                    page
                )

        except (
            TypeError,
            ValueError,
        ):

            page = None

        if (
            page is not None
            and page > 0
            and page not in clean_pages
        ):

            clean_pages.insert(
                0,
                page
            )

        if clean_pages:

            page = clean_pages[0]


        if (
            page is not None
            and page <= 0
        ):

            page = None

        confidence = result.get(
            "confidence",
            0.0,
        )

        try:

            confidence = float(
                confidence
            )

        except (
            TypeError,
            ValueError,
        ):

            confidence = 0.0

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        section_title = result.get(
            "section_title"
        )

        if section_title is not None:

            section_title = str(
                section_title
            ).strip()

            if not section_title:

                section_title = None

        paragraph_text = result.get(
            "paragraph_text"
        )

        if paragraph_text is not None:

            paragraph_text = str(
                paragraph_text
            ).strip()

            if not paragraph_text:

                paragraph_text = None

        matched_text = result.get(
            "matched_text"
        )

        if matched_text is not None:

            matched_text = str(
                matched_text
            ).strip()

            if not matched_text:

                matched_text = None

        sanitized = {

            "found": found,

            "source_type": (
                source_type
            ),

            "page": page,

            "pages": clean_pages,

            "section_title": (
                section_title
            ),

            "paragraph_text": (
                paragraph_text
            ),

            "matched_text": (
                matched_text
            ),

            "source_url": (
                source_url
            ),

            "direct_url": (
                result.get(
                    "direct_url"
                )
                or source_url
            ),

            "confidence": confidence,

            "location_reason": str(
                result.get(
                    "location_reason",
                    "",
                )
                or ""
            ).strip(),

        }

        return sanitized


    def locate(
        self,
        source_url: str,
        source_text: str,
        chunk_id: str | None = None,
        source_title: str | None = None,
        source_type: str | None = None,
        page_hint: Any = None,
    ) -> dict[str, Any]:

        source_url = str(
            source_url or ""
        ).strip()

        source_text = (
            self._normalize_text(
                source_text
            )
        )

        if not source_url:

            raise ValueError(
                "source_url is required."
            )

        if not source_text:

            raise ValueError(
                "source_text is required."
            )

        if len(source_text) > MAX_CHUNK_TEXT:

            source_text = (
                source_text[
                    :MAX_CHUNK_TEXT
                ]
            )

        detected_type = (
            self._detect_source_type(
                source_url,
                source_type,
            )
        )

        cache_key = (
            self._cache_key(
                source_url=source_url,
                chunk_id=chunk_id,
                source_text=source_text,
            )
        )


        cached = (
            self._get_cache(
                cache_key
            )
        )

        if cached is not None:

            locator = (
                cached.get(
                    "locator"
                )
                or {}
            )

            locator = dict(
                locator
            )

            locator[
                "cache_hit"
            ] = True

            locator[
                "cache_key"
            ] = cache_key

            print(
                "Exact source locator: "
                "Supabase cache HIT."
            )

            return locator


        print(
            "Exact source locator: "
            "Supabase cache MISS."
        )

        print(
            "Calling Gemini for exact source location..."
        )

        result = self._call_gemini(
            source_url=source_url,
            source_text=source_text,
            source_title=source_title,
            source_type=detected_type,
            page_hint=page_hint,
        )

        result = self._sanitize_result(
            result=result,
            source_url=source_url,
            source_type=detected_type,
        )


        self._save_cache(
            cache_key=cache_key,
            source_url=source_url,
            locator=result,
            chunk_id=chunk_id,
            source_title=source_title,
            source_type=detected_type,
            source_text=source_text,
        )

        result = dict(
            result
        )

        result[
            "cache_hit"
        ] = False

        result[
            "cache_key"
        ] = cache_key

        print(
            "Exact source location "
            "saved to Supabase."
        )

        return result


_source_locator = None


def get_locator() -> SourceLocator:

    global _source_locator

    if _source_locator is None:

        _source_locator = SourceLocator()

    return _source_locator


def locate_source(
    source_url: str,
    source_text: str,
    chunk_id: str | None = None,
    source_title: str | None = None,
    source_type: str | None = None,
    page_hint: Any = None,
) -> dict[str, Any]:

    return get_locator().locate(
        source_url=source_url,
        source_text=source_text,
        chunk_id=chunk_id,
        source_title=source_title,
        source_type=source_type,
        page_hint=page_hint,
    )
