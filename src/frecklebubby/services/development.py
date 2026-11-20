"""Development guidance (M13b): development items "around now", CDC tips by age band, the age-band notification and
the age fit of library passages. No model.

Ages: the corrected age (from the due date) until 2 years when the child has a due date (children.dev_age_days).
Every item of data/development.json names a library file and an exact phrase; tests/test_library_m13.py checks it.
The display windows below are the app's choice of when to show an item, not medical facts.
"""

import json
import logging
import math
import re
from datetime import datetime
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..models import Child, Entry, Family
from . import zone
from .children import corrected, dev_age_days, is_night
from .library import library
from .milestones import catalog
from .notifications import notify

log = logging.getLogger(__name__)

AROUND = 30  # days on each side of a "typical" age ("around 6 months")
SOON = 91  # days before a "by X" age and after a "from X" age
PER_CARD = 4
GRACE_DAYS = 14  # the band notification is sent only this long after the child reaches the band
DOMAINS = {"activity": "Moving and playing around now", "behavioural": "Behaviour around now",
           "physiological": "Body and health checks around now"}
CORRECTED_NOTE = ("Ages here are counted from the due date (corrected age), as the NHS and the AAP advise until "
                  "2 years.")
SUPPORT = {"corrected": ("corrected-age-premature", "until they are 2 years old.")}
TIPS_FILE = {12: "cdc-tips-1-year", 24: "cdc-tips-2-years", 36: "cdc-tips-3-years", 48: "cdc-tips-4-years",
             60: "cdc-tips-5-years"}


@lru_cache
def items() -> list[dict]:
    return json.loads((PACKAGE_DATA / "development.json").read_text())


def window(item: dict) -> tuple[int, int]:
    """(first day, last day) of age in which the item is shown."""
    a, t, b = item["from_days"], item["typical_days"], item["to_days"]
    if a is not None and b is not None:
        return a, b
    if t is not None:
        return max(0, t - AROUND), t + AROUND
    if b is not None:
        return max(0, b - SOON), b
    return a, a + SOON


def around(age_days: int) -> list[dict]:
    """Items whose window holds this age, the narrowest window first."""
    hits = [i for i in items() if window(i)[0] <= age_days <= window(i)[1]]
    return sorted(hits, key=lambda i: window(i)[1] - window(i)[0])


def bands() -> list[int]:
    return sorted({i["age_months"] for i in catalog()})


def band_of(age_months: float) -> int | None:
    """The CDC checklist band for this age: the last band reached (the first band before it)."""
    bs = bands()
    return max((b for b in bs if b <= age_months), default=bs[0] if bs else None)


def next_band(band: int | None) -> int | None:
    return min((b for b in bands() if band is None or b > band), default=None)


def tips_file(band: int) -> str:
    return TIPS_FILE.get(band, f"cdc-tips-{band}-months")


def tips(band: int, n: int = 2) -> list[str]:
    """The first n CDC tips of the band's "how to help" part (exact CDC sentences)."""
    try:
        body = library(tips_file(band))[1]
    except FileNotFoundError:
        return []
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ")][:n]


def _source(item: dict) -> str:
    return item["source"]["publisher"].split(" (")[0]


def cards(child: Child, local: datetime) -> list[dict]:
    """Insight cards: one per domain with the items "around now", each in the source's words and naming its source.
    Sources that disagree stay separate items, each with its own source."""
    from .insights import card  # insights imports this module

    age = dev_age_days(child, local.date())
    out = []
    for domain, title in DOMAINS.items():
        hits = [i for i in around(age) if i["domain"] == domain][:PER_CARD]
        if not hits:
            continue
        body = "\n".join(f"{_source(i)}: {i['text']}" for i in hits)  # one line per item, its source first
        if corrected(child, local.date()):
            body += "\n" + CORRECTED_NOTE
        cites = list({i["source"]["url"]: i["source"] for i in hits}.values())
        out.append(card(f"development_{domain}", "info", title, body, cites))
    return out


def context_lines(s: Session, child: Child, local: datetime, marks: dict[str, int] | None = None) -> list[str]:
    """For the assistant: milestones marked and not yet marked in the current and next band, and the development
    items around now. `marks`: library file → source number; an item with no number says it is not to be cited."""
    age = dev_age_days(child, local.date())
    months = age / 30.4375
    lines = []
    if corrected(child, local.date()):
        lines.append(f"Born early: development uses the corrected age, {months:.1f} months (from the due date).")
    done = {e.data.get("key") for e in s.scalars(select(Entry).where(Entry.child_id == child.id,
                                                                     Entry.type == "milestone"))}
    band = band_of(months)
    for b in (band, next_band(band)):
        if b is None:
            continue
        rows = [i for i in catalog() if i["age_months"] == b]
        marked = [i["text"] for i in rows if i["key"] in done]
        open_ = [i["text"] for i in rows if i["key"] not in done]
        lines.append(f"CDC milestones by {b} months: marked {len(marked)} of {len(rows)}"
                     + (f" ({'; '.join(marked[:6])})" if marked else "")
                     + (f". Not yet marked: {'; '.join(open_[:8])}" if open_ else "") + ".")
    dev = around(age)[:8]
    if dev:
        marks = marks or {}
        lines.append("Development around this age: " + " ".join(
            f"{i['text']} [{marks[i['library']]}]" if i["library"] in marks
            else f"{i['text']} ({_source(i)}; not a numbered source)" for i in dev))
    return lines


