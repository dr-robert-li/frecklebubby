"""Cry helper: likely needs from the logs, analyze with a fake model, limits, no-model and no-ffmpeg paths,
family isolation, cry entries in reports and export, MCP tools, and one test with the real exported model."""

import io
import json
import os
import shutil
import subprocess
import wave
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastmcp import Client

from frecklebubby.mcp_server import create_mcp
from frecklebubby.models import Child, Entry, Timer
from frecklebubby.services import cry

from .conftest import ctx_for, make_family

# 18:00 in Brisbane (UTC+10).
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


@pytest.fixture
def needs(client, monkeypatch):
    """needs(age_days, entries=[(type, minutes_ago, data, minutes_long|None)], now=NOW) -> {need: item}."""
    monkeypatch.setattr(cry, "predict", lambda *a, **k: None)

    made = []

    async def make(age_days: int, entries=(), now=NOW):
        email = f"p{len(made)}@example.com"  # a new family on each call
        made.append(email)
        await make_family(client, email=email, birthdate=(now.date() - timedelta(days=age_days)).isoformat())
        s, ctx = ctx_for(email)
        child = s.query(Child).filter_by(family_id=ctx.fam.id).one()
        for type_, ago, data, length in entries:
            start = now - timedelta(minutes=ago)
            s.add(Entry(child_id=child.id, type=type_, started_at=start, data=data,
                        ended_at=start + timedelta(minutes=length) if length is not None else None))
        s.commit()
        out = {n["need"]: n for n in cry.likely_needs(s, ctx, child, now)}
        s.close()
        return out

    return make


def feeds_every(hours: float, last_ago_min: float, n: int = 6):
    return [("bottle", last_ago_min + i * hours * 60, {"amount_ml": 120}, None) for i in range(n)]


def test_support_phrases_are_in_the_cited_files():
    for name, phrase in cry.SUPPORT.values():
        assert phrase in cry.library(name)[1], (name, phrase)


@pytest.mark.parametrize("last_ago,score", [(90, 0.1), (180, 0.6), (270, 0.95), (400, 0.95), (135, 0.35)])
async def test_hunger_against_own_usual_gap(needs, last_ago, score):
    n = (await needs(60, feeds_every(3, last_ago)))["hunger"]
    assert n["score"] == score
    assert "usual time between feeds is 3 h 0 min" in n["why"]
    assert n["citations"][0]["url"].startswith("https://www.cdc.gov/") and n["citations"][0]["kind"] == "bundled"


async def test_hunger_first_when_overdue(needs):
    ranked = list(await needs(60, feeds_every(3, 280)))
    assert ranked[0] == "hunger"


async def test_hunger_without_enough_feeds_uses_cdc_range(needs):
    n = (await needs(60, [("bottle", 180, {"amount_ml": 90}, None)]))["hunger"]
    assert n["score"] == 0.8 and "every 2 to 4 hours" in n["why"]
    n = (await needs(60))["hunger"]
    assert n["score"] == 0.3 and "No feed is logged" in n["why"]


@pytest.mark.parametrize("ended_ago,score", [(20, 0.5), (45, 0.5), (50, 0.15)])
async def test_wind_after_a_feed(needs, ended_ago, score):
    n = (await needs(60, [("nursing", ended_ago + 15, {}, 15)]))["wind"]
    assert n["score"] == score


@pytest.mark.parametrize("start_in,end_in,score", [(-10, 20, 0.7), (20, 50, 0.45), (120, 150, 0.15), (-90, -60, 0.95)])
async def test_tired_against_sleep_window(needs, monkeypatch, start_in, end_in, score):
    window = {"start": NOW + timedelta(minutes=start_in), "end": NOW + timedelta(minutes=end_in), "kind": "nap"}
    monkeypatch.setattr(cry, "predict", lambda *a, **k: window)
    n = (await needs(60, [("sleep", 200, {}, 60)]))["tired"]
    assert n["score"] == score and "Awake 2 h 20 min" in n["why"] and "not a medical standard" in n["why"]


async def test_no_tired_item_while_asleep(needs):
    assert (await needs(60))["tired"]["score"] == 0.25  # no sleep logged
    s, ctx = ctx_for("p0@example.com")
    child = s.query(Child).filter_by(family_id=ctx.fam.id).one()
    s.add(Timer(child_id=child.id, type="sleep", started_at=NOW - timedelta(minutes=5), data={}))
    s.commit()
    assert "tired" not in {n["need"] for n in cry.likely_needs(s, ctx, child, NOW)}
    s.close()


