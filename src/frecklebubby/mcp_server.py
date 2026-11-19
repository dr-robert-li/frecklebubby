"""MCP server: thin tools over the service layer.

Mounted in the app at /mcp (stateless Streamable HTTP, Clerk OAuth in clerk mode). `frecklebubby-mcp --stdio`
serves local clients as one user of the database.
"""

import argparse
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.server.dependencies import get_access_token, get_http_headers
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import DEV_USER
from .config import get_settings
from .db import SessionLocal, init_db, utcnow
from .models import Child, User
from .schemas import (
    ActivityKind,
    Amount,
    EntryIn,
    EntryOut,
    EntryPatch,
    EntryType,
    Food,
    MedicineUnit,
    MilestonesOut,
    MilkType,
    NappyMode,
    PooColor,
    PooConsistency,
    PottyResult,
    Prediction,
    Reaction,
    Side,
    SleepCondition,
    SleepLocation,
    Status,
    TimerBody,
)
from .services import Ctx, ServiceError, children, entries, milestones, plain_errors, reports, sleep, timers
from .services.families import context, sign_in

log = logging.getLogger(__name__)

ChildArg = Annotated[str | None, Field(description="Child name or id. Omit when the family has one child.")]
Time = Annotated[str | None, Field(description="ISO 8601, for example 2026-11-17T14:30. No offset = family time zone. Omit = now.")]
Notes = Annotated[str | None, Field(description="Optional note.")]
Volume = Annotated[Literal["ml", "oz"], Field(description="Volume unit.")]
Conditions = Annotated[list[SleepCondition] | None, Field(description="How the child fell asleep or woke.")]
Locations = Annotated[list[SleepLocation] | None, Field(description="Where the child slept.")]

READ = {"readOnlyHint": True}
DESTRUCTIVE = {"destructiveHint": True}
OZ_ML, LB_KG, IN_CM = 29.5735, 0.45359237, 2.54


def _ml(amount: float | None, units: str) -> float | None:
    return None if amount is None else round(amount * OZ_ML if units == "oz" else amount, 1)


def _parse(value: str | None) -> datetime:
    """ISO 8601 time; naive values are local to the family (services convert them); None is now."""
    if value is None:
        return utcnow()
    try:
        return datetime.fromisoformat(value)
    except ValueError as err:
        raise ToolError(f"Time {value!r} is not valid. Use ISO 8601, for example 2026-11-17T14:30.") from err


def _entry(e, ctx: Ctx) -> dict[str, Any]:
    out = EntryOut.model_validate(e).model_dump(mode="json", exclude={"created_at", "updated_at", "created_by"})
    out["started_at"] = e.started_at.astimezone(ctx.tz).isoformat()
    out["ended_at"] = e.ended_at.astimezone(ctx.tz).isoformat() if e.ended_at else None
    return out


