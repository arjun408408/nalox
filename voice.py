"""Nalox's voice: text-to-speech.

v4.1 — PLAIN, RELIABLE, INTERRUPTIBLE (Arjun's verdict on v4.0:
console said SPEAKING but he heard nothing, and he does NOT want a
robot voice at all):
  - Robot effect OFF by default (config robot_voice, default False)
    and, when off, NO processing anywhere: ElevenLabs speaks with
    HIS chosen voice exactly as generated; locally it's pyttsx3
    DIRECT (engine.say + runAndWait — no WAV detour). The robot code
    stays in the file, dormant, behind the flag.
  - Interruptible (barge-in): say() returns "done" or "interrupted".
    A module-level stop event is set by voice.stop() (nalox.py's
    barge-in monitor calls it when Arjun says the wake word / "stop"
    mid-speech). pyttsx3 runs in a worker thread — the caller polls
    the event and a ~30 s hard timeout, so a hung engine can never
    freeze Nalox: on timeout the thread is abandoned, the failure
    counted, and Nalox moves on. sounddevice playback polls the
    event and sd.stop()s; the mp3 player (winmm MCI) polls too;
    PowerShell speech is a polled subprocess that gets killed.
  - Every say() is written to the logbook (logbook.py): success as
    "[VOICE] via <path>: <text>", failures as ERROR lines — so the
    diagnostics page shows exactly which voice spoke, or why none
    did. output_device_name() names the default speaker so the boot
    log can show where the sound is supposed to come out.

Voice priority (unchanged):
  1. ElevenLabs (config elevenlabs_api_key set) — Arjun's voice ID,
     eleven_multilingual_v2 (English + Bengali). Audio is requested
     as raw PCM (pcm_22050) and played via sounddevice: that is his
     voice UNTOUCHED (no decoder for mp3 exists among the installed
     packages, and PCM makes playback interruptible via sd.stop()).
  2. edge-tts — Bengali when robot is off, English when use_edge_tts.
  3. pyttsx3 (offline) — a FRESH engine per utterance (reusing one
     could hang after the first line — the old "went silent" bug).
  4. PowerShell System.Speech — takes over after 2 consecutive
     pyttsx3 failures, so a line is never silently lost.

History: v3.3 added the ring-mod robot + fresh-engine robustness;
v3.5 made the robot a subtle layer on the ElevenLabs voice; v3.7
softened the local robot (it sounded choppy) and made the winsound
fallback play the processed audio. v4.1 retires the robot by
default at Arjun's explicit instruction.

v4.2 — is_speaking(): a module-level counter tracks say() calls in
progress (any thread — the Settings test voice, reminders, the main
loop). ears.py checks it and refuses to transcribe while Nalox is
talking, so Nalox never hears (or answers) its own voice again.

v4.8 — ELEVENLABS CIRCUIT BREAKER: Arjun's ElevenLabs key is set
but every call fails "402 Payment Required" (his custom voice on
an account without credits) — and the old code retried ElevenLabs
on EVERY utterance, paying a network round-trip + an ERROR line
per reply before falling back to pyttsx3. Now a 401/402 trips a
session breaker: ONE clear ERROR line is logged, and every later
say() goes straight to the fallback voice. The breaker resets
only when the key changes (checked by hash, never stored/logged)
or on restart.

v6.6 — THE BENGALI VOICE MUST ACTUALLY ARRIVE (field 2026-11-15
19:24 IST): the Bengali TEXT was right all along, but the voice
chain for it was ElevenLabs (402, dead) → edge-tts (failed on
EVERY chunk, "No audio was received") → pyttsx3 — an ENGLISH
Windows voice reading Bengali script aloud as gibberish; in the
greeting Arjun could make out only the word "sir". Three fixes:
  - GOOGLE TTS: a new network layer (raw requests to the public
    translate_tts endpoint — no new dependency) sits before
    pyttsx3 for every language; for Bengali/Hindi text it is the
    layer that guarantees the line is spoken IN its language.
  - PER-REPLY STICKINESS: an engine that fails during a reply
    is skipped for the rest of that reply — later chunks go
    straight to the engine that works instead of re-paying a
    dead engine's failure chunk after chunk.
  - SESSION BREAKERS for edge-tts and Google TTS, mirroring the
    ElevenLabs pattern: two consecutive failures park the engine
    for five minutes, one log line per break.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave

log = logging.getLogger("nalox.voice")

try:
    import logbook
except Exception:  # pragma: no cover - logbook must never break voice
    logbook = None


def _lb(category, text):
    """Mirror one line into the diagnostics logbook (guarded)."""
    if logbook is not None:
        try:
            logbook.log(category, text)
        except Exception:
            pass


# ------------------------------------------------- barge-in stop (v4.1)
# Set by stop() — called from nalox.py's barge-in monitor the moment
# Arjun interrupts. Every playback path polls this event; say()
# clears it when a new utterance starts.
_STOP_EVENT = threading.Event()

# ------------------------------------------------- speaking state (v4.2)
# A simple reference count of say() calls in progress, so the ears
# can ask "is Nalox talking right now?" (voice.is_speaking) and
# refuse to transcribe Nalox's OWN voice — the v4.1 screenshot showed
# the wake loop happily transcribing the Settings test-voice line.
#
# v4.3 FIELD FIX — WATCHDOG: on Arjun's laptop a say() path could
# leave the counter stuck above zero (a hung engine thread, an
# abandoned worker). is_speaking() then stayed True FOREVER and the
# wake loop never transcribed again — UI said "Listening", Nalox
# was deaf. say() already pairs begin/end with try/finally; the
# watchdog is the belt-and-braces guarantee: no speech may claim
# the flag for more than SPEAK_WATCHDOG_SECONDS, and the ears can
# force-clear via force_clear_speaking().
_SPEAK_LOCK = threading.Lock()
_SPEAK_COUNT = 0
_SPEAK_SINCE = 0.0  # monotonic time the current speech began

# Module-level so tests can shorten it.
SPEAK_WATCHDOG_SECONDS = 45.0

# v4.6 — per-call speech budget: a healthy say() of N characters
# takes roughly N/15 seconds of actual speech plus engine start;
# the budget below is generous headroom over that. A say() that
# runs past it means an engine path is stuck (the flag watchdog
# above still guarantees recovery) — say() logs an ERROR so the
# hang leaves evidence instead of silence.
SAY_BUDGET_MIN_SECONDS = 10.0
SAY_BUDGET_BASE_SECONDS = 2.5
SAY_BUDGET_PER_CHAR_SECONDS = 0.45


def say_budget_seconds(text):
    """The soft time budget for one say() of this text (v4.6)."""
    return max(SAY_BUDGET_MIN_SECONDS,
               SAY_BUDGET_BASE_SECONDS
               + SAY_BUDGET_PER_CHAR_SECONDS * len(text or ""))


# v6.14: the engines with a separable bytes synthesis —
# the only ones the one-chunk prefetch may use (see
# Speaker._maybe_start_prefetch). edge-tts synthesizes
# straight into its playback file inside its v6.11 retry
# boundary, and ElevenLabs plays sample buffers, so both
# keep their exact fused paths.
_PREFETCH_ENGINES = frozenset(
    ("google-tts", "google-cloud-tts"))

# ------------------------------------------------- v6.5 live chunks
# Sentence splitting for LIVE-SYNCED speech: the same terminator
# set the brain's reply guard uses (. ! ? and the Bengali/Hindi
# danda ।). Whitespace is normalised first, so joining the
# chunks with single spaces reproduces the reply text.
_SPEECH_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")


def speech_chunks(text):
    """Split a reply into the sentence chunks say() speaks
    one by one when an on_chunk callback is attached (v6.5).
    Pure — unit-testable."""
    body = re.sub(r"\s+", " ", (text or "").strip())
    if not body:
        return []
    return [part.strip() for part in _SPEECH_SPLIT_RE.split(body)
            if part.strip()]


def _speak_begin():
    global _SPEAK_COUNT, _SPEAK_SINCE
    with _SPEAK_LOCK:
        if _SPEAK_COUNT == 0:
            _SPEAK_SINCE = time.monotonic()
        _SPEAK_COUNT += 1


def _speak_end():
    global _SPEAK_COUNT
    with _SPEAK_LOCK:
        _SPEAK_COUNT = max(0, _SPEAK_COUNT - 1)


def force_clear_speaking():
    """Reset the speaking flag to zero (watchdog / ears rescue)."""
    global _SPEAK_COUNT
    with _SPEAK_LOCK:
        _SPEAK_COUNT = 0
    log.warning("Speaking flag force-cleared.")
    _lb("ERROR", "[voice] speaking flag force-cleared")


def is_speaking():
    """True while any say() is in progress (any thread, any path).

    Watchdog: if the current speech has (impossibly) lasted longer
    than SPEAK_WATCHDOG_SECONDS, the flag is assumed leaked — it is
    auto-cleared, an ERROR line goes to the logbook, and False is
    returned, so the ears can never be muted forever.
    """
    global _SPEAK_COUNT
    with _SPEAK_LOCK:
        if _SPEAK_COUNT <= 0:
            return False
        if time.monotonic() - _SPEAK_SINCE <= SPEAK_WATCHDOG_SECONDS:
            return True
        _SPEAK_COUNT = 0  # leaked flag — clear it under the lock
    log.error("Speaking watchdog fired: flag was stuck for over "
              "%.0f s; auto-cleared.", SPEAK_WATCHDOG_SECONDS)
    _lb("ERROR", "[voice] watchdog: speaking flag auto-cleared")
    return False

# Hard cap for one pyttsx3 utterance: a hung SAPI engine must never
# freeze Nalox (module-level so tests can shorten it).
PYTTSX3_TIMEOUT = 30.0
POWERSHELL_TIMEOUT = 60.0

# ------------------------------------------------------------- v7.7
# PYTTSX3 RUNS IN A CHILD PROCESS NOW. The field evidence
# (synced fault log, 2026-11-16 11:55 IST): "Windows fatal
# exception: code 0xe0000002" — the current thread inside
# pyttsx3/drivers/sapi5.py (say -> _pump -> startLoop ->
# runAndWait), called from this module, while the main thread
# waited in say(). A native SAPI5 crash like that does not
# raise — it takes the WHOLE process down with it (the
# recurring "process DIED (exit code 1)" family: 2026-11-15
# x4, 2026-11-16 07:50 and 11:53). A Python thread cannot be
# insulated from a native fatal exception in its own process,
# so the engine now lives in a child: the runner below is
# executed as `python -c <src> speak|render <textfile> <rate>
# [wavpath]`; the parent polls it with the same stop/timeout
# discipline the PowerShell path always had. A child crash —
# native or otherwise — is just an engine failure here: the
# breaker in _try_engine counts it and the chain moves on.
# The main process survives ANY child outcome.
_PYTTSX3_CHILD_SRC = (
    "import sys\n"
    "mode = sys.argv[1]\n"
    "with open(sys.argv[2], encoding='utf-8') as fh:\n"
    "    text = fh.read()\n"
    "rate = int(sys.argv[3])\n"
    "import pyttsx3\n"
    "engine = pyttsx3.init()\n"
    "engine.setProperty('rate', rate)\n"
    "try:\n"
    "    for v in engine.getProperty('voices'):\n"
    "        if 'en' in (v.id or '').lower() \\\n"
    "                or 'english' in (v.name or '').lower():\n"
    "            engine.setProperty('voice', v.id)\n"
    "            break\n"
    "except Exception:\n"
    "    pass\n"
    "if mode == 'render':\n"
    "    engine.save_to_file(text, sys.argv[4])\n"
    "else:\n"
    "    engine.say(text)\n"
    "engine.runAndWait()\n"
)


def _hidden_console_kwargs():
    """subprocess kwargs that keep a console child INVISIBLE
    (v7.7, item G): CREATE_NO_WINDOW on Windows, nothing
    elsewhere. A console child of a windowless parent (the
    supervisor runs Nalox without a console) otherwise pops
    a visible console window for its whole lifetime — the
    owner's "~1 second CMD flash" during tasks."""
    if os.name == "nt":
        return {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}

