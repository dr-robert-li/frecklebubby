"""Natural-language logging: a parent's note → proposals (one model call, strict JSON schema) → commit.

The model copies what the parent said (clock times, "minutes ago", durations, amounts with units); the server does
all time arithmetic and unit conversion, then checks each proposal with the same validators as the REST API.
"""

import dataclasses
import re
from datetime import datetime, time, timedelta
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Child, Entry
from ..schemas import (
    ActivityKind,
    ConfinedDevice,
    EntryIn,
    EntryOut,
    EntryType,
    Side,
    TimerAction,
    TimerBody,
    TimerOut,
    TimerType,
)
from ..services import Ctx, Invalid, ServiceError, plain_errors, to_utc
from ..services.children import age_months, get_child
from ..services.entries import FUTURE_LIMIT, create_entry, validate
from ..services.families import wording
from ..services.timers import act, find, list_timers, timer_out
from . import llm

OZ_ML, LB_KG, IN_CM = 29.5735, 0.45359237, 2.54

# --- model output schema ------------------------------------------------------------------------------------------

# Times and durations are the parent's own words; the server reads them (parse_time, parse_duration).
TIME = {"type": "string", "maxLength": 40}
_NUM = {"type": "number", "minimum": 0}
_STR = {"type": "string", "maxLength": 100}


def _ev(type_: str, props: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["type", *required],
            "properties": {"type": {"const": type_}, **props}}


def _enum(*values: str) -> dict:
    return {"enum": list(values)}


_SPAN = {"start": TIME, "end": TIME, "duration": TIME}
ACTIVITY_KINDS = get_args(ActivityKind)
DEVICES = ("car_seat", "bouncer", "swing", "pram", "carrier", "high_chair", "other")
EVENTS = [
    _ev("sleep", _SPAN, []),
    _ev("nursing", {**_SPAN, "left_minutes": _NUM, "right_minutes": _NUM, "last_side": _enum("left", "right")}, []),
    _ev("bottle", {"at": TIME, "amount": _NUM, "unit": _enum("ml", "oz"),
                   "milk_type": _enum("Breast Milk", "Formula", "Cow Milk", "Goat Milk", "Soy Milk", "Other")},
        ["at", "amount", "unit"]),
    _ev("solids", {"at": TIME, "foods": {"type": "array", "items": _STR, "minItems": 1, "maxItems": 10},
                   "reaction": _enum("LOVED", "MEH", "HATED", "ALLERGIC")}, ["at", "foods"]),
    _ev("nappy", {"at": TIME, "mode": _enum("pee", "poo", "both", "dry"),
                  "color": _enum("yellow", "brown", "black", "green", "red", "gray"),
                  "consistency": _enum("solid", "loose", "runny", "mucousy", "hard", "pebbles", "diarrhea"),
                  "rash": {"type": "boolean"}, "air_minutes": _NUM,
                  "pee_color": _enum("pale", "yellow", "dark_yellow", "orange_pink", "red"),
                  "pee_look": _enum("clear", "cloudy"), "pee_smell": {"type": "boolean"},
                  "pee_amount": _enum("little", "medium", "big"), "poo_amount": _enum("little", "medium", "big")},
        ["at", "mode"]),
    _ev("potty", {"at": TIME, "mode": _enum("pee", "poo", "both", "dry"),
                  "result": _enum("satButDry", "wentPotty", "accident")}, ["at", "mode", "result"]),
    _ev("pump", {"at": TIME, "left_amount": _NUM, "right_amount": _NUM, "total_amount": _NUM,
                 "unit": _enum("ml", "oz")}, ["at", "unit"]),
    _ev("growth", {"at": TIME, "weight": _NUM, "weight_unit": _enum("kg", "g", "lb"), "length": _NUM,
                   "head": _NUM, "length_unit": _enum("cm", "in")}, ["at"]),
    _ev("temperature", {"at": TIME, "value": _NUM, "unit": _enum("C", "F")}, ["at", "value", "unit"]),
    _ev("medicine", {"at": TIME, "name": _STR, "amount": _NUM, "unit": _enum("ml", "oz", "tsp", "drops", "mg")},
        ["at", "name"]),
    _ev("activity", {**_SPAN, "kind": _enum(*ACTIVITY_KINDS)}, ["kind"]),
    _ev("milestone", {"at": TIME, "title": _STR}, ["at", "title"]),
    _ev("note", {"at": TIME, "text": {"type": "string", "maxLength": 500}}, ["at", "text"]),
    _ev("cry", {**_SPAN, "soothed_by": _STR}, []),
    _ev("confined", {**_SPAN, "device": _enum(*DEVICES)}, ["device"]),
    _ev("timer", {"timer": _enum("sleep", "nursing", "pump", "activity", "confined"),
                  "action": _enum("start", "pause", "resume", "switch", "cancel", "complete"),
                  "at": TIME, "side": _enum("left", "right"),
                  "kind": _enum(*ACTIVITY_KINDS),
                  "device": _enum(*DEVICES)}, ["timer", "action"]),
]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["events"],
          "properties": {"events": {"type": "array", "maxItems": 12, "items": {"anyOf": EVENTS}},
                         "unclear": {"type": "boolean"}}}

