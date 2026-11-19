"""A built-in fake Huckleberry account: two children, 60 rows over all trackers.

Used by tests and by the e2e test of the import screen (`HUCKLEBERRY_FAKE=1`, only with `AUTH_MODE=dev`).
The rows are the fork's own Pydantic models, so their shapes are true. Password `wrong-password` fails sign-in.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from huckleberry_api.firebase_types import (
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
    FirebaseUserChildRef,
    FirebaseUserDocument,
    SolidsFoodEntry,
)
from huckleberry_api.models import HistoryEntry

from .huckleberry import SignInFailed

WRONG_PASSWORD = "wrong-password"
# Fixed for the life of the process, so a second import sees the same rows.
NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
OFFSET = -600  # minutes, Australia/Brisbane as the app stores it

USER = FirebaseUserDocument(childList=[FirebaseUserChildRef(cid="fake-mia", nickname="Mia"),
                                       FirebaseUserChildRef(cid="fake-leo", nickname="Leo")])
CHILDREN = {
    "fake-mia": FirebaseChildDocument(childsName="Mia", birthdate="2026-05-10", gender="F", nightStart="19:30",
                                      morningCutoff="06:30"),
    # Number birthdate: 2025-01-15 00:00 in Brisbane.
    "fake-leo": FirebaseChildDocument(childsName="Leo", birthdate=1736863200, gender="M"),
}


def _t(hours_ago: float) -> float:
    return (NOW - timedelta(hours=hours_ago)).timestamp()


def _rows(cid: str, older: bool) -> dict[str, list[HistoryEntry]]:
    rows: dict[str, list[HistoryEntry]] = {t: [] for t in ("sleep", "feed", "diaper", "health", "pump", "activities")}

    def add(tracker: str, key: str, data) -> None:
        rows[tracker].append(HistoryEntry(id=f"{cid}-{key}", tracker=tracker, data=data))

    for day in range(3):
        h = 24 * day
        add("sleep", f"night{day}", FirebaseSleepIntervalData(
            start=_t(h + 14), duration=10 * 3600, offset=OFFSET,
            details=FirebaseSleepDetails(startSleepCondition=FirebaseSleepCondition(happy=True),
                                         sleepLocations=FirebaseSleepLocations(onOwnInBed=True),
                                         endSleepCondition=FirebaseSleepCondition(wokeUpChild=True))))
        add("sleep", f"nap{day}", FirebaseSleepIntervalData(
            start=_t(h + 3), duration=5400, offset=OFFSET,
            details=FirebaseSleepDetails(startSleepCondition=FirebaseSleepCondition(**{"10-20_minutes": True}),
                                         sleepLocations=FirebaseSleepLocations(stroller=True), notes="Long walk")))
        for n, side in enumerate(("left", "right")):
            add("feed", f"breast{day}{n}", FirebaseBreastFeedIntervalData(
                mode="breast", start=_t(h + 6 + 4 * n), lastSide=side, leftDuration=600 + 60 * n,
                rightDuration=480, offset=OFFSET))
        bottles = [dict(amount=120.0, units="ml"), dict(amount=4.0, units="oz"), dict(units="ml")]
        add("feed", f"bottle{day}", FirebaseBottleFeedIntervalData(
            mode="bottle", start=_t(h + 8), bottleType="Formula" if day else "Breast Milk", offset=OFFSET,
            **bottles[day]))
        add("diaper", f"wet{day}", FirebaseDiaperData(
            mode="pee", start=_t(h + 5), offset=OFFSET, quantity=FirebaseDiaperQuantity(pee=50.0)))
        if older and day == 0:
            add("diaper", "potty0", FirebaseDiaperData(mode="both", start=_t(h + 1), offset=OFFSET, isPotty=True,
                                                       howItHappened="wentPotty"))
        else:
            add("diaper", f"dirty{day}", FirebaseDiaperData(
                mode="both", start=_t(h + 9), offset=OFFSET, quantity=FirebaseDiaperQuantity(pee=0.0, poo=100.0),
                color="yellow", consistency="runny", diaperRash=day == 1))
        add("activities", f"act{day}", FirebaseActivityIntervalData(
            mode=("bath", "tummyTime", "storyTime")[day], start=_t(h + 2), duration=900, offset=OFFSET))
        if older:
            add("feed", f"solids{day}", FirebaseSolidsFeedIntervalData(
                mode="solids", start=_t(h + 7), offset=OFFSET,
                foods={"banana": SolidsFoodEntry(id="banana", created_name="Banana", source="curated", amount=2),
                       "oat": SolidsFoodEntry(id="oat", created_name="Oats", source="custom", amount="half bowl")},
                reactions={"LOVED": True} if day else {"LOVED": True, "ALLERGIC": True}))
        else:
            add("pump", f"pump{day}", FirebasePumpIntervalData(
                start=_t(h + 4), offset=OFFSET, duration=900, units="ml",
                **(dict(entryMode="leftright", leftAmount=60.0, rightAmount=50.0) if day != 1
                   else dict(entryMode="total", leftAmount=45.0, rightAmount=45.0))))

    if older:
        add("health", "growth", FirebaseGrowthData(mode="growth", start=_t(30), offset=OFFSET, weight=24.25,
                                                   weightUnits="lbs.oz", height=2.75, heightUnits="ft.in",
                                                   head=18.5, headUnits="hin"))
        add("health", "temp", FirebaseTemperatureData(mode="temperature", start=_t(20), offset=OFFSET, amount=100.4,
                                                      units="F"))
    else:
        add("health", "growth", FirebaseGrowthData(mode="growth", start=_t(30), offset=OFFSET, weight=7.2,
                                                   weightUnits="kg", height=66.0, heightUnits="cm", head=42.5,
                                                   headUnits="hcm"))
        add("health", "temp", FirebaseTemperatureData(mode="temperature", start=_t(20), offset=OFFSET, amount=37.2,
                                                      units="C"))
    add("health", "med", FirebaseMedicationData(mode="medication", start=_t(19), offset=OFFSET, medication_id="m1",
                                                medication_name="Paracetamol", amount=2.5, units="ml", notes=""))
    return rows


ROWS = {"fake-mia": _rows("fake-mia", older=False), "fake-leo": _rows("fake-leo", older=True)}


class FakeHuckleberry:
    """Answers like HuckleberryAPI. `rows` is {child_uid: {tracker: [HistoryEntry]}}."""

    def __init__(self, rows: dict | None = None) -> None:
        self.rows = rows if rows is not None else ROWS

    async def get_user(self) -> FirebaseUserDocument:
        return USER

    async def get_child(self, child_uid: str) -> FirebaseChildDocument | None:
        return CHILDREN.get(child_uid)

    async def list_entries(self, child_uid: str, tracker: str, start_time: datetime, end_time: datetime) -> list:
        return [e for e in self.rows.get(child_uid, {}).get(tracker, [])
                if start_time.timestamp() <= e.data.start < end_time.timestamp()]


@asynccontextmanager
async def fake_client(email: str, password: str, timezone: str) -> AsyncIterator[FakeHuckleberry]:
    if password == WRONG_PASSWORD:
        raise SignInFailed
    yield FakeHuckleberry()
