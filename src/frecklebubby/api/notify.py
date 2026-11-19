"""Reminders, notifications, push subscriptions."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_ctx
from ..db import get_session
from ..schemas import NotificationOut, PushSubscriptionIn, PushUnsubscribe, ReminderIn, ReminderOut, ReminderPatch
from ..services import Ctx, notifications, reminders

router = APIRouter()


@router.get("/children/{cid}/reminders", response_model=list[ReminderOut])
def list_reminders(cid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return reminders.list_reminders(s, ctx, cid)


@router.post("/children/{cid}/reminders", response_model=ReminderOut, status_code=201)
def create_reminder(cid: int, body: ReminderIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return reminders.create_reminder(s, ctx, cid, body)


@router.patch("/reminders/{rid}", response_model=ReminderOut)
def patch_reminder(rid: int, body: ReminderPatch, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return reminders.update_reminder(s, ctx, rid, body)


@router.delete("/reminders/{rid}", status_code=204)
def delete_reminder(rid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    reminders.delete_reminder(s, ctx, rid)


@router.get("/notifications", response_model=list[NotificationOut], summary="Family notifications, newest first")
def list_notifications(unread: bool = False, limit: int = Query(50, ge=1, le=200),
                       ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return notifications.list_notifications(s, ctx, unread, limit)


@router.post("/notifications/read-all", status_code=204)
def read_all(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    notifications.mark_all_read(s, ctx)


@router.post("/notifications/{nid}/read", response_model=NotificationOut)
def read_one(nid: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return notifications.mark_read(s, ctx, nid)


@router.post("/push/subscriptions", status_code=204)
def subscribe(body: PushSubscriptionIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    notifications.subscribe(s, ctx, body)


@router.delete("/push/subscriptions", status_code=204)
def unsubscribe(body: PushUnsubscribe, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    notifications.unsubscribe(s, ctx, body.endpoint)


@router.post("/push/test")
def push_test(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)) -> dict:
    return {"sent": notifications.send_test(s, ctx)}
