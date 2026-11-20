"""Cry helper: what to check first, from the logs (deterministic) and, if the model files are installed, from the
sound (experimental).

Every fact in the text comes from a bundled library file (data/library). Each rule names the file and the exact
phrase that supports it; tests/test_cry.py checks that the phrase is in the file.

Combined order rule: the logs decide the order. The sound guess changes the order only when model_card.json shows
that the reason model beat the "always hungry" baseline by at least 10 points in accuracy AND in macro-F1 on
recorders it had not heard (SOUND_MARGIN); then each need's score is 0.7 x logs + 0.3 x sound probability.
Otherwise the sound guess is shown as a secondary hint only.
"""

import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA, get_settings
from ..db import utcnow
from ..knowledge.ingest import front_matter
from ..models import Child, Entry, Timer
from . import Ctx, Invalid, ServiceError
from .children import get_child
from .families import wording
from .insights import red_flags
from .sleep import predict

log = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 60.0
MIN_SECONDS = 1.0
AUDIO_TYPES = {"audio/webm", "video/webm", "audio/ogg", "audio/mp4", "video/mp4", "audio/x-m4a", "audio/m4a",
               "audio/aac", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/wave"}
FFMPEG_TIMEOUT = 20
SOUND_MARGIN = 0.10
SOUND_WEIGHT = 0.3
SOUND_TO_NEEDS = {"hungry": ["hunger"], "tired": ["tired"], "burping": ["wind"], "belly_pain": ["wind"],
                  "discomfort": ["nappy", "too_hot_or_cold"], "scared": ["cuddle"]}
FEED_TYPES = ("nursing", "bottle")


class NotInstalled(ServiceError):
    status = 501


# --- library citations ---------------------------------------------------------------------------------------------


@lru_cache
def library(name: str) -> tuple[dict, str]:
    """(front matter, body) of data/library/<name>.md."""
    return front_matter((PACKAGE_DATA / "library" / f"{name}.md").read_text())


def cite(*names: str) -> list[dict]:
    """Citations in the API shape, numbered from 1."""
    out = []
    for i, name in enumerate(names, 1):
        m = library(name)[0]
        out.append({"n": i, "kind": "bundled", **{k: m[k] for k in ("title", "publisher", "url", "year", "licence")
                                                  if m.get(k) is not None}})
    return out


# Each rule's supporting phrase, copied from the cited file (checked by a test).
SUPPORT = {
    "hunger": ("cdc-hunger-fullness-signs", "Crying is often a late sign of hunger."),
    "hunger_interval": ("cdc-breastfeeding-how-much", "most exclusively breastfed babies will feed every 2 to 4 hours"),
    "reasons": ("nhs-soothing-crying-baby", "The most common reasons for crying are:"),
    "wind": ("nhs-colic", "wind your baby after feeds"),
    "wind_bottle": ("nhs-bottle-feeding-advice", "If your baby swallows air while bottle feeding, they may feel "
                                                 "uncomfortable and cry."),
    "ill": ("nhs-soothing-crying-baby", "it can be a sign they're ill"),
    "evening": ("nhs-soothing-crying-baby", "Afternoon and evening are the most common times"),
    "age_peak": ("nhs-soothing-crying-baby", "The amount babies cry tends to increase when they're around 2 weeks old "
                                             "and then gradually reduces at around 3 months old."),
    "colic": ("nhs-colic", "cry more than 3 hours a day, 3 days a week for at least 1 week"),
    "colic_age": ("nhs-soothing-crying-baby", "This sometimes happens in babies who are under 5 months old."),
    "help_doctor": ("nhs-soothing-crying-baby", "signs of being unwell, such as a high temperature or they’re not "
                                                "interested in feeding"),
    "help_ambulance": ("nhs-soothing-crying-baby", "has not had a wet nappy in the past 8 hours"),
    "help_cry": ("nhs-colic", "your baby has a weak or high-pitched cry"),
    "never_shake": ("nhs-soothing-crying-baby", "you must never shake your baby"),
}


# --- likely needs from the logs ------------------------------------------------------------------------------------


def _dur(td: timedelta) -> str:
    m = max(0, round(td.total_seconds() / 60))
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def _interp(x: float, xs: tuple, ys: tuple) -> float:
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in zip(zip(xs, ys, strict=True), zip(xs[1:], ys[1:], strict=True), strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def _usual_gap(times: list[datetime], merge: timedelta = timedelta(minutes=30)) -> timedelta | None:
    """Median time between starts; starts closer than `merge` count as one (top-ups, cluster feeds). Needs 3 gaps."""
    starts: list[datetime] = []
    for t in sorted(times):
        if not starts or t - starts[-1] >= merge:
            starts.append(t)
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    return median(gaps) if len(gaps) >= 3 else None


def _ratio_score(r: float, cap: float) -> float:
    """Elapsed / usual: 0.5 or less -> 0.1, 1.0 -> 0.6, 1.5 or more -> 0.95 (then capped)."""
    return min(cap, _interp(r, (0.5, 1.0, 1.5), (0.1, 0.6, 0.95)))


def likely_needs(s: Session, ctx: Ctx, child: Child, now: datetime) -> list[dict]:
    """Ranked needs to check, from the child's recent logs. No model. Each: {need, score, why, citations}."""
    tz = ctx.tz
    word = wording(ctx.fam)
    she = child.name
    local = lambda dt: dt.astimezone(tz).strftime("%H:%M")  # noqa: E731
    recent = list(s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.started_at >= now - timedelta(days=7),
                                                Entry.started_at <= now + timedelta(minutes=5))
                            .order_by(Entry.started_at)))
    age_days = (now.astimezone(tz).date() - child.birthdate).days
    out: list[dict] = []

    def add(need: str, score: float, why: str, *sources: str) -> None:
        out.append({"need": need, "score": round(max(0.0, min(1.0, score)), 2), "why": why, "citations": cite(*sources)})

    # Hunger: time since the last feed against the child's own usual gap.
    feeds = [e for e in recent if e.type in FEED_TYPES]
    if feeds:
        since = now - feeds[-1].started_at
        usual = _usual_gap([e.started_at for e in feeds])
        if usual:
            add("hunger", _ratio_score(since / usual, 1.0),
                f"Last feed {_dur(since)} ago (at {local(feeds[-1].started_at)}). {she}'s usual time between feeds "
                f"is {_dur(usual)} (middle value, last 7 days). Crying is often a late sign of hunger.",
                "cdc-hunger-fullness-signs", "cdc-breastfeeding-how-much")
        elif age_days < 183:
            add("hunger", _ratio_score(since / timedelta(hours=2), 0.8),
                f"Last feed {_dur(since)} ago (at {local(feeds[-1].started_at)}). Not enough feeds are logged to know "
                f"{she}'s usual gap. The CDC says most breastfed babies feed every 2 to 4 hours.",
                "cdc-breastfeeding-how-much", "cdc-hunger-fullness-signs")
        else:
            add("hunger", 0.3, f"Last feed {_dur(since)} ago (at {local(feeds[-1].started_at)}).",
                "cdc-hunger-fullness-signs")
    else:
        add("hunger", 0.3, "No feed is logged in the last 7 days, so the app cannot compare. Hunger is one of the most "
            "common reasons for crying.", "nhs-soothing-crying-baby", "cdc-hunger-fullness-signs")

    # Wind: a feed that ended in the last 45 minutes.
    if feeds and now - (feeds[-1].ended_at or feeds[-1].started_at) <= timedelta(minutes=45):
        add("wind", 0.5, f"{she} fed {_dur(now - (feeds[-1].ended_at or feeds[-1].started_at))} ago. Babies can cry "
            "from wind after a feed. Try to wind (burp) them.", "nhs-colic", "nhs-bottle-feeding-advice")
    else:
        add("wind", 0.15, "Wind is one of the common reasons for crying.", "nhs-soothing-crying-baby")

    # Tired: time awake against the sleep prediction window.
    sleeping = s.scalar(select(Timer.id).where(Timer.child_id == child.id, Timer.type == "sleep"))
    p = None if sleeping else predict(s, child, tz, now)
    if p:
        sleeps = [e for e in recent if e.type == "sleep" and e.ended_at]
        awake = f"Awake {_dur(now - sleeps[-1].ended_at)}. " if sleeps else ""
        window = f"{she}'s next sleep window is {local(p['start'])}–{local(p['end'])}"
        if now >= p["end"]:
            score = min(0.95, 0.7 + (now - p["end"]).total_seconds() / 3600 * 0.25)
            why = f"{awake}{window}, which has passed. Tiredness is a common reason for crying."
        elif now >= p["start"]:
            score, why = 0.7, f"{awake}{window}, which is now. Tiredness is a common reason for crying."
        elif p["start"] - now <= timedelta(minutes=30):
            score, why = 0.45, f"{awake}{window}, which starts in {_dur(p['start'] - now)}."
        else:
            score, why = 0.15, f"{awake}{window}, so tiredness is less likely now."
        add("tired", score, why + " Sleep windows are common practice, not a medical standard.",
            "nhs-soothing-crying-baby")
    elif not sleeping:
        add("tired", 0.25, "No recent sleep is logged, so the app cannot compare. Tiredness is a common reason for "
            "crying.", "nhs-soothing-crying-baby")

    # Nappy: time since the last change against the usual gap.
    nappies = [e for e in recent if e.type in ("nappy", "potty")]
    if nappies:
        since = now - nappies[-1].started_at
        usual = _usual_gap([e.started_at for e in nappies], timedelta(minutes=10))
        score = _ratio_score(since / usual, 0.7) if usual else 0.3
        usual_text = f" {she}'s usual time between changes is {_dur(usual)}." if usual else ""
        add("nappy", score, f"Last {word} change {_dur(since)} ago (at {local(nappies[-1].started_at)}).{usual_text} "
            f"A dirty or wet {word} is a common reason for crying.", "nhs-soothing-crying-baby")
    else:
        add("nappy", 0.3, f"No {word} change is logged in the last 7 days. Check the {word}: a dirty or wet {word} "
            "is a common reason for crying.", "nhs-soothing-crying-baby")

    # Unwell: a temperature reading, recent medicine, or an allergic reaction.
    temps = [e for e in recent if e.type == "temperature" and e.started_at >= now - timedelta(hours=24)]
    hot = [e for e in temps if e.data["celsius"] >= 38.0 or e.data["celsius"] < 36.0]
    meds = [e for e in recent if e.type == "medicine" and e.started_at >= now - timedelta(hours=8)]
    allergic = [e for e in recent if e.type == "solids" and e.data.get("reaction") == "ALLERGIC"
                and e.started_at >= now - timedelta(hours=48)]
    if allergic:
        foods = ", ".join(f["name"] for f in allergic[-1].data.get("foods", []))
        add("allergic", 1.0, f"An allergic reaction was logged at {local(allergic[-1].started_at)} ({foods}). See the "
            "warning above.", "nhs-food-allergies")
    if hot:
        c = hot[-1].data["celsius"]
        add("unwell", 0.9, f"A temperature of {c:g} °C was logged at {local(hot[-1].started_at)}. The NHS says crying "
            "you cannot soothe can be a sign a baby is ill. Contact a doctor if they have signs of being unwell, such "
            "as a high temperature.", "nhs-soothing-crying-baby", "nhs-fever-in-children")
    elif meds:
        add("unwell", 0.5, f"Medicine ({meds[-1].data['name']}) was logged at {local(meds[-1].started_at)}, so {she} "
            "may be unwell. If the cry does not sound like their normal cry, get medical help.",
            "nhs-soothing-crying-baby", "nhs-colic")

    # Always worth a check (NHS list of common reasons).
    add("too_hot_or_cold", 0.15, f"Check that {she} is not too hot or too cold.", "nhs-soothing-crying-baby")
    add("cuddle", 0.15, "Babies also cry when they want a cuddle, or when they are bored or overstimulated.",
        "nhs-soothing-crying-baby")

    # Age and time of day (NHS crying page: more crying from about 2 weeks, less from about 3 months, most in the
    # afternoon and evening). shortcut: "afternoon and evening" = 12:00-23:59 local; the source gives no hours.
    hour = now.astimezone(tz).hour
    if 14 <= age_days <= 120 and hour >= 12:
        add("evening_crying", 0.35, f"{she} is {age_days // 7} weeks old and it is the afternoon or evening. The NHS "
            "says crying often increases from about 2 weeks old, eases from about 3 months, and is most common in the "
            "afternoon and evening.", "nhs-soothing-crying-baby")

    # Colic pattern from logged crying (under 5 months).
    if age_days < 152:
        per_day: dict = {}
        for e in recent:
            if e.type == "cry" and e.ended_at:
                d = e.started_at.astimezone(tz).date()
                per_day[d] = per_day.get(d, 0) + (e.ended_at - e.started_at).total_seconds()
        long_days = sum(1 for v in per_day.values() if v > 3 * 3600)
        if long_days >= 3:
            add("colic", 0.5, f"Crying of more than 3 hours was logged on {long_days} of the last 7 days. The NHS says "
                "a baby who cries more than 3 hours a day, 3 days a week for at least 1 week, but is otherwise "
                "healthy, may have colic. Talk to your child health nurse or doctor.", "nhs-colic")

    return sorted(out, key=lambda x: -x["score"])


