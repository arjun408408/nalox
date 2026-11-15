"""Nalox Phone link (v6.0) — the PC half of the companion app.

The owner's chosen pairing flow (he rejected ADB pairing:
"এতটা কষ্ট করা লাগবে না"): Nalox sends him a LINK (via
Telegram) → he opens it on the phone → a small page served
by THIS module offers [Install Nalox Phone] and [Connect] →
the app stores host/port/token from the nalox:// deep link
and holds a plain-TCP connection to this PC → voice commands
on the laptop then execute on the phone.

Two servers, both stdlib, both on their own threads:

* HTTP pairing server on port 8765 — runs ONLY while
  pairing mode is on (10 minutes, started from Settings or
  the "send me the phone link" voice/Telegram intent).
  Serves the pairing page and the APK itself
  (phone-app/nalox-phone.apk beside this file).

* TCP command server on port 8766 — always listening while
  Nalox runs, but the first line from any client must be
  {"type":"auth","token":...}; a wrong token is closed and
  logged. One phone at a time.

The brain's phone intents route LINK-FIRST through the
call_contact / open_app / phone_battery mirrors below —
they return exactly the result-dict shapes phone_control
returns, so every existing reply builder works unchanged.
Everything here never raises into the caller.
"""

import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAIR_HTTP_PORT = 8765
LINK_TCP_PORT = 8766
PAIRING_SECONDS = 600
ACK_TIMEOUT = 20.0

import logging
log = logging.getLogger("nalox.phone_link")


def _lb(text):
    try:
        import logbook
        logbook.log("SYSTEM", "[phone-link] " + text)
    except Exception:
        pass
    log.info("[phone-link] %s", text)


# ---------------------------------------------------------------- state
_lock = threading.Lock()
_state = {
    "cfg": None,
    "started": False,
    "pairing_until": 0.0,
    "http_server": None,
    "conn": None,          # the phone's socket, once authed
    "conn_lock": threading.Lock(),
    "device": "",
    "battery": None,
    "next_id": 0,
    "pending": {},         # id -> [threading.Event, ack-or-None]
    "memory_token": "",    # fallback if config can't persist
}


# ---------------------------------------------------------------- token
def get_token(cfg):
    """The pairing token: config phone_link_token, generated
    on first use (secrets.token_hex) and persisted back into
    config.json when possible. Regenerating it in Settings
    invalidates every old pairing.

    The session's adopted token (memory) wins over any
    single cfg dict: several cfg objects float around the
    app (boot config, Settings merges, test configs) and a
    token-less one must never make the link forget the
    token the phone already paired with."""
    if _state["memory_token"]:
        return _state["memory_token"]
    token = str((cfg or {}).get("phone_link_token") or "").strip()
    if not token:
        try:
            path = os.path.join(BASE_DIR, "config.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    token = str(
                        data.get("phone_link_token") or "").strip()
        except Exception:
            token = ""
    if token:
        _state["memory_token"] = token
        return token
    token = secrets.token_hex(16)
    _state["memory_token"] = token
    try:
        path = os.path.join(BASE_DIR, "config.json")
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        if isinstance(data, dict) and not data.get("phone_link_token"):
            data["phone_link_token"] = token
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            if isinstance(cfg, dict):
                cfg["phone_link_token"] = token
            _lb("pairing token generated and saved")
    except Exception as exc:
        log.warning("phone_link: could not persist token: %s", exc)
    return token


def regenerate_token(cfg):
    """Settings button: mint a fresh token (old pairings die
    with the old one — the phone must re-open a pairing link)."""
    token = secrets.token_hex(16)
    _state["memory_token"] = token
    try:
        path = os.path.join(BASE_DIR, "config.json")
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        if isinstance(data, dict):
            data["phone_link_token"] = token
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        if isinstance(cfg, dict):
            cfg["phone_link_token"] = token
    except Exception as exc:
        log.warning("phone_link: regenerate persist failed: %s", exc)
    drop_connection("token regenerated")
    _lb("pairing token regenerated — old pairings no longer work")
    return token


