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
import logging
import os
import re
import subprocess
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

# Session circuit breakers for the network fallback engines
# (edge-tts, Google TTS), mirroring the v4.8 ElevenLabs breaker:
# ENGINE_BREAK_FAILURES consecutive failures park the engine for
# ENGINE_BREAK_SECONDS (one log line per break); a success
# resets the count. Module-level so tests can shorten the park.
ENGINE_BREAK_SECONDS = 300.0
ENGINE_BREAK_FAILURES = 2


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
        self._net_fails = {}
        self._net_down_until = {}

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
                line = f"[voice] {label} unavailable — skipping it for a while"
                log.error(line)
                _lb("ERROR", line)

    def _note_net_success(self, engine):
        """A network engine answered (v6.6): its consecutive-
        failure count and any expired park reset."""
        self._net_fails[engine] = 0
        self._net_down_until.pop(engine, None)

    def _trip_elevenlabs(self, status, key):
        """Trip the breaker + log the ONE clear line. Later calls
        skip ElevenLabs silently — no per-utterance spam, no
        per-utterance network delay."""
        self._eleven_down = (status, _key_fingerprint(key))
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

    def _speak_pyttsx3_direct(self, text):
        """Plain pyttsx3 speak (v4.1 default local path).

        The engine lives in a worker thread; this thread polls the
        stop event and a hard timeout. Returns "done" / "interrupted";
        raises on engine error or timeout (a timeout abandons the
        worker thread — it is a daemon, and the failure counter in
        say() routes the next lines to PowerShell instead).
        """
        holder = {}

        def _run():
            engine = None
            try:
                engine = self._new_engine()
                holder["engine"] = engine
                engine.say(text)
                engine.runAndWait()
                holder["ok"] = True
            except Exception as exc:  # engine init/speak failure
                holder["error"] = exc
            finally:
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass

        worker = threading.Thread(target=_run, daemon=True,
                                  name="nalox-tts")
        worker.start()
        deadline = time.monotonic() + PYTTSX3_TIMEOUT
        while worker.is_alive():
            if _STOP_EVENT.is_set():
                engine = holder.get("engine")
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                return "interrupted"
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"pyttsx3 timed out after {PYTTSX3_TIMEOUT:.0f}s "
                    "(engine hung; thread abandoned)")
            worker.join(0.05)
        if "error" in holder:
            raise holder["error"]
        return "done"

    def _speak_pyttsx3(self, text, robot):
        """Speak with pyttsx3. Returns "done"/"interrupted".

        Robot OFF (v4.1 default): direct speak, see above.
        Robot ON (dormant): render to WAV, robotize, play via
        sounddevice (winsound fallback) — the v3.3–v3.7 path.
        """
        if not robot:
            return self._speak_pyttsx3_direct(text)
        engine = self._new_engine()
        tmp = os.path.join(tempfile.gettempdir(), "nalox_tts.wav")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            engine.save_to_file(text, tmp)
            engine.runAndWait()
        finally:
            try:
                engine.stop()
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
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

        asyncio.run(_make_bounded())
        return self._play_mp3_interruptible(tmp)

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
        tmp = os.path.join(tempfile.gettempdir(), "nalox_google.mp3")
        with open(tmp, "wb") as fh:
            fh.write(audio)
        return self._play_mp3_interruptible(tmp)

    # ---------- result bookkeeping ----------
    def _spoken(self, path, text, result):
        note = " (interrupted)" if result == "interrupted" else ""
        log.info("Spoke via %s%s.", path, note)
        _lb("VOICE", f"via {path}{note}: {text}")

    def _failed(self, path, exc):
        log.warning("%s failed: %s", path, exc)
        _lb("ERROR", f"Voice path {path} failed: {exc}")

    # ---------- public ----------
    def say(self, text, lang=None, on_chunk=None):
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
        """
        if not text:
            return "done"
        # v6.6: a new reply starts with a clean stickiness
        # slate — engines that failed during an EARLIER reply
        # are retried (subject to their session breakers);
        # engines that fail during THIS reply are skipped for
        # its remaining chunks.
        self._reply_skip = set()
        _speak_begin()
        _started = time.monotonic()
        try:
            chunks = speech_chunks(text) if on_chunk else []
            if not chunks:
                return self._say_impl(text, lang)
            result = "done"
            for chunk in chunks:
                if _STOP_EVENT.is_set():
                    result = "interrupted"
                    break
                try:
                    on_chunk(chunk)
                except Exception:
                    pass
                result = self._say_impl(chunk, lang)
                if result == "interrupted":
                    break
            return result
        finally:
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

    def _say_impl(self, text, lang=None):
        """The say() body (v4.1 paths), wrapped by say() so the
        v4.2 speaking counter covers every path and every return."""
        _STOP_EVENT.clear()
        lang = (lang or "").strip().lower()
        is_bengali = lang.startswith("bn")
        robot = self.robot_on()
        log.info("Nalox says (%s): %s", lang or "en", text)
        with self._lock:
            # 1) ElevenLabs — Arjun's own voice, English + Bengali.
            # v4.8: skipped entirely once the breaker has tripped
            # for the current key (401/402) — straight to the
            # fallback, no request, no log line.
            _el_key = (self.cfg.get("elevenlabs_api_key")
                       or "").strip()
            if _el_key and not self._elevenlabs_blocked(_el_key) \
                    and "elevenlabs" not in self._reply_skip:
                try:
                    result = self._speak_elevenlabs(text, robot)
                    self._spoken("ElevenLabs", text, result)
                    return result
                except _ElevenLabsUnavailable as down:
                    self._trip_elevenlabs(down.status, _el_key)
                except Exception as exc:
                    # v6.6: an ordinary failure is also sticky
                    # for the rest of this reply — later chunks
                    # don't re-pay it.
                    self._reply_skip.add("elevenlabs")
                    self._failed("ElevenLabs", exc)
            # 2) edge-tts — with the robot effect ON, the pyttsx3-WAV
            # path below is preferred so the effect applies; edge-tts
            # is used when robot_voice is off, or use_edge_tts is on.
            if robot:
                want_edge = bool(self.cfg.get("use_edge_tts"))
            else:
                want_edge = is_bengali or bool(self.cfg.get("use_edge_tts"))
            if want_edge and not self._engine_parked("edge-tts"):
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
            # 2b) Google TTS (v6.6) — one more network voice
            # before the offline engines, for EVERY language:
            # it is the layer that guarantees Bengali / Hindi
            # text is spoken in its own language when
            # ElevenLabs is down and edge-tts is flaking. The
            # robot path skips it (that path processes pyttsx3
            # WAV samples; an MP3 cannot join it), and a parked
            # engine is skipped without a call.
            if not robot and not self._engine_parked("google-tts"):
                try:
                    result = self._speak_google(text, lang)
                    self._note_net_success("google-tts")
                    self._spoken("google-tts", text, result)
                    return result
                except Exception as exc:
                    self._failed("google-tts", exc)
                    self._note_net_failure("google-tts",
                                           "Google TTS")
            # 3) pyttsx3 — fresh engine every time. After two failures
            # in a row it is skipped: PowerShell speaks instead, so
            # Nalox never goes silent mid-conversation.
            if self._pyttsx3_failures < 2:
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
            # 4) PowerShell System.Speech — last resort.
            try:
                result = self._speak_powershell(text)
                self._spoken("PowerShell", text, result)
                return result
            except Exception as exc:
                log.error("All TTS paths failed: %s", exc)
                _lb("ERROR", f"All voice paths failed for: {text} ({exc})")
                return "done"
