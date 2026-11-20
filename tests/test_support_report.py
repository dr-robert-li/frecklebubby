"""M11 support report: statuses from fixed rules, model suggestions and their checks, fallback, save and replace."""

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastmcp import Client
from sqlalchemy import func, select

from frecklebubby.ai import support_report
from frecklebubby.config import PACKAGE_DATA
from frecklebubby.mcp_server import create_mcp
from frecklebubby.models import SupportReport
from frecklebubby.services import reports, support
from frecklebubby.services.library import library

from .conftest import ctx_for, make_family
from .fake_llm import fake_llm_fixture  # noqa: F401

API = "/api/v1"
BNE = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 11, 10, 14, 0, tzinfo=BNE)  # in the past, so seeded entries are never "in the future"


def test_support_phrases_are_in_the_cited_files():
    for name, phrase in support.SUPPORT.values():
        assert phrase in library(name)[1], (name, phrase)
    sleep_file = library(support.SLEEP)[1]
    for r in json.loads((PACKAGE_DATA / "wake_windows.json").read_text())["total_sleep"]:
        assert f"{r['min_hours']} to {r['max_hours']} hours" in sleep_file, r
    assert reports.TUMMY["source"] == support.WHO


def t(days: float, hour: int, minute: int = 0) -> str:
    """Local time `days` before NOW's day at hour:minute."""
    return (NOW.replace(hour=hour, minute=minute) - timedelta(days=days)).isoformat()


async def seed(client, birth_days=130):
    """A 4-month-old with short sleep, few wet nappies, little tummy time, a long car seat trip and one cry."""
    born = (NOW - timedelta(days=birth_days)).date().isoformat()
    h, cid = await make_family(client, birthdate=born)
    rows = []
    for d in (1, 2, 3):
        rows.append({"type": "sleep", "started_at": t(d, 9), "ended_at": t(d, 17), "data": {}})
        rows += [{"type": "nappy", "started_at": t(d, hr), "data": {"mode": "pee"}} for hr in (8, 12, 16)]
        rows += [{"type": "activity", "started_at": t(d, 10), "ended_at": t(d, 10, 20), "data": {"kind": "indoorPlay"}},
                 {"type": "activity", "started_at": t(d, 10), "ended_at": t(d, 10, 5), "data": {"kind": "tummyTime"}}]
    rows.append({"type": "confined", "started_at": t(2, 13), "ended_at": t(2, 14, 30), "data": {"device": "car_seat"}})
    rows.append({"type": "cry", "started_at": t(1, 18), "ended_at": t(1, 18, 20), "data": {}})
    rows.append({"type": "nappy", "started_at": t(0, 9), "data": {"mode": "pee"}})
    for r in rows:
        res = await client.post(f"{API}/children/{cid}/entries", headers=h, json=r)
        assert res.status_code == 201, res.text
    return h, cid


async def make(cid, now=NOW):
    s, ctx = ctx_for("a@example.com")
    try:
        return await support_report.generate(s, ctx, cid, now)
    finally:
        s.close()


def texts(rep: dict) -> list[str]:
    out = [rep["goes_well"]["text"], rep["footer"]]
    for b in rep["blocks"]:
        out += [b["title"], b["note"] or "", *(n["label"] for n in b["numbers"]), *b["details"],
                *(x["text"] for x in b["suggestions"]), b["reference"]["text"] if b["reference"] else ""]
    return out


