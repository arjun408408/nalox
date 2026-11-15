"""Split-screen window layout (v5.1) — stdlib ctypes only.

From the IRIS demo Arjun sent (2026-11-15): "WhatsApp on the
left, Chrome on the right" — the assistant arranged two apps
side by side in one command. Nalox gets the same ability with
nothing but ctypes + user32:

    work_area()    — the desktop work area (screen minus the
                     taskbar) via SystemParametersInfoW.
    half_rects()   — pure math: split a work area into its
                     exact left / right halves.
    find_window()  — EnumWindows hunt for a top-level window by
                     title substring and/or owning process name.
    snap_window()  — restore-if-minimised (ShowWindow
                     SW_RESTORE) + SetWindowPos to one half.
    snap_active()  — snap the foreground window.
    snap_app()     — poll find_window() for a few seconds (a
                     just-launched app needs a moment to create
                     its window), then snap it.

GOLDEN RULE (the doctor's rule, applied to windows): every
ctypes call is wrapped — any failure returns False / None with
a log line. This module never raises into the brain, and on a
non-Windows system every entry point simply reports failure,
so Nalox stays importable and testable anywhere.

v5.2 CRASH AUDIT — the signatures below are now FULLY declared,
and this matters: ctypes' default restype is c_int, so an
undeclared OpenProcess returned its 64-bit HANDLE truncated to
32 bits, and that truncated value was then handed to
QueryFullProcessImageNameW and CloseHandle. On a good day the
handle was simply invalid (process-name matching silently never
worked); on a bad day the truncated value could collide with a
handle Nalox itself owns and CloseHandle would close it from
under the app. Every user32/kernel32 call this module makes now
has explicit argtypes/restype with pointer-sized (c_void_p)
handle types — the EnumWindows callback was already correct
(WINFUNCTYPE c_bool/c_void_p/c_void_p) and stays that way.
"""
import ctypes
import logging
import time

log = logging.getLogger("nalox.winlayout")

SPI_GETWORKAREA = 0x0030        # SystemParametersInfoW action
SW_RESTORE = 9                  # ShowWindow: un-minimise
SWP_NOZORDER = 0x0004           # SetWindowPos: keep z-order
SWP_NOACTIVATE = 0x0010         # SetWindowPos: don't steal focus
SWP_NOMOVE = 0x0002             # SetWindowPos: keep position
SWP_NOSIZE = 0x0001             # SetWindowPos: keep size
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _hwnd_const(value):
    """A signed HWND constant (HWND_TOPMOST=-1, HWND_NOTOPMOST
    =-2) as a c_void_p — ctypes masks the negative value to
    pointer width; the fallback spells it out."""
    try:
        return ctypes.c_void_p(value)
    except Exception:
        return ctypes.c_void_p(value & 0xFFFFFFFFFFFFFFFF)


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _user32():
    """ctypes.windll.user32, or None off Windows / on failure."""
    try:
        return ctypes.windll.user32
    except Exception:
        return None


def _kernel32():
    """ctypes.windll.kernel32, or None off Windows / on failure."""
    try:
        return ctypes.windll.kernel32
    except Exception:
        return None


def _setup_prototypes(u):
    """Pointer-safe signatures for EVERY call this module makes
    (v5.2 audit — see the module docstring). HWNDs and HANDLEs
    are c_void_p (pointer-sized on 64-bit Windows); an omitted
    restype would silently truncate them to c_int."""
    try:
        u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int,
                                   ctypes.c_uint]
        u.SetWindowPos.restype = ctypes.c_bool
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.ShowWindow.restype = ctypes.c_bool
        u.IsIconic.argtypes = [ctypes.c_void_p]
        u.IsIconic.restype = ctypes.c_bool
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u.IsWindowVisible.restype = ctypes.c_bool
        u.GetWindowTextW.argtypes = [ctypes.c_void_p,
                                     ctypes.c_wchar_p, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        u.GetWindowThreadProcessId.restype = ctypes.c_ulong
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = ctypes.c_void_p
        # v5.7 foreground dance: SetForegroundWindow alone is
        # refused when another process owns the foreground, so
        # the standard workaround attaches this thread's input
        # queue to the foreground + target threads first.
        u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        u.SetForegroundWindow.restype = ctypes.c_bool
        u.BringWindowToTop.argtypes = [ctypes.c_void_p]
        u.BringWindowToTop.restype = ctypes.c_bool
        u.AttachThreadInput.argtypes = [ctypes.c_ulong,
                                        ctypes.c_ulong,
                                        ctypes.c_bool]
        u.AttachThreadInput.restype = ctypes.c_bool
        u.SystemParametersInfoW.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
            ctypes.c_uint]
        u.SystemParametersInfoW.restype = ctypes.c_bool
        # EnumWindows' first argument is the callback itself;
        # its type is built per-call in find_window (WINFUNCTYPE
        # c_bool/c_void_p/c_void_p), so the prototype uses the
        # generic callable-sized c_void_p-compatible slot via a
        # CFUNCTYPE instance — ctypes accepts the callback object
        # for a c_void_p argtype only by address, so EnumWindows
        # is deliberately left to receive the callback object
        # directly (ctypes converts a callback argument without
        # argtypes). Only its restype is pinned.
        u.EnumWindows.restype = ctypes.c_bool
    except Exception:
        pass  # loose defaults still work for the common cases
    k = _kernel32()
    if k is not None:
        try:
            k.OpenProcess.argtypes = [ctypes.c_ulong,
                                      ctypes.c_bool,
                                      ctypes.c_ulong]
            k.OpenProcess.restype = ctypes.c_void_p
            k.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_ulong)]
            k.QueryFullProcessImageNameW.restype = ctypes.c_bool
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.CloseHandle.restype = ctypes.c_bool
            # v5.7: the foreground dance needs this thread's id.
            k.GetCurrentThreadId.argtypes = []
            k.GetCurrentThreadId.restype = ctypes.c_ulong
        except Exception:
            pass


