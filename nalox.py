"""Nalox — Arjun's personal voice assistant.

Started by supervisor.py (which is started by start_nalox.vbs at login).
Loop: greet -> morning briefing (+ headlines) -> startup YouTube check
-> listen for wake word "Nalox" -> record one command -> run it -> speak
the reply -> brief follow-up window (no wake word needed) -> listen again.

v2: bilingual greeting (config default_language), replies spoken in the
language of the command (ears auto-detects English/Bengali), and the
startup YouTube channel check.

v3: hacker-console HUD (hud.py, config show_hud), follow-up listening
window (config followup_seconds), a spoken morning briefing (config
morning_briefing) with top news headlines (config briefing_news), and a
reminder checker thread that speaks due reminders from reminders.json.

v3.4: live MIC meter in the HUD (ears.get_level) and a wake-word beep
+ HUD flash (ears.set_wake_callback), so Arjun can SEE and HEAR that
his voice reached Nalox.

v3.5: mic status lines from ears (auto-connect announcements) are
mirrored to the HUD via ears.set_status_callback; the boot log posts
"[voice] active: ..." (voice.describe_active) so Arjun can see which
voice will speak; the spoken "I hit a small problem" warning is
rate-limited to once per 300 s — HUD [error] posts are not limited.

v3.7: the boot sequence ends with "[ready] Say 'Nalox' to wake me" —
the wake word itself is far more forgiving now (rolling buffer +
fuzzy matching in ears.py), and the HUD has a TALK button as a
guaranteed wake path.

v4.0: the boot log also posts which brain is live — "[brain] Claude
connected" when an Anthropic API key is configured (Claude is the
agent brain's top priority), else "[brain] local/free mode".
v4.8: that label was a lie by omission — it printed "Claude
connected" for ANY non-empty key, validated or not (Arjun's Groq
key sat in the Claude field for a day under that label). The boot
line, the HUD header and the logbook header now all render
brain.brain_status_line() — the VALIDATED state (Groq ✓ / key
rejected (401) / Local — no key) — refreshed as the boot key
check lands and after every config hot-reload.

v4.1: the HUD is now a normal app window (hud.py rewritten — same
API). Every HUD post is mirrored into the logbook (logbook.py):
nalox_log.txt + nalox_page.html, the diagnostics page Arjun opens
with the 📋 Log button. The boot sequence records a SYSTEM snapshot
(version, mic, speaker output, voice, brain, robot flag) in the
logbook header. Replies are BARGE-IN interruptible: say() runs the
speech on a worker thread while ears.monitor_interrupt listens for
the wake word / "stop" — a match calls voice.stop() and Nalox goes
straight back to listening. The boot greeting can be switched off
in Settings (greet_on_startup); boot headlines default OFF
(briefing_news) — news only when asked.

Exit paths:
  - Tray icon -> Exit Nalox -> exit code 42 (supervisor won't relaunch)
  - Tray icon -> Restart    -> exit code 1  (supervisor relaunches)
  - HUD Exit button         -> exit code 42
  - A CONFIRMED PC shutdown/restart by voice (the machine itself
    is going down) -> exit code 42
  v5.4: voice/Telegram "stop" is NO LONGER an exit path — it is
  action "standby" (stop speaking, keep listening). Arjun's own
  stop commands were the mystery killer of v5.1/v5.2 (code 42 at
  boot from a queued Telegram "stop"); the rule now: deliberate
  app exit is tray/HUD clicks only.

v4.6: SELF-RESTART — the HUD's 🔄 Restart button and the voice
command "Nalox, restart" (brain action "restart") both land in
_restart_process(): exit code 1, so the supervisor relaunches a
FRESH process (mic streams, Whisper models, config — everything
rebuilt from scratch; that is exactly why a restart un-sticks
Nalox). A heartbeat thread writes one "[heartbeat] state=...
mic=... queue=..." line per minute to nalox_log.txt ONLY
(logbook.log_file_only — never the HUD feed): when Nalox hangs,
the last heartbeat shows the state it died in.

v4.7: NALOX LEARNS + GETS ITS ICON — the greeting, briefing,
reminders and brain replies address him by his LEARNED form of
address (memory_store.address_name — "call me Sir" persists in
prefs.json; boot posts one "[prefs] call me: ... | language:
..." line), and the process claims the Windows taskbar identity
"Nalox.Assistant" (SetCurrentProcessExplicitAppUserModelID,
before the HUD exists) so its taskbar button wears the logo
(assets/logo.ico — created as a shortcut by create_shortcut.py,
which UPDATE.bat runs; see hud.py for the window icon).

v4.7 ALWAYS-ON (same pack, Arjun's 11:35 IST demand — "Nalox
should always be there"): the HUD's X button only HIDES the
window (it already did — see hud.py); the tray icon (tray.py)
is its permanent home with Open/Restart/Exit; a single-instance
lock (nalox.lock) + show_request.flag poller means re-launching
Nalox (e.g. the Desktop shortcut) brings the running window
forward instead of starting a second copy; and a deliberate
exit (tray Exit / HUD Exit button) writes
exit_requested.flag, which supervisor.py honours — crashes and
kills are relaunched, deliberate exits are not. Restarts never
write the flag. (v5.4: a voice "stop" is no longer a deliberate
exit at all — see the Exit paths note above.)

v5.4: WAKE LINE — the wake acknowledgement is Arjun's chosen
line (config wake_line, default "Yes Sir, I'm here." since
v5.7 — the v5.4 line was "Yes Sir, I'm coming for you."),
computed by _wake_ack() and spoken through the main
loop's single say(ack) on both wake paths (bare wake and
"wake up"). The boot greeting is unchanged. Phone control
lives in brain.py / phone_control.py and needs nothing here.

v5.5: COMMAND CENTER — "Nalox, wake up" now opens the
fullscreen dashboard (dashboard.py: blue particle orb, SYSTEM
panel, live CHAT) instead of just showing the normal window;
the tray/show-request paths still show the normal window. If
the dashboard can't open, wake-up falls back to the window,
then to the show flag — it can never break the wake path.
Voice "open/close the dashboard" arrives as brain actions
"dashboard_open"/"dashboard_close", handled in run_command.
(v6.2 supersedes the fallback chain — see below.)

v6.2: THE COMMAND CENTER IS THE SURFACE + SELF-UPDATE.
The owner's sharpened orders (2026-11-15, restated twice):
(1) EVERY start lands on the Command Center — autostart,
manual launch, post-update restart — opened once boot
completes (the "START SURFACE" block in main); the plain
window is built WITHDRAWN (hud.py) and no start path ever
shows it. (2) "Wake up Nalox" opens ONLY the Command
Center, from any state: _show_for_wake_up is dashboard-
only now (no window substitution, no show flag), and
_open_dashboard hides the plain window when the Center
opens over it. The duplicate-launch show signal routes
dashboard-first too; the tray's "Open Nalox" item remains
as the diagnostics path to the plain window. The Command
Center's own top bar carries ⚙ Settings + 📋 Log (the
HUD's own handlers), so nothing he needs lives only on
the plain window. (3) Nalox UPDATES ITSELF from his
private GitHub repo (updater.py; Settings → Updates holds
repo + token): boot + 30-min checks (v7.2; 6-hourly
through v7.1), UPDATE.bat-parity
apply, restart via the supervisor, and a one-time spoken
"I have updated myself to version X.Y, sir." from the
updated_to.txt marker popped below. (4) All local
transcription lives in a worker PROCESS with hard
deadlines (ears.py) — the mid-command wedges are gone.

v5.5.1: COMMAND CENTER FIX — the v5.5 dashboard owned a
second Tk interpreter on its own thread and never opened on
Arjun's Windows laptop (field log 2026-11-15 14:17 IST: a
flood of "[dashboard] Command Center did not open" lines,
the real exception nowhere). The dashboard is now a
Toplevel hosted on the HUD's root/thread (attach()), every
failure logs the real exception once per attempt with a
cooldown against retry storms, and _open_dashboard adds at
most one companion line per distinct failure — with the
caller chain attached, so any mystery caller names itself.

v9.0 — TEXT-FIRST (the owner's architecture order,
2026-11-16 19:40 IST): the ears are REMOVED. No wake word,
no always-on listening, no local Whisper worker fleet —
ears.py is deleted and nothing at runtime loads a local
speech model. Nalox reads TEXT: typed in the windows'
input rows, sent from Telegram, or produced by ONE-SHOT
DICTATION (dictation.py — mic button / global hotkey /
armed windows; cloud transcription, Groq Whisper first).
The main loop is an input-queue consumer; every item is
handled exactly like a Telegram message. Voice REPLIES
are unchanged (the TTS chain never depended on the ears).
"""
import inspect
import logging
import os
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        RotatingFileHandler(os.path.join(LOG_DIR, "nalox.log"),
                            maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nalox")

CLEAN_EXIT_CODE = 42
# v6.0: a launch that finds a live Nalox already running
# exits with THIS code — never 42. 42 means "deliberate
# exit, supervisor stop"; a duplicate launch is not one,
# and the v5.8 field deaths came from exactly that
# confusion (a stale lock claim exiting 42 after a crash
# relaunch, read by the supervisor as a deliberate exit).
ALREADY_RUNNING_CODE = 43

from config import CONFIG                     # noqa: E402
# v9.0: ears.py is DELETED (text-first order) — dictation.py
# is the only hearing left, and it is one-shot + cloud-only.
import dictation as _dictation_mod             # noqa: E402
from dictation import Dictation                # noqa: E402
from voice import Speaker                      # noqa: E402
import voice as _voice_mod                     # noqa: E402  (barge-in stop)
import logbook                                 # noqa: E402  (diagnostics page)
from brain import Brain, _bn_num, _BN_WEEKDAYS, _BN_MONTHS  # noqa: E402

# v4.7: the learned-address helpers (memory_store.address_name) —
# greeting / briefing / reminders address him the way he TAUGHT
# Nalox ("call me Sir"), not always by his first name. Guarded:
# any import problem falls back to the pre-v4.7 behaviour.
try:
    from memory_store import address_name as _prefs_address
    from memory_store import address_name_bn as _prefs_address_bn
except Exception:  # pragma: no cover
    _prefs_address = None
    _prefs_address_bn = None


def _addr(cfg):
    """His preferred form of address (v4.7; default: his name)."""
    if _prefs_address is not None:
        try:
            return _prefs_address(cfg)
        except Exception:
            pass
    return cfg.get("user_name", "Arjun")


# v9.0: _wake_ack is GONE — the wake acknowledgement ("Yes
# Sir, I'm here.") retired with the wake word itself (the
# owner's text-first order). Dictation needs no spoken ack:
# the UI shows the recording state. The wake_line config key
# remains in config.py defaults, inert, so old config files
# keep loading.


def _missed_command_line(brain, cfg):
    """The spoken answer to a wake that heard NO command
    (v6.13 silent-path fix).

    The wake was acknowledged out loud — Arjun is standing
    there talking to Nalox — so an empty command listen
    must be ANSWERED, never met with silence (his
    2026-11-15 22:24 IST report: he spoke, and nothing at
    all came back). One short honest line in his reply
    language: the learned preference when there is one
    (Bengali, by his standing order), else the configured
    default language."""
    lang = None
    try:
        lang = brain._pref_lang()
    except Exception:
        lang = None
    if not lang:
        lang = str((cfg or {}).get("default_language")
                   or "bn").lower()
    if lang.startswith("hi"):
        return ("माफ़ कीजिए, मैं सुन नहीं पाया — "
                "एक बार फिर कहिए।")
    if lang.startswith("en"):
        return "Sorry, I couldn't hear that — please say it again."
    return (f"দুঃখিত {_bn_name(cfg)}, কথাটা শুনতে পাইনি — "
            "আবার একবার বলুন।")


def _set_app_user_model_id():
    """Windows taskbar identity (v4.7).

    Without an explicit AppUserModelID, a pythonw-hosted window
    groups under the generic Python icon — Arjun could not tell
    Nalox was even running. With "Nalox.Assistant" set BEFORE the
    HUD window exists, the taskbar button groups as Nalox and
    wears the window icon (assets/logo.ico, set in hud.py).
    Windows-only, fully guarded — a failure changes nothing.
    """
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.shell32 \
                .SetCurrentProcessExplicitAppUserModelID(
                    "Nalox.Assistant")
    except Exception:
        pass

# ------------------------------------------------------------ HUD (v3)
_hud = None
# v5.5: the fullscreen Command Center (dashboard.py) — created
# in main() beside the HUD; hudlog/hudstatus feed it the same
# lines and states the window gets.
_dashboard = None
# v4.6: the last UI state hudstatus() set — the heartbeat's
# "state=" field (which state Nalox was in when it hung).
_ui_state = "idle"


def _logbook_category(msg):
    """Map a HUD line to its logbook category (v4.1)."""
    if msg.startswith("NALOX:"):
        return "NALOX"
    if msg.startswith("[mic] heard:"):
        return "YOU"
    if msg.startswith("[heard]") or msg.startswith("[mic]"):
        return "MIC"
    if msg.startswith("[wake]") or msg.startswith("[barge-in]"):
        return "WAKE"
    if msg.startswith("[error]"):
        return "ERROR"
    if msg.startswith("[voice]") or msg.startswith("[speaker]"):
        return "VOICE"
    if msg.startswith("[brain]"):
        return "BRAIN"
    return "SYSTEM"


def hudlog(msg):
    """Post a line to the app window AND mirror it into the logbook.

    The logbook mirror (v4.1) is what fills nalox_log.txt /
    nalox_page.html — Arjun's diagnostics page — with the full
    conversation and every error, in plain sight.
    """
    if _hud is not None:
        try:
            _hud.post(msg)
        except Exception:
            pass
    if _dashboard is not None:
        try:
            _dashboard.post(msg)
        except Exception:
            pass
    try:
        logbook.log(_logbook_category(msg), msg)
        if msg.startswith("[mic] connected: "):
            logbook.set_status(mic=msg.split(": ", 1)[1])
        elif msg.startswith("[voice] active: "):
            logbook.set_status(voice=msg.split(": ", 1)[1])
    except Exception:
        pass


# ------------------------------------------------------------- v7.10 P4
# FIRST-INPUT BOOT DIET (v7.10: first-wake; v9.0: first
# input). Field report (owner, 2026-11-16 14:41 IST):
# after boot his speech did not get through until the
# first successful wake. The boot minute is crowded:
# brain validation, logsync's first sync, the +60 s
# updater check, and (v7.9) the male fixed-line cache
# warming, a NETWORK synthesis pass. Non-essential
# warm-up work waits behind this gate, which opens on
# the FIRST INPUT of the session (v9.0: the first typed /
# dictated / Telegram-handled turn) or
# BOOT_GATE_DEADLINE_S after boot, whichever comes
# first. Deferred in this release: the male cache
# warming (the only deferred starter — see main()).
# Audited and DELIBERATELY LEFT (FOR-AI.md v7.10):
# logsync's first sync (already ~75 s, outside the
# first minute, and it is the diagnostic channel)
# and the updater's +60 s boot check (one tiny version
# probe; it is the mechanism that self-delivered
# v7.4/v7.6/v7.8 in the field — the v7.9/v7.10
# auto-update guarantee rides on it). The gate opens
# exactly once and says so in ONE log line naming the
# trigger: "[sys] boot warm-up gate opened (first
# input)" / "(120s)".
BOOT_GATE_DEADLINE_S = 120.0
_boot_gate = threading.Event()
_boot_gate_lock = threading.Lock()
_boot_gate_opened = False


def _open_boot_gate(reason):
    """Open the first-input boot gate (v7.10, item P4;
    v9.0 trigger): release every deferred warm-up
    starter and log the opening ONCE, naming what
    opened it ("first input" or "120s"). Later calls
    are silent no-ops. Returns True only for the call
    that opened it. Never raises."""
    global _boot_gate_opened
    try:
        with _boot_gate_lock:
            if _boot_gate_opened:
                return False
            _boot_gate_opened = True
        _boot_gate.set()
        hudlog(f"[sys] boot warm-up gate opened "
               f"({reason})")
        return True
    except Exception:
        return False


def _boot_gate_timer():
    """The gate's deadline arm (v7.10, item P4): if no
    successful wake opens the gate within
    BOOT_GATE_DEADLINE_S, open it from the timer — a
    session where he never speaks still gets its
    warm-up, just late instead of never."""
    if not _boot_gate.wait(BOOT_GATE_DEADLINE_S):
        _open_boot_gate("120s")


def _after_boot_gate(fn):
    """Run fn() once the boot gate opens (v7.10, item
    P4), on a daemon thread; if the gate is already
    open it runs at once. fn's own failures are its
    own — the gate never propagates them."""
    def _run():
        _boot_gate.wait()
        try:
            fn()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True,
                     name="nalox-boot-gate").start()


