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
from .store import STOP, SYNONYMS, add_source, delete_sources, link_list

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
    """A rough word stem, so that settle, settled and settling are one word. Not for display."""
    for suffix, end in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""), ("e", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)] + end
    return w


# Words that are in most questions and most titles: they do not say what the question is about.
COMMON = {"baby", "babies", "child", "children", "infant", "week", "weeks", "month", "months", "year", "years", "old",
          "day", "days", "normal", "explain", "detail", "give", "many", "step", "steps", "long", "much", "often",
          "need", "help", "guide", "hour", "hours", "newborn", "newborns", "toddler", "toddlers"}


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[^\W_]+", text.lower())
            if w not in STOP and w not in COMMON and len(w) > 2}


def _ranked(question: str, items: list[dict]) -> list[tuple[int, dict]]:
    """(score, item), best first. A word of the question in the title or the topics counts 3, in the summary 1."""
    words = _stems(question) | _stems(" ".join(SYNONYMS.get(w, "") for w in re.findall(r"[^\W_]+", question.lower())))
    scored = []
    for item in items:
        topics = _stems(" ".join(item.get("topics", [])).replace("-", " ").replace("_", " "))
        title = _stems(item["title"])
        score = 3 * len(words & (title | topics)) + len(words & (_stems(item.get("summary", "")) - title - topics))
        if score >= 2:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])  # stable: equal scores keep the order of sources.yaml
    return scored


def _allowed(item: dict) -> bool:
    try:
        check_url(item.get("url", ""))
    except Refused:
        return False
    return True


def candidates(question: str, limit: int = 2) -> list[dict]:
    """sources.yaml web entries whose title, topics or summary share words with the question."""
    items = [i for i in link_list() if i.get("kind") == "web" and i.get("live_fetch") is not False and _allowed(i)]
    return [item for _, item in _ranked(question, items)[:limit]]


def related_links(question: str, limit: int = 3, fits=lambda title: True) -> list[dict]:
    """Trusted pages on the topic of the question, to give as links when the sources do not answer it. These
    include the pages the server may not read (live_fetch false). `fits`: keep a page only when its title fits
    the child's age. A page needs one word of the question in its title or topics."""
    items = [i for i in link_list() if i.get("kind") == "web" and str(i.get("url", "")).startswith("https://")]
    return [item for score, item in _ranked(question, items) if score >= 3 and fits(item["title"])][:limit]


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
        # Read again: two questions at the same moment can fetch one page two times.
        cached = s.scalars(select(KbSource).where(KbSource.kind == "web", KbSource.url == item["url"])).all()
        delete_sources(s, [c.id for c in cached])
        add_source(s, None, "web", {k: item.get(k) for k in ("title", "author", "publisher", "url", "year")}
                   | {"licence": "Linked; not stored in the bundle"}, sections)
        s.commit()
        fresh += 1
    return fresh
