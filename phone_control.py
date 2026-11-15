"""Phone control via ADB (v5.4) — Arjun's Android phone, from
the laptop, over Wi-Fi. No cable, ever, in the normal flow.

Arjun's picture (2026-11-15): the phone is usually FAR from the
laptop — left charging somewhere else in the house. Sitting at
the laptop he says "Nalox, call my mother" and the phone across
the room must act, untouched. So the connection is ADB over
Wi-Fi via Android 11+ Wireless debugging pairing:

  1. On the phone (one time): Developer options → Wireless
     debugging ON → "Pair device with pairing code" shows an
     IP:pairing-port and a 6-digit code.
  2. Those two values + the IP:connect-port from the Wireless
     debugging main screen go into Settings → Phone (config
     phone_pair_address / phone_pair_code / phone_wifi_address
     — they stay on this laptop, like his API keys).
  3. pair_phone() runs `adb pair` + `adb connect`. From then
     on, ensure_connected() re-runs `adb connect` whenever no
     authorized device is present — at Brain boot (background
     thread) and before every phone command.

A USB device that happens to be plugged in and authorized is
used silently (it is just another line in `adb devices`); the
cable is never the presented path — it survives only as the
one-time `adb tcpip 5555` alternative for phones whose
wireless pairing misbehaves (see the update README).

ADB itself ships with Nalox: the official Google platform-
tools (adb.exe + AdbWinApi.dll + AdbWinUsbApi.dll) live in the
platform-tools/ folder next to this file and win discovery;
config phone_adb_path overrides; PATH is the last resort.

GOLDEN RULES (same as the rest of Nalox):
  * Every adb call is a subprocess with a short timeout
    (<= 10 s) and CREATE_NO_WINDOW on Windows.
  * NOTHING in here raises into the brain. Actions return
    small dicts — {"ok": True, ...} or {"ok": False,
    "reason": ..., "state": ...} — and the brain phrases the
    honest spoken reply from them, in the command's language.
  * Connection state is cached for 60 s after a success, so a
    chatty command sequence doesn't pay an `adb devices`
    round-trip before every single action.
"""
import logging
import os
import re
import shutil
import subprocess
import threading
import time

log = logging.getLogger("nalox.phone")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ADB_TIMEOUT = 10          # seconds, per single adb invocation
CONNECT_CACHE_S = 60.0    # a success is trusted this long

# ------------------------------------------------------------ app map
# Canonical key -> Android package. Launched with monkey (the
# LAUNCHER intent) — no per-app activity names to maintain.
APP_PACKAGES = {
    "youtube": "com.google.android.youtube",
    "whatsapp": "com.whatsapp",
    "instagram": "com.instagram.android",
    "chrome": "com.android.chrome",
    "telegram": "org.telegram.messenger",
    "spotify": "com.spotify.music",
    "camera": "com.android.camera2",      # best-effort (OEMs vary)
    "settings": "com.android.settings",
}

# What Arjun might SAY (any of his three languages, code-mixed)
# -> canonical key above.
APP_ALIASES = {
    "youtube": "youtube", "you tube": "youtube",
    "ইউটিউব": "youtube", "यूट्यूब": "youtube",
    "whatsapp": "whatsapp", "whats app": "whatsapp",
    "হোয়াটসঅ্যাপ": "whatsapp", "व्हाट्सएप": "whatsapp",
    "instagram": "instagram", "insta": "instagram",
    "ইনস্টাগ্রাম": "instagram", "इंस्टाग्राम": "instagram",
    "chrome": "chrome", "browser": "chrome",
    "ক্রোম": "chrome", "क्रोम": "chrome",
    "telegram": "telegram", "টেলিগ্রাম": "telegram",
    "टेलीग्राम": "telegram",
    "spotify": "spotify", "স্পটিফাই": "spotify",
    "स्पॉटिफ़ाई": "spotify", "स्पोटिफाई": "spotify",
    "camera": "camera", "ক্যামেরা": "camera", "कैमरा": "camera",
    "settings": "settings", "সেটিংস": "settings",
    "सेटिंग्स": "settings", "सेटिंग": "settings",
}

