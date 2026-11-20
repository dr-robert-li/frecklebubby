"""Huckleberry import routes."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from ..auth import get_ctx, upload_limit
from ..db import get_session
from ..importer import huckleberry
from ..schemas import Email
from ..services import Ctx

router = APIRouter(tags=["import"])


class ImportIn(BaseModel):
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    timezone: str
    child_id: int | None = Field(None, description=(
        "Put the data into this child of your family. Only for a Huckleberry account with one child. The child "
        "keeps its name and birth date. Empty = each Huckleberry child becomes a new child."))


class ImportStarted(BaseModel):
    job_id: int


class JobOut(BaseModel):
    id: int
    status: Literal["pending", "running", "done", "failed"]
    progress: dict[str, Any]
    error: str | None


@router.post("/import/huckleberry", response_model=ImportStarted, status_code=202, description=(
    "Copy children and entries from Huckleberry. The import runs in the background; read its progress with "
    "GET /import/jobs/{id}. You can do the import again: it adds new entries and updates changed entries. "
    "It does not delete entries. If you changed an imported entry in Frecklebubby, the next import writes the "
    "Huckleberry values over your change. The password is used for this import only. It is not stored."),
    dependencies=[Depends(upload_limit)])
async def start_import(body: ImportIn, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    # async route: the job task needs the running event loop.
    return {"job_id": huckleberry.start_job(s, ctx, body.email, body.password, body.timezone,
                                             body.child_id).id}


@router.get("/import/jobs/{job_id}", response_model=JobOut, description=(
    "Progress of an import. `progress.skipped_reasons` lists the first 20 skipped rows and why."))
def get_job(job_id: int, ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
    return huckleberry.get_job(s, ctx, job_id)
