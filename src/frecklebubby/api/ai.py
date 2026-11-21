"""AI and knowledge routes: NL logging, assistant chat (SSE), sleep plan, insights, LLM test, knowledge sources."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from ..ai import assistant, jobs, llm, nl_log, sleep_plan, support_report
from ..auth import ai_limit, get_ctx, upload_limit, voice_limit
from ..db import get_session
from ..knowledge import uploads
from ..services import Ctx, insights, voice
from ..services.children import get_child

router = APIRouter()
HEARTBEAT = 15.0  # seconds between ': ping' lines when a stream has nothing to send (a proxy cuts a quiet stream)


async def heartbeat(events: AsyncIterator[str]) -> AsyncIterator[str]:
    """The events, plus a comment line when no event came for HEARTBEAT seconds."""
    nxt = asyncio.ensure_future(anext(events))
    try:
        while True:
            done, _ = await asyncio.wait({nxt}, timeout=HEARTBEAT)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event = nxt.result()
            except StopAsyncIteration:
                return
            yield event
            nxt = asyncio.ensure_future(anext(events))
    finally:
        nxt.cancel()


class CitationOut(BaseModel):
    n: int
    title: str
    publisher: str | None = None
    author: str | None = None
    url: str | None = None
    year: int | None = None
    kind: Literal["bundled", "link", "upload", "web"]
    licence: str | None = None


class InsightOut(BaseModel):
    kind: str
    severity: Literal["info", "attention", "urgent"]
    title: str
    body: str
    citations: list[CitationOut]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    voice: bool = Field(False, description="A voice command: also save the items that are not sure, with a flag.")


class LoggedItem(BaseModel):
    action: Literal["entry", "timer"]
    type: str
    summary: str
    entry_id: int | None = None
    timer_action: str | None = None
    undone: bool = False
    unsure: str | None = None  # a voice command saved it without a check: why it can be wrong


class LoggedOut(BaseModel):
    items: list[LoggedItem]
    proposals: list[nl_log.Proposal]
    message: str

    @field_validator("proposals", mode="before")
    @classmethod
    def _known(cls, v: list) -> list:
        """A proposal saved before 0.2.2 can name a removed type (play, bath). Leave it out, so the chat still loads."""
        out = []
        for p in v:
            try:
                out.append(nl_log.PROPOSAL.validate_python(p))
            except ValidationError:
                pass
        return out


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut]
    logged: LoggedOut | None = None
    created_at: datetime


class UndoIn(BaseModel):
    item: int = Field(ge=0, description="Index of the item in logged.items.")


class ProposalsIn(BaseModel):
    proposals: list[nl_log.Proposal] = Field(max_length=20, description="The proposals to save; [] dismisses them.")


class ScheduleRow(BaseModel):
    time: str
    kind: Literal["wake", "nap", "feed", "bedtime", "other"]
    label: str
    note: str | None = None


class Advice(BaseModel):
    text: str
    cites: list[int]


class SleepPlanOut(BaseModel):
    id: int
    created_at: datetime
    summary: str
    schedule: list[ScheduleRow]
    advice: list[Advice]
    citations: list[CitationOut]


class Cited(BaseModel):
    text: str
    cites: list[int]


class Number(BaseModel):
    label: str
    value: float
    unit: str  # "" (a count) | h | min | ml | kg | cm | percentile


class AreaOut(BaseModel):
    area: str
    title: str
    status: Literal["ok", "watch", "no_data"]
    compared: bool  # true when the status compares the numbers with a sourced threshold
    numbers: list[Number]
    reference: Cited | None
    note: str | None
    details: list[str]
    suggestions: list[Cited]
    suggested_by: Literal["model", "rules"] | None
    citations: list[CitationOut]


class GoesWell(Cited):
    citations: list[CitationOut]


class SupportReportOut(BaseModel):
    id: int
    created_at: datetime
    days: int
    from_: date = Field(alias="from")
    to: date
    ai: bool
    notice: str | None
    urgent: list[InsightOut]
    blocks: list[AreaOut]
    goes_well: GoesWell
    footer: str


class SourceOut(BaseModel):
    id: int
    kind: str
    title: str
    author: str | None
    publisher: str | None
    url: str | None
    licence: str | None
    year: int | None
    own: bool


class UploadOut(SourceOut):
    chunks: int


class JobOut(BaseModel):
    status: Literal["none", "running", "done", "failed"]
    error: str | None


class HeardOut(BaseModel):
    heard: bool  # false: no words, or (with wake) the words do not start with the keyword
    text: str  # the words; with wake, the words after the keyword


class LlmTestOut(BaseModel):
    ok: bool
    detail: str
    model: str


@router.post("/children/{cid}/nl/parse", response_model=nl_log.ParseOut, response_model_exclude_none=True,
             summary="Note in plain words → proposals", dependencies=[Depends(ai_limit)])
async def nl_parse(cid: int, body: nl_log.ParseIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return await nl_log.parse(s, ctx, cid, body.text)


@router.post("/children/{cid}/nl/commit", response_model=nl_log.CommitOut, summary="Save proposals (all or nothing)")
def nl_commit(cid: int, body: nl_log.CommitIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return nl_log.commit(s, ctx, cid, body.proposals)


@router.get("/children/{cid}/assistant/messages", response_model=list[MessageOut])
def messages(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return assistant.list_messages(s, ctx, cid)


@router.post("/children/{cid}/assistant/messages/{mid}/undo", response_model=MessageOut,
             summary="Undo one item of a chat turn's Logged block")
def undo_logged(cid: int, mid: int, body: UndoIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return assistant.undo(s, ctx, cid, mid, body.item)


@router.post("/children/{cid}/assistant/messages/{mid}/proposals", response_model=MessageOut,
             summary="Save (or with [] dismiss) the proposals of a chat turn")
def save_logged(cid: int, mid: int, body: ProposalsIn, ctx: Ctx = Depends(get_ctx),
                s: Session = Depends(get_session)):
    return assistant.save_proposals(s, ctx, cid, mid, body.proposals)


@router.delete("/children/{cid}/assistant/messages", status_code=204)
def clear_messages(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    assistant.clear_messages(s, ctx, cid)
    return Response(status_code=204)


@router.post("/children/{cid}/assistant/chat", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}},
             summary="Ask the assistant. Server-Sent Events: waiting, logged, token, citations, done, error. "
                     "A comment line (': ping') comes at least every 15 s, also while the request waits for the model.",
             dependencies=[Depends(ai_limit)])
async def chat(cid: int, body: ChatIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    events = assistant.chat(s, ctx, cid, body.message, body.voice)
    # child check, retrieval and the model connection (or "waiting"); errors become JSON (404, 429, 503)
    first = await anext(events)

    async def stream():
        yield first
        async for e in heartbeat(events):
            yield e

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/children/{cid}/insights", response_model=list[InsightOut])
def child_insights(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return insights.insights(s, ctx, cid)


@router.get("/children/{cid}/sleep/plan", response_model=SleepPlanOut | None)
def get_sleep_plan(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return sleep_plan.latest(s, ctx, cid)


@router.post("/children/{cid}/sleep/plan", response_model=JobOut, status_code=202, dependencies=[Depends(ai_limit)],
             summary="Start a new sleep plan (30-90 s). Poll GET .../sleep/plan/job, then read GET .../sleep/plan")
async def make_sleep_plan(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    get_child(s, ctx, cid)
    return jobs.start("sleep_plan", ctx, cid, sleep_plan.generate)


@router.get("/children/{cid}/sleep/plan/job", response_model=JobOut, summary="State of the last sleep plan job")
def sleep_plan_job(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    get_child(s, ctx, cid)
    return jobs.get("sleep_plan", cid)


@router.get("/children/{cid}/support-report", response_model=SupportReportOut | None, response_model_by_alias=True)
def get_support_report(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return support_report.latest(s, ctx, cid)


@router.post("/children/{cid}/support-report", response_model=JobOut, status_code=202,
             dependencies=[Depends(ai_limit)], summary=(
                 "Start a new support report (with the model: 30-120 s). Poll GET .../support-report/job, then read "
                 "GET .../support-report"))
async def make_support_report(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    get_child(s, ctx, cid)
    return jobs.start("support_report", ctx, cid, support_report.generate)


@router.get("/children/{cid}/support-report/job", response_model=JobOut, summary="State of the last support report job")
def support_report_job(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    get_child(s, ctx, cid)
    return jobs.get("support_report", cid)


@router.post("/family/settings/llm-test", response_model=LlmTestOut, summary="Test the model server connection",
             dependencies=[Depends(ai_limit)])
async def llm_test(ctx: Ctx = Depends(get_ctx)):
    return await llm.test(ctx.fam)


@router.post("/voice/transcribe", response_model=HeardOut, dependencies=[Depends(voice_limit)],
             summary="Speech to text for a voice command. WAV: one channel, 16 bit, 16 kHz, max 30 s. With wake: "
                     "only text that starts with \"Hey Bubby\" or \"OK Bubby\" comes back. The audio is not stored.")
async def transcribe(file: UploadFile = File(...), wake: bool = Form(False), ctx: Ctx = Depends(get_ctx)):
    ctx.fam  # noqa: B018  409 for a user with no family
    data = await file.read(voice.MAX_BYTES + 1)
    if len(data) > voice.MAX_BYTES:
        raise voice.Invalid("The recording is too long. The limit is 30 seconds.")
    text = await run_in_threadpool(voice.transcribe, data)
    if wake:
        command = voice.wake(text)
        return {"heard": command is not None, "text": command or ""}
    return {"heard": bool(text), "text": text}


@router.get("/knowledge/sources", response_model=list[SourceOut])
def sources(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return uploads.list_sources(s, ctx)


@router.post("/knowledge/uploads", response_model=UploadOut, status_code=201,
             summary="Upload a PDF, EPUB, TXT or MD file (max 50 MB). Private to the family.",
             dependencies=[Depends(upload_limit)])
async def upload(file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    ctx.fam  # noqa: B018  409 before reading a large body when the user has no family
    data = await file.read(uploads.MAX_BYTES + 1)
    return uploads.upload(s, ctx, file.filename or "", data)


@router.delete("/knowledge/sources/{source_id}", status_code=204)
def delete_source(source_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    uploads.delete_upload(s, ctx, source_id)
    return Response(status_code=204)
