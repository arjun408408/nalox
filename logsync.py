"""Nalox log sync (v6.9) — the log sends itself home.

The owner's standing order (2026-11-15 21:05 IST): he does
not read code or logs and cannot judge what to send Muse
or when — so Muse must check Nalox's log itself and fix
problems proactively. He tried to hand over access by
pasting the file:/// path of nalox_page.html on his PC,
which no one outside that PC can open. This module closes
the loop instead: Nalox uploads its own diagnostics log to
his PRIVATE GitHub repo, where Muse can read it with gh.

What is sent (one file, overwritten each sync):
    branch  `logs`, path `logs/latest-log.txt` in the SAME
    repo the updater uses (config github_repo, default
    arjun408408/nalox), containing a small header (Nalox
    version, local timestamp, "log sync" marker) + the
    tail of nalox_log.txt (~150 KB) + the tail of
    nalox_fault.log (~20 KB, when it exists). nalox_log.txt
    is the source of truth — nalox_page.html is only its
    HTML rendering (logbook.py), so the .txt is uploaded.

Auth: the SAME token as self-update (config github_token,
Settings → 🔄 Updates). Uploading needs the token to have
Contents: Read AND WRITE on the repo — the earlier
read-only instruction is superseded for exactly this
reason (a read-only token can fetch updates but can never
send the log home).

Triggers (all on ONE daemon thread; network timeouts
≤ 10 s; nothing here ever blocks ears/brain/voice/UI,
never speaks, never pops up, never raises into a caller):
    - first sync ~75 s after boot, then every 10 minutes;
    - error-triggered: logbook calls the registered hook
      whenever an ERROR line is written; the hook only sets
      a dirty flag, the thread polls it every ~30 s and
      syncs early — debounced to at most one error-triggered
      sync per 3 minutes.

Dormancy / failure discipline:
    - token empty -> fully dormant: zero API calls, zero
      log lines (the feature simply does not exist yet).
    - an upload rejected with 401/403 (e.g. a read-only
      token) -> exactly ONE local log line per session
      ("[logsync] token cannot write — …") and the feature
      goes dormant for the rest of the session.
    - any other network failure: silent; the next scheduled
      tick retries. No retry loops, no noise.

State: logsync_state.json in the install folder (last sync
time + status) — USER DATA: it is on the updater's deny
list, never ships in a pack, never enters git.
"""
import base64
import json
import logging
import os
import threading
import time

log = logging.getLogger("nalox.logsync")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "logsync_state.json")
LOG_PATH = os.path.join(BASE_DIR, "nalox_log.txt")
FAULT_PATH = os.path.join(BASE_DIR, "nalox_fault.log")

API_ROOT = "https://api.github.com/repos/"
BRANCH = "logs"
REMOTE_PATH = "logs/latest-log.txt"
HTTP_TIMEOUT = 10            # every GitHub call is bounded

FIRST_DELAY_S = 75.0         # first sync ~75 s after boot
INTERVAL_S = 10 * 60         # then every 10 minutes
POLL_S = 30.0                # the dirty-flag poll cadence
ERROR_DEBOUNCE_S = 3 * 60    # ≤1 error-triggered sync / 3 min

LOG_TAIL_BYTES = 150 * 1024      # nalox_log.txt tail cap
FAULT_TAIL_BYTES = 20 * 1024     # nalox_fault.log tail cap

_lock = threading.Lock()
_dirty = False               # an ERROR line was written
_started = False
_session_dormant = False     # a 401/403 parked us (session)
_warned = False              # the one allowed warning line
_last_error_sync = 0.0       # monotonic time of last error sync


def _lb(text):
    """One logbook SYSTEM line, guarded (never raises)."""
    try:
        import logbook
        logbook.log("SYSTEM", text)
    except Exception:
        pass
    log.info("%s", text)


