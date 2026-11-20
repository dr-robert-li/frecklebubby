"""M16: delete the family, delete the account."""

from sqlalchemy import select, text

from frecklebubby.config import get_settings
from frecklebubby.db import SessionLocal
from frecklebubby.models import Entry, ImportJob, User
from frecklebubby.services.notifications import notify

from .conftest import as_user, make_family, run_job
from .fake_llm import fake_llm_fixture  # noqa: F401

API = "/api/v1"
PLAN = {"summary": "Plan.", "schedule": [{"time": "07:00", "kind": "wake", "label": "Wake up"}], "advice": []}


def dump() -> dict[str, set[tuple]]:
    """Every row of every table (kb_chunk rows too; not the internal FTS tables)."""
    with SessionLocal() as s:
        names = s.scalars(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                               "AND name NOT LIKE 'kb_chunk_%'")).all()
        return {n: set(s.execute(text(f'SELECT * FROM "{n}"')).all()) for n in names}


def files() -> set[str]:
    root = get_settings().data_dir
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm"))}


async def fill(client, fake_llm, email: str, child: str) -> tuple[dict, int]:
    """A family with a row in each table that can hold family data."""
    h, cid = await make_family(client, email, child=child)
    c = f"{API}/children/{cid}"
    await client.post(f"{c}/entries", headers=h, json={"type": "bottle", "started_at": "2026-11-01T10:00:00Z",
                                                        "data": {"amount_ml": 100}})
    await client.post(f"{c}/timers/sleep/start", headers=h)
    await client.post(f"{c}/reminders", headers=h, json={"type": "bottle", "mode": "in", "interval_minutes": 180})
    await client.post(f"{API}/tokens", headers=h, json={"name": "t"})
    await client.post(f"{API}/push/subscriptions", headers=h,
                      json={"endpoint": f"https://push.example/{email}", "keys": {"p256dh": "p", "auth": "a"}})
    await client.post(f"{API}/family/invites", headers=h, json={"email": f"waiting-{email}"})
    files_ = {"file": ("own.md", f"# Own notes {child}\n\nSleep text.".encode(), "text/markdown")}
    assert (await client.post(f"{API}/knowledge/uploads", headers=h, files=files_)).status_code == 201
    fake_llm.replies += ["About 6 a day [1].", PLAN]
    await client.post(f"{c}/assistant/chat", headers=h, json={"message": "how many wet nappies is normal"})
    assert (await run_job(client, h, f"{c}/sleep/plan"))[0] == "done"
    assert (await run_job(client, h, f"{c}/support-report"))[0] == "done"
    with SessionLocal() as s:
        fid = (await client.get(f"{API}/family", headers=h)).json()["id"]
        notify(s, fid, cid, "test", "T", "B", f"key-{email}")
        s.add(ImportJob(family_id=fid, status="done"))
        s.commit()
    return h, cid


async def test_delete_family_leaves_no_row_and_keeps_the_other(client, fake_llm):
    await fill(client, fake_llm, "b@example.com", "Bea")
    before, before_files = dump(), files()

    h, _ = await fill(client, fake_llm, "a@example.com", "Ada")
    carer = as_user("carer@example.com")
    await client.post(f"{API}/family/invites", headers=h, json={"email": "carer@example.com"})
    assert (await client.get(f"{API}/me", headers=carer)).json()["role"] == "carer"
    await client.post(f"{API}/tokens", headers=carer, json={"name": "carer"})
    name = (await client.get(f"{API}/family", headers=h)).json()["name"]

    r = await client.request("DELETE", f"{API}/family", headers=h, json={"confirm": "wrong"})
    assert r.status_code == 422 and "family name" in r.json()["detail"]
    assert (await client.request("DELETE", f"{API}/family", headers=carer, json={"confirm": name})).status_code == 403
    assert (await client.request("DELETE", f"{API}/family", headers=h, json={"confirm": f" {name.upper()} "})
            ).status_code == 204

    after = dump()
    users = after.pop("user") - before.pop("user")
    assert {u.email for u in users} == {"a@example.com", "carer@example.com"}  # accounts stay, without a family
    assert after == before  # no row of family A is left, and no row of family B changed
    assert files() == before_files
    me = (await client.get(f"{API}/me", headers=h)).json()
    assert me["family"] is None and me["children"] == []


