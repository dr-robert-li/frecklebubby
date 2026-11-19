"""Business logic. API routers and MCP tools call only these functions.

Every function that reads or writes family data takes the caller's family and scopes the query by it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from ..models import Family, User


@dataclass
class Ctx:
    """Who is calling. family is None until the user creates or joins one."""

    user: User
    family: Family | None
    role: str | None
    source: str  # entry source: app | api | mcp

    @property
    def fam(self) -> Family:
        if self.family is None:
            raise Conflict("You are not in a family. Create a family first.")
        return self.family

    @property
    def tz(self) -> ZoneInfo:
        return zone(self.fam.timezone)

    def require_owner(self) -> None:
        if self.role != "owner":
            raise Forbidden("Only the family owner can do this.")


class ServiceError(Exception):
    status = 400


class NotFound(ServiceError):
    status = 404


class Invalid(ServiceError):
    status = 422


class Conflict(ServiceError):
    status = 409


class Forbidden(ServiceError):
    status = 403


def plain_errors(err: ValidationError, prefix: str = "") -> str:
    """One short line per pydantic error: 'data.amount_ml: Input should be less than or equal to 500'."""
    parts = []
    for e in err.errors():
        loc = ".".join(str(p) for p in (prefix, *e["loc"]) if p != "")
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return "; ".join(parts)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise Invalid(f"Unknown time zone {name!r}. Use an IANA name, for example Australia/Brisbane.") from err


def to_utc(value: datetime, tz: ZoneInfo) -> datetime:
    """Naive values are in the family time zone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(UTC).replace(microsecond=0)


def hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC start and end of a local day (23 or 25 hours on DST change days)."""
    start = datetime.combine(day, time(), tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), tz).astimezone(UTC)
    return start, end