# ------------------------------------------------------------ content
def _tail_text(path, cap):
    """The last `cap` bytes of a file as text ("" if absent).

    A truncated head drops its partial first line so the
    upload never starts mid-sentence. Never raises."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > cap:
                fh.seek(size - cap)
            data = fh.read()
        text = data.decode("utf-8", "replace")
        if size > cap:
            nl = text.find("\n")
            if nl >= 0:
                text = text[nl + 1:]
            text = ("[... earlier log lines trimmed by log "
                    "sync ...]\n" + text)
        return text
    except Exception:
        return ""


def _version(base_dir):
    try:
        with open(os.path.join(base_dir, "version.txt"),
                  encoding="utf-8") as fh:
            return fh.read().strip() or "?"
    except Exception:
        return "?"


def build_content(base_dir=BASE_DIR):
    """The exact bytes' text uploaded as logs/latest-log.txt:
    header + nalox_log.txt tail + separator + fault tail."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    header = ("Nalox log sync\n"
              f"Version: {_version(base_dir)}\n"
              f"Synced: {stamp} (laptop local time)\n"
              "log sync: nalox diagnostics upload — the tail "
              "of nalox_log.txt, then nalox_fault.log\n")
    log_tail = _tail_text(os.path.join(base_dir, "nalox_log.txt"),
                          LOG_TAIL_BYTES)
    fault_tail = _tail_text(
        os.path.join(base_dir, "nalox_fault.log"),
        FAULT_TAIL_BYTES)
    return (header
            + "\n===== nalox_log.txt (tail) =====\n"
            + (log_tail or "(log file is empty or missing)")
            + "\n===== nalox_fault.log (tail) =====\n"
            + (fault_tail or "(no fault log)"))