SYSTEM = """You turn a parent's note about their baby into log events. Answer with JSON only.

Rules:
- Make ONE event for EACH thing that happened. Three nappies are three events. Do not invent events. A note with no baby-care event gives {"events": []}.
- Times: copy the parent's own words for the time of each event into "at", for example "half past 12", "quarter to 2", "7:30 last night", "20 minutes ago", "at 9". Write "now" when the note gives no time or says "just now". Do NOT calculate or change times.
- Sleep, nursing, activity, cry and confined have "start", "end" and "duration" instead of "at". Copy the words for each one the note gives, for example {"start": "9", "end": "10:15"} or {"end": "10 minutes ago", "duration": "45 minutes"}. Leave out the ones the note does not give.
- Copy amounts and units as written. Do NOT convert units.
- Use a "timer" event only for something that goes on now: "fell asleep", "went down", "is asleep" with no end → timer sleep start. "woke up", "is awake", "she's up" with no start, while a sleep timer runs → timer sleep complete. "started feeding on the left" → timer nursing start, side left. "started tummy time" → timer activity start, kind tummyTime; "stop tummy time" → timer activity complete, kind tummyTime. Same for pumping, the other activities and confined time. Several activity timers can run at once: always give the kind of an activity timer.

Words:
- wet, wee, pee = "pee". dirty, pooey, poo, poop, soiled, number two = "poo". Pee AND poo in the same nappy ("wet and dirty", "poo and pee") = "both". dry = "dry".
- ONE nappy change is ONE "nappy" event, also when it had pee and poo, details and air time. Never repeat an event.
- breastfed, nursed, fed on the left or right side, on the boob = "nursing" (never a bottle). Minutes on each side go to left_minutes and right_minutes; last_side is the side fed last.
- formula in a bottle = bottle "Formula". expressed milk, EBM, breast milk in a bottle = bottle "Breast Milk".
- pumped or expressed (the parent) = ONE "pump" event; amounts from each side go to left_amount and right_amount.
- temp, temperature, a fever reading = "temperature". paracetamol, Panadol, Calpol, ibuprofen, Nurofen, vitamin D, drops = "medicine".
- weighed, weight, length, height, head = "growth".
- ate, tried, had food, puree = "solids". loved it = LOVED, ok or so-so = MEH, hated it or spat it out = HATED, rash, hives or swelling after food = ALLERGIC.
- bath, gave a bath, had a bath, bathed = "activity" kind "bath".
- tummy time, on the tummy = "activity" kind "tummyTime". story, reading, book = "storyTime". TV, screen, tablet = "screenTime". skin to skin, cuddles on the chest = "skinToSkin". brushed teeth = "brushTeeth".
- play, playing, floor play = "activity" kind "indoorPlay". playing outside, in the garden, at the park = "outdoorPlay". Play with some tummy time is two events: the play and the tummy time.
- in the car seat, pram, stroller, buggy, bouncer, swing, carrier, high chair = "confined" with that device (stroller and buggy = "pram").
- nappy details: rash = rash true. Nappy off, air time, left it off for N minutes = air_minutes. dark pee, dark wee = pee "dark_yellow"; pale, yellow, orange or pink, red pee = pee_color; cloudy pee = pee_look "cloudy"; smelly or strong-smelling pee = pee_smell true.
- nappy amounts: "big wee", "small poo", "medium poo" give pee_amount and poo_amount. small, little, tiny, a bit = "little". medium, normal = "medium". big, large, huge, a lot, full = "big".
- "color" and "consistency" describe the poo. A yellow, green or brown poo is "color", not pee_color.
- cried, was crying, screamed, was unsettled for a time = "cry"; what calmed the baby goes to soothed_by.
- the first time the baby did something new (smiled, sat up, crawled, first tooth, first word, first steps) = "milestone".
- Anything else the parent wants to record about the baby = "note". Chat, the weather or words that make no sense give {"events": []}.
- A question or a request for advice is not an event.
- If a part of the note can mean two different things, add "unclear": true.

Example. Note: "3oz formula at 6:20 this morning then she napped from 7 for 40 min. dirty nappy 10 mins ago, a bit runny"
{"events":[{"type":"bottle","at":"6:20 this morning","amount":3,"unit":"oz","milk_type":"Formula"},{"type":"sleep","start":"7","duration":"40 min"},{"type":"nappy","at":"10 mins ago","mode":"poo","consistency":"runny"}]}

Example. Note: "20 minutes of play, 5 of them tummy time. in the car seat since 9"
{"events":[{"type":"activity","kind":"indoorPlay","end":"now","duration":"20 minutes"},{"type":"activity","kind":"tummyTime","end":"now","duration":"5 minutes"},{"type":"confined","start":"9","device":"car_seat"}]}

Example. Note: "changed nappy, big wee and a small poo, the poo was green and runny. left the nappy off for 5 minutes"
{"events":[{"type":"nappy","at":"now","mode":"both","pee_amount":"big","poo_amount":"little","color":"green","consistency":"runny","air_minutes":5}]}

Example (a sleep timer runs). Note: "she's awake now, fed her on the right for 12 minutes"
{"events":[{"type":"timer","timer":"sleep","action":"complete"},{"type":"nursing","start":"now","right_minutes":12,"last_side":"right"}]}"""


