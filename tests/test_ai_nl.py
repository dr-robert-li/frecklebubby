from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from frecklebubby.ai.nl_log import parse_duration, parse_time, resolve, to_proposal

from .conftest import make_family
from .fake_llm import fake_llm_fixture  # noqa: F401

BNE = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 11, 20, 14, 35, tzinfo=BNE)


def clock(h, m=0, ampm="unsure", day="unsure"):
    return {"hour": h, "minute": m, "ampm": ampm, "day": day}


def test_resolve_times():
    assert resolve(clock(2), NOW) == NOW.replace(hour=14, minute=0)  # "at 2" at 14:35 = 14:00
    assert resolve(clock(3), NOW) == NOW.replace(hour=3, minute=0)  # 15:00 is still to come
    assert resolve(clock(8), NOW) == NOW.replace(hour=8, minute=0)
    assert resolve(clock(7, 30, "pm", "yesterday"), NOW) == datetime(2026, 11, 19, 19, 30, tzinfo=BNE)
    assert resolve(clock(13, 45), NOW) == NOW.replace(hour=13, minute=45)
    assert resolve({"minutes_ago": 20}, NOW) == NOW.replace(minute=15)
    assert resolve({"now": True}, NOW) == NOW
    # A start must not be after the end: "slept 9 till 6:10" = 21:00 yesterday to 06:10.
    end = resolve(clock(6, 10, "am", "today"), NOW)
    assert resolve(clock(9), NOW, before=end) == datetime(2026, 11, 19, 21, 0, tzinfo=BNE)


@pytest.mark.parametrize("words,expected", [
    ("now", NOW), ("just now", NOW), ("", NOW), ("20 minutes ago", NOW.replace(minute=15)),
    ("an hour and a half ago", NOW.replace(hour=13, minute=5)), ("half an hour ago", NOW.replace(minute=5)),
    ("at 2", NOW.replace(hour=14, minute=0)), ("quarter to 2", NOW.replace(hour=13, minute=45)),
    ("half past 12", NOW.replace(hour=12, minute=30)), ("quarter past 9", NOW.replace(hour=9, minute=15)),
    ("1pm", NOW.replace(hour=13, minute=0)), ("2am", NOW.replace(hour=2, minute=0)),
    ("8 this morning", NOW.replace(hour=8, minute=0)), ("noon", NOW.replace(hour=12, minute=0)),
    ("7:15 last night", datetime(2026, 11, 19, 19, 15, tzinfo=BNE)), ("2 last night", NOW.replace(hour=2, minute=0)),
    ("6:30 pm yesterday", datetime(2026, 11, 19, 18, 30, tzinfo=BNE)), ("at 14:05", NOW.replace(hour=14, minute=5)),
])
def test_parse_time_words(words, expected):
    assert resolve(parse_time(words), NOW) == expected


def test_parse_duration():
    assert [parse_duration(x) for x in ("an hour and a half", "45 minutes", "1.5 hours", "1h 20m", "half an hour",
                                        "two hours", "lunch")] == [90, 45, 90, 80, 30, 120, None]
    assert parse_time("for lunch") is None


def test_to_proposal_spans_and_units():
    p = to_proposal({"type": "sleep", "end": "10 minutes ago", "duration": "45 minutes"}, NOW)
    assert (p["started_at"], p["ended_at"]) == (NOW.replace(hour=13, minute=40), NOW.replace(minute=25))
    p = to_proposal({"type": "nursing", "start": "at 2", "left_minutes": 10, "right_minutes": 7,
                     "last_side": "right"}, NOW)
    assert p["data"] == {"left_seconds": 600, "right_seconds": 420, "last_side": "right"}
    assert p["ended_at"] == NOW.replace(hour=14, minute=17)
    assert to_proposal({"type": "bottle", "at": "now", "amount": 4, "unit": "oz"}, NOW)["data"] == {
        "amount_ml": 118.3}
    assert to_proposal({"type": "temperature", "at": "now", "value": 100.4, "unit": "F"}, NOW)["data"] == {
        "celsius": 38.0}
    assert to_proposal({"type": "growth", "at": "now", "weight": 6200, "weight_unit": "g"}, NOW)["data"] == {
        "weight_kg": 6.2}
    # Asleep since a time with no end = a running sleep.
    p = to_proposal({"type": "sleep", "start": "5 minutes ago"}, NOW)
    assert p["action"] == "timer" and p["timer_action"] == "start"


