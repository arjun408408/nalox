"""Supervisor: keeps Nalox alive.

Launches nalox.py with pythonw (no console). If Nalox crashes, wait 5 s
and relaunch. If Nalox exits with code 42 (tray 'Exit' or a confirmed
PC shutdown), do NOT relaunch — that was a clean, requested exit.
(v5.4: a voice/Telegram 'stop' no longer exits at all — it is
standby; see brain.py.)

v4.7 ALWAYS-ON: a deliberate exit (tray "Exit Nalox" / the app's
"Exit Nalox" button) ALSO writes exit_requested.flag
next to nalox.py. If that flag exists when nalox.py ends — whatever
the exit code — the supervisor does NOT relaunch. The flag is
removed by nalox.py itself on its next (manual) launch. Restarts
(exit code 1) never write the flag, so they always relaunch.

v6.0: the flag is a ONE-SHOT signal — when this supervisor
honours a deliberate exit it DELETES the flag (consumes it),
so it can never outlive the exit it described. And the
single-instance claim in nalox.py is now an OS-held lock
(the v4.7 PID-in-a-file + liveness guess let a crashed
child's lingering/reused PID veto every later launch with
a silent code 42 — the 2026-11-15 boot deaths); duplicate
launches exit 43 and are stopped for quietly. This
supervisor also claims its own OS lock (supervisor.lock):
a second supervisor stands down instead of spawning a
competing child.

v5.2: every child death + relaunch is ALSO mirrored into the
main diagnostics logbook (nalox_log.txt / nalox_page.html) with
the exit code interpreted — a native-crash NTSTATUS code names
itself on the page Arjun screenshots, instead of a silent gap.
Clean exits get a marker line in nalox_fault.log from here too
(tray/HUD exits never pass through nalox.py's marker writer).

v6.1: exit code 0 is a RESTART, not a death. The deliberate
restart paths that use it (Settings "Save & Restart", the
app-window Restart fallback) now log their own
"[sys] exiting (restart): <reason>" line before exiting —
and this supervisor reports code 0 in kind ("exited
(code 0) — a restart-style exit, relaunching"), instead of
the alarming "Nalox process DIED (exit code 0)" the field
log showed on 2026-11-15 16:02, ~35 s after the phone app
paired, when nothing had actually died.
"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "nalox.log")
CLEAN_EXIT_CODE = 42
# v6.0: nalox.py exits 43 when a launch finds a live Nalox
# already running (single-instance OS lock held). That is
# NOT a deliberate exit and NOT a crash: this supervisor
# stops quietly — another supervisor owns the running
# instance.
ALREADY_RUNNING_CODE = 43
EXIT_FLAG_FILE = os.path.join(BASE_DIR, "exit_requested.flag")
SUPERVISOR_LOCK_FILE = os.path.join(BASE_DIR, "supervisor.lock")
_supervisor_lock_handle = None


def _claim_supervisor_lock():
    """v6.0: ONE supervisor per install. The claim is an
    OS-held exclusive lock on supervisor.lock — released by
    the kernel the moment the holding supervisor dies,
    however it dies, so it can never go stale and veto a
    later start (the v5.8 stacked-supervisor mess: several
    supervisors spawning children that fought over the
    single-instance lock and spammed the log page with
    duplicate code-42 lines). True = this supervisor runs;
    False = another live supervisor already owns Nalox.
    Any machinery failure returns True — supervision must
    never be the reason Nalox doesn't start."""
    global _supervisor_lock_handle
    try:
        fh = open(SUPERVISOR_LOCK_FILE, "a+")
    except Exception:
        return True
    try:
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            try:
                fh.close()
            except Exception:
                pass
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        _supervisor_lock_handle = fh
        return True
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        return True


def _consume_exit_flag():
    """v6.0: a deliberate exit is honoured ONCE. When the
    supervisor stops for a deliberate exit (code 42 or the
    flag), it DELETES exit_requested.flag — the flag is a
    one-shot signal about the child that just ended, never
    a standing veto over future launches. (nalox.py also
    clears any stale flag at every boot; between the two,
    the flag can never outlive the exit it described.)"""
    try:
        if os.path.exists(EXIT_FLAG_FILE):
            os.remove(EXIT_FLAG_FILE)
            _log("Consumed the deliberate-exit flag (honoured once).")
    except Exception:
        pass


def _log(msg):
    line = f"[supervisor] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _logbook(category, msg):
    """Mirror one line into the MAIN diagnostics logbook
    (nalox_log.txt + nalox_page.html — the page Arjun
    screenshots). v5.2: a child death used to be visible only
    in this supervisor's own side log, so the page showed a
    silent gap and a fresh boot; now the death itself is on
    the page, with the exit code. Guarded: logging must never
    stop the supervisor supervising."""
    try:
        import logbook
        logbook.log(category, "[supervisor] " + msg)
    except Exception:
        pass