# --- proposals ----------------------------------------------------------------------------------------------------


class EntryProposal(BaseModel):
    action: Literal["entry"]
    type: EntryType
    started_at: datetime
    ended_at: datetime | None = None
    data: dict[str, Any] = {}
    notes: str | None = Field(None, max_length=2000)
    summary: str | None = None
    unsure: str | None = None  # why the server does not save it without a check (M14); ignored by commit


class TimerProposal(BaseModel):
    action: Literal["timer"]
    type: TimerType
    timer_action: TimerAction
    at: datetime | None = None
    side: Side | None = None
    kind: ActivityKind | None = None
    device: ConfinedDevice | None = None
    summary: str | None = None
    unsure: str | None = None  # why the server does not save it without a check (M14); ignored by commit


Proposal = Annotated[EntryProposal | TimerProposal, Field(discriminator="action")]


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ParseOut(BaseModel):
    proposals: list[Proposal]
    message: str


class CommitIn(BaseModel):
    proposals: list[Proposal] = Field(min_length=1, max_length=20)


class CommitOut(BaseModel):
    created: list[EntryOut]
    timers: list[TimerOut]


# --- time and unit resolution -------------------------------------------------------------------------------------


def resolve(t: dict | None, now: datetime, before: datetime | None = None) -> datetime:
    """Local aware time for a model time object. A clock time becomes its most recent occurrence not after
    `before` (default: now + 5 minutes)."""
    limit = before or now + FUTURE_LIMIT
    if not t or t.get("now"):
        return min(now, limit)
    if "minutes_ago" in t:
        return now - timedelta(minutes=int(t["minutes_ago"]))
    h, m, ampm = int(t["hour"]) % 24, int(t["minute"]) % 60, t.get("ampm", "unsure")
    if h > 12:
        hours = [h]
    elif ampm == "am":
        hours = [h % 12]
    elif ampm == "pm":
        hours = [h % 12 + 12]
    else:
        hours = [h % 12, h % 12 + 12]
    days = {"today": [0], "yesterday": [1]}.get(t.get("day", "unsure"), [0, 1])
    for ds in (days, [0, 1, 2]):
        cands = [datetime.combine(now.date() - timedelta(days=d), time(hh, m), now.tzinfo) for d in ds for hh in hours]
        past = [c for c in cands if c <= limit]
        if past:
            return max(past)
    return min(cands)


NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10,
                "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45}
_DUR = re.compile(r"(\d+(?:\.\d+)?|forty five|an?|one|two|three|four|five|six|ten|fifteen|twenty|thirty|forty)\s*"
                  r"(hours?|hrs?|h|minutes?|mins?|m)\b")


def parse_duration(words: str | None) -> int | None:
    """Minutes in "an hour and a half", "45 min", "1h 20m", "half an hour"; None if there is no length."""
    s = (words or "").lower().replace("-", " ")
    total, found = 0.0, False
    if re.search(r"half an? hour", s):
        total, found, s = 30, True, re.sub(r"half an? hour", "", s)
    if "quarter of an hour" in s:
        total, found = total + 15, True
    if hm := re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", s):  # "1:30" = 1 h 30 min
        return int(hm[1]) * 60 + int(hm[2])
    for num, unit in _DUR.findall(s):
        n = float(num) if num[0].isdigit() else NUMBER_WORDS[num]
        total, found = total + (n * 60 if unit.startswith("h") else n), True
    if found and re.search(r"(hours?|hrs?|h)\s+and\s+a\s+half", s):
        total += 30
    return round(total) if found else None


def parse_time(words: str | None) -> dict | None:
    """The parent's words for a time → {"minutes_ago"} or {"hour", "minute", "ampm", "day"}; {"now"} for "now";
    None when there is no time in the words."""
    s = (words or "").lower().strip()
    if not s or re.fullmatch(r"(just |right )?now|just|today", s):
        return {"now": True}
    if "ago" in s:
        mins = parse_duration(s.split("ago")[0])
        return {"minutes_ago": mins} if mins is not None else None
    day = ("yesterday" if "yesterday" in s else
           "today" if re.search(r"today|this (morning|afternoon|evening)|tonight", s) else "unsure")
    ampm = ("am" if re.search(r"\d\s*a\.?m\b|morning", s) else
            "pm" if re.search(r"\d\s*p\.?m\b|afternoon|evening|tonight", s) else "unsure")
    if re.search(r"noon|midday", s):
        h, m, ampm = 12, 0, "pm"
    elif "midnight" in s:
        h, m, ampm = 0, 0, "am"
    elif q := re.search(r"(half|quarter)\s+(past|to)\s+(\d{1,2})", s):
        h, step = int(q[3]), 30 if q[1] == "half" else 15
        h, m = (h, step) if q[2] == "past" else ((h - 1) % 24, 60 - step)
    elif c := re.search(r"(\d{1,2})(?:[:.](\d{2}))?", s):
        h, m = int(c[1]), int(c[2] or 0)
    else:
        return None
    if h > 23 or m > 59:
        return None
    if "last night" in s and h <= 12:
        # 7:30 last night = 19:30 yesterday; 2 last night = 02:00 today
        ampm, day = ("pm", "yesterday") if 5 <= h <= 11 or ampm == "pm" else ("am", "today")
    return {"hour": h, "minute": m, "ampm": ampm, "day": day}


