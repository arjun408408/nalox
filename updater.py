"""Nalox self-update from GitHub (v6.2) — no more UPDATE.bat.

The owner's standing order (2026-11-15): Nalox must UPDATE
ITSELF. He keeps the full Nalox source in a PRIVATE GitHub
repo under his own account; this module checks that repo and
applies a newer version exactly the way UPDATE.bat did —
code + assets + phone-app + platform-tools — and NEVER
touches his data:

    NEVER copied, even if the repo copy contains them:
    config.json (his API keys!), custom_commands.json,
    prefs.json, logs, *.flag, *.lock, nalox_log.txt,
    nalox_page.html, nalox_fault.log, memory stores,
    captures, updated_to.txt itself.

Config (Settings → Updates writes these; all local):
    github_repo   "owner/name" of the private repo
    github_token  a token for that repo (Contents: Read and
                  write since v6.9 — logsync.py sends the
                  diagnostics log home with the same token)
    auto_update   master switch for the scheduled checks

Flow: at boot (~60 s in, background thread) and then every
30 minutes (v7.2; 6-hourly through v7.1 — the shorter cycle
lets a pushed fix land within the hour instead of waiting
out a 6 h boundary) — only when repo+token are set AND
auto_update is on — fetch the repo's version.txt through
the GitHub API;
if it is newer than the local version.txt, download that
ref's zipball, stage it in a temp dir, apply the whitelist,
write the updated_to.txt marker, log
"[sys] exiting (restart): self-update to vX.Y" and exit via
the restart path (the supervisor relaunches). The next boot
finds the marker, speaks "I have updated myself to version
X.Y, sir." once and deletes it (nalox.py does that part).

Failure discipline: every failure is ONE logbook line, never
blocks the app, and a version whose download/apply failed is
not retried until the next scheduled check (no retry loops).
Settings' [Check for updates now] runs the same flow
immediately (force=True — it ignores the auto switch and the
failed-version skip: a human pressing the button IS the next
check) and reports the result in the window.

The HTTP layer is injectable (http=) so the test suite can
drive the whole flow against a fake GitHub.
"""
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

log = logging.getLogger("nalox.updater")


