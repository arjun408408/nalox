"""Nalox's logbook (v4.1) — the diagnostics page Arjun asked for.

Everything Nalox hears, says and trips over is written down in TWO
places in the install folder:

  - nalox_log.txt   — plain text, one line per event:
                      "HH:MM:SS [CATEGORY] text"
  - nalox_page.html — a self-contained dark page (auto-refreshes
                      every 3 s) with a status header (version, mic,
                      speaker output, voice, brain, robot flag, last
                      error) and the last ~200 log lines, ERROR
                      lines in red, YOU in cyan, NALOX in green.

Arjun opens the page from the app window's "📋 Log" button; when
something misbehaves he screenshots it and Muse can see exactly
what happened. Logging is thread-safe and FULLY exception-guarded:
a logging failure can never crash or even slow down Nalox.
"""
import html
import os
import threading
import time
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "nalox_log.txt")
PAGE_PATH = os.path.join(BASE_DIR, "nalox_page.html")

MAX_LINES = 200

_lock = threading.Lock()
_lines = deque(maxlen=MAX_LINES)
_loaded = False

# v6.2: commands heard THIS session (process lifetime) — the
# Command Center's "Commands this session" row. Counted in
# log() itself: every YOU line is one heard command. The
# file tail pulled in by _ensure_loaded() is history, not
# this session, and never passes through log() — so it can
# never inflate the count.
_session_commands = 0

# v6.9: ERROR hooks — callables invoked (guarded, no args)
# whenever an ERROR line is written. logsync.py registers
# its dirty-flag setter here so an error asks for an early
# log upload without logbook knowing anything about GitHub.
_error_hooks = []


def register_error_hook(callback):
    """Register a no-arg callable fired on every ERROR log
    line (v6.9, for logsync). Guarded; never raises."""
    try:
        if callable(callback) and callback not in _error_hooks:
            _error_hooks.append(callback)
    except Exception:
        pass


def session_command_count():
    """Commands heard since this process started (v6.2)."""
    return _session_commands

# Status header fields — nalox.py fills these in at boot (and keeps
# mic/voice current); anything unset shows as "unknown".
_status = {
    "version": "unknown",
    "mic": "unknown",
    "output": "unknown",
    "voice": "unknown",
    "brain": "unknown",
    "robot": "unknown",
    "skills": "0",
    "last_error": "No errors",
}

# Category -> CSS colour on the page.
_CATEGORY_COLORS = {
    "ERROR": "#ff6b6b",
    "YOU": "#22d3ee",
    "NALOX": "#33ff66",
    "WAKE": "#ffb000",
    "MIC": "#7dd3fc",
    "VOICE": "#e879f9",
    "BRAIN": "#a5b4fc",
    "SYSTEM": "#9fb89f",
}
_DEFAULT_COLOR = "#c9d1c9"


def _ensure_loaded():
    """Pull the existing nalox_log.txt tail into memory (once)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "r", encoding="utf-8",
                      errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line:
                        _lines.append(line)
    except Exception:
        pass


def set_status(**fields):
    """Update header fields (version/mic/output/voice/brain/robot).

    Unknown keys are ignored; everything is guarded.
    """
    try:
        with _lock:
            for key, value in fields.items():
                if key in _status and value is not None:
                    _status[key] = str(value)
            _ensure_loaded()
            _write_page()
    except Exception:
        pass


def get_status():
    """A copy of the current status header (v5.5).

    The Command Center's SYSTEM panel reads mic/brain from here
    — the same header the diagnostics page shows, so the two can
    never disagree. Never raises.
    """
    try:
        with _lock:
            return dict(_status)
    except Exception:
        return {}


def log(category, text):
    """Append one event and regenerate the page. Never raises."""
    global _session_commands
    try:
        cat = str(category or "SYSTEM").strip().upper() or "SYSTEM"
        if cat == "YOU":
            _session_commands += 1
        clean = " ".join(str(text).split())  # one physical line
        line = f"{time.strftime('%H:%M:%S')} [{cat}] {clean}"
        with _lock:
            _ensure_loaded()
            _lines.append(line)
            if cat == "ERROR":
                _status["last_error"] = line
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass  # the page regeneration below is guarded too
            _write_page()
        if cat == "ERROR":
            # v6.9: notify the error hooks (logsync's dirty
            # flag) OUTSIDE the lock and fully guarded — a
            # hook can never slow down or break logging.
            for _hook in list(_error_hooks):
                try:
                    _hook()
                except Exception:
                    pass
    except Exception:
        pass


def log_file_only(text):
    """Append one line to nalox_log.txt ONLY (v4.6 heartbeat).

    Unlike log(), this does NOT touch the in-memory lines or
    regenerate nalox_page.html — the heartbeat is high-frequency
    diagnostic evidence for hang investigations, and the page
    would drown in it. Same "HH:MM:SS <text>" shape as log()
    lines. Never raises.
    """
    try:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with _lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def regenerate():
    """Rewrite nalox_page.html from the current state. Never raises."""
    try:
        with _lock:
            _ensure_loaded()
            _write_page()
    except Exception:
        pass


def _category_of(line):
    """Extract the [CATEGORY] out of a stored log line."""
    try:
        start = line.index("[") + 1
        end = line.index("]", start)
        return line[start:end].strip().upper()
    except Exception:
        return ""


def _write_page():
    """Build the HTML page. Caller holds _lock. Guarded by callers."""
    rows = []
    for line in _lines:
        color = _CATEGORY_COLORS.get(_category_of(line), _DEFAULT_COLOR)
        rows.append(
            f'<div class="line" style="color:{color}">'
            f"{html.escape(line)}</div>")
    body = "\n".join(rows) if rows else \
        '<div class="line">No log lines yet.</div>'
    s = {k: html.escape(str(v)) for k, v in _status.items()}
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>NALOX // LOG</title>
<style>
  body {{ background:#0b0e13; color:#c9d1c9; margin:0;
         font-family:Consolas,'Courier New',monospace; }}
  header {{ background:#101623; border-bottom:2px solid #1d5c33;
            padding:14px 18px; }}
  header h1 {{ color:#33ff66; margin:0 0 8px 0; font-size:22px;
               letter-spacing:2px; }}
  table.status {{ border-collapse:collapse; font-size:13px; }}
  table.status td {{ padding:2px 14px 2px 0; vertical-align:top; }}
  table.status td.k {{ color:#5f7a63; }}
  .err {{ color:#ff6b6b; }}
  main {{ padding:12px 18px; font-size:13px; line-height:1.5; }}
  .line {{ white-space:pre-wrap; word-break:break-word; }}
</style>
</head>
<body>
<header>
  <h1>NALOX // LOG</h1>
  <table class="status">
    <tr><td class="k">Version</td><td>{s['version']}</td>
        <td class="k">Microphone</td><td>{s['mic']}</td></tr>
    <tr><td class="k">Speaker output</td><td>{s['output']}</td>
        <td class="k">Voice</td><td>{s['voice']}</td></tr>
    <tr><td class="k">Brain</td><td>{s['brain']}</td>
        <td class="k">Robot voice</td><td>{s['robot']}</td></tr>
    <tr><td class="k">Skills loaded</td><td>{s['skills']}</td>
        <td class="k"></td><td></td></tr>
    <tr><td class="k">Last error</td>
        <td class="err" colspan="3">{s['last_error']}</td></tr>
  </table>
</header>
<main>
{body}
</main>
</body>
</html>
"""
    try:
        with open(PAGE_PATH, "w", encoding="utf-8") as f:
            f.write(page)
    except Exception:
        pass
