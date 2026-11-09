"""Structured seed parser: MinerU ``content_list_v2.json`` -> canonical chunk JSONL.

This is the heart of the new ingestion strategy. It replaces the old
PDF->Markdown->fixed-char-chunk pipeline. The ``content_list_v2.json`` is a
list of pages; each page is a list of typed blocks (title/paragraph/table/
image/...). We use the page index (+1) as the authoritative page number
(fixing the old "Pages: 1" bug) and the block structure to build
clause/heading-aware chunks.

Output per document: ``corpus/seeds/chunks_jsonl/<document_id>.jsonl`` with the
same schema the ingestion script consumes (chunk_id, document_id, source_file,
page_start, page_end, heading_path, section, subsection, clause, chunk_type,
images, text, language).

Run:
    python backend/seed_parser.py
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

SEEDS = Path(__file__).resolve().parent.parent / "corpus" "seeds" if False else Path(__file__).resolve().parent.parent / "corpus" / "seeds"
JSONL_DIR = SEEDS / "chunks_jsonl"
JSON_FILES_DIR = SEEDS / "json_files"

_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+")


class _TableTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append(" ".join(self._cell).strip())
        elif tag == "tr":
            self.rows.append(self._row)

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)

    def text(self) -> str:
        return "\n".join(" | ".join(c for c in r) for r in self.rows if any(r))


def _block_text(block: dict) -> str:
    content = block.get("content", {})
    if not isinstance(content, dict):
        return ""
    out: list[str] = []
    for pc in content.get("paragraph_content", []) or []:
        if isinstance(pc, dict) and pc.get("type") == "text":
            out.append(pc.get("content", ""))
    return "".join(out)


def _table_text(block: dict) -> str:
    content = block.get("content", {})
    raw_html = content.get("html") if isinstance(content, dict) else None
    if raw_html:
        ex = _TableTextExtractor()
        try:
            ex.feed(raw_html)
            txt = ex.text()
            if txt:
                return txt
        except Exception:
            pass
    return ""


def _is_heading(text: str) -> tuple[bool, int]:
    t = text.strip()
    if not t or len(t) > 90:
        return False, 0
    m = _NUMBER_RE.match(t)
    if m:
        return True, len(m.group(1).split("."))
    if t.isupper() and len(t) >= 4:
        return True, 0
    if t.endswith(":") and len(t) >= 6:
        return True, 0
    return False, 0


def _parse_document(document_id: str, v2_path: Path) -> list[dict]:
    pages = json.loads(v2_path.read_text(encoding="utf-8"))
    chunks: list[dict] = []
    heading_path: list[str] = []

    for page_idx, blocks in enumerate(pages):
        page_no = page_idx + 1
        for block in blocks:
            btype = block.get("type")
            if btype in ("page_header", "page_footer", "page_number"):
                continue

            if btype == "image":
                src = block.get("content", {}).get("image_source", {}).get("path", "")
                chunks.append(_mk_chunk(
                    document_id, page_no, heading_path, "image",
                    f"[Image asset: {src}]", images=[src],
                ))
                continue

            if btype == "table":
                src = block.get("content", {}).get("image_source", {}).get("path", "")
                tbl = _table_text(block)
                if tbl:
                    chunks.append(_mk_chunk(
                        document_id, page_no, heading_path, "table",
                        tbl, images=[src] if src else [],
                    ))
                else:
                    chunks.append(_mk_chunk(
                        document_id, page_no, heading_path, "table",
                        f"[Image asset: {src}]", images=[src] if src else [],
                    ))
                continue

            # Text-bearing blocks: title / paragraph / list / algorithm / etc.
            text = _block_text(block).strip()
            if not text:
                continue
            text = html.unescape(text)
            is_head, level = _is_heading(text)
            if is_head and btype in ("title", "paragraph"):
                # Maintain a heading stack. Numbered headings nest by level;
                # non-numbered section titles (ALL-CAPS / trailing colon) replace
                # the previous non-numbered heading. Cap depth to stay tidy.
                if level > 0:
                    while heading_path and _level_of(heading_path[-1]) >= level:
                        heading_path.pop()
                elif heading_path and _level_of(heading_path[-1]) == 0:
                    heading_path.pop()
                heading_path.append(text)
                if len(heading_path) > 6:
                    heading_path = heading_path[-6:]
                continue

            chunks.append(_mk_chunk(
                document_id, page_no, list(heading_path), "text", text,
            ))

    # Renumber chunk_ids deterministically.
    for i, c in enumerate(chunks, 1):
        c["chunk_id"] = f"{document_id}_{i:05d}"
    return chunks


def _level_of(heading: str) -> int:
    m = _NUMBER_RE.match(heading)
    return len(m.group(1).split(".")) if m else 0


def _mk_chunk(document_id, page_no, heading_path, chunk_type, text, images=None) -> dict:
    clause = ""
    m = _NUMBER_RE.match(text)
    if m:
        clause = m.group(1)
    section = heading_path[0] if heading_path else ""
    subsection = heading_path[-1] if heading_path else ""
    return {
        "document_id": document_id,
        "source_file": f"{document_id}.pdf",
        "page_start": page_no,
        "page_end": page_no,
        "heading_path": list(heading_path),
        "section": section,
        "subsection": subsection,
        "clause": clause,
        "chunk_type": chunk_type,
        "images": images or [],
        "text": text,
        "language": "en",
    }


def main() -> None:
    JSONL_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(SEEDS.glob("*.pdf"))
    for pdf in pdfs:
        document_id = pdf.stem
        v2 = JSON_FILES_DIR / f"{document_id}_content_list_v2.json"
        if not v2.exists():
            print(f"[skip] no content_list_v2.json for {document_id}")
            continue
        chunks = _parse_document(document_id, v2)
        out = JSONL_DIR / f"{document_id}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for c in chunks:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"[ok] {document_id}: {len(chunks)} chunks -> {out.name}")


if __name__ == "__main__":
    main()
