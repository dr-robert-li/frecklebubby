"""Voice commands: the keyword check, the speech-to-text route (fake Whisper) and the chat that saves all."""

import io
import struct
import wave

import pytest

from frecklebubby.services import voice

from .conftest import make_family
from .fake_llm import fake_llm_fixture, sse_events  # noqa: F401

URL = "/api/v1/voice/transcribe"
BOTTLE = {"events": [{"type": "bottle", "at": "now", "amount": 120, "unit": "ml", "milk_type": "Formula"}]}


def wav(seconds=1.0, rate=16000, channels=1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 1000) * int(rate * seconds) * channels)
    return out.getvalue()


@pytest.fixture
def whisper(monkeypatch):
    said = {"text": ""}
    monkeypatch.setattr(voice, "TRANSCRIBER", lambda audio: said["text"])
    return said


@pytest.mark.parametrize("text, command", [
    ("Hey Bubby, log a wet nappy.", "log a wet nappy."),
    ("OK Bubby, she had 120 ml.", "she had 120 ml."),
    ("Okay, Bubby. Start a nap", "Start a nap"),
    ("hey bobby how long should she sleep", "how long should she sleep"),
    ("Hey Bubby.", ""),
    ("Hey baby, who is a good girl?", None),
    ("Hey buddy, come here", None),
    ("Can you pass the wipes? Hey Bubby", None),
    ("She had 120 ml at 2.", None),
])
def test_wake(text, command):
    assert voice.wake(text) == command


async def test_transcribe_with_and_without_keyword(client, whisper):
    h, _ = await make_family(client)
    assert (await client.get("/api/v1/config")).json()["voice"] is True
    whisper["text"] = "Hey Bubby, log a wet nappy."
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(), "audio/wav")}, data={"wake": "true"})
    assert r.status_code == 200 and r.json() == {"heard": True, "text": "log a wet nappy."}
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(), "audio/wav")})
    assert r.json() == {"heard": True, "text": "Hey Bubby, log a wet nappy."}
    # Other speech near the phone: the text does not come back.
    whisper["text"] = "Can you pass the wipes?"
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(), "audio/wav")}, data={"wake": "true"})
    assert r.json() == {"heard": False, "text": ""}


async def test_transcribe_refuses_other_files(client, whisper):
    h, _ = await make_family(client)
    for bad in (b"not audio", wav(rate=44100), wav(channels=2)):
        r = await client.post(URL, headers=h, files={"file": ("v.wav", bad, "audio/wav")})
        assert r.status_code == 422, r.text
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(seconds=31), "audio/wav")})
    assert r.status_code == 422 and "30 seconds" in r.json()["detail"]
    assert (await client.post(URL, files={"file": ("v.wav", wav(), "audio/wav")})).status_code == 409  # dev sign-in: a user with no family
    # A very short sound is not sent to the model.
    whisper["text"] = "words"
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(seconds=0.1), "audio/wav")})
    assert r.json() == {"heard": False, "text": ""}


async def test_no_voice_part(client, monkeypatch):
    h, _ = await make_family(client)
    monkeypatch.setenv("VOICE", "false")
    from frecklebubby.config import get_settings
    get_settings.cache_clear()
    assert (await client.get("/api/v1/config")).json()["voice"] is False
    r = await client.post(URL, headers=h, files={"file": ("v.wav", wav(), "audio/wav")})
    assert r.status_code == 501


async def test_voice_chat_saves_unsure_with_a_flag(client, fake_llm):
    h, cid = await make_family(client)
    # The amount is not in the words. A typed message asks first; a voice command saves and says "not sure".
    fake_llm.replies.append(BOTTLE)
    r = await client.post(f"/api/v1/children/{cid}/assistant/chat", headers=h,
                          json={"message": "she had a bottle", "voice": True})
    logged = sse_events(r.text)[0][1]
    assert logged["proposals"] == [] and logged["message"] == "Logged 1 item."
    assert logged["items"][0]["unsure"] == "the amount is not in your words"
    saved = (await client.get(f"/api/v1/children/{cid}/entries?type=bottle", headers=h)).json()
    assert len(saved) == 1
    msgs = (await client.get(f"/api/v1/children/{cid}/assistant/messages", headers=h)).json()
    assert msgs[1]["logged"]["items"][0]["unsure"] == "the amount is not in your words"
    # Undo works as for all logged items.
    r = await client.post(f"/api/v1/children/{cid}/assistant/messages/{msgs[1]['id']}/undo", headers=h, json={"item": 0})
    assert r.status_code == 200 and r.json()["logged"]["items"][0]["undone"]


async def test_voice_chat_does_not_save_a_copy(client, fake_llm):
    h, cid = await make_family(client)
    fake_llm.replies.append({"events": BOTTLE["events"] * 2})
    r = await client.post(f"/api/v1/children/{cid}/assistant/chat", headers=h,
                          json={"message": "120 ml formula", "voice": True})
    logged = sse_events(r.text)[0][1]
    assert len(logged["items"]) == 1 and len(logged["proposals"]) == 1
