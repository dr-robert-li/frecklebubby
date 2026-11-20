"""AI and knowledge routes: NL logging, assistant chat (SSE), sleep plan, insights, LLM test, knowledge sources."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ai import assistant, llm, nl_log, sleep_plan, support_report
from ..auth import get_ctx
from ..db import get_session
from ..knowledge import uploads
from ..services import Ctx, insights
from ..services.children import get_child

router = APIRouter()


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


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut]
    created_at: datetime


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


class LlmTestOut(BaseModel):
    ok: bool
    detail: str
    model: str


@router.post("/children/{cid}/nl/parse", response_model=nl_log.ParseOut, response_model_exclude_none=True,
             summary="Note in plain words → proposals")
async def nl_parse(cid: int, body: nl_log.ParseIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return await nl_log.parse(s, ctx, cid, body.text)


@router.post("/children/{cid}/nl/commit", response_model=nl_log.CommitOut, summary="Save proposals (all or nothing)")
def nl_commit(cid: int, body: nl_log.CommitIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return nl_log.commit(s, ctx, cid, body.proposals)


@router.get("/children/{cid}/assistant/messages", response_model=list[MessageOut])
def messages(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return assistant.list_messages(s, ctx, cid)


@router.delete("/children/{cid}/assistant/messages", status_code=204)
def clear_messages(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    assistant.clear_messages(s, ctx, cid)
    return Response(status_code=204)


@router.post("/children/{cid}/assistant/chat", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}},
             summary="Ask the assistant. Server-Sent Events: token, citations, done, error")
async def chat(cid: int, body: ChatIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    events = assistant.chat(s, ctx, cid, body.message)
    first = await anext(events)  # child check, retrieval and the model connection; errors become JSON (404, 503)

    async def stream():
        yield first
        async for e in events:
            yield e

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/children/{cid}/insights", response_model=list[InsightOut])
def child_insights(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return insights.insights(s, ctx, cid)


@router.get("/children/{cid}/sleep/plan", response_model=SleepPlanOut | None)
def get_sleep_plan(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return sleep_plan.latest(s, ctx, cid)


@router.post("/children/{cid}/sleep/plan", response_model=SleepPlanOut, summary="Make a sleep plan (slow: 30-90 s)")
async def make_sleep_plan(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    get_child(s, ctx, cid)
    return await sleep_plan.generate(s, ctx, cid)


@router.get("/children/{cid}/support-report", response_model=SupportReportOut | None, response_model_by_alias=True)
def get_support_report(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return support_report.latest(s, ctx, cid)


@router.post("/children/{cid}/support-report", response_model=SupportReportOut, response_model_by_alias=True,
             summary="Make a support report (slow with the model: 30-120 s)")
async def make_support_report(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return await support_report.generate(s, ctx, cid)


@router.post("/family/settings/llm-test", response_model=LlmTestOut, summary="Test the model server connection")
async def llm_test(ctx: Ctx = Depends(get_ctx)):
    return await llm.test(ctx.fam)


@router.get("/knowledge/sources", response_model=list[SourceOut])
def sources(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return uploads.list_sources(s, ctx)


@router.post("/knowledge/uploads", response_model=UploadOut, status_code=201,
             summary="Upload a PDF, EPUB, TXT or MD file (max 50 MB). Private to the family.")
async def upload(file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    ctx.fam  # noqa: B018  409 before reading a large body when the user has no family
    data = await file.read(uploads.MAX_BYTES + 1)
    return uploads.upload(s, ctx, file.filename or "", data)


@router.delete("/knowledge/sources/{source_id}", status_code=204)
def delete_source(source_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    uploads.delete_upload(s, ctx, source_id)
    return Response(status_code=204)