# ---------------------------------------------------------------- network
def lan_ip():
    """This PC's LAN address via the default-route source
    trick: the address the OS would use to leave the house.
    On the owner's topology (PC on the phone's hotspot) that
    IS the address the phone can reach."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        finally:
            probe.close()
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def pairing_url():
    return f"http://{lan_ip()}:{PAIR_HTTP_PORT}/"


def deep_link(cfg):
    return (f"nalox://pair?host={lan_ip()}&port={LINK_TCP_PORT}"
            f"&token={get_token(cfg)}")


# ---------------------------------------------------------------- pairing page
_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nalox Phone</title>
<style>
 body {{ background:#0d1117; color:#e8eef4; font-family:sans-serif;
        text-align:center; margin:0; padding:28px 18px; }}
 img {{ width:110px; height:110px; border-radius:50%; }}
 h1 {{ font-size:26px; margin:14px 0 4px; }}
 p {{ color:#9fb2c3; font-size:16px; line-height:1.45; }}
 a.btn {{ display:block; margin:18px auto; max-width:340px;
        padding:18px 10px; border-radius:14px; font-size:20px;
        font-weight:bold; text-decoration:none; color:#fff; }}
 .install {{ background:#1f6feb; }}
 .connect {{ background:#2ea043; }}
 code {{ word-break:break-all; color:#7ee0a3; font-size:12px; }}
</style></head><body>
<img src="/logo.png" alt="Nalox">
<h1>Nalox Phone</h1>
<p>Two taps and your phone is linked to Nalox on your laptop.</p>
<a class="btn install" href="/nalox-phone.apk">&#11015; 1. Install Nalox Phone</a>
<a class="btn connect" href="{deep}">&#128279; 2. Connect</a>
<p>After installing, tap <b>2. Connect</b> — the app opens,
saves this PC's address, and connects. No codes, nothing else
to type.</p>
<p>If Connect doesn't open the app, copy this link into the
app's paste box:<br><code>{deep}</code></p>
</body></html>"""


class _PairHandler(BaseHTTPRequestHandler):
    server_version = "NaloxPhone/1.0"

    def log_message(self, *args):  # keep the log clean
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                cfg = _state["cfg"] or {}
                page = _PAGE.format(deep=deep_link(cfg))
                self._send(200, page.encode("utf-8"),
                           "text/html; charset=utf-8")
            elif self.path == "/nalox-phone.apk":
                apk = os.path.join(BASE_DIR, "phone-app",
                                   "nalox-phone.apk")
                if os.path.exists(apk):
                    with open(apk, "rb") as fh:
                        self._send(200, fh.read(),
                                   "application/vnd.android."
                                   "package-archive")
                else:
                    self._send(404, b"APK not found on this PC",
                               "text/plain")
            elif self.path == "/logo.png":
                logo = os.path.join(BASE_DIR, "assets",
                                    "logo_round.png")
                if os.path.exists(logo):
                    with open(logo, "rb") as fh:
                        self._send(200, fh.read(), "image/png")
                else:
                    self._send(404, b"", "image/png")
            else:
                self._send(404, b"Not found", "text/plain")
        except Exception as exc:
            log.warning("phone_link http error: %s", exc)


def pairing_active():
    return time.time() < _state["pairing_until"]


def start_pairing(cfg):
    """Turn pairing mode on for PAIRING_SECONDS: the HTTP
    page goes live and the URL is returned (the caller sends
    it to the owner via Telegram)."""
    _state["cfg"] = cfg
    get_token(cfg)
    _state["pairing_until"] = time.time() + PAIRING_SECONDS
    if _state["http_server"] is None:
        try:
            server = ThreadingHTTPServer(("0.0.0.0", PAIR_HTTP_PORT),
                                         _PairHandler)
            _state["http_server"] = server
            threading.Thread(target=server.serve_forever,
                             daemon=True, name="phone-pair-http"
                             ).start()
            threading.Thread(target=_pairing_watchdog,
                             daemon=True, name="phone-pair-watch"
                             ).start()
        except Exception as exc:
            log.warning("phone_link: pairing server failed: %s", exc)
            _lb(f"pairing page could not start ({exc})")
            return pairing_url()
    url = pairing_url()
    _lb(f"pairing mode ON for {PAIRING_SECONDS // 60} minutes — "
        f"page at {url}")
    return url


