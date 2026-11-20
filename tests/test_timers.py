from datetime import timedelta

import pytest

from frecklebubby.schemas import TimerBody
from frecklebubby.services import Conflict, Invalid, NotFound
from frecklebubby.services.timers import act, elapsed

from .conftest import ctx_for, make_family, utc

T0 = utc(2026, 11, 1, 0, 0)


def at(minutes: float):
    return T0 + timedelta(minutes=minutes)


async def test_nursing_side_seconds(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    t, _ = act(s, ctx, cid, "nursing", "start", TimerBody(side="right"), now=at(0))
    assert t.data["side"] == "right"
    act(s, ctx, cid, "nursing", "switch", TimerBody(), now=at(5))          # right 300
    act(s, ctx, cid, "nursing", "pause", TimerBody(), now=at(8))           # left 180
    with pytest.raises(Conflict):
        act(s, ctx, cid, "nursing", "pause", TimerBody(), now=at(9))
    t, _ = act(s, ctx, cid, "nursing", "resume", TimerBody(side="right"), now=at(10))
    assert t.paused_seconds == 120
    assert elapsed(t, at(12)) == 600
    _, e = act(s, ctx, cid, "nursing", "complete", TimerBody(notes="good"), now=at(12))  # right +120
    assert e.data == {"left_seconds": 180, "right_seconds": 420, "last_side": "right"}
    assert (e.started_at, e.ended_at, e.notes, e.source) == (at(0), at(12), "good", "app")
    with pytest.raises(NotFound):
        act(s, ctx, cid, "nursing", "pause", TimerBody(), now=at(13))
    s.close()


async def test_restart_moves_start(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "nursing", "start", TimerBody(), now=at(10))
    t, _ = act(s, ctx, cid, "nursing", "start", TimerBody(at=at(4)), now=at(12))
    assert t.started_at == at(4)
    _, e = act(s, ctx, cid, "nursing", "complete", TimerBody(), now=at(14))
    assert e.data["left_seconds"] == 600  # moved time belongs to the running side
    t, _ = act(s, ctx, cid, "sleep", "start", TimerBody(), now=at(20))
    t, _ = act(s, ctx, cid, "sleep", "start", TimerBody(), now=at(25))
    assert t.started_at == at(25)
    with pytest.raises(Invalid, match="5 minutes in the future"):
        act(s, ctx, cid, "sleep", "start", TimerBody(at=at(40)), now=at(26))
    s.close()


async def test_sleep_activity_pump(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "sleep", "start", TimerBody(at=at(0)), now=at(1))
    with pytest.raises(Invalid, match="use them only with complete"):
        act(s, ctx, cid, "sleep", "pause", TimerBody(data={}), now=at(2))
    with pytest.raises(Invalid, match="only with a nursing timer"):
        act(s, ctx, cid, "sleep", "switch", TimerBody(), now=at(2))
    _, e = act(s, ctx, cid, "sleep", "complete",
               TimerBody(at=at(90), data={"locations": ["car"]}), now=at(95))
    assert (e.type, e.ended_at, e.data["locations"]) == ("sleep", at(90), ["car"])

    with pytest.raises(Invalid, match="kind: required"):
        act(s, ctx, cid, "activity", "start", TimerBody(), now=at(100))
    act(s, ctx, cid, "activity", "start", TimerBody(kind="storyTime"), now=at(100))
    with pytest.raises(Invalid, match="only with a nursing timer"):
        act(s, ctx, cid, "activity", "switch", TimerBody(), now=at(105))
    _, e = act(s, ctx, cid, "activity", "complete", TimerBody(), now=at(110))  # the one activity timer: no kind
    assert e.data == {"kind": "storyTime"}

    act(s, ctx, cid, "pump", "start", TimerBody(), now=at(120))
    with pytest.raises(Invalid, match="data.total_ml"):
        act(s, ctx, cid, "pump", "complete", TimerBody(data={"total_ml": 5000}), now=at(130))
    _, e = act(s, ctx, cid, "pump", "complete", TimerBody(data={"left_ml": 40, "right_ml": 50}), now=at(130))
    assert e.data["total_ml"] == 90
    act(s, ctx, cid, "pump", "start", TimerBody(), now=at(140))
    t, e = act(s, ctx, cid, "pump", "cancel", TimerBody(), now=at(141))
    assert (t, e) == (None, None)
    s.close()


async def test_timer_api(client):
    h, cid = await make_family(client)
    base = f"/api/v1/children/{cid}/timers"
    r = await client.post(f"{base}/nursing/start", headers=h, json={"side": "left"})
    assert r.status_code == 200
    assert r.json()["timer"]["data"]["side"] == "left" and r.json()["entry"] is None
    r = await client.post(f"{base}/nursing/switch", headers=h)
    assert r.json()["timer"]["data"]["side"] == "right"
    assert (await client.post(f"{base}/nursing/explode", headers=h)).status_code == 422
    assert (await client.post(f"{base}/bottle/start", headers=h)).status_code == 422
    assert (await client.post(f"{base}/sleep/pause", headers=h)).status_code == 404
    r = await client.post(f"{base}/nursing/complete", headers=h)
    assert r.json()["timer"] is None and r.json()["entry"]["type"] == "nursing"
    assert (await client.get(base, headers=h)).json() == []


async def test_parallel_activity_timers(client):
    _, cid = await make_family(client)
    s, ctx = ctx_for("a@example.com")
    act(s, ctx, cid, "activity", "start", TimerBody(kind="indoorPlay"), now=at(0))
    act(s, ctx, cid, "activity", "start", TimerBody(kind="tummyTime"), now=at(5))
    act(s, ctx, cid, "sleep", "start", TimerBody(), now=at(5))  # other types still one per child
    t, _ = act(s, ctx, cid, "activity", "start", TimerBody(kind="tummyTime", at=at(4)), now=at(6))
    assert t.started_at == at(4)  # a start on a running kind moves its start
    with pytest.raises(Invalid, match=r"2 activity timers run \(indoorPlay, tummyTime\)"):
        act(s, ctx, cid, "activity", "complete", TimerBody(), now=at(10))
    with pytest.raises(NotFound, match="No bath timer"):
        act(s, ctx, cid, "activity", "pause", TimerBody(kind="bath"), now=at(10))
    _, tummy = act(s, ctx, cid, "activity", "complete", TimerBody(kind="tummyTime"), now=at(10))
    assert (tummy.data, tummy.started_at, tummy.ended_at) == ({"kind": "tummyTime"}, at(4), at(10))
    _, play = act(s, ctx, cid, "activity", "complete", TimerBody(), now=at(20))  # one runs now: no kind
    assert (play.data, play.started_at, play.ended_at) == ({"kind": "indoorPlay"}, at(0), at(20))
    with pytest.raises(Invalid, match="only with an activity timer"):
        act(s, ctx, cid, "sleep", "complete", TimerBody(kind="bath"), now=at(21))
    s.close()
