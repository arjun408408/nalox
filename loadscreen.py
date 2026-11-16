#!/usr/bin/env python3
"""The boot loading screen (v7.11 — "Ready Means Ready").

Shown on every start, BEFORE the Command Center: his
logo, a progress bar with a real percentage, and the
boot probe's checklist (bootprobe.py) flipping
⏳ -> ✓ / ⚠ / ✗ stage by stage. When the probe gate
opens (all stages resolved, or the 45 s cap), nalox.py
closes this window and opens the Command Center — the
interface only ever appears on a machine that has
finished starting.

HOSTING mirrors dashboard.py exactly (v5.5.1's lesson):
the window is a Toplevel on the HUD's Tk root, built
and driven only on the HUD's thread via hud.run_on_tk —
Nalox keeps ONE Tk interpreter on ONE thread. Every
public method is any-thread and never raises; a build
or render failure sets `failed` and nalox.py falls
back to the pre-v7.11 boot (the gate's abort watch —
the screen can never brick startup).

HEADLESS MODE (_force_headless, the suites' pattern
from dashboard.py): no Tk at all — the class keeps the
same bookkeeping (shown / snapshot / progress /
close-exactly-once) as pure state, so the handoff
logic is unit-pinnable on a machine with no display.
The VISUAL result is first proven on the owner's PC.
"""

import logging
import os
import threading

log = logging.getLogger("nalox.loadscreen")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# The Command Center's palette (dashboard.py) — the
# loading screen speaks the same visual language.
BG = "#05080f"
PANEL = "#0a1120"
PANEL_EDGE = "#16233d"
ACCENT = "#38bdf8"
TEXT = "#e2e8f0"
DIM = "#7d8aa0"
OK_COLOR = "#34d399"
WARN_COLOR = "#fbbf24"
FAIL_COLOR = "#f87171"
PENDING_COLOR = "#64748b"

_MARKERS = {"ok": ("✓", OK_COLOR), "warn": ("⚠", WARN_COLOR),
            "fail": ("✗", FAIL_COLOR),
            "pending": ("⏳", PENDING_COLOR)}