# ------------------------------------------------------------ state
def _write_state(status, base_dir=BASE_DIR):
    """Record the last sync in logsync_state.json (user data,
    deny-listed in updater.py). Never raises."""
    try:
        state = {"status": status,
                 "last_sync": time.time(),
                 "last_sync_local": time.strftime("%H:%M")}
        with open(os.path.join(base_dir, "logsync_state.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def read_state(base_dir=BASE_DIR):
    """logsync_state.json as a dict ({} when absent). The
    Settings → Updates status line reads this. Never raises."""
    try:
        with open(os.path.join(base_dir, "logsync_state.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------ HTTP
def _default_http(method, url, headers, json_body=None):
    """(status, body_bytes) via requests — bounded, always."""
    import requests
    resp = requests.request(method, url, headers=headers or {},
                            json=json_body, timeout=HTTP_TIMEOUT)
    return resp.status_code, resp.content


def _headers(token):
    return {"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Nalox-LogSync"}


def _json_of(body):
    try:
        return json.loads((body or b"").decode("utf-8", "replace"))
    except Exception:
        return {}


# ------------------------------------------------------------ the sync
def _forbid():
    """A 401/403 landed: warn ONCE (locally), then go dormant
    for the rest of the session. Never raises."""
    global _session_dormant, _warned
    _session_dormant = True
    if not _warned:
        _warned = True
        _lb("[logsync] token cannot write — log not sent; "
            "the Updates token needs Contents: Read and write")


def sync_once(cfg, http=None, base_dir=BASE_DIR):
    """One log upload. Returns a short status string:

        "sent"            uploaded to logs/latest-log.txt
        "not-configured"  repo/token unset — fully dormant,
                          zero API calls, zero log lines
        "dormant"         parked for this session by a 401/403
        "forbidden"       THIS attempt was rejected 401/403
        "error"           any other failure (silent; the next
                          scheduled tick retries)

    Never raises, never blocks beyond the bounded HTTP calls.
    """
    if _session_dormant:
        return "dormant"
    cfg = cfg or {}
    repo = str(cfg.get("github_repo")
               or "arjun408408/nalox").strip()
    token = str(cfg.get("github_token") or "").strip()
    if not repo or "/" not in repo or not token:
        return "not-configured"
    http = http or _default_http
    headers = _headers(token)
    root = API_ROOT + repo
    try:
        # 1) The logs branch must exist — create it from
        #    main's HEAD the first time.
        status, _body = http(
            "GET", f"{root}/git/ref/heads/{BRANCH}", headers)
        if status in (401, 403):
            _forbid()
            _write_state("forbidden", base_dir)
            return "forbidden"
        if status == 404:
            mstatus, mbody = http(
                "GET", f"{root}/git/ref/heads/main", headers)
            if mstatus in (401, 403):
                _forbid()
                _write_state("forbidden", base_dir)
                return "forbidden"
            if mstatus != 200:
                _write_state("error", base_dir)
                return "error"
            main_sha = (_json_of(mbody).get("object")
                        or {}).get("sha")
            if not main_sha:
                _write_state("error", base_dir)
                return "error"
            cstatus, _cbody = http(
                "POST", f"{root}/git/refs", headers,
                {"ref": f"refs/heads/{BRANCH}", "sha": main_sha})
            if cstatus in (401, 403):
                _forbid()
                _write_state("forbidden", base_dir)
                return "forbidden"
            if cstatus not in (201, 422):
                # 422 = the branch already exists (a race) —
                # that is success for our purposes.
                _write_state("error", base_dir)
                return "error"
        elif status != 200:
            _write_state("error", base_dir)
            return "error"
        # 2) The current file's sha (needed to update it).
        sha = None
        gstatus, gbody = http(
            "GET", f"{root}/contents/{REMOTE_PATH}?ref={BRANCH}",
            headers)
        if gstatus in (401, 403):
            _forbid()
            _write_state("forbidden", base_dir)
            return "forbidden"
        if gstatus == 200:
            sha = _json_of(gbody).get("sha") or None
        elif gstatus != 404:
            _write_state("error", base_dir)
            return "error"
        # 3) Create/update the file on the logs branch.
        content = build_content(base_dir)
        payload = {
            "message": "nalox log sync "
                       + time.strftime("%Y-%m-%d %H:%M:%S"),
            "content": base64.b64encode(
                content.encode("utf-8")).decode("ascii"),
            "branch": BRANCH,
        }
        if sha:
            payload["sha"] = sha
        pstatus, _pbody = http(
            "PUT", f"{root}/contents/{REMOTE_PATH}", headers,
            payload)
        if pstatus in (401, 403):
            _forbid()
            _write_state("forbidden", base_dir)
            return "forbidden"
        if pstatus not in (200, 201):
            _write_state("error", base_dir)
            return "error"
    except Exception as exc:
        # A network explosion is just a missed tick.
        log.warning("log sync failed: %s", exc)
        _write_state("error", base_dir)
        return "error"
    _write_state("sent", base_dir)
    _lb("[logsync] log sent")
    return "sent"


# ------------------------------------------------------------ triggers
def notify_error():
    """The logbook ERROR hook: only sets the dirty flag (the
    sync thread does the work). Cheap, thread-safe, never
    raises — it runs inside logbook.log()."""
    global _dirty
    try:
        with _lock:
            _dirty = True
    except Exception:
        pass


def start_background(cfg):
    """Start the sync thread (called once from nalox.py's
    boot): first sync ~75 s in, then every 10 min, plus
    debounced error-triggered syncs. The live config is
    re-read each cycle (updater parity), so a token pasted
    in Settings applies without restarting the thread.
    Silent no-op behaviour when the token is unset is
    sync_once's job. Never raises."""
    global _started
    if _started:
        return
    _started = True
    try:
        import logbook
        logbook.register_error_hook(notify_error)
    except Exception:
        pass

    def _live_cfg():
        try:
            from config import load_config
            return load_config()
        except Exception:
            return cfg

    def _loop():
        global _dirty, _last_error_sync
        time.sleep(FIRST_DELAY_S)
        last_periodic = time.monotonic() - INTERVAL_S
        while True:
            try:
                now = time.monotonic()
                if _session_dormant:
                    pass
                elif _dirty and \
                        now - _last_error_sync >= ERROR_DEBOUNCE_S:
                    with _lock:
                        _dirty = False
                    _last_error_sync = now
                    last_periodic = now
                    sync_once(_live_cfg())
                elif now - last_periodic >= INTERVAL_S:
                    last_periodic = now
                    sync_once(_live_cfg())
            except Exception as exc:
                log.warning("log sync cycle failed: %s", exc)
            time.sleep(POLL_S)

    threading.Thread(target=_loop, daemon=True,
                     name="nalox-logsync").start()
