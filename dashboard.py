"""Nalox Command Center (v5.5, fixed v5.5.1) — the fullscreen
dashboard.

Arjun sent an IRIS demo reel (2026-11-15) and asked for its
moment: say "Wake up Nalox" and a whole command center opens
smoothly — a glowing blue orb in the middle, system health on
one side, the conversation on the other. This module is that
screen, built the Nalox way (stdlib only, defensive everywhere):

  - CENTER: an animated BLUE particle orb — a rotating 3D
    point-sphere (~300 points, Canvas ovals, blue palette)
    with a soft glow ring. v5.7 beauty pass: his round logo
    sits at the orb's heart (pre-rendered sizes, scaling
    with the pulse), a faint halo ring counter-rotates
    around the sphere, the glow blooms one ring wider, and
    the side panels wear subtle edge + accent-strip frames.
    It BREATHES while idle/listening, swells
    with Arjun's live mic level while HE speaks (the same
    ears.get_level() the HUD meter uses), and ripples while
    Nalox is speaking (the same voice.is_speaking() the HUD
    wave uses). Pure stdlib math, ~30 fps via after(), and the
    animation loop runs ONLY while the dashboard is visible —
    zero background CPU when hidden.
  - LEFT "SYSTEM": CPU / RAM / Disk / Battery, ~1x/s, STDLIB
    ONLY (ctypes: GetSystemTimes deltas, GlobalMemoryStatusEx,
    GetSystemPowerStatus; shutil.disk_usage) + the current mic
    name and brain line, read from the logbook status header —
    the same source the diagnostics page shows.
  - RIGHT "CHAT": the live conversation, fed by the same
    hudlog() lines the app window renders ("[mic] heard: ..."
    -> You, "NALOX: ..." -> Nalox).
  - TOP: round logo, "NALOX", a clock, the live status.

Public API mirrors hud.Hud (thread-safe, never raises):
    Dashboard(cfg); attach(hud); start(); show() -> bool;
    hide(); post(text); set_status(state); set_brain(text);
    is_visible(); stop()

show() returns True when the window is up — or queued to
come up, with a loud fallback if it truly can't (see the
v6.1 note below) — so nalox.py can fall back to the normal
window when it isn't. Inside the window, fullscreen failure
degrades to a maximized window, then to a plain
full-screen-sized window. A UI failure logs a logbook line
and can never crash the main loop.

v5.5.1 — SINGLE TK INTERPRETER (the field fix). v5.5 gave this
module its OWN Tk root on its OWN thread while hud.py already
owned a Tk root on the HUD thread. On Windows that second
interpreter is what never opened: the window was built against
the wrong interpreter (the PIL logo image, created against the
first interpreter, is invalid in the second), the show path
died, and the generic "did not open" line hid the exception —
while the non-sticky failure let every repeated trigger log
another identical line (~20 in 3 s at boot). Now the dashboard
is a Toplevel hosted on the HUD's root: attach(hud) hands over
the app window, the build runs on the HUD thread via
hud.run_on_tk, and the queue pump is an after() chain on that
same root — exactly how hud.Hud itself works. Every show/hide
failure logs the REAL exception (repr + traceback) to the
logbook ONCE per attempt, a failed attempt starts a cooldown
so repeated triggers stay silent, and show() while already
visible is a no-op.

The non-Tk state machine (visibility, chat buffer, orb math,
stats collectors) is deliberately display-free so the test
suite can drive it headlessly — see _force_headless, used
only by tests (it runs the state machine with no tkinter
at all).

v5.8 — CLOSE, BULLETPROOFED + HIS OWN COMMANDS + CHAT POLISH.
The field report (2026-11-15 15:09): the Command Center would
NOT close — ✕ and Esc did nothing and Arjun had to kill Nalox
from Task Manager. Root cause, in the old code: every close
route funnelled into hide(), whose first line was
`if not self._visible: return` — but _visible (a logical flag
on the caller thread) desyncs from the window's real state
(_win_open, Tk thread). Concretely: show() waits only 3 s for
the Tk thread to confirm; on a busy HUD thread the queued
show executes LATE, after show() already timed out — the
fullscreen window opens anyway while _visible stays False,
and from that moment hide() is a permanent no-op. Esc made
it worse: bound only on the Toplevel widget, it never fires
when focus sits outside the dashboard. And a show already
sitting in the queue could re-open the window after a hide.
Now: (1) show attempts carry a GENERATION; hide() bumps it,
so a pending or in-flight show is cancelled, never executed
late; a timed-out show cancels itself the same way. (2)
hide() never gates on the flag — it always queues the hide
(over a queue-full-resistant channel), and _tk_hide logs the
real outcome ([dashboard] line: closed / was not open /
failed with the exception) — never silent. (3) Escape is
bind_all while the dashboard is visible, unbound on hide;
the ✕, a labelled "✕ Close" button and WM_DELETE all call
the same hide(). (4) nalox.py's standby branch also hides
the dashboard — "বন্ধ করো" while it fills the screen now
clears the screen.
Also v5.8: the chat renders as BUBBLES (his lines
right-weighted in blue, Nalox's left in teal, via Text-tag
margins/backgrounds) with an animated "Thinking ●○○"
indicator under it while the brain works (driven by the
same ~30 fps orb loop — no second timer), and the right
panel gains his "⭐ Make your own command" form: phrase +
action + target, saved to custom_commands.json, listed with
Delete buttons — taught in HIS words, no coding (the brain
side is Brain._custom_intents).

v6.1 — SHOW WITHOUT THE CONFIRM HANDSHAKE. The field log
(2026-11-15 16:00/16:04) shows the v5.5.1–v5.8 show() still
failing on Arjun's real Windows Tk: "Command Center did
not confirm showing in time", twice — once at boot, once
from the HUD 🖥 button. Root cause: show() queued a "show"
item and BLOCKED the caller up to 3 s on an event set only
when the dashboard's own after() pump drained the queue.
From the HUD button, show() runs ON the Tk thread inside
the mainloop callback — the drain it waits for needs the
very mainloop it is blocking, so the timeout was
guaranteed; at boot the busy Tk thread simply missed the
3 s window, and the timeout then CANCELLED the queued show
(generation bump), so it never landed late either. Now
there is no confirmation round-trip at all: the show is
performed on the Tk thread (inline when the caller already
is that thread; dispatched through hud.run_on_tk — the
HUD's own FIFO pump, behind the build — otherwise), the
window's real mapped state (winfo_viewable()/state(),
read back on the Tk thread) is the only truth, a caller
whose wait expires has its show ACCEPTED (it lands when
the pump reaches it) instead of failed-and-cancelled, and
a window that still doesn't read as mapped gets one
deferred recheck, a log line carrying the REAL window
state, and the normal window raised as the fallback.

v6.2 — THE OPENING CEREMONY + A BIGGER, RICHER CENTER.
The owner's orders (2026-11-15): the Command Center is
now THE surface — every start lands on it, "Wake up
Nalox" opens ONLY it, and the plain window must never
come up on those paths (so _tk_verify_show no longer
raises the normal window: a failed show logs its real
state and that is all). On open, a ~1 s staged ceremony
runs on the existing animation loop: the window fades in
while the orb scales/spins up under a bright ring sweep,
the LEFT panel lights, then the RIGHT, and the status
pill flips to "● ONLINE". The header carries the ⚡ Level
BIG (number + word + a thin progress bar to the next
level, from perflevel.level_progress). The SYSTEM panel
gains Phone (connected device or "not connected"),
Commands this session (logbook's session counter) and
Uptime rows. The top bar also gains ⚙ Settings and 📋 Log
buttons wired to the HUD's OWN handlers, so nothing the
owner needs lives only on the plain window any more.

v7.1 — HE CAN SEE THE UPDATE. The owner's complaint
(2026-11-16): every version looks identical, and he once
tested the wrong version without knowing. The header now
carries a permanent VERSION BADGE read from version.txt
(running_version — the same source as nalox.py's boot
line, never a hard-coded string), and the first Command
Center open after an update lands shows a ONE-TIME
banner under the top bar ("✅ Updated to vX.Y — …"),
driven by the updater's popped marker via
set_update_notice() and cleared as it renders — a UI
element, never a chat line (chat purity untouched).
Polish, bounded: a 2 px accent strip under the top bar
follows the live status colour, and the SYSTEM panel
gains a GPU row (guarded nvidia-smi read, "—" when
unavailable). Layout, panels and behaviours are
otherwise exactly as they were.

v7.2 — HE CAN SEE THE MIC. Under the SYSTEM panel's mic
name, a live mic line (mic_live_text): an 8-cell level
bar fed by ears.get_level() plus "heard Xs ago" from
ears.mic_activity()'s gate-beat stamp. When he speaks
and Nalox hears him, the bar moves and the age stays
small; when the room is silent — or the mic is not
picking him up — the bar sits flat and the age grows.
Guarded end to end: a stats failure leaves the last
text (or "—") and can never break the dashboard.
"""
import logging
import math
import os
import queue
import shutil
import threading
import time
import traceback
from collections import deque

try:
    import ears as _ears  # for the live mic level (same as hud)
except Exception:  # pragma: no cover - orb just stays calm
    _ears = None

try:
    import voice as _voice  # for the speaking ripple (same as hud)
except Exception:  # pragma: no cover - orb just stays calm
    _voice = None

try:
    import logbook as _logbook  # status header + failure lines
except Exception:  # pragma: no cover
    _logbook = None

log = logging.getLogger("nalox.dashboard")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- palette: near-black blue, IRIS-style -------------------
BG = "#05080f"
PANEL = "#0a1120"
PANEL_EDGE = "#16233d"
FG = "#dbe7ff"
MUTED = "#7d8db0"
ACCENT = "#38bdf8"     # bright sky blue (front orb points)
DEEP = "#1e40af"       # deep blue (back orb points)
YOU_BLUE = "#60a5fa"
NALOX_TEAL = "#2dd4bf"
RED = "#ff6b6b"
AMBER = "#fbbf24"
VIOLET = "#e879f9"
# v5.8 chat bubbles: his lines sit in a deep-blue bubble
# weighted to the RIGHT of the chat panel, Nalox's in a dark
# teal bubble weighted LEFT (Text-tag margins do the
# weighting — see bubble_style).
BUBBLE_YOU = "#16355f"
BUBBLE_NALOX = "#0c2f38"
BUBBLE_ERROR = "#3d1524"
PANEL_STRIP = "#2563eb"
# v7.1: the one-time update banner's deep-green ground
# (its text rides the ONLINE green from STATUS_TEXT).
NOTICE_BG = "#0d2b1a"
NOTICE_FG = "#4ade80"

STATUS_TEXT = {
    "listening": ("● Listening", ACCENT),
    "awake": ("● Awake", AMBER),
    "thinking": ("● Thinking", YOU_BLUE),
    "speaking": ("● Speaking", VIOLET),
    "idle": ("● Standing by", MUTED),
    # v6.2: the opening ceremony's final beat — the pill
    # flips to ONLINE once the panels have lit.
    "online": ("● ONLINE", "#4ade80"),
}

ORB_POINTS = 300
MAX_CHAT_LINES = 200

# v5.5.1: after a failed show attempt, further show() calls
# return False silently for this long — the retry-storm killer.
# One real attempt (and one real log line) per cooldown window,
# no matter how often a caller pokes the dashboard.
FAIL_COOLDOWN_S = 10.0

# Blue palette steps, back (dim) -> front (bright).
_ORB_STEPS = ("#12275e", "#1e40af", "#2563eb",
              "#3b82f6", "#38bdf8", "#7dd3fc")


# ============================================================ orb math
def orb_points(count, rot_y, rot_x):
    """Fibonacci-sphere points, rotated, orthographic projection.

    Returns [(x, y, z), ...] with x/y in [-1, 1] and z the depth
    (-1 = far side, +1 = near side). Pure math — unit-testable.
    """
    pts = []
    n = max(1, int(count))
    golden = math.pi * (3.0 - math.sqrt(5.0))
    cos_x, sin_x = math.cos(rot_x), math.sin(rot_x)
    for i in range(n):
        y = 1.0 - (i / max(1, n - 1)) * 2.0 if n > 1 else 0.0
        r = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden * i + rot_y
        x = math.cos(theta) * r
        z = math.sin(theta) * r
        # tilt the sphere around the X axis
        y2 = y * cos_x - z * sin_x
        z2 = y * sin_x + z * cos_x
        pts.append((x, y2, z2))
    return pts


