"""M9 new logging: play with tummy time, confined time with the note and the warning, nappy details and their rules."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from sqlalchemy import select

from frecklebubby.ai.assistant import child_context
from frecklebubby.ai.nl_log import summary, to_proposal
from frecklebubby.db import SessionLocal
from frecklebubby.mcp_server import create_mcp
from frecklebubby.models import Child, Entry, Notification
from frecklebubby.schemas import TimerBody
from frecklebubby.services import Conflict, Invalid, confined, insights, reports
from frecklebubby.services.library import library
from frecklebubby.services.reminders import tick
from frecklebubby.services.timers import act

from .conftest import ctx_for, make_family, utc

API = "/api/v1"
BNE = ZoneInfo("Australia/Brisbane")
T0 = utc(2026, 11, 10, 0, 0)  # 10:00 in Brisbane


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def born(years=0, months=0, days=0) -> str:
    """Birthdate for this age on T0 (Brisbane day 2026-11-10)."""
    y, m = divmod(11 - 1 - months, 12)
    return (date(2026 - years + y, m + 1, 10) - timedelta(days=days)).isoformat()


async def post(client, h, cid, **entry):
    return await client.post(f"{API}/children/{cid}/entries", headers=h, json=entry)


# --- validation ---------------------------------------------------------------------------------------------------


async def test_validation(client):
    h, cid = await make_family(client)
    ok = [
        {"type": "play", "started_at": "2026-11-10T09:00", "ended_at": "2026-11-10T09:20",
         "data": {"kind": "outdoor", "tummy_seconds": 300}},
        {"type": "play", "started_at": "2026-11-10T09:00", "data": {}},
        {"type": "confined", "started_at": "2026-11-10T09:00", "ended_at": "2026-11-10T10:00",
         "data": {"device": "car_seat"}},
        {"type": "nappy", "started_at": "2026-11-10T09:00", "data": {"mode": "poo"}},  # old shape stays valid
        {"type": "nappy", "started_at": "2026-11-10T09:00",
         "data": {"mode": "both", "air_minutes": 10, "pee_color": "dark_yellow", "pee_look": "cloudy",
                  "pee_smell": True, "color": "yellow"}},
    ]
    for e in ok:
        r = await post(client, h, cid, **e)
        assert r.status_code == 201, (e, r.text)
    r = await post(client, h, cid, type="nappy", started_at="2026-11-10T09:00",
                   data={"mode": "pee", "rash_severity": "mild"})
    assert r.json()["data"]["rash"] is True  # severity means a rash
    bad = [
        ("confined", {}), ("confined", {"device": "sofa"}), ("play", {"tummy_seconds": 86401}),
        ("play", {"kind": "park"}), ("nappy", {"mode": "pee", "air_minutes": 241}),
        ("nappy", {"mode": "poo", "pee_color": "red"}), ("nappy", {"mode": "dry", "pee_smell": True}),
        ("nappy", {"mode": "pee", "pee_color": "green"}), ("nappy", {"mode": "pee", "rash_severity": "bad"}),
    ]
    for type_, data in bad:
        r = await post(client, h, cid, type=type_, started_at="2026-11-10T09:00", data=data)
        assert r.status_code == 422, (type_, data, r.text)
    r = await client.post(f"{API}/children/{cid}/reminders", headers=h,
                          json={"type": "play", "mode": "in", "interval_minutes": 180})
    assert r.status_code == 201


# --- timers -------------------------------------------------------------------------------------------------------


async def test_play_timer_tummy_toggle(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    t, _ = act(s, ctx, cid, "play", "start", TimerBody(), now=at(0))
    assert t.data == {"tummy_seconds": 0, "tummy_started_at": None}
    t, _ = act(s, ctx, cid, "play", "switch", TimerBody(), now=at(2))  # tummy on
    assert t.data["tummy_started_at"] == at(2).isoformat()
    t, _ = act(s, ctx, cid, "play", "switch", TimerBody(), now=at(5))  # off: 3 min
    assert t.data == {"tummy_seconds": 180, "tummy_started_at": None}
    act(s, ctx, cid, "play", "switch", TimerBody(), now=at(6))  # on again
    t, _ = act(s, ctx, cid, "play", "pause", TimerBody(), now=at(8))  # pause closes the tummy part: +2 min
    assert t.data == {"tummy_seconds": 300, "tummy_started_at": None}
    with pytest.raises(Conflict):
        act(s, ctx, cid, "play", "switch", TimerBody(), now=at(9))
    act(s, ctx, cid, "play", "resume", TimerBody(), now=at(10))
    act(s, ctx, cid, "play", "switch", TimerBody(), now=at(11))
    _, e = act(s, ctx, cid, "play", "complete", TimerBody(data={"kind": "indoor"}), now=at(15))  # +4 min
    assert e.data == {"tummy_seconds": 540, "kind": "indoor"}
    assert (e.type, e.started_at, e.ended_at) == ("play", at(0), at(15))
    s.close()


async def test_confined_timer_needs_device(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    with pytest.raises(Invalid, match="device: required"):
        act(s, ctx, cid, "confined", "start", TimerBody(), now=at(0))
    with pytest.raises(Invalid, match="device: use it only"):
        act(s, ctx, cid, "sleep", "start", TimerBody(device="pram"), now=at(0))
    t, _ = act(s, ctx, cid, "confined", "start", TimerBody(device="pram"), now=at(0))
    t, _ = act(s, ctx, cid, "confined", "start", TimerBody(at=at(-5), device="car_seat"), now=at(1))
    assert (t.started_at, t.data) == (at(-5), {"device": "car_seat"})
    _, e = act(s, ctx, cid, "confined", "complete", TimerBody(), now=at(30))
    assert e.data == {"device": "car_seat"}
    s.close()


# --- reports ------------------------------------------------------------------------------------------------------


async def test_day_report_play_confined_nappies(client):
    h, cid = await make_family(client)
    for e in [
        {"type": "play", "started_at": "2026-11-09T09:00", "ended_at": "2026-11-09T09:30",
         "data": {"tummy_seconds": 600}},
        {"type": "activity", "started_at": "2026-11-09T10:00", "ended_at": "2026-11-09T10:05",
         "data": {"kind": "tummyTime"}},
        {"type": "activity", "started_at": "2026-11-09T11:00", "ended_at": "2026-11-09T11:20",
         "data": {"kind": "outdoorPlay"}},
        {"type": "activity", "started_at": "2026-11-09T12:00", "ended_at": "2026-11-09T12:10",
         "data": {"kind": "bath"}},  # not play
        # two car trips 8 min apart = one 70-minute period; a later 20-minute bouncer time
        {"type": "confined", "started_at": "2026-11-09T13:00", "ended_at": "2026-11-09T13:40",
         "data": {"device": "car_seat"}},
        {"type": "confined", "started_at": "2026-11-09T13:48", "ended_at": "2026-11-09T14:10",
         "data": {"device": "car_seat"}},
        {"type": "confined", "started_at": "2026-11-09T16:00", "ended_at": "2026-11-09T16:20",
         "data": {"device": "bouncer"}},
        {"type": "nappy", "started_at": "2026-11-09T08:00", "data": {"mode": "pee", "rash": True, "air_minutes": 15}},
        {"type": "nappy", "started_at": "2026-11-09T12:00", "data": {"mode": "poo", "air_minutes": 5}},
    ]:
        assert (await post(client, h, cid, **e)).status_code == 201
    r = await client.get(f"{API}/children/{cid}/reports/daily?from=2026-11-09&to=2026-11-09", headers=h)
    d = r.json()["days"][0]
    assert d["play"] == {"count": 3, "seconds": 1800 + 300 + 1200, "tummy_seconds": 600 + 300}
    assert d["confined"] == {"count": 3, "seconds": 2400 + 1320 + 1200, "longest_seconds": 70 * 60}
    assert d["nappies"] == {"wet": 1, "dirty": 1, "air_minutes": 20, "rash": 1}
    assert d["activities"]["tummyTime"] == {"count": 1, "seconds": 300}  # old activity totals stay
    rec = r.json()["tummy_recommendation"]  # child born 2026-06-01: under 12 months
    assert rec["minutes"] == 30 and rec["citation"]["url"].startswith("https://www.who.int/")


async def test_tummy_recommendation_age(client):
    _, cid = await make_family(client, birthdate=born(months=13))
    s, ctx = ctx_for("a@example.com")
    assert reports.daily(s, ctx, cid, now=T0)["tummy_recommendation"] is None
    s.close()


# --- confined continuity and notifications ------------------------------------------------------------------------


def run(now) -> int:
    with SessionLocal() as s:
        return tick(s, now)


def notes() -> list[tuple[str, str, str]]:
    with SessionLocal() as s:
        return [(n.kind, n.title, n.body) for n in s.scalars(select(Notification).order_by(Notification.id))]


async def confined_child(client, birthdate: str, device="car_seat", start=0):
    h, cid = await make_family(client, birthdate=birthdate)
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "confined", "start", TimerBody(at=at(start), device=device), now=at(start))
    s.close()
    return h, cid


async def test_note_and_warning_under_12_months(client, pushes):
    h, cid = await confined_child(client, born(months=11))
    assert run(at(59)) == 0
    assert run(at(60)) == 1
    assert run(at(61)) == 0  # one note per period
    assert run(at(119)) == 0
    assert run(at(120)) == 1
    assert run(at(200)) == 0
    got = notes()
    assert [k for k, _, _ in got] == ["confined:note", "confined:warning"]
    assert got[0][1:] == ("Ada: in the car seat for 1 hour", got[0][2])
    assert "not restrained for more than 1 hour at a time" in got[0][2]
    assert got[1][1] == "Ada: time for a break"
    assert "take a break every 2 to 3 hours on a day trip" in got[1][2]
    assert "rule of thumb" not in got[1][2] and "limit" not in got[1][2]
    assert len(pushes) == 0  # no push subscription in this family; notify still saved both


async def test_no_warning_at_13_months(client):
    await confined_child(client, born(months=13))
    assert run(at(60)) == 1
    assert run(at(180)) == 0
    assert [k for k, _, _ in notes()] == ["confined:note"]


@pytest.mark.parametrize("birthdate,expected", [
    (born(years=4), ["confined:note"]),
    (born(years=5, days=-1), ["confined:note"]),  # 5 years tomorrow
    (born(years=5), []),
])
async def test_note_age_limit(client, birthdate, expected):
    await confined_child(client, birthdate)
    run(at(130))
    assert [k for k, _, _ in notes()] == expected


async def test_short_stop_does_not_reset_the_clock(client):
    h, cid = await make_family(client, birthdate=born(months=6))
    # 40 min in the car, a 10-minute stop, then the timer from 10:50: continuous since 10:00.
    await post(client, h, cid, type="confined", started_at="2026-11-10T10:00", ended_at="2026-11-10T10:40",
               data={"device": "car_seat"})
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "confined", "start", TimerBody(at=at(50), device="car_seat"), now=at(50))
    child = s.get(Child, cid)
    info = confined.now_info(s, child, BNE, at(60))
    assert (info["since"], info["seconds"], info["device"]) == (at(0), 3600, "car_seat")
    assert info["note"]["after_seconds"] == 3600 and info["warning"]["after_seconds"] == 7200
    s.close()
    assert run(at(60)) == 1


async def test_longer_stop_resets_the_clock(client):
    h, cid = await make_family(client, birthdate=born(months=6))
    await post(client, h, cid, type="confined", started_at="2026-11-10T10:00", ended_at="2026-11-10T10:40",
               data={"device": "pram"})
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "confined", "start", TimerBody(at=at(51), device="pram"), now=at(51))
    s.close()
    assert run(at(100)) == 0
    assert run(at(111)) == 1


async def test_status_has_confined_block(client):
    h, cid = await make_family(client)
    r = await client.get(f"{API}/children/{cid}/status", headers=h)
    assert r.json()["confined"] is None
    await client.post(f"{API}/children/{cid}/timers/confined/start", headers=h, json={"device": "bouncer"})
    st = (await client.get(f"{API}/children/{cid}/status", headers=h)).json()
    c = st["confined"]
    assert c["device"] == "bouncer" and c["seconds"] < 60
    assert c["note"]["citations"][0]["kind"] == "bundled"
    assert "20 minutes at a time" in c["warning"]["text"]  # not a car seat: WHO and NHS seat advice


# --- insight cards and red flags ------------------------------------------------------------------------------------


def cards_for(now=None) -> dict[str, dict]:
    s, ctx = ctx_for("a@example.com")
    child = s.scalar(select(Child))
    out = {c["kind"]: c for c in insights.insights(s, ctx, child.id, now)}
    s.close()
    return out


def add(type_: str, hours_ago: float, data: dict, ended_hours_ago: float | None = None, now=None):
    now = now or datetime.now(BNE).astimezone(ZoneInfo("UTC")).replace(microsecond=0)
    with SessionLocal() as s:
        child = s.scalar(select(Child))
        s.add(Entry(child_id=child.id, type=type_, started_at=now - timedelta(hours=hours_ago), data=data,
                    ended_at=now - timedelta(hours=ended_hours_ago) if ended_hours_ago is not None else None))
        s.commit()


async def test_rash_card(client):
    await make_family(client, birthdate=(date.today() - timedelta(days=150)).isoformat())
    add("nappy", 30, {"mode": "pee", "rash": True})
    assert "nappy_rash" not in cards_for()  # one rash, more than 24 h ago
    add("nappy", 2, {"mode": "pee", "rash": True, "air_minutes": 10})
    c = cards_for()["nappy_rash"]
    assert c["severity"] == "info"
    assert "leave nappies off when possible" in c["body"] and "little tummy time" in c["body"]
    assert "10 min" in c["body"] and "health visitor" not in c["body"]
    assert [x["title"] for x in c["citations"]][0] == "Nappy rash"
    add("nappy", 50, {"mode": "pee", "rash": True})
    c = cards_for()["nappy_rash"]
    assert c["severity"] == "attention" and "see a health visitor or GP" in c["body"]


async def test_confined_card(client):
    await make_family(client, birthdate=(date.today() - timedelta(days=150)).isoformat())
    add("confined", 30, {"device": "car_seat"}, ended_hours_ago=29.5)
    assert "confined" not in cards_for()
    add("confined", 50, {"device": "car_seat"}, ended_hours_ago=47.5)  # 2 h 30 min
    c = cards_for()["confined"]
    assert c["severity"] == "attention" and "longest: 2 h 30 min" in c["body"]


async def test_pee_red_flags(client):
    await make_family(client, birthdate=(date.today() - timedelta(days=10)).isoformat())
    add("nappy", 1, {"mode": "pee", "pee_color": "dark_yellow"})
    add("nappy", 2, {"mode": "pee", "pee_color": "orange_pink"})
    c = cards_for()
    assert c["dark_pee_newborn"]["severity"] == "urgent" and "jaundice" in c["dark_pee_newborn"]["body"]
    assert c["pee_red"]["title"] == "Pink or red pee" and "orange or pink pee" in c["pee_red"]["body"]


async def test_no_newborn_rule_after_28_days(client):
    await make_family(client, birthdate=(date.today() - timedelta(days=40)).isoformat())
    add("nappy", 1, {"mode": "pee", "pee_color": "dark_yellow"})
    assert "dark_pee_newborn" not in cards_for()


async def test_dark_pee_joins_wet_nappy_card(client):
    await make_family(client, birthdate=(date.today() - timedelta(days=60)).isoformat())
    for d in (1, 2, 3):
        add("nappy", 24 * d, {"mode": "pee", "pee_color": "dark_yellow" if d == 2 else "yellow"})
    c = cards_for()["wet_nappies"]
    assert c["severity"] == "attention" and "dark yellow, strong-smelling pee" in c["body"]
    assert c["citations"][-1]["title"].startswith("Dehydration")


async def test_assistant_context_has_rash(client):
    await make_family(client)
    add("nappy", 3, {"mode": "pee", "rash": True})
    s, ctx = ctx_for("a@example.com")
    text = child_context(s, ctx, s.scalar(select(Child)), datetime.now(ZoneInfo("UTC")))
    s.close()
    assert "Nappy rash logged on 1 of the last 8 days, last on" in text


# --- every fact in the new texts has a supporting phrase in the cited file -------------------------------------------

SUPPORT = {
    **confined.SUPPORT,
    "tummy_30": ("who-under-5-activity-sleep", "For infants not yet mobile, this includes at least 30 minutes in prone "
                                               "position (tummy time) spread throughout the day while awake."),
    "rash_air": ("nhs-nappy-rash", "leave nappies off when possible"),
    "rash_change": ("nhs-nappy-rash", "change wet or dirty nappies as soon as possible"),
    "rash_help": ("nhs-nappy-rash", "See a health visitor or GP if:"),
    "rash_help_1": ("nhs-nappy-rash", "your baby's nappy rash does not go away, gets worse or spreads to other areas"),
    "rash_help_2": ("nhs-nappy-rash", "your baby has a high temperature"),
    "rash_help_3": ("nhs-nappy-rash", "your baby seems very uncomfortable"),
    "air_prevents": ("nhs-nappies-and-poo", "Wearing a nappy all the time makes nappy rash more likely."),
    "dehydration": ("nhs-dehydration", "dark yellow, strong-smelling pee"),
    "dehydration_wet": ("nhs-dehydration", "fewer wet nappies than usual"),
    "jaundice_pee": ("nhs-newborn-jaundice", "their pee is dark yellow or brown or their poo is a pale creamy colour"),
    "jaundice_when": ("nhs-newborn-jaundice", "Ask for an urgent GP or midwife appointment or call NHS 111 if your baby "
                                              "is over 24 hours old and:"),
    "pee_blood": ("nhs-blood-in-urine", "Blood in your pee may be bright pink, red or dark brown."),
    "pee_blood_check": ("nhs-blood-in-urine", "you need to get it checked, even if there's only a small amount or "
                                              "you're not sure it's blood"),
    "pee_blood_gp": ("nhs-blood-in-urine", "Ask for an urgent GP appointment"),
    "pee_blood_adults": ("nhs-blood-in-urine", "This NHS page is written for adults."),
    "poo_blood": ("nhs-rectal-bleeding", "See a GP if your child has blood in their poo."),
}


def test_support_phrases_are_in_the_cited_files():
    for name, phrase in SUPPORT.values():
        assert phrase in library(name)[1], (name, phrase)


# --- MCP, natural language, export ----------------------------------------------------------------------------------


async def test_mcp_tools(client):
    h, cid = await make_family(client)
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        r = (await mcp.call_tool("log_play", {"start_time": "2026-11-10T09:00", "end_time": "2026-11-10T09:20",
                                              "tummy_minutes": 5, "kind": "indoor"})).structured_content
        assert r["data"] == {"kind": "indoor", "tummy_seconds": 300.0}
        r = (await mcp.call_tool("confined_timer", {"action": "start", "device": "high_chair"})).structured_content
        assert r["timer"]["data"] == {"device": "high_chair"}
        r = (await mcp.call_tool("log_nappy", {"mode": "pee", "rash_severity": "moderate", "air_minutes": 10,
                                               "pee_color": "pale"})).structured_content
        assert r["data"] == {"mode": "pee", "rash": True, "rash_severity": "moderate", "air_minutes": 10,
                             "pee_color": "pale"}
        r = (await mcp.call_tool("log_confined", {"device": "pram", "start_time": "2026-11-10T08:00",
                                                  "end_time": "2026-11-10T08:30"})).structured_content
        assert r["type"] == "confined"
        r = (await mcp.call_tool("play_timer", {"action": "start"})).structured_content
        r = (await mcp.call_tool("play_timer", {"action": "switch"})).structured_content
        assert r["timer"]["data"]["tummy_started_at"]
    csv = (await client.get(f"{API}/children/{cid}/export.csv", headers=h)).text
    assert 'play,' in csv and '"{""kind"":""indoor"",""tummy_seconds"":300.0}"' in csv


NOW = datetime(2026, 11, 20, 14, 35, tzinfo=BNE)


def test_nl_proposals():
    p = to_proposal({"type": "play", "end": "now", "duration": "20 minutes", "tummy_minutes": 5}, NOW)
    assert (p["started_at"], p["ended_at"], p["data"]) == (NOW - timedelta(minutes=20), NOW, {"tummy_seconds": 300})
    p = to_proposal({"type": "confined", "start": "9", "device": "car_seat"}, NOW)
    assert p == {"action": "timer", "type": "confined", "timer_action": "start", "at": NOW.replace(hour=9, minute=0),
                 "device": "car_seat"}
    p = to_proposal({"type": "nappy", "at": "now", "mode": "pee", "rash": True, "air_minutes": 10}, NOW)
    assert p["data"] == {"mode": "pee", "rash": True, "air_minutes": 10}
    p = to_proposal({"type": "nappy", "at": "now", "mode": "pee", "pee_color": "dark_yellow"}, NOW)
    assert p["data"] == {"mode": "pee", "pee_color": "dark_yellow", "rash": False}


async def test_nl_summary(client):
    await make_family(client)
    s, ctx = ctx_for("a@example.com")
    p = {"action": "entry", "type": "play", "started_at": NOW - timedelta(minutes=20), "ended_at": NOW,
         "data": {"tummy_seconds": 300}}
    assert summary(p, ctx) == "Play – tummy time 5 min – 14:15 to 14:35 (20 min)"
    p = {"action": "timer", "type": "confined", "timer_action": "start", "device": "car_seat", "at": NOW}
    assert summary(p, ctx) == "Confined timer – start – car seat – 14:35"
    s.close()


async def test_nl_commit_confined_timer(client):
    h, cid = await make_family(client)
    prop = {"action": "timer", "type": "confined", "timer_action": "start", "device": "swing"}
    r = await client.post(f"{API}/children/{cid}/nl/commit", headers=h, json={"proposals": [prop]})
    assert r.status_code == 200, r.text
    assert r.json()["timers"][0]["data"] == {"device": "swing"}
