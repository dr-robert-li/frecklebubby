"""Insight cards (no model): red flags from data/red_flags.json (= red_flags.md), milestones to watch, total sleep
against the recommended range, growth percentiles, wet nappies against a cited baseline."""

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..db import utcnow
from ..models import Child, Entry
from . import Ctx, day_bounds, sleep
from .children import age_months, get_child
from .confined import merge, under
from .families import wording
from .growth import growth
from .library import cite, source
from .milestones import catalog
from .reports import daily


@lru_cache
def rules() -> dict:
    return json.loads((PACKAGE_DATA / "red_flags.json").read_text())


@lru_cache
def act_early() -> dict[int, dict]:
    return {r["age_months"]: r for r in json.loads((PACKAGE_DATA / "milestones_act_early.json").read_text())}


def cites(items: list[dict], kind: str = "link") -> list[dict]:
    return [{"n": i, "kind": kind, **{k: v for k, v in c.items() if v is not None}} for i, c in enumerate(items, 1)]


def card(kind: str, severity: str, title: str, body: str, citations: list[dict], **fmt) -> dict:
    return {"kind": kind, "severity": severity, "title": title.format(**fmt), "body": body.format(**fmt),
            "citations": cites(citations)}


def _fmt_c(c: float) -> str:
    return f"{c:g} °C"


def _age(child: Child, at: datetime) -> float:
    return age_months(child, at)


def red_flags(s: Session, child: Child, tz, now: datetime, word: str = "nappy") -> list[dict]:
    """Urgent and attention cards from the child's recent entries."""
    r = {x["id"]: x for x in rules()["rules"]}
    w = {"nappy": word, "nappies": "nappies" if word == "nappy" else "diapers"}
    out: list[dict] = []
    recent = list(s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.started_at >= now - timedelta(days=10),
                                                Entry.started_at <= now + timedelta(minutes=5))
                            .order_by(Entry.started_at)))
    local = lambda dt: dt.astimezone(tz).strftime("%a %H:%M")  # noqa: E731

    # Temperatures
    temps = [(e.started_at, e.data["celsius"]) for e in recent if e.type == "temperature"]
    for rid in ("fever_under_3m", "fever_3_to_6m"):
        rule = r[rid]
        hits = [(t, c) for t, c in temps if t >= now - timedelta(hours=rule["window_hours"]) and c >= rule["min_celsius"]
                and rule.get("min_age_months", 0) <= _age(child, t) < rule["max_age_months"]]
        if hits:
            t, c = max(hits, key=lambda x: x[1])
            out.append(card(rid, rule["severity"], rule["title"], rule["body"], rule["citations"],
                            value=_fmt_c(c), time=local(t)))
    if temps and temps[-1][0] >= now - timedelta(hours=24):
        # Current fever episode: the latest readings that are all at or above 38.
        run = []
        for t, c in reversed(temps):
            if c < 38.0:
                break
            run.append(t)
        if run:
            # The latest reading is under 24 h old, so the fever counts as still going on.
            since, length, age = run[-1], now - run[-1], _age(child, now)
            rule = r["fever_5_days"]
            if length >= timedelta(days=rule["min_days"]) and rule["min_age_months"] <= age < rule["max_age_months"]:
                out.append(card("fever_5_days", rule["severity"], rule["title"], rule["body"], rule["citations"],
                                since=local(since)))
            rule = r["fever_24h_under_2y"]
            if length > timedelta(hours=rule["min_hours"]) and age < rule["max_age_months"]:
                out.append(card("fever_24h_under_2y", rule["severity"], rule["title"], rule["body"],
                                rule["citations"], since=local(since)))
        rule = r["low_temperature"]
        t, c = temps[-1]
        if c < rule["below_celsius"] and _age(child, t) < rule["max_age_months"]:
            out.append(card("low_temperature", rule["severity"], rule["title"], rule["body"], rule["citations"],
                            value=_fmt_c(c), time=local(t)))
    rule = r["fever_above_40_repeated"]
    high = [t for t, c in temps if c > rule["above_celsius"] and t >= now - timedelta(hours=rule["window_hours"])]
    if len(high) >= rule["min_readings"]:
        out.append(card("fever_above_40_repeated", rule["severity"], rule["title"], rule["body"], rule["citations"],
                        count=len(high), since=local(high[0])))

    # Wet nappies: only when the family logs nappies (one in the last 48 h).
    nappies = [e for e in recent if e.type == "nappy"]
    if any(e.started_at >= now - timedelta(hours=48) for e in nappies):
        wet = [e.started_at for e in nappies if e.data.get("mode") in ("pee", "both")]
        if wet:
            hours = (now - wet[-1]).total_seconds() / 3600
            for rid in ("no_wet_nappy_12h", "no_wet_nappy_8h"):
                rule = r[rid]
                if hours >= rule["hours"] and _age(child, now) < rule["max_age_months"]:
                    out.append(card("no_wet_nappy", rule["severity"], rule["title"], rule["body"], rule["citations"],
                                    time=local(wet[-1]), hours=int(hours), **w))
                    break

    # Poo colour
    for rid in ("stool_black", "stool_red", "stool_pale"):
        rule = r[rid]
        hits = [e for e in recent if e.type in ("nappy", "potty") and e.data.get("color") in rule["colors"]
                and e.started_at >= now - timedelta(hours=rule["window_hours"])
                and (e.started_at.date() - child.birthdate).days >= rule.get("min_age_days", 0)]
        if hits:
            out.append(card(rid, rule["severity"], rule["title"], rule["body"], rule["citations"],
                            time=local(hits[-1].started_at)))

    # Pee colour (M9). Rules only where a library file supports them (SUPPORT in tests/test_m9.py).
    for rid in ("pee_red", "dark_pee_newborn"):
        rule = r[rid]
        hits = [e for e in recent if e.type in ("nappy", "potty") and e.data.get("pee_color") in rule["colors"]
                and e.started_at >= now - timedelta(hours=rule["window_hours"])
                and rule.get("min_age_days", 0) <= (e.started_at.date() - child.birthdate).days
                < rule.get("max_age_days", 100_000)]
        if hits:
            out.append(card(rid, rule["severity"], rule["title"], rule["body"], rule["citations"],
                            time=local(hits[-1].started_at), color=PEE_WORDS[hits[-1].data["pee_color"]]))

    rule = r["allergic_reaction"]
    hits = [e for e in recent if e.type == "solids" and e.data.get("reaction") == "ALLERGIC"
            and e.started_at >= now - timedelta(hours=rule["window_hours"])]
    if hits:
        foods = ", ".join(f["name"] for f in hits[-1].data.get("foods", []))
        out.append(card("allergic_reaction", rule["severity"], rule["title"], rule["body"], rule["citations"],
                        time=local(hits[-1].started_at), foods=foods))
    return out


