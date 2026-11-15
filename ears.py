"""Nalox's ears: always-on wake-word listening + one-shot command capture.

v2 — BILINGUAL: the whisper models are the MULTILINGUAL builds ("tiny" /
"small", not ".en"), transcription runs with language=None (auto-detect)
so Arjun can speak English OR Bengali. Transcription returns
(text, detected_language) — e.g. ("open youtube", "en") or
("ইউটিউব খোলো", "bn").

v3.3 — command model is "small" (much better Bengali than "base"), the
command transcription is biased with initial_prompt="Nalox", and the
wake-word matcher also accepts the name in Bengali script (ন্যালক্স).

Wake word  : a rolling buffer of the last ~2.5 s of mic audio,
             re-transcribed every ~0.8 s with faster-whisper "tiny"
             and fuzzy-matched against "nalox" variants (v3.7).
Command    : after the wake word, record until ~1.2 s of silence and
             transcribe with faster-whisper "small".

v3.4 - live mic level for the HUD meter (get_level()), and a wake
callback (set_wake_callback) fired the instant the wake word matches,
so Nalox can beep + flash the console the moment it hears its name.

v3.5 HOTFIX:
  - ALL transcription goes through _transcribe(), which retries with
    bare arguments if the installed faster-whisper rejects an optional
    keyword. (v3.3/v3.4 passed prompt= — not a real kwarg — and EVERY
    transcription crashed with TypeError, so the wake word never
    fired and Nalox looped on "try again". Never again.)
  - Mic AUTO-CONNECT: pick_input_device() re-picks the input device
    at the start of every wake-listen session and every command
    recording — config mic_device (name substring) if set, else the
    Windows default input. Plug the external mic in and it just
    works; the HUD gets "[mic] connected: <name>" on every change.
  - Mic meter rescaled in decibels (-55 dB..-6 dB -> 0..1, DC removed,
    fast attack / gentle decay). The old linear RMS scaling showed a
    soft voice as LOUD and a loud voice as nothing.

v3.7 — WAKE WORD RESCUE (Arjun spoke, the meter danced, but Nalox
almost never woke, so no command was ever heard):
  - ROLLING BUFFER: the wake loop keeps the last ~2.5 s of audio and
    re-transcribes it every ~0.8 s, so "Nalox" is caught wherever it
    lands — the old disjoint 1.25 s hops could slice the word in half.
  - FUZZY MATCHING: the tiny model mangles the name ("alex",
    "now lox", ...), so looks_like_wake_word() now accepts Bengali
    script, known mishearings as substrings, any token containing
    "lox"/"laks", and any token within edit distance 1 of the name.
  - VISIBILITY: every non-empty transcription is posted to the HUD
    as "[heard] <text>" (repeats throttled), so Arjun can SEE what
    Nalox thinks he said.
  - TALK BUTTON: request_command() sets an event the wake loop
    checks on every sub-chunk — a guaranteed wake path that needs
    no wake word at all. (v4.1: the HUD button itself is gone at
    Arjun's demand — voice only — but the hook stays.)

v4.1 — BARGE-IN: monitor_interrupt() runs while Nalox speaks,
listening on its own stream for the wake word / "stop" / "থামো" /
"চুপ" (is_interrupt_word). On a match it calls the interrupt
callback (voice.stop) so Nalox shuts up and listens — Gemini-style.

v4.2 — LANGUAGE LOCK + HALLUCINATION KILL (Arjun's ruling: he
speaks ONLY English, Bengali and Hindi):
  - The tiny wake model was inventing text from room silence —
    Turkish, Korean, French, the classic Japanese "thanks for
    watching" — and flooding [heard]. Four defences now:
    (1) DECODING GUARDS on every transcription (VAD filter,
        condition_on_previous_text=False, no-speech / log-prob /
        compression-ratio thresholds) so silence decodes as silence;
    (2) an ADAPTIVE ENERGY GATE: the wake loop only transcribes
        when the buffer is clearly louder than the tracked ambient
        noise floor, so a quiet room costs no transcription at all;
    (3) a GARBAGE FILTER (is_garbage): punctuation floods, known
        hallucination phrases and one-token-on-repeat can never
        wake Nalox, never reach [heard], never become a command;
    (4) a LANGUAGE POLICY for commands (transcribe_command):
        auto-detect, but only en/bn/hi may pass — anything else is
        re-transcribed forced Bengali, then forced English, and
        only filter-clean text is delivered.
  - NO SELF-HEARING: while voice.is_speaking() is true the wake
    loop drains the mic without transcribing (plus a 0.4 s echo
    tail after speech ends), and the command recorder waits for
    Nalox to finish talking before it starts. The barge-in monitor
    is exempt — it is the designated during-speech listener.

v4.3 — EARS 2.0 (field evidence 09:24 IST: the tiny model with
forced English STILL rendered background sound as fluent English
YouTube-style lines — "don't forget to subscribe", "thank you.
bye." — and Arjun's Bengali never appeared as Bengali):
  - The wake stage is now an ENERGY SEGMENTER: 0.1 s chunks are
    watched continuously; a segment starts when a chunk beats the
    adaptive gate and ends after 0.7 s of quiet (5 s max). Room
    silence produces NO segments, so nothing is transcribed from
    it — the fixed rolling windows and the tiny wake model are
    gone from the wake path.
  - Each segment is transcribed ONCE with the command model
    ("small", config wake_model) and AUTO-DETECTED language, so
    Bengali speech shows up as Bengali text in [heard] — Gemini-
    style: he speaks in his own language and sees his own words.
  - (v4.5 REVERSED the no_speech drop that stood here — see the
    v4.5 section below. is_garbage() is now the only filter.)
  - Wake matching runs on the segment text: fuzzy Latin + Bengali
    + NEW Devanagari variants (नैलॉक्स / नालोक्स / नेलॉक्स). If words
    follow the wake word in the same breath ("Nalox কেমন আছো"),
    the remainder is delivered as the command immediately — no
    second recording round.
  - The barge-in monitor still uses the tiny model (it only hunts
    interrupt words); the command recorder keeps the v4.3
    single-pass script-acceptance rule.

v4.4 — SPEED (Arjun's 09:51 field report):
  - The command recorder now endpoints through the Segmenter on
    the ADAPTIVE gate (0.8 s trail, 8 s cap) instead of the old
    fixed-RMS silence rule that recorded a full 12 s of room
    noise and made the small model transcribe it for 30-47 s.
    Clips with under 0.3 s of real speech are never transcribed.
  - Wake + command transcription is biased with COMMAND_PROMPT
    (Nalox's vocabulary in all three scripts) instead of the
    bare name, and a prompt-ECHO guard drops any transcription
    that just parrots the prompt back.

v4.5 — NEVER DROP HIS VOICE (Arjun's 10:09 field report):
  - THE BUG: his real Bengali command ("...ওপেন কোড় য়ুটুব ওপেন
    কোড়ুটুব") was killed by the v4.3 hallucination drop — the
    log read "[ears] dropped likely-hallucination (no_speech
    1.00)". Whisper's no_speech_prob is miscalibrated for
    Bengali: it saturates at 1.00 on GENUINE Bengali speech.
    The drop trusted a number that lies in exactly the language
    Arjun speaks most.
  - NEW DELIVERY RULE (wake segments + commands): the segmenter
    only completes a segment on sustained speech energy, so a
    completed segment IS speech. If its text passes is_garbage()
    it is DELIVERED — posted as [heard], matched for the wake
    word, handed to the brain — regardless of no_speech_prob.
    no_speech is still computed and LOGGED (info only, on the
    heard-segment line); it never gates anything again. The
    only drops left are is_garbage() itself (blacklist phrases,
    token repetition, punctuation soup) and empty text.
  - FASTER WAKE: the default wake model is now "base" (config
    wake_model) — roughly 3x faster than "small" on CPU — while
    commands keep the accurate "small". On a LOUD segment (peak
    chunk RMS >= 3x the gate threshold — unmistakably real
    speech) the base pass gets ONE retry with the command model
    when it returns garbage/empty, OR when its clean text is
    labelled with a language outside {en, bn, hi} (base heard
    Arjun's Hindi as Spanish in testing — the name survived but
    the words were wrecked; small heard them perfectly). Weak
    segments get no retry (probably noise; silence stays cheap).

v4.6 — STABILITY (Arjun's 10:26 field report: "মাঝে মাঝে থেমে
যাচ্ছে" — Nalox sometimes hangs midway, deaf until restarted):
  - NON-BLOCKING TRANSCRIPTION: the wake loop used to transcribe
    each completed segment INLINE, so one stuck transcription
    froze capture itself — no chunks read, meter dead, wake word
    impossible. Segments now go onto a bounded queue
    (TRANSCRIBE_QUEUE_MAX, drop-oldest on overflow) drained by a
    dedicated worker thread; capture never waits for the model.
    A long-running transcription earns an ERROR log line while
    listening carries on. (v6.2: the decode itself moved into
    a worker PROCESS with hard deadlines — see the v6.2 note
    at the end of this header.)
  - MIC STREAM HEALTH: the wake capture is a callback stream
    feeding a queue, so a SILENTLY DEAD stream (device sleep /
    USB glitch — PortAudio just stops delivering) is detectable:
    no chunk for MIC_SILENT_SECONDS (10 s) while listening ->
    the stream is reopened and "[mic] stream reopened (silent
    10s+)" is logged. Reopens are at most one per
    MIC_REOPEN_MIN_INTERVAL (30 s); consecutive failures keep
    that cadence and log an ERROR from the third on.
  - BENGALI WAKE RESCUE, trigger (c): a LOUD segment whose base
    reading is clean but has NO wake match and whose dominant
    script is Bengali or Devanagari also earns the one small
    retry — base can mangle the NAME itself in Bengali speech,
    and the cleaner small reading may contain it. English-
    dominant no-match segments never retry (fast path + CPU).

v4.8 — CRASH CONTAINMENT (Arjun's 11:54 log: the main loop ate
a bare "ValueError: max() iterable argument is empty"):
  - transcribe_command / transcribe_file are wrapped — a model
    failure on a degenerate clip (faster-whisper's VAD internals
    raise exactly that ValueError) now reads as "nothing heard"
    instead of escaping into nalox.py's main loop.
  - The script-vote helpers (_script_lang / _dominant_script)
    pick their winner without max() over the vote dict, so the
    empty-vote case is structurally impossible there too.

v5.1 — CLOUD EARS (Arjun's #1 pain, from the IRIS reel he sent:
the demo assistant hears Hindi PERFECTLY because its hearing
is cloud AI; the local small model still garbles his Bengali):
  - The COMMAND path (listen_for_command only — the wake loop
    stays local, exactly as it was) tries cloud transcription
    FIRST when config cloud_ears != "off" and a usable key
    exists: (1) GEMINI audio (the field-confirmed key), then
    (2) GROQ whisper-large-v3, then (3) the local faster-whisper
    policy — transcribe_command_best(). A cloud timeout / error
    / empty or guard-rejected transcript falls back to local;
    local hearing existing means a command is NEVER lost to a
    cloud failure (the standing rule: answer everything heard).
  - Cloud transcripts pass the SAME guards as local ones:
    is_garbage(), the script/language lock ({en, bn, hi} via
    _script_plausible + _script_lang) and the prompt-echo guard.
  - The winning ear is logged on every command:
    "[ears] heard via cloud:gemini" / "cloud:groq" / "local".

v6.2 — TRANSCRIPTION LIVES IN A WORKER PROCESS (the owner's
field screenshot, 2026-11-15 17:38 IST: the follow-up
transcription WEDGED twice in one session — "[ears]
transcription stuck" x2 — and his "wake up" never landed):
  - The v4.6/v5.2/v6.0 design kept decodes in-process: a
    worker THREAD, a stuck watchdog, generation bumps, and
    finally per-instance decode locks + model rotation.
    All of it shared one fatal assumption — that a wedged
    native decode can be abandoned while its process lives.
    It cannot: the thread stays inside ctranslate2 forever,
    and every defence only routed around it.
  - v6.2 moves EVERY local faster-whisper decode (wake
    passes, the local command fallback, barge-in windows,
    Telegram voice-note files) into a dedicated worker
    PROCESS (_TxWorkerClient + _tx_process_main,
    multiprocessing). The parent asks, the process answers;
    each request carries a HARD deadline (wake 4 s, command
    12 s, file 30 s). On deadline expiry the parent KILLS
    and respawns the worker — a wedged native decode dies
    with its process — and logs "[ears] worker restarted
    (timeout)". The main process never blocks on a
    transcription again. The worker preloads its models at
    spawn, is a daemon (no orphan outlives the parent, as
    far as stdlib allows on Windows), and a crash-looping
    worker earns a respawn cap + backoff instead of a fork
    storm. Cloud ears are unchanged (already bounded HTTP).
  - v6.3 keeps the process isolation and fixes its one
    remaining flaw — the timeout CASCADE (field log
    2026-11-15 18:18–18:20: a restart every ~4 s, then the
    backoff pause): deadlines now run from the worker's
    per-job ACK after a readiness handshake (preload never
    eats decode time), the wake deadline is 8 s, a timed-out
    worker is PINGED before it is killed (slow ≠ wedged),
    consecutive timeouts trip a self-expiring wake cooldown,
    and identical restart lines are throttled. Cloud ears
    tighten to 6 s per provider (fast switching, with the
    brain).
  - The v6.0 decode locks / model rotation are RETIRED:
    inside the worker, decodes are strictly serial, so
    there is nothing left to lock.
"""
import collections
import logging
import math
import multiprocessing
import queue
import re
import threading
import time
import unicodedata

import numpy as np

log = logging.getLogger("nalox.ears")

SAMPLE_RATE = 16000
WAKE_WINDOW_SECONDS = 2.5        # rolling buffer length
WAKE_CHECK_SECONDS = 0.8         # re-transcribe the buffer every ~0.8 s
SILENCE_RMS = 0.012              # below this = "silence"
COMMAND_SILENCE_SECONDS = 1.2  # legacy (pre-v4.4 recorder); kept for reference
COMMAND_MAX_SECONDS = 8  # v4.4: recorder hard cap (was 12) — bounds transcription time
MIN_SPEECH_SECONDS = 0.4

# --------------------------------------- language lock (v4.2)
# Arjun speaks ONLY these three languages. A command transcription
# in anything else is by definition a Whisper hallucination (the
# v4.1 [heard] feed filled up with Turkish / Korean / French /
# Japanese invented from room silence) and is re-decoded, never
# delivered. The wake word is always decoded as English — it IS an
# English word.
ALLOWED_LANGS = {"en", "bn", "hi"}

# --------------------------------------- decoding guards (v4.2)
# Passed to EVERY faster-whisper transcription (wake, command,
# barge-in monitor, files). VAD trims non-speech before decoding;
# condition_on_previous_text=False stops one hallucinated phrase
# from priming the next; the three thresholds make the decoder
# reject low-confidence / repetitive / no-speech segments instead
# of inventing multilingual text from noise.
_DECODE_GUARDS = dict(
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
    condition_on_previous_text=False,
    no_speech_threshold=0.6,
    log_prob_threshold=-1.0,
    compression_ratio_threshold=2.4,
)

