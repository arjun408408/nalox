"""Nalox app window (v4.1) — a normal, polished assistant app.

v3–v4.0 this was a green-on-black "hacker console". Arjun rejected
that look outright ("looks like a hacker terminal"), so v4.1 rewrites
the internals as a clean modern app: dark-slate theme, Segoe UI, his
logo in the header, a status pill, a chat-like conversation view
(You: / Nalox:), the live mic meter (recolored), and a button row —
📋 Log (the diagnostics page), ⚙️ Settings, Hide, Exit Nalox.
Voice is the only input: the v3.7 TALK button is GONE at Arjun's
explicit demand.

The module name and the public API are UNCHANGED (nalox.py and
brain.py depend on them):
    Hud(cfg); start(); post(text); set_status(state);
    show(); hide(); stop()

v4.3 — THE FACE: Arjun asked for JARVIS's look — his logo ROUND
(assets/logo_round.png, a circular crop) with a status ring around
it that PULSES while Nalox speaks, and a 7-bar speaking wave beside
the logo that dances while Nalox talks. When ARJUN talks, the wave
stays calm and the mic meter below does the dancing instead.

v4.6 — a 🔄 Restart button joins the button row (Arjun's ask:
when Nalox hangs midway, speaking to it does nothing, so the fix
must be CLICKABLE). The HUD never imports nalox.py: nalox.py sets
hud.on_restart to its own restart routine (exit code 1 — the
supervisor relaunches). With no callback wired, the button falls
back to the Settings pattern (timer + os._exit(0)); either way a
safety timer guarantees the process actually exits.

v4.7 — ALWAYS-ON + ICON: the window/taskbar icon comes from
assets/logo.ico (iconbitmap, guarded); "show" now also grabs
focus (tray "Open Nalox" / the single-instance show signal land
here); the X button still only HIDES (WM_DELETE_WINDOW ->
withdraw — Nalox keeps listening); and the "Exit Nalox" button
additionally writes exit_requested.flag so the supervisor
honours the deliberate exit even beyond the exit code. Restart
never writes that flag.

v5.5 — a 🖥 Command Center button joins the button row: it
opens the fullscreen dashboard (dashboard.py) through the
on_command_center callback nalox.py wires (a window-owned
dashboard is the fallback). The normal window itself is NOT
restyled — it stays the everyday face.

v5.5.1 — THE DASHBOARD LIVES HERE now: the Command Center is
a Toplevel on THIS window's Tk root, built and driven on this
thread (see dashboard.py's attach() and the run_on_tk() hook
below). v5.5 let dashboard.py create a second Tk interpreter
on its own thread; on Windows that is what never opened. One
interpreter, one UI thread — this one.

Design rules (unchanged): the window lives on its OWN thread (tk
mainloop); other threads talk to it only through a thread-safe
queue polled with after(); everything is defensive — if tkinter,
Pillow or a display is unavailable the window disables itself
silently and Nalox runs headless fine. Only created when config
"show_hud" is true.
"""
import logging
import math
import os
import queue
import threading
import time

try:
    import dictation as _ears  # v9.0: the live mic level now
    # comes from the one-shot dictation recorder (get_level
    # kept its shape — the meter dances only while dictating)
except Exception:  # pragma: no cover - meter just stays flat
    _ears = None

try:
    import voice as _voice  # for the speaking wave + ring pulse
except Exception:  # pragma: no cover - face just stays calm
    _voice = None

log = logging.getLogger("nalox.hud")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BG = "#1f2430"        # window background (dark slate)
CARD = "#2a3040"      # cards / panels
CARD_DARK = "#232936"  # conversation + meter background
FG = "#e6e9f0"
MUTED = "#8b93a7"
ACCENT = "#2dd4bf"    # teal
BLUE = "#60a5fa"
AMBER = "#fbbf24"
VIOLET = "#e879f9"
RED = "#ff6b6b"
BTN_BG = "#343c52"
BTN_ACTIVE = "#3f4a68"

# state -> (pill text, pill fg, pill bg)
STATUS_STYLES = {
    "listening": ("● Ready", ACCENT, "#123b34"),
    "awake": ("● Awake", AMBER, "#3d2f10"),
    "thinking": ("● Thinking", BLUE, "#1e3350"),
    "speaking": ("● Speaking", VIOLET, "#3d1e42"),
    "idle": ("● Sleeping", MUTED, CARD),
}