# --- things to try (condensed from the NHS pages, with citations) -------------------------------------------------


def suggestions(word: str) -> list[dict]:
    t = lambda text, *src: {"kind": "try", "text": text, "citations": cite(*src)}  # noqa: E731
    h = lambda text, *src: {"kind": "help", "text": text, "citations": cite(*src)}  # noqa: E731
    return [
        t("Hold your baby close or use a sling. Move about gently, sway, talk or sing.", "nhs-soothing-crying-baby"),
        t("If you breastfeed, let your baby suckle at the breast.", "nhs-soothing-crying-baby"),
        t("Wind your baby after feeds. Hold them upright during feeds so that they swallow less air.", "nhs-colic"),
        t("Try gentle noise in the background, or something to listen to or look at.", "nhs-soothing-crying-baby"),
        t("Rock your baby in the pram, or go for a walk or a drive. If they fall asleep in the car seat, take them "
          "out as soon as possible and put them on a firm, flat surface to sleep.", "nhs-soothing-crying-baby"),
        t("Gently stroke your baby's back while you hold them against you.", "nhs-soothing-crying-baby"),
        t("Try a warm bath. It calms some babies, but makes others cry more.", "nhs-soothing-crying-baby"),
        t("Too much rocking and singing can keep a baby awake. Lying them down after a feed can help.",
          "nhs-soothing-crying-baby"),
        t("If the crying makes you very stressed, put your baby in their cot or pram, make sure they are safe, and go "
          "to another room for a short time (for example 10 minutes) to calm down. Never shake your baby.",
          "nhs-soothing-crying-baby"),
        h("Contact a doctor if your baby cries all the time and you cannot soothe them, or the cry does not sound like "
          "their normal cry, and they have signs of being unwell, such as a high temperature or no interest in "
          "feeding.", "nhs-soothing-crying-baby"),
        h("Call an ambulance (your local emergency number) if your baby has a fit; has blue, grey, pale or blotchy "
          "skin, lips or tongue; is unresponsive, floppy or not waking up as easily as usual; has difficulty "
          "breathing; is being violently sick a lot; has a high or low temperature; has a rash that does not fade "
          f"when you press it; or has not had a wet {word} in the past 8 hours.", "nhs-soothing-crying-baby"),
        h("Go to the emergency department or call an ambulance if your baby has a weak or high-pitched cry, or the "
          "cry does not sound like their normal cry.", "nhs-colic"),
    ]


