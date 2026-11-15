"""Nalox's eyes (v3.6): screen capture, OCR and webcam photos.

- capture_screen(): full virtual-screen PNG via PowerShell + .NET
  (System.Windows.Forms.SystemInformation.VirtualScreen +
  System.Drawing) — no new dependency. Raises if no PNG lands.
- ocr_image(): the text inside an image, read by Windows' built-in
  OCR engine (Windows.Media.Ocr) driven through a temp PowerShell
  WinRT script (en-US, falling back to the user's profile languages).
  Returns "" on ANY failure — OCR is best-effort and must never
  break a voice command.
- capture_camera(): one webcam photo via OpenCV
  (opencv-python-headless). Returns None when cv2 is missing or no
  camera answers — the camera is optional hardware.

Captures land in the "Nalox Captures" folder inside the install dir.
Off Windows these fail gracefully: capture_screen raises (callers
guard), ocr_image returns "", capture_camera returns None.
"""
import logging
import os
import subprocess
import tempfile
from datetime import datetime

log = logging.getLogger("nalox.vision")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "Nalox Captures")

# ------------------------------------------------------------- scripts
# Paths travel via environment variables, so quoting can never break.
_SCREEN_PS = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
try {
    $gfx.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
    $bmp.Save($env:NALOX_CAPTURE_PATH,
              [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $gfx.Dispose()
    $bmp.Dispose()
}
"""

_OCR_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
function Await-Op($op, $type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait()
    return $task.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$file = Await-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:NALOX_OCR_PATH)) ([Windows.Storage.StorageFile])
$stream = Await-Op ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
if ($bitmap.BitmapPixelFormat -ne [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8) {
    $bitmap = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert(
        $bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8)
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
    (New-Object Windows.Globalization.Language 'en-US'))
if (-not $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if (-not $engine) { exit 3 }
$result = Await-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[System.IO.File]::WriteAllText($env:NALOX_OCR_OUT, $result.Text,
                               [System.Text.Encoding]::UTF8)
"""


# ------------------------------------------------------------- helpers
def _captures_dir():
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    return CAPTURES_DIR


def _new_path(prefix, ext):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_captures_dir(), f"{prefix}_{stamp}{ext}")


def _run_powershell(script, env_extra, timeout=30):
    """Write `script` to a temp .ps1 and run it with extra env vars.

    Returns the CompletedProcess. Raises on spawn failure/timeout —
    callers decide whether that is fatal (screen) or not (OCR).
    """
    fd, ps_path = tempfile.mkstemp(suffix=".ps1", prefix="nalox_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        env = dict(os.environ)
        env.update(env_extra)
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", ps_path],
            env=env, timeout=timeout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        try:
            os.remove(ps_path)
        except Exception:
            pass


# ------------------------------------------------------------- screen
def capture_screen(path=None):
    """Screenshot the full virtual screen (all monitors) to a PNG.

    Returns the PNG path. Raises if the file does not appear or is
    trivially small — a failed capture must be loud, not silent.
    """
    if path is None:
        path = _new_path("screen", ".png")
    else:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    _run_powershell(_SCREEN_PS, {"NALOX_CAPTURE_PATH": path},
                    timeout=30)
    if not os.path.exists(path) or os.path.getsize(path) < 5000:
        raise RuntimeError(f"screenshot was not saved to {path}")
    log.info("Screenshot saved: %s", path)
    return path


def ocr_image(path):
    """Read the text in an image with Windows' built-in OCR.

    Returns the text (possibly ""), NEVER raises: any failure —
    no OCR engine, unreadable file, not Windows — returns "".
    """
    if not path or not os.path.exists(path):
        return ""
    fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="nalox_ocr_")
    os.close(fd)
    try:
        result = _run_powershell(
            _OCR_PS,
            {"NALOX_OCR_PATH": path, "NALOX_OCR_OUT": out_path},
            timeout=45)
        if result.returncode != 0:
            log.info("OCR exited with code %s for %s",
                     result.returncode, path)
            return ""
        with open(out_path, "r", encoding="utf-8",
                  errors="replace") as f:
            return f.read().strip()
    except Exception as exc:
        log.info("OCR failed for %s: %s", path, exc)
        return ""
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass


def look_at_screen():
    """Capture the screen and read its text.

    Returns {"image": png_path, "text": ocr_text}. Raises if the
    capture itself fails (brain guards this).
    """
    path = capture_screen()
    return {"image": path, "text": ocr_image(path)}


# ------------------------------------------------------------- camera
def capture_camera(path=None):
    """Take one webcam photo (JPG). Returns the path, or None.

    Warms the camera up on a few frames so the saved one is not the
    usual black first frame. None when OpenCV is not installed, no
    camera is present, or every frame read fails.
    """
    try:
        import cv2
    except Exception:
        log.info("OpenCV not available — camera disabled.")
        return None
    if path is None:
        path = _new_path("camera", ".jpg")
    else:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    cap = None
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            log.info("No camera could be opened.")
            return None
        frame = None
        for _ in range(8):  # warm-up frames; keep the last good one
            ok, shot = cap.read()
            if ok and shot is not None:
                frame = shot
        if frame is None:
            log.info("Camera opened but returned no frames.")
            return None
        if not cv2.imwrite(path, frame):
            log.info("Could not save the camera photo to %s", path)
            return None
        log.info("Camera photo saved: %s", path)
        return path
    except Exception as exc:
        log.info("Camera capture failed: %s", exc)
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
