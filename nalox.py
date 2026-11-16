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
"""
import inspect
import logging
import os
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
from ears import Ears                          # noqa: E402
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


def _wake_ack(cfg):
    """(text, lang) spoken the moment the wake word lands (v5.4).

    Arjun's chosen wake line — config wake_line, default "Yes
    Sir, I'm here." (v5.7; the v5.4 default was "Yes Sir, I'm
    coming for you.") — replaces the old short ack on
    BOTH wake paths: bare wake and "Nalox, wake up" both flow
    through the main loop's single say(ack), so this helper is
    the whole feature, and nothing else is spoken before
    listening starts. The line is the acknowledgement.

    The spoken language follows the line's OWN script, so an
    English line is never read out by a Bengali voice (or the
    reverse). An empty wake_line (Settings → General "Wake
    reply" cleared) brings the classic pre-v5.4 ack back."""
    line = str((cfg or {}).get("wake_line") or "").strip()
    if line:
        if any("\u0980" <= ch <= "\u09ff" for ch in line):
            return line, "bn"
        if any("\u0900" <= ch <= "\u097f" for ch in line):
            return line, "hi"
        return line, "en"
    default_lang = str((cfg or {}).get("default_language")
                       or "en").lower()
    if default_lang.startswith("bn"):
        return "হ্যাঁ, বলো?", "bn"
    return f"Yes, {_addr(cfg)}?", "en"


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
# the LOOP moves. v7.0: the main loop stamps its stage at
# every boundary (listening / heard / transcribing /
# thinking / speaking) and a supervisor thread checks the
# stamp every few seconds:
#   * "speaking" past watchdog_speaking_s (45 s) — speech
#     is cut through the EXISTING stop path (voice.stop(),
#     the same lever barge-in pulls), one logbook ERROR
#     names the stage + duration, back to listening;
#   * any other non-listening stage past watchdog_stage_s
#     (90 s) — one logbook ERROR, and for the transcription
#     stages the lane workers are respawned (the ears
#     clients' own restart machinery). The process is
#     NEVER killed from here — restarts belong to the
#     supervisor/service layer, exit codes unchanged.
# Interventions are throttled per stage (1 per 2 min) so a
# pathological loop cannot spam the log the owner reads.
# "listening" itself is never judged here — a quiet room
# is legitimate; the ears stream watchdog (ears.py) owns
# the listening state's health. Pure policy + arithmetic:
# the supervisor thread in main() performs the effects, so
# this class is unit-testable with a fake clock.
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
class _DashboardPreviewSink:
    """ears → Command Center bridge for the live hearing
    preview (v6.7 F): partial transcriptions stream into the
    YOU bubble while Arjun speaks; the final transcript
    finalizes it. The dashboard global is read live (it is
    created lazily), and every dashboard method is already
    guarded — a preview can never break listening."""

    def visible(self):
        try:
            return bool(_dashboard is not None
                        and _dashboard.is_visible())
        except Exception:
            return False

    def begin(self):
        # v7.6: each surface gates on its OWN visibility —
        # the fan-out sink may start the pump for the OTHER
        # surface; a hidden dashboard must not open (or be
        # fed) a bubble nobody can see.
        if self.visible() and _dashboard is not None:
            _dashboard.begin_you_preview()

    def update(self, text):
        if self.visible() and _dashboard is not None:
            _dashboard.update_you_preview(text)

    def finish(self, text):
        if not self.visible() or _dashboard is None:
            return
        if text:
            _dashboard.end_you_preview(text)
        else:
            _dashboard.cancel_you_preview()


class _HudPreviewSink:
    """The live hearing preview's plain-window surface
    (v7.6, item F): partials land in the HUD's conversation
    view as an in-place "You …" line, so the owner sees his
    words as he speaks even with the Command Center closed
    — v7.5 field: he closed it mid-session and the screen
    sat on a bare "Listening" while he talked. Same sink
    contract as the dashboard's; every method gates on
    THIS window being shown (it builds withdrawn)."""

    def visible(self):
        try:
            return bool(_hud is not None and _hud.is_shown())
        except Exception:
            return False

    def begin(self):
        if self.visible():
            _hud.preview_begin()

    def update(self, text):
        if self.visible():
            _hud.preview_update(text)

    def finish(self, text):
        if self.visible():
            _hud.preview_finish(text)


class _MultiPreviewSink:
    """Fan-out preview sink (v7.6, item F): the ears pump
    streams whenever ANY surface is visible, and each
    surface receives only while IT is visible — a hidden
    Command Center no longer starves the visible plain
    window, and vice versa. Wake semantics, the partial
    matcher and the pump itself are untouched: this only
    routes the same callbacks to both chat surfaces."""

    def __init__(self, *sinks):
        self._sinks = [s for s in sinks if s is not None]

    def visible(self):
        for sink in self._sinks:
            try:
                if sink.visible():
                    return True
            except Exception:
                pass
        return False

    def begin(self):
        for sink in self._sinks:
            try:
                sink.begin()
            except Exception:
                pass

    def update(self, text):
        for sink in self._sinks:
            try:
                sink.update(text)
            except Exception:
                pass

    def finish(self, text):
        for sink in self._sinks:
            try:
                sink.finish(text)
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
    open, the failure is already logged by _open_dashboard;
    the wake itself still lands (the caller goes on to
    listen for the command). Never raises."""
    return _open_dashboard()


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
    cfg = CONFIG
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
    ears = Ears(cfg)
    brain = Brain(cfg, speaker)

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

    # v6.7 F: live hearing preview — while Arjun speaks a
    # command, his words stream into the Command Center's
    # YOU bubble (the Gemini-app feel he asked for). The
    # sink reads the dashboard global live (created lazily);
    # a hidden or absent dashboard means no previews at all.
    # v7.6 F: the preview now fans out to BOTH chat
    # surfaces (Command Center + the plain window's
    # conversation view) — whichever one he can see shows
    # his words live; neither surface's hidden state can
    # starve the other.
    try:
        ears.set_preview_sink(_MultiPreviewSink(
            _DashboardPreviewSink(), _HudPreviewSink()))
    except Exception as exc:
        log.warning("Preview sink not registered: %s", exc)

    # Wake feedback (v3.4): the instant the wake word matches, post to
    # the HUD and play a short beep, so Arjun KNOWS Nalox heard him.
    def _on_wake():
        hudlog("[mic] wake word heard")
        try:
            import winsound
            winsound.Beep(880, 120)
        except Exception:
            pass

    # v5.2: "Nalox, wake up" — SHOW the window, instantly. The
    # ears and the HUD live in this same process, so the show is
    # a direct call when the HUD exists; the show_request.flag
    # path (watched by the poller below) is the fallback for
    # when it doesn't. Bare "Nalox" never reaches this callback.
    # v5.5: wake up now opens the COMMAND CENTER (fullscreen
    # dashboard). v6.2: _show_for_wake_up is dashboard-ONLY —
    # the plain window never comes up on this path.
    def _on_wake_up():
        hudlog("[wake] wake up — opening the Command Center")
        _show_for_wake_up()

    # v7.0: mic trouble alert — when the ears stream
    # watchdog burns its whole restart budget, the owner
    # hears ONE spoken line instead of shouting into a
    # dead mic. Spoken through the normal speaker, and
    # only when Nalox is not already talking.
    def _on_mic_alert():
        try:
            if not _voice_mod.is_speaking():
                speaker.say("স্যার, মাইকে সমস্যা হচ্ছে।",
                            lang="bn", fixed=True)
        except Exception:
            pass

    try:
        import ears as _ears_mod
        _ears_mod.set_wake_callback(_on_wake)
        _ears_mod.set_wake_up_callback(_on_wake_up)
        # Mic status lines (v3.5): "[mic] connected: ..." etc. -> HUD.
        _ears_mod.set_status_callback(hudlog)
        _ears_mod.set_mic_alert_callback(_on_mic_alert)
    except Exception as exc:
        log.warning("Ears callbacks not registered: %s", exc)

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
            hudlog("[sys] Command Center ready — say "
                   "'Nalox, wake up' to open it")
        except Exception as exc:
            log.warning("Command Center failed to start: %s", exc)
            _dashboard = None
    elif cfg.get("command_center", True):
        log.warning("Command Center skipped: no app window to "
                    "host it (the dashboard lives in the app "
                    "window's screen).")

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
            import ears as _ears_mod
            mic_name = _ears_mod._device_name(
                _ears_mod.pick_input_device(cfg))
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
    # evidence: the state it died in, the mic it was on, and
    # whether transcription jobs were piling up in the queue.
    try:
        def _heartbeat():
            while True:
                time.sleep(60)
                try:
                    # v7.2 (S2): the gate deltas ride the
                    # heartbeat — seg/blip/short/peak separate
                    # "he never spoke" (peak at the floor) from
                    # "the gate dropped it" (healthy peak,
                    # seg=0). See ears.wake_listen_stats.
                    _gs = ears.wake_listen_stats()
                    # v7.4 (Defect 2): the wake-decode
                    # aggregate rides the same line when any
                    # decode happened this window — count by
                    # path (t=tiny only, b=base retry,
                    # s=small escalation, r=fast-reject) and
                    # the slowest decode, so a flood window
                    # shows its real milliseconds.
                    _dec_tail = ""
                    if _gs.get("dec"):
                        _dec_tail = (
                            f" dec={_gs['dec']} "
                            f"(t{_gs.get('dec_tiny', 0)} "
                            f"b{_gs.get('dec_base', 0)} "
                            f"s{_gs.get('dec_small', 0)} "
                            f"r{_gs.get('dec_rej', 0)}) "
                            f"dmax={_gs.get('dec_max_ms', 0) / 1000.0:.1f}s")
                    logbook.log_file_only(
                        f"[heartbeat] state={_ui_state} "
                        f"mic={ears.current_mic_name()} "
                        f"queue={ears.transcribe_queue_size()} "
                        f"seg={_gs['seg']} blip={_gs['blip']} "
                        f"short={_gs['short']} "
                        f"peak={_gs['peak']:.4f}{_dec_tail}")
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
    try:
        from telegram_bridge import TelegramBridge
        bridge = TelegramBridge(cfg, brain, speaker, ears)
        if bridge.token:
            bridge.start()
    except Exception as exc:
        log.warning("Telegram bridge failed to start: %s", exc)

    # v6.2 SELF-UPDATE checker (updater.py): first check
    # ~60 s after boot, then every 30 min (v7.2; 6-hourly
    # through v7.1) — background thread, silent unless
    # Settings → Updates holds a repo + token.
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
    # v5.4: the wake acknowledgement is his chosen wake line
    # (config wake_line) — see _wake_ack. Both wake paths
    # (bare wake + "wake up") speak it through the main loop's
    # say(ack) below; the boot greeting is separate and
    # unchanged.
    ack, ack_lang = _wake_ack(cfg)
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

    def say(text, lang=None, fixed=False):
        """Speak a reply, mirrored to the HUD with a SPEAKING status.

        v7.1: fixed=True is forwarded to speaker.say — the
        fixed-line TTS cache (the wake ack and the
        could-not-hear line come through here; the greeting
        and the mic warning call speaker.say directly).

        v4.1 BARGE-IN: the speech runs on a worker thread while
        ears.monitor_interrupt listens on its own stream. If Arjun
        says the wake word / "stop" / "থামো" / "চুপ" mid-speech, the
        monitor calls voice.stop(), the speech is cut, and this
        returns "interrupted" — the main loop then goes straight
        back to listening (the follow-up window), Gemini-style.
        The boot greeting does NOT come through here (it calls
        speaker.say directly), so it can never interrupt itself.

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
        try:
            interrupted = ears.monitor_interrupt(
                lambda: worker.is_alive(), _voice_mod.stop)
        except Exception as exc:
            log.warning("Barge-in monitor failed: %s", exc)
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

    def run_command(command, cmd_lang, wake_rec_s=0.0, transcribe_s=0.0):
        """Run one heard command end-to-end (reply, exit, confirm flow).

        v4.3: ends with the [timing] stage line (field fix 4) so
        the log page shows exactly where each cycle's seconds went:
        wake->record, transcribe, brain, speak.
        """
        _stage("thinking")
        hudlog(f"[mic] heard: {command}")
        hudstatus("thinking")
        _t0 = time.monotonic()
        reply, action = brain.handle(command, lang=cmd_lang)
        _brain_s = time.monotonic() - _t0
        _speak_s = 0.0
        if reply:
            _t1 = time.monotonic()
            say(reply)
            _speak_s = time.monotonic() - _t1
        hudlog(f"[timing] wake→record {wake_rec_s:.1f}s, "
               f"transcribe {transcribe_s:.1f}s, "
               f"brain {_brain_s:.1f}s, speak {_speak_s:.1f}s")
        # v6.0: the same numbers feed the ⚡ Nalox Level in
        # the Command Center (perflevel keeps the rolling
        # samples; the dashboard renders the level).
        try:
            import perflevel
            perflevel.record_sample(
                record_s=wake_rec_s, transcribe_s=transcribe_s,
                brain_s=_brain_s, speak_s=_speak_s)
        except Exception:
            pass
        if action == "exit":
            log.info("Clean exit requested by voice.")
            _write_exit_flag()
            sys.exit(CLEAN_EXIT_CODE)
        if action == "standby":
            # v5.4: stop = stop SPEAKING, keep listening (the
            # owner's hard rule). A "stop"/goodbye command —
            # voice or Telegram — must NEVER end the process:
            # cut any speech still in progress and fall back
            # to wake listening. The standby reply itself was
            # already spoken above. Deliberate exit lives only
            # in the tray menu / HUD Exit button (physical
            # clicks) and in a confirmed PC shutdown above.
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
            log.info("Standby by command — speech cut, "
                     "back to wake listening.")
            hudstatus("awake")
            return
        if action == "dashboard_open":
            # v5.5: voice "open the dashboard" — the reply was
            # already spoken above. v6.2: _show_for_wake_up is
            # Command-Center-only (no window substitution).
            _show_for_wake_up()
            hudstatus("listening")
            return
        if action == "dashboard_close":
            # v5.5: voice "dashboard বন্ধ করো" — hide the
            # Command Center, back to the normal window and
            # plain wake listening.
            _close_dashboard()
            hudstatus("listening")
            return
        if action == "restart":
            # v4.6: the spoken reply ("Restarting, Arjun — back
            # in a moment.") has already been delivered above.
            log.info("Self-restart requested by voice.")
            _restart_process()
            return
        if action == "confirm":
            # The next utterance is the yes/no answer.
            hudstatus("awake")
            _stage("transcribing")
            answer, ans_lang = ears.listen_for_command()
            if answer:
                hudlog(f"[mic] heard: {answer}")
                hudstatus("thinking")
                _stage("thinking")
                reply2, action2 = brain.handle(answer, lang=ans_lang)
                if reply2:
                    say(reply2)
                if action2 == "exit":
                    log.info("Clean exit after confirmation.")
                    _write_exit_flag()
                    sys.exit(CLEAN_EXIT_CODE)
                if action2 == "restart":
                    log.info("Self-restart after confirmation.")
                    _restart_process()
                    return

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
            speaker.say(f"I have updated myself to version "
                        f"{_updated_to}, sir.", lang="en")
            hudstatus("listening")
    except Exception as exc:
        log.warning("Update announcement failed: %s", exc)

    # Main loop with mic-failure resilience: one bad cycle must never
    # kill responsiveness — log it, post it to the HUD, keep listening.
    # The same failure 3 times in a row earns one short spoken line,
    # and even that line is rate-limited (v3.5) to once per 300 s so a
    # persistent fault can't turn into a "try again" loop on speaker.
    hudstatus("listening")
    hudlog("[ready] Say 'Nalox' to wake me")

    # v7.0: the liveness supervisor — checks the stage
    # stamp every WATCHDOG_CHECK_S and performs the one
    # recovery each stuck stage has (see _StageWatch).
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
                    f"{_stuck_age:.0f}s — playback stopped, "
                    f"back to listening")
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
                if _stuck_stage in ("transcribing", "heard"):
                    try:
                        ears.respawn_transcription_workers()
                    except Exception:
                        pass

    threading.Thread(target=_liveness_supervisor,
                     daemon=True, name="liveness").start()

    last_error = None
    error_streak = 0
    last_error_speech = 0.0
    while True:
        try:
            _stage("listening")
            heard = ears.wait_for_wake_word()
            if not heard:
                continue
            hudstatus("awake")
            hudlog("[wake] wake word heard")
            _stage("heard")
            _ack_t0 = time.monotonic()
            say(ack, lang=ack_lang, fixed=True)
            _ack_s = time.monotonic() - _ack_t0
            # Ears 2.0: a one-breath command ("Nalox কেমন আছো")
            # arrives WITH the wake segment — no second recording.
            _pending = None
            try:
                _pending = ears.take_pending_command()
            except Exception:
                _pending = None
            if _pending:
                command, cmd_lang = _pending
            else:
                _stage("transcribing")
                command, cmd_lang = ears.listen_for_command()
            _rec_s = _ack_s + float(
                _ears_mod.LAST_TIMING.get("record", 0.0))
            _tr_s = float(_ears_mod.LAST_TIMING.get("transcribe", 0.0))
            if not command:
                # v6.13 SILENT-PATH FIX: the wake was ACKED
                # out loud, so an empty command here used to
                # loop back in TOTAL silence — the owner's
                # 22:24 IST field report ("কথা শুনছে, কিন্তু
                # কোনো লেখা আসে না"). The miss is now
                # ANSWERED with one short honest line. When
                # real speech was captured but every
                # transcription path returned empty
                # (ears.LAST_COMMAND_MISS == "engines-empty")
                # it is a system fault, not a quiet room: a
                # logbook ERROR goes with the answer, so
                # logsync uploads it early.
                if getattr(_ears_mod, "LAST_COMMAND_MISS",
                           None) == "engines-empty":
                    logbook.log(
                        "ERROR",
                        "[ears] speech was captured but "
                        "every transcription path returned "
                        "empty — answered with the "
                        "could-not-hear line")
                say(_missed_command_line(brain, cfg), fixed=True)
                hudstatus("listening")
                continue
            run_command(command, cmd_lang, _rec_s, _tr_s)
            # Follow-up window (v3): for a few seconds Nalox keeps
            # listening WITHOUT needing the wake word again. Each new
            # command re-opens the window; silence closes it.
            deadline = time.time() + followup_seconds
            while followup_seconds > 0 and time.time() < deadline:
                hudstatus("awake")
                hudlog(f"[sys] follow-up listening "
                       f"({followup_seconds}s) — no wake word needed")
                _stage("transcribing")
                text2, lang2 = ears.listen_for_command()
                if not text2:
                    continue
                run_command(text2, lang2,
                            float(_ears_mod.LAST_TIMING.get(
                                "record", 0.0)),
                            float(_ears_mod.LAST_TIMING.get(
                                "transcribe", 0.0)))
                deadline = time.time() + followup_seconds
            hudstatus("listening")
        except SystemExit:
            raise
        except Exception as exc:
            # Missing mic, device busy, model hiccup — log, breathe, retry.
            # v5.2: the [CRASH-GUARD] tag + a logbook ERROR line,
            # so a guarded failure is VISIBLE on the diagnostics
            # page as a recovery — never as silence.
            log.error("[CRASH-GUARD] main loop error: %s — "
                      "retrying in 3 s", exc)
            logbook.log("ERROR", f"[CRASH-GUARD] main loop: "
                                 f"{type(exc).__name__}: {exc} "
                                 "— kept listening")
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