class LoadingScreen:
    """The boot loading window (v7.11). See the module
    header for the hosting rules."""

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self._hud = None
        self._started = False
        self._force_headless = False
        self._failed = False
        self._shown = False
        self._closed = False
        self._close_count = 0
        self._lock = threading.Lock()
        # Latest probe state (any-thread; the Tk side
        # only ever reads these).
        self._snapshot = []
        self._progress = 0.0
        # Tk-thread-only state:
        self._root = None          # the Toplevel itself
        self._rows = {}            # key -> (marker, detail)
        self._bar_inner = None
        self._pct_label = None
        self._foot_label = None
        self._logo_img = None      # PhotoImage (keep a ref)
        self._redraw_queued = False
        self._poll_on = False

    # ------------------------------------------------ public API
    @property
    def failed(self):
        """True once the real window build/render has
        failed — nalox.py's gate abort watch reads this
        and falls back to the pre-v7.11 boot."""
        return self._failed

    @property
    def closed(self):
        return self._closed

    def attach(self, hud):
        """Host on the app window (hud.Hud), exactly
        like the Command Center. Call before start().
        Never raises."""
        try:
            self._hud = hud
            if hud is None:
                self._force_headless = True
        except Exception:
            pass

    def bind_probe(self, probe):
        """Render a BootProbe's state: the probe's
        on_update becomes this screen's feed (any
        previously registered callback is chained).
        Never raises."""
        try:
            prev = getattr(probe, "_on_update", None)

            def _feed(snapshot, progress):
                if prev is not None:
                    try:
                        prev(snapshot, progress)
                    except Exception:
                        pass
                self._on_probe_update(snapshot, progress)

            probe._on_update = _feed
            # Render whatever already resolved before
            # the binding landed.
            self._on_probe_update(probe.snapshot(),
                                  probe.progress())
        except Exception:
            pass

    def start(self):
        """Show the window. Returns immediately; the
        build lands on the Tk thread. Headless: pure
        bookkeeping. Never raises."""
        try:
            if self._started:
                return
            self._started = True
            self._shown = True
            if self._force_headless or self._hud is None:
                self._force_headless = True
                return
            self._hud.run_on_tk(self._tk_build)
        except Exception as exc:
            self._failed = True
            log.warning("Loading screen start failed: %s",
                        exc)

    def close(self):
        """Close the window — EXACTLY ONCE, however
        often it is called (the loading->Command Center
        handoff is a single event). Never raises."""
        try:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                self._close_count += 1
            self._poll_on = False
            if self._force_headless or self._hud is None:
                return
            self._hud.run_on_tk(self._tk_destroy)
        except Exception:
            pass

    # ------------------------------------------------ probe feed
    def _on_probe_update(self, snapshot, progress):
        """A probe resolution landed (any thread):
        store the state and queue ONE redraw."""
        try:
            with self._lock:
                self._snapshot = list(snapshot or [])
                try:
                    self._progress = float(progress)
                except Exception:
                    self._progress = 0.0
                if self._closed or self._force_headless \
                        or self._hud is None:
                    return
                if self._redraw_queued:
                    return
                self._redraw_queued = True
            self._hud.run_on_tk(self._tk_redraw)
        except Exception:
            pass

    # ------------------------------------------------ Tk thread
    def _tk_build(self):
        """Build + show the window (Tk thread only). A
        failure here marks the screen failed — the gate
        abort watch then opens the Command Center the
        old way instead of waiting on a broken screen."""
        try:
            if self._closed:
                return  # a close beat the build — stay down
            import tkinter as tk
            host = self._hud.tk_root() if self._hud else None
            if host is None:
                self._failed = True
                log.warning("Loading screen: no Tk root "
                            "to host on")
                return
            root = tk.Toplevel(host)
            self._root = root
            root.title("Nalox — starting")
            try:
                root.iconbitmap(os.path.join(
                    BASE_DIR, "assets", "logo.ico"))
            except Exception:
                pass
            root.configure(bg=BG)
            root.resizable(False, False)
            # Centre a 600x700 window on the screen.
            try:
                w, h = 600, 700
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                root.geometry(f"{w}x{h}+"
                              f"{max(0, (sw - w) // 2)}+"
                              f"{max(0, (sh - h) // 2)}")
            except Exception:
                pass
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            # The window is a boot stage, not an app:
            # its close button is inert while it lives
            # (it is destroyed by the gate, at most 45 s).
            try:
                root.protocol("WM_DELETE_WINDOW",
                              lambda: None)
            except Exception:
                pass

            outer = tk.Frame(root, bg=BG)
            outer.pack(fill="both", expand=True,
                       padx=34, pady=26)
            # His logo, prominent (guarded — a missing
            # image must never cost the screen).
            self._logo_img = self._load_logo(118)
            if self._logo_img is not None:
                tk.Label(outer, image=self._logo_img,
                         bg=BG).pack(pady=(2, 6))
            tk.Label(outer, text="NALOX", bg=BG, fg=TEXT,
                     font=("Segoe UI", 27, "bold")).pack()
            tk.Label(outer,
                     text="Getting everything ready…",
                     bg=BG, fg=DIM,
                     font=("Segoe UI", 11)).pack(
                         pady=(0, 14))
            # Progress: percentage + a drawn bar (the
            # dashboard's own-bar pattern, no ttk).
            self._pct_label = tk.Label(
                outer, text="0%", bg=BG, fg=ACCENT,
                font=("Segoe UI", 15, "bold"))
            self._pct_label.pack()
            bar_outer = tk.Frame(outer, bg=PANEL_EDGE,
                                 height=10)
            bar_outer.pack(fill="x", pady=(4, 16))
            bar_outer.pack_propagate(False)
            self._bar_inner = tk.Frame(bar_outer,
                                       bg=ACCENT, height=10)
            self._bar_inner.place(x=0, y=0, relwidth=0.0,
                                  relheight=1.0)
            # The checklist: one row per probe stage
            # (from the bound probe's snapshot; the
            # fixed stage defs when nothing is bound
            # yet, so the rows can never go missing).
            rows = tk.Frame(outer, bg=BG)
            rows.pack(fill="x")
            self._rows = {}
            stage_rows = self._snapshot
            if not stage_rows:
                try:
                    import bootprobe as _bp
                    stage_rows = [
                        {"key": k, "label": l,
                         "status": "pending", "detail": ""}
                        for k, l, _b in _bp.STAGE_DEFS]
                except Exception:
                    stage_rows = []
            for st in stage_rows:
                row = tk.Frame(rows, bg=BG)
                row.pack(fill="x", pady=2)
                marker = tk.Label(
                    row, text="⏳", bg=BG,
                    fg=PENDING_COLOR, width=3,
                    font=("Segoe UI", 12, "bold"))
                marker.pack(side="left")
                tk.Label(row, text=st["label"], bg=BG,
                         fg=TEXT, width=24, anchor="w",
                         font=("Segoe UI", 11)).pack(
                             side="left")
                detail = tk.Label(
                    row, text="", bg=BG, fg=DIM,
                    anchor="w", font=("Segoe UI", 10))
                detail.pack(side="left", fill="x",
                            expand=True)
                self._rows[st["key"]] = (marker, detail)
            self._foot_label = tk.Label(
                outer,
                text="The Command Center opens when "
                     "everything is ready.",
                bg=BG, fg=DIM, font=("Segoe UI", 9))
            self._foot_label.pack(pady=(16, 0))
            self._tk_redraw()
            self._poll_on = True
            root.after(250, self._tk_poll)
        except Exception as exc:
            self._failed = True
            log.warning("Loading screen build failed: "
                        "%s", exc)

    def _load_logo(self, px):
        """His round logo at px size (PIL), or None —
        the same guarded load the dashboard performs."""
        try:
            from PIL import Image, ImageTk
            for name in ("logo_round.png", "logo.jpg"):
                path = os.path.join(BASE_DIR, "assets",
                                    name)
                if os.path.isfile(path):
                    img = Image.open(path).convert("RGBA")
                    img = img.resize((px, px))
                    return ImageTk.PhotoImage(img)
        except Exception:
            pass
        return None

    def _tk_poll(self):
        """A 250 ms refresh chain while the window
        lives (Tk thread): the stored probe state is
        re-rendered even if an update callback was
        dropped on a full queue."""
        try:
            if self._closed or self._root is None:
                self._poll_on = False
                return
            self._tk_redraw()
            self._root.after(250, self._tk_poll)
        except Exception:
            self._poll_on = False

    def _tk_redraw(self):
        """Render the latest stored probe state (Tk
        thread). Runs from the update feed and the
        poll chain alike; cheap and idempotent."""
        try:
            self._redraw_queued = False
            if self._closed or self._root is None:
                return
            pct = int(round(self._progress * 100))
            if self._pct_label is not None:
                self._pct_label.config(text=f"{pct}%")
            if self._bar_inner is not None:
                self._bar_inner.place(
                    relwidth=max(0.0,
                                 min(1.0, self._progress)))
            for st in self._snapshot:
                widgets = self._rows.get(st["key"])
                if widgets is None:
                    continue
                marker, detail = widgets
                glyph, color = _MARKERS.get(
                    st["status"], _MARKERS["pending"])
                try:
                    marker.config(text=glyph, fg=color)
                    detail.config(text=st["detail"] or "")
                except Exception:
                    pass
            if self._progress >= 1.0 \
                    and self._foot_label is not None:
                self._foot_label.config(
                    text="Everything is ready — opening "
                         "the Command Center…")
        except Exception as exc:
            self._failed = True
            log.warning("Loading screen redraw failed: "
                        "%s", exc)

    def _tk_destroy(self):
        """Destroy the window (Tk thread), once."""
        try:
            self._poll_on = False
            root, self._root = self._root, None
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
        except Exception:
            pass
