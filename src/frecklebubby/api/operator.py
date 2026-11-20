"""M17: Settings > Server access (operators only). Not in the OpenAPI document; others get 404.

Only these routes exist: read the invites and the families, add an invite, remove an unused invite.
No route changes or deletes a family.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_ctx
from ..db import get_session
from ..schemas import InviteIn, ServerFamilyOut, ServerInviteOut
from ..services import Ctx, access

router = APIRouter(prefix="/operator", include_in_schema=False)


@router.get("/invites", response_model=list[ServerInviteOut])
def invites(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return access.list_invites(s, ctx)


@router.post("/invites", response_model=ServerInviteOut, status_code=201)
def create_invite(body: InviteIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return access.create_invite(s, ctx, body.email)


@router.delete("/invites/{invite_id}", status_code=204)
def delete_invite(invite_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    access.delete_invite(s, ctx, invite_id)


@router.get("/families", response_model=list[ServerFamilyOut])
def families(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return access.list_families(s, ctx)