# ------------------------------------------------------------- v7.11
# BOOT PROBE STAGES ("Ready Means Ready" — bootprobe.py
# runs them concurrently, loadscreen.py renders them).
# Each returns (status, detail): "ok" / "warn" / "fail"
# plus one short checklist line. Every stage wraps an
# EXISTING readiness signal — sounddevice's device pick,
# the speaker's own active-voice read, the phone link's
# local state — and the Brain's probe methods feed the
# answering machinery itself (validation state,
# persisted dead marks, reachability caches). No stage
# keeps a shadow copy of anything.
# v9.0: the four ears stages are gone with the ears; the
# mic stage now proves a microphone exists for one-shot
# dictation (dictation.pick_input_device).


def _boot_probe_mic(cfg):
    """The microphone stage: the dictation device pick
    (the v7.1 probe-and-choose, ported to dictation.py)
    + proof that at least one input device exists."""
    try:
        idx = _dictation_mod.pick_input_device(cfg)
        name = _dictation_mod._device_name(idx)
        try:
            import sounddevice as _sd
            have = any(
                (d.get("max_input_channels", 0) or 0) > 0
                for d in _sd.query_devices())
        except Exception:
            have = True  # cannot tell — do not cry wolf
        if have:
            return ("ok", name)
        return ("fail", "no microphone found")
    except Exception as exc:
        return ("warn", f"could not check "
                        f"({type(exc).__name__})")


def _boot_probe_voice(speaker):
    """The voice stage: the speaker's own active-voice
    read (the same line the boot log has always
    printed) — the engine that will speak is known
    before the greeting, not discovered by it."""
    try:
        line = speaker.describe_active()
        if line:
            return ("ok", line)
        return ("warn", "voice unknown")
    except Exception as exc:
        return ("warn", f"could not check "
                        f"({type(exc).__name__})")


def _boot_probe_phone():
    """The phone-link stage: local startup state only
    (the command server starts inside Brain.__init__;
    the phone itself being away is normal and is not
    a failure of the link)."""
    try:
        import phone_link
        if phone_link.is_connected():
            name = ""
            try:
                name = phone_link.device_name() or ""
            except Exception:
                pass
            return ("ok", "phone connected"
                    + (f": {name}" if name else ""))
        if getattr(phone_link, "_state", {}).get(
                "started"):
            return ("ok", "link server on — waiting "
                          "for the phone app")
        return ("warn", "link server not started")
    except Exception as exc:
        return ("warn", f"could not check "
                        f"({type(exc).__name__})")


def _boot_probe_telegram(holder):
    """The Telegram stage: local startup state only.
    The bridge object lands in the holder when main()
    builds it (a few hundred ms after the probe
    starts); the stage waits briefly for it, then
    reports what exists."""
    try:
        deadline = time.monotonic() + 8.0
        bridge = holder.get("bridge")
        while bridge is None \
                and time.monotonic() < deadline:
            time.sleep(0.2)
            bridge = holder.get("bridge")
        if bridge is None:
            return ("warn", "bridge not started")
        if not getattr(bridge, "token", None):
            return ("warn", "not configured")
        return ("ok", "bridge on")
    except Exception as exc:
        return ("warn", f"could not check "
                        f"({type(exc).__name__})")


# ------------------------------------------------------------- v9.0
# The v8.0 REAL-READINESS ears stages (_boot_probe_big_model,
# _boot_probe_ears_test, _boot_lanes_up, _boot_test_audio)
# are REMOVED with the ears: there is no local transcription
# model to force-load and no decode pipeline to test. The
# brain-side sibling (one real completion through the lead
# brain, Brain.probe_brain_answer_boot) stays — it is a
# brain check, not an ears check.


def hudstatus(state):
    """Set the HUD status line; no-op when the HUD is off."""
    global _ui_state
    _ui_state = str(state)
    if _hud is not None:
        try:
            _hud.set_status(state)
        except Exception:
            pass
    if _dashboard is not None:
        try:
            _dashboard.set_status(state)
        except Exception:
            pass


# ------------------------------------------- v7.0 LIVENESS WATCHDOG
# The heartbeat proves the process lives; it does not prove
# the LOOP moves. The main loop stamps its stage at every
# boundary (listening / thinking / speaking) and a
# supervisor thread checks the stamp every few seconds:
#   * "speaking" past watchdog_speaking_s (45 s) — speech
#     is cut through the EXISTING stop path (voice.stop(),
#     the same lever barge-in pulls), one logbook ERROR
#     names the stage + duration, back to listening;
#   * any other non-listening stage past watchdog_stage_s
#     (90 s) — one logbook ERROR names it. The process is
#     NEVER killed from here — restarts belong to the
#     supervisor/service layer, exit codes unchanged.
# Interventions are throttled per stage (1 per 2 min) so a
# pathological loop cannot spam the log the owner reads.
# "listening" itself is never judged here — in v9.0 it is
# the input queue's idle wait, and a quiet room (or a
# quiet keyboard) is legitimate. Pure policy + arithmetic:
# the supervisor thread in main() performs the effects, so
# this class is unit-testable with a fake clock.
# (v9.0: the v7.0 transcription-stage recovery — respawn
# the ears lane workers — is REMOVED with the ears; there
# are no workers left to respawn.)
WATCHDOG_CHECK_S = 5.0      # supervisor cadence
WATCHDOG_THROTTLE_S = 120.0  # max 1 intervention/stage/2 min


class _StageWatch:
    """Stage-stamp bookkeeping for the liveness watchdog."""

    def __init__(self, speaking_s=45.0, stage_s=90.0,
                 throttle_s=WATCHDOG_THROTTLE_S,
                 clock=time.monotonic):
        self.speaking_s = float(speaking_s)
        self.stage_s = float(stage_s)
        self.throttle_s = float(throttle_s)
        self._clock = clock
        self.stage = "listening"
        self.since = float(clock())
        self._last_action = {}

    def note(self, stage):
        """Stamp a stage boundary. Re-stamping the SAME
        stage also refreshes the clock — each follow-up
        listen_for_command is a fresh attempt, not a
        continuation of the previous one's stall."""
        self.stage = str(stage)
        self.since = float(self._clock())

    def check(self, now=None):
        """(stage, age_s) when an intervention is due, else
        None. On a due intervention the stamp resets to
        "listening" (the loop re-stamps as it moves) and
        the stage's throttle starts — the caller performs
        the stage's recovery effect exactly once."""
        if now is None:
            now = float(self._clock())
        else:
            now = float(now)
        stage = self.stage
        if stage == "listening":
            return None
        limit = self.speaking_s if stage == "speaking" \
            else self.stage_s
        age = now - self.since
        if age <= limit:
            return None
        if now - self._last_action.get(stage, -1e18) \
                < self.throttle_s:
            return None
        self._last_action[stage] = now
        self.stage = "listening"
        self.since = now
        return (stage, age)


# ------------------------------------------- v5.5 COMMAND CENTER
# v9.0: the live-caption preview sinks (_DashboardPreviewSink,
# _HudPreviewSink, _MultiPreviewSink) are REMOVED with the
# ears — there is no partial-transcription stream anymore.
# Dictated text appears in the input box whole, the moment
# the cloud transcription returns, and is then sent.


