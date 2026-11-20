"""M14: log from the assistant chat and from MCP (fake model)."""

from datetime import timedelta

import pytest
from fastmcp import Client

from frecklebubby.ai.nl_log import split_question
from frecklebubby.db import utcnow
from frecklebubby.mcp_server import create_mcp

from .conftest import make_family
from .fake_llm import fake_llm_fixture, sse_events  # noqa: F401

CHAT = "/api/v1/children/{}/assistant/chat"
BOTTLE = {"events": [{"type": "bottle", "at": "now", "amount": 120, "unit": "ml", "milk_type": "Formula"}]}


@pytest.mark.parametrize("text, report, asks", [
    ("she had 120 ml at 2", "she had 120 ml at 2", False),
    ("she only slept 20 minutes, is that normal?", "she only slept 20 minutes", True),
    ("how can I help her learn to sit?", "", True),
    ("what should she be doing now", "", True),
    ("is 120 ml, or 150 ml, enough?", "", True),
    ("can you log a wet nappy", "can you log a wet nappy", False),
    ("temp 38.5 at 1pm. Should I worry?", "temp 38.5 at 1pm", True),
    ("start a nap", "start a nap", False),
    ("and dirty nappies?", "", True),
])
def test_split_question(text, report, asks):
    assert split_question(text) == (report, asks)


async def chat(client, h, cid, message):
    r = await client.post(CHAT.format(cid), headers=h, json={"message": message})
    assert r.status_code == 200, r.text
    return sse_events(r.text)


async def entries(client, h, cid, type_=None):
    q = f"?type={type_}" if type_ else ""
    return (await client.get(f"/api/v1/children/{cid}/entries{q}", headers=h)).json()


async def messages(client, h, cid):
    return (await client.get(f"/api/v1/children/{cid}/assistant/messages", headers=h)).json()


async def test_report_is_saved_with_no_answer_call_then_undo(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append(BOTTLE)
    events = await chat(client, h, cid, "she had 120 ml of formula")
    assert len(fake_llm.requests) == 1 and fake_llm.requests[0]["response_format"]  # the parse call only
    kinds = [e for e, _ in events]
    assert kinds == ["logged", "citations", "done"]
    logged = events[0][1]
    assert logged["message"] == "Logged 1 item." and not logged["proposals"]
    item = logged["items"][0]
    assert item["type"] == "bottle" and item["summary"].startswith("Bottle – 120 ml formula – ") and not item["undone"]
    saved = await entries(client, h, cid, "bottle")
    assert [e["id"] for e in saved] == [item["entry_id"]] and saved[0]["source"] == "nl"

    # After a reload the Logged block is in the history.
    msgs = await messages(client, h, cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["id"] == logged["message_id"] == events[-1][1]["message_id"]
    assert msgs[1]["logged"]["items"][0]["entry_id"] == item["entry_id"] and msgs[0]["logged"] is None

    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{msgs[1]['id']}/undo", headers=h,
                          json={"item": 0})
    assert r.status_code == 200 and r.json()["logged"]["items"][0]["undone"] is True
    assert await entries(client, h, cid, "bottle") == []
    assert (await messages(client, h, cid))[1]["logged"]["items"][0]["undone"] is True
    # A second undo changes nothing; a wrong index is 404.
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{msgs[1]['id']}/undo", headers=h,
                          json={"item": 0})
    assert r.status_code == 200
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{msgs[1]['id']}/undo", headers=h,
                          json={"item": 5})
    assert r.status_code == 404


