"""Bath: an instant entry with a time and optional notes."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastmcp import Client

from frecklebubby.ai.nl_log import summary, to_proposal
from frecklebubby.mcp_server import create_mcp

from .conftest import ctx_for, make_family
from .fake_llm import fake_llm_fixture  # noqa: F401

API = "/api/v1"
NOW = datetime(2026, 11, 20, 14, 35, tzinfo=ZoneInfo("Australia/Brisbane"))


async def bath_entries(client, h, cid):
    return (await client.get(f"{API}/children/{cid}/entries?type=bath", headers=h)).json()


async def test_create_edit_delete_and_isolation(client):
    h, cid = await make_family(client)
    r = await client.post(f"{API}/children/{cid}/entries", headers=h,
                          json={"type": "bath", "started_at": "2026-11-10T18:00", "notes": "Warm"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["type"], e["data"], e["notes"], e["ended_at"]) == ("bath", {}, "Warm", None)
    r = await client.post(f"{API}/children/{cid}/entries", headers=h, json={
        "type": "bath", "started_at": "2026-11-10T18:00", "ended_at": "2026-11-10T18:15"})
    assert r.status_code == 422 and "no end time" in r.text

    hb, _ = await make_family(client, email="b@example.com", child="Bea")
    assert (await client.get(f"{API}/entries/{e['id']}", headers=hb)).status_code == 404
    assert (await client.patch(f"{API}/entries/{e['id']}", headers=hb, json={"notes": "x"})).status_code == 404
    assert (await client.delete(f"{API}/entries/{e['id']}", headers=hb)).status_code == 404
    assert (await client.get(f"{API}/children/{cid}/entries?type=bath", headers=hb)).status_code == 404

    r = await client.patch(f"{API}/entries/{e['id']}", headers=h,
                           json={"started_at": "2026-11-10T18:30", "notes": "Quick"})
    assert r.status_code == 200 and r.json()["notes"] == "Quick" and r.json()["started_at"].startswith(
        "2026-11-10T08:30")
    st = (await client.get(f"{API}/children/{cid}/status", headers=h)).json()
    assert st["last"]["bath"]["id"] == e["id"]
    assert (await client.delete(f"{API}/entries/{e['id']}", headers=h)).status_code == 204
    assert await bath_entries(client, h, cid) == []


async def test_report_counts_baths_and_old_bath_activities(client):
    h, cid = await make_family(client)
    for e in ({"type": "bath", "started_at": "2026-11-10T08:00"}, {"type": "bath", "started_at": "2026-11-10T18:00"},
              {"type": "activity", "started_at": "2026-11-09T18:00", "data": {"kind": "bath"}},
              {"type": "activity", "started_at": "2026-11-09T19:00", "data": {"kind": "storyTime"}}):
        assert (await client.post(f"{API}/children/{cid}/entries", headers=h, json=e)).status_code == 201
    days = (await client.get(f"{API}/children/{cid}/reports/daily?from=2026-11-09&to=2026-11-10",
                             headers=h)).json()["days"]
    assert [d["bath_count"] for d in days] == [1, 2]
    csv = (await client.get(f"{API}/children/{cid}/export.csv", headers=h)).text
    assert csv.count(",bath,") == 2


async def test_mcp_log_list_and_plain_words(client, fake_llm):
    h, cid = await make_family(client)
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        r = (await mcp.call_tool("log_bath", {"start_time": "2026-11-10T18:00", "notes": "Hair wash"})
             ).structured_content
        assert (r["type"], r["notes"], r["data"]) == ("bath", "Hair wash", {})
        fake_llm.replies.append({"events": [{"type": "bath", "at": "now"}]})
        out = (await mcp.call_tool("log_in_plain_words", {"text": "just had a bath"})).structured_content
        assert out["saved"][0]["type"] == "bath" and not out["proposals"]
        listed = (await mcp.call_tool("list_entries", {"type": "bath", "start": "2026-11-01T00:00",
                                                       "end": "2030-01-01T00:00"})).structured_content
        tools = {t.name: t.description for t in await mcp.list_tools()}
    assert [e["type"] for e in listed["result"]] == ["bath", "bath"]
    assert "bath" in tools["log_bath"].lower()
    assert len(await bath_entries(client, h, cid)) == 2


async def test_plain_words_in_chat(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "bath", "at": "now"}]})
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h, json={"message": "gave her a bath"})
    assert r.status_code == 200, r.text
    assert len(await bath_entries(client, h, cid)) == 1


async def test_nl_proposal_and_summary(client):
    await make_family(client)
    for at, hour in (("6pm", 18), ("now", 14)):  # "bath at 6pm", "just had a bath"
        p = to_proposal({"type": "bath", "at": at}, NOW)
        assert (p["type"], p["started_at"].hour, p["ended_at"], p["data"]) == ("bath", hour, None, {})
    s, ctx = ctx_for("a@example.com")
    assert summary(to_proposal({"type": "bath", "at": "6pm"}, NOW), ctx) == "Bath – 18:00"
    s.close()
