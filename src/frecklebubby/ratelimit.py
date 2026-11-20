"""Rate limits: a sliding window per (limit, key). The limits are settings ("count/seconds")."""

import math
import time
from collections import deque

from .config import get_settings
from .services import ServiceError

# shortcut: in memory, one process; move to a shared store if the app ever runs more than one process
_HITS: dict[tuple[str, object], deque[float]] = {}
clock = time.monotonic  # tests put a fake clock here


class TooMany(ServiceError):
    status = 429

    def __init__(self, detail: str, retry_after: int):
        super().__init__(detail)
        self.headers = {"Retry-After": str(retry_after)}


def _window(name: str, key: object) -> tuple[deque[float], int, int, float]:
    count, seconds = (int(x) for x in getattr(get_settings(), f"limit_{name}").split("/"))
    now = clock()
    q = _HITS.setdefault((name, key), deque())
    while q and q[0] <= now - seconds:
        q.popleft()
    return q, count, seconds, now


def check(name: str, key: object) -> None:
    """429 when the key used all its requests in the window."""
    q, count, seconds, now = _window(name, key)
    if len(q) >= count:
        wait = max(1, math.ceil(q[0] + seconds - now))
        minutes = math.ceil(wait / 60)
        raise TooMany(f"Too many requests. Try again in {minutes} minute{'s' if minutes > 1 else ''}.", wait)
    if not q:
        del _HITS[(name, key)]  # keep the table small


def add(name: str, key: object) -> None:
    q, _, _, now = _window(name, key)
    q.append(now)


def hit(name: str, key: object) -> None:
    check(name, key)
    add(name, key)


def reset() -> None:
    _HITS.clear()
