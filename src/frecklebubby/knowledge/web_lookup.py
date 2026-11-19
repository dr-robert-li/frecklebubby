"""Live lookup of approved medical pages (spec section 10). SSRF-safe: https only, allow-listed hosts, no redirect to
another host, 2 MB and 10 s limits. Pages are cached 7 days as kb_source kind 'web' (shared: they are public)."""

import logging
import re
import time
from datetime import timedelta
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..db import utcnow
from ..models import KbSource
from .ingest import html_sections
from .store import STOP, add_source, delete_sources, link_list

log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10.0
CACHE = timedelta(days=7)
MAX_REDIRECTS = 3
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests put a MockTransport here


class Refused(Exception):
    pass


def allowlist() -> set[str]:
    path = PACKAGE_DATA / "web_allowlist.txt"
    lines = path.read_text().splitlines() if path.is_file() else []
    return {ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#")}


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Refused("only https")
    if (parts.hostname or "").lower() not in allowlist() or parts.port not in (None, 443) or parts.username:
        raise Refused("host not on the allow list")


def _stem(w: str) -> str:
    return w[:-3] + "y" if w.endswith("ies") else w[:-1] if w.endswith("s") and len(w) > 3 else w


def candidates(question: str, limit: int = 2) -> list[dict]:
    """sources.yaml web entries whose topics, title or summary share words with the question."""
    words = {_stem(w) for w in re.findall(r"[^\W_]+", question.lower()) if w not in STOP and len(w) > 2}
    scored = []
    for item in link_list():
        if item.get("kind") != "web" or item.get("live_fetch") is False:
            continue
        try:
            check_url(item.get("url", ""))
        except Refused:
            continue
        topics = {_stem(t) for topic in item.get("topics", []) for t in re.split(r"[-_ ]", topic.lower())}
        about = {_stem(w) for w in re.findall(r"[^\W_]+", f"{item['title']} {item.get('summary', '')}".lower())}
        score = 2 * len(words & topics) + len(words & about)
        if score >= 2:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]


async def fetch(url: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Text of an allowed page. Raises Refused or httpx errors."""
    deadline = time.monotonic() + TIMEOUT
    host = urlsplit(url).hostname
    async with httpx.AsyncClient(transport=transport or TRANSPORT, follow_redirects=False, timeout=TIMEOUT,
                                 headers={"User-Agent": "Frecklebubby/0.1 (+self-hosted baby tracker)"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    if urlsplit(url).hostname != host:
                        raise Refused("redirect to another host")
                    continue
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if not ctype.startswith(("text/html", "text/plain", "application/xhtml")):
                    raise Refused("not a web page")
                if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                    raise Refused("page too large")
                body = b""
                async for part in r.aiter_bytes():
                    body += part
                    if len(body) > MAX_BYTES:
                        raise Refused("page too large")
                    if time.monotonic() > deadline:
                        raise Refused("too slow")
                return body.decode(r.encoding or "utf-8", "replace")
        raise Refused("too many redirects")


async def lookup(s: Session, question: str, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Fetch (or reuse from cache) the best approved pages for the question. Returns the number of fresh pages.
    Fails softly: a page that cannot be fetched is skipped."""
    fresh = 0
    for item in candidates(question):
        cached = s.scalars(select(KbSource).where(KbSource.kind == "web", KbSource.url == item["url"])).all()
        if any(c.fetched_at and c.fetched_at > utcnow() - CACHE for c in cached):
            continue
        try:
            sections = html_sections(await fetch(item["url"], transport))
        except (Refused, httpx.HTTPError) as err:
            log.warning("Web lookup skipped %s: %s", urlsplit(item["url"]).hostname, err or type(err).__name__)
            continue
        if not sections:
            continue
        delete_sources(s, [c.id for c in cached])
        add_source(s, None, "web", {k: item.get(k) for k in ("title", "author", "publisher", "url", "year")}
                   | {"licence": "Linked; not stored in the bundle"}, sections)
        s.commit()
        fresh += 1
    return fresh
