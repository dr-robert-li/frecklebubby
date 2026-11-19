from datetime import datetime
from types import SimpleNamespace

from frecklebubby.services.children import is_night

from .conftest import make_family

API = "/api/v1"


def test_night_vs_nap():
    child = SimpleNamespace(night_start="19:00", morning_cutoff="07:00")
    t = lambda h, m: datetime(2026, 11, 1, h, m)  # noqa: E731
    assert not is_night(child, t(17, 59))
    assert is_night(child, t(18, 0))
    assert is_night(child, t(2, 0))
    assert is_night(child, t(6, 59))
    assert not is_night(child, t(7, 0))
    assert not is_night(child, t(13, 0))
    # Without the 1 h lead (used by daytime_only reminders).
    assert not is_night(child, t(18, 30), early_minutes=0)


async def post(client, h, cid, **body):
    r = await client.post(f"{API}/children/{cid}/entries", headers=h, json=body)
    assert r.status_code == 201, r.text


async def test_daily_report_brisbane(client):
    h, cid = await make_family(client, tz="Australia/Brisbane")
    # Night sleep 31 Oct 19:30 to 1 Nov 06:00 local (UTC+10, no DST).
    await post(client, h, cid, type="sleep", started_at="2026-10-31T19:30:00", ended_at="2026-11-01T06:00:00")
    await post(client, h, cid, type="sleep", started_at="2026-11-01T13:00:00", ended_at="2026-11-01T14:30:00")
    await post(client, h, cid, type="bottle", started_at="2026-11-01T23:30:00", data={"amount_ml": 120})
    await post(client, h, cid, type="bottle", started_at="2026-11-02T00:10:00", data={"amount_ml": 90})
    await post(client, h, cid, type="nursing", started_at="2026-11-01T09:00:00", ended_at="2026-11-01T09:20:00",
               data={"left_seconds": 300, "right_seconds": 200})
    await post(client, h, cid, type="nappy", started_at="2026-11-01T10:00:00", data={"mode": "both"})
    await post(client, h, cid, type="nappy", started_at="2026-11-01T11:00:00", data={"mode": "pee"})
    await post(client, h, cid, type="activity", started_at="2026-11-01T17:00:00", ended_at="2026-11-01T17:15:00",
               data={"kind": "bath"})
    await post(client, h, cid, type="pump", started_at="2026-11-01T08:00:00", data={"total_ml": 80})
    await post(client, h, cid, type="medicine", started_at="2026-11-01T08:00:00", data={"name": "Vitamin D"})

    rep = (await client.get(f"{API}/children/{cid}/reports/daily", headers=h,
                            params={"from": "2026-10-31", "to": "2026-11-01"})).json()
    assert rep["timezone"] == "Australia/Brisbane"
    assert rep["sleep_recommendations"]  # age 5 months: AASM and NSF rows
    d31, d1 = rep["days"]
    assert d31["date"] == "2026-10-31"
    assert d31["sleep"] == {"total_seconds": 16200, "night_seconds": 16200, "nap_seconds": 0, "count": 1,
                            "nap_count": 0}
    assert d1["sleep"] == {"total_seconds": 21600 + 5400, "night_seconds": 21600, "nap_seconds": 5400, "count": 1,
                           "nap_count": 1}
    assert d1["feeds"] == {"count": 2, "bottle_ml": 120, "nursing_seconds": 500, "solids_count": 0}
    assert d1["nappies"] == {"wet": 2, "dirty": 1}
    assert d1["activities"] == {"bath": {"count": 1, "seconds": 900}}
    assert d1["pump_ml"] == 80 and d1["medicine_count"] == 1

    r = await client.get(f"{API}/children/{cid}/reports/daily", headers=h,
                         params={"from": "2026-11-02", "to": "2026-11-01"})
    assert r.status_code == 422


async def test_daily_report_dst_day(client):
    # Sydney moves to UTC+11 at 02:00 on 4 Oct 2026: that day has 23 hours.
    h, cid = await make_family(client, tz="Australia/Sydney")
    await post(client, h, cid, type="sleep", started_at="2026-10-03T13:00:00Z", ended_at="2026-10-04T14:00:00Z")
    await post(client, h, cid, type="bottle", started_at="2026-10-04T13:30:00Z", data={"amount_ml": 50})
    rep = (await client.get(f"{API}/children/{cid}/reports/daily", headers=h,
                            params={"from": "2026-10-03", "to": "2026-10-05"})).json()
    d3, d4, d5 = rep["days"]
    assert d3["sleep"]["total_seconds"] == 3600 and d3["sleep"]["count"] == 1
    assert d4["sleep"]["total_seconds"] == 23 * 3600
    assert d5["sleep"]["total_seconds"] == 3600
    assert d4["feeds"]["bottle_ml"] == 0 and d5["feeds"]["bottle_ml"] == 50  # 00:30 local on 5 Oct


async def test_status(client):
    h, cid = await make_family(client)
    await post(client, h, cid, type="bottle", started_at="2026-11-01T08:00:00", data={"amount_ml": 100})
    await client.post(f"{API}/children/{cid}/timers/sleep/start", headers=h)
    st = (await client.get(f"{API}/children/{cid}/status", headers=h)).json()
    assert [t["type"] for t in st["timers"]] == ["sleep"]
    assert st["last"]["bottle"]["data"]["amount_ml"] == 100
    assert st["prediction"] is None  # asleep
    assert st["unread_notifications"] == 0
    assert "sleep" in st["today"]
