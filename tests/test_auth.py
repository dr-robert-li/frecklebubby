import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from frecklebubby import auth
from frecklebubby.config import Settings, get_settings
from frecklebubby.db import SessionLocal
from frecklebubby.models import ApiToken

from .conftest import as_user, make_family

DOMAIN = "clerk.example.test"


async def test_dev_default_user(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "dev@example.com"
    assert r.json()["family"] is None


async def test_no_family_gives_409(client):
    r = await client.get("/api/v1/children")
    assert r.status_code == 409
    assert r.json() == {"detail": "You are not in a family. Create a family first."}


async def test_pat_is_hashed_and_works(client):
    h, cid = await make_family(client)
    r = await client.post("/api/v1/tokens", json={"name": "script"}, headers=h)
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("fb_pat_")
    with SessionLocal() as s:
        row = s.scalar(select(ApiToken))
        assert row.token_hash != token and token not in row.token_hash
    listed = (await client.get("/api/v1/tokens", headers=h)).json()
    assert "token" not in listed[0]

    bearer = {"Authorization": f"Bearer {token}"}
    r = await client.post(f"/api/v1/children/{cid}/entries", headers=bearer,
                          json={"type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "hi"})
    assert r.status_code == 201
    assert r.json()["source"] == "api"
    assert (await client.get("/api/v1/tokens", headers=h)).json()[0]["last_used_at"] is not None

    assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer fb_pat_wrong"})).status_code == 401
    await client.delete(f"/api/v1/tokens/{listed[0]['id']}", headers=h)
    assert (await client.get("/api/v1/me", headers=bearer)).status_code == 401


async def test_allowed_emails(env, client):
    env.setenv("ALLOWED_EMAILS", "a@example.com, B@example.com")
    get_settings.cache_clear()
    assert (await client.get("/api/v1/me", headers=as_user("a@example.com"))).status_code == 200
    assert (await client.get("/api/v1/me", headers=as_user("b@example.com"))).status_code == 200
    r = await client.get("/api/v1/me", headers=as_user("c@example.com"))
    assert r.status_code == 403


def test_clerk_mode_needs_settings():
    with pytest.raises(SystemExit, match="CLERK_DOMAIN"):
        Settings(auth_mode="clerk", _env_file=None).check()
    Settings(auth_mode="dev", _env_file=None).check()


# --- Clerk session JWT ----------------------------------------------------------------------------


@pytest.fixture
def clerk(env):
    env.setenv("AUTH_MODE", "clerk")
    env.setenv("CLERK_DOMAIN", DOMAIN)
    env.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_x")
    env.setenv("CLERK_OAUTH_CLIENT_ID", "cid")
    env.setenv("CLERK_OAUTH_CLIENT_SECRET", "secret")
    env.setenv("BASE_URL", "https://baby.example.test")
    get_settings.cache_clear()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "k1", "use": "sig"}
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return httpx.Response(200, json={"keys": [jwk]}, request=httpx.Request("GET", url))

    env.setattr(auth.httpx, "get", fake_get)
    env.setattr(auth, "_jwks", {"keys": {}, "fetched": -1e9})
    return key, calls


def _token(key, **over) -> str:
    now = int(time.time())
    claims = {"sub": "user_1", "iss": f"https://{DOMAIN}", "iat": now, "nbf": now, "exp": now + 60,
              "azp": "https://baby.example.test", "email": "Parent@Example.com"} | over
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


async def test_clerk_jwt(clerk, pushes):
    from frecklebubby.main import create_app

    key, calls = clerk
    app = create_app(scheduler=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async def me(token):
            return await c.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

        r = await me(_token(key))
        assert r.status_code == 200
        assert r.json()["user"]["email"] == "parent@example.com"
        assert calls == [f"https://{DOMAIN}/.well-known/jwks.json"]

        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert (await me(_token(other))).status_code == 401  # bad signature
        assert (await me(_token(key, exp=int(time.time()) - 3600))).status_code == 401  # expired
        assert (await me(_token(key, iss="https://evil.example"))).status_code == 401  # wrong issuer
        assert (await me(_token(key, azp="https://evil.example"))).status_code == 401  # wrong azp
        assert (await me(_token(key, email=None))).status_code == 401
        # Dev header does nothing in clerk mode.
        assert (await c.get("/api/v1/me", headers=as_user("x@example.com"))).status_code == 401
