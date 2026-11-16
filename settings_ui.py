"""Nalox Settings window (v4.1; v4.3 Connections) — opened from
the app window's "⚙️ Settings" button.

v4.3: the Voice/Brain key fields became a CONNECTIONS panel — one
row per integration (ElevenLabs, Claude, Groq, OpenAI, Telegram,
Gmail, YouTube, OpenWeather) with a status dot and a live Test
button — plus a voice-speed slider, a Mode dropdown
(jarvis/creator/focus), a document-folder field with "Index now",
and a 🩺 Doctor button. The body scrolls; Save / Save & Restart
stay pinned in the footer.
v4.8: a GEMINI row joins the panel (Google AI Studio — the free
brain key), placed above Groq to mirror the agent priority
Claude → Gemini → Groq → OpenAI.
v4.9: an OPENROUTER row joins above Gemini (one key — Claude +
many models), mirroring the new priority Claude → OpenRouter →
Gemini → Groq → OpenAI; and the Voice section gains a Bengali
voice chooser — Male (Pradeep) / Female (Nabanita), default
Male, writing the bn_voice key.
v5.0: a FREELLMAPI row becomes the FIRST brain row (above
Claude): Arjun's local unified-router app — base URL + masked
unified key + model ("auto") + Test — mirroring the new agent
priority FreeLLMAPI → Claude → OpenRouter → Gemini → Groq →
OpenAI.
v5.1: the Voice section gains a CLOUD HEARING toggle writing
cloud_ears (auto/off): Gemini/Groq transcribe his commands
for far better Bengali/Hindi; off keeps every voice clip on
the laptop with the local Whisper only.
v5.4: a PHONE section joins (ADB over Wi-Fi — no cable):
the Wireless debugging pairing fields (pair address + code,
Wi-Fi address), a "Pair phone (Wi-Fi)" button that runs the
pairing against the live field values and reports the
outcome, a Test connection button, and the one-line contacts
editor ("mother=+91…, father=+91…") that round-trips the
phone_contacts dict via _parse_contacts/_format_contacts.
The General section gains a "Wake reply" field writing
wake_line — the exact words spoken when the wake word lands.
v9.0: the "Wake reply" field is retired with the wake word
(wake_line is written back unchanged, inert); the General
section gains a "Dictation hotkey" field instead, the mic
test reads dictation.pick_input_device (ears.py is gone),
and the cloud toggle now reads "Cloud dictation" (off =
dictation disabled — there is no local fallback anymore).

Arjun should never have to hand-edit config.json again. This window
edits it for him: API keys (ElevenLabs / Anthropic / OpenRouter /
Gemini / Groq
/ OpenAI),
the microphone picker + mic test, a voice test button, the general
toggles (greeting / briefing news / YouTube at startup / start with
Windows) and the Access & Control switches (full control, YouTube
replies, email sending).

Saving MERGES the form values into config.json — unknown keys are
preserved — and writes atomically (temp file + os.replace). The
"Start with Windows" toggle creates/removes the Startup shortcut
(Nalox.lnk → start_nalox.vbs) with the same PowerShell WScript.Shell
approach INSTALL.bat uses.

Design rules: tkinter is imported lazily inside open_settings() so
this module stays importable headless; every GUI/audio action is
guarded — a Settings failure can never hurt the running assistant.
All keys stay only on this laptop (they are written to the local
config.json and nowhere else).
"""
import json
import logging
import os
import subprocess
import threading

log = logging.getLogger("nalox.settings")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

BG = "#1f2430"
CARD = "#2a3040"
FG = "#e6e9f0"
MUTED = "#8b93a7"
ACCENT = "#2dd4bf"

_window = None  # the open Toplevel, if any (one Settings at a time)


