"""A user of family A must get 404 on every family B resource."""

from frecklebubby.db import SessionLocal
from frecklebubby.services.notifications import notify

from .conftest import make_family

API = "/api/v1"


async def test_family_isolation(client):
    a, _ = await make_family(client, "a@example.com")
    b, bcid = await make_family(client, "b@example.com", child="Bea")

    entry = (await client.post(f"{API}/children/{bcid}/entries", headers=b,
                               json={"type": "bottle", "started_at": "2026-11-01T10:00:00Z",
                                     "data": {"amount_ml": 100}})).json()
    await client.post(f"{API}/children/{bcid}/timers/sleep/start", headers=b)
    for kind in ("indoorPlay", "tummyTime"):
        await client.post(f"{API}/children/{bcid}/timers/activity/start", headers=b, json={"kind": kind})
    reminder = (await client.post(f"{API}/children/{bcid}/reminders", headers=b,
                                  json={"type": "bottle", "mode": "in", "interval_minutes": 180})).json()
    token = (await client.post(f"{API}/tokens", json={"name": "b"}, headers=b)).json()
    invite = (await client.post(f"{API}/family/invites", json={"email": "c@example.com"}, headers=b)).json()
    with SessionLocal() as s:
        family_b = (await client.get(f"{API}/family", headers=b)).json()["id"]
        note = notify(s, family_b, bcid, "test", "T", "B", "iso-test")
    members_b = (await client.get(f"{API}/family/members", headers=b)).json()

    child_urls = ["", "/entries", "/timers", "/status", "/reports/daily", "/growth", "/export.csv", "/milestones",
                  "/sleep/prediction", "/reminders"]
    for suffix in child_urls:
        r = await client.get(f"{API}/children/{bcid}{suffix}", headers=a)
        assert r.status_code == 404, (suffix, r.text)
    checks = [
        ("PATCH", f"/children/{bcid}", {"name": "x"}),
        ("DELETE", f"/children/{bcid}", None),
        ("POST", f"/children/{bcid}/entries", {"type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "x"}),
        ("POST", f"/children/{bcid}/timers/sleep/complete", None),
        ("POST", f"/children/{bcid}/timers/sleep/cancel", None),
        ("POST", f"/children/{bcid}/timers/activity/start", {"kind": "tummyTime"}),
        ("POST", f"/children/{bcid}/timers/activity/pause", {"kind": "tummyTime"}),
        ("POST", f"/children/{bcid}/timers/activity/complete", {"kind": "indoorPlay"}),
        ("POST", f"/children/{bcid}/timers/activity/cancel", {"kind": "indoorPlay"}),
        ("POST", f"/children/{bcid}/reminders", {"type": "bottle", "mode": "in", "interval_minutes": 60}),
        ("GET", f"/entries/{entry['id']}", None),
        ("PATCH", f"/entries/{entry['id']}", {"notes": "x"}),
        ("DELETE", f"/entries/{entry['id']}", None),
        ("PATCH", f"/reminders/{reminder['id']}", {"enabled": False}),
        ("DELETE", f"/reminders/{reminder['id']}", None),
        ("POST", f"/notifications/{note.id}/read", None),
        ("DELETE", f"/tokens/{token['id']}", None),
        ("DELETE", f"/family/invites/{invite['id']}", None),
        ("DELETE", f"/family/members/{members_b[0]['user_id']}", None),
    ]
    for method, url, body in checks:
        r = await client.request(method, f"{API}{url}", headers=a, json=body)
        assert r.status_code == 404, (method, url, r.text)

    assert (await client.get(f"{API}/notifications", headers=a)).json() == []
    assert (await client.get(f"{API}/tokens", headers=a)).json() == []
    # B's data is untouched.
    assert (await client.get(f"{API}/entries/{entry['id']}", headers=b)).status_code == 200
    assert [(t["type"], t["data"]) for t in (await client.get(f"{API}/children/{bcid}/timers", headers=b)).json()] == [
        ("sleep", {}), ("activity", {"kind": "indoorPlay"}), ("activity", {"kind": "tummyTime"})]