async def test_delete_child_removes_only_that_child(client, fake_llm):
    h, keep = await fill(client, fake_llm, "a@example.com", "Ada")
    carer = as_user("carer@example.com")
    await client.post(f"{API}/family/invites", headers=h, json={"email": "carer@example.com"})
    assert (await client.get(f"{API}/me", headers=carer)).json()["role"] == "carer"
    other, _ = await make_family(client, email="other@example.com")
    before = dump()

    r = await client.post(f"{API}/children", headers=h, json={"name": "Twin", "birthdate": "2026-06-01", "sex": "F"})
    twin = r.json()["id"]
    await client.post(f"{API}/children/{twin}/entries", headers=h, json={"type": "nappy", "data": {"mode": "pee"}})
    await client.post(f"{API}/children/{twin}/timers/sleep/start", headers=h)
    assert dump() != before
    url = f"{API}/children/{twin}/permanent"

    r = await client.request("DELETE", url, headers=h, json={"confirm": "Ada"})
    assert r.status_code == 422 and "child's name" in r.json()["detail"]
    assert (await client.request("DELETE", url, headers=carer, json={"confirm": "Twin"})).status_code == 403
    assert (await client.request("DELETE", url, headers=other, json={"confirm": "Twin"})).status_code == 404
    assert (await client.request("DELETE", url, headers=h, json={"confirm": " twin "})).status_code == 204

    assert dump() == before  # no row of the deleted child is left, and no other row changed
    assert [c["id"] for c in (await client.get(f"{API}/me", headers=h)).json()["children"]] == [keep]


async def test_delete_family_refused_while_import_runs(client, monkeypatch):
    h, _ = await make_family(client)
    with SessionLocal() as s:
        fid = (await client.get(f"{API}/family", headers=h)).json()["id"]
        s.add(ImportJob(family_id=fid, status="running"))
        s.commit()
    from frecklebubby.importer import huckleberry

    monkeypatch.setattr(huckleberry, "_recover", lambda s: None)  # the job counts as alive in this process
    r = await client.request("DELETE", f"{API}/family", headers=h, json={"confirm": "Family a@example.com"})
    assert r.status_code == 409 and "import is running" in r.json()["detail"]


async def test_delete_account(client, fake_llm):
    h, cid = await make_family(client)
    carer = as_user("carer@example.com")
    await client.post(f"{API}/family/invites", headers=h, json={"email": "carer@example.com"})
    await client.get(f"{API}/me", headers=carer)
    entry = (await client.post(f"{API}/children/{cid}/entries", headers=carer,
                               json={"type": "nappy", "started_at": "2026-11-01T10:00:00Z", "data": {"mode": "pee"}}
                               )).json()
    await client.post(f"{API}/tokens", headers=carer, json={"name": "carer"})

    # the owner of a family with other members must hand over or delete the family first
    r = await client.request("DELETE", f"{API}/me", headers=h, json={"confirm": "a@example.com"})
    assert r.status_code == 409 and "Make another carer the owner" in r.json()["detail"]
    assert (await client.request("DELETE", f"{API}/me", headers=carer, json={"confirm": "x@example.com"})
            ).status_code == 422

    assert (await client.request("DELETE", f"{API}/me", headers=carer, json={"confirm": "Carer@Example.com"})
            ).status_code == 204
    with SessionLocal() as s:
        assert s.scalar(select(User).where(User.email == "carer@example.com")) is None
        kept = s.get(Entry, entry["id"])
        assert kept.created_by is None and kept.data["mode"] == "pee"  # the entry stays, without its author
        assert s.execute(text("SELECT count(*) FROM api_token")).scalar() == 0
    assert [m["email"] for m in (await client.get(f"{API}/family/members", headers=h)).json()] == ["a@example.com"]

    # hand over the family, then the old owner can go
    await client.post(f"{API}/family/invites", headers=h, json={"email": "c2@example.com"})
    c2 = as_user("c2@example.com")
    uid = (await client.get(f"{API}/me", headers=c2)).json()["user"]["id"]
    assert (await client.post(f"{API}/family/members/{uid}/owner", headers=c2)).status_code == 403
    assert (await client.post(f"{API}/family/members/{uid}/owner", headers=h)).status_code == 204
    assert (await client.get(f"{API}/me", headers=h)).json()["role"] == "carer"
    assert (await client.request("DELETE", f"{API}/me", headers=h, json={"confirm": "a@example.com"})
            ).status_code == 204
    assert (await client.get(f"{API}/children/{cid}", headers=c2)).status_code == 200

    # the only member: the family goes with the account
    assert (await client.request("DELETE", f"{API}/me", headers=c2, json={"confirm": "c2@example.com"})
            ).status_code == 204
    tables = dump()
    assert not tables["family"] and not tables["child"] and not tables["entry"] and not tables["membership"]
