"""A user of family A must get 404 on every family B resource."""

import string

from frecklebubby.db import SessionLocal
from frecklebubby.models import ChatMessage, ImportJob
from frecklebubby.services.notifications import notify

from .conftest import api_routes, make_family

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
                  "/sleep/prediction", "/sleep/regime", "/reminders"]
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


# --- M15: every route, built from the app's route list ---------------------------------------------

# Routes with no id: they act on the caller's own user or family, so there is no id of another family to give.
OWN = {
    ("GET", "/health"), ("GET", "/config"), ("GET", "/me"), ("DELETE", "/me"), ("POST", "/families"),
    ("GET", "/family"), ("PATCH", "/family"), ("DELETE", "/family"), ("GET", "/family/settings"),
    ("PATCH", "/family/settings"), ("GET", "/family/members"), ("GET", "/family/invites"),
    ("POST", "/family/invites"), ("GET", "/tokens"), ("POST", "/tokens"), ("GET", "/children"),
    ("POST", "/children"), ("GET", "/notifications"), ("POST", "/notifications/read-all"),
    ("POST", "/push/subscriptions"), ("DELETE", "/push/subscriptions"), ("POST", "/push/test"),
    ("POST", "/family/settings/llm-test"), ("GET", "/knowledge/sources"), ("POST", "/knowledge/uploads"),
    ("POST", "/import/huckleberry"), ("POST", "/voice/transcribe"),
}
# M17: operator routes; a user who is not an operator gets 404.
OPERATOR = {("GET", "/operator/invites"), ("POST", "/operator/invites"), ("DELETE", "/operator/invites/{invite_id}"),
            ("GET", "/operator/families")}
# A request body, so that the route reaches its family check (else the answer is 422).
BODIES = {
    ("PATCH", "/children/{cid}"): {"name": "x"},
    ("DELETE", "/children/{cid}/permanent"): {"confirm": "Bea"},
    ("POST", "/children/{cid}/entries"): {"type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "x"},
    ("POST", "/children/{cid}/reminders"): {"type": "bottle", "mode": "in", "interval_minutes": 60},
    ("PATCH", "/entries/{eid}"): {"notes": "x"},
    ("PATCH", "/reminders/{rid}"): {"enabled": False},
    ("POST", "/children/{cid}/nl/parse"): {"text": "a wet nappy"},
    ("POST", "/children/{cid}/nl/commit"): {"proposals": [
        {"action": "entry", "type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "x"}]},
    ("POST", "/children/{cid}/assistant/messages/{mid}/undo"): {"item": 0},
    ("POST", "/children/{cid}/assistant/messages/{mid}/proposals"): {"proposals": []},
    ("POST", "/children/{cid}/assistant/chat"): {"message": "how many wet nappies is normal"},
    ("POST", "/operator/invites"): {"email": "x@example.com"},
}
FILES = {("POST", "/children/{cid}/cry/analyze"): {"audio": ("a.webm", b"x", "audio/webm")}}


async def test_every_route_keeps_families_apart(app, client):
    """Each route with an id of family B, called by a user of family A, gives 404 (403 where the route already
    does) and never B's data. A new route must be added here, else this test fails."""
    a, _ = await make_family(client, "a@example.com")
    b, bcid = await make_family(client, "b@example.com", child="Bea")
    c = f"{API}/children/{bcid}"
    entry = (await client.post(f"{c}/entries", headers=b, json={"type": "bottle", "started_at": "2026-11-01T10:00:00Z",
                                                                  "data": {"amount_ml": 100}})).json()
    await client.post(f"{c}/timers/sleep/start", headers=b)
    reminder = (await client.post(f"{c}/reminders", headers=b,
                                  json={"type": "bottle", "mode": "in", "interval_minutes": 180})).json()
    token = (await client.post(f"{API}/tokens", json={"name": "b"}, headers=b)).json()
    invite = (await client.post(f"{API}/family/invites", json={"email": "c@example.com"}, headers=b)).json()
    upload = (await client.post(f"{API}/knowledge/uploads", headers=b, files={
        "file": ("bea.md", b"# Bea notes\n\nBea sleeps well.", "text/markdown")})).json()
    family_b = (await client.get(f"{API}/family", headers=b)).json()["id"]
    with SessionLocal() as s:
        note = notify(s, family_b, bcid, "test", "T", "Bea", "iso-every")
        msg = ChatMessage(child_id=bcid, role="assistant", content="Bea", citations=[])
        job = ImportJob(family_id=family_b, status="done")
        s.add_all([msg, job])
        s.commit()
        ids = {"cid": bcid, "eid": entry["id"], "rid": reminder["id"], "nid": note.id, "token_id": token["id"],
               "invite_id": invite["id"], "user_id": (await client.get(f"{API}/me", headers=b)).json()["user"]["id"],
               "mid": msg.id, "source_id": upload["id"], "job_id": job.id, "type": "sleep", "action": "complete"}

    missing, leaks = [], []
    for method, path in sorted(api_routes(app)):
        route = path.removeprefix(API)
        if not path.startswith(API) or method == "HEAD":
            continue
        params = {f for _, f, _, _ in string.Formatter().parse(route) if f}
        if (method, route) in OPERATOR:
            pass
        elif not params:
            if (method, route) not in OWN:
                missing.append(f"{method} {route}: no id; if it acts only on the caller's own family, add it to OWN")
            continue
        elif params - ids.keys():
            missing.append(f"{method} {route}: unknown id {params - ids.keys()}; make a family B row and add it to ids")
            continue
        key = (method, route)
        r = await client.request(method, f"{API}{route.format(**ids)}", headers=a, json=BODIES.get(key),
                                 files=FILES.get(key))
        if r.status_code not in (403, 404) or "Bea" in r.text:
            leaks.append(f"{method} {route}: {r.status_code} {r.text[:120]} (add a body to BODIES if it is 422)")
    assert not missing, "Routes not covered by the isolation test:\n" + "\n".join(missing)
    assert not leaks, "Routes that answer a user of another family:\n" + "\n".join(leaks)
    # B's data is still there.
    assert (await client.get(f"{c}/entries", headers=b)).json()[0]["id"] == entry["id"]
    assert (await client.get(f"{API}/tokens", headers=b)).json()[0]["id"] == token["id"]
