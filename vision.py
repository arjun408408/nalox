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


def _hidden_console_kwargs():
    """subprocess kwargs that keep a console child INVISIBLE
    (v7.7, item G): CREATE_NO_WINDOW on Windows, nothing
    elsewhere — a PowerShell child of a windowless parent
    otherwise flashes a console window during screen reads."""
    if os.name == "nt":
        return {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


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
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_hidden_console_kwargs())
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


# ------------------------------------------------- local vision (v6.8)
# The owner's ChatGPT consultation settled on Qwen3-VL 8B as
# the free local vision model, and his PC has an 8 GB NVIDIA
# GPU — so when Ollama is up, the screenshot itself (not just
# its OCR text) is described locally: faster, offline, and it
# sees layout/icons/images OCR never could. ANY failure —
# server down, model not pulled (404), timeout, empty answer
# — returns None and the caller uses the OCR path exactly as
# before. The timeout is generous: a vision model is slower
# than chat, and a local call costs nothing per second.
OLLAMA_VISION_TIMEOUT_S = 60.0


def describe_screen_ollama(cfg, image_path, lang=None):
    """Describe a screenshot with the LOCAL Ollama vision
    model (config ollama_vision_model, default
    "qwen3-vl:8b"). Returns the description in the reply
    language, or None on any failure. One log line either
    way: success names the model that answered; failure
    names the reason the regular path is taking over."""
    cfg = cfg or {}
    model = (cfg.get("ollama_vision_model")
             or "qwen3-vl:8b").strip() or "qwen3-vl:8b"
    url = (cfg.get("ollama_url")
           or "http://localhost:11434").rstrip("/")
    try:
        import base64
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
    except Exception as exc:
        log.info("[vision] ollama vision skipped — cannot "
                 "read the screenshot: %s", exc)
        return None
    if lang == "bn":
        lang_line = ("Reply in Bengali, in one or two short "
                     "sentences. ")
    elif lang == "hi":
        lang_line = ("Reply in Hindi, in one or two short "
                     "sentences. ")
    else:
        lang_line = ("Reply in English, in one or two short "
                     "sentences. ")
    prompt = ("Describe what is on this computer screen. "
              + lang_line
              + "If there is an error message, a chat "
                "message or anything that needs attention, "
                "say what it is and what it means. Do not "
                "invent anything you cannot see.")
    try:
        import requests
        resp = requests.post(
            url + "/api/chat",
            json={"model": model,
                  "messages": [{"role": "user",
                                "content": prompt,
                                "images": [b64]}],
                  "stream": False},
            timeout=OLLAMA_VISION_TIMEOUT_S)
    except Exception as exc:
        log.info("[vision] ollama vision unavailable "
                 "(%s: %s) — using the regular path",
                 type(exc).__name__, exc)
        return None
    if resp.status_code != 200:
        log.info("[vision] ollama vision unavailable "
                 "(HTTP %s — is %s pulled?) — using the "
                 "regular path", resp.status_code, model)
        return None
    try:
        text = ((resp.json().get("message") or {})
                .get("content") or "").strip()
    except Exception:
        text = ""
    if not text:
        log.info("[vision] ollama vision returned nothing "
                 "— using the regular path")
        return None
    log.info("[vision] answered by ollama %s", model)
    return text


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
