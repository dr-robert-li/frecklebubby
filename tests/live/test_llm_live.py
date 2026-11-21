"""Live tests against a real OpenAI-compatible model server. Run:
LLM_LIVE_URL=http://127.0.0.1:8081/v1 uv run pytest tests/live -m llm -s
LIVE_REPORT=path.json writes the details (notes, outputs, timings)."""

import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from frecklebubby.ai import nl_log

from ..conftest import make_family, run_job
from ..fake_llm import sse_events

URL = os.environ.get("LLM_LIVE_URL")
pytestmark = [pytest.mark.llm, pytest.mark.skipif(not URL, reason="set LLM_LIVE_URL to run live model tests")]

BNE = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 11, 20, 14, 35, tzinfo=BNE)  # Friday
REPORT: dict = {"model_url": URL, "nl": [], "assistant": [], "sleep_plan": None}

# (note, needs a running timer: True = sleep, a kind = that activity, expected proposals)
# An expected proposal: (kind, start "D14:05"/"Y19:15"/None = not checked, end or None, data subset).
# kind is an entry type or "timer:<type>:<action>". Text values match when they contain the expected text.
CASES = [
    ("she had 150ml of formula about half an hour ago", False,
     [("bottle", "D14:05", None, {"amount_ml": 150, "milk_type": "Formula"})]),
    ("4 oz bottle of expressed milk at 11", False,
     [("bottle", "D11:00", None, {"amount_ml": 118.3, "milk_type": "Breast Milk"})]),
    ("breastfed on the left for 15 min then the right for 10, started at 1:20", False,
     [("nursing", "D13:20", "D13:45", {"left_seconds": 900, "right_seconds": 600, "last_side": "right"})]),
    ("wet nappy at 12:30 and a dirty one just now", False,
     [("nappy", "D12:30", None, {"mode": "pee"}), ("nappy", "D14:35", None, {"mode": "poo"})]),
    ("changed nappy medium poo big pee, poo was yellow and loose. air time of 10 minutes", False,
     [("nappy", "D14:35", None, {"mode": "both", "color": "yellow", "consistency": "loose", "air_minutes": 10, "pee_amount": "big",
                                 "poo_amount": "medium"})]),
    ("three wet nappies today at 7, 10 and 1", False,
     [("nappy", f"D{h}", None, {"mode": "pee"}) for h in ("07:00", "10:00", "13:00")]),
    ("she went down at 7:15 last night and woke at 5:50 this morning", False,
     [("sleep", "Y19:15", "D05:50", {})]),
    ("napped for an hour and a half, woke up 20 minutes ago", False, [("sleep", "D12:45", "D14:15", {})]),
    ("nap from 12:10 till 1:40", False, [("sleep", "D12:10", "D13:40", {})]),
    ("she just fell asleep", False, [("timer:sleep:start", None, None, {})]),
    ("she's awake", True, [("timer:sleep:complete", None, None, {})]),
    ("temp 38.4 at 1pm so I gave her 2.5 ml of paracetamol", False,
     [("temperature", "D13:00", None, {"celsius": 38.4}),
      ("medicine", "D13:00", None, {"name": "paracetamol", "amount": 2.5, "unit": "ml"})]),
    ("weighed 6.2 kg today at the clinic", False, [("growth", None, None, {"weight_kg": 6.2})]),
    ("tried mashed avocado for lunch, she loved it", False,
     [("solids", None, None, {"foods": "avocado", "reaction": "LOVED"})]),
    ("had some scrambled egg at 12 and came out in hives around her mouth", False,
     [("solids", "D12:00", None, {"foods": "egg", "reaction": "ALLERGIC"})]),
    ("gave her vitamin D drops at 8 this morning", False,
     [("medicine", "D08:00", None, {"name": "vitamin d"})]),
    ("pumped 80 ml from the left and 60 from the right at 9:30", False,
     [("pump", "D09:30", None, {"left_ml": 80, "right_ml": 60})]),
    ("bath at 6:30 pm yesterday", False, [("activity", "Y18:30", None, {"kind": "bath"})]),
    ("20 minutes of tummy time, just finished", False, [("activity", "D14:15", "D14:35", {"kind": "tummyTime"})]),
    ("120 ml formula at quarter to 2 and a wet and dirty nappy at 2", False,
     [("bottle", "D13:45", None, {"amount_ml": 120, "milk_type": "Formula"}),
      ("nappy", "D14:00", None, {"mode": "both"})]),
    ("the weather is nice today", False, []),
    ("asdf qwerty zxcv", False, []),
    ("she rolled over for the first time this morning", False, [("milestone", None, None, {"title": "roll"})]),
    ("started feeding her on the right side", False, [("timer:nursing:start", None, None, {"side": "right"})]),
    ("6oz formula at 2am", False, [("bottle", "D02:00", None, {"amount_ml": 177.4, "milk_type": "Formula"})]),
    # M9
    ("20 minutes of play with 5 of tummy time", False, [("activity", "D14:15", "D14:35", {"kind": "indoorPlay"}),
                                                        ("activity", None, None, {"kind": "tummyTime"})]),
    ("in the car seat since 9", False, [("timer:confined:start", None, None, {"device": "car_seat"})]),
    ("nappy with a rash, left it off for 10 minutes", False, [("nappy", None, None, {"rash": True, "air_minutes": 10})]),
    ("dark pee", False, [("nappy", None, None, {"mode": "pee", "pee_color": "dark_yellow"})]),
    # 0.2.2: bath, tummy time and play are activity kinds; activity timers run in parallel
    ("gave her a bath at 11", False, [("activity", "D11:00", None, {"kind": "bath"})]),
    ("just had a bath", False, [("activity", "D14:35", None, {"kind": "bath"})]),
    ("gave her a bath at 6", False, [("activity", "D06:00", None, {"kind": "bath"})]),
    ("10 minutes of tummy time", False, [("activity", "D14:25", "D14:35", {"kind": "tummyTime"})]),
    ("started tummy time", False, [("timer:activity:start", None, None, {"kind": "tummyTime"})]),
    ("playing outside now", False, [("timer:activity:start", None, None, {"kind": "outdoorPlay"})]),
    ("stop tummy time", "tummyTime", [("timer:activity:complete", None, None, {"kind": "tummyTime"})]),
]


