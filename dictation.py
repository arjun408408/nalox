"""dictation.py — Nalox v9.0: TEXT-FIRST input. The ears are GONE.

History (why this module exists): through v8.x Nalox listened
ALL the time — a wake-word worker fleet decoding local Whisper
models around the clock. On the owner's PC that pipeline was
the sole bottleneck and the crash source: worker processes
died on model loads, queues saturated, and his speech was lost
while the brain (proven fast on TEXT via Telegram all along)
sat idle. The owner's order, 2026-11-16 19:40 IST: "তুমি ওই
ইয়ার্সের ফিচার্সটাই হাটিয়ে দাও… ও শুধু টেক্সটই পড়তে পারবে
এমন সিস্টেম করো।"

v9.0 architecture — Nalox reads TEXT. Input arrives as:
  * typed text (the input rows in both windows, Telegram), or
  * ONE-SHOT DICTATION (this module): he presses the mic
    button / the global hotkey (or a dictation is armed for
    him — Command Center open, or the follow-up window after
    a reply), speaks, pauses — the clip goes to CLOUD
    transcription (Groq Whisper first, the path that
    field-worked all day at 3–4 s; Gemini audio as fallback),
    and the resulting text is shown in the input box and
    auto-sent to the brain exactly like a typed message.

There is NO wake word, NO always-on listening, NO local
speech model and NO worker process anywhere in this design.
Nothing in this module imports faster-whisper or spawns a
subprocess for hearing. Recording happens in the main
process via sounddevice, only while a dictation is active.

The cloud-STT helpers, the transcription guards (garbage /
script lock / prompt echo) and the mic picker below are
ported from the retired ears.py — they were the parts of the
old ears that field-WORKED (the cloud path heard him at
3–4 s while the local fleet stalled). The local decode
machinery is deliberately NOT ported.
"""

import collections
import io
import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
import wave

import numpy as np
import requests

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - sounddevice missing
    sd = None

log = logging.getLogger("nalox.dictation")

SAMPLE_RATE = 16000

# --------------------------------------- language lock (v4.2, kept)
# Arjun speaks ONLY these three languages. A transcription in
# anything else is by definition a cloud-STT hallucination and
# is dropped, never delivered (the v8.0 field log's Chinese
# hallucination is the canonical case).
ALLOWED_LANGS = {"en", "bn", "hi"}

# Vocabulary bias for the cloud transcribers (kept short on
# purpose — a long prompt starts leaking into the output, and
# _looks_like_prompt_echo drops any transcription that parrots
# it back verbatim).
COMMAND_PROMPT = ("Nalox, YouTube, Chrome, খোলো, করো, গান বাজাও, "
                  "কেমন আছো, খবর, कैसे हो, गाना बजाओ")

_HALLUCINATION_PHRASES = [
    "thank you for watching",
    "thanks for watching",
    "ご視聴ありがとうございました",   # "thank you for watching" (JP)
    "ご視聴ありがとう",
    "subtitles by",
    "please subscribe",
    "subscribe to my channel",
    "don't forget to subscribe",
    "dont forget to subscribe",
]


def _is_word_char(ch):
    """Letters/digits in ANY script, plus combining marks (Bengali /
    Devanagari vowel signs are marks, not letters — they still make
    the character part of a word, not punctuation)."""
    return ch.isalnum() or unicodedata.category(ch).startswith("M")


def is_garbage(text):
    """True if a transcription is STT noise, not speech (v4.2).

    Catches what a transcriber invents from room silence:
      (a) empty / whitespace-only;
      (b) punctuation floods — over 55% of the non-space characters
          are not word characters ("....,,,,....");
      (c) known hallucination phrases ("thank you for watching",
          "please subscribe", ...);
      (d) one token repeated to death — the most common token is
          >= 60% of at least 4 tokens ("eee eee eee eee").
    Real English / Bengali / Hindi sentences pass easily.
    """
    if text is None:
        return True
    stripped = str(text).strip()
    if not stripped:
        return True  # (a)
    core = [c for c in stripped if not c.isspace()]
    if not core:
        return True
    non_word = sum(1 for c in core if not _is_word_char(c))
    if non_word / len(core) > 0.55:
        return True  # (b)
    lowered = stripped.lower()
    squashed = re.sub(r"\s+", " ",
                      re.sub(r"[^\w]+", " ", lowered)).strip()
    for phrase in _HALLUCINATION_PHRASES:
        if phrase in lowered or phrase in squashed:
            return True  # (c)
    tokens = squashed.split()
    if len(tokens) >= 4:
        common = collections.Counter(tokens).most_common(1)[0][1]
        if common / len(tokens) >= 0.6:
            return True  # (d)
    return False


