"""Support report (M11): the fixed blocks of services/support.py, plus suggestions that the model writes for the
`watch` blocks (max 4) and one "what goes well" line, from retrieved library passages. One saved report per child.

Checks on the model output (as the sleep plan and the assistant): a suggestion that cites a number the model did not
get, or no number, is dropped; so is one with a number that is not in the input, or with "should". An area with no
valid suggestion keeps the standard tips. No model, a model error or no valid output: the standard tips and NOTICE.
"""

import logging
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..knowledge.store import search
from ..models import SupportReport
from ..services import Ctx, support
from ..services.children import get_child
from ..services.families import wording
from . import llm
from .assistant import SOURCE_CHARS, child_context
from .sleep_plan import _advice

log = logging.getLogger(__name__)

NOTICE = "The AI model is not available. These are the standard tips."
MAX_WATCH = 4
MAX_PASSAGES = 7
QUERIES = {
    "sleep": "baby sleep routine bedtime settle naps",
    "feeds": "how often baby feeds hunger signs",
    "nappies": "wet nappies dehydration nappy rash care",
    "play": "tummy time floor play baby active",
    "confined": "car seat break restrained time bouncer seat",
    "crying": "soothing crying baby",
    "growth": "baby weight growth chart",
    "milestones": "milestones development play tips",
}
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
SHOULD = re.compile(r"\bshould\b", re.I)

SYSTEM = """You write short, kind suggestions for a parent in a baby-tracking app.
Rules:
- Use ONLY the child's data and the numbered sources. Do not use your own knowledge.
- For each area in "Areas to support", write 1 to 3 short suggestions the parent can try. Each suggestion is one
  thing that a source says. Put the numbers of the sources that say it in "cites".
- "goes_well" (when asked): one short, kind sentence with no numbers about an area in "Areas in range". Cite a
  source only if it says the same; else leave "cites" empty.
- Write a number only if it is in the data or the sources. Do not add facts, times or amounts.
- Be supportive. Do not blame. Do not use the word "should". No medicine.
- Short plain sentences. Say "{nappy}" for a nappy or diaper."""


def _schema(areas: list[str], well: bool) -> dict:
    item = {"type": "object", "additionalProperties": False, "required": ["text", "cites"],
            "properties": {"text": {"type": "string", "maxLength": 240},
                           "cites": {"type": "array", "maxItems": 3, "items": {"type": "integer", "minimum": 1}}}}
    props: dict = {"goes_well": item} if well else {}
    if areas:
        props["areas"] = {"type": "array", "minItems": 1, "maxItems": len(areas), "items": {
            "type": "object", "additionalProperties": False, "required": ["area", "suggestions"],
            "properties": {"area": {"enum": areas},
                           "suggestions": {"type": "array", "minItems": 1, "maxItems": 3, "items": item}}}}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _line(b: dict) -> str:
    nums = "; ".join(f"{n['label']}: {n['value']:g}{' ' + n['unit'] if n['unit'] else ''}" for n in b["numbers"])
    ref = f" Reference: {b['reference']['text']}" if b["reference"] else ""
    return f"- {b['area']} ({b['title']}): {nums or 'nothing logged'}.{ref}"


def check(a: dict, valid: set[int], allowed: set[str], cited: bool = True) -> dict | None:
    """A model suggestion with valid citations (at least one if `cited`) and only allowed numbers, or None."""
    marks = {int(n) for n in re.findall(r"\[(\d+)\]", a.get("text", ""))} | set(a.get("cites", []))
    if (cited and not marks) or not marks <= valid:
        return None
    out = _advice(a, valid)
    if not out["text"] or SHOULD.search(out["text"]) or not set(NUMBER.findall(out["text"])) <= allowed:
        return None
    return out


def _local(cites: list[int], citations: list[dict], into: list[dict]) -> list[int]:
    """Map prompt numbers to numbers in `into` (a block's own citation list), adding citations as needed."""
    out = []
    for n in cites:
        c = next(x for x in citations if x["n"] == n)
        same = next((x for x in into if x.get("url") == c.get("url") and x["title"] == c["title"]), None)
        if same is None:
            same = c | {"n": len(into) + 1}
            into.append(same)
        out.append(same["n"])
    return out