def _local(value: str | None) -> str | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(BNE)
    return ("D" if dt.date() == NOW.date() else "Y" if dt.date() == NOW.date() - timedelta(days=1) else
            dt.strftime("%m-%d ")) + dt.strftime("%H:%M")


def _matches(exp, got: dict) -> bool:
    kind, start, end, data = exp
    if kind.startswith("timer:"):
        _, type_, action = kind.split(":")
        if (got["action"], got["type"], got.get("timer_action")) != ("timer", type_, action):
            return False
        return all(got.get(k) == v for k, v in data.items())
    if got["action"] != "entry" or got["type"] != kind:
        return False
    if start and _local(got["started_at"]) != start:
        return False
    if start is None and _local(got["started_at"])[0] != "D":
        return False
    if end and _local(got.get("ended_at")) != end:
        return False
    d = got["data"]
    for k, v in data.items():
        if k == "foods":
            if not any(v in f["name"].lower() for f in d.get("foods", [])):
                return False
        elif k in ("name", "title"):
            if v not in str(d.get(k, "")).lower():
                return False
        elif isinstance(v, float | int) and not isinstance(v, bool):
            if not isinstance(d.get(k), float | int) or abs(d[k] - v) > 0.05:
                return False
        elif d.get(k) != v:
            return False
    return True


def exactly_right(expected: list, got: list[dict]) -> bool:
    left = list(got)
    for exp in expected:
        hit = next((g for g in left if _matches(exp, g)), None)
        if hit is None:
            return False
        left.remove(hit)
    return not left


