import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

from .conftest import make_family

API = "/api/v1"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(("type_", "data", "field"), [
    ("bottle", {"amount_ml": 501}, "data.amount_ml"),
    ("bottle", {"amount_ml": -1}, "data.amount_ml"),
    ("temperature", {"celsius": 29.9}, "data.celsius"),
    ("temperature", {"celsius": 45.1}, "data.celsius"),
    ("growth", {"weight_kg": 0.2}, "data.weight_kg"),
    ("growth", {"weight_kg": 61}, "data.weight_kg"),
    ("growth", {"height_cm": 151}, "data.height_cm"),
    ("growth", {"head_cm": 14}, "data.head_cm"),
    ("growth", {}, "data"),
    ("nappy", {"mode": "wet"}, "data.mode"),
    ("bottle", {"amount_ml": 50, "colour": "x"}, "data.colour"),
])
async def test_validation_ranges(client, type_, data, field):
    h, cid = await make_family(client)
    r = await client.post(f"{API}/children/{cid}/entries", headers=h,
                          json={"type": type_, "started_at": "2026-11-01T10:00:00Z", "data": data})
    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith(field)


async def test_valid_edges(client):
    h, cid = await make_family(client)
    for type_, data in [("bottle", {"amount_ml": 500}), ("temperature", {"celsius": 30}),
                        ("growth", {"weight_kg": 60, "height_cm": 20, "head_cm": 65})]:
        r = await client.post(f"{API}/children/{cid}/entries", headers=h,
                              json={"type": type_, "started_at": "2026-11-01T10:00:00Z", "data": data})
        assert r.status_code == 201, r.text


async def test_time_rules(client):
    h, cid = await make_family(client)
    now = datetime.now(UTC)
    url = f"{API}/children/{cid}/entries"

    async def post(**body):
        return await client.post(url, headers=h, json=body)

    r = await post(type="sleep", started_at=iso(now - timedelta(hours=1)))
    assert r.status_code == 422 and r.json()["detail"] == "ended_at: required for sleep"
    r = await post(type="sleep", started_at=iso(now - timedelta(hours=1)), ended_at=iso(now - timedelta(hours=2)))
    assert r.json()["detail"] == "ended_at: must be after started_at"
    r = await post(type="note", notes="x", started_at=iso(now + timedelta(minutes=10)))
    assert "5 minutes in the future" in r.json()["detail"]
    assert (await post(type="note", notes="x", started_at=iso(now + timedelta(minutes=4)))).status_code == 201
    r = await post(type="bottle", started_at=iso(now), ended_at=iso(now), data={"amount_ml": 5})
    assert r.json()["detail"] == "ended_at: a bottle entry has no end time"
    assert (await post(type="note", started_at=iso(now))).json()["detail"] == "notes: required for a note"

    # No offset = family time zone (Brisbane, UTC+10).
    r = await post(type="nappy", started_at="2026-11-01T08:00:00", data={"mode": "pee"})
    assert r.json()["started_at"] == "2026-10-31T22:00:00Z"


async def test_list_patch_delete_and_csv(client):
    h, cid = await make_family(client)
    url = f"{API}/children/{cid}/entries"
    ids = []
    for hour in range(5):
        r = await client.post(url, headers=h, json={"type": "bottle", "started_at": f"2026-11-01T0{hour}:00:00Z",
                                                    "data": {"amount_ml": 10 * hour, "milk_type": "Formula"}})
        ids.append(r.json()["id"])
    await client.post(url, headers=h, json={"type": "note", "started_at": "2026-11-01T06:00:00Z",
                                            "notes": "=HYPERLINK(1)"})
    page = (await client.get(url, headers=h, params={"type": "bottle", "limit": 2})).json()
    assert [e["id"] for e in page] == ids[:2:-1][:2] == [ids[4], ids[3]]
    page2 = (await client.get(url, headers=h, params={"type": "bottle", "limit": 2,
                                                      "before": page[-1]["started_at"]})).json()
    assert [e["id"] for e in page2] == [ids[2], ids[1]]
    ranged = (await client.get(url, headers=h, params={"from": "2026-11-01T01:00:00Z",
                                                       "to": "2026-11-01T03:00:00Z"})).json()
    assert [e["id"] for e in ranged] == [ids[2], ids[1]]

    r = await client.patch(f"{API}/entries/{ids[0]}", headers=h, json={"data": {"amount_ml": 900}})
    assert r.status_code == 422
    r = await client.patch(f"{API}/entries/{ids[0]}", headers=h, json={"data": {"amount_ml": 90}, "notes": "ok"})
    assert r.json()["data"] == {"amount_ml": 90} and r.json()["notes"] == "ok"
    assert (await client.delete(f"{API}/entries/{ids[1]}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/entries/{ids[1]}", headers=h)).status_code == 404

    r = await client.get(f"{API}/children/{cid}/export.csv", headers=h)
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="frecklebubby-Ada.csv"' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 5
    assert rows[0]["started_at"] == "2026-11-01T10:00:00+10:00"
    assert rows[0]["data"] == '{"amount_ml":90.0}'
    assert rows[-1]["notes"] == "'=HYPERLINK(1)"
