"""Loads config.json (next to this file) with sensible defaults."""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "user_name": "Arjun",
    "assistant_name": "Nalox",
    "whisper_wake_model": "tiny",
    # --- v6.7: the LOCAL command fallback gets the big ears.
    # Cloud ears still hear commands FIRST (Gemini audio →
    # Groq whisper); this model is what hears him when the
    # cloud is down or times out, and "small" garbled his
    # Bengali too often. large-v3-turbo is ~1.6 GB on first
    # download; if it cannot load (offline, disk, anything),
    # ears falls back to "small" for the session with ONE
    # log line — hearing never breaks over a download. The
    # owner lifted the CPU constraint explicitly (2026-11-15
    # 19:51 IST), so heaviness is spent where it buys hearing
    # accuracy. patch_config migrates installs still holding
    # the shipped "small" default; a hand-set value is kept. ---
    "whisper_command_model": "large-v3-turbo",
    # --- v4.3 Ears 2.0: the model that transcribes wake SEGMENTS
    # (auto language). v4.5: "base" by default — roughly 3x faster
    # than "small" on CPU, and wake only has to catch the name +
    # rough words; a LOUD segment it garbles is retried once with
    # the accurate command model ("small"), which still handles
    # every actual command recording. v6.4: the first pass drops
    # to "tiny" — the cheapest ears that can still catch the
    # name, and on Arjun's busy CPU every idle wake decode runs
    # on it; the safety net grows a rung instead of shrinking:
    # a loud GARBLED segment still retries once with "small"
    # (triggers a/b/c), and a loud NEAR-MISS of the name (a
    # token at edit distance exactly 2 — "malos", "nelos")
    # retries once with "base" (trigger d, WAKE_RETRY_MODEL
    # in ears.py).
    # patch_config migrates installs still holding a shipped
    # default ("small" from v4.3, "base" from v4.5). ---
    "wake_model": "tiny",
    # --- v5.1: CLOUD EARS — the COMMAND transcription may go
    # to the cloud first (Gemini audio, then Groq Whisper),
    # because the local small model still garbles Arjun's
    # Bengali/Hindi (the IRIS reel he sent hears Hindi perfectly
    # for exactly this reason). "auto" = use the cloud whenever
    # a Gemini/Groq key exists; the local model stays the
    # fallback, so hearing never depends on the network. "off" =
    # local only — voice clips never leave the laptop. The wake
    # loop is ALWAYS local regardless of this setting. ---
    "cloud_ears": "auto",
    # --- v3.5: mic auto-connect — "" = follow the Windows default
    # input; set to part of a device name (e.g. "USB") to prefer it ---
    "mic_device": "",
    "tts_rate": 175,
    # --- voice effect: v3.3 added a robotic JARVIS ring-mod;
    # v4.1 turns it OFF for good (Arjun rejected it outright) —
    # Nalox speaks with his plain ElevenLabs voice, or the plain
    # local voice until he pastes the ElevenLabs key in Settings ---
    "robot_voice": False,
    "robot_hz": 30,
    "use_edge_tts": False,
    "edge_tts_voice": "en-US-ChristopherNeural",
    # --- v2: Bengali bilingual ---
    "default_language": "en",
    # v4.9: the Bengali edge voice is MALE by default —
    # bn-BD-PradeepNeural. The old default (bn-BD-NabanitaNeural)
    # is female; Arjun asked for a man's voice ("ছেলের ভয়েস
    # চাই"). Settings → Voice can switch back to Female.
    "bn_voice": "bn-BD-PradeepNeural",
    # --- v2: ElevenLabs voice (top priority when the key is set) ---
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "auq43ws1oslv0tO4BDa7",
    # --- v2: power skills (leads / demo sites / email) ---
    "home_location": "",
    "lead_category": "restaurant",
    "search_radius_km": 5,
    "demo_base_url": "",
    "email_address": "",
    "email_app_password": "",
    # --- v2: startup YouTube check (v3.3: OFF by default — Arjun
    # asked Nalox not to open YouTube on its own at startup) ---
    "startup_youtube_check": False,
    "youtube_channel_url": "https://www.youtube.com/@MNYIntelligence",
    # --- v3: hacker console HUD, follow-up window, morning briefing ---
    "show_hud": True,
    "followup_seconds": 8,
    "morning_briefing": True,
    # --- v5.2: the AUTOMATIC startup briefing is cancelled
    # (Arjun's standing instruction, 2026-11-15): boot speaks
    # the greeting ONLY. The digest survives on demand ("good
    # morning" / Telegram) — it just never fires by itself at
    # startup. nalox.py's boot path honours this flag; the
    # v5.2 config patch forces it off on existing installs. ---
    "briefing_on_startup": False,
    # --- v3 expansion: agent brain (Groq) + news in the briefing ---
    "groq_api_key": "",
    "groq_model": "llama-3.3-70b-versatile",
    # --- v6.5: MODEL CANDIDATE LISTS — providers retire model
    # names without asking (field log 2026-11-15 18:44 IST:
    # Gemini answered a VALID key with 404 "gemini-2.5-flash is
    # no longer available to new users" and Groq with 404
    # model_not_found for llama-3.3-70b-versatile — the whole
    # chain silently died on names, not keys). The single
    # *_model value above stays the HEAD of the list (his
    # Settings choice tries first); on a model-not-found error
    # the brain walks the rest of the list inside the same
    # provider call, and REMEMBERS the model that worked
    # (written back to the single *_model key) so later calls
    # go straight to it. ---
    "groq_models": ["llama-3.3-70b-versatile",
                    "openai/gpt-oss-120b",
                    "llama-3.1-8b-instant",
                    "qwen/qwen3-32b"],
    # --- v4.8: GEMINI brain (Google AI Studio) — one FREE key,
    # reached through Gemini's OpenAI-compatible endpoint with
    # the same tool loop as Groq/OpenAI. Priority: Claude →
    # Gemini → Groq → OpenAI → Ollama. ---
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    # v6.5: Gemini candidates (see groq_models above).
    "gemini_models": ["gemini-2.5-flash",
                      "gemini-2.0-flash",
                      "gemini-2.5-flash-lite",
                      "gemini-flash-latest"],
    # --- v4.9: OPENROUTER brain — ONE key, many models (Claude
    # included), through OpenRouter's OpenAI-compatible API with
    # the same tool loop. Priority: Claude → OpenRouter →
    # Gemini → Groq → OpenAI → Ollama. The default model is
    # Claude Sonnet 4.5 reached via OpenRouter. ---
    "openrouter_api_key": "",
    "openrouter_model": "anthropic/claude-sonnet-4.5",
    # v6.5: OpenRouter candidates — empty by default (his one
    # configured model is the whole list until he adds more).
    "openrouter_models": [],
    # --- v5.0: FREELLMAPI brain — Arjun's LOCAL unified router
    # app (FreeLLMAPI, http://127.0.0.1:31415/v1): ONE local
    # "unified key" in front of a ~78-model chain that AUTO-
    # SWITCHES models inside the router when one fails. It is
    # the agent's FIRST provider whenever its key is set (the
    # owner's explicit instruction): a model dying inside the
    # router must never break the conversation — the router
    # moves on by itself. "auto" lets the router pick the model.
    "freellm_api_key": "",
    "freellm_base_url": "http://127.0.0.1:31415/v1",
    "freellm_model": "auto",
    # --- v4.1: NO headlines at boot — news only when Arjun asks ---
    "briefing_news": False,
    "ollama_model": "llama3.1",
    # --- v6.7: OLLAMA candidate list — the offline brain gets
    # the same candidate walk as the cloud providers (v6.5
    # machinery): the configured ollama_model above stays the
    # HEAD (tried first), then these in order; a name Ollama
    # answers 404 for (not pulled yet) walks to the next, and
    # the model that answers is remembered as ollama_model.
    # qwen3:8b is the one SETUP-OLLAMA.txt tells him to pull. ---
    "ollama_models": ["qwen3:8b", "qwen2.5:7b", "llama3.1:8b"],
    "ollama_url": "http://localhost:11434",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    # --- v4.0: Claude brain (Anthropic API) — the agent brain's TOP
    # priority whenever this key is set; raw HTTPS, no SDK needed ---
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-5",
    "telegram_bot_token": "",
    "telegram_owner_chat_id": "",
    "speak_telegram_commands": True,
    # --- v5.4: PHONE CONTROL — Nalox drives Arjun's Android
    # phone over Wi-Fi (ADB Wireless debugging pairing; the
    # phone is usually across the room, so the cable is only a
    # silent fallback — see phone_control.py). phone_adb_path
    # "" = the bundled platform-tools, then PATH. The pairing
    # values + the Wi-Fi address live ONLY in this local
    # config, exactly like his API keys. phone_contacts is the
    # call book he fills once in Settings → Phone
    # ({"mother": "+91..."}). ---
    "phone_adb_path": "",
    "phone_wifi_address": "",
    "phone_pair_address": "",
    "phone_pair_code": "",
    "phone_contacts": {},
    # --- v6.0: Nalox Phone app link token (phone_link.py).
    # Generated on first use and kept ONLY in this local
    # config; Settings → Phone can regenerate it (which
    # invalidates every old pairing). ---
    "phone_link_token": "",
    # --- v5.4: WAKE LINE — the exact words spoken the moment
    # the wake word lands (Arjun's chosen line). Replaces the
    # old short "Yes, Sir?" ack on both wake paths; Settings →
    # General "Wake reply" edits it; an empty value brings the
    # classic ack back. v5.7: the line itself changed at his
    # order — "Yes Sir, I'm here." (he did not want "I'm
    # coming for you" every time). patch_config migrates an
    # install still holding the OLD default; a customised
    # line is never touched. ---
    "wake_line": "Yes Sir, I'm here.",
    # --- v5.5: COMMAND CENTER — the fullscreen dashboard
    # (blue orb + SYSTEM + CHAT) behind "Nalox, wake up".
    # True = wake-up opens it (with the normal window as
    # fallback); False = wake-up shows the window as before. ---
    "command_center": True,
    # --- v6.2: SELF-UPDATE from GitHub (updater.py) — Nalox
    # checks the owner's private repo at boot (~60 s in) and
    # every 6 h, and applies a newer version itself, exactly
    # like UPDATE.bat did (code + assets; NEVER config.json
    # or any user data). The repo defaults to the owner's
    # own arjun408408/nalox; an empty TOKEN = self-update
    # off (no network calls at all). Both are set in
    # Settings → Updates; the token is a fine-grained PAT
    # with read access to that one repo, pasted LOCALLY,
    # never in chat. ---
    "github_repo": "arjun408408/nalox",
    "github_token": "",
    "auto_update": True,
    # --- v4.1: app-window Settings (settings_ui.py) ---
    "greet_on_startup": True,      # speak the boot greeting
    "autostart": True,             # Startup shortcut present (Settings)
    # --- v4.1: access & control — Arjun's standing instruction is
    # FULL control of his own PC: no confirmation prompts. All three
    # can be switched off in Settings if he ever changes his mind ---
    "full_control": True,
    "allow_youtube_reply": True,
    "allow_email_send": True,
    # --- v4.3: OpenJarvis chapter — digest weather (OpenWeatherMap,
    # free key), Gmail reading (IMAP; falls back to the mailer's
    # email_address / email_app_password when these are empty),
    # document memory folder, persona Modes, speaking rate ---
    "openweather_api_key": "",
    "weather_city": "Kolkata",
    "gmail_address": "",
    "gmail_app_password": "",
    "doc_folder": "",
    "mode": "jarvis",
    "voice_speed": 1.0,
    # --- v4.7: LEARNED preferences — "call me Sir" / "বাংলায়
    # কথা বলো". Empty = not learned yet (address = user_name,
    # language = per-utterance detection). The durable store is
    # prefs.json (memory_store); these keys are the live mirror
    # that Settings' "Call me" field also writes. ---
    "preferred_name": "",
    "preferred_lang": "",
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update({k: v for k, v in user_cfg.items() if v not in (None,)})
    except FileNotFoundError:
        pass
    except Exception as exc:  # corrupt json etc. — never crash on config
        print(f"[config] could not read config.json ({exc}); using defaults")
    return cfg


CONFIG = load_config()