async def test_statuses_and_fallback_without_model(client, fake_llm):
    _, cid = await seed(client)
    fake_llm.down = True
    rep = await make(cid)
    by = {b["area"]: b for b in rep["blocks"]}
    assert [b["area"] for b in rep["blocks"]] == ["sleep", "feeds", "nappies", "play", "confined", "crying", "growth",
                                                  "milestones"]
    assert {a: b["status"] for a, b in by.items()} == {
        "sleep": "watch", "feeds": "no_data", "nappies": "watch", "play": "watch", "confined": "watch",
        "crying": "ok", "growth": "no_data", "milestones": "ok"}
    assert by["sleep"]["numbers"][0] == {"label": "Average a day (3 logged days)", "value": 8.0, "unit": "h"}
    assert by["play"]["numbers"][1] == {"label": "Tummy time a day", "value": 5.0, "unit": "min"}
    assert by["confined"]["numbers"][1] == {"label": "Longest without a break", "value": 90.0, "unit": "min"}
    assert by["sleep"]["compared"] and not by["crying"]["compared"] and not by["feeds"]["compared"]
    assert by["crying"]["reference"] is None  # the crying review covers 0 to 12 weeks
    assert by["milestones"]["title"] == "Milestones by 4 months" and by["milestones"]["details"]
    assert rep["ai"] is False and rep["notice"] == support_report.NOTICE
    for b in rep["blocks"]:
        if b["status"] == "watch":
            assert b["suggested_by"] == "rules" and b["suggestions"], b["area"]
            n = {c["n"] for c in b["citations"]}
            assert all(set(x["cites"]) <= n for x in b["suggestions"])
        else:
            assert b["suggestions"] == [] and b["suggested_by"] is None
        assert "_well" not in b
    assert rep["goes_well"]["text"] == support.DEFAULT_WELL
    assert not [x for x in texts(rep) if re.search(r"\bshould\b", x, re.I)]
    assert rep["footer"] == "General information, not medical advice."
    assert rep["from"] == "2026-11-03" and str(rep["to"]) == "2026-11-10" and rep["days"] == 8


async def test_ok_against_the_references(client, fake_llm):
    born = (NOW - timedelta(days=130)).date().isoformat()
    h, cid = await make_family(client, birthdate=born)
    for d in (1, 2, 3):
        rows = [{"type": "sleep", "started_at": t(d, 1), "ended_at": t(d, 14), "data": {}},
                {"type": "activity", "started_at": t(d, 15), "ended_at": t(d, 16), "data": {"kind": "indoorPlay"}},
                {"type": "activity", "started_at": t(d, 15), "ended_at": t(d, 15, 32), "data": {"kind": "tummyTime"}}]
        rows += [{"type": "nappy", "started_at": t(d, 14, m), "data": {"mode": "pee"}} for m in range(0, 60, 9)]
        for r in rows:
            assert (await client.post(f"{API}/children/{cid}/entries", headers=h, json=r)).status_code == 201
    fake_llm.replies.append({"goes_well": {"text": "Sleep is going well [1].", "cites": []}})
    rep = await make(cid)
    by = {b["area"]: b["status"] for b in rep["blocks"]}
    assert by["sleep"] == by["play"] == by["nappies"] == "ok" and by["confined"] == "no_data"
    assert list(fake_llm.requests[0]["response_format"]["json_schema"]["schema"]["properties"]) == ["goes_well"]
    assert "Areas in range:\n- sleep (Sleep)" in fake_llm.requests[0]["messages"][1]["content"]
    assert rep["goes_well"]["text"] == "Sleep is going well." and rep["goes_well"]["cites"] == [1] and rep["ai"]
    fake_llm.replies.append({"goes_well": {"text": "Sleep is 13 hours.", "cites": []}})  # a number: not allowed
    rep = await make(cid)
    assert rep["goes_well"]["text"] == "Average logged sleep is in the recommended range for the age."
    assert rep["goes_well"]["citations"][0]["title"].startswith("Recommended sleep duration")
    assert rep["notice"] == support_report.NOTICE