# --- sound model (optional) ----------------------------------------------------------------------------------------


def model_dir() -> Path:
    st = get_settings()
    d = st.cry_model_dir or st.data_dir / "models" / "cry"
    if st.cry_model_dir or (d / "model_card.json").is_file():
        return d
    return st.bundled_data_dir / "models" / "cry"


_models: dict = {}


def load_models() -> dict | None:
    """{"card", "detector", "reason"} or None when the files or onnxruntime are missing. Cached per file version."""
    d = model_dir()
    files = [d / "model_card.json", d / "cry_detector.onnx", d / "cry_reason.onnx"]
    if not all(f.is_file() for f in files):
        return None
    key = (str(d), *(f.stat().st_mtime_ns for f in files))
    if _models.get("key") != key:
        try:
            import onnxruntime as ort
        except ImportError:
            log.warning("Cry model files are in %s, but onnxruntime is not installed (extra 'cry').", d)
            return None
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        card = json.loads(files[0].read_text())
        _models.clear()
        _models.update(key=key, card=card,
                       detector=ort.InferenceSession(str(files[1]), opts, providers=["CPUExecutionProvider"]),
                       reason=ort.InferenceSession(str(files[2]), opts, providers=["CPUExecutionProvider"]))
    return _models


def check_upload(data: bytes, content_type: str) -> None:
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind not in AUDIO_TYPES:
        raise Invalid("audio: send a WebM, Ogg, MP4, MP3 or WAV recording.")
    if not data:
        raise Invalid("audio: the recording is empty.")
    if len(data) > MAX_BYTES:
        raise Invalid("audio: the recording is too large (10 MB or less).")


