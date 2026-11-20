"""Huckleberry import: jobs, idempotency, isolation, password safety, restart recovery, 501."""

import asyncio
import copy
import json
import logging
import sys
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("huckleberry_api")

from frecklebubby.config import get_settings  # noqa: E402
from frecklebubby.db import SessionLocal  # noqa: E402
from frecklebubby.importer import fake, huckleberry  # noqa: E402
from frecklebubby.models import Entry, ImportJob  # noqa: E402

from .conftest import as_user, make_family  # noqa: E402

PASSWORD = "Zq7-very-secret-pw-91"
EXPECTED = {"sleep": 12, "nursing": 12, "bottle": 6, "nappy": 11, "potty": 1, "activity": 6, "pump": 3, "solids": 3,
            "growth": 2, "temperature": 2, "medicine": 2}


@pytest.fixture
def hb(monkeypatch):
    """A fake account whose rows a test can change. Returns the FakeHuckleberry."""
    client = fake.FakeHuckleberry(copy.deepcopy(fake.ROWS))

    @asynccontextmanager
    async def factory(email, password, timezone):
        if password == fake.WRONG_PASSWORD:
            raise huckleberry.SignInFailed
        yield client

    monkeypatch.setattr(huckleberry, "client_factory", factory)
    return client


async def start(client, h, password=PASSWORD):
    return await client.post("/api/v1/import/huckleberry", headers=h,
                             json={"email": "parent@example.com", "password": password,
                                   "timezone": "Australia/Brisbane"})


async def finish(client, h, job_id):
    for _ in range(500):
        r = await client.get(f"/api/v1/import/jobs/{job_id}", headers=h)
        assert r.status_code == 200, r.text
        if r.json()["status"] in ("done", "failed"):
            return r.json()
        await asyncio.sleep(0.01)
    raise AssertionError("import did not finish")


async def run_import(client, h, password=PASSWORD):
    r = await start(client, h, password)
    assert r.status_code == 202, r.text
    return await finish(client, h, r.json()["job_id"])


def imported_entries():
    with SessionLocal() as s:
        return list(s.query(Entry).filter(Entry.source == "import"))


async def test_import_and_reimport(client, hb):
    h, own_child = await make_family(client)
    job = await run_import(client, h)
    assert job["status"] == "done", job
    assert job["error"] is None
    assert job["progress"]["children"] == 2 and job["progress"]["skipped"] == 0
    assert job["progress"]["entries"] == EXPECTED
    assert job["progress"]["stage"] == "Done"

    kids = (await client.get("/api/v1/children", headers=h)).json()
    assert [k["name"] for k in kids] == ["Ada", "Mia", "Leo"]
    mia, leo = kids[1], kids[2]
    assert (mia["birthdate"], mia["sex"], mia["night_start"], mia["morning_cutoff"]) == ("2026-05-10", "F", "19:30",
                                                                                        "06:30")
    assert (leo["birthdate"], leo["sex"]) == ("2025-01-15", "M")
    leo_entries = (await client.get(f"/api/v1/children/{leo['id']}/entries?type=growth", headers=h)).json()
    assert leo_entries[0]["data"] == {"weight_kg": 11.0, "height_cm": 83.82, "head_cm": 46.99}
    assert leo_entries[0]["source"] == "import"
    assert (await client.get(f"/api/v1/children/{own_child}/entries", headers=h)).json() == []
    assert len(imported_entries()) == 60

    # Second run: same counts, no duplicates.
    again = await run_import(client, h)
    assert again["progress"]["entries"] == EXPECTED and again["progress"]["children"] == 2
    assert len(imported_entries()) == 60
    assert len((await client.get("/api/v1/children", headers=h)).json()) == 3

    # A changed row is updated, a new row is added, a removed row stays.
    bottle = next(e for e in hb.rows["fake-mia"]["feed"] if e.id == "fake-mia-bottle0")  # 120 ml
    bottle.data.amount = 150.0
    new = copy.deepcopy(hb.rows["fake-mia"]["diaper"][0])
    new.id = "batchdoc/row7"  # a row inside a multi container
    hb.rows["fake-mia"]["diaper"].append(new)
    del hb.rows["fake-leo"]["activities"][0]
    third = await run_import(client, h)
    assert third["status"] == "done"
    rows = {e.external_id: e for e in imported_entries()}
    assert len(rows) == 61
    assert rows[f"hb:feed:{bottle.id}"].data["amount_ml"] == 150.0
    assert "hb:diaper:batchdoc/row7" in rows
    assert "hb:activities:fake-leo-act0" in rows


