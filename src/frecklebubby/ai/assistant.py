"""Assistant chat (spec section 9): retrieval first, one streamed model call, citations mapped by the server.

Red flags (from the child's data and from a temperature in the question) come first, from the server, so an urgent
warning never depends on the model.
"""

import copy
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..knowledge import web_lookup
from ..knowledge.store import STOP, chunks_of, search
from ..models import ChatMessage, Child
from ..schemas import TimerBody
from ..services import Conflict, Ctx, Invalid, NotFound, cry, development
from ..services.children import age_months, corrected, dev_age_days, dev_age_months, get_child
from ..services.entries import delete_entry
from ..services.families import wording
from ..services.growth import growth
from ..services.insights import red_flags, text_flags
from ..services.library import library
from ..services.reports import daily
from ..services.sleep import predict
from ..services.timers import act
from . import llm, nl_log

log = logging.getLogger(__name__)

FOOTER = "General information, not medical advice."
CRY_WORDS = re.compile(r"\b(cry|cries|cried|crying|unsettled|fussy|fussing|screaming|colic\w*)\b", re.I)
NOT_COVERED = "The sources I have do not cover this question. Ask your doctor or child health nurse."
HISTORY_CHARS = 2400  # about 700 tokens; the whole prompt stays under about 6,000 tokens (context 8,192)
SOURCE_CHARS = 1100
ANSWER_TOKENS = 600
SEARCH_TOP = 6
# M13: a question about development also gets the CDC tips of the child's age band and the development items of the
# age as passages, picked by age (search drops the numbers in "my 15 month old").
DEV_WORDS = re.compile(r"\b(develop\w*|milestones?|learn\w*|skills?|sit\w*|crawl\w*|walk\w*|stand\w*|roll\w*|"
                       r"talk\w*|words?|speak\w*|babbl\w*|play\w*|tips?|activit\w*|doing|able|teeth|tooth|"
                       r"teething|potty|toilet|tantrums?|reflex\w*|grasp\w*|smil\w*|encourage|tummy|mov\w*)\b", re.I)
# Topics the library has no source for (M13 research): the answer says so first, deterministically.
NO_SOURCE = [
    (re.compile(r"regression", re.I), "sleep regressions"),
    (re.compile(r"growth spurt", re.I), "the ages of growth spurts"),
    (re.compile(r"\b(cry\w*|fuss\w*|colic\w*)\b.*\b(peak\w*|worst)\b|\b(peak\w*|worst)\b.*\b(cry\w*|fuss\w*|colic)\b",
                re.I), "a week when crying peaks"),
    (re.compile(r"\b(see|vision|eyesight|eyes?)\b.*\b(colou?rs?|focus\w*|how far|distance)\b", re.I),
     "vision by month"),
    (re.compile(r"dry (at|through the|all) night|night[- ]?time dry|night dryness|dry overnight", re.I),
     "an age for dryness at night"),
    (re.compile(r"\b(when|what age|how old)\b.*\b(speech|talk\w*|language)\b.*\b(check|assess\w*|therap\w*|"
                r"test\w*|worr\w*|late)\b", re.I), "an age for a speech check"),
]

