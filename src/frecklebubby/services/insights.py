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
from . import Ctx
from .children import age_months, get_child
from .families import wording
from .growth import growth
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

    rule = r["allergic_reaction"]
    hits = [e for e in recent if e.type == "solids" and e.data.get("reaction") == "ALLERGIC"
            and e.started_at >= now - timedelta(hours=rule["window_hours"])]
    if hits:
        foods = ", ".join(f["name"] for f in hits[-1].data.get("foods", []))
        out.append(card("allergic_reaction", rule["severity"], rule["title"], rule["body"], rule["citations"],
                        time=local(hits[-1].started_at), foods=foods))
    return out


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
    if off:
        body += " If you are worried about your child's sleep, talk to your doctor or child health nurse."
    return [card("sleep_total", "attention" if off else "info", "Total sleep this week", body,
                 [r["citation"] for r in recs])]


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
            + base["text"].format(**w) + " Fewer wet " + w["nappies"] + " than usual can be a sign of dehydration. "
            "If you are worried, contact a doctor.")
    return [card("wet_nappies", "info", "Wet {nappies}", body, base["citations"], **w)]


def insights(s: Session, ctx: Ctx, child_id: int, now: datetime | None = None) -> list[dict]:
    child = get_child(s, ctx, child_id)
    now = now or utcnow()
    word = wording(ctx.fam)
    w = {"nappy": word, "nappies": "nappies" if word == "nappy" else "diapers"}
    cards = (red_flags(s, child, ctx.tz, now, word) + _wet_nappy_card(s, ctx, child, now, w)
             + _sleep_card(s, ctx, child, now) + _growth_card(s, ctx, child) + _milestone_cards(s, ctx, child, now))
    order = {"urgent": 0, "attention": 1, "info": 2}
    return sorted(cards, key=lambda c: order[c["severity"]])
