from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from frecklebubby.config import get_settings
from frecklebubby.db import SessionLocal
from frecklebubby.services import notifications
from frecklebubby.services.families import context, sign_in

FIXTURES = Path(__file__).parent / "fixtures" / "data"


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


def ctx_for(email: str, source: str = "app"):
    """A service-layer Ctx and an open session for this user."""
    s = SessionLocal()
    return s, context(s, sign_in(s, email), source)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)