# Relation aliases for the contacts book: what he might say ->
# the canonical key he is most likely to have saved. Resolution
# ALSO tries the spoken form itself and a trailing-কে-stripped
# Bengali form, so a contact saved under any of these spellings
# is found.
_CONTACT_ALIASES = {
    "mother": ("mother", "mom", "mummy", "maa", "মা", "মাকে",
               "माँ", "मां", "अम्मी"),
    "father": ("father", "dad", "papa", "বাবা", "বাবাকে",
               "पिता", "पापा", "बाबा"),
}


# ------------------------------------------------------------ adb core
def _bundled_adb_path():
    """The platform-tools candidate next to this file."""
    name = "adb.exe" if os.name == "nt" else "adb"
    return os.path.join(BASE_DIR, "platform-tools", name)


def find_adb(cfg):
    """Locate adb: config override → bundled platform-tools →
    PATH. Returns a path or None. Never raises."""
    try:
        override = str((cfg or {}).get("phone_adb_path")
                       or "").strip()
        if override and os.path.isfile(override):
            return override
        bundled = _bundled_adb_path()
        if os.path.isfile(bundled):
            return bundled
        return shutil.which("adb")
    except Exception:
        return None


def _run_adb(cfg, args, timeout=ADB_TIMEOUT):
    """Run one adb command. Returns (output, None) on a
    completed run (whatever the exit code — callers read the
    text), or (None, reason) when adb is missing or the call
    itself failed/timed out. Never raises."""
    adb = find_adb(cfg)
    if adb is None:
        return None, "noadb"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(
            [adb] + [str(a) for a in args],
            capture_output=True, text=True, timeout=timeout,
            **kwargs)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _parse_devices(out):
    """`adb devices` text -> [(serial, state), ...]."""
    devices = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        if line.startswith("*"):      # daemon chatter
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


# ------------------------------------------------- connection state
_conn_lock = threading.Lock()
_conn_cache = {"at": 0.0, "state": None, "serial": None}


def _cache_ok(serial):
    with _conn_lock:
        _conn_cache.update(at=time.monotonic(), state="ok",
                           serial=serial)


def _cached_ok():
    with _conn_lock:
        if _conn_cache.get("state") == "ok" and \
                time.monotonic() - _conn_cache.get("at", 0.0) \
                < CONNECT_CACHE_S:
            return _conn_cache.get("serial")
    return None


def device_state(cfg, allow_connect=True):
    """(state, serial) — state is one of:
      "ok"           an authorized device is ready
      "unauthorized" a device is attached but not allowed yet
                     (the phone is showing / needs the Allow tap)
      "none"         nothing reachable
      "noadb"        the adb tools themselves are missing

    With allow_connect (the default) and no authorized device,
    a saved phone_wifi_address gets ONE `adb connect` attempt
    before the state is reported — this is the auto-connect
    the owner asked for: it runs before every phone command
    and once at Brain boot. A recent success (< 60 s) is
    served from cache without touching adb at all. Never
    raises."""
    try:
        if find_adb(cfg) is None:
            return "noadb", None
        serial = _cached_ok()
        if serial:
            return "ok", serial
        out, _err = _run_adb(cfg, ["devices"])
        if out is None:
            return "none", None
        devices = _parse_devices(out)
        for serial, state in devices:
            if state == "device":
                _cache_ok(serial)
                return "ok", serial
        for serial, state in devices:
            if state == "unauthorized":
                # A device that is present but not allowed
                # will not be fixed by connecting again — the
                # phone needs the Allow tap (or a fresh pair).
                # Report it at once instead of burning the
                # connect attempt below on it.
                return "unauthorized", None
        if allow_connect:
            addr = str((cfg or {}).get("phone_wifi_address")
                       or "").strip()
            if addr:
                _run_adb(cfg, ["connect", addr])
                out, _err = _run_adb(cfg, ["devices"])
                devices = _parse_devices(out) if out else []
                for serial, state in devices:
                    if state == "device":
                        _cache_ok(serial)
                        return "ok", serial
                for serial, state in devices:
                    if state == "unauthorized":
                        return "unauthorized", None
        return "none", None
    except Exception as exc:  # the golden rule: never raise
        log.warning("device_state failed: %s", exc)
        return "none", None


