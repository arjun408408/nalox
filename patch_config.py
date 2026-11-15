"""One-time config patch, shipped inside Nalox update packs.

UPDATE.bat copies this file into the Nalox folder and runs it with the
venv Python. It changes ONLY the keys in PATCHES below and preserves
everything else in config.json — above all Arjun's own API keys
(ElevenLabs / Groq / Telegram), which must never be overwritten by an
update pack. If config.json does not exist, it does nothing.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# v3.3: better Bengali model, no auto-YouTube.
# v3.7: robot_hz 35 -> 30.
# v4.1: robot voice OFF for good (Arjun rejected it — only his plain
# ElevenLabs voice, or the plain local voice), no news at startup,
# and full PC control ON (his standing instruction — no confirmation
# prompts; Settings keeps the toggle).
PATCHES = {
    "robot_voice": False,
    "robot_hz": 30,
    # v6.7: "whisper_command_model" is NO LONGER force-set
    # here — it is a migration now (see COMMAND_MODEL_OLD_
    # DEFAULT below): the shipped "small" default becomes
    # "large-v3-turbo", and a value he set by hand survives.
    "startup_youtube_check": False,
    "briefing_news": False,
    "full_control": True,
    # v5.2: the automatic startup briefing is CANCELLED
    # (Arjun's explicit instruction, 2026-11-15 — greeting
    # only at boot). briefing_on_startup is the new gate;
    # morning_briefing is the legacy key the boot digest and
    # the classic briefing both read — both go off. The
    # ON-DEMAND digest ("good morning" / Telegram) never read
    # either key, so it stays available.
    "briefing_on_startup": False,
    "morning_briefing": False,
}

# v4.3: brand-new keys get their defaults ONLY when absent — an
# existing value (e.g. a mode Arjun already picked) is never reset.
# v4.5: the wake_model default is now "base" (faster wake; loud
# segments the base model garbles are retried once with "small").
PATCH_IF_ABSENT = {
    "mode": "jarvis",
    "voice_speed": 1.0,
    # v6.4: the wake first pass is "tiny" now (see the migration
    # below) — an install missing the key gets the new default.
    "wake_model": "tiny",
    # v5.0: FreeLLMAPI brain keys — defaults only when absent;
    # a unified key Arjun already pasted is never touched.
    "freellm_api_key": "",
    "freellm_base_url": "http://127.0.0.1:31415/v1",
    "freellm_model": "auto",
    # v5.1: cloud ears on ("auto") by default — Gemini/Groq
    # hear commands when a key exists; Settings can turn it off.
    "cloud_ears": "auto",
    # v5.4: phone control (ADB over Wi-Fi) — empty defaults;
    # the pairing values + contacts he enters in Settings →
    # Phone are his own and are never touched once present.
    "phone_adb_path": "",
    "phone_wifi_address": "",
    "phone_pair_address": "",
    "phone_pair_code": "",
    "phone_contacts": {},
    # v6.0: Nalox Phone app link token — empty default;
    # phone_link.py generates the real one on first use and
    # a value he regenerates in Settings is never touched.
    "phone_link_token": "",
    # v5.4: his chosen wake line — added with the default ONLY
    # when absent; a line he edits in Settings → General is a
    # deliberate choice and is preserved. v5.7: the default is
    # the NEW line; an install still holding the v5.4 default
    # is migrated by WAKE_LINE_OLD_DEFAULT below.
    "wake_line": "Yes Sir, I'm here.",
    # v5.5: Command Center on by default — added only when
    # absent; if Arjun ever turns it off by hand, that choice
    # is preserved.
    "command_center": True,
    # v6.2: self-update keys — the repo defaults to the
    # owner's own arjun408408/nalox (patch-if-absent: his
    # Settings → Updates field comes prefilled; an edited
    # value is preserved); the token stays "" until HE
    # pastes one into Settings → Updates, and auto_update
    # defaults on so that once the token exists, no
    # further clicks are ever needed.
    "github_repo": "arjun408408/nalox",
    "github_token": "",
    "auto_update": True,
    # v6.5: model candidate lists (see config.py) — added
    # when absent; a list he edits by hand is preserved.
    "gemini_models": ["gemini-2.5-flash",
                      "gemini-2.0-flash",
                      "gemini-2.5-flash-lite",
                      "gemini-flash-latest"],
    "groq_models": ["llama-3.3-70b-versatile",
                    "openai/gpt-oss-120b",
                    "llama-3.1-8b-instant",
                    "qwen/qwen3-32b"],
    "openrouter_models": [],
    # v6.7: an install missing the command-model key gets the
    # new big default (an existing "small" is migrated below;
    # anything else is his and is preserved).
    "whisper_command_model": "large-v3-turbo",
    # v6.7: Ollama candidate list for the offline brain's
    # model walk — added when absent; his edits are kept.
    "ollama_models": ["qwen3:8b", "qwen2.5:7b", "llama3.1:8b"],
    # v6.8: the local vision model for screen reading —
    # added when absent; his edits are kept.
    "ollama_vision_model": "qwen3-vl:8b",
    # v6.8: Google Cloud TTS key (male Bengali voice) —
    # added empty when absent; the layer stays off until
    # he pastes a key (SETUP-GOOGLE-VOICE.txt).
    "google_tts_api_key": "",
    # v6.12: ears thread caps (see config.py) — added when
    # absent; a value he sets by hand is preserved.
    "ears_wake_threads": 2,
    "ears_command_threads": 4,
    "ears_preview_threads": 2,
    # v6.13: big-model device preference (see config.py) —
    # added when absent; his value is preserved.
    "ears_big_device": "auto",
    # v7.0: self-healing watchdog thresholds (see
    # config.py) — added when absent; his values are
    # preserved.
    "ears_mic_no_frames_s": 6.0,
    "ears_mic_flat_s": 20.0,
    "ears_mic_restart_budget": 3,
    "ears_mic_restart_window_s": 600.0,
    "watchdog_speaking_s": 45.0,
    "watchdog_stage_s": 90.0,
    # v7.1: wake escalation model + anti-chain stall gate
    # + stale wake-segment age cap (see config.py) — added
    # when absent; his values are preserved.
    "wake_escalation_model": "small",
    "ears_antichain_require_stall": True,
    "ears_wake_segment_max_age_s": 10.0,
}

# Wake-model migrations. The v4.3 patch WROTE wake_model="small"
# into config.json as its default (PATCH_IF_ABSENT above), and
# v4.5 migrated that to "base"; no Settings control exists for
# this key — so an existing "small" OR "base" is a shipped
# patch default, never a deliberate user choice. v6.4: the wake
# first pass becomes "tiny" (faster idle listening on a busy
# CPU; the retry net — small for garbles, base for near-misses
# of the name — keeps the accuracy), so BOTH old defaults
# migrate to "tiny". ANY other existing value ("medium", ... —
# only reachable by hand-editing the file) is treated as
# user-set and is preserved untouched.
WAKE_MODEL_OLD_DEFAULTS = ("small", "base")
WAKE_MODEL_NEW_DEFAULT = "tiny"

# v4.9 Bengali-voice migration, same shape as the wake-model one
# above. The old bn_voice default was bn-BD-NabanitaNeural
# (FEMALE) and no Settings control existed for the key before
# v4.9 — so an existing config holding exactly that value holds
# the old default, never a deliberate pick, and it migrates to
# the MALE default Arjun asked for ("ছেলের ভয়েস চাই"). ANY
# other existing value is treated as user-set and preserved.
BN_VOICE_OLD_DEFAULT = "bn-BD-NabanitaNeural"
BN_VOICE_NEW_DEFAULT = "bn-BD-PradeepNeural"

# v5.7 wake-line migration, same shape as the two above. The
# v5.4 patch wrote wake_line="Yes Sir, I'm coming for you."
# into installs as its default (PATCH_IF_ABSENT), and Arjun
# has now ordered a different line — "Yes Sir, I'm here." An
# install holding EXACTLY the old default holds the patch's
# choice, not a deliberate one, so it migrates. ANY other
# existing value (a line he typed into Settings → General
# himself) is treated as user-set and preserved untouched.
WAKE_LINE_OLD_DEFAULT = "Yes Sir, I'm coming for you."
WAKE_LINE_NEW_DEFAULT = "Yes Sir, I'm here."

# v6.7 command-model migration, same shape as the wake-model
# one. Every shipped patch up to v6.6 FORCE-wrote
# whisper_command_model="small" into config.json (it sat in
# PATCHES), so an existing "small" is the shipped default,
# never a deliberate choice — it migrates to the big local
# fallback "large-v3-turbo" (the owner lifted the CPU
# constraint, 2026-11-15). ANY other existing value (only
# reachable by hand-editing the file) is user-set and is
# preserved untouched.
COMMAND_MODEL_OLD_DEFAULT = "small"
COMMAND_MODEL_NEW_DEFAULT = "large-v3-turbo"


def main():
    if not os.path.exists(CONFIG_PATH):
        print("[patch] no config.json here - nothing to patch.")
        return
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        print(f"[patch] could not read config.json ({exc}) - skipped.")
        return
    changed = []
    for key, value in PATCHES.items():
        if cfg.get(key) != value:
            cfg[key] = value
            changed.append(f"{key}={value}")
    for key, value in PATCH_IF_ABSENT.items():
        if key not in cfg:
            cfg[key] = value
            changed.append(f"{key}={value} (new)")
    if cfg.get("wake_model") in WAKE_MODEL_OLD_DEFAULTS:
        cfg["wake_model"] = WAKE_MODEL_NEW_DEFAULT
        changed.append(
            f"wake_model={WAKE_MODEL_NEW_DEFAULT} "
            "(v6.4: a shipped patch default migrated to the "
            "tiny first pass; a user-set value would have "
            "been kept)")
    if cfg.get("bn_voice") == BN_VOICE_OLD_DEFAULT:
        cfg["bn_voice"] = BN_VOICE_NEW_DEFAULT
        changed.append(
            f"bn_voice={BN_VOICE_NEW_DEFAULT} "
            "(v4.9: female default migrated to the male Bengali "
            "voice Arjun asked for; a user-set value would have "
            "been kept)")
    if cfg.get("wake_line") == WAKE_LINE_OLD_DEFAULT:
        cfg["wake_line"] = WAKE_LINE_NEW_DEFAULT
        changed.append(
            f"wake_line={WAKE_LINE_NEW_DEFAULT} "
            "(v5.7: the v5.4 default wake line migrated to the "
            "line Arjun ordered; a user-set value would have "
            "been kept)")
    if cfg.get("whisper_command_model") == COMMAND_MODEL_OLD_DEFAULT:
        cfg["whisper_command_model"] = COMMAND_MODEL_NEW_DEFAULT
        changed.append(
            f"whisper_command_model={COMMAND_MODEL_NEW_DEFAULT} "
            "(v6.7: the shipped 'small' default migrated to the "
            "big local fallback; a user-set value would have "
            "been kept)")
    if not changed:
        print("[patch] config.json already up to date.")
        return
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("[patch] config.json updated: " + ", ".join(changed))


if __name__ == "__main__":
    main()