def _pairing_watchdog():
    while _state["http_server"] is not None:
        if not pairing_active():
            server = _state["http_server"]
            _state["http_server"] = None
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            _lb("pairing mode OFF (time up) — pairing page closed")
            return
        time.sleep(2)


def stop_pairing():
    _state["pairing_until"] = 0.0


# ---------------------------------------------------------------- TCP link
def start(cfg):
    """Boot entry: remember the config and start the TCP
    command server (auth-gated; pairing mode stays OFF until
    asked). Idempotent."""
    with _lock:
        if _state["started"]:
            _state["cfg"] = cfg
            return
        _state["started"] = True
        _state["cfg"] = cfg
    threading.Thread(target=_tcp_server, daemon=True,
                     name="phone-link-tcp").start()
    _lb(f"command server listening on port {LINK_TCP_PORT} "
        "(waiting for the Nalox Phone app)")


def _tcp_server():
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", LINK_TCP_PORT))
        srv.listen(2)
        # v6.2 stability bound: accept() gets a 1 s timeout so
        # the loop is never parked inside one unbounded wait —
        # the timeout just loops back into accept (the except
        # below already treats it as a retry tick).
        srv.settimeout(1.0)
    except Exception as exc:
        log.warning("phone_link: TCP server failed: %s", exc)
        _lb(f"command server could not start ({exc})")
        return
    while True:
        try:
            conn, addr = srv.accept()
        except Exception:
            time.sleep(0.5)
            continue
        threading.Thread(target=_handle_conn, args=(conn, addr),
                         daemon=True, name="phone-link-conn").start()


def _handle_conn(conn, addr):
    authed = False
    reader = None
    try:
        conn.settimeout(30)
        reader = conn.makefile("r", encoding="utf-8", newline="\n")
        first = reader.readline()
        if not first:
            conn.close()
            return
        try:
            hello = json.loads(first.strip())
        except Exception:
            hello = {}
        token = get_token(_state["cfg"] or {})
        if hello.get("type") != "auth" \
                or not token \
                or str(hello.get("token") or "") != token:
            _lb(f"rejected a connection from {addr[0]} — wrong "
                "or missing pairing token")
            try:
                conn.close()
            except Exception:
                pass
            return
        device = str(hello.get("device") or "Android phone")
        drop_connection("replaced by a new connection",
                        keep=conn)
        with _state["conn_lock"]:
            _state["conn"] = conn
            _state["device"] = device
        authed = True
        _lb(f"phone connected: {device} ({addr[0]})")
        conn.settimeout(75)  # pings arrive every 20 s
        while True:
            line = reader.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("type") == "ping":
                _send_raw(conn, {"type": "pong"})
            elif "id" in msg and "ok" in msg:
                _resolve_pending(msg)
    except Exception as exc:
        log.info("phone_link conn ended: %s", exc)
    finally:
        if authed:
            with _state["conn_lock"]:
                if _state["conn"] is conn:
                    _state["conn"] = None
                    _state["device"] = ""
                    _fail_all_pending()
            _lb("phone disconnected")
        try:
            conn.close()
        except Exception:
            pass


def _send_raw(conn, obj):
    try:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        return True
    except Exception:
        return False


def drop_connection(reason, keep=None):
    with _state["conn_lock"]:
        old = _state["conn"]
        if old is not None and old is not keep:
            _state["conn"] = None
            _state["device"] = ""
            try:
                old.close()
            except Exception:
                pass
            _fail_all_pending()
            log.info("phone_link: connection dropped (%s)", reason)


def _resolve_pending(msg):
    try:
        cid = int(msg.get("id"))
    except Exception:
        return
    slot = _state["pending"].pop(cid, None)
    if slot is not None:
        slot[1] = msg
        slot[0].set()


