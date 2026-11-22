"""The plug-in extension point (plugins.py). With no plug-in, the app keeps no audio and shows nothing more."""

import tempfile
from pathlib import Path

import pytest

from frecklebubby import plugins
from frecklebubby.config import get_settings

from .conftest import make_family
from .test_cry import fake_model, post_audio, wav_bytes  # noqa: F401  (fake_model is a fixture)


@pytest.fixture
def reg(monkeypatch):
    """An empty registry for one test: what a test adds does not stay."""
    r = plugins.Registry(loaded=True)
    for mod in ("frecklebubby.plugins", "frecklebubby.services.cry", "frecklebubby.services.entries",
                "frecklebubby.services.families"):
        monkeypatch.setattr(f"{mod}.registry", r)
    return r


def files(root) -> set[str]:
    return {str(p) for p in Path(root).rglob("*") if p.is_file() and not p.name.startswith("frecklebubby.db")}


async def test_no_plugin_keeps_no_audio(client, fake_model, reg):  # noqa: F811
    h, cid = await make_family(client)
    assert (await client.get("/api/v1/config")).json()["plugins"] is False
    assert (await client.get("/api/v1/plugins", headers=h)).json() == {"settings": [], "notices": []}
    data_dir, tmp = get_settings().data_dir, tempfile.gettempdir()
    before = files(data_dir), {p.name for p in Path(tmp).glob("fb-cry-*")}
    assert (await post_audio(client, cid, h, wav_bytes(5))).status_code == 200
    r = await client.post(f"/api/v1/children/{cid}/entries", headers=h,
                          json={"type": "cry", "started_at": "2026-11-01T10:00:00Z", "ended_at": "2026-11-01T10:05:00Z"})
    assert r.status_code == 201, r.text
    assert (files(data_dir), {p.name for p in Path(tmp).glob("fb-cry-*")}) == before
    assert reg.hooks == {}


async def test_plugin_gets_the_recording_and_the_entry(client, fake_model, reg):  # noqa: F811
    got = []
    reg.on("cry_analyzed", lambda **kw: got.append(("cry", kw)))
    reg.on("entry_saved", lambda **kw: got.append(("saved", kw["entry"].type)))
    reg.on("entry_deleted", lambda **kw: got.append(("deleted", kw["entry"].id)))
    reg.on("entry_saved", lambda **kw: 1 / 0)  # a fault in a plug-in does not break the request
    h, cid = await make_family(client)
    assert (await post_audio(client, cid, h, wav_bytes(11, 8000))).status_code == 200
    kind, kw = got[0]
    assert kind == "cry" and kw["child_id"] == cid and len(kw["samples"]) == 160000  # cut to 10 s at 16 kHz
    assert kw["result"]["sound"]["is_cry"] is True
    r = await client.post(f"/api/v1/children/{cid}/entries", headers=h,
                          json={"type": "cry", "started_at": "2026-11-01T10:00:00Z", "ended_at": "2026-11-01T10:05:00Z"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert (await client.delete(f"/api/v1/entries/{eid}", headers=h)).status_code in (200, 204)
    assert got[1:] == [("saved", "cry"), ("deleted", eid)]


async def test_setting_and_notice(client, reg):
    reg.setting("share", "Share recordings", "What is kept and why.")
    reg.notice("hello", "A message", "Text for the owner.")
    h, _ = await make_family(client)
    assert (await client.get("/api/v1/config")).json()["plugins"] is True
    st = (await client.get("/api/v1/plugins", headers=h)).json()
    assert st["settings"] == [{"key": "share", "label": "Share recordings", "text": "What is kept and why.",
                               "default": True, "value": True}]
    assert [n["key"] for n in st["notices"]] == ["hello"]
    st = (await client.put("/api/v1/plugins/settings/share", headers=h, json={"value": False})).json()
    assert st["settings"][0]["value"] is False
    assert (await client.put("/api/v1/plugins/settings/other", headers=h, json={"value": False})).status_code == 404
    # the notice shows one time
    assert (await client.post("/api/v1/plugins/notices/hello/seen", headers=h)).json()["notices"] == []
    st = (await client.get("/api/v1/plugins", headers=h)).json()
    assert st["notices"] == [] and st["settings"][0]["value"] is False