def _when(words: str | None, now: datetime, before: datetime | None = None) -> datetime | None:
    t = parse_time(words)
    return None if t is None else resolve(t, now, before)


def _span(ev: dict, now: datetime) -> tuple[datetime | None, datetime | None]:
    """(start, end) from any two of start, end, duration."""
    mins = parse_duration(ev.get("duration"))
    dur = timedelta(minutes=mins) if mins else None
    end = _when(ev["end"], now) if ev.get("end") else None
    start = _when(ev["start"], now, before=end) if ev.get("start") else None
    if start is None and end is not None and dur:
        start = end - dur
    if end is None and start is not None and dur:
        end = start + dur
    if start is None and end is None and dur:
        end, start = now, now - dur
    return start, end


def _ml(amount: float | None, unit: str) -> float | None:
    return None if amount is None else round(amount * OZ_ML if unit == "oz" else amount, 1)


def to_proposal(ev: dict, now: datetime) -> dict:
    """One model event → one proposal dict with local times (converted to UTC later)."""
    kind = ev["type"]
    if kind == "timer":
        p = {"action": "timer", "type": ev["timer"], "timer_action": ev["action"]}
        if ev.get("at") and ev["action"] in ("start", "complete"):
            p["at"] = _when(ev["at"], now)
        if ev.get("side") and ev["timer"] == "nursing":
            p["side"] = ev["side"]
        if ev.get("kind") and ev["timer"] == "activity":
            p["kind"] = ev["kind"]
        if ev.get("device") and ev["timer"] == "confined" and ev["action"] == "start":
            p["device"] = ev["device"]
        return p
    at = _when(ev.get("at"), now) or now
    end = None
    data: dict[str, Any] = {}
    notes = None
    if kind in ("sleep", "nursing", "activity", "cry", "confined"):
        start, end = _span(ev, now)
        if kind == "nursing" and start is None and end is None:
            mins = (ev.get("left_minutes") or 0) + (ev.get("right_minutes") or 0)
            end = now if mins else None
            start = now - timedelta(minutes=mins) if mins else now
        if kind == "activity" and end is not None and start in (None, end):
            # "playing outside now", "bath at 11": the model can put the one time in end, or in start and end.
            start, end = end, None
        playing = kind == "activity" and ev["kind"] in ("indoorPlay", "outdoorPlay", "tummyTime")
        if (kind in ("sleep", "confined") or playing) and end is None and start is not None:
            # Asleep (playing, in the car seat) since `start` with no end: that runs now, it is not finished.
            p = {"action": "timer", "type": kind, "timer_action": "start", "at": start}
            return p | ({"device": ev["device"]} if kind == "confined" else {"kind": ev["kind"]} if playing else {})
        at = start or end or now
        if kind == "nursing":
            left, right = ev.get("left_minutes"), ev.get("right_minutes")
            data = {"left_seconds": left * 60 if left is not None else None,
                    "right_seconds": right * 60 if right is not None else None, "last_side": ev.get("last_side")}
            if end is None and (left or right):
                end = at + timedelta(minutes=(left or 0) + (right or 0))
        elif kind == "activity":
            data = {"kind": ev["kind"]}
        elif kind == "cry":
            data = {"soothed_by": ev.get("soothed_by")}
        elif kind == "confined":
            data = {"device": ev["device"]}
    elif kind == "pump":
        u = ev.get("unit", "ml")
        data = {"left_ml": _ml(ev.get("left_amount"), u), "right_ml": _ml(ev.get("right_amount"), u),
                "total_ml": _ml(ev.get("total_amount"), u)}
    elif kind == "bottle":
        data = {"amount_ml": _ml(ev["amount"], ev["unit"]), "milk_type": ev.get("milk_type")}
    elif kind == "solids":
        data = {"foods": [{"name": f} for f in ev["foods"]], "reaction": ev.get("reaction")}
    elif kind == "nappy":
        mode = ev["mode"]
        data = {k: ev.get(k) for k in ("mode", "color", "consistency", "pee_color", "pee_look")} | {
            "pee_amount": ev.get("pee_amount") if mode in ("pee", "both") else None,
            "poo_amount": ev.get("poo_amount") if mode in ("poo", "both") else None,
            "rash": bool(ev.get("rash")), "air_minutes": round(ev["air_minutes"]) if ev.get("air_minutes") else None,
            "pee_smell": True if ev.get("pee_smell") else None}
    elif kind == "potty":
        data = {"mode": ev["mode"], "result": ev["result"]}
    elif kind == "growth":
        w = ev.get("weight")
        wf = {"g": 0.001, "lb": LB_KG}.get(ev.get("weight_unit", "kg"), 1)
        lf = IN_CM if ev.get("length_unit") == "in" else 1
        data = {"weight_kg": round(w * wf, 3) if w else None,
                "height_cm": round(ev["length"] * lf, 1) if ev.get("length") else None,
                "head_cm": round(ev["head"] * lf, 1) if ev.get("head") else None}
    elif kind == "temperature":
        v = ev["value"]
        data = {"celsius": round((v - 32) * 5 / 9 if ev["unit"] == "F" else v, 2)}
    elif kind == "medicine":
        data = {"name": ev["name"], "amount": ev.get("amount"), "unit": ev.get("unit")}
    elif kind == "milestone":
        data = {"title": ev["title"], "key": None}
    elif kind == "note":
        notes = ev["text"]
    return {"action": "entry", "type": kind, "started_at": at, "ended_at": end,
            "data": {k: v for k, v in data.items() if v is not None}, "notes": notes}


