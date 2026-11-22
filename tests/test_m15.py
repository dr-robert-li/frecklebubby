"""M15: rate limits, the model queue, heartbeats and the plan/report jobs."""

import asyncio

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from frecklebubby import ratelimit
from frecklebubby.ai import jobs, llm
from frecklebubby.api import ai as ai_api
from frecklebubby.config import get_settings
from frecklebubby.mcp_server import create_mcp

from .conftest import make_family, run_job
from .fake_llm import fake_llm_fixture  # noqa: F401
from .test_auth import clerk  # noqa: F401

API = "/api/v1"
QUESTION = "how many wet nappies is normal"


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit, "clock", lambda: now[0])
    return now


def limits(env, **values):
    for k, v in values.items():
        env.setenv(k.upper(), str(v))
    get_settings.cache_clear()


async def test_ai_limit_per_user_with_retry_after(client, env, fake_llm, clock):
    limits(env, limit_ai="2/60")
    a, _ = await make_family(client, "a@example.com")
    b, _ = await make_family(client, "b@example.com")
    url = f"{API}/family/settings/llm-test"
    assert [(await client.post(url, headers=a)).status_code for _ in range(2)] == [200, 200]
    r = await client.post(url, headers=a)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert r.json()["detail"] == "Too many requests. Try again in 1 minute."
    assert (await client.post(url, headers=b)).status_code == 200  # per user
    clock[0] += 30
    assert (await client.post(url, headers=a)).headers["retry-after"] == "30"
    clock[0] += 31
    assert (await client.post(url, headers=a)).status_code == 200


async def test_upload_limit(client, env, clock):
    limits(env, limit_uploads="1/3600")
    h, cid = await make_family(client)
    files = {"file": ("notes.md", b"# Notes\n\nSome text about sleep.", "text/markdown")}
    assert (await client.post(f"{API}/knowledge/uploads", headers=h, files=files)).status_code == 201
    r = await client.post(f"{API}/knowledge/uploads", headers=h, files=files)
    assert r.status_code == 429 and r.headers["retry-after"] == "3600"
    assert r.json()["detail"] == "Too many requests. Try again in 60 minutes."
    # the import start and the cry recording count with the uploads
    body = {"email": "x@example.com", "password": "x", "timezone": "UTC"}
    assert (await client.post(f"{API}/import/huckleberry", headers=h, json=body)).status_code == 429
    audio = {"audio": ("a.webm", b"x", "audio/webm")}
    assert (await client.post(f"{API}/children/{cid}/cry/analyze", headers=h, files=audio)).status_code == 429


async def test_wrong_token_per_address(client, env, clock):
    limits(env, limit_bad_token="2/600")
    bad = {"Authorization": "Bearer fb_pat_wrong"}
    assert [(await client.get(f"{API}/me", headers=bad)).status_code for _ in range(2)] == [401, 401]
    r = await client.get(f"{API}/me", headers=bad)
    assert r.status_code == 429 and int(r.headers["retry-after"]) == 600
    # CF-Connecting-IP is not trusted unless the setting says so
    assert (await client.get(f"{API}/me", headers=bad | {"CF-Connecting-IP": "203.0.113.9"})).status_code == 429
    limits(env, limit_bad_token="2/600", behind_cloudflare="true")
    assert (await client.get(f"{API}/me", headers=bad | {"CF-Connecting-IP": "203.0.113.9"})).status_code == 401
    # a request without a token (the dev sign-in) is not refused by this limit
    assert (await client.get(f"{API}/me", headers={"X-Dev-User": "a@example.com"})).status_code == 200


async def test_mcp_plain_words_limit(client, env, fake_llm, clock):
    limits(env, limit_ai="1/60")
    await make_family(client)
    fake_llm.replies.append({"events": []})
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        await mcp.call_tool("log_in_plain_words", {"text": "a wet nappy"})
        with pytest.raises(ToolError, match="Too many requests"):
            await mcp.call_tool("log_in_plain_words", {"text": "a wet nappy"})


async def test_queue_order_and_busy(env):
    limits(env, llm_queue_max=2)
    q = llm.QUEUE
    order, gate = [], asyncio.Event()

    async def user(n):
        async with q.slot():
            order.append(n)
            await gate.wait()

    first = asyncio.create_task(user(0))
    await asyncio.sleep(0)
    waiting = [asyncio.create_task(user(n)) for n in (1, 2)]
    await asyncio.sleep(0)
    assert q.busy and len(q.waiting) == 2 and order == [0]
    with pytest.raises(llm.Busy) as err:
        q.check()
    assert str(err.value) == "The assistant is busy. Try again in a minute." and err.value.status == 429
    gate.set()
    await asyncio.gather(first, *waiting)
    assert order == [0, 1, 2] and not q.busy

    # a waiter that gives up leaves the line; the others keep their place
    gate.clear()
    first = asyncio.create_task(user(3))
    await asyncio.sleep(0)
    quitter, last = asyncio.create_task(user(4)), asyncio.create_task(user(5))
    await asyncio.sleep(0)
    quitter.cancel()
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(first, last)
    assert order[3:] == [3, 5] and not q.busy and not q.waiting


