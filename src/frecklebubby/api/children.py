"""Children, entries, timers, status, reports, growth, export, milestones, sleep prediction."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..auth import get_ctx
from ..db import get_session, utcnow
from ..schemas import (
    ChildIn,
    ChildOut,
    ChildPatch,
    DailyReport,
    EntryIn,
    EntryOut,
    EntryPatch,
    EntryType,
    GrowthOut,
    MilestonesOut,
    Prediction,
    Status,
    TimerAction,
    TimerBody,
    TimerOut,
    TimerResult,
    TimerType,
)
from ..services import Ctx, children, entries, export, growth, milestones, reports, sleep, timers

router = APIRouter()


@router.get("/children", response_model=list[ChildOut])
def list_children(archived: bool = False, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return children.list_children(s, ctx, include_archived=archived)


@router.post("/children", response_model=ChildOut, status_code=201)
def create_child(body: ChildIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return children.create_child(s, ctx, body)


@router.get("/children/{cid}", response_model=ChildOut)
def get_child(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return children.get_child(s, ctx, cid)


@router.patch("/children/{cid}", response_model=ChildOut)
def patch_child(cid: int, body: ChildPatch, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return children.update_child(s, ctx, cid, body)


@router.delete("/children/{cid}", status_code=204, summary="Archive a child")
def archive_child(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    children.archive_child(s, ctx, cid)


# --- entries --------------------------------------------------------------------------------------


@router.get("/children/{cid}/entries", response_model=list[EntryOut], summary="List entries, newest first")
def list_entries(
    cid: int,
    type: EntryType | None = None,
    start: datetime | None = Query(None, alias="from", description="Entries that start at or after this time"),
    end: datetime | None = Query(None, alias="to", description="Entries that start before this time"),
    limit: int = Query(50, ge=1, le=1000),
    before: datetime | None = Query(None, description="Page cursor: entries that start before this time"),
    ctx: Ctx = Depends(get_ctx),
    s: Session = Depends(get_session),
):
    return entries.list_entries(s, ctx, cid, type, start, end, limit, before)


@router.post("/children/{cid}/entries", response_model=EntryOut, status_code=201)
def create_entry(cid: int, body: EntryIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return entries.create_entry(s, ctx, cid, body)


@router.get("/entries/{eid}", response_model=EntryOut)
def get_entry(eid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return entries.get_entry(s, ctx, eid)


@router.patch("/entries/{eid}", response_model=EntryOut)
def patch_entry(eid: int, body: EntryPatch, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return entries.update_entry(s, ctx, eid, body)


@router.delete("/entries/{eid}", status_code=204)
def delete_entry(eid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    entries.delete_entry(s, ctx, eid)


# --- timers ---------------------------------------------------------------------------------------


@router.get("/children/{cid}/timers", response_model=list[TimerOut])
def list_timers(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    child = children.get_child(s, ctx, cid)
    now = utcnow()
    return [timers.timer_out(t, now) for t in timers.list_timers(s, child.id)]


@router.post("/children/{cid}/timers/{type}/{action}", response_model=TimerResult)
def timer_action(cid: int, type: TimerType, action: TimerAction, body: TimerBody | None = None,
                 ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    now = utcnow()
    timer, entry = timers.act(s, ctx, cid, type, action, body or TimerBody(), now)
    return {"timer": timers.timer_out(timer, now) if timer else None, "entry": entry}


# --- views ----------------------------------------------------------------------------------------


@router.get("/children/{cid}/status", response_model=Status)
def status(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return reports.status(s, ctx, cid)


@router.get("/children/{cid}/reports/daily", response_model=DailyReport)
def daily_report(
    cid: int,
    start: date | None = Query(None, alias="from", description="First local day. Default: 6 days before `to`."),
    end: date | None = Query(None, alias="to", description="Last local day. Default: today."),
    ctx: Ctx = Depends(get_ctx),
    s: Session = Depends(get_session),
):
    return reports.daily(s, ctx, cid, start, end)


@router.get("/children/{cid}/growth", response_model=GrowthOut)
def child_growth(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return growth.growth(s, ctx, cid)


@router.get("/children/{cid}/export.csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}})
def export_csv(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    name, text = export.export_csv(s, ctx, cid)
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/children/{cid}/milestones", response_model=MilestonesOut)
def child_milestones(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return milestones.milestones(s, ctx, cid)


@router.get("/children/{cid}/sleep/prediction", response_model=Prediction | None)
def sleep_prediction(
    cid: int,
    default: bool = Query(False, description="With no sleep in the last 24 h, give the age default from now."),
    ctx: Ctx = Depends(get_ctx),
    s: Session = Depends(get_session),
):
    return sleep.predict(s, children.get_child(s, ctx, cid), ctx.tz, default=default)