async def test_family_isolation(client, hb):
    ha, _ = await make_family(client, "a@example.com")
    hb_user, _ = await make_family(client, "b@example.com", child="Bo")
    job = await run_import(client, ha)
    assert (await client.get(f"/api/v1/import/jobs/{job['id']}", headers=hb_user)).status_code == 404
    assert [k["name"] for k in (await client.get("/api/v1/children", headers=hb_user)).json()] == ["Bo"]
    # The same Huckleberry account in family B must not touch family A's children.
    other = await run_import(client, hb_user)
    assert other["status"] == "failed"
    assert "already in another family" in other["error"]
    assert [k["name"] for k in (await client.get("/api/v1/children", headers=ha)).json()] == ["Ada", "Mia", "Leo"]
    # No family yet → 409 from the family check.
    assert (await start(client, as_user("c@example.com"))).status_code == 409


async def test_wrong_password(client, hb):
    h, _ = await make_family(client)
    job = await run_import(client, h, fake.WRONG_PASSWORD)
    assert job["status"] == "failed"
    assert job["error"] == "Huckleberry sign-in failed. Check the email and password."
    assert len(imported_entries()) == 0


async def test_one_job_per_family(client, monkeypatch):
    gate = asyncio.Event()

    @asynccontextmanager
    async def slow(email, password, timezone):
        await gate.wait()
        yield fake.FakeHuckleberry()

    monkeypatch.setattr(huckleberry, "client_factory", slow)
    h, _ = await make_family(client)
    first = await start(client, h)
    assert first.status_code == 202
    second = await start(client, h)
    assert second.status_code == 409
    assert second.json()["detail"] == "An import is already running. Wait until it is done."
    gate.set()
    assert (await finish(client, h, first.json()["job_id"]))["status"] == "done"
    third = await start(client, h)  # free again
    assert third.status_code == 202
    assert (await finish(client, h, third.json()["job_id"]))["status"] == "done"


async def test_password_never_stored_or_logged(client, hb, monkeypatch, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    h, _ = await make_family(client)
    job = await run_import(client, h)
    assert job["status"] == "done"

    # A failure whose text holds the password is logged with the password hidden.
    @asynccontextmanager
    async def broken(email, password, timezone):
        raise RuntimeError(f"bad request with {password}")
        yield

    monkeypatch.setattr(huckleberry, "client_factory", broken)
    failed = await run_import(client, h)
    assert failed["status"] == "failed"
    assert failed["error"] == "The import stopped because of an error. Try again later."
    assert "bad request with ***" in caplog.text

    assert PASSWORD not in json.dumps(job) + json.dumps(failed)
    assert PASSWORD not in caplog.text
    with SessionLocal() as s:
        for j in s.query(ImportJob):
            assert PASSWORD not in json.dumps([j.progress, j.error, j.status])
        s.commit()
    for f in tmp_path.iterdir():
        if f.is_file() and f.name.startswith("frecklebubby.db"):
            assert PASSWORD.encode() not in f.read_bytes(), f.name


async def test_restart_marks_running_job_failed(client, hb):
    h, _ = await make_family(client)
    me = (await client.get("/api/v1/me", headers=h)).json()
    with SessionLocal() as s:
        s.add(ImportJob(family_id=me["family"]["id"], status="running", progress={"stage": "Reading sleep for Mia"}))
        s.commit()
        job_id = s.query(ImportJob).one().id
    r = await client.get(f"/api/v1/import/jobs/{job_id}", headers=h)
    assert r.json()["status"] == "failed"
    assert r.json()["error"] == "The server stopped during the import. Start it again."
    assert (await run_import(client, h))["status"] == "done"


async def test_501_without_the_extra(client, monkeypatch):
    monkeypatch.setattr(huckleberry, "client_factory", None)
    monkeypatch.delenv("HUCKLEBERRY_FAKE", raising=False)
    monkeypatch.setitem(sys.modules, "huckleberry_api", None)  # import fails as if not installed
    h, _ = await make_family(client)
    r = await start(client, h)
    assert r.status_code == 501
    assert "uv sync --extra import" in r.json()["detail"]
    with SessionLocal() as s:
        assert s.query(ImportJob).count() == 0


async def test_fake_switch_only_in_dev(client, monkeypatch):
    monkeypatch.setattr(huckleberry, "client_factory", None)
    monkeypatch.setenv("HUCKLEBERRY_FAKE", "1")
    h, _ = await make_family(client)
    job = await run_import(client, h)
    assert job["status"] == "done" and job["progress"]["entries"] == EXPECTED
    assert huckleberry._factory() is fake.fake_client
    monkeypatch.setenv("AUTH_MODE", "clerk")
    get_settings.cache_clear()
    assert huckleberry._factory() is huckleberry.real_client


async def test_bad_input(client, hb):
    h, _ = await make_family(client)
    r = await client.post("/api/v1/import/huckleberry", headers=h,
                          json={"email": "x@example.com", "password": PASSWORD, "timezone": "Mars/Base"})
    assert r.status_code == 422 and PASSWORD not in r.text
    r = await client.post("/api/v1/import/huckleberry", headers=h,
                          json={"email": "not-an-email", "password": PASSWORD, "timezone": "UTC"})
    assert r.status_code == 422 and PASSWORD not in r.text
