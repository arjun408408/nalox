"""Nalox Doctor (v4.3) — "Nalox, check yourself".

OpenJarvis has `jarvis doctor`; Nalox gets the same idea, sized for
one laptop. run_checks(cfg) runs a battery of small, independent
health checks and returns a list of (name, ok, detail) tuples:

    microphone   — open the picked input device, record 1 s, report
                   the peak level (proof the mic really hears).
    speaker      — name the default output device + a soft beep
                   (winsound, guarded — skipped off Windows).
    whisper      — are the wake + command model files in the local
                   faster-whisper cache? (A missing model is not
                   fatal — it downloads on first use — but the
                   doctor says so instead of failing silently.)
    cloud ears   — (v5.1) is cloud command hearing on, and which
                   provider would hear (Gemini / Groq / local)?
    phone        — (v5.4) ADB tools present? phone reachable
                   over Wi-Fi? how many contacts are saved?
    internet     — HTTPS HEAD to example.com, 4 s timeout.
    elevenlabs   — API key present? If yes, is the voices endpoint
                   reachable with it?
    claude       — Anthropic API key present?
    telegram     — bot token present?
    youtube      — client secret present? token (consent) present?
    gmail        — Gmail address + app password present?

GOLDEN RULE: every check is individually wrapped — a check that
explodes returns (name, False, "check failed: ...") and the rest
still run. run_checks itself never raises.
"""
import logging
import os

log = logging.getLogger("nalox.doctor")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------ helpers
def _hf_cache_roots():
    """Candidate Hugging Face hub cache directories."""
    roots = []
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(os.path.join(hf_home, "hub"))
    roots.append(os.path.join(os.path.expanduser("~"),
                              ".cache", "huggingface", "hub"))
    return roots


def _model_cached(size):
    """True if faster-whisper-<size> has a model.bin in the HF cache."""
    want = ("models--systran--faster-whisper-" + str(size).lower())
    for root in _hf_cache_roots():
        try:
            if not os.path.isdir(root):
                continue
            for entry in os.listdir(root):
                if entry.lower() != want:
                    continue
                snap_root = os.path.join(root, entry, "snapshots")
                if not os.path.isdir(snap_root):
                    continue
                for snap in os.listdir(snap_root):
                    if os.path.exists(os.path.join(snap_root, snap,
                                                   "model.bin")):
                        return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------ checks
def _check_microphone(cfg):
    import numpy as np
    import sounddevice as sd

    import ears
    idx = ears.pick_input_device(cfg)
    name = ears._device_name(idx)
    audio = sd.rec(int(1.0 * 16000), samplerate=16000, channels=1,
                   dtype="float32", device=idx)
    sd.wait()
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size \
        else 0.0
    # v4.3: report the wake gate too — threshold is
    # max(room floor x 2.5, 0.006); this recording's RMS stands in
    # for the room floor so Arjun can see the number he must beat.
    gate = max(rms * 2.5, 0.006)
    gate_note = f"gate ≈ {gate:.3f} (room rms {rms:.3f} x 2.5)"
    if peak >= 0.01:
        return True, (f"{name} — heard sound (peak {peak:.2f}); "
                      f"{gate_note}")
    return True, (f"{name} — opened fine, but the room was silent "
                  f"(peak {peak:.3f}); {gate_note}; speak during "
                  "the test to be sure")


def _check_speaker(cfg):
    name = "unknown output device"
    try:
        from voice import Speaker
        name = Speaker(cfg).output_device_name()
    except Exception:
        pass
    beeped = False
    try:
        import winsound
        winsound.Beep(660, 150)
        beeped = True
    except Exception:
        pass  # not on Windows / no audio stack — the name still helps
    if beeped:
        return True, f"{name} — test beep played"
    return True, f"{name} (beep skipped on this system)"