# ------------------------------------------------------------- v9.0
# UI INPUT DELEGATES. The windows (Command Center + plain
# window) are created lazily and never import nalox.py;
# main() installs the real handlers here and each surface
# wires its input row to these delegates the moment it
# exists. A surface built before main() installs the
# handlers simply drops the input (boot is seconds; the
# handlers land before the gate opens).
_input_submit_fn = None
_mic_trigger_fn = None
_arm_dictation_fn = None
# Barge-in (v9.0): set by the mic trigger while speech is
# playing; say() polls it and cuts the speech — the ears'
# monitor_interrupt replacement (there is no second stream
# anymore; the trigger IS the interrupt).
_barge_event = threading.Event()


def _ui_text_submit(text):
    """A window's input row was submitted (v9.0)."""
    fn = _input_submit_fn
    if fn is not None:
        try:
            fn(text)
        except Exception:
            pass


def _ui_mic_press():
    """A window's mic button was pressed (v9.0)."""
    fn = _mic_trigger_fn
    if fn is not None:
        try:
            fn()
        except Exception:
            pass


# v5.5.1: the last companion line _open_dashboard logged, keyed
# by the dashboard's failure text — a repeated failure with the
# SAME cause never earns a second line (the dashboard itself
# already logged the real exception, once per attempt).
_dash_logged_error = None


