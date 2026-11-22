"""Cry helper routes."""

from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_ctx, upload_limit
from ..db import get_session
from ..services import Ctx, cry
from .ai import CitationOut, InsightOut

router = APIRouter(tags=["cry"])


class Need(BaseModel):
    need: str
    score: float
    why: str
    citations: list[CitationOut]


class Reason(BaseModel):
    label: str
    probability: float


class Sound(BaseModel):
    installed: bool
    is_cry: bool
    cry_seconds: float
    snore_seconds: float
    reasons: list[Reason]
    experimental: Literal[True]
    reliability: str


class Suggestion(BaseModel):
    kind: Literal["try", "help"]
    text: str
    citations: list[CitationOut]


class Combined(BaseModel):
    need: str
    why: str


class CryHelpOut(BaseModel):
    sound: Sound
    likely_needs: list[Need]
    suggestions: list[Suggestion]
    urgent: list[InsightOut]
    combined: list[Combined]


@router.get("/children/{cid}/cry/help", response_model=CryHelpOut,
            summary="What to check when the baby cries, from the logs (no audio)")
def cry_help(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return cry.help(s, ctx, cid)


@router.post("/children/{cid}/cry/analyze", response_model=CryHelpOut, summary=(
    "Same as /cry/help, plus an experimental guess from a short recording (multipart field `audio`, at most "
    "10 s and 10 MB). The audio is analysed on this server and not stored."), dependencies=[Depends(upload_limit)])
async def cry_analyze(cid: int, audio: UploadFile = File(...), ctx: Ctx = Depends(get_ctx),
                      s: Session = Depends(get_session)):
    ctx.fam  # noqa: B018  409 before reading the body when the user has no family
    data = await audio.read(cry.MAX_BYTES + 1)
    return await run_in_threadpool(cry.analyze, s, ctx, cid, data, audio.content_type or "")
