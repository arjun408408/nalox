"""System tray icon for Nalox (pystray + Pillow).

v4.7 ALWAYS-ON: the tray is Nalox's permanent home on the PC.
Menu: "Nalox is running" (disabled status), "Open Nalox"
(default item — shows + focuses the window), "Command Center"
(v5.5, only when the caller wires it — opens the fullscreen
dashboard), "Restart", "Exit Nalox". "Exit Nalox" is one of only two deliberate-exit
paths: it writes exit_requested.flag (the supervisor checks it
and does NOT relaunch) and exits with code 42. "Restart" exits
with code 1 and never writes the flag. If pystray is unavailable
the tray is skipped and Nalox runs exactly as before.
"""
import logging
import os
import subprocess
import sys
import threading

log = logging.getLogger("nalox.tray")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLEAN_EXIT_CODE = 42


def make_icon_image():
    """Nalox's face: Arjun's channel logo, ROUND crop first
    (assets/logo_round.png, v4.7), then assets/logo.jpg.

    Falls back to a simple drawn gold 'N' on dark blue if the logo
    can't be loaded for any reason.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    for logo_name in ("logo_round.png", "logo.jpg"):
        logo_path = os.path.join(BASE_DIR, "assets", logo_name)
        try:
            img = Image.open(logo_path).convert("RGB")
            img = ImageOps.fit(img, (64, 64))  # centre-crop to a square icon
            log.info("Tray icon: using channel logo (%s)", logo_path)
            return img
        except Exception as exc:
            log.warning("Could not load %s (%s); trying next.", logo_name, exc)
    img = Image.new("RGB", (64, 64), (16, 24, 43))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 61, 61], radius=12, outline=(242, 193, 78), width=3)
    try:
        font = ImageFont.truetype("arialbd.ttf", 38)
    except Exception:
        font = ImageFont.load_default()
    d.text((32, 32), "N", fill=(242, 193, 78), font=font, anchor="mm")
    return img


def _write_exit_flag():
    """v4.7: mark a DELIBERATE exit so the supervisor does not
    relaunch. Guarded — a failed write must never block exiting
    (exit code 42 alone already stops the supervisor)."""
    try:
        with open(os.path.join(BASE_DIR, "exit_requested.flag"),
                  "w", encoding="utf-8") as fh:
            fh.write("exit requested from the tray menu\n")
    except Exception:
        pass


def run_tray(on_exit=None, on_show_console=None, on_hide_console=None,
             on_command_center=None):
    """Start the tray icon in a background thread (non-blocking).

    on_show_console (v4.7) is the tray's "Open Nalox" action (show +
    focus the window) and is registered as the menu's DEFAULT item
    (pystray fires the default item on double-click). on_hide_console
    is still accepted for older callers but no longer surfaced — the
    window's X button hides it. on_command_center (v5.5) adds a
    "Command Center" item that opens the fullscreen dashboard.
    """
    try:
        import pystray
    except Exception as exc:
        log.warning("pystray unavailable (%s); tray icon skipped.", exc)
        return None

    def _stop_speech_for_exit():
        # v7.7: no SAPI call may be mid-flight when the
        # process exits (see voice.stop_for_exit).
        try:
            import voice as _voice_mod
            _voice_mod.stop_for_exit()
        except Exception:
            pass

    def _exit(icon, _item):
        log.info("Exit chosen from tray.")
        _stop_speech_for_exit()
        _write_exit_flag()
        icon.stop()
        if on_exit:
            on_exit()
        os._exit(CLEAN_EXIT_CODE)

    def _restart(icon, _item):
        log.info("Restart chosen from tray.")
        _stop_speech_for_exit()
        icon.stop()
        os._exit(1)  # supervisor will relaunch; NO exit flag

    items = [pystray.MenuItem("Nalox is running", None, enabled=False)]
    if on_show_console is not None:
        items.append(pystray.MenuItem(
            "Open Nalox", lambda _icon, _item: on_show_console(),
            default=True))
    if on_command_center is not None:
        items.append(pystray.MenuItem(
            "Command Center",
            lambda _icon, _item: on_command_center()))
    items.append(pystray.MenuItem("Restart", _restart))
    items.append(pystray.MenuItem("Exit Nalox", _exit))

    icon = pystray.Icon(
        "nalox",
        make_icon_image(),
        "Nalox — your assistant",
        menu=pystray.Menu(*items),
    )
    t = threading.Thread(target=icon.run, daemon=True, name="tray")
    t.start()
    log.info("Tray icon started.")
    return icon
