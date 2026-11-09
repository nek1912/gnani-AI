"""
Web document cleaning and chunking.

This module converts Tavily webpage content into clean,
retrieval-friendly text.

Responsibilities:
- Remove HTML/CSS/JavaScript noise
- Remove navigation/header/footer boilerplate
- Remove images and image URLs
- Repair Markdown links
- Remove corrupted characters
- Remove webpage implementation artifacts
- Deduplicate repeated lines
- Preserve meaningful headings and paragraphs
- Produce coherent overlapping chunks

This module does NOT:
- perform web search
- generate answers
- perform semantic retrieval
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


DEFAULT_CHUNK_SIZE = 1600
DEFAULT_CHUNK_OVERLAP = 220
DEFAULT_MAX_CHUNKS = 20

MIN_CHUNK_LENGTH = 100


class _HTMLTextExtractor(HTMLParser):
    """
    Extract meaningful visible webpage text.

    Structural boilerplate containers such as nav/footer/header
    are ignored completely rather than merely converted to text.
    """

    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "aside",
        "li",
        "ul",
        "ol",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "br",
        "hr",
    }

    IGNORED_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
        "object",
        "embed",
        "form",
        "button",
        "select",
        "option",
        "textarea",
        "template",

        "nav",
        "footer",
        "header",

        "img",
        "picture",
        "video",
        "audio",
        "source",
        "track",
        "map",
        "area",
    }

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.parts = []
        self.ignore_depth = 0

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        tag = tag.lower()

        if tag in self.IGNORED_TAGS:
            self.ignore_depth += 1
            return

        if self.ignore_depth:
            return

        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(
        self,
        tag,
        attrs,
    ):
        tag = tag.lower()

        if tag in self.IGNORED_TAGS:
            return

        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(
        self,
        tag,
    ):
        tag = tag.lower()

        if tag in self.IGNORED_TAGS:

            if self.ignore_depth > 0:
                self.ignore_depth -= 1

            return

        if self.ignore_depth:
            return

        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(
        self,
        data,
    ):
        if self.ignore_depth:
            return

        if data:
            self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


class WebDocumentCleaner:


    @staticmethod
    def _is_image_url(
        value: str,
    ) -> bool:

        value = value.strip()

        if not value:
            return False

        try:
            path = urlparse(value).path.lower()
        except Exception:
            return False

        return path.endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".svg",
                ".ico",
                ".bmp",
                ".avif",
                ".tiff",
                ".tif",
            )
        )


    @staticmethod
    def _remove_html(
        text: str,
    ) -> str:

        if "<" not in text:
            return text

        try:

            parser = _HTMLTextExtractor()

            parser.feed(text)
            parser.close()

            return parser.get_text()

        except Exception:

            return re.sub(
                r"<[^>]+>",
                " ",
                text,
            )


    @staticmethod
    def _remove_code_blocks(
        text: str,
    ) -> str:

        text = re.sub(
            r"```[\s\S]*?```",
            " ",
            text,
        )

        text = re.sub(
            r"<script[\s\S]*?</script>",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        return text


    @staticmethod
    def _repair_markdown_links(
        text: str,
    ) -> str:


        text = re.sub(
            r"!\[[^\]]*\]\(\s*[^)]*\)",
            " ",
            text,
        )


        text = re.sub(
            r"!\[[^\]]*\]\s*",
            " ",
            text,
        )


        text = re.sub(
            r"\[([^\]]+)\]\(\s*https?://[^)]*\)",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )


        text = re.sub(
            r"\[([^\]]+)\]\(\s*\[?https?://.*?\)?\)",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )


        text = re.sub(
            r"https?://\S+\.(?:png|jpg|jpeg|gif|webp|svg|ico|bmp|avif|tiff?)(?:\?\S*)?",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        return text


    @staticmethod
    def _remove_css_noise(
        text: str,
    ) -> str:

        css_patterns = [

            r"(?s)\{[^{}]{0,3000}\}",

            r"(?i)(?:font-family|font-size|line-height|"
            r"background(?:-color)?|margin(?:-[a-z]+)?|"
            r"padding(?:-[a-z]+)?|display|position|"
            r"border(?:-[a-z]+)?|color|width|height|"
            r"z-index|opacity)\s*:\s*[^;{}\n]+;",

            r"(?is)@media\s*[^{]*\{.*?\}",

            r"(?is)(?:^|\s)[.#][a-zA-Z0-9_-]+\s*\{.*?\}",
        ]

        for pattern in css_patterns:

            text = re.sub(
                pattern,
                " ",
                text,
            )

        return text


    @staticmethod
    def _remove_js_noise(
        text: str,
    ) -> str:

        patterns = [

            r"(?i)\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*[^;\n]+;?",

            r"(?is)\bfunction\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{.*?\}",

            r"(?i)\b(?:document|window|console|localStorage|sessionStorage)\."
            r"[A-Za-z_$][\w$]*",

            r"(?i)\baddEventListener\s*\([^)]*\)",

            r"(?i)\b(?:true|false|null)\s*[,;]\s*",
        ]

        for pattern in patterns:

            text = re.sub(
                pattern,
                " ",
                text,
            )

        return text


    @staticmethod
    def _remove_navigation_noise(
        lines: list[str],
    ) -> list[str]:

        noise_exact = {
            "home",
            "menu",
            "search",
            "login",
            "log in",
            "sign in",
            "sign up",
            "register",
            "subscribe",
            "share",
            "print",
            "download",
            "next",
            "previous",
            "back",
            "close",
            "cancel",
            "skip",
            "skip to main content",
            "read more",
            "learn more",
            "view more",
            "view all",
            "click here",
            "more",
            "follow us",
            "contact us",
            "cookie policy",
            "privacy policy",
            "terms and conditions",
            "terms of use",
        }

        cleaned = []

        for line in lines:

            normalized = re.sub(
                r"\s+",
                " ",
                line.strip().lower(),
            )

            if not normalized:
                continue

            if normalized in noise_exact:
                continue


            tokens = re.findall(
                r"[a-zA-Z]+",
                normalized,
            )

            if tokens:

                navigation_tokens = {
                    "home",
                    "menu",
                    "search",
                    "login",
                    "signin",
                    "signup",
                    "register",
                    "subscribe",
                    "share",
                    "print",
                    "next",
                    "previous",
                    "contact",
                    "about",
                }

                nav_count = sum(
                    token in navigation_tokens
                    for token in tokens
                )

                if (
                    len(tokens) <= 8
                    and nav_count >= 2
                ):
                    continue

            cleaned.append(
                line.strip()
            )

        return cleaned


    @staticmethod
    def _remove_webpage_artifacts(
        lines: list[str],
    ) -> list[str]:

        cleaned = []

        artifact_patterns = [

            r"^[.#][\w-]+\s*\{",

            r"^(?:const|let|var)\s+\w+\s*=",

            r"^(?:function|return|document\.|window\.)",

            r"^[|:\-\s]+$",

            r"^(?:share|print|copy link|bookmark)$",

        ]

        compiled = [
            re.compile(
                pattern,
                re.IGNORECASE,
            )
            for pattern in artifact_patterns
        ]

        for line in lines:

            stripped = line.strip()

            if not stripped:
                continue

            if any(
                pattern.search(stripped)
                for pattern in compiled
            ):
                continue

            alnum_count = sum(
                char.isalnum()
                for char in stripped
            )

            if (
                len(stripped) >= 4
                and alnum_count / len(stripped) < 0.35
            ):
                continue

            cleaned.append(
                stripped
            )

        return cleaned


    @staticmethod
    def _remove_corruption(
        text: str,
    ) -> str:

        text = text.replace(
            "\ufffd",
            " ",
        )

        replacements = {
            "Ã©": "é",
            "Ã¨": "è",
            "Ãª": "ê",
            "Ã«": "ë",
            "Ã¡": "á",
            "Ã ": "à",
            "Ã¢": "â",
            "Ã¤": "ä",
            "Ã¥": "å",
            "Ã§": "ç",
            "Ã±": "ñ",
            "Ã¶": "ö",
            "Ã¼": "ü",
            "Ã‰": "É",
            "Ã€": "À",
            "Ã‚": "",
            "â€™": "'",
            "â€œ": '"',
            "â€\x9d": '"',
            "â€“": "–",
            "â€”": "—",
            "â€¦": "…",
            "â€¢": "•",
            "â‚¹": "₹",
            "Â": "",
        }

        for bad, good in replacements.items():
            text = text.replace(
                bad,
                good,
            )

        text = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
            " ",
            text,
        )

        return text


    @staticmethod
    def _deduplicate_lines(
        lines: list[str],
    ) -> list[str]:

        result = []
        seen = set()

        for line in lines:

            normalized = re.sub(
                r"\s+",
                " ",
                line.lower(),
            ).strip()

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            result.append(
                line.strip()
            )

        return result


    @staticmethod
    def _remove_duplicate_sentences(
        text: str,
    ) -> str:
        """
        Remove repeated sentences often caused by webpage
        extraction or duplicated accordion content.
        """

        sentences = re.split(
            r"(?<=[.!?])\s+",
            text,
        )

        seen = set()
        output = []

        for sentence in sentences:

            normalized = re.sub(
                r"\s+",
                " ",
                sentence.lower(),
            ).strip()

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            output.append(
                sentence.strip()
            )

        return " ".join(
            output
        )


    def clean(
        self,
        text: str,
    ) -> str:

        text = str(
            text or ""
        )

        if not text.strip():
            return ""


        text = html.unescape(
            text
        )


        text = self._remove_code_blocks(
            text
        )


        text = self._remove_html(
            text
        )


        text = self._repair_markdown_links(
            text
        )


        text = self._remove_css_noise(
            text
        )

        text = self._remove_js_noise(
            text
        )


        text = self._remove_corruption(
            text
        )


        text = text.replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        )

        raw_lines = text.split(
            "\n"
        )

        lines = []

        for line in raw_lines:

            line = re.sub(
                r"[ \t]+",
                " ",
                line,
            ).strip()

            if not line:
                continue


            urls = re.findall(
                r"https?://\S+",
                line,
            )

            if urls:

                url_chars = len(
                    " ".join(urls)
                )

                if (
                    url_chars >=
                    len(line) * 0.60
                ):
                    continue


            if self._is_image_url(
                line
            ):
                continue

            lines.append(
                line
            )


        lines = self._remove_navigation_noise(
            lines
        )


        lines = self._remove_webpage_artifacts(
            lines
        )


        lines = self._deduplicate_lines(
            lines
        )

        cleaned = "\n\n".join(
            lines
        )


        cleaned = self._remove_duplicate_sentences(
            cleaned
        )


        cleaned = re.sub(
            r"[ \t]{2,}",
            " ",
            cleaned,
        )

        cleaned = re.sub(
            r"\n{3,}",
            "\n\n",
            cleaned,
        )

        return cleaned.strip()


    def chunk(
        self,
        text: str,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
    ) -> list[str]:

        text = self.clean(
            text
        )

        if not text:
            return []

        chunk_size = max(
            500,
            int(chunk_size),
        )

        overlap = max(
            0,
            min(
                int(overlap),
                chunk_size // 2,
            ),
        )

        max_chunks = max(
            1,
            int(max_chunks),
        )


        paragraphs = re.split(
            r"\n\s*\n",
            text,
        )

        paragraphs = [
            paragraph.strip()
            for paragraph in paragraphs
            if paragraph.strip()
        ]


        if len(paragraphs) <= 1:

            paragraphs = [
                line.strip()
                for line in text.split(
                    "\n"
                )
                if line.strip()
            ]

        chunks = []
        current = ""


        def split_long_text(
            value: str,
        ) -> list[str]:

            pieces = []

            start = 0

            while start < len(value):

                end = min(
                    start + chunk_size,
                    len(value),
                )

                if end < len(value):

                    sentence_boundary = max(
                        value.rfind(
                            ". ",
                            start,
                            end,
                        ),
                        value.rfind(
                            "? ",
                            start,
                            end,
                        ),
                        value.rfind(
                            "! ",
                            start,
                            end,
                        ),
                    )

                    if sentence_boundary > start + (
                        chunk_size * 0.60
                    ):

                        end = (
                            sentence_boundary
                            + 1
                        )

                piece = value[
                    start:end
                ].strip()

                if piece:
                    pieces.append(
                        piece
                    )

                if end >= len(value):
                    break

                start = max(
                    0,
                    end - overlap,
                )

            return pieces


        for paragraph in paragraphs:


            if len(paragraph) > chunk_size:

                if current:

                    chunks.append(
                        current.strip()
                    )

                    current = ""

                long_pieces = split_long_text(
                    paragraph
                )

                chunks.extend(
                    long_pieces
                )

                continue


            proposed = (
                paragraph
                if not current
                else (
                    current
                    + "\n\n"
                    + paragraph
                )
            )

            if len(proposed) <= chunk_size:

                current = proposed

            else:

                if current:

                    chunks.append(
                        current.strip()
                    )


                if chunks and overlap > 0:

                    previous = chunks[-1]

                    overlap_text = previous[
                        max(
                            0,
                            len(previous) - overlap,
                        ):
                    ].strip()

                    candidate = (
                        overlap_text
                        + "\n\n"
                        + paragraph
                    )

                    if len(candidate) <= chunk_size:

                        current = candidate

                    else:

                        current = paragraph

                else:

                    current = paragraph

        if current:

            chunks.append(
                current.strip()
            )


        filtered = []

        for chunk in chunks:

            chunk = chunk.strip()

            if not chunk:
                continue

            if (
                len(chunk) < MIN_CHUNK_LENGTH
                and filtered
            ):

                merged = (
                    filtered[-1]
                    + "\n\n"
                    + chunk
                )

                if len(merged) <= (
                    chunk_size + overlap
                ):

                    filtered[-1] = merged

                continue

            filtered.append(
                chunk
            )


        return filtered[
            :max_chunks
        ]


_cleaner = None


def clean_web_text(
    text: str,
) -> str:

    global _cleaner

    if _cleaner is None:
        _cleaner = WebDocumentCleaner()

    return _cleaner.clean(
        text
    )


def chunk_web_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[str]:

    global _cleaner

    if _cleaner is None:
        _cleaner = WebDocumentCleaner()

    return _cleaner.chunk(
        text,
        chunk_size=chunk_size,
        overlap=overlap,
        max_chunks=max_chunks,
    )
