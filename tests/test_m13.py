"""M13b: corrected age, development items, CDC tips, the band notification and age-fit passages."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, text

from frecklebubby.ai import support_report
from frecklebubby.config import PACKAGE_DATA, get_settings
from frecklebubby.db import SessionLocal, init_db
from frecklebubby.knowledge.store import search
from frecklebubby.models import Child, Notification
from frecklebubby.services import development, reminders
from frecklebubby.services.children import dev_age_days
from frecklebubby.services.library import library

from .conftest import ctx_for, make_family
from .fake_llm import fake_llm_fixture, sse_events  # noqa: F401
from .test_support_report import make, seed

API = "/api/v1"
BNE = ZoneInfo("Australia/Brisbane")


def test_support_phrases():
    for name, phrase in development.SUPPORT.values():
        assert phrase in library(name)[1], (name, phrase)
    # Every CDC band has its tips file.
    for band in (2, 4, 6, 9, 12, 15, 18, 24, 30, 36, 48, 60):
        assert library(development.tips_file(band))[1]


def test_old_database_gets_the_new_columns(env, tmp_path):
    init_db(tmp_path)
    eng = create_engine(f"sqlite:///{tmp_path / 'frecklebubby.db'}")
    with eng.begin() as c:  # a 0.1.0 database has no due_date and no logged column
        c.execute(text("ALTER TABLE child DROP COLUMN due_date"))
        c.execute(text("ALTER TABLE chat_message DROP COLUMN logged"))
    init_db(tmp_path)
    with eng.begin() as c:
        assert "due_date" in {r[1] for r in c.execute(text("PRAGMA table_info(child)"))}
        assert "logged" in {r[1] for r in c.execute(text("PRAGMA table_info(chat_message)"))}


def test_corrected_age_until_2_years():
    c = Child(birthdate=date(2026, 1, 1), due_date=date(2026, 3, 1))
    assert dev_age_days(c, date(2026, 5, 1)) == 61  # from the due date
    assert dev_age_days(c, date(2026, 2, 1)) == 0  # before the due date: 0
    assert dev_age_days(c, date(2028, 1, 1)) == 730  # 2 years: from the birth date again
    assert dev_age_days(Child(birthdate=date(2026, 1, 1)), date(2026, 5, 1)) == 120


async def test_due_date_validation(client):
    h, cid = await make_family(client, birthdate="2026-06-01")
    r = await client.patch(f"{API}/children/{cid}", headers=h, json={"due_date": "2026-07-15"})
    assert r.status_code == 200 and r.json()["due_date"] == "2026-07-15"
    for bad in ("2026-05-20", "2026-12-01"):  # before the birth, or more than 20 weeks after it
        r = await client.patch(f"{API}/children/{cid}", headers=h, json={"due_date": bad})
        assert r.status_code == 422 and "due_date" in r.json()["detail"]
    ms = (await client.get(f"{API}/children/{cid}/milestones", headers=h)).json()
    days = (date.today() - date(2026, 7, 15)).days
    assert ms["corrected"] is True and ms["age_months"] == round(days / 30.4375, 1)
    r = await client.patch(f"{API}/children/{cid}", headers=h, json={"due_date": None})
    assert r.json()["due_date"] is None


def test_windows_and_wording():
    hits = {i["key"] for i in development.around(150)}  # 4.9 months
    assert "who-sitting-without-support" in hits and "who-walking-alone" not in hits
    for i in development.items():
        assert not re.search(r"\bshould\b", i["text"], re.I), i["key"]
        lo, hi = development.window(i)
        assert 0 <= lo <= hi, i["key"]


@pytest.mark.parametrize("heading, age, ok", [
    ("What you can do for your 4-month-old (CDC tips and activities) – 4 months: how to help your baby (CDC tips "
     "and activities)", 4.5, True),
    ("x – 24 months (2 years): more tips and activities (CDC)", 4.5, False),
    ("x – 24 months (2 years): more tips and activities (CDC)", 25, True),
    ("x – 2 months: how to help your baby (CDC tips and activities)", 1, True),
    ("x – From 24 months: play ideas and screen time", 4, False),
    ("x – From 4 months: play ideas", 3, True),
    ("x – Under 2 years and 2 to 5 years: screen time", 4, True),
    ("x – Under 2 years and 2 to 5 years: screen time", 70, True),
    ("x – 6 to 12 months: how to help your baby talk", 4, True),
    ("x – 6 to 12 months: how to help your baby talk", 2, False),
    ("x – 18 months to 3 years: when to start toilet training", 4, False),
    ("x – Toddlers (aged 1 to 2)", 4, False),
    ("x – Babies (under 1 year)", 4, True),
    ("x – Any age: toy safety", 40, True),
    ("x – Newborn: dummies and breastfeeding", 6, False),
    ("x – What baby poo looks like", 30, True),
])
def test_fits(heading, age, ok):
    assert development.fits(heading, age) is ok


async def test_support_report_passages_fit_the_age(client, fake_llm):
    """M11 fault: a 4-month-old got screen-time tips for older children. The play query finds passages for older
    ages; none of them reach the model now."""
    _, cid = await seed(client)
    s, ctx = ctx_for("a@example.com")
    try:
        found = [h["heading"] for h in search(s, ctx.fam, support_report.QUERIES["play"], limit=12)]
        assert any(not development.fits(x, 4.3) for x in found)  # the search alone gives some for other ages
    finally:
        s.close()
    await make(cid)
    prompt = fake_llm.requests[0]["messages"][1]["content"]
    headings = re.findall(r"^\[\d+\] (.+?):\n", prompt, re.M)
    assert headings and all(development.fits(x.split(", ", 1)[-1], 4.3) for x in headings), headings
    assert "24 months (2 years)" not in prompt and "From 24 months" not in prompt


async def test_support_report_milestones_block_has_development_items(client, fake_llm):
    _, cid = await seed(client)
    rep = await make(cid)
    ms = next(b for b in rep["blocks"] if b["area"] == "milestones")
    dev = [d for d in ms["details"] if d.startswith("Around now: ")]
    assert 1 <= len(dev) <= 3 and all(re.search(r"\([A-Z][^)]*\)$", d) for d in dev), dev


async def test_insight_cards(client):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=150)).isoformat())
    cards = (await client.get(f"{API}/children/{cid}/insights", headers=h)).json()
    act = next(c for c in cards if c["kind"] == "development_activity")
    assert "sit without support" in act["body"] and "WHO: Most healthy babies" in act["body"]
    assert any("who.int" in c["url"] for c in act["citations"])
    assert not any(re.search(r"\bshould\b", c["body"], re.I) for c in cards if c["kind"].startswith("development"))
    ms = next(c for c in cards if c["kind"] == "milestones" and "Coming up" not in c["title"])
    assert "CDC tips for this age: " in ms["body"]
    assert any(c["title"].startswith("What you can do for your 4-month-old") for c in ms["citations"])
    assert [c["n"] for c in ms["citations"]] == list(range(1, len(ms["citations"]) + 1))
    # Born early: the corrected age moves the windows and the card says so.
    due = (date.today() - timedelta(days=150) + timedelta(weeks=8)).isoformat()
    await client.patch(f"{API}/children/{cid}", headers=h, json={"due_date": due})
    cards = (await client.get(f"{API}/children/{cid}/insights", headers=h)).json()
    dev = [c for c in cards if c["kind"].startswith("development")]
    assert dev and all(development.CORRECTED_NOTE in c["body"] for c in dev)


async def test_band_notification(client):
    # A child who reached 4 months (122 days) 2 days before a fake noon.
    noon = datetime(2026, 11, 20, 12, 0, tzinfo=BNE)
    born = (noon.date() - timedelta(days=124)).isoformat()
    h, cid = await make_family(client, birthdate=born)
    with SessionLocal() as s:
        assert reminders.tick(s, noon) == 1
        n = s.scalar(select(Notification).where(Notification.kind == "milestones:band"))
        assert n.title == "Ada: milestones by 4 months" and n.dedupe_key == f"milestones:band:{cid}:4"
        assert "Things to look for: " in n.body and "every child grows at their own pace" in n.body.lower()
        assert reminders.tick(s, noon + timedelta(hours=1)) == 0  # once per child and band
        assert development.tick(s, noon.replace(hour=22) + timedelta(days=1)) == 0  # night: no message
        s.execute(Notification.__table__.delete())
        s.commit()
        assert development.tick(s, noon.replace(hour=22)) == 0  # night
        assert development.tick(s, noon + timedelta(days=20)) == 0  # too long after the band start
    # Off in the family settings.
    await client.patch(f"{API}/family/settings", headers=h, json={"milestone_alerts": False})
    with SessionLocal() as s:
        assert development.tick(s, noon) == 0
    await client.patch(f"{API}/family/settings", headers=h, json={"milestone_alerts": True})
    # Born early: at the same date the corrected age is under 4 months, so no 4-month message.
    await client.patch(f"{API}/children/{cid}", headers=h,
                       json={"due_date": (noon.date() - timedelta(days=100)).isoformat()})
    with SessionLocal() as s:
        assert development.tick(s, noon) == 0


async def test_assistant_gets_age_context_and_passages(client, fake_llm):
    h, cid = await make_family(client, birthdate=(date.today() - timedelta(days=130)).isoformat())
    fake_llm.replies.append("Hold her up while she sits [1].")
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h,
                          json={"message": "how can I help her learn to sit?"})
    assert r.status_code == 200
    assert len(fake_llm.requests) == 1  # a question: no parse call
    prompt = fake_llm.requests[0]["messages"][-1]["content"]
    assert "CDC milestones by 4 months: marked 0 of" in prompt
    assert "Development around this age: " in prompt
    assert "4 months: how to help your baby (CDC tips and activities)" in prompt  # picked by age, not by search
    assert "sitting without support" in prompt  # the WHO window passage of the sitting item
    assert "Hold your baby up while she sits." in prompt  # its CDC tip
    assert "24 months (2 years)" not in prompt


@pytest.mark.parametrize("question, topic", [
    ("when is the 4 month sleep regression?", "sleep regressions"),
    ("when are the growth spurts?", "the ages of growth spurts"),
    ("what week does crying peak?", "a week when crying peaks"),
    ("when will she be dry at night?", "an age for dryness at night"),
])
async def test_no_source_topics(client, fake_llm, question, topic):
    h, cid = await make_family(client)
    fake_llm.replies.append("The sources I have do not cover this.")
    r = await client.post(f"{API}/children/{cid}/assistant/chat", headers=h, json={"message": question})
    text_ = "".join(d["text"] for e, d in sse_events(r.text) if e == "token")
    assert text_.startswith(f"I have no source on {topic}.")
    if fake_llm.requests:
        assert "Do not give an age or a time for it." in fake_llm.requests[-1]["messages"][-1]["content"]


def test_band_message_names_2_or_3_things(env):
    env.setenv("BUNDLED_DATA_DIR", str(PACKAGE_DATA))  # the real CDC catalog
    get_settings.cache_clear()
    child = Child(name="Ada", birthdate=date(2026, 1, 1))
    for band in development.bands():
        title, body = development.band_message(child, band, set())
        things = development.look_for(band, set())
        assert 2 <= len(things) <= 3 and title == f"Ada: milestones by {band} months"
        assert all(t in body for t in things)


def test_nap_change_library_matches_the_norms_file():
    """The nap-change text in the library has the same ages as the bundled norms (25th to 75th percentile)."""
    import json

    from frecklebubby.config import PACKAGE_DATA
    text = (PACKAGE_DATA / "library" / "sleep-nap-changes.md").read_text()
    tr = json.loads((PACKAGE_DATA / "sleep_norms.json").read_text())["transitions"]
    for key in ("4to3", "3to2", "2to1"):
        lo, hi = (round(tr[key]["age_days"][i] / 30.4375, 1) for i in (1, 3))
        assert f"between {lo:g} and {hi:g} months" in text, key
