from datetime import date, timedelta

from frecklebubby.ai.assistant import FOOTER, CiteFilter

from .conftest import make_family, run_job
from .fake_llm import fake_llm_fixture, sse_events  # noqa: F401

CHAT = "/api/v1/children/{}/assistant/chat"


def test_cite_filter_split_tokens():
    f = CiteFilter({1, 2})
    out = "".join(f.feed(t) for t in ["Feed [", "1", "] often [", "7] and [2", ", 9]. See [Source 1]", " [a]"])
    assert out + f.flush() == "Feed [1] often  and [2]. See [1] [a]"


async def ask(client, h, cid, message):
    r = await client.post(CHAT.format(cid), headers=h, json={"message": message})
    return r, sse_events(r.text) if r.status_code == 200 else []


async def test_chat_streams_tokens_and_maps_citations(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append("Around 6 wet nappies a day is usual [1]. Some say 12 [99].")
    r, events = await ask(client, h, cid, "how many wet nappies is normal")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    kinds = [e for e, _ in events]
    assert kinds[-2:] == ["citations", "done"] and set(kinds[:-2]) == {"token"}
    text = "".join(d["text"] for e, d in events if e == "token")
    assert "[99]" not in text and "[1]" in text and text.endswith(FOOTER)
    cites = events[-2][1]["citations"]
    assert [c["n"] for c in cites] == [1] and cites[0]["url"].startswith("https://www.nhs.uk/")
    assert cites[0]["kind"] == "bundled" and cites[0]["publisher"]

    prompt = fake_llm.requests[0]["messages"]
    assert prompt[0]["role"] == "system" and "ONLY" in prompt[0]["content"]
    assert "Sources:\n[1] " in prompt[-1]["content"] and "Child data:" in prompt[-1]["content"]

    msgs = (await client.get(f"/api/v1/children/{cid}/assistant/messages", headers=h)).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["id"] == events[-1][1]["message_id"]
    assert [{k: v for k, v in c.items() if v is not None} for c in msgs[1]["citations"]] == cites

    # The next question carries the earlier turns.
    fake_llm.replies.append("Yes [2].")
    await ask(client, h, cid, "and dirty nappies?")
    roles = [m["role"] for m in fake_llm.requests[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]

    assert (await client.delete(f"/api/v1/children/{cid}/assistant/messages", headers=h)).status_code == 204
    assert (await client.get(f"/api/v1/children/{cid}/assistant/messages", headers=h)).json() == []


async def test_red_flag_first_from_question(client, fake_llm):
    born = (date.today() - timedelta(days=30)).isoformat()
    h, cid = await make_family(client, birthdate=born)
    # "baby has a fever 38.5" reports something: the parser reads it first (M14); here it finds nothing to log.
    fake_llm.replies += [{"events": []}, "Fever means 38C or above [3]."]
    r, events = await ask(client, h, cid, "baby has a fever 38.5, what should I do?")
    text = "".join(d["text"] for e, d in events if e == "token")
    assert events[0][0] == "token" and events[0][1]["text"].startswith("Urgent: High temperature in a baby under 3 months")
    assert "You wrote a temperature of 38.5 °C" in text and text.index("Urgent") < text.index("Fever means")
    cites = events[-2][1]["citations"]
    assert cites[0]["url"] == "https://www.nhs.uk/symptoms/fever-in-children/"


async def test_red_flag_from_logged_data_survives_model_down(client, fake_llm):
    born = (date.today() - timedelta(days=30)).isoformat()
    h, cid = await make_family(client, birthdate=born)
    from frecklebubby.db import utcnow

    await client.post(f"/api/v1/children/{cid}/entries", headers=h, json={
        "type": "temperature", "started_at": (utcnow() - timedelta(hours=1)).isoformat(), "data": {"celsius": 38.1}})
    fake_llm.down = True
    r, events = await ask(client, h, cid, "is she sleeping enough")
    assert r.status_code == 200
    assert events[0][1]["text"].startswith("Urgent: High temperature") and events[-1] == (
        "error", {"detail": "The assistant is not available now."})


async def test_model_down_503_and_trackers_work(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.down = True
    r, _ = await ask(client, h, cid, "how many wet nappies")
    assert r.status_code == 503 and r.json()["detail"] == "The assistant is not available now."
    assert (await client.get(f"/api/v1/children/{cid}/assistant/messages", headers=h)).json() == []
    assert (await client.get(f"/api/v1/children/{cid}/status", headers=h)).status_code == 200


async def test_no_sources_no_model_call(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": []})  # M14: words that are not a question go to the parser first
    r, events = await ask(client, h, cid, "xylophone quasar")
    text = "".join(d["text"] for e, d in events if e == "token")
    assert text.startswith("The sources I have do not cover this") and len(fake_llm.requests) == 1
    assert fake_llm.requests[0]["response_format"]  # only the parse call, no answer call
    r, events = await ask(client, h, cid, "what is a xylophone quasar?")  # a question: no parse call either
    assert len(fake_llm.requests) == 1


async def test_other_family_child_404(client, fake_llm):
    await make_family(client)
    hb, _ = await make_family(client, email="b@example.com")
    r, _ = await ask(client, hb, 1, "hello nappies")
    assert r.status_code == 404
    assert (await client.get("/api/v1/children/1/assistant/messages", headers=hb)).status_code == 404


async def test_llm_test(client, fake_llm):
    h, _ = await make_family(client)
    r = await client.post("/api/v1/family/settings/llm-test", headers=h)
    assert r.json() == {"ok": True, "detail": "The model server answered.", "model": "fake-model"}
    fake_llm.down = True
    r = await client.post("/api/v1/family/settings/llm-test", headers=h)
    assert r.json()["ok"] is False and r.json()["detail"].startswith("The assistant is not available now.")


async def test_sleep_plan(client, fake_llm):
    h, cid = await make_family(client)
    assert (await client.get(f"/api/v1/children/{cid}/sleep/plan", headers=h)).json() is None
    fake_llm.replies.append({
        "summary": "Two naps and a 19:00 bedtime.",
        "schedule": [{"time": "07:00", "kind": "wake", "label": "Wake up"},
                     {"time": "19:00", "kind": "bedtime", "label": "Bedtime", "note": "Same routine each night"}],
        "advice": [{"text": "Aim for 12 to 15 hours in 24 hours.", "cites": [1, 42]}],
    })
    status, plan = await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan")
    assert status == "done", plan
    assert plan["advice"] == [{"text": "Aim for 12 to 15 hours in 24 hours.", "cites": [1]}]
    assert [c["n"] for c in plan["citations"]] == [1] and plan["schedule"][1]["note"]
    assert fake_llm.requests[0]["response_format"]["json_schema"]["schema"]["required"] == [
        "summary", "schedule", "advice"]
    assert (await client.get(f"/api/v1/children/{cid}/sleep/plan", headers=h)).json()["id"] == plan["id"]
    fake_llm.down = True
    assert await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan") == ("failed", "The assistant is not available now.")
    assert (await client.get(f"/api/v1/children/{cid}/sleep/plan", headers=h)).json()["id"] == plan["id"]  # the last saved plan stays


async def test_sleep_plan_moves_marks_out_of_advice_text(client, fake_llm):
    # Gemma 4 wrote "... settle down. cites: [2]" into the text in the live e2e run.
    h, cid = await make_family(client)
    fake_llm.replies.append({
        "summary": "Plan.", "schedule": [{"time": "07:00", "kind": "wake", "label": "Wake up"}],
        "advice": [{"text": "Start a calm routine. cites: [1]", "cites": [1]},
                   {"text": "Dim the lights [1].", "cites": []},
                   {"text": "Keep it the same [1], [42]", "cites": []}],
    })
    _, plan = await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan")
    assert plan["advice"] == [{"text": "Start a calm routine.", "cites": [1]},
                              {"text": "Dim the lights.", "cites": [1]},
                              {"text": "Keep it the same", "cites": [1]}]


async def test_sleep_plan_tries_again_after_invalid_json(client, fake_llm):
    h, cid = await make_family(client)
    plan = {"summary": "Plan.", "schedule": [{"time": "07:00", "kind": "wake", "label": "Wake up"}],
            "advice": [{"text": "Keep a routine.", "cites": []}]}
    fake_llm.replies += ['{"summary": "cut o', plan]
    assert (await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan"))[1]["summary"] == "Plan."
    fake_llm.replies += ["not json", "still not json"]
    assert (await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan"))[0] == "failed"