def ensure_connected(cfg):
    """Boot-time / pre-command auto-connect: exactly
    device_state with the Wi-Fi connect attempt enabled.
    Returns (state, serial); never raises."""
    return device_state(cfg, allow_connect=True)


def pair_phone(cfg):
    """The Settings "Pair phone (Wi-Fi)" button: `adb pair`
    with the saved pairing address + code, then `adb connect`
    to the saved Wi-Fi address, then verify. Returns
    (ok, message) — the message is written for the Settings
    status line, so it says what to fix when it fails. All
    values come from cfg (Settings merges the live field
    values in before calling). Never raises."""
    try:
        if find_adb(cfg) is None:
            return False, ("ADB tools not found on this laptop "
                           "— phone control is off.")
        pair_addr = str((cfg or {}).get("phone_pair_address")
                        or "").strip()
        pair_code = str((cfg or {}).get("phone_pair_code")
                        or "").strip()
        wifi_addr = str((cfg or {}).get("phone_wifi_address")
                        or "").strip()
        if not pair_addr or not pair_code:
            return False, ("Type the pairing address (IP:port) "
                           "and the 6-digit code from the "
                           "phone's “Pair device with pairing "
                           "code” screen first.")
        out, err = _run_adb(cfg, ["pair", pair_addr, pair_code])
        if out is None:
            return False, (f"Pairing could not run ({err}). "
                           "Check the phone and this laptop are "
                           "on the same Wi-Fi.")
        if "Successfully paired" not in out:
            snippet = " ".join(out.split())[:100]
            return False, ("Pairing failed — the code is only "
                           "valid while that phone screen is "
                           f"open; try again. ({snippet})")
        if wifi_addr:
            out, _err = _run_adb(cfg, ["connect", wifi_addr])
            if out is not None and "connected" not in out.lower():
                snippet = " ".join(out.split())[:100]
                return False, (f"Paired ✓ — but connecting to "
                               f"{wifi_addr} failed ({snippet}). "
                               "Copy the IP:port from the "
                               "Wireless debugging MAIN screen "
                               "into the Wi-Fi address field.")
        state, serial = device_state(cfg, allow_connect=False)
        if state == "ok":
            return True, (f"Paired and connected ✓ — phone "
                          f"{serial} is ready, no cable needed.")
        if wifi_addr:
            return False, ("Paired ✓ — but the phone is not "
                           "answering yet. Keep Wireless "
                           "debugging ON and the phone awake, "
                           "then press Test connection.")
        return False, ("Paired ✓ — now copy the IP:port from "
                       "the Wireless debugging MAIN screen "
                       "into the Wi-Fi address field, then "
                       "press this button again.")
    except Exception as exc:
        return False, f"Pairing failed: {exc}"


def phone_status_line(cfg):
    """One human line for Settings → Phone's Test button and
    the Doctor: tools? connection? contacts? Never raises."""
    try:
        if find_adb(cfg) is None:
            return "✗ ADB tools missing — phone control is off."
        contacts = (cfg or {}).get("phone_contacts") or {}
        n = len(contacts) if isinstance(contacts, dict) else 0
        state, serial = device_state(cfg, allow_connect=True)
        if state == "ok":
            return (f"✓ Phone connected ({serial}) — "
                    f"{n} contact(s) saved.")
        if state == "unauthorized":
            return ("✗ Phone found but not authorized — tap "
                    "Allow on the phone (Wireless debugging).")
        if str((cfg or {}).get("phone_wifi_address")
               or "").strip():
            return ("✗ Phone not reachable on Wi-Fi — awake + "
                    "same Wi-Fi + Wireless debugging ON? If "
                    "it restarted, re-pair below.")
        return ("✗ Not paired yet — fill the pairing fields "
                "from the phone's Wireless debugging screen "
                "and press “Pair phone (Wi-Fi)”.")
    except Exception as exc:
        return f"✗ Phone check failed: {exc}"


# ------------------------------------------------------------ contacts
def _contact_candidates(name):
    """Spellings to try for a spoken contact name, in order:
    the name itself, its alias group (both directions), and
    the Bengali object-suffix (-কে) stripped form."""
    n = (name or "").strip().lower()
    if not n:
        return []
    cands = [n]
    if n.endswith("কে") and len(n) > 2:
        cands.append(n[:-2])
    for canon, aliases in _CONTACT_ALIASES.items():
        if n == canon or n in aliases:
            for a in (canon,) + tuple(aliases):
                if a not in cands:
                    cands.append(a)
    return cands


