"""Migration from Huckleberry (optional extra `import`, spec section 13).

The mapping functions are pure: they take the rows of the fork's Pydantic models (`huckleberry_api.firebase_types`)
and return Frecklebubby fields in canonical units. The runner reads the account in a background task and upserts
by `external_id`. The password lives only in the memory of that task: it is not stored, logged or put in the job.
"""

import asyncio
import copy
import logging
import math
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, utcnow
from ..models import Child, Entry, ImportJob
from ..schemas import DATA_MODELS
from ..services import Conflict, Ctx, Invalid, NotFound, ServiceError, zone
from ..services.entries import validate

log = logging.getLogger(__name__)

OZ_ML = 29.5735295625  # US fluid ounce
LB_KG = 0.45359237
FT_CM = 30.48
IN_CM = 2.54
MS_EPOCH = 100_000_000_000  # same threshold as the fork's _MS_EPOCH_THRESHOLD: larger values are milliseconds
# The fork's diaper writer: "App uses: 0.0 = little, 50.0 = medium, 100.0 = big. Other values are no quantity."
QUANTITY = {0: "little", 50: "medium", 100: "big"}
TRACKERS = ("sleep", "feed", "diaper", "health", "pump", "activities")
LABELS = {"sleep": "sleep", "feed": "feeds", "diaper": "nappies", "health": "health", "pump": "pumping",
          "activities": "activities"}
# shortcut: fixed 30-day windows; a row the fork cannot read loses its whole window (named in skipped_reasons).
WINDOW = timedelta(days=30)
MAX_REASONS = 20
# Ranges that real history can pass: a nursing timer left on, a very small preterm baby. Rows that pass only these
# limits are imported as they are. Other out-of-range values (bottle, pump, temperature) are most likely typing
# errors and are skipped with a reason.
LENIENT = {"nursing": {"left_seconds", "right_seconds"}, "growth": {"weight_kg", "height_cm", "head_cm"}}
SIGN_IN_FAILED = "Huckleberry sign-in failed. Check the email and password."
NOT_INSTALLED = ("The Huckleberry import is not installed on this server. "
                 "Install it with: uv sync --extra import. Then start the server again.")


class Skip(Exception):
    """A row that cannot become an entry. The message is the reason."""


class SignInFailed(Exception):
    """Wrong email or password. Has no text, so it cannot carry the password."""


class Stop(Exception):
    """Stops the job with a plain message for the user."""


class NotInstalled(ServiceError):
    status = 501


class Client(Protocol):
    """The part of `huckleberry_api.HuckleberryAPI` the import uses."""

    async def get_user(self) -> Any: ...
    async def get_child(self, child_uid: str) -> Any: ...
    async def list_entries(self, child_uid: str, tracker: str, start_time: datetime, end_time: datetime) -> list: ...


# (email, password, timezone) -> async context that yields a signed-in Client or raises SignInFailed.
Factory = Callable[[str, str, str], AbstractAsyncContextManager[Client]]
client_factory: Factory | None = None  # tests set this
_RUNNING: dict[int, asyncio.Task] = {}


# --- pure mapping -----------------------------------------------------------------------------------


def _ts(value: float) -> datetime:
    v = float(value)
    if not math.isfinite(v):
        raise Skip("the time is not a number")
    if v > MS_EPOCH:
        v /= 1000
    return datetime.fromtimestamp(v, UTC).replace(microsecond=0)


def _after(start: datetime, seconds: float | None) -> datetime | None:
    return None if seconds is None else start + timedelta(seconds=round(float(seconds)))


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _join(*parts: str | None) -> str | None:
    return " ".join(p for p in parts if p) or None


def _flags(model: Any) -> list[str]:
    return [k for k, v in model.model_dump(by_alias=True).items() if v] if model is not None else []


def _ml(value: float | None, units: str | None) -> float | None:
    return None if value is None else round(float(value) * (OZ_ML if units == "oz" else 1), 1)


def _qty(value: float | None) -> str | None:
    return None if value is None else QUANTITY.get(float(value))


def weight_kg(value: float | None, units: str | None) -> float | None:
    """`lbs.oz` values are decimal pounds (live app: 14.125 = 14 lb 2 oz). No unit = kg."""
    if value is None:
        return None
    return round(float(value) * (LB_KG if units == "lbs.oz" else 1), 3)


def height_cm(value: float | None, units: str | None) -> float | None:
    """`ft.in` values are decimal feet (live app: 5.3333 = 5 ft 4 in). No unit = cm."""
    if value is None:
        return None
    v = float(value)
    if units == "ft.in":
        # The fork's own log_growth writes inches under "ft.in"; no child is 8 feet tall, so a larger value is inches.
        v *= FT_CM if v <= 8 else IN_CM
    return round(v, 2)


