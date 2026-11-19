"""Personal access tokens. Only the SHA-256 hash is stored; the token is shown once."""

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import ApiToken, User
from . import Ctx, NotFound

PREFIX = "fb_pat_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(s: Session, ctx: Ctx, name: str) -> tuple[ApiToken, str]:
    token = PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(user_id=ctx.user.id, name=name, token_hash=_hash(token))
    s.add(row)
    s.commit()
    return row, token


def list_tokens(s: Session, ctx: Ctx) -> list[ApiToken]:
    return list(s.scalars(select(ApiToken).where(ApiToken.user_id == ctx.user.id).order_by(ApiToken.id)))


def delete_token(s: Session, ctx: Ctx, token_id: int) -> None:
    row = s.get(ApiToken, token_id)
    if row is None or row.user_id != ctx.user.id:
        raise NotFound("Token not found.")
    s.delete(row)
    s.commit()


def user_for_token(s: Session, token: str) -> User | None:
    row = s.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(token)))
    if row is None:
        return None
    row.last_used_at = utcnow()
    s.commit()
    return s.get(User, row.user_id)
