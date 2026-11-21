"""The day and night plan (0.6.0): the child's own last 14 days come first; values for the age fill gaps only."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from frecklebubby.models import Entry
from frecklebubby.services.children import get_child
from frecklebubby.services.regime import blend, pct, regime

from .conftest import ctx_for, make_family

BNE = ZoneInfo("Australia/Brisbane")
API = "/api/v1"
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=BNE)


def local(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=BNE)


def add(s, cid, kind, a, b):
    s.add(Entry(child_id=cid, type=kind, started_at=a, ended_at=b, data={}))


def day(s, cid, d, wake=(6, 0), bed=(19, 0), naps=((8, 0, 60), (11, 30, 60), (15, 0, 45)), feeds=((23, 0), (3, 0))):
    """Day d: the night before it ends at `wake`; naps (hour, minute, length); the night feeds of the night before."""
    add(s, cid, "sleep", local(d - 1, *bed), local(d, *wake))
    for h, m, length in naps:
        add(s, cid, "sleep", local(d, h, m), local(d, h, m) + timedelta(minutes=length))
    for h, m in feeds:
        add(s, cid, "nursing", local(d - 1 if h > 12 else d, h, m), local(d - 1 if h > 12 else d, h, m + 10))


async def child(client, birthdate="2026-06-01"):
    _, cid = await make_family(client, birthdate=birthdate)
    s, ctx = ctx_for("a@example.com")
    return s, get_child(s, ctx, cid), cid


def rows(r, part=None):
    return [(x["time"], x["kind"]) for x in r["schedule"] if part is None or x["part"] == part]


async def test_own_days_decide_the_24_hours(client):
    s, c, cid = await child(client)  # about 5.5 months
    for d in range(6, 17):
        day(s, cid, d)
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["basis"] == "own" and r["own_days"] >= 9 and r["naps"] == 3
    assert rows(r, "day") == [("06:00", "wake"), ("08:00", "nap"), ("11:30", "nap"), ("15:00", "nap"), ("19:00", "bedtime")]
    assert r["schedule"][1]["end"] == "09:00" and all(x["basis"] == "own" for x in r["schedule"])
    # The night: the two feeds at their usual times. Rows after midnight come after the rows before it.
    assert rows(r, "night") == [("23:00", "night_feed"), ("03:00", "night_feed")]
    facts = {f["key"]: f for f in r["facts"]}
    assert facts["feeds"]["value"] == "2" and facts["feeds"]["basis"] == "own"
    assert facts["night_sleep"]["value"] == "11 hours" and facts["total"]["value"] == "13.8 hours"
    assert r["notes"][0]["text"].startswith("This plan uses Ada's own times")
    assert all(1 <= n <= len(r["sources"]) for x in r["notes"] for n in x["cites"])


async def test_one_unusual_day_does_not_move_the_plan(client):
    s, c, cid = await child(client)
    for d in range(6, 17):
        day(s, cid, d, wake=(9, 30) if d == 12 else (6, 0), naps=((11, 0, 60),) if d == 12 else ((8, 0, 60), (11, 30, 60)))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r, "day")[:3] == [("06:00", "wake"), ("08:00", "nap"), ("11:30", "nap")]
    wake = r["schedule"][0]
    assert wake["earliest"] == "06:00" and wake["latest"] in ("06:00", "06:20")  # the usual range ignores the long tail


async def test_own_times_are_not_pulled_to_the_range_for_the_age(client):
    s, c, cid = await child(client)
    for d in range(6, 17):  # a late family: bedtime 22:30, wake 09:30, 5 night feeds would also stay
        day(s, cid, d, wake=(9, 30), bed=(22, 30), naps=((12, 0, 90),), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r, "day") == [("09:30", "wake"), ("12:00", "nap"), ("22:30", "bedtime")]
    assert rows(r, "night") == []
    assert any("no night feed on most" in n["text"] for n in r["notes"])


async def test_few_days_mix_with_the_age_and_no_days_use_the_age(client):
    s, c, cid = await child(client)
    r = regime(s, c, BNE, NOW)
    assert r["basis"] == "age" and r["own_days"] == 0
    kinds = [k for _, k in rows(r)]
    assert kinds[0] == "wake" and kinds[-1] == "bedtime" and "nap" in kinds  # typical times for the age
    assert all(x["basis"] == "age" and x["earliest"] is None for x in r["schedule"])
    assert "No complete day of sleep is logged" in r["notes"][0]["text"]
    for d in (15, 16):
        day(s, cid, d, wake=(5, 0))
    s.commit()
    r2 = regime(s, c, BNE, NOW)
    assert r2["basis"] == "mixed" and r2["schedule"][0]["basis"] == "mixed"
    assert "05:00" < r2["schedule"][0]["time"] < r["schedule"][0]["time"]  # between the own time and the age time


async def test_a_child_of_3_years_with_and_without_a_nap(client):
    s, c, cid = await child(client, birthdate="2023-06-01")  # 3.5 years: older than the norms file
    r = regime(s, c, BNE, NOW)
    assert r["basis"] == "age" and r["age_band"] == "3 to 4 years"
    assert [k for _, k in rows(r)] == ["wake", "nap", "bedtime"]
    assert any("About half of the children of this age still nap" in n["text"] for n in r["notes"])
    for d in range(6, 17):
        day(s, cid, d, wake=(6, 30), bed=(19, 30), naps=((12, 30, 90),) if d % 3 == 0 else (), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r) == [("06:30", "wake"), ("19:30", "bedtime")] and r["naps"] == 0
    assert any("The number of naps is changing" in n["text"] for n in r["notes"])


async def test_the_route_and_the_helpers(client):
    h, cid = await make_family(client)
    r = await client.get(f"{API}/children/{cid}/sleep/regime", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["basis"] == "age" and body["schedule"][0]["kind"] == "wake" and body["sources"]
    assert pct([1, 2, 3, 4, 5], 0.5) == 3 and pct([0, 10], 0.1) == 1
    assert blend([], None) is None and blend([], 7)["basis"] == "age"
    assert blend([10, 10], 20) == {"value": 16, "basis": "mixed", "samples": 2}
    assert blend([1, 1, 1, 1, 50], 20)["value"] == 1  # 5 days: own median only, the tail does not count