SYSTEM = """You answer a parent's questions in a baby-tracking app.
Rules:
- Use ONLY the numbered sources and the child's data in the message. Do not use your own knowledge.
- After each fact, put the number of its source in square brackets, for example [2]. Use only the numbers given.
- If the sources do not answer the question, say only: "The sources I have do not cover this." Do not guess.
- Give a medicine dose only if a source states it, and cite it.
- If something may be an emergency, tell the parent to contact a doctor or emergency services.
- Write short, plain sentences. At most 150 words. No headings. Do not add a disclaimer.
- Say "{nappy}" for a nappy or diaper."""


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def child_context(s: Session, ctx: Ctx, child: Child, now: datetime, marks: dict[str, int] | None = None) -> str:
    """The child's data for the model. `marks`: library file → source number, so the development items of the age
    point to their numbered source."""
    local = now.astimezone(ctx.tz)
    days = (local.date() - child.birthdate).days
    age = f"{days // 7} weeks" if days < 91 else f"{int(age_months(child, now))} months"
    if corrected(child, local.date()):
        dev = dev_age_days(child, local.date())
        age += f" (born early; corrected age {dev // 7} weeks)" if dev < 91 else \
            f" (born early; corrected age {int(dev / 30.4375)} months)"
    lines = [f"Now: {local.strftime('%A %Y-%m-%d %H:%M')}. Child: {child.name}, {age} old"
             + (f", {'girl' if child.sex == 'F' else 'boy'}" if child.sex else "") + "."]
    rep = daily(s, ctx, child.id, local.date() - timedelta(days=7), local.date() - timedelta(days=1), now)["days"]
    logged = [d for d in rep if d.sleep.total_seconds or d.feeds.count or d.nappies.wet + d.nappies.dirty]
    if logged:
        n = len(logged)
        lines.append(
            f"Last 7 days ({n} days logged), average per day: sleep {sum(d.sleep.total_seconds for d in logged) / n / 3600:.1f} h, "
            f"naps {sum(d.sleep.nap_count for d in logged) / n:.1f}, feeds {sum(d.feeds.count for d in logged) / n:.1f}, "
            f"bottle {sum(d.feeds.bottle_ml for d in logged) / n:.0f} ml, wet {sum(d.nappies.wet for d in logged) / n:.1f}, "
            f"dirty {sum(d.nappies.dirty for d in logged) / n:.1f}.")
    t = daily(s, ctx, child.id, local.date(), local.date(), now)["days"][0]
    lines.append(f"Today so far: sleep {t.sleep.total_seconds / 3600:.1f} h, feeds {t.feeds.count}, "
                 f"wet {t.nappies.wet}, dirty {t.nappies.dirty}.")
    p = predict(s, child, ctx.tz, now)
    if p:
        lines.append(f"Next sleep ({p['kind']}) predicted {p['start'].astimezone(ctx.tz):%H:%M}-"
                     f"{p['end'].astimezone(ctx.tz):%H:%M} ({p['note']})")
    rash = [d.date for d in rep + [t] if d.nappies.rash]
    if rash:
        lines.append(f"{wording(ctx.fam).capitalize()} rash logged on {len(rash)} of the last 8 days, last on "
                     f"{rash[-1]:%a %d %b}.")
    g = [x for x in growth(s, ctx, child.id)["points"] if x.get("weight_percentile") is not None]
    if g:
        lines.append(f"Latest weight {g[-1]['weight_kg']:g} kg, WHO percentile {g[-1]['weight_percentile']:.0f}.")
    lines += development.context_lines(s, child, local, marks or {})
    return "\n".join(lines)


def age_passages(s: Session, child: Child, question: str, local: datetime) -> list[dict]:
    """The CDC tips of the child's checklist band and the library passages of up to 2 development items of the age
    (the ones that share most words with the question, else the narrowest windows)."""
    band = development.band_of(dev_age_months(child, local))
    out = chunks_of(s, library(development.tips_file(band))[0]["title"]) if band else []
    words = {w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in STOP}
    items = development.around(dev_age_days(child, local.date()))

    def shared(i: dict) -> int:
        return len(words & set(re.findall(r"[a-z]{3,}", i["text"].lower())))

    picked = sorted((i for i in items if shared(i)), key=lambda i: -shared(i))[:2] or items[:2]
    for i in picked:
        for name, phrase in ((i["library"], i["phrase"]), (i.get("tip_library"), i.get("tip"))):
            if name:
                chunks = chunks_of(s, library(name)[0]["title"])
                out += [c for c in chunks if phrase[:60] in c["text"]][:1] or chunks[:1]
    return out


