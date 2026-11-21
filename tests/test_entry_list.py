"""The entry list: more than one type, order by time or by a logged amount, pages by offset."""

from .conftest import make_family

API = "/api/v1"


async def test_list_filter_and_order(client):
    h, cid = await make_family(client)
    c = f"{API}/children/{cid}/entries"
    rows = [
        {"type": "bottle", "started_at": "2026-11-01T08:00:00Z", "data": {"amount_ml": 90}},
        {"type": "bottle", "started_at": "2026-11-01T11:00:00Z", "data": {"amount_ml": 150}},
        {"type": "pump", "started_at": "2026-11-01T12:00:00Z", "data": {"left_ml": 40, "right_ml": 70}},
        {"type": "sleep", "started_at": "2026-11-01T13:00:00Z", "ended_at": "2026-11-01T15:00:00Z", "data": {}},
        {"type": "sleep", "started_at": "2026-11-01T17:00:00Z", "ended_at": "2026-11-01T17:30:00Z", "data": {}},
        {"type": "nursing", "started_at": "2026-11-01T18:00:00Z", "data": {"left_seconds": 600, "right_seconds": 300}},
        {"type": "temperature", "started_at": "2026-11-01T19:00:00Z", "data": {"celsius": 37.4}},
        {"type": "nappy", "started_at": "2026-11-01T20:00:00Z", "data": {"mode": "pee"}},
    ]
    for row in rows:
        assert (await client.post(c, headers=h, json=row)).status_code == 201

    async def get(q):
        r = await client.get(f"{c}?{q}", headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    assert [e["type"] for e in await get("type=bottle&type=nappy")] == ["nappy", "bottle", "bottle"]
    assert [e["started_at"][11:13] for e in await get("dir=asc")] == ["08", "11", "12", "13", "17", "18", "19", "20"]
    # by amount: entries with no amount of that kind are not in the list
    assert [e["type"] for e in await get("sort=volume")] == ["bottle", "pump", "bottle"]
    assert [e["data"].get("amount_ml") for e in await get("sort=volume&dir=asc&type=bottle")] == [90, 150]
    assert [e["type"] for e in await get("sort=duration")] == ["sleep", "sleep", "nursing"]
    assert [e["type"] for e in await get("sort=duration&dir=asc")] == ["nursing", "sleep", "sleep"]
    assert [e["type"] for e in await get("sort=temperature")] == ["temperature"]
    assert [e["type"] for e in await get("sort=volume&limit=1&offset=1")] == ["pump"]
    assert (await client.get(f"{c}?sort=colour", headers=h)).status_code == 422

    # the CSV export takes the same selection and order
    async def ids(q):
        r = await client.get(f"{API}/children/{cid}/export.csv?{q}", headers=h)
        assert r.status_code == 200, r.text
        return [line.split(",")[1] for line in r.text.strip().splitlines()[1:]]

    assert len(await ids("")) == 8 and (await ids(""))[0] == "bottle"  # all entries, the oldest first
    assert await ids("type=bottle&type=nappy&dir=desc") == ["nappy", "bottle", "bottle"]
    assert await ids("sort=volume&dir=desc") == ["bottle", "pump", "bottle"]
    assert await ids("from=2026-11-01T17:00:00Z&to=2026-11-01T19:00:00Z") == ["sleep", "nursing"]
