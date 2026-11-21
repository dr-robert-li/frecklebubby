"""Pydantic request/response models and entry data models."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# --- entry data (values match Huckleberry so that migration loses nothing) ------------------------

EntryType = Literal[
    "sleep", "nursing", "bottle", "solids", "nappy", "potty", "pump",
    "growth", "temperature", "medicine", "activity", "milestone", "note", "cry", "confined",
]
TimerType = Literal["sleep", "nursing", "pump", "activity", "confined"]
TimerAction = Literal["start", "pause", "resume", "switch", "cancel", "complete"]

SleepCondition = Literal["happy", "upset", "under_10_minutes", "10-20_minutes", "longTimeToFallAsleep", "wokeUpChild"]
SleepLocation = Literal[
    "onOwnInBed", "nursing", "wornOrHeld", "nextToCarer", "coSleep", "bottle", "stroller", "car", "swing"
]
Side = Literal["left", "right"]
MilkType = Literal["Breast Milk", "Formula", "Tube Feeding", "Cow Milk", "Goat Milk", "Soy Milk", "Other"]
Reaction = Literal["LOVED", "MEH", "HATED", "ALLERGIC"]
NappyMode = Literal["pee", "poo", "both", "dry"]
Amount = Literal["little", "medium", "big"]
PooColor = Literal["yellow", "brown", "black", "green", "red", "gray"]
PooConsistency = Literal["solid", "loose", "runny", "mucousy", "hard", "pebbles", "diarrhea"]
PottyResult = Literal["satButDry", "wentPotty", "accident"]
MedicineUnit = Literal["ml", "oz", "tsp", "drops", "mg"]
ActivityKind = Literal[
    "bath", "tummyTime", "storyTime", "screenTime", "skinToSkin", "outdoorPlay", "indoorPlay", "brushTeeth"
]
ConfinedDevice = Literal["car_seat", "bouncer", "swing", "pram", "carrier", "high_chair", "other"]
RashSeverity = Literal["mild", "moderate", "severe"]
PeeColor = Literal["pale", "yellow", "dark_yellow", "orange_pink", "red"]
PeeLook = Literal["clear", "cloudy"]

Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
HHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
]


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SleepData(_Data):
    start_conditions: list[SleepCondition] = []
    end_conditions: list[SleepCondition] = []
    locations: list[SleepLocation] = []


class NursingData(_Data):
    left_seconds: float | None = Field(None, ge=0, le=86400)
    right_seconds: float | None = Field(None, ge=0, le=86400)
    last_side: Side | None = None


class BottleData(_Data):
    milk_type: MilkType | None = None
    amount_ml: float = Field(ge=0, le=500)


class Food(_Data):
    name: Text100
    amount: str | None = Field(None, max_length=100)


class SolidsData(_Data):
    foods: list[Food] = Field(min_length=1)
    reaction: Reaction | None = None


class NappyData(_Data):
    mode: NappyMode
    pee_amount: Amount | None = None
    poo_amount: Amount | None = None
    color: PooColor | None = None
    consistency: PooConsistency | None = None
    rash: bool = False
    air_minutes: int | None = Field(None, ge=0, le=240, description="Time with the nappy off")
    rash_severity: RashSeverity | None = None
    pee_color: PeeColor | None = None
    pee_look: PeeLook | None = None
    pee_smell: bool | None = Field(None, description="Strong smell")

    @model_validator(mode="after")
    def _details(self):
        if self.rash_severity:
            self.rash = True
        if self.mode not in ("pee", "both") and (self.pee_color or self.pee_look or self.pee_smell):
            raise ValueError("pee_color, pee_look and pee_smell: only for a wet nappy (mode pee or both)")
        return self


class PottyData(NappyData):
    result: PottyResult


class PumpData(_Data):
    left_ml: float | None = Field(None, ge=0, le=1000)
    right_ml: float | None = Field(None, ge=0, le=1000)
    total_ml: float | None = Field(None, ge=0, le=2000)

    @model_validator(mode="after")
    def _total(self):
        if self.total_ml is None and (self.left_ml is not None or self.right_ml is not None):
            self.total_ml = (self.left_ml or 0) + (self.right_ml or 0)
        return self


class GrowthData(_Data):
    weight_kg: float | None = Field(None, ge=0.3, le=60)
    height_cm: float | None = Field(None, ge=20, le=150)
    head_cm: float | None = Field(None, ge=15, le=65)

    @model_validator(mode="after")
    def _one(self):
        if self.weight_kg is None and self.height_cm is None and self.head_cm is None:
            raise ValueError("give weight_kg, height_cm or head_cm")
        return self


class TemperatureData(_Data):
    celsius: float = Field(ge=30, le=45)


class MedicineData(_Data):
    name: Text100
    amount: float | None = Field(None, ge=0)
    unit: MedicineUnit | None = None


class ActivityData(_Data):
    kind: ActivityKind


class MilestoneData(_Data):
    key: str | None = None
    title: Text100


class CryData(_Data):
    """A crying episode. The sound fields come from the experimental cry helper; all fields are optional."""

    sound_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    sound_confidence: float | None = Field(None, ge=0, le=1)
    likely_needs: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]] | None = (
        Field(None, max_length=12))
    soothed_by: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None


class ConfinedData(_Data):
    device: ConfinedDevice


DATA_MODELS: dict[str, type[_Data]] = {
    "sleep": SleepData, "nursing": NursingData, "bottle": BottleData, "solids": SolidsData,
    "nappy": NappyData, "potty": PottyData, "pump": PumpData, "growth": GrowthData,
    "temperature": TemperatureData, "medicine": MedicineData, "activity": ActivityData,
    "milestone": MilestoneData, "note": _Data, "cry": CryData, "confined": ConfinedData,
}
END_REQUIRED = {"sleep"}
END_OPTIONAL = {"nursing", "pump", "activity", "cry", "confined"}

# --- users, families, children --------------------------------------------------------------------


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(Out):
    id: int
    email: str
    name: str


class FamilyIn(BaseModel):
    name: Text100
    timezone: str


class FamilyPatch(BaseModel):
    name: Text100 | None = None
    timezone: str | None = None


class FamilyOut(Out):
    id: int
    name: str
    timezone: str
    created_at: datetime


class ChildIn(BaseModel):
    name: Text100
    birthdate: date
    due_date: date | None = Field(None, description="Due date of a baby born early: development uses the corrected "
                                                    "age until 2 years.")
    sex: Literal["F", "M"] | None = None
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")] = "#B9A8E8"
    night_start: HHMM = "19:00"
    morning_cutoff: HHMM = "07:00"


class ChildPatch(BaseModel):
    name: Text100 | None = None
    birthdate: date | None = None
    due_date: date | None = None  # null clears it
    sex: Literal["F", "M"] | None = None
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    night_start: HHMM | None = None
    morning_cutoff: HHMM | None = None
    archived: bool | None = None


class ChildOut(Out):
    id: int
    name: str
    birthdate: date
    due_date: date | None = None
    sex: str | None
    color: str
    night_start: str
    morning_cutoff: str
    archived: bool
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    family: FamilyOut | None
    role: Literal["owner", "carer"] | None
    children: list[ChildOut]
    operator: bool = False


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str
    role: str


class ConfirmIn(BaseModel):
    confirm: str = Field(max_length=254, description="The family name (delete family), your email (delete account) or the child's name (delete child).")


class InviteIn(BaseModel):
    email: Email


class InviteOut(Out):
    id: int
    email: str
    created_at: datetime


class ServerInviteOut(InviteOut):
    used_at: datetime | None


class ServerFamilyOut(BaseModel):
    name: str
    members: list[str]
    created_at: datetime
    last_activity: datetime


# --- family settings ------------------------------------------------------------------------------


class Units(BaseModel):
    volume: Literal["ml", "oz"] = "ml"
    weight: Literal["kg", "lb"] = "kg"
    length: Literal["cm", "in"] = "cm"
    temperature: Literal["C", "F"] = "C"


class UnitsPatch(BaseModel):
    volume: Literal["ml", "oz"] | None = None
    weight: Literal["kg", "lb"] | None = None
    length: Literal["cm", "in"] | None = None
    temperature: Literal["C", "F"] | None = None


HttpUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^https?://\S+$")]


class LlmPatch(BaseModel):
    base_url: HttpUrl | None = None
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    api_key: Annotated[str, StringConstraints(max_length=500)] | None = None  # write-only; null or "" clears


class LlmOut(BaseModel):
    base_url: str
    model: str
    has_api_key: bool


class SettingsOut(BaseModel):
    units: Units
    wording: Literal["nappy", "diaper"]
    llm: LlmOut
    web_lookup: bool
    web_lookup_sites: list[str] = []  # the approved websites (fixed by the server, read only)
    milestone_alerts: bool = True  # M13: a notification when a child reaches a new milestone band


class SettingsPatch(BaseModel):
    units: UnitsPatch | None = None
    wording: Literal["nappy", "diaper"] | None = None
    llm: LlmPatch | None = None
    web_lookup: bool | None = None
    milestone_alerts: bool | None = None


# --- entries and timers ---------------------------------------------------------------------------


class EntryIn(BaseModel):
    type: EntryType
    started_at: datetime = Field(description="ISO 8601. No offset = family time zone.")
    ended_at: datetime | None = None
    data: dict[str, Any] = {}
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class EntryPatch(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None
    data: dict[str, Any] | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class EntryOut(Out):
    id: int
    child_id: int
    type: str
    started_at: datetime
    ended_at: datetime | None
    data: dict[str, Any]
    notes: str | None
    source: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class TimerBody(BaseModel):
    at: datetime | None = Field(None, description="start: start time; complete: end time. No offset = family time zone.")
    side: Side | None = None
    kind: ActivityKind | None = Field(None, description="activity timer only: which activity. Several kinds can "
                                                       "run at once; omit it when only one activity timer runs.")
    device: ConfinedDevice | None = Field(None, description="confined timer only (start)")
    data: dict[str, Any] | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class TimerOut(Out):
    type: str
    started_at: datetime
    paused_at: datetime | None
    paused_seconds: int
    data: dict[str, Any]
    elapsed_seconds: int = Field(description="Running time without pauses, at the time of the response.")


class TimerResult(BaseModel):
    timer: TimerOut | None = Field(description="The timer after the action; null after cancel or complete.")
    entry: EntryOut | None = Field(description="The new entry after complete.")


# --- reports, prediction, status ------------------------------------------------------------------


class Prediction(BaseModel):
    start: datetime
    end: datetime
    kind: Literal["nap", "bedtime"]
    basis: Literal["personal", "age"] = Field(description="personal = median of recent wake windows; age = age default")
    wake_window_minutes: int
    samples: int
    age_range_minutes: tuple[int, int]
    note: str
    # Optional (M7). Absent without a sleep norms file, except `method`.
    earliest: datetime | None = Field(None, description="Start of the 80 % interval for the start of the sleep")
    latest: datetime | None = Field(None, description="End of the 80 % interval for the start of the sleep")
    nap_index: int | None = Field(None, description="Which nap of the day (1 = first); null for bedtime")
    method: str | None = Field(None, description="personal_blend | age_norm | wake_window_table")
    confidence: str | None = Field(None, description="low | medium | high, from the number of recent samples")
    duration_minutes: int | None = Field(None, description="Expected length of this sleep")
    history_days: int | None = Field(None, description="Complete logged days used")


class Citation(BaseModel):
    title: str
    publisher: str
    url: str
    year: int | None = None


class SleepRecommendation(BaseModel):
    min_hours: float
    max_hours: float
    citation: Citation


class SleepDay(BaseModel):
    total_seconds: int = 0
    night_seconds: int = 0
    nap_seconds: int = 0
    count: int = 0
    nap_count: int = 0


class FeedDay(BaseModel):
    count: int = 0
    bottle_ml: float = 0
    nursing_seconds: int = 0
    solids_count: int = 0


class NappyDay(BaseModel):
    wet: int = 0
    dirty: int = 0
    air_minutes: int = 0
    rash: int = Field(0, description="Nappies with a rash")


class ActivityDay(BaseModel):
    count: int = 0
    seconds: int = 0


class CryDay(BaseModel):
    count: int = 0
    seconds: int = 0


class PlayDay(BaseModel):
    count: int = Field(0, description="Periods of play: activity entries of kind tummyTime, indoorPlay or outdoorPlay, "
                                      "with overlapping entries joined")
    seconds: int = Field(0, description="Time of these periods (parallel timers count once)")
    tummy_seconds: int = Field(0, description="Time of activity entries of kind tummyTime")


class ConfinedDay(BaseModel):
    count: int = 0
    seconds: int = 0
    longest_seconds: int = Field(0, description="Longest continuous period (gaps of 10 min or less joined)")


class DayReport(BaseModel):
    date: date
    sleep: SleepDay = SleepDay()
    feeds: FeedDay = FeedDay()
    nappies: NappyDay = NappyDay()
    pump_ml: float = 0
    medicine_count: int = 0
    bath_count: int = Field(0, description="Activity entries of kind bath")
    activities: dict[str, ActivityDay] = {}
    crying: CryDay = CryDay()
    play: PlayDay = PlayDay()
    confined: ConfinedDay = ConfinedDay()


class TummyRecommendation(BaseModel):
    minutes: int
    text: str
    citation: Citation


class DailyReport(BaseModel):
    timezone: str
    sleep_recommendations: list[SleepRecommendation]
    tummy_recommendation: TummyRecommendation | None = Field(
        None, description="Daily tummy time for babies under 12 months, with source; null from 12 months")
    days: list[DayReport]


class ConfinedLevel(BaseModel):
    after_seconds: int = Field(description="Show from this continuous time")
    title: str
    text: str
    citations: list[dict[str, Any]]


class ConfinedNow(BaseModel):
    since: datetime = Field(description="Start of the continuous confined period")
    device: str
    seconds: int = Field(description="Continuous seconds at response time")
    note: ConfinedLevel | None = Field(description="null when the child is 5 years or older")
    warning: ConfinedLevel | None = Field(description="null when the child is 12 months or older")


class Status(BaseModel):
    now: datetime
    timers: list[TimerOut]
    last: dict[str, EntryOut]
    today: DayReport
    prediction: Prediction | None
    unread_notifications: int
    confined: ConfinedNow | None = Field(None, description="Set while a confined timer runs")


# --- growth, milestones ---------------------------------------------------------------------------


class GrowthPoint(BaseModel):
    entry_id: int
    at: datetime
    age_months: float
    weight_kg: float | None = None
    weight_percentile: float | None = None
    height_cm: float | None = None
    height_percentile: float | None = None
    head_cm: float | None = None
    head_percentile: float | None = None


class CurvePoint(BaseModel):
    age_months: int
    p3: float
    p15: float
    p50: float
    p85: float
    p97: float


class GrowthOut(BaseModel):
    sex: str | None
    points: list[GrowthPoint]
    curves: dict[str, list[CurvePoint]] = Field(description="Keys weight, height, head. Empty when sex is not set.")


class MilestoneItem(BaseModel):
    key: str
    domain: str
    text: str
    source: dict[str, str]
    achieved: bool
    achieved_at: datetime | None


class MilestoneBand(BaseModel):
    age_months: int
    items: list[MilestoneItem]


class MilestonesOut(BaseModel):
    age_months: float = Field(description="Corrected age (from the due date) until 2 years when a due date is set.")
    corrected: bool = False
    bands: list[MilestoneBand]


# --- reminders, notifications, push, tokens -------------------------------------------------------

class ReminderIn(BaseModel):
    type: Literal[
        "sleep", "nursing", "bottle", "solids", "nappy", "potty", "pump",
        "growth", "temperature", "medicine", "activity", "milestone", "note", "confined",
        "sleep_alert",
    ]
    mode: Literal["in", "at"]
    interval_minutes: int | None = Field(None, ge=1, le=10080)
    times: list[HHMM] = []
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field([], description="0 = Monday. Empty = every day.")
    daytime_only: bool = False
    enabled: bool = True


class ReminderPatch(BaseModel):
    interval_minutes: int | None = Field(None, ge=1, le=10080)
    times: list[HHMM] | None = None
    days: list[Annotated[int, Field(ge=0, le=6)]] | None = None
    daytime_only: bool | None = None
    enabled: bool | None = None


class ReminderOut(Out):
    id: int
    child_id: int
    type: str
    mode: str
    interval_minutes: int | None
    times: list[str]
    days: list[int]
    daytime_only: bool
    enabled: bool


class NotificationOut(Out):
    id: int
    child_id: int | None
    kind: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class PushKeys(BaseModel):
    p256dh: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    auth: Annotated[str, StringConstraints(min_length=1, max_length=100)]


class PushSubscriptionIn(BaseModel):
    """The JSON of a browser PushSubscription."""

    endpoint: Annotated[str, StringConstraints(max_length=1000, pattern=r"^https://\S+$")]
    keys: PushKeys


class PushUnsubscribe(BaseModel):
    endpoint: str


class TokenIn(BaseModel):
    name: Text100


class TokenOut(Out):
    id: int
    name: str
    last_used_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    token: str = Field(description="Shown once. Store it now.")


class ConfigOut(BaseModel):
    auth_mode: str
    invite_only: bool = False
    clerk_publishable_key: str
    vapid_public_key: str
    version: str
    voice: bool = False  # voice commands are installed on this server


class RegimeRow(BaseModel):
    time: str = Field(description="HH:MM, local time")
    end: str | None = Field(None, description="End of a nap, HH:MM")
    kind: Literal["wake", "nap", "bedtime", "night_feed", "night_wake"]
    label: str
    part: Literal["day", "night"]
    basis: Literal["own", "mixed", "age"] = Field(description="own = the child's logs; age = typical for the age; mixed = both")
    earliest: str | None = Field(None, description="The child's own usual range (8 in 10 days), from")
    latest: str | None = Field(None, description="The child's own usual range, to")
    note: str | None = None


class RegimeFact(BaseModel):
    key: str
    label: str
    value: str
    basis: Literal["own", "mixed", "age"]
    samples: int
    usual: str | None = Field(None, description="The child's own usual range")
    common: str | None = Field(None, description="The range that is common for the age. Not a target.")
    outside: bool = Field(description="The child's own value is outside the common range")


class RegimeNote(BaseModel):
    text: str
    cites: list[int]


class RegimeSource(Citation):
    n: int
    kind: Literal["link"] = "link"
    publisher: str | None = None
    url: str | None = None


class RegimeOut(BaseModel):
    """The day and night plan: one typical 24 hours, calculated from the child's last 14 days and the age."""
    age_band: str
    basis: Literal["own", "mixed", "age"]
    own_days: int
    own_nights: int
    days: int
    naps: int
    schedule: list[RegimeRow]
    facts: list[RegimeFact]
    notes: list[RegimeNote]
    sources: list[RegimeSource]