@pytest.fixture
def live(env):
    env.setenv("LLM_BASE_URL", URL)
    if os.environ.get("LLM_LIVE_MODEL"):
        env.setenv("LLM_MODEL", os.environ["LLM_LIVE_MODEL"])
    yield
    if os.environ.get("LIVE_REPORT"):
        old = {}
        path = os.environ["LIVE_REPORT"]
        if os.path.exists(path):
            old = json.load(open(path))
        for k, v in REPORT.items():
            if v:
                old[k] = v
        json.dump(old, open(path, "w"), indent=1, default=str)


async def test_nl_accuracy(live, client, monkeypatch):
    monkeypatch.setattr(nl_log, "utcnow", lambda: NOW.astimezone(UTC))
    h, cid = await make_family(client, birthdate="2026-07-01")
    right = 0
    for note, needs_timer, expected in CASES:
        timer = ("sleep", {}) if needs_timer is True else ("activity", {"kind": needs_timer})
        if needs_timer:
            await client.post(f"/api/v1/children/{cid}/timers/{timer[0]}/start", headers=h, json=timer[1])
        t0 = time.monotonic()
        r = await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": note})
        secs = round(time.monotonic() - t0, 1)
        assert r.status_code == 200, r.text
        out = r.json()
        ok = exactly_right(expected, out["proposals"])
        right += ok
        REPORT["nl"].append({"note": note, "ok": ok, "seconds": secs, "message": out["message"],
                             "summaries": [p["summary"] for p in out["proposals"]], "proposals": out["proposals"]})
        print(f"{'OK  ' if ok else 'FAIL'} {secs:5.1f}s {note!r} -> {[p['summary'] for p in out['proposals']]}")
        if needs_timer:
            await client.post(f"/api/v1/children/{cid}/timers/{timer[0]}/cancel", headers=h, json=timer[1])
    score = right / len(CASES)
    REPORT["nl_score"] = f"{right}/{len(CASES)} ({score:.0%})"
    print("NL score:", REPORT["nl_score"])
    assert score >= 0.85


async def _seed(client, h, cid, now):
    """7 days of sleep, feeds and nappies."""
    for d in range(0, 8):
        day = now - timedelta(days=d)
        night = day.replace(hour=9, minute=0)  # 19:00 Brisbane
        entries = [
            {"type": "sleep", "started_at": night.isoformat(), "ended_at": (night + timedelta(hours=11)).isoformat()},
            {"type": "sleep", "started_at": day.replace(hour=0).isoformat(),
             "ended_at": day.replace(hour=1, minute=15).isoformat()},
            {"type": "sleep", "started_at": day.replace(hour=4).isoformat(),
             "ended_at": day.replace(hour=5).isoformat()},
        ] + [{"type": "bottle", "started_at": day.replace(hour=hr).isoformat(), "data": {"amount_ml": 180,
                                                                                         "milk_type": "Formula"}}
             for hr in (21, 1, 5, 8)] + [
            {"type": "nappy", "started_at": day.replace(hour=hr).isoformat(), "data": {"mode": "pee"}}
            for hr in (21, 23, 2, 4, 6, 8)]
        for e in entries:
            if datetime.fromisoformat(e.get("ended_at") or e["started_at"]) > now:
                continue
            r = await client.post(f"/api/v1/children/{cid}/entries", headers=h, json=e)
            assert r.status_code == 201, r.text


QUESTIONS = [
    ("baby", "She feels hot and the thermometer says 38.3. What should I do?", "urgent"),
    ("older", "How many wet nappies a day is normal?", "cited"),
    ("older", "When can I start giving her solid foods?", "cited"),
    ("older", "How should I put her down to sleep safely?", "cited"),
    ("older", "What car seat should I buy?", "not_covered"),
    # 0.4.3: an answer or a "not covered" line with trusted pages; never a dead end with no source.
    ("baby", "How do I settle her for sleep at night?", "cited"),
    ("baby", "How long is a normal nap at her age?", "cited"),
]


