"""M17: who may sign in, and the operator's invite list (Settings > Server access).

Operators are the emails in OPERATOR_EMAILS. They are not stored, and nobody becomes one from inside the app.
An operator sees family names, member emails and dates; never child data. An operator cannot change or delete
a family: after a person starts a family, it belongs to its owner.
"""

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import Child, Entry, Family, Invite, Membership, ServerInvite, User
from . import Conflict, Ctx, Forbidden, NotFound

INVITE_ONLY = "This server is invite only. Ask the person who runs it for an invite."


def check_access(s: Session, email: str) -> None:
    """403 when this email may not use the server. Called on each request (app, API token, MCP)."""
    st = get_settings()
    email = email.strip().lower()
    if not st.operators:  # 0.2.2 behaviour
        if st.allowed and email not in st.allowed:
            raise Forbidden("This email is not allowed on this server.")
        return
    if email in st.operators or email in st.allowed:
        return
    ways_in = union_all(
        select(literal(1)).where(ServerInvite.email == email),
        select(literal(1)).where(func.lower(Invite.email) == email),
        select(literal(1)).select_from(Membership).join(User, User.id == Membership.user_id)
        .where(func.lower(User.email) == email),
    ).limit(1)
    if s.scalar(ways_in) is None:
        raise Forbidden(INVITE_ONLY)


def is_operator(ctx: Ctx) -> bool:
    return ctx.user.email in get_settings().operators


def require_operator(ctx: Ctx) -> None:
    """404, not 403: the server access routes do not show that they exist."""
    if not is_operator(ctx):
        raise NotFound("Not found.")


def use_invite(s: Session, ctx: Ctx) -> None:
    """Before a new family: an invited person can start one family. The caller commits."""
    st = get_settings()
    if not st.operators or is_operator(ctx) or ctx.user.email in st.allowed:
        return
    invite = s.scalar(select(ServerInvite).where(ServerInvite.email == ctx.user.email))
    if invite is None or invite.used_at is not None:
        raise Forbidden("Your invite is for one family. Ask the person who runs this server for a new invite.")
    invite.used_at = utcnow()


def list_invites(s: Session, ctx: Ctx) -> list[ServerInvite]:
    require_operator(ctx)
    return list(s.scalars(select(ServerInvite).order_by(ServerInvite.id.desc())))


def create_invite(s: Session, ctx: Ctx, email: str) -> ServerInvite:
    require_operator(ctx)
    if s.scalar(select(ServerInvite.id).where(ServerInvite.email == email)):
        raise Conflict("This email already has an invite.")
    invite = ServerInvite(email=email)
    s.add(invite)
    s.commit()
    return invite


def delete_invite(s: Session, ctx: Ctx, invite_id: int) -> None:
    require_operator(ctx)
    invite = s.get(ServerInvite, invite_id)
    if invite is None:
        raise NotFound("Invite not found.")
    if invite.used_at is not None:
        raise Conflict("This invite is used. The family is now managed by its owner.")
    s.delete(invite)
    s.commit()


def list_families(s: Session, ctx: Ctx) -> list[dict]:
    """Name, member emails, date made, last activity (the last entry change). No child data."""
    require_operator(ctx)
    last = (select(Child.family_id, func.max(Entry.updated_at).label("at")).join(Entry, Entry.child_id == Child.id)
            .group_by(Child.family_id).subquery())
    rows = s.execute(select(Family, last.c.at).outerjoin(last, last.c.family_id == Family.id)
                     .order_by(Family.id.desc())).all()
    members: dict[int, list[str]] = {}
    for fid, email in s.execute(select(Membership.family_id, User.email).join(User, User.id == Membership.user_id)
                                .order_by(User.id)):
        members.setdefault(fid, []).append(email)
    return [{"name": f.name, "members": members.get(f.id, []), "created_at": f.created_at,
             "last_activity": max(f.created_at, at) if at else f.created_at} for f, at in rows]
