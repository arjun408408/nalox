"""Nalox Doctor (v4.3) — "Nalox, check yourself".

OpenJarvis has `jarvis doctor`; Nalox gets the same idea, sized for
one laptop. run_checks(cfg) runs a battery of small, independent
health checks and returns a list of (name, ok, detail) tuples:

    microphone   — open the picked input device, record 1 s, report
                   the peak level (proof the mic really hears).
    speaker      — name the default output device + a soft beep
                   (winsound, guarded — skipped off Windows).
    dictation    — (v9.0) which cloud transcriber would serve
                   one-shot dictation (Groq Whisper first, Gemini
                   fallback)? There are NO local speech models
                   anymore — the ears were removed by the owner's
                   text-first order, so there is nothing to cache.
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


# ------------------------------------------------------------ checks
def _check_microphone(cfg):
    import numpy as np
    import sounddevice as sd

    import dictation
    idx = dictation.pick_input_device(cfg)
    name = dictation._device_name(idx)
    audio = sd.rec(int(1.0 * 16000), samplerate=16000, channels=1,
                   dtype="float32", device=idx)
    sd.wait()
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size \
        else 0.0
    # Report the dictation speech gate too (v9.0: threshold
    # is max(room floor x 3, 0.008), the floor measured from
    # the dictation's first half-second; this recording's
    # RMS stands in for the room floor so Arjun can see the
    # number his voice must beat to start a dictation).
    gate = max(rms * 3.0, 0.008)
    gate_note = f"gate ≈ {gate:.3f} (room rms {rms:.3f} x 3)"
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
    # v9.0: RETIRED as a model check — the local Whisper
    # fleet is gone (text-first order); no model files are
    # needed or loaded. The check stays in the battery as
    # the by-design report so the Doctor page says so.
    return True, ("no local speech models by design (v9.0 "
                  "text-first) — dictation is cloud-only")


def _check_cloud_ears(cfg):
    # v9.0: dictation hearing is cloud-only — Groq Whisper
    # first (the field-proven path), Gemini audio as the
    # fallback; there is no local backup anymore. The
    # doctor reports which provider would serve.
    mode = str(cfg.get("cloud_ears") or "auto").strip().lower()
    if mode == "off":
        return False, ("off in Settings — voice clips never "
                       "leave the laptop, so dictation cannot "
                       "run (typing + Telegram still work)")
    try:
        import dictation
        provider = dictation.cloud_ear_provider(cfg)
    except Exception:
        provider = None
    if provider == "groq":
        return True, ("on — Groq Whisper (whisper-large-v3) "
                      "transcribes dictation first; Gemini "
                      "is the fallback")
    if provider == "gemini":
        return True, ("on — Gemini transcribes dictation "
                      "(no Groq key set)")
    return False, ("on, but no Groq/Gemini key is set — "
                   "dictation has no transcriber until a key "
                   "is pasted (typing + Telegram still work)")


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
    ("Speech models", _check_whisper),
    ("Dictation hearing", _check_cloud_ears),
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