# --------------------------------------- vocabulary bias (v4.4)
# Whisper decodes far better when it knows the world it is
# listening to. The old bias was the bare name ("Nalox"); v4.4
# lists Nalox's whole command world in all three scripts — the
# platform names plus the core verbs/phrases in Bengali + Hindi —
# which measurably reduces the garbling Arjun saw at 09:51
# ("য়ুটুব বুপন কোড়ো" for "YouTube ওপেন করো"). Kept SHORT
# (well under 150 characters): a long prompt starts leaking into
# the output, and _looks_like_prompt_echo below drops any
# transcription that parrots it back verbatim.
COMMAND_PROMPT = ("Nalox, YouTube, Chrome, খোলো, করো, গান বাজাও, "
                  "কেমন আছো, খবর, कैसे हो, गाना बजाओ")


def _echo_tokens(s):
    """Whitespace tokens, punctuation-stripped (script-safe: no
    regex \\w, which would shred Bengali/Devanagari words at
    their vowel signs)."""
    return [t.strip(" .,!?।") for t in (s or "").lower().split()
            if t.strip(" .,!?।")]


def _looks_like_prompt_echo(text, prompt):
    """True if a transcription just parrots the initial_prompt.

    Whisper occasionally "answers" with the prompt itself. The
    guard is deliberately narrow so real commands can never trip
    it: the prompt needs >= 3 tokens, and the output must either
    BE the prompt or BEGIN with its full token run (>= 4 tokens)
    while being no longer than the prompt itself (+1 token).
    A real command ("nalox open chrome", "গান বাজাও") shares at
    most the first token or two and always passes.
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


# --------------------------------------- stability watchdogs (v4.6)
# Arjun's "মাঝে মাঝে থেমে যাচ্ছে": Nalox would hang midway — the
# wake loop transcribed INLINE (one stuck decode froze capture)
# and a silently dead mic stream blocked read() forever. The
# mic-side bound lives below (MIC_SILENT_SECONDS); the decode
# side is bounded since v6.2 by the worker PROCESS deadlines
# (WAKE_TX_DEADLINE / COMMAND_TX_DEADLINE near _TxWorkerClient)
# — the v4.6 stuck-warning and the v5.2 abandon watchdog are
# retired with the in-process machinery they guarded.
TRANSCRIBE_QUEUE_MAX = 3        # pending wake segments, drop-oldest
MIC_SILENT_SECONDS = 10.0       # no chunk for this long = dead stream
MIC_REOPEN_MIN_INTERVAL = 30.0  # at most one stream reopen per this


class _MicHealth:
    """Bookkeeping for the silent-stream watchdog (v4.6).

    Pure time arithmetic — no I/O — so the reopen policy is
    unit-testable with a fake clock. The wake loop feeds it real
    monotonic timestamps: note_chunk() on every arrived chunk,
    reopen_due() when a read times out, note_reopen() when it
    acts. Policy: a reopen is due when the stream has been
    silent for silent_seconds AND the last reopen (or loop
    start) was at least min_interval ago. Consecutive silent
    periods count up in .failures; any real chunk resets them.
    """

    def __init__(self, silent_seconds=MIC_SILENT_SECONDS,
                 min_interval=MIC_REOPEN_MIN_INTERVAL):
        self.silent_seconds = float(silent_seconds)
        self.min_interval = float(min_interval)
        self.failures = 0

    def note_chunk(self):
        self.failures = 0

    def reopen_due(self, now, last_chunk_at, last_reopen_at):
        return (now - last_chunk_at > self.silent_seconds
                and now - last_reopen_at >= self.min_interval)

    def note_reopen(self):
        self.failures += 1
        return self.failures

# --------------------------------------- garbage filter (v4.2)
# Phrases Whisper famously hallucinates from silence/applause. A
# transcription containing one is never a real command from Arjun.
_HALLUCINATION_PHRASES = [
    "thank you for watching",
    "thanks for watching",
    "ご視聴ありがとうございました",   # "thank you for watching" (JP)
    "ご視聴ありがとう",
    "subtitles by",
    "please subscribe",
    "subscribe to my channel",
    # v4.3 field additions (observed on Arjun's machine, 09:24 IST)
    "don't forget to subscribe",
    "dont forget to subscribe",
]

# How long after Nalox stops speaking the wake loop keeps draining
# the mic instead of transcribing (speaker echo tail, v4.2).
ECHO_TAIL_SECONDS = 0.4

# Latin mishearings of "Nalox" the tiny wake model actually produces,
# matched as substrings (v3.7). "alex" is included on purpose: it is
# the classic Whisper mishearing of "Nalox", and Arjun gives Nalox no
# other commands containing "Alex".
WAKE_SUBSTRINGS = [
    "nalox", "nalaks", "nalex", "nell ox", "now lox", "no lox",
    "knalox", "nalok", "nalux", "alex",
]

# Bengali-script spellings (Whisper sometimes writes the name in
# Bengali script when Arjun speaks Bengali).
WAKE_VARIANTS_BN = ["ন্যালক্স", "ন্যালোক্স"]

# Devanagari spellings (v4.3) — same idea for Hindi speech.
# v5.2: "नालॉक्स" added — the spelling in Arjun's own wake-up
# phrase ("नालॉक्स उठो"); without it the Hindi wake-up (and any
# one-breath Hindi command in that spelling) never matched.
WAKE_VARIANTS_HI = ["नैलॉक्स", "नालोक्स", "नेलॉक्स", "नालॉक्स"]

# v5.2 WAKE-UP PHRASES (Arjun's instruction, 2026-11-15):
# "Nalox, wake up" is stronger than the bare wake word — it
# also SHOWS the Nalox window instantly (nalox.py registers a
# wake-up callback that raises the HUD). Bare "Nalox" keeps the
# old behaviour (listen only, window untouched). The verbs are
# matched next to the name in all three languages, in native
# script or mixed (Whisper happily writes "nalox ওঠো").
WAKE_UP_VERBS_BN = ["ওঠো", "উঠো", "জাগো", "জেগে"]
WAKE_UP_VERBS_HI = ["उठो", "जागो", "उठ", "जाग"]
# Latin garbles of "wake up" the wake model produces: the
# adjacent token pair, and the squashed single token "wakeup"
# (checked directly in looks_like_wake_up).
_WAKE_UP_LATIN_PAIRS = [("wake", "up"), ("weak", "up"),
                        ("wake", "app"), ("wak", "up")]


def looks_like_wake_up(text):
    """True for a WAKE-UP utterance: the wake word AND a
    wake-up verb ("wake up" / ওঠো / জাগো / उठो / जागो), in any
    of Nalox's three languages or scripts, garbles included.

    The name is mandatory (a bare "wake up" said to someone
    else in the room must not pop the window), and so is the
    verb (a bare "Nalox" must NOT pop the window — that is the
    whole point of having two phrases)."""
    if not text or not looks_like_wake_word(text):
        return False
    raw = text.lower()
    if any(v in raw for v in WAKE_UP_VERBS_BN):
        return True
    if any(v in raw for v in WAKE_UP_VERBS_HI):
        return True
    cleaned = re.sub(r"[^a-z ]", " ", raw)
    tokens = [t for t in re.sub(r"\s+", " ", cleaned).split() if t]
    if "wakeup" in tokens:
        return True
    for a, b in zip(tokens, tokens[1:]):
        if (a, b) in _WAKE_UP_LATIN_PAIRS:
            return True
    # "nalox wake" with nothing after it: Whisper clips the
    # final "up" often enough that the lone verb still counts
    # when it directly follows the name token.
    for i, tok in enumerate(tokens):
        if tok == "wake" and i > 0 and _is_wake_token(tokens[i - 1]):
            return True
    return False


def _strip_wake_up_phrase(remainder):
    """Remove a leading wake-up phrase from a one-breath
    remainder: "wake up" / "ওঠো" / "জাগো" / "उठो" said right
    after the name is the wake-up ADDRESS, not a command —
    "nalox wake up open youtube" should open YouTube, not ask
    the brain what "wake up open youtube" means. Returns the
    cleaned remainder ("" when nothing else was said)."""
    rest = (remainder or "").strip(" .,!?।")
    if not rest:
        return ""
    low = rest.lower()
    for verb in WAKE_UP_VERBS_BN + WAKE_UP_VERBS_HI:
        if low.startswith(verb):
            return rest[len(verb):].strip(" .,!?।")
    tokens = rest.split()
    if tokens:
        first = re.sub(r"[^a-z]", "", tokens[0].lower())
        second = (re.sub(r"[^a-z]", "", tokens[1].lower())
                  if len(tokens) > 1 else "")
        if first == "wakeup":
            return " ".join(tokens[1:]).strip(" .,!?।")
        if (first, second) in _WAKE_UP_LATIN_PAIRS or (
                first == "wake" and len(tokens) == 1):
            return " ".join(tokens[2:]).strip(" .,!?।")
    return rest

_models = {}
_models_lock = threading.Lock()

# ------------------------------------------------- live mic level (v3.4,
# rescaled v3.5) — the HUD's mic meter reads this. Updated from every
# captured chunk in the wake loop and the command recorder.
#
# v3.4 scaled linear RMS against a fixed full-scale, which inverted
# reality for Arjun: a soft voice pegged the meter and a loud voice
# barely moved it. v3.5 works in DECIBELS like real audio gear: the
# chunk's RMS (after removing the DC offset) is converted to dBFS and
# mapped linearly from -55 dB (quiet room) to -6 dB (loud, close
# speech) onto 0..1. Fast attack (a new louder chunk shows instantly),
# gentle decay (the bars fall smoothly, not in one jump). A plain
# module float is fine — worst case the meter shows a stale frame.
_LEVEL_DB_MIN = -55.0
_LEVEL_DB_MAX = -6.0
_level = 0.0
_level_time = 0.0


def _chunk_level(chunk):
    """Level 0..1 for one float32 chunk, from its dBFS loudness."""
    x = np.asarray(chunk, dtype=np.float32)
    if x.size == 0:
        return 0.0
    x = x - float(np.mean(x))  # remove DC offset before measuring
    rms = float(np.sqrt(np.mean(np.square(x))))
    db = 20.0 * math.log10(max(rms, 1e-7))
    level = (db - _LEVEL_DB_MIN) / (_LEVEL_DB_MAX - _LEVEL_DB_MIN)
    return min(1.0, max(0.0, level))


def _update_level(chunk):
    global _level, _level_time
    try:
        new = _chunk_level(chunk)
    except Exception:
        return
    if new > _level:
        _level = new                       # fast attack
    else:
        _level = max(new, _level - 0.06)   # gentle decay per chunk
    _level_time = time.monotonic()


def get_level():
    """Current smoothed mic level, 0.0..1.0 (0.0 if stale > 0.4 s)."""
    if time.monotonic() - _level_time > 0.4:
        return 0.0
    return _level


# --------------------------------------- stage timing (v4.3)
# The last command's stage durations, read by nalox.py to build the
# "[timing] wake→record Xs, transcribe Ys, brain Zs, speak Ws" line
# on the log page — so a slow stage is provable from a screenshot.
LAST_TIMING = {"record": 0.0, "transcribe": 0.0}


# ------------------------------------------------- wake callback (v3.4)
_wake_callback = None


def set_wake_callback(fn):
    """Register fn() to be called the instant the wake word matches."""
    global _wake_callback
    _wake_callback = fn


def _fire_wake_callback():
    fn = _wake_callback
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass  # a broken beep/HUD hook must never break listening


# --------------------------------------- wake-UP callback (v5.2)
# "Nalox, wake up" (or ওঠো/জাগো/उठो) additionally SHOWS the
# window. nalox.py registers fn() here; ears fires it from the
# wake-segment handler the moment a wake-UP variant matches.
_wake_up_callback = None


def set_wake_up_callback(fn):
    """Register fn() to be called when a wake-UP phrase matches."""
    global _wake_up_callback
    _wake_up_callback = fn


def _fire_wake_up_callback():
    fn = _wake_up_callback
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass  # showing the window must never break listening


# ------------------------------------------------- status callback (v3.5)
# Short human-readable status lines (mic changes, device problems)
# that nalox.py mirrors to the HUD.
_status_callback = None


def set_status_callback(fn):
    """Register fn(message: str) for mic/device status lines."""
    global _status_callback
    _status_callback = fn


def _fire_status(msg):
    fn = _status_callback
    if fn is None:
        return
    try:
        fn(msg)
    except Exception:
        pass  # status reporting must never break listening


# --------------------------------------- manual TALK trigger (v3.7)
# The HUD's TALK button sets this event; the wake loop checks it on
# every sub-chunk and wakes exactly as if the wake word had matched.
# The guaranteed path for when the mic hears Arjun fine but the tiny
# wake model mangles his "Nalox" beyond even the fuzzy matcher.
_manual_command = threading.Event()


def request_command():
    """Ask the wake loop to wake up NOW (HUD TALK button)."""
    _manual_command.set()


# --------------------------------------- [heard] visibility (v3.7)
# Every non-empty wake transcription is mirrored to the HUD as
# "[heard] <text>", so Arjun can SEE what Nalox thinks he said.
# Identical repeats inside 2 s are skipped — the rolling buffer
# re-transcribes overlapping audio, so the same phrase would
# otherwise spam the console several times.
_last_heard_text = ""
_last_heard_time = 0.0


def _post_heard(text):
    global _last_heard_text, _last_heard_time
    text = (text or "").strip()
    if not text:
        return
    if is_garbage(text):
        return  # v4.2: hallucinations are never displayed
    now = time.monotonic()
    if text == _last_heard_text and now - _last_heard_time < 2.0:
        return
    _last_heard_text = text
    _last_heard_time = now
    _fire_status(f"[heard] {text}")


# ------------------------------------------------- mic auto-connect (v3.5)
def pick_input_device(cfg=None):
    """Index of the input device Nalox should listen on, or None.

    If config mic_device is a non-empty string, the first input-capable
    device whose name contains it (case-insensitive) wins. Otherwise
    the system default input device (sounddevice.default.device[0]).
    Any failure returns None, which means "sounddevice default".
    Re-evaluated before every listen, so hot-plugging the external
    mic switches over automatically.
    """
    try:
        import sounddevice as sd
    except Exception:
        return None
    want = ""
    if cfg:
        want = (cfg.get("mic_device") or "").strip().lower()
    if want:
        try:
            for idx, dev in enumerate(sd.query_devices()):
                try:
                    if dev.get("max_input_channels", 0) > 0 \
                            and want in (dev.get("name") or "").lower():
                        return idx
                except Exception:
                    continue
        except Exception:
            pass  # fall through to the default device
    try:
        default_in = sd.default.device[0]
        if default_in is not None and int(default_in) >= 0:
            return int(default_in)
    except Exception:
        pass
    return None


def _device_name(idx):
    """Human name for a device index (for HUD/log lines)."""
    try:
        import sounddevice as sd
    except Exception:
        return "system default microphone"
    try:
        if idx is None:
            idx = sd.default.device[0]
        if idx is None or int(idx) < 0:
            return "system default microphone"
        return str(sd.query_devices(int(idx))["name"])
    except Exception:
        return "system default microphone"


def _get_model(name):
    with _models_lock:
        if name not in _models:
            from faster_whisper import WhisperModel
            log.info("Loading whisper model %s (first run downloads it)...", name)
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _models[name]


# --------------------------------------- worker PROCESS (v6.2)
# THE definitive hang fix. Every local faster-whisper decode
# runs in ONE dedicated worker process (multiprocessing,
# spawn): the parent sends a job over a queue, the worker —
# which owns the WhisperModel cache in ITS address space —
# decodes strictly serially and sends the result back. Each
# request carries a HARD deadline, measured from the moment
# the worker ACKs the job (v6.3 — see below):
#   wake passes   WAKE_TX_DEADLINE    (8 s)
#   commands      COMMAND_TX_DEADLINE (12 s)
#   voice files   FILE_TX_DEADLINE    (30 s)
# On a VERIFIED wedge the parent TERMINATES the worker and
# spawns a fresh one: a wedged native decode dies with its
# process, which is the one thing the v4.6–v6.0 thread
# machinery (stuck watchdog, generation bumps, decode locks,
# model rotation — all retired) could never do. The log line
# is "[ears] worker restarted (timeout)".
#
# Lifecycle: the worker is a daemon process (multiprocessing
# reaps daemons when the parent exits — no orphan, as far as
# stdlib allows on Windows); it preloads the whisper models
# at spawn so the first real segment never pays the load
# inside its deadline; and if it crash-loops (more than
# WORKER_MAX_RESTARTS spawns inside WORKER_RESTART_WINDOW),
# respawns pause for WORKER_BACKOFF_S instead of fork-bombing
# a broken install — requests during the pause fail fast as
# "nothing heard" and the next window retries.
#
# v6.3 — THE TIMEOUT CASCADE, KILLED. Field log 2026-11-15
# 18:18–18:20: "[ears] worker restarted (timeout)" at
# 18:18:53, then 18:19:44/:48/:52/:56 — every ~4 s, exactly
# the old wake deadline — then "restarting too often —
# pausing". The loop could never recover: the deadline clock
# started at SUBMISSION, so a freshly spawned worker was
# still loading its models (or an honestly slow decode was
# mid-flight) when the next 4 s deadline killed it again.
# Three mechanisms end it:
#   1. READINESS HANDSHAKE — the worker posts a "ready"
#      sentinel after preload and ACKs every job it picks
#      up. The client tracks readiness per spawn; a request
#      first waits for the ack under a generous READY_TIMEOUT
#      (never counted as a request timeout, logged once), and
#      the decode deadline runs from the ACK — decode time
#      only, never preload time.
#   2. PING BEFORE KILL — a decode that overruns its
#      deadline earns a ping with a short grace. A worker
#      that answers (or whose late result lands first) is
#      SLOW, not wedged: the late request is dropped and the
#      worker is KEPT. Only a worker that fails the ping —
#      or is already dead — is restarted.
#   3. NO CASCADE — consecutive decode timeouts trip a
#      short cooldown during which automatic wake/raw jobs
#      fail fast instead of queueing up behind a struggling
#      worker; the cooldown expires on its own and the next
#      request is the recovery probe. Wake listening can
#      never stay dead. And identical [ears] restart lines
#      are throttled (first + a summary count), so neither
#      the log nor the chat mirror can flood again.
#
# v6.4 — BUSY IS NOT DEAD. v6.3's field log (2026-11-15
# 18:33–18:38) showed the cascade's ghost: no more 4 s kill
# loop, wake + commands worked — but "[ears] worker
# restarted (timeout)" still landed every 1–2 idle minutes.
# Root cause, in code terms: mechanism 2 was UNSOUND. The
# ping rode the SAME serial job queue as the decodes, and
# the worker's single main loop cannot even READ a ping
# while a decode is running — so any decode still in flight
# 1 s (PING_TIMEOUT) past its deadline produced neither a
# pong nor the late result, and the client killed a healthy,
# merely busy worker. (Phase 1 had the same flaw in milder
# form: a job submitted mid-decode is not ACKed until the
# running decode ends, so ACK_TIMEOUT could expire on a
# healthy worker too.) The v6.3 suite never saw it because
# its "slowalive" fake answered pings from a timer thread
# while "decoding" — a worker that does not exist.
# v6.4 moves liveness OFF the job queue:
#   1. OUT-OF-BAND HEARTBEAT — the worker answers heartbeat
#      tokens on a DEDICATED queue pair, from a thread that
#      never touches the models. A pong lands within ~1 s
#      even mid-decode. Liveness = heartbeat ONLY.
#   2. WAKE NEVER DIES FOR SLOWNESS — a wake/raw request
#      that overruns is DROPPED (its late result discarded);
#      the worker is left alone to finish and catch up. A
#      wake-path restart needs a dead heartbeat (no pong for
#      HEARTBEAT_DEAD_S) or a dead process.
#   3. COMMANDS KEEP TRUE-WEDGE RESTARTS — a command/file
#      decode that hangs with a dead heartbeat restarts the
#      worker exactly once, as before; one that is merely
#      slow (heartbeat alive) is waited out to a generous
#      hard cap and its late result is USED — never killed
#      mid-flight.
WAKE_TX_DEADLINE = 8.0
COMMAND_TX_DEADLINE = 12.0
FILE_TX_DEADLINE = 30.0
WORKER_MAX_RESTARTS = 5
WORKER_RESTART_WINDOW = 120.0
WORKER_BACKOFF_S = 60.0
READY_TIMEOUT = 60.0
ACK_TIMEOUT = 5.0
HEARTBEAT_TIMEOUT = 1.0
HEARTBEAT_DEAD_S = 3.0
COMMAND_HARD_CAP_S = 30.0
FILE_HARD_CAP_S = 45.0
WAKE_RETRY_MODEL = "base"
WAKE_COOLDOWN_AFTER = 2
WAKE_COOLDOWN_S = 20.0
LOG_THROTTLE_WINDOW = 60.0
_AUTO_KINDS = ("wake_pass", "raw")


class _LogThrottle:
    """First occurrence logs at once; repeats inside
    LOG_THROTTLE_WINDOW are counted silently and flushed as
    ONE summary line when the window rolls (v6.3)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}  # key -> [window_start, suppressed]

    def emit(self, key, msg, status=None):
        now = time.monotonic()
        summary = None
        first = False
        with self._lock:
            st = self._state.get(key)
            if st is None or now - st[0] >= LOG_THROTTLE_WINDOW:
                if st is not None and st[1]:
                    summary = st[1]
                self._state[key] = [now, 0]
                first = True
            else:
                st[1] += 1
        if summary:
            log.error("%s (repeated %d more times, suppressed)",
                      msg, summary)
        if first:
            log.error("%s", msg)
            _fire_status(status if status is not None else msg)
        return first