def create_mcp(fixed_email: str | None = None, auth: AuthProvider | None = None) -> FastMCP:
    """fixed_email: act as this user (stdio, tests). Else the user comes from the OAuth token or, in dev mode,
    from the X-Dev-User header."""

    def caller_email() -> str:
        if fixed_email:
            return fixed_email
        token = get_access_token()
        if token is not None:
            email, verified = token.claims.get("email"), token.claims.get("email_verified") is not False
            if isinstance(email, str) and verified:
                return email
            raise ToolError("Your sign-in has no verified email.")
        if get_settings().auth_mode == "dev":
            return get_http_headers().get("x-dev-user") or DEV_USER
        raise ToolError("Sign in first.")

    @contextmanager
    def call() -> Iterator[tuple[Session, Ctx]]:
        email = caller_email().strip().lower()
        allowed = get_settings().allowed
        if allowed and email not in allowed:
            raise ToolError("This email is not allowed on this server.")
        with SessionLocal() as s:
            try:
                yield s, context(s, sign_in(s, email), "mcp")
            except ServiceError as err:
                raise ToolError(str(err)) from err
            except ValidationError as err:
                raise ToolError(plain_errors(err)) from err

    def child_of(s: Session, ctx: Ctx, child: str | None) -> Child:
        return children.resolve_child(s, ctx, child)

    def log_entry(child: str | None, type_: str, start_time: str | None, data: dict, notes: str | None = None,
                  end_time: str | None = None, end_required: bool = False) -> dict[str, Any]:
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            ended = _parse(end_time) if end_time or end_required else None
            body = EntryIn(type=type_, started_at=_parse(start_time), ended_at=ended,
                           data={k: v for k, v in data.items() if v is not None}, notes=notes)
            return _entry(entries.create_entry(s, ctx, c.id, body), ctx)

    def timer(child: str | None, type_: str, action: str, start_time: str | None, end_time: str | None,
              **body: Any) -> dict[str, Any]:
        if start_time and action != "start":
            raise ToolError("start_time: use it only with start")
        if end_time and action != "complete":
            raise ToolError("end_time: use it only with complete")
        at = start_time if action == "start" else end_time
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            now = utcnow()
            t, e = timers.act(s, ctx, c.id, type_, action, TimerBody(at=_parse(at) if at else None, **body), now)
            return {"done": f"{type_} timer: {action}",
                    "timer": timers.timer_out(t, now) | {"started_at": t.started_at.astimezone(ctx.tz).isoformat()}
                    if t else None,
                    "entry": _entry(e, ctx) if e else None}

    mcp = FastMCP(
        "Frecklebubby",
        instructions=(
            "Logs and reads baby-care data in Frecklebubby. Times are ISO 8601; a time without an offset is in the "
            "family time zone; an omitted time means now. Timers (sleep, nursing, pump, activity) are live; log_* "
            "tools save events that are over. To fix or remove an entry: call list_entries, confirm the entry with "
            "the user, then call update_entry or delete_entry with its id. get_status shows running timers, the "
            "last entry of each type, today's totals and the next sleep window."
        ),
        auth=auth,
        mask_error_details=True,
    )

    # --- children and status ----------------------------------------------------------------------

    @mcp.tool(annotations=READ)
    def list_children() -> list[dict[str, Any]]:
        """List the children in the family with id, name, birthdate and sex."""
        with call() as (s, ctx):
            return [{"id": c.id, "name": c.name, "birthdate": c.birthdate.isoformat(), "sex": c.sex}
                    for c in children.list_children(s, ctx)]

    @mcp.tool(annotations=READ)
    def get_status(child: ChildArg = None) -> dict[str, Any]:
        """Show now: running timers, the last entry of each type, today's totals, the next sleep window and
        the unread notification count. Times in UTC; now_local gives the family time."""
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            out = Status.model_validate(reports.status(s, ctx, c.id)).model_dump(mode="json")
            return {"now_local": utcnow().astimezone(ctx.tz).isoformat(), "timezone": ctx.fam.timezone, **out}

    # --- sleep ------------------------------------------------------------------------------------

    @mcp.tool(annotations=DESTRUCTIVE)
    def sleep_timer(
        action: Annotated[Literal["start", "pause", "resume", "cancel", "complete"], Field(
            description="start (or move the start of a running timer), pause, resume, cancel (discard), "
                        "complete (stop and save).")],
        start_time: Annotated[str | None, Field(description="start only: when sleep started. Omit = now.")] = None,
        end_time: Annotated[str | None, Field(description="complete only: when sleep ended. Omit = now.")] = None,
        start_conditions: Conditions = None,
        end_conditions: Conditions = None,
        locations: Locations = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Control the live sleep timer ("fell asleep", "woke up"). Use log_sleep for a sleep that is over."""
        data = {k: v for k, v in {"start_conditions": start_conditions, "end_conditions": end_conditions,
                                  "locations": locations}.items() if v}
        return timer(child, "sleep", action, start_time, end_time, data=data or None, notes=notes)

    @mcp.tool
    def log_sleep(
        start_time: Annotated[str, Field(description="When sleep started, ISO 8601.")],
        end_time: Annotated[str | None, Field(description="When sleep ended, ISO 8601. Omit = now.")] = None,
        start_conditions: Conditions = None,
        end_conditions: Conditions = None,
        locations: Locations = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Save a sleep that is over. Does not touch the live timer."""
        return log_entry(child, "sleep", start_time, {"start_conditions": start_conditions,
                                                       "end_conditions": end_conditions, "locations": locations},
                         notes, end_time, end_required=True)

    # --- feeding ----------------------------------------------------------------------------------

    @mcp.tool(annotations=DESTRUCTIVE)
    def nursing_timer(
        action: Annotated[Literal["start", "pause", "resume", "switch", "cancel", "complete"], Field(
            description="start (or move the start of a running timer), pause, resume, switch sides, "
                        "cancel (discard), complete (stop and save).")],
        side: Annotated[Side | None, Field(description="start, resume or switch: breast side. start default: left.")] = None,
        start_time: Annotated[str | None, Field(description="start only: when nursing started. Omit = now.")] = None,
        end_time: Annotated[str | None, Field(description="complete only: when nursing ended. Omit = now.")] = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Control the live breastfeeding timer. It counts seconds per side. Use log_nursing for a feed that is over."""
        return timer(child, "nursing", action, start_time, end_time, side=side, notes=notes)

    @mcp.tool
    def log_nursing(
        start_time: Annotated[str, Field(description="When nursing started, ISO 8601.")],
        end_time: Annotated[str | None, Field(description="When nursing ended, ISO 8601. Omit = now.")] = None,
        left_seconds: Annotated[float | None, Field(description="Seconds on the left breast.", ge=0)] = None,
        right_seconds: Annotated[float | None, Field(description="Seconds on the right breast.", ge=0)] = None,
        last_side: Annotated[Side | None, Field(description="Side nursed last.")] = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Save a breastfeed that is over."""
        return log_entry(child, "nursing", start_time, {"left_seconds": left_seconds, "right_seconds": right_seconds,
                                                         "last_side": last_side}, notes, end_time, end_required=True)

    @mcp.tool
    def log_bottle(
        amount: Annotated[float, Field(description="Amount fed, in `units`.", ge=0)],
        units: Volume = "ml",
        milk_type: Annotated[MilkType | None, Field(description="What was in the bottle.")] = None,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a bottle feed."""
        return log_entry(child, "bottle", start_time, {"amount_ml": _ml(amount, units), "milk_type": milk_type}, notes)

    @mcp.tool
    def log_solids(
        foods: Annotated[list[Food], Field(description="Foods eaten: name and optional amount as text.", min_length=1)],
        reaction: Annotated[Reaction | None, Field(description="How the child liked it.")] = None,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a solid-food meal."""
        return log_entry(child, "solids", start_time,
                         {"foods": [f.model_dump(exclude_none=True) for f in foods], "reaction": reaction}, notes)

    # --- pump -------------------------------------------------------------------------------------

    @mcp.tool(annotations=DESTRUCTIVE)
    def pump_timer(
        action: Annotated[Literal["start", "pause", "resume", "cancel", "complete"], Field(
            description="start (or move the start of a running timer), pause, resume, cancel (discard), "
                        "complete (stop and save with amounts).")],
        start_time: Annotated[str | None, Field(description="start only: when pumping started. Omit = now.")] = None,
        end_time: Annotated[str | None, Field(description="complete only: when pumping ended. Omit = now.")] = None,
        left_amount: Annotated[float | None, Field(description="complete only: left side amount.", ge=0)] = None,
        right_amount: Annotated[float | None, Field(description="complete only: right side amount.", ge=0)] = None,
        total_amount: Annotated[float | None, Field(description="complete only: total amount.", ge=0)] = None,
        units: Volume = "ml",
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Control the live breast-pumping timer. Use log_pump for a session that is over."""
        data = {k: _ml(v, units) for k, v in {"left_ml": left_amount, "right_ml": right_amount,
                                              "total_ml": total_amount}.items() if v is not None}
        return timer(child, "pump", action, start_time, end_time, data=data or None, notes=notes)

    @mcp.tool
    def log_pump(
        start_time: Time = None,
        end_time: Annotated[str | None, Field(description="When pumping ended, ISO 8601. Optional.")] = None,
        left_amount: Annotated[float | None, Field(description="Left side amount.", ge=0)] = None,
        right_amount: Annotated[float | None, Field(description="Right side amount.", ge=0)] = None,
        total_amount: Annotated[float | None, Field(description="Total amount when sides were not measured.", ge=0)] = None,
        units: Volume = "ml",
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Save a breast-pumping session that is over."""
        return log_entry(child, "pump", start_time, {"left_ml": _ml(left_amount, units),
                                                      "right_ml": _ml(right_amount, units),
                                                      "total_ml": _ml(total_amount, units)}, notes, end_time)

    # --- activities -------------------------------------------------------------------------------

    @mcp.tool(annotations=DESTRUCTIVE)
    def activity_timer(
        action: Annotated[Literal["start", "pause", "resume", "switch", "cancel", "complete"], Field(
            description="start (or move the start of a running timer), pause, resume, switch (change the kind), "
                        "cancel (discard), complete (stop and save). One activity timer runs per child.")],
        kind: Annotated[ActivityKind | None, Field(description="start and switch: which activity.")] = None,
        start_time: Annotated[str | None, Field(description="start only: when it started. Omit = now.")] = None,
        end_time: Annotated[str | None, Field(description="complete only: when it ended. Omit = now.")] = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Control the live activity timer (bath, tummy time, story time, play and so on)."""
        return timer(child, "activity", action, start_time, end_time, kind=kind, notes=notes)

    @mcp.tool
    def log_activity(
        kind: Annotated[ActivityKind, Field(description="Which activity.")],
        start_time: Time = None,
        end_time: Annotated[str | None, Field(description="When it ended, ISO 8601. Optional.")] = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Save an activity that is over."""
        return log_entry(child, "activity", start_time, {"kind": kind}, notes, end_time)

    # --- nappy and potty --------------------------------------------------------------------------

    @mcp.tool
    def log_nappy(
        mode: Annotated[NappyMode, Field(description="What was in the nappy.")],
        pee_amount: Annotated[Amount | None, Field(description="How much pee.")] = None,
        poo_amount: Annotated[Amount | None, Field(description="How much poo.")] = None,
        color: Annotated[PooColor | None, Field(description="Poo colour.")] = None,
        consistency: Annotated[PooConsistency | None, Field(description="Poo consistency.")] = None,
        rash: Annotated[bool, Field(description="Nappy rash.")] = False,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a nappy (diaper) change."""
        return log_entry(child, "nappy", start_time, {"mode": mode, "pee_amount": pee_amount, "poo_amount": poo_amount,
                                                       "color": color, "consistency": consistency, "rash": rash}, notes)

    @mcp.tool
    def log_potty(
        mode: Annotated[NappyMode, Field(description="What happened: pee, poo, both or dry.")],
        result: Annotated[PottyResult, Field(description="satButDry, wentPotty (success) or accident.")],
        pee_amount: Annotated[Amount | None, Field(description="How much pee.")] = None,
        poo_amount: Annotated[Amount | None, Field(description="How much poo.")] = None,
        color: Annotated[PooColor | None, Field(description="Poo colour.")] = None,
        consistency: Annotated[PooConsistency | None, Field(description="Poo consistency.")] = None,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a potty-training attempt (potty or toilet, not a nappy change)."""
        return log_entry(child, "potty", start_time, {"mode": mode, "result": result, "pee_amount": pee_amount,
                                                       "poo_amount": poo_amount, "color": color,
                                                       "consistency": consistency}, notes)

    # --- health -----------------------------------------------------------------------------------

    @mcp.tool
    def log_growth(
        weight: Annotated[float | None, Field(description="Weight: kg (metric) or lb (imperial).", gt=0)] = None,
        height: Annotated[float | None, Field(description="Length or height: cm (metric) or in (imperial).", gt=0)] = None,
        head: Annotated[float | None, Field(description="Head circumference: cm (metric) or in (imperial).", gt=0)] = None,
        units: Annotated[Literal["metric", "imperial"], Field(description="Unit system for all values.")] = "metric",
        start_time: Time = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log growth measurements (one or more of weight, height, head circumference)."""
        imp = units == "imperial"
        conv = {"weight_kg": (weight, LB_KG), "height_cm": (height, IN_CM), "head_cm": (head, IN_CM)}
        data = {k: round(v * f if imp else v, 3) for k, (v, f) in conv.items() if v is not None}
        return log_entry(child, "growth", start_time, data)

    @mcp.tool
    def log_temperature(
        value: Annotated[float, Field(description="Temperature reading.")],
        units: Annotated[Literal["C", "F"], Field(description="C for Celsius, F for Fahrenheit.")] = "C",
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a body temperature reading."""
        celsius = round((value - 32) * 5 / 9 if units == "F" else value, 2)
        return log_entry(child, "temperature", start_time, {"celsius": celsius}, notes)

    @mcp.tool
    def log_medicine(
        name: Annotated[str, Field(description="Medicine name.")],
        amount: Annotated[float | None, Field(description="Dose amount, in `unit`.", ge=0)] = None,
        unit: Annotated[MedicineUnit | None, Field(description="Dose unit.")] = None,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a medicine dose."""
        return log_entry(child, "medicine", start_time, {"name": name, "amount": amount, "unit": unit}, notes)

    @mcp.tool
    def log_milestone(
        title: Annotated[str, Field(description="What the child did, for example 'First steps'.")],
        key: Annotated[str | None, Field(description="Catalog key from get_milestones, if it matches one.")] = None,
        start_time: Time = None,
        notes: Notes = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Log a development milestone."""
        return log_entry(child, "milestone", start_time, {"title": title, "key": key}, notes)

    @mcp.tool
    def log_note(
        text: Annotated[str, Field(description="The note.", min_length=1)],
        start_time: Time = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Save a free-text note."""
        return log_entry(child, "note", start_time, {}, text)

    # --- history ----------------------------------------------------------------------------------

    @mcp.tool(annotations=READ)
    def list_entries(
        type: Annotated[EntryType | None, Field(description="Only this entry type. Omit = all types.")] = None,
        start: Annotated[str | None, Field(description="Range start, ISO 8601. Omit = 24 hours before end.")] = None,
        end: Annotated[str | None, Field(description="Range end, ISO 8601. Omit = now.")] = None,
        limit: Annotated[int, Field(description="Maximum number of entries.", ge=1, le=500)] = 100,
        child: ChildArg = None,
    ) -> list[dict[str, Any]]:
        """List entries that start in a time range, newest first. Each has an id for update_entry and
        delete_entry. Times are in the family time zone."""
        end_dt = _parse(end)
        start_dt = _parse(start) if start else end_dt - timedelta(hours=24)
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            return [_entry(e, ctx) for e in entries.list_entries(s, ctx, c.id, type, start_dt, end_dt, limit)]

    @mcp.tool
    def update_entry(
        entry_id: Annotated[int, Field(description="Entry id from list_entries.")],
        start_time: Annotated[str | None, Field(description="New start, ISO 8601.")] = None,
        end_time: Annotated[str | None, Field(description="New end, ISO 8601.")] = None,
        data: Annotated[dict[str, Any] | None, Field(
            description="Fields to change in data (same names as list_entries shows). null removes a field.")] = None,
        notes: Annotated[str | None, Field(description="New note.")] = None,
    ) -> dict[str, Any]:
        """Change a saved entry. Find it with list_entries and confirm with the user first."""
        with call() as (s, ctx):
            e = entries.get_entry(s, ctx, entry_id)
            changes: dict[str, Any] = {}
            if start_time:
                changes["started_at"] = _parse(start_time)
            if end_time:
                changes["ended_at"] = _parse(end_time)
            if data is not None:
                changes["data"] = {k: v for k, v in {**e.data, **data}.items() if v is not None}
            if notes is not None:
                changes["notes"] = notes
            return _entry(entries.update_entry(s, ctx, e.id, EntryPatch(**changes)), ctx)

    @mcp.tool(annotations=DESTRUCTIVE)
    def delete_entry(entry_id: Annotated[int, Field(description="Entry id from list_entries.")]) -> str:
        """Delete a saved entry for ever. Find it with list_entries and confirm with the user first."""
        with call() as (s, ctx):
            entries.delete_entry(s, ctx, entry_id)
            return f"Deleted entry {entry_id}"

    # --- reports ----------------------------------------------------------------------------------

    @mcp.tool(annotations=READ)
    def get_daily_report(
        from_date: Annotated[str | None, Field(description="First day, YYYY-MM-DD. Omit = 6 days before to_date.")] = None,
        to_date: Annotated[str | None, Field(description="Last day, YYYY-MM-DD. Omit = today.")] = None,
        child: ChildArg = None,
    ) -> dict[str, Any]:
        """Totals per day in the family time zone: sleep (total, night, naps), feeds, nappies, pump, medicine,
        activities, plus the recommended total sleep for the age with its source."""
        try:
            start = date.fromisoformat(from_date) if from_date else None
            end = date.fromisoformat(to_date) if to_date else None
        except ValueError as err:
            raise ToolError("Dates must be YYYY-MM-DD.") from err
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            rep = reports.daily(s, ctx, c.id, start, end)
            return {**rep, "days": [d.model_dump(mode="json") for d in rep["days"]]}

    @mcp.tool(annotations=READ)
    def get_sleep_prediction(child: ChildArg = None) -> dict[str, Any] | None:
        """Next sleep window from the child's recent wake windows (or age ranges). Wake-window ranges are common
        practice, not a medical standard. Returns null while the child sleeps or with no sleep in the last 24 h."""
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            p = sleep.predict(s, c, ctx.tz)
            if p is None:
                return None
            out = Prediction.model_validate(p).model_dump(mode="json")
            return out | {"start": p["start"].astimezone(ctx.tz).isoformat(),
                          "end": p["end"].astimezone(ctx.tz).isoformat()}

    @mcp.tool(annotations=READ)
    def get_milestones(child: ChildArg = None) -> dict[str, Any]:
        """Development milestone checklist by age (CDC), with the achieved flag and the source of each item."""
        with call() as (s, ctx):
            c = child_of(s, ctx, child)
            return MilestonesOut.model_validate(milestones.milestones(s, ctx, c.id)).model_dump(mode="json")

    return mcp


def main() -> None:
    """Console entry point: frecklebubby-mcp --stdio [--user EMAIL]."""
    parser = argparse.ArgumentParser(description="Frecklebubby MCP server for local clients (stdio)")
    parser.add_argument("--stdio", action="store_true", required=True, help="serve over stdio")
    parser.add_argument("--user", help="email of the user to act as; default: the only user in the database")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    init_db(get_settings().data_dir)
    email = args.user
    if not email:
        with SessionLocal() as s:
            users = s.scalars(select(User.email).limit(2)).all()
        if len(users) != 1:
            raise SystemExit("Give --user EMAIL: the database has no user or more than one.")
        email = users[0]
    create_mcp(fixed_email=email).run(transport="stdio")


if __name__ == "__main__":
    main()
