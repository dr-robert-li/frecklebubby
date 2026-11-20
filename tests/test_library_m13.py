"""M13 development data: each item is supported by an exact phrase of a bundled library file."""
import json
from pathlib import Path

import pytest

from frecklebubby.knowledge.ingest import front_matter

DATA = Path(__file__).parents[1] / "src" / "frecklebubby" / "data"
LIB = DATA / "library"
ITEMS = json.loads((DATA / "development.json").read_text(encoding="utf-8"))
FIELDS = ("title", "publisher", "url", "licence", "year", "retrieved")


def text(name):
    return (LIB / f"{name}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("item", ITEMS, ids=[i["key"] for i in ITEMS])
def test_item(item):
    assert item["domain"] in ("physiological", "behavioural", "activity")
    assert item["phrase"] in text(item["library"])
    if item.get("tip"):
        assert item["tip"] in text(item["tip_library"])
    days = [item[k] for k in ("from_days", "typical_days", "to_days") if item[k] is not None]
    assert days and days == sorted(days) and days[0] >= 0
    assert "should" not in item["text"].lower()
    assert {"title", "publisher", "url"} <= item["source"].keys()


def test_keys_unique():
    keys = [i["key"] for i in ITEMS]
    assert len(keys) == len(set(keys))


def test_corrected_age_phrases():
    body = text("corrected-age-premature")
    assert "until they are 2 years old." in body
    assert "to track development until 2 years of age" in body


@pytest.mark.parametrize("path", sorted(LIB.glob("*.md")), ids=lambda p: p.stem)
def test_front_matter(path):
    meta, body = front_matter(path.read_text(encoding="utf-8"))
    assert all(meta.get(f) for f in FIELDS), [f for f in FIELDS if not meta.get(f)]
    assert body.strip()