def _script_of(ch):
    """'bn' / 'hi' / 'latin' / '' for one character (v4.3)."""
    code = ord(ch)
    if 0x0980 <= code <= 0x09FF:
        return "bn"       # Bengali block
    if 0x0900 <= code <= 0x097F:
        return "hi"       # Devanagari block
    if ch.isalpha():
        try:
            if "LATIN" in unicodedata.name(ch):
                return "latin"
        except Exception:
            pass
    return ""


def _script_plausible(text):
    """True when ≥70% of the letters are Latin/Bengali/Devanagari.

    The detected-language LABEL from a transcriber is often
    wrong (Bengali heard as "ur"/"tr"), but the TEXT is what
    matters. If the characters are overwhelmingly from Arjun's
    three scripts, the transcription is real speech in one of
    his languages — whatever the label says.
    """
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return False
    good = sum(1 for ch in letters if _script_of(ch))
    return good / len(letters) >= 0.70


def _script_lang(text, detected):
    """The language to report for a plausible transcription: the
    dominant script wins; otherwise the detected label if allowed."""
    counts = {"bn": 0, "hi": 0, "latin": 0}
    for ch in (text or ""):
        kind = _script_of(ch)
        if kind:
            counts[kind] += 1
    best = None
    for kind in ("bn", "hi", "latin"):
        if counts[kind] > 0 and (best is None
                                 or counts[kind] > counts[best]):
            best = kind
    if best is not None:
        return {"bn": "bn", "hi": "hi", "latin": "en"}[best]
    return detected if detected in ALLOWED_LANGS else "en"


def _echo_tokens(s):
    """Whitespace tokens, punctuation-stripped (script-safe: no
    regex \\w, which would shred Bengali/Devanagari words at
    their vowel signs)."""
    return [t.strip(" .,!?।") for t in (s or "").lower().split()
            if t.strip(" .,!?।")]


def _looks_like_prompt_echo(text, prompt):
    """True if a transcription just parrots the bias prompt.

    The guard is deliberately narrow so real commands can never
    trip it: the prompt needs >= 3 tokens, and the output must
    either BE the prompt or BEGIN with its full token run
    (>= 4 tokens) while being no longer than the prompt itself
    (+1 token). A real command ("nalox open chrome",
    "গান বাজাও") shares at most the first token or two and
    always passes.
    """
    ptoks = _echo_tokens(prompt)
    if len(ptoks) < 3:
        return False
    ttoks = _echo_tokens(text)
    if not ttoks:
        return False
    if ttoks == ptoks:
        return True
    k = min(len(ptoks), len(ttoks))
    return (k >= 4 and ttoks[:k] == ptoks[:k]
            and len(ttoks) <= len(ptoks) + 1)


# --------------------------------------------- status lines
_status_cb = None


def set_status_callback(cb):
    """nalox.py routes one-line status events (e.g. "[mic]
    connected …") to the HUD/logbook through here."""
    global _status_cb
    _status_cb = cb


def _fire_status(msg):
    cb = _status_cb
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


# ------------------------------------------------ mic level
# The HUD / Command Center mic meters read these. The level is
# fed ONLY by an active dictation's recorder — idle means flat,
# which is the truth in a push-to-talk world.
_level_lock = threading.Lock()
_level_value = 0.0
_level_beat_t = None          # last time a block beat the gate


