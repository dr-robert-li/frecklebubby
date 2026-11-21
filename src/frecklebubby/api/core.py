"""Config, health, me, families, members, invites, settings, tokens."""

from importlib.metadata import version

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_ctx
from ..config import get_settings
from ..db import get_session
from ..schemas import (
    ConfigOut,
    ConfirmIn,
    FamilyIn,
    FamilyOut,
    FamilyPatch,
    InviteIn,
    InviteOut,
    MemberOut,
    MeOut,
    SettingsOut,
    SettingsPatch,
    TokenCreated,
    TokenIn,
    TokenOut,
)
from ..services import Ctx, families, tokens, voice
from ..services.notifications import vapid_public_key

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/config", response_model=ConfigOut)
def config():
    st = get_settings()
    return {"auth_mode": st.auth_mode, "invite_only": bool(st.operators), "clerk_publishable_key": st.clerk_publishable_key,
            "vapid_public_key": vapid_public_key(), "version": version("frecklebubby"), "voice": voice.available()}


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.me(s, ctx)


@router.post("/families", response_model=FamilyOut, status_code=201)
def create_family(body: FamilyIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.create_family(s, ctx, body)


@router.get("/family", response_model=FamilyOut)
def get_family(ctx: Ctx = Depends(get_ctx)):
    return ctx.fam


@router.patch("/family", response_model=FamilyOut)
def patch_family(body: FamilyPatch, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.update_family(s, ctx, body)


@router.get("/family/settings", response_model=SettingsOut)
def get_family_settings(ctx: Ctx = Depends(get_ctx)):
    return families.get_family_settings(ctx)


@router.patch("/family/settings", response_model=SettingsOut)
def patch_family_settings(body: SettingsPatch, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.update_family_settings(s, ctx, body)


@router.get("/family/members", response_model=list[MemberOut])
def members(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.list_members(s, ctx)


@router.delete("/family/members/{user_id}", status_code=204)
def remove_member(user_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    families.remove_member(s, ctx, user_id)


@router.post("/family/members/{user_id}/owner", status_code=204, summary="Make this member the owner (you become a carer)")
def make_owner(user_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    families.make_owner(s, ctx, user_id)


@router.delete("/family", status_code=204, summary=(
    "Delete the family and all its data for good (owner only). `confirm` is the family name. "
    "Members stay as users without a family; their API tokens and push subscriptions are deleted."))
def delete_family(body: ConfirmIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    families.delete_family(s, ctx, body.confirm)


@router.delete("/me", status_code=204, summary=(
    "Delete your account for good. `confirm` is your email. Entries you made stay without an author. "
    "If you are the only member, the family is deleted too. The sign-in account at Clerk is separate."))
def delete_me(body: ConfirmIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    families.delete_account(s, ctx, body.confirm)


@router.get("/family/invites", response_model=list[InviteOut])
def invites(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.list_invites(s, ctx)


@router.post("/family/invites", response_model=InviteOut, status_code=201)
def create_invite(body: InviteIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return families.create_invite(s, ctx, body.email)


@router.delete("/family/invites/{invite_id}", status_code=204)
def delete_invite(invite_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    families.delete_invite(s, ctx, invite_id)


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return tokens.list_tokens(s, ctx)


@router.post("/tokens", response_model=TokenCreated, status_code=201)
def create_token(body: TokenIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    row, token = tokens.create_token(s, ctx, body.name)
    return {**TokenOut.model_validate(row).model_dump(), "token": token}


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(token_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    tokens.delete_token(s, ctx, token_id)
