"""Token verification: PAT, Clerk session JWT, dev sign-in. Never log tokens."""

import logging
import time
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import ratelimit
from .config import get_settings
from .db import get_session
from .services import Ctx
from .services.access import check_access
from .services.families import context, sign_in
from .services.tokens import PREFIX, user_for_token

log = logging.getLogger(__name__)

DEV_USER = "dev@example.com"
_JWKS_TTL = 3600
_jwks: dict = {"keys": {}, "fetched": 0.0}


def _unauthorized(detail: str = "Sign-in is not valid. Sign in again.") -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def clerk_domain() -> str:
    return get_settings().clerk_domain.removeprefix("https://").rstrip("/")


def _fetch_jwks() -> None:
    r = httpx.get(f"https://{clerk_domain()}/.well-known/jwks.json", timeout=10)
    r.raise_for_status()
    _jwks["keys"] = {k["kid"]: jwt.PyJWK(k) for k in r.json()["keys"] if k.get("kid")}
    _jwks["fetched"] = time.monotonic()


def _key(kid: str) -> jwt.PyJWK:
    age = time.monotonic() - _jwks["fetched"]
    # Refetch when stale, or when the key is unknown (Clerk rotated keys) but not more than once a minute.
    if age > _JWKS_TTL or (kid not in _jwks["keys"] and age > 60):
        try:
            _fetch_jwks()
        except (httpx.HTTPError, ValueError, KeyError) as err:
            log.warning("Could not load Clerk JWKS: %s", type(err).__name__)
    if kid not in _jwks["keys"]:
        raise _unauthorized()
    return _jwks["keys"][kid]


def verify_clerk_jwt(token: str) -> dict:
    """Verify a Clerk session token. Returns its claims. The token must carry an `email` claim."""
    settings = get_settings()
    try:
        kid = jwt.get_unverified_header(token).get("kid") or ""
        claims = jwt.decode(
            token, _key(kid).key, algorithms=["RS256"], issuer=f"https://{clerk_domain()}",
            options={"require": ["exp", "iat", "sub", "iss"], "verify_aud": False}, leeway=5,
        )
    except jwt.PyJWTError as err:
        raise _unauthorized() from err
    base = urlsplit(settings.base_url)
    azp = claims.get("azp")
    if azp and azp.rstrip("/") != f"{base.scheme}://{base.netloc}":
        raise _unauthorized()
    if not isinstance(claims.get("email"), str):
        raise _unauthorized("The session token has no email. Add the email claim to the Clerk session token.")
    return claims


def client_address(request: Request) -> str:
    """Behind Cloudflare Tunnel the peer is the tunnel; the real client is in CF-Connecting-IP."""
    if get_settings().behind_cloudflare and request.headers.get("cf-connecting-ip"):
        return request.headers["cf-connecting-ip"]
    return request.client.host if request.client else ""


def get_ctx(request: Request, s: Session = Depends(get_session)) -> Ctx:
    settings = get_settings()
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    address = client_address(request)
    if token:
        ratelimit.check("bad_token", address)
    if token.startswith(PREFIX):
        user = user_for_token(s, token)
        if user is None:
            ratelimit.add("bad_token", address)
            raise _unauthorized("The API token is not valid.")
        check_access(s, user.email)
        return context(s, user, "api")
    if token and settings.auth_mode == "clerk":
        try:
            claims = verify_clerk_jwt(token)
        except HTTPException:
            ratelimit.add("bad_token", address)
            raise
        check_access(s, claims["email"])
        user = sign_in(s, claims["email"], claims.get("name") or "", claims["sub"])
        return context(s, user, "app")
    if settings.auth_mode == "dev" and not token:
        email = (request.headers.get("x-dev-user") or DEV_USER).strip().lower()
        check_access(s, email)
        return context(s, sign_in(s, email), "app")
    raise _unauthorized("Sign in first.")


def ai_limit(ctx: Ctx = Depends(get_ctx)) -> None:
    """Route dependency: requests to the AI model, per user."""
    ratelimit.hit("ai", ctx.user.id)


def upload_limit(ctx: Ctx = Depends(get_ctx)) -> None:
    """Route dependency: file uploads and import starts, per user."""
    ratelimit.hit("uploads", ctx.user.id)
