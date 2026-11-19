"""M7 sleep model with the small made-up norms in fixtures/sleep_norms.json (bands 0-3, 3-6, 6-12, 12-24 months)."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from frecklebubby.config import get_settings
from frecklebubby.models import Entry
from frecklebubby.services.children import get_child
from frecklebubby.services.insights import insights
from frecklebubby.services.sleep import norms, predict

from .conftest import FIXTURES, ctx_for, make_family

BNE = ZoneInfo("Australia/Brisbane")
API = "/api/v1"
NORMS = FIXTURES.parent / "sleep_norms.json"


def local(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=BNE)


@pytest.fixture
def with_norms(env):
    env.setenv("SLEEP_NORMS_PATH", str(NORMS))
    get_settings.cache_clear()


def three_naps(s, cid, days):
    """Night 19:00-06:00, naps 08:00-09:00, 11:30-12:30, 15:00-15:45 (wake windows 120, 150, 150, bedtime 195)."""
    for day in days:
        for a, b in ((local(day - 1, 19), local(day, 6)), (local(day, 8), local(day, 9)),
                     (local(day, 11, 30), local(day, 12, 30)), (local(day, 15), local(day, 15, 45))):
            s.add(Entry(child_id=cid, type="sleep", started_at=a, ended_at=b, data={}))
    s.commit()


async def test_blend_nap_and_bedtime(client, with_norms):
    _, cid = await make_family(client, birthdate="2026-06-01")  # about 5.5 months: band 91-182 days
    s, ctx = ctx_for("a@example.com")
    child = get_child(s, ctx, cid)
    three_naps(s, cid, range(8, 16))

    # 06:30, after the night: nap 1. The own windows (120) equal the norm (120), so 06:00 + 120 min.
    p = predict(s, child, BNE, now=local(15, 6, 30))
    assert (p["kind"], p["nap_index"], p["method"], p["basis"], p["samples"]) == ("nap", 1, "personal_blend",
                                                                                   "personal", 7)
    assert p["start"] == local(15, 7, 45) and p["end"] == local(15, 8, 15)
    assert p["earliest"] < p["start"] < p["end"] < p["latest"]
    assert p["confidence"] == "high" and p["history_days"] == 7 and p["duration_minutes"] == 60
    assert "last 7 days" in p["note"]

    # 17:00 wake after a catnap (4 naps, threshold 16:00): bedtime. Own bedtime window 195 vs norm 150, shrunk:
    # 17:00 + 184 min = 20:04, then pulled towards the usual 19:00 (weight 0.5 * 7/8): about 19:36.
    s.add(Entry(child_id=cid, type="sleep", started_at=local(15, 16, 30), ended_at=local(15, 17), data={}))
    s.commit()
    p = predict(s, child, BNE, now=local(15, 17, 5))
    assert p["kind"] == "bedtime" and p["nap_index"] is None
    mid = p["start"] + timedelta(minutes=15)
    assert local(15, 19, 30) <= mid <= local(15, 19, 40)
    s.close()


async def test_age_norm_without_history_and_night_waking(client, with_norms):
    _, cid = await make_family(client, birthdate="2026-06-01")
    s, ctx = ctx_for("a@example.com")
    child = get_child(s, ctx, cid)
    s.add(Entry(child_id=cid, type="sleep", started_at=local(14, 19), ended_at=local(15, 6), data={}))
    s.commit()
    p = predict(s, child, BNE, now=local(15, 6, 10))
    assert (p["method"], p["basis"], p["samples"], p["history_days"]) == ("age_norm", "age", 0, 0)
    assert p["start"] + timedelta(minutes=15) == local(15, 8)  # norm 120 min
    assert p["note"].startswith("Based on typical patterns")
    # Woke at 23:50 after bedtime: the next window is also in the night, so no prediction.
    s.add(Entry(child_id=cid, type="sleep", started_at=local(15, 19), ended_at=local(15, 23, 50), data={}))
    s.commit()
    assert predict(s, child, BNE, now=local(16, 0, 30)) is None
    s.close()


async def test_fallback_without_or_with_bad_norms(client, env, tmp_path):
    _, cid = await make_family(client, birthdate="2026-06-01")
    s, ctx = ctx_for("a@example.com")
    child = get_child(s, ctx, cid)
    three_naps(s, cid, range(12, 16))
    assert norms() is None
    assert predict(s, child, BNE, now=local(15, 16))["method"] == "wake_window_table"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bands": []}))
    env.setenv("SLEEP_NORMS_PATH", str(bad))
    get_settings.cache_clear()
    assert norms() is None
    p = predict(s, child, BNE, now=local(15, 16))
    assert p["method"] == "wake_window_table" and "earliest" not in p
    s.close()


async def test_endpoint_shape(client, with_norms):
    h, cid = await make_family(client, birthdate="2026-06-01")
    s, _ = ctx_for("a@example.com")
    three_naps(s, cid, range(8, 16))
    s.close()
    r = await client.get(f"{API}/children/{cid}/sleep/prediction", headers=h)
    # The newest sleep ended days ago, so null; with default=true the old age default comes back.
    assert r.status_code == 200
    old = {"start", "end", "kind", "basis", "wake_window_minutes", "samples", "age_range_minutes", "note"}
    r = await client.get(f"{API}/children/{cid}/sleep/prediction?default=true", headers=h)
    assert old <= set(r.json())
    s, ctx = ctx_for("a@example.com")
    from frecklebubby.schemas import Prediction

    p = Prediction.model_validate(predict(s, get_child(s, ctx, cid), BNE, now=local(15, 6, 30))).model_dump(mode="json")
    assert old <= set(p) and p["kind"] in ("nap", "bedtime") and p["earliest"] and p["latest"]
    s.close()


async def test_stage_and_outlook_cards(client, with_norms):
    _, cid = await make_family(client, birthdate="2026-06-01")  # 167 days on 15 Nov: 3 to 2 starts at 190 days
    s, ctx = ctx_for("a@example.com")
    three_naps(s, cid, range(8, 16))
    cards = {c["kind"]: c for c in insights(s, ctx, cid, now=local(15, 20))}
    stage = cards["sleep_stage"]
    assert stage["title"] == "Mostly 3 naps a day" and "50% of days had 3 naps" in stage["body"]
    assert stage["citations"][0]["kind"] == "link" and stage["citations"][0]["url"] == "https://example.com/norms"
    out = cards["sleep_outlook"]
    assert out["title"] == "Nap change ahead: 3 naps to 2 naps"
    assert "between about 6 and 8.5 months" in out["body"] and "should" not in out["body"].lower()
    total = cards["sleep_total"]
    assert "research dataset of app users" in total["body"]
    assert [c["publisher"] for c in total["citations"]][-1] == "Test"
    s.close()