async def test_question_is_never_logged(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append("Around 6 wet nappies a day is usual [1].")
    events = await chat(client, h, cid, "how many wet nappies a day is normal?")
    assert len(fake_llm.requests) == 1 and "response_format" not in fake_llm.requests[0]
    assert "logged" not in [e for e, _ in events]
    assert await entries(client, h, cid) == []
    assert (await messages(client, h, cid))[1]["logged"] is None


async def test_log_and_ask_in_one_turn(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies += [{"events": [{"type": "sleep", "end": "now", "duration": "20 minutes"}]},
                         "Short naps are common [1]."]
    events = await chat(client, h, cid, "she only slept 20 minutes, is that normal?")
    kinds = [e for e, _ in events]
    assert kinds[0] == "logged" and "token" in kinds and kinds[-2:] == ["citations", "done"]
    assert fake_llm.requests[0]["messages"][1]["content"].endswith("Note: she only slept 20 minutes")
    prompt = fake_llm.requests[1]["messages"][-1]["content"]
    assert "Just logged from this message: Sleep – " in prompt and "Question: she only slept 20 minutes" in prompt
    sleep = await entries(client, h, cid, "sleep")
    assert len(sleep) == 1
    msgs = await messages(client, h, cid)
    assert len(msgs) == 2 and msgs[1]["content"].startswith("Short naps are common")
    assert msgs[1]["logged"]["items"][0]["entry_id"] == sleep[0]["id"]


async def test_unsure_is_not_saved_then_confirmed(client, fake_llm):
    h, cid = await make_family(client)
    # The amount is not in the words: the model guessed it.
    fake_llm.replies.append(BOTTLE)
    events = await chat(client, h, cid, "she had a bottle")
    logged = events[0][1]
    assert logged["items"] == [] and logged["proposals"][0]["unsure"] == "the amount is not in your words"
    assert "Check this before I save" in logged["message"]
    assert await entries(client, h, cid) == []

    mid = logged["message_id"]
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{mid}/proposals", headers=h,
                          json={"proposals": logged["proposals"]})
    assert r.status_code == 200, r.text
    out = r.json()["logged"]
    assert out["proposals"] == [] and out["items"][0]["type"] == "bottle" and out["message"] == "Logged 1 item."
    assert len(await entries(client, h, cid, "bottle")) == 1

    # Dismiss: an empty list saves nothing.
    fake_llm.replies.append(BOTTLE)
    logged = (await chat(client, h, cid, "she had another bottle"))[0][1]
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{logged['message_id']}/proposals", headers=h,
                          json={"proposals": []})
    assert r.json()["logged"]["proposals"] == [] and r.json()["logged"]["items"] == []
    assert len(await entries(client, h, cid, "bottle")) == 1


async def test_unsure_double_old_note_and_running_timer(client, fake_llm):
    h, cid = await make_family(client)
    await client.post(f"/api/v1/children/{cid}/entries", headers=h, json={
        "type": "bottle", "started_at": (utcnow() - timedelta(minutes=5)).isoformat(), "data": {"amount_ml": 90}})
    fake_llm.replies.append(BOTTLE)
    p = (await chat(client, h, cid, "120 ml formula"))[0][1]["proposals"][0]
    assert p["unsure"].startswith("a bottle at ") and p["unsure"].endswith(" is already logged")

    fake_llm.replies.append({"events": [{"type": "nappy", "at": "30 hours ago", "mode": "pee"}]})
    p = (await chat(client, h, cid, "wet nappy 30 hours ago"))[0][1]["proposals"][0]
    assert p["unsure"] == "it is more than 24 hours ago"

    # The model must choose a nappy mode; when the words do not say it, that is a guess.
    fake_llm.replies.append({"events": [{"type": "nappy", "at": "now", "mode": "both", "rash": True}]})
    p = (await chat(client, h, cid, "nappy with a rash"))[0][1]["proposals"][0]
    assert p["unsure"] == "say if it was wet, dirty or dry"

    fake_llm.replies.append({"events": [{"type": "note", "at": "now", "text": "seems happy"}]})
    p = (await chat(client, h, cid, "she seems happy"))[0][1]["proposals"][0]
    assert p["unsure"] == "check the note"

    # With a question, a note is not what the parent wants to save: no Logged block, an answer.
    fake_llm.replies += [{"events": [{"type": "note", "at": "now", "text": "worried about sleep"}]}, "Sleep [1]."]
    events = await chat(client, h, cid, "I am worried about her sleep, what can I do?")
    assert "logged" not in [e for e, _ in events]

    await client.post(f"/api/v1/children/{cid}/timers/sleep/start", headers=h)
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "start"}]})
    p = (await chat(client, h, cid, "she fell asleep"))[0][1]["proposals"][0]
    assert p["unsure"] == "the sleep timer already runs"
    assert len(await entries(client, h, cid, "bottle")) == 1


async def test_repeated_item_is_not_saved_twice(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "nappy", "at": "now", "mode": "pee"}] * 3})
    logged = (await chat(client, h, cid, "wet nappy"))[0][1]
    assert len(logged["items"]) == 1
    assert [p["unsure"] for p in logged["proposals"]] == ["it is the same as another item"] * 2
    assert len(await entries(client, h, cid, "nappy")) == 1