MAX_LOG_LINES = 300

WELCOME_LINES = [
    "Nalox is ready.",
    "Type below, tap 🎙 and speak, or message on Telegram.",
]


def _release_topmost(root):
    """Drop a window's -topmost raise (v5.7).

    The HUD (and Settings) raise themselves with -topmost so
    they land in front when they appear — but v5.6 and earlier
    never let go, so the app window sat above EVERYTHING
    forever and every app Nalox opened appeared behind it
    (the owner's 14:38 complaint). The raise is now a brief
    landing gesture, released ~1 s later via after()."""
    try:
        root.attributes("-topmost", False)
    except Exception:
        pass


class Hud:
    """Thread-safe handle to the app window.

    Public API (safe to call from any thread, never raises):
        start(), post(text), set_status(state), set_brain(text),
        show(), hide(), stop()
    """

    def __init__(self, cfg):
        self.cfg = cfg
        # v4.6: restart hook — nalox.py assigns its restart routine
        # here after construction (the HUD must not import nalox).
        # None = nobody wired it; the button then falls back to a
        # plain supervisor-relaunch exit on its own.
        self.on_restart = None
        # v5.5: Command Center hook — nalox.py assigns its
        # dashboard opener here (the HUD must not import
        # nalox.py). None = nobody wired it; the button then
        # opens a dashboard of its own, guarded like everything
        # else in this window.
        self.on_command_center = None
        self._dashboard = None
        self._queue = queue.Queue(maxsize=500)
        self._failed = False
        self._thread = None
        self._root = None
        self._status_label = None
        # v4.8: the brain status line in the header ("Brain: Groq
        # ✓" / "Brain: Claude — key rejected (401)" / "Brain:
        # Local — no key"). set_brain() may be called before the
        # window exists; the text is kept here and applied by
        # _build / _poll whenever it lands.
        self._brain_label = None
        self._brain_text = None
        self._text = None
        self._logo_img = None  # keep a reference or Tk garbage-collects it
        self._mic_canvas = None
        self._mic_db_label = None
        # v4.3 face: logo ring canvas + speaking-wave canvas + the
        # last status seen (drives the ring colour).
        self._logo_canvas = None
        self._wave_canvas = None
        self._status_state = "listening"
        # Whether this window is currently SHOWN (it
        # builds withdrawn — v6.2 silent start — and
        # show()/hide() track it from there).
        self._shown = False
        # v9.0 INPUT ROW state: the callback attributes
        # nalox.py wires (typed text + mic button), and the
        # Tk-thread widget refs.
        self.on_text_submit = None
        self.on_mic_press = None
        self._input_entry = None
        self._mic_btn = None
        self._dict_label = None

    # ------------------------------------------------ public API
    def start(self):
        """Spawn the tk thread. Returns immediately."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="nalox-hud")
        self._thread.start()

    def post(self, text):
        self._send(("log", str(text)))

    def set_status(self, state):
        self._send(("status", str(state).strip().lower()))

    def set_brain(self, text):
        """v4.8: update the header's brain line (thread-safe)."""
        self._brain_text = str(text)
        self._send(("brain", str(text)))

    def show(self):
        self._shown = True
        self._send(("cmd", "show"))

    def hide(self):
        self._shown = False
        self._send(("cmd", "hide"))

    def is_shown(self):
        """v7.6: True when this window is up on screen
        (built withdrawn; show()/hide() track it)."""
        return bool(self._shown) and not self._failed

    # -------------------------------- v9.0 input row
    def set_input_text(self, text):
        """Show text in the input box (a finished
        dictation lands here just before it auto-sends).
        Thread-safe."""
        self._send(("input_text", str(text or "")))

    def set_dictation_state(self, state, seconds_left=None):
        """The dictation state line beside the mic
        button ("🎙 বলুন…" / countdown / "শুনছি…").
        Thread-safe."""
        self._send(("dict_state", (str(state), seconds_left)))

    def stop(self):
        self._send(("cmd", "quit"))

    def run_on_tk(self, fn):
        """Run fn() on the Tk thread (v5.5.1).

        The Command Center (dashboard.py) is a Toplevel on
        this window's root: it builds and drives its widgets
        from callbacks queued here, so Nalox keeps exactly
        ONE Tk interpreter on ONE thread. fn runs inside
        _poll's drain — keep it quick, and it must guard its
        own failures (the drain guards them again anyway).
        """
        self._send(("callback", fn))

    def tk_root(self):
        """The Tk root this window owns (None until built).

        Only meaningful on/after the Tk thread has built the
        window; dashboard.py reads it inside a run_on_tk
        callback, where the root is guaranteed to exist.
        """
        return self._root

    def _send(self, item):
        if self._failed:
            return
        try:
            self._queue.put_nowait(item)
        except Exception:
            pass  # queue full / shutting down — never break Nalox

    # ------------------------------------------------ tk thread
    def _run(self):
        try:
            import tkinter as tk
        except Exception as exc:
            self._failed = True
            log.warning("App window disabled: tkinter unavailable (%s)", exc)
            return
        try:
            self._build(tk)
            self._poll()
            self._root.mainloop()
        except Exception as exc:
            self._failed = True
            log.warning("App window disabled: %s", exc)

    def _build(self, tk):
        root = tk.Tk()
        self._root = root
        root.title("Nalox")
        # v4.7: the window + taskbar icon is his logo (multi-size
        # .ico). Guarded — a missing icon must never kill the app.
        try:
            root.iconbitmap(
                os.path.join(BASE_DIR, "assets", "logo.ico"))
        except Exception:
            pass
        root.configure(bg=BG)
        try:
            root.attributes("-topmost", True)
            # v5.7: brief raise only — released ~1 s later so
            # the window never stays pinned above the apps
            # Nalox opens (see _release_topmost).
            root.after(1000, lambda: _release_topmost(root))
        except Exception:
            pass
        try:
            screen_w = root.winfo_screenwidth()
            root.geometry("430x560+%d+40" % max(0, screen_w - 450))
        except Exception:
            root.geometry("430x560")
        # The X button hides the window instead of killing it, so
        # "show console" can always bring it back.
        root.protocol("WM_DELETE_WINDOW", self.hide)

        # ---------------- header: round logo + wave + title -------
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 6))

        # v4.3 THE FACE: his logo ROUND like JARVIS's (the circular
        # crop ships as assets/logo_round.png), drawn on a small
        # canvas with a status ring around it — dim slate idle,
        # teal listening, PULSING violet while Nalox speaks. Beside
        # it, a 7-bar speaking wave that dances only while Nalox
        # talks; when Arjun talks the wave stays calm and the mic
        # meter below dances instead. Both animate in _poll.
        self._logo_canvas = tk.Canvas(header, width=68, height=68,
                                      bg=BG, highlightthickness=0)
        self._logo_canvas.pack(side="left")
        for logo_name in ("logo_round.png", "logo.png", "logo.jpg"):
            try:
                from PIL import Image, ImageTk
                img = Image.open(os.path.join(BASE_DIR, "assets",
                                              logo_name))
                img = img.convert("RGBA")
                img.thumbnail((54, 54))
                self._logo_img = ImageTk.PhotoImage(img)
                break
            except Exception:
                self._logo_img = None
        self._wave_canvas = tk.Canvas(header, width=90, height=36,
                                      bg=BG, highlightthickness=0)
        self._wave_canvas.pack(side="left", padx=(8, 0))

        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", padx=12)
        tk.Label(title_box, text="NALOX", bg=BG, fg=FG,
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(title_box, text="Your personal assistant", bg=BG,
                 fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        # v4.8: the brain line — which brain is live and whether
        # its key actually works, in plain sight at all times.
        self._brain_label = tk.Label(
            title_box, text=self._brain_text or "Brain: checking…",
            bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._brain_label.pack(anchor="w")
        pill_text, pill_fg, pill_bg = STATUS_STYLES["listening"]
        self._status_label = tk.Label(
            title_box, text=pill_text, bg=pill_bg, fg=pill_fg,
            font=("Segoe UI", 9, "bold"), padx=8, pady=1)
        self._status_label.pack(anchor="w", pady=(4, 0))

        # ---------------- mic meter --------------------------------
        mic_frame = tk.Frame(root, bg=CARD)
        mic_frame.pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(mic_frame, text="🎤", bg=CARD, fg=FG,
                 font=("Segoe UI", 11)).pack(side="left", padx=(8, 0))
        self._mic_canvas = tk.Canvas(
            mic_frame, height=40, bg=CARD_DARK, highlightthickness=0)
        self._mic_canvas.pack(side="left", fill="x", expand=True,
                              padx=8, pady=6)
        self._mic_db_label = tk.Label(
            mic_frame, text="--", bg=CARD, fg=MUTED,
            font=("Segoe UI", 9, "bold"), width=6)
        self._mic_db_label.pack(side="left", padx=(0, 8))

        # ---------------- conversation view -------------------------
        self._text = tk.Text(
            root, bg=CARD_DARK, fg=FG, insertbackground=FG,
            font=("Segoe UI", 10), relief="flat", wrap="word",
            highlightthickness=0, state="disabled")
        self._text.pack(fill="both", expand=True, padx=12, pady=(10, 6))
        self._text.tag_configure("you_name", foreground=BLUE,
                                 font=("Segoe UI", 10, "bold"))
        self._text.tag_configure("nalox_name", foreground=ACCENT,
                                 font=("Segoe UI", 10, "bold"))
        self._text.tag_configure("body", foreground=FG)
        self._text.tag_configure("muted", foreground=MUTED)
        self._text.tag_configure("error", foreground=RED)

        # ---------------- input row (v9.0) --------------------------
        # The text-first door: type + Enter (or ➤) sends the
        # line exactly like a Telegram message; 🎙 starts /
        # finishes a one-shot dictation; the state line
        # shows "🎙 বলুন…" + the follow-up countdown.
        in_frame = tk.Frame(root, bg=BG)
        in_frame.pack(fill="x", padx=12, pady=(0, 2))
        _entry = tk.Entry(
            in_frame, bg=CARD_DARK, fg=FG, insertbackground=FG,
            font=("Segoe UI", 10), relief="flat",
            highlightbackground=BTN_BG, highlightthickness=1)
        _entry.pack(side="left", fill="x", expand=True, ipady=4)
        _mic = tk.Button(
            in_frame, text="🎙", bg=ACCENT, fg="#123b34",
            activebackground=BTN_ACTIVE, relief="flat",
            font=("Segoe UI", 11, "bold"), cursor="hand2",
            padx=8, pady=2)
        _mic.pack(side="left", padx=(6, 0))
        _send = tk.Button(
            in_frame, text="➤", bg=BTN_BG, fg=FG,
            activebackground=BTN_ACTIVE, relief="flat",
            font=("Segoe UI", 10), cursor="hand2",
            padx=8, pady=2)
        _send.pack(side="left", padx=(6, 0))
        self._input_entry = _entry
        self._mic_btn = _mic

        def _submit_input(_event=None):
            try:
                _text = _entry.get().strip()
            except Exception:
                _text = ""
            if not _text:
                return "break"
            try:
                _entry.delete(0, "end")
            except Exception:
                pass
            _cb = self.on_text_submit
            if _cb is not None:
                try:
                    _cb(_text)
                except Exception:
                    pass
            return "break"

        _entry.bind("<Return>", _submit_input)
        _send.configure(command=_submit_input)

        def _mic_press():
            _cb = self.on_mic_press
            if _cb is not None:
                try:
                    _cb()
                except Exception:
                    pass

        _mic.configure(command=_mic_press)
        self._dict_label = tk.Label(
            root, text="", bg=BG, fg=ACCENT,
            font=("Segoe UI", 9, "bold"))
        self._dict_label.pack(anchor="w", padx=14, pady=(0, 2))

        # ---------------- buttons row -------------------------------
        btn_frame = tk.Frame(root, bg=BG)
        btn_frame.pack(fill="x", padx=12, pady=(2, 12))

        def btn(text, command, fg=FG):
            return tk.Button(
                btn_frame, text=text, command=command, bg=BTN_BG,
                fg=fg, activebackground=BTN_ACTIVE, activeforeground=fg,
                relief="flat", font=("Segoe UI", 10), cursor="hand2",
                padx=10, pady=4)

        btn("📋 Log", self._on_log).pack(side="left", padx=(0, 6))
        btn("⚙️ Settings", self._on_settings).pack(side="left", padx=(0, 6))
        btn("🖥 Command Center", self._on_command_center).pack(
            side="left", padx=(0, 6))
        btn("Hide", self._on_hide).pack(side="left", padx=(0, 6))
        btn("🔄 Restart", self._on_restart).pack(side="left", padx=(0, 6))
        btn("Exit Nalox", self._on_exit, fg="#ff8585").pack(side="right")

        for line in WELCOME_LINES:
            self._append(line)

        # v6.2 SILENT START: the window is built WITHDRAWN.
        # Boot must never flash the plain window — every start
        # lands on the Command Center (nalox.py opens it once
        # boot completes), and this window appears only when
        # it is explicitly asked for (tray "Open Nalox", the
        # single-instance show signal). show() deiconifies it
        # exactly as before.
        try:
            root.withdraw()
        except Exception:
            pass

    # ------------------------------------------------ button actions
    # (all run on the tk thread)
    def _on_log(self):
        """Open the diagnostics page (nalox_page.html)."""
        try:
            import logbook
            logbook.regenerate()
            path = logbook.PAGE_PATH
            if os.path.exists(path):
                os.startfile(path)  # Windows: default browser
        except Exception as exc:
            log.warning("Could not open the log page: %s", exc)

    def _on_settings(self):
        """Open the Settings window (settings_ui.py)."""
        try:
            import settings_ui
            settings_ui.open_settings(self._root, self.cfg)
        except Exception as exc:
            log.warning("Could not open Settings: %s", exc)

    def _on_command_center(self):
        """Open the fullscreen Command Center (v5.5).

        nalox.py's opener (the on_command_center callback) owns
        the shared dashboard and its window fallback; with no
        callback wired, open one owned by this window. Either
        way a failure only logs — the button can never break
        the app window.
        """
        callback = self.on_command_center
        if callable(callback):
            try:
                callback()
                return
            except Exception as exc:
                log.warning("Command Center callback failed (%s); "
                            "trying a window-owned dashboard", exc)
        try:
            if self._dashboard is None:
                import dashboard
                self._dashboard = dashboard.Dashboard(self.cfg)
                # v5.5.1: hosted on THIS window's root/thread —
                # the dashboard owns no interpreter of its own.
                self._dashboard.attach(self)
                self._dashboard.start()
            self._dashboard.show()
        except Exception as exc:
            log.warning("Could not open the Command Center: %s", exc)

    def _on_hide(self):
        self._shown = False
        try:
            self._root.withdraw()
        except Exception:
            pass

    def _on_restart(self):
        """Restart Nalox (v4.6) — Arjun's hang remedy, clickable.

        Posts the feed line FIRST (he must SEE that the click
        landed), then hands over to nalox.py's restart routine
        via the on_restart callback (exit code 1 — supervisor
        relaunches). If nobody wired the callback, or it raises,
        fall back to the Settings pattern: a timer thread and
        os._exit(0) (any code but 42 relaunches). A 3 s safety
        timer with code 1 is armed in every case, so even a
        half-broken callback can never leave a zombie process
        that only LOOKS restarted.
        """
        try:
            self.post("Restarting Nalox…")
        except Exception:
            pass
        # v7.7: speech stops before the restart begins —
        # covers the direct-exit fallback below too (the
        # callback path lands in nalox.py's restart, which
        # stops speech again, harmlessly).
        try:
            import voice as _voice_mod
            _voice_mod.stop_for_exit()
        except Exception:
            pass
        try:
            import logbook
            logbook.log("SYSTEM", "Restart pressed in the app window.")
        except Exception:
            pass
        callback = self.on_restart
        if callable(callback):
            try:
                callback()
                threading.Timer(3.0, lambda: os._exit(1)).start()
                return
            except Exception as exc:
                log.warning("Restart callback failed (%s); "
                            "falling back to a direct exit", exc)

        def _die():
            # v6.1: name the exit before taking it (the
            # "[sys] exiting (restart)" rule — no silent
            # deliberate exits; the supervisor reads code 0
            # as a restart, and this line says why).
            try:
                import logbook
                logbook.log(
                    "SYSTEM",
                    "[sys] exiting (restart): app-window "
                    "Restart — direct exit (the restart "
                    "callback was unavailable)")
            except Exception:
                pass
            try:
                os._exit(0)  # not 42: the supervisor relaunches
            except Exception:
                pass
        threading.Timer(0.25, _die).start()

    def _on_exit(self):
        """Clean exit — code 42 tells the supervisor NOT to relaunch
        (same as the tray's "Exit Nalox")."""
        try:
            import logbook
            logbook.log("SYSTEM", "Exit Nalox pressed in the app window.")
        except Exception:
            pass
        # v7.7: speech stops before the exit begins (no
        # SAPI call mid-flight during shutdown).
        try:
            import voice as _voice_mod
            _voice_mod.stop_for_exit()
        except Exception:
            pass
        # v4.7 ALWAYS-ON: a deliberate exit also writes the flag
        # the supervisor checks before relaunching, so Nalox stays
        # down until the next manual launch (which clears it).
        # Restart paths never write this flag.
        try:
            with open(os.path.join(BASE_DIR, "exit_requested.flag"),
                      "w", encoding="utf-8") as fh:
                fh.write("exit requested from the app window\n")
        except Exception:
            pass

        def _die():
            try:
                os._exit(42)
            except Exception:
                pass
        threading.Timer(0.25, _die).start()

    # ------------------------------------------------ rendering
    def _draw_face(self):
        """Animate the logo ring + speaking wave (tk thread, ~80 ms).

        Ring: violet and PULSING (width oscillates) while Nalox is
        speaking; teal while listening; amber awake; blue thinking;
        dim slate otherwise. Wave: 7 bars dance procedurally while
        Nalox speaks (per-bar phase), flat calm line otherwise —
        Arjun's own voice animates the mic meter, not this wave.
        """
        t = time.monotonic()
        speaking = False
        if _voice is not None:
            try:
                speaking = bool(_voice.is_speaking())
            except Exception:
                speaking = False
        canvas = self._logo_canvas
        if canvas is not None:
            try:
                canvas.delete("face")
                if speaking:
                    width = 3.5 + 1.5 * math.sin(t * 6.0)
                    colour = VIOLET
                elif self._status_state == "listening":
                    width, colour = 2, ACCENT
                elif self._status_state == "awake":
                    width, colour = 2, AMBER
                elif self._status_state == "thinking":
                    width, colour = 2, BLUE
                else:
                    width, colour = 2, "#4a5468"
                canvas.create_oval(3, 3, 65, 65, outline=colour,
                                   width=max(1, int(round(width))),
                                   tags="face")
                if self._logo_img is not None:
                    canvas.create_image(34, 34, image=self._logo_img,
                                        tags="face")
                else:
                    canvas.create_text(34, 34, text="N", fill=ACCENT,
                                       font=("Segoe UI", 22, "bold"),
                                       tags="face")
            except Exception:
                pass
        wave = self._wave_canvas
        if wave is not None:
            try:
                wave.delete("wave")
                bars, gap = 7, 3
                bar_w = (90 - gap * (bars + 1)) / bars
                mid, max_h = 18.0, 15.0
                for i in range(bars):
                    if speaking:
                        frac = 0.4 + 0.6 * abs(
                            math.sin(t * 9.0 + i * 0.9))
                    else:
                        frac = 0.07  # calm flat line
                    bh = max(1.5, frac * max_h)
                    x0 = gap + i * (bar_w + gap)
                    wave.create_rectangle(
                        x0, mid - bh, x0 + bar_w, mid + bh,
                        fill=VIOLET if speaking else "#4a5468",
                        outline="", tags="wave")
            except Exception:
                pass

    def _draw_mic(self):
        """Redraw the 16-bar mic equalizer + dB readout (tk thread)."""
        canvas = self._mic_canvas
        if canvas is None:
            return
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 40 or h < 10:
            return
        level = 0.0
        if _ears is not None:
            try:
                level = float(_ears.get_level())
            except Exception:
                level = 0.0
        level = max(0.0, min(1.0, level))
        t = time.monotonic()
        canvas.delete("micbar")
        bars = 16
        gap = 3
        bar_w = max(2.0, (w - gap * (bars + 1)) / bars)
        base = h - 4
        max_h = h - 8
        for i in range(bars):
            wave = 0.55 + 0.45 * math.sin(t * 7.0 + i * 1.35)
            frac = level * wave
            if frac < 0.04:
                frac = 0.04  # tiny idle bars, never fully dead
            elif frac > 1.0:
                frac = 1.0
            bh = frac * max_h
            x0 = gap + i * (bar_w + gap)
            colour = AMBER if frac > 0.85 else ACCENT
            canvas.create_rectangle(x0, base - bh, x0 + bar_w, base,
                                    fill=colour, outline="", tags="micbar")
        if self._mic_db_label is not None:
            if level <= 0.01:
                txt = "--"
            else:
                txt = "%d dB" % int(-50 + level * 50)
            try:
                self._mic_db_label.configure(text=txt)
            except Exception:
                pass

    def _append(self, text):
        """Render one posted line in the conversation view.

        The post() feed is the same one nalox.py/brain.py have always
        used; the prefixes are rendered chat-style:
          "NALOX: ..."        -> "Nalox" (teal) + body
          "[mic] heard: ..."  -> "You" (blue) + body
          "[heard] ..."       -> muted, with a 🎙
          "[error] ..."       -> red
          everything else     -> muted system note
        """
        widget = self._text
        if widget is None:
            return
        widget.configure(state="normal")
        try:
            if text.startswith("NALOX: "):
                widget.insert("end", "Nalox  ", "nalox_name")
                widget.insert("end", text[len("NALOX: "):] + "\n", "body")
            elif text.startswith("[mic] heard: "):
                widget.insert("end", "You  ", "you_name")
                widget.insert("end", text[len("[mic] heard: "):] + "\n",
                              "body")
            elif text.startswith("[error]"):
                widget.insert("end", text + "\n", "error")
            elif text.startswith("[heard] "):
                widget.insert("end", "🎙 " + text[len("[heard] "):] + "\n",
                              "muted")
            else:
                widget.insert("end", text + "\n", "muted")
            line_count = int(widget.index("end-1c").split(".")[0])
            if line_count > MAX_LOG_LINES:
                widget.delete("1.0", "%d.0" % (line_count - MAX_LOG_LINES))
            widget.see("end")
        finally:
            widget.configure(state="disabled")

    def _poll(self):
        """Drain the queue into the widgets; reschedule via after()."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "input_text":
                    if self._input_entry is not None:
                        try:
                            self._input_entry.delete(0, "end")
                            self._input_entry.insert(
                                0, str(payload or ""))
                        except Exception:
                            pass
                elif kind == "dict_state":
                    _st, _left = payload
                    if self._dict_label is not None:
                        try:
                            import dashboard as _dash_mod
                            self._dict_label.configure(
                                text=_dash_mod
                                .dictation_state_text(_st, _left))
                        except Exception:
                            pass
                    if self._mic_btn is not None:
                        try:
                            self._mic_btn.configure(
                                text="⏹" if _st in (
                                    "recording", "followup")
                                else "🎙")
                        except Exception:
                            pass
                elif kind == "status":
                    self._status_state = payload
                    label, fg, bg = STATUS_STYLES.get(
                        payload, STATUS_STYLES["idle"])
                    if self._status_label is not None:
                        self._status_label.configure(text=label, fg=fg,
                                                     bg=bg)
                elif kind == "brain":
                    # v4.8: green when the brain answers, red when
                    # its key is rejected/unreachable, muted else.
                    self._brain_text = payload
                    if self._brain_label is not None:
                        if "✓" in payload:
                            fg = "#7ee2a0"
                        elif "rejected" in payload \
                                or "unreachable" in payload \
                                or "wrong field" in payload:
                            fg = "#ff8585"
                        else:
                            fg = MUTED
                        self._brain_label.configure(text=payload, fg=fg)
                elif kind == "callback":
                    # v5.5.1: run_on_tk() work — the Command
                    # Center's build lands here, on the Tk
                    # thread, against this window's root.
                    try:
                        payload()
                    except Exception as exc:
                        log.warning("Tk callback failed: %s", exc)
                elif kind == "cmd":
                    if payload == "show":
                        self._root.deiconify()
                        self._root.lift()
                        try:
                            self._root.focus_force()
                        except Exception:
                            pass
                    elif payload == "hide":
                        self._root.withdraw()
                    elif payload == "quit":
                        self._root.destroy()
                        return
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self._draw_face()
        except Exception:
            pass
        try:
            self._draw_mic()
        except Exception:
            pass
        try:
            self._root.after(80, self._poll)
        except Exception:
            pass  # window is gone; stop polling