def _hb_echo_loop(hb_req_q, hb_res_q):
    """The worker's heartbeat responder (v6.4).

    Echoes every token the instant it arrives, on its own
    thread, and NEVER touches the models or the job queue —
    that independence is the whole design: the parent reads
    liveness from this channel only, so a worker buried in a
    20 s decode still pongs within ~1 s, and "busy" can never
    again be mistaken for "dead" (the v6.3 ping rode the
    serial job queue and starved behind the very decode it
    was judging). None is the poison pill."""
    while True:
        try:
            token = hb_req_q.get()
        except Exception:
            return
        if token is None:
            return
        try:
            hb_res_q.put(token)
        except Exception:
            return


def _tx_process_main(req_q, res_q, hb_req_q, hb_res_q,
                     cfg_snapshot):
    """The transcription worker process's whole life.

    Runs in the CHILD (spawn: this module is re-imported
    there; the model cache it builds is its own). Its logging
    is silenced — two processes writing one rotating log
    would corrupt it, and the parent logs every outcome
    anyway. After preloading the models it posts a
    (0, "ready", True) sentinel, and it ACKs every job the
    moment it picks it up — the parent's deadline measures
    decode time from that ack, never preload (v6.3). Jobs
    are (job_id, kind, payload):
      "ping"     -> ("pong", payload) — lifecycle proof
      "wake_pass"  (audio, model_name, kwargs)
                 -> _transcribe_rich(...) 4-tuple
      "command"  (audio, model_name, initial_prompt)
                 -> transcribe_command(...) (text, lang)
      "raw"      (audio, model_name, initial_prompt, language)
                 -> transcribe(...) (text, lang)
      "file"     (path, model_name)
                 -> _transcribe_file_local(...) (text, lang)
    A job that raises answers None (the parent reads that as
    "nothing heard"); a job that never answers is killed by
    the parent's deadline. None on the request queue is the
    poison pill (a clean exit).

    v6.4: a heartbeat thread (_hb_echo_loop) starts BEFORE
    preload and answers on the dedicated heartbeat queues
    for the process's whole life — liveness never queues
    behind a decode again."""
    try:
        logging.disable(logging.CRITICAL)
    except Exception:
        pass
    try:
        threading.Thread(target=_hb_echo_loop,
                         args=(hb_req_q, hb_res_q),
                         daemon=True,
                         name="nalox-ears-heartbeat").start()
    except Exception:
        pass
    cfg = cfg_snapshot or {}
    # Preload BEFORE the first job, so model load time never
    # eats a request deadline. Guarded per model: a model
    # that fails here fails per-job instead, same outcome.
    # v6.4: WAKE_RETRY_MODEL (the near-miss retry) preloads
    # too, so a first near-miss never pays its load either.
    _preload = []
    for _name in (cfg.get("wake_model") or "tiny",
                  cfg.get("whisper_command_model") or "small",
                  cfg.get("whisper_wake_model") or "tiny",
                  WAKE_RETRY_MODEL):
        if _name and _name not in _preload:
            _preload.append(_name)
    for _name in _preload:
        try:
            _get_model(_name)
        except Exception:
            pass
    # v6.3 READINESS HANDSHAKE: the models are loaded — tell
    # the parent BEFORE the first job is read. The client's
    # request deadlines only ever measure decode time (from
    # a job's ack), never this preload.
    try:
        res_q.put((0, "ready", True))
    except Exception:
        return
    while True:
        try:
            job = req_q.get()
        except Exception:
            return
        if job is None:
            return  # poison pill — the parent is closing us
        try:
            job_id, kind, payload = job
        except Exception:
            continue
        # v6.3 ACK: proof a READY worker picked the job up —
        # the parent starts the decode deadline when it sees
        # this, so a slow spawn can never eat decode time.
        try:
            res_q.put((job_id, "ack", None))
        except Exception:
            return
        result = None
        try:
            if kind == "ping":
                result = ("pong", payload)
            elif kind == "wake_pass":
                audio, model_name, kwargs = payload
                result = _transcribe_rich(
                    _get_model(model_name), audio, **kwargs)
            elif kind == "command":
                audio, model_name, prompt = payload
                result = transcribe_command(audio, model_name,
                                            prompt)
            elif kind == "raw":
                audio, model_name, prompt, language = payload
                result = transcribe(audio, model_name,
                                    initial_prompt=prompt,
                                    language=language)
            elif kind == "file":
                path, model_name = payload
                result = _transcribe_file_local(path, model_name)
        except Exception:
            result = None
        try:
            res_q.put((job_id, kind, result))
        except Exception:
            return


def _spawn_tx_process(cfg):
    """Default worker factory: (proc, req_q, res_q, hb_req_q,
    hb_res_q) for one fresh spawn-context worker — the job
    queues plus the v6.4 heartbeat pair. The test suite
    injects its own factory into _TxWorkerClient to simulate
    wedges and crashes without real processes."""
    ctx = multiprocessing.get_context("spawn")
    req_q = ctx.Queue()
    res_q = ctx.Queue()
    hb_req_q = ctx.Queue()
    hb_res_q = ctx.Queue()
    proc = ctx.Process(target=_tx_process_main,
                       args=(req_q, res_q, hb_req_q, hb_res_q,
                             dict(cfg or {})),
                       daemon=True, name="nalox-ears-worker")
    proc.start()
    return proc, req_q, res_q, hb_req_q, hb_res_q