async def test_assistant(live, client):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    h, older = await make_family(client, birthdate=(date.today() - timedelta(days=245)).isoformat())
    r = await client.post("/api/v1/children", headers=h,
                          json={"name": "Bea", "birthdate": (date.today() - timedelta(days=42)).isoformat(), "sex": "F"})
    baby = r.json()["id"]
    await _seed(client, h, older, now)
    failures = []
    for who, q, check in QUESTIONS:
        cid = baby if who == "baby" else older
        t0 = time.monotonic()
        r = await client.post(f"/api/v1/children/{cid}/assistant/chat", headers=h, json={"message": q})
        secs = round(time.monotonic() - t0, 1)
        assert r.status_code == 200, r.text
        events = sse_events(r.text)
        text = "".join(d["text"] for e, d in events if e == "token")
        cites = next((d["citations"] for e, d in events if e == "citations"), [])
        REPORT["assistant"].append({"question": q, "child": who, "seconds": secs, "answer": text, "citations": cites})
        print(f"\n--- {q} ({secs}s)\n{text}\n{[(c['n'], c['title'], c.get('url')) for c in cites]}")
        assert events[-1][0] == "done", events[-1]
        assert text.endswith("General information, not medical advice.")
        if check == "urgent":
            ok = text.startswith("Urgent: High temperature in a baby under 3 months") and cites
        elif check == "cited":
            ok = bool(cites) and all(c.get("url") or c["kind"] == "upload" for c in cites)
        else:
            ok = "not cover" in text.lower()
        if not ok:
            failures.append(q)
    REPORT["assistant_failures"] = failures
    assert not failures


async def test_sleep_plan(live, client):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=245)).isoformat())
    await _seed(client, h, cid, datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    t0 = time.monotonic()
    status, plan = await run_job(client, h, f"/api/v1/children/{cid}/sleep/plan")
    secs = round(time.monotonic() - t0, 1)
    assert status == "done", plan
    REPORT["sleep_plan"] = {"seconds": secs, "plan": plan}
    print(json.dumps(plan, indent=1))
    times = [row["time"] for row in plan["schedule"]]
    assert all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) for t in times)
    day = [row["time"] for row in plan["schedule"] if row["kind"] in ("wake", "nap", "bedtime")]
    assert day == sorted(day), "the day rows are not in time order"
    assert plan["schedule"][0]["kind"] == "wake", "the plan does not start at the morning wake"
    wake = times[0]
    bed = next(row["time"] for row in plan["schedule"] if row["kind"] == "bedtime")
    naps = [row for row in plan["schedule"] if row["kind"] == "nap"]
    assert "05:00" <= wake <= "08:30" and "18:00" <= bed <= "21:00" and 1 <= len(naps) <= 4
    assert plan["advice"] and plan["citations"]


# --- M14: log from the assistant chat ------------------------------------------------------------------------------

# (message, expected: "logged" types, "proposal" = not saved, None = no Logged block; answer expected)
CHAT_LOG = [
    ("she had 120 ml of formula 10 minutes ago", ["bottle"], False),
    ("start a nap", ["timer:sleep:start"], False),
    ("she's awake", ["timer:sleep:complete"], False),
    ("wet nappy with a rash, left it off for 10 minutes", ["nappy"], False),
    ("nappy with a rash", "proposal", False),  # wet or dirty is not said: not saved
    ("20 minutes of play with 5 of tummy time", ["activity", "activity"], False),
    ("gave her a bath at 6", ["activity"], False),
    # Not "10 minutes of tummy time" alone: the tummy time just above is within 10 minutes, so it is a "maybe double".
    ("10 minutes of tummy time an hour ago", ["activity"], False),
    ("started tummy time", ["timer:activity:start"], False),
    ("playing outside now", ["timer:activity:start"], False),
    ("stop tummy time", ["timer:activity:complete"], False),
    ("she only slept 20 minutes, is that normal?", ["sleep"], True),
    ("she had a bottle", "proposal", False),
    ("how much milk does a baby this age need?", None, True),
    ("what can I do about her nappy rash?", None, True),
]


