"""Evidence locator endpoint — Gemini-powered exact source location."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.evidence.source_locator import SourceLocator

router = APIRouter(prefix="/evidence", tags=["evidence"])

_locator = SourceLocator()


class EvidenceLocateRequest(BaseModel):
    source_url: str
    excerpt: str
    chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    title: str | None = None
    source_type: str = "web"


@router.post("/locate")
def locate_evidence(req: EvidenceLocateRequest) -> dict:
    result = _locator.locate(
        source_url=req.source_url,
        source_text=req.excerpt,
        chunk_id=req.chunk_id,
        source_title=req.title,
        source_type=req.source_type,
        page_hint=req.page,
    )
    return {"status": "ok", "evidence": result}
