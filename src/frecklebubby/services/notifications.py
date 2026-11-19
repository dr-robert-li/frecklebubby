"""In-app notifications, push subscriptions and Web Push (VAPID)."""

import base64
import json
import logging
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import Membership, Notification, PushSubscription
from ..schemas import PushSubscriptionIn
from . import Ctx, NotFound

log = logging.getLogger(__name__)


# --- VAPID ----------------------------------------------------------------------------------------


@lru_cache
def _vapid(path: Path) -> Vapid:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        v = Vapid()
        v.generate_keys()
        v.save_key(str(path))
        path.chmod(0o600)
        log.info("Made new VAPID keys in %s", path)
    return Vapid.from_file(str(path))


def vapid() -> Vapid:
    """The server's VAPID key; made on first use in DATA_DIR."""
    return _vapid(get_settings().data_dir.resolve() / "vapid_private.pem")


def vapid_public_key() -> str:
    raw = vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claims() -> dict:
    base = get_settings().base_url
    # Push services want a contact URL or mailto in "sub".
    return {"sub": base if base.startswith("https://") else "mailto:admin@frecklebubby.invalid"}


# --- notifications --------------------------------------------------------------------------------


def list_notifications(s: Session, ctx: Ctx, unread_only: bool = False, limit: int = 50) -> list[Notification]:
    q = select(Notification).where(Notification.family_id == ctx.fam.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return list(s.scalars(q.order_by(Notification.id.desc()).limit(max(1, min(limit, 200)))))


def mark_read(s: Session, ctx: Ctx, notification_id: int) -> Notification:
    n = s.get(Notification, notification_id)
    if n is None or n.family_id != ctx.fam.id:
        raise NotFound("Notification not found.")
    n.read_at = n.read_at or utcnow()
    s.commit()
    return n


def mark_all_read(s: Session, ctx: Ctx) -> None:
    s.execute(update(Notification).where(Notification.family_id == ctx.fam.id, Notification.read_at.is_(None))
              .values(read_at=utcnow()))
    s.commit()


def notify(s: Session, family_id: int, child_id: int | None, kind: str, title: str, body: str,
           dedupe_key: str) -> Notification | None:
    """Save a notification and push it to the family. None if the dedupe_key was used before."""
    if s.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return None
    n = Notification(family_id=family_id, child_id=child_id, kind=kind, title=title, body=body,
                     dedupe_key=dedupe_key)
    s.add(n)
    try:
        s.commit()
    except IntegrityError:  # another worker saved it first
        s.rollback()
        return None
    user_ids = s.scalars(select(Membership.user_id).where(Membership.family_id == family_id)).all()
    send_push(s, user_ids, {"title": title, "body": body, "id": n.id, "child_id": child_id, "kind": kind})
    return n


# --- push -----------------------------------------------------------------------------------------


def subscribe(s: Session, ctx: Ctx, body: PushSubscriptionIn) -> None:
    sub = s.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint)
        s.add(sub)
    # The browser owns the endpoint; the last user who signs in on it gets the pushes.
    sub.user_id, sub.p256dh, sub.auth = ctx.user.id, body.keys.p256dh, body.keys.auth
    s.commit()


def unsubscribe(s: Session, ctx: Ctx, endpoint: str) -> None:
    sub = s.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint,
                                                  PushSubscription.user_id == ctx.user.id))
    if sub is None:
        raise NotFound("Subscription not found.")
    s.delete(sub)
    s.commit()


def send_push(s: Session, user_ids: list[int], payload: dict) -> int:
    """Push to all subscriptions of these users. Drops subscriptions the push service says are gone."""
    if not user_ids:
        return 0
    subs = s.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all()
    sent = 0
    for sub in subs:
        try:
            webpush({"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=json.dumps(payload), vapid_private_key=vapid(), vapid_claims=_claims(), timeout=10)
            sent += 1
        except WebPushException as err:
            code = getattr(err.response, "status_code", None)
            if code in (404, 410):
                s.delete(sub)
            else:
                log.warning("Web Push failed with status %s", code)
        except Exception as err:  # network errors must not stop the reminder loop
            log.warning("Web Push failed: %s", type(err).__name__)
    s.commit()
    return sent


def send_test(s: Session, ctx: Ctx) -> int:
    return send_push(s, [ctx.user.id], {"title": "Frecklebubby", "body": "Push notifications work.",
                                        "kind": "test"})
