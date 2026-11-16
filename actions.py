"""OS actions Nalox can perform on Arjun's Windows laptop.
Every function returns a short spoken reply string."""
import ctypes
import os
import shutil
import subprocess
import tempfile
import webbrowser
from datetime import datetime

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:  # pragma: no cover
    pyautogui = None

try:
    import winlayout as _winlayout
except Exception:  # pragma: no cover - opens still work
    _winlayout = None


# ------------------------------------------------- v5.7: step aside + front
# The owner's complaint (2026-11-15 14:38): apps Nalox opened
# appeared BEHIND the Nalox window / Command Center — "আমি
# যদি বলি ওপেন ক্রোম, তো ক্রোমটা আমার স্ক্রিনে ওপেন করবে,
# কেন ও পিছনে ওপেন করে?" Two rules now govern every open:
#   1. STEP ASIDE: if the Command Center is up, it hides
#      itself BEFORE the open executes. The dashboard lives
#      in nalox.py, which registers a hook here at startup
#      (actions must not import nalox.py — the hook is the
#      seam, exactly like hud.on_command_center).
#   2. FRONT: after the launch, the new window is brought
#      to the foreground (winlayout.foreground_app) — an
#      open is done when the app is IN FRONT, not when its
#      process starts.
_step_aside_hook = None


def set_step_aside_hook(fn):
    """Register (or clear, with None) the step-aside hook."""
    global _step_aside_hook
    _step_aside_hook = fn if callable(fn) else None


def _step_aside():
    hook = _step_aside_hook
    if hook is not None:
        try:
            hook()
        except Exception:
            pass


_BROWSER_PROCS = ("chrome.exe", "msedge.exe", "firefox.exe",
                  "brave.exe", "opera.exe")


def _front(title_hints=(), process_hints=(), timeout_s=2.0):
    """Best-effort foreground for a just-opened window."""
    if _winlayout is None:
        return
    try:
        _winlayout.foreground_app(title_hints=title_hints,
                                  process_hints=process_hints,
                                  timeout_s=timeout_s)
    except Exception:
        pass


def _front_app(name):
    """Foreground hints for an app opened by name: its known
    process names (from APP_CANDIDATES) + title spellings."""
    key = (name or "").strip().lower()
    titles = set()
    procs = set()
    if key:
        titles.add(key)
        titles.add(key.title())
    for cand in APP_CANDIDATES.get(key, []):
        base = cand.replace("/", "\\").split("\\")[-1]
        if base.lower().endswith(".exe"):
            procs.add(base)
    if key == "whatsapp":
        procs.add("WhatsApp.exe")
        titles.add("WhatsApp")
    if not procs and key:
        procs.add(key.replace(" ", "") + ".exe")
    _front(title_hints=sorted(titles),
           process_hints=sorted(procs))