async def test_model_suggestions_are_checked(client, fake_llm):
    _, cid = await seed(client)
    fake_llm.replies.append({
        "areas": [
            {"area": "sleep", "suggestions": [
                {"text": "Try a calm bedtime routine.", "cites": [1]},
                {"text": "Aim for 987 hours of sleep.", "cites": [1]},  # 987 is not in the input
                {"text": "Read a story [42].", "cites": []}]},  # citation that does not exist
            {"area": "play", "suggestions": [{"text": "You should do more tummy time.", "cites": [1]}]},
            {"area": "nappies", "suggestions": [{"text": "Offer feeds often.", "cites": []}]},  # no citation
        ],
        "goes_well": {"text": "Crying was logged on 1 day [1].", "cites": []},
    })
    rep = await make(cid)
    schema = fake_llm.requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["areas"]["items"]["properties"]["area"]["enum"] == ["sleep", "nappies", "play",
                                                                                    "confined"]
    prompt = fake_llm.requests[0]["messages"][1]["content"]
    assert "Areas to support:\n- sleep (Sleep): Average a day (3 logged days): 8 h" in prompt and "\n[1] " in prompt
    by = {b["area"]: b for b in rep["blocks"]}
    sleep = by["sleep"]
    assert sleep["suggested_by"] == "model" and [x["text"] for x in sleep["suggestions"]] == [
        "Try a calm bedtime routine."]
    n = sleep["suggestions"][0]["cites"][0]
    assert next(c for c in sleep["citations"] if c["n"] == n)["kind"] == "bundled"  # a block-local number
    assert by["play"]["suggested_by"] == "rules" and by["nappies"]["suggested_by"] == "rules"
    assert "goes_well" not in schema["properties"]  # no area in range: the rules line stays
    assert rep["goes_well"]["text"] == support.DEFAULT_WELL
    assert rep["ai"] is True and rep["notice"] is None


async def test_invalid_output_gives_the_standard_tips(client, fake_llm):
    _, cid = await seed(client)
    fake_llm.replies.append({"areas": [{"area": "sleep", "suggestions": [{"text": "Sleep more [7].", "cites": [7]}]}],
                             "goes_well": {"text": "All is well.", "cites": [99]}})
    rep = await make(cid)
    assert rep["ai"] is False and rep["notice"] == support_report.NOTICE
    assert all(b["suggested_by"] in ("rules", None) for b in rep["blocks"])


async def test_nothing_logged_needs_no_model(client, fake_llm):
    _, cid = await make_family(client, birthdate=(NOW - timedelta(days=20)).date().isoformat())
    rep = await make(cid)
    assert fake_llm.requests == [] and rep["notice"] is None
    assert {b["status"] for b in rep["blocks"]} == {"no_data"}
    crying = next(b for b in rep["blocks"] if b["area"] == "crying")
    assert crying["citations"][0]["title"].startswith("Crying in the first 3 months")


async def test_save_replace_and_red_flags_api(client, fake_llm):
    h, cid = await make_family(client, birthdate=(datetime.now(BNE) - timedelta(days=40)).date().isoformat())
    url = f"{API}/children/{cid}/support-report"
    r = await client.get(url, headers=h)
    assert r.status_code == 200 and r.json() is None
    fake_llm.down = True
    first = (await client.post(url, headers=h)).json()
    assert first["notice"] is None and first["urgent"] == []  # nothing logged: no model call
    # a red flag after the report: the saved report shows it (red flags are read again)
    now = datetime.now(BNE) - timedelta(minutes=5)
    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "temperature", "started_at": now.isoformat(), "data": {"celsius": 38.4}})
    got = (await client.get(url, headers=h)).json()
    assert got["id"] == first["id"] and got["created_at"] == first["created_at"]
    assert got["urgent"][0]["severity"] == "urgent" and got["urgent"][0]["kind"] == "fever_under_3m"
    second = (await client.post(url, headers=h)).json()
    assert second["id"] == first["id"]
    s, _ = ctx_for("a@example.com")
    assert s.scalar(select(func.count()).select_from(SupportReport)) == 1
    s.close()
    other, _ = await make_family(client, email="b@example.com")
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.post(url, headers=other)).status_code == 404


async def test_mcp_tool(client, fake_llm):
    await make_family(client)
    fake_llm.down = True
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        assert (await mcp.call_tool("get_support_report", {})).structured_content["result"] is None
        rep = (await mcp.call_tool("get_support_report", {"make": True})).structured_content["result"]
        assert len(rep["blocks"]) == 8 and "from" in rep and rep["footer"]