class _TxWorkerClient:
    """Parent-side handle on the transcription worker.

    request() is the only door: it serialises callers (one
    job in flight — the worker decodes serially anyway) and
    NEVER raises; callers read None as "nothing heard" — the
    same shape a failed in-process decode always produced.

    v6.3 protocol (the timeout-cascade fix — see the long
    note at the worker constants): a request runs in two
    phases. Phase 1 waits for the worker's ACK under
    READY_TIMEOUT (fresh spawn still loading models) or
    ACK_TIMEOUT (worker already ready) — never counted as a
    request timeout. Phase 2 runs the caller's deadline
    against the decode itself.

    v6.4 protocol (busy-is-not-dead — same note): liveness
    is read ONLY from the out-of-band heartbeat (a dedicated
    queue pair answered by a worker thread that never
    touches the models). A phase-2 timeout on the automatic
    kinds (wake_pass / raw) DROPS the request when the
    heartbeat is alive — the worker is left alone to finish
    and catch up — and restarts only when no pong arrives
    for HEARTBEAT_DEAD_S or the process has exited. A
    command/file timeout with a live heartbeat is waited
    out to its hard cap (COMMAND_HARD_CAP_S /
    FILE_HARD_CAP_S) and the late result is used; with a
    dead heartbeat it restarts exactly once. A phase-1 (ack)
    timeout means the worker never even started the job
    inside its whole budget: a live heartbeat then means
    "busy with an earlier job" (automatic kinds drop;
    command/file keep waiting under the hard cap), while a
    heartbeat silent for a full HEARTBEAT_TIMEOUT on a
    thread that only echoes marks a zombie — restart.
    """

    def __init__(self, cfg, process_factory=None):
        self._cfg = dict(cfg or {})
        self._factory = process_factory or _spawn_tx_process
        self._call_lock = threading.Lock()
        self._proc = None
        self._req_q = None
        self._res_q = None
        self._hb_req_q = None
        self._hb_res_q = None
        self._hb_seq = 0
        self._next_id = 0
        self._restart_stamps = []
        self._backoff_until = 0.0
        self._closed = False
        # v6.3 state: readiness of the CURRENT spawn, the
        # once-per-spawn "loading models" log, the consecutive
        # decode-timeout count and the wake cooldown it trips.
        self._ready = False
        self._start_logged = False
        self._consec_timeouts = 0
        self._cooldown_until = 0.0
        self._throttle = _LogThrottle()

    # ------------------------------------------------ lifecycle
    def _spawn(self):
        now = time.monotonic()
        self._restart_stamps = [
            t for t in self._restart_stamps
            if now - t < WORKER_RESTART_WINDOW]
        if len(self._restart_stamps) >= WORKER_MAX_RESTARTS:
            self._restart_stamps = []
            self._backoff_until = now + WORKER_BACKOFF_S
            self._throttle.emit(
                "backoff",
                "[ears] transcription worker restarted too "
                "often — pausing restarts for %ds"
                % int(WORKER_BACKOFF_S),
                status="[ears] transcription worker "
                       "restarting too often — pausing")
            return False
        self._restart_stamps.append(now)
        try:
            (self._proc, self._req_q, self._res_q,
             self._hb_req_q, self._hb_res_q) = \
                self._factory(self._cfg)
            self._ready = False
            self._start_logged = False
            return True
        except Exception as exc:
            log.error("[ears] could not start the "
                      "transcription worker: %s", exc)
            self._proc = None
            self._req_q = None
            self._res_q = None
            self._hb_req_q = None
            self._hb_res_q = None
            return False

    def _kill(self):
        proc, self._proc = self._proc, None
        self._req_q = None
        self._res_q = None
        self._hb_req_q = None
        self._hb_res_q = None
        self._ready = False
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.join(timeout=2.0)
        except Exception:
            pass
        try:
            if proc.is_alive():
                proc.kill()
        except Exception:
            pass

    def close(self):
        """Poison + terminate the worker (Ears.stop)."""
        with self._call_lock:
            self._closed = True
            try:
                if self._req_q is not None:
                    self._req_q.put(None)
            except Exception:
                pass
            self._kill()

    # ------------------------------------------------ message pump
    def _classify(self, msg, job_id, kind, ping_id=None):
        """Sort one worker message for the current wait:
        'ready' / 'ack' / 'result' / 'pong' / 'stale'."""
        try:
            rid, mkind, result = msg
        except Exception:
            return "stale", None
        if mkind == "ready":
            self._ready = True
            return "ready", None
        if mkind == "ack":
            return ("ack", None) if rid == job_id \
                else ("stale", None)
        if ping_id is not None and rid == ping_id \
                and mkind == "ping":
            return "pong", result
        if rid == job_id and mkind == kind:
            return "result", result
        return "stale", None

    def _pump(self, timeout, job_id, kind, ping_id=None,
              want=("result",)):
        """Wait up to `timeout` for a wanted event.

        Returns (event, value): one of `want`, or 'died' /
        'timeout'. Ready sentinels and stale messages are
        absorbed inside the same budget (a ready flips
        self._ready and the wait continues)."""
        end = time.monotonic() + max(0.0, float(timeout))
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return "timeout", None
            try:
                msg = self._res_q.get(timeout=min(left, 0.25))
            except queue.Empty:
                if self._proc is not None \
                        and not self._proc.is_alive():
                    return "died", None
                continue
            except Exception:
                return "timeout", None
            event, value = self._classify(msg, job_id, kind,
                                          ping_id)
            if event in want:
                return event, value
            # 'ready' / 'stale' / unwanted 'ack' — keep waiting.

    # ------------------------------------------------ outcomes
    def _restart(self, reason):
        """Kill + respawn, with the log line throttled."""
        msg = {"timeout": "[ears] worker restarted (timeout)",
               "crashed": "[ears] worker restarted (crashed)",
               "unresponsive":
                   "[ears] worker restarted (unresponsive)"}[
                       reason]
        self._throttle.emit("restart-" + reason, msg)
        self._kill()
        self._spawn()

    def _note_success(self):
        self._consec_timeouts = 0

    def _note_timeout(self, kind):
        """One decode timeout (wedged or slow-alive). Two in
        a row on the automatic kinds trip the wake cooldown:
        wake/raw requests then fail fast until it expires, so
        a struggling worker is never buried under new jobs —
        and listening recovers on its own when it does."""
        self._consec_timeouts += 1
        if kind in _AUTO_KINDS \
                and self._consec_timeouts >= WAKE_COOLDOWN_AFTER:
            self._consec_timeouts = 0
            self._cooldown_until = \
                time.monotonic() + WAKE_COOLDOWN_S
            self._throttle.emit(
                "cooldown",
                "[ears] wake transcription paused briefly "
                "(worker slow) — still listening")

    # ------------------------------------------------ heartbeat (v6.4)
    def _probe_heartbeat(self, wait_s):
        """One out-of-band liveness probe: send a fresh token
        on the heartbeat queue and wait up to `wait_s` for its
        echo. The worker's heartbeat thread never touches the
        models, so a live worker echoes in milliseconds EVEN
        MID-DECODE — the property the v6.3 job-queue ping did
        not have. Stale echoes from earlier probes are
        discarded. Only ever called under _call_lock."""
        proc = self._proc
        if proc is None or not proc.is_alive():
            return False
        if self._hb_req_q is None or self._hb_res_q is None:
            return False
        self._hb_seq += 1
        token = ("hb", self._hb_seq)
        try:
            self._hb_req_q.put(token)
        except Exception:
            return False
        end = time.monotonic() + max(0.0, float(wait_s))
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return False
            try:
                msg = self._hb_res_q.get(
                    timeout=min(left, 0.25))
            except queue.Empty:
                if not proc.is_alive():
                    return False
                continue
            except Exception:
                return False
            if msg == token:
                return True
            # A stale echo from an earlier probe — keep
            # waiting for THIS probe's token.

    def _heartbeat_dead(self):
        """Dead = no pong within HEARTBEAT_DEAD_S. A live
        worker answers in milliseconds, so the full window
        only ever burns on a genuinely unresponsive one."""
        return not self._probe_heartbeat(HEARTBEAT_DEAD_S)

    def _timeout_recovery(self, job_id, kind, phase2_started):
        """Phase 2 expired with no result (v6.4).

        The heartbeat — never the job queue — decides:
          * heartbeat DEAD (or the process died): a genuine
            wedge. Restart exactly once, as v6.3 did.
          * heartbeat ALIVE, automatic kind (wake/raw): the
            worker is busy, not dead. DROP the request (its
            late result is discarded as stale by later pumps)
            and leave the worker alone to finish and catch
            up. Wake-path restarts for slowness are gone.
          * heartbeat ALIVE, command/file: wait out the
            remainder up to the kind's hard cap and USE the
            late result. At the cap, give up on this request
            — the worker is still never killed mid-flight."""
        proc = self._proc
        if proc is None or not proc.is_alive():
            self._restart("crashed")
            return None
        if self._heartbeat_dead():
            self._note_timeout(kind)
            self._restart("timeout")
            return None
        if kind in _AUTO_KINDS:
            self._note_timeout(kind)
            return None
        cap = COMMAND_HARD_CAP_S if kind == "command" \
            else FILE_HARD_CAP_S
        left = cap - (time.monotonic() - phase2_started)
        if left > 0:
            ev, val = self._pump(left, job_id, kind,
                                  want=("result",))
            if ev == "result":
                self._note_success()
                return val
            if ev == "died":
                self._restart("crashed")
                return None
        return None

    def _ack_timeout(self, job_id, kind, deadline, submitted):
        """Phase 1 expired: the worker never ACKed the job
        inside its whole budget (READY_TIMEOUT fresh /
        ACK_TIMEOUT ready). A heartbeat probe tells busy
        from zombie:
          * probe answers — the process is alive; the job is
            queued behind an earlier decode (or, fresh, still
            loading past even READY_TIMEOUT). Automatic kinds
            drop the now-stale segment and keep the worker;
            command/file keep waiting for the ack under the
            hard cap, then run the normal phase 2.
          * probe silent for HEARTBEAT_TIMEOUT — the echo
            thread answers in milliseconds when the process
            is healthy, so a full second of silence after the
            whole ack budget marks a zombie: restart it."""
        if not self._probe_heartbeat(HEARTBEAT_TIMEOUT):
            self._restart("timeout")
            return None
        if kind in _AUTO_KINDS:
            self._note_timeout(kind)
            return None
        cap = COMMAND_HARD_CAP_S if kind == "command" \
            else FILE_HARD_CAP_S
        while True:
            left = cap - (time.monotonic() - submitted)
            if left <= 0:
                # The whole hard cap spent waiting for an ack
                # that never came, heartbeat alive throughout:
                # give up on this request, keep the worker.
                return None
            ev, val = self._pump(min(left, 1.0), job_id, kind,
                                  want=("ack", "result"))
            if ev == "result":
                self._note_success()
                return val
            if ev == "died":
                self._restart("crashed")
                return None
            if ev == "ack":
                return self._await_result(job_id, kind, deadline)
            # slice expired — loop re-checks the cap; the
            # process-death check rides _pump's 'died'.

    def _await_result(self, job_id, kind, deadline):
        """Phase 2: the decode deadline runs from the ack."""
        started = time.monotonic()
        ev, val = self._pump(deadline, job_id, kind,
                             want=("result",))
        if ev == "result":
            self._note_success()
            return val
        if ev == "died":
            self._restart("crashed")
            return None
        return self._timeout_recovery(job_id, kind, started)

    # ------------------------------------------------ requests
    def request(self, kind, payload, deadline):
        """One job: the worker's result, or None (timeout /
        crash / backoff / cooldown / closed)."""
        with self._call_lock:
            if self._closed:
                return None
            now = time.monotonic()
            if kind in _AUTO_KINDS and now < self._cooldown_until:
                # Cascade guard: fail fast — the wake loop
                # drains its stale segments and the next real
                # request after the cooldown is the probe.
                return None
            if self._proc is None:
                if now < self._backoff_until:
                    return None
                if not self._spawn():
                    return None
            self._next_id += 1
            job_id = self._next_id
            try:
                self._req_q.put((job_id, kind, payload))
            except Exception:
                self._kill()
                return None
            if kind == "ping":
                # A job-queue ping is a lifecycle proof, not a
                # decode: the plain deadline applies (v6.2
                # semantics). v6.4: on a timeout the HEARTBEAT
                # decides — a busy worker whose ping is still
                # queued behind a decode is kept, not killed.
                ev, val = self._pump(deadline, job_id, kind,
                                     want=("result",))
                if ev == "result":
                    self._note_success()
                    return val
                if ev == "died":
                    self._restart("crashed")
                elif not self._probe_heartbeat(
                        HEARTBEAT_TIMEOUT):
                    self._restart("timeout")
                return None
            # ---- phase 1: readiness + ack (NOT the deadline)
            submitted = time.monotonic()
            if not self._ready:
                if not self._start_logged:
                    self._start_logged = True
                    log.info("[ears] transcription worker is "
                             "starting — loading its models "
                             "(a first request waits here; "
                             "this is not a hang)")
                ev, val = self._pump(READY_TIMEOUT, job_id,
                                     kind, want=("ack", "result"))
            else:
                ev, val = self._pump(ACK_TIMEOUT, job_id, kind,
                                     want=("ack", "result"))
            if ev == "result":
                # A worker that answers without acking first
                # (the protocol tolerates it) — the answer is
                # the answer.
                self._note_success()
                return val
            if ev == "died":
                self._restart("crashed")
                return None
            if ev == "timeout":
                # Never picked the job up inside its start
                # budget — busy or zombie; the heartbeat
                # decides (see _ack_timeout).
                return self._ack_timeout(job_id, kind, deadline,
                                         submitted)
            # ---- phase 2: the decode deadline runs from the ack
            return self._await_result(job_id, kind, deadline)


def _lang_of(info):
    lang = (getattr(info, "language", None) or "en").strip().lower()
    return lang or "en"


def _transcribe(model, audio, **kwargs):
    """model.transcribe(), crash-proof against rejected keywords.

    The v3.3 bug: ears passed prompt= (not a real faster-whisper
    keyword) and EVERY call raised TypeError, so no wake word and no
    command ever got through. Now: try the full call; on TypeError
    first retry WITHOUT the v4.2 VAD kwargs (vad_filter /
    vad_parameters — the newest additions, the most likely to be
    rejected by an older faster-whisper); if that still raises
    TypeError, strip ALL optional kwargs and retry with the safest
    possible call — (audio) plus beam_size=1 — so a keyword
    mismatch can never take transcription down again.
    """
    try:
        return model.transcribe(audio, **kwargs)
    except TypeError as exc:
        log.warning("transcribe() rejected kwargs %s (%s); "
                    "retrying without the VAD options",
                    sorted(kwargs), exc)
        reduced = {k: v for k, v in kwargs.items()
                   if k not in ("vad_filter", "vad_parameters")}
        if len(reduced) != len(kwargs):
            try:
                return model.transcribe(audio, **reduced)
            except TypeError:
                pass  # fall through to the bare call below
        return model.transcribe(audio, beam_size=1)


def _is_word_char(ch):
    """Letters/digits in ANY script, plus combining marks (Bengali /
    Devanagari vowel signs are marks, not letters — they still make
    the character part of a word, not punctuation)."""
    return ch.isalnum() or unicodedata.category(ch).startswith("M")