# ------------------------------------------------- v6.6 net engines
# Google Translate TTS (the public translate_tts endpoint the
# Translate web page itself uses): raw HTTPS via requests — no
# new dependency. The language follows the requested lang when
# given, else the text's own script (google_tts_lang).
GOOGLE_TTS_URL = "https://translate.google.com/translate_tts"
GOOGLE_TTS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/120.0.0.0 Safari/537.36")
GOOGLE_TTS_TIMEOUT = 15.0
GOOGLE_TTS_MAX_CHARS = 180  # the endpoint's per-request limit

# ------------------------------------------------------------- v6.8
# GOOGLE CLOUD TEXT-TO-SPEECH — the MALE Bengali voice. The
# translate_tts layer above speaks Bengali with a FEMALE
# voice and that endpoint has no other (field 2026-11-15
# 20:26 IST — the owner: "নালক্স নাম তো ছেলে… বাংলা ভয়েস
# মেয়ে বলছে, এটা ঠিক করবে"; his standing rule since v4.9
# is a male Bengali voice). Cloud TTS has one: bn-IN
# Standard-B. It needs his own free Google Cloud API key
# (config google_tts_api_key, Settings → Voice; the free
# tier covers 1M characters/month — see
# SETUP-GOOGLE-VOICE.txt). No key pasted = the layer is
# never attempted and costs zero delay. Engine name in the
# chain/logs/state: "google-cloud-tts", sitting between
# edge-tts and the translate layer.
GOOGLE_CLOUD_TTS_URL = ("https://texttospeech.googleapis.com"
                        "/v1/text:synthesize")
GOOGLE_CLOUD_TTS_TIMEOUT = 15.0
GOOGLE_CLOUD_TTS_MAX_CHARS = 800  # well under the API's limit


def google_cloud_voice(lclass):
    """(languageCode, voice name) for a language class
    (v6.8): the Standard-B voices are the MALE ones —
    Bengali bn-IN-Standard-B is the point of the layer;
    Hindi/English use their Standard-B for consistency.
    Pure — unit-testable."""
    if lclass == "bn":
        return "bn-IN", "bn-IN-Standard-B"
    if lclass == "hi":
        return "hi-IN", "hi-IN-Standard-B"
    return "en-IN", "en-IN-Standard-B"

# Session circuit breakers for the network fallback engines
# (edge-tts, Google TTS), mirroring the v4.8 ElevenLabs breaker:
# ENGINE_BREAK_FAILURES consecutive failures park the engine for
# ENGINE_BREAK_SECONDS (one log line per break); a success
# resets the count. Module-level so tests can shorten the park.
ENGINE_BREAK_SECONDS = 300.0
ENGINE_BREAK_FAILURES = 2

# v6.11 — edge-tts gets ONE in-call retry for network flakes
# before a failure counts (field 2026-11-15 21:41 IST: on
# Arjun's phone-hotspot network edge-tts dies with "No audio
# was received" often enough that Bengali replies kept
# falling through to the FEMALE Google Translate voice —
# while his chosen FREE male voice is edge-tts's own
# bn-BD-PradeepNeural). The retry lives INSIDE _speak_edge,
# so it happens before _try_engine's bookkeeping: a landed
# retry is a plain success (breaker untouched, stickiness
# untouched), and a doubly-failed chunk raises ONCE, so the
# breaker still counts it exactly once. Module-level so
# tests can shorten the backoff.
EDGE_RETRY_BACKOFF_SECONDS = 0.8


def _edge_failure_retryable(exc):
    """True when an edge-tts synthesis failure is a network
    flake worth ONE fresh-connection retry (v6.11): the
    no-audio error, a timeout, or a connection failure.
    A ValueError (e.g. an invalid voice name) is a config
    error — retrying it would fail identically, so it is
    never retried. Pure — unit-testable; matches the
    aiohttp/websockets failure classes by module name so
    voice.py needs no new imports."""
    if isinstance(exc, ValueError):
        return False
    if type(exc).__name__ == "NoAudioReceived":
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError,
                        ConnectionError, OSError)):
        return True
    module = type(exc).__module__ or ""
    if module.startswith(("aiohttp", "websockets")):
        return True
    return "no audio" in str(exc).lower()

# ------------------------------------------------------------- v6.7 D
# VOICE HEALTH PERSISTS ACROSS RESTARTS (voice_state.json,
# beside this file — USER DATA: never shipped in packs,
# deny-listed in the updater, git-ignored). v6.6's breakers
# were session-only, so every fresh boot re-paid the whole
# failure crawl before reaching the engine that works
# (field 2026-11-15 19:52 IST: ElevenLabs 402 → edge-tts
# slow-fail → google-tts, ~10 s of tax on the GREETING of
# every boot). Now the state survives: the last engine that
# WORKED per language class (bn/hi/en — google_tts_lang's
# classes) and the parked-until WALL times of broken
# engines. A new Speaker loads it, starts each language at
# its last working engine, and keeps parked engines parked
# until their time is up. ElevenLabs is the one exception:
# its persisted 401/402 block is restored WITH an armed
# one-time re-probe in case he bought credits; a success
# clears the block and reclaims first place. v7.3: the
# re-probe runs in the BACKGROUND (start_boot_probe) — it
# used to run inside the boot's first uncached say() and,
# on a slow hotspot, taxed exactly the line he was waiting
# to hear (field 2026-11-16 07:51 IST).
VOICE_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "voice_state.json")
_VOICE_ENGINES = ("elevenlabs", "edge-tts", "google-cloud-tts",
                  "google-tts", "pyttsx3", "powershell")
_VOICE_CLASSES = ("bn", "hi", "en")

# ------------------------------------------------------------- v7.1
# FIXED-LINE TTS CACHE (pattern re-implemented from a study
# of jarvis-hector — technique only, no code copied).
# Nalox's FIXED lines — the boot greeting, the wake ack
# "Yes Sir, I'm here.", the Bengali could-not-hear line,
# the mic-warning line — are the same strings every day,
# yet v7.0 re-synthesized them through the network chain
# on every boot (paying ElevenLabs' 402 crawl and hotspot
# latency for the two lines he hears most). Now a fixed
# line is synthesized ONCE per (text, engine, voice,
# speed) and replayed from disk: instant, offline, immune
# to the 402 and to hotspot slowness. The first-ever play
# goes through the normal chain and populates the cache on
# success; only say(..., fixed=True) call sites take part
# (nalox.py marks exactly the fixed lines) — dynamic brain
# replies are NEVER cached. Files live in the install
# folder's cache/tts dir: USER DATA — never shipped in
# packs (updater deny-list), never in git (.gitignore).
# Each engine's audio is stored in its NATIVE format —
# ElevenLabs as WAV (its PCM samples via _write_wav; no
# MP3 decoder ships with the install, so its playback
# stays the samples path) and the MP3 engines as MP3 —
# so cached playback rides the exact interruptible
# players normal playback uses, and barge-in/stop cuts it
# identically. Cache hits are BREAKER-NEUTRAL: they are
# not recorded as engine successes or failures anywhere.
TTS_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache", "tts")
_FIXED_CACHE_MAX_CHARS = 200
_FIXED_CACHE_ENGINES = ("elevenlabs", "edge-tts",
                        "google-cloud-tts", "google-tts")


