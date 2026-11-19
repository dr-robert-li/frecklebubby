from datetime import date, timedelta

import pytest

from frecklebubby.db import utcnow
from frecklebubby.models import Child, Entry
from frecklebubby.services.insights import red_flags, text_flags

from .conftest import ctx_for, make_family

NOW = utcnow()


@pytest.fixture
def kid(client):
    """kid(age_days, entries=[(type, hours_ago, data)]) -> red-flag kinds for that child now."""

    async def make(age_days: int, entries=()):
        await make_family(client, birthdate=(date.today() - timedelta(days=age_days)).isoformat())
        s, ctx = ctx_for("a@example.com")
        child = s.query(Child).one()
        for type_, hours, data in entries:
            s.add(Entry(child_id=child.id, type=type_, started_at=NOW - timedelta(hours=hours), data=data))
        s.commit()
        cards = red_flags(s, child, ctx.tz, NOW)
        s.close()
        return cards

    return make


def kinds(cards):
    return {c["kind"]: c["severity"] for c in cards}


def temp(c, hours=1):
    return ("temperature", hours, {"celsius": c})


@pytest.mark.parametrize("age_days,celsius,expected", [
    (60, 37.9, {}), (60, 38.0, {"fever_under_3m": "urgent"}),
    (120, 38.5, {}), (120, 38.9, {}), (120, 39.0, {"fever_3_to_6m": "urgent"}),
    (400, 39.5, {}),
    (60, 36.0, {}), (60, 35.9, {"low_temperature": "urgent"}),
])
async def test_temperature_thresholds(kid, age_days, celsius, expected):
    assert kinds(await kid(age_days, [temp(celsius)])) == expected


async def test_fever_citation_and_text(kid):
    card = (await kid(60, [temp(38.2)]))[0]
    assert card["citations"][0] == {"n": 1, "kind": "link", "title": "High temperature (fever) in children",
                                    "publisher": "NHS", "url": "https://www.nhs.uk/symptoms/fever-in-children/"}
    assert "38.2 °C" in card["body"] and "emergency department" in card["body"]


async def test_old_reading_is_ignored(kid):
    assert kinds(await kid(60, [temp(38.5, hours=25)])) == {}


@pytest.mark.parametrize("hours,expected", [
    (23, {}), (25, {"fever_24h_under_2y": "attention"}),
    (24 * 5, {"fever_24h_under_2y": "attention", "fever_5_days": "urgent"}),
    (24 * 5 - 1, {"fever_24h_under_2y": "attention"}),
])
async def test_fever_duration(kid, hours, expected):
    assert kinds(await kid(400, [temp(38.4, hours), temp(38.6, hours / 2), temp(38.1)])) == expected


async def test_fever_24h_not_over_2_years(kid):
    assert kinds(await kid(800, [temp(38.4, 30), temp(38.1)])) == {}


async def test_fever_episode_ends_with_normal_reading(kid):
    assert kinds(await kid(400, [temp(38.4, 30), temp(37.0, 10), temp(38.1)])) == {}


@pytest.mark.parametrize("readings,expected", [
    ([40.1, 40.2], {"fever_above_40_repeated": "attention"}), ([40.1], {}), ([40.0, 40.0], {}),
])
async def test_above_40_repeated(kid, readings, expected):
    out = kinds(await kid(800, [temp(c, 2 + i) for i, c in enumerate(readings)]))
    assert {k: v for k, v in out.items() if k == "fever_above_40_repeated"} == expected


def nappy(hours, mode="pee", color=None):
    return ("nappy", hours, {"mode": mode, **({"color": color} if color else {})})


@pytest.mark.parametrize("age_days,hours,expected", [
    (60, 7.9, {}), (60, 8, {"no_wet_nappy": "attention"}), (60, 12, {"no_wet_nappy": "urgent"}),
    (200, 8, {}), (200, 12, {"no_wet_nappy": "urgent"}),
])
async def test_wet_nappy(kid, age_days, hours, expected):
    assert kinds(await kid(age_days, [nappy(hours), nappy(1, "poo")])) == expected


async def test_wet_nappy_needs_logging(kid):
    assert kinds(await kid(60, [nappy(50)])) == {}  # nothing logged in the last 48 h


@pytest.mark.parametrize("age_days,color,expected", [
    (5, "black", {}), (30, "black", {"stool_black": "urgent"}), (5, "red", {"stool_red": "urgent"}),
    (30, "gray", {"stool_pale": "urgent"}), (30, "green", {}), (30, "yellow", {}),
])
async def test_stool_colour(kid, age_days, color, expected):
    # Black poo in the first week is meconium; a fresh wet nappy keeps the wet-nappy rule quiet.
    assert kinds(await kid(age_days, [nappy(1, "both", color)])) == expected


@pytest.mark.parametrize("reaction,expected", [("ALLERGIC", {"allergic_reaction": "urgent"}), ("LOVED", {})])
async def test_allergic(kid, reaction, expected):
    cards = await kid(300, [("solids", 2, {"foods": [{"name": "egg"}], "reaction": reaction})])
    assert kinds(cards) == expected
    if cards:
        assert "(egg)" in cards[0]["body"] and cards[0]["citations"][0]["publisher"] == "NHS"


@pytest.mark.parametrize("text,age_days,expected", [
    ("baby has a fever 38.5", 60, ["fever_under_3m"]),
    ("temp is 101 F", 60, ["fever_under_3m"]),
    ("she is 39.2°C", 120, ["fever_3_to_6m"]),
    ("temperature 38.5", 120, []),
    ("temp 35.5", 400, ["low_temperature"]),
    ("she drank 120 ml at 38 minutes past", 60, []),
    ("temp 37.2", 60, []),
])
def test_text_flags(text, age_days, expected):
    child = Child(birthdate=date.today() - timedelta(days=age_days))
    assert [c["kind"] for c in text_flags(text, child, NOW)] == expected


async def test_insights_endpoint(client):
    born = (date.today() - timedelta(days=130)).isoformat()
    h, cid = await make_family(client, birthdate=born)
    for d in range(1, 5):  # 4 days of 13 h sleep
        start = NOW - timedelta(days=d, hours=13)
        await client.post(f"/api/v1/children/{cid}/entries", headers=h, json={
            "type": "sleep", "started_at": start.isoformat(), "ended_at": (start + timedelta(hours=13)).isoformat()})
    await client.post(f"/api/v1/children/{cid}/entries", headers=h, json={
        "type": "temperature", "started_at": (NOW - timedelta(hours=1)).isoformat(), "data": {"celsius": 39.4}})
    r = await client.get(f"/api/v1/children/{cid}/insights", headers=h)
    assert r.status_code == 200
    cards = r.json()
    assert cards[0]["severity"] == "urgent" and cards[0]["kind"] == "fever_3_to_6m"
    by_kind = {c["kind"]: c for c in cards}
    assert "sleep_total" in by_kind and by_kind["sleep_total"]["citations"][0]["year"] in (2015, 2016)
    assert "milestones" in by_kind and by_kind["milestones"]["citations"][0]["publisher"] == "CDC"
    assert all(c["citations"] and c["citations"][0]["n"] == 1 for c in cards)
    hb, _ = await make_family(client, email="b@example.com")
    assert (await client.get(f"/api/v1/children/{cid}/insights", headers=hb)).status_code == 404
