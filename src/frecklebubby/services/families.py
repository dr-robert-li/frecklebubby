"""Users, families, members, invites and family settings."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Child, Family, Invite, Membership, User
from ..schemas import FamilyIn, FamilyPatch, LlmOut, SettingsOut, SettingsPatch, Units
from . import Conflict, Ctx, Invalid, NotFound, zone


def sign_in(s: Session, email: str, name: str = "", clerk_sub: str | None = None) -> User:
    """Find or create the user; link the Clerk subject; join an invited family if the user has none."""
    email = email.strip().lower()
    user = s.scalar(select(User).where(User.clerk_sub == clerk_sub)) if clerk_sub else None
    user = user or s.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(email=email, name=name or email.split("@")[0], clerk_sub=clerk_sub)
        s.add(user)
        s.flush()
    elif clerk_sub and user.clerk_sub != clerk_sub:
        user.clerk_sub = clerk_sub
    if s.get(Membership, user.id) is None:
        invite = s.scalar(select(Invite).where(func.lower(Invite.email) == user.email).order_by(Invite.id))
        if invite:
            s.add(Membership(user_id=user.id, family_id=invite.family_id, role="carer"))
            s.delete(invite)
    s.commit()
    return user


def context(s: Session, user: User, source: str) -> Ctx:
    m = s.get(Membership, user.id)
    family = s.get(Family, m.family_id) if m else None
    return Ctx(user=user, family=family, role=m.role if m else None, source=source)


def me(s: Session, ctx: Ctx) -> dict:
    children = []
    if ctx.family:
        children = s.scalars(
            select(Child).where(Child.family_id == ctx.family.id, Child.archived.is_(False)).order_by(Child.id)
        ).all()
    return {"user": ctx.user, "family": ctx.family, "role": ctx.role, "children": children}


def create_family(s: Session, ctx: Ctx, body: FamilyIn) -> Family:
    if ctx.family:
        raise Conflict("You are already in a family.")
    zone(body.timezone)
    family = Family(name=body.name, timezone=body.timezone, settings={})
    s.add(family)
    s.flush()
    s.add(Membership(user_id=ctx.user.id, family_id=family.id, role="owner"))
    s.commit()
    return family


def update_family(s: Session, ctx: Ctx, body: FamilyPatch) -> Family:
    family = ctx.fam
    if body.timezone is not None:
        zone(body.timezone)
        family.timezone = body.timezone
    if body.name is not None:
        family.name = body.name
    s.commit()
    return family


# --- settings -------------------------------------------------------------------------------------


def llm_config(family: Family) -> tuple[str, str, str]:
    """Effective (base_url, model, api_key): family values over server defaults. Never log the key."""
    env = get_settings()
    llm = family.settings.get("llm", {})
    return (llm.get("base_url") or env.llm_base_url, llm.get("model") or env.llm_model,
            llm.get("api_key") or env.llm_api_key)


def get_family_settings(ctx: Ctx) -> SettingsOut:
    st = ctx.fam.settings
    base_url, model, _ = llm_config(ctx.fam)
    return SettingsOut(
        units=Units(**st.get("units", {})),
        wording=st.get("wording", "nappy"),
        llm=LlmOut(base_url=base_url, model=model, has_api_key=bool(st.get("llm", {}).get("api_key"))),
        web_lookup=st.get("web_lookup", False),
        milestone_alerts=st.get("milestone_alerts", True),
    )


def update_family_settings(s: Session, ctx: Ctx, body: SettingsPatch) -> SettingsOut:
    st = dict(ctx.fam.settings)
    if body.units is not None:
        st["units"] = {**st.get("units", {}), **body.units.model_dump(exclude_none=True)}
    if body.wording is not None:
        st["wording"] = body.wording
    if body.web_lookup is not None:
        st["web_lookup"] = body.web_lookup
    if body.milestone_alerts is not None:
        st["milestone_alerts"] = body.milestone_alerts
    if body.llm is not None:
        llm = dict(st.get("llm", {}))
        for key in body.llm.model_fields_set:
            value = getattr(body.llm, key)
            if value in (None, ""):
                llm.pop(key, None)
            else:
                llm[key] = value
        st["llm"] = llm
    ctx.fam.settings = st  # new dict so SQLAlchemy sees the change
    s.commit()
    return get_family_settings(ctx)


def wording(family: Family) -> str:
    return family.settings.get("wording", "nappy")


# --- members and invites --------------------------------------------------------------------------


def list_members(s: Session, ctx: Ctx) -> list[dict]:
    rows = s.execute(
        select(User, Membership.role).join(Membership, Membership.user_id == User.id)
        .where(Membership.family_id == ctx.fam.id).order_by(User.id)
    ).all()
    return [{"user_id": u.id, "email": u.email, "name": u.name, "role": role} for u, role in rows]


def remove_member(s: Session, ctx: Ctx, user_id: int) -> None:
    ctx.require_owner()
    m = s.get(Membership, user_id)
    if m is None or m.family_id != ctx.fam.id:
        raise NotFound("Member not found.")
    if user_id == ctx.user.id:
        raise Invalid("The owner cannot leave the family.")
    s.delete(m)
    s.commit()


def list_invites(s: Session, ctx: Ctx) -> list[Invite]:
    return list(s.scalars(select(Invite).where(Invite.family_id == ctx.fam.id).order_by(Invite.id)))


def create_invite(s: Session, ctx: Ctx, email: str) -> Invite:
    ctx.require_owner()
    if any(m["email"] == email for m in list_members(s, ctx)):
        raise Conflict("This person is already in the family.")
    if any(i.email == email for i in list_invites(s, ctx)):
        raise Conflict("This email already has an invite.")
    invite = Invite(family_id=ctx.fam.id, email=email, created_by=ctx.user.id)
    s.add(invite)
    s.commit()
    return invite


def delete_invite(s: Session, ctx: Ctx, invite_id: int) -> None:
    ctx.require_owner()
    invite = s.get(Invite, invite_id)
    if invite is None or invite.family_id != ctx.fam.id:
        raise NotFound("Invite not found.")
    s.delete(invite)
    s.commit()