def head_cm(value: float | None, units: str | None) -> float | None:
    """`hin` = inches, `hcm` (or no unit) = cm."""
    if value is None:
        return None
    return round(float(value) * (IN_CM if units == "hin" else 1), 2)


def celsius(value: float, units: str) -> float:
    v = float(value)
    return round((v - 32) * 5 / 9 if units == "F" else v, 2)


def _hhmm(value: Any) -> str | None:
    # shortcut: numeric nightStart/morningCutoff have no documented unit, so they are not imported.
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(:\d{2})?", value.strip()) if isinstance(value, str) else None
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        return None
    return f"{int(m[1]):02}:{m[2]}"


def _birthdate(value: Any, tz: ZoneInfo) -> date | None:
    try:
        if isinstance(value, str):
            return date.fromisoformat(value.strip()[:10])
        if isinstance(value, int | float):
            return _ts(value).astimezone(tz).date()
    except (ValueError, OverflowError, OSError, Skip):
        pass
    return None


def map_child(doc: Any, nickname: str | None, tz: ZoneInfo) -> dict[str, Any]:
    """FirebaseChildDocument (or None) → child fields. `birthdate` is None when Huckleberry has no usable one."""
    name = (getattr(doc, "childsName", None) or nickname or "").strip()[:100] or "Child"
    birth = _birthdate(getattr(doc, "birthdate", None), tz)
    gender = getattr(doc, "gender", None)
    return {"name": name, "birthdate": min(birth, date.today()) if birth else None,
            "sex": gender if gender in ("F", "M") else None,
            "night_start": _hhmm(getattr(doc, "nightStart", None)),
            "morning_cutoff": _hhmm(getattr(doc, "morningCutoff", None))}


def _entry(type_: str, start: datetime, end: datetime | None, data: dict, notes: str | None) -> dict[str, Any]:
    return {"type": type_, "started_at": start, "ended_at": end,
            "data": {k: v for k, v in data.items() if v is not None}, "notes": notes}


def map_row(tracker: str, row: Any) -> dict[str, Any]:
    """One history row (a fork model) → {type, started_at, ended_at, data, notes}. Raises Skip."""
    start = _ts(row.start)
    notes = _text(getattr(row, "notes", None))
    mode = getattr(row, "mode", None)

    if tracker == "sleep":
        d = row.details
        data = {"start_conditions": _flags(d and d.startSleepCondition),
                "end_conditions": _flags(d and d.endSleepCondition), "locations": _flags(d and d.sleepLocations)}
        return _entry("sleep", start, _after(start, row.duration), data, _text(d and d.notes))

    if tracker == "feed" and mode == "breast":
        left, right = row.leftDuration, row.rightDuration
        data = {"left_seconds": None if left is None else float(left),
                "right_seconds": None if right is None else float(right),
                "last_side": row.lastSide if row.lastSide in ("left", "right") else None}
        return _entry("nursing", start, _after(start, (left or 0) + (right or 0)), data, notes)

    if tracker == "feed" and mode == "bottle":
        if row.amount is None:
            # Frecklebubby needs an amount; 0 ml keeps the feed in the count without adding volume.
            return _entry("bottle", start, None, {"milk_type": row.bottleType, "amount_ml": 0.0},
                          _join(notes, "No amount in Huckleberry."))
        return _entry("bottle", start, None, {"milk_type": row.bottleType, "amount_ml": _ml(row.amount, row.units)},
                      notes)

    if tracker == "feed" and mode == "solids":
        foods = []
        for f in (row.foods or {}).values():
            amount = f.amount if isinstance(f.amount, str) or f.amount is None else f"{f.amount:g}"
            foods.append({"name": (f.created_name.strip() or f.id)[:100], "amount": _text(amount)})
        foods = [{k: v for k, v in f.items() if v is not None} for f in foods]
        reactions = [k for k, v in (row.reactions or {}).items() if v]
        reaction = "ALLERGIC" if "ALLERGIC" in reactions else (reactions[0] if reactions else None)
        if len(reactions) > 1:
            notes = _join(notes, f"Reactions in Huckleberry: {', '.join(reactions)}.")
        if not foods:
            raise Skip("solids with no food")
        return _entry("solids", start, None, {"foods": foods, "reaction": reaction}, notes)

    if tracker == "diaper":
        q = row.quantity
        data = {"mode": row.mode, "pee_amount": _qty(q and q.pee), "poo_amount": _qty(q and q.poo),
                "color": row.color, "consistency": row.consistency, "rash": bool(row.diaperRash)}
        if not row.isPotty:
            return _entry("nappy", start, None, data, notes)
        # Huckleberry can save a potty event without howItHappened; Frecklebubby needs a result.
        data["result"] = row.howItHappened or ("satButDry" if row.mode == "dry" else "wentPotty")
        return _entry("potty", start, None, data, notes)

    if tracker == "health" and mode == "growth":
        data = {"weight_kg": weight_kg(row.weight, row.weightUnits), "height_cm": height_cm(row.height, row.heightUnits),
                "head_cm": head_cm(row.head, row.headUnits)}
        return _entry("growth", start, None, data, notes)

    if tracker == "health" and mode == "medication":
        amount = float(row.amount) or None  # the app stores a blank amount as 0.0
        data = {"name": row.medication_name.strip()[:100], "amount": amount, "unit": row.units if amount else None}
        return _entry("medicine", start, None, data, notes)

    if tracker == "health" and mode == "temperature":
        return _entry("temperature", start, None, {"celsius": celsius(row.amount, row.units)}, notes)

    if tracker == "pump":
        left, right = row.leftAmount, row.rightAmount
        if row.entryMode == "total":
            # The app stores half of a total in each side field; the sides are not real.
            both = None if left is None and right is None else (left or 0) + (right or 0)
            data = {"total_ml": _ml(both, row.units)}
        else:
            data = {"left_ml": _ml(left, row.units), "right_ml": _ml(right, row.units)}
        return _entry("pump", start, _after(start, row.duration), data, notes)

    if tracker == "activities" and row.mode == "bath":
        return _entry("bath", start, None, {}, notes)  # a bath has no end time in Frecklebubby
    if tracker == "activities":
        return _entry("activity", start, _after(start, row.duration), {"kind": row.mode}, notes)

    raise Skip(f"unknown {tracker} row")