# ------------------------------------------------------------ config io
def _load_raw():
    """config.json exactly as it is on disk ({} if unreadable)."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_cfg():
    """Effective config (defaults + config.json) via config.py."""
    try:
        from config import load_config
        return load_config()
    except Exception:
        return dict(_load_raw())


def _save_merge(updates):
    """Merge `updates` into config.json, preserving unknown keys.

    Atomic: write to a temp file, then os.replace. Returns True/False.
    """
    try:
        raw = _load_raw()
        raw.update(updates)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return True
    except Exception as exc:
        log.warning("Settings save failed: %s", exc)
        return False


# ------------------------------------------------- phone contacts (v5.4)
def _parse_contacts(text):
    """The Settings → Phone contacts field -> the phone_contacts
    dict. Format: "mother=+91…, father=+91…" — comma separated
    name=number pairs. Keys are lowercased (the brain matches
    spoken names case-insensitively); a pair without "=" or
    with an empty side is skipped, never fatal."""
    contacts = {}
    for part in str(text or "").split(","):
        if "=" not in part:
            continue
        name, _eq, number = part.partition("=")
        name = name.strip().lower()
        number = number.strip()
        if name and number:
            contacts[name] = number
    return contacts


def _format_contacts(contacts):
    """The phone_contacts dict -> the one-line field text
    (sorted by name, so the round-trip is stable)."""
    if not isinstance(contacts, dict):
        return ""
    bits = []
    for name in sorted(contacts):
        number = str(contacts[name] or "").strip()
        if name and number:
            bits.append(f"{name}={number}")
    return ", ".join(bits)


# ------------------------------------------------------------ autostart
def _startup_link_path():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup", "Nalox.lnk")


def _autostart_exists():
    try:
        return os.path.exists(_startup_link_path())
    except Exception:
        return False


def _set_autostart(on):
    """Create/remove the Startup shortcut (same approach as INSTALL.bat)."""
    link = _startup_link_path()
    try:
        if not on:
            if os.path.exists(link):
                os.remove(link)
            return True
        target = os.path.join(BASE_DIR, "start_nalox.vbs")
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$lnk = $ws.CreateShortcut('{link}'); "
            f"$lnk.TargetPath = '{target}'; "
            f"$lnk.WorkingDirectory = '{BASE_DIR}'; "
            "$lnk.Description = 'Nalox voice assistant'; $lnk.Save()")
        # v7.7 (item G): the PowerShell child stays hidden.
        _nw = {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)} \
            if os.name == "nt" else {}
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            timeout=30, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_nw)
        return os.path.exists(link)
    except Exception as exc:
        log.warning("Autostart toggle failed: %s", exc)
        return False


# ------------------------------------------------------------ mic list
def _input_devices():
    """[(display, saved_value)] for the mic dropdown; Auto first.

    saved_value is what goes into config mic_device: "" for Auto,
    otherwise the device NAME (ears.pick_input_device matches it as
    a substring). Fully guarded — sounddevice problems just leave
    the Auto entry.
    """
    options = [("Auto (Windows default)", "")]
    try:
        import sounddevice as sd
        seen = set()
        for dev in sd.query_devices():
            try:
                if dev.get("max_input_channels", 0) > 0:
                    name = str(dev.get("name") or "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        options.append((name, name))
            except Exception:
                continue
    except Exception:
        pass
    return options


# ------------------------------------------------------------ the window
def open_settings(parent, cfg=None):
    """Open the Settings Toplevel (or raise the existing one).

    Runs on the caller's (tk) thread. Never raises.
    """
    global _window
    try:
        import tkinter as tk
    except Exception as exc:
        log.warning("Settings unavailable: tkinter import failed (%s)", exc)
        return None
    try:
        if _window is not None and _window.winfo_exists():
            _window.lift()
            _window.focus_set()
            return _window
    except Exception:
        _window = None
    try:
        _window = _build(tk, parent, cfg or _load_cfg())
        return _window
    except Exception as exc:
        log.warning("Settings window failed to open: %s", exc)
        _window = None
        return None


def _build(tk, parent, cfg):
    win = tk.Toplevel(parent)
    win.title("Nalox Settings")
    win.configure(bg=BG)
    win.geometry("480x760")
    try:
        win.attributes("-topmost", True)
        # v5.7: brief raise only — a permanent topmost here
        # would pin Settings above everything else on screen.
        # Released ~1 s later, mirroring hud._release_topmost.
        win.after(1000, lambda: win.attributes("-topmost", False))
    except Exception:
        pass

    tk.Label(win, text="⚙️  Nalox Settings", bg=BG, fg=FG,
             font=("Segoe UI", 15, "bold")).pack(anchor="w",
                                                 padx=14, pady=(12, 4))

    # ---- scrollable body (v4.3: Connections made the form long) ----
    canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
    scrollbar = tk.Scrollbar(win, orient="vertical",
                             command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="top", fill="both", expand=True)
    body = tk.Frame(canvas, bg=BG)
    _win_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def _on_body_config(_evt=None):
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas_config(evt):
        try:
            canvas.itemconfigure(_win_id, width=evt.width)
        except Exception:
            pass

    body.bind("<Configure>", _on_body_config)
    canvas.bind("<Configure>", _on_canvas_config)

    def _wheel(evt):
        try:
            canvas.yview_scroll(int(-evt.delta / 120), "units")
        except Exception:
            pass

    canvas.bind_all("<MouseWheel>", _wheel)

    def section(title):
        frame = tk.Frame(body, bg=CARD)
        frame.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(frame, text=title, bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w",
                                                     padx=10, pady=(8, 2))
        return frame

    def field(frame, label, value, show=None):
        row = tk.Frame(frame, bg=CARD)
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text=label, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9), width=20).pack(side="left")
        var = tk.StringVar(value=str(value or ""))
        entry = tk.Entry(row, textvariable=var, show=show,
                         bg="#1a1f2b", fg=FG, insertbackground=FG,
                         relief="flat", font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True)
        return var

    def check(frame, label, value):
        var = tk.BooleanVar(value=bool(value))
        tk.Checkbutton(
            frame, text=label, variable=var, bg=CARD, fg=FG,
            activebackground=CARD, activeforeground=FG,
            selectcolor="#1a1f2b", font=("Segoe UI", 10),
            anchor="w").pack(fill="x", padx=10, pady=1)
        return var

    def button(frame, text, command):
        return tk.Button(
            frame, text=text, command=command, bg="#343c52", fg=FG,
            activebackground="#3f4a68", activeforeground=FG,
            relief="flat", font=("Segoe UI", 10), cursor="hand2")

    def set_status(var, msg):
        try:
            win.after(0, lambda: var.set(msg))
        except Exception:
            pass

    # ---------------- Voice ----------------
    fr = section("🎙  Voice")
    el_voice = field(fr, "Voice ID", cfg.get("elevenlabs_voice_id"))
    robot_var = check(fr, "Robot voice effect (not recommended)",
                      cfg.get("robot_voice", False))
    speed_var = tk.DoubleVar(
        value=float(cfg.get("voice_speed") or 1.0))
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=2)
    tk.Label(row, text="Voice speed", bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), width=20).pack(side="left")
    tk.Scale(row, variable=speed_var, from_=0.8, to=1.3,
             resolution=0.05, orient="horizontal", bg=CARD, fg=FG,
             highlightthickness=0, troughcolor="#1a1f2b",
             font=("Segoe UI", 8)).pack(side="left", fill="x",
                                         expand=True)
    # v4.9: Bengali voice chooser — exactly two friendly options.
    # Arjun rejected the female default ("মেয়ের ভয়েস না —
    # ছেলের ভয়েস চাই"); Male (Pradeep) is the default. The
    # chooser writes the bn_voice key the edge-tts path reads.
    bn_displays = ["Male (Pradeep)", "Female (Nabanita)"]
    bn_values = ["bn-BD-PradeepNeural", "bn-BD-NabanitaNeural"]
    _bn_now = str(cfg.get("bn_voice") or "")
    bn_var = tk.StringVar(
        value=bn_displays[bn_values.index(_bn_now)]
        if _bn_now in bn_values else bn_displays[0])
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=2)
    tk.Label(row, text="Bengali voice", bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), width=20).pack(side="left")
    tk.OptionMenu(row, bn_var, *bn_displays).pack(side="left",
                                                  fill="x",
                                                  expand=True)
    # v6.8: Google Cloud TTS key — the MALE Bengali voice
    # (bn-IN-Standard-B). The free translate voice Nalox
    # falls back to is female and cannot change; this key
    # (free tier, SETUP-GOOGLE-VOICE.txt in the Nalox
    # folder) turns on the male voice. Masked like every
    # key; empty = the layer stays off, zero delay.
    gt_key = field(fr, "Google TTS key (male Bengali voice)",
                   cfg.get("google_tts_api_key"), show="*")
    tk.Label(fr, text="Free key — steps in "
                      "SETUP-GOOGLE-VOICE.txt (Nalox folder). "
                      "Paste it here only, never in chat. "
                      "(optional — skip it if Google asks for a card)",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    # v5.1: cloud hearing toggle — Groq/Gemini transcribe
    # dictation. v9.0: dictation is cloud-ONLY (the local
    # ears are gone); off = dictation disabled, clips never
    # leave the laptop (typing + Telegram still work).
    cloud_var = check(
        fr, "Cloud dictation — Groq/Gemini transcribe "
            "the mic button's clips (off = no dictation)",
        str(cfg.get("cloud_ears") or "auto").strip().lower()
        != "off")
    voice_status = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 8))

    def collect_voice():
        return {"elevenlabs_api_key": el_key.get().strip(),
                "elevenlabs_voice_id": el_voice.get().strip(),
                "google_tts_api_key": gt_key.get().strip(),
                "robot_voice": bool(robot_var.get()),
                "bn_voice": bn_values[bn_displays.index(bn_var.get())],
                "cloud_ears": "auto" if cloud_var.get() else "off",
                "voice_speed": round(float(speed_var.get()), 2)}

    def test_voice():
        merged = _load_cfg()
        merged.update(collect_voice())
        merged.update(collect_connections())
        voice_status.set("Speaking…")

        def _run():
            try:
                from voice import Speaker
                Speaker(merged).say("Hi Arjun, this is my voice.")
            except Exception as exc:
                log.warning("Voice test failed: %s", exc)
        threading.Thread(target=_run, daemon=True,
                         name="settings-voice-test").start()

    button(row, "🔊 Test voice", test_voice).pack(side="left")
    tk.Label(row, textvariable=voice_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 9)).pack(side="left", padx=8)

    # ---------------- Connections (v4.3) ----------------
    fr = section("🔌  Connections")
    tk.Label(fr, text="● = set up · ○ = not set up. Test buttons "
                      "check the connection live.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)

    def conn_header(name, is_set):
        row = tk.Frame(fr, bg=CARD)
        row.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(row, text="●" if is_set else "○",
                 bg=CARD, fg="#4ade80" if is_set else MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Label(row, text="  " + name, bg=CARD, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        status = tk.StringVar(value="")
        tk.Label(row, textvariable=status, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="right")
        return status

    def test_row(status_var, fn):
        row = tk.Frame(fr, bg=CARD)
        row.pack(fill="x", padx=10, pady=(2, 2))

        def _go():
            status_var.set("Testing…")

            def _run():
                try:
                    msg = fn()
                except Exception as exc:
                    msg = f"Failed: {exc}"
                set_status(status_var, msg)
            threading.Thread(target=_run, daemon=True,
                             name="settings-conn-test").start()
        button(row, "Test", _go).pack(side="left")
        return row

    def _http_test(url, headers=None):
        import requests
        resp = requests.get(url, headers=headers or {}, timeout=8)
        if resp.status_code == 200:
            return "Connected ✓"
        return f"HTTP {resp.status_code} — check the key"

    # ElevenLabs
    st = conn_header("ElevenLabs (voice)",
                     bool(cfg.get("elevenlabs_api_key")))
    el_key = field(fr, "API key", cfg.get("elevenlabs_api_key"),
                   show="*")
    tk.Label(fr, text="Key পাবে: elevenlabs.io → Profile → API Keys",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    test_row(st, lambda: _http_test(
        "https://api.elevenlabs.io/v1/voices",
        {"xi-api-key": el_key.get().strip()}))

    # FreeLLMAPI (v5.0 — Arjun's LOCAL unified router app; the
    # FIRST brain row because the agent tries it first: its own
    # 78-model chain auto-switches when a model fails)
    st = conn_header("FreeLLMAPI (local router)",
                     bool(cfg.get("freellm_api_key")))
    fl_url = field(fr, "Base URL",
                   cfg.get("freellm_base_url",
                           "http://127.0.0.1:31415/v1"))
    fl_key = field(fr, "API key", cfg.get("freellm_api_key"),
                   show="*")
    tk.Label(fr, text="Local router app: 78 models, auto-switch. "
                      "Base URL + unified key from its Agents page.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    fl_model = field(fr, "Model",
                     cfg.get("freellm_model", "auto"))
    test_row(st, lambda: _http_test(
        fl_url.get().strip().rstrip("/") + "/models",
        {"Authorization": "Bearer " + fl_key.get().strip()}))

    # Anthropic / Claude
    st = conn_header("Claude (Anthropic brain)",
                     bool(cfg.get("anthropic_api_key")))
    an_key = field(fr, "API key", cfg.get("anthropic_api_key"),
                   show="*")
    tk.Label(fr, text="Key পাবে: console.anthropic.com → API Keys",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    an_model = field(fr, "Model",
                     cfg.get("anthropic_model", "claude-sonnet-4-5"))
    test_row(st, lambda: _http_test(
        "https://api.anthropic.com/v1/models",
        {"x-api-key": an_key.get().strip(),
         "anthropic-version": "2023-06-01"}))

    # OpenRouter (v4.9 — ONE key, many models, Claude included;
    # sits above Gemini because the agent tries it first)
    st = conn_header("OpenRouter (one key — Claude + many models)",
                     bool(cfg.get("openrouter_api_key")))
    or_key = field(fr, "API key", cfg.get("openrouter_api_key"),
                   show="*")
    tk.Label(fr, text="One key for Claude + many models: "
                      "openrouter.ai/keys",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    or_model = field(fr, "Model",
                     cfg.get("openrouter_model",
                             "anthropic/claude-sonnet-4.5"))
    test_row(st, lambda: _http_test(
        "https://openrouter.ai/api/v1/models",
        {"Authorization": "Bearer " + or_key.get().strip()}))

    # Gemini (v4.8 — Google AI Studio, the FREE brain key; sits
    # above Groq because the agent tries it first)
    st = conn_header("Gemini (free brain — Google AI Studio)",
                     bool(cfg.get("gemini_api_key")))
    gemini_key = field(fr, "API key", cfg.get("gemini_api_key"),
                       show="*")
    tk.Label(fr, text="Free key: aistudio.google.com/apikey "
                      "→ Create API key (কার্ড লাগে না)",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    gemini_model = field(fr, "Model",
                         cfg.get("gemini_model", "gemini-2.5-flash"))
    test_row(st, lambda: _http_test(
        "https://generativelanguage.googleapis.com/v1beta/openai/models",
        {"Authorization": "Bearer " + gemini_key.get().strip()}))

    # Groq
    st = conn_header("Groq (optional brain)",
                     bool(cfg.get("groq_api_key")))
    groq_key = field(fr, "API key", cfg.get("groq_api_key"), show="*")
    test_row(st, lambda: _http_test(
        "https://api.groq.com/openai/v1/models",
        {"Authorization": "Bearer " + groq_key.get().strip()}))

    # OpenAI
    st = conn_header("OpenAI (optional brain)",
                     bool(cfg.get("openai_api_key")))
    openai_key = field(fr, "API key", cfg.get("openai_api_key"),
                       show="*")
    test_row(st, lambda: _http_test(
        "https://api.openai.com/v1/models",
        {"Authorization": "Bearer " + openai_key.get().strip()}))

    # Ollama (v6.7 — the OFFLINE brain: no key field at all,
    # it runs on this laptop and the agent tries it LAST,
    # when every cloud brain is down. A static pointer to
    # the one-time setup file is all that belongs here.)
    tk.Label(fr, text="Offline brain (Ollama): no key needed — "
                      "one-time setup: SETUP-OLLAMA.txt in the "
                      "Nalox folder",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)

    # Telegram
    st = conn_header("Telegram (phone bridge)",
                     bool(cfg.get("telegram_bot_token")))
    tg_token = field(fr, "Bot token", cfg.get("telegram_bot_token"),
                     show="*")
    tg_chat = field(fr, "Your chat ID",
                    cfg.get("telegram_owner_chat_id"))

    def _test_telegram():
        token = tg_token.get().strip()
        if not token:
            return "No token yet"
        import requests
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        data = resp.json() if resp.content else {}
        if data.get("ok"):
            name = (data.get("result") or {}).get("username", "bot")
            return f"Connected ✓ @{name}"
        return "Token rejected — check BotFather"
    test_row(st, _test_telegram)

    # Gmail (same creds drive reading + the lead mailer)
    _gmail_addr = cfg.get("gmail_address") or cfg.get("email_address")
    _gmail_pass = cfg.get("gmail_app_password") \
        or cfg.get("email_app_password")
    st = conn_header("Gmail (read inbox + send leads)",
                     bool(_gmail_pass))
    gm_addr = field(fr, "Gmail address", _gmail_addr)
    gm_pass = field(fr, "App password", _gmail_pass, show="*")
    tk.Label(fr, text="App password পাবে: Google Account → Security "
                      "→ App passwords",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)

    def _test_gmail():
        merged = _load_cfg()
        merged.update(collect_connections())
        import skills
        count = skills.gmail_unread_count(merged)
        if count is None:
            return "Login failed — check address + app password"
        return f"Connected ✓ — {count} unread"
    test_row(st, _test_gmail)

    # YouTube (OAuth files, not a key field)
    _yt_secret = os.path.exists(
        os.path.join(BASE_DIR, "youtube_client_secret.json"))
    _yt_token = os.path.exists(
        os.path.join(BASE_DIR, "youtube_token.json"))
    st = conn_header("YouTube (comments + calendar)",
                     _yt_secret)
    st.set("ready ✓" if _yt_token else
           ("secret saved — first use asks consent" if _yt_secret
            else "not set up"))
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(2, 2))

    def _open_guide():
        try:
            os.startfile(os.path.join(BASE_DIR, "SETUP-YOUTUBE.txt"))
        except Exception as exc:
            st.set(f"Guide open failed: {exc}")
    button(row, "📖 Setup guide", _open_guide).pack(side="left")
    tk.Label(fr, text="Google Cloud থেকে client secret file টা "
                      "Nalox folder-এ রাখলেই হবে (guide-এ সব আছে)।",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=420, justify="left").pack(anchor="w",
                                                  padx=10)

    # OpenWeather
    st = conn_header("OpenWeather (digest weather)",
                     bool(cfg.get("openweather_api_key")))
    ow_key = field(fr, "API key", cfg.get("openweather_api_key"),
                   show="*")
    ow_city = field(fr, "City", cfg.get("weather_city", "Kolkata"))

    def _test_weather():
        merged = _load_cfg()
        merged.update(collect_connections())
        import skills
        line = skills.fetch_weather(merged)
        return line if line else "No weather — check key + city"
    test_row(st, _test_weather)
    tk.Label(fr, text="", bg=CARD).pack(pady=2)

    def collect_connections():
        gmail_addr = gm_addr.get().strip()
        gmail_pass = gm_pass.get().strip()
        return {
            "freellm_api_key": fl_key.get().strip(),
            "freellm_base_url": fl_url.get().strip()
                                or "http://127.0.0.1:31415/v1",
            "freellm_model": fl_model.get().strip() or "auto",
            "anthropic_api_key": an_key.get().strip(),
            "anthropic_model": an_model.get().strip()
                               or "claude-sonnet-4-5",
            "openrouter_api_key": or_key.get().strip(),
            "openrouter_model": or_model.get().strip()
                                or "anthropic/claude-sonnet-4.5",
            "gemini_api_key": gemini_key.get().strip(),
            "gemini_model": gemini_model.get().strip()
                            or "gemini-2.5-flash",
            "groq_api_key": groq_key.get().strip(),
            "openai_api_key": openai_key.get().strip(),
            "telegram_bot_token": tg_token.get().strip(),
            "telegram_owner_chat_id": tg_chat.get().strip(),
            "gmail_address": gmail_addr,
            "gmail_app_password": gmail_pass,
            # mailer.py reads the email_* pair — keep both in sync.
            "email_address": gmail_addr,
            "email_app_password": gmail_pass,
            "openweather_api_key": ow_key.get().strip(),
            "weather_city": ow_city.get().strip() or "Kolkata",
        }

    # ---------------- Brain (v7.4) ----------------
    # Smart routing + the Brain Test. Routing itself has
    # no controls here (it follows config: brain_smart_
    # routing + groq_power_model); this section is the
    # MEASURING instrument the owner ordered — one button
    # runs brainbench against every candidate (Groq walk,
    # OpenRouter incl. GLM when a key is saved, Ollama)
    # with fixed Bengali prompts and shows the table.
    fr = section("🧠  Brain")
    tk.Label(fr, text="Smart routing: simple talk → instant "
                      "model · action + hard work → power "
                      "model (automatic). Brain Test মাপে কোন "
                      "brain সবচেয়ে fast + বাংলা ঠিক বলে।",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10)
    # v7.8: Muse Wonder (Meta Model API) — the owner's
    # paid Meta brain (his order, 2026-11-16). The key
    # field lives here with the Brain controls and is
    # wired exactly like the Connections key fields:
    # saved into config.json on Save, never logged. With
    # a key, Muse Wonder joins the chat race and the
    # Brain Test below; without one it is never called.
    tk.Label(fr, text="Muse Wonder (Meta Model API) — "
                      "paid brain, chat race-এ যোগ দেয়",
             bg=CARD, fg=FG,
             font=("Segoe UI", 9, "bold")).pack(
                 anchor="w", padx=10, pady=(8, 0))
    muse_key = field(fr, "API key", cfg.get("muse_api_key"),
                     show="*")
    tk.Label(fr, text="Key পাবে: dev.meta.ai → API keys "
                      "(আগে payment method যোগ করতে হয় — "
                      "এটা PAID API)। Key শুধু এই laptop-এই "
                      "থাকবে, chat-এ কখনো পাঠিও না।",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10)
    muse_model = field(fr, "Model",
                       cfg.get("muse_model",
                               "muse-wonder-1.0"))

    def collect_brain():
        return {"muse_api_key": muse_key.get().strip(),
                "muse_model": muse_model.get().strip()
                or "muse-wonder-1.0"}

    bench_status = tk.StringVar(value="")
    bench_lines = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 2))
    tk.Label(row, textvariable=bench_status, bg=CARD,
             fg=MUTED, font=("Segoe UI", 8)).pack(side="right")
    _bench_poll = {"live": False}

    def _bench_show():
        try:
            import brainbench
            state = brainbench.last_results()
            if state.get("lines"):
                bench_lines.set("\n".join(state["lines"]))
            if state.get("error"):
                bench_status.set("Failed — see the log")
            elif state.get("running"):
                bench_status.set("Running…")
            elif state.get("at"):
                bench_status.set("Done ✓")
        except Exception:
            pass

    def _bench_poll():
        _bench_show()
        try:
            import brainbench
            if brainbench.is_running():
                win.after(1200, _bench_poll)
            else:
                _bench_poll["live"] = False
        except Exception:
            _bench_poll["live"] = False

    def _brain_test():
        try:
            import brainbench
        except Exception as exc:
            bench_status.set(f"Unavailable: {exc}")
            return
        if brainbench.is_running():
            bench_status.set("Already running…")
            return
        bench_status.set("Running…")
        if not brainbench.start_benchmark(dict(cfg)):
            bench_status.set("Already running…")
            return
        if not _bench_poll["live"]:
            _bench_poll["live"] = True
            win.after(600, _bench_poll)

    button(row, "🧪 Brain Test", _brain_test).pack(side="left")
    tk.Label(fr, textvariable=bench_lines, bg=CARD, fg=FG,
             font=("Consolas", 8), wraplength=430,
             justify="left").pack(anchor="w", padx=10,
                                  pady=(2, 6))
    _bench_show()

    # ---------------- Microphone ----------------
    fr = section("🎤  Microphone")
    options = _input_devices()
    current_mic = str(cfg.get("mic_device") or "")
    displays = [d for d, _v in options]
    values = [v for _d, v in options]
    if current_mic and current_mic not in values:
        displays.append(f"{current_mic} (current)")
        values.append(current_mic)
    mic_var = tk.StringVar(
        value=displays[values.index(current_mic)]
        if current_mic in values else displays[0])
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=2)
    tk.Label(row, text="Input device", bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), width=20).pack(side="left")
    tk.OptionMenu(row, mic_var, *displays).pack(side="left", fill="x",
                                                expand=True)
    mic_status = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 2))

    def chosen_mic_value():
        try:
            return values[displays.index(mic_var.get())]
        except Exception:
            return ""

    def test_mic():
        mic_status.set("Listening for 1.5 s — speak now…")

        def _run():
            msg = "Mic test failed."
            try:
                import numpy as np
                import sounddevice as sd

                import dictation
                tmp_cfg = dict(_load_cfg())
                tmp_cfg["mic_device"] = chosen_mic_value()
                idx = dictation.pick_input_device(tmp_cfg)
                audio = sd.rec(int(1.5 * 16000), samplerate=16000,
                               channels=1, dtype="float32", device=idx)
                sd.wait()
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                if peak >= 0.05:
                    msg = f"Mic OK — peak level {peak:.2f} (closer to 1.0 = louder)."
                elif peak >= 0.01:
                    msg = f"Mic heard you, but quietly — peak {peak:.2f}. Try speaking closer."
                else:
                    msg = f"Mic heard almost nothing (peak {peak:.2f}) — check the microphone."
            except Exception as exc:
                msg = f"Mic test failed: {exc}"
            set_status(mic_status, msg)

        threading.Thread(target=_run, daemon=True,
                         name="settings-mic-test").start()

    button(row, "🎙 Test mic", test_mic).pack(side="left")
    tk.Label(fr, textvariable=mic_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), wraplength=420,
             justify="left").pack(anchor="w", padx=10, pady=(0, 8))

    # ---------------- Phone (v5.4: ADB over Wi-Fi) ----------------
    fr = section("📱  Phone")
    # ---- v6.0: the Nalox Phone app — the easy way, on top ----
    tk.Label(fr, text="📱 Nalox Phone app (easiest): Nalox "
                      "sends you a link on Telegram → open it "
                      "on the phone → Install the little app → "
                      "tap Connect once. No codes, no "
                      "developer options, no cable. Voice "
                      "commands (call mother, open YouTube) "
                      "then run on the phone.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(0, 2))
    app_status = tk.StringVar(value="")
    app_row = tk.Frame(fr, bg=CARD)
    app_row.pack(fill="x", padx=10, pady=(2, 2))

    def _app_status_now():
        try:
            import phone_link
            if phone_link.is_connected():
                return ("✓ App connected: "
                        + (phone_link.device_name()
                           or "Android phone"))
            if phone_link.pairing_active():
                return ("Pairing is ON — waiting for the "
                        "phone to connect…")
        except Exception:
            pass
        return "App not connected — send the link to pair."

    def _send_phone_link():
        app_status.set("Starting pairing…")

        def _run():
            try:
                import phone_link
                import telegram_bridge
                cfg_now = _load_cfg()
                url = phone_link.start_pairing(cfg_now)
                sent = telegram_bridge.send_message(
                    cfg_now,
                    "📱 Nalox Phone pairing is ON for 10 "
                    "minutes.\n"
                    f"Open this link on your phone: {url}\n"
                    "Then tap 1. Install Nalox Phone, and "
                    "after installing, 2. Connect.")
                if sent:
                    msg = ("✓ Link sent to your Telegram — "
                           f"open it on the phone: {url}")
                else:
                    msg = ("Pairing is ON — open this on "
                           f"the phone: {url} (Telegram send "
                           "didn't go through)")
            except Exception as exc:
                msg = f"✗ Could not start pairing: {exc}"
            set_status(app_status, msg)
        threading.Thread(target=_run, daemon=True,
                         name="settings-phone-link").start()

    def _regen_phone_token():
        def _run():
            try:
                import phone_link
                phone_link.regenerate_token(_load_cfg())
                msg = ("✓ New pairing token made — old "
                       "pairings no longer work. Send a "
                       "fresh link to pair again.")
            except Exception as exc:
                msg = f"✗ Token change failed: {exc}"
            set_status(app_status, msg)
        threading.Thread(target=_run, daemon=True,
                         name="settings-phone-token").start()

    button(app_row, "📩 Send the phone link",
           _send_phone_link).pack(side="left")
    button(app_row, "🔑 New pairing token",
           _regen_phone_token).pack(side="left", padx=6)
    app_status.set(_app_status_now())
    tk.Label(fr, textvariable=app_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), wraplength=420,
             justify="left").pack(anchor="w", padx=10,
                                  pady=(0, 6))
    tk.Label(fr, text="— Alternative: ADB over Wi-Fi "
                      "(needs Developer options on the "
                      "phone) —",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(2, 2))
    tk.Label(fr, text="Your Android phone, controlled from "
                      "Nalox — no cable. One-time pairing: "
                      "phone Settings → Developer options → "
                      "Wireless debugging ON → “Pair device "
                      "with pairing code”, then copy the three "
                      "values below from the phone's screens.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(0, 2))
    # v5.8: HOTSPOT help — his PC's internet IS his phone's
    # hotspot, so the phone can never join a router Wi-Fi;
    # the pairing screen's own address is the way in.
    tk.Label(fr, text="Using your phone's HOTSPOT for "
                      "internet? Keep the hotspot ON, turn "
                      "Wireless debugging ON too, and copy "
                      "the IP:port the phone SHOWS on its "
                      "pairing screen — that shown address "
                      "is the right one, whatever network "
                      "it is.\n"
                      "হটস্পট দিয়ে PC চললে: হটস্পট ON রাখো, "
                      "Wireless debugging-ও ON করো — pairing "
                      "screen-এ ফোন যে IP:port দেখাবে, সেটাই "
                      "নিচে বসাও।\n"
                      "If your phone will not run both "
                      "together, use the one-time 30-second "
                      "cable method in the update README "
                      "(adb tcpip 5555) — after that, no "
                      "cable is needed until the phone "
                      "restarts.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(0, 4))
    pair_addr_var = field(fr, "Pair address (IP:port)",
                          cfg.get("phone_pair_address"))
    pair_code_var = field(fr, "Pairing code (6 digits)",
                          cfg.get("phone_pair_code"))
    wifi_addr_var = field(fr, "Wi-Fi address (IP:port)",
                          cfg.get("phone_wifi_address"))
    contacts_var = field(fr, "Contacts (name=number, …)",
                         _format_contacts(cfg.get("phone_contacts")))
    phone_status = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 2))

    def collect_phone():
        return {
            "phone_pair_address": pair_addr_var.get().strip(),
            "phone_pair_code": pair_code_var.get().strip(),
            "phone_wifi_address": wifi_addr_var.get().strip(),
            "phone_contacts": _parse_contacts(contacts_var.get()),
        }

    def _phone_cfg_now():
        merged = _load_cfg()
        merged.update(collect_phone())
        return merged

    def _pair_phone():
        phone_status.set("Pairing over Wi-Fi…")

        def _run():
            try:
                import phone_control
                ok, msg = phone_control.pair_phone(
                    _phone_cfg_now())
            except Exception as exc:
                ok, msg = False, f"Pairing failed: {exc}"
            if ok:
                # Persist the values that just worked, so a
                # later Save can't resurrect stale ones.
                _save_merge(collect_phone())
            set_status(phone_status,
                       ("✓ " if ok else "✗ ") + msg)
        threading.Thread(target=_run, daemon=True,
                         name="settings-phone-pair").start()

    def _test_phone():
        phone_status.set("Checking the phone…")

        def _run():
            try:
                import phone_control
                msg = phone_control.phone_status_line(
                    _phone_cfg_now())
            except Exception as exc:
                msg = f"✗ Phone check failed: {exc}"
            set_status(phone_status, msg)
        threading.Thread(target=_run, daemon=True,
                         name="settings-phone-test").start()

    button(row, "📶 Pair phone (Wi-Fi)", _pair_phone).pack(
        side="left")
    button(row, "🔍 Test connection", _test_phone).pack(
        side="left", padx=6)
    tk.Label(fr, textvariable=phone_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), wraplength=420,
             justify="left").pack(anchor="w", padx=10, pady=(0, 8))

    # ---------------- General ----------------
    fr = section("🧰  General")
    # v4.7: the name Nalox calls him. Same value the voice
    # preference-learning writes (memory_store prefs + config
    # mirror) — the field shows the voice-learned name too.
    _callme_initial = str(cfg.get("preferred_name") or "").strip()
    if not _callme_initial:
        try:
            import memory_store
            _callme_initial = str(
                memory_store.load_prefs().get("preferred_name")
                or "").strip()
        except Exception:
            _callme_initial = ""
    callme_var = field(fr, "Call me", _callme_initial)
    # v9.0: the "Wake reply" field is RETIRED with the wake
    # word (wake_line stays in his config, inert, and is
    # written back unchanged by collect_all). In its place:
    # the dictation hotkey — press it anywhere to start /
    # finish a one-shot dictation.
    hotkey_var = field(fr, "Dictation hotkey",
                       cfg.get("dictation_hotkey")
                       or "ctrl+alt+space")
    tk.Label(fr, text="Press the hotkey (or the 🎙 button) "
                      "to dictate; pause or press again to "
                      "send. Example: ctrl+alt+space",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10)
    greet_var = check(fr, "Greeting at startup",
                      cfg.get("greet_on_startup", True))
    news_var = check(fr, "News in morning briefing",
                     cfg.get("briefing_news", False))
    yt_var = check(fr, "Open YouTube at startup",
                   cfg.get("startup_youtube_check", False))
    auto_var = check(fr, "Start with Windows",
                     _autostart_exists() or cfg.get("autostart", True))
    mode_var = tk.StringVar(
        value=str(cfg.get("mode") or "jarvis").lower())
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=2)
    tk.Label(row, text="Mode", bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), width=20).pack(side="left")
    tk.OptionMenu(row, mode_var, "jarvis", "creator",
                  "focus").pack(side="left")
    tk.Label(row, text="jarvis = balanced · creator = YouTube-first "
                       "· focus = one-line answers",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(side="left",
                                                           padx=6)
    doc_var = field(fr, "Document folder", cfg.get("doc_folder"))
    doc_status = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(2, 2))

    def _index_now():
        doc_status.set("Indexing…")

        def _run():
            try:
                import docmemory
                folder = doc_var.get().strip()
                if not folder:
                    set_status(doc_status, "Set a folder first")
                    return
                n = docmemory.index_folder(folder)
                set_status(doc_status,
                           f"Indexed ✓ — {n} chunks searchable")
            except Exception as exc:
                set_status(doc_status, f"Index failed: {exc}")
        threading.Thread(target=_run, daemon=True,
                         name="settings-doc-index").start()
    button(row, "🗂 Index now", _index_now).pack(side="left")
    tk.Label(row, textvariable=doc_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 8)).pack(side="left", padx=8)
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 8))

    def _doctor_popup():
        merged = _load_cfg()
        merged.update(collect_all())

        def _run():
            try:
                import doctor
                results = doctor.run_checks(merged)
            except Exception as exc:
                results = [("Doctor", False, str(exc))]

            def _show():
                try:
                    pop = tk.Toplevel(win)
                    pop.title("Nalox Doctor")
                    pop.configure(bg=BG)
                    pop.geometry("440x380")
                    tk.Label(pop, text="🩺  Nalox Doctor",
                             bg=BG, fg=FG,
                             font=("Segoe UI", 13, "bold")).pack(
                                 anchor="w", padx=12, pady=(10, 4))
                    for name, ok, detail in results:
                        tk.Label(
                            pop,
                            text=("✓ " if ok else "✗ ") + name
                                 + " — " + detail,
                            bg=BG, fg="#4ade80" if ok else "#f87171",
                            font=("Segoe UI", 9), wraplength=410,
                            justify="left").pack(anchor="w", padx=12,
                                                 pady=1)
                except Exception:
                    pass
            try:
                win.after(0, _show)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True,
                         name="settings-doctor").start()
    button(row, "🩺 Check (Doctor)", _doctor_popup).pack(side="left")
    tk.Label(row, text="mic · speaker · models · internet · keys",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(side="left",
                                                           padx=8)

    # ---------------- Access & Control ----------------
    fr = section("🔐  Access & Control")
    full_var = check(fr, "Full PC control (no confirmation prompts)",
                     cfg.get("full_control", True))
    yt_reply_var = check(fr, "Allow YouTube comment replies",
                         cfg.get("allow_youtube_reply", True))
    email_var = check(fr, "Allow sending emails",
                      cfg.get("allow_email_send", True))
    tk.Label(fr, text="", bg=CARD).pack(pady=2)

    # ---------------- Updates (v6.2: self-update) ----------------
    fr = section("🔄  Updates")
    tk.Label(fr, text="Nalox নিজে নিজে update হবে: তোমার "
                      "private GitHub repo-তে নতুন version "
                      "উঠলেই Nalox সেটা নিজে download করে "
                      "লাগিয়ে restart নেবে — UPDATE.bat আর "
                      "চালাতে হবে না। Repo-র নাম (owner/name) "
                      "আর একটা token নিচে বসাও। "
                      "Token পাবে: GitHub → Settings → "
                      "Developer settings → Fine-grained "
                      "tokens → শুধু এই repo-র Contents: "
                      "Read and write। Token শুধু এই laptop-এই "
                      "থাকবে — chat-এ কখনো পাঠিও না।",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(0, 2))
    upd_repo = field(fr, "GitHub repo (owner/name)",
                     cfg.get("github_repo"))
    upd_token = field(fr, "GitHub token", cfg.get("github_token"),
                      show="*")
    # v6.9: the same token also powers LOG SYNC (logsync.py)
    # — Nalox sends its diagnostics log to the repo's logs
    # branch so Muse can check it; that is why the token
    # now needs write access, not just read.
    tk.Label(fr, text="This token also sends Nalox's log to "
                      "Muse for checking — it needs Contents: "
                      "Read and write.",
             bg=CARD, fg=MUTED, font=("Segoe UI", 8),
             wraplength=430, justify="left").pack(
                 anchor="w", padx=10, pady=(0, 2))

    def _logsync_status_text():
        try:
            import logsync
            state = logsync.read_state()
            if state.get("status") == "sent" \
                    and state.get("last_sync_local"):
                return ("Log sync: last sent "
                        + str(state["last_sync_local"]))
        except Exception:
            pass
        return "Log sync: off"

    tk.Label(fr, text=_logsync_status_text(),
             bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                 anchor="w", padx=10, pady=(0, 2))
    upd_auto = check(fr, "Auto-update (start-এ + প্রতি 6 ঘণ্টায় "
                         "নিজে check করবে)",
                     cfg.get("auto_update", True))
    upd_status = tk.StringVar(value="")
    row = tk.Frame(fr, bg=CARD)
    row.pack(fill="x", padx=10, pady=(4, 2))

    def collect_updates():
        return {
            "github_repo": upd_repo.get().strip(),
            "github_token": upd_token.get().strip(),
            "auto_update": bool(upd_auto.get()),
        }

    def _check_updates_now():
        upd_status.set("Checking GitHub…")

        def _run():
            try:
                import updater
                merged = _load_cfg()
                merged.update(collect_updates())
                _save_merge(collect_updates())
                result = updater.check_and_update(
                    merged, force=True)
                if result == "updated":
                    msg = ("✓ New version applied — Nalox "
                           "is restarting itself now")
                elif result == "current":
                    msg = "✓ Already on the newest version"
                elif result == "not-configured":
                    msg = ("Repo + token বসিয়ে আগে Save "
                           "করো, তারপর check করো")
                else:
                    msg = f"✗ {result} — details on the log page"
            except Exception as exc:
                msg = f"✗ Update check failed: {exc}"
            set_status(upd_status, msg)
        threading.Thread(target=_run, daemon=True,
                         name="settings-update-check").start()

    button(row, "🔍 Check for updates now",
           _check_updates_now).pack(side="left")
    tk.Label(fr, textvariable=upd_status, bg=CARD, fg=MUTED,
             font=("Segoe UI", 9), wraplength=420,
             justify="left").pack(anchor="w", padx=10,
                                  pady=(0, 8))
    tk.Frame(body, bg=BG).pack(pady=6)

    # ---------------- footer (fixed, outside the scroll area) ----
    footer = tk.Frame(win, bg=BG)
    footer.pack(side="bottom", fill="x")
    tk.Label(footer, text="All keys stay only on this laptop.",
             bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(pady=(6, 0))
    status_var = tk.StringVar(value="")
    tk.Label(footer, textvariable=status_var, bg=BG, fg=ACCENT,
             font=("Segoe UI", 9)).pack()
    row = tk.Frame(footer, bg=BG)
    row.pack(pady=(4, 12))

    def collect_all():
        updates = collect_voice()
        updates.update(collect_connections())
        updates.update(collect_brain())
        updates.update(collect_phone())
        updates.update(collect_updates())
        updates.update({
            "mic_device": chosen_mic_value(),
            # v9.0: wake_line is retired (inert) — written
            # back unchanged so his value is never lost.
            "wake_line": str(cfg.get("wake_line") or ""),
            "dictation_hotkey": hotkey_var.get().strip()
                                or "ctrl+alt+space",
            "greet_on_startup": bool(greet_var.get()),
            "briefing_news": bool(news_var.get()),
            "startup_youtube_check": bool(yt_var.get()),
            "autostart": bool(auto_var.get()),
            "full_control": bool(full_var.get()),
            "allow_youtube_reply": bool(yt_reply_var.get()),
            "allow_email_send": bool(email_var.get()),
            "mode": mode_var.get(),
            "doc_folder": doc_var.get().strip(),
            "preferred_name": callme_var.get().strip(),
        })
        return updates

    def do_save(restart=False):
        ok = _save_merge(collect_all())
        _set_autostart(bool(auto_var.get()))
        if not ok:
            status_var.set("Could not save — see the log page.")
            return
        # v4.7: dual-write the "Call me" name into the persistent
        # prefs store too, so voice-learning and Settings never
        # disagree (same pattern as the Gmail dual-write).
        try:
            import memory_store
            memory_store.set_pref("preferred_name",
                                  callme_var.get().strip())
        except Exception:
            pass
        if restart:
            status_var.set("Saved ✓ — restarting Nalox…")
            # v6.1: SAY the exit before taking it. This
            # os._exit(0) was the one silent deliberate exit
            # left in the codebase: the supervisor could only
            # report it as "Nalox process DIED (exit code 0)"
            # (field 2026-11-15 16:02 — he had just been in
            # Settings → Phone pairing the app). A deliberate
            # restart now leaves its reason on the log page,
            # like every other deliberate exit since v6.0.
            try:
                import logbook
                logbook.log(
                    "SYSTEM",
                    "[sys] exiting (restart): Settings — "
                    "Save & Restart")
            except Exception:
                pass
            log.info("Settings: Save & Restart — exiting "
                     "(code 0, supervisor relaunches).")
            # v7.7: speech stops before the exit begins.
            try:
                import voice as _voice_mod
                _voice_mod.stop_for_exit()
            except Exception:
                pass

            def _exit():
                try:
                    os._exit(0)  # not 42: the supervisor relaunches
                except Exception:
                    pass
            threading.Timer(0.8, _exit).start()
        else:
            status_var.set(
                "Saved ✓ — restart Nalox to apply voice/brain changes")

    button(row, "Save", lambda: do_save(False)).pack(side="left", padx=4)
    button(row, "Save & Restart", lambda: do_save(True)).pack(side="left",
                                                              padx=4)
    return win