async def test_parse_and_commit(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [
        {"type": "bottle", "at": "20 minutes ago", "amount": 4, "unit": "oz", "milk_type": "Formula"},
        {"type": "nappy", "at": "now", "mode": "pee"},
        {"type": "bottle", "at": "now", "amount": 900, "unit": "ml"},  # invalid: dropped with a reason
    ]})
    r = await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "4oz formula 20 min ago, wet"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [p["type"] for p in out["proposals"]] == ["bottle", "nappy"]
    assert out["proposals"][0]["data"] == {"amount_ml": 118.3, "milk_type": "Formula"}
    assert out["proposals"][0]["summary"].startswith("Bottle – 118.3 ml formula – ")
    assert out["proposals"][1]["summary"].startswith("Nappy – wet – ")
    assert "could not use 1" in out["message"] and "amount_ml" in out["message"]
    # The prompt has the schema, the current time and the note; the server does the unit conversion.
    req = fake_llm.requests[0]
    assert req["response_format"]["type"] == "json_schema" and "Note: 4oz formula" in req["messages"][1]["content"]

    r = await client.post(f"/api/v1/children/{cid}/nl/commit", headers=h, json={"proposals": out["proposals"]})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert [e["source"] for e in created] == ["nl", "nl"] and created[0]["data"]["amount_ml"] == 118.3


async def test_commit_all_or_nothing(client, fake_llm):
    h, cid = await make_family(client)
    good = {"action": "entry", "type": "nappy", "started_at": "2026-11-01T10:00:00Z", "data": {"mode": "poo"}}
    bad = {"action": "entry", "type": "bottle", "started_at": "2026-11-01T10:00:00Z", "data": {"amount_ml": 900}}
    r = await client.post(f"/api/v1/children/{cid}/nl/commit", headers=h, json={"proposals": [good, bad]})
    assert r.status_code == 422 and r.json()["detail"].startswith("Item 2: data.amount_ml")
    assert (await client.get(f"/api/v1/children/{cid}/entries", headers=h)).json() == []
    timer = {"action": "timer", "type": "sleep", "timer_action": "complete"}  # no timer runs
    r = await client.post(f"/api/v1/children/{cid}/nl/commit", headers=h, json={"proposals": [good, timer]})
    assert r.status_code == 404
    assert (await client.get(f"/api/v1/children/{cid}/entries", headers=h)).json() == []


async def test_timer_phrases(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "start"}]})
    r = await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "she just fell asleep"})
    props = r.json()["proposals"]
    assert props == [{"action": "timer", "type": "sleep", "timer_action": "start", "summary": "Sleep timer – start – now"}]
    r = await client.post(f"/api/v1/children/{cid}/nl/commit", headers=h, json={"proposals": props})
    assert r.json()["timers"][0]["type"] == "sleep"

    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "complete"}]})
    r = await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "she's awake"})
    props = r.json()["proposals"]
    assert props[0]["timer_action"] == "complete"
    assert "Running timers: sleep timer since" in fake_llm.requests[-1]["messages"][1]["content"]
    r = await client.post(f"/api/v1/children/{cid}/nl/commit", headers=h, json={"proposals": props})
    assert r.json()["created"][0]["type"] == "sleep" and r.json()["created"][0]["source"] == "nl"

    # No timer runs now: "awake" again is not proposed.
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "complete"}]})
    out = (await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "awake"})).json()
    assert out["proposals"] == [] and "No sleep timer is running" in out["message"]


async def test_nothing_understood(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": []})
    out = (await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "purple monkey"})).json()
    assert out["proposals"] == [] and out["message"].startswith("I did not find anything")


async def test_diaper_wording_and_units(client, fake_llm):
    h, cid = await make_family(client)
    await client.patch("/api/v1/family/settings", headers=h, json={"wording": "diaper", "units": {"volume": "oz"}})
    fake_llm.replies.append({"events": [{"type": "nappy", "at": "now", "mode": "both"},
                                        {"type": "bottle", "at": "now", "amount": 120, "unit": "ml"}]})
    out = (await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "x"})).json()
    assert out["proposals"][0]["summary"].startswith("Diaper – wet and dirty")
    assert out["proposals"][1]["summary"].startswith("Bottle – 4.1 oz")


async def test_model_down_gives_503_and_trackers_work(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.down = True
    r = await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": "wet nappy"})
    assert r.status_code == 503 and r.json() == {"detail": "The assistant is not available now."}
    r = await client.post(f"/api/v1/children/{cid}/entries", headers=h,
                          json={"type": "nappy", "started_at": "2026-11-01T10:00:00Z", "data": {"mode": "pee"}})
    assert r.status_code == 201


async def test_other_family_child(client, fake_llm):
    await make_family(client)
    hb, _ = await make_family(client, email="b@example.com")
    r = await client.post("/api/v1/children/1/nl/parse", headers=hb, json={"text": "wet nappy"})
    assert r.status_code == 404 and not fake_llm.requests
