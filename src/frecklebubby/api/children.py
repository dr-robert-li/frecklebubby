"""Children, entries, timers, status, reports, growth, export, milestones, sleep prediction."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..auth import get_ctx
from ..db import get_session, utcnow
from ..schemas import (
    ChildIn,
    ChildOut,
    ChildPatch,
    ConfirmIn,
    DailyReport,
    EntryIn,
    EntryOut,
    EntryPatch,
    EntryType,
    GrowthOut,
    MilestonesOut,
    Prediction,
    RegimeOut,
    Status,
    TimerAction,
    TimerBody,
    TimerOut,
    TimerResult,
    TimerType,
    TrainingIn,
    TrainingNightIn,
    TrainingOut,
)
from ..services import Ctx, children, entries, export, growth, milestones, regime, reports, sleep, timers, training

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


@router.delete("/children/{cid}/permanent", status_code=204, summary=(
    "Delete a child and all its data for good (owner only). `confirm` is the child's name. "
    "This cannot be undone. To hide a child and keep the data, archive it."))
def delete_child(cid: int, body: ConfirmIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    children.delete_child(s, ctx, cid, body.confirm)


# --- entries --------------------------------------------------------------------------------------


@router.get("/children/{cid}/entries", response_model=list[EntryOut], summary="List entries, newest first")
def list_entries(
    cid: int,
    type: list[EntryType] | None = Query(None, description="One type or more. Give the parameter again for each type"),
    start: datetime | None = Query(None, alias="from", description="Entries that start at or after this time"),
    end: datetime | None = Query(None, alias="to", description="Entries that start before this time"),
    limit: int = Query(50, ge=1, le=1000),
    before: datetime | None = Query(None, description="Page cursor: entries that start before this time"),
    sort: Literal["time", "duration", "volume", "weight", "height", "head", "temperature"] = Query(
        "time", description="Order by the start time or by a logged amount. With an amount, entries without it "
                            "are left out"),
    dir: Literal["desc", "asc"] = Query("desc", description="desc: newest or largest first. asc: oldest or smallest first"),
    offset: int = Query(0, ge=0, description="Page cursor for all orders: skip this number of entries"),
    ctx: Ctx = Depends(get_ctx),
    s: Session = Depends(get_session),
):
    return entries.list_entries(s, ctx, cid, type, start, end, limit, before, dir == "desc", sort, offset)


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


@router.get("/children/{cid}/sleep/regime", response_model=RegimeOut,
            summary="The day and night plan: one typical 24 hours, from the child's last 14 days and the age")
def sleep_regime(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return regime.regime(s, children.get_child(s, ctx, cid), ctx.tz)


def _today(ctx: Ctx) -> date:
    return utcnow().astimezone(ctx.tz).date()


@router.get("/children/{cid}/sleep/training", response_model=TrainingOut,
            summary="Sleep training (an option, off by default): the state, the steps for tonight, and the age limits")
def get_training(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return training.out(s, children.get_child(s, ctx, cid), _today(ctx))


@router.put("/children/{cid}/sleep/training", response_model=TrainingOut,
            summary="Start sleep training, or change the pace, the switch, parental presence or pause")
def put_training(cid: int, body: TrainingIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    child = children.get_child(s, ctx, cid)
    usual = regime.regime(s, child, ctx.tz)["usual_bedtime"] if body.method == "fading" else None
    training.save(s, child, body.model_dump(exclude_unset=True), _today(ctx), usual)
    return training.out(s, child, _today(ctx))


@router.post("/children/{cid}/sleep/training/nights", response_model=TrainingOut,
             summary="Report one night of sleep training. With the switch on, the answer moves the scale")
def training_night(cid: int, body: TrainingNightIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    child = children.get_child(s, ctx, cid)
    training.report(s, child, body.model_dump(mode="json"))
    return training.out(s, child, _today(ctx))


@router.delete("/children/{cid}/sleep/training", response_model=TrainingOut, summary="End the sleep training")
def end_training(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    child = children.get_child(s, ctx, cid)
    training.end(s, child)
    return training.out(s, child, _today(ctx))
