"""Citations from bundled library files (data/library). Rules that state a medical fact name the file and the exact
supporting phrase; tests check that the phrase is in the file."""

from functools import lru_cache

from ..config import PACKAGE_DATA
from ..knowledge.ingest import front_matter


@lru_cache
def library(name: str) -> tuple[dict, str]:
    """(front matter, body) of data/library/<name>.md."""
    return front_matter((PACKAGE_DATA / "library" / f"{name}.md").read_text())


def cite(*names: str) -> list[dict]:
    """Citations in the API shape, numbered from 1."""
    out = []
    for i, name in enumerate(names, 1):
        m = library(name)[0]
        out.append({"n": i, "kind": "bundled", **{k: m[k] for k in ("title", "publisher", "url", "year", "licence")
                                                  if m.get(k) is not None}})
    return out


def cite_files(*names: str, start: int = 1) -> list[dict]:
    """As cite(), numbered from `start` (to add to a card's citations)."""
    return [c | {"n": c["n"] + start - 1} for c in cite(*names)]


def source(name: str) -> dict:
    """{title, publisher, url, year} of a library file (the shape of insight rule citations)."""
    m = library(name)[0]
    return {k: m.get(k) for k in ("title", "publisher", "url", "year")}