def is_garbage(text):
    """True if a transcription is Whisper noise, not speech (v4.2).

    Catches what the tiny model invents from room silence:
      (a) empty / whitespace-only;
      (b) punctuation floods — over 55% of the non-space characters
          are not word characters ("....,,,,....");
      (c) known hallucination phrases ("thank you for watching",
          the Japanese equivalent, "please subscribe", ...);
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


def transcribe(audio_f32, model_name, initial_prompt=None, language=None):
    """Transcribe a float32 mono 16 kHz numpy array.

    Language is AUTO-DETECTED unless `language` forces one (the
    wake loop forces "en" — the wake word is English). Every call
    carries the v4.2 decoding guards (_DECODE_GUARDS: VAD +
    anti-hallucination thresholds). Returns (text, language) —
    text is lowercased. `initial_prompt` biases the decoder (used
    with "Nalox" for commands). NOTE: faster-whisper's keyword is
    initial_prompt; the old prompt= kwarg crashed every call.
    """
    if audio_f32 is None or len(audio_f32) < SAMPLE_RATE * 0.2:
        return "", "en"
    model = _get_model(model_name)
    kwargs = dict(beam_size=1, language=language, word_timestamps=False)
    kwargs.update(_DECODE_GUARDS)
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    # v6.2: no decode lock — this function only ever runs
    # inside the worker process now, where decodes are
    # strictly serial (the v6.0 per-instance locks retired
    # with the in-process design they protected).
    segments, info = _transcribe(model, audio_f32, **kwargs)
    text = " ".join(seg.text for seg in segments).strip().lower()
    if initial_prompt and _looks_like_prompt_echo(text, initial_prompt):
        log.info("Dropped a prompt-echo transcription: %r", text)
        return "", _lang_of(info)
    return text, _lang_of(info)


def _transcribe_rich(model, audio, **kwargs):
    """_transcribe + confidence stats.

    Returns (text, language, avg_no_speech_prob, avg_logprob).

    v4.5: the no_speech average is a LOGGING stat only. It was
    the v4.3 hallucination weapon (segments averaging above 0.7
    were dropped) until Arjun's 10:09 screenshot proved it
    saturates at 1.00 on genuine Bengali speech and eats his
    real commands. Callers now log it for diagnosis and deliver
    any garbage-filter-clean text regardless of its value.

    v6.2: runs worker-side (serial — no lock; the v6.0 locked
    variant is retired with the in-process design).
    """
    segments, info = _transcribe(model, audio, **kwargs)
    segs = list(segments)
    text = " ".join(s.text for s in segs).strip().lower()
    prompt = kwargs.get("initial_prompt")
    if prompt and _looks_like_prompt_echo(text, prompt):
        # The model parroted the vocabulary prompt back. The
        # EMPTY text is what kills it (callers drop empty text);
        # the 1.0 no_speech is reported only so logs stay honest
        # about why nothing was heard.
        return "", _lang_of(info), 1.0, 0.0
    if segs:
        nsp = sum(float(getattr(s, "no_speech_prob", 0.0) or 0.0)
                  for s in segs) / len(segs)
        lp = sum(float(getattr(s, "avg_logprob", 0.0) or 0.0)
                 for s in segs) / len(segs)
    else:
        nsp, lp = 1.0, 0.0
    return text, _lang_of(info), nsp, lp


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

    v4.3 latency fix: the detected-language LABEL from Whisper is
    often wrong (Bengali heard as "ur"/"tr"), but the TEXT is what
    matters. If the characters are overwhelmingly from Arjun's
    three scripts, the transcription is real speech in one of his
    languages — whatever the label says.
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
    # v4.8: the winner is picked by hand, not max(counts, ...) —
    # with zero letters there IS no winner, and a max() over an
    # empty vote is the "max() iterable argument is empty" crash
    # class from Arjun's 11:54 log. First-maximal order (bn, hi,
    # latin) matches the old max() tie-breaking exactly.
    best = None
    for kind in ("bn", "hi", "latin"):
        if counts[kind] > 0 and (best is None
                                 or counts[kind] > counts[best]):
            best = kind
    if best is not None:
        return {"bn": "bn", "hi": "hi", "latin": "en"}[best]
    return detected if detected in ALLOWED_LANGS else "en"


def _dominant_script(text):
    """'bn' / 'hi' / 'latin' / '' — the script most of the text's
    letters are written in (v4.6, for the Bengali wake rescue)."""
    counts = {"bn": 0, "hi": 0, "latin": 0}
    for ch in (text or ""):
        kind = _script_of(ch)
        if kind:
            counts[kind] += 1
    best = ""
    for kind in ("bn", "hi", "latin"):
        if counts[kind] > 0 and (not best
                                 or counts[kind] > counts[best]):
            best = kind
    return best


def _transcribe_command_policy(audio_f32, model_name,
                               initial_prompt=None):
    """Command transcription — v4.3 FAST language policy.

    The v4.2 policy could run the small model THREE times per
    command (auto → forced bn → forced en) = 10–30 s of CPU on a
    laptop, which Arjun felt as "replies after a long time". Now:

      1. ONE auto-detect pass (beam_size=1). If the text passes the
         garbage filter AND its script is plausible (≥70% of
         letters Latin/Bengali/Devanagari), it is delivered
         immediately — the detected-language label is NOT trusted
         over the actual characters; the reported language comes
         from the dominant script.
      2. Only a garbage / empty / implausible first pass earns a
         re-transcription: forced Bengali, then forced English
         (the v4.2 fallback chain), each still garbage-checked.
      3. Nothing clean -> "" — hallucinations never become commands.
      4. ENGLISH ANCHOR (v4.3): English is the base language. Only
         en/bn/hi exist in Nalox's world; whenever detection is
         ambiguous or lands outside that set, handling falls back
         to English — the forced chain ENDS in English, the
         script-derived language defaults to English for Latin
         text, and an out-of-set label is normalised to "en".
    Returns (text, language).
    """
    text, lang = transcribe(audio_f32, model_name,
                            initial_prompt=initial_prompt)
    if text and not is_garbage(text) and _script_plausible(text):
        return text, _script_lang(text, lang)
    for forced in ("bn", "en"):
        text2, _ = transcribe(audio_f32, model_name,
                              initial_prompt=initial_prompt,
                              language=forced)
        if text2 and not is_garbage(text2):
            log.info("Command language policy: auto-detect gave "
                     "%r (%s); delivered the forced-%s pass: %r",
                     text, lang, forced, text2)
            return text2, forced
    if text:
        log.info("Command dropped as garbage/hallucination: %r "
                 "(detected language: %s)", text, lang)
    return "", lang if lang in ALLOWED_LANGS else "en"


def transcribe_command(audio_f32, model_name, initial_prompt=None):
    """The command-transcription policy, crash-contained (v4.8).

    Arjun's 11:54 log shows the main loop eating a bare
    "ValueError: max() iterable argument is empty" — a
    faster-whisper internals failure on a degenerate clip,
    escaping through this previously-unguarded path and costing
    a command + a 3 s loop sleep. A failed transcription now
    reads as "nothing heard" and the loop lives on.
    """
    try:
        return _transcribe_command_policy(audio_f32, model_name,
                                          initial_prompt)
    except Exception as exc:
        log.warning("Command transcription failed: %s: %s",
                    type(exc).__name__, exc)
        return "", "en"


# ------------------------------------------------- cloud ears (v5.1)
# The command path's hearing upgrade: cloud speech-to-text first
# (Gemini audio, then Groq Whisper), local faster-whisper as the
# always-there fallback. The wake loop does NOT use this — it
# stays local and instant, exactly as before.
CLOUD_EARS_TIMEOUT = 6.0  # seconds, per provider attempt (v6.3: was 8 — fast switching)
_GEMINI_STT_URL = ("https://generativelanguage.googleapis.com"
                   "/v1beta/models/{model}:generateContent")
_GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_GROQ_STT_MODEL = "whisper-large-v3"
_STT_INSTRUCTION = (
    "Transcribe exactly what is spoken, word for word. The "
    "language may be Bengali, Hindi or English. Return ONLY the "
    "transcript text, nothing else.")


def cloud_ear_provider(cfg):
    """Which cloud ear WOULD hear commands with this config:
    "gemini" / "groq" / None (key-based only; the cloud_ears
    on/off switch is the callers' concern). Used by the Doctor."""
    cfg = cfg or {}
    if (cfg.get("gemini_api_key") or "").strip():
        return "gemini"
    if (cfg.get("groq_api_key") or "").strip():
        return "groq"
    return None


def _wav_bytes(audio_f32):
    """float32 mono 16 kHz audio -> 16-bit PCM WAV bytes
    (stdlib wave — the exact shape both cloud APIs accept).

    v5.2 crash audit: the samples are flattened defensively —
    a 2-D / odd-shaped array used to flow straight into the
    PCM conversion and produce an interleaved garbage WAV in
    silence; a non-numeric array raises here and the caller
    (_cloud_transcribe) treats that as "no cloud ear", exactly
    like any other cloud failure."""
    import io
    import wave
    flat = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
    pcm = (np.clip(flat, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _cloud_gemini(wav, cfg):
    """One Gemini audio transcription attempt -> text or None.

    POSTs the clip as inline_data to generateContent with the
    key the config already holds for the Gemini BRAIN (field-
    confirmed working). Any failure — HTTP error, timeout,
    odd payload — returns None; the caller moves on."""
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        return None
    model = (cfg.get("gemini_model") or "").strip() \
        or "gemini-2.5-flash"
    try:
        import base64

        import requests
        payload = {
            "contents": [{"parts": [
                {"text": _STT_INSTRUCTION},
                {"inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav).decode("ascii"),
                }},
            ]}],
            "generationConfig": {"temperature": 0},
        }
        resp = requests.post(
            _GEMINI_STT_URL.format(model=model),
            headers={"x-goog-api-key": key,
                     "Content-Type": "application/json"},
            json=payload, timeout=CLOUD_EARS_TIMEOUT)
        if resp.status_code != 200:
            log.info("Cloud ear gemini: HTTP %s — trying next",
                     resp.status_code)
            return None
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = " ".join(str(p.get("text") or "") for p in parts)
        return text.strip() or None
    except Exception as exc:
        log.info("Cloud ear gemini failed (%s: %s) — trying next",
                 type(exc).__name__, exc)
        return None


def _cloud_groq(wav, cfg):
    """One Groq Whisper transcription attempt -> text or None
    (multipart upload of the WAV, whisper-large-v3)."""
    key = (cfg.get("groq_api_key") or "").strip()
    if not key:
        return None
    try:
        import requests
        resp = requests.post(
            _GROQ_STT_URL,
            headers={"Authorization": "Bearer " + key},
            files={"file": ("command.wav", wav, "audio/wav")},
            data={"model": _GROQ_STT_MODEL,
                  "response_format": "json"},
            timeout=CLOUD_EARS_TIMEOUT)
        if resp.status_code != 200:
            log.info("Cloud ear groq: HTTP %s — trying next",
                     resp.status_code)
            return None
        text = (resp.json().get("text") or "").strip()
        return text or None
    except Exception as exc:
        log.info("Cloud ear groq failed (%s: %s) — trying next",
                 type(exc).__name__, exc)
        return None


def _cloud_transcribe(audio_f32, cfg):
    """Cloud-first command transcription -> (text, lang, source)
    or None. source is "cloud:gemini" / "cloud:groq".

    The guards are the LOCAL ones, unchanged (v5.1 spec): a
    cloud transcript that is garbage, written in a script
    outside the {en, bn, hi} lock, an echo of Nalox's own
    vocabulary prompt, or an echo of the STT instruction itself
    is rejected exactly like a bad local decode — the next ear
    (or the local model) gets its turn."""
    try:
        wav = _wav_bytes(audio_f32)
    except Exception as exc:
        log.warning("Cloud ears: WAV encode failed: %s", exc)
        return None
    attempts = []
    if (cfg.get("gemini_api_key") or "").strip():
        attempts.append(("gemini", _cloud_gemini))
    if (cfg.get("groq_api_key") or "").strip():
        attempts.append(("groq", _cloud_groq))
    for name, fn in attempts:
        # v5.2 CRASH-GUARD: both provider functions already catch
        # their own exceptions; this wrap means even a future
        # provider that forgets to can't take the others down.
        try:
            raw = fn(wav, cfg)
        except Exception as exc:
            log.error("[CRASH-GUARD] cloud ear %s raised past "
                      "its own guard: %s: %s",
                      name, type(exc).__name__, exc)
            continue
        if not raw:
            continue
        text = raw.strip().lower()
        if "transcribe exactly" in text:
            log.info("Cloud ear %s echoed the instruction — "
                     "rejected", name)
            continue
        if is_garbage(text):
            log.info("Cloud ear %s transcript rejected as "
                     "garbage: %r", name, text)
            continue
        if not _script_plausible(text):
            log.info("Cloud ear %s transcript outside the "
                     "language lock: %r", name, text)
            continue
        if _looks_like_prompt_echo(text, COMMAND_PROMPT):
            log.info("Cloud ear %s transcript was a prompt "
                     "echo — rejected", name)
            continue
        return text, _script_lang(text, "en"), "cloud:" + name
    return None


def transcribe_command_best(audio_f32, model_name, cfg,
                            initial_prompt=None, local_fn=None):
    """THE command transcription entry point (v5.1).

    Returns (text, language, source) — source says which ear
    produced the final text: "cloud:gemini" / "cloud:groq" /
    "local". Cloud ears are tried first when config cloud_ears
    is not "off"; ANY cloud failure lands on the local policy,
    so a command that local hearing can read is never lost.

    v6.2: the local policy itself runs in the worker PROCESS
    — callers with an Ears instance pass local_fn (Ears
    ._local_command, hard 12 s deadline); without one, the
    policy runs in-process (the worker's own "command" job
    lands here, and so do direct test calls)."""
    cfg = cfg or {}
    mode = str(cfg.get("cloud_ears") or "auto").strip().lower()
    if mode != "off":
        try:
            got = _cloud_transcribe(audio_f32, cfg)
        except Exception as exc:  # _cloud_transcribe is guarded
            log.warning("Cloud ears failed (%s) — local "
                        "Whisper takes over", exc)
            got = None
        if got:
            return got
    if local_fn is not None:
        text, lang = local_fn(audio_f32, model_name,
                              initial_prompt)
    else:
        text, lang = transcribe_command(audio_f32, model_name,
                                        initial_prompt)
    return text, lang, "local"


def _nalox_is_speaking():
    """True while Nalox's own voice is playing (v4.2).

    Guarded: any import/attribute problem means "not speaking" —
    listening must never depend on the voice module working.
    """
    try:
        import voice
        return bool(voice.is_speaking())
    except Exception:
        return False


def _rms(chunk):
    if len(chunk) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(chunk))))