# --- summary text -------------------------------------------------------------------------------------------------

NAPPY_WORDS = {"pee": "wet", "poo": "dirty", "both": "wet and dirty", "dry": "dry"}


def _hm(dt: datetime, ctx: Ctx) -> str:
    return dt.astimezone(ctx.tz).strftime("%H:%M")


def _dur(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def _words(kind: str) -> str:
    """tummyTime -> tummy time"""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", kind).lower()


def summary(p: dict, ctx: Ctx) -> str:
    units = ctx.fam.settings.get("units", {})
    word = "Diaper" if wording(ctx.fam) == "diaper" else "Nappy"
    labels = {"sleep": "Sleep", "nursing": "Breastfeed", "pump": "Pump", "activity": "Activity", "nappy": word,
              "cry": "Crying", "confined": "Confined"}
    if p["action"] == "timer":
        what = {"start": "start", "pause": "pause", "resume": "resume", "switch": "switch",
                "cancel": "cancel", "complete": "stop and save"}[p["timer_action"]]
        extra = p.get("side") or _words(p.get("kind") or "") or (p.get("device") or "").replace("_", " ")
        at = _hm(p["at"], ctx) if p.get("at") else "now"
        return " – ".join(x for x in (f"{labels.get(p['type'], p['type'].title())} timer", what, extra, at) if x)
    t, d = p["type"], p["data"]
    detail = ""
    if t == "bottle":
        amt = f"{round(d['amount_ml'] / OZ_ML, 1)} oz" if units.get("volume") == "oz" else f"{d['amount_ml']:g} ml"
        detail = f"{amt} {d.get('milk_type', '').lower()}".strip()
    elif t == "nursing":
        detail = ", ".join(f"{s} {round(d[f'{s}_seconds'] / 60)} min" for s in ("left", "right") if f"{s}_seconds" in d)
    elif t in ("nappy", "potty"):
        detail = NAPPY_WORDS[d["mode"]] + (f", {d['color']}" if d.get("color") else "") + (
            f", {d['consistency']}" if d.get("consistency") else "") + (", rash" if d.get("rash") else "") + (
            f", {d['pee_amount']} pee" if d.get("pee_amount") else "") + (
            f", {d['poo_amount']} poo" if d.get("poo_amount") else "") + (
            f", pee {d['pee_color'].replace('_', ' ')}" if d.get("pee_color") else "") + (
            ", cloudy" if d.get("pee_look") == "cloudy" else "") + (", strong smell" if d.get("pee_smell") else "") + (
            f", air time {d['air_minutes']} min" if d.get("air_minutes") else "")
        if t == "potty":
            detail += f" ({d['result']})"
    elif t == "temperature":
        c = d["celsius"]
        detail = f"{round(c * 9 / 5 + 32, 1)} °F" if units.get("temperature") == "F" else f"{c:g} °C"
    elif t == "medicine":
        detail = " ".join(str(x) for x in (d["name"], f"{d['amount']:g}" if "amount" in d else "", d.get("unit", "")) if x)
    elif t == "growth":
        parts = []
        if "weight_kg" in d:
            parts.append(f"{round(d['weight_kg'] / LB_KG, 2)} lb" if units.get("weight") == "lb" else f"{d['weight_kg']:g} kg")
        for k, name in (("height_cm", "length"), ("head_cm", "head")):
            if k in d:
                v = f"{round(d[k] / IN_CM, 1)} in" if units.get("length") == "in" else f"{d[k]:g} cm"
                parts.append(f"{name} {v}")
        detail = ", ".join(parts)
    elif t == "solids":
        detail = ", ".join(f["name"] for f in d["foods"]) + (f" ({d['reaction'].lower()})" if d.get("reaction") else "")
    elif t == "pump":
        detail = f"{d['total_ml']:g} ml" if "total_ml" in d else ""
    elif t == "activity":
        detail = _words(d["kind"])
    elif t == "milestone":
        detail = d["title"]
    elif t == "note":
        detail = (p.get("notes") or "")[:60]
    elif t == "cry":
        detail = f"soothed by {d['soothed_by']}" if d.get("soothed_by") else ""
    elif t == "confined":
        detail = d["device"].replace("_", " ")
    when = _hm(p["started_at"], ctx)
    if p.get("ended_at"):
        when += f" to {_hm(p['ended_at'], ctx)} ({_dur((p['ended_at'] - p['started_at']).total_seconds())})"
    return " – ".join(x for x in (labels.get(t, t.title()), detail, when) if x)


def entry_summary(e, ctx: Ctx) -> str:
    """Summary text of a saved entry (the data is canonical after validation)."""
    return summary({"action": "entry", "type": e.type, "started_at": e.started_at, "ended_at": e.ended_at,
                    "data": e.data, "notes": e.notes}, ctx)


# --- parse and commit ---------------------------------------------------------------------------------------------


def _context(s: Session, ctx: Ctx, child: Child, now_local: datetime) -> str:
    running = [f"{t.type} timer{f' {t.kind}' if t.kind else ''} since {_hm(t.started_at, ctx)}"
               for t in list_timers(s, child.id)]
    weeks = (now_local.date() - child.birthdate).days // 7
    age = f"{weeks} weeks" if weeks < 13 else f"{int(age_months(child, now_local))} months"
    return (f"Now: {now_local.strftime('%A %Y-%m-%d %H:%M')} (24-hour clock).\n"
            f"Child: {child.name}, {age} old.\n"
            f"Running timers: {', '.join(running) or 'none'}.\n"
            f"Usual volume unit: {ctx.fam.settings.get('units', {}).get('volume', 'ml')}.")


def check_timer(s: Session, child: Child, p: dict) -> None:
    """Same rules as services.timers.act, without changing anything."""
    body = TimerBody(at=p.get("at"), side=p.get("side"), kind=p.get("kind"), device=p.get("device"))
    if body.at and p["timer_action"] not in ("start", "complete"):
        raise Invalid("at: use it only with start or complete")
    if body.side and p["type"] != "nursing":
        raise Invalid("side: use it only with a nursing timer")
    if body.kind and p["type"] != "activity":
        raise Invalid("kind: use it only with an activity timer")
    if p["type"] == "activity" and p["timer_action"] == "start" and not body.kind:
        raise Invalid("kind: say which activity")
    if p["type"] == "activity" and p["timer_action"] == "switch":
        raise Invalid("switch: start the other activity instead")
    running = {t.type for t in list_timers(s, child.id)}
    if body.device and not (p["type"] == "confined" and p["timer_action"] == "start"):
        raise Invalid("device: use it only to start a confined timer")
    if p["type"] == "confined" and p["timer_action"] == "start" and not body.device and "confined" not in running:
        raise Invalid("device: say where the child is, for example the car seat")
    if p["timer_action"] != "start" and find(s, child.id, p["type"], body.kind) is None:
        raise Invalid(f"No {body.kind or p['type']} timer is running.")


# --- not sure: never save a guess (M14) --------------------------------------------------------------------------

DOUBLE = timedelta(minutes=10)  # an entry of the same type this close may be the same event
TOO_OLD = timedelta(hours=24)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# The parent said what was in the nappy (the model must choose a mode, so it can guess one).
NAPPY_SAID = re.compile(r"\b(wet|wee\w*|pee\w*|urine|dirty|poo\w*|soiled|number (one|two)|stool|bm|dry|both)\b", re.I)


# A nappy detail stays only when the parent's words have a word for it (the model can invent "cloudy").
_AMOUNT = re.compile(r"little|small|tiny|bit|medium|normal|big|large|huge|lot|full|massive|heavy|explosion", re.I)
PEE_SAID = {"pee_amount": _AMOUNT, "poo_amount": _AMOUNT,
            "pee_look": re.compile(r"cloud|clear|murky", re.I),
            "pee_smell": re.compile(r"smell|stink|pong|whiff|strong", re.I),
            "pee_color": re.compile(r"dark|pale|yellow|orange|pink|red|blood", re.I)}


def said_only(ev: dict, text: str) -> dict:
    return {k: v for k, v in ev.items() if k not in PEE_SAID or PEE_SAID[k].search(text)}


def merge_nappies(events: list[dict]) -> list[dict]:
    """The model can split one nappy change into two events (amounts in one, colour in the other): join nappy
    events with the same time and mode that do not disagree. Equal events stay (parse marks them "not sure")."""
    out: list[dict] = []
    for ev in events:
        same = next((o for o in out if ev.get("type") == o.get("type") == "nappy" and o != ev
                     and all(o.get(k) == ev.get(k) for k in ("at", "mode"))
                     and all(o.get(k, v) == v for k, v in ev.items())), None)
        if same:
            same.update(ev)
        else:
            out.append(dict(ev))
    return out


def _numbers(text: str) -> set[float]:
    found = {float(n.replace(",", ".")) for n in _NUMBER.findall(text)}
    words = text.lower().replace("-", " ")
    return found | {float(v) for w, v in NUMBER_WORDS.items() if len(w) > 2 and re.search(rf"\b{w}\b", words)}


def doubt(s: Session, ctx: Ctx, child: Child, ev: dict, p: dict, text: str, now: datetime) -> str | None:
    """Why this proposal may be a guess, or None. Checks: every number of the event is in the parent's words (a
    missing amount or time is not invented); not more than 24 h back; no entry of the same type within 10 minutes;
    no timer start on a running timer; a note is always checked (it is the catch-all type)."""
    have = _numbers(text)
    for k, v in ev.items():
        if isinstance(v, bool) or k == "type":
            continue
        if isinstance(v, int | float) and float(v) not in have:
            return f"the {k.replace('_', ' ')} is not in your words"
        if isinstance(v, str) and k in ("at", "start", "end", "duration") and any(
                n and n not in have for n in _numbers(v)):
            return "the time is not in your words"
    if ev.get("type") in ("nappy", "potty") and not NAPPY_SAID.search(text):
        return "say if it was wet, dirty or dry"
    when = p.get("started_at") or p.get("at")
    if when and when < now - TOO_OLD:
        return "it is more than 24 hours ago"
    label = summary(p, ctx).split(" – ")[0]
    if p["action"] == "entry":
        near = s.scalar(select(Entry.started_at).where(
            Entry.child_id == child.id, Entry.type == p["type"], Entry.started_at >= when - DOUBLE,
            Entry.started_at <= when + DOUBLE,
            func.json_extract(Entry.data, "$.kind") == p["data"]["kind"] if p["type"] == "activity" else true())
            .limit(1))
        if near:
            return f"a {label.lower()} at {_hm(near, ctx)} is already logged"
        if p["type"] == "note":
            return "check the note"
    elif p["timer_action"] == "start" and find(s, child.id, p["type"], p.get("kind")):
        return f"the {label.lower()} already runs"
    return None


async def parse(s: Session, ctx: Ctx, child_id: int, text: str, limited: bool = True) -> dict:
    """{"proposals", "message", "problems"}. A proposal that may be a guess has `unsure` (the reason)."""
    child = get_child(s, ctx, child_id)
    now = utcnow()
    now_local = now.astimezone(ctx.tz)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{_context(s, ctx, child, now_local)}\n\nNote: {text.strip()}"}]
    out = await llm.complete_json(ctx.fam, messages, SCHEMA, max_tokens=1500, limited=limited)
    proposals, problems = [], []
    seen: set[str] = set()  # a model can repeat one event many times: a second equal item is never saved unchecked
    for ev in merge_nappies(out.get("events", [])):
        try:
            ev = said_only(ev, text)
            p = to_proposal(ev, now_local)
            if (ev["type"] == "activity" and ev.get("end") and not ev.get("start") and not ev.get("duration")
                    and find(s, child.id, "activity", ev["kind"])):
                # "stop tummy time" can come as an activity that ends now: stop the running timer of that kind.
                p = {"action": "timer", "type": "activity", "timer_action": "complete", "kind": ev["kind"],
                     "at": p.get("started_at") or p.get("at")}
            if p["action"] == "entry":
                p["started_at"] = to_utc(p["started_at"], ctx.tz)
                p["ended_at"] = to_utc(p["ended_at"], ctx.tz) if p["ended_at"] else None
                p["data"] = validate(p["type"], p["started_at"], p["ended_at"], p["data"], p["notes"], now)
            else:
                p["at"] = to_utc(p["at"], ctx.tz) if p.get("at") else None
                check_timer(s, child, p)
            p["summary"] = summary(p, ctx)
            p["unsure"] = doubt(s, ctx, child, ev, p, text, now) or (
                "your words can mean two things" if out.get("unclear") else None) or (
                "it is the same as another item" if p["summary"] in seen else None)
            seen.add(p["summary"])
            proposals.append({k: v for k, v in p.items() if v is not None})
        except (ServiceError, KeyError, TypeError, ValueError) as err:
            problems.append(str(err) if isinstance(err, ServiceError) else "an item was not complete")
    if proposals:
        message = f"I found {len(proposals)} {'item' if len(proposals) == 1 else 'items'}. Check and confirm."
    else:
        message = "I did not find anything to log. Say what happened and when, for example \"120 ml formula at 2pm\"."
    if problems:
        message += f" I could not use {len(problems)}: {'; '.join(p.rstrip('.') for p in problems)}."
    return {"proposals": proposals, "message": message, "problems": problems}


def commit(s: Session, ctx: Ctx, child_id: int, proposals: list[EntryProposal | TimerProposal]) -> dict:
    """Save all proposals or none. `items` (not in the API answer) has one row per proposal for the chat."""
    child = get_child(s, ctx, child_id)
    nl = dataclasses.replace(ctx, source="nl")
    created, running, items = [], [], []
    # shortcut: the services commit after each change; turn those commits into flushes so that one bad proposal
    # rolls back all. Give the services a commit flag if more callers need this.
    s.commit = s.flush  # type: ignore[method-assign]
    try:
        for i, p in enumerate(proposals, 1):
            try:
                if isinstance(p, EntryProposal):
                    body = EntryIn(type=p.type, started_at=p.started_at, ended_at=p.ended_at, data=p.data,
                                   notes=p.notes)
                    e = create_entry(s, nl, child.id, body)
                    created.append(EntryOut.model_validate(e))
                    items.append({"action": "entry", "type": p.type, "summary": entry_summary(e, ctx),
                                  "entry_id": e.id})
                else:
                    t, e = act(s, nl, child.id, p.type, p.timer_action, TimerBody(at=p.at, side=p.side, kind=p.kind,
                                                                                        device=p.device))
                    if t:
                        running.append(timer_out(t, utcnow()))
                    if e:
                        created.append(EntryOut.model_validate(e))
                    items.append({"action": "timer", "type": p.type, "timer_action": p.timer_action, "kind": p.kind,
                                  "summary": entry_summary(e, ctx) if e else summary(p.model_dump(), ctx),
                                  "entry_id": e.id if e else None})
            except ServiceError as err:
                raise type(err)(f"Item {i}: {err}") from err
            except ValidationError as err:
                raise Invalid(f"Item {i}: {plain_errors(err)}") from err
    except BaseException:
        s.rollback()
        raise
    finally:
        del s.commit
    s.commit()
    return {"created": created, "timers": running, "items": [x | {"undone": False} for x in items]}


# --- log in one step (assistant chat, MCP) --------------------------------------------------------------------------

PROPOSAL = TypeAdapter(Proposal)
# A clause that starts with one of these words asks something (unless it asks the app to log).
ASKS = re.compile(r"^(is|are|am|can|could|should|shall|will|would|do|does|how|what|when|where|why|which|who|whose|"
                  r"tell me|explain|any (tips|ideas)|tips|ideas|help me)\b", re.I)
LOG_WORDS = re.compile(r"\b(log|record|save|track|add|start|stop)\b", re.I)
_SENTENCE = re.compile(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+[.!?\n]*")


def split_question(text: str) -> tuple[str, bool]:
    """(the part that reports something, whether the text asks something). No model.

    A sentence that ends with "?" is a question; when its first clause does not start like a question ("she slept
    20 minutes, is that normal?"), only its last clause is. A clause that starts like a question is a question too,
    unless it asks the app to log ("can you log 120 ml"). The rest is the report that the parser reads."""
    report, asks = [], False
    for m in _SENTENCE.finditer(text):
        sentence = m.group(0)
        q_mark = sentence.rstrip().endswith("?")
        parts = [x.strip(" ?!.\n") for x in re.split(r"[,;]", sentence)]
        parts = [x for x in parts if x]
        if not parts:
            continue
        starts = [bool(ASKS.match(x)) and not LOG_WORDS.search(x) for x in parts]
        whole = q_mark and starts[0]
        for i, x in enumerate(parts):
            if whole or starts[i] or (q_mark and i == len(parts) - 1):
                asks = True
            else:
                report.append(x)
    return ", ".join(report), asks


def _json(p: dict) -> dict:
    return PROPOSAL.dump_python(PROPOSAL.validate_python(p), mode="json", exclude_none=True)


async def log_words(s: Session, ctx: Ctx, child_id: int, text: str, save: bool = True,
                    drop_notes: bool = False, limited: bool = True) -> dict:
    """Parse the words and save what is sure in one step. {"items": saved rows, "proposals": not saved (unsure, or
    all when save is false; JSON form), "message"}. `drop_notes`: the text also asks something, so a note is not
    what the parent wants to record."""
    out = await parse(s, ctx, child_id, text, limited)
    props = [p for p in out["proposals"] if not (drop_notes and p["action"] == "entry" and p["type"] == "note")]
    sure = [p for p in props if save and not p.get("unsure")]
    later = [p for p in props if p not in sure]
    items, failed = [], ""
    if sure:
        try:
            items = commit(s, ctx, child_id, [PROPOSAL.validate_python(p) for p in sure])["items"]
        except ServiceError as err:
            later, failed = props, f" I could not save them: {err}"
    parts = []
    if items:
        parts.append(f"Logged {len(items)} {'item' if len(items) == 1 else 'items'}.")
    if later:
        parts.append(f"Check {'this' if len(later) == 1 else f'these {len(later)}'} before I save.")  # why: per item
    if out["problems"]:
        parts.append(f"I could not use {len(out['problems'])}: "
                     + "; ".join(x.rstrip(".") for x in out["problems"]) + ".")
    message = " ".join(parts) + failed if parts or failed else out["message"]
    return {"items": items, "proposals": [_json(p) for p in later], "message": message}