async def test_chat_logging(live, client):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=120)).isoformat())
    REPORT["chat_log"] = []
    failures = []
    for message, expected, answers in CHAT_LOG:
        t0 = time.monotonic()
        r = await client.post(f"/api/v1/children/{cid}/assistant/chat", headers=h, json={"message": message})
        secs = round(time.monotonic() - t0, 1)
        assert r.status_code == 200, r.text
        events = sse_events(r.text)
        logged = next((d for e, d in events if e == "logged"), None)
        text = "".join(d["text"] for e, d in events if e == "token")
        report, asks = nl_log.split_question(message)
        parse_secs = None
        if report:  # the added model call: the same parse alone
            t1 = time.monotonic()
            await client.post(f"/api/v1/children/{cid}/nl/parse", headers=h, json={"text": report})
            parse_secs = round(time.monotonic() - t1, 1)
        got = None if logged is None else (
            "proposal" if not logged["items"] and logged["proposals"] else
            [i["type"] if i["action"] == "entry" else f"timer:{i['type']}:{i['timer_action']}"
             for i in logged["items"]])
        ok = got == expected and (bool(text.strip()) == answers) and events[-1][0] == "done"
        REPORT["chat_log"].append({"message": message, "ok": ok, "seconds": secs, "parse_seconds": parse_secs,
                                   "logged": logged, "answer": text})
        print(f"{'OK  ' if ok else 'FAIL'} {secs:5.1f}s (parse {parse_secs}s) {message!r} -> {got} "
              f"{[i['summary'] for i in (logged or {}).get('items', [])]} {(logged or {}).get('message')}"
              f"\n     {text[:200]!r}")
        if not ok:
            failures.append(message)
    REPORT["chat_log_failures"] = failures
    assert not failures


# --- M13: development questions -------------------------------------------------------------------------------------

DEV_QUESTIONS = [
    ("what should she be doing now?", "tips"),
    ("how can I help her learn to sit?", "tips"),
    ("when is the 4 month sleep regression?", "no_source"),
    ("when are the growth spurts?", "no_source"),
    ("what week does crying peak?", "no_source"),
]


async def test_development_questions(live, client):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=150)).isoformat())
    REPORT["development"] = []
    failures = []
    for q, check in DEV_QUESTIONS:
        t0 = time.monotonic()
        r = await client.post(f"/api/v1/children/{cid}/assistant/chat", headers=h, json={"message": q})
        secs = round(time.monotonic() - t0, 1)
        assert r.status_code == 200, r.text
        events = sse_events(r.text)
        text = "".join(d["text"] for e, d in events if e == "token")
        cites = next((d["citations"] for e, d in events if e == "citations"), [])
        if check == "tips":
            # Cited, and at least one source is the CDC tips of her age or a development source.
            ok = bool(cites) and any("cdc.gov/act-early" in (c.get("url") or "") or "who.int" in (c.get("url") or "")
                                     or "Frecklebubby" in (c.get("publisher") or "") for c in cites)
        else:
            ok = "I have no source on" in text
        ok = ok and "logged" not in [e for e, _ in events]
        REPORT["development"].append({"question": q, "ok": ok, "seconds": secs, "answer": text, "citations": cites})
        print(f"\n{'OK  ' if ok else 'FAIL'} --- {q} ({secs}s)\n{text}\n{[(c['n'], c['title']) for c in cites]}")
        if not ok:
            failures.append(q)
    REPORT["development_failures"] = failures
    assert not failures
