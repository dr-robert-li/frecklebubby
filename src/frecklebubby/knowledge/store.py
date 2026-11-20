"""Knowledge store: bundled library and source list in kb_source/kb_chunk, FTS5 BM25 search scoped by family."""

import hashlib
import logging
import re
from functools import lru_cache

import yaml
from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA, get_settings
from ..db import utcnow
from ..models import Family, KbSource
from .ingest import Sections, chunks, front_matter, md_sections

log = logging.getLogger(__name__)

LIBRARY = PACKAGE_DATA / "library"
SOURCES = PACKAGE_DATA / "sources.yaml"
TOP = 6  # spec section 10
SOURCE_FIELDS = ("title", "author", "publisher", "url", "licence", "year")

STOP = set("""a about after again all am an and any are as at be been before being but by can could did do does
doing for from had has have having he her here hers him his how i if in into is it its just me more most my no nor
not now of off on once only or our out over own same she should so some such than that the their them then there
these they this those through to too under until up very was we were what when where which while who whom why will
with would you your yours baby babies child my old normal ok okay get got im ive give""".split())
# Parents' words and the words in the sources differ (US and UK English).
SYNONYMS = {"diaper": "nappy", "diapers": "nappies", "poop": "poo", "pee": "wee", "temp": "temperature",
            "feverish": "fever", "solid": "solids", "weaning": "solids", "crib": "cot", "binky": "dummy",
            "pacifier": "dummy", "tylenol": "paracetamol", "panadol": "paracetamol", "nurse": "breastfeed",
            "nursing": "breastfeeding", "spit": "reflux", "long": "hours"}


def fts_query(question: str) -> str:
    """Safe FTS5 MATCH text: plain words only, each quoted, joined with OR. Parents type anything."""
    words = []
    for w in re.findall(r"[^\W_]+", question.lower()):
        if w in STOP or w.isdigit() or len(w) < 2:
            continue
        for v in (w, SYNONYMS.get(w)):
            if v and v not in words:
                words.append(v)
    return " OR ".join(f'"{w}"' for w in words[:20])


def search(s: Session, family: Family, question: str, limit: int = TOP, web: bool | None = None) -> list[dict]:
    """Best chunks for the question from bundled texts, this family's uploads and (if web lookup is on) cached web
    pages. Each hit: source fields + heading + text + score (lower is better)."""
    ensure_bundled(s)
    q = fts_query(question)
    if not q:
        return []
    web = family.settings.get("web_lookup", False) if web is None else web
    kinds = ("bundled", "upload", "web") if web else ("bundled", "upload")
    rows = s.execute(text(
        "SELECT c.source_id, c.heading, c.text, bm25(kb_chunk, 0.0, 3.0, 1.0) AS score "
        "FROM kb_chunk c JOIN kb_source s ON s.id = c.source_id "
        "WHERE kb_chunk MATCH :q AND (s.family_id IS NULL OR s.family_id = :fid) "
        f"AND s.kind IN ({', '.join(repr(k) for k in kinds)}) ORDER BY score LIMIT :n"
    ), {"q": q, "fid": family.id, "n": limit}).all()
    sources = {src.id: src for src in s.scalars(select(KbSource).where(KbSource.id.in_({r[0] for r in rows})))}
    return [{**source_dict(sources[r[0]]), "heading": r[1], "text": r[2], "score": r[3]} for r in rows]


def chunks_of(s: Session, title: str) -> list[dict]:
    """All passages of one bundled library file (by its title), in file order, in the shape of search hits."""
    ensure_bundled(s)
    src = s.scalar(select(KbSource).where(KbSource.kind == "bundled", KbSource.family_id.is_(None),
                                          KbSource.title == title).limit(1))
    if src is None:
        return []
    rows = s.execute(text("SELECT heading, text FROM kb_chunk WHERE source_id = :id ORDER BY rowid"),
                     {"id": src.id}).all()
    return [{**source_dict(src), "heading": h, "text": t, "score": 0.0} for h, t in rows]


def source_dict(src: KbSource) -> dict:
    return {"id": src.id, "kind": src.kind, **{k: getattr(src, k) for k in SOURCE_FIELDS}}


def add_source(s: Session, family_id: int | None, kind: str, meta: dict, sections: Sections) -> tuple[KbSource, int]:
    """New kb_source row and its chunks. The caller commits."""
    year = meta.get("year")
    src = KbSource(family_id=family_id, kind=kind, title=str(meta.get("title") or "Untitled")[:300],
                   author=meta.get("author"), publisher=meta.get("publisher"), url=meta.get("url"),
                   licence=meta.get("licence"), year=int(year) if str(year or "").isdigit() else None,
                   fetched_at=utcnow())
    s.add(src)
    s.flush()
    pieces = chunks(sections)
    for heading, body in pieces:
        s.execute(text("INSERT INTO kb_chunk (source_id, heading, text) VALUES (:id, :h, :t)"),
                  {"id": src.id, "h": f"{src.title} – {heading}" if heading else src.title, "t": body})
    return src, len(pieces)


def delete_sources(s: Session, ids: list[int]) -> None:
    """Remove sources and their chunks. The caller commits."""
    for i in ids:
        s.execute(text("DELETE FROM kb_chunk WHERE source_id = :id"), {"id": i})
    s.execute(delete(KbSource).where(KbSource.id.in_(ids)))


@lru_cache
def link_list() -> list[dict]:
    """sources.yaml: cite-and-link entries (title, author, publisher, url, topics, summary, kind)."""
    return yaml.safe_load(SOURCES.read_text()) or []


def _bundle_hash() -> str:
    h = hashlib.sha256()
    for path in [*sorted(LIBRARY.glob("*.md")), SOURCES]:
        h.update(path.name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


_done: set[tuple[str, str]] = set()


def ensure_bundled(s: Session) -> None:
    """Load the bundled library and source list once per database; reload when the bundled files change."""
    marker = get_settings().data_dir / "kb_bundle.sha256"
    digest = _bundle_hash()
    key = (str(marker.resolve()), digest)
    if key in _done:
        return
    if not (marker.is_file() and marker.read_text() == digest and s.scalar(
            select(KbSource.id).where(KbSource.kind == "bundled").limit(1))):
        old = list(s.scalars(select(KbSource.id).where(KbSource.family_id.is_(None),
                                                       or_(KbSource.kind == "bundled", KbSource.kind == "link"))))
        delete_sources(s, old)
        n = 0
        for path in sorted(LIBRARY.glob("*.md")):
            meta, body = front_matter(path.read_text())
            n += add_source(s, None, "bundled", meta, md_sections(body))[1]
        for item in link_list():
            add_source(s, None, "link", item, [])
        s.commit()
        marker.write_text(digest)
        log.info("Knowledge library loaded: %d chunks", n)
    _done.add(key)
