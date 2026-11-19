"""Huckleberry → Frecklebubby mapping. Rows are the fork's own models, so a schema change there breaks these tests."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("huckleberry_api")

from huckleberry_api.firebase_types import (  # noqa: E402
    FirebaseActivityIntervalData,
    FirebaseBottleFeedIntervalData,
    FirebaseBreastFeedIntervalData,
    FirebaseChildDocument,
    FirebaseDiaperData,
    FirebaseDiaperQuantity,
    FirebaseGrowthData,
    FirebaseMedicationData,
    FirebasePumpIntervalData,
    FirebaseSleepCondition,
    FirebaseSleepDetails,
    FirebaseSleepIntervalData,
    FirebaseSleepLocations,
    FirebaseSolidsFeedIntervalData,
    FirebaseTemperatureData,
    SolidsFoodEntry,
)

from frecklebubby.importer.huckleberry import Skip, check, map_child, map_row  # noqa: E402

from .conftest import utc  # noqa: E402

T0 = 1_779_000_000  # 2026-05-17T06:40:00Z
START = utc(2026, 5, 17, 6, 40)
NOW = utc(2026, 11, 20)
BNE = ZoneInfo("Australia/Brisbane")


def full(tracker, row):
    e = map_row(tracker, row)
    e["data"] = check(e, NOW)
    return e


def test_sleep():
    row = FirebaseSleepIntervalData(start=T0, duration=5400, offset=-600, details=FirebaseSleepDetails(
        startSleepCondition=FirebaseSleepCondition(happy=True, **{"10-20_minutes": True}),
        endSleepCondition=FirebaseSleepCondition(upset=True, happy=False),
        sleepLocations=FirebaseSleepLocations(car=True, swing=False), notes=" nap in car "))
    e = full("sleep", row)
    assert e == {"type": "sleep", "started_at": START, "ended_at": START + timedelta(seconds=5400),
                 "data": {"start_conditions": ["happy", "10-20_minutes"], "end_conditions": ["upset"],
                          "locations": ["car"]}, "notes": "nap in car"}


def test_sleep_without_details_and_ms_start():
    e = full("sleep", FirebaseSleepIntervalData(start=T0 * 1000, duration=60, offset=0))
    assert e["started_at"] == START and e["notes"] is None
    assert e["data"] == {"start_conditions": [], "end_conditions": [], "locations": []}


def test_breast():
    e = full("feed", FirebaseBreastFeedIntervalData(mode="breast", start=T0, lastSide="right", leftDuration=600,
                                                     rightDuration=480.4, offset=0, notes="sleepy"))
    assert e["type"] == "nursing" and e["ended_at"] == START + timedelta(seconds=1080)
    assert e["data"] == {"left_seconds": 600.0, "right_seconds": 480.4, "last_side": "right"}
    e = full("feed", FirebaseBreastFeedIntervalData(mode="breast", start=T0, lastSide="none", leftDuration=300,
                                                     offset=0))
    assert e["data"] == {"left_seconds": 300.0} and e["ended_at"] == START + timedelta(seconds=300)


def test_bottle_oz_and_missing_amount():
    e = full("feed", FirebaseBottleFeedIntervalData(mode="bottle", start=T0, bottleType="Formula", amount=4,
                                                     units="oz", offset=0))
    assert e["data"] == {"milk_type": "Formula", "amount_ml": 118.3}  # 4 × 29.5735 ml
    e = full("feed", FirebaseBottleFeedIntervalData(mode="bottle", start=T0, bottleType="Cow Milk", units="ml",
                                                     offset=0, notes="cup"))
    assert e["data"] == {"milk_type": "Cow Milk", "amount_ml": 0.0}
    assert e["notes"] == "cup No amount in Huckleberry."


def test_solids():
    row = FirebaseSolidsFeedIntervalData(mode="solids", start=T0, offset=0, notes="first try", foods={
        "a": SolidsFoodEntry(id="a", created_name="Egg", source="curated", amount=1.5),
        "b": SolidsFoodEntry(id="b", created_name="", source="custom", amount="a little"),
        "c": SolidsFoodEntry(id="c", created_name="Pear", source="curated"),
    }, reactions={"LOVED": True, "ALLERGIC": True, "MEH": False})
    e = full("feed", row)
    assert e["data"] == {"foods": [{"name": "Egg", "amount": "1.5"}, {"name": "b", "amount": "a little"},
                                   {"name": "Pear"}], "reaction": "ALLERGIC"}
    assert e["notes"] == "first try Reactions in Huckleberry: LOVED, ALLERGIC."
    with pytest.raises(Skip, match="no food"):
        map_row("feed", FirebaseSolidsFeedIntervalData(mode="solids", start=T0, offset=0))


def test_nappy_quantity_encoding():
    row = FirebaseDiaperData(mode="both", start=T0, offset=0, quantity=FirebaseDiaperQuantity(pee=0.0, poo=100.0),
                             color="green", consistency="mucousy", diaperRash=True, notes="n")
    e = full("diaper", row)
    assert e["type"] == "nappy" and e["notes"] == "n"
    assert e["data"] == {"mode": "both", "pee_amount": "little", "poo_amount": "big", "color": "green",
                         "consistency": "mucousy", "rash": True}
    e = full("diaper", FirebaseDiaperData(mode="pee", start=T0, offset=0, quantity=FirebaseDiaperQuantity(pee=50)))
    assert e["data"] == {"mode": "pee", "pee_amount": "medium", "rash": False}
    e = full("diaper", FirebaseDiaperData(mode="pee", start=T0, offset=0, quantity=FirebaseDiaperQuantity(pee=25)))
    assert "pee_amount" not in e["data"]  # not an app value: no amount


def test_potty():
    e = full("diaper", FirebaseDiaperData(mode="poo", start=T0, offset=0, isPotty=True, howItHappened="accident"))
    assert e["type"] == "potty" and e["data"]["result"] == "accident"
    assert full("diaper", FirebaseDiaperData(mode="dry", start=T0, offset=0, isPotty=True))["data"]["result"] == "satButDry"
    assert full("diaper", FirebaseDiaperData(mode="pee", start=T0, offset=0, isPotty=True))["data"]["result"] == "wentPotty"


def test_growth_imperial_live_app_encoding():
    # Live-app row from the fork's tests: 14 lb 2 oz, 5 ft 4 in, 10.2 in.
    e = full("health", FirebaseGrowthData(mode="growth", start=T0, offset=0, weight=14.125, weightUnits="lbs.oz",
                                          height=5.333333333333333, heightUnits="ft.in", head=10.2, headUnits="hin"))
    assert e["data"] == {"weight_kg": 6.407, "height_cm": 162.56, "head_cm": 25.91}


def test_growth_metric_and_fork_writer_inches():
    e = full("health", FirebaseGrowthData(mode="growth", start=T0, offset=0, weight=7.2, weightUnits="kg",
                                          height=66, heightUnits="cm", head=42.5, headUnits="hcm"))
    assert e["data"] == {"weight_kg": 7.2, "height_cm": 66.0, "head_cm": 42.5}
    # The fork's log_growth writes inches under "ft.in".
    e = full("health", FirebaseGrowthData(mode="growth", start=T0, offset=0, height=25.0, heightUnits="ft.in"))
    assert e["data"] == {"height_cm": 63.5}
    with pytest.raises(Skip, match="weight_kg, height_cm or head_cm"):
        full("health", FirebaseGrowthData(mode="growth", start=T0, offset=0))


def test_medication():
    e = full("health", FirebaseMedicationData(mode="medication", start=T0, offset=0, medication_id="x",
                                              medication_name="Ibuprofen", amount=0.0, notes=""))
    assert e["type"] == "medicine" and e["data"] == {"name": "Ibuprofen"} and e["notes"] is None
    e = full("health", FirebaseMedicationData(mode="medication", start=T0, offset=0, medication_id="x",
                                              medication_name="Vitamin D", amount=1, units="drops", notes="am"))
    assert e["data"] == {"name": "Vitamin D", "amount": 1.0, "unit": "drops"} and e["notes"] == "am"


def test_temperature():
    e = full("health", FirebaseTemperatureData(mode="temperature", start=T0, offset=0, amount=100.4, units="F"))
    assert e["type"] == "temperature" and e["data"] == {"celsius": 38.0}
    assert full("health", FirebaseTemperatureData(mode="temperature", start=T0, offset=0, amount=98.6,
                                                  units="F"))["data"] == {"celsius": 37.0}
    assert full("health", FirebaseTemperatureData(mode="temperature", start=T0, offset=0, amount=36.85,
                                                  units="C"))["data"] == {"celsius": 36.85}


def test_pump():
    e = full("pump", FirebasePumpIntervalData(start=T0, entryMode="leftright", leftAmount=2, rightAmount=1,
                                              units="oz", offset=0, duration=600))
    assert e["data"] == {"left_ml": 59.1, "right_ml": 29.6, "total_ml": 88.7}
    assert e["ended_at"] == START + timedelta(seconds=600)
    e = full("pump", FirebasePumpIntervalData(start=T0, entryMode="total", leftAmount=45, rightAmount=45,
                                              units="ml", offset=0))
    assert e["data"] == {"total_ml": 90.0} and e["ended_at"] is None
    e = full("pump", FirebasePumpIntervalData(start=T0, entryMode="total", units="ml", offset=0))
    assert e["data"] == {}


def test_activity():
    e = full("activities", FirebaseActivityIntervalData(mode="skinToSkin", start=T0, offset=0, duration=1200,
                                                        notes="calm"))
    assert e == {"type": "activity", "started_at": START, "ended_at": START + timedelta(seconds=1200),
                 "data": {"kind": "skinToSkin"}, "notes": "calm"}
    assert full("activities", FirebaseActivityIntervalData(mode="bath", start=T0, offset=0))["ended_at"] is None


def test_range_rules():
    # Lenient: real history can pass these limits.
    e = full("feed", FirebaseBreastFeedIntervalData(mode="breast", start=T0, lastSide="left", leftDuration=90000,
                                                     offset=0))
    assert e["data"]["left_seconds"] == 90000.0
    e = full("health", FirebaseGrowthData(mode="growth", start=T0, offset=0, weight=0.25, weightUnits="kg"))
    assert e["data"] == {"weight_kg": 0.25}
    # Strict: most likely typing errors.
    with pytest.raises(Skip, match="amount_ml"):
        full("feed", FirebaseBottleFeedIntervalData(mode="bottle", start=T0, bottleType="Formula", amount=900,
                                                     units="ml", offset=0))
    with pytest.raises(Skip, match="celsius"):
        full("health", FirebaseTemperatureData(mode="temperature", start=T0, offset=0, amount=60, units="C"))
    with pytest.raises(Skip, match="future"):
        full("activities", FirebaseActivityIntervalData(mode="bath", start=NOW.timestamp() + 3600, offset=0))
    with pytest.raises(Skip, match="after started_at"):
        full("sleep", FirebaseSleepIntervalData(start=T0, duration=-60, offset=0))


def test_child():
    doc = FirebaseChildDocument(childsName=" Mia ", birthdate="2026-05-10", gender="F", nightStart="19:30",
                                morningCutoff=420)
    assert map_child(doc, "nick", BNE) == {"name": "Mia", "birthdate": date(2026, 5, 10), "sex": "F",
                                           "night_start": "19:30", "morning_cutoff": None}
    # Number birthdate: 2025-01-15 00:00 Brisbane = 2025-01-14 14:00 UTC.
    doc = FirebaseChildDocument(birthdate=1736863200, gender="", nightStart="7:05")
    assert map_child(doc, "Leo", BNE) == {"name": "Leo", "birthdate": date(2025, 1, 15), "sex": None,
                                          "night_start": "07:05", "morning_cutoff": None}
    assert map_child(FirebaseChildDocument(birthdate=1736863200000), None, BNE)["birthdate"] == date(2025, 1, 15)
    assert map_child(None, None, BNE) == {"name": "Child", "birthdate": None, "sex": None, "night_start": None,
                                          "morning_cutoff": None}
    assert map_child(FirebaseChildDocument(birthdate="not a date"), "X", BNE)["birthdate"] is None