PEE_WORDS = {"pale": "pale", "yellow": "yellow", "dark_yellow": "dark yellow", "orange_pink": "orange or pink",
             "red": "red"}

TEMP_RE = re.compile(r"(\d{2,3}(?:[.,]\d{1,2})?)\s*(°\s*[cf]\b|°|degrees?(?:\s*[cf]\b)?|[cf]\b)?", re.I)


def text_flags(text: str, child: Child, now: datetime) -> list[dict]:
    """Red flags from a temperature the parent wrote in a question ("she has 38.5", "101 F")."""
    keyword = re.search(r"temp|fever|thermometer|°", text, re.I)
    values = []
    for m in TEMP_RE.finditer(text):
        v, unit = float(m.group(1).replace(",", ".")), (m.group(2) or "").lower()
        if not (unit or keyword):
            continue
        if unit.endswith("f") or (not unit.endswith("c") and 93 <= v <= 110):
            v = round((v - 32) * 5 / 9, 1)
        if 30 <= v <= 45:
            values.append(v)
    out: list[dict] = []
    r = {x["id"]: x for x in rules()["rules"]}
    age = _age(child, now)
    for v in values:
        for rid in ("fever_under_3m", "fever_3_to_6m"):
            rule = r[rid]
            if v >= rule["min_celsius"] and rule.get("min_age_months", 0) <= age < rule["max_age_months"]:
                out.append(_from_text(rid, rule, v))
        rule = r["low_temperature"]
        if v < rule["below_celsius"] and age < rule["max_age_months"]:
            out.append(_from_text("low_temperature", rule, v))
    return out[:1]


def _from_text(rid: str, rule: dict, value: float) -> dict:
    rest = rule["body"].split(". ", 1)[1]
    return card(rid, rule["severity"], rule["title"], f"You wrote a temperature of {_fmt_c(value)}. {rest}",
                rule["citations"])