# ------------------------------------------------------------ geometry
def work_area():
    """(x, y, width, height) of the Windows work area, or None."""
    u = _user32()
    if u is None:
        return None
    try:
        _setup_prototypes(u)
        rect = _RECT()
        if not u.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                       ctypes.byref(rect), 0):
            log.warning("winlayout: SystemParametersInfoW failed")
            return None
        return (rect.left, rect.top,
                rect.right - rect.left, rect.bottom - rect.top)
    except Exception as exc:
        log.warning("winlayout: work area failed: %s", exc)
        return None


def half_rects(work):
    """Split a work-area rect into (left, right) halves.

    Pure math, no OS calls: (0, 0, 1920, 1040) ->
    left (0, 0, 960, 1040), right (960, 0, 960, 1040). An odd
    width gives the right half the spare pixel."""
    x, y, w, h = work
    lw = w // 2
    return (x, y, lw, h), (x + lw, y, w - lw, h)


def rect_for_side(side, work=None):
    """The (x, y, w, h) rect for "left" / "right", or None."""
    if work is None:
        work = work_area()
    if work is None:
        return None
    left, right = half_rects(work)
    return left if str(side).lower() == "left" else right


# ------------------------------------------------------------ finding
def _process_name(u, hwnd):
    """Owning process image name (e.g. 'chrome.exe'), or ''."""
    try:
        pid = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.replace("/", "\\").split("\\")[-1]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def _window_title(u, hwnd):
    try:
        length = u.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def find_window(title_hints=(), process_hints=()):
    """HWND of the first visible top-level window matching any
    title substring (case-insensitive) or owning-process name.

    Matching is deliberately conservative — a window matches
    only on the hints the caller supplied (the app's known
    title/process identity), never on a guess, so Nalox snaps
    the RIGHT window or honestly reports none found."""
    u = _user32()
    if u is None:
        return None
    titles = [str(t).strip().lower() for t in title_hints or ()
              if str(t).strip()]
    procs = [str(p).strip().lower() for p in process_hints or ()
             if str(p).strip()]
    if not titles and not procs:
        return None
    _setup_prototypes(u)
    try:
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    except AttributeError:  # not Windows — EnumWindows unused
        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found = []

    def _enum(hwnd, _lparam):
        try:
            if found:
                return False
            if not u.IsWindowVisible(hwnd):
                return True
            if titles:
                title = _window_title(u, hwnd).lower()
                if title and any(h in title for h in titles):
                    found.append(hwnd)
                    return False
            if procs:
                name = _process_name(u, hwnd).lower()
                if name and name in procs:
                    found.append(hwnd)
                    return False
        except Exception:
            pass
        return True

    try:
        u.EnumWindows(callback_type(_enum), 0)
    except Exception as exc:
        log.warning("winlayout: EnumWindows failed: %s", exc)
        return None
    return found[0] if found else None


# ------------------------------------------------------------ snapping
def snap_window(hwnd, side):
    """Move one window to the left / right half of the work
    area. True on success; False (with a log line) on any
    failure — never raises."""
    u = _user32()
    if u is None or not hwnd:
        return False
    rect = rect_for_side(side)
    if rect is None:
        log.warning("winlayout: no work area — cannot snap")
        return False
    x, y, w, h = rect
    try:
        _setup_prototypes(u)
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        ok = u.SetWindowPos(hwnd, None, x, y, w, h,
                            SWP_NOZORDER | SWP_NOACTIVATE)
        if not ok:
            log.warning("winlayout: SetWindowPos failed for "
                        "hwnd %s", hwnd)
        return bool(ok)
    except Exception as exc:
        log.warning("winlayout: snap failed: %s", exc)
        return False