def orb_radius_factor(t, level, speaking, intro=1.0):
    """The orb's scale: breathe idle, swell with his voice,
    ripple while Nalox speaks, scale in on open (intro 0..1)."""
    factor = 1.0 + 0.045 * math.sin(t * 0.9)          # breathing
    if speaking:
        factor += 0.10 + 0.06 * math.sin(t * 6.5)     # ripple
    elif level and level > 0.02:
        factor += min(0.35, float(level) * 0.45)      # his voice
    intro = max(0.0, min(1.0, float(intro)))
    return factor * intro


def orb_color(z):
    """Blue shade for a point at depth z (-1..1)."""
    idx = int((max(-1.0, min(1.0, z)) + 1.0) / 2.0 * len(_ORB_STEPS))
    return _ORB_STEPS[min(idx, len(_ORB_STEPS) - 1)]


def ring_points(count, rot, tilt_x=0.9):
    """Points on a flat halo RING around the orb (v5.7): a
    circle in 3D, tilted like the sphere, projected the same
    way. The frame rotates it AGAINST the sphere's spin — a
    slow counter-rotating halo. Returns [(x, y, z), ...]
    with x/y in [-1, 1]. Pure math — unit-testable."""
    pts = []
    n = max(1, int(count))
    cos_x, sin_x = math.cos(tilt_x), math.sin(tilt_x)
    for i in range(n):
        a = (2.0 * math.pi * i / n) + rot
        x, z = math.cos(a), math.sin(a)
        y2 = 0.0 * cos_x - z * sin_x
        z2 = 0.0 * sin_x + z * cos_x
        pts.append((x, y2, z2))
    return pts


# v5.7: his round logo lives at the CENTER of the orb (his
# order: "আমার Nalox-এর logo টা include দেবা"). The logo is
# pre-rendered once at these diameters; each frame picks the
# nearest size to the orb's pulsing inner diameter, so the
# logo breathes WITH the orb without a per-frame PIL resize
# (the 30 fps budget survives).
LOGO_SIZES = (56, 72, 88, 104, 120, 136, 152, 176, 200)


def logo_px_for(radius, sizes=LOGO_SIZES):
    """The pre-rendered logo diameter nearest to the orb's
    current inner diameter (radius * 1.04), clamped to the
    available sizes. Pure — unit-testable. None when no
    sizes exist (no logo available)."""
    if not sizes:
        return None
    target = max(1.0, float(radius) * 1.04)
    return min(sizes, key=lambda s: abs(s - target))


# ============================================================ system stats
# STDLIB ONLY. Every collector returns None off Windows or on
# any failure — the panel then shows "—" instead of lying.

def _win_filetimes():
    """(idle, kernel, user) 100-ns ticks from GetSystemTimes."""
    try:
        import ctypes

        class _FT(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]

        idle, kernel, user = _FT(), _FT(), _FT()
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel),
                ctypes.byref(user)):
            return None

        def _v(ft):
            return (ft.hi << 32) | ft.lo
        return _v(idle), _v(kernel), _v(user)
    except Exception:
        return None


def cpu_percent_from(prev, cur):
    """Pure delta math for GetSystemTimes samples.

    Kernel time INCLUDES idle time, so busy = 1 - idle/total.
    """
    if not prev or not cur:
        return None
    idle_d = cur[0] - prev[0]
    total_d = (cur[1] - prev[1]) + (cur[2] - prev[2])
    if total_d <= 0:
        return None
    pct = 100.0 * (1.0 - idle_d / total_d)
    return max(0.0, min(100.0, pct))


def _win_memory():
    """(load_percent, used_bytes, total_bytes) or None."""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(ms)):
            return None
        return (int(ms.dwMemoryLoad),
                int(ms.ullTotalPhys - ms.ullAvailPhys),
                int(ms.ullTotalPhys))
    except Exception:
        return None


def ram_percent_from(mem):
    """(load%, used, total) tuple -> percent float (or None)."""
    if not mem:
        return None
    return float(mem[0])


def _win_power():
    """(percent, charging) or None (percent None = unknown)."""
    try:
        import ctypes

        class _PS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        ps = _PS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(
                ctypes.byref(ps)):
            return None
        pct = int(ps.BatteryLifePercent)
        if pct < 0 or pct > 100:
            pct = None  # 255 = unknown
        return pct, int(ps.ACLineStatus) == 1
    except Exception:
        return None


def battery_from(power):
    """(percent, charging) tuple -> (percent|None, charging)."""
    if not power:
        return None, False
    return power[0], bool(power[1])


def disk_percent(path=None):
    """Used-percent of the disk holding the install (or path)."""
    try:
        usage = shutil.disk_usage(path or BASE_DIR)
        if usage.total <= 0:
            return None
        return 100.0 * usage.used / usage.total
    except Exception:
        return None


# v7.1: GPU utilization for the SYSTEM panel — a guarded
# nvidia-smi read, cached for GPU_REFRESH_S (the panel
# ticks every second and must not spawn a process every
# tick). None when the tool/driver is absent — the row
# then shows "—", exactly like an unavailable battery.
GPU_REFRESH_S = 10.0
_GPU_CACHE = {"at": 0.0, "pct": None}


def gpu_percent():
    """GPU utilization % via nvidia-smi, or None. Never
    raises, never blocks past the tool's own timeout."""
    now = time.monotonic()
    if now - _GPU_CACHE["at"] < GPU_REFRESH_S:
        return _GPU_CACHE["pct"]
    _GPU_CACHE["at"] = now
    pct = None
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        lines = (out.stdout or "").strip().splitlines()
        if lines:
            pct = max(0, min(100,
                             int(float(lines[0].strip()))))
    except Exception:
        pct = None
    _GPU_CACHE["pct"] = pct
    return pct


def running_version(base_dir=None):
    """The running version, read from version.txt (v7.1) —
    the SAME file nalox.py's boot line reads, so the
    header badge can never drift from the shipped
    version. "?" when the file is unreadable."""
    try:
        with open(os.path.join(base_dir or BASE_DIR,
                               "version.txt"),
                  encoding="utf-8") as fh:
            return fh.read().strip() or "?"
    except Exception:
        return "?"


def update_notice_text(version):
    """The one-time update banner's line (v7.1): the
    version from the updater's marker + this release's
    headline in the owner's words. Pure."""
    version = str(version or "?").strip() or "?"
    return (f"✅ Updated to v{version} — শোনা আর আটকাবে না, "
            "greeting সঙ্গে সঙ্গে বলবে")


def collect_stats(prev_cpu_sample):
    """One stats snapshot. Returns (stats, new_cpu_sample).

    stats keys: cpu, ram, disk (percents or None),
    battery (percent or None), charging (bool). Never raises.
    """
    stats = {"cpu": None, "ram": None, "disk": None,
             "battery": None, "charging": False,
             "gpu": None}
    sample = _win_filetimes()
    if sample is not None and prev_cpu_sample is not None:
        stats["cpu"] = cpu_percent_from(prev_cpu_sample, sample)
    stats["ram"] = ram_percent_from(_win_memory())
    stats["disk"] = disk_percent()
    stats["gpu"] = gpu_percent()
    stats["battery"], stats["charging"] = battery_from(_win_power())
    return stats, (sample if sample is not None else prev_cpu_sample)


def mic_live_text(level, loud_age_s):
    """The SYSTEM panel's live mic line (v7.2). Pure.

    (smoothed mic level 0..1, seconds since a chunk last beat
    the gate — None when nothing has beaten it since boot)
    -> one display line: an 8-cell level bar plus the age of
    the last heard speech energy, so the owner can SEE the
    mic hearing him (bar moving, age small) or not hearing
    him (bar flat, age growing)."""
    try:
        lvl = max(0.0, min(1.0, float(level)))
    except Exception:
        lvl = 0.0
    filled = int(round(lvl * 8))
    bar = "█" * filled + "░" * (8 - filled)
    if loud_age_s is None:
        age = "no speech heard yet"
    else:
        secs = int(loud_age_s)
        if secs < 2:
            age = "hearing you now"
        elif secs < 60:
            age = f"heard {secs}s ago"
        else:
            age = f"heard {secs // 60}m ago"
    return f"🎙 {bar} · {age}"


# ============================================================ chat feed
def parse_chat_line(text):
    """Map one hudlog() line to (who, body) for the CHAT panel.

    Same prefix convention the HUD renders:
      "NALOX: ..."        -> ("nalox", body)
      "[mic] heard: ..."  -> ("you", body)
      "[error] ..."       -> ("error", whole line)
      anything else       -> ("sys", whole line)
    """
    text = str(text)
    if text.startswith("NALOX: "):
        return "nalox", text[len("NALOX: "):]
    if text.startswith("[mic] heard: "):
        return "you", text[len("[mic] heard: "):]
    if text.startswith("[error]"):
        return "error", text
    return "sys", text


# v6.3 CHAT PURITY (owner's order, 2026-11-15 18:25 IST:
# "শুধু ন্যালক্স আর ইউ-র চ্যাট দেখাবে" — the CHAT panel shows
# ONLY the conversation). The v6.2 field screenshot showed
# the chat polluted with [timing] / [sys] follow-up / [ears]
# restart / [voice] / [ERROR] lines. The selection below is
# the ONLY door into the chat model: genuine conversation
# lines (his "[mic] heard:" lines and Nalox's "NALOX:"
# replies) pass; everything else is excluded HERE and only
# here — the full unfiltered stream still flows to the
# 📋 Log page (logbook) exactly as before.
CHAT_WHO = ("you", "nalox")


def chat_selection(lines):
    """The CHAT panel's line selection (v6.3): from raw
    hudlog lines, the (who, body) pairs for genuine
    conversation lines only — YOU + NALOX, in order. Pure —
    unit-testable; Dashboard.post routes through the same
    predicate."""
    out = []
    for line in lines or []:
        who, body = parse_chat_line(line)
        if who in CHAT_WHO:
            out.append((who, body))
    return out


# v5.8: bubble styling as pure data (unit-testable). The
# Text widget applies these per tag: background paints the
# bubble, lmargin/rmargin weight it to one side of the
# panel, spacing gives each bubble its breathing room.
def bubble_style(who):
    """Tag options for one chat bubble kind."""
    if who == "you":
        return {"background": BUBBLE_YOU, "lmargin1": 110,
                "lmargin2": 110, "rmargin": 6,
                "spacing1": 2, "spacing3": 6}
    if who == "nalox":
        return {"background": BUBBLE_NALOX, "lmargin1": 6,
                "lmargin2": 6, "rmargin": 110,
                "spacing1": 2, "spacing3": 6}
    if who == "error":
        return {"background": BUBBLE_ERROR, "lmargin1": 6,
                "lmargin2": 6, "rmargin": 6,
                "spacing1": 2, "spacing3": 6}
    return {"lmargin1": 6, "lmargin2": 6, "rmargin": 6,
            "spacing1": 1, "spacing3": 3}


_THINK_FRAMES = ("● ○ ○", "○ ● ○", "○ ○ ●", "○ ○ ○")


def thinking_frame(t):
    """The animated thinking indicator for time t (v5.8):
    three dots chasing each other. Pure — unit-testable.
    Rendered under the chat while the brain status is
    "thinking"; driven by the orb's existing ~30 fps loop,
    so it costs no second timer."""
    phase = int(max(0.0, float(t)) * 2.5) % len(_THINK_FRAMES)
    return "Thinking  " + _THINK_FRAMES[phase]


# ============================================================ ceremony (v6.2)
CEREMONY_SECONDS = 1.0


def ceremony_phase(elapsed):
    """The opening ceremony's staging for `elapsed` seconds
    since the window opened (v6.2). Pure — unit-testable.

    Returns (progress, left_lit, right_lit, online):
      progress 0..1 across CEREMONY_SECONDS — the window
        fade + orb scale/spin-up ride it;
      left_lit from 45% (the SYSTEM panel lights);
      right_lit from 70% (the CHAT panel lights);
      online from 95% (the status pill flips to ONLINE).
    """
    try:
        p = float(elapsed) / CEREMONY_SECONDS
    except Exception:
        p = 1.0
    p = max(0.0, min(1.0, p))
    return (p, p >= 0.45, p >= 0.70, p >= 0.95)


