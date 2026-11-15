@echo off
REM ============================================================
REM  Nalox UPDATE v6.6 - one click, NO reinstall.
REM  This pack can be unzipped ANYWHERE. UPDATE.bat finds the
REM  real Nalox install by itself: the real install is the
REM  folder that contains .venv\Scripts\python.exe - and the
REM  pack never has one. It then stops Nalox, backs up the old
REM  code, copies the new code, patches config.json safely
REM  (your API keys are kept), installs packages ONLY if
REM  requirements.txt changed, and restarts Nalox, which
REM  announces the update out loud.
REM ============================================================
cd /d "%~dp0"
title Nalox Update v6.6

echo.
echo  ==========================================
echo    Nalox update v7.0
echo  ==========================================
echo.

for %%I in ("%~dp0.") do set "PACKDIR=%%~fI"
set "TARGET="

REM --- Step 1: is this pack already inside the real install? ---
if exist "%~dp0.venv\Scripts\python.exe" goto selftarget
goto search

:selftarget
set "TARGET=%PACKDIR%"
goto verify

REM --- Step 2: search the usual places for the real install ---
:search
echo  Looking for your Nalox install...
set "TARGETFILE=%TEMP%\nalox_target.txt"
if exist "%TARGETFILE%" del "%TARGETFILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots = @($env:USERPROFILE, (Join-Path $env:USERPROFILE 'Downloads'), (Join-Path $env:USERPROFILE 'Desktop'), (Join-Path $env:USERPROFILE 'Documents'), (Join-Path $env:USERPROFILE 'OneDrive'), (Join-Path $env:USERPROFILE 'OneDrive\Documents')); $found = $null; foreach ($r in $roots) { if ($found) { break }; if (-not (Test-Path $r)) { continue }; $hits = Get-ChildItem -Path $r -Filter 'nalox.py' -Recurse -Depth 3 -File -ErrorAction SilentlyContinue; foreach ($h in $hits) { if (Test-Path (Join-Path $h.DirectoryName '.venv\Scripts\python.exe')) { $found = $h.DirectoryName; break } } }; if ($found) { Set-Content -Path $env:TARGETFILE -Value $found -Encoding ASCII }"
if not exist "%TARGETFILE%" goto notfound
set /p TARGET=<"%TARGETFILE%"
if "%TARGET%"=="" goto notfound
goto verify

:notfound
echo.
echo  ==========================================================
echo    Nalox install folder not found.
echo    Copy this pack's files into your Nalox folder and
echo    run UPDATE.bat from there.
echo  ==========================================================
echo.
pause
exit /b 1

REM --- Step 3: verify the target really is a working install ---
:verify
if not exist "%TARGET%\.venv\Scripts\python.exe" goto notfound
if exist "%TARGET%\start_nalox.vbs" goto found
echo.
echo  ==========================================================
echo    Found a Nalox folder at:
echo    %TARGET%
echo    but start_nalox.vbs is missing there, so Nalox could
echo    not be restarted after the update. Nothing was changed.
echo    Copy this pack's files into your Nalox folder and
echo    run UPDATE.bat from there.
echo  ==========================================================
echo.
pause
exit /b 1

:found
echo  Nalox found in: %TARGET%
echo.

echo  Stopping Nalox...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*supervisor.py*' -or $_.CommandLine -like '*nalox.py*') -and (($_.ExecutablePath -like ($env:TARGET + '*')) -or ($_.CommandLine -like ('*' + $env:TARGET + '*'))) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
REM --- v6.0: an update is an explicit RUN-IT act. Clear any stale
REM --- exit/lock state so the fresh start can never be vetoed.
if exist "%TARGET%\exit_requested.flag" del "%TARGET%\exit_requested.flag"
if exist "%TARGET%\show_request.flag" del "%TARGET%\show_request.flag"
if exist "%TARGET%\nalox.lock" del "%TARGET%\nalox.lock"
if exist "%TARGET%\supervisor.lock" del "%TARGET%\supervisor.lock"