def history(s: Session, child_id: int) -> list[dict]:
    rows = s.scalars(select(ChatMessage).where(ChatMessage.child_id == child_id)
                     .order_by(ChatMessage.id.desc()).limit(8)).all()
    out, used = [], 0
    for m in rows:
        text = m.content.replace(FOOTER, "").strip()[:600]
        done = [i["summary"] for i in (m.logged or {}).get("items", []) if not i.get("undone")]
        if done:
            text = f"Logged: {'; '.join(done)}. {text}".strip()
        if used + len(text) > HISTORY_CHARS:
            break
        used += len(text)
        out.insert(0, {"role": m.role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


class CiteFilter:
    """Streams text and drops [n] marks whose n is not in `valid`. Holds back a possible mark until it is complete."""

    MARK = re.compile(r"\[(?:sources?\s*)?(\d+(?:\s*,\s*\d+)*)\]", re.I)
    PARTIAL = re.compile(r"\[(?:s(?:o(?:u(?:r(?:c(?:e(?:s)?)?)?)?)?)?\s*)?[\d,\s]*", re.I)

    def __init__(self, valid: set[int]):
        self.valid, self.buf = valid, ""

    def feed(self, text: str) -> str:
        self.buf += text
        out = ""
        while self.buf:
            i = self.buf.find("[")
            if i < 0:
                out, self.buf = out + self.buf, ""
                break
            out, self.buf = out + self.buf[:i], self.buf[i:]
            m = self.MARK.match(self.buf)
            if m:
                keep = [n for n in (int(x) for x in m.group(1).split(",")) if n in self.valid]
                out += "".join(f"[{n}]" for n in keep)
                self.buf = self.buf[m.end():]
            elif self.PARTIAL.fullmatch(self.buf) and len(self.buf) < 24:
                break  # wait for more text
            else:
                out, self.buf = out + self.buf[0], self.buf[1:]
        return out

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        return out


def used_numbers(text: str) -> set[int]:
    return {int(n) for m in re.finditer(r"\[(\d+)\]", text) for n in [m.group(1)]}


async def chat(s: Session, ctx: Ctx, child_id: int, message: str) -> AsyncIterator[str]:
    """SSE events. Raises llm.LlmError before the first event when the model is down and there is no warning."""
    child = get_child(s, ctx, child_id)
    now = utcnow()
    word = wording(ctx.fam)
    family, user_id = ctx.fam, ctx.user.id

    # 0. M14: save what the message reports (one parse call; none for a pure question), before the red flags so
    # that a logged temperature counts. A guess is not saved: it comes back as a proposal to confirm.
    report, asks = nl_log.split_question(message)
    logged = None
    if report:
        try:
            logged = await nl_log.log_words(s, ctx, child.id, report, drop_notes=asks)
        except llm.LlmError:
            asks = True  # not read: answer it as a question (that fails too if the model is down)
        if logged and not (logged["items"] or logged["proposals"]):
            logged, asks = None, True  # nothing to log: it is a question in other words
    row_ids: tuple[int, int] | None = None
    if logged:
        # Saved at once, so that a lost stream or a model error still shows what was logged.
        with SessionLocal() as s2:
            q = ChatMessage(child_id=child.id, user_id=user_id, role="user", content=message, citations=[])
            a = ChatMessage(child_id=child.id, user_id=user_id, role="assistant", content="", citations=[],
                            logged=logged)
            s2.add_all([q, a])
            s2.commit()
            row_ids = (q.id, a.id)
        yield sse("logged", logged | {"message_id": row_ids[1]})

    # 1. Deterministic red flags: the question text first, then urgent flags in the child's data.
    flags, seen = [], set()
    for f in text_flags(message, child, now) + [c for c in red_flags(s, child, ctx.tz, now, word)
                                               if c["severity"] == "urgent"]:
        if f["kind"] not in seen:
            seen.add(f["kind"])
            flags.append(f)

    # 2. Retrieval (and live lookup of approved pages if the family turned it on).
    if asks and family.settings.get("web_lookup"):
        await web_lookup.lookup(s, message)
    local = now.astimezone(ctx.tz)
    hits = development.age_fit(search(s, family, message, limit=2 * SEARCH_TOP), dev_age_months(child, local),
                               SEARCH_TOP) if asks else []
    if asks and DEV_WORDS.search(message):  # the age passages first, then the search hits
        merged, have = [], set()
        for h in age_passages(s, child, message, local) + hits:
            if (h["id"], h["heading"]) not in have:
                have.add((h["id"], h["heading"]))
                merged.append(h)
        hits = merged
    gaps = [topic for rx, topic in NO_SOURCE if rx.search(message)] if asks else []

    # 3. One numbering for all citations: red-flag pages first, then the sources the model sees.
    citations: list[dict] = []

    def number(c: dict, kind: str) -> int:
        for x in citations:
            if c.get("url") and x.get("url") == c.get("url") or (c.get("id") and x.get("source_id") == c.get("id")):
                return x["n"]
        n = len(citations) + 1
        citations.append({"n": n, "kind": kind, "source_id": c.get("id"),
                          **{k: c.get(k) for k in ("title", "publisher", "author", "url", "year", "licence")}})
        return n

    warning = ""
    for f in flags:
        marks = "".join(f"[{number(c, c.get('kind', 'link'))}]" for c in f["citations"])
        warning += f"Urgent: {f['title']}. {f['body']} {marks}\n\n"
    if gaps:
        warning += " ".join(f"I have no source on {t}." for t in gaps) + "\n\n"
    blocks, model_numbers, titles = [], set(), {}
    for h in hits:
        n = number(h, h["kind"])
        model_numbers.add(n)
        if h["kind"] == "bundled":
            titles[h["title"]] = n
        blocks.append(f"[{n}] {h['title']} ({h.get('publisher') or 'own upload'}), {h['heading']}:\n"
                      f"{h['text'][:SOURCE_CHARS]}")

    files = {i["library"] for i in development.items()}
    data = child_context(s, ctx, child, now, marks={x: titles[library(x)[0]["title"]] for x in files
                                                    if library(x)[0]["title"] in titles})
    if CRY_WORDS.search(message):
        data += "\n" + cry.context_lines(s, ctx, child, now)
    if logged and logged["items"]:
        data += "\nJust logged from this message: " + "; ".join(i["summary"] for i in logged["items"]) + "."
    if gaps:
        data += "\nThe sources have nothing on " + " or ".join(gaps) + ". Do not give an age or a time for it."
    prompt = [{"role": "system", "content": SYSTEM.format(nappy=word)}, *history(s, child.id),
              {"role": "user", "content": f"Child data:\n{data}\n\nSources:\n"
                                          + "\n\n".join(blocks) + f"\n\nQuestion: {message}"}]
    child_id = child.id

    def cited(answer: str) -> list[dict]:
        used = used_numbers(answer)
        return [{k: v for k, v in c.items() if v is not None and k != "source_id"} for c in citations if c["n"] in used]

    async def finish(answer: str) -> AsyncIterator[str]:
        cited_list = cited(answer)
        yield sse("citations", {"citations": cited_list})
        with SessionLocal() as s2:  # the request session may be closed while the response streams
            if row_ids:
                msg = s2.get(ChatMessage, row_ids[1])
                msg.content, msg.citations = answer, cited_list
            else:
                s2.add(ChatMessage(child_id=child_id, user_id=user_id, role="user", content=message, citations=[]))
                msg = ChatMessage(child_id=child_id, user_id=user_id, role="assistant", content=answer,
                                  citations=cited_list)
                s2.add(msg)
            s2.commit()
            yield sse("done", {"message_id": msg.id})

    if logged and not asks:  # only a report: no answer from the model
        answer = warning + FOOTER if warning else ""
        if answer:
            yield sse("token", {"text": answer})
        async for e in finish(answer):
            yield e
        return

    if not hits:
        answer = warning + NOT_COVERED + "\n\n" + FOOTER
        yield sse("token", {"text": answer})
        async for e in finish(answer):
            yield e
        return

    answer, sent = warning, False
    try:
        async with llm.stream(family, prompt, ANSWER_TOKENS) as tokens:
            if warning:
                sent = True
                yield sse("token", {"text": warning})
            filt = CiteFilter(model_numbers)
            async for tok in tokens:
                text = filt.feed(tok)
                if text:
                    answer, sent = answer + text, True
                    yield sse("token", {"text": text})
            tail = filt.flush() + "\n\n" + FOOTER
    except llm.LlmError:
        if not sent:
            if not warning and not logged:
                raise  # nothing sent yet: the endpoint answers 503
            yield sse("token", {"text": warning})
        yield sse("citations", {"citations": cited(warning)})
        yield sse("error", {"detail": llm.UNAVAILABLE})
        return
    answer += tail
    yield sse("token", {"text": tail})
    async for e in finish(answer):
        yield e


def list_messages(s: Session, ctx: Ctx, child_id: int) -> list[ChatMessage]:
    child = get_child(s, ctx, child_id)
    return list(s.scalars(select(ChatMessage).where(ChatMessage.child_id == child.id).order_by(ChatMessage.id)))


def clear_messages(s: Session, ctx: Ctx, child_id: int) -> None:
    child = get_child(s, ctx, child_id)
    s.execute(delete(ChatMessage).where(ChatMessage.child_id == child.id))
    s.commit()


# --- M14: the "Logged" block of a chat turn ----------------------------------------------------------------------

UNDO = {"start": "cancel", "pause": "resume", "resume": "pause", "switch": "switch"}


def _logged_message(s: Session, ctx: Ctx, child_id: int, message_id: int) -> ChatMessage:
    child = get_child(s, ctx, child_id)
    m = s.get(ChatMessage, message_id)
    if m is None or m.child_id != child.id or not m.logged:
        raise NotFound("Message not found.")
    return m


def undo(s: Session, ctx: Ctx, child_id: int, message_id: int, index: int) -> ChatMessage:
    """Undo one saved item: delete the entry, cancel a started timer, or reverse a pause, resume or switch."""
    m = _logged_message(s, ctx, child_id, message_id)
    logged = copy.deepcopy(m.logged)
    if not 0 <= index < len(logged["items"]):
        raise NotFound("Item not found.")
    item = logged["items"][index]
    if item.get("undone"):
        return m
    if item.get("entry_id"):
        try:
            delete_entry(s, ctx, item["entry_id"])
        except NotFound:
            pass  # deleted already, for example in the edit sheet
    else:
        back = UNDO.get(item.get("timer_action", ""))
        if back is None or (back == "switch" and item["type"] not in ("nursing", "play")):
            raise Invalid("This cannot be undone. Change it on the Home page.")
        try:
            act(s, ctx, m.child_id, item["type"], back, TimerBody())
        except NotFound as err:
            raise Conflict("The timer is not running now. Change it on the Home page.") from err
    item["undone"] = True
    m.logged = logged
    s.commit()
    return m


def save_proposals(s: Session, ctx: Ctx, child_id: int, message_id: int, proposals: list) -> ChatMessage:
    """Confirm the proposals of a chat turn (the parent may remove or change some); an empty list dismisses them."""
    m = _logged_message(s, ctx, child_id, message_id)
    logged = copy.deepcopy(m.logged)
    if proposals:
        logged["items"] += nl_log.commit(s, ctx, m.child_id, proposals)["items"]
        logged["message"] = f"Logged {len(logged['items'])} {'item' if len(logged['items']) == 1 else 'items'}."
    logged["proposals"] = []
    m.logged = logged
    s.commit()
    return m