@pytest.mark.parametrize("last_ago,score", [(90, 0.1), (180, 0.6), (360, 0.7)])
async def test_nappy_against_own_usual_gap(needs, last_ago, score):
    nappies = [("nappy", last_ago + i * 180, {"mode": "pee"}, None) for i in range(5)]
    n = (await needs(60, nappies))["nappy"]
    assert n["score"] == score and "nappy change" in n["why"]


@pytest.mark.parametrize("celsius,ago,present", [(38.2, 60, True), (37.9, 60, False), (35.8, 60, True),
                                                 (38.5, 25 * 60, False)])
async def test_temperature(needs, celsius, ago, present):
    out = await needs(200, [("temperature", ago, {"celsius": celsius}, None)])
    assert ("unwell" in out) == present
    if present:
        assert out["unwell"]["score"] == 0.9 and f"{celsius:g} °C" in out["unwell"]["why"]


@pytest.mark.parametrize("ago,present", [(120, True), (8 * 60 + 5, False)])
async def test_recent_medicine(needs, ago, present):
    out = await needs(200, [("medicine", ago, {"name": "Paracetamol"}, None)])
    assert ("unwell" in out) == present


async def test_allergic_reaction(needs):
    out = await needs(300, [("solids", 120, {"foods": [{"name": "Egg"}], "reaction": "ALLERGIC"}, None)])
    assert out["allergic"]["score"] == 1.0 and "Egg" in out["allergic"]["why"]
    assert list(out)[0] == "allergic"


@pytest.mark.parametrize("age_days,hour,present", [(50, 18, True), (50, 9, False), (13, 18, False), (14, 18, True),
                                                   (120, 18, True), (121, 18, False)])
async def test_evening_crying_by_age_and_time(needs, age_days, hour, present):
    now = datetime(2026, 11, 20, 0, 0, tzinfo=UTC) + timedelta(hours=hour - 10)
    out = await needs(age_days, now=now)
    assert ("evening_crying" in out) == present
    if present:
        assert out["evening_crying"]["citations"][0]["title"] == "Soothing a crying baby"


@pytest.mark.parametrize("days,minutes,age,present", [(3, 190, 60, True), (2, 190, 60, False), (3, 180, 60, False),
                                                      (3, 190, 160, False)])
async def test_colic_pattern_from_logged_crying(needs, days, minutes, age, present):
    cries = [("cry", 24 * 60 * d + 300, {}, minutes) for d in range(days)]
    assert ("colic" in await needs(age, cries)) == present


# --- API ----------------------------------------------------------------------------------------------------------

CARD = {
    "detector": {"labels": ["cry", "snore"], "threshold": 0.5, "median_frames": 1, "frame_seconds": 0.32,
                 "is_cry_min_seconds": 1.0},
    "reason": {"labels": ["belly_pain", "burping", "discomfort", "hungry", "scared", "tired"],
               "metrics": {"accuracy": 0.45, "macro_f1": 0.2, "balanced_accuracy": 0.2, "macro_ovr_auc": 0.55},
               "baselines": {"always_hungry": {"accuracy": 0.78, "macro_f1": 0.15},
                             "prior_sampler": {"accuracy": 0.6, "macro_f1": 0.17}}},
}
SOUND = {"is_cry": True, "cry_seconds": 8.3, "snore_seconds": 0.0,
         "reasons": [{"label": "tired", "probability": 0.9}, {"label": "hungry", "probability": 0.1}]}


def wav_bytes(seconds: float, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(seconds * sr)) * 0.05) * 3000).astype("<i2").tobytes())
    return buf.getvalue()


def post_audio(client, cid, h, data: bytes, ctype="audio/wav"):
    return client.post(f"/api/v1/children/{cid}/cry/analyze", headers=h, files={"audio": ("rec", data, ctype)})


@pytest.fixture
def fake_model(monkeypatch):
    calls = []
    monkeypatch.setattr(cry, "load_models", lambda: {"card": CARD})
    monkeypatch.setattr(cry, "infer", lambda models, wav: calls.append(len(wav)) or dict(SOUND))
    return calls


async def test_help_without_model(client):
    h, cid = await make_family(client)
    r = await client.get(f"/api/v1/children/{cid}/cry/help", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sound"] == {"installed": False, "is_cry": False, "cry_seconds": 0.0, "snore_seconds": 0.0,
                             "reasons": [], "experimental": True, "reliability": cry.NOT_INSTALLED}
    assert body["likely_needs"] and all(n["citations"] for n in body["likely_needs"])
    assert {s["kind"] for s in body["suggestions"]} == {"try", "help"}
    assert all(s["citations"] for s in body["suggestions"])
    assert [c["need"] for c in body["combined"]] == [n["need"] for n in body["likely_needs"][:5]]


