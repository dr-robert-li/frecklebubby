"""Sleep training (0.7.0): an option, off by default. Methods, age limits, the scale, the switch, and the plan."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from frecklebubby.models import Entry
from frecklebubby.services.training import scale, waits

from .conftest import ctx_for, make_family

BNE = ZoneInfo("Australia/Brisbane")
API = "/api/v1"


def born(months: float) -> str:
    return (date.today() - timedelta(days=round(months * 30.4375))).isoformat()


async def family(client, months, email="a@example.com", due=None):
    h, cid = await make_family(client, email=email, birthdate=born(months))
    if due:
        assert (await client.patch(f"{API}/children/{cid}", json={"due_date": due}, headers=h)).status_code == 200
    return h, f"{API}/children/{cid}/sleep/training", cid


def night(n, minutes=40, wakes=2, answer="ok"):
    return {"day": (date.today() - timedelta(days=20 - n)).isoformat(), "minutes_to_sleep": minutes, "wakes": wakes,
            "answer": answer}


def test_the_scale_and_the_waits():
    assert [scale([4, 3, 1], p) for p in (1, 5, 10)] == [4, 3, 1]
    assert waits(1) == [2]  # gentle: a fixed 2 minutes
    assert waits(5) == [2, 4, 6, 8, 10]  # the usual schedule of the trials (Hiscock 2008)
    assert waits(10) == [5, 10, 15]  # firm; no source gives a wait above 15 minutes
    assert all(max(waits(p)) <= 15 and waits(p) == sorted(waits(p)) for p in range(1, 11))
    assert [max(waits(p)) for p in range(1, 11)] == sorted(max(waits(p)) for p in range(1, 11))  # firmer: never shorter


async def test_age_limits(client):
    h, url, _ = await family(client, 3)  # below 4 months: not available, and the server refuses it
    g = (await client.get(url, headers=h)).json()
    assert g["gate"]["available"] is False and "not for a baby younger than 4 months" in g["gate"]["reason"]
    assert g["training"] is None
    assert (await client.put(url, json={"method": "graduated"}, headers=h)).status_code == 422

    h, url, _ = await family(client, 5, "b@example.com")  # 4 to 6 months: a warning to confirm, no plain extinction
    g = (await client.get(url, headers=h)).json()["gate"]
    assert g["methods"] == ["graduated"] and "Speak to a child health nurse first" in g["warning"]
    r = await client.put(url, json={"method": "graduated"}, headers=h)
    assert r.status_code == 409 and "start at about 6 months" in r.json()["detail"]
    assert (await client.put(url, json={"method": "extinction", "confirm_warning": True}, headers=h)).status_code == 422
    assert (await client.put(url, json={"method": "graduated", "confirm_warning": True}, headers=h)).status_code == 200

    h, url, _ = await family(client, 8, "c@example.com")  # from 6 months; bedtime fading from 12 months
    assert (await client.get(url, headers=h)).json()["gate"]["methods"] == ["extinction", "graduated"]
    h, url, _ = await family(client, 14, "d@example.com")
    assert (await client.get(url, headers=h)).json()["gate"]["methods"] == ["extinction", "graduated", "fading"]
    # Born 2 months early: 5 months old is 3 months corrected. Not available.
    h, url, _ = await family(client, 5, "e@example.com", due=born(3))
    assert (await client.get(url, headers=h)).json()["gate"]["available"] is False


async def test_graduated_extinction_the_scale_and_the_switch(client):
    h, url, _ = await family(client, 9)
    t = (await client.put(url, json={"method": "graduated", "pace": 5}, headers=h)).json()["training"]
    assert t["status"] == "active" and t["auto_pace"] is True and t["tonight"]["night"] == 1
    steps = " ".join(t["tonight"]["steps"])
    assert "2, 4, 6, 8, 10 minutes, then 10 minutes each time" in steps and "Do not pick Ada up" in steps
    assert "A feed that Ada still needs at night stays" in steps and "Change the pace in the morning" in steps
    # The switch is on: "too hard" moves the scale one step to gentle for the next night; "faster" one step to firm.
    t = (await client.post(url + "/nights", json=night(1, answer="too_hard"), headers=h)).json()["training"]
    assert t["pace"] == 4 and t["tonight"]["night"] == 2 and t["nights"][0]["pace"] == 5
    t = (await client.post(url + "/nights", json=night(2, answer="faster"), headers=h)).json()["training"]
    assert t["pace"] == 5
    # The switch is off: the scale stays, and the parent moves it by hand.
    t = (await client.put(url, json={"auto_pace": False, "pace": 9}, headers=h)).json()["training"]
    t = (await client.post(url + "/nights", json=night(3, answer="too_hard"), headers=h)).json()["training"]
    assert t["pace"] == 9 and "4, 8, 12, 14 minutes, then 14 minutes each time" in " ".join(t["tonight"]["steps"])
    assert (await client.put(url, json={"pace": 11}, headers=h)).status_code == 422
    # The same night again replaces the report.
    t = (await client.post(url + "/nights", json=night(3, minutes=5), headers=h)).json()["training"]
    assert len(t["nights"]) == 3 and t["nights"][-1]["minutes_to_sleep"] == 5
    # A new method needs a stop first. After the end the mode is off.
    assert (await client.put(url, json={"method": "extinction"}, headers=h)).status_code == 409
    assert (await client.delete(url, headers=h)).json()["training"] is None
    assert (await client.delete(url, headers=h)).status_code == 404


async def test_parental_presence_steps_follow_the_scale(client):
    h, url, _ = await family(client, 9)
    t = (await client.put(url, json={"method": "graduated", "presence": True, "pace": 5}, headers=h)).json()["training"]
    assert "Step 1 of 5: Sit beside the bed. Pat or stroke Ada" in " ".join(t["tonight"]["steps"])
    assert "Each step is for 3 nights" in " ".join(t["tonight"]["steps"])
    for n in (1, 2, 3):
        t = (await client.post(url + "/nights", json=night(n), headers=h)).json()["training"]
    assert "Step 2 of 5: Sit beside the bed. Do not touch Ada" in " ".join(t["tonight"]["steps"])
    t = (await client.put(url, json={"pace": 10}, headers=h)).json()["training"]  # firm: 1 night for each step
    assert "Step 4 of 5: Sit at the door" in " ".join(t["tonight"]["steps"])
    await client.delete(url, headers=h)
    t = (await client.put(url, json={"method": "extinction", "presence": True}, headers=h)).json()["training"]
    assert "Night 1 of 7: lie down in the same room" in " ".join(t["tonight"]["steps"])
    await client.delete(url, headers=h)
    t = (await client.put(url, json={"method": "extinction"}, headers=h)).json()["training"]
    assert "Do not go back in until the morning" in " ".join(t["tonight"]["steps"])


async def test_review_success_no_gain_two_weeks_and_illness(client):
    h, url, cid = await family(client, 9)
    await client.put(url, json={"method": "graduated", "auto_pace": False}, headers=h)
    for n in range(1, 8):
        t = (await client.post(url + "/nights", json=night(n, minutes=45), headers=h)).json()["training"]
    assert t["review"]["kind"] == "no_gain" and "gentler pace" in t["review"]["text"]
    for n in range(8, 11):
        t = (await client.post(url + "/nights", json=night(n, minutes=8, wakes=1), headers=h)).json()["training"]
    assert t["review"]["kind"] == "success" and "You can end the sleep training" in t["review"]["text"]
    for n in range(11, 15):
        t = (await client.post(url + "/nights", json=night(n, minutes=30), headers=h)).json()["training"]
    assert t["review"]["kind"] == "stop" and "Speak to a child health nurse or a doctor" in t["review"]["text"]
    assert t["pause_hint"] is False
    await client.post(f"{API}/children/{cid}/entries", headers=h, json={
        "type": "temperature", "started_at": datetime.now(BNE).isoformat(), "data": {"celsius": 38.6}})
    t = (await client.get(url, headers=h)).json()["training"]
    assert t["pause_hint"] is True
    t = (await client.put(url, json={"status": "paused"}, headers=h)).json()["training"]
    assert t["status"] == "paused"


async def test_bedtime_fading_and_the_sleep_plan(client):
    h, url, cid = await family(client, 30)  # 2.5 years
    plan = f"{API}/children/{cid}/sleep/regime"
    # Bedtime fading starts from the time at which the child falls asleep now: it needs logs.
    r = await client.put(url, json={"method": "fading", "goal_bedtime": "19:30"}, headers=h)
    assert r.status_code == 422 and "Log the night sleep" in r.json()["detail"]
    assert (await client.put(url, json={"method": "fading"}, headers=h)).status_code == 422
    s, _ = ctx_for("a@example.com")
    today = datetime.now(BNE).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(1, 12):  # asleep at 21:30, awake at 06:30: 9 hours, below the recommended 11 to 14 hours
        a = today - timedelta(days=d) + timedelta(hours=21, minutes=30)
        s.add(Entry(child_id=cid, type="sleep", started_at=a, ended_at=a + timedelta(hours=9), data={}))
    s.commit()
    before = (await client.get(plan, headers=h)).json()
    assert before["training"] is False and any(x["kind"] == "night" and x["change"] for x in before["schedule"])
    t = (await client.put(url, json={"method": "fading", "goal_bedtime": "19:30", "auto_pace": False}, headers=h)).json()["training"]
    assert t["tonight"]["bedtime"] == "22:00" and "Bedtime tonight: 22:00" in t["tonight"]["steps"][0]
    # While the mode runs, the plan takes no step at bedtime: bedtime is the one of the training.
    after = (await client.get(plan, headers=h)).json()
    row = next(x for x in after["schedule"] if x["kind"] == "night")
    assert after["training"] is True and row["time"] == "22:00" and "Sleep training (bedtime fading)" in row["change"]
    # 2 nights at the start time. Then 2 good nights in a row (asleep in 15 minutes or less): 15 minutes earlier.
    for n, minutes, expect in ((1, 10, "22:00"), (2, 10, "21:45"), (3, 12, "21:45"), (4, 5, "21:30"), (5, 40, "21:45")):
        t = (await client.post(url + "/nights", json=night(n, minutes=minutes), headers=h)).json()["training"]
        assert t["tonight"]["bedtime"] == expect, (n, t["tonight"]["bedtime"])
    # The mode off: the plan works as before.
    await client.delete(url, headers=h)
    again = (await client.get(plan, headers=h)).json()
    assert again["training"] is False and again["schedule"] == before["schedule"]