async def test_invented_pee_details_are_dropped(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "nappy", "at": "now", "mode": "pee", "pee_color": "dark_yellow",
                                         "pee_look": "cloudy", "pee_smell": True}]})
    await chat(client, h, cid, "dark pee")
    assert (await entries(client, h, cid, "nappy"))[0]["data"] == {"mode": "pee", "rash": False,
                                                                   "pee_color": "dark_yellow"}


async def test_timer_from_chat_and_undo_cancels_it(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "start"}]})
    logged = (await chat(client, h, cid, "she just fell asleep"))[0][1]
    item = logged["items"][0]
    assert item["action"] == "timer" and item["timer_action"] == "start" and item["entry_id"] is None
    timers = (await client.get(f"/api/v1/children/{cid}/timers", headers=h)).json()
    assert [t["type"] for t in timers] == ["sleep"]
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{logged['message_id']}/undo", headers=h,
                          json={"item": 0})
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/children/{cid}/timers", headers=h)).json() == []
    # The timer is gone, so a later undo of a stop cannot work: the server says so.
    fake_llm.replies.append({"events": [{"type": "timer", "timer": "sleep", "action": "start"}]})
    logged = (await chat(client, h, cid, "she fell asleep again"))[0][1]
    await client.post(f"/api/v1/children/{cid}/timers/sleep/cancel", headers=h)
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{logged['message_id']}/undo", headers=h,
                          json={"item": 0})
    assert r.status_code == 409


async def test_model_down_after_logging_keeps_the_block(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append(BOTTLE)

    def down_after_parse(request, _orig=fake_llm.handler):
        if len(fake_llm.requests) >= 1:
            fake_llm.down = True
        return _orig(request)

    import httpx

    from frecklebubby.ai import llm
    llm.TRANSPORT = httpx.MockTransport(down_after_parse)
    events = await chat(client, h, cid, "120 ml formula, is that enough?")
    assert events[0][0] == "logged" and events[-1] == ("error", {"detail": "The assistant is not available now."})
    msgs = await messages(client, h, cid)
    assert msgs[1]["logged"]["items"][0]["type"] == "bottle" and msgs[1]["content"] == ""


async def test_other_family_cannot_undo(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append(BOTTLE)
    mid = (await chat(client, h, cid, "120 ml formula"))[0][1]["message_id"]
    hb, cb = await make_family(client, email="b@example.com")
    for c in (cid, cb):
        r = await client.post(f"/api/v1/children/{c}/assistant/messages/{mid}/undo", headers=hb, json={"item": 0})
        assert r.status_code == 404
    assert len(await entries(client, h, cid, "bottle")) == 1


async def test_mcp_log_in_plain_words(client, fake_llm):
    h, cid = await make_family(client)
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        fake_llm.replies.append(BOTTLE)
        out = (await mcp.call_tool("log_in_plain_words", {"text": "120 ml formula just now"})).structured_content
        assert out["message"] == "Logged 1 item." and out["saved"][0]["type"] == "bottle" and not out["proposals"]
        e = await entries(client, h, cid, "bottle")
        assert len(e) == 1 and e[0]["source"] == "nl"

        fake_llm.replies.append({"events": [{"type": "nappy", "at": "now", "mode": "pee"}]})
        out = (await mcp.call_tool("log_in_plain_words", {"text": "wet nappy", "save": False})).structured_content
        assert out["saved"] == [] and out["proposals"][0]["type"] == "nappy"
        assert await entries(client, h, cid, "nappy") == []

        fake_llm.replies.append(BOTTLE)  # a guess: not saved
        out = (await mcp.call_tool("log_in_plain_words", {"text": "a bottle"})).structured_content
        assert out["saved"] == [] and out["proposals"][0]["unsure"] == "the amount is not in your words"

        tools = {t.name: t.description for t in await mcp.list_tools()}
    # Each entry type has a tool whose description names it.
    for words, tool in (("play", "log_activity"), ("tummy time", "log_activity"), ("car seat", "log_confined"),
                        ("crying", "log_cry"), ("bottle", "log_bottle"), ("breastfeed", "log_nursing"),
                        ("nappy", "log_nappy"), ("potty", "log_potty"), ("pump", "log_pump"),
                        ("milestone", "log_milestone"), ("note", "log_note"), ("medicine", "log_medicine"),
                        ("temperature", "log_temperature"), ("growth", "log_growth"), ("solid", "log_solids"),
                        ("bath", "log_activity"), ("story", "log_activity"), ("sleep", "log_sleep")):
        assert words in tools[tool].lower(), (words, tool)