def _mark_fault_log(text):
    """Append a marker to nalox_fault.log (the faulthandler
    file) — used for supervisor-observed CLEAN exits, which
    include tray/HUD exits that never pass through nalox.py's
    own marker writer."""
    try:
        with open(os.path.join(BASE_DIR, "nalox_fault.log"), "a",
                  encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


# Windows NTSTATUS exit codes that mean "the process died in
# native code" — the v5.1 silent deaths should surface as one
# of these, and naming it on the log page turns a mystery into
# a diagnosis.
_NTSTATUS = {
    0xC0000005: "ACCESS VIOLATION — native crash (bad memory "
                "access in C code; see nalox_fault.log)",
    0xC0000409: "STACK BUFFER OVERRUN / abort — native crash "
                "(see nalox_fault.log)",
    0xC000001D: "ILLEGAL INSTRUCTION — native crash",
    0xC0000094: "INTEGER DIVIDE BY ZERO in native code",
    0xC0000374: "HEAP CORRUPTION — native crash",
}


def _describe_code(code):
    """Human meaning of a child exit code, for the log page."""
    try:
        masked = int(code) & 0xFFFFFFFF
    except Exception:
        return f"exit code {code}"
    if masked in _NTSTATUS:
        return f"exit code {code} (0x{masked:08X}): {_NTSTATUS[masked]}"
    return f"exit code {code}"


def pythonw_path():
    exe = sys.executable
    candidate = exe.replace("python.exe", "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    return exe


def main():
    if not _claim_supervisor_lock():
        _log("Another supervisor is already running — standing down.")
        _logbook("SYSTEM", "[supervisor] another supervisor is "
                           "already running — this one is standing "
                           "down (one supervisor per install).")
        return
    _log("Supervisor started.")
    while True:
        try:
            proc = subprocess.Popen(
                [pythonw_path(), os.path.join(BASE_DIR, "nalox.py")],
                cwd=BASE_DIR,
            )
            code = proc.wait()
        except Exception as exc:
            _log(f"Failed to launch nalox.py: {exc}")
            code = -1
        if code == CLEAN_EXIT_CODE:
            _log("Nalox exited cleanly (code 42). Supervisor stopping.")
            _logbook("SYSTEM", "Nalox exited cleanly (code 42) — "
                               "deliberate exit, supervisor stopping.")
            _mark_fault_log(
                f"===== CLEAN EXIT {time.strftime('%Y-%m-%d %H:%M:%S')}"
                " — supervisor saw code 42 =====")
            _consume_exit_flag()
            return
        if code == ALREADY_RUNNING_CODE:
            _log("Nalox launch found a live instance already "
                 "running (code 43). Supervisor stopping.")
            _logbook("SYSTEM", "A Nalox instance is already "
                               "running — this launch closed "
                               "(code 43), supervisor stopping.")
            _mark_fault_log(
                f"===== CLEAN EXIT {time.strftime('%Y-%m-%d %H:%M:%S')}"
                " — supervisor saw code 43 (already running) =====")
            return
        if os.path.exists(EXIT_FLAG_FILE):
            _log("Deliberate exit flag found — not relaunching. "
                 "Supervisor stopping.")
            _logbook("SYSTEM", "Deliberate exit (flag) — supervisor "
                               "stopping, not relaunching.")
            _mark_fault_log(
                f"===== CLEAN EXIT {time.strftime('%Y-%m-%d %H:%M:%S')}"
                " — supervisor saw the deliberate-exit flag =====")
            _consume_exit_flag()
            return
        if code == 0:
            # v6.1: a restart-style exit (Settings "Save &
            # Restart" / the app-window Restart fallback) —
            # the child logged its own "[sys] exiting
            # (restart)" reason; report it as what it is,
            # not as a death, and relaunch as always.
            _log("Nalox exited with code 0 (restart-style "
                 "exit); relaunching in 5 seconds...")
            _logbook("SYSTEM", "Nalox exited (code 0) — a "
                               "restart-style exit, "
                               "relaunching in 5 seconds.")
            time.sleep(5)
            continue
        _log(f"Nalox exited with code {code}; relaunching in 5 seconds...")
        _logbook("ERROR", f"Nalox process DIED ({_describe_code(code)})"
                          " — relaunching in 5 seconds. A traceback "
                          "in nalox_fault.log, if present, names the "
                          "native fault.")
        time.sleep(5)


if __name__ == "__main__":
    main()
