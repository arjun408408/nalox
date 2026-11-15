"""Create the Nalox Desktop + Start Menu shortcuts (v4.7).

Run by UPDATE.bat after the file copy (and safe to run by hand).
The shortcut MIRRORS the autostart entry exactly: the target is
start_nalox.vbs in the install folder (the very launcher the
Startup folder's Nalox.lnk points at — it starts supervisor.py
with the venv pythonw, which starts nalox.py), the working
directory is the install folder, and the icon is
assets/logo.ico.

So one click on the shortcut starts Nalox when it is not
running — and, thanks to the single-instance lock in nalox.py,
brings the running window forward when it already is: the
shortcut doubles as the "bring Nalox back" button. Pinning to
the taskbar stays one manual right-click ("Pin to taskbar") —
Windows does not allow programs to pin themselves.

Windows implementation: the .lnk files are written through the
WScript.Shell COM object from a generated PowerShell script
(the same mechanism settings_ui uses for the autostart entry).
--dry-run prints the resolved target/icon/link paths and writes
nothing (works on any platform, used by the build tests).

Failure isolation: ANY failure prints a line and exits 0 — an
icon must never break an update.
"""
import os
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _desktop_dir():
    try:
        return os.path.join(os.path.expanduser("~"), "Desktop")
    except Exception:
        return "Desktop"


def _programs_dir():
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        return os.path.join(appdata, "Microsoft", "Windows",
                            "Start Menu", "Programs")
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                        "Microsoft", "Windows", "Start Menu",
                        "Programs")


def shortcut_paths():
    """(target, icon, workdir, [link paths]) — pure, testable."""
    target = os.path.join(BASE_DIR, "start_nalox.vbs")
    icon = os.path.join(BASE_DIR, "assets", "logo.ico")
    links = [os.path.join(_desktop_dir(), "Nalox.lnk"),
             os.path.join(_programs_dir(), "Nalox.lnk")]
    return target, icon, BASE_DIR, links


_PS1 = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($link in @(__LINKS__)) {
    $dir = Split-Path $link
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $sc = $shell.CreateShortcut($link)
    $sc.TargetPath = '__TARGET__'
    $sc.WorkingDirectory = '__WORKDIR__'
    $sc.IconLocation = '__ICON__'
    $sc.Description = 'Nalox - your personal assistant'
    $sc.Save()
    Write-Host "created: $link"
}
"""


def _ps_single(value):
    """Escape a string for a PowerShell single-quoted literal."""
    return str(value).replace("'", "''")


def _ps_quote(value):
    return "'" + _ps_single(value) + "'"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    target, icon, workdir, links = shortcut_paths()
    if "--dry-run" in argv:
        print("create_shortcut (dry run) - nothing will be written")
        print("  target : " + target)
        print("  icon   : " + icon)
        print("  workdir: " + workdir)
        for link in links:
            print("  link   : " + link)
        return 0
    if not sys.platform.startswith("win"):
        print("create_shortcut: not Windows - shortcuts skipped.")
        return 0
    try:
        ps1 = (_PS1
               .replace("__LINKS__",
                        ", ".join(_ps_quote(p) for p in links))
               .replace("__TARGET__", _ps_single(target))
               .replace("__WORKDIR__", _ps_single(workdir))
               .replace("__ICON__", _ps_single(icon)))
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".ps1",
                                       prefix="nalox_shortcut_")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(ps1)
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy",
                 "Bypass", "-File", tmp],
                capture_output=True, text=True, timeout=60)
            out = (proc.stdout or "") + (proc.stderr or "")
            for line in out.splitlines():
                if line.strip():
                    print("create_shortcut: " + line.strip())
            if proc.returncode != 0:
                print("create_shortcut: PowerShell exited with "
                      f"{proc.returncode} - shortcuts not created "
                      "(Nalox itself is unaffected).")
                return 0
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        print("create_shortcut: Desktop + Start Menu shortcuts "
              "created (icon: assets/logo.ico).")
        return 0
    except Exception as exc:
        print(f"create_shortcut: failed ({exc}) - continuing anyway.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
