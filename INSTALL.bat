@echo off
REM ============================================================
REM  Nalox - one-time installer. Run this ONCE.
REM  Future versions arrive as small UPDATE packs - you will
REM  NOT need to run this full install again.
REM
REM  IMPORTANT: Nalox needs Python 3.12 (or 3.11 / 3.13).
REM  Python 3.14 / 3.15 are too new - the voice packages have
REM  no ready-made wheels for them yet, so install would fail.
REM ============================================================
cd /d "%~dp0"
title Nalox Installer

echo.
echo  ==========================================
echo    Installing Nalox - please wait...
echo    First install downloads a lot, be patient.
echo  ==========================================
echo.

REM --- pick a SUPPORTED Python: 3.12 first, then 3.11, then 3.13 ---
set "PYCMD="
py -3.12 --version >nul 2>&1 && set "PYCMD=py -3.12"
if defined PYCMD goto pyfound
py -3.11 --version >nul 2>&1 && set "PYCMD=py -3.11"
if defined PYCMD goto pyfound
py -3.13 --version >nul 2>&1 && set "PYCMD=py -3.13"
if defined PYCMD goto pyfound
goto nopython

:nopython
echo.
echo  ==========================================================
echo    PYTHON VERSION PROBLEM - please read!
echo  ==========================================================
echo    Nalox needs Python 3.12, but this PC only has a newer
echo    Python - 3.14 or 3.15. The voice packages Nalox uses
echo    do not exist yet for those versions, so installing
echo    with them ALWAYS fails. That is what happened before.
echo.
echo    FIX - 2 minutes, one time only:
echo    1. Go to https://www.python.org/downloads/
echo    2. Download and install Python 3.12 for Windows.
echo       Keep your current Python too - they live together fine.
echo    3. During install, TICK "Add python.exe to PATH".
echo    4. Run INSTALL.bat again - it picks 3.12 by itself.
echo  ==========================================================
echo.
pause
exit /b 1

:pyfound
echo  Using Python: %PYCMD%
%PYCMD% --version

REM --- fresh venv if the previous install never finished ---
if not exist ".venv\Scripts\python.exe" goto makevenv
if exist ".venv\.nalox_install_ok" goto venvready
echo  Removing the unfinished environment from the last try...
rmdir /s /q ".venv"

:makevenv
echo  Creating Nalox environment...
%PYCMD% -m venv .venv

:venvready
echo  Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo  Installing Nalox packages - this can take a few minutes...
".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
if not errorlevel 1 goto pipok
echo.
echo  Retrying once...
".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
if not errorlevel 1 goto pipok
echo.
echo  ERROR: package install failed. Check your internet and
echo  run INSTALL.bat again. If it keeps failing, send Muse
echo  a screenshot of this window.
pause
exit /b 1

:pipok
echo ok> ".venv\.nalox_install_ok"
".venv\Scripts\python.exe" -c "import hashlib,pathlib; pathlib.Path(r'.venv\.nalox_req_hash').write_text(hashlib.md5(pathlib.Path('requirements.txt').read_bytes()).hexdigest())"

echo  Adding Nalox to Windows Startup...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup\Nalox.lnk')); $lnk.TargetPath = [IO.Path]::Combine('%~dp0', 'start_nalox.vbs'); $lnk.WorkingDirectory = '%~dp0'; $lnk.Description = 'Nalox voice assistant'; $lnk.Save()"

echo.
echo  ==========================================
echo    Nalox is installed!
echo    Starting Nalox now... say "Nalox" to test.
echo    From now on Nalox starts automatically
echo    every time you log in to Windows.
echo    Future updates: just run UPDATE.bat from
echo    the update pack Muse sends - no reinstall!
echo  ==========================================
echo.

start "" wscript.exe "%~dp0start_nalox.vbs"
pause