def decode(data: bytes):
    """Browser recording -> mono float32 at 16 kHz, with ffmpeg. The upload exists only in a temp file that is
    deleted before this returns. Audio is never stored or logged."""
    import numpy as np

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise NotInstalled("Sound analysis needs ffmpeg on the server. Ask the person who runs this server to "
                           "install it.")
    with tempfile.TemporaryDirectory(prefix="fb-cry-") as tmp:
        src = Path(tmp) / "upload"
        src.write_bytes(data)
        try:
            r = subprocess.run(
                [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file",
                 "-i", str(src), "-t", str(MAX_SECONDS + 1), "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
                 "-f", "f32le", "pipe:1"],
                capture_output=True, timeout=FFMPEG_TIMEOUT, check=False)
        except subprocess.TimeoutExpired as err:
            raise Invalid("audio: the recording took too long to read.") from err
    if r.returncode != 0:
        raise Invalid("audio: the server could not read this recording.")
    wav = np.frombuffer(r.stdout, dtype=np.float32)
    seconds = len(wav) / 16000
    if seconds > MAX_SECONDS + 0.5:
        raise Invalid("audio: the recording is longer than 60 seconds.")
    if seconds < MIN_SECONDS:
        raise Invalid("audio: the recording is too short (1 second or more).")
    return wav