def _levenshtein(a, b):
    """Tiny edit distance (two-row DP, no dependencies)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,                    # delete
                           cur[j - 1] + 1,                 # insert
                           prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]


def looks_like_wake_word(text):
    """Fuzzy check: does this transcript contain the wake word?

    v3.7 — deliberately generous, because the tiny wake model
    mangles "Nalox" constantly. The text is normalised (lowercase,
    punctuation stripped), then Nalox wakes if ANY rule hits:
      (a) the name in Bengali script appears in the raw text;
      (b) a known Latin mishearing (WAKE_SUBSTRINGS) appears as a
          substring — of the cleaned text, or of the text with
          spaces removed (Whisper sometimes splits the name);
      (c) a token of length >= 4 is within edit distance 1 of
          "nalox" or "nalax";
      (d) a token contains "lox" or "laks".
    """
    if not text:
        return False
    raw = text.lower()
    if any(v in raw for v in WAKE_VARIANTS_BN):
        return True  # (a) name written in Bengali script
    if any(v in raw for v in WAKE_VARIANTS_HI):
        return True  # (a2) name written in Devanagari (v4.3)
    cleaned = re.sub(r"[^a-z ]", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return False
    despaced = cleaned.replace(" ", "")
    for variant in WAKE_SUBSTRINGS:
        if variant in cleaned or variant in despaced:
            return True  # (b) a known mishearing, verbatim
    for token in cleaned.split():
        if "lox" in token or "laks" in token:
            return True  # (d) the unmistakable tail of the name
        if len(token) >= 4 and (_levenshtein(token, "nalox") <= 1
                                or _levenshtein(token, "nalax") <= 1):
            return True  # (c) one typo away from the name
    return False


def _wake_near_miss(text):
    """True if the text ALMOST contains the wake word (v6.4).

    A token the fuzzy matcher scores as close-but-not-wake:
    at least 4 letters and at MINIMUM edit distance EXACTLY
    2 from "nalox" / "nalax". Distance 0–1 already wakes via
    looks_like_wake_word's rules (and its substring / "lox"
    tail rules catch more — "mellox" wakes on its tail), so
    a near-miss is what is left: the fast tiny model's
    typical manglings of a name it nearly heard — "malos",
    "nelos", "balos". Callers only consult this when
    looks_like_wake_word is already False; a hit earns ONE
    retry with the stronger WAKE_RETRY_MODEL ("base")."""
    if not text:
        return False
    cleaned = re.sub(r"[^a-z ]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return False
    for token in cleaned.split():
        if len(token) >= 4 and min(
                _levenshtein(token, "nalox"),
                _levenshtein(token, "nalax")) == 2:
            return True
    return False


def _is_wake_token(token):
    """True if ONE Latin token is (a mangling of) the wake word —
    the per-token core of looks_like_wake_word, reused by the
    one-breath remainder splitter."""
    if not token:
        return False
    if token in ("nalox", "nalaks", "nalex", "nalok", "nalux",
                 "nalax", "alex"):
        return True
    if "lox" in token or "laks" in token:
        return True
    if len(token) >= 4 and (_levenshtein(token, "nalox") <= 1
                            or _levenshtein(token, "nalax") <= 1):
        return True
    return False


def split_wake_remainder(text, lang="en"):
    """Split a one-breath utterance (Ears 2.0).

    "Nalox কেমন আছো" / "ন্যালক্স কেমন আছো" / "nalox open youtube"
    -> (remainder, language). Returns ("", lang) when nothing
    usable follows the wake word (a bare "Nalox" — the normal
    command recorder then takes over). Bengali / Devanagari
    variants are matched in the raw text; Latin goes token by
    token so "now lox open youtube" also splits after "lox".
    """
    raw = (text or "").strip()
    if not raw:
        return "", lang
    for variant in WAKE_VARIANTS_BN:
        if variant in raw:
            rest = raw.split(variant, 1)[1].strip(" .,!?।")
            return (rest, "bn") if len(rest) >= 2 else ("", lang)
    for variant in WAKE_VARIANTS_HI:
        if variant in raw:
            rest = raw.split(variant, 1)[1].strip(" .,!?।")
            return (rest, "hi") if len(rest) >= 2 else ("", lang)
    # Latin wake spellings appear literally even in mixed-script
    # transcripts ("nalox कैसे हो") — cut the RAW text there so
    # the remainder keeps its own script. (The first version of
    # this splitter tokenised with [^a-z0-9 ] and silently DELETED
    # the Hindi/Bengali remainder — caught by the v4.3 real-audio
    # test.) The remainder's language follows its dominant script.
    m = re.search(r"(nalox|nalaks|nalex|nalok|nalux|nalax|alex|"
                  r"nell\s+ox|now\s+lox|no\s+lox)", raw.lower())
    if m:
        rest = raw[m.end():].strip(" .,!?।")
        if len(rest) >= 2:
            return rest, _script_lang(rest, "en")
        return "", lang
    # Fuzzy per-token fallback for mangled spellings — split on
    # whitespace only, so non-Latin tokens survive intact.
    tokens = raw.split()
    for i, tok in enumerate(tokens):
        core = re.sub(r"[^a-z0-9]", "", tok.lower())
        prev = re.sub(r"[^a-z0-9]", "",
                      tokens[i - 1].lower()) if i > 0 else ""
        if _is_wake_token(core) or (
                core == "ox" and prev in ("nell", "now", "no")):
            rest = " ".join(tokens[i + 1:]).strip(" .,!?।")
            if len(rest) >= 2:
                return rest, _script_lang(rest, "en")
            return "", lang
    return "", lang


# Extra name spellings the cloud STT services produce (v6.6) —
# kept OUT of WAKE_VARIANTS_* (those drive wake MATCHING, a
# wider net there costs false wakes); these only ever STRIP a
# leading token from a transcript that already woke Nalox.
_EXTRA_NAME_SPELLINGS = ["নালক্স", "নালোক্স", "नालक्स"]


def _strip_leading_wake_name(text):
    """Remove ONE leading wake-name token from a transcript
    (v6.6) — used on the command-path re-hearing of a
    one-breath segment, whose reading may carry the name in
    any script or spelling ("নালক্স, কী খবর" / "nalox …").
    Returns the rest of the text, "" when the text was ONLY
    the name, and the text itself (stripped) when no leading
    name is found — callers compare to tell the cases apart."""
    raw = (text or "").strip()
    if not raw:
        return ""
    for variant in sorted(WAKE_VARIANTS_BN + WAKE_VARIANTS_HI
                          + _EXTRA_NAME_SPELLINGS,
                          key=len, reverse=True):
        if raw.startswith(variant):
            return raw[len(variant):].strip(" .,!?।")
    parts = raw.split(None, 1)
    first = parts[0] if parts else ""
    rest = parts[1].strip(" .,!?।") if len(parts) > 1 else ""
    core = re.sub(r"[^a-z0-9]", "", first.lower())
    if core and _is_wake_token(core):
        return rest
    token = first.strip(" .,!?।")
    if token and not core:
        # A pure Bengali/Devanagari first token within edit
        # distance 2 of a script variant is the name as the
        # STT spelled it ("নালক্স" for "ন্যালক্স").
        for variant in WAKE_VARIANTS_BN + WAKE_VARIANTS_HI:
            if _levenshtein(token, variant) <= 2:
                return rest
    return raw


class Segmenter:
    """Energy segmenter (Ears 2.0) — pure bookkeeping, no I/O.

    Feed it one 0.1 s chunk at a time with the chunk's RMS and the
    current gate threshold. A segment STARTS on the first chunk
    that beats the threshold and ENDS after TRAIL_CHUNKS (0.7 s)
    of below-threshold chunks, or at MAX_CHUNKS (5 s). feed()
    returns the completed segment (list of chunks, including the
    trailing quiet — Whisper's VAD trims it) or None. Segments
    with fewer than MIN_SPEECH_CHUNKS loud chunks are blips
    (a cough, a click) and are discarded. Silence NEVER produces
    a segment — that is the whole point.

    v4.4: the timings are constructor parameters (defaults are
    exactly the class constants, so wake behaviour is unchanged);
    the command recorder reuses this class with a 0.8 s trail
    and an 8 s cap.
    """
    TRAIL_CHUNKS = 7      # 0.7 s of quiet ends a segment
    MAX_CHUNKS = 50       # 5 s hard cap
    MIN_SPEECH_CHUNKS = 2  # ignore sub-0.2 s blips

    def __init__(self, trail_chunks=None, max_chunks=None,
                 min_speech_chunks=None):
        self._trail = (self.TRAIL_CHUNKS if trail_chunks is None
                       else int(trail_chunks))
        self._max = (self.MAX_CHUNKS if max_chunks is None
                     else int(max_chunks))
        self._min_speech = (self.MIN_SPEECH_CHUNKS
                            if min_speech_chunks is None
                            else int(min_speech_chunks))
        self._chunks = []
        self._speech = 0
        self._trailing = 0
        self._active = False

    @property
    def active(self):
        return self._active

    def reset(self):
        self._chunks = []
        self._speech = 0
        self._trailing = 0
        self._active = False

    def feed(self, chunk, rms, threshold):
        """One chunk in; a completed segment out (or None)."""
        if not self._active:
            if rms > threshold:
                self._active = True
                self._chunks = [chunk]
                self._speech = 1
                self._trailing = 0
            return None
        self._chunks.append(chunk)
        if rms > threshold:
            self._speech += 1
            self._trailing = 0
        else:
            self._trailing += 1
        if (self._trailing >= self._trail
                or len(self._chunks) >= self._max):
            segment = self._chunks
            speech = self._speech
            self.reset()
            if speech >= self._min_speech:
                return segment
        return None


# --------------------------------------- barge-in interrupts (v4.1)
# While Nalox is SPEAKING, Arjun can cut in like with Gemini/JARVIS:
# the wake word (any variant above) or a plain stop word — "stop",
# "থামো" (stop), "চুপ" (hush). "stop" is matched as a whole TOKEN so
# ordinary words like "stock" or "stopping" never interrupt.
INTERRUPT_BN = ["থামো", "চুপ"]


def is_interrupt_word(text):
    """True if a transcript should cut Nalox off mid-speech."""
    if not text:
        return False
    if looks_like_wake_word(text):
        return True
    raw = text.lower()
    if any(word in raw for word in INTERRUPT_BN):
        return True
    cleaned = re.sub(r"[^a-z ]", " ", raw)
    return "stop" in cleaned.split()


class _ChunkSource:
    """Callback-driven mic chunk source (v4.6).

    sounddevice's blocking read() can hang FOREVER when a stream
    dies silently (USB sleep, device switch) — the wake loop sat
    inside read() while Windows had already buried the device,
    which is one half of Arjun's "থেমে যাচ্ছে" hang. This source
    instead runs the stream with a callback that drops chunks
    into a bounded queue; the consumer reads with a timeout, so
    "no chunk arrived" becomes observable — and the mic-health
    watchdog can reopen the stream. The audio callback itself
    never blocks: a full queue drops the chunk (and counts it).

    read(timeout) returns one (frames, 1) float32 array, or None
    on timeout. reopen() closes and reopens on the current best
    device (Ears._open_stream re-picks it). close() is idempotent.
    """

    def __init__(self, ears, block_frames, max_chunks=100):
        self._ears = ears
        self._block = int(block_frames)
        self._queue = queue.Queue(maxsize=max_chunks)
        self._stream = None
        self.dropped = 0
        self._open()

    def _open(self):
        import sounddevice as sd

        def _cb(indata, frames, time_info, status):
            try:
                self._queue.put_nowait(indata.copy())
            except queue.Full:
                self.dropped += 1  # never block the audio thread

        stream = self._ears._open_stream(
            sd, callback=_cb, blocksize=self._block)
        stream.start()
        self._stream = stream

    def read(self, timeout=0.25):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def reopen(self):
        self.close()
        while True:  # stale chunks from the dead stream are junk
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._open()

    def close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


class Ears:
    def __init__(self, cfg):
        self.cfg = cfg
        self._stop = threading.Event()
        # Mic auto-connect state (v3.5): the sentinel forces a
        # "[mic] connected: ..." status line on the very first listen.
        self._device_index = "unset"
        self._device_name = ""
        # Barge-in state (v4.1): once the monitor has failed to open
        # its stream it disables itself and complains exactly once.
        self._bargein_broken = False
        # Adaptive energy gate state (v4.2): the ambient noise floor
        # (RMS), learned by a slow EMA over quiet buffers. 0.0 means
        # "not calibrated yet" — the first buffer only calibrates.
        self._noise_floor = 0.0
        # Self-hearing state (v4.2): whether Nalox was speaking on
        # the previous wake-loop chunk, and when that speech ended
        # (the echo tail is measured from there).
        self._was_speaking = False
        self._speech_end = 0.0
        # v4.3: gate visibility (last floor posted in a [gate] line)
        # and the ears-side speaking watchdog (when the wake loop
        # first found itself blocked by is_speaking()).
        self._gate_reported_floor = 0.0
        self._speaking_blocked_since = 0.0
        # Ears 2.0: a one-breath command remainder waiting for
        # nalox.py ("Nalox কেমন আছো" -> ("কেমন আছো", "bn")).
        self._pending_command = None
        # v4.6: wake segments are transcribed OFF the capture
        # loop (a stuck decode must never freeze listening): a
        # bounded job queue + one consumer thread.
        # v6.2: the consumer no longer decodes itself — EVERY
        # decode goes to the worker PROCESS via _tx_client,
        # under hard deadlines (see _TxWorkerClient). The
        # v5.2 generation/heartbeat watchdog state is retired:
        # a wedged decode is now killed with its process, not
        # abandoned in-process.
        self._tx_queue = queue.Queue(maxsize=TRANSCRIBE_QUEUE_MAX)
        self._tx_worker = None
        self._tx_lock = threading.Lock()
        self._tx_seq = 0
        self._tx_client = _TxWorkerClient(cfg)
        self._wake_event = threading.Event()

    def stop(self):
        self._stop.set()
        try:
            self._tx_client.close()
        except Exception:
            pass

    # ---------- adaptive energy gate (v4.2; v4.3 retuned) ----------
    def gate_threshold(self):
        """The RMS a buffer must beat to be transcribed right now."""
        return max(self._noise_floor * 2.5, 0.006)

    def _report_gate(self):
        """Post the [gate] line (HUD + logbook) when the calibrated
        floor is new or changed materially (>25%) — v4.3 makes the
        gate VISIBLE so a too-quiet voice is diagnosable from the
        log page instead of a mystery."""
        floor = self._noise_floor
        reported = self._gate_reported_floor
        if reported <= 0.0 or abs(floor - reported) / max(reported, 1e-9) > 0.25:
            self._gate_reported_floor = floor
            _fire_status(
                f"[gate] floor={floor:.4f} "
                f"threshold={self.gate_threshold():.4f} "
                "(say 'Nalox' a bit louder if I miss you)")

    def _track_floor(self, rms):
        """Learn the ambient noise floor from one QUIET chunk
        (slow EMA, v4.2) and report material changes (v4.3)."""
        floor = self._noise_floor
        if floor <= 0.0:
            # First calibration — only a QUIET chunk may set the
            # floor. A loud first chunk is speech, not ambience:
            # calibrating on it would set the gate above the
            # speech itself and deafen Nalox (found by the v4.3
            # real-audio test: digital-silence padding, then the
            # first speech chunk became the "floor"). Loud onset
            # gets a conservative default floor instead.
            self._noise_floor = rms if rms <= 0.02 else 0.0024
            self._report_gate()
            return
        if rms <= floor * 2.0:
            self._noise_floor = floor + 0.05 * (rms - floor)
            self._report_gate()

    def _gate_open(self, rms):
        """Should this audio be transcribed at all? (v4.2; the
        floor tracking moved to _track_floor in v4.3 so the
        segmenter can share it.)"""
        if self._noise_floor <= 0.0:
            self._track_floor(rms)
            return False
        if rms <= self._noise_floor * 2.0:
            self._track_floor(rms)
            return False
        return rms > self.gate_threshold()

    # ---------- low level capture ----------
    def _open_stream(self, sd, **kwargs):
        """Open an input stream on the best mic RIGHT NOW (v3.5).

        The device is re-picked on every call: config mic_device if
        it matches, else the Windows default input — so plugging in
        the external mic (or unplugging it) switches automatically.
        A changed device is announced via the status callback. If the
        chosen device refuses to open, fall back to device=None and
        say so; opening a stream must never kill the listen loop.

        v4.6: extra sounddevice kwargs (callback=, blocksize= for
        the _ChunkSource) pass through to both attempts.
        """
        idx = pick_input_device(self.cfg)
        name = _device_name(idx)
        if idx != self._device_index or name != self._device_name:
            self._device_index = idx
            self._device_name = name
            log.info("Mic connected: %s (device %s)", name, idx)
            _fire_status(f"[mic] connected: {name}")
        try:
            return sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                  dtype="float32", device=idx, **kwargs)
        except Exception as exc:
            log.warning("Could not open mic %r (%s); using default",
                        name, exc)
            _fire_status(f"[mic] could not open '{name}' — "
                         "using the default microphone")
            return sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                  dtype="float32", device=None, **kwargs)

    def _record_seconds(self, seconds):
        import sounddevice as sd
        frames = int(seconds * SAMPLE_RATE)
        audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1,
                       dtype="float32",
                       device=pick_input_device(self.cfg))
        sd.wait()
        flat = audio.flatten()
        _update_level(flat)
        return flat

    # ---------- wake word loop ----------
    def take_pending_command(self):
        """The one-breath command remainder, if the last wake
        segment carried one (Ears 2.0). (text, lang) or None."""
        pending, self._pending_command = self._pending_command, None
        return pending

    def current_mic_name(self):
        """The mic the streams currently open on (v4.6 heartbeat)."""
        return self._device_name or "unknown"

    # ---------- transcription worker (v4.6 thread; v6.2 process) ----------
    # The wake loop CAPTURES; this thread COORDINATES. Completed
    # segments arrive on a bounded queue; for each one the
    # thread asks the worker PROCESS for its decode (hard
    # deadline — see _handle_wake_segment / _wake_pass) and
    # applies the wake policy. Capture never waits for any of
    # it, and since v6.2 neither does anything else: a decode
    # that wedges is terminated with its process by the
    # client, and this thread simply hears "nothing" for that
    # segment and moves on.
    def _ensure_tx_worker(self):
        with self._tx_lock:
            if self._tx_worker is not None \
                    and self._tx_worker.is_alive():
                return
            worker = threading.Thread(target=self._tx_loop,
                                      daemon=True, name="ears-tx")
            worker.start()
            self._tx_worker = worker

    def _tx_loop(self):
        while not self._stop.is_set():
            try:
                audio, model_name, job_id = self._tx_queue.get(
                    timeout=0.5)
            except queue.Empty:
                continue
            woke = False
            try:
                woke = bool(self._handle_wake_segment(audio,
                                                      model_name))
            except Exception as exc:
                log.warning("Wake transcription job failed: %s", exc)
            except BaseException as exc:
                # v5.2 CRASH-GUARD (kept): a HARD failure
                # (MemoryError, a native-layer error surfacing
                # as BaseException) must not strand the wake
                # loop — log it and let this thread die;
                # _ensure_tx_worker starts a fresh one on the
                # next submitted segment. The decodes themselves
                # live in the worker process since v6.2, so a
                # native crash there can't even reach this line.
                log.error("[CRASH-GUARD] wake worker hit a hard "
                          "failure (%s: %s) — thread exiting; a "
                          "fresh worker will take over",
                          type(exc).__name__, exc)
                _fire_status("[CRASH-GUARD] wake worker restarted")
                return
            if woke:
                # Segments still queued were recorded BEFORE the
                # wake — their moment has passed; drop them so a
                # stale one can't re-wake or double-post [heard].
                dropped = 0
                while True:
                    try:
                        self._tx_queue.get_nowait()
                        dropped += 1
                    except queue.Empty:
                        break
                if dropped:
                    log.info("Wake fired — dropped %d stale "
                             "queued segment(s)", dropped)
                self._wake_event.set()

    def _submit_wake_segment(self, audio, model_name):
        """Queue one completed wake segment for transcription.

        Returns True if queued. On a full queue the OLDEST job is
        dropped (the freshest speech is the most likely to be the
        wake word) and the drop is logged. Never blocks.
        """
        self._ensure_tx_worker()
        with self._tx_lock:
            self._tx_seq += 1
            job_id = self._tx_seq
        job = (audio, model_name, job_id)
        try:
            self._tx_queue.put_nowait(job)
            return True
        except queue.Full:
            pass
        try:
            self._tx_queue.get_nowait()
            log.warning("Transcription queue full — dropped the "
                        "oldest wake segment")
        except queue.Empty:
            pass
        try:
            self._tx_queue.put_nowait(job)
            return True
        except queue.Full:
            log.warning("Transcription queue full — dropped a "
                        "wake segment")
            return False

    def transcribe_queue_size(self):
        """Pending wake-segment jobs (v4.6 heartbeat evidence)."""
        try:
            return self._tx_queue.qsize()
        except Exception:
            return -1

    # ---------- worker-process decode doors (v6.2) ----------
    def _wake_pass(self, audio, model_name, kwargs):
        """ONE wake decode in the worker process, under
        WAKE_TX_DEADLINE. (text, lang, no_speech) or None —
        None means the worker timed out / crashed / is in
        backoff, which the wake policy treats exactly like an
        empty decode (its one retry then gets a fresh worker).
        Never raises, never blocks past the deadline."""
        got = self._tx_client.request(
            "wake_pass", (audio, model_name, kwargs),
            WAKE_TX_DEADLINE)
        if got is None:
            return None
        try:
            text, lang, nsp, _lp = got
            return text, lang, float(nsp)
        except Exception:
            return None

    def _local_command(self, audio, model_name, initial_prompt):
        """The local command fallback, worker-side: the full
        transcribe_command policy under COMMAND_TX_DEADLINE.
        ("", "en") on any worker failure. Never raises."""
        got = self._tx_client.request(
            "command", (audio, model_name, initial_prompt),
            COMMAND_TX_DEADLINE)
        if got is None:
            return "", "en"
        try:
            return got[0], got[1]
        except Exception:
            return "", "en"

    def _raw_transcribe(self, audio, model_name):
        """One plain decode in the worker process (barge-in
        windows), under WAKE_TX_DEADLINE. ("", "en") on any
        worker failure. Never raises."""
        got = self._tx_client.request(
            "raw", (audio, model_name, None, None),
            WAKE_TX_DEADLINE)
        if got is None:
            return "", "en"
        try:
            return got[0], got[1]
        except Exception:
            return "", "en"

    def _segment_peak_rms(self, audio):
        """Peak 0.1 s-chunk RMS inside a completed segment (v4.5).

        The wake retry decision needs "was this segment LOUD?" —
        the peak chunk, not the average (a segment is mostly the
        trailing quiet by design).
        """
        if audio is None or len(audio) == 0:
            return 0.0
        block = int(0.1 * SAMPLE_RATE)
        peak = 0.0
        for i in range(0, len(audio), block):
            r = _rms(audio[i:i + block])
            if r > peak:
                peak = r
        return peak

    def _handle_wake_segment(self, audio, model_name):
        """Transcribe ONE completed segment; True if it woke Nalox.

        Auto-detected language (Bengali speech -> Bengali text).

        v4.5 DELIVERY RULE — a completed segment exists only
        because the segmenter heard sustained speech energy, so
        the segment IS speech. Its text is delivered (posted as
        [heard], wake-matched, remainder handed to the brain)
        whenever it passes is_garbage() — REGARDLESS of
        no_speech_prob, which saturates at 1.00 on genuine
        Bengali and ate Arjun's real command at 10:09. The hard
        no_speech drop is GONE; no_speech is logged as info only.
        The only drops left: empty text and is_garbage() itself
        (blacklist phrases / repetition / punctuation soup).

        v4.5 RETRY — the fast wake model ("base") is only
        trusted within its depth. On a LOUD segment (peak chunk
        RMS >= 3x the gate threshold — unmistakably real speech)
        it gets exactly ONE retry with the accurate command model
        ("small") when either:
          (a) its text came back garbage/empty, or
          (b) its text is clean but the detected language is
              OUTSIDE Arjun's set {en, bn, hi} — base heard his
              Hindi as Spanish "kasiho" in the real-audio test:
              the wake word survived but the remainder was wrecked,
              while small heard "कैसे हो" perfectly. A clean
              retry reading replaces the first pass; a garbage
              retry never displaces a clean first pass.
        Weak segments get no retry either way: they were probably
        noise, and quiet rooms must stay free.

        v4.6 RETRY, trigger (c) — the Bengali wake rescue: on
        v4.5 Arjun's verdict was "English works, Bengali still
        doesn't". One way that happens: base reads his Bengali
        cleanly enough to pass the garbage filter, in-set label
        and all — but mangles the NAME itself, so no wake match
        and triggers (a)/(b) never fire. So: a loud segment with
        no wake match whose dominant script is Bengali or
        Devanagari ALSO earns the one retry (if not already
        spent) — the small reading may contain the name. English-
        dominant no-match segments never retry: they were almost
        certainly not addressed to Nalox, and the fast path stays
        fast.

        v6.4 — the first pass is now the TINY model by default
        (config wake_model default "tiny": the cheapest ears
        that can catch the name, ~3x faster again than base on
        a busy CPU — every idle second of wake listening runs
        on it). RETRY, trigger (d): a clean loud segment with
        no wake match whose text is a NEAR-MISS (a token at
        edit distance exactly 2 from the name — _wake_near_miss)
        earns the one retry with WAKE_RETRY_MODEL ("base").
        Triggers (a)/(b)/(c) are unchanged and keep the command
        model ("small"); the one-retry budget is shared — any
        trigger that fires spends it.

        v6.6 — the one-breath REMAINDER is no longer trusted
        to the wake decode: the wake ears only have to find
        the NAME. When a remainder exists, the same segment
        audio is re-heard through the command path
        (transcribe_command_best — cloud first) and ITS
        reading (wake-name stripped) becomes the command;
        the wake remainder survives only as the fallback when
        the command path hears nothing usable.
        """
        kwargs = dict(beam_size=1, language=None, word_timestamps=False)
        kwargs.update(_DECODE_GUARDS)
        kwargs["initial_prompt"] = COMMAND_PROMPT
        started = time.monotonic()
        text, lang, no_speech = "", "en", 1.0
        # v6.2: the decode runs in the worker PROCESS under
        # the wake deadline (v6.3: 8 s, measured from the
        # worker's ack) — a timeout/crash reads as an empty
        # decode here, and the retry policy below gets its
        # say with a fresh worker.
        got_pass = self._wake_pass(audio, model_name, kwargs)
        if got_pass is not None:
            text, lang, no_speech = got_pass
        took = time.monotonic() - started

        command_model = (self.cfg.get("whisper_command_model")
                         or "small")
        peak = self._segment_peak_rms(audio)
        threshold = self.gate_threshold()
        loud = peak >= 3.0 * threshold
        can_retry = (command_model != model_name and loud)
        # v6.4: the near-miss retry runs on WAKE_RETRY_MODEL
        # ("base") — stronger than the tiny first pass, faster
        # than going straight to the command model.
        can_retry_base = (WAKE_RETRY_MODEL != model_name and loud)

        def _retry_with_command_model():
            """The one small-model retry; (text, lang, nsp) or None."""
            got2 = self._wake_pass(audio, command_model, kwargs)
            if got2 is None:
                return None
            t2, l2, n2 = got2
            if t2 and not is_garbage(t2):
                return t2, l2, n2
            return None

        def _retry_with_base_model():
            """The one base-model retry (v6.4 trigger (d));
            (text, lang, nsp) or None, same cleanliness rule."""
            got2 = self._wake_pass(audio, WAKE_RETRY_MODEL, kwargs)
            if got2 is None:
                return None
            t2, l2, n2 = got2
            if t2 and not is_garbage(t2):
                return t2, l2, n2
            return None

        retried = False
        if not text or is_garbage(text):
            if can_retry:
                retried = True
                log.info("Wake segment garbled by %s (peak %.4f = "
                         "%.1fx the gate) — retrying once with %s",
                         model_name, peak,
                         peak / max(threshold, 1e-9), command_model)
                got = _retry_with_command_model()
                took = time.monotonic() - started
                if got is not None:
                    text, lang, no_speech = got
            if not text or is_garbage(text):
                if text:
                    log.info("Wake segment dropped as garbage: %r "
                             "(no_speech %.2f — info only, never "
                             "the reason)", text, no_speech)
                return False
        elif lang not in ALLOWED_LANGS and can_retry:
            retried = True
            log.info("Wake model %s labelled a loud segment %r "
                     "(lang %s, outside en/bn/hi) — retrying once "
                     "with %s", model_name, text, lang, command_model)
            got = _retry_with_command_model()
            took = time.monotonic() - started
            if got is not None:
                text, lang, no_speech = got
        # v4.6 trigger (c): clean, loud, no wake match, dominant
        # script Bengali/Devanagari — the base pass may have
        # mangled the NAME itself; one small retry may find it.
        if not retried and can_retry \
                and not looks_like_wake_word(text) \
                and _dominant_script(text) in ("bn", "hi"):
            log.info("Wake segment in %s script with no wake "
                     "match (loud, peak %.4f) — retrying once "
                     "with %s (Bengali wake rescue)",
                     _dominant_script(text), peak, command_model)
            got = _retry_with_command_model()
            took = time.monotonic() - started
            if got is not None:
                text, lang, no_speech = got
        # v6.4 trigger (d): clean, loud, no wake match — but a
        # token sits at edit distance exactly 2 from the name
        # (_wake_near_miss): the tiny first pass ALMOST heard
        # him. One retry with WAKE_RETRY_MODEL ("base"), whose
        # sharper ears usually resolve the name outright.
        if not retried and can_retry_base \
                and not looks_like_wake_word(text) \
                and _wake_near_miss(text):
            retried = True
            log.info("Wake segment near-miss by %s (%r — close "
                     "to the name, no match) — retrying once "
                     "with %s", model_name, text, WAKE_RETRY_MODEL)
            got = _retry_with_base_model()
            took = time.monotonic() - started
            if got is not None:
                text, lang, no_speech = got
        log.info("Heard segment: %r (lang %s, no_speech %.2f, %.1fs)",
                 text, lang, no_speech, took)
        _post_heard(text)
        if not looks_like_wake_word(text):
            return False
        # English anchor: an out-of-set detected label (e.g. "ur"
        # for Bengali speech) never propagates — the remainder's
        # language comes from its actual script, defaulting to en.
        if lang not in ALLOWED_LANGS:
            lang = "en"
        log.info("Wake word heard (segment: %r, lang %s, %.1fs)",
                 text, lang, took)
        # v5.2: a wake-UP variant ("nalox wake up" / "ন্যালক্স
        # ওঠো" / "नालॉक्स उठो") also raises the window — the
        # wake-up callback fires below; the phrase itself is
        # stripped from any one-breath remainder so it never
        # reaches the brain as a "command".
        wake_up = looks_like_wake_up(text)
        remainder, rlang = split_wake_remainder(text, lang)
        if wake_up:
            remainder = _strip_wake_up_phrase(remainder)
        if remainder and not is_garbage(remainder):
            # v6.6: the remainder came from the WAKE model's
            # ears (tiny by default) — sharp enough to catch
            # the name, NOT sharp enough to trust with the
            # command itself. Field 2026-11-15 19:24 IST: he
            # asked "কী খবর বর্তমানে" in one breath and the
            # tiny decode delivered "kik har bortomard" — the
            # brain could only ask what he meant. So the SAME
            # segment audio now goes through the real command
            # ears (transcribe_command_best — cloud Gemini /
            # Groq first, the local command model behind
            # them); a leading wake-name token is stripped
            # from its reading, and THAT becomes the command.
            # If the command path hears nothing usable, the
            # wake remainder stands — a command is never lost.
            try:
                ctext, clang, csrc = transcribe_command_best(
                    audio, command_model, self.cfg,
                    initial_prompt=COMMAND_PROMPT,
                    local_fn=self._local_command)
            except Exception as exc:
                log.error("[CRASH-GUARD] one-breath "
                          "re-transcription failed: %s: %s",
                          type(exc).__name__, exc)
                ctext, clang, csrc = "", "en", "local"
            if ctext and not is_garbage(ctext):
                crest, crlang = split_wake_remainder(ctext,
                                                     clang)
                cand = crest
                if not cand:
                    stripped = _strip_leading_wake_name(ctext)
                    if stripped and stripped != ctext.strip():
                        # The splitter missed this spelling
                        # of the name; the stripper caught it.
                        cand = stripped
                        crlang = _script_lang(
                            cand, clang if clang in ALLOWED_LANGS
                            else rlang)
                    elif stripped == ctext.strip() \
                            and not looks_like_wake_word(ctext):
                        # No name anywhere in the reading —
                        # the whole text IS the command (the
                        # command ears often drop the name).
                        cand = ctext.strip(" .,!?।")
                        crlang = _script_lang(
                            cand, clang if clang in ALLOWED_LANGS
                            else rlang)
                    # (stripped == "" means the reading was
                    # ONLY the name — no command in it; the
                    # wake remainder below stands.)
                if cand and not is_garbage(cand):
                    if wake_up:
                        cand = _strip_wake_up_phrase(cand)
                    if cand:
                        log.info("One-breath command re-heard "
                                 "via %s: %r (%s) — the wake "
                                 "ears had %r", csrc, cand,
                                 crlang, remainder)
                        remainder, rlang = cand, crlang
            took = time.monotonic() - started
            self._pending_command = (remainder, rlang)
            LAST_TIMING["record"] = len(audio) / SAMPLE_RATE
            LAST_TIMING["transcribe"] = took
            log.info("One-breath command: %r (%s)", remainder, rlang)
        if wake_up:
            log.info("Wake-UP phrase heard (segment: %r) — "
                     "window show requested", text)
            _fire_wake_up_callback()
        _fire_wake_callback()
        return True

    def wait_for_wake_word(self):
        """Block until the wake word is heard (or stop() is called).

        EARS 2.0 (v4.3) — SEGMENT-BASED WAKE. 0.1 s chunks stream
        past an energy Segmenter fed by the adaptive gate; only a
        completed speech segment is transcribed, with the wake
        model (v6.4: "tiny" by default — fastest; a loud segment
        it garbles is retried once with the command model, and a
        near-miss of the name once with "base") and
        auto-detected language. Silence costs
        nothing and can invent nothing. Self-hearing protection is
        unchanged: while Nalox speaks the mic is drained and the
        segmenter reset, plus the 0.4 s echo tail; the v4.3
        speaking-flag watchdog rescue also stays. The HUD TALK
        button (request_command) still wakes instantly.

        v4.6 — the loop no longer transcribes or blocks:
          - Capture runs on a _ChunkSource (callback stream +
            queue); reads time out every 0.25 s, so a silently
            dead mic stream is DETECTED (no chunk for
            MIC_SILENT_SECONDS while listening) and reopened —
            "[mic] stream reopened (silent 10s+)" — at most once
            per MIC_REOPEN_MIN_INTERVAL, with an ERROR log from
            the third consecutive silent period on.
          - Completed segments are handed to the transcription
            thread (_submit_wake_segment); this loop only
            polls the wake event the thread sets. A stuck decode
            delays nothing here — and since v6.2 the decode
            itself is deadline-killed in its worker process
            (see _TxWorkerClient).
        """
        block = int(0.1 * SAMPLE_RATE)
        segmenter = Segmenter()
        model_name = (self.cfg.get("wake_model")
                      or self.cfg.get("whisper_command_model", "small"))
        log.info("Listening for wake word '%s' (Ears 2.0 segments, "
                 "model %s)...", self.cfg["assistant_name"], model_name)
        self._wake_event.clear()
        self._ensure_tx_worker()
        source = _ChunkSource(self, block)
        health = _MicHealth()
        last_chunk_at = time.monotonic()
        last_reopen_at = 0.0
        try:
            while not self._stop.is_set():
                if _manual_command.is_set():
                    _manual_command.clear()
                    log.info("Woken by request_command().")
                    _fire_wake_callback()
                    return True
                if self._wake_event.is_set():
                    self._wake_event.clear()
                    return True
                data = source.read(timeout=0.25)
                now = time.monotonic()
                if data is None:
                    # No chunk arrived — the stream may be dead.
                    if health.reopen_due(now, last_chunk_at,
                                         last_reopen_at):
                        last_reopen_at = now
                        failures = health.note_reopen()
                        if failures >= 3:
                            log.error("[mic] stream reopened "
                                      "(silent 10s+) — %d "
                                      "consecutive silent periods",
                                      failures)
                        else:
                            log.warning("[mic] stream reopened "
                                        "(silent 10s+)")
                        _fire_status("[mic] stream reopened "
                                     "(silent 10s+)")
                        try:
                            source.reopen()
                        except Exception as exc:
                            log.warning("Mic stream reopen "
                                        "failed: %s", exc)
                    continue
                last_chunk_at = now
                health.note_chunk()
                chunk = data.flatten()
                _update_level(chunk)
                # --- no self-hearing (v4.2): drain, never decode ---
                if _nalox_is_speaking():
                    # v4.3 watchdog rescue: a speaking flag blocking
                    # listening for >45 s straight is leaked — the
                    # ears-side second layer force-clears it.
                    if not self._speaking_blocked_since:
                        self._speaking_blocked_since = time.monotonic()
                    elif time.monotonic() - self._speaking_blocked_since \
                            > 45.0:
                        try:
                            import voice as _voice_mod
                            _voice_mod.force_clear_speaking()
                        except Exception:
                            pass
                        _fire_status("[voice] speaking flag "
                                     "force-cleared by ears watchdog")
                        self._speaking_blocked_since = 0.0
                    self._was_speaking = True
                    segmenter.reset()
                    continue
                self._speaking_blocked_since = 0.0
                if self._was_speaking:
                    self._was_speaking = False
                    self._speech_end = time.monotonic()
                if time.monotonic() - self._speech_end < ECHO_TAIL_SECONDS:
                    segmenter.reset()  # speaker echo tail — discard
                    continue
                rms = _rms(chunk)
                if not segmenter.active:
                    self._track_floor(rms)
                segment = segmenter.feed(chunk, rms,
                                         self.gate_threshold())
                if segment is None:
                    continue
                audio = np.concatenate(segment)
                if len(audio) < SAMPLE_RATE * 0.4:
                    continue
                # v4.6: the worker transcribes; capture never waits.
                self._submit_wake_segment(audio, model_name)
        finally:
            source.close()
        return False

    # ---------- barge-in monitor (v4.1) ----------
    def _bargein_fail(self, exc):
        """Disable barge-in after one stream failure; complain once."""
        if not self._bargein_broken:
            self._bargein_broken = True
            log.warning("Barge-in monitor unavailable (%s); "
                        "continuing without it", exc)
            _fire_status("[mic] barge-in unavailable — "
                         "could not open a monitor stream")

    def monitor_interrupt(self, active_fn, on_interrupt):
        """Listen for an interrupt WHILE Nalox is speaking (v4.1).

        Opens its OWN input stream (the main listen stream is closed
        while speaking) and transcribes 1.2 s windows with the wake
        (tiny) model. While active_fn() is true: if a window matches
        is_interrupt_word() — the wake word, "stop", "থামো", "চুপ" —
        on_interrupt() is called (nalox.py passes voice.stop) and
        True is returned. Returns False when the speech ends on its
        own, when stop() is called, after a 60 s safety cap, or when
        the stream can't be opened (barge-in then disables itself —
        see _bargein_fail). Echo safety: only interrupt words are
        checked, and Nalox's own replies virtually never contain
        them; monitor transcripts are never posted as [heard].
        """
        if self._bargein_broken:
            return False
        import sounddevice as sd
        block = int(0.1 * SAMPLE_RATE)
        window_blocks = 12  # 1.2 s windows
        chunks = []
        started = time.monotonic()
        try:
            stream_ctx = self._open_stream(sd)
        except Exception as exc:
            self._bargein_fail(exc)
            return False
        try:
            with stream_ctx as stream:
                while not self._stop.is_set() and active_fn():
                    if time.monotonic() - started > 60.0:
                        return False  # safety cap — never listen forever
                    data, _ = stream.read(block)
                    chunk = data.flatten()
                    _update_level(chunk)
                    chunks.append(chunk)
                    if len(chunks) < window_blocks:
                        continue
                    audio = np.concatenate(chunks)
                    chunks = []
                    if _rms(audio) < SILENCE_RMS * 0.8:
                        continue  # silence — skip transcription
                    # v6.2: decoded in the worker process under
                    # the wake deadline — a wedged barge-in
                    # decode reads as "no interrupt" and the
                    # worker is restarted by the client.
                    text, _lang = self._raw_transcribe(
                        audio, self.cfg["whisper_wake_model"])
                    if text and is_interrupt_word(text):
                        log.info("Barge-in interrupt heard "
                                 "(transcript: %r)", text)
                        try:
                            on_interrupt()
                        except Exception:
                            pass
                        return True
        except Exception as exc:
            self._bargein_fail(exc)
            return False
        return False

    # ---------- one command ----------
    def listen_for_command(self):
        """Record one utterance; returns (text, detected_language).

        text is '' if nothing was heard.

        v4.4 ENDPOINTING (field fix for the 31-47 s transcriptions
        in Arjun's 09:51 screenshot): the recorder now runs
        through the same Segmenter as the wake loop, fed by the
        ADAPTIVE gate threshold. The old recorder stopped after
        1.2 s below a FIXED RMS level — in a noisy room the noise
        itself sat above that level, so follow-up recordings ran
        the full 12 s cap and the small model then spent half a
        minute transcribing room noise. Now recording starts when
        speech beats the gate, stops 0.8 s after speech energy
        ends, and is hard-capped at 8 s; a clip whose actual
        speech content is under 0.3 s is never transcribed at
        all. It waits up to ~5 s for speech to start (nalox.py's
        follow-up window simply re-calls until its own deadline).

        v4.2 behaviour kept: if Nalox is still speaking when this
        is called (the Settings test voice, a reminder, a Telegram
        reply — anything on another thread), recording waits for
        the speech to finish first (up to ~10 s) so the command
        never contains Nalox's own voice; transcription follows
        the transcribe_command language policy.
        """
        import sounddevice as sd
        deadline = time.monotonic() + 10.0
        while _nalox_is_speaking() and not self._stop.is_set() \
                and time.monotonic() < deadline:
            time.sleep(0.1)
        record_start = time.monotonic()  # stage timing
        block = int(0.1 * SAMPLE_RATE)
        segmenter = Segmenter(trail_chunks=8,
                              max_chunks=int(COMMAND_MAX_SECONDS * 10),
                              min_speech_chunks=2)
        segment = None
        wait_chunks = 0
        with self._open_stream(sd) as stream:
            while not self._stop.is_set():
                data, _ = stream.read(block)
                chunk = data.flatten()
                _update_level(chunk)
                rms = _rms(chunk)
                if not segmenter.active:
                    self._track_floor(rms)
                    wait_chunks += 1
                    if wait_chunks > 50:  # ~5 s and nobody spoke
                        break
                segment = segmenter.feed(chunk, rms,
                                         self.gate_threshold())
                if segment is not None:
                    break
        LAST_TIMING["record"] = time.monotonic() - record_start
        if segment is None:
            LAST_TIMING["transcribe"] = 0.0
            return "", "en"
        threshold = self.gate_threshold()
        speech_s = 0.1 * sum(1 for c in segment
                             if _rms(c) > threshold)
        if speech_s < 0.3:
            LAST_TIMING["transcribe"] = 0.0
            log.info("Command clip held only %.1fs of speech — "
                     "not transcribing it", speech_s)
            return "", "en"
        audio = np.concatenate(segment)
        _t0 = time.monotonic()
        # v5.2 CRASH-GUARD: transcribe_command_best is internally
        # contained (cloud fns catch, the local policy has been
        # crash-contained since v4.8) — this wrap is the last net,
        # so NO transcription failure of any shape can escape into
        # the main loop and cost more than this one command.
        try:
            text, lang, ear_src = transcribe_command_best(
                audio, self.cfg["whisper_command_model"], self.cfg,
                initial_prompt=COMMAND_PROMPT,
                local_fn=self._local_command)
        except Exception as exc:
            log.error("[CRASH-GUARD] command transcription "
                      "escaped containment: %s: %s",
                      type(exc).__name__, exc)
            _fire_status("[CRASH-GUARD] transcription failed — "
                         "kept listening")
            text, lang, ear_src = "", "en", "local"
        LAST_TIMING["transcribe"] = time.monotonic() - _t0
        log.info("Command heard: %r (language: %s)", text, lang)
        # v5.1: which ear produced this text is always on the
        # record — cloud:gemini / cloud:groq / local — so a
        # Bengali garble is diagnosable from the log page.
        log.info("[ears] heard via %s", ear_src)
        _fire_status(f"[ears] heard via {ear_src}")
        if text:
            _post_heard(text)
        return text, lang

    # ---------- file transcription (Telegram voice notes) ----------
    def transcribe_file(self, path):
        """Transcribe an audio file. Returns (text, detected_language).

        v4.8: crash-contained like transcribe_command — a model
        failure on an odd file returns ("", "en"), never raises
        into the Telegram bridge.
        v6.2: the decode runs in the worker process under
        FILE_TX_DEADLINE (see _transcribe_file_local); a worker
        failure of any shape reads as ("", "en") here too."""
        got = self._tx_client.request(
            "file", (path, self.cfg["whisper_command_model"]),
            FILE_TX_DEADLINE)
        if got is None:
            return "", "en"
        try:
            return got[0], got[1]
        except Exception:
            return "", "en"


def _transcribe_file_local(path, model_name):
    """The worker-side file decode (v6.2): the pre-v6.2
    Ears.transcribe_file body, running in the worker process
    where decodes are serial. Crash-contained — a model
    failure on an odd file returns ("", "en")."""
    try:
        model = _get_model(model_name)
        segments, info = _transcribe(model, path,
                                     language=None,
                                     beam_size=1,
                                     **_DECODE_GUARDS)
        text = " ".join(seg.text for seg in segments).strip()
        return text, _lang_of(info)
    except Exception as exc:
        log.warning("File transcription failed: %s: %s",
                    type(exc).__name__, exc)
        return "", "en"
