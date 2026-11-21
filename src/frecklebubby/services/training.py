"""The optional sleep training mode (0.7.0). Off by default. With the mode off, the sleep plan works as before.

Methods: extinction, graduated extinction, bedtime fading; each with parental presence as an option. The pace is a
scale from 1 (gentle) to 10 (firm). The numbers at the ends of the scale are from published trials and reviews
(data/sleep_training.json). The steps of a night are fixed before bedtime and change only between nights: the one
documented risk is a parent who gives in after long crying, which teaches longer crying.
"""

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..db import utcnow
from ..models import Child, Entry, SleepTraining
from . import Conflict, Invalid, NotFound
from .children import dev_age_days

METHODS = {"extinction": "Extinction", "graduated": "Graduated extinction", "fading": "Bedtime fading"}
ANSWERS = {"too_hard": -1, "ok": 0, "faster": 1}
PACE = (1, 10)


@lru_cache
def table() -> dict:
    return json.loads((PACKAGE_DATA / "sleep_training.json").read_text())


def scale(ends: list[float], pace: int) -> float:
    """A value on the scale: ends = [gentle (1), usual (5), firm (10)], straight lines between them."""
    lo, mid, hi = ends
    return lo + (mid - lo) * (pace - 1) / 4 if pace <= 5 else mid + (hi - mid) * (pace - 5) / 5


def clock(minutes: float) -> str:
    m = round(minutes / 5) * 5 % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def gate(child: Child, today: date) -> dict:
    """Which methods the child can use, by the corrected age. Below 4 months: none."""
    ages = table()["ages"]
    months = dev_age_days(child, today) / 30.4375
    if months < ages["min_months"]:
        return {"available": False, "methods": [], "warning": None,
                "reason": f"Sleep training is not for a baby younger than {ages['min_months']} months. A young baby "
                          "has no fixed day and night yet, and needs feeds at night. No study supports sleep training "
                          "at this age."}
    methods = ["graduated"]
    warning = None
    if months < ages["warn_below_months"]:
        warning = (f"The studies of sleep training start at about {ages['warn_below_months']} months. Before that age "
                   "the gain is small, and many babies still need a feed at night. Speak to a child health nurse first.")
    else:
        methods.insert(0, "extinction")
        if months >= ages["fading_from_months"]:
            methods.append("fading")
    return {"available": True, "methods": methods, "warning": warning, "reason": None}


def current(s: Session, child: Child) -> SleepTraining | None:
    return s.scalar(select(SleepTraining).where(SleepTraining.child_id == child.id, SleepTraining.status != "ended")
                    .order_by(SleepTraining.id.desc()).limit(1))


def waits(pace: int) -> list[int]:
    """Graduated extinction: the minutes to wait before check 1, 2, 3 ... The last value repeats."""
    g = table()["graduated"]
    first, inc, top = (round(scale(g[k], pace)) for k in ("first_wait", "increment", "max_wait"))
    out = [min(first, top)]
    while inc and out[-1] < top:
        out.append(min(out[-1] + inc, top))
    return out


def save(s: Session, child: Child, body: dict, today: date, usual_bedtime: float | None) -> SleepTraining:
    """Start the mode, or change the mode that runs (pace, switch, pause, parental presence)."""
    t = current(s, child)
    g = gate(child, today)
    if t is None:
        if not g["available"]:
            raise Invalid(g["reason"])
        method = body.get("method")
        if method not in g["methods"]:
            raise Invalid("This method is not available for the age of the child.")
        if g["warning"] and not body.get("confirm_warning"):
            raise Conflict(g["warning"])
        t = SleepTraining(child_id=child.id, method=method, state={}, nights=[])
        if method == "fading":
            if not body.get("goal_bedtime"):
                raise Invalid("Give the bedtime that you want to reach.")
            if usual_bedtime is None:
                raise Invalid("Log the night sleep for some days first. Bedtime fading starts from the time at which "
                              "the child falls asleep now.")
            t.goal_bedtime = body["goal_bedtime"]
            t.state = {"bedtime": usual_bedtime + table()["fading"]["start_later"], "good": 0}
        s.add(t)
    elif body.get("method") not in (None, t.method):
        raise Conflict("Stop this sleep training first. Then start the new method.")
    for key in ("presence", "auto_pace"):
        if body.get(key) is not None:
            setattr(t, key, bool(body[key]))
    if body.get("pace") is not None:
        t.pace = min(max(int(body["pace"]), PACE[0]), PACE[1])
    if body.get("status") in ("active", "paused"):
        t.status = body["status"]
    s.commit()
    return t