async def test_analyze_without_model_still_checks_the_upload(client):
    h, cid = await make_family(client)
    r = await post_audio(client, cid, h, wav_bytes(3))
    assert r.status_code == 200 and r.json()["sound"]["installed"] is False
    assert (await post_audio(client, cid, h, b"hello", "text/plain")).status_code == 422


async def test_analyze_with_fake_model(client, fake_model):
    h, cid = await make_family(client)
    r = await post_audio(client, cid, h, wav_bytes(5), "audio/wav")
    assert r.status_code == 200, r.text
    sound = r.json()["sound"]
    assert sound["installed"] and sound["is_cry"] and sound["experimental"]
    assert sound["reasons"][0] == {"label": "tired", "probability": 0.9}
    assert "right about 4 times in 10" in sound["reliability"] and "about 8 times in 10" in sound["reliability"]
    assert "only a hint" in sound["reliability"]
    assert fake_model == [80000]  # decoded with ffmpeg to 16 kHz mono


async def test_weak_sound_model_does_not_change_the_order(client, fake_model):
    h, cid = await make_family(client)
    base = (await client.get(f"/api/v1/children/{cid}/cry/help", headers=h)).json()
    got = (await post_audio(client, cid, h, wav_bytes(3))).json()
    assert [c["need"] for c in got["combined"]] == [c["need"] for c in base["combined"]]


def test_strong_sound_model_moves_its_need_up():
    needs = [{"need": "hunger", "score": 0.6, "why": "a"}, {"need": "tired", "score": 0.4, "why": "b"}]
    strong = json.loads(json.dumps(CARD))
    strong["reason"]["metrics"].update(accuracy=0.95, macro_f1=0.6)
    sound = {"reasons": [{"label": "tired", "probability": 0.9}]}
    assert [c["need"] for c in cry.combine(needs, sound, CARD)] == ["hunger", "tired"]
    combined = cry.combine(needs, sound, strong)
    assert [c["need"] for c in combined] == ["tired", "hunger"]
    assert "sound guess (experimental)" in combined[0]["why"]


@pytest.mark.parametrize("data,ctype,detail", [
    (b"x" * (10 * 1024 * 1024 + 1), "audio/webm", "too large"),
    (b"", "audio/webm", "empty"),
    (b"abc", "application/pdf", "WebM"),
    (b"not audio at all", "audio/webm", "could not read"),
])
async def test_upload_limits(client, fake_model, data, ctype, detail):
    h, cid = await make_family(client)
    r = await post_audio(client, cid, h, data, ctype)
    assert r.status_code == 422 and detail in r.json()["detail"]
    assert fake_model == []


async def test_length_limits(client, fake_model):
    h, cid = await make_family(client)
    assert "longer than 60" in (await post_audio(client, cid, h, wav_bytes(62, 8000))).json()["detail"]
    assert "too short" in (await post_audio(client, cid, h, wav_bytes(0.5))).json()["detail"]
    assert (await post_audio(client, cid, h, wav_bytes(60, 8000))).status_code == 200


async def test_ffmpeg_missing_gives_501(client, fake_model, monkeypatch):
    h, cid = await make_family(client)
    monkeypatch.setattr(cry.shutil, "which", lambda name: None)
    r = await post_audio(client, cid, h, wav_bytes(3))
    assert r.status_code == 501 and "ffmpeg" in r.json()["detail"]


async def test_upload_is_not_left_on_disk(client, fake_model, monkeypatch, tmp_path):
    h, cid = await make_family(client)
    monkeypatch.setattr(cry.tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    assert (await post_audio(client, cid, h, wav_bytes(2))).status_code == 200
    assert list((tmp_path / "tmp").iterdir()) == []


async def test_family_isolation(client, fake_model):
    _, cid = await make_family(client)
    hb, _ = await make_family(client, email="b@example.com", child="Bo")
    assert (await client.get(f"/api/v1/children/{cid}/cry/help", headers=hb)).status_code == 404
    assert (await post_audio(client, cid, hb, wav_bytes(2))).status_code == 404
    assert fake_model == []


async def test_urgent_cards_in_help(client):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=40)).isoformat())
    await client.post(f"/api/v1/children/{cid}/entries", headers=h,
                      json={"type": "temperature", "started_at": datetime.now(UTC).isoformat(), "data": {"celsius": 38.4}})
    body = (await client.get(f"/api/v1/children/{cid}/cry/help", headers=h)).json()
    assert body["urgent"][0]["kind"] == "fever_under_3m" and body["urgent"][0]["severity"] == "urgent"
    assert body["combined"][0]["need"] == "unwell"