async def _suggest(s: Session, ctx: Ctx, child, now: datetime, rep: dict) -> bool:
    """Put model suggestions into the watch blocks and goes_well. False when nothing valid came back."""
    watch = [b for b in rep["blocks"] if b["status"] == "watch"][:MAX_WATCH]
    ok = [b for b in rep["blocks"] if b["status"] == "ok"]
    in_range = [b for b in ok if b["compared"]]
    hits, seen = [], set()
    for b in watch + [b for b in ok if "_well" in b]:
        for h in search(s, ctx.fam, QUERIES.get(b["area"], b["title"]), limit=3 if b in watch else 1):
            if (h["id"], h["heading"]) not in seen and len(hits) < MAX_PASSAGES:
                seen.add((h["id"], h["heading"]))
                hits.append(h)
    citations, blocks = [], []
    for h in hits:
        if h["id"] not in {c["source_id"] for c in citations}:
            citations.append({"n": len(citations) + 1, "source_id": h["id"], "kind": h["kind"],
                              **{k: h[k] for k in ("title", "publisher", "author", "url", "year", "licence") if h[k]}})
        n = next(c["n"] for c in citations if c["source_id"] == h["id"])
        blocks.append(f"[{n}] {h['title']}, {h['heading']}:\n{h['text'][:SOURCE_CHARS]}")
    user = (f"Child data:\n{child_context(s, ctx, child, now)}\n\n"
            "Areas to support:\n" + ("\n".join(_line(b) for b in watch) or "none") + "\n\n"
            "Areas in range:\n" + ("\n".join(_line(b) for b in in_range) or "none") + "\n\n"
            "Other logged areas (no reference to compare with):\n"
            + ("\n".join(_line(b) for b in ok if not b["compared"]) or "none") + "\n\n"
            "Sources:\n" + ("\n\n".join(blocks) or "none")
            + "\n\nWrite the suggestions for the areas to support" + (" and the goes_well line." if in_range else "."))
    out = await llm.complete_json(ctx.fam, [{"role": "system", "content": SYSTEM.format(nappy=wording(ctx.fam))},
                                            {"role": "user", "content": user}],
                                  _schema([b["area"] for b in watch], bool(in_range)), max_tokens=1200)
    valid, allowed = {c["n"] for c in citations}, set(NUMBER.findall(SYSTEM + user))
    for c in citations:
        c.pop("source_id")
    used = False
    by_area = {b["area"]: b for b in watch}
    for a in out.get("areas", []):
        b = by_area.get(a.get("area"))
        good = [x for x in (check(x, valid, allowed) for x in a.get("suggestions", [])) if x]
        if b is None or not good or b.get("_model"):
            continue
        b["_model"] = True
        b["suggestions"] = [{"text": x["text"], "cites": _local(x["cites"], citations, b["citations"])}
                            for x in good]
        b["suggested_by"] = "model"
        used = True
    g = in_range and check(out.get("goes_well") or {}, valid, set(), cited=False)  # no numbers in this line
    if g:
        into: list[dict] = []
        rep["goes_well"] = {"text": g["text"], "cites": _local(g["cites"], citations, into),
                            "citations": into}
        used = True
    return used


def _out(row: SupportReport, s: Session, ctx: Ctx, child, now: datetime) -> dict:
    """The saved payload; red flags are read again so that a warning is never old or missing."""
    return {"id": row.id, "created_at": row.created_at, **row.payload, "urgent": support.urgent(s, ctx, child, now)}


async def generate(s: Session, ctx: Ctx, child_id: int, now: datetime | None = None) -> dict:
    child = get_child(s, ctx, child_id)
    now = now or utcnow()
    rep = support.report(s, ctx, child, now)
    ai, notice = False, None
    if any(b["status"] == "watch" or b["compared"] and b["status"] == "ok" for b in rep["blocks"]):  # else no call
        try:
            ai = await _suggest(s, ctx, child, now, rep)
        except llm.LlmError:
            pass
        if not ai:
            notice = NOTICE
            log.info("Support report uses the standard tips")
    for b in rep["blocks"]:
        b.pop("_well", None)
        b.pop("_model", None)
    rep |= {"ai": ai, "notice": notice}
    payload = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in rep.items()}
    row = s.scalar(select(SupportReport).where(SupportReport.child_id == child.id))
    if row is None:
        row = SupportReport(child_id=child.id)
        s.add(row)
    row.created_at, row.days, row.payload = now, rep["days"], payload
    s.commit()
    return _out(row, s, ctx, child, now)


def latest(s: Session, ctx: Ctx, child_id: int) -> dict | None:
    child = get_child(s, ctx, child_id)
    row = s.scalar(select(SupportReport).where(SupportReport.child_id == child.id))
    return None if row is None else _out(row, s, ctx, child, utcnow())
