"""The day and night plan: a timeline of sleep blocks and feeds. The start point is the child's own last 14 days;
then one small step toward best practice when the logs are outside a recommended range."""

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


def rows(r, feeds=True):
    return [(x["time"], x["end"], x["kind"]) for x in r["schedule"] if feeds or x["kind"] != "feed"]


def changed(r):
    return [(x["time"], x["kind"], x["change"]) for x in r["schedule"] if x["change"]]


async def test_own_days_give_one_timeline_of_sleep_blocks_and_feeds(client):
    s, c, cid = await child(client)  # about 5.5 months; 13.75 hours of sleep: inside the recommended 12 to 16 hours
    for d in range(6, 17):
        day(s, cid, d)
        for h, m in ((6, 10), (10, 0), (14, 0), (18, 30)):  # the feeds of the day
            add(s, cid, "bottle", local(d, h, m), local(d, h, m + 10))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["mode"] == "clock" and r["basis"] == "own" and r["own_days"] >= 9 and r["naps"] == 3
    assert r["confidence"] == "normal"
    # From the morning, in the order of the clock. The night is one block; the night feeds come after its start.
    assert rows(r) == [
        ("06:10", None, "feed"), ("08:00", "09:00", "nap"), ("10:00", None, "feed"), ("11:30", "12:30", "nap"),
        ("14:00", None, "feed"), ("15:00", "15:45", "nap"), ("18:30", None, "feed"), ("19:00", "06:00", "night"),
        ("23:00", None, "feed"), ("03:00", None, "feed")]
    assert [x["part"] for x in r["schedule"]][-3:] == ["night", "night", "night"]
    assert r["nudges"] == [] and changed(r) == []  # inside the ranges: the plan is the child's own pattern
    facts = {f["key"]: f for f in r["facts"]}
    assert facts["feeds"]["value"] == "2" and facts["feeds_24h"]["value"] == "6"
    assert facts["night_sleep"]["value"] == "11 hours" and facts["total"]["value"] == "13.8 hours"
    assert r["notes"][0]["text"].startswith("The start point of this plan is Ada's own times")
    assert all(1 <= n <= len(r["sources"]) for x in r["notes"] + r["nudges"] for n in x["cites"])


async def test_one_unusual_day_does_not_move_the_plan(client):
    s, c, cid = await child(client)
    for d in range(6, 17):
        day(s, cid, d, wake=(9, 30) if d == 12 else (6, 0),
            naps=((11, 0, 60),) if d == 12 else ((8, 0, 90), (11, 30, 90), (15, 0, 45)), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r) == [("08:00", "09:30", "nap"), ("11:30", "13:00", "nap"), ("15:00", "15:45", "nap"),
                       ("19:00", "06:00", "night")]


