from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from frecklebubby.db import SessionLocal
from frecklebubby.models import Entry, PushSubscription
from frecklebubby.services import notifications
from frecklebubby.services.reminders import tick

from .conftest import make_family

BNE = ZoneInfo("Australia/Brisbane")
API = "/api/v1"
SUB = {"endpoint": "https://push.example.test/abc", "keys": {"p256dh": "BPk", "auth": "au"}}


def local(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=BNE)


def run(now) -> int:
    with SessionLocal() as s:
        return tick(s, now)


async def test_in_mode_fires_once_and_pushes(client, pushes):
    h, cid = await make_family(client)
    await client.post(f"{API}/push/subscriptions", headers=h, json=SUB)
    r = await client.post(f"{API}/children/{cid}/reminders", headers=h,
                          json={"type": "nappy", "mode": "in", "interval_minutes": 180})
    assert r.status_code == 201
    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "nappy", "started_at": "2026-11-10T09:00:00", "data": {"mode": "pee"}})

    assert run(local(10, 11, 59)) == 0
    assert run(local(10, 12, 0)) == 1
    assert run(local(10, 12, 1)) == 0  # dedupe: once per last entry
    notes = (await client.get(f"{API}/notifications", headers=h)).json()
    assert len(notes) == 1
    assert notes[0]["title"] == "Ada: nappy time"
    assert notes[0]["body"] == "The last nappy was 3 h 0 min ago."
    assert len(pushes) == 1 and pushes[0][0]["endpoint"] == SUB["endpoint"]
    assert (await client.get(f"{API}/children/{cid}/status", headers=h)).json()["unread_notifications"] == 1

    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "nappy", "started_at": "2026-11-10T12:30:00", "data": {"mode": "poo"}})
    assert run(local(10, 15, 30)) == 1  # new last entry, new notification

    await client.post(f"{API}/notifications/{notes[0]['id']}/read", headers=h)
    assert len((await client.get(f"{API}/notifications?unread=true", headers=h)).json()) == 1
    await client.post(f"{API}/notifications/read-all", headers=h)
    assert (await client.get(f"{API}/notifications?unread=true", headers=h)).json() == []


async def test_wording_diaper(client):
    h, cid = await make_family(client)
    await client.patch(f"{API}/family/settings", headers=h, json={"wording": "diaper"})
    await client.post(f"{API}/children/{cid}/reminders", headers=h,
                      json={"type": "nappy", "mode": "in", "interval_minutes": 60})
    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "nappy", "started_at": "2026-11-10T09:00:00", "data": {"mode": "pee"}})
    run(local(10, 10, 30))
    assert (await client.get(f"{API}/notifications", headers=h)).json()[0]["title"] == "Ada: diaper time"


async def test_at_mode_days_and_daytime(client):
    h, cid = await make_family(client)
    # 2026-11-10 is a Tuesday (weekday 1).
    await client.post(f"{API}/children/{cid}/reminders", headers=h,
                      json={"type": "medicine", "mode": "at", "times": ["08:00", "20:00"], "days": [1, 2]})
    r = await client.post(f"{API}/children/{cid}/reminders", headers=h,
                          json={"type": "bottle", "mode": "at", "times": ["20:00"], "daytime_only": True})
    assert r.status_code == 201
    assert run(local(10, 7, 59)) == 0
    assert run(local(10, 8, 0)) == 1
    assert run(local(10, 8, 5)) == 0
    assert run(local(10, 20, 20)) == 0  # past the 15 minute grace; bottle skipped at night
    assert run(local(11, 20, 1)) == 1   # medicine only; the bottle reminder is in the night
    assert run(local(12, 8, 0)) == 0    # Thursday is not in days
    bad = await client.post(f"{API}/children/{cid}/reminders", headers=h, json={"type": "bottle", "mode": "at"})
    assert bad.status_code == 422


async def test_sleep_alert(client):
    h, cid = await make_family(client, birthdate="2026-06-01")
    await client.post(f"{API}/children/{cid}/reminders", headers=h,
                      json={"type": "sleep_alert", "mode": "in", "interval_minutes": 10})
    with SessionLocal() as s:
        s.add(Entry(child_id=cid, type="sleep", started_at=local(10, 8), ended_at=local(10, 9), data={}))
        s.commit()
    # Age default 90-150 -> 120 min -> window 10:45-11:15; alert from 10:35.
    assert run(local(10, 10, 34)) == 0
    assert run(local(10, 10, 35)) == 1
    assert run(local(10, 10, 50)) == 0
    note = (await client.get(f"{API}/notifications", headers=h)).json()[0]
    assert note["body"] == "The next sleep window starts at 10:45."


async def test_disabled_and_gone_subscription(client, monkeypatch):
    h, cid = await make_family(client)
    await client.post(f"{API}/push/subscriptions", headers=h, json=SUB)
    rid = (await client.post(f"{API}/children/{cid}/reminders", headers=h,
                             json={"type": "bottle", "mode": "in", "interval_minutes": 60})).json()["id"]
    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "bottle", "started_at": "2026-11-10T09:00:00", "data": {"amount_ml": 90}})
    await client.patch(f"{API}/reminders/{rid}", headers=h, json={"enabled": False})
    assert run(local(10, 11)) == 0
    await client.patch(f"{API}/reminders/{rid}", headers=h, json={"enabled": True})

    class Gone:
        status_code = 410

    def gone(sub, **kw):
        raise notifications.WebPushException("gone", response=Gone())

    monkeypatch.setattr(notifications, "webpush", gone)
    assert run(local(10, 11)) == 1
    with SessionLocal() as s:
        assert s.scalar(select(PushSubscription)) is None


async def test_push_test_endpoint(client, pushes):
    h, _ = await make_family(client)
    assert (await client.post(f"{API}/push/test", headers=h)).json() == {"sent": 0}
    await client.post(f"{API}/push/subscriptions", headers=h, json=SUB)
    assert (await client.post(f"{API}/push/test", headers=h)).json() == {"sent": 1}
    r = await client.request("DELETE", f"{API}/push/subscriptions", headers=h, json={"endpoint": SUB["endpoint"]})
    assert r.status_code == 204
    assert (await client.get(f"{API}/config")).json()["vapid_public_key"]