def check(entry: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Frecklebubby validation with the LENIENT ranges. Returns the data to store. Raises Skip."""
    try:
        return validate(entry["type"], entry["started_at"], entry["ended_at"], entry["data"], entry["notes"], now)
    except Invalid as err:
        if str(err).startswith("data."):
            try:
                DATA_MODELS[entry["type"]].model_validate(entry["data"])
            except ValidationError as verr:
                lenient = LENIENT.get(entry["type"], set())
                if all(e["loc"][0] in lenient and e["type"] in ("less_than_equal", "greater_than_equal")
                       for e in verr.errors()):
                    return entry["data"]
        raise Skip(str(err)) from None


# --- clients ----------------------------------------------------------------------------------------


@asynccontextmanager
async def real_client(email: str, password: str, timezone: str) -> AsyncIterator[Client]:
    import aiohttp
    from huckleberry_api import HuckleberryAPI

    async with aiohttp.ClientSession() as web:
        api = HuckleberryAPI(email=email, password=password, timezone=timezone, websession=web)
        try:
            await api.authenticate()
        except aiohttp.ClientResponseError as err:
            if err.status in (400, 401, 403):
                raise SignInFailed from None
            raise
        yield api


def _factory() -> Factory:
    if client_factory is not None:
        return client_factory
    try:
        if os.environ.get("HUCKLEBERRY_FAKE") == "1" and get_settings().auth_mode == "dev":
            from .fake import fake_client

            return fake_client
        import huckleberry_api  # noqa: F401
    except ImportError as err:
        raise NotInstalled(NOT_INSTALLED) from err
    return real_client


# --- jobs -------------------------------------------------------------------------------------------


def _recover(s: Session) -> None:
    """A pending or running job with no task in this process was cut off by a restart: mark it failed."""
    live = [i for i, t in _RUNNING.items() if not t.done()]
    for job in s.scalars(select(ImportJob).where(ImportJob.status.in_(("pending", "running")),
                                                ImportJob.id.not_in(live))):
        job.status, job.error, job.finished_at = "failed", "The server stopped during the import. Start it again.", utcnow()
    s.commit()


def start_job(s: Session, ctx: Ctx, email: str, password: str, timezone: str) -> ImportJob:
    """Make a job and start its task. Call from a running event loop."""
    factory = _factory()
    zone(timezone)
    _recover(s)
    if s.scalar(select(ImportJob.id).where(ImportJob.family_id == ctx.fam.id,
                                           ImportJob.status.in_(("pending", "running")))):
        raise Conflict("An import is already running. Wait until it is done.")
    job = ImportJob(family_id=ctx.fam.id, status="pending",
                    progress={"stage": "Waiting", "children": 0, "entries": {}, "skipped": 0, "skipped_reasons": []})
    s.add(job)
    s.commit()
    _RUNNING[job.id] = asyncio.create_task(run(job.id, ctx.fam.id, ctx.user.id, email, password, timezone, factory))
    return job


def get_job(s: Session, ctx: Ctx, job_id: int) -> ImportJob:
    _recover(s)
    job = s.get(ImportJob, job_id)
    if job is None or job.family_id != ctx.fam.id:
        raise NotFound("Import not found.")
    return job


def _save(job_id: int, **fields: Any) -> None:
    with SessionLocal() as s:
        job = s.get(ImportJob, job_id)
        for key, value in fields.items():
            setattr(job, key, copy.deepcopy(value))
        s.commit()


def _upsert_child(family_id: int, cid: str, fields: dict[str, Any]) -> int:
    ext = f"hb:child:{cid}"
    with SessionLocal() as s:
        child = s.scalar(select(Child).where(Child.external_id == ext))
        if child is not None and child.family_id != family_id:
            raise Stop("A child in this Huckleberry account is already in another family. Nothing more was imported.")
        if child is None:
            child = Child(family_id=family_id, external_id=ext, birthdate=fields["birthdate"] or date.today())
            s.add(child)
        for key, value in fields.items():
            if value is not None:
                setattr(child, key, value)
        s.commit()
        return child.id


def _store(child_id: int, user_id: int, tracker: str, rows: list, now: datetime, progress: dict) -> None:
    """Upsert the rows of one tracker. Re-import writes Huckleberry values over local changes; it never deletes."""
    with SessionLocal() as s:
        for hist in rows:
            ext = f"hb:{tracker}:{hist.id}"
            try:
                e = map_row(tracker, hist.data)
                data = check(e, now)
            except (Skip, ValueError, OverflowError, OSError, TypeError, AttributeError) as err:
                _skip(progress, f"{LABELS[tracker]} {hist.id}: {err or type(err).__name__}")
                continue
            entry = s.scalar(select(Entry).where(Entry.external_id == ext))
            if entry is None:
                entry = Entry(child_id=child_id, external_id=ext, source="import", created_by=user_id)
                s.add(entry)
            elif entry.child_id != child_id:
                _skip(progress, f"{LABELS[tracker]} {hist.id}: already imported for another child")
                continue
            entry.type, entry.started_at, entry.ended_at = e["type"], e["started_at"], e["ended_at"]
            entry.data, entry.notes, entry.source = data, e["notes"], "import"
            progress["entries"][e["type"]] = progress["entries"].get(e["type"], 0) + 1
        s.commit()


def _skip(progress: dict, reason: str) -> None:
    progress["skipped"] += 1
    if len(progress["skipped_reasons"]) < MAX_REASONS:
        progress["skipped_reasons"].append(reason)


async def run(job_id: int, family_id: int, user_id: int, email: str, password: str, timezone: str,
              factory: Factory) -> None:
    progress = {"stage": "Signing in to Huckleberry", "children": 0, "entries": {}, "skipped": 0,
                "skipped_reasons": []}
    try:
        await asyncio.to_thread(_save, job_id, status="running", progress=progress)
        tz, now = zone(timezone), utcnow()
        async with factory(email, password, timezone) as hb:
            user = await hb.get_user()
            for ref in (user.childList if user else []):
                fields = map_child(await hb.get_child(ref.cid), ref.nickname, tz)
                child_id = await asyncio.to_thread(_upsert_child, family_id, ref.cid, fields)
                progress["children"] += 1
                # A year before birth also finds pumping in pregnancy; no birthdate = 5 years back.
                first = (datetime.combine(fields["birthdate"] - timedelta(days=365), time(), UTC)
                         if fields["birthdate"] else now - timedelta(days=5 * 365))
                for tracker in TRACKERS:
                    progress["stage"] = f"Reading {LABELS[tracker]} for {fields['name']}"
                    await asyncio.to_thread(_save, job_id, progress=progress)
                    rows, a = [], first
                    while a < now + timedelta(days=1):
                        b = a + WINDOW
                        try:
                            rows += await hb.list_entries(ref.cid, tracker, a, b)
                        except ValidationError:
                            _skip(progress, f"{LABELS[tracker]} from {a.date()} to {b.date()}: Huckleberry sent rows "
                                            "this version cannot read")
                        a = b
                    await asyncio.to_thread(_store, child_id, user_id, tracker, rows, now, progress)
        progress["stage"] = "Done"
        await asyncio.to_thread(_save, job_id, status="done", progress=progress, finished_at=utcnow())
    except Exception as err:
        if isinstance(err, SignInFailed):
            message = SIGN_IN_FAILED
        elif isinstance(err, Stop):
            message = str(err)
        else:
            message = "The import stopped because of an error. Try again later."
            log.error("Huckleberry import %s failed: %s: %s", job_id, type(err).__name__,
                      str(err).replace(password, "***") if password else err)
        await asyncio.to_thread(_save, job_id, status="failed", progress=progress, error=message,
                                finished_at=utcnow())
    finally:
        _RUNNING.pop(job_id, None)