# --- age fit of library passages ----------------------------------------------------------------------------------

_UNIT = {"week": 12 / 52, "month": 1, "year": 12}
_N = r"(\d+)\s+(week|month|year)s?"


def _m(n: str, unit: str) -> float:
    return int(n) * _UNIT[unit]


def fits(heading: str, age_months: float) -> bool:
    """Is a library passage with this heading for a child of this age? Headings name their ages ("4 months: ...",
    "6 to 12 months: ...", "From 18 months: ...", "Under 2 years ...", "Any age: ..."); a heading with no age fits all.
    A range fits from 3 months before it starts. A CDC tips heading fits only the child's own checklist band."""
    h = heading.rsplit(" – ", 1)[-1].lower()
    head = h.split(":")[0]
    a = age_months
    tests: list[bool] = []
    if "any age" in head or "from birth" in head:
        return True
    for lo, lu, hi, hu in re.findall(rf"(\d+)\s+(week|month|year)s?\s+to\s+{_N}", head):
        tests.append(_m(lo, lu) - 3 <= a < _m(hi, hu) + (12 if hu == "year" else 1))
    rest = re.sub(rf"(\d+)\s+(week|month|year)s?\s+to\s+{_N}", "", head)
    for lo, hi, unit in re.findall(r"(\d+)\s+to\s+(\d+)\s+(week|month|year)s?", rest):
        tests.append(_m(lo, unit) - 3 <= a < _m(hi, unit) + (12 if unit == "year" else 1))
    for lo, hi in re.findall(r"aged\s+(\d+)\s+to\s+(\d+)", head):
        tests.append(int(lo) * 12 - 3 <= a < (int(hi) + 1) * 12)
    for n, unit in re.findall(rf"(?:birth|newborn|up)\s+to\s+{_N}", head):
        tests.append(a < _m(n, unit) + (12 if unit == "year" else 1))
    for n, unit in re.findall(rf"\bfrom\s+{_N}", head):
        tests.append(a >= _m(n, unit) - 3)
    for n, unit in re.findall(rf"\bunder\s+{_N}", head):
        tests.append(a < _m(n, unit))
    if not tests:
        if single := re.match(_N, head):
            n = _m(*single.groups())
            if "cdc" in h:
                return band_of(a) == n
            return n - 3 <= a < n + 12
        if head.startswith("newborn"):
            return a < 3
        return True
    return any(tests)


def age_fit(hits: list[dict], age_months: float, limit: int) -> list[dict]:
    return [h for h in hits if fits(h["heading"], age_months)][:limit]


# --- the age-band notification --------------------------------------------------------------------------------------


def look_for(band: int, done: set[str]) -> list[str]:
    """2 or 3 milestones of the band to look for: one per domain, not yet marked."""
    picked, seen = [], set()
    for i in catalog():
        if i["age_months"] == band and i["key"] not in done and i["domain"] not in seen:
            picked.append(i["text"])
            seen.add(i["domain"])
    return picked[:3]


def band_message(child: Child, band: int, done: set[str]) -> tuple[str, str]:
    """Title and text: 2 or 3 things to look for."""
    picked = look_for(band, done)
    body = (f"{child.name} is now in the {band}-month band of the CDC milestones checklist. Things to look for: "
            + "; ".join(picked) + ". Mark them in the milestones checklist when you see them. Every child grows at "
            "their own pace.")
    return f"{child.name}: milestones by {band} months", body


def tick(s: Session, now: datetime) -> int:
    """One notification when a child reaches a new band (dedupe per child and band), daytime only, when the family
    has not turned it off (family settings `milestone_alerts`). Called by the reminder tick."""
    fired = 0
    rows = s.execute(select(Child, Family).join(Family, Child.family_id == Family.id)
                     .where(Child.archived.is_(False))).all()
    for child, family in rows:
        if family.settings.get("milestone_alerts") is False:
            continue
        try:
            local = now.astimezone(zone(family.timezone))
            if is_night(child, local, early_minutes=0):
                continue
            age = dev_age_days(child, local.date())
            band = max((b for b in bands() if b * 30.4375 <= age), default=None)
            if band is None or age - math.ceil(band * 30.4375) > GRACE_DAYS:
                continue
            key = f"milestones:band:{child.id}:{band}"
            done = {e.data.get("key") for e in s.scalars(select(Entry).where(Entry.child_id == child.id,
                                                                             Entry.type == "milestone"))}
            title, body = band_message(child, band, done)
            if notify(s, family.id, child.id, "milestones:band", title, body, key):
                fired += 1
        except Exception:
            s.rollback()
            log.exception("Milestone band check for child %s failed", child.id)
    return fired