async def test_a_little_too_little_sleep_gets_the_smallest_step_and_follows_the_logs(client):
    s, c, cid = await child(client, birthdate="2026-01-10")  # 10 months: 12 to 15 hours recommended, 10 to 18 can be right
    for d in range(6, 17):  # 9 h at night and 2 naps of 45 minutes: 10.5 hours
        day(s, cid, d, bed=(21, 0), naps=((10, 0, 45), (14, 30, 45)), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    # Below the recommended range, but 10 hours or more can be right: the smallest step, 15 minutes at bedtime.
    assert rows(r) == [("10:00", "10:45", "nap"), ("14:30", "15:15", "nap"), ("20:45", "06:00", "night")]
    assert changed(r) == [("20:45", "night", "15 minutes earlier than Ada's usual 21:00")]
    text = r["nudges"][0]["text"]
    assert len(r["nudges"]) == 1 and "10.5 hours" in text and "12 to 15 hours" in text and r["nudges"][0]["cites"]
    assert "can also be right for some children" in text and "adds about 15 minutes" in text
    assert {f["key"]: f["value"] for f in r["facts"]}["total"] == "10.5 hours"  # the fact is the logs, not the plan
    assert not any("speak to a doctor or nurse" in n["text"] for n in r["notes"][:2])
    # The family follows: bedtime at 20:45 for a week. The next plan starts there and takes the next step.
    for d in range(10, 17):
        s.query(Entry).filter(Entry.child_id == cid, Entry.started_at == local(d - 1, 21)).update(
            {"started_at": local(d - 1, 20, 45)})
    s.commit()
    r2 = regime(s, c, BNE, NOW)
    assert changed(r2) == [("20:30", "night", "15 minutes earlier than Ada's usual 20:45")]


async def test_much_too_little_sleep_gets_a_larger_step_and_the_doctor_note(client):
    s, c, cid = await child(client, birthdate="2026-01-10")
    for d in range(6, 17):  # 8 h at night and 2 naps of 45 minutes: 9.5 hours, below the 10 hours that can be right
        day(s, cid, d, bed=(22, 0), naps=((10, 0, 45), (14, 30, 45)), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    # A quarter of the gap of 150 minutes: 40 minutes. Bedtime takes 20, each nap takes 10. Not the full 150.
    assert rows(r) == [("10:00", "10:55", "nap"), ("14:30", "15:25", "nap"), ("21:40", "06:00", "night")]
    assert "adds about 40 minutes" in r["nudges"][0]["text"] and "can also be right" not in r["nudges"][0]["text"]
    assert any("Fewer than 10 hours" in n["text"] and "speak to a doctor or nurse" in n["text"] for n in r["notes"])


async def test_more_sleep_than_recommended_is_never_cut(client):
    s, c, cid = await child(client, birthdate="2026-01-10")  # 10 months
    for d in range(6, 17):  # 12.5 h at night and 2 naps of 2 hours: 16.5 hours, inside 16 to 18 that can be right
        day(s, cid, d, wake=(7, 0), bed=(18, 30), naps=((9, 0, 120), (13, 0, 120)), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["nudges"] == [] and changed(r) == []
    assert any("Up to 18 hours can be right for some children, so the plan makes no change" in n["text"] for n in r["notes"])
    # 19.5 hours: not recommended. Still no cut: check the logs, then a doctor, with the warning signs.
    for d in range(6, 17):
        add(s, cid, "sleep", local(d, 15, 15), local(d, 18, 0))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert changed(r) == [] and len(r["nudges"]) == 1
    text = r["nudges"][0]["text"]
    assert "more than 18 hours" in text and "does not cut sleep" in text and "timer that was not stopped" in text
    assert "speak to a doctor or nurse" in text and "hard to wake" in text


async def test_from_2_years_a_long_late_nap_with_a_late_night_ends_a_little_earlier(client):
    s, c, cid = await child(client, birthdate="2024-03-01")  # 2 years 8 months
    for d in range(6, 17):  # nap 13:00 to 15:45, night 21:00 to 06:45: 12.5 hours, inside the range
        day(s, cid, d, wake=(6, 45), bed=(21, 0), naps=((13, 0, 165),), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r) == [("13:00", "15:30", "nap"), ("21:00", "06:45", "night")]
    assert changed(r) == [("13:00", "nap", "Ends 15 minutes earlier than Ada's usual 15:45. Wake Ada gently.")]
    assert "longer than 2 hours" in r["nudges"][0]["text"] and len(r["nudges"][0]["cites"]) == 2
    # The same nap with an early night: the night does not suffer, so the nap stays.
    s, c, cid = await child3(client, birthdate="2024-03-01", email="d@example.com")
    for d in range(6, 17):
        day(s, cid, d, wake=(6, 45), bed=(19, 30), naps=((13, 0, 135),), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert changed(r) == [] and r["nudges"] == []
    # The number of naps is shown next to the typical number, with no step toward it.
    assert {f["key"]: f["value"] for f in r["facts"]}["naps"] == "1"


async def test_a_late_family_inside_the_range_is_not_changed(client):
    s, c, cid = await child(client)
    for d in range(6, 17):  # bedtime 22:30, wake 09:30, one nap: 12.5 hours, inside 12 to 16 hours
        day(s, cid, d, wake=(9, 30), bed=(22, 30), naps=((12, 0, 90),), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r) == [("12:00", "13:30", "nap"), ("22:30", "09:30", "night")]
    assert r["nudges"] == [] and changed(r) == []


async def test_few_days_mix_with_the_age_and_no_days_use_the_age(client):
    s, c, cid = await child(client)
    r = regime(s, c, BNE, NOW)
    assert r["basis"] == "age" and r["own_days"] == 0 and r["nudges"] == []  # no logs: no step
    kinds = [x["kind"] for x in r["schedule"]]
    assert kinds[-1] == "night" and "nap" in kinds  # typical times for the age
    assert all(x["basis"] == "age" and x["earliest"] is None for x in r["schedule"])
    assert "No complete day of sleep is logged" in r["notes"][0]["text"]
    for d in (15, 16):
        day(s, cid, d, wake=(5, 0))
    s.commit()
    r2 = regime(s, c, BNE, NOW)
    assert r2["basis"] == "mixed" and r2["schedule"][-1]["basis"] == "mixed"
    assert "05:00" < r2["schedule"][-1]["end"] < r["schedule"][-1]["end"]  # between the own time and the age time


async def test_a_child_of_3_years_with_and_without_a_nap(client):
    s, c, cid = await child(client, birthdate="2023-06-01")  # 3.5 years: older than the norms file
    r = regime(s, c, BNE, NOW)
    assert r["basis"] == "age" and r["age_band"] == "3 to 4 years"
    assert [x["kind"] for x in r["schedule"]] == ["nap", "night"]
    assert any("About half of the children of this age still nap" in n["text"] for n in r["notes"])
    for d in range(6, 17):  # 11 hours at night: inside 10 to 13 hours
        day(s, cid, d, wake=(6, 30), bed=(19, 30), naps=((12, 30, 90),) if d % 3 == 0 else (), feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert rows(r) == [("19:30", "06:30", "night")] and r["naps"] == 0 and r["nudges"] == []
    assert any("The number of naps is changing" in n["text"] for n in r["notes"])


async def test_a_young_baby_gets_blocks_from_the_usual_hours_and_small_steps(client):
    s, c, cid = await child(client, birthdate="2026-10-07")  # 40 days: no fixed day and night yet
    for d in range(4, 16):  # 8.7 hours of sleep and 7 feeds are logged
        for h, m, length in ((1, 30, 120), (4, 0, 130), (9, 0, 60), (17, 0, 90), (20, 0, 120)):
            add(s, cid, "sleep", local(d, h, m), local(d, h, m) + timedelta(minutes=length))
        for h, m in ((0, 30), (3, 40), (6, 30), (10, 30), (14, 0), (18, 40), (22, 10)):
            add(s, cid, "nursing", local(d, h, m), local(d, h, m + 15))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["mode"] == "rhythm" and r["basis"] == "own" and r["own_days"] == 12
    blocks = rows(r, feeds=False)
    # The baby's own usual hours of sleep, and ONE new block in the longest time with no sleep (10:00 to 17:00).
    assert [b for b in blocks if b[0] not in [x[0] for x in changed(r)]] == [
        ("09:00", "10:00", "nap"), ("17:00", "18:30", "nap"), ("20:00", "22:00", "night"),
        ("01:30", "03:30", "night"), ("04:00", "06:10", "night")]
    new = [x for x in r["schedule"] if x["change"] and x["kind"] != "feed"]
    assert len(new) == 1 and "10:00" < new[0]["time"] < new[0]["end"] < "17:00" and "Offer a sleep" in new[0]["change"]
    # 7 feeds are fewer than 8 to 12: ONE new feed, in the longest time between two feeds.
    feeds = [x for x in r["schedule"] if x["kind"] == "feed"]
    assert len(feeds) == 8 and [x["time"] for x in feeds if x["change"]] == ["16:20"]
    assert len(r["nudges"]) == 2 and "8.7 hours" in r["nudges"][0]["text"] and "14 to 17 hours" in r["nudges"][0]["text"]
    assert "about 7 feeds" in r["nudges"][1]["text"] and all(n["cites"] for n in r["nudges"])
    times = [x["time"] for x in r["schedule"]]
    assert times[0] >= "07:00" and times.index("09:00") < times.index("20:00") < times.index("01:30")  # from the morning
    facts = {f["key"]: f for f in r["facts"]}
    assert facts["feeds_24h"]["value"] == "7" and facts["feeds_24h"]["common"] == "8 to 12"
    assert facts["total"]["label"] == "Sleep logged in 24 hours" and facts["total"]["value"] == "8.7 hours"
    assert any("no fixed day and night yet" in n["text"] for n in r["notes"])
    # With no logs: typical blocks and feeds for the age, and no feed inside a sleep block.
    s2, c2, _ = await child2(client)
    r2 = regime(s2, c2, BNE, NOW)
    assert r2["mode"] == "rhythm" and r2["basis"] == "age" and r2["nudges"] == []
    sleeps = [x for x in r2["schedule"] if x["kind"] != "feed"]
    assert len(sleeps) >= 4 and sum(x["kind"] == "feed" for x in r2["schedule"]) >= 6
    mins = lambda x: (int(x[:2]) * 60 + int(x[3:]) - 420) % 1440  # noqa: E731  minutes after 07:00
    assert not any(mins(b["time"]) <= mins(f["time"]) < mins(b["end"]) for b in sleeps for f in r2["schedule"]
                   if f["kind"] == "feed")


async def test_a_young_baby_with_sleeps_at_different_hours_each_day_still_gets_the_usual_number_of_blocks(client):
    s, c, cid = await child(client, birthdate="2026-10-07")
    for d in range(4, 16):  # 5 sleeps a day; the day sleeps move by up to 2 hours from day to day
        shift = (d % 4) * 40
        for h, m, length in ((1, 30, 120), (4, 0, 120)):
            add(s, cid, "sleep", local(d, h, m), local(d, h, m) + timedelta(minutes=length))
        for h, length in ((8, 60), (12, 90), (17, 60)):
            add(s, cid, "sleep", local(d, h) + timedelta(minutes=shift), local(d, h) + timedelta(minutes=shift + length))
        for h in (0, 3, 6, 9, 12, 15, 18, 21):  # each feed is logged as two entries: left, then right
            add(s, cid, "nursing", local(d, h, 30), local(d, h, 40))
            add(s, cid, "nursing", local(d, h, 45), local(d, h, 55))
    s.commit()
    r = regime(s, c, BNE, NOW)
    usual = [x for x in r["schedule"] if x["kind"] != "feed" and not x["change"]]
    assert r["mode"] == "rhythm" and len(usual) == 5 and sum(x["kind"] == "nap" for x in usual) == 3
    assert {f["key"]: f["value"] for f in r["facts"]}["feeds_24h"] == "8"  # two sides are one feed
    assert not any("feeds in 24 hours" in n["text"] for n in r["nudges"])
    mins = lambda x: (int(x[:2]) * 60 + int(x[3:]) - 420) % 1440  # noqa: E731
    sleeps = [x for x in r["schedule"] if x["kind"] != "feed"]
    assert not any(mins(b["time"]) <= mins(f["time"]) < mins(b["end"]) for b in sleeps for f in r["schedule"]
                   if f["kind"] == "feed")


async def test_day_sleeps_at_changing_hours_still_get_their_blocks_between_the_feeds(client):
    # From the live server: 3 night sleeps at fixed hours, and 2 day sleeps at hours that change each day. With one
    # count for the 24 hours the night took all blocks, and the plan showed 4 feeds in a row with no sleep.
    s, c, cid = await child(client, birthdate="2026-10-07")
    for d in range(4, 16):
        for h, m, length in ((20, 20, 65), (1, 30, 125), (4, 5, 145)):
            add(s, cid, "sleep", local(d, h, m), local(d, h, m) + timedelta(minutes=length))
        for h, length in ((8 + d % 3, 60), (13 + (d * 2) % 4, 90)):  # 08:00 to 10:00, and 13:00 to 16:00
            add(s, cid, "sleep", local(d, h, 15), local(d, h, 15) + timedelta(minutes=length))
        for h, m in ((0, 30), (3, 40), (6, 30), (9, 5), (11, 20), (13, 55), (16, 0), (18, 50), (21, 30)):
            add(s, cid, "nursing", local(d, h, m), local(d, h, m) + timedelta(minutes=10))
    s.commit()
    r = regime(s, c, BNE, NOW)
    usual = [x for x in r["schedule"] if x["kind"] != "feed" and not x["change"]]
    assert [x["kind"] for x in usual].count("nap") == 2 and [x["kind"] for x in usual].count("night") == 3
    kinds = "".join("f" if x["kind"] == "feed" else "s" for x in r["schedule"])
    assert "ffff" not in kinds  # no long run of feeds with no sleep between


async def test_a_young_baby_with_a_long_night_gets_naps_and_a_night(client):
    s, c, cid = await child(client, birthdate="2026-09-07")  # 10 weeks, and the logs show a night of 10 hours
    for d in range(6, 17):
        day(s, cid, d, bed=(20, 0), naps=((8, 0, 90), (11, 0, 90), (14, 0, 90), (17, 0, 45)))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["mode"] == "clock" and rows(r, feeds=False)[0] == ("08:00", "09:30", "nap")
    assert rows(r, feeds=False)[-1][2] == "night"


async def test_logs_that_fit_no_known_pattern_give_a_rough_guide_and_no_steps(client):
    # A family on night shifts: the child sleeps in the day. The app finds no night, and it must say so.
    s, c, cid = await child(client, birthdate="2026-01-10")
    for d in range(4, 16):
        add(s, cid, "sleep", local(d, 8), local(d, 15))
        add(s, cid, "sleep", local(d, 17), local(d, 18))
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["confidence"] == "low" and r["nudges"] == [] and not any(x["change"] for x in r["schedule"])
    assert "do not show one regular pattern" in r["notes"][0]["text"] and "night sleep" in r["notes"][0]["text"]
    # A different number of naps each day: also a rough guide.
    s, c, cid = await child3(client)
    for d in range(4, 16):
        day(s, cid, d, bed=(21, 30), naps=[(9 + 2 * i, 0, 30) for i in range(d % 5)], feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["confidence"] == "low" and r["nudges"] == [] and "number of naps" in r["notes"][0]["text"]
    # The same days for a baby of 4 months: a changing number of naps is normal there. Not a rough guide.
    s, c, cid = await child3(client, birthdate="2026-07-10", email="e@example.com")
    for d in range(4, 16):
        day(s, cid, d, bed=(21, 30), naps=[(9 + 2 * i, 0, 30) for i in range(d % 5)], feeds=())
    s.commit()
    r = regime(s, c, BNE, NOW)
    assert r["confidence"] == "normal" and any("The number of naps is changing" in n["text"] for n in r["notes"])


async def child3(client, birthdate="2026-01-10", email="c@example.com"):
    _, cid = await make_family(client, email=email, birthdate=birthdate)
    s, ctx = ctx_for(email)
    return s, get_child(s, ctx, cid), cid


async def child2(client):
    _, cid = await make_family(client, email="b@example.com", birthdate="2026-10-07")
    s, ctx = ctx_for("b@example.com")
    return s, get_child(s, ctx, cid), cid


async def test_the_route_and_the_helpers(client):
    h, cid = await make_family(client)
    r = await client.get(f"{API}/children/{cid}/sleep/regime", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["basis"] == "age" and body["schedule"][-1]["kind"] == "night" and body["sources"] and body["nudges"] == []
    assert pct([1, 2, 3, 4, 5], 0.5) == 3 and pct([0, 10], 0.1) == 1
    assert blend([], None) is None and blend([], 7)["basis"] == "age"
    assert blend([10, 10], 20) == {"value": 16, "basis": "mixed", "samples": 2}
    assert blend([1, 1, 1, 1, 50], 20)["value"] == 1  # 5 days: own median only, the tail does not count