def end(s: Session, child: Child) -> None:
    t = current(s, child)
    if t is None:
        raise NotFound("No sleep training runs for this child.")
    t.status = "ended"
    s.commit()


def report(s: Session, child: Child, body: dict) -> SleepTraining:
    """The parent's report of one night. With the switch on, the answer moves the scale for the next night."""
    t = current(s, child)
    if t is None:
        raise NotFound("No sleep training runs for this child.")
    night = {"night": len(t.nights) + 1, "date": body["day"], "pace": t.pace,
             "minutes_to_sleep": body.get("minutes_to_sleep"), "wakes": body.get("wakes"),
             "crying_minutes": body.get("crying_minutes"), "answer": body.get("answer") or "ok"}
    t.nights = [n for n in t.nights if n["date"] != body["day"]] + [night]
    for i, n in enumerate(t.nights, 1):
        n["night"] = i
    if t.auto_pace:
        t.pace = min(max(t.pace + ANSWERS.get(night["answer"], 0), PACE[0]), PACE[1])
    if t.method == "fading" and night["minutes_to_sleep"] is not None:
        f, st = table()["fading"], dict(t.state)
        step, need = (30, 1) if t.pace > 8 else (15, 1) if t.pace > 6 else (15, 2)
        goal = int(t.goal_bedtime[:2]) * 60 + int(t.goal_bedtime[3:])
        goal += 1440 if goal < 12 * 60 else 0  # a goal after midnight
        if night["minutes_to_sleep"] <= f["good_minutes"]:
            st["good"] = st.get("good", 0) + 1
            if st["good"] >= need and len(t.nights) >= f["hold_nights"]:
                st["bedtime"], st["good"] = max(st["bedtime"] - step, goal), 0
        else:
            st["good"] = 0
            if len(t.nights) >= f["hold_nights"]:
                st["bedtime"] += 15  # not asleep in 15 minutes: 15 minutes later (Cooney 2018)
        t.state = st
    s.commit()
    return t