def format_uptime(seconds):
    """Session uptime as "45s" / "2m 05s" / "1h 02m"
    (v6.2, the SYSTEM panel's Uptime row). Pure."""
    try:
        s = int(max(0.0, float(seconds)))
    except Exception:
        return "—"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _show_gen(payload):
    """The generation carried by a ("show", gen) command
    payload, or None when the payload is not a show command.
    (The legacy bare "show" string counts as generation-less
    and returns -1: still a show, but never equal to a live
    generation — v5.8 senders always attach the generation.)"""
    if payload == "show":
        return -1
    if isinstance(payload, tuple) and len(payload) == 2 \
            and payload[0] == "show":
        return payload[1]
    return None


# ============================================================ the window
class Dashboard:
    """Thread-safe handle to the Command Center window.

    v5.5.1: the window is a Toplevel hosted on the HUD's Tk
    root (see attach()); this class owns NO interpreter and NO
    UI thread. Public API (safe from any thread, never raises):
        attach(hud), start(), show() -> bool, hide(),
        post(text), set_status(state), set_brain(text),
        is_visible(), stop()
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self._queue = queue.Queue(maxsize=500)
        self._failed = False
        self._thread = None
        self._ready = threading.Event()
        self._visible = False
        self._status_state = "listening"
        self._brain_text = None
        self._chat = deque(maxlen=MAX_CHAT_LINES)
        self._chat_lock = threading.Lock()
        # v6.5 LIVE CHAT SYNC: the streaming NALOX bubble —
        # while a reply is being spoken, its entry in the chat
        # model is the LAST one and its body grows chunk by
        # chunk (begin_nalox_reply / append_nalox_chunk /
        # end_nalox_reply, driven from nalox.py's say() via
        # voice's on_chunk callback). _tk_stream_text is the
        # Tk-thread mirror of what the open bubble has
        # rendered so far (Tk thread only).
        self._stream_open = False
        self._stream_parts = []
        self._tk_stream_text = None
        # Tk thread only: True when the live bubble already
        # carries its trailing newline (it was rendered whole
        # by a rebuild) — _tk_end_stream must not add another.
        self._tk_stream_has_nl = False
        # v6.7 F LIVE HEARING PREVIEW: while the owner speaks
        # a command, a YOU bubble is open in the model and its
        # body is REPLACED by each partial transcription (the
        # Gemini-app feel: his words appear as he speaks).
        # The final transcript finalizes the same bubble —
        # via end_you_preview (the ears sink) or via post()
        # when the "[heard]" line lands, whichever is first;
        # the loser is absorbed (_preview_final_body dedupe).
        # _tk_preview_text mirrors the rendered body (Tk only).
        self._preview_open = False
        self._preview_final_body = None
        self._preview_final_at = 0.0
        self._tk_preview_text = None
        self._tk_preview_has_nl = False
        # Test seam: when True, the state machine runs WITHOUT
        # tkinter (no display calls at all) on a helper thread.
        self._force_headless = False
        # v5.5.1 hosting state: the HUD that owns the one Tk
        # interpreter, and whether the Toplevel got built.
        self._hud = None
        self._started = False
        self._build_queued = False
        self._built = False
        # v5.5.1 attempt bookkeeping: show() attempts are
        # serialized, a failure is logged once per attempt, and
        # a failed attempt starts FAIL_COOLDOWN_S of silence.
        self._show_lock = threading.Lock()
        self._last_fail_at = 0.0
        self.last_error = ""
        # v5.8 close-bulletproofing: the show/hide GENERATION.
        # Every show attempt carries the generation it was
        # issued under; hide() (and a timed-out show) bumps it,
        # so a queued or in-flight show from before a close is
        # recognised as stale on the Tk thread and never opens
        # the window late — the desync that made the Command
        # Center unclosable in the field.
        self._gen = 0
        self._esc_bound = False     # bind_all <Escape> active
        self._thinking_label = None
        # v5.8: "Make your own command" form widgets (Tk
        # thread only): phrase/target entries, the action
        # variable, the hint line, and the saved-commands list.
        self._cc_phrase = None
        self._cc_target = None
        self._cc_action_var = None
        self._cc_hint = None
        self._cc_list = None
        # Tk-thread-only state (touched solely on the HUD thread):
        self._root = None          # the Toplevel window itself
        self._win_open = False     # Toplevel currently deiconified
        self._orb_canvas = None
        self._chat_text = None
        self._status_label = None
        self._level_label = None
        self._clock_label = None
        self._brain_label = None
        self._mic_label = None
        self._mic_live_label = None  # v7.2: live mic readout
        self._stat_widgets = {}
        self._logo_img = None
        # v5.7: the orb-centre logo, pre-rendered at LOGO_SIZES
        # (list of (px, PhotoImage)), + the halo's own rotation.
        self._orb_logo_imgs = []
        self._rot2 = 0.0
        self._show_event = None
        self._show_result = False
        self._show_error = ""
        # v6.1: the Tk thread's ident (captured in _tk_build)
        # — show() performs inline when its caller already IS
        # that thread — plus the pending-show bookkeeping for
        # the dispatched path: a show already on its way is
        # never dispatched twice, and a lost one expires.
        self._tk_thread_id = None
        self._show_pending = False
        self._show_pending_at = 0.0
        self._poll_on = False
        self._anim_on = False
        self._stats_on = False
        self._intro_t0 = 0.0
        self._rot = 0.0
        self._cpu_sample = None
        self._chat_dirty = True
        # v6.2 ceremony + header/panel state: the boot clock
        # (this Dashboard is constructed in nalox.py's boot,
        # so its age IS the session uptime), the ceremony's
        # done-flag, the panels/strips it lights, the BIG
        # header Level widgets, and the new SYSTEM rows.
        self._boot_mono = time.monotonic()
        self._ceremony_done = True   # no ceremony until a show
        self._left_panel = None
        self._right_panel = None
        self._left_strip = None
        self._right_strip = None
        self._level_big_label = None
        self._level_word_label = None
        self._level_bar = None
        self._phone_label = None
        self._cmds_label = None
        self._uptime_label = None
        # v7.1: the version badge + the one-time update
        # banner + the status accent strip. _update_notice
        # is any-thread state (set by nalox.py when the
        # updater marker pops); the widgets are Tk-thread
        # only, and the pending text is consumed by
        # _tk_apply_update_notice exactly once.
        self._update_notice = None
        self._version_label = None
        self._notice_bar = None
        self._notice_label = None
        self._top_strip = None

    # ------------------------------------------------ public API
    def attach(self, hud):
        """Host the Command Center on the app window (hud.Hud).

        The dashboard becomes a Toplevel on the HUD's Tk root;
        its build and every later widget call run on the HUD's
        thread via hud.run_on_tk / the root's after() chain.
        Call before or after start() — the build is queued as
        soon as both have happened. Never raises.
        """
        try:
            self._hud = hud
            if self._started:
                self._queue_build()
        except Exception:
            pass

    def start(self):
        """Prepare the window. Returns immediately.

        Real mode: queue the Toplevel build on the HUD thread
        (needs attach() first — with no host there is nothing
        to build on, and show() will say so, once). Headless
        test mode: spawn the state-machine thread instead.
        """
        if self._force_headless:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run_headless, daemon=True,
                    name="nalox-dashboard")
                self._thread.start()
            return
        self._started = True
        self._queue_build()

    def show(self):
        """Bring the Command Center up. Never raises.

        v6.1: NO confirmation round-trip (see the module
        header for the field failure that killed the old
        handshake). The show is PERFORMED on the Tk thread
        and the window's real mapped state is the only
        truth:
          - called ON the Tk thread (the HUD 🖥 button —
            its callback runs inside the mainloop) -> the
            show is performed inline, synchronously: waiting
            for a queue drain here would deadlock the
            mainloop against itself;
          - called from any other thread -> dispatched via
            hud.run_on_tk (the HUD's own pump queue, FIFO
            behind the build, so a show asked for before the
            root is ready lands once it is) and the caller
            waits briefly for the verdict; a wait that
            expires is NOT a failure — the request stays
            queued, lands when the pump reaches it, and
            show() returns True ("accepted") instead of
            cancelling it the way the old 3 s timeout did.
        True = the window is up, or queued to come up (the
        performer logs the real state if it truly can't —
        v6.2: it never substitutes the plain window; the
        Command Center is the only wake/start surface).
        False = a verified
        failure (real reason logged, once per attempt) or
        the post-failure cooldown.
        """
        try:
            if self._failed:
                return False
            if self._visible:
                return True
            self.start()
            if self._force_headless:
                self._visible = True
                return True
            if self._hud is None:
                self._fail_structural(
                    "Command Center has no app window to open "
                    "on — it lives inside the Nalox app window, "
                    "which is off.")
                return False
            with self._show_lock:
                if self._visible:
                    return True
                if self._show_pending and \
                        time.monotonic() - self._show_pending_at \
                        < 10.0:
                    return True  # a show is already on its way
                if time.monotonic() - self._last_fail_at \
                        < FAIL_COOLDOWN_S:
                    return False  # cooldown: silent, no retry
                gen = self._gen
                if self._tk_thread_id is not None and \
                        threading.get_ident() == self._tk_thread_id:
                    # ON the Tk thread: perform it right here.
                    self._tk_perform_show(gen)
                    return bool(self._show_result)
                event = threading.Event()
                self._show_event = event
                self._show_result = False
                self._show_error = ""
                self._show_pending = True
                self._show_pending_at = time.monotonic()
                # FIFO: the build (queued by start()/attach())
                # sits ahead of this callback in the HUD's
                # queue, so a not-yet-built dashboard is built
                # first and shown second.
                self._queue_build()
                run = getattr(self._hud, "run_on_tk", None)
                if not callable(run):
                    self._show_pending = False
                    self._fail_structural(
                        "Command Center unavailable: the app "
                        "window cannot host it (no run_on_tk "
                        "hook).")
                    return False
                try:
                    run(lambda: self._tk_perform_show(gen))
                except Exception:
                    self._show_pending = False
                    raise
                if event.wait(timeout=2.0):
                    return bool(self._show_result)
                # No verdict yet — the Tk pump hasn't reached
                # it (a busy boot). NOT a failure: the request
                # stays queued and lands when the pump runs,
                # and the performer logs the real outcome
                # either way.
                return True
        except Exception:
            try:
                self._note_attempt_failure(
                    "Command Center show crashed:\n"
                    + traceback.format_exc())
            except Exception:
                pass
            return False

    # ------------------------------------------------ show (Tk thread)
    def _window_state(self):
        """(state, viewable) read from the REAL window, on
        the Tk thread — (None, None) when there is nothing
        to read (no window yet, or a test stub in its
        place). v6.1: this read-back, not a confirmation
        callback, is the show's source of truth.
        update_idletasks() runs first, so a just-deiconified
        window has had its mapping events processed before
        it is judged."""
        root = self._root
        if root is None:
            return None, None
        try:
            root.update_idletasks()
        except Exception:
            pass
        try:
            state = root.state()
        except Exception:
            state = None
        try:
            viewable = bool(root.winfo_viewable())
        except Exception:
            viewable = None
        return state, viewable

    def _window_state_text(self):
        """The real window state as one loggable fragment —
        what failure lines carry instead of the old generic
        confirmation-timeout line."""
        state, viewable = self._window_state()
        geo = "?"
        try:
            if self._root is not None:
                geo = self._root.geometry()
        except Exception:
            pass
        return (f"state={state}, viewable={viewable}, "
                f"geometry={geo}")

    def _finish_show(self, ok, err):
        """Publish a show attempt's verdict (v6.1): remember
        the result for any waiting show() caller, wake it,
        and clear the pending flag so the next show() can
        dispatch afresh. Logging is the caller's job (via
        _note_attempt_failure) — this is bookkeeping only."""
        try:
            self._show_result = bool(ok)
            self._show_error = err or ""
            self._show_pending = False
            event, self._show_event = self._show_event, None
            if event is not None:
                event.set()
        except Exception:
            pass

    def _tk_perform_show(self, gen):
        """Perform one show attempt ON THE TK THREAD (v6.1):
        inline from show() when its caller already is the Tk
        thread, via hud.run_on_tk otherwise, or from the
        legacy queue drain — one code path judges every
        show. _tk_show does the deiconify/place/lift work;
        the verdict comes from the window's real mapped
        state read back here."""
        try:
            if gen != self._gen:
                # A close landed after this show was issued:
                # the close wins, quietly (not a failure).
                self._finish_show(
                    False, "show cancelled by a later close")
                return
            ok, err = False, ""
            try:
                ok, err = self._tk_show()
            except Exception:
                ok, err = False, traceback.format_exc()
            if not ok:
                self._note_attempt_failure(
                    err or "Command Center show failed for an "
                           "unknown reason.")
                self._finish_show(False, err or "")
                return
            state, viewable = self._window_state()
            if self._root is None or viewable or \
                    state in ("normal", "zoomed"):
                self._visible = True
                self._finish_show(True, "")
                return
            # _tk_show claims success but the window does not
            # read as mapped yet — mapping can lag a beat
            # behind deiconify, so accept the show for now
            # and let ONE deferred recheck deliver the final
            # verdict (see _tk_verify_show).
            self._visible = True
            self._finish_show(True, "")
            try:
                self._root.after(
                    150, lambda: self._tk_verify_show(gen))
            except Exception:
                self._tk_verify_show(gen)
        except Exception:
            try:
                self._note_attempt_failure(
                    "Command Center show crashed:\n"
                    + traceback.format_exc())
            except Exception:
                pass
            try:
                self._finish_show(False, "show crashed")
            except Exception:
                pass

    def _tk_verify_show(self, gen):
        """Deferred visibility recheck (v6.1, Tk thread):
        the window was deiconified but did not read as
        mapped at perform time. Reading as mapped now =
        all is well. A close that superseded the show =
        stay silent (its own lines stand). STILL not
        mapped = say so with the REAL window state and mark
        the attempt failed.
        v6.2: the normal window is NO LONGER raised as a
        fallback — the owner's rule is that wake-up (and
        every start) surfaces the Command Center ONLY; the
        plain window stays down. The failure is logged with
        its real state, and that is all."""
        try:
            if gen != self._gen or not self._win_open:
                return  # a close won meanwhile
            state, viewable = self._window_state()
            if viewable or state in ("normal", "zoomed"):
                self._visible = True
                return
            self._visible = False
            self._note_attempt_failure(
                "Command Center window did not become "
                "visible (" + self._window_state_text() + ").")
        except Exception:
            pass

    def hide(self):
        """Hide the Command Center (back to the normal window).

        v5.8: THE one close path — the ✕ button, the labelled
        "✕ Close" button, Escape (bind_all while visible),
        WM_DELETE_WINDOW, voice "dashboard_close" and the
        standby branch in nalox.py all end here. It NEVER
        gates on the visible flag (that gate, against a
        desynced flag, is what trapped the window on screen):
        it bumps the generation (cancelling any pending or
        in-flight show), clears the flag, and ALWAYS queues
        the hide when a window exists or might exist. The Tk
        side logs the real outcome — closed / was not open /
        failed — so a close is never silent. Non-blocking:
        safe to call from a Tk callback. Never raises."""
        try:
            self._gen += 1  # cancel any pending/in-flight show
            self._show_pending = False  # v6.1: a queued show is
            # cancelled by the generation bump above; the next
            # show() must be free to dispatch afresh.
            was_visible = self._visible
            self._visible = False
            if self._force_headless:
                self._send(("cmd", "hide"))
                self._log_line(
                    "SYSTEM",
                    "[dashboard] Command Center closed."
                    if was_visible else
                    "[dashboard] close: Command Center was "
                    "not open.")
                return
            if self._failed:
                self._log_line(
                    "SYSTEM",
                    "[dashboard] close: Command Center is not "
                    "running (it failed to start) — nothing "
                    "to close.")
                return
            if not self._built:
                self._log_line(
                    "SYSTEM",
                    "[dashboard] close: Command Center was "
                    "not open.")
                return
            # The Tk thread performs the hide and logs the
            # outcome itself (see _tk_hide).
            self._send_cmd(("cmd", "hide"))
        except Exception:
            pass

    def is_visible(self):
        return bool(self._visible)

    def post(self, text):
        """Feed one line (same lines hudlog posts).

        v6.3 CHAT PURITY: only genuine conversation lines
        (YOU + NALOX — see chat_selection) enter the chat
        model; system/ears/timing/voice/error lines stop
        here. They are NOT lost — hudlog mirrors every line
        to the logbook / 📋 Log page independently of this
        panel."""
        try:
            who, body = parse_chat_line(text)
            if who not in CHAT_WHO:
                return
            with self._chat_lock:
                if who == "you" and self._preview_open:
                    # v6.7 F: the final "[heard]" line FINALIZES
                    # the open preview bubble (same bubble, final
                    # words) instead of adding a second one.
                    if self._chat and self._chat[-1][0] == "you":
                        self._chat[-1] = ("you", body)
                    self._preview_open = False
                    self._preview_final_body = body
                    self._preview_final_at = time.monotonic()
                    self._send(("chat_pend", body))
                    return
                if who == "you" and self._preview_final_body \
                        is not None and \
                        body == self._preview_final_body and \
                        time.monotonic() - self._preview_final_at \
                        < 5.0:
                    # The preview already finalized this exact
                    # line (the ears sink beat the log line to
                    # it) — absorb the duplicate. Time-bounded:
                    # a genuinely repeated command later is a
                    # new line, never absorbed.
                    self._preview_final_body = None
                    return
                if who == "you":
                    self._preview_final_body = None
                self._chat.append((who, body))
            self._send(("chat", (who, body)))
        except Exception:
            pass

    # --------------------------------------- v6.7 F hearing preview
    def begin_you_preview(self):
        """Open the live YOU bubble for a command being
        spoken (v6.7 F): an empty "you" entry enters the
        model; update_you_preview replaces its body with
        each partial transcription."""
        try:
            with self._chat_lock:
                if self._preview_open:
                    # A stale preview (its recording died
                    # before finishing) — discard it so this
                    # session starts clean.
                    if self._chat and \
                            self._chat[-1][0] == "you":
                        self._chat.pop()
                    self._send(("chat_pcancel", None))
                self._preview_open = True
                self._preview_final_body = None
                self._chat.append(("you", ""))
            self._send(("chat_pbegin", None))
        except Exception:
            pass

    def update_you_preview(self, text):
        """Replace the live bubble's body with the newest
        partial (v6.7 F). Partials REPLACE — each one is a
        fresh decode of everything said so far, not a delta."""
        try:
            text = str(text or "").strip()
            if not text:
                return
            with self._chat_lock:
                if not self._preview_open:
                    return
                if self._chat and self._chat[-1][0] == "you":
                    self._chat[-1] = ("you", text)
            self._send(("chat_pupdate", text))
        except Exception:
            pass

    def end_you_preview(self, final_text):
        """Finalize the live bubble with the FINAL transcript
        (v6.7 F) — the words the brain will actually receive.
        The matching "[heard]" log line, when it lands in
        post(), is absorbed by the _preview_final_body
        dedupe instead of doubling the bubble."""
        try:
            final_text = str(final_text or "").strip()
            with self._chat_lock:
                if not self._preview_open:
                    return
                self._preview_open = False
                if final_text:
                    if self._chat and \
                            self._chat[-1][0] == "you":
                        self._chat[-1] = ("you", final_text)
                    self._preview_final_body = final_text
                    self._preview_final_at = time.monotonic()
            self._send(("chat_pend", final_text))
        except Exception:
            pass

    def cancel_you_preview(self):
        """Discard the live bubble (v6.7 F): the recording
        produced nothing the brain will hear (silence,
        garbage) — the partial was never a real line, so it
        leaves no trace in the chat."""
        try:
            with self._chat_lock:
                if not self._preview_open:
                    return
                self._preview_open = False
                if self._chat and self._chat[-1][0] == "you":
                    self._chat.pop()
            self._send(("chat_pcancel", None))
        except Exception:
            pass

    # --------------------------------------- v6.5 live chat sync
    def begin_nalox_reply(self):
        """Open the streaming NALOX bubble for a reply that is
        about to be spoken (v6.5). The bubble enters the chat
        model EMPTY; append_nalox_chunk grows it in step with
        the voice. A stale still-open stream is closed in the
        model first (its text stays as it was spoken)."""
        try:
            with self._chat_lock:
                self._stream_open = True
                self._stream_parts = []
                self._chat.append(("nalox", ""))
            self._send(("chat_begin", None))
        except Exception:
            pass

    def append_nalox_chunk(self, chunk):
        """Grow the streaming bubble by one spoken sentence
        (v6.5). The model body is the chunks joined by single
        spaces — exactly the reply text as spoken. A chunk
        with no open stream opens one implicitly (a lost
        begin must never lose the words)."""
        try:
            chunk = str(chunk or "").strip()
            if not chunk:
                return
            with self._chat_lock:
                if not self._stream_open:
                    self._stream_open = True
                    self._stream_parts = []
                    self._chat.append(("nalox", ""))
                self._stream_parts.append(chunk)
                body = " ".join(self._stream_parts)
                if self._chat and self._chat[-1][0] == "nalox":
                    self._chat[-1] = ("nalox", body)
            self._send(("chat_chunk", chunk))
        except Exception:
            pass

    def end_nalox_reply(self):
        """Close the streaming bubble (v6.5): the reply is
        fully spoken (or was interrupted — the bubble keeps
        exactly the chunks that were spoken)."""
        try:
            with self._chat_lock:
                self._stream_open = False
                self._stream_parts = []
            self._send(("chat_end", None))
        except Exception:
            pass

    def set_status(self, state):
        state = str(state).strip().lower()
        self._status_state = state
        self._send(("status", state))

    def set_brain(self, text):
        self._brain_text = str(text)
        self._send(("brain", str(text)))

    def set_update_notice(self, version):
        """v7.1: queue the one-time update banner. Called
        by nalox.py when the updater's marker pops at boot
        — the marker is already deleted by then, so this
        can never repeat. The banner renders at the next
        build / visible tick and clears itself as it
        renders (see _tk_apply_update_notice). A UI
        element only: nothing enters the chat model.
        Never raises."""
        try:
            self._update_notice = update_notice_text(version)
        except Exception:
            pass

    def _tk_apply_update_notice(self):
        """Tk thread: render the pending update banner
        ONCE (v7.1). The pending text is cleared BEFORE
        rendering, so no later build, show or tick can
        ever repeat it — the banner shows on the first
        Command Center open after the update and never
        again."""
        text = self._update_notice
        if not text or self._notice_bar is None:
            return
        self._update_notice = None
        try:
            import tkinter as tk
            self._notice_label = tk.Label(
                self._notice_bar, text=text, bg=NOTICE_BG,
                fg=NOTICE_FG, font=("Segoe UI", 11, "bold"))
            self._notice_label.pack(fill="x", padx=16,
                                    pady=5)
        except Exception:
            pass

    def stop(self):
        try:
            self._gen += 1  # cancel any pending show
            self._show_pending = False
            self._visible = False
            self._poll_on = False
            self._send_cmd(("cmd", "quit"))
        except Exception:
            pass

    # ------------------------------------------------ internals
    def _send(self, item):
        if self._failed:
            return
        try:
            self._queue.put_nowait(item)
        except Exception:
            pass  # queue full / shutting down — never break Nalox

    def _send_cmd(self, item):
        """Queue a COMMAND item (show / hide / quit) so it can
        never be lost (v5.8): unlike chat lines, a hide is not
        expendable — if the bounded queue is full of chat, the
        queue is drained to make room rather than dropping
        the command. (A dropped hide was one road into the
        unclosable-window trap.)"""
        if self._failed:
            return
        try:
            self._queue.put_nowait(item)
            return
        except Exception:
            pass
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass
        try:
            self._queue.put_nowait(item)
        except Exception:
            pass

    def _log_line(self, category, text):
        """One logbook line, guarded (v5.8 — hide outcomes are
        logged through here so a close is never silent)."""
        try:
            if _logbook is not None:
                _logbook.log(category, text)
        except Exception:
            pass
        try:
            log.info("%s", text)
        except Exception:
            pass

    def _fail_structural(self, text):
        """A permanent failure (no host window, no Tk root, the
        build itself crashed): log the REAL error ONCE, then
        stay quietly out of the way — the normal window is the
        fallback. Guarded — never raises."""
        if self._failed:
            return
        self._failed = True
        self.last_error = str(text)
        try:
            log.warning("%s", text)
        except Exception:
            pass
        try:
            if _logbook is not None:
                _logbook.log("ERROR", "[dashboard] " + str(text))
        except Exception:
            pass

    def _note_attempt_failure(self, text):
        """One show attempt failed: remember when + what, and
        log the REAL exception text ONCE for this attempt.
        Repeat triggers inside the cooldown never reach here.
        Guarded — never raises."""
        self._last_fail_at = time.monotonic()
        self.last_error = str(text)
        if self._failed:
            return  # the structural failure was already logged
        try:
            log.warning("Command Center show failed: %s", text)
        except Exception:
            pass
        try:
            if _logbook is not None:
                _logbook.log("ERROR", "[dashboard] Command Center "
                                      "show failed: " + str(text))
        except Exception:
            pass

    # ------------------------------------------------ build (HUD thread)
    def _queue_build(self):
        """Ask the HUD to build the Toplevel on its own thread.
        Runs the failure bookkeeping itself; never raises."""
        if self._built or self._build_queued or self._failed:
            return
        hud = self._hud
        if hud is None:
            return  # attach() will call us again
        if getattr(hud, "_failed", False):
            self._fail_structural(
                "Command Center unavailable: the app window "
                "itself failed to start, so there is no screen "
                "to host it.")
            self._ready.set()
            return
        run = getattr(hud, "run_on_tk", None)
        if not callable(run):
            self._fail_structural(
                "Command Center unavailable: the app window "
                "cannot host it (no run_on_tk hook).")
            self._ready.set()
            return
        self._build_queued = True
        try:
            run(self._tk_build)
        except Exception as exc:
            self._build_queued = False
            self._fail_structural(
                "Command Center build could not be queued: "
                f"{type(exc).__name__}: {exc}")
            self._ready.set()

    def _tk_build(self):
        """Runs ON THE HUD THREAD (via hud.run_on_tk): create
        the Toplevel on the HUD's Tk root and start the queue
        pump. Any failure is structural — logged once, with
        the real traceback."""
        try:
            import tkinter as tk
            # v6.1: remember WHICH thread this is — show()
            # performs inline when its caller is this thread.
            self._tk_thread_id = threading.get_ident()
            host = self._hud.tk_root() \
                if self._hud is not None else None
            if host is None:
                raise RuntimeError(
                    "the app window has no Tk root to host "
                    "the Command Center")
            self._build_widgets(tk, host)
            self._built = True
            self._poll_on = True
            try:
                self._root.after(50, self._poll)
            except Exception:
                pass
        except Exception:
            self._fail_structural(
                "Command Center could not be built:\n"
                + traceback.format_exc())
        finally:
            self._ready.set()

    def _run_headless(self):
        """State-machine-only loop for tests: no display calls.
        Queue items are consumed; a current-generation "show"
        confirms instantly, a stale one (issued before a
        hide) is refused — the same rule the Tk drain runs."""
        self._ready.set()
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                return
            try:
                kind, payload = item
            except Exception:
                continue
            if kind == "cmd" and payload == "quit":
                return
            if kind == "cmd" and _show_gen(payload) is not None:
                gen = _show_gen(payload)
                if gen == self._gen:
                    self._visible = True
                    self._show_result = True
                    self._show_error = ""
                else:
                    self._show_result = False
                    self._show_error = \
                        "show cancelled by a later close"
                if self._show_event is not None:
                    self._show_event.set()
            elif kind == "cmd" and payload == "hide":
                self._visible = False

    def _build_widgets(self, tk, host):
        root = tk.Toplevel(host)
        self._root = root
        root.title("Nalox — Command Center")
        try:
            root.iconbitmap(
                os.path.join(BASE_DIR, "assets", "logo.ico"))
        except Exception:
            pass
        root.configure(bg=BG)
        root.withdraw()  # shown only via show()
        root.protocol("WM_DELETE_WINDOW", self.hide)
        # v5.8: no widget-level <Escape> bind here any more —
        # Escape is bind_all'ed in _tk_show (active only while
        # the dashboard is visible) and unbound in _tk_hide,
        # so one Esc press reaches hide() exactly once, from
        # wherever the focus sits.

        # ---------------- top bar ----------------
        top = tk.Frame(root, bg=PANEL, height=64)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)
        for logo_name in ("logo_round.png", "logo.jpg"):
            try:
                from PIL import Image, ImageTk
                img = Image.open(os.path.join(BASE_DIR, "assets",
                                              logo_name))
                img = img.convert("RGBA")
                img.thumbnail((44, 44))
                self._logo_img = ImageTk.PhotoImage(img)
                break
            except Exception:
                self._logo_img = None
        if self._logo_img is not None:
            tk.Label(top, image=self._logo_img, bg=PANEL).pack(
                side="left", padx=(14, 8), pady=10)
        else:
            tk.Label(top, text="N", bg=PANEL, fg=ACCENT,
                     font=("Segoe UI", 24, "bold")).pack(
                         side="left", padx=(14, 8))
        tk.Label(top, text="NALOX", bg=PANEL, fg=FG,
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(top, text="COMMAND CENTER", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 10)).pack(side="left", padx=(10, 0),
                                              pady=(8, 0))
        # v7.1 VERSION BADGE: the running version, read
        # from version.txt at build time (running_version —
        # the same source as the boot line, never a
        # hard-coded string). The owner could not SEE which
        # version was running and once tested the wrong
        # one; the badge sits in the header permanently.
        self._version_label = tk.Label(
            top, text="v" + running_version(), bg=AMBER,
            fg="#231a04", font=("Segoe UI", 10, "bold"),
            padx=7, pady=1)
        self._version_label.pack(side="left", padx=(10, 0),
                                 pady=(6, 0))
        close_btn = tk.Button(
            top, text="✕", command=self.hide, bg=PANEL, fg=MUTED,
            activebackground=PANEL_EDGE, activeforeground=FG,
            relief="flat", font=("Segoe UI", 14), cursor="hand2",
            padx=12)
        close_btn.pack(side="right", padx=(0, 10))
        # v5.8: a clearly-LABELLED close button beside the ✕ —
        # same one hide() path (the field failure was a close
        # he could not make work at all; the way out must be
        # unmissable). Escape (bind_all while visible) is the
        # third route into the same hide().
        tk.Button(
            top, text="✕ Close", command=self.hide, bg=PANEL,
            fg=FG, activebackground=PANEL_EDGE,
            activeforeground=FG, relief="flat",
            font=("Segoe UI", 11, "bold"), cursor="hand2",
            padx=10).pack(side="right", padx=(0, 2))
        # v6.2: ⚙ Settings + 📋 Log live HERE now too — the
        # plain window must become unnecessary, so everything
        # the owner needs is on this surface. The buttons call
        # the HUD's OWN handlers (hud.Hud._on_settings /
        # _on_log) — literally the same code the app window's
        # buttons run.
        tk.Button(
            top, text="📋 Log", command=self._on_log_btn,
            bg=PANEL, fg=FG, activebackground=PANEL_EDGE,
            activeforeground=FG, relief="flat",
            font=("Segoe UI", 11), cursor="hand2",
            padx=10).pack(side="right", padx=(0, 2))
        tk.Button(
            top, text="⚙ Settings", command=self._on_settings_btn,
            bg=PANEL, fg=FG, activebackground=PANEL_EDGE,
            activeforeground=FG, relief="flat",
            font=("Segoe UI", 11), cursor="hand2",
            padx=10).pack(side="right", padx=(0, 2))
        # v6.2: the ⚡ Level, BIG — number + word + a thin
        # progress bar toward the next level — in the header
        # where the owner asked for it ("the Level system
        # bigger"). Fed by perflevel.level_progress() on the
        # same 1 s tick as the SYSTEM panel.
        level_box = tk.Frame(top, bg=PANEL)
        level_box.pack(side="right", padx=(0, 18))
        tk.Label(level_box, text="⚡", bg=PANEL, fg=AMBER,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        self._level_big_label = tk.Label(
            level_box, text="—", bg=PANEL, fg=FG,
            font=("Segoe UI", 22, "bold"))
        self._level_big_label.pack(side="left", padx=(2, 4))
        level_side = tk.Frame(level_box, bg=PANEL)
        level_side.pack(side="left")
        self._level_word_label = tk.Label(
            level_side, text="Level", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9, "bold"))
        self._level_word_label.pack(anchor="w")
        self._level_bar = tk.Canvas(
            level_side, width=84, height=5, bg=PANEL,
            highlightthickness=0)
        self._level_bar.pack(anchor="w", pady=(2, 0))
        self._clock_label = tk.Label(
            top, text="--:--:--", bg=PANEL, fg=FG,
            font=("Segoe UI", 16, "bold"))
        self._clock_label.pack(side="right", padx=(0, 16))
        text0, fg0 = STATUS_TEXT["listening"]
        self._status_label = tk.Label(
            top, text=text0, bg=PANEL, fg=fg0,
            font=("Segoe UI", 12, "bold"))
        self._status_label.pack(side="right", padx=(0, 16))

        # v7.1 polish: a 2 px accent strip under the top
        # bar that follows the live status colour (the same
        # STATUS_TEXT colour the status pill uses — sky for
        # Listening, amber for Awake, violet for Speaking),
        # refreshed on the SYSTEM tick.
        self._top_strip = tk.Frame(root, bg=fg0, height=2)
        self._top_strip.pack(fill="x", side="top")
        # v7.1: the one-time UPDATE NOTICE banner slot — an
        # empty frame (zero height while empty) under the
        # strip; _tk_apply_update_notice fills it exactly
        # once after an update lands.
        self._notice_bar = tk.Frame(root, bg=NOTICE_BG)
        self._notice_bar.pack(fill="x", side="top")

        # ---------------- body: SYSTEM | ORB | CHAT ----------------
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)

        # v5.7 BEAUTY PASS: the panels get a subtle framed
        # look — a 1 px edge in PANEL_EDGE plus a thin blue
        # accent strip along the top (layered flat frames read
        # as a soft gradient against the near-black body; all
        # stdlib, no new deps).
        left = tk.Frame(body, bg=PANEL, width=264,
                        highlightbackground=PANEL_EDGE,
                        highlightthickness=1)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._left_panel = left
        self._left_strip = tk.Frame(left, bg=PANEL_STRIP, height=2)
        self._left_strip.pack(fill="x")
        tk.Label(left, text="SYSTEM", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 11, "bold")).pack(
                     anchor="w", padx=16, pady=(16, 10))
        for key, label in (("cpu", "CPU"), ("gpu", "GPU"),
                           ("ram", "RAM"),
                           ("disk", "Disk"), ("battery", "Battery")):
            row = tk.Frame(left, bg=PANEL)
            row.pack(fill="x", padx=16, pady=(0, 4))
            tk.Label(row, text=label, bg=PANEL, fg=FG,
                     font=("Segoe UI", 11)).pack(side="left")
            val = tk.Label(row, text="—", bg=PANEL, fg=ACCENT,
                           font=("Segoe UI", 11, "bold"))
            val.pack(side="right")
            bar = tk.Canvas(left, height=6, bg=PANEL,
                            highlightthickness=0)
            bar.pack(fill="x", padx=16, pady=(0, 12))
            self._stat_widgets[key] = (val, bar)
        self._mic_label = tk.Label(
            left, text="🎤 —", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), wraplength=232, justify="left")
        self._mic_label.pack(anchor="w", padx=16, pady=(8, 2))
        # v7.2: the live mic readout — level bar + "heard Xs
        # ago" under the mic name (refreshed by _stats_tick
        # from ears.mic_activity; degrades to "🎙 —").
        self._mic_live_label = tk.Label(
            left, text="🎙 —", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), wraplength=232, justify="left")
        self._mic_live_label.pack(anchor="w", padx=16, pady=(0, 2))
        self._brain_label = tk.Label(
            left, text=self._brain_text or "Brain: checking…",
            bg=PANEL, fg=MUTED, font=("Segoe UI", 10),
            wraplength=232, justify="left")
        self._brain_label.pack(anchor="w", padx=16, pady=(2, 2))
        # v6.0: the ⚡ Nalox Level — measured speed (perflevel
        # over the session's [timing] samples + provider
        # health), refreshed by the same 1 s tick.
        self._level_label = tk.Label(
            left, text="⚡ Nalox Level: —", bg=PANEL, fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
            wraplength=232, justify="left")
        self._level_label.pack(anchor="w", padx=16, pady=(2, 2))
        # v6.2: the SYSTEM panel grows — Phone (the Nalox
        # Phone app's live state), Commands this session
        # (logbook's counter) and Uptime. Every row degrades
        # to "—" when its source is missing.
        self._phone_label = tk.Label(
            left, text="📱 —", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), wraplength=232, justify="left")
        self._phone_label.pack(anchor="w", padx=16, pady=(2, 2))
        self._cmds_label = tk.Label(
            left, text="🎙 Commands this session: —", bg=PANEL,
            fg=MUTED, font=("Segoe UI", 10),
            wraplength=232, justify="left")
        self._cmds_label.pack(anchor="w", padx=16, pady=(2, 2))
        self._uptime_label = tk.Label(
            left, text="⏱ Uptime: —", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), wraplength=232, justify="left")
        self._uptime_label.pack(anchor="w", padx=16, pady=(2, 8))

        right = tk.Frame(body, bg=PANEL, width=360,
                         highlightbackground=PANEL_EDGE,
                         highlightthickness=1)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._right_panel = right
        self._right_strip = tk.Frame(right, bg=PANEL_STRIP,
                                     height=2)
        self._right_strip.pack(fill="x")
        tk.Label(right, text="CHAT", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 11, "bold")).pack(
                     anchor="w", padx=16, pady=(16, 10))
        chat = tk.Text(
            right, bg=PANEL, fg=FG, insertbackground=FG,
            font=("Segoe UI", 11), relief="flat", wrap="word",
            highlightthickness=0, state="disabled", height=12)
        chat.pack(fill="both", expand=True, padx=12, pady=(0, 2))
        chat.tag_configure("you_name", foreground=YOU_BLUE,
                           font=("Segoe UI", 11, "bold"),
                           lmargin1=110, lmargin2=110, rmargin=6)
        chat.tag_configure("nalox_name", foreground=NALOX_TEAL,
                           font=("Segoe UI", 11, "bold"),
                           lmargin1=6, lmargin2=6, rmargin=110)
        chat.tag_configure("body", foreground=FG)
        chat.tag_configure("muted", foreground=MUTED,
                           font=("Segoe UI", 10))
        chat.tag_configure("error", foreground=RED)
        # v5.8: the bubble paints (see bubble_style) — his
        # lines in a blue bubble weighted right, Nalox's in a
        # teal bubble weighted left, errors in a dark red one.
        for tag_name, who in (("you_bubble", "you"),
                              ("nalox_bubble", "nalox"),
                              ("error_bubble", "error"),
                              ("sys_bubble", "sys")):
            chat.tag_configure(tag_name, **bubble_style(who))
        self._chat_text = chat
        # v5.8: the thinking indicator — animated by the orb
        # loop while the brain works (see _anim_tick); blank
        # at all other times.
        self._thinking_label = tk.Label(
            right, text="", bg=PANEL, fg=ACCENT,
            font=("Segoe UI", 11, "bold"))
        self._thinking_label.pack(anchor="w", padx=16,
                                  pady=(0, 4))
        self._build_cc_panel(tk, right)

        center = tk.Frame(body, bg=BG)
        center.pack(side="left", fill="both", expand=True)
        self._orb_canvas = tk.Canvas(center, bg=BG,
                                     highlightthickness=0)
        self._orb_canvas.pack(fill="both", expand=True)
        # v5.7: pre-render his round logo at LOGO_SIZES for the
        # orb's centre (see logo_px_for). Any failure (no PIL,
        # no asset) just leaves the orb logoless, as before.
        self._orb_logo_imgs = []
        for logo_name in ("logo_round.png", "logo.jpg"):
            try:
                from PIL import Image, ImageTk
                src_img = Image.open(
                    os.path.join(BASE_DIR, "assets",
                                 logo_name)).convert("RGBA")
                imgs = []
                for px in LOGO_SIZES:
                    img = src_img.copy()
                    img.thumbnail((px, px))
                    imgs.append((px, ImageTk.PhotoImage(img)))
                self._orb_logo_imgs = imgs
                break
            except Exception:
                self._orb_logo_imgs = []
        # v7.1: a notice queued before this build (the
        # updater marker pops during boot, the window may
        # build after) renders with the window.
        self._tk_apply_update_notice()

    # --------------------------------------- v5.8: his own commands
    def _build_cc_panel(self, tk, parent):
        """The "⭐ Make your own command" form (v5.8) — the
        owner's headline feature: he teaches Nalox HIS phrases
        in HIS words, no coding. Phrase + action + target,
        saved to custom_commands.json (the brain hot-reloads
        it); his saved commands list below with Delete
        buttons; greyed example rows hint at built-ins.
        Runs on the Tk thread inside _build_widgets."""
        import custom_commands as cc
        tk.Frame(parent, bg=PANEL_EDGE, height=1).pack(
            fill="x", padx=12, pady=(2, 8))
        tk.Label(parent, text="⭐ Make your own command",
                 bg=PANEL, fg=FG,
                 font=("Segoe UI", 12, "bold")).pack(
                     anchor="w", padx=16)
        tk.Label(parent, text="Teach Nalox your own words. "
                              "No coding.",
                 bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=16,
                                            pady=(0, 6))

        def _field(label):
            tk.Label(parent, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 10)).pack(
                         anchor="w", padx=16)
            entry = tk.Entry(
                parent, bg="#0d1830", fg=FG,
                insertbackground=FG, relief="flat",
                font=("Segoe UI", 11),
                highlightbackground=PANEL_EDGE,
                highlightthickness=1)
            entry.pack(fill="x", padx=16, pady=(1, 6))
            return entry

        self._cc_phrase = _field("When I say…")
        tk.Label(parent, text="Do this:", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w", padx=16)
        labels = [cc.ACTION_LABELS[a] for a in cc.ACTIONS]
        self._cc_action_var = tk.StringVar(value=labels[0])
        tk.OptionMenu(parent, self._cc_action_var,
                      *labels).pack(fill="x", padx=16,
                                    pady=(1, 6))
        self._cc_target = _field("Open / type / say this…")
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=16, pady=(0, 2))
        tk.Button(
            row, text="💾 Save command", command=self._cc_save,
            bg=DEEP, fg=FG, activebackground=PANEL_EDGE,
            activeforeground=FG, relief="flat",
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            padx=10, pady=3).pack(side="left")
        self._cc_hint = tk.Label(
            parent, text="", bg=PANEL, fg=AMBER,
            font=("Segoe UI", 9), wraplength=320,
            justify="left")
        self._cc_hint.pack(anchor="w", padx=16, pady=(2, 4))
        self._cc_list = tk.Frame(parent, bg=PANEL)
        self._cc_list.pack(fill="x", padx=16)
        tk.Label(parent,
                 text="Try saying:\n"
                      "• “clean my recycle bin”\n"
                      "• “open this PC”\n"
                      "• “Nalox, wake up”",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                 justify="left").pack(anchor="w", padx=16,
                                       pady=(6, 10))
        self._cc_refresh()

    def _cc_refresh(self):
        """Rebuild the saved-commands list from the store
        (Tk thread). Each row: his phrase, the action, and a
        Delete button. Guarded — a broken store shows an
        empty list, never a crash."""
        frame = self._cc_list
        if frame is None:
            return
        try:
            import tkinter as tk
            import custom_commands as cc
            for child in frame.winfo_children():
                child.destroy()
            commands = cc.load_commands_safe()
            if not commands:
                tk.Label(frame, text="No commands yet — "
                                     "teach me one above!",
                         bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 9)).pack(
                             anchor="w")
                return
            for idx, cmd in enumerate(commands):
                row = tk.Frame(frame, bg=PANEL)
                row.pack(fill="x", pady=1)
                label = cc.ACTION_LABELS.get(
                    cmd["action"], cmd["action"])
                text = f"“{cmd['phrase']}” → {label}"
                if cmd.get("target"):
                    text += f": {cmd['target']}"
                tk.Label(row, text=text, bg=PANEL, fg=FG,
                         font=("Segoe UI", 9),
                         wraplength=250,
                         justify="left").pack(side="left")
                tk.Button(
                    row, text="✕ Delete",
                    command=lambda i=idx: self._cc_delete(i),
                    bg=PANEL, fg=RED,
                    activebackground=PANEL_EDGE,
                    activeforeground=FG, relief="flat",
                    font=("Segoe UI", 9), cursor="hand2",
                    padx=6).pack(side="right")
        except Exception:
            pass

    def _cc_save(self):
        """Save button: validate (inline hint, no crash),
        write the store, refresh the list, clear the form.
        The brain hot-reloads the file — the new command
        works on his next utterance. Tk thread; guarded."""
        try:
            import custom_commands as cc
            phrase = self._cc_phrase.get().strip() \
                if self._cc_phrase is not None else ""
            target = self._cc_target.get().strip() \
                if self._cc_target is not None else ""
            label = self._cc_action_var.get() \
                if self._cc_action_var is not None else ""
            action = next(
                (a for a, lab in cc.ACTION_LABELS.items()
                 if lab == label), "")
            problem = cc.validate_command(phrase, action,
                                          target)
            if problem:
                if self._cc_hint is not None:
                    self._cc_hint.configure(text=problem,
                                            fg=RED)
                return
            cc.add_command(phrase, action, target)
            if self._cc_hint is not None:
                self._cc_hint.configure(
                    text=f"Saved ✓ — now say: “{phrase}”",
                    fg=NALOX_TEAL)
            if self._cc_phrase is not None:
                self._cc_phrase.delete(0, "end")
            if self._cc_target is not None:
                self._cc_target.delete(0, "end")
            self._cc_refresh()
            self._log_line(
                "SYSTEM",
                f"[dashboard] custom command saved: "
                f"“{phrase}” → {action}")
        except Exception:
            try:
                if self._cc_hint is not None:
                    self._cc_hint.configure(
                        text="Could not save — try again.",
                        fg=RED)
            except Exception:
                pass

    def _cc_delete(self, index):
        """Delete button for one saved command (Tk thread)."""
        try:
            import custom_commands as cc
            cc.delete_command(index)
            self._cc_refresh()
            if self._cc_hint is not None:
                self._cc_hint.configure(text="Deleted.",
                                        fg=MUTED)
        except Exception:
            pass

    # ------------------------------------------------ show / hide (Tk thread)
    def _tk_show(self):
        """Fullscreen -> maximized -> plain window, in that
        order; then the ~350 ms fade/scale-in.

        Returns (True, "") when the window is really up, or
        (False, real-error-text) — the exception text travels
        back to show(), which logs it once for this attempt.
        """
        root = self._root
        if root is None:
            return False, ("Command Center window does not "
                           "exist (its build did not run).")
        if self._win_open:
            return True, ""
        try:
            root.deiconify()
        except Exception:
            return False, ("Command Center deiconify failed:\n"
                           + traceback.format_exc())
        placed = False
        errors = []
        try:
            root.attributes("-fullscreen", True)
            placed = True
        except Exception as exc:
            errors.append(f"fullscreen: {type(exc).__name__}: {exc}")
        if not placed:
            try:
                root.state("zoomed")  # Windows maximized
                placed = True
            except Exception as exc:
                errors.append(f"zoomed: {type(exc).__name__}: {exc}")
        if not placed:
            try:
                w = root.winfo_screenwidth()
                h = root.winfo_screenheight()
                root.geometry(f"{w}x{h}+0+0")
                placed = True
            except Exception as exc:
                errors.append(f"geometry: {type(exc).__name__}: {exc}")
        if not placed:
            return False, ("Command Center could not be placed "
                           "on screen (" + "; ".join(errors) + ").")
        self._win_open = True
        try:
            root.lift()
            root.focus_force()
        except Exception:
            pass
        # v5.8: Escape works from ANYWHERE while the Command
        # Center is up — bind_all, not just the Toplevel (the
        # old widget-only binding never fired when focus sat
        # outside the dashboard). Unbound again in _tk_hide.
        try:
            root.bind_all("<Escape>", self._on_escape)
            self._esc_bound = True
        except Exception:
            pass
        # v5.8: his saved commands may have changed since the
        # build — refresh the panel's list on every open.
        try:
            self._cc_refresh()
        except Exception:
            pass
        self._intro_t0 = time.monotonic()
        # v6.2: every open replays the opening ceremony.
        self._ceremony_done = False
        try:
            root.attributes("-alpha", 0.0)
            self._fade_step(0)
        except Exception:
            pass  # no alpha support: the window is simply up
        if self._chat_dirty:
            self._rebuild_chat()
        self._anim_on = True
        self._stats_on = True
        try:
            root.after(33, self._anim_tick)
            root.after(50, self._stats_tick)
        except Exception:
            pass
        return True, ""

    def _fade_step(self, step):
        """Alpha 0 -> 1 over ~350 ms (10 steps of 35 ms)."""
        try:
            if not self._win_open:
                return
            frac = min(1.0, (step + 1) / 10.0)
            self._root.attributes("-alpha", frac)
            if frac < 1.0:
                self._root.after(35, lambda: self._fade_step(step + 1))
        except Exception:
            pass

    def _on_escape(self, _event=None):
        """Escape key (bind_all while visible, v5.8): the same
        one hide() every other close route uses."""
        self.hide()

    # --------------------------------------- v6.2 top-bar buttons
    def _on_settings_btn(self):
        """⚙ Settings (top bar): the HUD's OWN settings
        handler — the same code the app window's ⚙️ Settings
        button runs (hud.Hud._on_settings). The plain window
        no longer owns anything the owner needs. Guarded:
        with no host window the button is a no-op."""
        try:
            hud = self._hud
            handler = getattr(hud, "_on_settings", None)
            if callable(handler):
                handler()
        except Exception:
            pass

    def _on_log_btn(self):
        """📋 Log (top bar): the HUD's OWN log handler
        (hud.Hud._on_log — regenerate + open the diagnostics
        page). Same reasoning as _on_settings_btn."""
        try:
            hud = self._hud
            handler = getattr(hud, "_on_log", None)
            if callable(handler):
                handler()
        except Exception:
            pass

    def _tk_hide(self):
        """Withdraw the window; loops stop via the _win_open
        flag their ticks check first. v5.8: also releases the
        bind_all Escape, and LOGS the outcome (closed / was
        not open / failed) — a close is never silent. Returns
        True when the window was actually open."""
        was_open = self._win_open
        self._win_open = False
        self._anim_on = False
        self._stats_on = False
        # v6.2: the ceremony resets with the window — panels
        # back to their resting strip colour, so the next
        # open lights them again in sequence.
        self._ceremony_done = True
        for strip in (self._left_strip, self._right_strip):
            if strip is not None:
                try:
                    strip.configure(bg=PANEL_STRIP)
                except Exception:
                    pass
        root = self._root
        if self._esc_bound and root is not None:
            try:
                root.unbind_all("<Escape>")
            except Exception:
                pass
            self._esc_bound = False
        if root is None:
            self._log_line(
                "SYSTEM",
                "[dashboard] close: Command Center window "
                "does not exist — nothing to close.")
            return False
        try:
            root.attributes("-alpha", 0.0)
        except Exception:
            pass
        try:
            root.withdraw()
            root.attributes("-alpha", 1.0)  # ready for next show
        except Exception:
            self._log_line(
                "ERROR",
                "[dashboard] Command Center hide failed:\n"
                + traceback.format_exc())
            return False
        self._log_line(
            "SYSTEM",
            "[dashboard] Command Center closed."
            if was_open else
            "[dashboard] close: Command Center was not open.")
        return was_open

    # ------------------------------------------------ rendering (Tk thread)
    def _mic_level(self):
        if _ears is not None:
            try:
                return max(0.0, min(1.0, float(_ears.get_level())))
            except Exception:
                pass
        return 0.0

    def _speaking(self):
        if _voice is not None:
            try:
                return bool(_voice.is_speaking())
            except Exception:
                pass
        return False

    def _anim_tick(self):
        """One orb frame (~30 fps). Runs ONLY while visible —
        when hidden the chain simply does not reschedule."""
        if not self._anim_on or not self._win_open:
            self._anim_on = False
            return
        try:
            self._draw_orb()
        except Exception:
            pass
        # v6.2: the opening ceremony rides this same loop —
        # panels light in sequence, the pill flips ONLINE.
        try:
            self._apply_ceremony()
        except Exception:
            pass
        # v5.8: the thinking indicator rides THIS loop (no
        # second timer): three chasing dots under the chat
        # while the brain's status is "thinking", blank
        # otherwise.
        try:
            if self._thinking_label is not None:
                if self._status_state == "thinking":
                    self._thinking_label.configure(
                        text=thinking_frame(time.monotonic()))
                else:
                    self._thinking_label.configure(text="")
        except Exception:
            pass
        try:
            self._root.after(33, self._anim_tick)
        except Exception:
            self._anim_on = False

    def _apply_ceremony(self):
        """One opening-ceremony frame (v6.2, Tk thread, driven
        by _anim_tick): the LEFT panel lights at 45%, the
        RIGHT at 70%, the status pill flips to ● ONLINE at
        95% and holds it for a beat (~0.9 s past the sequence)
        before the pill returns to the live status. A no-op
        once the ceremony is done (and on every later open it
        replays — _tk_show resets the flag)."""
        if self._ceremony_done or not self._intro_t0:
            return
        elapsed = time.monotonic() - self._intro_t0
        _p, left_on, right_on, online = ceremony_phase(elapsed)
        try:
            if left_on and self._left_strip is not None:
                self._left_strip.configure(bg=ACCENT)
            if right_on and self._right_strip is not None:
                self._right_strip.configure(bg=ACCENT)
            if online and self._status_label is not None:
                text, fg = STATUS_TEXT["online"]
                self._status_label.configure(text=text, fg=fg)
        except Exception:
            pass
        if elapsed >= CEREMONY_SECONDS + 0.9:
            self._ceremony_done = True
            try:
                if self._status_label is not None:
                    text, fg = STATUS_TEXT.get(
                        self._status_state, STATUS_TEXT["idle"])
                    self._status_label.configure(text=text, fg=fg)
            except Exception:
                pass

    def _draw_orb(self):
        canvas = self._orb_canvas
        if canvas is None:
            return
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 60 or h < 60:
            return
        cx, cy = w / 2.0, h / 2.0
        t = time.monotonic()
        # v6.2: the intro scale-in now spans the full ~1 s
        # ceremony (was 0.35 s) — the orb grows while the
        # ring sweep races and the panels light around it.
        intro = min(1.0, (t - self._intro_t0) / CEREMONY_SECONDS) \
            if self._intro_t0 else 1.0
        ceremony_p = intro
        level = self._mic_level()
        speaking = self._speaking()
        factor = orb_radius_factor(t, level, speaking, intro)
        radius = min(w, h) * 0.30 * factor
        # v6.2 spin-up: the sphere starts slow and accelerates
        # into its steady spin across the ceremony.
        self._rot += 0.011 * (0.2 + 0.8 * ceremony_p)
        tilt = 0.42 + 0.10 * math.sin(t * 0.23)
        canvas.delete("orb")
        # soft glow: four rings just outside the sphere
        # (v5.7: one more, wider and fainter — the IRIS orb
        # blooms softly into the black).
        for scale, colour, width in (
                (1.36, "#040b1a", 12), (1.22, "#081226", 10),
                (1.13, "#0b1e42", 7), (1.05, "#123064", 4)):
            r = radius * scale
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               outline=colour, width=width,
                               tags="orb")
        # dark core so back points read as depth
        r0 = radius * 0.98
        canvas.create_oval(cx - r0, cy - r0, cx + r0, cy + r0,
                           fill="#060d1d", outline="", tags="orb")
        # v6.2 ceremony: a bright sweep arc races around the
        # orb while the opening sequence runs (one revolution
        # across the ceremony, then it's gone).
        if ceremony_p < 1.0:
            _create_arc = getattr(canvas, "create_arc", None)
            if _create_arc is not None:
                try:
                    r = radius * 1.45
                    _create_arc(cx - r, cy - r, cx + r, cy + r,
                                start=90.0,
                                extent=-359.0 * ceremony_p,
                                style="arc", outline="#7dd3fc",
                                width=3, tags="orb")
                except Exception:
                    pass
        # v5.7: the counter-rotating halo — a faint tilted
        # ring of particles turning AGAINST the sphere.
        self._rot2 -= 0.006
        ring_r = radius * 1.30
        for x, y, z in ring_points(90, self._rot2, tilt):
            px, py = cx + x * ring_r, cy + y * ring_r
            size = 1.1 + (z + 1.0) * 0.8
            canvas.create_oval(px - size, py - size,
                               px + size, py + size,
                               fill=orb_color(z * 0.4 - 0.3),
                               outline="", tags="orb")
        for x, y, z in orb_points(ORB_POINTS, self._rot, tilt):
            px, py = cx + x * radius, cy + y * radius
            size = 1.4 + (z + 1.0) * 1.5
            canvas.create_oval(px - size, py - size,
                               px + size, py + size,
                               fill=orb_color(z), outline="",
                               tags="orb")
        # v5.7: his logo at the orb's heart — the nearest
        # pre-rendered size to the pulsing diameter, with a
        # thin halo ring around it. It scales WITH the pulse
        # (logo_px_for reads the same radius the sphere used).
        if self._orb_logo_imgs:
            px = logo_px_for(radius)
            img = None
            for size, photo in self._orb_logo_imgs:
                if size == px:
                    img = photo
                    break
            if img is not None:
                hr = radius * 0.58
                canvas.create_oval(cx - hr, cy - hr, cx + hr,
                                   cy + hr, outline="#1d4ed8",
                                   width=1, tags="orb")
                canvas.create_image(cx, cy, image=img,
                                    tags="orb")

    def _stats_tick(self):
        """~1 s: clock + SYSTEM panel. Visible-only chain."""
        if not self._stats_on or not self._win_open:
            self._stats_on = False
            return
        try:
            if self._clock_label is not None:
                self._clock_label.configure(
                    text=time.strftime("%H:%M:%S"))
            stats, self._cpu_sample = collect_stats(self._cpu_sample)
            for key in ("cpu", "gpu", "ram", "disk", "battery"):
                widgets = self._stat_widgets.get(key)
                if widgets is None:
                    continue
                val_label, bar = widgets
                pct = stats.get(key)
                if pct is None:
                    val_label.configure(text="—")
                    self._draw_bar(bar, None, ACCENT)
                    continue
                text = f"{int(round(pct))}%"
                if key == "battery" and stats.get("charging"):
                    text += " ⚡"
                val_label.configure(text=text)
                self._draw_bar(bar, pct, ACCENT)
            # mic + brain: the logbook status header is the same
            # source the diagnostics page shows; pushed values
            # (set_brain) win when fresher.
            status = {}
            if _logbook is not None:
                try:
                    status = _logbook.get_status()
                except Exception:
                    status = {}
            if self._mic_label is not None:
                mic = status.get("mic")
                if mic and mic != "unknown":
                    self._mic_label.configure(text="🎤 " + mic)
            # v7.2: the live mic readout — level bar + the
            # age of the last gate beat, from ears'
            # mic_activity(). Fully guarded: any failure
            # keeps the previous text and never breaks the
            # tick (the panel degrades, it does not die).
            if self._mic_live_label is not None:
                try:
                    if _ears is not None:
                        _lvl, _age = _ears.mic_activity()
                        self._mic_live_label.configure(
                            text=mic_live_text(_lvl, _age))
                except Exception:
                    pass
            if self._brain_label is not None:
                brain = self._brain_text or status.get("brain")
                if brain and brain != "unknown":
                    self._brain_label.configure(text=brain)
            if self._level_label is not None:
                try:
                    import perflevel
                    self._level_label.configure(
                        text=perflevel.level_line())
                except Exception:
                    pass
            # v6.2: the BIG header Level (number + word + the
            # progress bar to the next level).
            if self._level_big_label is not None:
                try:
                    import perflevel
                    _lvl, _word, _frac = \
                        perflevel.level_progress()
                    self._level_big_label.configure(
                        text=str(_lvl) if _lvl > 0 else "—")
                    if self._level_word_label is not None:
                        self._level_word_label.configure(
                            text=("Level · " + _word)
                            if _lvl > 0 else "Level")
                    if self._level_bar is not None:
                        self._draw_bar(self._level_bar,
                                       _frac * 100.0, AMBER)
                except Exception:
                    pass
            # v6.2 SYSTEM rows: phone / commands / uptime.
            if self._phone_label is not None:
                ptxt = "📱 —"
                try:
                    import phone_link
                    if phone_link.is_connected():
                        ptxt = "📱 " + (
                            phone_link.device_name()
                            or "Android phone")
                    else:
                        ptxt = "📱 not connected"
                except Exception:
                    pass
                try:
                    self._phone_label.configure(text=ptxt)
                except Exception:
                    pass
            if self._cmds_label is not None:
                try:
                    _n = _logbook.session_command_count() \
                        if _logbook is not None else None
                    self._cmds_label.configure(
                        text="🎙 Commands this session: "
                             + (str(_n) if _n is not None
                                else "—"))
                except Exception:
                    pass
            if self._uptime_label is not None:
                try:
                    self._uptime_label.configure(
                        text="⏱ Uptime: " + format_uptime(
                            time.monotonic() - self._boot_mono))
                except Exception:
                    pass
            if self._status_label is not None:
                text, fg = STATUS_TEXT.get(
                    self._status_state, STATUS_TEXT["idle"])
                self._status_label.configure(text=text, fg=fg)
                # v7.1: the accent strip follows the same
                # status colour.
                if self._top_strip is not None:
                    try:
                        self._top_strip.configure(bg=fg)
                    except Exception:
                        pass
            # v7.1: a pending update banner renders on the
            # first visible tick (and clears itself).
            self._tk_apply_update_notice()
        except Exception:
            pass
        try:
            self._root.after(1000, self._stats_tick)
        except Exception:
            self._stats_on = False

    def _draw_bar(self, canvas, pct, colour):
        try:
            w = canvas.winfo_width()
            if w < 20:
                w = 232
            canvas.delete("bar")
            canvas.create_rectangle(0, 0, w, 6, fill="#101c33",
                                    outline="", tags="bar")
            if pct is not None:
                fill_w = max(2.0, w * max(0.0, min(100.0, pct)) / 100.0)
                canvas.create_rectangle(0, 0, fill_w, 6, fill=colour,
                                        outline="", tags="bar")
        except Exception:
            pass

    # ------------------------------------------------ chat (Tk thread)
    def _append_chat(self, who, body):
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            return
        widget.configure(state="normal")
        try:
            # v5.8: bubble rows — the name sits on its own
            # line (weighted to the bubble's side), the body
            # inside the coloured bubble tag.
            if who == "you":
                widget.insert("end", "You\n", "you_name")
                widget.insert("end", body + "\n", "you_bubble")
            elif who == "nalox":
                widget.insert("end", "Nalox\n", "nalox_name")
                widget.insert("end", body + "\n", "nalox_bubble")
            elif who == "error":
                widget.insert("end", body + "\n", "error_bubble")
            else:
                widget.insert("end", body + "\n", "sys_bubble")
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _rebuild_chat(self):
        widget = self._chat_text
        if widget is None:
            return
        widget.configure(state="normal")
        try:
            widget.delete("1.0", "end")
        finally:
            widget.configure(state="disabled")
        with self._chat_lock:
            lines = list(self._chat)
        for who, body in lines:
            self._append_chat(who, body)
        self._chat_dirty = False
        # v6.5: a reply still streaming when the window
        # (re)opens resumes growing in the replayed bubble.
        if self._stream_open:
            self._tk_resume_stream()
        # v6.7 F: a hearing preview still open resumes
        # replacing in the replayed bubble.
        if self._preview_open:
            self._tk_resume_preview()

    # --------------------------------------- v6.5 live chat sync (Tk)
    def _tk_begin_stream(self):
        """Open the live bubble in the widget: the name line
        now, the body growing at the stream mark as chunks
        land."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            return
        widget.configure(state="normal")
        try:
            widget.insert("end", "Nalox\n", "nalox_name")
            widget.mark_set("nalox_stream", "end-1c")
            widget.mark_gravity("nalox_stream", "right")
            self._tk_stream_text = ""
            self._tk_stream_has_nl = False
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _tk_resume_stream(self):
        """Re-attach the stream mark to the replayed bubble
        (the window opened mid-reply): the model's last entry
        is the streaming bubble, rendered by _append_chat as
        body + "\\n" — the mark goes between body and that
        newline."""
        widget = self._chat_text
        if widget is None:
            return
        try:
            with self._chat_lock:
                body = self._chat[-1][1] if self._chat else ""
            widget.mark_set("nalox_stream", "end-2c")
            widget.mark_gravity("nalox_stream", "right")
            self._tk_stream_text = body
            self._tk_stream_has_nl = True
        except Exception:
            self._tk_stream_text = None

    def _tk_stream_chunk(self, chunk):
        """Append one spoken sentence to the live bubble."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            return
        widget.configure(state="normal")
        try:
            if self._tk_stream_text is None:
                self._tk_resume_stream()
            if self._tk_stream_text is None:
                self._chat_dirty = True
                return
            delta = (" " if self._tk_stream_text else "") + chunk
            widget.insert("nalox_stream", delta, "nalox_bubble")
            self._tk_stream_text += delta
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _tk_end_stream(self):
        """Close the live bubble: the trailing newline every
        finished bubble carries (see _append_chat)."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            self._tk_stream_text = None
            self._tk_stream_has_nl = False
            return
        if self._tk_stream_text is None:
            return  # never rendered live — the model is whole
        widget.configure(state="normal")
        try:
            if not self._tk_stream_has_nl:
                widget.insert("nalox_stream", "\n", "nalox_bubble")
            widget.mark_unset("nalox_stream")
            widget.see("end")
        finally:
            widget.configure(state="disabled")
            self._tk_stream_text = None
            self._tk_stream_has_nl = False

    # --------------------------------------- v6.7 F hearing preview (Tk)
    def _tk_begin_preview(self):
        """Open the live YOU bubble in the widget: the name
        line now, the body REPLACED at the preview mark as
        partials land."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            return
        widget.configure(state="normal")
        try:
            widget.mark_set("you_preview_name", "end-1c")
            widget.mark_gravity("you_preview_name", "left")
            widget.insert("end", "You\n", "you_name")
            widget.mark_set("you_preview", "end-1c")
            widget.mark_gravity("you_preview", "left")
            self._tk_preview_text = ""
            self._tk_preview_has_nl = False
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _tk_resume_preview(self):
        """Re-attach the preview marks to the replayed bubble
        (the window opened mid-command): the model's last
        entry is the preview, rendered whole by _append_chat
        as name + body + newline."""
        widget = self._chat_text
        if widget is None:
            return
        try:
            with self._chat_lock:
                body = self._chat[-1][1] if self._chat else ""
            widget.mark_set(
                "you_preview_name",
                f"end-1c-{len(body) + 4}c")
            widget.mark_gravity("you_preview_name", "left")
            widget.mark_set("you_preview",
                            f"end-1c-{len(body)}c")
            widget.mark_gravity("you_preview", "left")
            self._tk_preview_text = body
            self._tk_preview_has_nl = True
        except Exception:
            self._tk_preview_text = None

    def _tk_update_preview(self, text):
        """Replace the live bubble's body with the newest
        partial transcription."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            return
        widget.configure(state="normal")
        try:
            if self._tk_preview_text is None:
                self._tk_resume_preview()
            if self._tk_preview_text is None:
                self._chat_dirty = True
                return
            widget.delete("you_preview", "end-1c")
            widget.insert("you_preview", text, "you_bubble")
            self._tk_preview_text = text
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _tk_end_preview(self, final_text):
        """Finalize the live bubble with the FINAL words:
        the body is set to the final transcript (a post()
        finalize may already have set it — replacing with
        the same text is harmless) and the bubble gains its
        trailing newline."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            self._tk_preview_text = None
            self._tk_preview_has_nl = False
            return
        if self._tk_preview_text is None:
            return  # never rendered live — the model is whole
        widget.configure(state="normal")
        try:
            if final_text and final_text != self._tk_preview_text:
                widget.delete("you_preview", "end-1c")
                widget.insert("you_preview", final_text,
                              "you_bubble")
                self._tk_preview_text = final_text
            if not self._tk_preview_has_nl:
                widget.insert("end-1c", "\n", "you_bubble")
            widget.mark_unset("you_preview")
            widget.mark_unset("you_preview_name")
            widget.see("end")
        finally:
            widget.configure(state="disabled")
            self._tk_preview_text = None
            self._tk_preview_has_nl = False

    def _tk_cancel_preview(self):
        """Remove the live bubble entirely (nothing was
        finally heard — the partial leaves no trace)."""
        widget = self._chat_text
        if widget is None:
            self._chat_dirty = True
            self._tk_preview_text = None
            self._tk_preview_has_nl = False
            return
        if self._tk_preview_text is None:
            return
        widget.configure(state="normal")
        try:
            widget.delete("you_preview_name", "end-1c")
            widget.mark_unset("you_preview")
            widget.mark_unset("you_preview_name")
            widget.see("end")
        finally:
            widget.configure(state="disabled")
            self._tk_preview_text = None
            self._tk_preview_has_nl = False

    # ------------------------------------------------ queue pump (Tk thread)
    def _poll(self):
        """after() chain on the HUD root: drain the queue into
        the Toplevel, reschedule. Mirrors hud.Hud's own pump."""
        if not self._poll_on:
            return
        try:
            self._drain_queue()
        except Exception:
            pass
        if self._poll_on and self._root is not None:
            try:
                self._root.after(50, self._poll)
            except Exception:
                self._poll_on = False

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "chat":
                    who, body = payload
                    if self._win_open:
                        self._append_chat(who, body)
                    else:
                        self._chat_dirty = True
                elif kind == "chat_begin":
                    if self._win_open:
                        self._tk_begin_stream()
                    else:
                        self._chat_dirty = True
                elif kind == "chat_chunk":
                    if self._win_open:
                        self._tk_stream_chunk(payload)
                    else:
                        self._chat_dirty = True
                elif kind == "chat_end":
                    if self._win_open:
                        self._tk_end_stream()
                    else:
                        self._chat_dirty = True
                elif kind == "chat_pbegin":
                    if self._win_open:
                        self._tk_begin_preview()
                    else:
                        self._chat_dirty = True
                elif kind == "chat_pupdate":
                    if self._win_open:
                        self._tk_update_preview(payload)
                    else:
                        self._chat_dirty = True
                elif kind == "chat_pend":
                    if self._win_open:
                        self._tk_end_preview(payload)
                    else:
                        self._chat_dirty = True
                elif kind == "chat_pcancel":
                    if self._win_open:
                        self._tk_cancel_preview()
                    else:
                        self._chat_dirty = True
                elif kind == "status":
                    if self._status_label is not None:
                        text, fg = STATUS_TEXT.get(
                            payload, STATUS_TEXT["idle"])
                        self._status_label.configure(text=text, fg=fg)
                elif kind == "brain":
                    self._brain_text = payload
                    if self._brain_label is not None:
                        self._brain_label.configure(text=payload)
                elif kind == "cmd":
                    gen = _show_gen(payload)
                    if gen is not None:
                        # v6.1: the same performer show() uses
                        # — one code path judges every show
                        # (the legacy queue route is kept for
                        # any sender that still uses it).
                        self._tk_perform_show(gen)
                    elif payload == "hide":
                        try:
                            self._tk_hide()
                        except Exception:
                            self._log_line(
                                "ERROR",
                                "[dashboard] Command Center "
                                "hide failed:\n"
                                + traceback.format_exc())
                    elif payload == "quit":
                        self._poll_on = False
                        try:
                            self._root.destroy()
                        except Exception:
                            pass
                        self._root = None
                        return
        except queue.Empty:
            pass