def _fail_all_pending():
    for _cid, slot in list(_state["pending"].items()):
        slot[1] = {"ok": False, "reason": "not_connected"}
        slot[0].set()
    _state["pending"].clear()


# ---------------------------------------------------------------- API
def is_connected():
    with _state["conn_lock"]:
        return _state["conn"] is not None


def device_name():
    with _state["conn_lock"]:
        return _state["device"] or ""


def cached_battery():
    return _state["battery"]


def send_command(cmd, timeout=ACK_TIMEOUT):
    """Send one command dict to the phone; return its ack
    dict. Never raises; a missing phone is
    {"ok": False, "reason": "not_connected"}."""
    with _state["conn_lock"]:
        conn = _state["conn"]
    if conn is None:
        return {"ok": False, "reason": "not_connected"}
    with _lock:
        _state["next_id"] += 1
        cid = _state["next_id"]
    payload = dict(cmd)
    payload["id"] = cid
    slot = [threading.Event(), None]
    _state["pending"][cid] = slot
    if not _send_raw(conn, payload):
        _state["pending"].pop(cid, None)
        return {"ok": False, "reason": "not_connected"}
    if not slot[0].wait(timeout):
        _state["pending"].pop(cid, None)
        return {"ok": False, "reason": "timeout"}
    ack = slot[1] or {"ok": False, "reason": "not_connected"}
    if isinstance(ack, dict) and ack.get("battery") is not None:
        try:
            _state["battery"] = int(ack["battery"])
        except Exception:
            pass
    return ack


# ------------------------------------------------- phone_control mirrors
def call_contact(cfg, name):
    """Same contract as phone_control.call_contact, over the
    app link."""
    import phone_control
    key, number = phone_control.resolve_contact(cfg, name)
    if number is None:
        return {"ok": False, "reason": "unknown_contact",
                "name": (name or "").strip()}
    if not is_connected():
        return {"ok": False, "reason": "not_connected",
                "state": "none", "name": key, "number": number}
    ack = send_command({"cmd": "call", "number": number})
    if ack.get("ok"):
        mode = "dial" if ack.get("detail") == "dial_fallback" \
            else "call"
        return {"ok": True, "mode": mode, "number": number,
                "name": key}
    if ack.get("reason") == "timeout":
        return {"ok": False, "reason": "timeout", "name": key}
    return {"ok": False, "reason": "call_failed", "name": key}


def open_app(cfg, app_name):
    """Same contract as phone_control.open_app, over the link."""
    import phone_control
    canon = phone_control.normalize_app(app_name)
    if canon is None:
        return {"ok": False, "reason": "unknown_app",
                "app": (app_name or "").strip()}
    if not is_connected():
        return {"ok": False, "reason": "not_connected",
                "state": "none", "app": canon}
    package = phone_control.APP_PACKAGES[canon]
    ack = send_command({"cmd": "open_app", "package": package})
    if ack.get("ok"):
        return {"ok": True, "app": canon, "package": package}
    if ack.get("detail") == "not_installed":
        return {"ok": False, "reason": "not_installed",
                "app": canon, "package": package}
    if ack.get("reason") == "timeout":
        return {"ok": False, "reason": "timeout", "app": canon}
    return {"ok": False, "reason": "open_failed", "app": canon}


def phone_battery(cfg):
    """Same contract as phone_control.phone_battery."""
    if not is_connected():
        return {"ok": False, "reason": "not_connected",
                "state": "none"}
    ack = send_command({"cmd": "battery"})
    if ack.get("ok") and ack.get("battery") is not None:
        try:
            return {"ok": True, "level": int(ack["battery"])}
        except Exception:
            pass
    if ack.get("reason") == "timeout":
        return {"ok": False, "reason": "timeout"}
    return {"ok": False, "reason": "battery_failed"}


def ring_phone():
    """Find-my-phone: ring at max alarm volume (~15 s)."""
    if not is_connected():
        return {"ok": False, "reason": "not_connected"}
    ack = send_command({"cmd": "ring"}, timeout=8)
    return {"ok": bool(ack.get("ok"))}