def tonight(t: SleepTraining, name: str) -> dict:
    """The steps for the next night, from the method, the scale and the number of nights so far."""
    tb = table()
    n = len(t.nights) + 1
    steps, bedtime = [], None
    feed = f"A feed that {name} still needs at night stays. Feed, then put {name} down awake."
    ill = f"Do not train when {name} is ill. Go to {name} at any time if you think that something is wrong."
    if t.method == "fading":
        bedtime = clock(t.state["bedtime"])
        steps = [f"Bedtime tonight: {bedtime}. Do not put {name} to bed before this time.",
                 f"Keep {name} awake until then, with quiet play and the usual bedtime routine.",
                 f"Wake {name} at the usual time in the morning. Keep the naps as they are.",
                 f"When {name} falls asleep in {tb['fading']['good_minutes']} minutes or less, bedtime moves earlier. "
                 f"The goal is {t.goal_bedtime}."]
        if t.presence:
            steps.append(f"Stay with {name} at bedtime as you do now. No study tested bedtime fading together with "
                         "parental presence, so the bedtime steps are the same.")
    elif t.presence and t.method == "graduated":
        per = max(1, round(scale(tb["presence"]["nights_per_step"], t.pace)))
        k = min((n - 1) // per, len(tb["presence"]["steps"]) - 1)
        steps = [f"Do the bedtime routine. Put {name} in bed awake.",
                 f"Step {k + 1} of {len(tb['presence']['steps'])}: " + tb["presence"]["steps"][k].format(name=name),
                 f"Stay until {name} is asleep. At a wake in the night, go back to the same place.",
                 f"Each step is for {per} night{'s' if per > 1 else ''}. Then you move one step away.", feed]
    elif t.presence:  # extinction with parental presence
        stay = tb["presence"]["stay_nights"]
        if n <= stay:
            steps = [f"Do the bedtime routine. Put {name} in bed awake and say goodnight.",
                     f"Night {n} of {stay}: lie down in the same room, on a separate bed or mattress. Pretend to sleep.",
                     f"Do not pick {name} up. If {name} is very upset, soothe for a short time with your voice, then "
                     "pretend to sleep again after about 2 minutes.", feed]
        else:
            steps = [f"Do the bedtime routine. Put {name} in bed awake and say goodnight.",
                     f"The {stay} nights in the room are done. Leave the room tonight.",
                     f"Do not go back in until the morning, except for a feed that {name} still needs, or when you "
                     "think that something is wrong.", feed]
    elif t.method == "graduated":
        w = waits(t.pace)
        check = round(scale(tb["graduated"]["check_seconds"], t.pace) / 5) * 5
        listed = ", ".join(str(x) for x in w)
        steps = [f"Do the bedtime routine. Put {name} in bed awake, say goodnight and leave the room.",
                 (f"If {name} cries, wait {w[0]} minutes before each check." if len(w) == 1 else
                  f"If {name} cries, wait before each check: {listed} minutes, then {w[-1]} minutes each time."),
                 f"A check is {check} seconds or less. Use a calm voice or a pat. Do not pick {name} up. Keep the light "
                 f"off. Leave while {name} is still awake.",
                 "At a wake in the night, start again from the first wait.", feed]
    else:
        steps = [f"Do the bedtime routine. Put {name} in bed awake, say goodnight and leave the room.",
                 f"Do not go back in until the morning, except for a feed that {name} still needs, or when you think "
                 "that something is wrong. Then check with little light and few words.",
                 "The first nights are the hardest. Crying usually gets less after some nights.", feed]
    steps.append(ill)
    steps.append("Follow the steps for the whole night. Change the pace in the morning, not in the night: to go in "
                 "after long crying teaches longer crying.")
    return {"night": n, "bedtime": bedtime, "steps": steps}


def review(t: SleepTraining) -> dict | None:
    """What the nights so far show: the goal holds, no gain, or two weeks are over."""
    r = table()["review"]
    done = [n for n in t.nights if n.get("minutes_to_sleep") is not None]
    last = done[-r["good_nights"]:]
    if len(last) == r["good_nights"] and all(
            n["minutes_to_sleep"] <= r["good_minutes"] and (n.get("wakes") or 0) <= r["good_wakes"] for n in last):
        return {"kind": "success", "text": f"The last {r['good_nights']} nights were good: asleep in {r['good_minutes']} "
                                           "minutes or less, with 1 wake or none. You can end the sleep training. If "
                                           "the old pattern comes back later, some nights of the same steps usually help."}
    if len(t.nights) >= r["max_nights"]:
        return {"kind": "stop", "text": f"The sleep training has run for {len(t.nights)} nights. Speak to a child "
                                        "health nurse or a doctor before you continue."}
    if len(done) >= r["no_gain_nights"] and median(n["minutes_to_sleep"] for n in done[-3:]) >= median(
            n["minutes_to_sleep"] for n in done[:3]):
        return {"kind": "no_gain", "text": f"After {len(done)} nights the time to fall asleep is not shorter. You can "
                                           "try a gentler pace or a different method, or speak to a child health nurse."}
    return None


def ill(s: Session, child: Child, now: datetime | None = None) -> bool:
    """A fever or a medicine in the last 24 hours: the page asks the parent to pause."""
    now = now or utcnow()
    rows = s.execute(select(Entry.type, Entry.data).where(
        Entry.child_id == child.id, Entry.type.in_(("temperature", "medicine")), Entry.started_at >= now - timedelta(hours=24)))
    return any(kind == "medicine" or (data or {}).get("celsius", 0) >= 38 for kind, data in rows)


def out(s: Session, child: Child, today: date) -> dict:
    t = current(s, child)
    g = gate(child, today)
    body = None
    if t:
        body = {"id": t.id, "method": t.method, "method_name": METHODS[t.method], "presence": t.presence, "pace": t.pace,
                "auto_pace": t.auto_pace, "status": t.status, "goal_bedtime": t.goal_bedtime, "nights": t.nights,
                "tonight": tonight(t, child.name), "review": review(t), "pause_hint": ill(s, child)}
    src = table()["sources"]
    return {"gate": g, "training": body, "scale": {"min": PACE[0], "max": PACE[1]},
            "sources": [{"n": i + 1, "kind": "link", **v} for i, v in enumerate(src.values())]}
