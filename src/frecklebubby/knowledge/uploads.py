"""Private uploads per family (PDF, EPUB, txt, md) and the source list."""

from pathlib import PurePath

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import KbSource
from ..services import Ctx, Invalid, NotFound
from .ingest import epub_sections, front_matter, md_sections, pdf_sections
from .store import add_source, delete_sources, ensure_bundled, source_dict

MAX_BYTES = 50 * 1024 * 1024
TYPES = (".pdf", ".epub", ".txt", ".md")


def list_sources(s: Session, ctx: Ctx) -> list[dict]:
    ensure_bundled(s)
    rows = s.scalars(select(KbSource).where(or_(KbSource.family_id.is_(None), KbSource.family_id == ctx.fam.id))
                     .order_by(KbSource.kind, KbSource.title))
    return [source_dict(r) | {"own": r.family_id == ctx.fam.id} for r in rows]


def upload(s: Session, ctx: Ctx, filename: str, data: bytes) -> dict:
    name = PurePath(filename or "upload").name
    ext = PurePath(name).suffix.lower()
    if ext not in TYPES:
        raise Invalid("file: use a PDF, EPUB, TXT or MD file")
    if len(data) > MAX_BYTES:
        raise Invalid("file: the file is larger than 50 MB")
    meta: dict = {"title": PurePath(name).stem}
    try:
        if ext == ".pdf":
            sections, title = pdf_sections(data)
            meta["title"] = title or meta["title"]
        elif ext == ".epub":
            sections = epub_sections(data)
        else:
            raw = data.decode("utf-8", "replace")
            fm, body = front_matter(raw) if ext == ".md" else ({}, raw)
            meta |= {k: v for k, v in fm.items() if k in ("title", "author", "publisher", "year")}
            sections = md_sections(body)
    except Exception as err:  # broken files come in many forms (pypdf, zipfile, yaml errors)
        raise Invalid("file: the file could not be read") from err
    if not any(t.strip() for _, t in sections):
        raise Invalid("file: no text found in the file (scanned PDFs are not supported)")
    src, n = add_source(s, ctx.fam.id, "upload", meta, sections)
    s.commit()
    return source_dict(src) | {"own": True, "chunks": n}


def delete_upload(s: Session, ctx: Ctx, source_id: int) -> None:
    src = s.get(KbSource, source_id)
    if src is None or src.family_id != ctx.fam.id:
        raise NotFound("Source not found. Only your own uploads can be deleted.")
    delete_sources(s, [src.id])
    s.commit()
