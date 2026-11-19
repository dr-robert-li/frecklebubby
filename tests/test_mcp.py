import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from frecklebubby.mcp_server import create_mcp

from .conftest import make_family

EXPECTED = {
    "list_children", "get_status", "sleep_timer", "log_sleep", "nursing_timer", "log_nursing", "log_bottle",
    "pump_timer", "log_pump", "activity_timer", "log_activity", "log_solids", "log_nappy", "log_potty", "log_growth",
    "log_temperature", "log_medicine", "log_milestone", "log_note", "list_entries", "update_entry", "delete_entry",
    "get_daily_report", "get_sleep_prediction", "get_milestones", "get_insights", "search_knowledge",
}


async def call(client, name, **args):
    return (await client.call_tool(name, args)).structured_content


async def test_tools(client):
    h, cid = await make_family(client)
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        assert {t.name for t in await mcp.list_tools()} == EXPECTED
        assert (await call(mcp, "list_children"))["result"][0]["name"] == "Ada"

        e = await call(mcp, "log_bottle", amount=4, units="oz", start_time="2026-11-01T08:00")
        assert e["data"]["amount_ml"] == 118.3 and e["source"] == "mcp"
        assert e["started_at"] == "2026-11-01T08:00:00+10:00"

        with pytest.raises(ToolError, match="data.amount_ml"):
            await mcp.call_tool("log_bottle", {"amount": 600})
        with pytest.raises(ToolError, match="not valid"):
            await mcp.call_tool("log_bottle", {"amount": 6, "start_time": "yesterday"})

        t = await call(mcp, "sleep_timer", action="start", child="ada")
        assert t["timer"]["type"] == "sleep"
        with pytest.raises(ToolError, match="end_time: use it only with complete"):
            await mcp.call_tool("sleep_timer", {"action": "pause", "end_time": "2026-11-01T09:00"})
        done = await call(mcp, "sleep_timer", action="complete", locations=["car"])
        assert done["entry"]["data"]["locations"] == ["car"] and done["timer"] is None

        await call(mcp, "log_growth", weight=10, units="imperial", start_time="2026-11-01T09:00")
        await call(mcp, "log_temperature", value=100.4, units="F", start_time="2026-11-01T09:00")
        await call(mcp, "log_nappy", mode="both", color="yellow", start_time="2026-11-01T10:00")
        await call(mcp, "log_note", text="Good day", start_time="2026-11-01T11:00")

        listed = (await call(mcp, "list_entries", start="2026-11-01T00:00", end="2026-11-02T00:00"))["result"]
        by_type = {x["type"]: x for x in listed}
        assert by_type["growth"]["data"]["weight_kg"] == 4.536
        assert by_type["temperature"]["data"]["celsius"] == 38.0

        upd = await call(mcp, "update_entry", entry_id=by_type["nappy"]["id"], data={"color": None, "rash": True})
        assert upd["data"] == {"mode": "both", "rash": True}
        assert "Deleted" in (await mcp.call_tool("delete_entry", {"entry_id": upd["id"]})).data

        rep = await call(mcp, "get_daily_report", from_date="2026-11-01", to_date="2026-11-01")
        assert rep["days"][0]["feeds"]["bottle_ml"] == 118.3
        status = await call(mcp, "get_status")
        assert status["timezone"] == "Australia/Brisbane"
        assert (await call(mcp, "get_milestones"))["bands"]
        assert isinstance((await call(mcp, "get_insights"))["result"], list)
        hits = (await call(mcp, "search_knowledge", query="how many wet nappies"))["result"]
        assert hits and hits[0]["url"].startswith("https://")

    # A second child makes the child argument required.
    await client.post("/api/v1/children", headers=h, json={"name": "Bo", "birthdate": "2025-01-01"})
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        with pytest.raises(ToolError, match="Say which child: Ada, Bo"):
            await mcp.call_tool("get_status", {})
        with pytest.raises(ToolError, match="No single child"):
            await mcp.call_tool("get_status", {"child": "Zed"})


async def test_mcp_family_isolation(client):
    h, cid = await make_family(client, "a@example.com")
    entry = (await client.post(f"/api/v1/children/{cid}/entries", headers=h, json={
        "type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "private"})).json()
    await make_family(client, "b@example.com", child="Bea")
    async with Client(create_mcp(fixed_email="b@example.com")) as mcp:
        with pytest.raises(ToolError, match="Entry not found"):
            await mcp.call_tool("delete_entry", {"entry_id": entry["id"]})
        with pytest.raises(ToolError, match="No single child"):
            await mcp.call_tool("get_status", {"child": str(cid)})
        with pytest.raises(ToolError, match="Entry not found"):
            await mcp.call_tool("update_entry", {"entry_id": entry["id"], "notes": "x"})
    assert (await client.get(f"/api/v1/entries/{entry['id']}", headers=h)).json()["notes"] == "private"


async def test_mcp_allowed_emails(env, client):
    await make_family(client, "a@example.com")
    env.setenv("ALLOWED_EMAILS", "other@example.com")
    from frecklebubby.config import get_settings
    get_settings.cache_clear()
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        with pytest.raises(ToolError, match="not allowed"):
            await mcp.call_tool("list_children", {})