def _note_level(level, beat):
    global _level_value, _level_beat_t
    with _level_lock:
        # light smoothing so the meter does not jitter per block
        _level_value = max(float(level),
                           _level_value * 0.6)
        if beat:
            _level_beat_t = time.monotonic()


def _decay_level():
    global _level_value
    with _level_lock:
        _level_value *= 0.7


def get_level():
    """Current smoothed mic level, 0..1 (0 when not dictating)."""
    with _level_lock:
        return _level_value


def mic_activity():
    """(level, seconds since a block last beat the speech gate —
    None when nothing has beaten it since boot)."""
    with _level_lock:
        lvl = _level_value
        beat = _level_beat_t
    if beat is None:
        return lvl, None
    return lvl, max(0.0, time.monotonic() - beat)


# --------------------------------------------- mic picking
# Ported from ears.py (the v7.1 hectorg2211 import): an
# explicitly configured mic always wins; in auto mode the
# default input is probed ONCE per process — if it is dead
# silent (a stale Bluetooth default), the loudest other input
# is used instead.
_PROBE_SECONDS = 0.5
_PROBE_MIN_PEAK = 0.001
_PROBE_MAX_SCAN = 6
_probe_cache = {"done": False, "device": None}


def _device_name(idx):
    try:
        if idx is None:
            return "system default microphone"
        return sd.query_devices(idx)["name"]
    except Exception:
        return "system default microphone"


def _probe_device_peak(idx):
    """Peak level of a short live probe on `idx` (or None if the
    device cannot be opened). Never raises."""
    try:
        peak = [0.0]

        def _cb(indata, frames, t_, status):
            try:
                p = float(np.max(np.abs(indata))) if frames else 0.0
            except Exception:
                p = 0.0
            if p > peak[0]:
                peak[0] = p

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype="float32", device=idx,
                            callback=_cb):
            time.sleep(_PROBE_SECONDS)
        return peak[0]
    except Exception:
        return None


def _probe_inputs():
    """Probe the default input; if it hears nothing, scan the
    other inputs and return the loudest one's index (or None to
    keep the default). Runs at most once per process."""
    if sd is None:
        return None
    try:
        default = sd.default.device[0]
    except Exception:
        return None
    if default is None or default < 0:
        return None
    peak = _probe_device_peak(default)
    if peak is None or peak >= _PROBE_MIN_PEAK:
        return None            # default works (or can't probe)
    best_idx, best_peak = None, _PROBE_MIN_PEAK
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    scanned = 0
    for i, dev in enumerate(devices):
        if i == default or scanned >= _PROBE_MAX_SCAN:
            continue
        try:
            if dev.get("max_input_channels", 0) < 1:
                continue
        except Exception:
            continue
        scanned += 1
        p = _probe_device_peak(i)
        if p is not None and p > best_peak:
            best_idx, best_peak = i, p
    if best_idx is not None:
        _fire_status(
            f"[mic] default mic silent — using "
            f"{_device_name(best_idx)} instead")
    return best_idx


def pick_input_device(cfg):
    """sounddevice input index for dictation, or None (default).

    cfg["mic_device"] (a name substring) wins when set.
    Otherwise the default input, probed once per process: a
    dead-silent default falls back to the loudest other input.
    """
    if sd is None:
        return None
    name = (cfg or {}).get("mic_device") or ""
    if name:
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if name.lower() in dev["name"].lower() \
                        and dev["max_input_channels"] > 0:
                    return i
        except Exception:
            pass
        return None
    if not _probe_cache["done"]:
        _probe_cache["done"] = True
        _probe_cache["device"] = _probe_inputs()
    return _probe_cache["device"]


# --------------------------------------- cloud transcription
# Ported from ears.py's cloud ears — the path that WORKED in
# the field ("heard via cloud:groq", 3–4 s). v9.0 order per
# the owner's brief: Groq Whisper FIRST, Gemini audio as the
# fallback. There is NO local fallback — that is the point.
CLOUD_STT_TIMEOUT = 8.0        # per provider attempt (seconds)
_GEMINI_STT_URL = ("https://generativelanguage.googleapis.com"
                   "/v1beta/models/{model}:generateContent")
_GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_GROQ_STT_MODEL = "whisper-large-v3"
_STT_INSTRUCTION = (
    "Transcribe exactly what is said in this audio, word for "
    "word, in the speaker's own language and script (English, "
    "Bengali or Hindi). Output ONLY the transcription — no "
    "translation, no commentary, no quotation marks.")

# Groq 429 retry: the free plan's per-minute window resets
# continuously, so a rate-limited transcription waits briefly
# and retries INSIDE the attempt budget instead of failing.
_RL_DELAYS_S = (0.4, 1.2)
_RL_JITTER_S = 0.3
_RL_MIN_FIT_S = 0.25


def _rl_delay(attempt):
    import random
    base = _RL_DELAYS_S[min(attempt, len(_RL_DELAYS_S) - 1)]
    return base + random.uniform(0.0, _RL_JITTER_S)


def _rl_sleep(seconds, deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        return False
    time.sleep(min(seconds, left))
    return deadline - time.monotonic() >= _RL_MIN_FIT_S


def cloud_ear_provider(cfg):
    """"groq" / "gemini" / None — which cloud transcriber would
    serve dictation (v9.0 order: Groq first). Used by Doctor."""
    cfg = cfg or {}
    if str(cfg.get("cloud_ears") or "auto").strip().lower() == "off":
        return None
    if (cfg.get("groq_api_key") or "").strip():
        return "groq"
    if (cfg.get("gemini_api_key") or "").strip():
        return "gemini"
    return None


def _wav_bytes(audio_f32):
    """float32 mono 16 kHz numpy array -> 16-bit PCM WAV bytes."""
    pcm = (np.clip(audio_f32, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _clean_cloud_text(text):
    """The guard chain every cloud transcription passes before
    it may become a command (ported from ears.py): instruction
    echo, garbage, the {en,bn,hi} script lock, prompt echo.
    Returns (text, lang) or None."""
    if not text:
        return None
    text = str(text).strip()
    if "transcribe exactly" in text.lower():
        return None                    # the model echoed the ask
    if is_garbage(text):
        return None
    if not _script_plausible(text):
        return None                    # out-of-set hallucination
    if _looks_like_prompt_echo(text, COMMAND_PROMPT):
        return None
    return text, _script_lang(text, "en")


def _cloud_groq_wav(wav, cfg, timeout):
    """Groq Whisper on WAV bytes -> raw text or None."""
    key = (cfg.get("groq_api_key") or "").strip()
    if not key:
        return None
    deadline = time.monotonic() + max(1.0, float(timeout))
    attempt = 0
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        try:
            resp = requests.post(
                _GROQ_STT_URL,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"model": _GROQ_STT_MODEL,
                      "prompt": COMMAND_PROMPT},
                timeout=left)
        except Exception:
            return None
        if getattr(resp, "status_code", 0) == 429 \
                and attempt < len(_RL_DELAYS_S):
            if _rl_sleep(_rl_delay(attempt), deadline):
                attempt += 1
                continue
            return None
        break
    if getattr(resp, "status_code", 0) != 200:
        return None
    try:
        return (resp.json().get("text") or "").strip() or None
    except Exception:
        return None


def _cloud_gemini_audio(b64, mime, cfg, timeout):
    """Gemini audio transcription -> raw text or None."""
    import base64
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        return None
    model = cfg.get("gemini_model") or "gemini-2.5-flash"
    try:
        resp = requests.post(
            _GEMINI_STT_URL.format(model=model),
            headers={"x-goog-api-key": key,
                     "Content-Type": "application/json"},
            json={"contents": [{"parts": [
                {"text": _STT_INSTRUCTION},
                {"inline_data": {"mime_type": mime,
                                 "data": b64}}]}],
                "generationConfig": {"temperature": 0}},
            timeout=timeout)
        if getattr(resp, "status_code", 0) != 200:
            return None
        data = resp.json()
        parts = (data["candidates"][0]["content"]["parts"])
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception:
        return None


def transcribe_cloud(audio_f32, cfg, timeout=CLOUD_STT_TIMEOUT):
    """One-shot cloud transcription of a recorded clip.

    Groq Whisper first, Gemini audio as fallback (v9.0 brief).
    Returns (text, lang, "cloud:groq"|"cloud:gemini") or None.
    Honors cfg cloud_ears == "off" (voice clips never leave the
    laptop — with the local ears gone, dictation then simply
    cannot run and the caller speaks the couldn't-hear line).
    """
    cfg = cfg or {}
    if str(cfg.get("cloud_ears") or "auto").strip().lower() == "off":
        log.info("[dictation] cloud transcription is OFF "
                 "(cloud_ears=off) — dictation cannot run")
        return None
    if audio_f32 is None or len(audio_f32) < SAMPLE_RATE * 0.25:
        return None
    wav = _wav_bytes(audio_f32)
    raw = _cloud_groq_wav(wav, cfg, timeout)
    if raw:
        got = _clean_cloud_text(raw)
        if got:
            return got[0], got[1], "cloud:groq"
    import base64
    raw = _cloud_gemini_audio(base64.b64encode(wav).decode(),
                              "audio/wav", cfg, timeout)
    if raw:
        got = _clean_cloud_text(raw)
        if got:
            return got[0], got[1], "cloud:gemini"
    return None


_MIME_BY_EXT = {".ogg": "audio/ogg", ".oga": "audio/ogg",
                ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
                ".wav": "audio/wav", ".webm": "audio/webm"}


def transcribe_cloud_bytes(data, filename, cfg,
                           timeout=CLOUD_STT_TIMEOUT):
    """Cloud transcription of an audio FILE's bytes (Telegram
    voice notes — v9.0 routes them through the SAME function
    family as dictation: Groq Whisper first with the real
    filename, Gemini inline audio as fallback; the raw bytes
    pass through — no local decode anywhere).

    Returns (text, lang, source) or None."""
    cfg = cfg or {}
    if not data:
        return None
    if str(cfg.get("cloud_ears") or "auto").strip().lower() == "off":
        log.info("[dictation] cloud transcription is OFF "
                 "(cloud_ears=off) — voice note not transcribed")
        return None
    ext = os.path.splitext(filename or "")[1].lower()
    key = (cfg.get("groq_api_key") or "").strip()
    if key:
        deadline = time.monotonic() + max(1.0, float(timeout))
        attempt = 0
        resp = None
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                resp = requests.post(
                    _GROQ_STT_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (filename or "voice.ogg",
                                    data)},
                    data={"model": _GROQ_STT_MODEL,
                          "prompt": COMMAND_PROMPT},
                    timeout=left)
            except Exception:
                resp = None
                break
            if getattr(resp, "status_code", 0) == 429 \
                    and attempt < len(_RL_DELAYS_S):
                if _rl_sleep(_rl_delay(attempt), deadline):
                    attempt += 1
                    continue
            break
        if resp is not None \
                and getattr(resp, "status_code", 0) == 200:
            try:
                raw = (resp.json().get("text") or "").strip()
            except Exception:
                raw = ""
            got = _clean_cloud_text(raw)
            if got:
                return got[0], got[1], "cloud:groq"
    import base64
    raw = _cloud_gemini_audio(
        base64.b64encode(data).decode(),
        _MIME_BY_EXT.get(ext, "audio/ogg"), cfg, timeout)
    if raw:
        got = _clean_cloud_text(raw)
        if got:
            return got[0], got[1], "cloud:gemini"
    return None


# ------------------------------------------------ hotkey
# The global dictation hotkey is registered with the Windows
# RegisterHotKey API from nalox.py (stdlib ctypes, no new
# dependency). parse_hotkey turns the Settings string
# ("ctrl+alt+space") into (modifier mask, virtual-key code) —
# pure and unit-testable off Windows.
_MOD_BITS = {"ctrl": 0x0002, "control": 0x0002,
             "alt": 0x0001, "shift": 0x0004,
             "win": 0x0008, "windows": 0x0008}
_VK_SPECIAL = {"space": 0x20, "enter": 0x0D, "return": 0x0D,
               "tab": 0x09, "esc": 0x1B, "escape": 0x1B}


def parse_hotkey(spec):
    """'ctrl+alt+space' -> (0x0003, 0x20). Letters/digits map
    to their VK codes; f1..f24 supported. Returns None for
    anything unparsable (the hotkey then simply stays off)."""
    parts = [p.strip().lower() for p in str(spec or "").split("+")
             if p.strip()]
    if len(parts) < 2:
        return None
    mods = 0
    key = None
    for part in parts:
        if part in _MOD_BITS:
            mods |= _MOD_BITS[part]
        elif key is None:
            key = part
        else:
            return None
    if not mods or key is None:
        return None
    if key in _VK_SPECIAL:
        return mods, _VK_SPECIAL[key]
    if len(key) == 1 and key.isalnum():
        return mods, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return mods, 0x70 + n - 1
    return None


# ------------------------------------------------ recorder
_BLOCK = 1600                    # 100 ms blocks at 16 kHz
_FLOOR_BLOCKS = 8                # first ~0.8 s sets the floor
_GATE_MIN = 0.008                # absolute speech-gate floor


def _block_rms(block):
    try:
        if block is None or len(block) == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(
            np.asarray(block, dtype=np.float64)))))
    except Exception:
        return 0.0


