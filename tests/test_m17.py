"""M17: invite only server with an operator list."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import delete

from frecklebubby.config import get_settings
from frecklebubby.db import SessionLocal
from frecklebubby.mcp_server import create_mcp
from frecklebubby.models import Membership
from frecklebubby.services.access import INVITE_ONLY

from .conftest import api_routes, as_user, make_family

API = "/api/v1"
OP = as_user("op@example.com")


@pytest.fixture
def invite_only(env):
    env.setenv("OPERATOR_EMAILS", "Op@Example.com, op2@example.com")
    env.setenv("ALLOWED_EMAILS", "fixed@example.com")
    get_settings.cache_clear()


async def me(client, email):
    return await client.get(f"{API}/me", headers=as_user(email))


async def test_without_operators_anyone_signs_in(client):
    r = await me(client, "anyone@example.com")
    assert r.status_code == 200 and r.json()["operator"] is False
    assert (await client.get(f"{API}/operator/invites", headers=as_user("anyone@example.com"))).status_code == 404


async def test_five_ways_in_and_a_refused_email(invite_only, client):
    # 1. an operator (no invite needed, can start a family)
    assert (await me(client, "op@example.com")).json()["operator"] is True
    await make_family(client, "op@example.com")
    # refused
    r = await me(client, "stranger@example.com")
    assert r.status_code == 403 and r.json()["detail"] == INVITE_ONLY
    assert (await client.post(f"{API}/families", headers=as_user("stranger@example.com"),
                              json={"name": "S", "timezone": "UTC"})).status_code == 403
    # 2. on the operator's invite list
    r = await client.post(f"{API}/operator/invites", headers=OP, json={"email": "New@Example.com"})
    assert r.status_code == 201 and r.json()["used_at"] is None
    assert (await me(client, "new@example.com")).json()["operator"] is False
    h, cid = await make_family(client, "new@example.com")
    assert (await client.get(f"{API}/operator/invites", headers=OP)).json()[0]["used_at"]
    # 3. invited as a carer by a family
    await client.post(f"{API}/family/invites", headers=h, json={"email": "carer@example.com"})
    assert (await me(client, "carer@example.com")).json()["role"] == "carer"
    # 4. already a member (the carer invite is used up when the carer joins)
    assert (await client.get(f"{API}/family/invites", headers=h)).json() == []
    assert (await me(client, "carer@example.com")).status_code == 200
    # 5. in ALLOWED_EMAILS
    await make_family(client, "fixed@example.com")

    # an invited person can start one family only (here: one who left the family and still has the invite)
    with SessionLocal() as s:
        s.execute(delete(Membership).where(Membership.user_id == (await me(client, "new@example.com")).json()["user"]["id"]))
        s.commit()
    r = await client.post(f"{API}/families", headers=h, json={"name": "Again", "timezone": "UTC"})
    assert r.status_code == 403 and "one family" in r.json()["detail"]


async def test_deleting_the_family_ends_the_invite(invite_only, client):
    await client.post(f"{API}/operator/invites", headers=OP, json={"email": "new@example.com"})
    h, _ = await make_family(client, "new@example.com")
    r = await client.request("DELETE", f"{API}/family", headers=h, json={"confirm": "Family new@example.com"})
    assert r.status_code == 204
    r = await me(client, "new@example.com")
    assert r.status_code == 403 and r.json()["detail"] == INVITE_ONLY
    assert (await client.get(f"{API}/operator/invites", headers=OP)).json() == []
    # the operator invites the email again: it can start a new family
    assert (await client.post(f"{API}/operator/invites", headers=OP, json={"email": "new@example.com"})
            ).status_code == 201
    await make_family(client, "new@example.com")
    # delete the account (the only member): the family and the invite go
    r = await client.request("DELETE", f"{API}/me", headers=h, json={"confirm": "new@example.com"})
    assert r.status_code == 204
    assert (await me(client, "new@example.com")).status_code == 403
    assert (await client.get(f"{API}/operator/families", headers=OP)).json() == []
    assert (await client.get(f"{API}/config")).json()["invite_only"] is True


async def test_access_is_checked_on_each_request_for_tokens_and_mcp(invite_only, client):
    await client.post(f"{API}/operator/invites", headers=OP, json={"email": "new@example.com"})
    h, _ = await make_family(client, "new@example.com")
    carer = as_user("carer@example.com")
    await client.post(f"{API}/family/invites", headers=h, json={"email": "carer@example.com"})
    uid = (await client.get(f"{API}/me", headers=carer)).json()["user"]["id"]
    token = (await client.post(f"{API}/tokens", headers=carer, json={"name": "t"})).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"{API}/me", headers=bearer)).status_code == 200
    async with Client(create_mcp(fixed_email="carer@example.com")) as mcp:
        await mcp.call_tool("list_children", {})
    # the owner removes the carer: no way in is left, from the next request on
    assert (await client.delete(f"{API}/family/members/{uid}", headers=h)).status_code == 204
    r = await client.get(f"{API}/me", headers=bearer)
    assert r.status_code == 403 and r.json()["detail"] == INVITE_ONLY
    async with Client(create_mcp(fixed_email="carer@example.com")) as mcp:
        with pytest.raises(ToolError, match="invite only"):
            await mcp.call_tool("list_children", {})


async def test_operator_invites_and_families(invite_only, client):
    await client.post(f"{API}/operator/invites", headers=OP, json={"email": "new@example.com"})
    waiting = (await client.post(f"{API}/operator/invites", headers=OP, json={"email": "later@example.com"})).json()
    assert (await client.post(f"{API}/operator/invites", headers=OP, json={"email": "later@example.com"})
            ).status_code == 409
    await make_family(client, "op@example.com")
    h, cid = await make_family(client, "new@example.com", child="Secretname")
    await client.post(f"{API}/children/{cid}/entries", headers=h,
                      json={"type": "note", "started_at": "2026-11-01T10:00:00Z", "notes": "private note"})

    fams = await client.get(f"{API}/operator/families", headers=OP)
    new = fams.json()[0]
    assert new | {"created_at": 0, "last_activity": 0} == {"name": "Family new@example.com", "members": [
        "new@example.com"], "created_at": 0, "last_activity": 0}
    assert len(fams.json()) == 2 and new["last_activity"] >= new["created_at"]
    assert "Secretname" not in fams.text and "private note" not in fams.text
    # the operator cannot read the family's data
    assert (await client.get(f"{API}/children/{cid}", headers=OP)).status_code == 404
    assert (await client.get(f"{API}/children/{cid}/entries", headers=OP)).status_code == 404

    # remove a waiting invite: that email is refused; a used invite cannot be removed
    assert (await client.delete(f"{API}/operator/invites/{waiting['id']}", headers=OP)).status_code == 204
    assert (await me(client, "later@example.com")).status_code == 403
    used = next(i for i in (await client.get(f"{API}/operator/invites", headers=OP)).json() if i["used_at"])
    r = await client.delete(f"{API}/operator/invites/{used['id']}", headers=OP)
    assert r.status_code == 409 and r.json()["detail"] == "This invite is used. The family is now managed by its owner."
    assert (await client.delete(f"{API}/operator/invites/999", headers=OP)).status_code == 404


async def test_server_access_routes_are_hidden_and_cannot_change_families(invite_only, app, client):
    h, _ = await make_family(client, "fixed@example.com")
    for method, path in [("GET", "/invites"), ("POST", "/invites"), ("DELETE", "/invites/1"), ("GET", "/families")]:
        r = await client.request(method, f"{API}/operator{path}", headers=h, json={"email": "x@example.com"})
        assert r.status_code == 404 and r.json() == {"detail": "Not found."}, (method, path)
    assert not [p for p in app.openapi()["paths"] if "/operator" in p]
    routes = {(m, p) for m, p in api_routes(app) if "/operator" in p}
    assert routes == {("GET", f"{API}/operator/invites"), ("POST", f"{API}/operator/invites"),
                      ("DELETE", f"{API}/operator/invites/{{invite_id}}"), ("GET", f"{API}/operator/families")}