def _smooth(on, size: int):
    """Median filter for a 0/1 frame series (odd size), edges repeated."""
    import numpy as np

    if size <= 1:
        return on
    k = size // 2
    padded = np.pad(on.astype(np.int32), k, mode="edge")
    window = np.lib.stride_tricks.sliding_window_view(padded, size).sum(axis=1)
    return window > k


def infer(models: dict, wav) -> dict:
    """Run both models. Separate from analyze() so tests can replace it."""
    import numpy as np

    card = models["card"]
    det = card["detector"]
    x = wav[None, :].astype(np.float32)
    probs = models["detector"].run(None, {"audio": x})[0]
    secs = []
    for c in range(probs.shape[1]):
        on = _smooth(probs[:, c] >= det["threshold"], det["median_frames"])
        secs.append(min(float(on.sum()) * det["frame_seconds"], len(wav) / 16000))
    cry_s, snore_s = secs[det["labels"].index("cry")], secs[det["labels"].index("snore")]
    is_cry = cry_s >= det["is_cry_min_seconds"]
    reasons = []
    if is_cry:
        p = models["reason"].run(None, {"audio": x})[0]
        reasons = sorted(({"label": lab, "probability": round(float(v), 3)}
                          for lab, v in zip(card["reason"]["labels"], p, strict=True)), key=lambda r: -r["probability"])
    return {"is_cry": bool(is_cry), "cry_seconds": round(cry_s, 1), "snore_seconds": round(snore_s, 1),
            "reasons": reasons}


