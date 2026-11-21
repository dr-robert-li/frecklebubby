"""Sleep plan: the assistant pipeline with a fixed question and JSON schema output. Stored in sleep_plan."""

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..knowledge.store import search
from ..models import Entry, SleepPlan
from ..services import Ctx
from ..services.children import get_child, is_night
from ..services.sleep import age_summary, norms, recommendations, stage, wake_range
from . import llm
from .assistant import SOURCE_CHARS, child_context

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "schedule", "advice"],
    "properties": {
        "summary": {"type": "string", "maxLength": 400},
        "schedule": {"type": "array", "minItems": 2, "maxItems": 16, "items": {
            "type": "object", "additionalProperties": False, "required": ["time", "kind", "label"],
            "properties": {"time": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
                           "kind": {"enum": ["wake", "nap", "feed", "bedtime", "other"]},
                           "label": {"type": "string", "maxLength": 80},
                           "note": {"type": "string", "maxLength": 160}}}},
        "advice": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "cites"],
            "properties": {"text": {"type": "string", "maxLength": 300},
                           "cites": {"type": "array", "maxItems": 3, "items": {"type": "integer", "minimum": 1}}}}},
    },
}

SYSTEM = """You make a simple daily sleep plan for a baby, for parents in a baby-tracking app.
Rules:
- Use ONLY the child's data, the age ranges and the numbered sources given. Do not use your own knowledge.
- The schedule is one full typical day, in time order, 24-hour HH:MM. It is not a plan for the rest of today.
- The first row is the morning wake (kind "wake") at the given morning start time. The last row is bedtime.
- Fit the recommended total sleep and the wake-window range. Start from the child's own recent times.
- If typical values for the age are given, use them where the child's own days are few or irregular.
- Advice: 2 to 4 short tips. Put the numbers of the sources that support each tip in "cites".
- No medicine. Short plain sentences."""

QUERIES = ("recommended sleep duration by age naps hours", "baby sleep routine bedtime naps settle")


def _recent_days(s: Session, ctx: Ctx, child, now) -> str:
    """One line per day for the last 7 days: night sleep and naps as local times."""
    rows = s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.type == "sleep",
                                         Entry.started_at >= now - timedelta(days=7)).order_by(Entry.started_at))
    days: dict[str, list[str]] = {}
    for e in rows:
        a, b = e.started_at.astimezone(ctx.tz), e.ended_at.astimezone(ctx.tz)
        kind = "night" if is_night(child, a) else "nap"
        days.setdefault(a.strftime("%a %d"), []).append(f"{kind} {a:%H:%M}-{b:%H:%M}")
    return "\n".join(f"{d}: {', '.join(v)}" for d, v in days.items()) or "No sleep logged in the last 7 days."


async def generate(s: Session, ctx: Ctx, child_id: int) -> dict:
    child = get_child(s, ctx, child_id)
    now = utcnow()
    months = (now.date() - child.birthdate).days / 30.4375
    lo, hi = wake_range(months)
    recs = "; ".join(f"{r['min_hours']:g}-{r['max_hours']:g} h per 24 h ({r['citation']['publisher'].split(' /')[0]})"
                     for r in recommendations(months)) or "none for this age"
    n = norms()
    st = stage(s, child, ctx.tz, now, n) if n else None
    typical = (age_summary(n, (now.astimezone(ctx.tz).date() - child.birthdate).days) + "\n") if n else ""
    if st:
        typical += f"This child recently: {st['naps']} naps on most days.\n"
    hits, seen = [], set()
    for q in QUERIES:
        for h in search(s, ctx.fam, q, limit=4):
            if (h["id"], h["heading"]) not in seen and len(hits) < 6:
                seen.add((h["id"], h["heading"]))
                hits.append(h)
    numbers: dict[int, int] = {}
    citations, blocks = [], []
    for h in hits:
        if h["id"] not in numbers:
            numbers[h["id"]] = len(numbers) + 1
            citations.append({"n": numbers[h["id"]], "kind": h["kind"],
                              **{k: h[k] for k in ("title", "publisher", "author", "url", "year", "licence") if h[k]}})
        blocks.append(f"[{numbers[h['id']]}] {h['title']}, {h['heading']}:\n{h['text'][:SOURCE_CHARS]}")
    # The plan is for a full day: the time now, today's totals and the next sleep make the model start from now.
    data = "\n".join(x for x in child_context(s, ctx, child, now).splitlines()
                     if not x.startswith(("Today so far", "Next sleep")))
    data = re.sub(r"^Now: [^.]*\. ", "", data)
    user = (f"Child data:\n{data}\n"
            f"Morning starts at {child.morning_cutoff}. Night starts at {child.night_start}.\n"
            f"Wake-window range for this age (common practice, not a medical standard): {lo}-{hi} minutes.\n"
            f"Recommended total sleep: {recs}.\n" + typical
            + f"Sleep in the last 7 days:\n{_recent_days(s, ctx, child, now)}\n\nSources:\n" + "\n\n".join(blocks)
            + f"\n\nMake the sleep plan for a typical day. Start with the wake at {child.morning_cutoff}.")
    out = await llm.complete_json(ctx.fam, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                  SCHEMA, max_tokens=2000, limited=False)  # a polled job: no wait limit
    valid = {c["n"] for c in citations}
    advice = [_advice(a, valid) for a in out.get("advice", [])]
    used = {n for a in advice for n in a["cites"]}
    content = {"summary": out.get("summary", ""), "schedule": out.get("schedule", []), "advice": advice}
    plan = SleepPlan(child_id=child.id, content=content, citations=[c for c in citations if c["n"] in used])
    s.add(plan)
    s.commit()
    return plan_out(plan)


def _advice(a: dict, valid: set[int]) -> dict:
    """The model sometimes also writes its marks into the text ("... cites: [2]"): move them to `cites`."""
    marks = [int(n) for n in re.findall(r"\[(\d+)\]", a["text"])]
    text = re.sub(r"\s*(?:\(?\s*(?:cites?|sources?)\s*:?\s*)?(?:\[\d+\][,\s]*)+\)?", " ", a["text"])
    text = re.sub(r"\s+([.,;:!?])", r"\1", text).strip()
    return {"text": text, "cites": [n for n in dict.fromkeys([*a.get("cites", []), *marks]) if n in valid]}


def plan_out(plan: SleepPlan | None) -> dict | None:
    if plan is None:
        return None
    return {"id": plan.id, "created_at": plan.created_at, **plan.content, "citations": plan.citations}


def latest(s: Session, ctx: Ctx, child_id: int) -> dict | None:
    child = get_child(s, ctx, child_id)
    return plan_out(s.scalar(select(SleepPlan).where(SleepPlan.child_id == child.id)
                             .order_by(SleepPlan.id.desc()).limit(1)))