def snap_active(side):
    """Snap the FOREGROUND window ("put this on the left")."""
    u = _user32()
    if u is None:
        return False
    try:
        _setup_prototypes(u)
        hwnd = u.GetForegroundWindow()
    except Exception as exc:
        log.warning("winlayout: foreground window failed: %s", exc)
        return False
    if not hwnd:
        log.info("winlayout: no foreground window to snap")
        return False
    return snap_window(hwnd, side)


def snap_app(name, side, title_hints=(), process_hints=(),
             wait_s=6.0):
    """Snap an app's window, waiting up to wait_s for the window
    to appear (a just-opened app needs a moment). False when no
    matching window shows up — the caller says so honestly and
    leaves the app open."""
    deadline = time.monotonic() + max(0.0, float(wait_s))
    while True:
        hwnd = find_window(title_hints, process_hints)
        if hwnd:
            return snap_window(hwnd, side)
        if time.monotonic() >= deadline:
            log.info("winlayout: no window found for %r — "
                     "leaving it open, unsnapped", name)
            return False
        time.sleep(0.4)


# ------------------------------------------------------------ foreground (v5.7)
# The owner's complaint (2026-11-15 14:38): "আমি যদি বলি ওপেন
# ক্রোম, তো ক্রোমটা আমার স্ক্রিনে ওপেন করবে — কেন ও পিছনে
# ওপেন করে?" Apps Nalox opened appeared BEHIND the Nalox
# window (which sat topmost) / behind the Command Center.
# So an open is not done when the process starts — it is done
# when its window is IN FRONT. Windows refuses a bare
# SetForegroundWindow from a background process, hence the
# standard dance: attach this thread's input queue to the
# foreground window's thread and the target's thread, then
# BringWindowToTop + SetForegroundWindow, then detach. The
# topmost toggle is the fallback when even that is refused.

def foreground_window(hwnd):
    """Bring one window to the front and give it focus.
    True on success; False (with a log line) on any failure —
    never raises."""
    u = _user32()
    if u is None or not hwnd:
        return False
    k = _kernel32()
    try:
        _setup_prototypes(u)
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        if u.GetForegroundWindow() == hwnd:
            return True
        cur = 0
        if k is not None:
            try:
                cur = k.GetCurrentThreadId()
            except Exception:
                cur = 0
        attached = []
        threads = set()
        fg = u.GetForegroundWindow()
        if fg:
            try:
                t_fg = u.GetWindowThreadProcessId(fg, None)
                if t_fg:
                    threads.add(t_fg)
            except Exception:
                pass
        try:
            t_tgt = u.GetWindowThreadProcessId(hwnd, None)
            if t_tgt:
                threads.add(t_tgt)
        except Exception:
            pass
        for th in threads:
            if cur and th != cur:
                try:
                    if u.AttachThreadInput(cur, th, True):
                        attached.append(th)
                except Exception:
                    pass
        ok = False
        try:
            try:
                u.BringWindowToTop(hwnd)
            except Exception:
                pass
            ok = bool(u.SetForegroundWindow(hwnd))
        finally:
            for th in attached:
                try:
                    u.AttachThreadInput(cur, th, False)
                except Exception:
                    pass
        if not ok:
            # Fallback: raise via the topmost toggle — set
            # topmost, then release it; the window ends up in
            # front WITHOUT staying topmost.
            try:
                flags = SWP_NOMOVE | SWP_NOSIZE
                u.SetWindowPos(hwnd, _hwnd_const(-1), 0, 0, 0, 0,
                               flags)
                u.SetWindowPos(hwnd, _hwnd_const(-2), 0, 0, 0, 0,
                               flags)
                ok = True
            except Exception:
                pass
        try:
            if u.GetForegroundWindow() == hwnd:
                ok = True
        except Exception:
            pass
        if not ok:
            log.info("winlayout: could not foreground hwnd %s",
                     hwnd)
        return bool(ok)
    except Exception as exc:
        log.warning("winlayout: foreground failed: %s", exc)
        return False


def foreground_app(title_hints=(), process_hints=(),
                   timeout_s=2.0):
    """Poll for a just-opened app's window (it needs a moment
    to appear) and bring it to the FRONT. True when the window
    ended up in front; False when none showed up in time —
    the app is still open, just not fronted. Never raises."""
    if _user32() is None:
        return False
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        hwnd = find_window(title_hints, process_hints)
        if hwnd and foreground_window(hwnd):
            return True
        if time.monotonic() >= deadline:
            if hwnd:
                log.info("winlayout: window %s found but "
                         "foreground refused", hwnd)
            else:
                log.info("winlayout: no window to foreground "
                         "for %r / %r", title_hints, process_hints)
            return False
        time.sleep(0.15)