def _milestone_cards(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    items = catalog()
    if not items:
        return []
    age = _age(child, now.astimezone(ctx.tz))
    achieved = {e.data.get("key") for e in s.scalars(select(Entry).where(Entry.child_id == child.id,
                                                                         Entry.type == "milestone"))}
    bands = sorted({i["age_months"] for i in items})
    current = max((b for b in bands if b <= age), default=None)
    upcoming = min((b for b in bands if b > age), default=None)
    out = []
    for band, title in ((current, "Milestones by {m} months"), (upcoming, "Coming up: milestones by {m} months")):
        if band is None:
            continue
        open_items = [i for i in items if i["age_months"] == band and i["key"] not in achieved]
        if not open_items:
            continue
        listed = "; ".join(i["text"] for i in open_items[:4]) + (f" (and {len(open_items) - 4} more)"
                                                                if len(open_items) > 4 else "")
        body = f"Not yet marked: {listed}. Mark them in the milestones checklist when you see them."
        cite = [open_items[0]["source"]]
        if band == current and band in act_early():
            body += " " + act_early()[band]["text"]
            cite = [act_early()[band]["source"]]
        out.append(card("milestones", "info", title, body, cite, m=band))
    return out


def _sleep_card(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    today = now.astimezone(ctx.tz).date()
    rep = daily(s, ctx, child.id, today - timedelta(days=7), today - timedelta(days=1), now)
    days = [d for d in rep["days"] if d.sleep.total_seconds > 0]
    recs = rep["sleep_recommendations"]
    if len(days) < 3 or not recs:
        return []
    avg_h = sum(d.sleep.total_seconds for d in days) / len(days) / 3600
    ranges = "; ".join(f"{r['min_hours']:g} to {r['max_hours']:g} hours ({r['citation']['publisher'].split(' /')[0]} "
                       f"{r['citation']['year']})" for r in recs)
    low, high = min(r["min_hours"] for r in recs), max(r["max_hours"] for r in recs)
    off = avg_h < low or avg_h > high
    body = (f"Average logged sleep over {len(days)} days: {int(avg_h)} h {round(avg_h % 1 * 60)} min a day. "
            f"Recommended for this age: {ranges}. Only logged sleep counts.")
    cites_ = [r["citation"] for r in recs]
    cohort = _cohort_total(child, now, avg_h * 60)
    if cohort:
        body += " " + cohort
        cites_.append(sleep.norms()["source"])
    if off:
        body += " If you are worried about your child's sleep, talk to your doctor or child health nurse."
    return [card("sleep_total", "attention" if off else "info", "Total sleep this week", body, cites_)]


# --- sleep model cards (M7): optional norms file from training/sleep ---------------------------------------------------

def _months(days: float) -> str:
    return f"{round(days / 30.4375 * 2) / 2:g}"


def _cohort_total(child: Child, now: datetime, avg_minutes: float) -> str:
    """Where the child's average total sleep falls among babies of the same age in the research dataset."""
    n = sleep.norms()
    b = sleep.band(n, (now.date() - child.birthdate).days) if n else None
    q = n["bands"][b].get("total_24h") if b is not None else None
    if not q:
        return ""
    where = ("below most" if avg_minutes < q[0] else "a little below the middle half" if avg_minutes < q[1]
             else "within the middle half" if avg_minutes <= q[3] else "a little above the middle half"
             if avg_minutes <= q[4] else "above most")
    return (f"Babies this age in a research dataset of app users logged {q[1] / 60:.1f} to {q[3] / 60:.1f} hours a "
            f"day (middle half). This average is {where} of them.")


def sleep_model_cards(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    """Current nap stage and, when a nap change is common at this age, an outlook card."""
    n = sleep.norms()
    if n is None:
        return []
    age = (now.astimezone(ctx.tz).date() - child.birthdate).days
    b = sleep.band(n, age)
    st = sleep.stage(s, child, ctx.tz, now, n)
    if b is None or st is None:
        return []
    k = st["naps"]
    naps = lambda x: f"{x} nap" + ("" if x == 1 else "s")  # noqa: E731
    share = (n["bands"][b].get("naps_share") or {}).get(str(min(k, 4)))
    body = f"In the last {st['days']} logged days, your child had {naps(k)} on {round(st['share'] * 100)}% of days."
    if share is not None:
        body += (f" Among babies this age in a research dataset of app users, {round(share * 100)}% of days had "
                 f"{naps(k) if k < 4 else '4 or more naps'}.")
    out = [card("sleep_stage", "info", "Mostly {naps} a day", body, [n["source"]], naps=naps(k))]
    t = n.get("transitions", {}).get(f"{k}to{k - 1}", {}).get("age_days")
    if t and t[1] - 28 <= age <= t[3]:
        dur = n["transitions"][f"{k}to{k - 1}"].get("duration_days")
        body = (f"Many babies move from {naps(k)} to {naps(k - 1)} between about {_months(t[1])} and "
                f"{_months(t[3])} months. This is the middle half of babies in a research dataset of app users.")
        if dur:
            body += f" For half of them the change took about {max(1, round(dur[2] / 7))} weeks, with mixed days."
        body += " Every baby is different."
        out.append(card("sleep_outlook", "info", "Nap change ahead: {a} to {b}", body, [n["source"]],
                        a=naps(k), b=naps(k - 1)))
    return out


def _growth_card(s: Session, ctx: Ctx, child: Child) -> list[dict]:
    from ..knowledge.store import link_list

    g = growth(s, ctx, child.id)
    last = next((p for p in reversed(g["points"]) if any(p.get(f"{m}_percentile") is not None
                                                         for m in ("weight", "height", "head"))), None)
    if last is None:
        return []
    parts = [f"{name} {last[f]:g} {unit} is on the {round(last[f'{m}_percentile'])}th percentile"
             for m, f, name, unit in (("weight", "weight_kg", "weight", "kg"), ("height", "height_cm", "length", "cm"),
                                      ("head", "head_cm", "head", "cm"))
             if last.get(f"{m}_percentile") is not None]
    who = next((i for i in link_list() if i.get("id") == "who-growth-standards"), None)
    cite = [{k: who[k] for k in ("title", "publisher", "url", "year")}] if who else []
    body = ("Latest measurement: " + "; ".join(parts) + " of the WHO growth standards. A single point says little; "
            "the line over time matters more. Ask your child health nurse or doctor if you are worried.")
    return [card("growth", "info", "Growth", body, cite)]


def _wet_nappy_card(s: Session, ctx: Ctx, child: Child, now: datetime, w: dict) -> list[dict]:
    base = rules()["wet_nappy_baseline"]
    age_days = (now.astimezone(ctx.tz).date() - child.birthdate).days
    if not (base["min_age_days"] <= age_days and _age(child, now) < base["max_age_months"]):
        return []
    today = now.astimezone(ctx.tz).date()
    rep = daily(s, ctx, child.id, today - timedelta(days=base["days"]), today - timedelta(days=1), now)
    days = rep["days"]
    if not all(d.nappies.wet + d.nappies.dirty for d in days):
        return []  # not logged every day
    avg = sum(d.nappies.wet for d in days) / len(days)
    if avg >= base["per_day"]:
        return []
    body = (f"Average logged: {avg:.1f} wet {w['nappies']} a day over the last {len(days)} days. "
            + base["text"].format(**w) + " Fewer wet " + w["nappies"] + " than usual can be a sign of dehydration. ")
    cites_ = list(base["citations"])
    # Dark pee (M9): "dark yellow, strong-smelling pee" and "fewer wet nappies than usual" (nhs-dehydration).
    lo = day_bounds(today - timedelta(days=base["days"]), ctx.tz)[0]
    dark = s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.type.in_(("nappy", "potty")),
                                         Entry.started_at >= lo, Entry.started_at <= now))
    dark = [e for e in dark if e.data.get("pee_color") == "dark_yellow"]
    if dark:
        body += (f"Dark yellow pee was also logged {len(dark)} {'time' if len(dark) == 1 else 'times'}. The NHS lists "
                 f"dark yellow, strong-smelling pee and fewer wet {w['nappies']} than usual as signs of dehydration. ")
        cites_.append(source("nhs-dehydration"))
    body += "If you are worried, contact a doctor."
    return [card("wet_nappies", "attention" if dark else "info", "Wet {nappies}", body, cites_, **w)]


def _bundled(kind: str, severity: str, title: str, body: str, *names: str) -> dict:
    """An insight card cited from library files."""
    return {"kind": kind, "severity": severity, "title": title, "body": body, "citations": cite(*names)}


def _rash_card(s: Session, ctx: Ctx, child: Child, now: datetime, w: dict) -> list[dict]:
    """Rash in the last 24 h: NHS care advice and an app tip. Rash on 3 or more of the last 7 days: when to get help."""
    today = now.astimezone(ctx.tz).date()
    rows = list(s.scalars(select(Entry).where(
        Entry.child_id == child.id, Entry.type.in_(("nappy", "potty")),
        Entry.started_at >= day_bounds(today - timedelta(days=6), ctx.tz)[0], Entry.started_at <= now)
        .order_by(Entry.started_at)))
    rash = [e for e in rows if e.data.get("rash")]
    days = {e.started_at.astimezone(ctx.tz).date() for e in rash}
    recent = rash and rash[-1].started_at >= now - timedelta(hours=24)
    if not recent and len(days) < 3:
        return []
    n, ns, name = w["nappy"], w["nappies"], child.name
    names = ["nhs-nappy-rash"]
    body = ""
    if recent:
        body = (f"A {n} rash was logged at {rash[-1].started_at.astimezone(ctx.tz):%a %H:%M}. The NHS says to leave "
                f"{ns} off when possible, and to change wet or dirty {ns} as soon as possible. A {n} change is a good "
                f"time for this if {name} is calm.")
        if under(child, today, 12):
            body += " It is also a good time for a little tummy time."
            names.append("who-under-5-activity-sleep")
        body += " "
    air = sum(e.data.get("air_minutes", 0) for e in rows)
    if air:
        body += f"Time with the {n} off logged this week: {air} min. "
    if len(days) >= 3:
        body += (f"A {n} rash was logged on {len(days)} of the last 7 days. The NHS says to see a health visitor or "
                 "GP if the rash does not go away, gets worse or spreads, if your baby has a high temperature, or if "
                 "your baby seems very uncomfortable.")
    return [_bundled("nappy_rash", "attention" if len(days) >= 3 else "info", f"{n.capitalize()} rash",
                     body.strip(), *names)]


def _confined_card(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    """A continuous confined period over the limit for the age in the last 7 days."""
    today = now.astimezone(ctx.tz).date()
    if not under(child, today, 60):
        return []
    rows = s.execute(select(Entry.started_at, Entry.ended_at).where(
        Entry.child_id == child.id, Entry.type == "confined", Entry.ended_at.is_not(None),
        Entry.started_at >= now - timedelta(days=7), Entry.started_at <= now)).all()
    over = [(a, b) for a, b in merge([(a, b) for a, b in rows]) if b - a > timedelta(hours=1)]
    if not over:
        return []
    longest = max(b - a for a, b in over)
    warn = under(child, today, 12) and longest > timedelta(hours=2)
    m = int(longest.total_seconds() // 60)
    days = len({a.astimezone(ctx.tz).date() for a, _ in over})
    body = (f"On {days} of the last 7 days, {child.name} was in a car seat, pram or other seat for more than 1 hour "
            f"without a break (longest: {m // 60} h {m % 60} min). WHO advises that children under 5 are not "
            "restrained for more than 1 hour at a time.")
    names = ["who-under-5-activity-sleep"]
    if warn:
        body += (" For a car seat, HealthyChildren.org (AAP) says to take a break every 2 to 3 hours on a day "
                 "trip.")
        names.append("car-seat-time")
    return [_bundled("confined", "attention" if warn else "info", "Time in a seat or pram", body, *names)]


def insights(s: Session, ctx: Ctx, child_id: int, now: datetime | None = None) -> list[dict]:
    child = get_child(s, ctx, child_id)
    now = now or utcnow()
    word = wording(ctx.fam)
    w = {"nappy": word, "nappies": "nappies" if word == "nappy" else "diapers"}
    cards = (red_flags(s, child, ctx.tz, now, word) + _wet_nappy_card(s, ctx, child, now, w)
             + _rash_card(s, ctx, child, now, w) + _confined_card(s, ctx, child, now)
             + _sleep_card(s, ctx, child, now) + sleep_model_cards(s, ctx, child, now) + _growth_card(s, ctx, child) + _milestone_cards(s, ctx, child, now))
    order = {"urgent": 0, "attention": 1, "info": 2}
    return sorted(cards, key=lambda c: order[c["severity"]])
