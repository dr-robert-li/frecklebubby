from datetime import timedelta
from zoneinfo import ZoneInfo

from frecklebubby.models import Entry, Timer
from frecklebubby.services.children import get_child
from frecklebubby.services.growth import percentile
from frecklebubby.services.sleep import predict, recommendations, wake_range

from .conftest import ctx_for, make_family

BNE = ZoneInfo("Australia/Brisbane")
API = "/api/v1"


def local(day, h, m=0):
    from datetime import datetime
    return datetime(2026, 11, day, h, m, tzinfo=BNE)


def add_sleep(s, cid, start, end):
    s.add(Entry(child_id=cid, type="sleep", started_at=start, ended_at=end, data={}))


def test_tables():
    assert wake_range(0.5) == (45, 75)
    assert wake_range(5.5) == (90, 150)
    assert wake_range(48) == (330, 420)
    assert {r["citation"]["year"] for r in recommendations(6)} == {2015, 2016}
    assert [(r["min_hours"], r["max_hours"]) for r in recommendations(24)] == [(11, 14)]


async def test_prediction(client):
    _, cid = await make_family(client, birthdate="2026-06-01")
    s, ctx = ctx_for("a@example.com")
    child = get_child(s, ctx, cid)
    for day in (12, 13, 14):
        add_sleep(s, cid, local(day - 1, 19), local(day, 6))
        add_sleep(s, cid, local(day, 8), local(day, 9))          # wake window 120
        add_sleep(s, cid, local(day, 11, 30), local(day, 12, 30))  # 150
        add_sleep(s, cid, local(day, 15), local(day, 15, 45))      # 150
    add_sleep(s, cid, local(14, 19), local(15, 6))                  # bedtime window 195
    add_sleep(s, cid, local(15, 8), local(15, 9))
    s.commit()

    p = predict(s, child, BNE, now=local(15, 10))
    assert (p["basis"], p["wake_window_minutes"], p["samples"], p["kind"]) == ("personal", 150, 3, "nap")
    assert p["start"] == local(15, 11, 15) and p["end"] == local(15, 11, 45)

    add_sleep(s, cid, local(15, 11, 30), local(15, 12, 30))
    add_sleep(s, cid, local(15, 15), local(15, 15, 45))
    s.commit()
    p = predict(s, child, BNE, now=local(15, 16))
    # 195 min is clamped to the 4-6 month range (90-150); the window ends after 18:00 so it is bedtime.
    assert (p["wake_window_minutes"], p["kind"]) == (150, "bedtime")
    assert p["age_range_minutes"] == (90, 150)

    # No sleep in the last 24 h.
    later = local(17, 10)
    assert predict(s, child, BNE, now=later) is None
    p = predict(s, child, BNE, now=later, default=True)
    assert (p["basis"], p["wake_window_minutes"], p["start"]) == ("age", 120, later + timedelta(minutes=105))

    s.add(Timer(child_id=cid, type="sleep", started_at=local(15, 16), paused_seconds=0, data={}))
    s.commit()
    assert predict(s, child, BNE, now=local(15, 16, 30)) is None
    s.close()


async def test_prediction_api_few_samples(client):
    h, cid = await make_family(client, birthdate="2026-06-01")
    r = await client.get(f"{API}/children/{cid}/sleep/prediction", headers=h)
    assert r.status_code == 200 and r.json() is None
    r = await client.get(f"{API}/children/{cid}/sleep/prediction?default=true", headers=h)
    assert r.json()["basis"] == "age"
    assert "not a medical standard" in r.json()["note"]


def test_percentile_formula():
    L, M, S = 0.3809, 3.2322, 0.14171
    assert percentile(M, (L, M, S)) == 50.0
    assert percentile(M * (1 + L * S) ** (1 / L), (L, M, S)) == 84.1


async def test_growth(client):
    h, cid = await make_family(client, birthdate="2026-06-01", sex="F")
    url = f"{API}/children/{cid}/entries"
    await client.post(url, headers=h, json={"type": "growth", "started_at": "2026-06-01T09:00:00",
                                            "data": {"weight_kg": 3.2322, "height_cm": 50}})
    await client.post(url, headers=h, json={"type": "growth", "started_at": "2026-07-16T09:00:00",
                                            "data": {"weight_kg": 4.6}})
    await client.post(url, headers=h, json={"type": "growth", "started_at": "2026-11-01T09:00:00",
                                            "data": {"weight_kg": 7}})
    g = (await client.get(f"{API}/children/{cid}/growth", headers=h)).json()
    p0, p1, p2 = g["points"]
    assert p0["weight_percentile"] == 50.0
    assert p0["height_cm"] == 50 and p0["height_percentile"] is None  # no length table in the fixtures
    assert 1.4 < p1["age_months"] < 1.5 and 30 < p1["weight_percentile"] < 70
    assert p2["weight_percentile"] is None  # outside the fixture table (0-3 months)
    assert [c["age_months"] for c in g["curves"]["weight"]] == [0, 1, 2, 3]
    w0 = g["curves"]["weight"][0]
    assert w0["p3"] < w0["p15"] < w0["p50"] == 3.232 < w0["p85"] < w0["p97"]
    assert g["curves"]["height"] == []

    await client.patch(f"{API}/children/{cid}", headers=h, json={"sex": None})
    g = (await client.get(f"{API}/children/{cid}/growth", headers=h)).json()
    assert g["curves"] == {} and g["points"][0]["weight_percentile"] is None


async def test_milestones(client):
    h, cid = await make_family(client)
    await client.post(f"{API}/children/{cid}/entries", headers=h, json={
        "type": "milestone", "started_at": "2026-08-01T09:00:00", "data": {"key": "2m_smiles", "title": "Smiles"}})
    m = (await client.get(f"{API}/children/{cid}/milestones", headers=h)).json()
    assert [b["age_months"] for b in m["bands"]] == [2, 4]
    smiles = m["bands"][0]["items"][0]
    assert smiles["key"] == "2m_smiles" and smiles["achieved"] is True
    assert smiles["source"]["publisher"] == "CDC"
    assert m["bands"][1]["items"][0]["achieved"] is False