def _load_voice_state():
    """The persisted voice health, or a clean empty state.

    Corrupt / missing / odd-shaped files all read as the
    clean default — a damaged state file must never cost
    Nalox its voice."""
    try:
        with open(VOICE_STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        state = {}
        last_good = data.get("last_good")
        if isinstance(last_good, dict):
            state["last_good"] = {
                k: v for k, v in last_good.items()
                if k in _VOICE_CLASSES and v in _VOICE_ENGINES}
        parked = data.get("parked_until")
        if isinstance(parked, dict):
            state["parked_until"] = {
                k: float(v) for k, v in parked.items()
                if k in _VOICE_ENGINES
                and isinstance(v, (int, float))}
        el = data.get("eleven_down")
        if isinstance(el, dict) and el.get("fp"):
            state["eleven_down"] = {
                "status": int(el.get("status") or 0),
                "fp": str(el["fp"])}
        return state
    except Exception:
        return {}


def _save_voice_state(state):
    """Persist the voice health (guarded — a failed write
    costs the optimisation, never the speech)."""
    try:
        with open(VOICE_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


def google_tts_lang(text, lang=None):
    """The tl= language for a Google TTS request (v6.6): the
    requested lang wins (bn/hi/en prefixes); without one, the
    text's own dominant script decides — Bengali block, then
    Devanagari, else English. Pure — unit-testable."""
    code = (lang or "").strip().lower()
    if code.startswith("bn"):
        return "bn"
    if code.startswith("hi"):
        return "hi"
    if code.startswith("en"):
        return "en"
    bn = sum(1 for ch in (text or "") if "\u0980" <= ch <= "\u09ff")
    hi = sum(1 for ch in (text or "") if "\u0900" <= ch <= "\u097f")
    if bn and bn >= hi:
        return "bn"
    if hi:
        return "hi"
    return "en"


def google_tts_chunks(text, limit=GOOGLE_TTS_MAX_CHARS):
    """Split text into <=limit pieces for translate_tts (v6.6),
    preferring sentence/word boundaries. Pure — unit-testable."""
    body = re.sub(r"\s+", " ", (text or "").strip())
    if not body:
        return []
    if len(body) <= limit:
        return [body]
    pieces = []
    rest = body
    while len(rest) > limit:
        cut = -1
        for sep in ("। ", ". ", "! ", "? ", "; ", ", ", " "):
            idx = rest.rfind(sep, 0, limit + 1)
            if idx > 0:
                cut = idx + len(sep)
                break
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return [p for p in pieces if p]


def stop():
    """Interrupt whatever Nalox is currently saying."""
    _STOP_EVENT.set()


def stop_for_exit(grace_s=1.5):
    """Stop in-flight speech BEFORE a process exit (v7.7).

    Every exit path (self-update restart, supervisor
    restart, deliberate exit) calls this first: a SAPI call
    must never be mid-flight while the process tears down —
    the 2026-11-16 11:53 self-update restart died with exit
    code 1 while speech threads were inside the voice layer.
    Sets the stop event, then waits up to grace_s for the
    speaking flag to clear. Guarded end to end: an exit must
    never be blocked or broken by its own safety step."""
    try:
        stop()
    except Exception:
        pass
    try:
        deadline = time.monotonic() + max(0.0, float(grace_s))
        while time.monotonic() < deadline:
            if not is_speaking():
                break
            time.sleep(0.02)
    except Exception:
        pass


class _ElevenLabsUnavailable(Exception):
    """ElevenLabs refused the account itself (HTTP 401/402) —
    retrying every utterance is pointless (v4.8 breaker)."""

    def __init__(self, status):
        super().__init__(f"ElevenLabs HTTP {status}")
        self.status = status


def _key_fingerprint(key):
    """A hash of an API key, for change detection only — the key
    itself is never stored on the Speaker or written to a log."""
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


class Speaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._pyttsx3_failures = 0   # consecutive pyttsx3 failures
        self._output_name = None     # cached speaker name
        # v4.8: ElevenLabs circuit breaker — None, or
        # (http_status, key_fingerprint) once a 401/402 trips it.
        self._eleven_down = None
        # v6.6: per-reply engine stickiness + session breakers
        # for the network fallback engines (edge-tts, Google
        # TTS). _reply_skip holds the engines that already
        # failed during the CURRENT say() — later chunks of
        # the same reply go straight to the engine that works
        # instead of re-paying a dead engine's failure per
        # chunk (field 2026-11-15 19:24 IST: edge-tts failed
        # on BOTH chunks of one reply). _net_fails counts
        # CONSECUTIVE failures per engine across replies; at
        # ENGINE_BREAK_FAILURES the engine is parked until
        # _net_down_until[engine] — one log line per break.
        self._reply_skip = set()
        # v6.11: the "[voice] edge-tts retry ok" line is
        # logged at most once per reply; say() resets this
        # with the rest of the per-reply state.
        self._edge_retry_noted = False
        self._net_fails = {}
        self._net_down_until = {}
        # v6.7 D: persisted voice health (voice_state.json) —
        # the last working engine per language class + parked
        # engines survive the restart, so a fresh boot starts
        # where the last session learned to start. The
        # ElevenLabs persisted block restores with an armed
        # one-time re-probe (see start_boot_probe, v7.3).
        self._vstate = _load_voice_state()
        self._el_persisted = None
        self._el_probe_armed = False
        # v6.14: one-chunk TTS prefetch state (see
        # _maybe_start_prefetch). _reply_gen stamps every
        # prefetch with the say() that armed it, so a stale
        # slot can never be consumed by a later reply;
        # _prefetch_next is the armed (gen, text, lang) of
        # the next chunk — engine-agnostic: whichever
        # prefetchable engine serves the current chunk
        # adopts it at playback start; _prefetch_slot is
        # the running/done synth, stamped with the engine
        # that produced it.
        self._reply_gen = 0
        self._prefetch_next = None
        self._prefetch_slot = None
        # v7.1: True only inside a say(..., fixed=True) —
        # the fixed-line TTS cache reads/stores then (see
        # the TTS_CACHE_DIR note). Per-reply state like
        # _reply_skip: set by say(), cleared in its finally.
        self._fixed_active = False
        self._apply_vstate()

    # ------------------------------------------------ v6.7 D state
    _boot_line_done = False

    def _apply_vstate(self):
        """Fold the persisted health into this session: live
        parks become session parks (wall → monotonic), the
        ElevenLabs block restores + arms its re-probe, and
        the ONE boot line names the engine a language will
        start with."""
        now = time.time()
        for engine, until in (self._vstate.get("parked_until")
                              or {}).items():
            if until > now:
                self._net_down_until[engine] = (
                    time.monotonic() + (until - now))
        el = self._vstate.get("eleven_down")
        if el:
            self._el_persisted = (el["status"], el["fp"])
            self._eleven_down = self._el_persisted
            self._el_probe_armed = True
        last_good = self._vstate.get("last_good") or {}
        if last_good and not Speaker._boot_line_done:
            Speaker._boot_line_done = True
            for lclass in _VOICE_CLASSES:
                engine = last_good.get(lclass)
                if engine:
                    line = (f"[voice] starting with {engine} "
                            f"(worked last time)")
                    log.info(line)
                    _lb("VOICE", line)
                    break

    # ------------------------------------------------ v7.3 probe
    def start_boot_probe(self):
        """Start the once-per-boot ElevenLabs re-probe IN THE
        BACKGROUND (v7.3) and return at once.

        Until v7.2 the re-probe ran INSIDE the first say() of
        the boot that missed the fixed-line cache: the block
        lifted for one real network attempt on the speech
        path itself. On the owner's hotspot a 402 round-trip
        takes seconds, and in the field (2026-11-16 07:51
        IST) it landed on the wake ack — say() overran its
        budget 13 s > 11 s before google-tts could speak.
        The probe now runs on a daemon thread: speech NEVER
        waits for it. While the block stands, say() skips
        ElevenLabs at zero cost and the sticky engine speaks;
        if the probe finds the account alive (he bought
        credits), it clears the block and ElevenLabs returns
        from the NEXT reply. Called once by nalox.py at boot;
        a no-op unless a persisted block armed it."""
        if not self._el_probe_armed:
            return
        self._el_probe_armed = False
        try:
            threading.Thread(target=self._run_boot_probe,
                             daemon=True,
                             name="nalox-el-probe").start()
        except Exception:
            pass

    def _run_boot_probe(self):
        """The probe itself: ONE tiny synthesis (a single
        character — the cheapest call that exercises the
        exact TTS path the breaker guards), never played
        aloud. A 401/402 keeps the block (the account is
        still dead; the boot already logged that line once,
        so this stays quiet). A success clears the block +
        the persisted copy, so the custom voice reclaims
        first place from the next reply. Any other failure
        (network down, timeout) keeps the block too — the
        probe only ever PROVES life, it never punishes."""
        key = (self.cfg.get("elevenlabs_api_key") or "").strip()
        if not key or self._el_persisted is None:
            return
        if self._el_persisted[1] != _key_fingerprint(key):
            return  # a different key — the block is not its
        try:
            self._synth_elevenlabs(".", False)
        except _ElevenLabsUnavailable:
            log.info("[voice] ElevenLabs still unavailable "
                     "(boot probe) — staying on the working "
                     "voice")
            return
        except Exception:
            return
        self._eleven_down = None
        self._el_persisted = None
        # ElevenLabs RECLAIMS first place (the pre-v7.3
        # in-say probe did this by speaking the line itself
        # and being recorded good): without this, the sticky
        # engine would keep winning step 1 of every reply
        # and the custom voice would never be tried again.
        # His voice speaks every language class, so it
        # becomes the remembered starter for all of them.
        _lg = self._vstate.setdefault("last_good", {})
        for _cls in _VOICE_CLASSES:
            _lg[_cls] = "elevenlabs"
        if "eleven_down" in self._vstate:
            del self._vstate["eleven_down"]
        self._persist_vstate()
        line = ("[voice] ElevenLabs is back — your custom "
                "voice returns from the next reply")
        log.info(line)
        _lb("VOICE", line)

    def _persist_vstate(self):
        _save_voice_state(self._vstate)

    def _record_good(self, engine, lclass):
        """A real success (v6.7 D): this engine becomes its
        language class's remembered starter, its park clears,
        and an ElevenLabs success clears the persisted block
        (it has reclaimed its place).

        ONLY the network engines are ever recorded: the
        offline last resorts (pyttsx3 / PowerShell) "work"
        precisely when the network is having a bad evening —
        remembering one of them would start every later
        boot on the worst voice and never retry the good
        ones."""
        if engine not in ("elevenlabs", "edge-tts",
                          "google-cloud-tts", "google-tts"):
            return
        changed = False
        last_good = self._vstate.setdefault("last_good", {})
        if last_good.get(lclass) != engine:
            last_good[lclass] = engine
            changed = True
        parked = self._vstate.setdefault("parked_until", {})
        if engine in parked:
            del parked[engine]
            changed = True
        if engine == "elevenlabs":
            self._eleven_down = None
            self._el_persisted = None
            if "eleven_down" in self._vstate:
                del self._vstate["eleven_down"]
                changed = True
        if changed:
            self._persist_vstate()

    def stop(self):
        """Interrupt the current utterance (barge-in)."""
        stop()

    def is_speaking(self):
        """True while this (or any) Speaker is mid-utterance (v4.2)."""
        return is_speaking()

    # ------------------------------------------------ robot effect
    def robot_on(self):
        """v4.1: OFF unless Arjun turns it on in config/Settings."""
        return bool(self.cfg.get("robot_voice", False))

    def speed(self):
        """Speaking rate multiplier (v4.3): config voice_speed,
        clamped to 0.8–1.3. 1.0 = normal."""
        try:
            value = float(self.cfg.get("voice_speed", 1.0) or 1.0)
        except Exception:
            value = 1.0
        return min(1.3, max(0.8, value))

    # ------------------------------------------------ v4.8 breaker
    def _elevenlabs_blocked(self, key):
        """True when the breaker has tripped for THIS key. A
        different key (Arjun pasted a fresh one) un-trips it —
        that, or a restart, is the only re-check."""
        if self._eleven_down is None:
            return False
        _status, fingerprint = self._eleven_down
        return fingerprint == _key_fingerprint(key)

    # ------------------------------------------------ v6.6 breakers
    def _engine_parked(self, engine):
        """True when a network fallback engine is unusable for
        THIS call: it already failed during the current reply
        (per-reply stickiness), or its session circuit breaker
        is still inside its park (ENGINE_BREAK_SECONDS)."""
        if engine in self._reply_skip:
            return True
        until = self._net_down_until.get(engine)
        return until is not None and time.monotonic() < until

    def _note_net_failure(self, engine, label):
        """Record a network-engine failure (v6.6): the engine
        is sticky-skipped for the rest of this reply, and the
        failure counts toward its session breaker. Tripping
        the breaker logs ONE line; a failure after a park
        expires re-trips it (a new break, a new line)."""
        self._reply_skip.add(engine)
        fails = self._net_fails.get(engine, 0) + 1
        self._net_fails[engine] = fails
        if fails >= ENGINE_BREAK_FAILURES:
            until = self._net_down_until.get(engine)
            if until is None or time.monotonic() >= until:
                self._net_down_until[engine] = (
                    time.monotonic() + ENGINE_BREAK_SECONDS)
                # v6.7 D: the park persists (wall clock) so
                # the next boot does not re-pay this engine.
                self._vstate.setdefault(
                    "parked_until", {})[engine] = (
                        time.time() + ENGINE_BREAK_SECONDS)
                self._persist_vstate()
                line = f"[voice] {label} unavailable — skipping it for a while"
                log.error(line)
                _lb("ERROR", line)

    def _note_net_success(self, engine):
        """A network engine answered (v6.6): its consecutive-
        failure count and any expired park reset."""
        self._net_fails[engine] = 0
        self._net_down_until.pop(engine, None)
        # v6.7 D: a success also clears the persisted park.
        parked = self._vstate.get("parked_until") or {}
        if engine in parked:
            del parked[engine]
            self._persist_vstate()

    def _trip_elevenlabs(self, status, key):
        """Trip the breaker + log the ONE clear line. Later calls
        skip ElevenLabs silently — no per-utterance spam, no
        per-utterance network delay."""
        self._eleven_down = (status, _key_fingerprint(key))
        # v6.7 D: the block persists too — restored next boot
        # WITH the one-time re-probe armed (see _apply_vstate).
        self._el_persisted = self._eleven_down
        self._vstate["eleven_down"] = {
            "status": status, "fp": self._eleven_down[1]}
        self._persist_vstate()
        reason = ("payment/credits" if status == 402
                  else "key rejected")
        line = (f"[voice] ElevenLabs unavailable ({status} — "
                f"{reason}). Using the local voice for this "
                "session.")
        log.error(line)
        _lb("ERROR", line)
        # The diagnostics header's voice line tells the truth too.
        if logbook is not None:
            try:
                logbook.set_status(voice=self.describe_active())
            except Exception:
                pass

    def describe_active(self):
        """Short line naming the voice that will actually speak.

        Mirrors the priority logic in say(). Posted to the console
        and the logbook at boot so Arjun can SEE which voice is live.
        """
        key = (self.cfg.get("elevenlabs_api_key") or "").strip()
        if key:
            if self._elevenlabs_blocked(key):
                status = self._eleven_down[0]
                return (f"ElevenLabs — unavailable ({status}), "
                        "local voice")
            if self.robot_on():
                return "ElevenLabs — your custom voice (robot layer on)"
            return "ElevenLabs — your custom voice"
        if self.cfg.get("use_edge_tts"):
            return "Edge TTS voice"
        if self.robot_on():
            return "Local robot voice — ElevenLabs API key not set"
        return "Local plain voice — ElevenLabs API key not set"

    def output_device_name(self):
        """Name of the default OUTPUT device (where sound comes out).

        Guarded: any failure returns "unknown output device". The
        boot log records this as "[speaker] output: <name>" — the
        first thing to check when Nalox "speaks" but nothing is
        heard (e.g. Windows is sending audio to another device).
        """
        if self._output_name:
            return self._output_name
        name = "unknown output device"
        try:
            import sounddevice as sd
            try:
                name = str(sd.query_devices(kind="output")["name"])
            except Exception:
                idx = sd.default.device[1]
                if idx is not None and int(idx) >= 0:
                    name = str(sd.query_devices(int(idx))["name"])
        except Exception:
            pass
        self._output_name = name
        return name

    def _robotize(self, samples, rate, depth=0.85):
        """Ring-modulate (+ gently bit-crush) a float32 mono signal.

        DORMANT since v4.1 (robot_voice defaults off) — kept for the
        config flag. depth 0.30 = subtle sheen (ElevenLabs/local
        paths when the flag is on); bit-crush skipped at depth
        <= 0.35. Returns a float32 array, peak-normalized.
        """
        import numpy as np
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return x
        hz = float(self.cfg.get("robot_hz", 30) or 30)
        depth = float(min(1.0, max(0.0, depth)))
        t = np.arange(x.size, dtype=np.float32) / float(rate)
        carrier = np.sin(2.0 * np.pi * hz * t).astype(np.float32)
        x = (1.0 - depth) * x + depth * (x * carrier)
        if depth > 0.35:
            # Gentle bit-crush: quantize to ~10-bit steps.
            x = np.round(x * 512.0) / 512.0
        peak = float(np.max(np.abs(x)))
        if peak > 1e-4:
            x = x * (0.92 / peak)
        return x.astype(np.float32)

    # ------------------------------------------------ playback helpers
    def _play_samples_interruptible(self, samples, rate):
        """Play float32 samples via sounddevice, polling the stop
        event. Returns "done" or "interrupted"; raises if sounddevice
        itself fails (callers fall back to winsound)."""
        import sounddevice as sd
        sd.play(samples, int(rate))
        duration = len(samples) / float(rate) if rate else 0.0
        start = time.monotonic()
        while True:
            if _STOP_EVENT.is_set():
                try:
                    sd.stop()
                except Exception:
                    pass
                return "interrupted"
            elapsed = time.monotonic() - start
            if elapsed >= duration:
                break
            active = None
            try:
                stream = sd.get_stream()
                active = bool(stream is not None and stream.active)
            except Exception:
                active = None
            if active is False and elapsed > 0.1:
                break  # stream finished early (or underran dry)
            time.sleep(0.05)
        try:
            sd.wait()
        except Exception:
            pass
        return "done"

    def _play_samples_winsound(self, samples, rate):
        """Last-ditch playback: write a WAV and PlaySound it.

        Blocking and NOT interruptible — only used when sounddevice
        playback itself has failed. Returns "done".
        """
        out = os.path.join(tempfile.gettempdir(), "nalox_tts_play.wav")
        self._write_wav(out, samples, rate)
        import winsound
        winsound.PlaySound(out, winsound.SND_FILENAME)
        return "done"

    @staticmethod
    def _read_wav(path):
        """Read a WAV file with the stdlib wave module -> (float32, rate)."""
        import numpy as np
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if width == 2:
            data = np.frombuffer(frames, dtype=np.int16) \
                .astype(np.float32) / 32768.0
        elif width == 4:
            data = np.frombuffer(frames, dtype=np.int32) \
                .astype(np.float32) / 2147483648.0
        elif width == 1:
            data = (np.frombuffer(frames, dtype=np.uint8)
                    .astype(np.float32) - 128.0) / 128.0
        else:
            raise RuntimeError(f"unsupported WAV sample width: {width}")
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return data.astype(np.float32), rate

    @staticmethod
    def _write_wav(path, samples, rate):
        """Write float32 mono samples to a 16-bit PCM WAV (stdlib)."""
        import numpy as np
        x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        pcm = (x * 32767.0).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(rate))
            wf.writeframes(pcm.tobytes())

    # ---------- pyttsx3 (offline) — fresh engine per utterance ----------
    def _new_engine(self):
        import pyttsx3
        engine = pyttsx3.init()
        # v4.3: the Settings speaking-rate slider scales the base rate.
        engine.setProperty(
            "rate", int(int(self.cfg.get("tts_rate", 175)) * self.speed()))
        # Prefer an English voice if several are installed.
        try:
            for v in engine.getProperty("voices"):
                if "en" in (v.id or "").lower() \
                        or "english" in (v.name or "").lower():
                    engine.setProperty("voice", v.id)
                    break
        except Exception:
            pass
        return engine

    # ---------- pyttsx3 child process (v7.7) ----------
    def _launch_tts_child(self, argv):
        """Spawn the pyttsx3 child (v7.7). The ONE launch
        seam: tests substitute it with a fake process to
        prove a child crash can never reach this process.
        The child is console-hidden (item G)."""
        return subprocess.Popen(
            argv, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_hidden_console_kwargs())

    def _run_tts_child(self, argv, poll_stop):
        """Poll a pyttsx3 child to its end. Returns
        "done" / "interrupted"; raises RuntimeError on a
        timeout (child killed) or a non-zero exit — a
        crashed child, INCLUDING a native SAPI5 fatal
        exception, is an ordinary engine failure here."""
        proc = self._launch_tts_child(argv)
        deadline = time.monotonic() + PYTTSX3_TIMEOUT
        while proc.poll() is None:
            if poll_stop and _STOP_EVENT.is_set():
                try:
                    proc.kill()
                except Exception:
                    pass
                return "interrupted"
            if time.monotonic() > deadline:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise RuntimeError(
                    f"pyttsx3 timed out after "
                    f"{PYTTSX3_TIMEOUT:.0f}s (child killed)")
            time.sleep(0.05)
        if proc.returncode != 0:
            raise RuntimeError(
                f"pyttsx3 child exited with code "
                f"{proc.returncode}")
        return "done"

    def _tts_child_argv(self, mode, text, extra=()):
        """(argv, textfile) for one pyttsx3 child run. The
        text rides in a UNIQUE temp file per utterance —
        say() runs concurrently (main loop + Telegram
        thread; the 2026-11-16 fault dump shows both inside
        the voice layer at once), so a fixed file would
        race. The caller deletes the file when done."""
        fd, path = tempfile.mkstemp(prefix="nalox_tts_",
                                    suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        rate = int(int(self.cfg.get("tts_rate", 175))
                   * self.speed())
        argv = [sys.executable, "-c", _PYTTSX3_CHILD_SRC,
                mode, path, str(rate)] + list(extra)
        return argv, path

    def _speak_pyttsx3_direct(self, text):
        """Plain pyttsx3 speak (v4.1 default local path).

        v7.7: the engine lives in a CHILD PROCESS (see
        _PYTTSX3_CHILD_SRC) — the pre-v7.7 in-process worker
        thread could be killed by a native SAPI5 fatal
        exception, taking Nalox with it (fault log
        2026-11-16: 0xe0000002 inside sapi5.py's runAndWait,
        process exit code 1). This thread only polls the
        child: stop event -> kill -> "interrupted"; the
        PYTTSX3_TIMEOUT cap -> kill -> raise; a non-zero
        exit (crash) -> raise. The failure counter in
        _try_engine routes the next lines onward, exactly
        as it did for thread-era failures.
        """
        argv, textfile = self._tts_child_argv("speak", text)
        try:
            return self._run_tts_child(argv, poll_stop=True)
        finally:
            try:
                os.remove(textfile)
            except Exception:
                pass

    def _speak_pyttsx3(self, text, robot):
        """Speak with pyttsx3. Returns "done"/"interrupted".

        Robot OFF (v4.1 default): direct speak, see above.
        Robot ON (dormant): the child renders a WAV (v7.7 —
        the render is a SAPI call too, so it is isolated
        exactly like the speak path), then the parent
        robotizes and plays the samples via sounddevice
        (winsound fallback), as in the v3.3–v3.7 path —
        sample playback is not SAPI and stays in-process.
        """
        if not robot:
            return self._speak_pyttsx3_direct(text)
        fd, tmp = tempfile.mkstemp(prefix="nalox_tts_",
                                   suffix=".wav")
        os.close(fd)
        try:
            os.remove(tmp)
        except Exception:
            pass
        argv, textfile = self._tts_child_argv("render", text,
                                              extra=(tmp,))
        try:
            self._run_tts_child(argv, poll_stop=False)
        finally:
            try:
                os.remove(textfile)
            except Exception:
                pass
        if not os.path.exists(tmp) or os.path.getsize(tmp) < 1000:
            raise RuntimeError("pyttsx3 produced no audio file")
        samples, rate = self._read_wav(tmp)
        if samples.size < rate // 10:
            raise RuntimeError("pyttsx3 produced (almost) no audio")
        import numpy as np
        processed = self._robotize(samples, rate, depth=0.30)
        pad = np.zeros(int(rate * 0.05), dtype=np.float32)
        processed = np.concatenate([pad, processed, pad])
        try:
            return self._play_samples_interruptible(processed, rate)
        except Exception as exc:
            log.warning("sounddevice playback failed (%s); playing "
                        "via winsound", exc)
            return self._play_samples_winsound(processed, rate)

    # ---------- PowerShell System.Speech (last resort) ----------
    def _speak_powershell(self, text):
        """Speak via Windows' own SAPI through PowerShell. The text is
        passed through a temp file so quoting can never break it.
        Polled subprocess: the stop event kills it ("interrupted");
        a timeout kills it and raises."""
        tmp = os.path.join(tempfile.gettempdir(), "nalox_say.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$t = Get-Content -Raw -Encoding UTF8 '{tmp}'; "
            "$s.Speak($t)")
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_hidden_console_kwargs())
        deadline = time.monotonic() + POWERSHELL_TIMEOUT
        while proc.poll() is None:
            if _STOP_EVENT.is_set():
                try:
                    proc.kill()
                except Exception:
                    pass
                return "interrupted"
            if time.monotonic() > deadline:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise RuntimeError("PowerShell speech timed out")
            time.sleep(0.05)
        if proc.returncode != 0:
            raise RuntimeError(
                f"PowerShell speech exited with code {proc.returncode}")
        return "done"

    # ---------- mp3 playback (Windows winmm MCI, interruptible) ----------
    def _play_mp3_interruptible(self, path):
        """Play an mp3 via MCI, polling the stop event.

        "play" without "wait" + a status poll loop: on the stop
        event, MCI "stop" halts playback -> "interrupted". Raises if
        MCI is unavailable or the file won't open (callers fall
        through to the next voice path)."""
        import ctypes
        winmm = ctypes.windll.winmm
        winmm.mciSendStringW("close nalox", None, 0, None)  # stale alias
        rc = winmm.mciSendStringW(
            f'open "{path}" type mpegvideo alias nalox', None, 0, None)
        if rc != 0:
            raise RuntimeError(f"MCI could not open the mp3 (code {rc})")
        try:
            winmm.mciSendStringW("play nalox", None, 0, None)
            buf = ctypes.create_unicode_buffer(128)
            while True:
                if _STOP_EVENT.is_set():
                    winmm.mciSendStringW("stop nalox", None, 0, None)
                    return "interrupted"
                buf.value = ""
                winmm.mciSendStringW("status nalox mode", buf, 128, None)
                if buf.value != "playing":
                    break
                time.sleep(0.05)
            return "done"
        finally:
            winmm.mciSendStringW("close nalox", None, 0, None)

    # ---------- ElevenLabs (online, top priority when key is set) ----------
    def _synth_elevenlabs(self, text, robot):
        """Synthesize with ElevenLabs -> (pcm, play_rate).

        v7.3: split out of _speak_elevenlabs so the boot
        re-probe can test the account WITHOUT playing
        anything aloud. Raises _ElevenLabsUnavailable on a
        401/402, exactly as the speaking path always did."""
        import requests
        key = (self.cfg.get("elevenlabs_api_key") or "").strip()
        voice_id = (self.cfg.get("elevenlabs_voice_id") or "").strip()
        if not key or not voice_id:
            raise RuntimeError("ElevenLabs key/voice id not configured")
        import numpy as np
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": "pcm_22050"},
            headers={"xi-api-key": key,
                     "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=30,
        )
        # v4.8: an account-level refusal (401 bad key / 402 no
        # credits) is a breaker signal, not an ordinary failure —
        # say() must not pay this round-trip on every utterance.
        if resp.status_code in (401, 402):
            raise _ElevenLabsUnavailable(resp.status_code)
        resp.raise_for_status()
        pcm = np.frombuffer(resp.content, dtype=np.int16) \
            .astype(np.float32) / 32768.0
        if pcm.size == 0:
            raise RuntimeError("ElevenLabs returned no audio")
        if robot:
            pcm = self._robotize(pcm, 22050, depth=0.30)
        # v4.3: speaking rate — play the 22050 Hz samples back at a
        # scaled rate (22050 × speed). At 0.8–1.3 the pitch shift is
        # mild and it works uniformly for every playback path.
        play_rate = int(22050 * self.speed())
        # v7.1: a fixed line's rendering joins the disk
        # cache — the samples exactly as they are about to
        # be played (the helper itself refuses the robot
        # path, whose rendering is a different sound).
        self._cache_store_fixed(
            "elevenlabs", text, voice_id,
            wav_samples=pcm, wav_rate=play_rate)
        return pcm, play_rate

    def _speak_elevenlabs(self, text, robot):
        """Arjun's own voice. Returns "done"/"interrupted".

        The audio is requested as raw PCM (pcm_22050) and played via
        sounddevice — with robot OFF (the v4.1 default) the samples
        are played EXACTLY as generated: his voice, untouched. (PCM
        rather than mp3 because no mp3 decoder ships with the
        installed packages, and PCM playback is interruptible via
        sd.stop().) With robot ON, the dormant _robotize applies its
        subtle 0.30 layer first. If sounddevice playback fails, the
        samples are written to a WAV and played with winsound.
        """
        pcm, play_rate = self._synth_elevenlabs(text, robot)
        try:
            return self._play_samples_interruptible(pcm, play_rate)
        except Exception as exc:
            log.warning("sounddevice playback failed (%s); playing "
                        "via winsound", exc)
            return self._play_samples_winsound(pcm, play_rate)

    # ---------- edge-tts (online) ----------
    def _speak_edge(self, text, voice_name):
        import edge_tts
        tmp = os.path.join(tempfile.gettempdir(), "nalox_speech.mp3")

        async def _make():
            # v4.3: edge-tts takes a rate like "+15%" / "-10%".
            speed = self.speed()
            kwargs = {}
            if speed != 1.0:
                kwargs["rate"] = f"{int(round((speed - 1.0) * 100)):+d}%"
            communicate = edge_tts.Communicate(text, voice_name, **kwargs)
            await communicate.save(tmp)

        # v6.2 stability bound: edge-tts rides a websocket with
        # no useful total timeout of its own — a dead network
        # could park this coroutine (and the speech thread, and
        # the speaking flag) for minutes. 20 s is generous for
        # one short line; a timeout raises and say() falls
        # through to the next voice path as usual.
        async def _make_bounded():
            await asyncio.wait_for(_make(), timeout=20)

        # v6.11: ONE retry on a fresh connection for network
        # flakes (see _edge_failure_retryable). _make() builds
        # a NEW edge_tts.Communicate per run, so the second
        # pass is a genuinely fresh connection. The retry sits
        # inside this method, before _try_engine's failure
        # bookkeeping: if it lands, the chunk is a plain
        # success and the circuit breaker never hears about
        # the flake; if it also fails, the exception rises
        # ONCE and the breaker counts the chunk once, exactly
        # as before v6.11. A barge-in (stop event set) skips
        # the retry — never speak over Arjun.
        retried = False
        while True:
            try:
                asyncio.run(_make_bounded())
                break
            except Exception as exc:
                if retried or not _edge_failure_retryable(exc) \
                        or _STOP_EVENT.is_set():
                    raise
                retried = True
                time.sleep(EDGE_RETRY_BACKOFF_SECONDS)
        if retried:
            self._log_edge_retry_ok()
        # v7.1: a fixed line's MP3 joins the disk cache
        # before playback (read back from the temp file the
        # synthesis just wrote).
        if self._fixed_active and not self.robot_on():
            try:
                with open(tmp, "rb") as fh:
                    _mp3 = fh.read()
            except Exception:
                _mp3 = None
            if _mp3:
                self._cache_store_fixed(
                    "edge-tts", text, voice_name,
                    mp3_bytes=_mp3)
        return self._play_mp3_interruptible(tmp)

    def _log_edge_retry_ok(self):
        """The v6.11 edge-tts retry landed — one log line
        per reply at most (the flag resets in say() with
        the rest of the per-reply state)."""
        if self._edge_retry_noted:
            return
        self._edge_retry_noted = True
        line = "[voice] edge-tts retry ok"
        log.info(line)
        _lb("VOICE", line)

    # ---------- Google Cloud Text-to-Speech (v6.8, online) ----------
    def _speak_google_cloud(self, text, lang=None):
        """Google Cloud TTS — the male-voice layer (v6.8).

        The translate_tts layer below speaks Bengali with a
        female voice and offers no alternative; this API has
        bn-IN-Standard-B, a MALE Bengali voice (the owner's
        standing rule: Nalox is a boy, his Bengali voice is
        male). One REST call per chunk: POST
        texttospeech.googleapis.com/v1/text:synthesize with
        his key as the ?key= parameter (the shape this API
        documents for API-key auth), the voice picked by the
        text's language class (google_cloud_voice), MP3 out —
        base64 audioContent, decoded and concatenated, then
        played through the SAME MCI path as every network
        engine, so barge-in/stop behaves identically. Any
        non-200 (a 400 on a voice name included) raises —
        an engine failure, and the chain moves on."""
        audio = self._take_prefetched("google-cloud-tts",
                                      text)
        if audio is None:
            audio = self._synth_google_cloud(text, lang)
        # v7.1: a fixed line's MP3 joins the disk cache.
        self._cache_store_fixed(
            "google-cloud-tts", text,
            google_cloud_voice(google_tts_lang(text, lang))[1],
            mp3_bytes=audio)
        tmp = os.path.join(tempfile.gettempdir(),
                           "nalox_google_cloud.mp3")
        with open(tmp, "wb") as fh:
            fh.write(audio)
        # v6.14: the next chunk's synthesis (if say() armed
        # one for this engine) starts NOW, so it overlaps
        # this chunk's playback instead of queuing behind
        # it.
        self._maybe_start_prefetch("google-cloud-tts")
        return self._play_mp3_interruptible(tmp)

    def _synth_google_cloud(self, text, lang=None):
        """The synthesis half of _speak_google_cloud (the
        v6.14 split): every piece's REST call, concatenated
        MP3 bytes out, raising exactly as the fused version
        did. Separate so the prefetch thread can run it
        while the previous chunk plays."""
        import base64

        import requests
        key = (self.cfg.get("google_tts_api_key") or "").strip()
        if not key:
            raise RuntimeError("Google Cloud TTS key not set")
        language_code, voice_name = google_cloud_voice(
            google_tts_lang(text, lang))
        audio = b""
        for piece in google_tts_chunks(
                text, limit=GOOGLE_CLOUD_TTS_MAX_CHARS):
            resp = requests.post(
                GOOGLE_CLOUD_TTS_URL,
                params={"key": key},
                json={"input": {"text": piece},
                      "voice": {"languageCode": language_code,
                                "name": voice_name},
                      "audioConfig": {"audioEncoding": "MP3"}},
                timeout=GOOGLE_CLOUD_TTS_TIMEOUT)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Google Cloud TTS HTTP {resp.status_code}")
            content = (resp.json().get("audioContent") or "")
            if not content:
                raise RuntimeError(
                    "Google Cloud TTS returned no audio")
            audio += base64.b64decode(content)
        if not audio:
            raise RuntimeError("Google Cloud TTS returned no audio")
        return audio

    # ---------- Google Translate TTS (v6.6, online) ----------
    def _speak_google(self, text, lang=None):
        """Google's voice — the layer that exists so a Bengali
        line is SPOKEN IN BENGALI even when ElevenLabs is down
        (402) and edge-tts flakes out ("No audio was received"
        on every chunk, field 2026-11-15 19:24 IST — after
        which pyttsx3, an English Windows voice, read the
        Bengali reply aloud as gibberish and Arjun heard only
        the word "sir").

        Raw HTTPS to the public translate_tts endpoint (the
        one the Translate web page uses; no new dependency).
        The language follows the requested lang, else the
        text's own script (google_tts_lang); long text is
        split at google_tts_chunks boundaries and the MP3
        pieces are concatenated — MP3 frames play back-to-back
        through the SAME MCI path edge-tts audio uses, so
        barge-in/stop behaves identically."""
        audio = self._take_prefetched("google-tts", text)
        if audio is None:
            audio = self._synth_google(text, lang)
        # v7.1: a fixed line's MP3 joins the disk cache.
        self._cache_store_fixed(
            "google-tts", text, google_tts_lang(text, lang),
            mp3_bytes=audio)
        tmp = os.path.join(tempfile.gettempdir(), "nalox_google.mp3")
        with open(tmp, "wb") as fh:
            fh.write(audio)
        # v6.14: the next chunk's synthesis (if say() armed
        # one for this engine) starts NOW, so it overlaps
        # this chunk's playback instead of queuing behind
        # it (field 2026-11-15 22:40 IST: a two-chunk
        # google-tts reply took 8.9 s to speak, the second
        # synthesis waiting on the first playback).
        self._maybe_start_prefetch("google-tts")
        return self._play_mp3_interruptible(tmp)

    def _synth_google(self, text, lang=None):
        """The synthesis half of _speak_google (the v6.14
        split): the translate_tts piece loop, concatenated
        MP3 bytes out, raising exactly as the fused version
        did. Separate so the prefetch thread can run it
        while the previous chunk plays."""
        import requests
        tl = google_tts_lang(text, lang)
        audio = b""
        for piece in google_tts_chunks(text):
            resp = requests.get(
                GOOGLE_TTS_URL,
                params={"ie": "UTF-8", "q": piece, "tl": tl,
                        "client": "tw-ob"},
                headers={"User-Agent": GOOGLE_TTS_UA,
                         "Referer": "https://translate.google.com/"},
                timeout=GOOGLE_TTS_TIMEOUT)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Google TTS HTTP {resp.status_code}")
            if len(resp.content) < 100:
                raise RuntimeError("Google TTS returned no audio")
            audio += resp.content
        if not audio:
            raise RuntimeError("Google TTS returned no audio")
        return audio

    # ---------- v6.14: one-chunk TTS prefetch ----------
    def _start_prefetch(self, engine, text, lang, gen):
        """Synthesize ONE future chunk on a daemon thread —
        synthesis ONLY (never playback, never bookkeeping).
        The outcome lands in _prefetch_slot: the bytes on
        success, the exception on failure. The consumer
        (_take_prefetched) re-raises a stored failure
        inside the engine's own attempt, so it is booked
        exactly like a serial synthesis failure, once."""
        slot = {"gen": gen, "engine": engine, "text": text,
                "audio": None, "exc": None, "thread": None}

        def _run():
            try:
                if engine == "google-tts":
                    slot["audio"] = self._synth_google(
                        text, lang)
                else:
                    slot["audio"] = \
                        self._synth_google_cloud(text, lang)
            except Exception as exc:
                slot["exc"] = exc

        thread = threading.Thread(
            target=_run, daemon=True,
            name="nalox-tts-prefetch")
        slot["thread"] = thread
        self._prefetch_slot = slot
        thread.start()

    def _maybe_start_prefetch(self, engine):
        """Called by a prefetchable engine at the moment
        its playback is about to start: say() armed the
        NEXT chunk's text, and THIS engine — the one
        actually serving the current chunk — adopts the
        arm and begins synthesizing that text through its
        own synthesis now, so the synthesis overlaps this
        chunk's playback. A stale arm, or a stop already
        in flight, starts nothing. The slot is stamped
        with this engine: only a later attempt BY THE
        SAME engine for the same text consumes it."""
        nxt = self._prefetch_next
        if not nxt:
            return
        gen, text, lang = nxt
        if gen != self._reply_gen:
            return
        if _STOP_EVENT.is_set():
            return
        self._prefetch_next = None
        self._start_prefetch(engine, text, lang, gen)

    def _take_prefetched(self, engine, text):
        """Consume this engine's prefetch slot for `text`:
        the synthesized bytes — or raise the stored
        failure, which the engine's own attempt then books
        through the normal _try_engine path, exactly once.
        Returns None when there is nothing usable (no
        slot, a stale generation, a different engine or
        text): the caller synthesizes serially, exactly
        as before v6.14. A slot is consumed at most once,
        and a slot left over from an interrupted reply is
        never consumed at all (say() bumps the generation
        on every reply)."""
        slot = self._prefetch_slot
        if slot is None:
            return None
        self._prefetch_slot = None
        if slot["gen"] != self._reply_gen \
                or slot["engine"] != engine \
                or slot["text"] != text:
            return None
        thread = slot["thread"]
        if thread is not None:
            # Still synthesizing (the previous chunk was
            # short): wait for it — bounded by the synth's
            # own per-piece HTTP timeouts, and never worse
            # than synthesizing serially from this point.
            thread.join()
        if slot["exc"] is not None:
            raise slot["exc"]
        return slot["audio"]

    # ---------- v7.1: fixed-line TTS cache ----------
    def _fixed_cache_voice(self, engine, text, lang, lclass,
                           is_bengali):
        """The voice `engine` would speak THIS text with —
        the cache key's voice component — or None when the
        engine is not eligible for this line at all. Mirrors
        _try_engine's identity gates (keys, the edge-tts
        language rule); breaker/stickiness state is health,
        not identity, and plays no part here."""
        if engine == "elevenlabs":
            if not (self.cfg.get("elevenlabs_api_key")
                    or "").strip():
                return None
            voice = (self.cfg.get("elevenlabs_voice_id")
                     or "").strip()
            return voice or None
        if engine == "edge-tts":
            want_edge = is_bengali or bool(
                self.cfg.get("use_edge_tts"))
            if not want_edge:
                return None
            if is_bengali:
                return self.cfg.get("bn_voice",
                                    "bn-BD-PradeepNeural")
            return self.cfg.get("edge_tts_voice",
                                "en-US-ChristopherNeural")
        if engine == "google-cloud-tts":
            if not (self.cfg.get("google_tts_api_key")
                    or "").strip():
                return None
            return google_cloud_voice(lclass)[1]
        if engine == "google-tts":
            return lclass
        return None

    def _fixed_cache_path(self, engine, voice, text):
        """Content-hash path for one (engine, voice, speed,
        text) rendering — the engine's native format."""
        key = hashlib.sha256(
            f"{engine}\n{voice}\n{self.speed():.2f}\n{text}"
            .encode("utf-8")).hexdigest()
        ext = ".wav" if engine == "elevenlabs" else ".mp3"
        return os.path.join(TTS_CACHE_DIR, key + ext)

    def _fixed_cache_lookup(self, text, lang, lclass,
                            is_bengali):
        """(engine, path) of a cached rendering of this
        fixed line, or None. The language's remembered
        engine goes first (the voice he actually hears),
        then the canonical chain order."""
        if len(text) > _FIXED_CACHE_MAX_CHARS:
            return None
        order = []
        pref = (self._vstate.get("last_good") or {}).get(
            lclass)
        if pref in _FIXED_CACHE_ENGINES:
            order.append(pref)
        for engine in _VOICE_ENGINES:
            if engine in _FIXED_CACHE_ENGINES \
                    and engine not in order:
                order.append(engine)
        for engine in order:
            voice = self._fixed_cache_voice(
                engine, text, lang, lclass, is_bengali)
            if not voice:
                continue
            path = self._fixed_cache_path(engine, voice,
                                          text)
            try:
                if os.path.isfile(path) \
                        and os.path.getsize(path) > 0:
                    return engine, path
            except Exception:
                continue
        return None

    def _play_fixed_cached(self, engine, path, text):
        """Play a cached fixed line through the engine's
        own interruptible player — barge-in/stop cuts it
        exactly like a live synthesis. Logged as tts-cache
        and recorded NOWHERE else: a hit is neither an
        engine success nor a failure (breaker-neutral)."""
        if engine == "elevenlabs":
            samples, rate = self._read_wav(path)
            try:
                result = self._play_samples_interruptible(
                    samples, rate)
            except Exception:
                result = self._play_samples_winsound(
                    samples, rate)
        else:
            result = self._play_mp3_interruptible(path)
        self._spoken("tts-cache", text, result)
        return result

    def _cache_store_fixed(self, engine, text, voice,
                           mp3_bytes=None, wav_samples=None,
                           wav_rate=None):
        """Populate the fixed-line cache after a successful
        live synthesis (v7.1). Only inside a fixed say and
        never on the robot path (a robotized rendering is a
        different sound, and the robot path never reads the
        cache). Never raises — a cache failure must not
        cost the line that was just spoken."""
        if not self._fixed_active or self.robot_on():
            return
        if not text or len(text) > _FIXED_CACHE_MAX_CHARS:
            return
        try:
            path = self._fixed_cache_path(engine, voice,
                                          text)
            if os.path.isfile(path) \
                    and os.path.getsize(path) > 0:
                return
            os.makedirs(TTS_CACHE_DIR, exist_ok=True)
            if mp3_bytes is not None:
                if not mp3_bytes:
                    return
                with open(path, "wb") as fh:
                    fh.write(mp3_bytes)
            elif wav_samples is not None:
                self._write_wav(path, wav_samples, wav_rate)
        except Exception:
            pass

    # ---------- result bookkeeping ----------
    def _spoken(self, path, text, result):
        note = " (interrupted)" if result == "interrupted" else ""
        log.info("Spoke via %s%s.", path, note)
        _lb("VOICE", f"via {path}{note}: {text}")

    def _failed(self, path, exc):
        log.warning("%s failed: %s", path, exc)
        _lb("ERROR", f"Voice path {path} failed: {exc}")

    # ---------- public ----------
    def say(self, text, lang=None, on_chunk=None, fixed=False):
        """Speak one line. Returns "done" or "interrupted".

        "interrupted" means Arjun barged in (voice.stop() was
        called) — callers should listen to him right away, and an
        interruption is never counted as a voice failure.

        v6.5 LIVE CHUNKS: with on_chunk attached, the reply is
        spoken SENTENCE BY SENTENCE and on_chunk(chunk) fires
        the moment each sentence STARTS — the Command Center's
        chat bubble grows in step with the voice (the IRIS-reel
        feel the owner asked for) instead of dumping the whole
        line at once. Each chunk runs the full voice priority
        chain on its own, so a mid-reply failover (edge-tts →
        pyttsx3) simply continues the sequence: no chunk is
        repeated and none is lost. A stop/barge-in ends the
        loop at once — later chunks are never fired, so the
        bubble freezes at exactly what was spoken. Without
        on_chunk the behaviour is byte-for-byte the old one.

        v7.1 FIXED LINES: fixed=True marks one of Nalox's
        genuinely fixed strings (the boot greeting, the wake
        ack, the could-not-hear line, the mic warning — the
        call sites live in nalox.py). A fixed line is served
        from the TTS disk cache when a rendering exists and
        populates the cache when the live chain synthesizes
        it (see the TTS_CACHE_DIR note). The cache unit is
        the spoken chunk: the marked lines are single
        sentences, and a chunk of a fixed line is itself a
        fixed string. Dynamic replies never pass fixed=True
        — that discipline lives at the call sites, which is
        why there are exactly four of them.
        """
        if not text:
            return "done"
        # v6.6: a new reply starts with a clean stickiness
        # slate — engines that failed during an EARLIER reply
        # are retried (subject to their session breakers);
        # engines that fail during THIS reply are skipped for
        # its remaining chunks.
        self._reply_skip = set()
        self._edge_retry_noted = False
        # v7.1: the fixed-line cache arms for THIS call
        # only (cleared in the finally below).
        self._fixed_active = bool(fixed)
        # v6.14: a new reply invalidates every prefetch
        # trace of the old one — the generation bump makes
        # any leftover slot unconsumable, even by an
        # identical text.
        self._reply_gen += 1
        self._prefetch_next = None
        self._prefetch_slot = None
        _speak_begin()
        _started = time.monotonic()
        try:
            chunks = speech_chunks(text) if on_chunk else []
            if not chunks:
                return self._say_impl(text, lang)
            result = "done"
            for idx, chunk in enumerate(chunks):
                if _STOP_EVENT.is_set():
                    result = "interrupted"
                    break
                try:
                    on_chunk(chunk)
                except Exception:
                    pass
                # v6.14: arm the NEXT chunk's text — if a
                # prefetchable engine serves THIS chunk, it
                # adopts the arm at its playback start
                # (_maybe_start_prefetch) and synthesizes
                # the next chunk during this playback.
                if idx + 1 < len(chunks):
                    self._prefetch_next = (
                        self._reply_gen, chunks[idx + 1],
                        lang)
                result = self._say_impl(chunk, lang)
                # An arm this chunk's engine didn't take is
                # stale the moment the chunk ends.
                self._prefetch_next = None
                if result == "interrupted":
                    break
            return result
        finally:
            # v6.14: nothing prefetched outlives the reply —
            # a running prefetch thread finishes into a slot
            # nobody will ever read.
            self._prefetch_next = None
            self._prefetch_slot = None
            # v7.1: the fixed-line cache disarms with the
            # reply, exactly like the prefetch state.
            self._fixed_active = False
            _speak_end()
            # v4.6: overrun evidence — a say() past its budget is
            # a stuck engine path; the speaking-flag watchdog
            # guarantees the flag itself recovers.
            _took = time.monotonic() - _started
            _budget = say_budget_seconds(text)
            if _took > _budget:
                log.error("say() overran its budget: %.1fs for "
                          "%d chars (budget %.1fs) — an engine "
                          "path is stuck; the speaking watchdog "
                          "will recover the flag",
                          _took, len(text), _budget)
                _lb("ERROR", f"[voice] say() overran its budget "
                             f"({_took:.0f}s > {_budget:.0f}s)")

    def _try_engine(self, engine, text, lang, robot, is_bengali,
                    force=False):
        """ONE engine attempt (v6.7 D refactor of the old
        linear _say_impl): the engine's spoken result
        ("done"/"interrupted") on success, None when it is
        ineligible (no key, parked, robot-gated, already
        failed this reply) or it failed — with exactly the
        bookkeeping the linear chain always did (spoken
        lines, breaker notes, failure lines). force=True
        bypasses the ElevenLabs block for one attempt (the
        pre-v7.3 in-say() re-probe used it; the background
        probe now works through _synth_elevenlabs instead,
        and no production caller passes force anymore)."""
        if engine == "elevenlabs":
            # 1) ElevenLabs — Arjun's own voice, English +
            # Bengali. v4.8: skipped entirely once the breaker
            # has tripped for the current key (401/402).
            _el_key = (self.cfg.get("elevenlabs_api_key")
                       or "").strip()
            if not _el_key:
                return None
            if not force and self._elevenlabs_blocked(_el_key):
                return None
            if "elevenlabs" in self._reply_skip:
                return None
            try:
                result = self._speak_elevenlabs(text, robot)
                self._spoken("ElevenLabs", text, result)
                return result
            except _ElevenLabsUnavailable as down:
                self._trip_elevenlabs(down.status, _el_key)
            except Exception as exc:
                # v6.6: an ordinary failure is also sticky
                # for the rest of this reply.
                self._reply_skip.add("elevenlabs")
                self._failed("ElevenLabs", exc)
            return None
        if engine == "edge-tts":
            # 2) edge-tts — with the robot effect ON, the
            # pyttsx3-WAV path is preferred so the effect
            # applies; edge-tts is used when robot_voice is
            # off, or use_edge_tts is on.
            if robot:
                want_edge = bool(self.cfg.get("use_edge_tts"))
            else:
                want_edge = is_bengali or bool(
                    self.cfg.get("use_edge_tts"))
            if not want_edge or self._engine_parked("edge-tts"):
                return None
            if is_bengali:
                # v4.9: default is the MALE Bengali edge voice
                # (Pradeep) — config.py's default agrees; this
                # literal is only the last-resort fallback.
                voice_name = self.cfg.get("bn_voice",
                                          "bn-BD-PradeepNeural")
            else:
                voice_name = self.cfg.get("edge_tts_voice",
                                          "en-US-ChristopherNeural")
            try:
                result = self._speak_edge(text, voice_name)
                self._note_net_success("edge-tts")
                self._spoken("edge-tts", text, result)
                return result
            except Exception as exc:
                self._failed("edge-tts", exc)
                self._note_net_failure("edge-tts", "edge-tts")
            return None
        if engine == "google-cloud-tts":
            # 2a) Google Cloud TTS (v6.8) — the MALE Bengali
            # voice (bn-IN-Standard-B), the fix for the
            # translate layer's female voice. Only attempted
            # when his Google Cloud key is pasted (Settings →
            # Voice): no key = ineligible, zero delay. Same
            # breaker/stickiness/persistence bookkeeping as
            # every network engine; the robot path skips it
            # like the other MP3 layers.
            _gc_key = (self.cfg.get("google_tts_api_key")
                       or "").strip()
            if not _gc_key or robot \
                    or self._engine_parked("google-cloud-tts"):
                return None
            try:
                result = self._speak_google_cloud(text, lang)
                self._note_net_success("google-cloud-tts")
                self._spoken("google-cloud-tts", text, result)
                return result
            except Exception as exc:
                self._failed("google-cloud-tts", exc)
                self._note_net_failure("google-cloud-tts",
                                       "Google Cloud TTS")
            return None
        if engine == "google-tts":
            # 2b) Google TTS (v6.6) — one more network voice
            # before the offline engines, for EVERY language:
            # it is the layer that guarantees Bengali / Hindi
            # text is spoken in its own language when
            # ElevenLabs is down and edge-tts is flaking. The
            # robot path skips it (that path processes pyttsx3
            # WAV samples; an MP3 cannot join it), and a parked
            # engine is skipped without a call.
            if robot or self._engine_parked("google-tts"):
                return None
            try:
                result = self._speak_google(text, lang)
                self._note_net_success("google-tts")
                self._spoken("google-tts", text, result)
                return result
            except Exception as exc:
                self._failed("google-tts", exc)
                self._note_net_failure("google-tts",
                                       "Google TTS")
            return None
        if engine == "pyttsx3":
            # 3) pyttsx3 — fresh engine every time. After two
            # failures in a row it is skipped: PowerShell
            # speaks instead, so Nalox never goes silent
            # mid-conversation.
            if self._pyttsx3_failures >= 2:
                return None
            try:
                result = self._speak_pyttsx3(text, robot)
                self._pyttsx3_failures = 0
                self._spoken("pyttsx3", text, result)
                return result
            except Exception as exc:
                self._pyttsx3_failures += 1
                log.error("pyttsx3 failed (%d in a row): %s",
                          self._pyttsx3_failures, exc)
                self._failed("pyttsx3", exc)
            return None
        if engine == "powershell":
            # 4) PowerShell System.Speech — last resort.
            try:
                result = self._speak_powershell(text)
                self._spoken("PowerShell", text, result)
                return result
            except Exception as exc:
                log.error("All TTS paths failed: %s", exc)
                _lb("ERROR", f"All voice paths failed for: {text} ({exc})")
            return None
        return None

    def _say_impl(self, text, lang=None):
        """The say() body: engines in canonical order —
        except where v6.7 D's persisted health says otherwise:

          step 1 — this language class's remembered engine
          (the one that worked last session) goes first.
          step 2 — the canonical chain, skipping anything
          already tried above.

        v7.3: there is NO step 0 anymore. The ElevenLabs boot
        re-probe left the speech path (see start_boot_probe):
        while the 401/402 block stands — tripped this session
        or restored from the persisted state — _try_engine
        skips ElevenLabs instantly (zero network, zero wait)
        and the sticky engine speaks. The background probe is
        the only thing that can clear the block mid-session.

        Every success is recorded into the persisted state;
        barge-in/budget semantics are say()'s, unchanged."""
        _STOP_EVENT.clear()
        lang = (lang or "").strip().lower()
        is_bengali = lang.startswith("bn")
        robot = self.robot_on()
        log.info("Nalox says (%s): %s", lang or "en", text)
        lclass = google_tts_lang(text, lang)
        tried = set()
        with self._lock:
            # v7.1: a FIXED line with a cached rendering
            # plays from disk — before the whole chain, so a
            # cached greeting never pays a doomed ElevenLabs
            # 402 round-trip to rediscover what it already
            # knows. Breaker-neutral (no _record_good, no
            # breaker notes); a playback failure falls through
            # to the live chain.
            if self._fixed_active and not robot:
                _hit = self._fixed_cache_lookup(
                    text, lang, lclass, is_bengali)
                if _hit is not None:
                    try:
                        return self._play_fixed_cached(
                            _hit[0], _hit[1], text)
                    except Exception:
                        pass
            pref = (self._vstate.get("last_good")
                    or {}).get(lclass)
            if pref and pref not in tried:
                result = self._try_engine(pref, text, lang,
                                           robot, is_bengali)
                tried.add(pref)
                if result is not None:
                    self._record_good(pref, lclass)
                    return result
            for engine in _VOICE_ENGINES:
                if engine in tried:
                    continue
                result = self._try_engine(engine, text, lang,
                                           robot, is_bengali)
                if result is not None:
                    self._record_good(engine, lclass)
                    return result
            return "done"