def _hidden_console_kwargs():
    """subprocess kwargs that keep a console child INVISIBLE
    (v7.7, item G): CREATE_NO_WINDOW on Windows, nothing
    elsewhere — the update path's pip / adb / patch children
    are console tools and must never flash a window."""
    if os.name == "nt":
        return {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_PATH = os.path.join(BASE_DIR, "version.txt")
MARKER_NAME = "updated_to.txt"

API_ROOT = "https://api.github.com/repos/"
HTTP_TIMEOUT = 30          # every GitHub call is bounded
CHECK_FIRST_DELAY_S = 60.0   # first check ~60 s after boot
CHECK_INTERVAL_S = 5 * 60    # then every 5 min (v7.9 item G;
                             # was 30 min v7.2–v7.8, 6 h before)
FAILED_RETRY_S = 5 * 60      # a failed version waits a cycle
# v7.9 (item G): the owner — "তুমি দিলেই অটোমেটিক আপডেট করে
# নেবে" (when a version is pushed, Nalox takes it by
# itself). Three parts: the 5-minute cadence above; a
# Command-Center-open poke (poke_check, debounced so the
# show path can never stampede GitHub); and a BUSY DEFERRAL
# — a staged update never restarts mid-conversation: the
# restart waits for the turn to end, capped, then applies
# anyway (see _deferred_restart).
POKE_DEBOUNCE_S = 120.0      # show-poke: ≤1 check per 2 min
DEFER_POLL_S = 5.0           # busy re-check cadence
DEFER_MAX_S = 600.0          # never defer a restart > 10 min

# The UPDATE.bat apply set, mirrored: top-level code files,
# docs and data folders. Anything not listed here is never
# copied — that whitelist IS the user-data protection.
_COPY_FILE_SUFFIXES = (".py",)
_COPY_FILES = {"version.txt", "SETUP-YOUTUBE.txt",
               "SETUP-OLLAMA.txt",
               "SETUP-GOOGLE-VOICE.txt",
               "UPDATE-README.txt", "README.md", "FOR-AI.md",
               ".gitignore"}
_COPY_DIRS = ("skills", "assets", "platform-tools", "phone-app")
# Belt-and-braces deny list, checked BEFORE the whitelist:
# even a future whitelist edit must never ship these.
_NEVER_FILES = {"config.json", "custom_commands.json",
                "prefs.json", MARKER_NAME, "nalox_log.txt",
                "nalox_page.html", "nalox_fault.log",
                "requirements.txt",
                # v6.7: persisted engine/brain health — his
                # machine's own state, never shipped or
                # overwritten by an update.
                "voice_state.json", "brain_state.json",
                # v6.9: the log-sync state (last sync time +
                # status) — same rule: his machine's own
                # state, never shipped or overwritten.
                "logsync_state.json",
                # v6.10: the ears ladder's remembered
                # resolution — same rule again.
                "ears_state.json"}
_NEVER_SUFFIXES = (".flag", ".lock", ".db", ".sqlite",
                   ".sqlite3")
_NEVER_DIRS = {"logs", "captures", "leads", "demos",
               "__pycache__", ".venv", ".git",
               # v7.1: the fixed-line TTS cache — his
               # machine's own rendered audio, never shipped
               # or overwritten by an update.
               "cache"}

# repo -> (version, monotonic time) of the last failed
# download/apply, so a broken version is not retried until
# the next scheduled check.
_failed = {}
_started = False

# v7.9 (item G): state for the show-poke + busy deferral.
# start_background registers the live (cfg, restart_fn) so
# poke_check() — called from the dashboard's show path,
# which has neither — can run a real check. The busy probe
# is registered by nalox.py (set_busy_probe): True while a
# voice turn is in progress (speaking / brain working).
_poke_state = {"cfg": None, "restart_fn": None, "last": 0.0}
_busy_probe = None


def set_busy_probe(fn):
    """Register the turn-busy probe (nalox.py). Guarded —
    a broken probe must never break updating."""
    global _busy_probe
    _busy_probe = fn


def _turn_busy():
    """True when the registered probe says a voice turn is
    in progress. No probe / probe error = not busy (v7.8
    behaviour: restart immediately)."""
    probe = _busy_probe
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def poke_check():
    """v7.9 (item G): a Command Center open asks for an
    update check NOW — debounced to at most one check per
    POKE_DEBOUNCE_S from this trigger. The check runs on
    its own daemon thread (the UI thread never waits on
    HTTP). Returns "started" / "debounced" / "unregistered"
    / "disabled". Never raises."""
    try:
        cfg = _poke_state.get("cfg")
        if cfg is None:
            return "unregistered"
        if not cfg.get("auto_update", True):
            return "disabled"
        now = time.monotonic()
        if now - float(_poke_state.get("last") or 0.0) \
                < POKE_DEBOUNCE_S:
            return "debounced"
        _poke_state["last"] = now
        restart_fn = _poke_state.get("restart_fn")

        def _run():
            try:
                live = cfg
                try:
                    from config import load_config
                    live = load_config()
                except Exception:
                    pass
                check_and_update(live, restart_fn=restart_fn)
            except Exception as exc:
                log.warning("poked update check failed: %s",
                            exc)

        threading.Thread(target=_run, daemon=True,
                         name="nalox-updater-poke").start()
        return "started"
    except Exception:
        return "unregistered"


def _lb(text):
    """One logbook SYSTEM line, guarded (never raises)."""
    try:
        import logbook
        logbook.log("SYSTEM", text)
    except Exception:
        pass
    log.info("%s", text)


# ------------------------------------------------------------ versions
def parse_version(text):
    """'6.2' / 'v6.2.1' -> (6, 2, 1); None when unparseable."""
    try:
        s = str(text or "").strip().lower().lstrip("v")
        parts = []
        for chunk in s.split("."):
            chunk = "".join(c for c in chunk if c.isdigit())
            if chunk == "":
                return None
            parts.append(int(chunk))
        return tuple(parts) if parts else None
    except Exception:
        return None


def is_newer(remote, local):
    """True when remote parses and is strictly newer."""
    r = parse_version(remote)
    l = parse_version(local)
    if r is None:
        return False
    if l is None:
        return True
    n = max(len(r), len(l))
    r += (0,) * (n - len(r))
    l += (0,) * (n - len(l))
    return r > l


def local_version(base_dir=BASE_DIR):
    try:
        with open(os.path.join(base_dir, "version.txt"),
                  encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


# ------------------------------------------------------------ HTTP
def _default_http(method, url, headers):
    """(status, body_bytes) via requests — bounded, always."""
    import requests
    resp = requests.request(method, url, headers=headers or {},
                            timeout=HTTP_TIMEOUT)
    return resp.status_code, resp.content


def _headers(token, accept):
    return {"Authorization": "Bearer " + token,
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Nalox-Updater"}


def fetch_remote_version(repo, token, http=None):
    """The repo's version.txt content, or None on any failure
    (bad token, no such file, network down — all the same to
    the caller: log one line, skip this cycle)."""
    http = http or _default_http
    url = API_ROOT + repo + "/contents/version.txt"
    try:
        status, body = http("GET", url, _headers(
            token, "application/vnd.github.raw+json"))
    except Exception as exc:
        log.warning("update check: version fetch failed: %s", exc)
        return None
    if status != 200:
        log.warning("update check: version fetch HTTP %s "
                    "(token rejected?)", status)
        return None
    try:
        return body.decode("utf-8", "replace").strip()
    except Exception:
        return None


def download_zipball(repo, token, http=None):
    """The repo's zipball bytes (default branch), or None."""
    http = http or _default_http
    url = API_ROOT + repo + "/zipball"
    try:
        status, body = http("GET", url, _headers(
            token, "application/vnd.github+json"))
    except Exception as exc:
        log.warning("update download failed: %s", exc)
        return None
    if status != 200 or not body:
        log.warning("update download: HTTP %s", status)
        return None
    return body


# ------------------------------------------------------------ apply
def _never(rel):
    """True when a staged relative path must NEVER be copied
    into the install (user data / runtime state)."""
    parts = rel.replace("\\", "/").split("/")
    if any(p in _NEVER_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    if name in _NEVER_FILES:
        return True
    if name.endswith(_NEVER_SUFFIXES):
        return True
    return False


def _wanted(rel):
    """True when a staged relative path is part of the
    UPDATE.bat apply set (code + assets + phone-app +
    platform-tools + docs)."""
    if _never(rel):
        return False
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 1:
        name = parts[0]
        return name.endswith(_COPY_FILE_SUFFIXES) \
            or name in _COPY_FILES
    return parts[0] in _COPY_DIRS


def _stage_zip(zip_bytes):
    """Extract a GitHub zipball to a temp dir; return
    (stage_root, cleanup_dir) where stage_root is the single
    top folder inside the zipball. Raises on a bad zip."""
    tmp = tempfile.mkdtemp(prefix="nalox-update-")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)
        entries = [e for e in os.listdir(tmp)
                   if os.path.isdir(os.path.join(tmp, e))]
        if len(entries) != 1:
            raise ValueError("zipball has no single top folder")
        return os.path.join(tmp, entries[0]), tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _requirements_changed(stage_root, base_dir):
    """True when the staged requirements.txt differs from the
    installed one (md5) — UPDATE.bat pip-installs only then."""
    import hashlib

    def _md5(path):
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return None
    staged = _md5(os.path.join(stage_root, "requirements.txt"))
    if staged is None:
        return False
    return staged != _md5(os.path.join(base_dir,
                                       "requirements.txt"))


def _pip_install(stage_root, base_dir):
    """pip-install the staged requirements with the install's
    own venv python (UPDATE.bat parity). False on failure —
    the caller then aborts the update rather than applying
    code whose packages are missing."""
    venv_py = os.path.join(base_dir, ".venv", "Scripts",
                           "python.exe")
    if not os.path.exists(venv_py):
        venv_py = sys.executable
    try:
        subprocess.run(
            [venv_py, "-m", "pip", "install", "--prefer-binary",
             "-r", os.path.join(stage_root, "requirements.txt")],
            timeout=600, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=True,
            **_hidden_console_kwargs())
        return True
    except Exception as exc:
        log.warning("update: pip install failed: %s", exc)
        return False


def _kill_adb_server(base_dir):
    """v7.1 (F6): stop the adb server running from the
    install's bundled platform-tools, so its binaries are
    unlocked for the copy in apply_update. The server is
    spawned by phone_control.py from THIS tree; left
    running, it holds adb.exe / AdbWinApi.dll /
    AdbWinUsbApi.dll open and the copy dies mid-apply with
    WinError 32 (field 2026-11-16 00:39 IST). Best-effort:
    any failure is ignored — the copy guard below names
    the file if it is still locked. The server respawns on
    the next phone command."""
    try:
        adb = os.path.join(base_dir, "platform-tools",
                           "adb.exe")
        if os.path.exists(adb):
            subprocess.run([adb, "kill-server"], timeout=10,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           **_hidden_console_kwargs())
    except Exception:
        pass


def _raise_locked(rel, exc):
    """v7.1 (F6): a copy blocked by a sharing/lock error
    fails the WHOLE apply, naming the exact file. Skipping
    the file instead would strand a half-updated install
    the version check could never detect (version.txt
    would already match), so the apply stays
    all-or-nothing: the raise keeps the caller's
    no-success-marker discipline intact and the version is
    retried on the next cycle."""
    log.warning("update: file locked during apply: %s (%s)",
                rel, exc)
    raise RuntimeError(
        f"file locked during apply: {rel} ({exc})")


def apply_update(zip_bytes, base_dir=BASE_DIR):
    """Apply a downloaded zipball to base_dir, UPDATE.bat
    style. Returns the list of relative paths copied. Raises
    on a bad zip / failed pip step — the caller treats any
    raise as "this version failed"."""
    stage_root, tmp = _stage_zip(zip_bytes)
    try:
        if _requirements_changed(stage_root, base_dir):
            if not _pip_install(stage_root, base_dir):
                raise RuntimeError(
                    "requirements changed but pip install "
                    "failed — update aborted, nothing applied")
        applied = []
        _adb_killed = False
        for root, _dirs, files in os.walk(stage_root):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, stage_root)
                if not _wanted(rel):
                    continue
                rel_fwd = rel.replace(os.sep, "/")
                # v7.1 (F6): the platform-tools binaries
                # are locked by the running adb server —
                # stop it once, lazily, before the first
                # one is copied (see _kill_adb_server).
                if not _adb_killed \
                        and rel_fwd.startswith(
                            "platform-tools/"):
                    _adb_killed = True
                    _kill_adb_server(base_dir)
                dest = os.path.join(base_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    shutil.copy2(full, dest)
                except PermissionError as exc:
                    _raise_locked(rel_fwd, exc)
                except OSError as exc:
                    if getattr(exc, "winerror", None) \
                            in (32, 33):
                        _raise_locked(rel_fwd, exc)
                    raise
                applied.append(rel_fwd)
        if not applied:
            raise ValueError("zipball contained nothing to apply")
        # UPDATE.bat parity: patch_config.py flips only its
        # listed keys (his API keys are preserved by design).
        patch = os.path.join(base_dir, "patch_config.py")
        if os.path.exists(patch):
            venv_py = os.path.join(base_dir, ".venv", "Scripts",
                                   "python.exe")
            try:
                subprocess.run(
                    [venv_py if os.path.exists(venv_py)
                     else sys.executable, patch],
                    timeout=60, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_hidden_console_kwargs())
            except Exception:
                pass  # patching is best-effort, never fatal
        return applied
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------ marker
def write_updated_marker(version, base_dir=BASE_DIR):
    try:
        with open(os.path.join(base_dir, MARKER_NAME), "w",
                  encoding="utf-8") as f:
            f.write(str(version).strip() + "\n")
        return True
    except Exception:
        return False


def pop_updated_marker(base_dir=BASE_DIR):
    """Read + delete updated_to.txt; the version string, or
    None. nalox.py calls this once at boot: a present marker
    means the previous process updated itself, and the line
    "I have updated myself to version X.Y, sir." is spoken
    exactly once (the marker is gone before the speaking)."""
    path = os.path.join(base_dir, MARKER_NAME)
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            version = f.read().strip()
        os.remove(path)
        return version or None
    except Exception:
        return None


# ------------------------------------------------------------ the check
def _default_restart():
    """The restart path when no callback was supplied
    (Settings' manual check): log nothing extra — the
    "[sys] exiting (restart)" line is written by
    check_and_update before this runs — and exit 1 on a
    short timer so the caller can show its result first.
    The supervisor relaunches on code 1."""
    def _die():
        try:
            os._exit(1)
        except Exception:
            pass
    threading.Timer(1.0, _die).start()


def _restart_now(restart_fn, remote, applied_count):
    """The actual restart for an applied update (v7.9 item
    G factored this out of check_and_update so the deferred
    path fires the IDENTICAL sequence): the exiting line,
    the v7.7 speech stop, then the restart callback."""
    _lb(f"[sys] exiting (restart): self-update to v{remote} "
        f"({applied_count} files applied)")
    # v7.7: stop in-flight speech BEFORE the restart begins
    # — the 2026-11-16 11:53 self-update restart exited
    # code 1 with speech threads inside the voice layer.
    try:
        import voice as _voice_mod
        _voice_mod.stop_for_exit()
    except Exception:
        pass
    try:
        (restart_fn or _default_restart)()
    except Exception:
        _default_restart()


def _deferred_restart(restart_fn, remote, applied_count,
                      probe=None, cap_s=None, poll_s=None):
    """v7.9 (item G): poll the busy state until the voice
    turn ends, then restart; after cap_s, restart anyway —
    never cut a conversation mid-sentence, never wait
    forever. Runs on a daemon thread from check_and_update;
    tests drive it directly with a scripted probe and tiny
    cap/poll. Returns "idle" or "cap"."""
    if probe is None:
        probe = _turn_busy
    cap = DEFER_MAX_S if cap_s is None else float(cap_s)
    poll = DEFER_POLL_S if poll_s is None else float(poll_s)
    waited = 0.0
    while True:
        try:
            busy = bool(probe())
        except Exception:
            busy = False
        if not busy:
            _lb("[update] conversation finished — "
                "restarting for the update now")
            _restart_now(restart_fn, remote, applied_count)
            return "idle"
        if waited >= cap:
            _lb("[update] restart defer cap reached — "
                "restarting for the update anyway")
            _restart_now(restart_fn, remote, applied_count)
            return "cap"
        time.sleep(poll)
        waited += poll


def check_and_update(cfg, base_dir=BASE_DIR, http=None,
                     restart_fn=None, force=False,
                     busy_fn=None):
    """One update check. Returns a short status string:

        "not-configured"  repo/token not set — nothing done
        "disabled"        auto_update off (scheduled path)
        "current"         already on the newest version
        "skipped-failed"  this version failed < 5 min ago
        "updated"         applied; a restart is on its way
        "error: ..."      one failure, logged, nothing applied

    Never raises, never blocks beyond the bounded HTTP calls.
    """
    cfg = cfg or {}
    repo = str(cfg.get("github_repo") or "").strip()
    token = str(cfg.get("github_token") or "").strip()
    if not repo or not token or "/" not in repo:
        return "not-configured"
    if not force and not cfg.get("auto_update", True):
        return "disabled"
    remote = fetch_remote_version(repo, token, http=http)
    if remote is None:
        _lb("[update] could not read the repo version "
            "(check the GitHub token in Settings → Updates) "
            "— skipping this check")
        return "error: version fetch failed"
    current = local_version(base_dir)
    if not is_newer(remote, current):
        return "current"
    if not force:
        failed = _failed.get(repo)
        if failed and failed[0] == remote \
                and time.monotonic() - failed[1] < FAILED_RETRY_S:
            return "skipped-failed"
    blob = download_zipball(repo, token, http=http)
    if not blob:
        _failed[repo] = (remote, time.monotonic())
        _lb(f"[update] v{remote} download failed — will retry "
            "at the next scheduled check")
        return "error: download failed"
    try:
        applied = apply_update(blob, base_dir)
    except Exception as exc:
        _failed[repo] = (remote, time.monotonic())
        _lb(f"[update] v{remote} could not be applied "
            f"({type(exc).__name__}: {exc}) — will retry at "
            "the next scheduled check")
        return "error: apply failed"
    write_updated_marker(remote, base_dir)
    # v7.9 (item G): if a voice turn is in progress, the
    # restart DEFERS until the turn ends (polled, capped at
    # DEFER_MAX_S, then applied anyway) — the update is
    # already staged + marked; only the restart waits. Not
    # busy (the overwhelmingly common case, and every
    # pre-v7.9 caller) = the v7.8 immediate path.
    _busy = False
    try:
        _busy = bool(busy_fn()) if busy_fn is not None \
            else _turn_busy()
    except Exception:
        _busy = False
    if _busy:
        _lb(f"[update] v{remote} applied — restart deferred "
            "until the current conversation ends "
            f"(max {int(DEFER_MAX_S)}s)")
        threading.Thread(
            target=_deferred_restart,
            args=(restart_fn, remote, len(applied)),
            kwargs={"probe": busy_fn} if busy_fn is not None
            else {},
            daemon=True, name="nalox-updater-defer").start()
        return "updated"
    _restart_now(restart_fn, remote, len(applied))
    return "updated"


def start_background(cfg, restart_fn=None):
    """The scheduled checker (called once from nalox.py's
    boot): first check ~60 s after start, then every 5 min
    (v7.9 item G; 30 min v7.2–v7.8, 6-hourly through v7.1).
    Silent no-op when repo/token are unset or auto_update is
    off — check_and_update re-reads the live config each
    cycle, so values Arjun saves in Settings apply without a
    restart of the checker itself. Never raises.

    v7.9: also registers (cfg, restart_fn) for poke_check —
    the Command Center's show path pokes through here."""
    global _started
    _poke_state["cfg"] = cfg
    _poke_state["restart_fn"] = restart_fn
    if _started:
        return
    _started = True

    def _loop():
        time.sleep(CHECK_FIRST_DELAY_S)
        while True:
            try:
                live = cfg
                try:
                    from config import load_config
                    live = load_config()
                except Exception:
                    pass
                check_and_update(live, restart_fn=restart_fn)
            except Exception as exc:
                log.warning("update check cycle failed: %s", exc)
            time.sleep(CHECK_INTERVAL_S)

    threading.Thread(target=_loop, daemon=True,
                     name="nalox-updater").start()