def _open_dashboard():
    """Show the fullscreen Command Center. True only if it
    really came up. Never raises.

    v5.5.1: dashboard.py logs the REAL exception itself, once
    per attempt, and debounces repeat attempts (cooldown), so
    this function's old per-call "[dashboard] Command Center
    did not open" line — the one that flooded Arjun's log
    ~20x in 3 s on 2026-11-15 — is now a companion line logged
    AT MOST ONCE per distinct failure, with the caller chain
    attached so any mystery caller names itself in the log.

    v6.2: on success the PLAIN WINDOW HIDES — the Command
    Center is the surface now; if Arjun had the app window
    open, opening the Center puts it away (the sharpened
    wake/start rule: the plain window never shares the
    screen with the Center, and never substitutes for it).
    """
    global _dashboard, _dash_logged_error
    try:
        if _dashboard is None:
            from dashboard import Dashboard
            _dashboard = Dashboard(CONFIG)
            if _hud is not None:
                _dashboard.attach(_hud)
            _dashboard.start()
            # v9.0: wire the input row (typed text + mic
            # button) to the main loop's delegates.
            _dashboard.on_text_submit = _ui_text_submit
            _dashboard.on_mic_press = _ui_mic_press
        if _dashboard.show():
            try:
                _hide = getattr(_hud, "hide", None)
                if callable(_hide):
                    _hide()
            except Exception:
                pass
            return True
        err = getattr(_dashboard, "last_error", "") or "unknown"
        if err != _dash_logged_error:
            _dash_logged_error = err
            chain = []
            try:
                frame = inspect.currentframe()
                if frame is not None:
                    frame = frame.f_back
                while frame is not None and len(chain) < 4:
                    chain.append(frame.f_code.co_name)
                    frame = frame.f_back
            except Exception:
                pass
            logbook.log("ERROR", "[dashboard] Command Center did "
                                 "not open (via "
                                 + (" <- ".join(chain) or "?")
                                 + ")")
        return False
    except Exception as exc:
        try:
            logbook.log("ERROR", f"[dashboard] open failed: "
                                 f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        log.warning("Command Center open failed: %s", exc)
        return False


def _close_dashboard():
    """Hide the Command Center (voice "dashboard_close")."""
    try:
        if _dashboard is not None:
            _dashboard.hide()
    except Exception:
        pass


def _step_aside_for_open():
    """v5.7 STEP ASIDE: registered into actions.py at startup.

    When an open action (app / folder / URL) executes while
    the Command Center is up, the dashboard hides itself
    FIRST — the opened app then lands in front of a clear
    desktop instead of behind the fullscreen dashboard (the
    owner's 14:38 complaint). The dashboard global is read
    live, so the lazy creation in _open_dashboard is covered
    too. Never raises."""
    try:
        if _dashboard is not None and _dashboard.is_visible():
            _dashboard.hide()
    except Exception:
        pass


def _show_for_wake_up():
    """v5.5 wake-up routing: the Command Center.
    v6.2 (the owner's sharpened rule, restated twice): wake
    up opens ONLY the Command Center — the plain window is
    never shown on this path, never substituted on failure,
    and the show flag is not written (its poller is a
    start-surface path of its own now). If the Center can't
    open, the failure is already logged by _open_dashboard.
    v9.0: the wake WORD is gone, but "open the Command
    Center" (voice/typed/Telegram/UI) still lands here —
    and a successful open ARMS one dictation, so he can
    simply start talking (the v9.0 auto-arm). Never
    raises."""
    ok = _open_dashboard()
    if ok and _arm_dictation_fn is not None:
        try:
            _arm_dictation_fn()
        except Exception:
            pass
    return ok


# ---------------------------------------------------- v4.7 ALWAYS-ON
# Single-instance lock + show signal + deliberate-exit flag. All
# stdlib, all guarded: none of this may ever stop Nalox starting.
LOCK_FILE = os.path.join(BASE_DIR, "nalox.lock")
SHOW_FLAG_FILE = os.path.join(BASE_DIR, "show_request.flag")
EXIT_FLAG_FILE = os.path.join(BASE_DIR, "exit_requested.flag")

# v5.2: native-crash evidence. faulthandler (stdlib) writes a
# Python traceback here if the process dies in NATIVE code
# (a segfault inside ctranslate2 / PortAudio / a ctypes call) —
# the v5.1 field failure died exactly that way: log silent,
# no Python error, supervisor relaunching a corpse. Deliberate
# exits append a CLEAN EXIT marker line to the same file (see
# _mark_clean_exit), so "marker present" vs "fault traceback
# with no marker after it" distinguishes a shutdown Arjun
# asked for from a crash he didn't.
FAULT_LOG_FILE = os.path.join(BASE_DIR, "nalox_fault.log")
_fault_file_handle = None


def _enable_faulthandler():
    """Point stdlib faulthandler at nalox_fault.log (guarded —
    diagnostics must never stop Nalox starting)."""
    global _fault_file_handle
    try:
        import faulthandler
        _fault_file_handle = open(FAULT_LOG_FILE, "a",
                                  encoding="utf-8")
        _fault_file_handle.write(
            f"\n===== Nalox boot {time.strftime('%Y-%m-%d %H:%M:%S')}"
            " — faulthandler armed =====\n")
        _fault_file_handle.flush()
        faulthandler.enable(file=_fault_file_handle,
                            all_threads=True)
        log.info("faulthandler armed -> %s", FAULT_LOG_FILE)
    except Exception as exc:
        log.warning("faulthandler could not be armed: %s", exc)


def _mark_clean_exit(reason):
    """Append the CLEAN EXIT marker to nalox_fault.log.

    Written on every deliberate way down (voice/tray exit via
    _write_exit_flag, self-restart via _restart_process). A
    crash leaves NO marker after its traceback — that absence
    is the evidence."""
    try:
        with open(FAULT_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"===== CLEAN EXIT {time.strftime('%Y-%m-%d %H:%M:%S')}"
                     f" — {reason} =====\n")
    except Exception:
        pass


def _pid_alive(pid):
    """True if a process with this pid exists (guarded).

    v6.0: kept as a diagnostic helper only — the single-
    instance claim below no longer decides anything with it
    (a dead pid can answer OpenProcess while its process
    object lingers, and Windows reuses pids; both made this
    return True for a corpse). Prototypes are declared now:
    the undeclared restype truncated 64-bit handles to c_int.
    """
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        if sys.platform.startswith("win"):
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [
                ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(
                0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


# v6.0: the single-instance claim is an OS-HELD exclusive
# lock on nalox.lock (msvcrt.locking on Windows, flock on
# POSIX), held open for the process's whole life. The v4.7
# design trusted a PID written into the file plus the
# _pid_alive guess above — and a crashed child's PID can
# still answer OpenProcess while its process object lingers
# (the supervisor itself holds a handle through its Popen
# object) or after Windows reuses the PID, so every later
# launch "saw" a live instance, exited with code 42, and
# the supervisor read that as a deliberate exit and stopped
# for good (field, 2026-11-15: the 15:06:18 instant-42
# after the crash relaunch, then every manual start at
# 15:26-15:30). An OS lock cannot go stale: the kernel
# releases it the moment the holder dies, however it dies.
# The PID is still written into the file — as information
# for humans, never as the decision.
_instance_lock_handle = None
# v6.0: the pid of the current lock holder, recorded by the
# claim for the boot-exit log line (a wedged holder must be
# identifiable from the log page alone).
_last_holder_pid = None


def _try_lock_file(fh):
    """One non-blocking exclusive OS lock attempt on an open
    file handle. True when THIS handle now holds the lock."""
    try:
        if sys.platform.startswith("win"):
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:
        return False


def _adopt_lock(fh):
    """Record this process as the lock holder (PID is written
    for humans only) and keep the handle open for life."""
    global _instance_lock_handle
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _instance_lock_handle = fh


def _read_holder_pid():
    """The PID recorded in LOCK_FILE by its holder. Purely
    informational (the OS lock is the decision, never the
    PID). None when unreadable."""
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as fh:
            return int((fh.read() or "").strip() or 0) or None
    except Exception:
        return None


def _terminate_pid(pid):
    """Best-effort hard stop of ONE pid — used only to clear
    a WEDGED lock holder before a takeover. Guarded: never
    our own pid, never a nonsense value. Never raises."""
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if sys.platform.startswith("win"):
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [
                ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.TerminateProcess.argtypes = [
                ctypes.c_void_p, ctypes.c_uint]
            handle = kernel32.OpenProcess(0x0001, False, pid)
            if not handle:
                return False
            try:
                return bool(kernel32.TerminateProcess(handle, 1))
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
        import signal as _signal
        os.kill(pid, _signal.SIGKILL)
        return True
    except Exception:
        return False


SHOW_ACK_SECONDS = 3.0


def _claim_single_instance():
    """v6.0: True if THIS process should run.

    Layer 1 — the OS lock (see the note above _try_lock_file):
    a free lock is claimed and we run; a DEAD holder can
    never block this, because the kernel released its lock
    with the process. The v5.8 veto (a stale PID trusted via
    OpenProcess, then a silent exit 42) is gone: the PID in
    the file is never the decision.

    Layer 2 — the lock is HELD, so a process exists. Live is
    not the same as WORKING (the field failure was launches
    dying against an instance that never showed a window),
    so the holder must prove it is responsive: write
    show_request.flag and give its poller SHOW_ACK_SECONDS
    to CONSUME it (the poller deletes the flag within ~1 s
    and brings the window forward). Consumed → a responsive
    instance is running: return False; the caller exits with
    ALREADY_RUNNING_CODE (43) after logging the reason.
    NOT consumed → the holder is wedged: log the takeover,
    terminate the PID recorded in the lock file, wait for
    the OS lock to free, claim it and run. If the lock still
    will not free, return False (exit 43, reason logged by
    the caller) — a start is never vetoed silently, and
    never with code 42. Any unexpected failure inside the
    claim machinery returns True: the lock must never be
    the reason Nalox doesn't start."""
    global _instance_lock_handle, _last_holder_pid
    try:
        fh = open(LOCK_FILE, "a+")
    except Exception:
        return True
    if _try_lock_file(fh):
        _adopt_lock(fh)
        return True
    # The lock is held by a live process — responsiveness
    # check via the show signal.
    holder_pid = _read_holder_pid()
    _last_holder_pid = holder_pid
    wrote = False
    try:
        with open(SHOW_FLAG_FILE, "w", encoding="utf-8") as sf:
            sf.write("show\n")
        wrote = True
    except Exception:
        pass
    if not wrote:
        # Could not even signal — never kill on uncertain
        # evidence; stand down (43, logged by the caller).
        try:
            fh.close()
        except Exception:
            pass
        return False
    deadline = time.time() + SHOW_ACK_SECONDS
    acked = False
    while time.time() < deadline:
        if not os.path.exists(SHOW_FLAG_FILE):
            acked = True
            break
        time.sleep(0.25)
    if acked:
        log.info("Another Nalox instance (pid %s) is running "
                 "and answered the show signal.",
                 holder_pid)
        try:
            fh.close()
        except Exception:
            pass
        return False
    # Wedged holder — take over.
    log.warning("Lock holder (pid %s) did not answer the show "
                "signal within %.0fs — treating it as wedged "
                "and taking over.", holder_pid, SHOW_ACK_SECONDS)
    try:
        import logbook
        logbook.log("SYSTEM",
                    "[sys] the previous Nalox instance (pid "
                    f"{holder_pid}) was not responding — this "
                    "start is taking over from it.")
    except Exception:
        pass
    if holder_pid:
        _terminate_pid(holder_pid)
    give_up = time.time() + 3.0
    while time.time() < give_up:
        if _try_lock_file(fh):
            _adopt_lock(fh)
            return True
        time.sleep(0.25)
    try:
        fh.close()
    except Exception:
        pass
    return False


def _write_exit_flag():
    """Mark a DELIBERATE exit so the supervisor does not
    relaunch. Since v5.4 the only voice path that lands here
    is a CONFIRMED PC shutdown/restart (the machine itself is
    going down) — a plain voice/Telegram "stop" is standby
    and never exits. Tray/HUD exits write the same flag
    themselves. Restart paths never call this."""
    _mark_clean_exit("deliberate exit (pc shutdown/restart)")
    try:
        with open(EXIT_FLAG_FILE, "w", encoding="utf-8") as fh:
            fh.write("exit requested by voice\n")
    except Exception:
        pass


def _clear_exit_flag():
    """A fresh (manual) launch clears any stale deliberate-exit
    flag, per the supervisor's contract. v6.0: the removal is
    logged — a stale flag is evidence, not a silent event."""
    try:
        if os.path.exists(EXIT_FLAG_FILE):
            os.remove(EXIT_FLAG_FILE)
            log.info("Cleared a stale deliberate-exit flag at boot "
                     "(a fresh launch always runs).")
    except Exception:
        pass


def _restart_process():
    """Restart Nalox itself (v4.6) — the one remedy for a hang.

    Shared by the HUD's 🔄 Restart button (via hud.on_restart)
    and the voice command "Nalox, restart" (brain action
    "restart", whose spoken reply has already been delivered by
    the time this runs). Posts the feed line, then exits with
    code 1 on a short timer so the line (and any speech) lands
    first; the supervisor relaunches a fresh process. If the
    timer path somehow fails, fall back to a direct os._exit(1).
    """
    try:
        hudlog("Restarting Nalox…")
    except Exception:
        pass
    # v7.7: no speech may be mid-flight when the process
    # exits — a SAPI call in another thread (Telegram) was
    # in the voice layer when the 2026-11-16 self-update
    # restart died with exit code 1.
    try:
        _voice_mod.stop_for_exit()
    except Exception:
        pass
    _mark_clean_exit("self-restart (supervisor relaunches)")
    log.info("Restarting Nalox (exit code 1 — supervisor relaunches).")

    def _die():
        try:
            os._exit(1)
        except Exception:
            pass

    try:
        threading.Timer(0.6, _die).start()
    except Exception:
        _die()


def _bn_name(cfg):
    # v4.7: the Bengali form of his PREFERRED address (অর্জুন only
    # while the address is his real name; a learned "Sir"/"স্যার"
    # is used verbatim — it is what he asked to be called).
    if _prefs_address_bn is not None:
        try:
            return _prefs_address_bn(cfg)
        except Exception:
            pass
    return "অর্জুন" if cfg.get("user_name") == "Arjun" else cfg.get("user_name", "")


def greeting(cfg, lang=None):
    """The boot greeting, in the language Arjun actually
    talks to Nalox in (v6.5).

    Until v6.4 this keyed off config default_language alone,
    so a Bengali learned preference still booted in English
    (field screenshot 2026-11-15 18:54 IST). Now the caller
    passes the LEARNED preference (brain._pref_lang()) as
    lang; default_language is only the fallback. The wake
    line is NOT this function's business — "Yes Sir, I'm
    here." is his chosen line and never changes."""
    hour = datetime.now().hour
    name = _addr(cfg)
    lang = (lang or cfg.get("default_language")
            or "en").lower()
    if lang.startswith("bn"):
        if hour < 12:
            part = "শুভ সকাল"
        elif hour < 17:
            part = "শুভ বিকেল"
        else:
            part = "শুভ সন্ধ্যা"
        return (f"{part}, {_bn_name(cfg)}! আমি "
                f"{cfg['assistant_name']}। কেমন আছেন? "
                "আজ কী করতে পারি?")
    if lang.startswith("hi"):
        if hour < 12:
            part = "शुभ प्रभात"
        elif hour < 17:
            part = "शुभ दोपहर"
        else:
            part = "शुभ संध्या"
        return (f"{part}, {name}! मैं {cfg['assistant_name']} हूँ। "
                "आप कैसे हैं? आज मैं आपकी क्या मदद कर सकता हूँ?")
    if hour < 12:
        part = "Good morning"
    elif hour < 17:
        part = "Good afternoon"
    else:
        part = "Good evening"
    return (f"{part}, {name}! Hi {name}, how are you? "
            f"I'm {cfg['assistant_name']}. How can I help you today?")


# ------------------------------------------------- morning briefing (v3)
def _battery_percent():
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is not None:
            return int(batt.percent)
    except Exception:
        pass
    return None


def fetch_headlines(limit=3):
    """Top headlines from Google News RSS (India, English). [] on failure."""
    try:
        import requests
        import xml.etree.ElementTree as ET
        resp = requests.get(
            "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
            timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if title:
                titles.append(title.rsplit(" - ", 1)[0])  # drop the source
            if len(titles) >= limit:
                break
        return titles
    except Exception as exc:
        log.info("Headlines skipped: %s", exc)
        return []


def morning_briefing(cfg, speaker):
    """One short spoken line: day/date + time + battery.

    Headlines follow ONLY when briefing_news is on — v4.1 default
    OFF (Arjun: no news at boot; news only when he asks for it).
    """
    if not cfg.get("morning_briefing", True):
        return
    bn = (cfg.get("default_language") or "en").lower().startswith("bn")
    now = datetime.now()
    pct = _battery_percent()
    if bn:
        hour12 = now.hour % 12 or 12
        if now.hour < 4:
            part = "রাত"
        elif now.hour < 12:
            part = "সকাল"
        elif now.hour < 16:
            part = "দুপুর"
        elif now.hour < 19:
            part = "বিকেল"
        else:
            part = "রাত"
        line = (f"আজ {_BN_WEEKDAYS[now.weekday()]}, {_bn_num(now.day)} "
                f"{_BN_MONTHS[now.month - 1]}। এখন {part} "
                f"{_bn_num(hour12)}টা বেজে {_bn_num(f'{now.minute:02d}')} মিনিট।")
        if pct is not None:
            line += f" ব্যাটারি {_bn_num(pct)} শতাংশ আছে।"
    else:
        line = (f"Today is {now.strftime('%A')}, {now.day} "
                f"{now.strftime('%B')}, "
                f"{now.strftime('%I:%M %p').lstrip('0')}.")
        if pct is not None:
            line += f" Battery is at {pct} percent."
    hudlog("[briefing] " + line)
    speaker.say(line, lang="bn" if bn else "en")
    log.info("Morning briefing spoken.")
    # Headlines ride along ONLY when briefing_news is on (v4.1:
    # default off — news is spoken when Arjun asks, not at boot).
    if cfg.get("briefing_news", False):
        titles = fetch_headlines(3)
        if titles:
            intro = "আজকের বড় খবর: " if bn else "Top news: "
            news = intro + " ".join(
                f"{i + 1}. {t}." for i, t in enumerate(titles))
            hudlog("[news] " + news)
            speaker.say(news, lang="bn" if bn else "en")


def startup_youtube_check(cfg, speaker):
    """v2: right after the greeting, open Arjun's YouTube channel +
    YouTube Studio in HIS default browser and say what's happening."""
    if not cfg.get("startup_youtube_check", True):
        return
    bn = (cfg.get("default_language") or "en").lower().startswith("bn")
    try:
        speaker.say(
            "অবশ্যই — আমি এখনই তোমার ইউটিউব চ্যানেলটা চেক করছি। "
            "তোমার browser-এ খুলে দিচ্ছি।"
            if bn else
            "Sure — I'm checking your YouTube channel now. "
            "Opening it in your browser.",
            lang="bn" if bn else "en")
        webbrowser.open(cfg.get("youtube_channel_url",
                                "https://www.youtube.com/@MNYIntelligence"))
        webbrowser.open("https://studio.youtube.com")
        hudlog("[sys] startup YouTube check: channel + Studio opened")
        log.info("Startup YouTube check: channel + Studio opened.")
    except Exception as exc:
        log.warning("Startup YouTube check failed: %s", exc)


# ------------------------------------------------------- reminders (v3)
def _probe_stage_icon(status):
    """One stage's mark for the boot-probe detail line
    (v8.1): ✓ ready, ⚠ still warming / warning, ✗ failed."""
    return {"ok": "✓", "warn": "⚠", "fail": "✗"}.get(
        status, "⚠")


def _boot_probe_detail_line(probe):
    """ONE line naming EVERY boot-probe stage's outcome
    + detail (v8.1): "[sys] boot probe detail: mic ✓ …;
    Ears running test ✗ <reason>; …". The v8.0 gate
    verdict named the FAILED stages but never their
    REASONS — the stage functions' detail strings lived
    only on the loading screen, so a synced log could
    not say WHY "Ears running test" failed. Reasons here
    are the stages' own detail strings, verbatim."""
    try:
        snap = probe.snapshot()
    except Exception:
        return None
    if not snap:
        return None
    parts = []
    for s in snap:
        icon = _probe_stage_icon(s.get("status"))
        detail = str(s.get("detail") or "").strip()
        if s.get("capped") and not s.get("resolved"):
            detail = (detail + " " if detail else "") \
                + "(still warming)"
        parts.append(f"{s.get('label')} {icon}"
                     + (f" {detail}" if detail else ""))
    return "[sys] boot probe detail: " + "; ".join(parts)


def _log_boot_probe_detail(probe):
    """Write the boot-probe detail block to the logbook
    (v8.1) — once at the gate, and again from the late
    watcher when a capped stage later resolves with a
    different outcome. Logging only; never raises."""
    try:
        line = _boot_probe_detail_line(probe)
        if line:
            logbook.log("SYSTEM", line)
    except Exception:
        pass


def _boot_probe_late_watch(probe, initial_line):
    """Daemon (v8.1): after a CAPPED gate, some stages
    were still warming; when one of them later resolves
    (its outcome/detail changes), re-log the FULL detail
    block so the synced log eventually carries every
    stage's final reason. Bounded (~15 min, 5 s polls);
    exits quietly when nothing is left unresolved."""
    try:
        last = initial_line
        deadline = time.monotonic() + 900.0
        while time.monotonic() < deadline:
            time.sleep(5.0)
            try:
                snap = probe.snapshot()
            except Exception:
                return
            if all(s.get("resolved") for s in snap):
                line = _boot_probe_detail_line(probe)
                if line and line != last:
                    _log_boot_probe_detail(probe)
                return
            line = _boot_probe_detail_line(probe)
            if line and line != last:
                last = line
                _log_boot_probe_detail(probe)
    except Exception:
        pass


def _reminder_checker(store, speaker, cfg):
    """Background thread: every ~20 s, speak any reminders that are due."""
    user = _addr(cfg)
    user_bn = _bn_name(cfg)
    while True:
        time.sleep(20)
        try:
            for item in store.pop_due():
                text = item.get("text", "")
                lang = (item.get("lang") or "en").lower()
                hudlog(f"[reminder] {text}")
                hudstatus("speaking")
                if lang.startswith("bn"):
                    speaker.say(f"{user_bn}, মনে করিয়ে দিচ্ছি: {text}",
                                lang="bn")
                else:
                    speaker.say(f"{user}, reminder: {text}", lang="en")
                hudstatus("listening")
                log.info("Reminder spoken: %s", text)
        except Exception as exc:
            log.warning("Reminder checker error: %s", exc)


def main():
    global _hud, _dashboard
    global _input_submit_fn, _mic_trigger_fn, _arm_dictation_fn
    cfg = CONFIG
    # v7.11: the boot probe's hard cap is measured from
    # process start (GATE_CAP_S) — this is as close to
    # it as the process can see.
    _boot_t0 = time.monotonic()
    # v5.2: arm faulthandler FIRST — if native code kills this
    # process later (the silent v5.1 deaths), the traceback is
    # already pointed at nalox_fault.log.
    _enable_faulthandler()
    # v4.7: claim the taskbar identity BEFORE any window exists.
    _set_app_user_model_id()
    # v4.7 ALWAYS-ON: single instance. A manual launch clears any
    # stale deliberate-exit flag; if a live Nalox already holds
    # the lock, this launch just asks it to show its window (the
    # Desktop shortcut doubles as the "bring Nalox back" button)
    # and leaves quietly — v6.0: with exit code 43 (NOT 42), so
    # its supervisor stops without mistaking the duplicate for
    # a deliberate exit, and the exit flag is NOT written (the
    # running instance is untouched).
    _clear_exit_flag()
    if not _claim_single_instance():
        log.info("Nalox is already running — asked it to show its "
                 "window; this launch is closing.")
        # v6.0: a boot-time exit LOGS its reason to the logbook
        # (the page Arjun screenshots) — the v5.8 instant-42s
        # were silent here — and exits 43, not 42: a duplicate
        # launch is not a deliberate exit, and the supervisor
        # must never read it as one. The verdict names the
        # holder's pid so a wedged holder is identifiable.
        try:
            logbook.log("SYSTEM", "[sys] exiting at boot: another "
                                  "Nalox instance is already "
                                  "running (pid "
                                  f"{_last_holder_pid}) and "
                                  "answered the show signal — "
                                  "this launch is closing; the "
                                  "running instance was asked to "
                                  "show its window")
        except Exception:
            pass
        sys.exit(ALREADY_RUNNING_CODE)
    log.info("=== Nalox starting for %s ===", cfg["user_name"])

    speaker = Speaker(cfg)
    # v7.3: the ElevenLabs boot re-probe runs in the
    # BACKGROUND (voice.start_boot_probe) — if last session's
    # 402 block persisted, one tiny background synthesis
    # checks whether he bought credits, while speech goes
    # straight to the working voice and never waits for it.
    try:
        speaker.start_boot_probe()
    except Exception:
        pass
    # v7.9 (item H): warm the fixed-line TTS cache with the
    # MALE Bengali edge voice in the background — the
    # Bengali greeting variants, the could-not-hear line
    # and the mic warning, spelled exactly as the greeting
    # builder and _missed_command_line compose them (the
    # cache key is the text itself). A no-op inside voice.py
    # unless Bengali-male is configured; never blocks boot.
    try:
        _bn_addr = _bn_name(cfg)
        _bn_fixed = [
            f"{_part}, {_bn_addr}! আমি "
            f"{cfg['assistant_name']}। কেমন আছেন? "
            "আজ কী করতে পারি?"
            for _part in ("শুভ সকাল", "শুভ বিকেল",
                          "শুভ সন্ধ্যা")]
        _bn_fixed.append(
            f"দুঃখিত {_bn_addr}, কথাটা শুনতে পাইনি — "
            "আবার একবার বলুন।")
        _bn_fixed.append("স্যার, মাইকে সমস্যা হচ্ছে।")
        # v7.9 (item I.3): the no-silent-work progress
        # line is a fixed line too — warmed (male) and
        # cache-served like the others.
        _bn_fixed.append("কাজটা চলছে, sir — একটু অপেক্ষা করুন।")
        # v7.10 (item P4): the warming itself is
        # DEFERRED behind the first-wake boot gate —
        # the boot minute belongs to the ears, and a
        # network synthesis pass has no business
        # competing with the first wake. It runs after
        # the first successful wake or at the 120 s
        # deadline, whichever comes first; the warming
        # code in voice.py is unchanged.
        threading.Thread(target=_boot_gate_timer,
                         daemon=True,
                         name="nalox-boot-gate-timer").start()
        _after_boot_gate(
            lambda: speaker.start_male_cache_warming(
                _bn_fixed))
    except Exception:
        pass
    # ------------------------------------------------ v9.0 INPUT
    # TEXT-FIRST: the main loop consumes an input queue.
    # Every item is (text, lang, kind, rec_s, tx_s, label)
    # and is handled exactly like a Telegram message.
    # Producers: the windows' input rows (typed), the
    # one-shot Dictation (mic button / hotkey / armed
    # windows), and a "missed" sentinel for a dictation
    # that heard speech but got nothing usable back.
    _input_q = queue.Queue()

    def _followup_s():
        try:
            return max(1.0, float(cfg.get("followup_seconds", 8)
                                  or 8))
        except Exception:
            return 8.0

    def _on_dictation_text(text, lang, source, rec_s, tx_s):
        hudlog(f"[input] dictation ({source}): {text}")
        # v9.0 brief: the dictated text is SHOWN in the
        # input box (both windows) and auto-sent — he sees
        # exactly what the brain received.
        for _win in (_dashboard, _hud):
            if _win is not None:
                try:
                    _win.set_input_text(text)
                except Exception:
                    pass
        _input_q.put((text, lang, "dictation", rec_s, tx_s,
                      f"🎙 {source}"))

    def _on_dictation_empty(had_speech):
        # He spoke but the cloud returned nothing usable:
        # the main loop speaks the could-not-hear line
        # (serialized there — never from this thread). A
        # no-speech ending (an arm that heard nothing, a
        # press with nothing said) closes silently.
        if had_speech:
            _input_q.put(("", None, "missed", 0.0, 0.0, ""))

    def _on_dictation_state(state, seconds_left):
        for _win in (_dashboard, _hud):
            if _win is not None:
                try:
                    _win.set_dictation_state(state,
                                             seconds_left)
                except Exception:
                    pass

    _mic_error_spoken = [False]

    def _on_mic_error():
        hudlog("[mic] could not open the microphone")
        if not _mic_error_spoken[0]:
            _mic_error_spoken[0] = True
            try:
                if not _voice_mod.is_speaking():
                    speaker.say("স্যার, মাইকে সমস্যা হচ্ছে।",
                                lang="bn", fixed=True)
            except Exception:
                pass

    dictation = Dictation(
        cfg,
        on_text=_on_dictation_text,
        on_empty=_on_dictation_empty,
        on_state=_on_dictation_state,
        on_mic_error=_on_mic_error)

    def _submit_text(text):
        """A typed line from a window's input row (v9.0):
        logged with its source, then queued exactly like
        a Telegram message. Typed input wins over an
        armed dictation (the arm is cancelled)."""
        text = (text or "").strip()
        if not text:
            return
        try:
            dictation.cancel()
        except Exception:
            pass
        hudlog(f"[input] text: {text}")
        _input_q.put((text, None, "typed", 0.0, 0.0,
                      "⌨ typed"))

    def _mic_trigger():
        """The mic button / global hotkey (v9.0). While
        Nalox is speaking, the press is a BARGE-IN: the
        event cuts the speech (say() polls it) and the
        dictation starts; otherwise the press toggles
        the one-shot dictation (start / finish-now)."""
        try:
            if _voice_mod.is_speaking():
                _barge_event.set()
        except Exception:
            pass
        dictation.trigger()

    def _next_input(timeout_s):
        """The next queued input item, or None on timeout
        (the confirm flow's yes/no wait)."""
        try:
            return _input_q.get(
                timeout=max(0.1, float(timeout_s)))
        except queue.Empty:
            return None

    # The windows wire themselves to these delegates.
    _input_submit_fn = _submit_text
    _mic_trigger_fn = _mic_trigger
    _arm_dictation_fn = lambda: dictation.arm_followup(
        _followup_s())

    brain = Brain(cfg, speaker)

    # v7.11 (Ready Means Ready): the BOOT PROBE starts
    # now — every stage runs concurrently from here, so
    # by the time the gate below is reached, each
    # provider/subsystem has been checked, ordered and
    # marked (the dead Gemini names are already in the
    # persisted dead set, Ollama is already started).
    # A failure to even START the probe costs nothing:
    # _boot_probe stays None and the boot proceeds
    # ungated, exactly as before v7.11.
    # v9.0: the stage set is bootprobe.STAGE_DEFS — the
    # four ears stages are gone with the ears; what
    # remains is the mic (for dictation), the brain
    # probes + the real lead answer test, voice, phone
    # and Telegram.
    _boot_probe = None
    _boot_ctx = {"bridge": None}
    try:
        import bootprobe as _bootprobe_mod
        _boot_probe = _bootprobe_mod.BootProbe()
        _boot_ctx["probe"] = _boot_probe
        _boot_probe.start_stage(
            "mic", lambda: _boot_probe_mic(cfg),
            timeout_s=10.0)
        _boot_probe.start_stage(
            "groq", lambda: brain.probe_groq_boot(),
            timeout_s=30.0)
        _boot_probe.start_stage(
            "braintest",
            lambda: brain.probe_brain_answer_boot(),
            timeout_s=30.0)
        _boot_probe.start_stage(
            "voice", lambda: _boot_probe_voice(speaker),
            timeout_s=10.0)
        _boot_probe.start_stage(
            "gemini", lambda: brain.probe_gemini_boot(),
            timeout_s=12.0)
        _boot_probe.start_stage(
            "freellm", lambda: brain.probe_freellm_boot(),
            timeout_s=8.0)
        _boot_probe.start_stage(
            "ollama", lambda: brain.probe_ollama_boot(),
            timeout_s=40.0)
        _boot_probe.start_stage(
            "muse", lambda: brain.probe_muse_boot(),
            timeout_s=10.0)
        _boot_probe.start_stage(
            "phone", _boot_probe_phone, timeout_s=6.0)
        _boot_probe.start_stage(
            "telegram",
            lambda: _boot_probe_telegram(_boot_ctx),
            timeout_s=12.0)
    except Exception as exc:
        log.warning("Boot probe failed to start: %s", exc)
        _boot_probe = None

    # v5.7 STEP ASIDE: actions.py calls this hook before every
    # open (app/folder/URL) so the Command Center hides itself
    # and the opened app comes to the FRONT (winlayout brings
    # it forward on the actions side). Registered before any
    # command can run; the hook reads the dashboard global
    # live, so registration order vs. dashboard creation does
    # not matter.
    try:
        import actions as _actions_mod
        _actions_mod.set_step_aside_hook(_step_aside_for_open)
    except Exception as exc:
        log.warning("Step-aside hook not registered: %s", exc)

    # v9.0: dictation status lines ("[mic] connected …"
    # when a dictation opens the mic) route to the
    # HUD/logbook exactly like the old ears status lines
    # did. The wake/wake-up/mic-alert callbacks are gone
    # with the wake word — a dictation that cannot open
    # the mic reports through Dictation's on_mic_error
    # (wired at construction above).
    try:
        _dictation_mod.set_status_callback(hudlog)
    except Exception as exc:
        log.warning("Dictation status callback failed: %s", exc)

    # v9.0: the GLOBAL DICTATION HOTKEY (config
    # dictation_hotkey, default Ctrl+Alt+Space) — a
    # dedicated thread owns the Windows RegisterHotKey
    # registration and its message loop (stdlib ctypes;
    # no new dependency). Any failure — a taken combo,
    # a non-Windows host — leaves the hotkey off and
    # says so once; the buttons keep working.
    def _hotkey_thread():
        try:
            spec = str(cfg.get("dictation_hotkey")
                       or "ctrl+alt+space")
            parsed = _dictation_mod.parse_hotkey(spec)
            if parsed is None:
                hudlog(f"[hotkey] dictation hotkey "
                       f"{spec!r} not understood — hotkey off")
                return
            if not sys.platform.startswith("win"):
                return
            import ctypes
            from ctypes import wintypes
            _MOD_NOREPEAT = 0x4000
            _WM_HOTKEY = 0x0312
            _user32 = ctypes.windll.user32
            if not _user32.RegisterHotKey(
                    None, 1, parsed[0] | _MOD_NOREPEAT,
                    parsed[1]):
                hudlog(f"[hotkey] could not register "
                       f"{spec} (another app may own it) "
                       f"— the mic buttons still work")
                return
            hudlog(f"[hotkey] dictation hotkey live: {spec}")
            _msg = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(_msg),
                                      None, 0, 0) > 0:
                if _msg.message == _WM_HOTKEY:
                    _mic_trigger()
        except Exception as exc:
            log.warning("Hotkey thread failed: %s", exc)

    threading.Thread(target=_hotkey_thread, daemon=True,
                     name="nalox-hotkey").start()

    # Hacker console HUD (v3) — optional, never fatal.
    if cfg.get("show_hud", True):
        try:
            from hud import Hud
            _hud = Hud(cfg)
            _hud.start()
            brain.hud = _hud
            # v4.6: the 🔄 Restart button calls this — the HUD
            # itself never imports nalox.py.
            _hud.on_restart = _restart_process
            # v9.0: the plain window's input row (typed
            # text + mic button) routes to the delegates.
            _hud.on_text_submit = _ui_text_submit
            _hud.on_mic_press = _ui_mic_press
            hudlog(f"> user: {cfg['user_name']} | lang: "
                   f"{cfg.get('default_language', 'en')}")
        except Exception as exc:
            log.warning("HUD failed to start: %s", exc)
            _hud = None

    # Command Center (v5.5) — the fullscreen dashboard behind
    # "Nalox, wake up". Created beside the HUD, started lazily
    # by _open_dashboard; a failure here only costs the
    # showpiece, never the assistant. The HUD's 🖥 button and
    # the tray item route through the same helper.
    # v5.5.1: the dashboard is a Toplevel hosted on the HUD's
    # own Tk root/thread (attach) — it owns no interpreter —
    # so it exists only when the app window does.
    if cfg.get("show_hud", True) and cfg.get("command_center", True) \
            and _hud is not None:
        try:
            from dashboard import Dashboard
            _dashboard = Dashboard(cfg)
            _dashboard.attach(_hud)
            _dashboard.start()
            _hud.on_command_center = _open_dashboard
            hudlog("[sys] Command Center ready")
        except Exception as exc:
            log.warning("Command Center failed to start: %s", exc)
            _dashboard = None
    elif cfg.get("command_center", True):
        log.warning("Command Center skipped: no app window to "
                    "host it (the dashboard lives in the app "
                    "window's screen).")

    # v7.11: the LOADING SCREEN — up over the rest of
    # the boot, rendering the probe's checklist live;
    # the gate (at the start-surface block below)
    # closes it the moment the interface may open. It
    # hosts on the HUD like the Command Center; with no
    # app window there is no screen, and the probe +
    # gate still run (the readiness is the point — the
    # window is its display). A failure here only costs
    # the display: _load_screen stays None and the gate
    # simply has nothing to close.
    _load_screen = None
    if _boot_probe is not None and _hud is not None:
        try:
            from loadscreen import LoadingScreen
            _load_screen = LoadingScreen(cfg)
            _load_screen.attach(_hud)
            _load_screen.bind_probe(_boot_probe)
            _load_screen.start()
        except Exception as exc:
            log.warning("Loading screen failed to "
                        "start: %s", exc)
            _load_screen = None

    # Brain status line in the HUD header (v4.8): pushed now and
    # refreshed every few seconds, so when the boot key check
    # lands — or a hot-reloaded key changes the state — the
    # header (and the logbook page header) flip from "checking…"
    # to the truth on their own.
    if _hud is not None:
        try:
            _hud.set_brain(brain.brain_status_line())
        except Exception:
            pass
        if _dashboard is not None:
            try:
                _dashboard.set_brain(brain.brain_status_line())
            except Exception:
                pass

        def _brain_line_refresher():
            while True:
                time.sleep(5)
                try:
                    _line = brain.brain_status_line()
                    _hud.set_brain(_line)
                    logbook.set_status(brain=_line)
                    if _dashboard is not None:
                        _dashboard.set_brain(_line)
                except Exception:
                    pass

        threading.Thread(target=_brain_line_refresher, daemon=True,
                         name="nalox-brain-line").start()

    # Which voice will speak (v3.5) — posted AFTER the HUD is up so
    # Arjun actually sees it in the console at boot.
    active_voice = "unknown"
    try:
        active_voice = speaker.describe_active()
        hudlog("[voice] active: " + active_voice)
        log.info("Active voice: %s", active_voice)
    except Exception as exc:
        log.warning("Could not describe the active voice: %s", exc)

    # Which brain is live (v4.8) — asked from the Brain itself
    # (brain_status_line): Claude when its key is set, else Groq
    # / OpenAI with the key's live state, else Ollama, else
    # local. The v4.0–v4.7 line printed "Claude connected" for
    # any non-empty Anthropic field and "local/free mode"
    # otherwise — never validated — so a Groq key pasted into
    # the Claude field looked exactly like a working Claude
    # (Arjun's 11:55 log page). The refresher above keeps the
    # HUD/logbook line current once validation lands.
    try:
        _brain_line = brain.brain_status_line()
    except Exception:
        _brain_line = "Brain: Local — no key"
    hudlog("[brain] " + _brain_line)
    log.info("Agent brain: %s", _brain_line)

    # Learned preferences in effect (v4.7) — one boot line, so a
    # screenshot shows at a glance how Nalox will address him and
    # in which language it will answer.
    try:
        hudlog(f"[prefs] call me: {_addr(cfg)} | language: "
               f"{brain._pref_lang() or 'auto'}")
    except Exception:
        pass

    # Logbook boot snapshot (v4.1): fill the diagnostics page header
    # and record one SYSTEM line with everything a screenshot needs —
    # version, mic, speaker output (the first suspect when Nalox
    # "speaks" but nothing is heard), voice, brain, robot flag.
    try:
        version = "?"
        try:
            with open(os.path.join(BASE_DIR, "version.txt"),
                      encoding="utf-8") as vf:
                version = vf.read().strip() or "?"
        except Exception:
            pass
        mic_name = "unknown"
        try:
            mic_name = _dictation_mod._device_name(
                _dictation_mod.pick_input_device(cfg))
        except Exception:
            pass
        out_name = speaker.output_device_name()
        # v4.8: the logbook header shows the same brain truth as
        # the HUD (refreshed as validation lands) — the v4.0–v4.7
        # header claimed "Claude (Anthropic)" for a merely-present
        # key.
        try:
            brain_name = brain.brain_status_line()
        except Exception:
            brain_name = "unknown"
        robot_name = "on" if speaker.robot_on() else "off"
        try:
            import skillfiles as _skillfiles
            _skills_n = str(_skillfiles.count_skills())
        except Exception:
            _skills_n = "0"
        logbook.set_status(version="v" + version, mic=mic_name,
                           output=out_name, voice=active_voice,
                           brain=brain_name, robot=robot_name,
                           skills=_skills_n)
        hudlog(f"[speaker] output: {out_name}")
        logbook.log(
            "SYSTEM",
            f"Nalox v{version} started | mic: {mic_name} | "
            f"output: {out_name} | voice: {active_voice} | "
            f"brain: {brain_name} | robot: {robot_name} | "
            f"briefing_news: {bool(cfg.get('briefing_news'))} | "
            f"full_control: {bool(cfg.get('full_control', True))}")
    except Exception as exc:
        log.warning("Logbook boot snapshot failed: %s", exc)

    # Reminders (v3): shared store; brain adds, the checker thread speaks.
    try:
        from reminders import ReminderStore
        store = ReminderStore()
        brain.reminders = store
        t = threading.Thread(target=_reminder_checker,
                             args=(store, speaker, cfg),
                             daemon=True, name="reminders")
        t.start()
        log.info("Reminder checker started (%d pending).", len(store))
    except Exception as exc:
        log.warning("Reminders failed to start: %s", exc)

    # Scheduled action tasks (v4.3): a checker thread ticks every
    # ~30 s; due tasks run their action and the result is delivered
    # on the task's channel (voice and/or Telegram).
    try:
        import scheduler as _scheduler_mod

        def _deliver_scheduled(text, channel):
            hudlog("[scheduled] " + text)
            if channel in ("speak", "both"):
                try:
                    speaker.say(text, lang="en")
                except Exception:
                    pass
            if channel in ("telegram", "both"):
                try:
                    import telegram_bridge
                    telegram_bridge.send_message(cfg, text)
                except Exception:
                    pass

        def _scheduler_checker():
            while True:
                try:
                    _scheduler_mod.run_due_tasks(
                        cfg, brain, _deliver_scheduled)
                except Exception as exc:
                    log.warning("Scheduler tick failed: %s", exc)
                time.sleep(30)

        threading.Thread(target=_scheduler_checker, daemon=True,
                         name="scheduler").start()
        log.info("Scheduler checker started.")
    except Exception as exc:
        log.warning("Scheduler failed to start: %s", exc)

    # Heartbeat (v4.6): one line per minute into nalox_log.txt
    # ONLY (logbook.log_file_only — never the HUD feed, never the
    # HTML page). When Nalox "hangs", the heartbeat tail is the
    # evidence: the UI state it died in, the mic dictation
    # would use, how many inputs are queued, and the
    # dictation state. (v9.0: the ears' segment/decode
    # aggregates are gone with the ears — there is no decode
    # fleet left to flood.)
    try:
        def _heartbeat():
            while True:
                time.sleep(60)
                try:
                    logbook.log_file_only(
                        f"[heartbeat] state={_ui_state} "
                        f"mic={dictation.current_mic_name()} "
                        f"queue={_input_q.qsize()} "
                        f"dict={dictation.state}")
                except Exception:
                    pass

        threading.Thread(target=_heartbeat, daemon=True,
                         name="heartbeat").start()
        log.info("Heartbeat started (60 s, log file only).")
    except Exception as exc:
        log.warning("Heartbeat failed to start: %s", exc)

    # Tray icon (manual control) — optional, never fatal.
    try:
        import tray
        tray.run_tray(
            on_show_console=(_hud.show if _hud is not None else None),
            on_hide_console=(_hud.hide if _hud is not None else None),
            on_command_center=(_show_for_wake_up
                                if _dashboard is not None else None))
    except Exception as exc:
        log.warning("Tray failed to start: %s", exc)

    # v4.7 ALWAYS-ON: show-signal poller. A second launch (the
    # Desktop / Start-Menu shortcut) writes show_request.flag
    # instead of starting a copy; this poller spots it within
    # ~1 s and surfaces Nalox.
    # v6.2: a manual launch lands on the COMMAND CENTER like
    # every other start (the flag's consumption — the
    # responsiveness proof _claim_single_instance relies on —
    # is unchanged). Only with no dashboard at all does the
    # signal fall back to the plain window.
    try:
        def _show_poller():
            while True:
                try:
                    if os.path.exists(SHOW_FLAG_FILE):
                        os.remove(SHOW_FLAG_FILE)
                        if _dashboard is not None:
                            _open_dashboard()
                        elif _hud is not None:
                            _hud.show()
                except Exception:
                    pass
                time.sleep(1.0)

        threading.Thread(target=_show_poller, daemon=True,
                         name="show-poller").start()
    except Exception as exc:
        log.warning("Show-signal poller failed to start: %s", exc)

    # Telegram phone bridge — silently off unless configured.
    # v9.0: the bridge no longer takes the ears — voice notes
    # transcribe through dictation.transcribe_cloud_bytes.
    try:
        from telegram_bridge import TelegramBridge
        bridge = TelegramBridge(
            cfg, brain, speaker,
            on_input=lambda: _open_boot_gate("first input"))
        # v7.11: the boot probe's Telegram stage reads
        # the bridge from the holder (its probe thread
        # started beside the Brain and waits for this).
        _boot_ctx["bridge"] = bridge
        if bridge.token:
            bridge.start()
    except Exception as exc:
        log.warning("Telegram bridge failed to start: %s", exc)

    # v6.2 SELF-UPDATE checker (updater.py): first check
    # ~60 s after boot, then every 5 min (v7.9 item G;
    # 30 min v7.2–v7.8) + a debounced poke whenever the
    # Command Center opens — background thread, silent
    # unless Settings → Updates holds a repo + token.
    try:
        import updater as _updater_mod
        _updater_mod.start_background(cfg, _restart_process)
    except Exception as exc:
        log.warning("Self-update checker failed to start: %s", exc)

    # v6.9 LOG SYNC (logsync.py): the diagnostics log uploads
    # itself to the logs branch of the same private repo
    # (~75 s after boot, every 10 min, early on errors), so
    # Muse can check it without Arjun screenshotting
    # anything. Fully dormant until the Updates token exists;
    # the thread never blocks anything and never speaks.
    try:
        import logsync as _logsync_mod
        _logsync_mod.start_background(cfg)
    except Exception as exc:
        log.warning("Log sync failed to start: %s", exc)

    # v7.11 THE GATE (Ready Means Ready): before the
    # interface opens, wait for the boot probe — every
    # stage resolved (✓/⚠/✗ alike; a failure is a
    # resolution, never a block), or the cap from
    # process start (pending stages are marked "still
    # warming" and finish in the background — the brain
    # and voice lines keep updating as they land, as
    # they always have). If the LOADING SCREEN itself
    # has failed, the wait aborts at once and the boot
    # is v7.10's exactly — the screen can never brick
    # startup. The outcome lands in the logbook as ONE
    # line with the per-stage verdicts, so a synced log
    # shows what boot knew before the first word.
    # v9.0: the cap is 90 s (bootprobe.GATE_CAP_S) —
    # the ears stages are gone; the slowest remaining
    # stages are the Ollama probe and the brain answer
    # test.
    if _boot_probe is not None:
        try:
            _gate = _boot_probe.wait_gate(
                _boot_t0 + _bootprobe_mod.GATE_CAP_S,
                abort=lambda: (_load_screen is not None
                               and _load_screen.failed))
            _snap = _boot_probe.snapshot()
            _ok_n = sum(1 for s in _snap
                        if s["status"] == "ok")
            _warn_l = [s["label"] for s in _snap
                       if s["status"] == "warn"]
            _fail_l = [s["label"] for s in _snap
                       if s["status"] == "fail"]
            _verdict = (f"{_ok_n}/{len(_snap)} ok"
                        + (f"; warn: {', '.join(_warn_l)}"
                           if _warn_l else "")
                        + (f"; FAILED: "
                           f"{', '.join(_fail_l)}"
                           if _fail_l else ""))
            if _gate == "ready":
                logbook.log(
                    "SYSTEM",
                    "[sys] boot probe complete — "
                    f"everything checked ({_verdict})")
            elif _gate == "capped":
                logbook.log(
                    "SYSTEM",
                    "[sys] boot probe cap reached — "
                    "opening anyway; still-warming "
                    f"stages finish in background "
                    f"({_verdict})")
            else:
                logbook.log(
                    "SYSTEM",
                    "[sys] boot probe aborted (loading "
                    "screen failed) — opening the "
                    "Command Center the pre-v7.11 way "
                    f"({_verdict})")
            # v8.1: the verdict above names WHICH stages
            # failed; this block names WHY — every stage's
            # outcome + its own detail string, in one
            # logbook line, so a synced log can diagnose a
            # failed stage without a screenshot. When the
            # gate capped with stages still warming, a
            # daemon re-logs the block as they resolve.
            _log_boot_probe_detail(_boot_probe)
            try:
                if any(s.get("capped")
                       and not s.get("resolved")
                       for s in _snap):
                    threading.Thread(
                        target=_boot_probe_late_watch,
                        args=(_boot_probe,
                              _boot_probe_detail_line(
                                  _boot_probe)),
                        daemon=True,
                        name="bootprobe-late").start()
            except Exception:
                pass
        except Exception as exc:
            log.warning("Boot gate failed: %s", exc)
        try:
            if _load_screen is not None:
                _load_screen.close()
        except Exception:
            pass

    # v6.2 START SURFACE (the owner's sharpened rule): EVERY
    # start lands on the Command Center — autostart at login,
    # a manual launch, the post-update restart — once Nalox
    # is up. The plain window was built withdrawn (hud.py)
    # and stays down; it exists behind the tray menu for
    # diagnostics only. A failure here only costs the
    # showpiece (already logged by _open_dashboard).
    if _dashboard is not None:
        try:
            if _open_dashboard():
                logbook.log("SYSTEM", "[sys] Command Center "
                                      "opened at start")
        except Exception:
            pass

    default_lang = (cfg.get("default_language") or "en").lower()
    # v9.0: there is NO wake acknowledgement anymore (the
    # wake word is gone). followup_seconds now sizes the
    # post-reply dictation arm window.
    followup_seconds = max(0, int(cfg.get("followup_seconds", 8) or 0))

    # v7.0: liveness watchdog — the loop stamps its stage
    # through _stage(); the supervisor thread (started just
    # before the main loop below) performs the recoveries.
    _watch = _StageWatch(
        speaking_s=float(cfg.get("watchdog_speaking_s", 45.0)
                         or 45.0),
        stage_s=float(cfg.get("watchdog_stage_s", 90.0)
                      or 90.0))

    def _stage(name):
        try:
            _watch.note(name)
        except Exception:
            pass

    # v7.9 (item G): the updater's busy probe — a staged
    # update defers its restart while a voice turn is in
    # progress (any non-listening stage, or speech active).
    try:
        import updater as _updater_probe_mod

        def _update_turn_busy():
            try:
                if _watch.stage != "listening":
                    return True
            except Exception:
                pass
            try:
                import voice as _voice_probe_mod
                return bool(_voice_probe_mod.is_speaking())
            except Exception:
                return False

        _updater_probe_mod.set_busy_probe(_update_turn_busy)
    except Exception:
        pass

    def say(text, lang=None, fixed=False):
        """Speak a reply, mirrored to the HUD with a SPEAKING status.

        v7.1: fixed=True is forwarded to speaker.say — the
        fixed-line TTS cache (the could-not-hear line comes
        through here; the greeting and the mic warning call
        speaker.say directly).

        v9.0 BARGE-IN: the speech runs on a worker thread
        while this function polls the barge-in event. A mic
        press (button or hotkey) while Nalox speaks sets
        the event (see _mic_trigger): the speech is cut via
        voice.stop() and this returns "interrupted" — and
        the press has already started the dictation, so he
        is recording the moment the voice stops. (The ears'
        monitor_interrupt stream is gone with the ears;
        the trigger IS the interrupt now.) The boot
        greeting does NOT come through here (it calls
        speaker.say directly), so it can never interrupt
        itself.

        v6.5 LIVE CHAT SYNC: the plain window and the logbook
        still receive the reply as ONE full "NALOX:" line (the
        log is unchanged), but the Command Center's chat does
        NOT — it opens a streaming bubble and grows it sentence
        by sentence via voice's on_chunk callback, so the text
        lands in step with the audio (the IRIS feel). The
        Thinking indicator stays up until the first chunk.
        """
        if not text:
            return "done"
        _stage("speaking")
        if _hud is not None:
            try:
                _hud.post("NALOX: " + text)
            except Exception:
                pass
        try:
            logbook.log("NALOX", "NALOX: " + text)
        except Exception:
            pass
        if _dashboard is not None:
            try:
                _dashboard.begin_nalox_reply()
            except Exception:
                pass
        outcome = {}
        _chunk_seen = []

        def _on_chunk(chunk):
            if not _chunk_seen:
                _chunk_seen.append(True)
                hudstatus("speaking")
            if _dashboard is not None:
                try:
                    _dashboard.append_nalox_chunk(chunk)
                except Exception:
                    pass

        def _speak():
            try:
                outcome["result"] = speaker.say(
                    text,
                    lang=lang if lang is not None else brain.last_lang,
                    on_chunk=_on_chunk, fixed=fixed)
            except Exception as exc:  # speaker.say is guarded; be safe
                log.warning("speaker.say raised: %s", exc)
                outcome["result"] = "done"

        worker = threading.Thread(target=_speak, daemon=True, name="say")
        worker.start()
        interrupted = False
        # v9.0: poll the barge-in event while the speech
        # runs (a stale set from before this speech is
        # cleared first — only a press DURING this reply
        # may cut it).
        _barge_event.clear()
        while worker.is_alive():
            if _barge_event.is_set():
                _barge_event.clear()
                try:
                    _voice_mod.stop()
                except Exception:
                    pass
                interrupted = True
                break
            worker.join(timeout=0.1)
        worker.join(timeout=40)
        if _dashboard is not None:
            try:
                _dashboard.end_nalox_reply()
            except Exception:
                pass
        if not _chunk_seen:
            hudstatus("speaking")
        if interrupted or outcome.get("result") == "interrupted":
            hudlog("[barge-in] interrupted by Arjun")
            return "interrupted"
        return "done"

    def run_command(command, cmd_lang, rec_s=0.0,
                    transcribe_s=0.0, source_label=""):
        """Run one input end-to-end (reply, exit, confirm flow).

        v9.0: the input is TEXT (typed / dictated /
        Telegram-shaped) — this is the same door Telegram
        uses, fed by the input queue. Returns
        (action, spoke) so the main loop knows whether a
        follow-up dictation arm makes sense.

        v4.3: ends with the [timing] stage line (field fix 4) so
        the log page shows exactly where each cycle's seconds went:
        record, transcribe, brain, speak.
        """
        _stage("thinking")
        # v9.0: the visible input marker — the SYSTEM
        # panel names where THIS turn's words came from
        # ("🎙 Last input: 🎙 cloud:groq" / "⌨ typed").
        try:
            if _dashboard is not None and source_label:
                _dashboard.set_last_input(source_label)
        except Exception:
            pass
        hudlog(f"[mic] heard: {command}")
        hudstatus("thinking")
        _t0 = time.monotonic()
        reply, action = brain.handle(command, lang=cmd_lang)
        _brain_s = time.monotonic() - _t0
        _speak_s = 0.0
        spoke = bool(reply)
        if reply:
            _t1 = time.monotonic()
            say(reply)
            _speak_s = time.monotonic() - _t1
        hudlog(f"[timing] record {rec_s:.1f}s, "
               f"transcribe {transcribe_s:.1f}s, "
               f"brain {_brain_s:.1f}s, speak {_speak_s:.1f}s")
        # v6.0: the same numbers feed the ⚡ Nalox Level in
        # the Command Center (perflevel keeps the rolling
        # samples; the dashboard renders the level).
        try:
            import perflevel
            perflevel.record_sample(
                record_s=rec_s, transcribe_s=transcribe_s,
                brain_s=_brain_s, speak_s=_speak_s)
        except Exception:
            pass
        if action == "exit":
            log.info("Clean exit requested by voice.")
            try:
                _voice_mod.stop_for_exit()
            except Exception:
                pass
            _write_exit_flag()
            sys.exit(CLEAN_EXIT_CODE)
        if action == "standby":
            # v5.4: stop = stop SPEAKING, stay alive (the
            # owner's hard rule). A "stop"/goodbye command —
            # typed, dictated or Telegram — must NEVER end
            # the process: cut any speech still in progress.
            # The standby reply itself was already spoken
            # above. Deliberate exit lives only in the tray
            # menu / HUD Exit button (physical clicks) and
            # in a confirmed PC shutdown above.
            try:
                _voice_mod.stop()
            except Exception:
                pass
            # v5.8: standby ALSO closes the Command Center —
            # "বন্ধ করো" while the fullscreen dashboard fills
            # the screen must clear the screen (the owner's
            # 15:09 field report: he said stop, the dashboard
            # stayed up, and he ended up in Task Manager).
            _close_dashboard()
            log.info("Standby by command — speech cut.")
            hudstatus("awake")
            return (action, spoke)
        if action == "dashboard_open":
            # v5.5: "open the dashboard" — the reply was
            # already spoken above. v6.2: _show_for_wake_up
            # is Command-Center-only (no window
            # substitution). v9.0: it also arms a dictation.
            _show_for_wake_up()
            hudstatus("listening")
            return (action, spoke)
        if action == "dashboard_close":
            # v5.5: "dashboard বন্ধ করো" — hide the Command
            # Center, back to the normal window.
            _close_dashboard()
            hudstatus("listening")
            return (action, spoke)
        if action == "restart":
            # v4.6: the spoken reply ("Restarting, Arjun — back
            # in a moment.") has already been delivered above.
            log.info("Self-restart requested by command.")
            _restart_process()
            return (action, spoke)
        if action == "confirm":
            # The NEXT input is the yes/no answer (v9.0:
            # typed or dictated — a dictation is armed so
            # he can simply say it; 45 s, then the question
            # lapses silently).
            hudstatus("awake")
            try:
                dictation.arm_followup(_followup_s())
            except Exception:
                pass
            _item = _next_input(45.0)
            if _item:
                answer, ans_lang = _item[0], _item[1]
                hudlog(f"[mic] heard: {answer}")
                hudstatus("thinking")
                _stage("thinking")
                reply2, action2 = brain.handle(
                    answer, lang=ans_lang)
                if reply2:
                    say(reply2)
                    spoke = True
                if action2 == "exit":
                    log.info("Clean exit after confirmation.")
                    try:
                        _voice_mod.stop_for_exit()
                    except Exception:
                        pass
                    _write_exit_flag()
                    sys.exit(CLEAN_EXIT_CODE)
                if action2 == "restart":
                    log.info("Self-restart after confirmation.")
                    _restart_process()
                    return (action2, spoke)
                return (action2, spoke)
            return (action, spoke)
        return (action, spoke)

    # Startup greeting, then the morning briefing, then the YouTube check.
    # The greeting itself is NOT barge-in monitored (it contains the
    # name "Nalox") and can be switched off in Settings (v4.1).
    try:
        # v6.5: the greeting speaks his LEARNED language
        # preference when one exists (Bengali-only is his
        # standing order) — default_language is the fallback.
        try:
            _greet_lang = brain._pref_lang() or default_lang
        except Exception:
            _greet_lang = default_lang
        greet_text = greeting(cfg, lang=_greet_lang)
        if cfg.get("greet_on_startup", True):
            hudstatus("speaking")
            hudlog("NALOX: " + greet_text)
            speaker.say(greet_text, lang=_greet_lang,
                        fixed=True)
        else:
            hudlog("[sys] greeting skipped (turned off in Settings)")
        # v4.3: the boot briefing IS Morning Digest 2.0 — greeting,
        # battery, YouTube stats, today's reminders, headlines ONLY
        # when briefing_news is on, weather when a key is set — and
        # it also goes to Telegram. Any digest failure falls back
        # to the classic v4.2 briefing below.
        #
        # v5.2 — OWNER'S CANCELLATION (2026-11-15): the automatic
        # startup briefing is OFF, for good. Boot speaks the
        # GREETING ONLY; the digest still exists on demand ("good
        # morning" / Telegram) — it just never fires by itself at
        # startup again. briefing_on_startup defaults False and
        # the v5.2 config patch forces it (and the legacy
        # morning_briefing gate) off on Arjun's install.
        _digest_done = False
        if cfg.get("briefing_on_startup", False):
            try:
                if cfg.get("morning_briefing", True):
                    import skills as _skills_mod
                    _spoken, _tg_text = _skills_mod.digest(
                        cfg, brain=brain,
                        reminders=locals().get("store"),
                        lang=default_lang,
                        youtube_first=(str(cfg.get("mode") or "jarvis")
                                       .lower() == "creator"))
                    hudlog("[briefing] " + _spoken)
                    hudstatus("speaking")
                    speaker.say(_spoken, lang=default_lang)
                    hudstatus("listening")
                    _skills_mod.push_digest(cfg, _tg_text)
                    _digest_done = True
            except Exception as exc:
                log.warning("Boot digest failed (%s); using the "
                            "classic briefing", exc)
            if not _digest_done:
                morning_briefing(cfg, speaker)
        else:
            hudlog("[sys] startup briefing off — greeting only "
                   "(digest is on demand: say 'good morning')")
        startup_youtube_check(cfg, speaker)
    except Exception as exc:
        log.error("Greeting/briefing/startup check failed: %s", exc)

    # v6.2 SELF-UPDATE announcement: if the previous process
    # updated itself, its updated_to.txt marker is waiting.
    # Pop it FIRST (so the line can never repeat), then speak
    # it exactly once — right after the greeting, before the
    # ready line.
    try:
        import updater as _updater_mod
        _updated_to = _updater_mod.pop_updated_marker()
        if _updated_to:
            hudlog(f"[sys] self-updated to v{_updated_to}")
            # v7.1: the Command Center ALSO shows it, once —
            # a banner under its top bar, so he can SEE the
            # update landed even if he missed the spoken
            # line (his 2026-11-16 complaint: updates were
            # invisible). The marker is already popped, so
            # neither announcement can ever repeat.
            if _dashboard is not None:
                try:
                    _dashboard.set_update_notice(_updated_to)
                except Exception:
                    pass
            hudstatus("speaking")
            # v9.0 (fold-in C): the announcement follows
            # the learned language preference — under his
            # Bengali-only order it is spoken in Bengali,
            # never English (the v8.2 field sync caught
            # the English line under a bn pref).
            _ann_lang = default_lang
            try:
                _ann_lang = brain._pref_lang() or default_lang
            except Exception:
                pass
            if str(_ann_lang).startswith("bn"):
                speaker.say(
                    f"স্যার, আমি নিজে নিজে version "
                    f"{_updated_to}-তে update হয়ে গেছি।",
                    lang="bn")
            elif str(_ann_lang).startswith("hi"):
                speaker.say(
                    f"सर, मैं खुद version {_updated_to} "
                    f"पर update हो गया हूँ।", lang="hi")
            else:
                speaker.say(f"I have updated myself to version "
                            f"{_updated_to}, sir.", lang="en")
            hudstatus("listening")
    except Exception as exc:
        log.warning("Update announcement failed: %s", exc)

    # v9.0 OPEN-ARM: the Command Center opened at start
    # (above) — arm ONE dictation so he can simply start
    # talking. It hears nothing inside the window and
    # closes silently; the greeting is already spoken, so
    # there is no self-hearing.
    try:
        dictation.arm_followup(_followup_s())
    except Exception:
        pass

    # Main loop (v9.0): an input-queue consumer. Typed
    # lines, dictated lines and the missed-dictation
    # sentinel arrive here and run exactly like Telegram
    # messages. One bad cycle must never kill
    # responsiveness — log it, post it, keep going. The
    # same failure 3 times in a row earns one short spoken
    # line, rate-limited to once per 300 s so a persistent
    # fault can't become a "try again" loop on speaker.
    hudstatus("listening")
    hudlog(f"[ready] Type, tap 🎙, or press "
           f"{cfg.get('dictation_hotkey') or 'ctrl+alt+space'} "
           f"and speak — Telegram works too")

    # v7.0: the liveness supervisor — checks the stage
    # stamp every WATCHDOG_CHECK_S and performs the one
    # recovery each stuck stage has (see _StageWatch).
    # v9.0: the transcription-stage recovery (respawn the
    # ears workers) is gone with the ears; a stuck
    # non-speaking stage is named in one ERROR line.
    def _liveness_supervisor():
        while True:
            time.sleep(WATCHDOG_CHECK_S)
            try:
                _hit = _watch.check()
            except Exception:
                continue
            if not _hit:
                continue
            _stuck_stage, _stuck_age = _hit
            if _stuck_stage == "speaking":
                log.error("[watchdog] speaking stuck for "
                          "%.0fs — stopping playback",
                          _stuck_age)
                logbook.log(
                    "ERROR",
                    f"[watchdog] speaking stuck for "
                    f"{_stuck_age:.0f}s — playback stopped")
                try:
                    _voice_mod.stop()
                except Exception:
                    pass
            else:
                log.error("[watchdog] stage %r stuck for "
                          "%.0fs — recovering",
                          _stuck_stage, _stuck_age)
                logbook.log(
                    "ERROR",
                    f"[watchdog] stage '{_stuck_stage}' "
                    f"stuck for {_stuck_age:.0f}s — "
                    f"recovering")

    threading.Thread(target=_liveness_supervisor,
                     daemon=True, name="liveness").start()

    last_error = None
    error_streak = 0
    last_error_speech = 0.0
    while True:
        try:
            _stage("listening")
            _item = _input_q.get()
            _text, _lang, _kind, _rec_s, _tr_s, _label = _item
            # v9.0: the first input opens the boot
            # warm-up gate (v7.10 P4's trigger, renamed).
            try:
                _open_boot_gate("first input")
            except Exception:
                pass
            if _kind == "missed":
                # He spoke; the cloud returned nothing
                # usable. ANSWER — never silence (the
                # standing rule). It is also a system
                # fault worth an early log sync.
                logbook.log(
                    "ERROR",
                    "[dictation] speech was captured but "
                    "cloud transcription returned nothing "
                    "usable — answered with the "
                    "could-not-hear line")
                say(_missed_command_line(brain, cfg),
                    fixed=True)
                hudstatus("listening")
                continue
            hudstatus("awake")
            _action, _spoke = run_command(
                _text, _lang, _rec_s, _tr_s,
                source_label=_label)
            # Follow-up (v9.0): after a SPOKEN reply, arm
            # ONE dictation inside the follow-up window so
            # the conversation can continue hands-lightly.
            # It hears nothing -> it simply closes. A
            # standby turn never arms (he said stop).
            if _spoke and _action not in ("standby",) \
                    and followup_seconds > 0:
                try:
                    dictation.arm_followup(_followup_s())
                except Exception:
                    pass
            hudstatus("listening")
        except SystemExit:
            raise
        except Exception as exc:
            # A bad input cycle — log, breathe, retry.
            # v5.2: the [CRASH-GUARD] tag + a logbook ERROR line,
            # so a guarded failure is VISIBLE on the diagnostics
            # page as a recovery — never as silence.
            log.error("[CRASH-GUARD] main loop error: %s — "
                      "retrying in 3 s", exc)
            logbook.log("ERROR", f"[CRASH-GUARD] main loop: "
                                 f"{type(exc).__name__}: {exc} "
                                 "— kept going")
            hudlog(f"[error] {type(exc).__name__}: {exc}")
            if repr(exc) == last_error:
                error_streak += 1
            else:
                last_error = repr(exc)
                error_streak = 1
            if error_streak >= 3:
                error_streak = 0
                last_error = None
                # Speak the warning at most once per 300 s (v3.5);
                # the HUD [error] posts above are NOT rate-limited.
                if time.time() - last_error_speech >= 300:
                    last_error_speech = time.time()
                    try:
                        if default_lang.startswith("bn"):
                            speaker.say("আমি একটু সমস্যায় পড়েছি, "
                                        "আবার চেষ্টা করছি।", lang="bn")
                        else:
                            speaker.say(f"I hit a small problem, "
                                        f"{_addr(cfg)}. Trying again.",
                                        lang="en")
                    except Exception:
                        pass
            hudstatus("listening")
            _stage("listening")
            time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # deliberate exits (code 42) and restarts pass through
    except BaseException as exc:
        # v5.2 CRASH-GUARD of last resort: an unhandled failure
        # anywhere in boot (Speaker/Ears/Brain construction sits
        # outside the main loop's own guard) leaves its evidence
        # in the logbook + fault log BEFORE the process goes
        # down, so the next screenshot shows WHAT died instead
        # of a silent gap. The supervisor then relaunches Nalox
        # (no exit flag was written — this was not deliberate).
        try:
            log.exception("[CRASH-GUARD] Nalox crashed in boot/main")
            logbook.log("ERROR", f"[CRASH-GUARD] Nalox crashed: "
                                 f"{type(exc).__name__}: {exc} — "
                                 "supervisor will relaunch")
            # NOTE: no clean-exit marker is written to
            # nalox_fault.log here — that absence is itself the
            # evidence that this death was a crash.
        except Exception:
            pass
        raise
