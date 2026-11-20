"""Support report, fixed part (M11): one block per area with the numbers, the reference they are compared with (a
library citation) and a status from fixed rules: ok | watch | no_data. No model.

The status rules are the existing insight rules (services/insights.py), so a report and the insight cards agree.
Where no library file gives a threshold, the block shows the numbers only (`compared` is false; status ok or no_data).
Each fact in a reference or a standard tip has a SUPPORT phrase; tests/test_support_report.py checks that the phrase is
in the cited file.

To add an area: write one function (Period) -> block dict and add it to AREAS.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Entry
from ..schemas import DayReport
from . import Ctx, development
from . import insights as ins
from .children import age_months, corrected, dev_age_days, dev_age_months
from .confined import under
from .families import wording
from .growth import growth
from .library import cite
from .milestones import catalog
from .reports import TUMMY, daily
from .sleep import recommendations

DAYS = 7  # last 7 full days plus today
FOOTER = "General information, not medical advice."

SLEEP, HELP_SLEEP, WHO, NHS_ACTIVE, NHS_PLAY = ("sleep-duration-recommendations", "nhs-helping-baby-sleep",
                                                "who-under-5-activity-sleep", "nhs-keep-baby-active",
                                                "nhs-physical-activity-under-5")
CAR, WET, DRY, RASH, CRY, FEED = ("car-seat-time", "nhs-formula-questions", "nhs-dehydration", "nhs-nappy-rash",
                                  "infant-crying-first-months", "cdc-breastfeeding-how-much")
SUPPORT = {
    "sleep_worried": (SLEEP, "parents who are worried about too little or too much sleep should ask their health "
                             "professional"),
    "sleep_routine": (HELP_SLEEP, "Getting your baby into a simple, soothing bedtime routine may help them settle"),
    "sleep_routine_items": (HELP_SLEEP, "dimming the lights in the room to create a calm atmosphere"),
    "feeds_differ": (FEED, "Every baby is different."),
    "wet_6": (WET, "around 6 wet nappies a day from a few days after the birth"),
    "wet_fewer": (DRY, "fewer wet nappies than usual"),
    "rash_air": (RASH, "leave nappies off when possible"),
    "rash_change": (RASH, "change wet or dirty nappies as soon as possible"),
    "rash_help": (RASH, "your baby's nappy rash does not go away, gets worse or spreads to other areas"),
    "tummy_30": (WHO, "For infants not yet mobile, this includes at least 30 minutes in prone position (tummy time)"),
    "tummy_nhs": (NHS_PLAY, "Try to include at least 30 minutes of tummy time spread throughout the day when they're "
                            "awake."),
    "tummy_little": (NHS_ACTIVE, "Little and often is best to begin with."),
    "tummy_awake": (NHS_ACTIVE, "Only do tummy time when your baby is awake and alert, and you're there to keep an "
                                "eye on them."),
    "who_1h": (WHO, "should not be restrained for more than 1 hour at a time"),
    "break": (NHS_ACTIVE, "consider taking a break and getting your child out of their seat for a bit"),
    "seats_20min": (NHS_ACTIVE, "it's best to use them for no more than 20 minutes at a time"),
    "aap": (CAR, "take a break every 2 to 3 hours on a day trip"),
    "cry_6w": (CRY, "In the first 6 weeks, the average fussing and crying time was about 2 hours a day"),
    "cry_12w": (CRY, "By 10 to 12 weeks, the average dropped to about 1 hour a day"),
    "cry_vary": (CRY, "Babies vary a lot around this average."),
    "cry_limit": (CRY, "They are not a limit for a single baby."),
}


@dataclass
class Period:
    s: Session
    ctx: Ctx
    child: Child
    now: datetime
    today: date
    days: list[DayReport]  # the 7 full days
    now_day: DayReport  # today so far
    w: dict  # nappy wording


def _citations(sources: list) -> list[dict]:
    """Library file names (kind bundled) or {title, publisher, url, year} dicts (kind link), numbered from 1."""
    out = []
    for i, x in enumerate(sources, 1):
        c = cite(x)[0] if isinstance(x, str) else {"kind": "link", **{k: v for k, v in x.items() if v is not None}}
        out.append(c | {"n": i})
    return out


def block(area: str, title: str, status: str, numbers: list[dict], *, compared: bool = False,
          ref: tuple[str, list[int]] | None = None, sources: list | None = None, note: str | None = None,
          details: list[str] | None = None, tips: list[tuple[str, list[int]]] | None = None,
          well: tuple[str, list[int]] | None = None) -> dict:
    """One area. `ref`, `tips` and `well` cite by number in `sources`. Tips are kept only for status watch."""
    out = {"area": area, "title": title, "status": status, "compared": compared, "numbers": numbers,
           "reference": {"text": ref[0], "cites": ref[1]} if ref else None, "note": note, "details": details or [],
           "suggestions": [{"text": t, "cites": c} for t, c in tips or []] if status == "watch" else [],
           "suggested_by": "rules" if status == "watch" else None, "citations": _citations(sources or [])}
    if well and status == "ok":
        out["_well"] = well  # rules text for "what goes well"; removed before the report is saved
    return out


def num(label: str, value: float, unit: str = "") -> dict:
    return {"label": label, "value": round(value, 1), "unit": unit}


def _logged(days: list[DayReport], has) -> list[DayReport]:
    return [d for d in days if has(d)]


def _avg(days: list[DayReport], value) -> float:
    return sum(value(d) for d in days) / len(days) if days else 0.0


def _per_day(n: int) -> str:
    return f"{n} logged {'day' if n == 1 else 'days'}"


# --- areas --------------------------------------------------------------------------------------------------------

def sleep_block(p: Period) -> dict:
    logged = _logged(p.days, lambda d: d.sleep.total_seconds)
    numbers = [num(f"Average a day ({_per_day(len(logged))})", _avg(logged, lambda d: d.sleep.total_seconds) / 3600,
                   "h"), num("Naps a day", _avg(logged, lambda d: d.sleep.nap_count)),
               num("Today so far", p.now_day.sleep.total_seconds / 3600, "h")] if logged else []
    recs = recommendations(age_months(p.child, p.now))
    card = ins._sleep_card(p.s, p.ctx, p.child, p.now)  # the same rule as the insight card: 3 or more days
    status = ("no_data" if not logged or (recs and not card) else "ok" if not card
              else "watch" if card[0]["severity"] == "attention" else "ok")
    ref = None
    if recs:
        ranges = "; ".join(f"{r['min_hours']:g} to {r['max_hours']:g} hours ({r['citation']['publisher'].split(' /')[0]}"
                           f" {r['citation']['year']})" for r in recs)
        ref = (f"Recommended in 24 hours for this age, naps included: {ranges}.", [1])
    low = recs and _avg(logged, lambda d: d.sleep.total_seconds) / 3600 < min(r["min_hours"] for r in recs)
    tips = ([("Only logged sleep counts. If some sleep was not logged, the average looks lower.", [])] if low else []) + [
        (f"A simple, soothing bedtime routine may help {p.child.name} settle, for example a bath, a fresh "
         f"{p.w['nappy']}, a story and dim lights.", [2]),
        (f"If you are worried about {p.child.name}'s sleep, talk to your doctor or child health nurse.", [1])]
    note = "Log sleep on 3 or more days to compare it with the recommended range." if logged and not card else None
    return block("sleep", "Sleep", status, numbers, compared=bool(recs), ref=ref, sources=[SLEEP, HELP_SLEEP],
                 note=note, tips=tips, well=("Average logged sleep is in the recommended range for the age.", [1]))


def feeds_block(p: Period) -> dict:
    logged = _logged(p.days, lambda d: d.feeds.count or d.feeds.solids_count)
    numbers = []
    if logged:
        numbers = [num(f"Feeds a day ({_per_day(len(logged))})", _avg(logged, lambda d: d.feeds.count))]
        if any(d.feeds.bottle_ml for d in logged):
            numbers.append(num("Bottle a day", _avg(logged, lambda d: d.feeds.bottle_ml), "ml"))
        if any(d.feeds.nursing_seconds for d in logged):
            numbers.append(num("Breastfeeding a day", _avg(logged, lambda d: d.feeds.nursing_seconds) / 60, "min"))
        if any(d.feeds.solids_count for d in logged):
            numbers.append(num("Solid meals a day", _avg(logged, lambda d: d.feeds.solids_count)))
        numbers.append(num("Feeds today so far", p.now_day.feeds.count))
    return block("feeds", "Feeds", "ok" if logged else "no_data", numbers, sources=[FEED],
                 ref=("CDC: every baby is different. How much and how often a baby feeds depends on the baby's needs.",
                      [1]))


def nappies_block(p: Period) -> dict:
    w = p.w
    logged = _logged(p.days, lambda d: d.nappies.wet + d.nappies.dirty)
    rash_days = sum(1 for d in [*p.days[1:], p.now_day] if d.nappies.rash)  # the 7 days of the rash card
    numbers = []
    if logged:
        numbers = [num(f"Wee a day ({_per_day(len(logged))})", _avg(logged, lambda d: d.nappies.wet)),
                   num("Poo a day", _avg(logged, lambda d: d.nappies.dirty)),
                   num("Wee today so far", p.now_day.nappies.wet)]
    if rash_days:
        numbers.append(num("Days with a rash (last 7)", rash_days))
    air = sum(d.nappies.air_minutes for d in [*p.days, p.now_day])
    if air:
        numbers.append(num(f"Time with the {w['nappy']} off", air, "min"))
    wet_rule = ins.rules()["wet_nappy_baseline"]
    age_days = (p.today - p.child.birthdate).days
    in_age = wet_rule["min_age_days"] <= age_days and age_months(p.child, p.now) < wet_rule["max_age_months"]
    low_wet = bool(ins._wet_nappy_card(p.s, p.ctx, p.child, p.now, w))
    rash = [c for c in ins._rash_card(p.s, p.ctx, p.child, p.now, w) if c["severity"] == "attention"]
    status = "watch" if low_wet or rash else "ok" if logged else "no_data"
    ref = (f"The NHS says babies have around 6 wet {w['nappies']} a day from a few days after the birth.", [1]) \
        if in_age else None
    tips = []
    if low_wet:
        tips += [(f"The NHS lists fewer wet {w['nappies']} than usual as a sign of dehydration. If you are worried, "
                  "contact a doctor.", [2]),
                 (f"Log every {w['nappy']} for a few days, so that the count is complete.", [])]
    if rash:
        tips += [(f"The NHS says to leave {w['nappies']} off when possible, and to change wet or dirty {w['nappies']} as "
                  f"soon as possible. A {w['nappy']} change is a good time for this if {p.child.name} is calm.", [3]),
                 ("The NHS says to see a health visitor or GP if the rash does not go away, gets worse or spreads, if "
                  "your baby has a high temperature, or if your baby seems very uncomfortable.", [3])]
    return block("nappies", w["nappies"].capitalize(), status, numbers, compared=in_age, ref=ref,
                 sources=[WET, DRY, RASH], tips=tips,
                 well=(f"The logged wet {w['nappies']} reach the NHS figure of around 6 a day.", [1]) if in_age else None)


def play_block(p: Period) -> dict:
    logged = _logged(p.days, lambda d: d.play.count)
    baby = under(p.child, p.today, TUMMY["under_months"])
    tummy = _avg(logged, lambda d: d.play.tummy_seconds) / 60
    numbers = []
    if logged:
        numbers = [num(f"Play a day ({_per_day(len(logged))})", _avg(logged, lambda d: d.play.seconds) / 60, "min")]
        if baby or any(d.play.tummy_seconds for d in logged):
            numbers.append(num("Tummy time a day", tummy, "min"))
        numbers.append(num("Tummy time today so far", p.now_day.play.tummy_seconds / 60, "min"))
    status = "no_data" if not logged else "watch" if baby and tummy < TUMMY["minutes"] else "ok"
    name = p.child.name
    tips = [(f"Tummy time can be spread through the day, while {name} is awake. Little and often is best to begin "
             "with.", [2, 3]),
            (f"Do tummy time when {name} is awake and alert, and you are there to keep an eye on {name}.", [3]),
            (f"A {p.w['nappy']} change is a good time for a little tummy time.", [1])]
    note = f"The 30 minutes are for babies who are not yet mobile. If {name} already moves around, this does not apply."
    return block("play", "Play and tummy time", status, numbers, compared=baby,
                 ref=(TUMMY["text"], [1, 2]) if baby else None, sources=[WHO, NHS_PLAY, NHS_ACTIVE],
                 note=note if baby else None, tips=tips,
                 well=("Tummy time reached the WHO 30 minutes a day on average.", [1]) if baby else None)


def confined_block(p: Period) -> dict:
    all_days = [*p.days, p.now_day]
    logged = _logged(p.days, lambda d: d.confined.count)
    numbers = []
    if logged or p.now_day.confined.count:
        numbers = [num(f"In a seat or pram a day ({_per_day(len(logged))})",
                       _avg(logged, lambda d: d.confined.seconds) / 60, "min"),
                   num("Longest without a break", max(d.confined.longest_seconds for d in all_days) / 60, "min")]
    young = under(p.child, p.today, 60)
    over = ins._confined_card(p.s, p.ctx, p.child, p.now)  # the insight rule: over 1 hour in the last 7 days
    status = "watch" if over else "ok" if numbers else "no_data"
    name, baby = p.child.name, under(p.child, p.today, 12)
    tips = [(f"When it is safe, take a break and get {name} out of the seat to move.", [2])]
    if baby:
        tips += [("On a long car trip, plan stops. HealthyChildren.org (AAP) says to take a break every 2 to 3 hours "
                  "on a day trip.", [3]),
                 ("The NHS says to use a bouncer or seat for no more than 20 minutes at a time.", [2])]
    return block("confined", "Time in a seat or pram", status, numbers, compared=young,
                 ref=("WHO advises that children under 5 are not restrained for more than 1 hour at a time, for "
                      "example in a car seat, pram or high chair.", [1]) if young else None,
                 sources=[WHO, NHS_ACTIVE, CAR], tips=tips,
                 well=("No time in a seat or pram over 1 hour without a break was logged.", [1]) if young else None)


def crying_block(p: Period) -> dict:
    logged = _logged(p.days, lambda d: d.crying.count)
    numbers = []
    if logged or p.now_day.crying.count:
        numbers = [num(f"Crying times a day ({_per_day(len(logged))})", _avg(logged, lambda d: d.crying.count)),
                   num("Crying a day", _avg(logged, lambda d: d.crying.seconds) / 60, "min")]
    small = (p.today - p.child.birthdate).days < 91  # the review covers 0 to 12 weeks
    ref = ("A 2017 review of diary studies: in the first 6 weeks, babies fussed and cried about 2 hours a day on "
           "average, and about 1 hour a day by 10 to 12 weeks. Babies vary a lot. These are averages, not a limit "
           "for one baby.", [1]) if small else None
    return block("crying", "Crying", "ok" if numbers else "no_data", numbers, ref=ref, sources=[CRY] if small else [],
                 note="Only cries with an end time count in the minutes." if numbers else None)


def growth_block(p: Period) -> dict:
    from ..knowledge.store import link_list

    points = growth(p.s, p.ctx, p.child.id)["points"]
    numbers = []
    if points:
        last = points[-1]
        day = last["at"].astimezone(p.ctx.tz).strftime("%d %b").lstrip("0")
        for m, field, name, unit in (("weight", "weight_kg", "Weight", "kg"), ("height", "height_cm", "Length", "cm"),
                                     ("head", "head_cm", "Head", "cm")):
            if field in last:
                numbers.append(num(f"{name} ({day})", last[field], unit))
                if last.get(f"{m}_percentile") is not None:
                    numbers.append(num(f"{name} percentile (WHO)", round(last[f"{m}_percentile"]), "percentile"))
    who = next(({k: i[k] for k in ("title", "publisher", "url", "year")} for i in link_list()
                if i.get("id") == "who-growth-standards"), None)
    return block("growth", "Growth", "ok" if numbers else "no_data", numbers, sources=[who] if who else [],
                 ref=("WHO growth standards. A single point says little; the line over time matters more.",
                      [1] if who else []))


def milestones_block(p: Period) -> dict:
    items = catalog()
    local = p.now.astimezone(p.ctx.tz)
    age = dev_age_months(p.child, local)  # M13: corrected age until 2 years for a baby born early
    bands = sorted({i["age_months"] for i in items})
    band = max((b for b in bands if b <= age), default=None)
    # M13: development items around this age, each in the source's words and naming its source.
    dev = [f"Around now: {i['text']} ({i['source']['publisher'].split(' (')[0]})"
           for i in development.around(dev_age_days(p.child, local.date()))[:3]]
    note = development.CORRECTED_NOTE if corrected(p.child, local.date()) else None
    if band is None:
        return block("milestones", "Milestones", "no_data", [], details=dev,
                     note=note or ("The checklist starts at 2 months." if bands else None))
    done = {e.data.get("key") for e in p.s.scalars(select(Entry).where(Entry.child_id == p.child.id,
                                                                       Entry.type == "milestone"))}
    in_band = [i for i in items if i["age_months"] == band]
    open_items = [i["text"] for i in in_band if i["key"] not in done]
    return block("milestones", f"Milestones by {band} months", "ok",
                 [num("Marked", len(in_band) - len(open_items)), num("Not yet marked", len(open_items))],
                 ref=('CDC "Learn the Signs. Act Early." checklist. Every child grows at their own pace. Mark items in '
                      "the milestones checklist when you see them.", [1]),
                 sources=[in_band[0]["source"]], note=note, details=open_items[:6]
                 + ([f"and {len(open_items) - 6} more"] if len(open_items) > 6 else []) + dev)


AREAS = (sleep_block, feeds_block, nappies_block, play_block, confined_block, crying_block, growth_block,
         milestones_block)

DEFAULT_WELL = "You kept a log this week. A log helps you and your doctor or child health nurse see patterns."


def goes_well(blocks: list[dict]) -> dict:
    """The rules line for "what goes well": the first area that is in range of its reference."""
    b = next((b for b in blocks if "_well" in b), None)
    if b is None:
        return {"text": DEFAULT_WELL, "cites": [], "citations": []}
    text, cites = b["_well"]
    cs = [c for c in b["citations"] if c["n"] in cites]
    return {"text": text, "cites": list(range(1, len(cs) + 1)), "citations": [c | {"n": i} for i, c in enumerate(cs, 1)]}


def report(s: Session, ctx: Ctx, child: Child, now: datetime) -> dict:
    """The fixed part of the report. Blocks keep a `_well` key until the report is saved."""
    today = now.astimezone(ctx.tz).date()
    days = daily(s, ctx, child.id, today - timedelta(days=DAYS), today, now)["days"]
    word = wording(ctx.fam)
    w = {"nappy": word, "nappies": "nappies" if word == "nappy" else "diapers"}
    p = Period(s, ctx, child, now, today, days[:-1], days[-1], w)
    blocks = [f(p) for f in AREAS]
    return {"from": days[0].date, "to": today, "days": DAYS + 1, "blocks": blocks, "goes_well": goes_well(blocks),
            "footer": FOOTER}


def urgent(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    """Red flags (existing rules, unchanged), urgent first."""
    order = {"urgent": 0, "attention": 1, "info": 2}
    return sorted(ins.red_flags(s, child, ctx.tz, now, wording(ctx.fam)), key=lambda c: order[c["severity"]])
