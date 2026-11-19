from .conftest import as_user, make_family

API = "/api/v1"


async def test_onboarding(client):
    h = as_user("a@example.com")
    r = await client.post(f"{API}/families", json={"name": "A", "timezone": "Mars/Base"}, headers=h)
    assert r.status_code == 422
    assert "time zone" in r.json()["detail"]
    h, cid = await make_family(client)
    me = (await client.get(f"{API}/me", headers=h)).json()
    assert me["role"] == "owner"
    assert me["family"]["timezone"] == "Australia/Brisbane"
    assert [c["id"] for c in me["children"]] == [cid]
    r = await client.post(f"{API}/families", json={"name": "B", "timezone": "UTC"}, headers=h)
    assert r.status_code == 409


async def test_invite_flow(client):
    owner, cid = await make_family(client)
    carer = as_user("Carer@Example.com")
    r = await client.post(f"{API}/family/invites", json={"email": "Carer@Example.com"}, headers=owner)
    assert r.status_code == 201
    assert r.json()["email"] == "carer@example.com"
    assert (await client.post(f"{API}/family/invites", json={"email": "carer@example.com"},
                              headers=owner)).status_code == 409

    me = (await client.get(f"{API}/me", headers=carer)).json()
    assert me["role"] == "carer"
    assert me["children"][0]["id"] == cid
    assert (await client.get(f"{API}/family/invites", headers=owner)).json() == []
    members = (await client.get(f"{API}/family/members", headers=owner)).json()
    assert {m["role"] for m in members} == {"owner", "carer"}

    # Carers cannot manage members or invites.
    assert (await client.post(f"{API}/family/invites", json={"email": "x@example.com"},
                              headers=carer)).status_code == 403
    owner_id = next(m["user_id"] for m in members if m["role"] == "owner")
    carer_id = next(m["user_id"] for m in members if m["role"] == "carer")
    assert (await client.delete(f"{API}/family/members/{owner_id}", headers=carer)).status_code == 403
    assert (await client.delete(f"{API}/family/members/{owner_id}", headers=owner)).status_code == 422

    assert (await client.delete(f"{API}/family/members/{carer_id}", headers=owner)).status_code == 204
    assert (await client.get(f"{API}/me", headers=carer)).json()["family"] is None
    assert (await client.get(f"{API}/children/{cid}", headers=carer)).status_code == 409


async def test_settings(client):
    h, _ = await make_family(client)
    st = (await client.get(f"{API}/family/settings", headers=h)).json()
    assert st == {"units": {"volume": "ml", "weight": "kg", "length": "cm", "temperature": "C"}, "wording": "nappy",
                  "llm": {"base_url": "http://llama:8080/v1", "model": "", "has_api_key": False},
                  "web_lookup": False}
    r = await client.patch(f"{API}/family/settings", headers=h, json={
        "units": {"volume": "oz"}, "wording": "diaper", "web_lookup": True,
        "llm": {"base_url": "https://llm.example/v1", "model": "qwen", "api_key": "sk-secret"}})
    st = r.json()
    assert st["units"]["volume"] == "oz" and st["units"]["weight"] == "kg"
    assert st["llm"] == {"base_url": "https://llm.example/v1", "model": "qwen", "has_api_key": True}
    assert "sk-secret" not in r.text
    # Omitted api_key keeps it; null clears it.
    st = (await client.patch(f"{API}/family/settings", headers=h, json={"llm": {"model": "m2"}})).json()
    assert st["llm"]["has_api_key"] is True
    st = (await client.patch(f"{API}/family/settings", headers=h, json={"llm": {"api_key": None}})).json()
    assert st["llm"]["has_api_key"] is False
    r = await client.patch(f"{API}/family/settings", headers=h, json={"llm": {"base_url": "ftp://x"}})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


async def test_children_crud(client):
    h, cid = await make_family(client)
    r = await client.patch(f"{API}/children/{cid}", json={"night_start": "25:00"}, headers=h)
    assert r.status_code == 422
    r = await client.patch(f"{API}/children/{cid}", json={"night_start": "18:30", "sex": None}, headers=h)
    assert r.json()["night_start"] == "18:30" and r.json()["sex"] is None
    assert (await client.delete(f"{API}/children/{cid}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/children", headers=h)).json() == []
    assert len((await client.get(f"{API}/children?archived=true", headers=h)).json()) == 1