def _default_stream_factory(callback, device):
    """Open the real sounddevice input stream (main process —
    no worker). Returns the stream object UNSTARTED — the
    Dictation starts it (the factory contract, shared with
    the test fakes)."""
    if sd is None:
        raise RuntimeError("sounddevice is not available")
    return sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                          dtype="float32", blocksize=_BLOCK,
                          device=device, callback=callback)


class Dictation:
    """One-shot push-to-talk dictation (v9.0).

    Lifecycle: idle -> recording (manual trigger; a no-speech
    onset deadline applies) or idle -> followup (armed after a
    reply / on Command Center open; closes silently if he says
    nothing inside the window) -> transcribing -> idle.

    Callbacks (all optional, all fired off the UI thread):
      on_text(text, lang, source, rec_s, tx_s)
      on_empty(had_speech)   — nothing usable came back
      on_state(state, seconds_left) — "recording" / "followup"
          (seconds_left = the arm window while no speech yet,
          None once speech started) / "transcribing" / "idle"
      on_mic_error()         — the mic could not be opened

    Test seams: `stream_factory(callback, device)` and
    `transcribe_fn(audio, cfg)` are injectable.
    """

    def __init__(self, cfg, on_text=None, on_empty=None,
                 on_state=None, on_mic_error=None,
                 stream_factory=None, transcribe_fn=None):
        self.cfg = cfg or {}
        self._on_text = on_text
        self._on_empty = on_empty
        self._on_state = on_state
        self._on_mic_error = on_mic_error
        self._factory = stream_factory or _default_stream_factory
        self._transcribe = transcribe_fn or transcribe_cloud
        self._lock = threading.Lock()
        self._state = "idle"
        self._stream = None
        self._chunks = []
        self._rms = []            # per-block RMS, parallel list
        self._started_t = 0.0
        self._onset = False
        self._onset_block = 0
        self._last_loud_block = -1
        self._floor = 0.0
        self._followup = False
        self._window_s = 0.0
        self._monitor = None
        self._mic_name = None
        self._stopped = True

    # ------------------------------------------------ public
    @property
    def state(self):
        with self._lock:
            return self._state

    def is_active(self):
        return self.state != "idle"

    def is_recording(self):
        return self.state in ("recording", "followup")

    def current_mic_name(self):
        if self._mic_name:
            return self._mic_name
        try:
            return _device_name(pick_input_device(self.cfg))
        except Exception:
            return "system default microphone"

    def trigger(self):
        """The mic button / hotkey: start when idle, finish
        NOW when already recording (second press = send)."""
        st = self.state
        if st == "idle":
            self._start(followup=False)
        elif st in ("recording", "followup"):
            self._stop(finalize=True)
        # transcribing: a press is ignored (a turn is landing)

    def arm_followup(self, seconds):
        """Arm ONE dictation (post-reply window / Command
        Center open). No-op unless idle — an arm never steals
        an active recording."""
        if self.state != "idle":
            return
        self._window_s = max(1.0, float(seconds or 8.0))
        self._start(followup=True)

    def cancel(self):
        """Stop silently (typed input won, window closed…)."""
        if self.state in ("recording", "followup"):
            self._stop(finalize=False)

    # ------------------------------------------------ states
    def _set_state(self, state, seconds_left=None):
        with self._lock:
            self._state = state
        cb = self._on_state
        if cb is not None:
            try:
                cb(state, seconds_left)
            except Exception:
                pass

    def _start(self, followup):
        with self._lock:
            if self._state != "idle":
                return
            self._state = "followup" if followup else "recording"
            self._followup = followup
            self._chunks = []
            self._rms = []
            self._onset = False
            self._onset_block = 0
            self._last_loud_block = -1
            self._floor = 0.0
            self._stopped = False
            self._started_t = time.monotonic()
        try:
            device = pick_input_device(self.cfg)
            self._mic_name = _device_name(device)
            stream = self._factory(self._on_block, device)
        except Exception:
            log.exception("[dictation] could not open the mic")
            with self._lock:
                self._state = "idle"
                self._stopped = True
            cb = self._on_mic_error
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
            self._set_state("idle")
            return
        with self._lock:
            self._stream = stream
        try:
            stream.start()
        except Exception:
            log.exception("[dictation] mic stream would not "
                          "start")
            with self._lock:
                self._state = "idle"
                self._stopped = True
                self._stream = None
            cb = self._on_mic_error
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
            self._set_state("idle")
            return
        _fire_status(f"[mic] connected ({self._mic_name})")
        self._set_state("followup" if followup else "recording",
                        self._window_s if followup else None)
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True,
            name="nalox-dictation-watch")
        self._monitor.start()

    def _on_block(self, indata, frames, time_info, status):
        """sounddevice callback (also the fake-stream seam):
        store the block, update the meter, track onset."""
        try:
            block = np.asarray(indata, dtype=np.float32).reshape(-1)
        except Exception:
            return
        rms = _block_rms(block)
        loud = False
        with self._lock:
            if self._stopped:
                return
            self._chunks.append(block.copy())
            self._rms.append(rms)
            idx = len(self._rms) - 1
            if idx < _FLOOR_BLOCKS:
                # Calibration window (~0.8 s): store only.
                # The floor is the LOW QUARTILE of the
                # window, never its max — he may start
                # speaking inside the window (real clips
                # start at block 3-4), and a max-floor
                # would set the gate ABOVE his voice and
                # deafen the take (the v9.0 proof caught
                # exactly that). When the window closes,
                # the buffered blocks are REPLAYED through
                # the gate, so speech that began during
                # calibration still onsets at its true
                # first loud block (and the trim keeps it).
                if idx == _FLOOR_BLOCKS - 1:
                    _sorted = sorted(self._rms)
                    self._floor = _sorted[len(_sorted) // 4]
                    _gate = self._gate()
                    for _j, _r in enumerate(self._rms):
                        if _r >= _gate:
                            if not self._onset:
                                self._onset = True
                                self._onset_block = _j
                            self._last_loud_block = _j
                    loud = rms >= _gate
            else:
                loud = rms >= self._gate()
                if loud:
                    if not self._onset:
                        self._onset = True
                        self._onset_block = idx
                    self._last_loud_block = idx
        _note_level(min(1.0, rms * 4.0), loud)

    def _gate(self):
        return max(_GATE_MIN, self._floor * 3.0)

    def _monitor_loop(self):
        silence_s = float(self.cfg.get("dictation_silence_s")
                          or 1.2)
        max_s = float(self.cfg.get("dictation_max_s") or 60.0)
        onset_manual_s = float(
            self.cfg.get("dictation_onset_timeout_s") or 12.0)
        last_report = 0.0
        while True:
            time.sleep(0.1)
            with self._lock:
                if self._stopped:
                    return
                state = self._state
                onset = self._onset
                elapsed = time.monotonic() - self._started_t
                last_loud = self._last_loud_block
                n_blocks = len(self._rms)
            _decay_level()
            if state == "followup" and not onset:
                left = self._window_s - elapsed
                if left <= 0:
                    self._stop(finalize=False)   # silent close
                    return
                if elapsed - last_report >= 1.0:
                    last_report = elapsed
                    self._set_state("followup",
                                    max(0.0, left))
                continue
            if not onset:
                if elapsed >= onset_manual_s:
                    # Pressed but the gate never fired. If
                    # the tape is plainly LOUD, he WAS
                    # talking — he pressed and spoke in
                    # the same breath, so the calibration
                    # window filled with speech and the
                    # gate sat above it. Send the tape to
                    # the cloud anyway (v9.0 proof catch);
                    # a truly quiet tape is just discarded.
                    _rescue = False
                    with self._lock:
                        if (state == "recording" and self._rms
                                and max(self._rms) >= 0.02):
                            self._onset = True
                            self._onset_block = 0
                            self._last_loud_block = max(
                                _j for _j, _r in
                                enumerate(self._rms)
                                if _r >= _GATE_MIN)
                            _rescue = True
                    self._stop(finalize=_rescue)
                    return
                continue
            # speech happened: end on the pause, or the cap
            since_loud = (n_blocks - 1 - last_loud) * 0.1
            if since_loud >= silence_s or elapsed >= max_s:
                self._stop(finalize=True)
                return

    def _stop(self, finalize):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            stream = self._stream
            self._stream = None
            chunks = self._chunks
            rms = self._rms
            onset = self._onset
            onset_block = self._onset_block
            last_loud = self._last_loud_block
            started = self._started_t
            was_followup = self._state == "followup"
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if not finalize or not onset or not chunks:
            self._set_state("idle")
            cb = self._on_empty
            if finalize and cb is not None:
                try:
                    cb(False)
                except Exception:
                    pass
            return
        # trim: 0.3 s before onset .. 0.35 s after last loud
        lo = max(0, onset_block - 3)
        hi = min(len(chunks), last_loud + 4)
        audio = (np.concatenate(chunks[lo:hi])
                 if hi > lo else np.concatenate(chunks))
        # had_speech is a RELATIVE peak rule, not just
        # "the gate fired once": a noise gust barely
        # crossing the gate must close a follow-up arm
        # silently, while real speech near the mic peaks
        # well above it. (A usable STT text overrides
        # this either way — see _transcribe_worker.)
        _peak = max(rms[lo:hi]) if rms[lo:hi] else 0.0
        had_speech = ((hi - lo) * 0.1 >= 0.35
                      and _peak >= self._gate() * 1.5)
        if not was_followup:
            # A MANUAL press that reached onset always
            # earns the couldn't-hear line when the cloud
            # returns nothing (never silence — the v9.0
            # brief); the peak rule above exists to keep
            # FOLLOW-UP arms silent through mere noise.
            had_speech = True
        rec_s = max(0.0, time.monotonic() - started)
        self._set_state("transcribing")
        threading.Thread(target=self._transcribe_worker,
                         args=(audio, rec_s, had_speech),
                         daemon=True,
                         name="nalox-dictation-stt").start()

    def _transcribe_worker(self, audio, rec_s, had_speech=True):
        t0 = time.monotonic()
        got = None
        try:
            got = self._transcribe(audio, self.cfg)
        except Exception:
            log.exception("[dictation] transcription failed")
            got = None
        tx_s = time.monotonic() - t0
        self._set_state("idle")
        if got:
            text, lang, source = got
            log.info("[dictation] heard via %s: %r",
                     source, text)
            cb = self._on_text
            if cb is not None:
                try:
                    cb(text, lang, source, rec_s, tx_s)
                except Exception:
                    pass
        else:
            cb = self._on_empty
            if cb is not None:
                try:
                    cb(had_speech)
                except Exception:
                    pass
