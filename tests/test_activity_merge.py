"""0.2.2: play and bath are activity kinds, and activity timers run in parallel (one per kind)."""

import json

from fastmcp import Client
from sqlalchemy import create_engine, text

from frecklebubby.db import init_db
from frecklebubby.mcp_server import create_mcp

from .conftest import make_family
from .fake_llm import fake_llm_fixture  # noqa: F401

API = "/api/v1"
OLD_TIMER = """CREATE TABLE timer (id INTEGER NOT NULL PRIMARY KEY, child_id INTEGER NOT NULL REFERENCES child (id)
ON DELETE CASCADE, type VARCHAR NOT NULL, started_at VARCHAR(20) NOT NULL, paused_at VARCHAR(20),
paused_seconds INTEGER NOT NULL, data JSON NOT NULL, started_by INTEGER REFERENCES user (id) ON DELETE SET NULL,
UNIQUE (child_id, type))"""


def rows(c, sql: str) -> list[tuple]:
    return [tuple(r) for r in c.execute(text(sql))]


async def test_old_database_is_converted_once(client, tmp_path):
    h, cid = await make_family(client)
    eng = create_engine(f"sqlite:///{tmp_path / 'frecklebubby.db'}")
    entry = ("INSERT INTO entry (child_id, type, started_at, ended_at, data, notes, source, created_by, created_at, "
             "updated_at) VALUES (:c, :t, :s, :e, :d, :n, 'app', 1, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')")
    timer = ("INSERT INTO timer (child_id, type, started_at, paused_seconds, data) "
             "VALUES (:c, :t, '2026-11-10T01:00:00Z', 0, :d)")
    with eng.begin() as c:  # a 0.2.1 database
        c.execute(text("DROP TABLE timer"))
        c.execute(text(OLD_TIMER))
        for t, s, e, d, n in (
                ("bath", "2026-11-09T08:00:00Z", None, {}, "Warm"),
                ("play", "2026-11-09T09:00:00Z", "2026-11-09T09:20:00Z", {"kind": "outdoor", "tummy_seconds": 300}, "Park"),
                ("play", "2026-11-09T10:00:00Z", "2026-11-09T10:30:00Z", {"tummy_seconds": 0}, None),
                ("activity", "2026-11-09T11:00:00Z", None, {"kind": "storyTime"}, None)):
            c.execute(text(entry), {"c": cid, "t": t, "s": s, "e": e, "d": json.dumps(d), "n": n})
        for t, d in (("activity", {"kind": "storyTime"}),
                     ("play", {"tummy_seconds": 60, "tummy_started_at": "2026-11-10T01:05:00+00:00"}),
                     ("sleep", {})):
            c.execute(text(timer), {"c": cid, "t": t, "d": json.dumps(d)})
        for t in ("play", "bath", "bottle"):
            c.execute(text("INSERT INTO reminder (child_id, type, mode, interval_minutes, times, days, daytime_only, "
                           "enabled) VALUES (:c, :t, 'in', 60, '[]', '[]', 0, 1)"), {"c": cid, "t": t})
        # A chat turn saved by 0.2.1: its JSON is not converted.
        logged = {"items": [{"action": "timer", "type": "play", "timer_action": "start", "summary": "Play timer",
                             "entry_id": None, "undone": False}],
                  "proposals": [{"action": "entry", "type": "bath", "started_at": "2026-11-09T08:00:00Z",
                                 "data": {}, "summary": "Bath"},
                                {"action": "entry", "type": "note", "started_at": "2026-11-09T08:00:00Z",
                                 "notes": "x", "summary": "Note"}],
                  "message": "Logged 1 item."}
        c.execute(text("INSERT INTO chat_message (child_id, role, content, citations, logged, created_at) "
                       "VALUES (:c, 'assistant', 'ok', '[]', :l, '2026-11-09T08:00:00Z')"),
                  {"c": cid, "l": json.dumps(logged)})

    init_db(tmp_path)
    with eng.begin() as c:
        first = (rows(c, "SELECT type, started_at, ended_at, data, notes FROM entry ORDER BY id"),
                 rows(c, "SELECT type, kind, started_at, data FROM timer ORDER BY id"),
                 rows(c, "SELECT type FROM reminder ORDER BY id"))
    entries, timers, reminders = first
    assert entries == [
        ("activity", "2026-11-09T08:00:00Z", None, '{"kind":"bath"}', "Warm"),
        ("activity", "2026-11-09T09:00:00Z", "2026-11-09T09:20:00Z", '{"kind":"outdoorPlay"}', "Park"),
        ("activity", "2026-11-09T10:00:00Z", "2026-11-09T10:30:00Z", '{"kind":"indoorPlay"}', None),
        ("activity", "2026-11-09T11:00:00Z", None, '{"kind": "storyTime"}', None),
        ("activity", "2026-11-09T09:00:00Z", "2026-11-09T09:05:00Z", '{"kind":"tummyTime"}', None),
    ]
    assert timers == [
        ("activity", "storyTime", "2026-11-10T01:00:00Z", '{"kind": "storyTime"}'),
        ("activity", "indoorPlay", "2026-11-10T01:00:00Z", '{"kind":"indoorPlay"}'),
        ("sleep", "", "2026-11-10T01:00:00Z", "{}"),
        ("activity", "tummyTime", "2026-11-10T01:05:00Z", '{"kind":"tummyTime"}'),
    ]
    assert reminders == [("activity",), ("activity",), ("bottle",)]

    init_db(tmp_path)  # a second start changes nothing
    with eng.begin() as c:
        assert (rows(c, "SELECT type, started_at, ended_at, data, notes FROM entry ORDER BY id"),
                rows(c, "SELECT type, kind, started_at, data FROM timer ORDER BY id"),
                rows(c, "SELECT type FROM reminder ORDER BY id")) == first

    # The app reads the converted data and the old chat JSON.
    st = (await client.get(f"{API}/children/{cid}/status", headers=h)).json()
    assert sorted(t["data"].get("kind", t["type"]) for t in st["timers"]) == [
        "indoorPlay", "sleep", "storyTime", "tummyTime"]
    days = (await client.get(f"{API}/children/{cid}/reports/daily?from=2026-11-09&to=2026-11-09",
                             headers=h)).json()["days"]
    assert days[0]["bath_count"] == 1 and days[0]["play"] == {"count": 2, "seconds": 3000, "tummy_seconds": 300}
    msgs = (await client.get(f"{API}/children/{cid}/assistant/messages", headers=h))
    assert msgs.status_code == 200, msgs.text
    assert [p["type"] for p in msgs.json()[0]["logged"]["proposals"]] == ["note"]  # the old bath proposal is left out
    r = await client.post(f"{API}/children/{cid}/assistant/messages/{msgs.json()[0]['id']}/undo", headers=h,
                          json={"item": 0})
    assert r.status_code == 409  # no play timer type now: a plain answer, not a crash


