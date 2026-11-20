"""Users, families, members, invites and family settings."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ApiToken,
    Child,
    Family,
    ImportJob,
    Invite,
    KbSource,
    Membership,
    PushSubscription,
    ServerInvite,
    User,
)
from ..schemas import FamilyIn, FamilyPatch, LlmOut, SettingsOut, SettingsPatch, Units
from . import Conflict, Ctx, Invalid, NotFound, zone
from .access import is_operator, use_invite


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
    return {"user": ctx.user, "family": ctx.family, "role": ctx.role, "children": children,
            "operator": is_operator(ctx)}


def create_family(s: Session, ctx: Ctx, body: FamilyIn) -> Family:
    if ctx.family:
        raise Conflict("You are already in a family.")
    zone(body.timezone)
    use_invite(s, ctx)
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


def make_owner(s: Session, ctx: Ctx, user_id: int) -> None:
    """Give the owner role to another member. The old owner becomes a carer."""
    ctx.require_owner()
    m = s.get(Membership, user_id)
    if m is None or m.family_id != ctx.fam.id:
        raise NotFound("Member not found.")
    if user_id == ctx.user.id:
        raise Invalid("You are the owner already.")
    m.role = "owner"
    s.get(Membership, ctx.user.id).role = "carer"
    s.commit()


# --- delete data (M16) ----------------------------------------------------------------------------


def _purge_family(s: Session, family_id: int) -> None:
    """Delete the family and all its rows. The foreign keys cascade from family and child; the search rows
    (kb_chunk, no foreign key) and the members' tokens and push subscriptions go here. The caller commits.
    The app keeps no family files on disk (uploads are stored as search rows only), so there is no file step."""
    from ..importer.huckleberry import _recover
    from ..knowledge.store import delete_sources

    _recover(s)
    if s.scalar(select(ImportJob.id).where(ImportJob.family_id == family_id,
                                           ImportJob.status.in_(("pending", "running")))):
        raise Conflict("An import is running. Wait until it is done, then try again.")
    members = select(Membership.user_id).where(Membership.family_id == family_id)
    delete_sources(s, list(s.scalars(select(KbSource.id).where(KbSource.family_id == family_id))))
    s.execute(delete(ApiToken).where(ApiToken.user_id.in_(members)))
    s.execute(delete(PushSubscription).where(PushSubscription.user_id.in_(members)))
    # M17: the server invite of each member goes too; to use the server again, a member needs a new invite.
    s.execute(delete(ServerInvite).where(ServerInvite.email.in_(select(User.email).where(User.id.in_(members)))))
    s.execute(delete(Family).where(Family.id == family_id))


def delete_family(s: Session, ctx: Ctx, confirm: str) -> None:
    """The owner deletes the family for good. confirm must be the family name."""
    ctx.require_owner()
    if confirm.strip().casefold() != ctx.fam.name.strip().casefold():
        raise Invalid("confirm: type the family name to delete the family.")
    _purge_family(s, ctx.fam.id)
    s.commit()


def delete_account(s: Session, ctx: Ctx, confirm: str) -> None:
    """The user deletes the account: membership, tokens, push subscriptions (foreign keys cascade). Entries keep
    their data and lose the author. The only member of a family deletes the family too."""
    if confirm.strip().lower() != ctx.user.email:
        raise Invalid("confirm: type your email to delete your account.")
    if ctx.family is not None:
        others = s.scalar(select(func.count()).select_from(Membership).where(
            Membership.family_id == ctx.family.id, Membership.user_id != ctx.user.id))
        if others and ctx.role == "owner":
            raise Conflict("You are the owner of a family with other carers. Make another carer the owner, "
                           "or delete the family first.")
        if not others:
            _purge_family(s, ctx.family.id)
    s.execute(delete(ServerInvite).where(ServerInvite.email == ctx.user.email))
    s.execute(delete(User).where(User.id == ctx.user.id))
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