# --- cry entries --------------------------------------------------------------------------------------------------


async def test_cry_entry_crud_report_export(client):
    h, cid = await make_family(client)
    url = f"/api/v1/children/{cid}/entries"
    body = {"type": "cry", "started_at": "2026-11-01T18:00:00+10:00", "ended_at": "2026-11-01T18:20:00+10:00",
            "data": {"sound_reason": "hungry", "sound_confidence": 0.41, "likely_needs": ["hunger", "tired"],
                     "soothed_by": "feed"}}
    r = await client.post(url, headers=h, json=body)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["data"]["likely_needs"] == ["hunger", "tired"]
    assert (await client.post(url, headers=h, json={"type": "cry", "started_at": "2026-11-01T19:00:00+10:00"})
            ).status_code == 201  # no model, no end: a plain manual log
    bad = {**body, "data": {"sound_confidence": 1.5}}
    assert (await client.post(url, headers=h, json=bad)).status_code == 422
    bad = {**body, "data": {"volume": "loud"}}
    assert (await client.post(url, headers=h, json=bad)).status_code == 422
    r = await client.patch(f"/api/v1/entries/{e['id']}", headers=h, json={"data": {"soothed_by": "rocking"}})
    assert r.json()["data"] == {"soothed_by": "rocking"}
    rep = (await client.get(f"/api/v1/children/{cid}/reports/daily?from=2026-11-01&to=2026-11-01", headers=h)).json()
    assert rep["days"][0]["crying"] == {"count": 2, "seconds": 1200}
    csv = (await client.get(f"/api/v1/children/{cid}/export.csv", headers=h)).text
    assert ",cry,2026-11-01T18:00:00+10:00,2026-11-01T18:20:00+10:00,20.0," in csv
    assert (await client.delete(f"/api/v1/entries/{e['id']}", headers=h)).status_code == 204


async def test_mcp_cry_tools(client):
    await make_family(client)
    async with Client(create_mcp(fixed_email="a@example.com")) as mcp:
        e = (await mcp.call_tool("log_cry", {"start_time": "2026-11-01T18:00", "end_time": "2026-11-01T18:30",
                                             "soothed_by": "walk"})).structured_content
        assert e["type"] == "cry" and e["data"] == {"soothed_by": "walk"} and e["source"] == "mcp"
        out = (await mcp.call_tool("get_cry_help", {})).structured_content
        assert "sound" not in out and out["likely_needs"] and out["suggestions"]


# --- real model (only on a machine with the exported files) -------------------------------------------------------

MODEL_DIR = Path(os.environ.get("CRY_TEST_MODEL_DIR",
                                Path(__file__).parents[1] / "src/frecklebubby/data/models/cry"))
CRY_CLIP = os.environ.get("CRY_TEST_CLIP", "")


@pytest.mark.cry_model
@pytest.mark.skipif(not (MODEL_DIR / "model_card.json").is_file(), reason=f"no exported cry model in {MODEL_DIR}")
def test_real_model_on_cry_silence_and_speech(env, tmp_path):
    env.setenv("CRY_MODEL_DIR", str(MODEL_DIR))
    from frecklebubby.config import get_settings

    get_settings.cache_clear()
    clip = Path(CRY_CLIP) if CRY_CLIP else next(
        iter(sorted((Path.home() / "Desktop/projects/DeepInfant/Data/v2/hungry").glob("*.wav"))), None)
    if not clip or not clip.is_file():
        pytest.skip("no cry clip (set CRY_TEST_CLIP)")
    models = cry.load_models()
    assert models is not None
    got = cry.infer(models, cry.decode(clip.read_bytes()))
    assert got["is_cry"] and got["cry_seconds"] >= 1 and got["reasons"]
    assert abs(sum(r["probability"] for r in got["reasons"]) - 1) < 0.01
    assert not cry.infer(models, np.zeros(16000 * 5, dtype=np.float32))["is_cry"]
    if shutil.which("espeak-ng"):
        speech = tmp_path / "speech.wav"
        subprocess.run(["espeak-ng", "-w", str(speech), "Hello. The weather is nice today. Shall we go for a walk "
                        "in the park after lunch?"], check=True)
        assert not cry.infer(models, cry.decode(speech.read_bytes()))["is_cry"]