def _check_whisper(cfg):
    # Ears 2.0: wake segments use the wake model (config
    # wake_model — "base" by default since v4.5, with a one-time
    # "small" retry on loud segments); commands use the command
    # model ("small"); the tiny model only serves the barge-in
    # monitor now.
    seg = str(cfg.get("wake_model")
              or cfg.get("whisper_command_model") or "base")
    cmd = str(cfg.get("whisper_command_model") or "small")
    tiny = str(cfg.get("whisper_wake_model") or "tiny")
    wanted = [("wake", seg), ("command", cmd),
              ("barge-in", tiny)]
    seen = set()
    missing = []
    for label, size in wanted:
        if size in seen:
            continue
        seen.add(size)
        if not _model_cached(size):
            missing.append(f"{label} model '{size}'")
    if missing:
        return False, ("not downloaded yet: " + ", ".join(missing)
                       + " — the first listen will fetch it")
    return True, (f"models cached: segment '{seg}', command "
                  f"'{cmd}', barge-in '{tiny}'")


def _check_cloud_ears(cfg):
    # v5.1: cloud ears hear COMMANDS (Gemini audio first — the
    # field-confirmed key — then Groq Whisper); the local model
    # is always the fallback, and the wake loop never leaves
    # the laptop. The doctor reports which ear would be used.
    mode = str(cfg.get("cloud_ears") or "auto").strip().lower()
    if mode == "off":
        return True, "off in Settings — local Whisper hears commands"
    try:
        import ears
        provider = ears.cloud_ear_provider(cfg)
    except Exception:
        provider = None
    if provider == "gemini":
        return True, ("on — Gemini hears commands (best Bengali/"
                      "Hindi); local Whisper is the backup")
    if provider == "groq":
        return True, ("on — Groq Whisper (whisper-large-v3) hears "
                      "commands; local Whisper is the backup")
    return False, ("on, but no Gemini/Groq key is set — local "
                   "Whisper only until a key is pasted")


def _check_internet(cfg):
    import requests
    resp = requests.head("https://example.com", timeout=4,
                         allow_redirects=True)
    if resp.status_code < 500:
        return True, f"online (example.com answered {resp.status_code})"
    return False, f"example.com answered {resp.status_code}"


def _check_elevenlabs(cfg):
    key = (cfg.get("elevenlabs_api_key") or "").strip()
    if not key:
        return False, "API key not set — Settings → Connections"
    try:
        import requests
        resp = requests.get("https://api.elevenlabs.io/v1/voices",
                            headers={"xi-api-key": key}, timeout=6)
        if resp.status_code == 200:
            return True, "API key set and accepted by ElevenLabs"
        return False, f"key set, but ElevenLabs answered {resp.status_code}"
    except Exception as exc:
        return False, f"key set, but the check failed: {exc}"


def _check_claude(cfg):
    # v5.0: FreeLLMAPI (Arjun's local router app) is the brain's
    # FIRST provider when its unified key is set — the doctor
    # names it first, mirroring the agent's priority: FreeLLMAPI
    # → Claude → OpenRouter → Gemini → Groq → OpenAI → local.
    if (cfg.get("freellm_api_key") or "").strip():
        return True, "FreeLLMAPI key set — FreeLLMAPI is the brain"
    if (cfg.get("anthropic_api_key") or "").strip():
        return True, "Anthropic API key set — Claude is the brain"
    # v4.8: the doctor names the brain that will ACTUALLY run —
    # priority Claude → Gemini → Groq → OpenAI → Ollama/local.
    # v4.9: OpenRouter joins in priority order (second, right
    # after direct Anthropic) — priority Claude → OpenRouter →
    # Gemini → Groq → OpenAI → Ollama/local.
    if (cfg.get("openrouter_api_key") or "").strip():
        return True, "OpenRouter API key set — OpenRouter is the brain"
    if (cfg.get("gemini_api_key") or "").strip():
        return True, "Gemini API key set — Gemini is the brain"
    if (cfg.get("groq_api_key") or "").strip():
        return True, "Groq API key set — Groq is the brain"
    if (cfg.get("openai_api_key") or "").strip():
        return True, "OpenAI API key set — OpenAI is the brain"
    return False, "no brain key — local/free mode (commands only)"