def sound_useful(card: dict) -> bool:
    r = card["reason"]
    m, base = r["metrics"], r["baselines"]
    best_f1 = max(b["macro_f1"] for b in base.values())
    return (m["accuracy"] >= base["always_hungry"]["accuracy"] + SOUND_MARGIN
            and m["macro_f1"] >= best_f1 + SOUND_MARGIN)


def reliability(card: dict) -> str:
    r = card["reason"]
    acc, hungry = r["metrics"]["accuracy"], r["baselines"]["always_hungry"]["accuracy"]
    text = (f"In tests on babies the model had not heard, it was right about {round(acc * 10)} times in 10. "
            f"Always guessing \"hungry\" was right about {round(hungry * 10)} times in 10.")
    if not sound_useful(card):
        text += " So the sound guess is only a hint. Check the list above first."
    return text


NOT_INSTALLED = "Sound analysis is not installed on this server."


def _sound_block(sound: dict | None, card: dict | None) -> dict:
    if card is None:
        return {"installed": False, "is_cry": False, "cry_seconds": 0.0, "snore_seconds": 0.0, "reasons": [],
                "experimental": True, "reliability": NOT_INSTALLED}
    return {"installed": True, **(sound or {"is_cry": False, "cry_seconds": 0.0, "snore_seconds": 0.0, "reasons": []}),
            "experimental": True, "reliability": reliability(card)}


def combine(needs: list[dict], sound: dict, card: dict | None) -> list[dict]:
    """Logs first; the sound changes the order only when the model card shows a clear margin (see module doc)."""
    probs: dict[str, float] = {}
    for r in sound.get("reasons", []):
        for need in SOUND_TO_NEEDS.get(r["label"], []):
            probs[need] = max(probs.get(need, 0.0), r["probability"])
    w = SOUND_WEIGHT if card and probs and sound_useful(card) else 0.0
    top = sound["reasons"][0]["label"] if sound.get("reasons") else None
    out = []
    for n in needs:
        why = n["why"]
        if top and n["need"] in SOUND_TO_NEEDS.get(top, []):
            why += " The sound guess (experimental) also points to this."
        out.append({"need": n["need"], "why": why, "score": (1 - w) * n["score"] + w * probs.get(n["need"], 0.0)})
    out.sort(key=lambda x: -x["score"])
    return [{"need": x["need"], "why": x["why"]} for x in out[:5]]


def _help(s: Session, ctx: Ctx, child: Child, now: datetime, sound: dict | None, card: dict | None) -> dict:
    word = wording(ctx.fam)
    needs = likely_needs(s, ctx, child, now)
    block = _sound_block(sound, card)
    return {"sound": block, "likely_needs": needs, "suggestions": suggestions(word),
            "urgent": red_flags(s, child, ctx.tz, now, word), "combined": combine(needs, block, card)}


def help(s: Session, ctx: Ctx, child_id: int, now: datetime | None = None) -> dict:  # noqa: A001
    """What to check, from the logs only (no audio)."""
    child = get_child(s, ctx, child_id)
    models = load_models()
    return _help(s, ctx, child, now or utcnow(), None, models["card"] if models else None)


def analyze(s: Session, ctx: Ctx, child_id: int, data: bytes, content_type: str, now: datetime | None = None) -> dict:
    """What to check, from the logs and the sound. The audio is not stored."""
    child = get_child(s, ctx, child_id)
    check_upload(data, content_type)
    models = load_models()
    sound = infer(models, decode(data)) if models else None
    return _help(s, ctx, child, now or utcnow(), sound, models["card"] if models else None)


def context_lines(s: Session, ctx: Ctx, child: Child, now: datetime) -> str:
    """Short text for the assistant prompt when the question is about crying."""
    top = likely_needs(s, ctx, child, now)[:3]
    return "Crying check from the logs (most likely first): " + " ".join(f"{n['need']}: {n['why']}" for n in top)