# ---------------------------------------------------------------- v7.7
def _hidden_console_kwargs():
    """subprocess kwargs that keep a console child INVISIBLE
    (v7.7, item G): CREATE_NO_WINDOW on Windows, nothing
    elsewhere. Console children (taskkill, powershell,
    shutdown, CLI shims) of a windowless parent otherwise
    flash a console window during tasks — the owner's
    "~1 second CMD flash" when he asks for a song."""
    if os.name == "nt":
        return {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


# ------------------------------------------------- v7.7: Chrome profile
# The owner's screenshot (2026-11-16 12:01 IST): Nalox opened
# Chrome for a song and stalled at the "Who's using Chrome?"
# profile picker — Chrome was launched with no profile, so
# it asked. The fix: launch Chrome with its LAST-USED
# profile (named in Chrome's own "Local State" file) via
# --profile-directory, so the picker never appears. When
# the last profile cannot be determined, launches behave
# exactly as before (the fallback is today's behaviour,
# never a broken launch).
def _chrome_last_profile(state_path=None):
    """Chrome's last-used profile directory name (e.g.
    "Default" / "Profile 1") from the Local State file, or
    None when it cannot be determined. Pure file reading —
    unit-testable with a fixture path."""
    try:
        if state_path is None:
            base = os.path.expandvars(
                r"%LOCALAPPDATA%\Google\Chrome\User Data")
            state_path = os.path.join(base, "Local State")
        import json
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        profile = (state.get("profile") or {}).get("last_used")
        if not profile or not isinstance(profile, str):
            return None
        profile = profile.strip()
        # A directory NAME, never a path — anything with a
        # separator in it is not a profile name.
        if not profile or "/" in profile or "\\" in profile:
            return None
        return profile
    except Exception:
        return None


def _chrome_exe_path():
    """The chrome.exe path open_app would use, or None."""
    for cand in APP_CANDIDATES.get("chrome", []):
        path = os.path.expandvars(cand)
        try:
            if os.path.isabs(path) and os.path.exists(path):
                return path
            found = shutil.which(path)
            if found:
                return found
        except Exception:
            continue
    return None


def _chrome_command(url=None):
    """The argv for launching Chrome DIRECTLY with its
    last-used profile (v7.7, item F) — [exe,
    --profile-directory=<dir>] plus the URL when given.
    None when the exe or the profile is unknown: callers
    then keep today's launch behaviour unchanged."""
    exe = _chrome_exe_path()
    if not exe:
        return None
    profile = _chrome_last_profile()
    if not profile:
        return None
    argv = [exe, f"--profile-directory={profile}"]
    if url:
        argv.append(url)
    return argv


def _default_browser_is_chrome():
    """True when Chrome is the Windows default browser
    (the http association's ProgId is ChromeHTML…), False
    when another browser is, None when undeterminable
    (off Windows / registry unreadable)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\http\UserChoice")
        try:
            progid, _ = winreg.QueryValueEx(key, "ProgId")
        finally:
            winreg.CloseKey(key)
        return str(progid).startswith("ChromeHTML")
    except Exception:
        return None


# ---------------------------------------------------------------- browser
def open_url(url):
    _step_aside()
    # v7.7 (item F): when Chrome is the default browser and
    # its last-used profile is known, launch Chrome directly
    # with that profile — webbrowser.open() hands Chrome no
    # profile and the "Who's using Chrome?" picker stalls
    # the task (the owner's 2026-11-16 screenshot).
    if _default_browser_is_chrome():
        argv = _chrome_command(url)
        if argv:
            try:
                subprocess.Popen(argv,
                                 **_hidden_console_kwargs())
                _front(process_hints=_BROWSER_PROCS,
                       timeout_s=3.0)
                return url
            except Exception:
                pass  # fall through to today's behaviour
    opened = webbrowser.open(url)  # opens in Arjun's DEFAULT browser
    if opened is not False:
        _front(process_hints=_BROWSER_PROCS, timeout_s=3.0)
    return url


def open_youtube():
    open_url("https://www.youtube.com")
    return "Opening YouTube."


def search_youtube(query):
    from urllib.parse import quote_plus
    open_url("https://www.youtube.com/results?search_query=" + quote_plus(query))
    return f"Searching YouTube for {query}."


def play_on_youtube(query):
    # v5.0: actually PLAY — resolve the first search result and
    # open its WATCH page, so the video starts. The pre-v5.0
    # version only opened the search page (Arjun: "সার্চ করতে
    # পারবে, চালাতে পারবে না"). On any resolution failure the
    # search page opens instead, and the reply says so.
    try:
        import youtube_play
        url = youtube_play.first_video_url(query)
    except Exception:
        url = None
    if url:
        open_url(url)
        return f"Playing {query} on YouTube."
    return search_youtube(query)


def google_search(query):
    from urllib.parse import quote_plus
    open_url("https://www.google.com/search?q=" + quote_plus(query))
    return f"Searching Google for {query}."


WEBSITES = {
    "gmail": "https://mail.google.com",
    "email": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "chatgpt": "https://chat.openai.com",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "youtube studio": "https://studio.youtube.com",
    "studio": "https://studio.youtube.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "maps": "https://maps.google.com",
    "news": "https://news.google.com",
}


def open_website(name):
    url = WEBSITES.get(name.strip().lower())
    if not url:
        # Treat unknown names as <name>.com
        url = "https://" + name.strip().lower().replace(" ", "") + ".com"
    open_url(url)
    return f"Opening {name}."


# ---------------------------------------------------------------- apps
APP_CANDIDATES = {
    "chrome": ["chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "google chrome": ["chrome.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "vscode": ["code", r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe"],
    "vs code": ["code"],
    "visual studio code": ["code"],
    "spotify": ["spotify.exe", os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "paint": ["mspaint.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "task manager": ["taskmgr.exe"],
    "settings": ["ms-settings:"],
    "terminal": ["wt.exe", "cmd.exe"],
    "cmd": ["cmd.exe"],
}


def open_app(name):
    _step_aside()
    key = name.strip().lower()
    candidates = APP_CANDIDATES.get(key)
    if not candidates:
        candidates = [key.replace(" ", "") + ".exe", key]
    for cand in candidates:
        path = os.path.expandvars(cand)
        try:
            # v7.7 (item F): Chrome launches with its
            # last-used profile when known, so the profile
            # picker never stalls the open (os.startfile
            # cannot take arguments, so a known profile
            # means a direct Popen instead).
            if key in ("chrome", "google chrome", "browser"):
                argv = _chrome_command()
                if argv:
                    subprocess.Popen(
                        argv, **_hidden_console_kwargs())
                    _front_app(name)
                    return f"Opening {name}."
            if os.path.isabs(path) and os.path.exists(path):
                os.startfile(path)
                _front_app(name)
                return f"Opening {name}."
            found = shutil.which(path)
            if found:
                subprocess.Popen([found],
                                 **_hidden_console_kwargs())
                _front_app(name)
                return f"Opening {name}."
            if path.endswith(".exe") and not os.path.isabs(path):
                os.startfile(path)  # Windows can resolve many built-ins by name
                _front_app(name)
                return f"Opening {name}."
        except Exception:
            continue
    return f"Sorry, I could not find {name} on this laptop."


# v6.8: the close side of open_app (field 2026-11-15 20:26
# IST: "ক্রোম বন্ধ করো" — a CLOSE command — was answered
# "Opening chrome." and Chrome OPENED, because no close
# path existed at all). Process image names per app;
# taskkill /F ends them, the same full-control rules as
# every other action. Returns "Closing {name}." when at
# least one process was actually ended, else None (the
# caller words the "not open" reply in the right language).
APP_PROCESSES = {
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "browser": ["chrome.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "vscode": ["Code.exe"],
    "vs code": ["Code.exe"],
    "visual studio code": ["Code.exe"],
    "spotify": ["Spotify.exe"],
    "paint": ["mspaint.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "task manager": ["taskmgr.exe"],
    "settings": ["SystemSettings.exe"],
    "terminal": ["WindowsTerminal.exe", "cmd.exe"],
    "cmd": ["cmd.exe"],
}


def close_app(name):
    key = (name or "").strip().lower()
    procs = APP_PROCESSES.get(key)
    if not procs:
        procs = [key.replace(" ", "") + ".exe"]
    closed = False
    for proc in procs:
        try:
            done = subprocess.run(
                ["taskkill", "/IM", proc, "/F"],
                capture_output=True, timeout=10,
                **_hidden_console_kwargs())
            if done.returncode == 0:
                closed = True
        except Exception:
            continue
    if closed:
        return f"Closing {name}."
    return None


# ---------------------------------------------------------------- system
def volume(action):
    if pyautogui is None:
        return "Volume control is not available right now."
    if action == "up":
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume up."
    if action == "down":
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume down."
    if action == "mute":
        pyautogui.press("volumemute")
        return "Muted."
    return "Okay."


def screenshot():
    if pyautogui is None:
        return "Screenshot is not available right now."
    pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(pictures, exist_ok=True)
    name = "nalox_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
    path = os.path.join(pictures, name)
    pyautogui.screenshot().save(path)
    return f"Screenshot saved to your Pictures folder as {name}."


def type_text(text):
    if pyautogui is None:
        return "Typing is not available right now."
    pyautogui.write(text, interval=0.02)
    return "Typed it."


def press_key(key):
    if pyautogui is None:
        return "Keyboard control is not available right now."
    key = key.strip().lower().replace(" ", "")
    aliases = {"return": "enter", "escape": "esc", "spacebar": "space"}
    pyautogui.press(aliases.get(key, key))
    return f"Pressed {key}."


def battery_status():
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is None:
            return "This laptop does not report a battery."
        plugged = "charging" if batt.power_plugged else "not charging"
        return f"Battery is at {int(batt.percent)} percent, {plugged}."
    except Exception:
        return "I could not read the battery status."


def lock_pc():
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Locking your laptop."
    except Exception:
        return "I could not lock the laptop."


def shutdown_pc():
    subprocess.Popen(["shutdown", "/s", "/t", "5"],
                     **_hidden_console_kwargs())
    return "Shutting down. Goodbye!"


def restart_pc():
    subprocess.Popen(["shutdown", "/r", "/t", "5"],
                     **_hidden_console_kwargs())
    return "Restarting your laptop."


def cancel_shutdown():
    subprocess.Popen(["shutdown", "/a"],
                     **_hidden_console_kwargs())


FOLDERS = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}


def open_folder(name):
    _step_aside()
    folder = FOLDERS.get(name.strip().lower())
    if not folder:
        return f"I don't know the folder {name}."
    path = os.path.join(os.path.expanduser("~"), folder)
    if os.path.exists(path):
        os.startfile(path)
        _front(title_hints=(folder,), process_hints=("explorer.exe",))
        return f"Opening your {folder} folder."
    return f"I could not find the {folder} folder."


def open_path(path):
    """Open a file or folder by its full path (v5.8 — the
    custom commands' open_file / open-a-folder-by-path route).
    Returns {"ok": bool, "error": str} like open_this_pc."""
    _step_aside()
    p = os.path.expandvars((path or "").strip().strip('"'))
    if not p or not os.path.exists(p):
        return {"ok": False,
                "error": f"not found: {p}"[:160]}
    try:
        os.startfile(p)
        if os.path.isdir(p):
            _front(title_hints=(os.path.basename(
                       p.rstrip("\\/")),),
                   process_hints=("explorer.exe",))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


# ---------------------------------------------------------------- v5.6 PC chores
# "বললেই করে ফেলে" (say it -> it's done): the deterministic PC
# chores behind brain.py's local chore intents and the agent
# tools of the same names. The owner has given FULL control, so
# these run immediately — no confirmation, no discussion.
# SAFE SCOPE ONLY: the Recycle Bin and the user Temp folder.
# Nothing here ever touches his personal folders or any
# personal file.

def _sh_empty_recycle_bin():
    """SHEmptyRecycleBinW via ctypes — no confirmation dialog,
    no progress UI, no sound. Raises on failure (including off
    Windows, where ctypes.windll does not exist). HRESULT 0 is
    S_OK; 1 is S_FALSE — the bin was already empty, which is
    the goal state anyway."""
    flags = 0x0001 | 0x0002 | 0x0004  # NOCONFIRMATION|NOPROGRESSUI|NOSOUND
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    if hr not in (0, 1):
        raise OSError(
            f"SHEmptyRecycleBinW failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")


def _ps_empty_recycle_bin():
    """PowerShell fallback: Clear-RecycleBin -Force. Raises on
    failure."""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Clear-RecycleBin -Force -ErrorAction Stop"],
        capture_output=True, timeout=60,
        **_hidden_console_kwargs())
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace")
        raise OSError("Clear-RecycleBin failed: " + detail.strip()[:200])


def empty_recycle_bin():
    """Empty the Recycle Bin right now. Returns a result dict:
    {"ok": bool, "via": "shell32"|"powershell"|""}."""
    try:
        _sh_empty_recycle_bin()
        return {"ok": True, "via": "shell32"}
    except Exception:
        pass
    try:
        _ps_empty_recycle_bin()
        return {"ok": True, "via": "powershell"}
    except Exception as exc:
        return {"ok": False, "via": "", "error": str(exc)[:160]}


def _open_shell_location(location):
    """Open a shell: location in Explorer. Raises on failure
    (os.startfile is Windows-only; explorer.exe is the fallback
    and raises FileNotFoundError anywhere else)."""
    try:
        os.startfile(location)
        return
    except Exception:
        pass
    subprocess.Popen(["explorer.exe", location],
                     **_hidden_console_kwargs())


def open_this_pc():
    """Open 'This PC' (My Computer) in File Explorer."""
    _step_aside()
    try:
        _open_shell_location("shell:MyComputerFolder")
        _front(title_hints=("This PC",),
               process_hints=("explorer.exe",))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def open_recycle_bin():
    """Open the Recycle Bin window (NOT empty it)."""
    _step_aside()
    try:
        _open_shell_location("shell:RecycleBinFolder")
        _front(title_hints=("Recycle Bin",),
               process_hints=("explorer.exe",))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def _temp_dir():
    """The user Temp folder (%TEMP% on Windows)."""
    return tempfile.gettempdir()


def _clear_folder_contents(path):
    """Delete the CONTENTS of path — never path itself, and
    never anything outside it: scandir yields only direct
    children, and a lexical containment check runs before any
    delete. Locked / in-use entries are skipped silently.
    Returns (entries_deleted, bytes_freed)."""
    freed = 0
    count = 0
    base = os.path.abspath(path)
    try:
        entries = list(os.scandir(base))
    except Exception:
        return 0, 0
    for entry in entries:
        try:
            if os.path.dirname(os.path.abspath(entry.path)) != base:
                continue  # paranoia: not a direct child — hands off
            if entry.is_dir(follow_symlinks=False):
                size = 0
                for root, _dirs, files in os.walk(entry.path):
                    for fname in files:
                        try:
                            size += os.path.getsize(
                                os.path.join(root, fname))
                        except Exception:
                            pass
                shutil.rmtree(entry.path, ignore_errors=True)
                if not os.path.exists(entry.path):
                    count += 1
                    freed += size
            else:
                # files AND symlinks land here: removing a link
                # removes the link, never its target
                size = entry.stat(follow_symlinks=False).st_size
                os.remove(entry.path)
                count += 1
                freed += size
        except Exception:
            continue  # locked / in use — skip silently
    return count, freed


def pc_quick_clean():
    """Quick PC clean (v5.6): empty the Recycle Bin + clear the
    user Temp folder's contents. That is the WHOLE scope — no
    personal folder is ever touched. Returns a result dict:
    {"bin_ok": bool, "temp_files": int, "temp_mb": float}."""
    bin_res = empty_recycle_bin()
    count, freed = _clear_folder_contents(_temp_dir())
    return {"bin_ok": bool(bin_res.get("ok")),
            "temp_files": count,
            "temp_mb": round(freed / (1024 * 1024), 1)}