def _check_telegram(cfg):
    if (cfg.get("telegram_bot_token") or "").strip():
        owner = (cfg.get("telegram_owner_chat_id") or "").strip()
        if owner:
            return True, "bot token + owner chat id set"
        return True, "bot token set (owner chat id still missing)"
    return False, "bot token not set — the phone bridge is off"


def _check_phone(cfg):
    # v6.0: the Nalox Phone APP LINK is the primary transport
    # now — when the app is connected it is reported first.
    # ADB (v5.4) remains the fallback line below. The check
    # only LOOKS: auto-connect is the brain's job, and the
    # doctor shouldn't take 20 s proving a phone is asleep.
    contacts = cfg.get("phone_contacts") or {}
    n = len(contacts) if isinstance(contacts, dict) else 0
    try:
        import phone_link
        if phone_link.is_connected():
            device = phone_link.device_name() or "Android phone"
            return True, (f"app connected ({device}) — "
                          f"{n} contact(s) saved")
    except Exception:
        pass
    import phone_control
    if phone_control.find_adb(cfg) is None:
        return False, ("not connected — say \"send me the "
                       "phone link\" to pair the Nalox Phone app")
    state, serial = phone_control.device_state(
        cfg, allow_connect=False)
    if state == "ok":
        return True, (f"phone connected via ADB ({serial}) — "
                      f"{n} contact(s) saved")
    if state == "unauthorized":
        return False, ("phone found but not authorized — tap "
                       "Allow on the phone (Wireless debugging)")
    if str(cfg.get("phone_wifi_address") or "").strip():
        return False, ("phone not reachable on Wi-Fi right "
                       "now — asleep/off, or re-pair in "
                       f"Settings → Phone; {n} contact(s) saved")
    return False, ("not paired yet — say \"send me the phone "
                   "link\" for the app, or pair via ADB in "
                   "Settings → Phone")


def _check_youtube(cfg):
    secret = os.path.exists(
        os.path.join(BASE_DIR, "youtube_client_secret.json"))
    token = os.path.exists(os.path.join(BASE_DIR, "youtube_token.json"))
    if secret and token:
        return True, "client secret + consent token present"
    if secret:
        return True, ("client secret present — consent happens on the "
                      "first 'reply all'")
    return False, "not set up — see SETUP-YOUTUBE.txt"


def _check_gmail(cfg):
    try:
        import skills
        if skills.gmail_is_setup(cfg):
            return True, "Gmail address + app password set"
    except Exception:
        pass
    return False, "not set up — Settings → Connections (app password)"


_CHECKS = [
    ("Microphone", _check_microphone),
    ("Speaker", _check_speaker),
    ("Whisper models", _check_whisper),
    ("Cloud hearing", _check_cloud_ears),
    ("Internet", _check_internet),
    ("ElevenLabs voice", _check_elevenlabs),
    ("Claude brain", _check_claude),
    ("Telegram", _check_telegram),
    ("Phone", _check_phone),
    ("YouTube", _check_youtube),
    ("Gmail", _check_gmail),
]


def run_checks(cfg):
    """Run every check; return [(name, ok, detail)]. Never raises."""
    results = []
    for name, fn in _CHECKS:
        try:
            ok, detail = fn(cfg)
            results.append((name, bool(ok), str(detail)))
        except Exception as exc:
            log.warning("Doctor check %s failed: %s", name, exc)
            results.append((name, False, f"check failed: {exc}"))
    return results


def summary_line(results):
    """The one spoken line: all good, or the problem count."""
    bad = sum(1 for _n, ok, _d in results if not ok)
    if bad == 0:
        return "All good, Arjun."
    if bad == 1:
        return "One problem, Arjun — details on screen."
    return f"{bad} problems, Arjun — details on screen."