def resolve_contact(cfg, name):
    """(saved_key, number) for a spoken name, or (None, None).
    The contacts book is config phone_contacts — a dict the
    owner fills once in Settings → Phone."""
    contacts = (cfg or {}).get("phone_contacts") or {}
    if not isinstance(contacts, dict):
        return None, None
    book = {}
    for key, value in contacts.items():
        k = str(key).strip().lower()
        v = str(value).strip()
        if k and v:
            book[k] = v
    for cand in _contact_candidates(name):
        if cand in book:
            return cand, book[cand]
    return None, None


def _clean_number(number):
    """Keep digits + one leading +; None when it can't be a
    phone number."""
    raw = str(number or "").strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 6:
        return None
    return ("+" if plus else "") + digits


# ------------------------------------------------------------ actions
def call_number(cfg, number):
    """Place a call from the phone. CALL intent first; when
    the phone refuses it (some brands/permissions), fall back
    to the DIAL intent — dialer open, number filled, one tap
    left for the owner — and SAY which happened (mode)."""
    num = _clean_number(number)
    if num is None:
        return {"ok": False, "reason": "bad_number"}
    state, _serial = device_state(cfg)
    if state != "ok":
        return {"ok": False, "reason": "not_connected",
                "state": state}
    for action, mode in (("android.intent.action.CALL", "call"),
                         ("android.intent.action.DIAL", "dial")):
        out, _err = _run_adb(
            cfg, ["shell", "am", "start", "-a", action,
                  "-d", f"tel:{num}"])
        if out is not None and "Starting: Intent" in out \
                and "Error" not in out and "Exception" not in out:
            return {"ok": True, "mode": mode, "number": num}
    return {"ok": False, "reason": "call_failed"}


def call_contact(cfg, name):
    """Call a saved contact by spoken name/relation."""
    key, number = resolve_contact(cfg, name)
    if number is None:
        return {"ok": False, "reason": "unknown_contact",
                "name": (name or "").strip()}
    result = call_number(cfg, number)
    result["name"] = key
    result["number"] = number
    return result


def normalize_app(name):
    """A spoken app name (any of the three languages) -> the
    canonical APP_PACKAGES key, or None."""
    raw = (name or "").strip().lower().strip(".,!?।")
    if not raw:
        return None
    if raw in APP_ALIASES:
        return APP_ALIASES[raw]
    for token in raw.split():
        token = token.strip(".,!?।")
        if token in APP_ALIASES:
            return APP_ALIASES[token]
    return None


def open_app(cfg, app_name):
    """Open an app ON THE PHONE via monkey's LAUNCHER intent."""
    canon = normalize_app(app_name)
    if canon is None:
        return {"ok": False, "reason": "unknown_app",
                "app": (app_name or "").strip()}
    state, _serial = device_state(cfg)
    if state != "ok":
        return {"ok": False, "reason": "not_connected",
                "state": state, "app": canon}
    package = APP_PACKAGES[canon]
    out, _err = _run_adb(
        cfg, ["shell", "monkey", "-p", package,
              "-c", "android.intent.category.LAUNCHER", "1"])
    if out is not None and "Events injected" in out:
        return {"ok": True, "app": canon, "package": package}
    if out is not None and ("No activities found" in out
                            or "monkey aborted" in out
                            or "** Error" in out):
        return {"ok": False, "reason": "not_installed",
                "app": canon, "package": package}
    if out is None:
        return {"ok": False, "reason": "not_connected",
                "state": "none", "app": canon}
    return {"ok": False, "reason": "open_failed", "app": canon}


def phone_battery(cfg):
    """The phone's battery percentage via dumpsys."""
    state, _serial = device_state(cfg)
    if state != "ok":
        return {"ok": False, "reason": "not_connected",
                "state": state}
    out, _err = _run_adb(cfg, ["shell", "dumpsys", "battery"])
    if out:
        m = re.search(r"level:\s*(\d+)", out)
        if m:
            return {"ok": True, "level": int(m.group(1))}
    return {"ok": False, "reason": "battery_failed"}
