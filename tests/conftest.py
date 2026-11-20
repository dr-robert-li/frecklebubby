import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from frecklebubby.config import get_settings
from frecklebubby.db import SessionLocal
from frecklebubby.services import notifications
from frecklebubby.services.families import context, sign_in

FIXTURES = Path(__file__).parent / "fixtures" / "data"


@pytest.fixture(autouse=True)
def _fresh_limits():
    """Rate limits, the model queue and the model jobs live in memory: start each test empty."""
    from frecklebubby import ratelimit
    from frecklebubby.ai import jobs, llm

    ratelimit.reset()
    jobs.reset()
    llm.QUEUE = llm.Queue()
    yield


@pytest.fixture
def pushes(monkeypatch):
    """Records Web Push calls instead of sending them."""
    sent = []
    monkeypatch.setattr(notifications, "webpush", lambda sub, **kw: sent.append((sub, kw)))
    return sent


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key in ("ALLOWED_EMAILS", "CLERK_DOMAIN", "CLERK_PUBLISHABLE_KEY", "CLERK_OAUTH_CLIENT_ID",
                "CLERK_OAUTH_CLIENT_SECRET", "BASE_URL"):
        monkeypatch.setenv(key, "")  # empty, not deleted: a deleted key falls back to a local .env file
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BUNDLED_DATA_DIR", str(FIXTURES))
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def app(env, pushes):
    from frecklebubby.main import create_app

    return create_app(scheduler=False)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def as_user(email: str) -> dict:
    return {"X-Dev-User": email}


async def make_family(client, email="a@example.com", tz="Australia/Brisbane", child="Ada",
                      birthdate="2026-06-01", sex="F") -> tuple[dict, int]:
    h = as_user(email)
    r = await client.post("/api/v1/families", json={"name": f"Family {email}", "timezone": tz}, headers=h)
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/children", json={"name": child, "birthdate": birthdate, "sex": sex}, headers=h)
    assert r.status_code == 201, r.text
    return h, r.json()["id"]


async def run_job(client, h: dict, url: str) -> tuple[str, dict | str | None]:
    """M15: POST url starts the job (202); poll url/job; then GET url. Returns ("done", result) or ("failed", error)."""
    r = await client.post(url, headers=h)
    assert r.status_code == 202, r.text
    while (job := (await client.get(f"{url}/job", headers=h)).json())["status"] == "running":
        await asyncio.sleep(0.01)
    if job["status"] == "failed":
        return "failed", job["error"]
    return job["status"], (await client.get(url, headers=h)).json()


def api_routes(app) -> set[tuple[str, str]]:
    """(method, path) of every API route, also the ones that are not in the OpenAPI document."""
    from fastapi.routing import APIRoute, iter_route_contexts

    return {(m, c.path) for c in iter_route_contexts(app.routes) if isinstance(c.route, APIRoute) for m in c.methods}


def ctx_for(email: str, source: str = "app"):
    """A service-layer Ctx and an open session for this user."""
    s = SessionLocal()
    return s, context(s, sign_in(s, email), source)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)
