"""Document serving endpoint — safe local PDF access."""

from __future__ import annotations

import re
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "corpus" / "seeds"

_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-\.(), ]+\.pdf$")


def _resolve_pdf(filename: str) -> Path:
    """Safely resolve a PDF filename against the canonical corpus directory.

    Prevents path traversal by rejecting any filename containing path
    separators, ``..``, or characters outside the safe set.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    resolved = (CORPUS_DIR / filename).resolve()
    if not resolved.is_relative_to(CORPUS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    return resolved


@router.get("/pdf/{filename}")
async def serve_pdf(filename: str) -> FileResponse:
    r"""Serve a PDF from the canonical corpus directory.

    Only serves files matching ``[A-Za-z0-9_\-\. ]+\.pdf`` from
    ``corpus/seeds/``.  Path traversal and arbitrary filesystem access
    are blocked.
    """
    path = _resolve_pdf(filename)
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=filename,
    )