async def hold_slot():
    """Hold the model slot until the returned event is set."""
    release, held = asyncio.Event(), asyncio.Event()

    async def holder():
        async with llm.QUEUE.slot():
            held.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await held.wait()
    return release, task


async def test_chat_busy_answer(client, env, fake_llm):
    limits(env, llm_queue_max=0)
    h, cid = await make_family(client)
    release, task = await hold_slot()
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h, json={"message": QUESTION})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert r.json()["detail"] == "The assistant is busy. Try again in a minute."
    r = await client.post(f"{API}/children/{cid}/sleep/plan", headers=h)
    assert r.status_code == 429
    release.set()
    await task


async def test_request_without_stream_stops_waiting(client, env, fake_llm):
    limits(env, llm_queue_wait=0.05)
    h, cid = await make_family(client)
    release, task = await hold_slot()
    r = await client.post(f"{API}/children/{cid}/nl/parse", headers=h, json={"text": "a wet nappy"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert r.json()["detail"] == "The assistant is busy. Try again in a minute."
    assert (await client.post(f"{API}/family/settings/llm-test", headers=h)).status_code == 429
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        with pytest.raises(ToolError, match="busy"):
            await mcp.call_tool("log_in_plain_words", {"text": "a wet nappy"})
    assert not llm.QUEUE.waiting  # those that gave up left the line
    release.set()
    await task
    assert not llm.QUEUE.busy and not fake_llm.requests


async def test_chat_waits_with_heartbeat(client, env, fake_llm, monkeypatch):
    limits(env, llm_queue_wait=0.01)  # the chat stream is not limited: it sends a heartbeat
    monkeypatch.setattr(ai_api, "HEARTBEAT", 0.02)
    h, cid = await make_family(client)
    fake_llm.replies.append("About 6 a day [1].")
    release, task = await hold_slot()
    chat = asyncio.create_task(client.post(f"{API}/children/{cid}/assistant/chat", headers=h,
                                           json={"message": QUESTION}))
    while not llm.QUEUE.waiting:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)  # waits for the model now
    assert not chat.done()
    release.set()
    r = await chat
    await task
    blocks = r.text.strip().split("\n\n")
    assert r.status_code == 200 and blocks[0].startswith("event: waiting")
    assert blocks[1:3] == [": ping", ": ping"]  # sent while it waited
    assert '"text": "[1]."' in r.text and blocks[-1].startswith("event: done")


async def test_heartbeat_wrapper():
    async def slow():
        yield "a"
        await asyncio.sleep(0.05)
        yield "b"

    ai_api.HEARTBEAT, old = 0.01, ai_api.HEARTBEAT
    try:
        out = [e async for e in ai_api.heartbeat(slow())]
    finally:
        ai_api.HEARTBEAT = old
    assert out[0] == "a" and out[-1] == "b" and ": ping\n\n" in out


async def test_plan_job_polls_and_keeps_one_running(client, env, fake_llm):
    limits(env, llm_queue_wait=0.01)  # a polled job is not limited
    h, cid = await make_family(client)
    url = f"{API}/children/{cid}/sleep/plan"
    assert (await client.get(f"{url}/job", headers=h)).json() == {"status": "none", "error": None}
    release, task = await hold_slot()  # the job waits for the model
    fake_llm.replies.append({"summary": "Plan.", "schedule": [], "advice": []})
    r = await client.post(url, headers=h)
    assert r.status_code == 202 and r.json() == {"status": "running", "error": None}
    assert (await client.post(url, headers=h)).json()["status"] == "running"  # the same job
    await asyncio.sleep(0.05)
    assert (await client.get(f"{url}/job", headers=h)).json()["status"] == "running"
    assert (await client.get(url, headers=h)).json() is None
    release.set()
    await task
    await jobs.wait("sleep_plan", cid)
    assert (await client.get(f"{url}/job", headers=h)).json() == {"status": "done", "error": None}
    assert (await client.get(url, headers=h)).json()["summary"] == "Plan."
    assert len(fake_llm.requests) == 1


async def test_report_job_api(client, fake_llm):
    h, cid = await make_family(client)
    status, rep = await run_job(client, h, f"{API}/children/{cid}/support-report")
    assert status == "done" and len(rep["blocks"]) == 8


async def test_wrong_session_token_per_address(env, clerk, pushes, clock):  # noqa: F811
    from frecklebubby.main import create_app

    from .test_auth import _token

    limits(env, limit_bad_token="1/600")
    key, _ = clerk
    app = create_app(scheduler=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        def me(token):
            return c.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})

        assert (await me(_token(key, iss="https://evil.example"))).status_code == 401
        assert (await me(_token(key))).status_code == 429  # this address is stopped for a time
        clock[0] += 601
        assert (await me(_token(key))).status_code == 200


async def test_queue_parallel(env):
    limits(env, llm_parallel=2, llm_queue_max=1)
    q = llm.QUEUE
    order, gate = [], asyncio.Event()

    async def user(n):
        async with q.slot():
            order.append(n)
            await gate.wait()

    tasks = [asyncio.create_task(user(n)) for n in range(3)]
    await asyncio.sleep(0.01)
    assert order == [0, 1] and q.busy and len(q.waiting) == 1  # two run, the third waits
    with pytest.raises(llm.Busy):
        q.check()
    gate.set()
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2] and q.active == 0 and not q.busy
