"""Voice commands: speech to text on the server (Whisper, optional extra "voice") and the keyword check.

The audio is not stored and not logged. The text is logged nowhere."""

import io
import logging
import re
import threading
import wave
from importlib.util import find_spec

from ..config import get_settings
from . import Invalid, ServiceError

RATE = 16000  # the page sends WAV: one channel, 16 bit, 16 kHz
MAX_SECONDS = 30
MAX_BYTES = 44 + RATE * 2 * MAX_SECONDS + 4096
MAX_WAITING = 4  # recordings that can wait for the speech model; one more gets "busy"
# The keyword: "Hey Bubby" or "OK Bubby" at the start. Whisper writes the name in more than one way.
# Not "baby" and not "buddy": parents say "hey baby" and "hey buddy" to the child.
WAKE = re.compile(r"^\W*(?:hey|hi|ok|okay|o\.k\.)\W+(?:bubby|bubbie|bubbi|buby|bubby's|bobby|bubbly|bubba|bubbe)\b\W*", re.I)
PROMPT = "Hey Bubby, OK Bubby."  # helps Whisper to write the keyword the same way each time

log = logging.getLogger(__name__)
_model = None
_lock = threading.Lock()
_waiting = 0
TRANSCRIBER = None  # tests put a function (samples) -> text here


class Busy(ServiceError):
    status = 429

    def __init__(self):
        super().__init__("The voice service is busy. Try again in a moment.")
        self.headers = {"Retry-After": "5"}


class Unavailable(ServiceError):
    status = 503

    def __init__(self):
        super().__init__("The voice service is not available now.")


class NotInstalled(ServiceError):
    status = 501

    def __init__(self):
        super().__init__("Voice commands are not installed on this server.")


def available() -> bool:
    return TRANSCRIBER is not None or (get_settings().voice and find_spec("faster_whisper") is not None)


def wake(text: str) -> str | None:
    """The command after the keyword, or None when the text does not start with the keyword."""
    m = WAKE.match(text)
    return text[m.end():].strip() if m else None


def samples(data: bytes):
    """WAV bytes -> float32 samples. Only the one format the page sends: no other decoder sees the upload."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as w:
            ok = w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == RATE and w.getcomptype() == "NONE"
            frames = w.readframes(RATE * MAX_SECONDS) if ok else b""
    except (wave.Error, EOFError) as err:
        raise Invalid("The recording is not a WAV file.") from err
    if not ok:
        raise Invalid("The recording must be WAV: one channel, 16 bit, 16 kHz.")
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        st = get_settings()
        root = st.data_dir / "models" / "whisper"
        root.mkdir(parents=True, exist_ok=True)
        _model = WhisperModel(st.whisper_model, device="cpu", compute_type="int8", download_root=str(root))
    return _model


def warm() -> None:
    """At server start, in a thread: download and load the model, so that the first command does not wait."""
    try:
        with _lock:
            _load()
        log.info("The speech model is ready.")
    except Exception as err:  # no network for the download, bad model name: voice commands answer 503
        log.warning("The speech model did not load: %s", type(err).__name__)


def _whisper(audio) -> str:
    segments, _ = _load().transcribe(audio, language=get_settings().whisper_language or None, beam_size=1,
                                    initial_prompt=PROMPT, condition_on_previous_text=False,
                                    no_speech_threshold=0.6)
    return " ".join(x.text.strip() for x in segments if x.no_speech_prob < 0.6).strip()


def transcribe(data: bytes) -> str:
    """The words in the recording ("" for silence or noise). One recording at a time; a few can wait."""
    global _waiting
    if not available():
        raise NotInstalled()
    audio = samples(data)
    if len(audio) < RATE // 4:
        return ""
    if _waiting >= MAX_WAITING:
        raise Busy()
    _waiting += 1
    try:
        with _lock:
            text = (TRANSCRIBER or _whisper)(audio)
    except ServiceError:
        raise
    except Exception as err:  # the model did not download or load
        log.warning("Speech to text failed: %s", type(err).__name__)
        raise Unavailable() from err
    finally:
        _waiting -= 1
    # Whisper can repeat the prompt for a recording with no words.
    return "" if text.strip(" .,!").lower() == PROMPT.strip(".").lower() else text
