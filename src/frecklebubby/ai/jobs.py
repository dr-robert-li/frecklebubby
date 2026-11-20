"""Slow model work (sleep plan, support report) as a job: start it, return at once, then poll.

A proxy cuts a request that sends no data for 100 s (Cloudflare). The result is saved by the job itself
(the last one saved stays until a new one is done), so the page reads it with the normal GET.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import User
from ..services import Ctx, NotFound, ServiceError
from ..services.families import context
from . import llm

log = logging.getLogger(__name__)

Make = Callable[[Session, Ctx, int], Awaitable[Any]]

# (kind, child id) -> {"status": "running" | "done" | "failed", "error": str | None}
# shortcut: in memory, one process; a restart forgets the job (the page then shows the last saved result).
_JOBS: dict[tuple[str, int], dict] = {}
_TASKS: dict[tuple[str, int], asyncio.Task] = {}


def start(kind: str, ctx: Ctx, child_id: int, make: Make) -> dict:
    """Start the job for this child, or return the one that runs. The caller checked the child."""
    key = (kind, child_id)
    job = _JOBS.get(key)
    if job and job["status"] == "running":
        return job
    llm.QUEUE.check()
    job = _JOBS[key] = {"status": "running", "error": None}
    _TASKS[key] = asyncio.create_task(_run(job, key, ctx.user.id, ctx.source, make))
    return job


def get(kind: str, child_id: int) -> dict:
    return _JOBS.get((kind, child_id)) or {"status": "none", "error": None}


async def wait(kind: str, child_id: int) -> None:
    task = _TASKS.get((kind, child_id))
    if task:
        await asyncio.shield(task)


async def _run(job: dict, key: tuple[str, int], user_id: int, source: str, make: Make) -> None:
    try:
        with SessionLocal() as s:
            user = s.get(User, user_id)
            if user is None:
                raise NotFound("The account was deleted.")
            await make(s, context(s, user, source), key[1])
        job["status"] = "done"
    except ServiceError as err:
        job["status"], job["error"] = "failed", str(err)
    except Exception:
        log.exception("Job %s failed", key[0])
        job["status"], job["error"] = "failed", "Something went wrong. Try again."
    finally:
        _TASKS.pop(key, None)


def reset() -> None:
    _JOBS.clear()
    _TASKS.clear()
