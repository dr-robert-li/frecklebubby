"""Sleep plan: the app calculates the day and night plan (services/regime.py). The model writes only the summary
and the cited advice for it. Stored in sleep_plan."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..knowledge.store import search
from ..models import SleepPlan
from ..services import Ctx
from ..services.children import get_child
from ..services.regime import regime
from . import llm
from .assistant import SOURCE_CHARS, child_context

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "advice"],
    "properties": {
        "summary": {"type": "string", "maxLength": 400},
        "advice": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "cites"],
            "properties": {"text": {"type": "string", "maxLength": 300},
                           "cites": {"type": "array", "maxItems": 3, "items": {"type": "integer", "minimum": 1}}}}},
    },
}

SYSTEM = """You write the summary and the advice for a day and night sleep plan, for parents in a baby-tracking app.
The app calculated the plan from the child's own logs. You do not change it.
Rules:
- Use ONLY the plan, the child's data and the numbered sources given. Do not use your own knowledge.
- Do not give new clock times. Do not tell the parent to change a time of the plan.
- When the plan has small steps toward best practice, say in a kind way what they are and that they are small.
  Do not ask for bigger or faster changes.
- Summary: 2 or 3 short sentences about this child's day and night, from the plan and the facts.
- Do not blame the parent. Children differ a lot.
- Advice: 2 to 4 short tips that fit the child's age and this plan, also for the night when the child wakes or feeds
  at night. Put the numbers of the sources that support each tip in "cites".
- Use a tip only when the source gives it for a child of this age. Do not use a tip for older children (for
  example food before bed, or a child who gets out of bed) for a baby.
- No medicine. Short plain sentences."""

QUERIES = ("baby sleep routine bedtime naps settle", "night feeds night waking baby sleep")
KINDS = {"night": "bedtime"}  # the kinds of the plan rows before 0.6.0


def plan_text(r: dict) -> str:
    """The calculated plan as text for the model."""
    basis = {"own": "the child's own logs", "mixed": "the child's logs and typical values for the age",
             "age": "typical values for the age (no logs)"}[r["basis"]]
    lines = [f"Plan for one typical 24 hours (age: {r['age_band']}; start point: {basis}):"]
    if r["mode"] == "rhythm":
        lines.append("A young baby with no fixed day and night: the sleep blocks are the hours of usual sleep.")
    for x in r["schedule"]:
        change = f" [small change in this plan: {x['change']}]" if x["change"] else ""
        lines.append(f"- {x['time']}{'-' + x['end'] if x['end'] else ''} {x['label']}{change}")
    if r["nudges"]:
        lines += ["Small steps toward best practice in this plan:"] + [f"- {n['text']}" for n in r["nudges"]]
    lines.append("Facts:")
    for f in r["facts"]:
        common = f"; common for the age: {f['common']}" if f["common"] else ""
        lines.append(f"- {f['label']}: {f['value']}{common}")
    lines += ["Notes from the app:"] + [f"- {n['text']}" for n in r["notes"]]
    return "\n".join(lines)


async def generate(s: Session, ctx: Ctx, child_id: int) -> dict:
    child = get_child(s, ctx, child_id)
    now = utcnow()
    r = regime(s, child, ctx.tz, now)
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
    # The plan is for a full day: the time now, today's totals and the next sleep are not for the model.
    data = "\n".join(x for x in child_context(s, ctx, child, now).splitlines()
                     if not x.startswith(("Today so far", "Next sleep")))
    data = re.sub(r"^Now: [^.]*\. ", "", data)
    user = (f"Child data:\n{data}\n\n{plan_text(r)}\n\nSources:\n" + "\n\n".join(blocks)
            + "\n\nWrite the summary and the advice for this plan.")
    out = await llm.complete_json(ctx.fam, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                  SCHEMA, max_tokens=1200, limited=False)  # a polled job: no wait limit
    valid = {c["n"] for c in citations}
    advice = [_advice(a, valid) for a in out.get("advice", [])]
    used = {n for a in advice for n in a["cites"]}
    schedule = [{"time": x["time"], "kind": KINDS.get(x["kind"], x["kind"]), "label": x["label"],
                 **({"note": x["note"]} if x["note"] else {})} for x in r["schedule"]]
    content = {"summary": out.get("summary", ""), "schedule": schedule, "advice": advice}
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