async def test_chat_logs_bath_and_tummy_time_and_undo(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "activity", "kind": "bath", "start": "now"},
                                        {"type": "timer", "timer": "activity", "action": "start", "kind": "tummyTime"},
                                        {"type": "timer", "timer": "activity", "action": "start",
                                         "kind": "indoorPlay"}]})
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h,
                          json={"message": "gave her a bath, started tummy time and play"})
    assert r.status_code == 200, r.text
    msg = (await client.get(f"{API}/children/{cid}/assistant/messages", headers=h)).json()[-1]
    assert [i["summary"].split(" – ")[:2] for i in msg["logged"]["items"]] == [
        ["Activity", "bath"], ["Activity timer", "start"], ["Activity timer", "start"]]
    # Undo the tummy time start: only that timer stops.
    r = await client.post(f"{API}/children/{cid}/assistant/messages/{msg['id']}/undo", headers=h, json={"item": 1})
    assert r.status_code == 200, r.text
    timers = (await client.get(f"{API}/children/{cid}/timers", headers=h)).json()
    assert [t["data"]["kind"] for t in timers] == ["indoorPlay"]

    fake_llm.replies.append({"events": [{"type": "timer", "timer": "activity", "action": "complete",
                                         "kind": "indoorPlay"}]})
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h, json={"message": "stop the play"})
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/children/{cid}/timers", headers=h)).json() == []
    kinds = [e["data"]["kind"] for e in (await client.get(f"{API}/children/{cid}/entries?type=activity",
                                                          headers=h)).json()]
    assert sorted(kinds) == ["bath", "indoorPlay"]


async def test_plain_words_need_a_kind_when_two_run(client, fake_llm):
    h, cid = await make_family(client)
    for kind in ("indoorPlay", "tummyTime"):
        await client.post(f"{API}/children/{cid}/timers/activity/start", headers=h, json={"kind": kind})
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "activity", "action": "complete"}]})
    out = (await client.post(f"{API}/children/{cid}/nl/parse", headers=h, json={"text": "stop it"})).json()
    assert out["proposals"] == [] and "indoorPlay, tummyTime" in out["message"]
    r = await client.post(f"{API}/children/{cid}/timers/activity/complete", headers=h, json={})
    assert r.status_code == 422 and "Say which kind" in r.text
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        tools = {t.name: t.description for t in await mcp.list_tools()}
        r = (await mcp.call_tool("activity_timer", {"action": "complete", "kind": "tummyTime"})).structured_content
    assert r["entry"]["data"] == {"kind": "tummyTime"}
    assert "several kinds can run at once" in tools["activity_timer"].lower()
    assert not {"play_timer", "log_play", "log_bath"} & set(tools)


async def test_an_activity_that_ends_now_stops_its_running_timer(client, fake_llm):
    h, cid = await make_family(client)
    await client.post(f"{API}/children/{cid}/timers/activity/start", headers=h, json={"kind": "tummyTime"})
    fake_llm.replies.append({"events": [{"type": "activity", "kind": "tummyTime", "end": "now"}]})
    out = (await client.post(f"{API}/children/{cid}/nl/parse", headers=h, json={"text": "stop tummy time"})).json()
    assert [(p["action"], p["timer_action"], p["kind"]) for p in out["proposals"]] == [
        ("timer", "complete", "tummyTime")]