echo  Backing up current code to backup_update...
if not exist "%TARGET%\backup_update" mkdir "%TARGET%\backup_update"
copy /y "%TARGET%\*.py" "%TARGET%\backup_update\" >nul 2>&1

echo  Copying new code...
if /i "%PACKDIR%"=="%TARGET%" goto copied
copy /y "%~dp0*.py" "%TARGET%\" >nul
copy /y "%~dp0version.txt" "%TARGET%\" >nul
if exist "%~dp0skills" xcopy /y /e /q "%~dp0skills" "%TARGET%\skills\" >nul
if exist "%~dp0assets" xcopy /y /e /q "%~dp0assets" "%TARGET%\assets\" >nul
if exist "%~dp0platform-tools" xcopy /y /e /q "%~dp0platform-tools" "%TARGET%\platform-tools\" >nul
if exist "%~dp0phone-app" xcopy /y /e /q "%~dp0phone-app" "%TARGET%\phone-app\" >nul
if exist "%~dp0SETUP-YOUTUBE.txt" copy /y "%~dp0SETUP-YOUTUBE.txt" "%TARGET%\" >nul
if exist "%~dp0SETUP-OLLAMA.txt" copy /y "%~dp0SETUP-OLLAMA.txt" "%TARGET%\" >nul
if exist "%~dp0SETUP-GOOGLE-VOICE.txt" copy /y "%~dp0SETUP-GOOGLE-VOICE.txt" "%TARGET%\" >nul

:copied
echo  Patching settings - plain voice (robot off for good),
echo  no news at startup, full PC control on. Your API keys stay safe.
if not exist "%TARGET%\patch_config.py" goto nopatch
"%TARGET%\.venv\Scripts\python.exe" "%TARGET%\patch_config.py"

:nopatch
REM --- v4.7: Desktop + Start Menu shortcuts with the logo icon ---
echo  Creating the Nalox shortcut on your Desktop (logo icon)...
if exist "%TARGET%\create_shortcut.py" "%TARGET%\.venv\Scripts\python.exe" "%TARGET%\create_shortcut.py"

REM --- Packages: pip install ONLY if requirements.txt changed ---
if not exist "%~dp0requirements.txt" goto restart
"%TARGET%\.venv\Scripts\python.exe" -c "import hashlib,pathlib,sys; new=hashlib.md5(pathlib.Path(r'%~dp0requirements.txt').read_bytes()).hexdigest(); hp=pathlib.Path(r'%TARGET%\.venv\.nalox_req_hash'); old=hp.read_text().strip() if hp.exists() else ''; sys.exit(0 if new!=old else 1)"
if errorlevel 1 goto reqsame
echo  Package list changed - installing new packages, please wait...
copy /y "%~dp0requirements.txt" "%TARGET%\" >nul
"%TARGET%\.venv\Scripts\python.exe" -m pip install --prefer-binary -r "%TARGET%\requirements.txt"
if errorlevel 1 goto pipfail
"%TARGET%\.venv\Scripts\python.exe" -c "import hashlib,pathlib; pathlib.Path(r'%TARGET%\.venv\.nalox_req_hash').write_text(hashlib.md5(pathlib.Path(r'%TARGET%\requirements.txt').read_bytes()).hexdigest())"
goto restart

:pipfail
echo  Package install hit a problem - Nalox will still start,
echo  and the ears ladder keeps the hearing working meanwhile.
echo  Run UPDATE.bat again later to retry the packages.
goto restart

:reqsame
echo  Packages unchanged - skipping the big download.

:restart
echo  Restarting Nalox...
start "" wscript.exe "%TARGET%\start_nalox.vbs"

powershell -NoProfile -Command "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('Nalox has been updated successfully.')"

echo.
echo  ==========================================
echo    Update complete! Nalox is back on.
echo  ==========================================
pause
