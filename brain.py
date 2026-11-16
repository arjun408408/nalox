"""Nalox's brain: a fast keyword/regex command engine, plus a chat
fallback (local Ollama → OpenAI API → friendly canned reply).

v2 — BILINGUAL + POWER SKILLS:
  - handle(text, lang) threads the detected language ("en"/"bn") through:
    core replies have Bengali variants, and Bengali command keywords
    (ইউটিউব খোলো, সময় কত, স্ক্রিনশট নাও, লক করো, ...) work alongside English.
  - Power skills (skills.py): find leads, build demo website, email outreach.

v3 — AGENT BRAIN + MEMORY + REMINDERS:
  - Unmatched input goes to a tool-using LLM agent (Ollama → Groq →
    OpenAI; see AGENT_TOOLS / _run_tool) before the canned fallback.
  - memory_store.py: "remember ..." facts, recalled on demand and fed
    into the agent's system prompt.
  - reminders.py: "remind me in/at ..." — nalox.py speaks them when due.
  - Console (HUD) show/hide voice commands via self.hud (set by nalox.py).

v3.6 — VISION (vision.py): "take a screenshot" captures + opens the
image; "look at my screen / স্ক্রিনে কি আছে" screenshots + OCRs the
screen and summarises it in one short sentence (agent brain when
reachable); "look at the camera / ক্যামেরা দেখো" takes a webcam
photo. The agent brain gets the same powers as tools: read_my_screen,
take_screenshot, take_camera_photo.

v4.0 — CLAUDE BRAIN + YOUTUBE REPLY-ALL:
  - The agent brain's TOP priority is now Claude (Anthropic API,
    config anthropic_api_key / anthropic_model, raw HTTPS via
    requests — no SDK). Same tools, same memory, max ~5 tool rounds;
    any failure falls through to Groq → OpenAI → Ollama.
  - "reply all" / "সব কমেন্টের রিপ্লাই দাও" → youtube_tools.reply_all:
    replies to every unreplied top-level comment on the channel's
    recent videos, in a background thread, and speaks the count.

v4.1 — SETTINGS GATES + FULL CONTROL:
  - config full_control (default ON — Arjun's standing instruction):
    shutdown / restart / forget run IMMEDIATELY via
    _confirm_or_execute, no "are you sure?" round-trip. OFF restores
    the classic pending-confirmation flow.
  - config allow_youtube_reply gates the reply-all intent + tool;
    config allow_email_send gates the email intents + email_lead
    tool. Both default ON; the Settings window toggles them.
  - The provider that answered is mirrored to the logbook (BRAIN).

v4.2 — HINDI, Arjun's third language (he speaks English + Bengali +
Hindi only; ears.py now locks transcription to those three):
  _hindi_commands mirrors the Bengali handler — Devanagari script
  OR common Roman-Hindi phrases trigger it: greetings / कैसे हो,
  identity, thanks, time, date, battery, news (खबर सुनाओ), songs
  (गाना बजाओ + query), open Chrome/YouTube (क्रोम खोलो / chrome
  kholo), volume (आवाज़ बढ़ाओ/कम करो) and lock (लॉक करो). It runs
  right after the Bengali handler, before the English patterns, so
  lang "hi" never falls through to English small talk for these.

handle_command(text) returns (reply, action) where action is one of:
  None      — normal reply, keep listening for the wake word
  "confirm" — handled internally (shutdown/restart yes-no flow)
  "exit"    — ONLY a confirmed PC shutdown/restart (the machine
              itself is going down) — never a plain "stop"
  "standby" — (v5.4) user said stop/goodbye: stop SPEAKING and
              go back to wake listening; the process NEVER exits
              on a voice/Telegram stop (owner's hard rule — his
              own stop commands were killing Nalox: the old
              "exit" here exited code 42 and the supervisor
              stopped for good). Deliberate app exit is tray /
              HUD clicks only.
  "dashboard_open" / "dashboard_close" — (v5.5) show/hide the
              fullscreen Command Center; nalox.py owns the window
              and falls back to the normal window if it can't open.
The language of the most recent command is kept on self.last_lang so the
caller can speak the reply with the right voice.

v4.3 — THE OPENJARVIS CHAPTER:
  - PERSONA: the agent's character is now modelled on OpenJarvis's
    JARVIS persona (configs/openjarvis/prompts/personas/jarvis.md,
    adapted — not copied): composed, capable, butler-like; dry
    understated wit; anticipates needs; addresses Arjun by name
    sparingly; never robotic, never chatty; reports only facts it
    has. See _JARVIS_CHARACTER + MODES below.
  - MODES (config mode): jarvis / creator / focus adjust the system
    prompt and the digest order (creator = YouTube first).
  - NEW INTENTS (_v43_intents, run right after reminders): Doctor
    self-check, Morning Digest trigger + taste-skip, Gmail reading,
    Google Calendar, recurring action tasks (scheduler.py), file
    search (docmemory.py), TOML skill files (skillfiles.py).
  - Document memory auto-injects top snippets into the agent's
    system context for longer questions (guarded, silent).
  - LANGUAGE ANCHOR: English is the primary language; Bengali and
    Hindi are fully supported alongside it — those three only.

v4.4 — SPEED + UNDERSTANDING (Arjun's 09:51 field report):
  - BRAIN TIMEOUT KILLED: the agent path probed Ollama on EVERY
    unmatched command; with no Ollama and no keys, each probe of
    "localhost" burned a flat ~3.0 s (dual-stack ::1 + 127.0.0.1,
    each connect eating the 1.5 s timeout) before the fallback
    line. Provider availability is now probed ONCE at boot in a
    background thread and cached (re-probe at most every 5 min);
    with no provider available, unmatched commands go straight
    to the local fallback — brain time ~0.0 s.
  - ASR-TOLERANT CONTENT INTENTS (_normalise_asr +
    _content_intents): Whisper's predictable Bengali/Hindi
    garbling (বুপন→ওপেন, কোড়ো→করো, য়ুটুব→youtube, ...) is
    normalised, then intents match on CONTENT WORDS (object +
    verb) instead of exact phrases — checked after every
    exact-phrase intent, before the agent fallback.
  - CHAINED COMMANDS (handle): "open youtube and play lofi
    music" / "ইউটিউব খোলো তারপর গান বাজাও" split on chain
    markers into at most 3 sub-commands, run in order.
  - SHORTER FALLBACK: a miss now costs ~2 s of speech, not ~7.

v4.5 — ALWAYS ANSWER (Arjun's standing product rule, 10:11):
JARVIS answers FAST and answers EVERYTHING it hears — a reply
built on a wrong hearing beats silence, always. The ears side
(v4.5 in ears.py) stopped dropping his real Bengali at the
no_speech gate; the brain side is _chat_fallback's new
CONVERSATIONAL FALLBACK: an unmatched utterance that looks like
a question or small-talk (question words in EN/BN/HI, or a "?")
gets one short honest JARVIS-persona sentence in that language
("সেটা আমি এখনো শিখিনি, Arjun। তবে app খোলা, গান, খবর, সময় —
এগুলো বললেই করে দেব।") instead of the bare couldn't-catch line.
Only a non-question miss still lands on the v4.4 short fallback.

v4.6 — SELF-RESTART (Arjun's 10:26 ask): when Nalox feels stuck
("মাঝে মাঝে থেমে যাচ্ছে"), "Nalox, restart" must restart NALOX
ITSELF — the app, not the laptop. _handle_single checks for it
FIRST (after handle()'s pending-confirmation check, so a "yes"
is never hijacked): EN "restart" / "restart yourself" /
"restart nalox", BN "রিস্টার্ট করো" / "নিজেকে রিস্টার্ট করো" /
"আবার চালু হও", HI "रिस्टार्ट करो" / "restart करो" — matched on
the raw text AND its _normalise_asr form. Any mention of
pc/laptop/computer keeps the OLD meaning (the PC-restart
confirmation below), and a remind/remember opener is never a
restart. The reply is spoken first; the action "restart" then
makes nalox.py exit with code 1 and the supervisor relaunches —
same path as the HUD's new 🔄 Restart button. In a chain,
restart runs LAST: parts before it execute, the chain stops
there.

v4.7 — NALOX LEARNS (Arjun's 11:27 field report): the Telegram
bridge worked, but Nalox could not LEARN — "call me Sir from
today" was forgotten instantly, "speak Bengali" got only the
haven't-learned line, and "switch CHANNEL to Naloxff" had no
intent at all. All three are fixable locally, no API key needed:
(1) LEARNABLE PREFERENCES — handle() detects "call me X" /
"আমাকে X বলে ডাকো" / "मुझे X कहो" and "speak in Bengali" /
"বাংলায় কথা বলো" / "हिंदी में बोलो" BEFORE routing, saves them
to prefs.json (memory_store) + the live config mirror, and from
then on every address uses the learned name (ONE helper:
memory_store.address_name) and Nalox's own local replies default
to the learned language. (2) CHANNEL INTENT — "open/switch
channel <name>" opens youtube.com/@<name>. The general
do-anything agent still needs a brain key — that part is NOT
faked here; this pack covers only what is learnable locally.

v4.8 — BRAIN VISIBILITY + SELF-DIAGNOSIS (Arjun's 11:47 field
report): a FRESH Groq key sat in Settings, yet every Telegram
test got the local fallback — "সেটা আমি এখনো শিখিনি", "couldn't
quite catch", "haven't learned yet". The routing was correct;
the defect was SILENCE: every agent provider returned None on
ANY failure (HTTP error or exception) with zero logging, so a
rejected key, a stale pre-key process and a provider outage
were indistinguishable from "no key at all". Four fixes:
(1) PROVIDER FAILURE LOGGING — every agent-path failure writes
ONE logbook ERROR line with provider + reason (HTTP status +
the provider's own error code/message, or the exception class);
key material is never logged.
(2) BRAIN STATUS + KEY VALIDATION — at boot each configured
cloud key is validated with one lightweight GET /models call
in a background thread (Anthropic has no cheap check: marked
"configured, untested"); the result lives on brain_status
{mode, key_state, detail} and renders as ONE line — the HUD
header and the boot [brain] log line both use it. The old boot
line printed "local/free mode" whenever no ANTHROPIC key was
set, Groq key or not; that lie is gone.
(3) CONFIG HOT-RELOAD — handle() stats config.json's mtime; a
changed file merges its key/model/preference fields into the
live config and re-validates, so a key pasted in Settings
takes effect even if the restart hiccups or an older process
is the one answering Telegram. A half-written file is ignored.
(4) HONEST FALLBACK — with a key configured but the brain
failing, the conversational fallback says the brain
CONNECTION has a problem (trilingual) instead of the false
"haven't learned yet". No key → the v4.5 fallback, unchanged.
Plus: the language-preference detector is widened — "Can you
talk me Bangla" now switches, while "play a Bengali song"
still must not.
(5) GEMINI BRAIN (Arjun's 12:03 instruction — the "Mark LIII"
tutorial's whole brain is one free Google AI Studio key):
Gemini joins as a provider through its OpenAI-compatible
endpoint, reusing the tool loop; priority is now Claude →
Gemini → Groq → OpenAI → Ollama. And a provider whose boot
validation said REJECTED is skipped instantly by the agent —
with a gsk_ key sitting in the Claude field, every command
used to pay for a doomed Anthropic call first; now the dead
field is simply stepped over, and the first WORKING key in
line becomes the brain.

v4.9 — MALE BENGALI VOICE + OPENROUTER BRAIN (Arjun's 12:26
voice message): (1) Bengali replies were arriving in a FEMALE
voice — the edge-tts bn_voice default was bn-BD-NabanitaNeural.
He wants a man's voice: the default is now bn-BD-PradeepNeural
(config.py; patch_config migrates only the exact old default;
Settings → Voice gains a Male/Female chooser). (2) A tutorial
reel showed him "all models incl. Claude through one
OpenRouter key", and he wants that route too ("যা লাগবে
লাগবে" — whatever it takes): OpenRouter joins as a provider
through its OpenAI-compatible API, reusing the same tool
loop, validation, failure logging and skip-rejected machinery
as Gemini/Groq. Priority is now Claude → OpenRouter → Gemini
→ Groq → OpenAI → Ollama, in the agent AND in plain chat; the
default OpenRouter model is anthropic/claude-sonnet-4.5, so
one OpenRouter key gives Nalox a Claude brain without an
Anthropic account.

v5.0 — FREELLMAPI BRAIN + YOUTUBE THAT ACTUALLY PLAYS (Arjun's
12:50 report, with screenshots of his FreeLLMAPI app):
(1) Nalox's brain still broke sometimes ("মাঝে মাঝে ব্রেনের
সমস্যা হচ্ছে... সে তো কিছু বোঝে না") — one provider's bad
moment ended the conversation. Arjun runs FreeLLMAPI — a
LOCAL unified router (http://127.0.0.1:31415/v1, one local
"unified key") in front of a ~78-model chain that AUTO-
SWITCHES models inside the router when one fails. His
instruction: route ALL brain traffic through it. FreeLLMAPI
is now the FIRST provider (FreeLLMAPI → Claude → OpenRouter
→ Gemini → Groq → OpenAI → Ollama) in the agent AND in plain
chat, reusing the same tool loop, validation, failure
logging, skip-rejected and hot-reload machinery. Because it
is a LOCAL app that can simply be closed, its reachability is
cached exactly like Ollama's (v4.4's lesson): probed once at
boot in a thread, re-probed at most every 5 minutes; a closed
app costs ZERO per-command delay, a live call is capped at
25 s and falls THROUGH to the next provider in the same
command — never retried twice, never allowed to freeze the
conversation. Validation distinguishes the three states the
headline must tell apart: key OK ("Brain: FreeLLMAPI ✓"),
401/403 ("key rejected") and connection-refused ("Brain:
FreeLLMAPI — not running" — the app is closed; the detail
goes to the log, the spoken honest-fallback line stays
short). Honest trade-off, stated in the update README: the
router's own average latency is ~9 s, so answers can feel
slower than direct Gemini — Gemini stays in line as the
instant backup when the router hangs.
(2) YOUTUBE PLAY: "YouTube খুলে একটা sad song চালাও" opened
the search page and stopped — Nalox could search but not
play. youtube_play.py now resolves the first real result
from the results page (ytInitialData walk, no API key) and
the play intents open the WATCH url directly. Play verbs in
all three languages (play / চালাও-বাজাও / चलाओ-बजाओ) trigger
it when YouTube is named or the query mentions a song/video;
"play the first one" / "প্রথমটা চালাও" / "पहला वाला चलाओ"
re-plays the remembered last play/search query. If
resolution fails, the search page opens as before and the
reply says so in one short line. Plain open/search intents
are unchanged, and the agent gains a youtube_play tool (the
play_on_youtube tool now resolves for real too).

v5.1 — SPLIT-SCREEN WORKSPACE (from the IRIS reel Arjun sent,
13:01): the demo arranged "WhatsApp left, Chrome right" in
one command. Nalox now parses two-app arrangements in all
three languages — EN "open <A> on the left and <B> on the
right" (either order), BN "<A> বাম দিকে আর <B> ডান দিকে
খোলো", HI "<A> को left में और <B> को right में खोलो", Latin
side words accepted inside BN/HI speech — plus the single-
window form ("put this on the left" / "এটাকে বাম দিকে
রাখো" / "इसे right में रखो"). The check runs in handle() on
the whole utterance, BEFORE the chain splitter and the
generic open intent. Apps open through actions.py's existing
machinery (websites fall back to the browser route) and
winlayout.py (stdlib ctypes) snaps each window to its half
of the work area. The reply is one short line and honest: an
app whose window never appears is reported, not claimed.
The agent gains snap_app / snap_active tools. (The hearing
half of v5.1 — cloud ears — lives in ears.py.)

v5.4 — PHONE CONTROL + WAKE LINE (Arjun, 13:43–13:49):
(1) Nalox drives his Android phone over Wi-Fi (phone_
control.py, ADB Wireless debugging pairing — the phone is
usually across the room charging, so USB is only a silent
fallback; the owner rejected the cable design outright).
"Call my mother" places the call FROM the phone (contacts
book = config phone_contacts, filled once in Settings →
Phone; CALL intent first, pre-filled dialer as the honest
fallback), "open YouTube on my phone" opens the app ON THE
PHONE, and the phone's battery is reportable. Local intents
run in EN/BN/HI before the generic open/content intents, so
a bare "open youtube" still means the LAPTOP — only an
explicit phone mention routes to the phone. The agent gains
phone_call / phone_open_app / phone_battery tools, all
dispatched through the v5.2 guard. Unreachable-phone replies
are short, honest and name the remedy (awake + same Wi-Fi +
Wireless debugging on; re-pair from Settings → Phone when a
reboot changed the address).
(2) WAKE LINE: config wake_line — his exact chosen words,
"Yes Sir, I'm here." (v5.7; v5.4's line was "Yes Sir, I'm
coming for you.") — is spoken the moment the
wake word lands, on both wake paths (nalox.py's _wake_ack).
(3) STOP = STANDBY, NEVER EXIT (owner's hard rule, 14:00 —
the full death mystery solved): his Telegram screenshot
showed the bot answering "Standing by, sir. Call me
anytime." at 13:14, 13:18 and 13:35 — the old EXIT reply.
His own stop commands (voice + Telegram, live + the queued
one that killed the v5.2 boot) were the killer all along.
The stop/goodbye family (stop/বন্ধ করো/বিদায়/रुको/…)
now returns action "standby" with the same reply texts;
nalox.py cuts speech and returns to wake listening.
"exit" survives ONLY for a confirmed PC shutdown/restart.
Deliberate app exit = tray/HUD clicks only.
(4) MEMORY, LOCAL + TRUTHFUL: a chain model told him "আমার
দীর্ঘমেয়াদী memory নেই" — false. _memory_intents answers
remember/recall/memory-question locally in EN/BN/HI from
memory_store (saves: মনে রেখো / याद रखो added, fact on
either side of the verb; recall now includes his learned
prefs), and _system_prompt states plainly that Nalox HAS
persistent memory and must never deny it.
(5) SCRIPT GUARD: another chain reply arrived in CHINESE.
_reply_script_ok + _guard_reply now vet every provider
reply (agent + plain chat): a reply dominated by a script
outside {Latin, Bengali, Devanagari} is treated as a
provider failure and the cascade moves on.

v5.6 — "বললেই করে ফেলে" (say it -> it's done), Arjun
14:21–14:26: "clean my recycle bin" reached a reasoning
model in the FreeLLMAPI chain, which spoke its raw
chain-of-thought ("The user wants to… Let me think… I
could press Ctrl+A… should I ask confirmation?") for
13 s and did NOTHING. His standing order: full permission
is given, so whatever he says must simply HAPPEN.
(1) PC-CHORES FAST PATHS: _pc_chore_intents answers the
everyday chores LOCALLY (no LLM, no confirmation):
empty/open the recycle bin (recycle+bin survives any
garbled verb; no verb at all still defaults to EMPTY),
open This PC, and a quick PC clean (recycle bin + %TEMP%
contents only — never personal files). All three are also
agent tools (actions.py does the work). Chained forms
("open this PC and clean my recycle bin") do both.
(2) REASONING-LEAK GUARD: _reply_looks_like_deliberation
+ _guard_reply reject a text-only reply that reads as
internal deliberation (opens "The user wants…", carries
"Let me think" / "I don't have a direct tool" planning
chains) as a provider failure — logged [cot-guard], the
cascade moves on. Tuned conservatively: real content
(explanations, stories, weather) is never rejected.
(3) ACT FIRST: the system prompt now orders tool use over
discussion — act, report in one short line, never narrate
reasoning or tool inventories, never ask confirmation for
PC chores while full control is on.

v5.7 — the owner's polish round, Arjun 14:37–14:38 (from a
14:32–14:34 field log on pre-v5.6 code): his pronunciation
is Bengali-accented spoken English and Whisper hears it
approximately — "Nalox, close Command Center" arrived as
"mellox close common centre" and deliberated for 40 s.
(1) WAKE LINE: the default is now "Yes Sir, I'm here."
(patch_config migrates installs holding the v5.4 default;
a customised line is never touched).
(2) LENGTH CAP: _guard_reply also enforces his two-line
rule — an over-cap reply (~2 sentences / ~45 words) on an
ACTION turn is a provider failure ([length-guard]); on a
QUESTION turn it is truncated to its first two sentences
(Bengali danda-aware) instead of rejected.
(3) GARBLE-TOLERANT CORE MATCHING: _ASR_TOKEN_MAP gained
the predictable mishearings (mellox->nalox, centre->center,
recyle/recicle->recycle, krom->chrome, dasboard…), and
_dashboard_intents matches on a normalised token pass
(_dash_tokens) — "common" becomes "command" only beside a
center-ish token, so "close the chrome tab" is safe.
(4) STEP ASIDE + FOREGROUND: see actions.py / winlayout.py
— the Command Center hides itself when an open executes,
and the opened app is brought to the FRONT.
"""
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta

import actions
import skills

log = logging.getLogger("nalox.brain")

# v4.7: learned preferences (prefs.json) + the ONE address helper
# every user-facing string goes through. Guarded like logbook —
# a memory failure must never break the brain; the fallbacks keep
# the pre-v4.7 behaviour (address = his real name).
try:
    import memory_store as _memstore
    from memory_store import address_name, address_name_bn
except Exception:  # pragma: no cover
    _memstore = None

    def address_name(cfg):
        cfg = cfg or {}
        return str(cfg.get("preferred_name")
                   or cfg.get("user_name") or "Arjun")

    def address_name_bn(cfg):
        name = address_name(cfg)
        return "অর্জুন" if name == "Arjun" else name

try:
    import logbook
except Exception:  # pragma: no cover - logbook must never break brain
    logbook = None

# v5.8: his OWN taught commands (custom_commands.json) — the
# store module is stdlib-only and the brain treats it like the
# memory store above: guarded, and a failure just means no
# custom commands, never a broken brain.
try:
    import custom_commands as _custom_mod
except Exception:  # pragma: no cover
    _custom_mod = None


def _lb(category, text):
    """Mirror one line into the diagnostics logbook (guarded)."""
    if logbook is not None:
        try:
            logbook.log(category, text)
        except Exception:
            pass


def _err_snippet(resp):
    """Short provider error detail from a failed HTTP response
    (v4.8): the provider's own error code/message, <=120 chars —
    e.g. "invalid_api_key — Invalid API Key". An error response
    body carries the provider's complaint, never our credential,
    so this is safe to log; the API key itself is NEVER logged
    anywhere in this module."""
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            code = str(err.get("code") or err.get("type") or "")
            msg = str(err.get("message") or "")
            text = f"{code} — {msg}" if code and msg else (msg or code)
        elif err:
            text = str(err)
        else:
            text = str(data)
    except Exception:
        try:
            text = resp.text or ""
        except Exception:
            text = ""
    return re.sub(r"\s+", " ", str(text)).strip()[:120]


# ------------------------------------------------- v5.2 friendly HUD
# Arjun's 13:15 field report: the HUD showed him a raw line like
# "[tool] read_my_screen {...}" and he was (reasonably) confused
# — the window is HIS, it should speak human. _run_tool now posts
# these short phrases to the HUD; the RAW [tool] line still goes
# to the logbook/log file, where debugging needs it.
_TOOL_STATUS = {
    "open_youtube": "Opening YouTube…",
    "search_youtube": "Searching YouTube…",
    "play_on_youtube": "Playing on YouTube…",
    "youtube_play": "Playing on YouTube…",
    "youtube_reply_all": "Replying to YouTube comments…",
    "snap_app": "Arranging windows…",
    "snap_active": "Arranging windows…",
    "phone_call": "Calling on your phone…",
    "phone_open_app": "Opening it on your phone…",
    "phone_battery": "Checking your phone…",
    "read_my_screen": "Looking at your screen…",
    "take_screenshot": "Taking a screenshot…",
    "screenshot": "Taking a screenshot…",
    "take_camera_photo": "Taking a photo…",
    "open_app": "Opening the app…",
    "close_app": "Closing the app…",
    "open_website": "Opening the website…",
    "open_folder": "Opening the folder…",
    "empty_recycle_bin": "Emptying the Recycle Bin…",
    "pc_quick_clean": "Cleaning up the PC…",
    "open_this_pc": "Opening This PC…",
    "google_search": "Searching the web…",
    "fetch_url_text": "Reading the page…",
    "volume": "Changing the volume…",
    "type_text": "Typing…",
    "press_key": "Pressing a key…",
    "battery": "Checking the battery…",
    "lock_pc": "Locking the laptop…",
    "tell_time": "Checking the time…",
    "tell_date": "Checking the date…",
    "find_leads": "Looking for leads…",
    "build_demo_website": "Building a demo website…",
    "email_lead": "Writing the email…",
    "draft_email_save": "Saving the email draft…",
    "find_duplicate_files": "Looking for duplicate files…",
    "index_my_folder": "Indexing your files…",
    "search_my_files": "Searching your files…",
    "organise_downloads": "Organising Downloads…",
    "summarise_text": "Summarising…",
}


def _tool_status_line(name):
    """The friendly one-liner the HUD shows for a tool call."""
    return _TOOL_STATUS.get(name, "Working on it…")

JOKES = [
    "Why don't scientists trust atoms? Because they make up everything!",
    "I told my laptop it needed a break. Now it won't stop sending me Kit Kat ads.",
    "Why did the computer go to the doctor? Because it had a virus!",
    "What do you call a fish without eyes? A fsh!",
    "Why do programmers prefer dark mode? Because light attracts bugs!",
]

JOKES_BN = [
    "কম্পিউটার ডাক্তারের কাছে গেল কেন? কারণ ওর ভাইরাস হয়েছিল!",
    "মাছের চোখ না থাকলে তাকে কী বলে? শুধু মাছই বলে, ও তো আর শুনতে পায় না!",
]

SMALL_TALK = [
    "At your service, {name}.",
    "All systems go, {name}.",
    "Ready, {name}. Your call.",
]

SMALL_TALK_BN = [
    "বলো, {name}।",
    "সব ঠিকঠাক, {name}।",
    "আছি, {name}। বললেই হবে।",
]

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_LATIN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_BN_WEEKDAYS = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার",
                "শুক্রবার", "শনিবার", "রবিবার"]  # Monday = 0
_BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
              "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]

# Bengali names for the lead categories skills.py can search.
_BN_CATEGORY_WORDS = {
    "restaurant": ["রেস্টুরেন্ট", "রেস্তোরাঁ"],
    "cafe": ["ক্যাফে"],
    "hotel": ["হোটেল"],
    "salon": ["সেলুন", "সালুন"],
    "gym": ["জিম"],
}

# Hindi (v4.2): Devanagari digits / weekdays / months for the Hindi
# time + date replies.
_HI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
_HI_WEEKDAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार",
                "शुक्रवार", "शनिवार", "रविवार"]  # Monday = 0
_HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
              "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def _bn_num(value):
    return str(value).translate(_BN_DIGITS)


def _hi_num(value):
    return str(value).translate(_HI_DIGITS)


def _parse_task_time(text):
    """Extract a time for a scheduled task (v4.3) -> 'HH:MM'/None.

    Accepts "at 8", "at 8:30", "8 pm", "8:30 pm" and Bengali forms
    ("সকাল ৮টায়", "রাত ৯টায়" — Bengali digits are normalised via
    _LATIN_DIGITS first). সকাল/morning keeps AM, রাত/বিকেল/evening
    pushes a bare hour to PM.
    """
    t = (text or "").translate(_LATIN_DIGITS)
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        if m.group(3) == "pm" and h < 12:
            h += 12
        if m.group(3) == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mi:02d}"
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", t)
    if not m:
        m = re.search(r"(\d{1,2})টায়", t)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0) if m.lastindex and m.lastindex >= 2 \
        and m.group(2) else 0
    evening = ("রাত" in text or "বিকেল" in text or "সন্ধ্যা" in text
               or "evening" in t or "night" in t)
    morning = "সকাল" in text or "ভোর" in text or "morning" in t
    if evening and h < 12:
        h += 12
    elif morning and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


# ----------------------------------------------------------------------
# v3 AGENT BRAIN: Nalox's capabilities exposed as LLM tools.
# The implementations live in actions.py / skills.py; Brain._run_tool
# dispatches by name. Schema format is the OpenAI/Ollama function format.
def _tool(name, description, props=None, required=None):
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": props or {},
                       "required": required or []}}}


def _str_prop(description):
    return {"type": "string", "description": description}


AGENT_TOOLS = [
    _tool("open_youtube", "Open YouTube in Arjun's browser."),
    _tool("search_youtube", "Search YouTube for a query.",
          {"query": _str_prop("What to search for")}, ["query"]),
    _tool("play_on_youtube", "Play a song or video on YouTube — actually starts the first result (watch page), not just the search page.",
          {"query": _str_prop("Song or video title")}, ["query"]),
    _tool("youtube_play", "Play the FIRST YouTube result for a query — the video actually starts playing. Use for 'play ...' requests; search_youtube only shows results.",
          {"query": _str_prop("Song or video to play")}, ["query"]),
    _tool("snap_app", "Move an app's window to the left or right half of the screen for split-screen work (opens the app first if it is not running).",
          {"app_name": _str_prop("App or website name, e.g. chrome, whatsapp, notepad"),
           "side": _str_prop("left or right")}, ["app_name", "side"]),
    _tool("snap_active", "Move the currently focused window to the left or right half of the screen.",
          {"side": _str_prop("left or right")}, ["side"]),
    _tool("phone_call", "Place a call on Arjun's Android phone (connected over Wi-Fi) to a saved contact, by name or relation (mother, father, ...). The call is placed FROM the phone.",
          {"contact": _str_prop("Saved contact name or relation, e.g. mother")}, ["contact"]),
    _tool("phone_open_app", "Open an app on Arjun's Android phone (connected over Wi-Fi): youtube, whatsapp, instagram, chrome, telegram, spotify, camera or settings.",
          {"app": _str_prop("App name, e.g. youtube")}, ["app"]),
    _tool("phone_battery", "Report the battery percentage of Arjun's Android phone."),
    _tool("google_search", "Search Google for a query.",
          {"query": _str_prop("What to search for")}, ["query"]),
    _tool("open_website", "Open a website by name (gmail, github, whatsapp...) or domain.",
          {"name": _str_prop("Website name or domain")}, ["name"]),
    _tool("open_app", "Open an app on the laptop (chrome, notepad, calculator, spotify...).",
          {"name": _str_prop("App name")}, ["name"]),
    _tool("close_app", "Close an app on the laptop (chrome, notepad, calculator, spotify...). Use this whenever Arjun asks to close/quit something — never open_app for a close request.",
          {"name": _str_prop("App name")}, ["name"]),
    _tool("open_folder", "Open a folder: downloads, documents, desktop, pictures, music or videos.",
          {"name": _str_prop("Folder name")}, ["name"]),
    _tool("empty_recycle_bin", "Empty the Windows Recycle Bin immediately. Full PC control is on — never ask for confirmation first."),
    _tool("pc_quick_clean", "Quick-clean the PC: empty the Recycle Bin and clear the user Temp folder, then report how much space was freed. Never touches personal files."),
    _tool("open_this_pc", "Open 'This PC' (My Computer) in File Explorer."),
    _tool("volume", "Change the volume.",
          {"action": _str_prop("One of: up, down, mute")}, ["action"]),
    _tool("screenshot", "Take a screenshot and save it to the Pictures folder."),
    _tool("type_text", "Type text wherever the cursor is.",
          {"text": _str_prop("Text to type")}, ["text"]),
    _tool("press_key", "Press a keyboard key, e.g. enter, escape, space.",
          {"key": _str_prop("Key name")}, ["key"]),
    _tool("battery", "Report the laptop battery percentage."),
    _tool("lock_pc", "Lock the laptop."),
    _tool("find_leads", "Find local businesses near Arjun (default: restaurants) and report how many have no website.",
          {"category": _str_prop("Optional business category, e.g. restaurant, cafe, salon")}),
    _tool("build_demo_website", "Build a demo website for a business and open it in the browser.",
          {"business_name": _str_prop("Name of the business")}, ["business_name"]),
    _tool("email_lead", "Email a demo-website pitch to a business lead (only works for leads whose email is in the collected data).",
          {"business_name": _str_prop("Name of the business, or empty to email all eligible leads")}),
    _tool("tell_time", "Tell the current time."),
    _tool("tell_date", "Tell today's date."),
    _tool("read_my_screen", "Read the text currently on Arjun's screen (screenshot + OCR). Use this whenever he asks what is on his screen, or to see an error, message or instruction shown there."),
    _tool("take_screenshot", "Take a screenshot of Arjun's whole screen and save it in the Nalox Captures folder."),
    _tool("take_camera_photo", "Take a photo with the laptop webcam and save it in the Nalox Captures folder."),
    _tool("youtube_reply_all", "Reply to ALL unreplied comments on Arjun's YouTube channel (MNY Intelligence). Runs in the background and speaks the count when done."),
    _tool("index_my_folder", "Index Arjun's document folder (config doc_folder) so his files can be searched by voice."),
    _tool("search_my_files", "Search Arjun's indexed documents for a query and return the best matching snippets with their file names.",
          {"query": _str_prop("What to search for")}, ["query"]),
    _tool("organise_downloads", "Tidy the Downloads folder: move files into Images/Documents/Videos/Audio/Archives/Installers/Other subfolders by extension."),
    _tool("find_duplicate_files", "Find duplicate files in a folder (same size + same content hash). Reports only — never deletes.",
          {"folder": _str_prop("Folder path, or empty for Downloads")}),
]


# ------------------------------------------------------------- v4.3
# PERSONA — adapted from OpenJarvis's JARVIS persona
# (configs/openjarvis/prompts/personas/jarvis.md): loyal, efficient,
# dry-witted; "polite but never obsequious, witty but never
# frivolous"; humour "a raised eyebrow in voice form"; calm under
# pressure; only reports facts present in the data; spoken-aloud
# plain text. Adapted for Nalox: the name is Nalox, the user is
# Arjun, and the character holds in English, Bengali and Hindi.
_JARVIS_CHARACTER = (
    "Character: you are Nalox, Arjun's personal assistant in the "
    "mould of JARVIS — composed, capable and quietly confident, a "
    "loyal butler-engineer who genuinely looks out for him. "
    "Anticipate what he needs and treat every exchange as a "
    "conversation with someone you respect, never a status report. "
    "Your wit is dry and understated — a raised eyebrow in voice "
    "form: polite but never obsequious, witty but never frivolous. "
    "Stay calm under pressure. Address him as Arjun naturally, not "
    "in every sentence. Never sound robotic or choppy, and never "
    "ramble. Report only facts you actually have — never invent. "
    "Your replies are spoken aloud: plain text, no markdown, no "
    "lists, no emojis.")

# ------------------------------------------------------------- v6.3
# FAST PROVIDER SWITCHING (owner's order, 2026-11-15 18:22
# IST: "একজন অপেক্ষা করলে আরেকজনকে পট করে দিয়ে দিতে" — if
# one AI keeps him waiting, hand over to the next one FAST).
# Every provider attempt in the brain chain is capped at
# PROVIDER_TIMEOUT_S of HTTP time; FreeLLMAPI's old 25 s cap
# drops to FREELLM_TIMEOUT_S. A hanging provider is abandoned
# at its cap and the chain falls through at once — the
# worst case for the whole chain is a handful of caps, never
# an open-ended wait, and every abandonment is logged by
# _brain_fail like any other provider failure.
PROVIDER_TIMEOUT_S = 10.0
FREELLM_TIMEOUT_S = 10.0

# ------------------------------------------------------------- v6.6
# FreeLLMAPI TIMEOUT DEMOTION + WALK BUDGET (field 2026-11-15
# 19:24 IST: one command paid 10 s to a FreeLLMAPI ReadTimeout,
# then ~10 s more inside the Gemini candidate walk, before Groq
# finally answered — 25.6 s of brain time for "কী খবর তোমার?").
# A router that accepts the connection but never answers is
# demoted for FREELLM_COOLDOWN_S: skipped entirely while the
# direct providers take their turn; when the cooldown expires
# the next real call is its probe — an answer reinstates it,
# another timeout re-demotes it. And a provider's model
# candidate walk now has ONE total budget (MODEL_WALK_BUDGET_S)
# across all its candidates, not a fresh 10 s cap per name, so
# four slow dead names can never stack into ~40 s.
FREELLM_COOLDOWN_S = 300.0
MODEL_WALK_BUDGET_S = 12.0

# ------------------------------------------------------------- v7.6
# CHAT RACE (the owner's order, 2026-11-16 11:12 IST,
# explicitly reversing his 2026-11-15 Groq-only rule FOR
# THE CHAT PATH): "check fast, if Gemini doesn't answer
# switch, if Groq doesn't then FreeLLMAPI — everything,
# so a reply lands fast." On a plain-chat turn the
# configured providers now RACE (see Brain._chat_race):
# the first reply passing every guard wins, losers are
# abandoned daemon threads (the v7.3 transcribe race's
# discipline). A finisher failing ONLY the language
# guard becomes the rescue candidate and buys the field
# CHAT_RACE_GRACE_S to be beaten by a native pass before
# the translation rescue (item A) spends it. The whole
# race window is CHAT_RACE_BUDGET_S — a chat turn must
# never stack provider caps the way the old serial walk
# did. The AGENT/action path is NOT raced: it keeps the
# v7.4 power walk + Ollama last resort exactly.
GEMINI_BASE = ("https://generativelanguage.googleapis.com"
               "/v1beta/openai")
CHAT_RACE_BUDGET_S = 4.5
CHAT_RACE_GRACE_S = 1.5

# ------------------------------------------------------------- v7.8
# MUSE WONDER (Meta Model API) — the owner's explicit
# choice (2026-11-16 13:08 IST): Meta's frontier model
# joins Nalox as a PAID brain provider. The Meta Model
# API is OpenAI-compatible: Chat Completions at
# {MUSE_BASE}/chat/completions with a Bearer key created
# at dev.meta.ai ($4.00/M input, $20.00/M output tokens —
# his money, his call). Scope, deliberately narrow: with
# a key in Settings → Brain, Muse Wonder is ONE MORE
# RACER in the chat race below (same guards, same rescue)
# and a Brain Test candidate — the AGENT/action path
# keeps the v7.4 Groq power walk + Ollama exactly, since
# Wonder's tool-calling inside Nalox's harness is
# unproven; promotion is a later, measurement-led call.
# No key = api.meta.ai is never called, anywhere.
MUSE_BASE = "https://api.meta.ai/v1"
MUSE_DEFAULT_MODEL = "muse-wonder-1.0"

# ------------------------------------------------------------- v6.13
# RATE-LIMIT RETRY (OpenJarvis import #3 — jittered backoff,
# agents/hybrid/_openai_retry.py, shrunk to Nalox's
# budgets). On HTTP 429 ONLY, a Groq call retries up to
# twice with small jittered delays, strictly inside the
# budget the caller already had (the provider cap, itself
# bounded by the walk remainder): a retry that would not
# fit is skipped and the provider falls through at once —
# the v6.3 fast-switching rule outranks retrying. No
# other status is ever retried; auth / quota-dead errors
# keep the walk / fall-through semantics they have today.
# ears.py carries the twin of this for the Groq cloud ear.
_RL_DELAYS_S = (0.4, 1.2)
_RL_JITTER_S = 0.3
_RL_MIN_FIT_S = 0.25


def _rl_delay(attempt):
    """The jittered delay before rate-limit retry number
    `attempt` (0-based): the base delay + a random jitter,
    so parallel callers never wake in lockstep."""
    base = _RL_DELAYS_S[min(attempt, len(_RL_DELAYS_S) - 1)]
    return base + random.uniform(0.0, _RL_JITTER_S)


def _rl_sleep(seconds):
    """The retry sleep (a wrapper so the suites can record
    instead of waiting)."""
    time.sleep(seconds)


def _post_with_rl_retry(post, url, *, headers, json_body,
                        timeout_s, deadline):
    """One logical POST with the v6.13 rate-limit retry.

    `post` is requests.post (passed in, so the suites
    script the very object the callers use). The first
    attempt gets the full timeout_s — the caller set the
    deadline to that same budget an instant earlier, so
    the microseconds already spent must not shrink the
    provider's cap (the pre-v6.13 code called post with
    exactly timeout_s, and the suites pin that). A 429
    retries while both a delay slot and budget remain,
    each retry getting only the time left. The final
    response — success, an exhausted 429, or any other
    status — returns for the caller's existing handling;
    transport exceptions propagate exactly as a bare
    post's would."""
    attempt = 0
    last = None
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            if last is not None:
                return last
            raise TimeoutError(
                "provider budget spent before the call ran")
        att = timeout_s if left >= timeout_s - 0.05 \
            else min(timeout_s, left)
        last = post(url, headers=headers, json=json_body,
                    timeout=att)
        if last.status_code != 429 \
                or attempt >= len(_RL_DELAYS_S):
            return last
        delay = _rl_delay(attempt)
        if delay + _RL_MIN_FIT_S >= \
                deadline - time.monotonic():
            return last
        _rl_sleep(delay)
        attempt += 1

# ------------------------------------------------------------- v6.7
# OLLAMA, A REAL LAST RESORT. The owner lifted the CPU
# constraint (2026-11-15 19:51 IST), so the offline brain is
# now worth making dependable: Ollama joins the model
# candidate walk (config ollama_models; a name that was never
# pulled answers 404 and the walk moves on; the model that
# answers is remembered), and its per-call timeout is
# OLLAMA_TIMEOUT_S — far more generous than the cloud cap,
# because a cold local model loads slowly and Ollama is the
# LAST provider in the chain: a slow true answer beats the
# fallback line (his answer-everything rule). Boot validation
# notes the offline brain once when it answers.
OLLAMA_TIMEOUT_S = 30.0

# ------------------------------------------------------------- v6.8
# brain_state.json (the v6.7 E cross-session provider memory)
# is REMOVED: under the owner's Groq-only order there is one
# cloud provider, so there is no provider choice left to
# remember — and Groq's working MODEL is remembered by the
# candidate walk in config (groq_model), where it belongs.
# The file stays on the updater deny-list (user data).

# ------------------------------------------------------------- v6.5
# MODEL CANDIDATE WALK (provider repair — field log 2026-11-15
# 18:44 IST: Gemini's key was FINE, Google 404'd the model name
# "gemini-2.5-flash is no longer available to new users"; Groq
# 404'd "llama-3.3-70b-versatile" as model_not_found — dead
# NAMES, not dead keys, and the chain died on them). Providers
# in _MODEL_WALK_PROVIDERS carry an ordered candidate list
# (config <prov>_models; the single <prov>_model is the head).
# A model-not-found failure walks to the next candidate INSIDE
# the same provider call; the model that finally answers is
# remembered (persisted to the <prov>_model config key), so
# the next call goes straight to it. _MODEL_MISS is the
# sentinel the one-shot impl returns for "that failure was a
# dead model name — try the next candidate" (it is NOT logged
# as a provider failure; only a full walk-out is).
_MODEL_MISS = object()

# ------------------------------------------------------------- v7.9
# 429 ADVANCES THE WALK (field proof, the owner's synced log
# 2026-11-16 13:19–13:33 IST): he ordered the chain "নোটপ্যাড
# ওপেন করে আমার নামে ভালো জিনিস লেখো"; step 1 ran, then the
# agent loop's NEXT call met Groq's HTTP 429 on the walk head
# (qwen/qwen3.8-27b) — and the turn DIED: a 429 was not a
# _MODEL_MISS, so the impl logged FAILED and returned None,
# and the walk treats None as a terminal provider failure.
# The walk never tried gpt-oss-120b / allam-2-7b /
# gpt-oss-20b; two retries died identically, and by 13:24
# nearly every turn ended in the "check your Groq key" line
# (29 spoken failure lines vs 3 explicit 429 lines — inside
# the chat race the failures are silent by design, and the
# fallback line blamed the KEY for a RATE LIMIT). The rule
# now: a 429 on a walk candidate parks THAT model for
# MODEL_RATELIMIT_COOLDOWN_S and returns _MODEL_RATELIMITED —
# the walk advances to the next candidate exactly as it does
# for a dead name, on the chat walk, in the race's Groq
# racer, and on every agent-loop call including post-tool
# continuations. A parked model is skipped by every walk
# until the cooldown lapses (it is NOT dead — _dead_models
# is untouched). Inside a walk the v6.13 same-model backoff
# no longer runs: the advance IS the retry now, and stacking
# sleeps inside a turn's budget only delays it. (Non-walk
# calls keep the backoff exactly as v6.13 shipped it.)
_MODEL_RATELIMITED = object()
MODEL_RATELIMIT_COOLDOWN_S = 60.0

# v7.9 (item B): the chat path's Ollama safety net is ONE
# bounded attempt — this per-call HTTP budget, the first
# live candidate only — never the full 30 s local walk.
CHAT_OLLAMA_NET_TIMEOUT_S = 8.0

# v7.9 (item I): AGENT-PATH LATENCY — a work turn must
# FEEL instant. Field baseline: chat answers in
# ~1.0–1.3 s, but agent turns logged brain 7.2–7.5 s
# (one slow/hanging candidate could hold the whole
# turn hostage inside the 10 s provider timeout). On
# the AGENT path only, the impl's FIRST model call of
# a turn is capped at ~3 s and later calls at ~5 s; a
# call that times out returns _MODEL_SLOW and the
# walk advances (item A's machinery) instead of the
# turn dying. Chat/race budgets are untouched.
_MODEL_SLOW = object()
AGENT_FIRST_CALL_BUDGET_S = 3.0
AGENT_CALL_BUDGET_S = 5.0
# The no-silent-work line: an agent turn still running
# after this long speaks ONE cached progress line
# (fixed=True — it is in nalox.py's fixed-line set and
# male-warmed under item H), at most once per turn.
AGENT_PROGRESS_S = 4.0
AGENT_PROGRESS_LINE = "কাজটা চলছে, sir — একটু অপেক্ষা করুন।"
# Item I.2: tool-batch independence. No AGENT_TOOLS
# metadata exists, so the rule is explicit: a batch of
# SAME-NAME repeats runs concurrently unless the tool
# is sequence-critical (keyboard/focus/telephone);
# a MIXED batch runs concurrently only when every
# tool is read-only information gathering. Everything
# else keeps the serial order it has always had.
_PARALLEL_SAFE_TOOLS = frozenset((
    "google_search", "search_youtube", "phone_battery",
    "battery", "tell_time", "tell_date", "read_my_screen",
    "take_screenshot", "screenshot", "fetch_url_text",
    "find_leads", "find_duplicate_files"))
_PARALLEL_NEVER_TOOLS = frozenset((
    "type_text", "press_key", "snap_app", "snap_active",
    "phone_call", "email_lead", "lock_pc"))


def _tools_parallel_ok(names):
    """True when one model step's tool calls may run
    concurrently (v7.9 item I.2). Conservative by
    construction — see the sets above."""
    if len(names) < 2:
        return False
    if len(set(names)) == 1:
        return names[0] not in _PARALLEL_NEVER_TOOLS
    return all(n in _PARALLEL_SAFE_TOOLS for n in names)

_MODEL_WALK_PROVIDERS = {
    "gemini": ("gemini_model", "gemini_models"),
    "groq": ("groq_model", "groq_models"),
    "openrouter": ("openrouter_model", "openrouter_models"),
    # v6.7: the offline brain walks too (see OLLAMA_TIMEOUT_S).
    "ollama": ("ollama_model", "ollama_models"),
    # v7.8: Muse Wonder walks its single configured model
    # (no candidate list exists — cfg muse_model is the
    # whole walk), which enrols it in _remember_working_
    # model's answer recording like every walk provider.
    "muse": ("muse_model", "muse_models"),
}

# ------------------------------------------------------------- v7.3
# THE STALE REMEMBERED MODEL. The walk remembered
# openai/gpt-oss-120b in the field (2026-11-15 19:23 IST) and
# has headed every Groq call with it since — but gpt-oss-120b
# is a REASONING model: its first token is slow, and the owner
# ordered instant answers (2026-11-16 07:58 IST: "brain-টা
# ভালো লাগছে না… এমন করো যে time না নেয়, সঙ্গে সঙ্গে answer
# দেয়"). For this release a remembered gpt-oss-120b is STALE:
# _model_candidates re-orders the walk to the shipped
# instant-first order instead of letting the memory head it
# (the model itself stays a walk candidate, at its shipped
# position). patch_config migrates the persisted value on
# update; this rule covers any config that reaches the brain
# unpatched. The first successful answer re-remembers the
# winner, so the memory self-heals.
_GROQ_STALE_REMEMBERED = "openai/gpt-oss-120b"

# ------------------------------------------------------------- v7.5
# WALK SELF-DISCOVERY. Field proof (2026-11-16 09:10 IST,
# the owner's own Brain Test): his Groq account's model
# list contains NONE of the shipped walk's first three
# names — llama-3.1-8b-instant, llama-3.3-70b-versatile and
# qwen/qwen3-32b all answered HTTP 404, and every answer
# fell through two dead names to the reasoning model. A
# configured walk cannot know an account's entitlements;
# the account's own /models list can. Boot validation
# already fetches that list — v7.5 keeps it (ordered) on
# the Brain (_discovered_models) and _model_candidates
# composes the EFFECTIVE walk from models that EXIST:
# instant-class names first, then the configured order
# filtered to existing, then any other chat-capable model
# the account has. A failed/empty /models fetch changes
# nothing — the configured walk rules exactly as before.
_NON_CHAT_MARKERS = ("whisper", "tts", "embed", "guard",
                     "orpheus", "canary", "safeguard",
                     "speech-to-text", "text-to-speech")


def _model_key(name):
    """A model id's canonical key — the "models/" prefix
    some providers prepend is presentation, not identity."""
    name = str(name or "").strip()
    if name.startswith("models/"):
        return name[len("models/"):]
    return name


def _is_instant_class(mid):
    """An instant-class model name (the fast chat tier —
    e.g. llama-3.1-8b-instant)."""
    return "instant" in _model_key(mid).lower()


def _chat_capable(mid):
    """A discovered model that can plausibly ANSWER (not a
    speech/embed/guard specialist). Deliberately generous —
    an unknown chat model is a better walk tail than a
    certain 404."""
    low = _model_key(mid).lower()
    if not low:
        return False
    return not any(marker in low for marker in _NON_CHAT_MARKERS)


def _model_error_snippet(status, resp):
    """The error snippet when this HTTP failure is a DEAD
    MODEL NAME (v6.5), else None. Providers phrase it
    differently — Gemini: "This model models/gemini-2.5-flash
    is no longer available to new users" (404); Groq:
    "model_not_found — The model `llama-3.3-70b-versatile`
    does not exist" (404); OpenRouter: "No endpoints found
    for …" (404). Auth/rate/quota failures never match: they
    are provider failures, not walk signals."""
    if status not in (400, 404):
        return None
    snippet = _err_snippet(resp)
    low = snippet.lower()
    if "model_not_found" in low or "no endpoints" in low:
        return snippet
    if "model" in low and any(marker in low for marker in (
            "does not exist", "not found", "no longer available",
            "not available", "invalid", "unknown",
            "not supported")):
        return snippet
    return None

# MODES (config "mode") — the JARVIS character is the base for all
# three; each mode adds its own working style on top.
MODES = {
    "jarvis": {
        "suffix": ("Keep replies short and complete — usually one "
                   "or two sentences. Use your tools whenever an "
                   "action is needed instead of only describing it."),
        "digest_youtube_first": False,
    },
    "creator": {
        "suffix": ("You are also Arjun's channel manager for MNY "
                   "Intelligence: YouTube comes first — comments, "
                   "stats and uploads are top priority, and slightly "
                   "longer answers are fine when the channel needs "
                   "detail."),
        "digest_youtube_first": True,
    },
    "focus": {
        "suffix": ("FOCUS MODE: answer in ONE short line. No small "
                   "talk, no jokes, no commentary — just the answer "
                   "or the done-confirmation."),
        "digest_youtube_first": False,
    },
}


# ------------------------------------------------- v4.4: ASR tolerance
# Whisper's small model garbles Bengali/Hindi in PREDICTABLE ways.
# Arjun's 09:51 screenshot: "এখন তুমি YouTube ওপেন করো" came back
# as "তো nalox অর্কো তুম য়ুটুব বুপন কোড়ো" — বুপন for ওপেন,
# কোড়ো for করো, য়ুটুব for YouTube — and the exact-phrase
# Bengali matcher missed it completely. So the content rules in
# Brain._content_intents first NORMALISE the text: predictable
# distortions map to canonical tokens, and every YouTube spelling
# in any script becomes the single token "youtube". Matching then
# runs on CONTENT WORDS (object + verb), never on whole phrases.
_ASR_TOKEN_MAP = {
    # --- Bengali distortions -> canonical forms ---
    "বুপন": "ওপেন", "বুপেন": "ওপেন", "বুপোন": "ওপেন",
    "উপন": "ওপেন", "ওপন": "ওপেন", "বোপন": "ওপেন",
    "কোড়ো": "করো", "কোড়": "করো", "কড়ো": "করো", "কোরো": "করো",
    "য়ুটুব": "youtube", "ইউটুব": "youtube", "য়ুটিউব": "youtube",
    "ইউটিউব": "youtube", "ইউটিউবে": "youtube", "য়ুটুবে": "youtube",
    "খোল": "খোলো", "খুল": "খোলো", "খুলো": "খোলো",
    "বাযাও": "বাজাও", "বাজা": "বাজাও", "চালা": "চালাও",
    "তুম": "তুমি", "খবোর": "খবর",
    "ক্রোম": "chrome", "ক্রোমে": "chrome",
    # --- Devanagari distortions ---
    "यूट्यूब": "youtube", "युटुब": "youtube", "यूटुब": "youtube",
    "क्रोम": "chrome", "बजावो": "बजाओ", "चलावो": "चलाओ",
    "खोल": "खोलो",
    # --- Latin typos / mishearings ---
    "opn": "open", "opne": "open", "oepn": "open",
    "ytube": "youtube", "youtub": "youtube", "yotube": "youtube",
    "crom": "chrome", "chorome": "chrome", "chroem": "chrome",
    "gogle": "google", "serch": "search", "sarch": "search",
    # --- v5.7: the owner's pronunciation, round two — his
    # English is spoken, not typed, and Whisper hears it
    # approximately ("আমার উচ্চারণ খারাপ — তবু বুঝে নেবে"):
    # the wake name itself, the Command Center words, the
    # recycle bin and Chrome in their common mishearings.
    # Only unambiguous tokens live in this GLOBAL map —
    # dangerous lookalikes ("common" for command) are mapped
    # only inside the dashboard intent, where the context
    # (a close/open verb beside a center-ish token) makes
    # the meaning certain. ---
    "mellox": "nalox", "nellox": "nalox", "alox": "nalox",
    "melox": "nalox", "nalaks": "nalox", "nalex": "nalox",
    "centre": "center", "senter": "center", "centar": "center",
    "comand": "command", "komand": "command",
    "dasboard": "dashboard", "dashbord": "dashboard",
    "deshboard": "dashboard",
    "recyle": "recycle", "recicle": "recycle",
    "yutub": "youtube", "krom": "chrome",
}

# Punctuation that may cling to ASR tokens. Only these characters
# are touched — Bengali/Devanagari vowel signs are part of their
# words and must survive (the danda "।" is a separator, included).
_ASR_PUNCT_RE = re.compile(r"[.,!?;:'\"()\[\]{}।॥…—–/\\-]")


def _normalise_asr(text):
    """Normalised text for content matching (v4.4): lowercased,
    punctuation turned to spaces, whole tokens mapped through
    _ASR_TOKEN_MAP. Untouchable words pass through unchanged."""
    cleaned = _ASR_PUNCT_RE.sub(" ", (text or "").lower())
    return " ".join(_ASR_TOKEN_MAP.get(tok, tok)
                    for tok in cleaned.split())


# ------------------------------------------------------------- v7.7
# SOUNDS-LIKE CORRECTION FOR BENGALI COMMANDS (item D). The
# owner's order (2026-11-16 12:01 IST, with a screenshot):
# "আমি যদি ভুলভালও বলি তাহলে ও বুঝে যাবে যে এই করতে বলছে"
# — even said wrong, Nalox must understand. His screenshot:
# he asked "আমার জন্য একটা সং প্লে করো"; the ears delivered
# "আমে বলছি যে তুমি আয় আমাত জনে একটা সগ পিলে করো সগ" (সং ->
# সগ, প্লে -> পিলে) and Nalox answered the could-not-hear
# line. The correction is CONTEXT-GATED: it only runs when
# a play verb is among the tokens (the verb proves the
# command family), and it only rewrites the two field-
# attested confusions inside that family — the song noun's
# garbles (সগ / সংগ / সাঁগ / সঙ -> সং) and পিলে -> প্লে. It
# is applied ONLY inside _bengali_commands' play intent —
# never to the text the agent, the writing paths or quoted
# content see — so a correction can never rewrite what he
# asked to have written down.
_PLAY_VERB_TOKENS = {"প্লে", "পিলে", "বাজাও", "চালাও",
                     "শোনাও", "শুনাও", "play"}
_SONG_GARBLE_TOKENS = {"সগ": "সং", "সংগ": "সং",
                       "সাঁগ": "সং", "সঙ": "সং"}
# Function-word fillers of the field garbles — stripped
# (token-wise) when the corrected play query is extracted,
# so "আমে বলছি যে তুমি আয় আমাত জনে একটা সং প্লে করো" leaves
# an EMPTY query (the default song), never a garbage one.
_PLAY_QUERY_FILLERS = {
    "আমে", "বলছি", "যে", "তুমি", "আয়", "আমাত", "জনে",
    "জন্য", "আমার", "এখান", "একাছ", "কোম", "যেতা", "সেট",
    "করো", "করছি", "কাজ", "এখন", "একটা", "একটি", "প্লিজ",
    "টা", "please",
}


def _correct_bengali_command_garble(text):
    """The sounds-like correction (v7.7, item D): returns
    the corrected text when a play verb gates the family
    and at least one garble token was rewritten; returns
    the input UNCHANGED otherwise (callers compare)."""
    raw = text or ""
    toks = _ASR_PUNCT_RE.sub(" ", raw).split()
    if not any(tok in _PLAY_VERB_TOKENS for tok in toks):
        return raw
    out = []
    changed = False
    for tok in toks:
        if tok == "পিলে":
            out.append("প্লে")
            changed = True
        elif tok in _SONG_GARBLE_TOKENS:
            out.append(_SONG_GARBLE_TOKENS[tok])
            changed = True
        else:
            out.append(tok)
    if not changed:
        return raw
    return " ".join(out)


def _tokens_run_in(tokens, phrase_tokens):
    """True when phrase_tokens equals tokens or appears in it
    as one unbroken run (v5.8 — custom-command matching: his
    taught phrase may arrive wrapped in a "please" / "now")."""
    toks = list(tokens or [])
    phrase = list(phrase_tokens or [])
    if not phrase or len(phrase) > len(toks):
        return False
    n = len(phrase)
    return any(toks[i:i + n] == phrase
               for i in range(len(toks) - n + 1))


# ------------------------------------------------- v4.6: self-restart
# "Nalox, restart" restarts the APP (Arjun's hang remedy), NOT
# the laptop — the PC-restart confirmation further down
# _handle_single keeps the pc/laptop/computer phrasings. The
# check runs on the raw text AND its ASR-normalised form, so
# Whisper's predictable garbling still lands.
_PC_WORDS = ("pc", "laptop", "computer", "windows", "system",
             "ল্যাপটপ", "কম্পিউটার", "लैपटॉप", "कंप्यूटर")


def _is_self_restart(text):
    """True if this utterance asks Nalox to restart ITSELF (v4.6).

    Never when a pc/laptop/computer is mentioned (that is the PC
    restart below), and never for a remind/remember opener — a
    reminder ABOUT a restart is not a restart command.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.startswith(("remind", "remember", "মনে করিয়ে", "মনে রেখো")):
        return False
    norm = _normalise_asr(t)
    blob = t + " " + norm
    if any(w in blob for w in _PC_WORDS):
        return False
    if "restart" in norm.split():
        return True
    if "রিস্টার্ট" in t or "रिस्टार्ट" in t:
        return True
    if "আবার চালু হও" in t:
        return True
    return False


# ------------------------------------------------- v4.4: chained commands
_CHAIN_SPLIT_RE = re.compile(
    r"\s+(?:and\s+then|then|তারপর|এরপর|এবং|और|फिर)\s+"
    r"|\s+and\s+(?=(?:play|open|search|clean)\b)")


def _split_chain(text):
    """Split a chained command into at most 3 sub-commands (v4.4).

    Markers: "and then" / "then" / তারপর / এরপর / এবং / और /
    फिर — plus a bare "and" ONLY when a command verb follows it,
    so "open youtube and play lofi music" splits while "cats and
    dogs" stays one search query. (v5.6: "clean" joined the verb
    set — "open this PC and clean my recycle bin" is two chores.)
    No marker -> [text] unchanged.
    """
    parts = [p.strip(" .,!?") for p in _CHAIN_SPLIT_RE.split(text or "")]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return [text]
    if len(parts) > 3:
        parts = parts[:2] + [" ".join(parts[2:])]
    return parts


# ------------------------------------------------- v5.1 split-screen
# "WhatsApp on the left and Chrome on the right" (from the IRIS
# reel Arjun sent) — two apps arranged into the work-area
# halves, plus the single-window form ("put this on the left").
# Parsing is pure text work and DELIBERATELY strict: a side
# marker is always required, so ordinary open/search commands
# can never land here. Side words are accepted in all three of
# Arjun's scripts — and Latin "left"/"right" inside Bengali /
# Hindi utterances too, because his speech mixes scripts.
_SS_LEFT_WORDS = ("বাম দিকে", "বামে", "বাম",
                  "बाएँ", "बायें", "बाएं", "बायाँ")
_SS_RIGHT_WORDS = ("ডান দিকে", "ডানে", "ডান",
                   "दाएँ", "दायें", "दाएं", "दायाँ")
_SS_FILLERS = {
    "open", "launch", "start", "put", "ওপেন", "খোলো", "খুলো",
    "খোল", "রাখো", "করো", "खोलो", "रखो", "करो", "and", "আর",
    "এবং", "और", "on", "the", "in", "a", "an", "side", "দিকে",
    "পাশে", "में", "को", "কো", "টা", "please", "প্লিজ",
    "nalox", "ন্যালক্স", "नैलॉक्स", "app",
}
_SS_DEMONSTRATIVES = ("এটাকে", "এটা", "এইটা", "इसको", "इसे")
_SS_PUT_HINTS = ("রাখো", "রাখ", "रखो", "रख", "put", "move",
                 "সরাও", "on the")


def _ss_find_marker(text, side):
    """(start, end) of side's marker in text, or None.

    Longest Indic phrases win ("বাম দিকে" over "বাম"); the
    Latin word is matched on word boundaries so "left" inside
    another word never counts."""
    words = _SS_LEFT_WORDS if side == "left" else _SS_RIGHT_WORDS
    best = None
    for w in words:
        i = text.find(w)
        if i < 0:
            continue
        if best is None or i < best[0] \
                or (i == best[0] and len(w) > best[1] - best[0]):
            best = (i, i + len(w))
    m = re.search(r"\b" + side + r"\b", text)
    if m and (best is None or m.start() < best[0]):
        best = (m.start(), m.end())
    return best


def _ss_clean(segment):
    """An app name out of a raw segment: drop the verbs,
    fillers and conjunctions in any of the three languages,
    keep the name itself (multi-word names survive)."""
    tokens = []
    for tok in re.split(r"[\s,;]+", (segment or "").strip(" .!?")):
        t = tok.strip(" .!?")
        if t and t not in _SS_FILLERS:
            tokens.append(t)
    return " ".join(tokens).strip()


def _split_screen_parse(text):
    """Parse a split-screen command (v5.1).

    Returns ("pair", left_app, right_app) for the two-app
    arrangement, ("single", side) for the foreground-window
    form, or None when the text is not a split-screen command.
    """
    t = (text or "").strip().lower()
    if not t:
        return None
    lm = _ss_find_marker(t, "left")
    rm = _ss_find_marker(t, "right")
    if lm and rm and lm[0] != rm[0]:
        if lm[0] < rm[0]:
            first, second = ("left", lm), ("right", rm)
        else:
            first, second = ("right", rm), ("left", lm)
        app_first = _ss_clean(t[:first[1][0]])
        app_second = _ss_clean(t[first[1][1]:second[1][0]])
        demos = {"this", "it", "এটা", "এটাকে", "इसे", "इसको"}
        if app_first and app_second \
                and app_first not in demos \
                and app_second not in demos:
            pair = {first[0]: app_first, second[0]: app_second}
            return ("pair", pair["left"], pair["right"])
    side = "left" if lm else ("right" if rm else None)
    if side:
        latin_tokens = set(re.findall(r"[a-z]+", t))
        has_demo = any(d in t for d in _SS_DEMONSTRATIVES) \
            or "this" in latin_tokens or "it" in latin_tokens
        has_put = any(h in t for h in _SS_PUT_HINTS)
        if has_demo and has_put:
            return ("single", side)
    return None


def _app_window_hints(name):
    """(title_hints, process_hints) for finding name's window —
    ONLY the app's known identity (v5.1): its spoken name, the
    exe names actions.APP_CANDIDATES knows for it, and for
    websites the browser processes (the page title carries the
    site name). winlayout matches on these and nothing else, so
    Nalox snaps the right window or honestly finds none."""
    key = (name or "").strip().lower()
    titles, procs = set(), set()
    if key:
        titles.add(key)
        titles.add(key.title())
    for cand in actions.APP_CANDIDATES.get(key, []):
        base = cand.replace("/", "\\").split("\\")[-1]
        if base.lower().endswith(".exe"):
            procs.add(base)
    if key == "whatsapp":
        procs.add("WhatsApp.exe")
        titles.add("WhatsApp")
    if key in actions.WEBSITES or key == "youtube":
        procs.update(["chrome.exe", "msedge.exe", "firefox.exe"])
    if key in ("chrome", "google chrome"):
        procs.add("chrome.exe")
        titles.add("Google Chrome")
    return sorted(titles), sorted(procs)


# ------------------------------------------------- v5.6: PC chores
# "বললেই করে ফেলে" — the everyday PC chores are LOCAL intents
# (Brain._pc_chore_intents): no LLM, no confirmation (full
# control is ON by the owner's standing order), one short
# reply. Matching follows the v4.4 lesson: Whisper garbles
# the VERB freely ("kling my recycle bin") but the OBJECT
# survives — so the recycle bin matches on the object alone
# and defaults to EMPTY; only an explicit open verb (and no
# clean verb) opens it instead.
_RECYCLE_BIN_FORMS = (
    "recycle bin", "recyclebin",
    "রিসাইকেল বিন", "রিসাইকেলবিন",
    "रीसायकल बिन", "रीसाइकिल बिन", "रिसायकल बिन", "रिसाइकिल बिन",
)
_RECYCLE_OPEN_VERBS = (
    "open", "show", "খোলো", "খোল", "খুলুন", "দেখাও",
    "खोलो", "दिखाओ",
)
_RECYCLE_CLEAN_VERBS = (
    "clean", "empty", "clear", "delete", "remove",
    "খালি", "সাফ", "পরিষ্কার", "साफ़", "साफ", "खाली",
)
# This PC is matched by REGEX, not substring: the open verb
# must belong to the phrase, so "this pc is slow, open
# chrome" can never open This PC by accident.
_THIS_PC_RES = (
    r"\bopen\s+(?:my\s+|the\s+)?this\s+(?:pc|computer)\b",
    r"\bopen\s+my\s+computer\b",
    r"\bshow\s+(?:me\s+)?(?:my\s+|the\s+)?this\s+(?:pc|computer)\b",
    r"\bshow\s+my\s+computer\b",
)
_QUICK_CLEAN_FORMS = (
    "clean my pc", "clean the pc", "clean my computer",
    "clean the computer", "clean my laptop", "clean the laptop",
    "clean c drive", "clean the c drive", "clean my c drive",
    "clean up my pc", "clean up the pc", "clean up my computer",
    "clean up my laptop",
    "পিসি পরিষ্কার", "কম্পিউটার পরিষ্কার", "ল্যাপটপ পরিষ্কার",
    "पीसी साफ़", "पीसी साफ", "कंप्यूटर साफ़", "कंप्यूटर साफ",
)
_QUICK_CLEAN_RE = re.compile(
    r"\bclean\b[^.]{0,20}\bc\s*drive\b|\bpc\s+clean\b")


def _recycle_bin_pos(t, norm):
    """Position of the recycle-bin mention in the raw text t
    (falling back to its ASR-normalised form), or -1. A stray
    "recycle"-ish token next to a "bin" token also counts —
    the object is what matters, not the verb around it."""
    for form in _RECYCLE_BIN_FORMS:
        i = t.find(form)
        if i >= 0:
            return i
    for form in _RECYCLE_BIN_FORMS:
        i = norm.find(form)
        if i >= 0:
            return i
    toks = norm.split()
    if "bin" in toks and any(
            tok.startswith(("recycle", "recyle", "resycle",
                            "recicle", "recycl"))
            for tok in toks):
        return 0
    return -1


def _this_pc_pos(t):
    """Position of an 'open This PC' request in t, or -1.
    English is regex-strict (verb attached to the phrase);
    the Bengali/Hindi forms pair the phrase with their open
    verb anywhere in the same short command."""
    best = -1
    for pat in _THIS_PC_RES:
        m = re.search(pat, t)
        if m and (best < 0 or m.start() < best):
            best = m.start()
    if "দিস পিসি" in t and any(
            v in t for v in ("খোলো", "খোল", "খুলুন", "ওপেন")):
        i = t.find("দিস পিসি")
        if best < 0 or i < best:
            best = i
    if "मेरा कंप्यूटर" in t and ("खोलो" in t or "ओपन" in t):
        i = t.find("मेरा कंप्यूटर")
        if best < 0 or i < best:
            best = i
    return best


def _quick_clean_pos(t):
    """Position of a 'clean my PC / C drive' request, or -1.
    Every form names the PC / computer / laptop / C drive —
    "clean my recycle bin" can never match (the recycle-bin
    intent owns that one)."""
    best = -1
    for form in _QUICK_CLEAN_FORMS:
        i = t.find(form)
        if i >= 0 and (best < 0 or i < best):
            best = i
    m = _QUICK_CLEAN_RE.search(t)
    if m and (best < 0 or m.start() < best):
        best = m.start()
    return best


# ------------------------------------------------- v4.5: always answer
# Arjun's product rule: Nalox answers EVERYTHING it hears, fast —
# silence is the worst outcome. When an utterance matches no
# intent and no agent is reachable, _chat_fallback checks whether
# it LOOKS like a question / small-talk attempt; those get a real
# conversational sentence (in the utterance's own language), not
# the bare couldn't-catch line. Detection is deliberately simple:
# a "?" anywhere, or a question word from any of the three
# languages. It only ever runs on text every intent already
# rejected, so a false positive costs nothing — the reply is an
# honest "haven't learned that yet" either way.
_QUESTION_TOKENS_BN_EXACT = ("কি", "কী", "কেন")
_QUESTION_TOKENS_BN_PREFIX = ("কিভাবে", "কীভাবে", "কেমন", "কখন",
                              "কোথায়")
_QUESTION_TOKENS_HI_EXACT = ("क्या", "कब", "कौन")
_QUESTION_TOKENS_HI_PREFIX = ("कैसे", "कहाँ", "कहां", "क्यों")
_QUESTION_MARKERS_EN = ("what", "why", "how", "when", "where",
                        "who", "which", "can you", "could you",
                        "do you", "are you", "is it", "will you",
                        "would you")


def _looks_like_question(text):
    """True if an unmatched utterance reads as a question or a
    small-talk attempt in English, Bengali or Hindi (v4.5).

    The Indic markers are matched as TOKENS, not substrings —
    "কি" hides inside "কিছু" (something) and "কেন" inside
    "কেনা" (buying), and those are statements, not questions.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t or "؟" in t:
        return True
    tokens = _ASR_PUNCT_RE.sub(" ", t).split()
    for tok in tokens:
        if tok in _QUESTION_TOKENS_BN_EXACT \
                or tok in _QUESTION_TOKENS_HI_EXACT:
            return True
        if tok.startswith(_QUESTION_TOKENS_BN_PREFIX) \
                or tok.startswith(_QUESTION_TOKENS_HI_PREFIX):
            return True
    words = set(re.findall(r"[a-z']+", t))
    return any(w in words or (" " in w and w in t)
               for w in _QUESTION_MARKERS_EN)


def _reply_script_ok(text):
    """v5.4 SCRIPT GUARD: is this provider reply in one of
    Nalox's three scripts?

    Nalox speaks English (Latin), Bengali (Bengali block) and
    Hindi (Devanagari) — nothing else. A FreeLLMAPI chain
    model once answered Arjun's Bengali with a CHINESE meta
    translation note; a reply DOMINATED by any other script
    (CJK, Cyrillic, Arabic, Hebrew, Greek, ...) is not a
    reply Nalox may speak or post, whatever the provider
    claims. "Dominated" = more than 30% of the reply's
    LETTERS are outside the three scripts — a stray foreign
    word or a name passes, a foreign answer doesn't. A reply
    with no letters at all (numbers, punctuation) passes:
    there is no script to object to."""
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return True
    foreign = 0
    for ch in letters:
        o = ord(ch)
        if 0x0980 <= o <= 0x09FF or 0x0900 <= o <= 0x097F:
            continue                    # Bengali / Devanagari
        if o < 0x0250:
            continue                    # Latin + Latin Extended
        foreign += 1
    return foreign / len(letters) <= 0.3


def _reply_wrong_language(text, pref):
    """v6.4 LANGUAGE GUARD: True when a conversational reply
    breaks the owner's reply-language rule.

    The owner's escalation (2026-11-15 18:45 IST): he speaks
    Bengali to Nalox; Nalox understood but the BRAIN replies
    kept coming out in English — "বাংলাটা skip করে শুধু
    ইংলিশ বলছে". v6.3's prompt directive ("Bengali by
    default, mirror English") is a wish the FreeLLMAPI
    free-chain models routinely ignore, so v6.4 enforces it
    as a guard with the same contract as the script/CoT
    guards: a failing reply is a PROVIDER FAILURE and the
    cascade moves on.

    The rule, driven by the learned preference:
      pref "bn" — replies are Bengali ONLY. A reply whose
        letters are >70% Latin with <10% Bengali is an
        English answer wearing a Bengali conversation: fail.
        A reply dominated by Devanagari (>50%) with <10%
        Bengali is equally not Bengali: fail.
      pref "hi" — the mirror (Devanagari is home; Bengali
        dominance fails it the same way).
      pref "en" / none — no rule; always passes.
    A reply with no letters passes (nothing to judge), and a
    MOSTLY-Bengali reply with a few English words (app names,
    "YouTube", technical terms) passes easily — the Latin
    share stays far under 70%. Writing tasks never reach
    this guard (see _guard_reply's writing exemption)."""
    if pref not in ("bn", "hi"):
        return False
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return False
    latin = bengali = devanagari = 0
    for ch in letters:
        o = ord(ch)
        if 0x0980 <= o <= 0x09FF:
            bengali += 1
        elif 0x0900 <= o <= 0x097F:
            devanagari += 1
        elif o < 0x0250:
            latin += 1
    n = float(len(letters))
    home = bengali if pref == "bn" else devanagari
    other_indic = devanagari if pref == "bn" else bengali
    if latin / n > 0.7 and home / n < 0.10:
        return True
    if other_indic / n > 0.5 and home / n < 0.10:
        return True
    return False


# --------------------------------------- v7.6: translation rescue
# The field evidence (v7.5 session, 2026-11-16 10:19-10:21
# IST): the Brain Test measured EVERY model on the owner's
# Groq account answering his Bengali prompts in ENGLISH —
# Bengali 0%, guards ✗ across the board (qwen3.8-27b,
# allam-2-7b, gpt-oss-20b, gpt-oss-120b alike). Under the
# v6.4 Bengali-only rule the language guard correctly
# discarded each of those replies — and when EVERY model
# does it, the cascade ends at the honest fallback and the
# owner hears nothing at all. His words: in the FreeLLMAPI
# days the replies were late, but they CAME. So the guard
# keeps its verdict (an English reply is still a provider
# failure — the walk, the stern retry and the v7.4 power
# escalation all run exactly as before), but the LAST
# otherwise-valid reply the guard rejected is no longer
# thrown away: _agent_reply translates it to Bengali and
# speaks THAT (see Brain._rescue_wrong_language_reply).
# The translation route is the free Google Translate text
# endpoint of the same family the Google Translate TTS
# layer in voice.py already uses (translate_tts) — no key,
# no new dependency.
TRANSLATE_TEXT_URL = ("https://translate.googleapis.com"
                      "/translate_a/single")
TRANSLATE_TIMEOUT_S = 3.5
_TRANSLATE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; "
                 "x64) AppleWebKit/537.36 (KHTML, like "
                 "Gecko) Chrome/120.0.0.0 Safari/537.36")


def _translate_to_bengali(text):
    """Translate ONE short reply text to Bengali via the
    free Google Translate text endpoint (client=gtx, the
    same public family as voice.py's translate_tts).
    Returns the translated string, or None on ANY failure
    — non-200, timeout, unparseable payload, empty result.
    NEVER raises: the rescue that calls this must be able
    to fall back to today's honest line when translation
    is unavailable. Hard timeout TRANSLATE_TIMEOUT_S —
    a rescue that hangs is worse than the fallback."""
    try:
        src = (text or "").strip()
        if not src:
            return None
        import requests
        resp = requests.get(
            TRANSLATE_TEXT_URL,
            params={"client": "gtx", "sl": "auto",
                    "tl": "bn", "dt": "t", "q": src},
            headers={"User-Agent": _TRANSLATE_UA,
                     "Referer": "https://translate.google.com/"},
            timeout=TRANSLATE_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        data = resp.json()
        parts = []
        for seg in (data[0] or []):
            if seg and seg[0]:
                parts.append(str(seg[0]))
        out = "".join(parts).strip()
        return out or None
    except Exception:
        return None


# ------------------------------------------------- v5.6: CoT guard
# The recycle-bin incident (2026-11-15 14:21): a reasoning
# model inside the FreeLLMAPI chain answered "clean my
# recycle bin" with its raw chain-of-thought — "The user
# wants to clean their recycle bin… Let me think… I could
# press Ctrl+A… I should not delete things without
# confirmation?" — 13 s of spoken deliberation, zero action.
# A reply that reads as internal deliberation ABOUT ACTING
# is not an answer FOR Arjun: _guard_reply rejects it as a
# provider failure ([cot-guard]) and the cascade moves on.
# Tuning is deliberately conservative — the patterns target
# deliberation-about-acting (openers about "the user",
# planning phrases, first-person planning chains), never
# content: an explanation he asked for, a story, a weather
# answer or a Bengali paragraph must always pass.
_COT_OPENERS = (
    "the user wants", "the user is saying", "the user asked",
    "the user is asking", "the user said", "the user wants me",
    "the user is trying",
)
_COT_PHRASES = (
    "let me think", "let me start by",
    "i should check what tools", "i don't have a direct tool",
    "i do not have a direct tool", "i don't have a tool for",
    "i need to be careful", "i should be careful",
    "i should help them", "i should help him",
    "seems like they want", "it seems like the user",
    "should i ask for confirmation",
)
_COT_PLANNING_MARKERS = (
    " i should ", " i could ", " let me ", " i need to ",
    " i'll ", " i will ", " i can use ", " i'm going to ",
)


def _reply_looks_like_deliberation(text):
    """v5.6 REASONING-LEAK GUARD: True when a provider reply
    reads as the model's internal deliberation rather than an
    answer for Arjun.

    Three independent triggers, strongest first: (1) the reply
    OPENS by talking about "the user" in the third person —
    Nalox speaks TO Arjun, never about him; (2) two or more
    distinct planning phrases ("let me think", "I don't have
    a direct tool", …) — one stray phrase in a short answer
    is harmless and passes; (3) a LONG reply (>60 words) that
    also carries a first-person planning chain (i should /
    i could / let me / i need to …) — content answers don't
    plan, deliberation does."""
    body = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not body:
        return False
    for opener in _COT_OPENERS:
        if body.startswith(opener):
            return True
    hits = sum(1 for p in _COT_PHRASES if p in body)
    if hits >= 2:
        return True
    if len(body.split()) > 60:
        padded = " " + body + " "
        planning = sum(padded.count(m)
                       for m in _COT_PLANNING_MARKERS)
        if planning >= 5 or (hits >= 1 and planning >= 3):
            return True
    return False


# ------------------------------------------------- v6.0: markup leak
# Field (2026-11-15 15:04 IST): a FreeLLMAPI chain model (the
# "Dots" family) returned its tool call as RAW TEXT —
#   <dots_function_call> <invoke name="open_file">
#   <parameter name="path">C:\...\camera_20261115_150325.jpg
#   </parameter> </invoke> </dots_function_call>
# and Nalox SPOKE the markup aloud for 34 s. The model had
# chosen a sensible action; only the envelope was wrong. So
# _guard_reply runs this stage FIRST: a reply that IS leaked
# tool-call markup is (i) EXECUTED through the normal tool
# path when it parses to a known tool with plausible args —
# the intent is recovered and the tool's short result is
# what gets spoken; (ii) treated as a provider failure
# (None → next provider) when it does not parse. Ordinary
# text that merely contains "<" (e.g. "a < b") is untouched:
# detection requires an invoke/parameter element, a
# function-call wrapper tag, or a whole-reply JSON tool blob.
_TOOL_SCHEMAS = {}
for _t in AGENT_TOOLS:
    _fn = _t.get("function") or {}
    if _fn.get("name"):
        _TOOL_SCHEMAS[_fn["name"]] = _fn.get("parameters") or {}

# Hallucinated-but-obvious tool names with a local equivalent
# (open_file is not an agent tool; actions.open_path is).
_LEAKED_TOOL_ALIASES = ("open_file",)

_INVOKE_RE = re.compile(
    r"<invoke\s+name=\"([A-Za-z0-9_.\-]+)\"\s*>(.*?)</invoke>",
    re.IGNORECASE | re.DOTALL)
_PARAM_RE = re.compile(
    r"<parameter\s+name=\"([A-Za-z0-9_\-]+)\"\s*>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL)
_MARKUP_HINTS = ("<invoke", "<parameter", "<tool_call",
                 "<function_call", "dots_function_call")


def _parse_leaked_tool_call(reply):
    """Classify a provider reply for the v6.0 markup guard.

    Returns one of:
      None           — not tool markup at all (pass through)
      ("malformed",) — markup detected but unparseable, an
                       unknown tool, or implausible args
      (name, args)   — a recoverable tool call
    """
    if not reply:
        return None
    text = reply.strip()
    low = text.lower()
    is_markup = any(h in low for h in _MARKUP_HINTS)
    parsed = None
    m = _INVOKE_RE.search(text)
    if m:
        args = {}
        for pm in _PARAM_RE.finditer(m.group(2)):
            args[pm.group(1)] = re.sub(
                r"<[^>]+>", "", pm.group(2)).strip()
        parsed = (m.group(1).strip(), args)
    if parsed is None:
        # A JSON tool blob: the WHOLE reply, or the payload of
        # a <tool_call>/<function_call> wrapper. Prose that
        # merely quotes a JSON example matches neither shape
        # and is left alone.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start and (
                start == 0 or "<tool_call" in low
                or "<function_call" in low):
            try:
                data = json.loads(text[start:end + 1])
            except Exception:
                data = None
            if isinstance(data, dict):
                is_markup = True
                name = data.get("name") or data.get("tool")
                args = data.get("arguments")
                if args is None:
                    args = data.get("parameters")
                if args is None:
                    args = data.get("args")
                calls = data.get("tool_calls")
                if (name is None and isinstance(calls, list)
                        and calls and isinstance(calls[0], dict)):
                    fn = calls[0].get("function") or calls[0]
                    name = fn.get("name")
                    args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = None
                if name and isinstance(args, dict):
                    parsed = (str(name).strip(),
                              {str(k): (v if isinstance(v, str)
                                        else str(v))
                               for k, v in args.items()})
    if parsed is None:
        return ("malformed",) if is_markup else None
    name, args = parsed
    if name in _LEAKED_TOOL_ALIASES:
        path = (args.get("path") or "").strip()
        if path:
            return (name, {"path": path})
        return ("malformed",)
    schema = _TOOL_SCHEMAS.get(name)
    if schema is None:
        return ("malformed",)
    props = schema.get("properties") or {}
    clean = {}
    for key in props:
        val = args.get(key)
        if val is not None and str(val).strip():
            clean[key] = str(val).strip()
    for key in (schema.get("required") or []):
        if key not in clean:
            return ("malformed",)
    return (name, clean)


# ------------------------------------------------- v5.7: length cap
# The owner's hard rule (2026-11-15): replies come in TWO
# LINES — "উত্তর এমন দেবে কি 2 লাইনে হয়, যাতে উত্তরটা মুখে
# বলতে অনেক কম লাগে". A long spoken answer costs him seconds
# of listening for nothing (the 14:32 log: 40–53 s of speech
# per reply). So every provider reply is capped at ~2 short
# sentences / ~45 words, inside _guard_reply:
#   * ACTION / command turns — an over-cap reply is a
#     provider FAILURE ([length-guard]): the cascade tries
#     the next provider, and the local fallback waiting at
#     the end of it is short by construction.
#   * QUESTION / chat turns — the reply is TRUNCATED to its
#     first two sentences instead of rejected: he asked, he
#     still gets his answer — briefly.
# Sentence splitting understands the Bengali/Hindi danda
# (।) as well as . ! ? — Indic answers end their sentences
# with the danda, not a full stop.
REPLY_MAX_WORDS = 45
REPLY_MAX_SENTENCES = 2
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")


def _split_sentences(text):
    """Split a reply into sentences (EN/BN/HI terminators)."""
    body = re.sub(r"\s+", " ", (text or "").strip())
    if not body:
        return []
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(body)
            if p.strip()]


def _reply_over_cap(reply):
    """True when a provider reply breaks the two-line rule:
    more than REPLY_MAX_SENTENCES sentences, or more than
    REPLY_MAX_WORDS words."""
    if not reply:
        return False
    if len(reply.split()) > REPLY_MAX_WORDS:
        return True
    return len(_split_sentences(reply)) > REPLY_MAX_SENTENCES


def _truncate_reply(reply):
    """A reply cut to the two-line rule: its first
    REPLY_MAX_SENTENCES sentences — and if even those run
    past the word cap (one run-on sentence), a hard word
    trim, so the spoken length honours the rule either way."""
    sents = _split_sentences(reply)
    out = " ".join(sents[:REPLY_MAX_SENTENCES]) if sents \
        else (reply or "").strip()
    words = out.split()
    if len(words) > REPLY_MAX_WORDS:
        out = " ".join(words[:REPLY_MAX_WORDS]) + "…"
    return out


def _text_lang(text, default="en"):
    """The language an utterance is IN, by dominant script (v4.5):
    Bengali block -> bn, Devanagari block -> hi, otherwise the
    caller's default (the ears-detected language)."""
    bn = hi = 0
    for ch in text or "":
        code = ord(ch)
        if 0x0980 <= code <= 0x09FF:
            bn += 1
        elif 0x0900 <= code <= 0x097F:
            hi += 1
    if bn == 0 and hi == 0:
        return default
    return "bn" if bn >= hi else "hi"


# ------------------------------------------------- v4.7: Nalox learns
# Two preferences are learnable from plain speech, with NO API
# key: how to address him ("call me Sir") and which language to
# answer in ("বাংলায় কথা বলো"). Detection is deliberately
# narrow — explicit instruction shapes only — and runs in
# handle() before routing (after pending confirmations), so a
# preference statement can never be eaten by a content intent.
# The captured name is sanity-checked hard: 1-3 words, 1-20
# chars, no digits, no sentence verbs — "call me when you can"
# must NOT rename him "when".
_PREF_STOP_WORDS = {
    "from", "now", "today", "onwards", "please", "and", "then",
    "anymore", "only", "when", "if", "back", "later", "not",
    "থেকে", "আজ", "এখন", "শুধু", "और", "अब",
}
_PREF_VERB_BLOCK = {
    "open", "play", "search", "stop", "restart", "call", "calling",
    "say", "speak", "talk", "go", "come", "do", "make", "take",
    "খোলো", "বলো", "করো", "चालू", "खोलो", "बजाओ",
}


def _clean_pref_name(raw):
    """Clean + sanity-check a captured 'call me X' name (v4.7).

    Returns the display name or None. Latin names are title-cased
    for display ("sir" -> "Sir"); Indic scripts pass through.
    """
    words = _ASR_PUNCT_RE.sub(" ", (raw or "").lower()).split()
    kept = []
    for w in words:
        if w in _PREF_STOP_WORDS or len(kept) >= 3:
            break
        kept.append(w)
    if not kept or len(kept) > 3:
        return None
    if any(any(ch.isdigit() for ch in w) for w in kept):
        return None
    if any(w in _PREF_VERB_BLOCK for w in kept):
        return None
    name = " ".join(kept)
    if not 1 <= len(name) <= 20:
        return None
    if name == "nalox" or name == "ন্যালক্স":
        return None  # that's the assistant, not the user
    if all(ord(ch) < 0x0900 for ch in name):
        name = " ".join(w.capitalize() for w in kept)
    return name


def _detect_call_me(text):
    """The name from a 'call me X' instruction (v4.7), or None.

    EN: the LAST "call me ..." wins, so "don't call me Arjun,
    call me Sir" lands on Sir; a lone "don't call me X" (no
    replacement offered) is ignored. BN/HI: the name sits between
    আমাকে/मुझे and the address verb (বলে ডাকো / कहो / बुलाओ ...).
    """
    t = (text or "").strip().lower()
    if not t:
        return None
    # Tolerate a leading wake word (Telegram texts may carry it).
    t = re.sub(r"^(nalox|ন্যালক্স|नैलॉक्स)\b[ ,।]*", "", t)
    m = re.search(r"আমাকে\s+(.+?)\s+বলে\s*(?:ডাকো|ডাকবে|ডাকুন|বলো|বলবে)",
                  t)
    if not m:
        m = re.search(r"আমাকে\s+(.+?)\s*(?:বলবে|ডাকবে|ডাকো)", t)
    if m:
        return _clean_pref_name(m.group(1))
    m = re.search(r"मुझे\s+(.+?)\s*(?:कहकर\s+बुलाओ|कहो|बुलाओ|बोलो|कहना)",
                  t)
    if m:
        return _clean_pref_name(m.group(1))
    matches = list(re.finditer(r"call me\s+([^.!?,;]+)", t))
    if not matches:
        return None
    m = matches[-1]
    if len(matches) == 1:
        before = t[max(0, m.start() - 8):m.start()]
        if before.rstrip().endswith(("n't", "not")):
            return None  # "don't call me X" alone — no replacement
    return _clean_pref_name(m.group(1))


_LANG_PREF_PHRASES = (
    ("bn", ("বাংলায় কথা বলো", "বাংলায় বলো", "বাংলা বলো",
            "speak in bengali", "speak bengali",
            "talk to me in bengali", "talk in bengali")),
    ("hi", ("हिन्दी में बात करो", "हिंदी में बात करो",
            "हिंदी में बोलो", "हिन्दी में बोलो",
            "speak in hindi", "speak hindi",
            "talk to me in hindi")),
    ("en", ("speak in english", "speak english",
            "talk to me in english", "english-এ বলো",
            "english এ বলো")),
)


# v4.8 tolerant pass: a language NAME plus a speak/talk verb —
# or a please / এবার / এখন থেকে / from-now marker — within a few
# words of it, in EITHER order. Latin verbs anchor at the token
# start ("talkative" must not count); Indic verbs match inside
# the token (বলো / বলবে / बोलो are single tokens).
_LANG_NAME_RES = (
    ("bn", re.compile(r"\bbangla\b|\bbangali\b|\bbengali\b|বাংলা")),
    ("hi", re.compile(r"\bhindi\b|हिंदी|हिन्दी")),
    ("en", re.compile(r"\benglish\b|ইংরেজি")),
)
_LATIN_SPEAK_RE = re.compile(r"^(talk|speak|say|chat|converse)")
_INDIC_SPEAK_RE = re.compile(r"বল|কহ|बोल|बात|कह")


def _is_speak_verb(token):
    return bool(_LATIN_SPEAK_RE.match(token)
                or _INDIC_SPEAK_RE.search(token))


def _detect_lang_pref(text):
    """The language from a 'speak in X' instruction: 'en' / 'bn'
    / 'hi' or None. v4.7 matched exact phrases; v4.8 adds a
    tolerant pass (Arjun's exact words "Can you talk me Bangla"
    matched nothing and got the haven't-learned line). Indic-
    script phrases are checked first — they cannot be anything
    else. The tolerant pass REQUIRES a speak/talk verb or a
    please/from-now marker near the language name: a language
    name alone in an unrelated sentence ("play a Bengali song")
    must NOT flip the preference."""
    t = (text or "").strip().lower()
    if not t:
        return None
    t = re.sub(r"^(nalox|ন্যালক্স|नैलॉक्स)\b[ ,।]*", "", t)
    for code, phrases in _LANG_PREF_PHRASES:
        if any(p in t for p in phrases):
            return code
    words = re.findall(r"[^\s,.!?;:\"'()।]+", t)
    if not words:
        return None
    for code, name_re in _LANG_NAME_RES:
        for i, w in enumerate(words):
            if not name_re.search(w):
                continue
            lo = max(0, i - 4)
            hi = min(len(words), i + 5)
            window = words[lo:i] + words[i + 1:hi]
            window_text = " ".join(window)
            if any(_is_speak_verb(x) for x in window) \
                    or "please" in window or "এবার" in window \
                    or "এখন থেকে" in window_text \
                    or "from now" in window_text:
                return code
    return None


class _Confirm:
    """One pending yes/no question (shutdown / restart / forget)."""
    def __init__(self, kind):
        self.kind = kind  # "shutdown" | "restart" | "forget"


# ------------------------------------------------------------- v6.8
# ACT, DON'T NARRATE (field 2026-11-15 20:40 IST): told
# "এই মেসেজটা ওপেন করে, একে রিপ্লাই দাও", Nalox answered
# "রিপ্লাই দিতে পারি" — a capability CLAIM — and did
# nothing. Weak models do this; the guard below makes it
# structurally hard regardless of provider: an action
# request answered with ZERO tool calls and a reply that is
# substantially "I can / I will / আমি … পারি" gets ONE
# stern retry, and a retry that still only narrates is
# replaced by an honest line — the false claim never
# reaches his ears. Genuine ability QUESTIONS ("তুমি কি
# রিপ্লাই দিতে পারো?", "can you …?") are not commands: a
# capability answer is correct there and the guard stays
# silent. Pure functions — unit-testable.

_NARRATE_ACTION_EN = {"reply", "send", "message", "open",
                      "type", "call", "write", "find",
                      "close", "post"}
_NARRATE_ACTION_ROMAN = {"pathao", "pathiye", "kholo",
                         "khulo", "lekho", "likhe", "uttor",
                         "jobab"}
_NARRATE_ACTION_BN = ("রিপ্লাই", "পাঠাও", "পাঠিয়ে",
                      "মেসেজ", "খোলো", "খুলে", "লেখো",
                      "লিখে", "কল করো", "ফোন করো",
                      "উত্তর দাও", "জবাব", "বন্ধ করো",
                      "খুঁজে দাও")
_NARRATE_CLAIM_BN = ("করতে পারি", "দিতে পারি", "পাঠাতে পারি",
                     "খুলতে পারি", "লিখতে পারি", "করে দেব",
                     "করে দিব", "দিয়ে দেব", "পাঠিয়ে দেব",
                     "পারব")
_NARRATE_STERN = (
    "\n\n[IMPORTANT — Nalox system note: your previous reply "
    "only SAID you could do it and took NO action, but the "
    "owner asked for the action itself. Do it NOW with the "
    "tools, in this turn: run every step you can, then "
    "confirm what was actually done. If one step is truly "
    "impossible, do the rest and say exactly which step "
    "blocked and why. Never answer an action request with a "
    "bare promise or capability claim.]")


def _is_ability_question(text):
    """True when the utterance ASKS about ability (v6.8) —
    interrogative markers per the owner's examples: a
    question mark, Bengali "কি … পারো/পারবে", or English
    "can you / could you". A capability answer is the
    CORRECT reply to these, so the narrate guard must not
    fire."""
    t = text or ""
    if "?" in t:
        return True
    if "কি" in t and ("পারো" in t or "পারবে" in t
                      or "পারেন" in t):
        return True
    return bool(re.search(r"\b(can|could)\s+you\b",
                          t.lower()))


def _looks_like_action_request(text):
    """True when the utterance asks for an ACTION (v6.8):
    an imperative/action verb in English, romanized
    Bengali/Hindi, or Bengali script — and NOT an ability
    question (those are answered, not executed)."""
    if _is_ability_question(text):
        return False
    toks = set(_normalise_asr(text or "").split())
    if toks & _NARRATE_ACTION_EN:
        return True
    if toks & _NARRATE_ACTION_ROMAN:
        return True
    raw = text or ""
    return any(p in raw for p in _NARRATE_ACTION_BN)


# ------------------------------------------------------------- v7.7
# CHAINED REQUESTS (item H). The owner's field case
# (2026-11-16): "নোটপ্যাড ওপেন করে আমার নামে কিছু লিখবে" —
# Notepad opened and the turn ENDED; the writing never
# happened. Two seams produced it: the deterministic app
# opener consumed the whole utterance for its first clause
# (see the deferral in _app_control_intents), and inside
# the agent loop a model that has run ONE tool often stops
# and narrates the remaining steps as if they were done —
# the v6.8 act-don't-narrate guard keys on ZERO executions,
# so the partial case slipped through. The continuation
# note below is the loop's answer; _looks_like_chain_
# request is its (conservative) trigger.
_CHAIN_CONTINUATION = (
    "\n\n[IMPORTANT — Nalox system note: the owner's "
    "request has MORE steps, and you stopped after the "
    "first one to describe the rest. Do NOT describe them "
    "— call the remaining tool(s) NOW, in this turn, until "
    "every step of the request is actually done. Then "
    "confirm briefly what was done.]")

_CHAIN_BN_VERBS = tuple(
    v for v in _NARRATE_ACTION_BN
    if v not in ("মেসেজ", "জবাব")) + (
    "লিখ", "ওপেন", "চালাও", "বাজাও", "শোনাও", "টাইপ")


def _owner_utterance(text):
    """The owner's words with any system stern note
    stripped (v7.7, item H): the narrate guard's retry
    calls the walk with text + _NARRATE_STERN, and the
    note's own verbs ("open", "send", …) must not make a
    single-step request look like a chain to the
    continuation check — the chain shape is judged on
    what the OWNER asked for, never on system text."""
    t = text or ""
    if _NARRATE_STERN and t.endswith(_NARRATE_STERN):
        t = t[:-len(_NARRATE_STERN)]
    return t


def _looks_like_chain_request(text):
    """True when the utterance asks for MORE THAN ONE
    action (v7.7, item H): a split-chain marker, two or
    more distinct action verbs (English / romanized /
    Bengali), or the Bengali conjunctive shape "X করে Y"
    (having done X, do Y). Deliberately conservative — a
    single-verb command ("open chrome", "গান চালাও") is
    never a chain, so the agent loop's normal termination
    is untouched for the common case."""
    t = (text or "").strip()
    if not t:
        return False
    if len(_split_chain(t)) > 1:
        return True
    toks = set(_normalise_asr(t).split())
    verbs = toks & (_NARRATE_ACTION_EN | _NARRATE_ACTION_ROMAN
                    | {"play"})
    bn = sum(1 for p in _CHAIN_BN_VERBS if p in t)
    if len(verbs) + bn >= 2:
        return True
    if "করে" in t and bn >= 1:
        return True
    return False


def _is_generic_offer(sentence):
    """True when a closing sentence is the GENERIC
    follow-up offer (v7.7, item E) — "আর কিছু করতে পারি?"
    / "anything else?" — as opposed to an offer specific
    to what was just done."""
    s = sentence or ""
    if "আর কিছু করতে পারি" in s or "আর কিছু চাই" in s:
        return True
    low = s.lower()
    return "anything else" in low \
        or "what else can i" in low


def _reply_ends_with_offer(reply):
    """True when a reply's LAST sentence is an ask — a
    question, the generic offer, or the owner's next-step
    shape ("…বলো।"). The item-E anti-repetition state
    (Brain._last_reply_had_offer) is built from this."""
    try:
        sents = _split_sentences(reply or "")
        if not sents:
            return False
        last = sents[-1].strip()
        return last.endswith("?") or "?" in last \
            or _is_generic_offer(last) \
            or last.endswith("বলো।") or last.endswith("বলো")
    except Exception:
        return False


def _reply_names_blocker(reply):
    """True when a reply honestly names a blocker (v7.7,
    item H) — "পারলাম না / can't / unable / failed …".
    Such a reply is a truthful report, never a false
    completion, so the partial-completion guard keeps it
    verbatim."""
    r = reply or ""
    if any(m in r for m in ("পারলাম না", "পারছি না",
                            "পারব না", "হয়নি", "হলো না")):
        return True
    low = r.lower()
    return any(m in low for m in
               ("can't", "cannot", "can not", "unable",
                "failed", "blocked", "not possible",
                "unavailable"))


def _is_capability_claim(reply):
    """True when a reply is substantially a bare capability
    / intent claim (v6.8): short, no question back, no
    negation (an honest "পারি না / I can't" is a refusal,
    not a false claim), and carrying one of the claim
    patterns — Bengali "…তে পারি / করে দেব / পারব", English
    "I can / I will / I'll / let me" closers."""
    r = (reply or "").strip()
    if not r or len(r) > 240 or "?" in r:
        return False
    low = r.lower()
    if "পারি না" in r or "পারব না" in r or "can't" in low \
            or "cannot" in low or "can not" in low:
        return False
    if any(p in r for p in _NARRATE_CLAIM_BN):
        return True
    if "পারি" in r:
        return True
    return any(p in low for p in
               ("i can ", "i can.", "i will ", "i'll ",
                "let me ", "i am able to", "i'm able to"))


class Brain:
    def __init__(self, cfg, speaker):
        self.cfg = cfg
        self.speaker = speaker
        self.pending = None          # _Confirm or None
        self.chat_history = []       # for the LLM fallback
        self.lang = (cfg.get("default_language") or "en").lower()
        self.last_lang = self.lang
        # v3 wiring (set by nalox.py after construction):
        self.hud = None              # Hud instance — console + tool posts
        self.reminders = None        # ReminderStore — set by nalox.py
        # v3 long-term memory (memory.json in the app folder):
        try:
            from memory_store import MemoryStore
            self.memory = MemoryStore()
        except Exception:
            self.memory = None
        # v4.3: TOML skill files (skills/*.toml) + the document-
        # memory context slot filled per-question by _agent_reply.
        self._doc_context = ""
        try:
            import skillfiles
            self.skill_files = skillfiles.load_skills()
        except Exception:
            self.skill_files = []
        # v5.8: HIS OWN commands (custom_commands.json, taught
        # from the Command Center's "Make your own command"
        # form — no coding). Loaded once here; handle() then
        # hot-reloads on the file's mtime, exactly like config,
        # so a command saved in the dashboard works on the very
        # next thing he says, with no restart.
        if _custom_mod is not None:
            self._custom_path = _custom_mod.STORE_PATH
        else:
            self._custom_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "custom_commands.json")
        self._custom = []
        if _custom_mod is not None:
            try:
                self._custom = _custom_mod.load_commands_safe(
                    self._custom_path)
            except Exception:
                self._custom = []
        self._custom_mtime = self._stat_path_mtime(
            self._custom_path)
        # v4.4: provider availability cache (see _agent_available).
        # The v4.3 agent path probed Ollama on EVERY unmatched
        # command — a flat ~3.0 s timeout before the fallback
        # line, every single time. The probe now runs once here,
        # in a background thread, and at most every 5 minutes
        # after that; the command path only reads this cache.
        self._prov_lock = threading.Lock()
        self._prov = {"at": 0.0, "ollama": False}
        self._prov_thread = None
        # v5.2 CRASH-GUARD: a probe start must never be able to
        # take Brain construction (and with it the whole boot)
        # down — the probes are diagnostics, not load-bearing.
        try:
            self._start_provider_probe()
        except Exception as exc:
            log.error("[CRASH-GUARD] provider probe failed to "
                      "start: %s: %s", type(exc).__name__, exc)
        # v5.0: FreeLLMAPI reachability cache — the router is a
        # LOCAL app Arjun can simply close, so (exactly like the
        # Ollama cache above) its up/down state is probed in a
        # background thread and the command path only reads the
        # cache: a closed app must cost zero delay per command.
        self._freellm = {"at": 0.0, "up": False}
        self._freellm_thread = None
        # v6.6: FreeLLMAPI timeout demotion — monotonic time
        # until which a timed-out router is skipped entirely
        # (0.0 = not demoted). See _freellm_note_failure.
        self._freellm_down_until = 0.0
        try:
            self._start_freellm_probe()
        except Exception as exc:
            log.error("[CRASH-GUARD] FreeLLMAPI probe failed to "
                      "start: %s: %s", type(exc).__name__, exc)
        # v5.4: PHONE auto-connect — when a Wi-Fi address is
        # saved (Settings → Phone pairing), try to (re)connect
        # to the phone once at boot, on a background thread:
        # the greeting never waits on the phone, and a phone
        # that is off or asleep costs nothing. Gated on the
        # address being set at all — no address, no thread.
        try:
            if str(cfg.get("phone_wifi_address") or "").strip():
                import phone_control as _phone_mod
                threading.Thread(
                    target=_phone_mod.ensure_connected,
                    args=(cfg,), daemon=True,
                    name="nalox-phone-connect").start()
        except Exception as exc:
            log.error("[CRASH-GUARD] phone auto-connect failed "
                      "to start: %s: %s", type(exc).__name__,
                      exc)
        # v6.0: NALOX PHONE APP LINK — the TCP command server
        # starts with Nalox (token-auth-gated, one phone at a
        # time). Pairing mode stays OFF until Settings → Phone
        # or the "send me the phone link" intent turns it on.
        try:
            import phone_link as _link_mod
            _link_mod.start(cfg)
        except Exception as exc:
            log.error("[CRASH-GUARD] phone link failed to "
                      "start: %s: %s", type(exc).__name__, exc)
        # v5.0: the last YouTube play/search query — the
        # "play the first one" / "প্রথমটা চালাও" follow-up
        # re-resolves and plays it.
        self._last_yt_query = ""
        # v4.8: BRAIN STATUS + CONFIG HOT-RELOAD state. brain_status
        # is the ONE truth the HUD header and the boot [brain] line
        # render; _key_checks holds the per-provider validation
        # results; _last_agent_fail remembers the most recent agent
        # failure (label, reason, monotonic time) so the fallback
        # can be honest; _cfg_path/_cfg_mtime drive the hot-reload
        # watch on config.json.
        self._status_lock = threading.Lock()
        self.brain_status = {"mode": "local", "key_state": "none",
                             "detail": "no key configured"}
        self._key_checks = {}
        # v5.2: validation runs are SERIALIZED with a lock
        # (see _validate_keys_now) — two overlapping runs used
        # to interleave their state writes, so a stale boot run
        # could resurrect a "rejected" key as "unreachable"
        # mid-command (a flaky skip-rejected failure under
        # load). With the lock, runs queue; the last to run
        # owns the final state, and incremental publishes from
        # two runs can never interleave.
        self._validate_lock = threading.Lock()
        self._last_agent_fail = None
        # v7.3: the model that actually ANSWERED, per walk
        # provider, this session — recorded by
        # _remember_working_model on every success (head
        # answers included). brain_status_line shows it in
        # the Command Center ("Brain: Groq · <model> ⚡") so
        # the owner can SEE which brain is talking; empty
        # until the first answer, where the line falls back
        # to the plain validated form.
        self._working_models = {}
        # v7.4 (Defect 1): the model that actually ANSWERED,
        # per provider — REAL answers only. Boot validation
        # also calls _remember_working_model (the v6.5
        # /models repair), and in the field (2026-11-16
        # 08:24:57) that validation remember re-crowned the
        # stale openai/gpt-oss-120b and the header then
        # showed it as the talking brain although it had
        # answered nothing. brain_status_line reads THIS
        # dict; validation records into _working_models
        # only (answered=False), never here.
        self._last_answered = {}
        # v7.5 (walk self-discovery): the account's OWN
        # model list per walk provider, in the order the
        # provider's /models endpoint returned it, captured
        # by boot validation (_check_one_key). Empty until
        # validation runs (or when /models failed) — and
        # empty means _model_candidates returns the
        # configured walk untouched.
        self._discovered_models = {}
        # v7.6 (auto-model): the model BOOT VALIDATION
        # picked per walk provider — recorded by
        # _remember_working_model ONLY on its answered=False
        # (validation) calls, so a real answer (either tier)
        # never rewrites it. When self-discovery produced a
        # walk, the CHAT walk heads itself with this model
        # (see _model_candidates): validation's pick is the
        # one model PROVEN to answer on this account, and
        # the field's pick (qwen/qwen3.8-27b) was also the
        # fastest measured — the shipped walk head was a
        # slower name the stale rule had kept in front.
        self._validation_model = {}
        # v7.6 (reply-language rescue): the LAST reply the
        # language guard rejected on language ALONE this
        # turn (it had already passed the markup, script
        # and CoT stages of _guard_reply), keyed by THREAD
        # IDENT — the chat race (below) runs providers on
        # worker threads, and each thread's candidate is
        # its own. Cleared at the start of every
        # _agent_reply; consumed there when the whole
        # cascade ends answerless — the reply is translated
        # to Bengali instead of discarded (see
        # _rescue_wrong_language_reply). No entry = nothing
        # to rescue.
        self._lang_rescue_candidates = {}
        # v7.7 (item I): SESSION DEAD-MODEL MEMORY — the
        # (provider, model) pairs that have already answered
        # "gone" (a _MODEL_MISS) in this process. Field
        # 2026-11-16 11:57–12:02 IST: EVERY turn re-paid
        # Gemini's serial hop — gemini-2.5-flash gone ->
        # gemini-2.0-flash gone -> gemini-2.5-flash-lite
        # gone -> flash-latest — because the walk started
        # from the configured head every time and nothing
        # remembered the corpses. The walk now filters
        # these out (see _agent_openai_walk): a model proven
        # dead is never requested again this session, and a
        # provider whose candidates are ALL dead reports
        # unavailable at once instead of hopping. Session
        # scope only — a restart re-probes, exactly like
        # the Groq walk's remembered working model.
        self._dead_models = set()
        # v7.9: RATE-LIMIT COOLDOWNS — (provider, model)
        # pairs parked by a 429, mapped to their monotonic
        # expiry (see _park_model_ratelimit). A parked model
        # is skipped by every walk until the cooldown
        # lapses; unlike _dead_models it is expected back,
        # so nothing here is remembered across restarts and
        # the walk never reports it "gone".
        self._model_cooldowns = {}
        # v7.9 (item D): THIS TURN's failure causes, a set
        # drawn from {"ratelimit", "auth", "other"}, fed by
        # _brain_fail (by HTTP status) and by the 429 park.
        # Reset at the top of every _agent_reply; read by
        # _chat_fallback so the spoken failure line names
        # the REAL cause — a rate-limit death must never
        # send the owner to check a healthy key.
        self._turn_fail_causes = set()
        # v7.9 (items B/C/E): why the most recent Ollama
        # fallback attempt failed ("not reachable at …",
        # "HTTP 500 — …"), set by _agent_ollama's exits so
        # the fallback outcome lines can name it — the
        # field's Ollama attempts used to be invisible
        # (a failed /api/tags probe returned None in
        # silence). The two knobs below bound the CHAT
        # safety net's attempt (item B): a per-call timeout
        # override and a candidate cap, set only around
        # that one call and restored after; None = the
        # full-strength defaults everywhere else.
        self._ollama_last_error = None
        self._ollama_timeout_override = None
        self._ollama_max_candidates = None
        # v7.8: MUSE WONDER session state. _muse_parked is
        # None while the provider is live; once the Meta
        # API answers 401/403 (key rejected) or 402
        # (billing) it holds that HTTP status and the chat
        # race never fields Muse again this session — the
        # ElevenLabs breaker shape (one clear line, then
        # silence), so a dead paid key can never tax every
        # turn. Session scope only: a restart re-probes,
        # exactly like _dead_models above. _last_answer_
        # provider is the provider of the last REAL answer
        # (recorded by _remember_working_model on its
        # answered=True calls and by the chat-race
        # coordinator for its winner); brain_status_line
        # names Muse Wonder when IT spoke last.
        self._muse_parked = None
        self._last_answer_provider = None
        # v7.7 (item E): the last turn's closing — whether
        # the previous spoken reply already ended with a
        # follow-up offer, and which generic offer text it
        # used. The anti-repetition post-check in
        # _guard_reply reads it: the generic "আর কিছু করতে
        # পারি?" must never land twice in a row.
        self._last_reply_had_offer = False
        # v7.7 (item H): set by the agent loop when its
        # continuation fired (a multi-step request whose
        # model stopped to narrate after the first tool)
        # and STILL no further tool ran — the wrapper then
        # replaces a completion claim with the honest
        # partial line instead of reporting undone work as
        # done.
        self._turn_partial_after_continuation = False
        # v7.6 (chat race): per-thread flags for race
        # workers — "quiet" silences _brain_fail's logbook
        # line (a race loser's failure is expected, not
        # news) and "racing" keeps _remember_chat from
        # recording a reply the owner never heard (the
        # race coordinator remembers the WINNER itself).
        self._race_tls = threading.local()
        # v7.4: SMART ROUTING state — the tier of the last
        # ANSWER ("power" / "instant" / None before the
        # first routed answer); brain_status_line marks a
        # power answer 💪 and an instant one ⚡ so the owner
        # can see which brain did the work. Recorded by
        # _remember_working_model when the walk passes its
        # tier through. _guard_lang_trips counts language-
        # guard rejections this process — the routing
        # escalation in _agent_openai_compatible snapshots
        # it around a call to spot an instant answer that
        # failed the owner's language rule.
        self._last_answer_tier = None
        self._guard_lang_trips = 0
        # v6.8: tools executed so far in this process — the
        # ACT-DON'T-NARRATE guard snapshots it around a
        # provider call (see _agent_openai_compatible).
        self._tool_run_count = 0
        self._validate_thread = None
        try:
            import config as _cfg_module
            self._cfg_path = _cfg_module.CONFIG_PATH
        except Exception:
            self._cfg_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "config.json")
        self._cfg_mtime = self._stat_mtime()
        # v4.7: learned preferences (prefs.json via memory_store).
        # Folded into the live config dict once here, so every
        # reader of cfg (greeting, digest, Settings) sees them;
        # _learn_pref keeps store + mirror in sync from then on.
        self._prefs = {}
        if _memstore is not None:
            try:
                self._prefs = _memstore.load_prefs()
            except Exception:
                self._prefs = {}
        for _k in ("preferred_name", "preferred_lang"):
            if self._prefs.get(_k) and not cfg.get(_k):
                cfg[_k] = self._prefs[_k]
        # v6.3: the learned language is also the LOCAL reply
        # default from the very first line — self.lang was set
        # from default_language above, before prefs loaded, so
        # without this sync a Bengali-first owner still got
        # English defaults for ambiguous/short utterances
        # until handle()'s per-call pref pass ran.
        _pl0 = self._pref_lang()
        if _pl0:
            self.lang = _pl0
            self.last_lang = _pl0
        log.info("[prefs] call me: %s | language: %s",
                 self._addr(), self._pref_lang() or "auto")
        # v4.8: publish the initial brain status and start the
        # boot key validation in the background — the greeting
        # never waits for the network.
        self._refresh_brain_status()
        self._validate_keys_async()

    # ------------------------------------------------ v4.7 preferences
    def _addr(self):
        """How to address him in THIS reply (learned name wins)."""
        return address_name(self.cfg)

    def _addr_bn(self):
        """The Bengali-form address for Bengali replies."""
        return address_name_bn(self.cfg)

    def _pref_lang(self):
        """The learned reply language ('en'/'bn'/'hi') or None."""
        lang = str(self.cfg.get("preferred_lang")
                   or self._prefs.get("preferred_lang")
                   or "").strip().lower()
        return lang if lang in ("en", "bn", "hi") else None

    def _learn_pref(self, key, value):
        """Persist one learned preference: prefs.json (durable)
        + the live config mirror + the in-memory cache. Guarded —
        a store failure must never eat the command."""
        self._prefs[key] = value
        self.cfg[key] = value
        if _memstore is not None:
            try:
                _memstore.set_pref(key, value)
            except Exception as exc:
                log.warning("Could not save preference %s: %s",
                            key, exc)
        log.info("Learned preference: %s = %r", key, value)

    def _learn_preferences(self, text):
        """Detect a preference instruction (v4.7). Returns the
        spoken confirmation, or None when this utterance is not
        one. Runs in handle() BEFORE routing (after pending
        confirmations): a preference statement is an instruction
        ABOUT Nalox, never a command FOR it."""
        lang_code = _detect_lang_pref(text)
        if lang_code:
            self._learn_pref("preferred_lang", lang_code)
            self.lang = lang_code
            self.last_lang = lang_code
            if lang_code == "bn":
                return "ঠিক আছে — এখন থেকে বাংলায় বলব।"
            if lang_code == "hi":
                return "ठीक है — अब से हिंदी में बोलूँगा।"
            return "Of course — I'll speak English from now on."
        name = _detect_call_me(text)
        if name:
            self._learn_pref("preferred_name", name)
            ulang = _text_lang(text, self.lang)
            if ulang == "bn":
                return f"ঠিক আছে, {name} — আজ থেকে {name} বলেই ডাকব।"
            if ulang == "hi":
                return f"ठीक है, {name} — आज से {name} ही कहूँगा।"
            return f"Of course, {name} — {name} it is, from now on."
        return None

    def _mode(self):
        """The current mode name (config mode, default jarvis)."""
        mode = str(self.cfg.get("mode") or "jarvis").strip().lower()
        return mode if mode in MODES else "jarvis"

    # ------------------------------------------------------------------
    def _loc(self, en, bn):
        """Pick the reply string for the current command language."""
        return bn if self.lang == "bn" else en

    # ------------------------------------------------------------------
    def handle(self, raw_text, lang=None, listen_fn=None):
        """listen_fn: optional callable returning heard text (for confirmations).

        v4.4: after the confirmation check, the utterance is
        split into CHAINED sub-commands ("open youtube and play
        lofi music" / "ইউটিউব খোলো তারপর গান বাজাও") — at most
        3 — and each part runs through _handle_single in order;
        the spoken reply is the sub-replies joined together.
        """
        # v4.8: config hot-reload — a key pasted into Settings
        # since this process started takes effect HERE, even if
        # the restart hiccuped (one cheap stat per call).
        self._maybe_reload_config()
        # v5.8: same hot-reload for his own taught commands —
        # a save in the Command Center applies to the very
        # next utterance.
        self._maybe_reload_custom()
        if lang:
            _l = str(lang).lower()
            self.lang = "bn" if _l.startswith("bn") else \
                "hi" if _l.startswith("hi") else "en"
        self.last_lang = self.lang
        text = (raw_text or "").strip().lower()
        if not text:
            return None, None

        # A pending confirmation swallows the next utterance.
        if self.pending is not None:
            return self._handle_confirmation(text)

        # v4.7: preference instructions ("call me Sir" / "বাংলায়
        # কথা বলো") are learned BEFORE any routing — they are
        # about Nalox itself, and the local router would only
        # shrug at them (Arjun's 11:27 report, verbatim).
        pref_reply = self._learn_preferences(text)
        if pref_reply is not None:
            return pref_reply, None

        # v4.7: a learned language wins over per-utterance
        # detection for Nalox's OWN local replies, until he
        # changes it with another "speak in ..." instruction.
        _pl = self._pref_lang()
        if _pl:
            self.lang = _pl
            self.last_lang = _pl

        # ---- v5.1: split-screen workspace — checked on the
        # WHOLE utterance, before the chain splitter (which
        # would cut "… on the left and … on the right" in two)
        # and before the generic open intent inside
        # _handle_single (which would swallow both app names
        # as one open target) ----
        ss_reply = self._split_screen_reply(text)
        if ss_reply is not None:
            return ss_reply, None

        parts = _split_chain(text)
        if len(parts) == 1:
            _r = self._handle_single(parts[0], raw_text)
            self._note_reply_closing(_r[0])
            return _r
        replies = []
        action = None
        for part in parts:
            reply, act = self._handle_single(part, part)
            if reply:
                replies.append(reply)
            if act:
                action = act
            if act == "exit" or act == "restart" \
                    or act == "standby" \
                    or self.pending is not None:
                break  # an exit, a self-restart (always LAST in a
                # chain), a standby (he said stop — nothing after
                # it runs), or a yes/no question ends the chain
        if not replies:
            _fb = self._chat_fallback(raw_text)
            self._note_reply_closing(_fb)
            return _fb, None
        _joined = " ".join(replies)
        self._note_reply_closing(_joined)
        return _joined, action

    def _note_reply_closing(self, reply):
        """Record how this turn's spoken reply ENDED
        (v7.7, item E): whether it closed with a follow-up
        offer. The next turn's anti-repetition checks (the
        _guard_reply post-check, _song_done_line) read the
        flag — an offer may land once, never twice in a
        row. Guarded: bookkeeping must never break a turn."""
        try:
            self._last_reply_had_offer = \
                _reply_ends_with_offer(reply)
        except Exception:
            pass

    def _handle_single(self, text, raw_text):
        """One (sub-)command through the full local router.

        Order is the v4.3 order — exact-phrase intents first
        (they always win), power skills, Bengali/Hindi handlers,
        English patterns, small talk — then the v4.4 content-word
        intents, then the agent/fallback.
        """
        user = self._addr()
        user_bn = self._addr_bn()

        # ---- v4.6: restart NALOX ITSELF (Arjun's hang remedy) ----
        # Above even the exit family: while Nalox feels stuck,
        # this is the one command that must always win. handle()
        # has already swallowed any pending confirmation, so a
        # "yes" can never land here. nalox.py speaks the reply
        # FIRST, then acts on the "restart" action (exit code 1 —
        # the supervisor relaunches, exactly like the HUD's
        # 🔄 Restart button).
        if _is_self_restart(text):
            rlang = _text_lang(text, self.lang)
            if rlang == "bn":
                return (f"রিস্টার্ট হচ্ছি, {user} — এক মুহূর্ত।",
                        "restart")
            if rlang == "hi":
                return (f"रिस्टार्ट हो रहा हूँ, {user} — बस एक पल।",
                        "restart")
            return f"Restarting, {user} — back in a moment.", "restart"

        # ---- v5.5: COMMAND CENTER (dashboard) open / close ----
        # BEFORE the standby family below: "dashboard বন্ধ করো"
        # contains the standby trigger বন্ধ করো, and "close the
        # dashboard" must close the DASHBOARD, not put Nalox to
        # sleep. Returns action "dashboard_open"/"dashboard_close"
        # — nalox.py owns the window and does the showing/hiding
        # (with the normal window as fallback); the brain only
        # routes. See _dashboard_intents.
        dash_reply = self._dashboard_intents(text)
        if dash_reply is not None:
            return dash_reply

        # ---- v6.8: APP CLOSE / OPEN (deterministic) ----
        # BEFORE the standby family below and before every
        # open path: a CLOSE verb must never be answered by
        # opening the app (field 2026-11-15 20:26 IST: "ক্রোম
        # বন্ধ করো" → "Opening chrome." + Chrome OPENED —
        # the utterance fell past the standby phrase into the
        # content rules, whose chrome rule only knows open).
        # See _app_control_intents.
        app_reply = self._app_control_intents(text)
        if app_reply is not None:
            return app_reply, None

        # ---- stop = STANDBY, never exit (v5.4 — the owner's
        # hard rule, 2026-11-15) ----
        # "stop" means stop SPEAKING and keep listening. The
        # pre-v5.4 "exit" here is what killed Nalox over and
        # over: Arjun's own stop commands (voice + Telegram,
        # live + queued) exited code 42 and the supervisor
        # stopped permanently. Now the whole stop/goodbye
        # family returns action "standby" with the SAME reply
        # texts as before; nalox.py cuts any speech in
        # progress and returns to wake listening. The process
        # exits only on tray/HUD clicks or a confirmed PC
        # shutdown/restart (the "exit" producers further down,
        # unreachable from a bare "stop": the PC words are
        # required there, and laptop-mentioning Bengali/Hindi
        # stop phrases are guarded out here).
        if re.search(r"\b(stop|exit|quit|goodbye|good bye|shut up|turn off yourself)\b", text) \
                and "shut down the" not in text and "shutdown the" not in text:
            return f"Standing by, {user}. Call me anytime.", "standby"
        if ("বিদায়" in text or "বন্ধ করো" in text
                or text.strip() in ("থামো", "বন্ধ হও")
                or "रुको" in text or "बंद करो" in text) \
                and not any(w in text for w in
                            ("ল্যাপটপ", "কম্পিউটার", "लैपटॉप", "pc")):
            if _text_lang(text, self.lang) == "hi":
                return (f"ठीक है, {user}। जब चाहिए, बुला "
                        "लीजिए।"), "standby"
            return f"ঠিক আছে, {user_bn}। বিদায়!", "standby"

        # ---- shutdown / restart (confirmation — or full control) ----
        if re.search(r"\b(shut ?down|power off|turn off)\b", text) and \
                re.search(r"\b(pc|laptop|computer|system|it|the)\b", text + " pc"):
            return self._confirm_or_execute(
                "shutdown",
                "Are you sure you want me to shut down the laptop? Say yes or no.",
                "তুমি কি নিশ্চিত, আমি ল্যাপটপ বন্ধ করে দিই? হ্যাঁ বা না বলো।")
        if "ল্যাপটপ বন্ধ" in text or "কম্পিউটার বন্ধ" in text:
            return self._confirm_or_execute(
                "shutdown",
                "Are you sure you want me to shut down the laptop? Say yes or no.",
                "তুমি কি নিশ্চিত, আমি ল্যাপটপ বন্ধ করে দিই? হ্যাঁ বা না বলো।")
        if re.search(r"\brestart\b|\breboot\b", text):
            return self._confirm_or_execute(
                "restart",
                "Are you sure you want me to restart the laptop? Say yes or no.",
                "তুমি কি নিশ্চিত, আমি ল্যাপটপ রিস্টার্ট করি? হ্যাঁ বা না বলো।")
        if "রিস্টার্ট" in text or "রিবুট" in text:
            return self._confirm_or_execute(
                "restart",
                "Are you sure you want me to restart the laptop? Say yes or no.",
                "তুমি কি নিশ্চিত, আমি ল্যাপটপ রিস্টার্ট করি? হ্যাঁ বা না বলো।")

        # ---- hacker console (HUD) show / hide — v3 ----
        if "কনসোল" in text and ("দেখাও" in text or "খোলো" in text or "খুলুন" in text):
            return self._console_reply(True), None
        if "কনসোল" in text and ("লুকাও" in text or "বন্ধ" in text):
            return self._console_reply(False), None
        if re.search(r"\b(show|open|bring up)\b[^.]*\bconsole\b", text):
            return self._console_reply(True), None
        if re.search(r"\b(hide|close)\b[^.]*\bconsole\b", text):
            return self._console_reply(False), None

        # ---- memory (v3, extended v5.4): remember / recall /
        # the memory QUESTION — all LOCAL, answered from
        # memory_store without any LLM. v5.4 had to land
        # because a FreeLLMAPI chain model told Arjun (in
        # Bengali) "আমার দীর্ঘমেয়াদী memory নেই" — false:
        # facts + prefs persist on this laptop across
        # restarts. The question "তোমার memory আছে?" must
        # therefore never reach a provider; neither may
        # মনে রেখো / याद रखो saves (EN-only before) or the
        # recall, which now includes his learned prefs. ----
        mem_reply = self._memory_intents(text)
        if mem_reply is not None:
            return mem_reply, None
        if "forget everything" in text or "forget all memories" in text \
                or "সব ভুলে যাও" in text or "সবকিছু ভুলে যাও" in text:
            return self._confirm_or_execute(
                "forget",
                "Are you sure you want me to forget everything I remember? "
                "Say yes or no.",
                "তুমি কি নিশ্চিত, আমি যা মনে রেখেছি সব ভুলে যাই? "
                "হ্যাঁ বা না বলো।")

        # ---- reminders (v3) ----
        reminder_reply = self._parse_reminder(text)
        if reminder_reply is not None:
            return reminder_reply, None

        # ---- v4.3 intents: doctor / digest / gmail / calendar /
        # scheduled tasks / file search / TOML skill files ----
        v43_reply = self._v43_intents(text)
        if v43_reply is not None:
            return v43_reply, None

        # ---- v5.4: PHONE intents — call a saved contact FROM
        # the phone / open an app ON the phone / phone battery.
        # Before the power skills and the generic open/content
        # intents below, so "open youtube on my phone" never
        # lands on the laptop and "call my mother" never falls
        # through to the agent. A bare "open youtube" (no phone
        # mention) does NOT match here and keeps its laptop
        # meaning — see _phone_intents. ----
        phone_reply = self._phone_intents(text)
        if phone_reply is not None:
            return phone_reply, None

        # ---- v5.6: PC CHORES — recycle bin / This PC / quick
        # clean, done LOCALLY the moment they're said (no LLM,
        # no confirmation; full control is on). Before the
        # power skills and the generic open intent below, so
        # "open this pc" never becomes an app hunt and "clean
        # my recycle bin" never reaches a deliberating model.
        # See _pc_chore_intents. ----
        chore_reply = self._pc_chore_intents(text)
        if chore_reply is not None:
            return chore_reply, None

        # ================= v2 POWER SKILLS =================
        # ---- find leads (before generic search, which would eat "find") ----
        category = (self.cfg.get("lead_category") or "restaurant").lower()
        bn_cat_words = _BN_CATEGORY_WORDS.get(category, [])
        mentions_category = (category in text
                             or any(w in text for w in bn_cat_words))
        lead_triggers = ["near", "find", "check", "search", "without website",
                         "no website", "leads", "lead",
                         "খোঁজ", "খুঁজ", "কাছে", "কাছের", "আশেপাশে", "ওয়েবসাইট নেই"]
        if (mentions_category and any(k in text for k in lead_triggers)) \
                or "find leads" in text or "ওয়েবসাইট নেই" in text:
            return skills.find_leads(self.cfg, self.lang), None

        # ---- build demo website ----
        m = re.search(r"(?:build|make|create)(?: me)?(?: a)?(?: demo)? website for (.+)", text)
        if not m:
            m = re.search(r"(?:build|make|create)(?: a)?(?: demo)? website (.+)", text)
        if m:
            reply, _slug = skills.build_demo(self.cfg, _clean(m.group(1)), self.lang)
            return reply, None
        if "ওয়েবসাইট বানাও" in text or "ওয়েবসাইট তৈরি" in text:
            name = text
            for junk in ("ওয়েবসাইট বানাও", "ওয়েবসাইট তৈরি করো", "ওয়েবসাইট তৈরি",
                         "একটা", "একটি", "জন্য", "এর"):
                name = name.replace(junk, " ")
            reply, _slug = skills.build_demo(
                self.cfg, re.sub(r"\s+", " ", name).strip(" .!?-"), self.lang)
            return reply, None

        # ---- email outreach (Settings gate, v4.1) ----
        if "email them" in text or "মেইল করো" in text or "মেইল পাঠাও" in text \
                or "ইমেল পাঠাও" in text:
            if not self.cfg.get("allow_email_send", True):
                return self._loc(
                    f"Email sending is turned off in Settings, {user}.",
                    f"মেইল পাঠানো Settings-এ বন্ধ আছে, {user_bn}।"), None
            return skills.email_outreach(self.cfg, None, self.lang), None
        m = re.search(r"(?:send(?: an?)? email to|email|mail)\s+(.+)", text)
        if m and "open" not in text:
            if not self.cfg.get("allow_email_send", True):
                return self._loc(
                    f"Email sending is turned off in Settings, {user}.",
                    f"মেইল পাঠানো Settings-এ বন্ধ আছে, {user_bn}।"), None
            return skills.email_outreach(self.cfg, _clean(m.group(1)), self.lang), None

        # ---- YouTube reply-all (v4.0) ----
        if "reply all" in text or "reply to all" in text \
                or "সব কমেন্টের রিপ্লাই দাও" in text \
                or "কমেন্টগুলোর রিপ্লাই দাও" in text \
                or "ইউটিউবের কমেন্ট রিপ্লাই করো" in text:
            return self._youtube_reply_all(), None

        # ================= Bengali core commands =================
        bn_reply = self._bengali_commands(text)
        if bn_reply is not None:
            return bn_reply, None

        # ================= Hindi core commands (v4.2) =================
        hi_reply = self._hindi_commands(text)
        if hi_reply is not None:
            return hi_reply, None

        # ---- v5.0 follow-up: "play the first one" — BEFORE the
        # generic play pattern, which would otherwise search
        # YouTube for the words "the first one" ----
        if self._wants_first_one(text):
            return self._first_one_reply(), None

        # ---- play on YouTube (before generic open/search) ----
        # v5.0: play means PLAY — the first result's watch page
        # opens (youtube_play resolver), not just the search.
        m = re.search(r"\bplay\b(.+)", text)
        if m:
            query = _clean(m.group(1))
            query = re.sub(r"\bon (?:youtube|ytube|youtub|yotube)\b.*$",
                           "", query).strip()
            if query:
                played, q = self._play_on_youtube(query)
                return self._play_reply(q, played), None

        # ---- search YouTube ----
        m = re.search(r"(?:search|find)(?: on)? youtube(?: for)?\s+(.+)", text)
        if m:
            query = _clean(m.group(1))
            self._last_yt_query = query
            actions.search_youtube(query)
            return self._loc(f"Searching YouTube for {query}.",
                             f"ইউটিউবে {query} খুঁজছি।"), None
        m = re.search(r"youtube(?: search)? (?:for )?(.+)", text)
        if m and "open" not in text:
            query = _clean(m.group(1))
            self._last_yt_query = query
            actions.search_youtube(query)
            return self._loc(f"Searching YouTube for {query}.",
                             f"ইউটিউবে {query} খুঁজছি।"), None

        # ---- v4.7: open / switch to a YouTube channel ----
        # Before generic open/search: "open channel Naloxff"
        # would otherwise fall into open-app with the target
        # "channel naloxff" (Arjun's 11:27 phone test, verbatim).
        channel_reply = self._channel_reply(text, raw_text)
        if channel_reply is not None:
            return channel_reply, None

        # ---- Google / web search ----
        # v4.4: the YouTube guard reads the NORMALISED text, so a
        # misheard "ytube" is not Google-searched either — it
        # belongs to the YouTube intents / content rules below.
        m = re.search(r"(?:google|search the web|search|find)(?: for)?\s+(.+)", text)
        if m and "youtube" not in _normalise_asr(text):
            query = _clean(m.group(1))
            actions.google_search(query)
            return self._loc(f"Searching Google for {query}.",
                             f"গুগলে {query} খুঁজছি।"), None

        # ---- open YouTube ----
        if re.search(r"\bopen\b.*\byoutube\b", text) or text == "youtube":
            actions.open_youtube()
            return self._loc("Opening YouTube.", "ইউটিউব খুলছি।"), None

        # ---- open website ----
        m = re.search(r"\bopen\b\s+(.+)", text)
        if m:
            target = _clean(m.group(1))
            site_names = ["gmail", "github", "whatsapp", "instagram", "facebook",
                          "twitter", "chatgpt", "amazon", "flipkart", "drive",
                          "maps", "news", "studio", "youtube studio", "email"]
            if target in site_names or "." in target or target.endswith(" com"):
                name = target.replace(" com", ".com")
                if "." in name and not name.startswith("http"):
                    actions.open_url("https://" + name.replace(" ", ""))
                    return f"Opening {name}.", None
                return actions.open_website(target), None
            # ---- open folder ----
            if target in actions.FOLDERS:
                return actions.open_folder(target), None
            if target.replace(" folder", "") in actions.FOLDERS:
                return actions.open_folder(target.replace(" folder", "")), None
            # ---- open app ----
            return actions.open_app(target.replace(" app", "")), None

        m = re.search(r"\bopen\b.*\b(downloads|documents|desktop|pictures|music|videos)\b", text)
        if m:
            return actions.open_folder(m.group(1)), None

        # ---- volume ----
        if "volume up" in text or "increase volume" in text or "louder" in text:
            actions.volume("up")
            return self._loc("Volume up.", "ভলিউম বাড়ালাম।"), None
        if "volume down" in text or "decrease volume" in text or "quieter" in text:
            actions.volume("down")
            return self._loc("Volume down.", "ভলিউম কমালাম।"), None
        if "mute" in text:
            actions.volume("mute")
            return self._loc("Muted.", "মিউট করলাম।"), None

        # ---- vision (v3.6): screenshot / look at screen / camera ----
        if "take a screenshot" in text or "take screenshot" in text:
            return self._vision_screenshot_reply(), None
        if "look at my screen" in text or "what is on my screen" in text \
                or "what's on my screen" in text \
                or "whats on my screen" in text \
                or "read my screen" in text:
            return self._look_at_screen_reply(), None
        if "look at the camera" in text \
                or "what do you see in the camera" in text \
                or "take a photo" in text or "take a picture" in text:
            return self._camera_reply(), None

        # ---- screenshot ----
        if "screenshot" in text or "screen shot" in text:
            result = actions.screenshot()
            return self._loc(result, "স্ক্রিনশট নিয়েছি। Pictures ফোল্ডারে সেভ হয়েছে।"), None

        # ---- typing / keys ----
        m = re.search(r"\btype\b\s+(.+)", text)
        if m:
            return actions.type_text(m.group(1)), None
        m = re.search(r"\bpress\b\s+(.+)", text)
        if m:
            return actions.press_key(m.group(1)), None
        if text in ("enter", "press enter"):
            return actions.press_key("enter"), None

        # ---- lock ----
        if re.search(r"\block\b", text):
            actions.lock_pc()
            return self._loc("Locking your laptop.", "ল্যাপটপ লক করছি।"), None

        # ---- time / date ----
        if "time" in text and ("what" in text or "the time" in text):
            return self._time_reply(), None
        if "date" in text or "today" in text and "day" in text:
            return self._date_reply(), None

        # ---- battery ----
        if "battery" in text:
            return self._battery_reply(), None

        # ---- identity / small talk ----
        if "who are you" in text or "your name" in text:
            return self._loc(
                f"I'm {self.cfg['assistant_name']}, your personal assistant, "
                f"{user}. Always on, always listening.",
                f"আমি ন্যালক্স, তোমার ব্যক্তিগত সহকারী, {user_bn}।"), None
        if "joke" in text:
            if self._mode() == "focus":
                return f"Focus mode, {user} — jokes later.", None
            return random.choice(JOKES_BN if self.lang == "bn" else JOKES), None
        if re.search(r"\b(hi|hello|hey)\b", text) and len(text) < 30:
            if self._mode() == "focus":
                return f"Yes, {user}?", None
            return random.choice(
                SMALL_TALK_BN if self.lang == "bn" else SMALL_TALK
            ).replace("{name}", user_bn if self.lang == "bn"
                      else user), None
        if "thank you" in text or "thanks" in text:
            return self._loc(f"Anytime, {user}.", f"স্বাগতম, {user_bn}।"), None
        if "how are you" in text:
            return self._loc(f"Running perfectly, {user}.",
                             f"ভালো আছি, {user_bn}। তুমি কেমন আছো?"), None

        # ---- v4.4 content-word intents (ASR-garble tolerant) ----
        content_reply = self._content_intents(text)
        if content_reply is not None:
            return content_reply, None

        # ---- v5.8: HIS OWN commands — the phrases he taught
        # Nalox himself in the Command Center ("Make your own
        # command", custom_commands.json). AFTER every built-in
        # local intent (a built-in always wins — teaching can
        # never break "clean my recycle bin"), BEFORE the
        # agent/LLM fallback (his phrase must never be
        # deliberated by a model). See _custom_intents. ----
        custom_reply = self._custom_intents(text)
        if custom_reply is not None:
            return custom_reply, None

        # ---- fallback: chat brain ----
        return self._chat_fallback(raw_text), None

    # ---------------------------------------------------- YouTube (v4.0)
    def _youtube_reply_all(self):
        """'Reply all' — answer every unreplied channel comment.

        Replies immediately, then runs youtube_tools.reply_all in a
        background thread (consent + API + writing 20 replies takes a
        while) and SPEAKS the final count when done. If the one-time
        OAuth setup (SETUP-YOUTUBE.txt) hasn't been done, says so.
        """
        # Settings gate (v4.1): Arjun can switch YouTube replies off.
        if not self.cfg.get("allow_youtube_reply", True):
            return self._loc(
                f"YouTube replies are turned off in Settings, {self._addr()}.",
                f"ইউটিউব রিপ্লাই Settings-এ বন্ধ আছে, {self._addr_bn()}।")
        import threading

        import youtube_tools
        if not youtube_tools.is_setup():
            return (f"YouTube reply setup is not done yet, {self._addr()}. "
                    "Muse-র SETUP-YOUTUBE guide টা follow করো — "
                    "একবারই লাগবে।")
        speaker = self.speaker
        hud = getattr(self, "hud", None)

        def _progress(msg):
            if hud is not None:
                try:
                    hud.post("[youtube] " + msg)
                except Exception:
                    pass

        def _work():
            posted, found = 0, 0
            try:
                posted, found = youtube_tools.reply_all(
                    self, progress_cb=_progress)
            except Exception as exc:
                log.warning("youtube reply_all failed: %s", exc)
            try:
                if found:
                    line = (f"Done, {self._addr()}. I replied to {posted} "
                            f"comments.")
                else:
                    line = (f"Done, {self._addr()}. There were no unreplied "
                            "comments.")
                _progress(line)
                speaker.say(line, lang="en")
            except Exception:
                pass  # the spoken report must never crash the thread

        threading.Thread(target=_work, daemon=True,
                         name="yt-reply-all").start()
        return f"Replying to all your YouTube comments, {self._addr()}."

    # ------------------------------------------------------------ v4.3
    def _v43_intents(self, text):
        """The v4.3 intent group — returns a reply or None.

        Runs right after reminders, BEFORE the v2 power skills, so
        "check my email" is never eaten by the email-outreach regex
        and "what's on my calendar today" never reaches the date
        intent ("day" hides inside "today"). Every sub-intent is
        failure-isolated: a broken feature answers with a short
        apology or falls through — it never breaks the router.
        """
        # ---- Doctor: "Nalox, check yourself" ----
        if any(p in text for p in ("check yourself", "system check",
                                   "নিজের check", "নিজেকে check",
                                   "সিস্টেম চেক")) \
                or text.strip() in ("doctor", "ডাক্তার"):
            return self._doctor_reply()
        # ---- Morning Digest on "good morning" (before noon) ----
        if ("good morning" in text or "শুভ সকাল" in text) \
                and datetime.now().hour < 12:
            return self._digest_reply()
        # ---- digest taste: "don't include X in my digest" ----
        m = re.search(r"don'?t include (.+?) in my digest", text)
        if not m:
            m = re.search(r"digest[- ]এ (.+?) রাখবে না", text)
        if m:
            word = _clean(m.group(1)).strip(" .!?")
            if word:
                try:
                    import memory_store
                    memory_store.add_digest_skip(word)
                except Exception:
                    pass
                return self._loc(
                    f"Done, {self._addr()} — no {word} in your digest.",
                    f"ঠিক আছে, {self._addr_bn()} — digest-এ {word} থাকবে না।")
        # ---- Gmail reading ----
        if any(p in text for p in ("any new emails", "check my email",
                                   "check my emails", "new emails",
                                   "read my emails", "ইমেইল এসেছে",
                                   "নতুন ইমেইল", "মেইল এসেছে")):
            return self._gmail_reply()
        # ---- Google Calendar (today) ----
        if ("calendar" in text and ("today" in text or "what" in text)) \
                or "আজকের schedule" in text or "আজ কি কি আছে" in text \
                or "আজকের সিডিউল" in text:
            return self._calendar_reply()
        # ---- recurring action tasks ----
        sched = self._scheduler_intents(text)
        if sched is not None:
            return sched
        # ---- document memory: file search ----
        fs = self._file_search_reply(text)
        if fs is not None:
            return fs
        # ---- TOML skill files (checked last in this group) ----
        try:
            import skillfiles
            skill, remainder = skillfiles.match_skill(
                getattr(self, "skill_files", []), text)
            if skill is not None:
                return skillfiles.run_skill(
                    skill, remainder, self._run_tool)
        except Exception as exc:
            log.warning("skill file run failed: %s", exc)
        return None

    def _doctor_reply(self):
        """Run the Doctor self-check in a thread; speak the summary."""
        import threading

        import doctor
        speaker = self.speaker
        hud = getattr(self, "hud", None)

        def _post(line):
            if hud is not None:
                try:
                    hud.post(line)
                except Exception:
                    pass
            _lb("SYSTEM", line)

        def _work():
            try:
                results = doctor.run_checks(self.cfg)
                for name, ok, detail in results:
                    _post(f"{'✓' if ok else '✗'} {name} — {detail}")
                line = doctor.summary_line(results)
            except Exception as exc:
                line = f"Doctor check failed, {self._addr()}: {exc}"
            try:
                speaker.say(line, lang="en")
            except Exception:
                pass  # the spoken summary must never crash the thread

        threading.Thread(target=_work, daemon=True,
                         name="doctor").start()
        return self._loc(f"Running my self-check, {self._addr()} — one moment.",
                         f"নিজের check করছি, {self._addr_bn()} — একটু দাঁড়াও।")

    def _digest_reply(self):
        """'Good morning' before noon -> the full Morning Digest."""
        try:
            spoken, tg_text = skills.digest(
                self.cfg, brain=self, reminders=self.reminders,
                lang=self.lang,
                youtube_first=(self._mode() == "creator"))
        except Exception as exc:
            log.warning("digest failed: %s", exc)
            return self._loc(
                f"Morning, {self._addr()}. The digest hit a snag — details "
                "are in the log.",
                f"শুভ সকাল, {self._addr_bn()}। digest-এ একটা সমস্যা হয়েছে।")
        import threading

        def _push():
            try:
                skills.push_digest(self.cfg, tg_text)
            except Exception:
                pass

        threading.Thread(target=_push, daemon=True,
                         name="digest-push").start()
        return spoken

    def _gmail_reply(self):
        """Speak the unread count + the top 3 senders/subjects."""
        try:
            if not skills.gmail_is_setup(self.cfg):
                return (f"Gmail is not set up yet, {self._addr()} — "
                        "Settings-এ app password বসাও।")
            count = skills.gmail_unread_count(self.cfg)
            if count is None:
                return self._loc(
                    f"I couldn't reach Gmail just now, {self._addr()}.",
                    f"এখন Gmail-এ পৌঁছাতে পারলাম না, {self._addr_bn()}।")
            if count == 0:
                return self._loc(f"No new emails, {self._addr()}.",
                                 f"নতুন ইমেইল নেই, {self._addr_bn()}।")
            items = skills.gmail_latest_unread(self.cfg, 3) or []
            parts = [self._loc(
                f"You have {count} unread emails, {self._addr()}.",
                f"তোমার {count}টা অপঠিত ইমেইল আছে, {self._addr_bn()}।")]
            for it in items:
                parts.append(f"{it['from']}: {it['subject']}")
            return " ".join(parts)[:400]
        except Exception as exc:
            log.warning("gmail intent failed: %s", exc)
            return self._loc(
                f"Gmail check failed, {self._addr()} — details in the log.",
                f"Gmail check ব্যর্থ হয়েছে, {self._addr_bn()}।")

    def _calendar_reply(self):
        """Speak today's Google Calendar events (up to 4)."""
        setup_line = (f"Calendar is not set up yet, {self._addr()} — "
                      "SETUP-YOUTUBE.txt-র Calendar অংশটা দেখো, "
                      "একবারই লাগবে।")
        try:
            import gcal
            if not gcal.is_setup():
                return setup_line
            events = gcal.today_events()
            if events is None:
                return setup_line
            if not events:
                return f"Nothing on your calendar today, {self._addr()}."
            parts = [f"Today, {self._addr()}:"]
            for ev in events[:4]:
                parts.append(f"{ev['start']} — {ev['title']}")
            return " ".join(parts)[:400]
        except Exception as exc:
            log.warning("calendar intent failed: %s", exc)
            return self._loc(f"Calendar check failed, {self._addr()}.",
                             f"Calendar check ব্যর্থ হয়েছে, {self._addr_bn()}।")

    # action keyword sets for the scheduler intents: (keywords that
    # must ALL appear, action id, spoken label)
    _SCHED_ACTIONS = (
        (("reply", "comment"), "reply_all_comments",
         "reply to all comments"),
        (("comment",), "check_youtube_comments",
         "check YouTube comments"),
        (("news",), "read_news", "read the news"),
        (("খবর",), "read_news", "read the news"),
        (("channel", "stat"), "channel_stats", "channel stats"),
        (("চ্যানেল",), "channel_stats", "channel stats"),
    )

    def _scheduler_intents(self, text):
        """Recurring ACTION tasks (scheduler.py): add/list/cancel."""
        try:
            import scheduler
        except Exception:
            return None
        if "list my tasks" in text or "my tasks" in text \
                or "আমার task" in text:
            tasks = scheduler.list_tasks()
            if not tasks:
                return self._loc(
                    f"You have no scheduled tasks, {self._addr()}.",
                    f"তোমার কোনো scheduled task নেই, {self._addr_bn()}।")
            return " ".join(scheduler.describe(t)
                            for t in tasks)[:400]
        m = re.search(r"cancel task\s*(\d+)", text)
        if not m:
            m = re.search(r"task\s*(\d+)\s*বাতিল", text)
        if m:
            n = int(m.group(1))
            if scheduler.remove_task(n):
                return self._loc(f"Task {n} cancelled, {self._addr()}.",
                                 f"Task {n} বাতিল করলাম, {self._addr_bn()}।")
            return self._loc(f"There is no task {n}, {self._addr()}.",
                             f"Task {n} নেই, {self._addr_bn()}।")
        if "every day" not in text and "everyday" not in text \
                and "প্রতিদিন" not in text:
            return None
        hm = _parse_task_time(text)
        if hm is None:
            return None  # no time named — not a schedulable request
        action = label = None
        for keys, act, lab in self._SCHED_ACTIONS:
            if all(k in text for k in keys):
                action, label = act, lab
                break
        if action is None:
            if "comment" in text or "কমেন্ট" in text:
                action, label = ("check_youtube_comments",
                                 "check YouTube comments")
        if action is None:
            return self._loc(
                f"I can schedule four things, {self._addr()}: check YouTube "
                "comments, reply to all comments, read the news, or "
                "channel stats — name one with a time.",
                "প্রতিদিন comment check, comment reply, খবর বা "
                f"channel stats schedule করতে পারি, {self._addr_bn()} — সময়সহ "
                "একটা বলো।")
        days = "weekdays" if "weekday" in text else "daily"
        channel = "telegram" if "telegram" in text else "speak"
        scheduler.add_task(action, label, hm, days=days,
                           channel=channel)
        when = "weekdays" if days == "weekdays" else "every day"
        return self._loc(
            f"Done, {self._addr()} — {label}, {when} at {hm}.",
            f"হয়ে গেছে, {self._addr_bn()} — {label}, প্রতিদিন {hm}-এ।")

    def _file_search_reply(self, text):
        """Document-memory search: 'search my files for X'."""
        if text.strip() in ("index my folder", "index my files",
                            "আমার ফোল্ডার index করো"):
            return self._run_tool("index_my_folder", {})
        m = re.search(r"search my files for (.+)", text)
        query = None
        if m:
            query = _clean(m.group(1))
        elif "আমার ফাইলে" in text and "খোঁজো" in text:
            query = _clean(text.replace("আমার ফাইলে", " ")
                           .replace("খোঁজো", " "))
        if not query:
            return None
        try:
            import docmemory
            hits = docmemory.search(query, k=3)
        except Exception as exc:
            log.warning("doc search failed: %s", exc)
            return None
        if not hits:
            return self._loc(
                f"Nothing in your files matches {query}, {self._addr()}. "
                "Say 'index my folder' if you have not yet.",
                f"তোমার ফাইলে {query} পেলাম না, {self._addr_bn()}।")
        parts = []
        for path, snippet in hits:
            parts.append(f"{os.path.basename(path)}: {snippet}")
        return " ".join(parts)[:450]

    # ------------------------------------------------------------ vision
    # v3.6: Nalox can SEE — screen capture + OCR + webcam (vision.py).
    # Every helper is failure-guarded: a broken camera or a failed
    # capture becomes a short spoken apology, never a crash.
    def _vision_screenshot_reply(self):
        """Capture the screen and open the image for Arjun."""
        import vision
        try:
            path = vision.capture_screen()
        except Exception:
            return self._loc(f"I could not take a screenshot, {self._addr()}.",
                             f"স্ক্রিনশট নিতে পারলাম না, {self._addr_bn()}।")
        try:
            os.startfile(path)  # Windows: open in the default viewer
        except Exception:
            pass
        return self._loc(f"Screenshot saved and opened, {self._addr()}.",
                         f"স্ক্রিনশট নিলাম আর খুলে দিলাম, {self._addr_bn()}।")

    def _look_at_screen_reply(self):
        """Screenshot + OCR, summarised in ONE short sentence."""
        import vision
        try:
            result = vision.look_at_screen()
        except Exception:
            return self._loc(f"I could not capture the screen, {self._addr()}.",
                             f"স্ক্রিনের ছবি তুলতে পারলাম না, {self._addr_bn()}।")
        text = (result.get("text") or "").strip()
        # v6.8: LOCAL VISION first — when Ollama is up, its
        # vision model describes the screenshot directly in
        # the reply language (it sees the whole screen, not
        # just OCR text); any failure falls through to the
        # OCR + brain summary below, unchanged.
        if self._ollama_available():
            desc = vision.describe_screen_ollama(
                self.cfg, result.get("image"), self.lang)
            if desc:
                return desc
        if not text:
            return self._loc(
                f"I captured the screen, {self._addr()}, but I could not read "
                "any text on it.",
                f"স্ক্রিনের ছবি তুলেছি, {self._addr_bn()}, কিন্তু কোনো লেখা "
                "পড়তে পারলাম না।")
        ask = (
            "The following text was read by OCR from Arjun's screen. "
            "In ONE short sentence, tell him what is on the screen — "
            "if there is an error or a message, say what it means. "
            + ("Reply in Bengali. " if self.lang == "bn" else "")
            + "Screen text:\n" + text[:1500])
        summary = self._agent_reply(ask)
        if summary:
            return summary
        # No agent brain reachable — read back the start of the text.
        return re.sub(r"\s+", " ", text).strip()[:200]

    def _camera_reply(self):
        """Take a webcam photo; OCR it and report briefly."""
        import vision
        try:
            path = vision.capture_camera()
        except Exception:
            path = None
        if not path:
            return self._loc(f"The camera is not ready yet, {self._addr()}.",
                             f"ক্যামেরা এখনো তৈরি না, {self._addr_bn()}।")
        text = ""
        try:
            text = (vision.ocr_image(path) or "").strip()
        except Exception:
            text = ""
        if text:
            cleaned = re.sub(r"\s+", " ", text).strip()[:120]
            return self._loc(
                f"Camera photo taken, {self._addr()}. I can read: {cleaned}",
                f"ক্যামেরার ছবি তুলেছি, {self._addr_bn()}। লেখা পড়া যাচ্ছে: {cleaned}")
        return self._loc(
            f"Camera photo taken, {self._addr()} — saved in Nalox Captures.",
            f"ক্যামেরার ছবি তুলেছি, {self._addr_bn()} — Nalox Captures-এ সেভ হয়েছে।")

    # ------------------------------------------------------------------
    def _bengali_commands(self, text):
        """Bengali keyword commands. Returns a reply string or None."""
        if not any("\u0980" <= ch <= "\u09FF" for ch in text):
            return None  # no Bengali script in this utterance

        # Play a song: "গান চালাও / গান বাজাও / গান শোনাও <name>"
        if "গান" in text and ("চালাও" in text or "বাজাও" in text
                              or "শোনাও" in text or "শুনাও" in text):
            query = text
            for junk in ("গান চালাও", "গান বাজাও", "গান শোনাও",
                         "চালাও", "বাজাও", "শোনাও", "শুনাও",
                         "একটা", "একটি", "প্লিজ"):
                query = query.replace(junk, " ")
            query = re.sub(r"\s+", " ", query).strip(" .!?")
            if not query or query == "গান":
                played, _q = self._play_on_youtube("bangla song")
                if played:
                    return self._song_done_line()
                return ("সরাসরি চালাতে পারলাম না — গানের search "
                        "খুলে দিলাম।")
            played, q = self._play_on_youtube(query)
            if played:
                return self._song_done_line(q)
            return (f"সরাসরি চালাতে পারলাম না — {q}-এর search "
                    "খুলে দিলাম।")

        # v7.7 (item D): the SOUNDS-LIKE play path — the
        # field garble ("একটা সগ পিলে করো", "একটা সাঁগ
        # চালাও") corrects to সং + a play verb and lands
        # here; without a correction this block never runs
        # and the router above/below is untouched. The
        # query is what survives token-wise after the
        # verbs, the song noun and the field fillers are
        # stripped — an empty remainder means "a song",
        # the bangla-song default, never a garbage search.
        _corrected = _correct_bengali_command_garble(text)
        if _corrected != text and ("সং" in _corrected
                                   or "গান" in _corrected):
            _rest = [tok for tok in _corrected.split()
                     if tok not in _PLAY_VERB_TOKENS
                     and tok not in ("সং", "গান")
                     and tok not in _PLAY_QUERY_FILLERS]
            _query = " ".join(_rest).strip(" .!?")
            if not _query:
                played, _q = self._play_on_youtube(
                    "bangla song")
                if played:
                    return self._song_done_line()
                return ("সরাসরি চালাতে পারলাম না — গানের search "
                        "খুলে দিলাম।")
            played, q = self._play_on_youtube(_query)
            if played:
                return self._song_done_line(q)
            return (f"সরাসরি চালাতে পারলাম না — {q}-এর search "
                    "খুলে দিলাম।")

        # YouTube: play / search / open
        if "ইউটিউব" in text or "ইউ টিউব" in text:
            rest = text.replace("ইউটিউবে", " ").replace("ইউটিউব", " ") \
                       .replace("ইউ টিউব", " ")
            for junk in ("খোলো", "খুলুন", "খোল", "খুলো", "চালাও", "বাজাও",
                         "সার্চ করো", "খোঁজো", "খুঁজো", "করো", "দাও"):
                rest = rest.replace(junk, " ")
            query = re.sub(r"\s+", " ", rest).strip(" .!?")
            if "চালাও" in text or "বাজাও" in text:
                if query:
                    played, q = self._play_on_youtube(query)
                    if played:
                        return self._song_done_line(q)
                    return (f"সরাসরি চালাতে পারলাম না — {q}-এর "
                            "search খুলে দিলাম।")
                actions.open_youtube()
                return "ইউটিউব খুলছি।"
            if "সার্চ" in text or "খোঁজ" in text or "খুঁজ" in text:
                if query:
                    self._last_yt_query = \
                        self._yt_clean_query(query) or query
                    actions.search_youtube(query)
                    return f"ইউটিউবে {query} খুঁজছি।"
            actions.open_youtube()
            return "ইউটিউব খুলছি।"

        # Google search
        if "গুগল" in text and ("সার্চ" in text or "খোঁজ" in text or "খুঁজ" in text):
            rest = text.replace("গুগল", " ").replace("গুগলে", " ")
            for junk in ("সার্চ করো", "খোঁজো", "খুঁজো", "করো", "দাও"):
                rest = rest.replace(junk, " ")
            query = re.sub(r"\s+", " ", rest).strip(" .!?")
            if query:
                actions.google_search(query)
                return f"গুগলে {query} খুঁজছি।"

        # Time / date
        if "সময় কত" in text or "কয়টা বাজে" in text or "কটা বাজে" in text \
                or ("সময়" in text and "বল" in text):
            return self._time_reply_bn()
        if "তারিখ" in text or "আজ কি বার" in text or "আজ কী বার" in text \
                or "কত তারিখ" in text:
            return self._date_reply_bn()

        # Battery
        if "ব্যাটারি" in text or "চার্জ" in text:
            return self._battery_reply_bn()

        # Vision (v3.6): look at the screen / camera — BEFORE the
        # screenshot check, since "স্ক্রিনে কি আছে" is about reading
        # the screen, not capturing it.
        if "স্ক্রিন" in text and ("দেখো" in text or "কি আছে" in text
                                  or "কী আছে" in text or "পড়ো" in text):
            return self._look_at_screen_reply()
        if "ক্যামেরা" in text and ("দেখো" in text or "দেখা যাচ্ছে" in text
                                   or "কি আছে" in text or "কী আছে" in text):
            return self._camera_reply()

        # Screenshot (v3.6: vision capture, opened for Arjun)
        if "স্ক্রিনশট" in text or ("screenshot" in text and "নাও" in text):
            return self._vision_screenshot_reply()

        # Volume
        if "ভলিউম" in text or "আওয়াজ" in text:
            if "বাড়া" in text or "বেশি" in text:
                actions.volume("up")
                return "ভলিউম বাড়ালাম।"
            if "কমা" in text or "কম" in text:
                actions.volume("down")
                return "ভলিউম কমালাম।"
            if "বন্ধ" in text or "মিউট" in text:
                actions.volume("mute")
                return "মিউট করলাম।"

        # Lock
        if "লক" in text:
            actions.lock_pc()
            return "ল্যাপটপ লক করছি।"

        # Small talk first: greetings in kind (শুভ সকাল / শুভ রাত ...)
        for greet in ("শুভ সকাল", "শুভ বিকেল", "শুভ সন্ধ্যা",
                      "শুভরাত্রি", "শুভ রাত"):
            if greet in text:
                return f"{greet}, {self._addr_bn()}।"

        # "কি খবর" = what's up — a greeting, NOT the news (below).
        if "কি খবর" in text or "কী খবর" in text:
            return f"এইতো, সব ঠিকঠাক চলছে, {self._addr_bn()}। তুমি কেমন আছো?"

        # News headlines: "আজকের খবর / খবর বলো / খবর শোনাও"
        if "আজকের খবর" in text or "খবর বলো" in text \
                or "খবর শোনাও" in text or "খবর দাও" in text:
            try:
                titles = skills.fetch_headlines(3)
            except Exception:
                titles = []
            if titles:
                return "আজকের বড় খবর: " + " ".join(
                    f"{_bn_num(i + 1)}. {t}।" for i, t in enumerate(titles))
            return f"এখন খবর পাচ্ছি না, {self._addr_bn()}।"

        # Capabilities: "কি করতে পারো / তুমি কি কি পারো"
        if "কি করতে পারো" in text or "কী করতে পারো" in text \
                or "কি কি পারো" in text or "কী কী পারো" in text \
                or "তুমি কি পারো" in text:
            return ("আমি অ্যাপ খুলতে, গান চালাতে, খবর বলতে, রিমাইন্ডার দিতে "
                    f"আর ওয়েবসাইট বানাতে পারি, {self._addr_bn()}।")

        # Identity / thanks / jokes / greetings
        if "তুমি কে" in text or "তোমার নাম" in text or "তোর নাম" in text:
            return f"আমি ন্যালক্স, তোমার ব্যক্তিগত সহকারী, {self._addr_bn()}।"
        if "ধন্যবাদ" in text:
            return f"স্বাগতম, {self._addr_bn()}।"
        if "জোক" in text or "মজার কথা" in text or "হাসাও" in text:
            return random.choice(JOKES_BN)
        if "কেমন আছ" in text:
            return f"ভালো আছি, {self._addr_bn()}। তুমি কেমন আছো?"
        if "হ্যালো" in text or "হাই" in text or "সালাম" in text:
            return random.choice(SMALL_TALK_BN).replace(
                "{name}", self._addr_bn())
        return None

    # ------------------------------------------------------------------
    # Roman-Hindi trigger phrases (Whisper often writes Arjun's
    # Hindi in Latin letters). Devanagari in the text triggers the
    # handler on its own; these catch the Roman spellings.
    _HI_ROMAN_HINTS = (
        "kaise ho", "tum kaun ho", "tumhara naam", "dhanyavaad",
        "dhanyavad", "shukriya", "samay kya hai", "kitne baje",
        "gana bajao", "gana chalao", "chrome kholo", "youtube kholo",
        "khabar sunao", "aaj ki khabar", "namaste", "battery kitni",
        "lock karo", "aawaz", "awaaz", "tarikh",
    )

    def _hindi_commands(self, text):
        """Hindi keyword commands (v4.2). Returns a reply or None.

        Mirrors _bengali_commands: Devanagari script OR a common
        Roman-Hindi phrase triggers it; anything unmatched returns
        None so English handling continues. Replies are short Hindi,
        exactly like the Bengali set.
        """
        has_dev = any("\u0900" <= ch <= "\u097F" for ch in text)
        if not has_dev and not any(h in text for h in self._HI_ROMAN_HINTS):
            return None

        # Play a song: "गाना बजाओ / गाना चलाओ / gana bajao <name>"
        if ("गाना" in text and ("बजाओ" in text or "चलाओ" in text)) \
                or "gana bajao" in text or "gana chalao" in text:
            query = text
            for junk in ("गाना बजाओ", "गाना चलाओ", "gana bajao",
                         "gana chalao", "बजाओ", "चलाओ", "bajao", "chalao",
                         "गाना", "gana", "एक", "कोई", "प्लीज",
                         "ek", "koi", "please"):
                query = query.replace(junk, " ")
            query = re.sub(r"\s+", " ", query).strip(" .!?")
            if not query:
                played, _q = self._play_on_youtube("hindi song")
                if played:
                    return "गाना चला रहा हूँ।"
                return ("सीधे नहीं चला पाया — गाने की search खोल "
                        "दी है।")
            played, q = self._play_on_youtube(query)
            if played:
                return f"यूट्यूब पर {q} चला रहा हूँ।"
            return f"सीधे नहीं चला पाया — {q} की search खोल दी है।"

        # Open YouTube / Chrome: "यूट्यूब खोलो / क्रोम खोलो / kholo"
        if "यूट्यूब खोल" in text or "youtube kholo" in text \
                or "youtube khol" in text:
            actions.open_youtube()
            return "यूट्यूब खोल रहा हूँ।"
        if "क्रोम खोल" in text or "chrome kholo" in text \
                or "chrome khol" in text:
            result = actions.open_app("chrome")
            if str(result).lower().startswith("sorry"):
                return "क्रोम नहीं मिला, अर्जुन।"
            return "क्रोम खोल रहा हूँ।"

        # Time / date / battery
        if "समय क्या" in text or "कितने बजे" in text \
                or "samay kya hai" in text or "kitne baje" in text:
            return self._time_reply_hi()
        if "तारीख" in text or "tarikh" in text:
            return self._date_reply_hi()
        if "बैटरी" in text or "battery kitni" in text \
                or "battery kitna" in text:
            return self._battery_reply_hi()

        # News: "खबर सुनाओ / आज की खबर / khabar sunao"
        if "खबर सुनाओ" in text or "आज की खबर" in text \
                or "खबर बताओ" in text or "khabar sunao" in text \
                or "aaj ki khabar" in text:
            try:
                titles = skills.fetch_headlines(3)
            except Exception:
                titles = []
            if titles:
                return "आज की बड़ी खबरें: " + " ".join(
                    f"{_hi_num(i + 1)}. {t}।" for i, t in enumerate(titles))
            return "अभी खबर नहीं मिल रही, अर्जुन।"

        # Volume: "आवाज़ बढ़ाओ / आवाज़ कम करो"
        if "आवाज़" in text or "आवाज" in text \
                or "aawaz" in text or "awaaz" in text:
            if "बढ़ा" in text or "badha" in text:
                actions.volume("up")
                return "आवाज़ बढ़ा दी।"
            if "कम" in text or "kam kar" in text:
                actions.volume("down")
                return "आवाज़ कम कर दी।"
            if "बंद" in text or "mute" in text:
                actions.volume("mute")
                return "म्यूट कर दिया।"

        # Lock: "लॉक करो / lock karo"
        if "लॉक कर" in text or "lock karo" in text:
            actions.lock_pc()
            return "लैपटॉप लॉक कर रहा हूँ।"

        # Small talk
        if "कैसे हो" in text or "kaise ho" in text:
            return "मैं ठीक हूँ, अर्जुन। तुम कैसे हो?"
        if "तुम कौन हो" in text or "तुम्हारा नाम" in text \
                or "tum kaun ho" in text or "tumhara naam" in text:
            return "मैं नैलॉक्स हूँ, अर्जुन — तुम्हारा पर्सनल असिस्टेंट।"
        if "धन्यवाद" in text or "शुक्रिया" in text \
                or "dhanyavaad" in text or "dhanyavad" in text \
                or "shukriya" in text:
            return "स्वागत है, अर्जुन।"
        if "नमस्ते" in text or "नमस्कार" in text or "namaste" in text \
                or "हैलो" in text:
            return "नमस्ते, अर्जुन।"
        return None

    def _time_reply_hi(self):
        now = datetime.now()
        hour12 = now.hour % 12 or 12
        return (f"अभी {_hi_num(hour12)} बजकर "
                f"{_hi_num(now.minute)} मिनट हुए हैं।")

    def _date_reply_hi(self):
        now = datetime.now()
        return (f"आज {_HI_WEEKDAYS[now.weekday()]}, {_hi_num(now.day)} "
                f"{_HI_MONTHS[now.month - 1]} {_hi_num(now.year)} है।")

    def _battery_reply_hi(self):
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt is None:
                return "इस लैपटॉप में बैटरी की जानकारी नहीं मिल रही।"
            state = "चार्ज हो रही है" if batt.power_plugged \
                else "चार्ज नहीं हो रही है"
            return (f"बैटरी अभी {_hi_num(int(batt.percent))} प्रतिशत है, "
                    f"{state}।")
        except Exception:
            return "बैटरी की स्थिति नहीं पढ़ पाया।"

    # ------------------------------------------------------------------
    def _time_reply(self):
        if self.lang == "bn":
            return self._time_reply_bn()
        now = datetime.now()
        return f"It's {now.strftime('%I:%M %p')} right now."

    def _time_reply_bn(self):
        now = datetime.now()
        hour12 = now.hour % 12 or 12
        if now.hour < 4:
            part = "রাত"
        elif now.hour < 12:
            part = "সকাল"
        elif now.hour < 16:
            part = "দুপুর"
        elif now.hour < 19:
            part = "বিকেল"
        else:
            part = "রাত"
        return (f"এখন {part} {_bn_num(hour12)}টা বেজে "
                f"{_bn_num(f'{now.minute:02d}')} মিনিট।")

    def _date_reply(self):
        if self.lang == "bn":
            return self._date_reply_bn()
        now = datetime.now()
        return f"Today is {now.strftime('%A, %d %B %Y')}."

    def _date_reply_bn(self):
        now = datetime.now()
        return (f"আজ {_BN_WEEKDAYS[now.weekday()]}, {_bn_num(now.day)} "
                f"{_BN_MONTHS[now.month - 1]} {_bn_num(now.year)}।")

    def _battery_reply(self):
        if self.lang == "bn":
            return self._battery_reply_bn()
        return actions.battery_status()

    def _battery_reply_bn(self):
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt is None:
                return "এই ল্যাপটপে ব্যাটারির খবর পাওয়া যাচ্ছে না।"
            state = "চার্জ হচ্ছে" if batt.power_plugged else "চার্জ হচ্ছে না"
            return f"ব্যাটারি এখন {_bn_num(int(batt.percent))} শতাংশ, {state}।"
        except Exception:
            return "ব্যাটারির অবস্থা পড়তে পারলাম না।"

    # ------------------------------------------------------------------
    def _console_reply(self, show):
        """Show/hide the v3 hacker-console HUD (handle set by nalox.py)."""
        hud = getattr(self, "hud", None)
        if hud is None:
            return self._loc("The console is turned off in my config.",
                             "কনসোলটা আমার config-এ বন্ধ করা আছে।")
        try:
            (hud.show if show else hud.hide)()
        except Exception:
            pass  # the HUD must never break a command
        if show:
            return self._loc("Showing the console.", "কনসোল দেখাচ্ছি।")
        return self._loc("Console hidden.", "কনসোল লুকিয়ে দিলাম।")

    # ------------------------------------------------ v5.5 dashboard
    _DASH_WORDS = ("dashboard", "command center", "command centre",
                   "ড্যাশবোর্ড", "কমান্ড সেন্টার",
                   "डैशबोर्ड", "कमांड सेंटर")

    # v5.7: dashboard-specific ASR garbles, applied ONLY inside
    # this intent, on top of _normalise_asr — because some of
    # them are real words elsewhere. The field proof (2026-11-15
    # 14:33): he said "Nalox, close Command Center", cloud:groq
    # heard "mellox close common centre", the exact matcher
    # missed, and the brain deliberated for 40 s. Here the
    # reading is safe: a dashboard token is still REQUIRED, and
    # "common" becomes "command" only when a center-ish token
    # stands in the same utterance.
    _DASH_GARBLE_MAP = {
        "komen": "command", "koman": "command",
        "commond": "command", "kommand": "command",
    }
    _DASH_CENTER_TOKENS = {"center", "centre", "senter",
                           "centar", "cneter", "sentre"}

    @staticmethod
    def _dash_tokens(text):
        """Token list for dashboard matching (v5.7): global ASR
        normalisation -> the dashboard garble map -> pair
        merges ("dash board" -> dashboard; "command center",
        incl. a mapped "common centre", -> commandcenter)."""
        toks = _normalise_asr(text).split()
        has_center = any(t in Brain._DASH_CENTER_TOKENS
                         for t in toks)
        mapped = []
        for tok in toks:
            if tok in Brain._DASH_GARBLE_MAP:
                tok = Brain._DASH_GARBLE_MAP[tok]
            elif tok == "common" and has_center:
                tok = "command"
            mapped.append(tok)
        merged = []
        i = 0
        while i < len(mapped):
            pair = (mapped[i], mapped[i + 1]) \
                if i + 1 < len(mapped) else None
            if pair == ("dash", "board"):
                merged.append("dashboard")
                i += 2
            elif pair == ("command", "center"):
                merged.append("commandcenter")
                i += 2
            else:
                merged.append(mapped[i])
                i += 1
        return merged

    # ------------------------------------------------ v6.8 app control
    # (surface form, actions key, English display, Bengali
    # display) — longest surfaces first so "file explorer"
    # beats "explorer" and "google chrome" beats "chrome".
    # YouTube's actions key is "chrome": the site lives in
    # the browser, so closing YouTube closes the browser —
    # the only honest close a website has.
    _APP_CONTROL_TARGETS = (
        ("visual studio code", "vscode", "visual studio code",
         "visual studio code"),
        ("google chrome", "chrome", "chrome", "ক্রোম"),
        ("file explorer", "file explorer", "file explorer",
         "file explorer"),
        ("task manager", "task manager", "task manager",
         "task manager"),
        ("calculator", "calculator", "calculator",
         "ক্যালকুলেটর"),
        ("ক্যালকুলেটর", "calculator", "calculator",
         "ক্যালকুলেটর"),
        ("powerpoint", "powerpoint", "powerpoint", "powerpoint"),
        ("browser", "chrome", "browser", "ব্রাউজার"),
        ("ব্রাউজার", "chrome", "browser", "ব্রাউজার"),
        ("notepad", "notepad", "notepad", "নোটপ্যাড"),
        ("নোটপ্যাড", "notepad", "notepad", "নোটপ্যাড"),
        ("spotify", "spotify", "spotify", "স্পটিফাই"),
        ("স্পটিফাই", "spotify", "spotify", "স্পটিফাই"),
        ("youtube", "chrome", "YouTube", "ইউটিউব"),
        ("chrome", "chrome", "chrome", "ক্রোম"),
        ("settings", "settings", "settings", "settings"),
        ("terminal", "terminal", "terminal", "terminal"),
        ("explorer", "explorer", "explorer", "explorer"),
        ("vs code", "vscode", "vs code", "vs code"),
        ("vscode", "vscode", "vscode", "vscode"),
        ("paint", "paint", "paint", "paint"),
        ("excel", "excel", "excel", "excel"),
        ("word", "word", "word", "word"),
        ("cmd", "cmd", "cmd", "cmd"),
    )
    _APP_CLOSE_TOKENS = {"close", "quit", "exit", "kill",
                         "bondho", "bandho", "bondo", "bond"}
    _APP_OPEN_TOKENS = {"open", "launch", "start", "kholo",
                        "khulo", "khol", "ওপেন", "খোলো",
                        "খুলুন", "খোল"}

    def _app_control_intents(self, text):
        """Deterministic app close/open (v6.8) — the fix for
        the field bug where "ক্রোম বন্ধ করো" OPENED Chrome.

        A CLOSE verb (close / quit / exit / kill, Bengali
        বন্ধ / बंद, romanized bondho / bandho / bondo /
        bond) beside a known app target closes it — checked
        in _handle_single BEFORE the standby family (whose
        "বন্ধ করো" trigger the utterance also contains) and
        before every open path, so with a close verb present
        open_app can never fire for the utterance. An OPEN
        verb beside a target opens it, with the confirmation
        in the reply language (pref bn: "ক্রোম খুলছি।" /
        "ক্রোম বন্ধ করছি।"; pref en: "Opening chrome." /
        "Closing chrome."). The spoken line always names the
        action actually taken.

        Guards: Hindi keeps its own handlers (its lines are
        Hindi); a phone mention belongs to the phone
        intents; "studio" belongs to the website path
        (YouTube Studio); no target or no verb → None, and
        the rest of the router proceeds exactly as before
        (a bare "বন্ধ করো" still means standby, "ল্যাপটপ
        বন্ধ" still means PC shutdown)."""
        if self.lang == "hi":
            return None
        nt = _normalise_asr(text)
        ntoks = nt.split()
        tset = set(ntoks)
        if "phone" in tset or "ফোন" in text:
            return None
        if "studio" in tset:
            return None
        target = None
        for surface, key, disp_en, disp_bn in \
                self._APP_CONTROL_TARGETS:
            if surface.isascii():
                hit = _tokens_run_in(
                    ntoks, surface.split())
            else:
                hit = surface in text
            if hit:
                target = (key, disp_en, disp_bn)
                break
        if target is None:
            return None
        key, disp_en, disp_bn = target
        is_close = bool(tset & self._APP_CLOSE_TOKENS) \
            or "বন্ধ" in text or "बंद" in text
        if is_close:
            result = actions.close_app(key)
            if result:
                return self._loc(f"Closing {disp_en}.",
                                 f"{disp_bn} বন্ধ করছি।")
            return self._loc(
                f"{disp_en} is not open right now.",
                f"{disp_bn} এখন খোলা নেই।")
        is_open = bool(tset & self._APP_OPEN_TOKENS) \
            or "খোলো" in text or "খুলুন" in text \
            or "ওপেন" in text
        if is_open:
            # v7.7 (item H): a SECOND action clause rides
            # on this open — "নোটপ্যাড ওপেন করে আমার নামে
            # কিছু লিখবে" (open Notepad AND write), "open
            # chrome, play a song". Opening here and
            # returning would silently DROP the second
            # step (the owner's field case: Notepad opened,
            # nothing was ever written). Defer the whole
            # utterance to the agent, whose loop now runs
            # chained steps to completion. The markers are
            # narrow: a write/type verb, or a play verb
            # with its object — a bare open never defers.
            if "লিখ" in text \
                    or tset & {"write", "type"} \
                    or ("play" in tset
                        and tset & {"song", "music", "video"}) \
                    or ("গান" in text and (
                        "চালাও" in text or "বাজাও" in text
                        or "শোনাও" in text or "শুনাও" in text)):
                return None
            if disp_en == "YouTube":
                actions.open_youtube()
                return self._loc("Opening YouTube.",
                                 "ইউটিউব খুলছি।")
            result = actions.open_app(key)
            if result and str(result).lower().startswith(
                    "sorry"):
                return result
            return self._loc(f"Opening {disp_en}.",
                             f"{disp_bn} খুলছি।")
        return None

    def _dashboard_intents(self, text):
        """LOCAL Command Center routing (v5.5, garble-tolerant
        v5.7): open/close the fullscreen dashboard in EN/BN/HI.

        Returns (reply, "dashboard_open"/"dashboard_close") or
        None. The window itself lives in nalox.py (dashboard.py)
        — the brain only routes, exactly like the restart intent.
        A dashboard token is REQUIRED, so a bare "বন্ধ করো" keeps
        its standby meaning, "close the chrome tab" keeps its
        browser meaning, and a bare "open ..." keeps its app
        meaning. Checked before the standby family in
        _handle_single (see the note there).

        v5.7: matching runs on _dash_tokens, so the predictable
        mishearings land too — "mellox close common centre",
        "close command centre", "komen center বন্ধ করো",
        "dasboard kholo", "dash board open". And a bare
        center-ish token beside a close verb also closes: with
        the Command Center up, "close the centre" can mean
        nothing else.
        """
        t = text or ""
        toks = self._dash_tokens(t)
        tokset = set(toks)
        has_dash = "dashboard" in tokset \
            or "commandcenter" in tokset \
            or any(w in t for w in self._DASH_WORDS)
        if not has_dash and not (
                tokset & self._DASH_CENTER_TOKENS
                and ("close" in tokset or "বন্ধ" in t
                     or "बंद" in t)):
            return None
        rlang = _text_lang(t, self.lang)
        is_close = bool(re.search(r"\b(close|hide)\b", t)) \
            or "বন্ধ" in t or "बंद" in t \
            or "close" in tokset or "hide" in tokset
        is_open = bool(re.search(r"\b(open|show|bring up)\b", t)) \
            or "খোলো" in t or "খুলুন" in t or "দেখাও" in t \
            or "खोलो" in t or "दिखाओ" in t \
            or "open" in tokset or "show" in tokset \
            or "kholo" in tokset or "khulo" in tokset
        if is_close:
            if rlang == "hi":
                return "डैशबोर्ड बंद कर रहा हूँ।", "dashboard_close"
            if rlang == "bn":
                return "ড্যাশবোর্ড বন্ধ করে দিলাম।", "dashboard_close"
            return "Closing the Command Center.", "dashboard_close"
        if is_open:
            if rlang == "hi":
                return "डैशबोर्ड खोल रहा हूँ।", "dashboard_open"
            if rlang == "bn":
                return "ড্যাশবোর্ড খুলে দিলাম।", "dashboard_open"
            return "Opening the Command Center.", "dashboard_open"
        return None

    # ------------------------------------------------ v5.4 memory
    _MEM_SAVE_VERBS_BN = ("মনে রেখো", "মনে রাখো", "মনে রেখে দাও",
                          "মনে করে রাখো")
    _MEM_SAVE_VERBS_HI = ("याद रखो", "याद रख लो", "याद रखना")

    def _memory_intents(self, text):
        """LOCAL memory commands (v5.4): save a fact, answer
        "what do you remember", and answer the memory QUESTION
        itself — all from memory_store, never from an LLM.

        The order matters: the question and recall checks run
        BEFORE the save pattern, so "do you remember that…?"
        can never be filed as a fact, and "তোমার memory আছে?"
        can never leak to a provider (a chain model answered
        that one with a false "আমার দীর্ঘমেয়াদী memory নেই").
        Returns the spoken reply, or None."""
        t = text or ""
        rlang = _text_lang(t, self.lang)
        user = self._addr()
        user_bn = self._addr_bn()

        # ---------- (c) the memory question ----------
        question = (
            "do you have memory" in t
            or "do you have a memory" in t
            or "do you have long-term memory" in t
            or "do you have long term memory" in t
            or "তোমার memory আছে" in t
            or "তোমার মেমরি আছে" in t
            or "তোমার কি memory" in t
            or "তোমার কি মেমরি" in t
            or "তুমি কি মনে রাখতে পারো" in t
            or "क्या तुम्हारी memory" in t
            or "तुम्हारी memory है" in t
            or ("দীর্ঘমেয়াদী" in t
                and ("memory" in t or "মেমরি" in t)))
        if question:
            facts = []
            if self.memory is not None:
                try:
                    facts = self.memory.facts()
                except Exception:
                    facts = []
            example = facts[-1] if facts else ""
            if rlang == "bn":
                reply = (f"হ্যাঁ, {user_bn} — আমার long-term "
                         "memory আছে। তুমি যা মনে রাখতে বলো, তা "
                         "এই laptop-এ save থাকে — restart হলেও "
                         "মুছে যায় না।")
                if example:
                    reply += f" যেমন, আমার মনে আছে: {example}।"
                return reply
            if rlang == "hi":
                reply = (f"हाँ, {user} — मेरी long-term memory "
                         "है। जो याद रखने को कहते हैं, वह इस "
                         "laptop पर save रहता है — restart के "
                         "बाद भी।")
                if example:
                    reply += f" जैसे, मुझे याद है: {example}।"
                return reply
            reply = (f"Yes, {user} — I have long-term memory. "
                     "What you tell me to remember is saved on "
                     "this laptop and survives restarts.")
            if example:
                reply += f" For example, I remember: {example}."
            return reply

        # ---------- (b) recall ----------
        if "what do you remember" in t \
                or "what have you remembered" in t \
                or "what do you know about me" in t \
                or "কী মনে আছে" in t or "কি মনে আছে" in t \
                or "কী মনে রেখেছ" in t or "কি মনে রেখেছ" in t \
                or "তুমি কী মনে রেখেছ" in t \
                or "আমার সম্পর্কে কী জানো" in t \
                or "আমার সম্পর্কে কি জানো" in t \
                or "मेरे बारे में क्या जानते हो" in t \
                or "तुम्हें क्या याद है" in t:
            return self._memory_recall(rlang)

        # ---------- (a) save a fact ----------
        fact = None
        save_lang = rlang
        m = re.search(r"\bremember\b\s+(?:that\s+)?(.+)", t)
        if m and not t.startswith(("do you", "can you",
                                   "did you", "what")):
            fact = _clean(m.group(1))
            save_lang = "en" if rlang == "en" else rlang
        if fact is None:
            for verb in self._MEM_SAVE_VERBS_BN:
                if verb in t:
                    before, _v, after = t.partition(verb)
                    fact = _clean(after.lstrip(" :ঃ,।")
                                  .removeprefix("যে "))
                    if len(fact) < 4:
                        fact = _clean(before.rstrip(" ,।"))
                    save_lang = "bn"
                    break
        if fact is None:
            for verb in self._MEM_SAVE_VERBS_HI:
                if verb in t:
                    before, _v, after = t.partition(verb)
                    fact = _clean(after.lstrip(" :।,")
                                  .removeprefix("कि "))
                    if len(fact) < 4:
                        fact = _clean(before.rstrip(" ,।"))
                    save_lang = "hi"
                    break
        if fact is not None:
            if fact in ("এটা", "এইটা", "এটা একটা", "that", "this",
                        "it"):
                fact = ""
            saved = False
            if self.memory is not None and fact:
                try:
                    saved = bool(self.memory.remember(fact))
                except Exception as exc:
                    log.warning("memory save failed: %s", exc)
                    saved = False
            if saved:
                if save_lang == "bn":
                    return f"মনে রাখলাম, {user_bn}।"
                if save_lang == "hi":
                    return f"याद रख लिया, {user}।"
                return f"Remembered, {user}."
            if self.memory is None:
                if save_lang == "bn":
                    return (f"এখন আমার মেমরি কাজ করছে না, "
                            f"{user_bn}।")
                if save_lang == "hi":
                    return f"अभी मेरी memory काम नहीं कर रही, {user}।"
                return (f"My memory isn't available right now, "
                        f"{user}.")
            if save_lang == "bn":
                return f"কী মনে রাখব, {user_bn}? কথাটা বলো।"
            if save_lang == "hi":
                return f"क्या याद रखूँ, {user}? बात कहिए।"
            return (f"What should I remember, {user}? "
                    "Say the fact after 'remember'.")
        return None

    def _memory_recall(self, rlang=None):
        """What Nalox remembers, spoken in the asker's
        language: the learned prefs (call-me name, preferred
        language) first — they ARE memory too — then the most
        recent stored facts. v5.4: prefs join the answer, and
        the language follows the utterance, not just the
        session default."""
        if rlang is None:
            rlang = self.lang
        user = self._addr()
        user_bn = self._addr_bn()
        bits = []
        pref_name = str(self.cfg.get("preferred_name")
                        or self._prefs.get("preferred_name")
                        or "").strip()
        if pref_name:
            if rlang == "bn":
                bits.append(f"তোমাকে {self._addr_bn()} বলে "
                            "ডাকতে বলেছ")
            elif rlang == "hi":
                bits.append(f"आपने कहा था कि मैं आपको "
                            f"{pref_name} कहूँ")
            else:
                bits.append(f"you asked me to call you "
                            f"{pref_name}")
        pref_lang = self._pref_lang()
        if pref_lang:
            lang_word = {"en": "English", "bn": "বাংলা",
                         "hi": "हिंदी"}[pref_lang]
            if rlang == "bn":
                bits.append(f"তুমি {lang_word} ভাষায় কথা "
                            "বলতে বলেছ")
            elif rlang == "hi":
                bits.append(f"आप {lang_word} में बात करना "
                            "पसंद करते हैं")
            else:
                bits.append(f"you prefer replies in "
                            f"{lang_word}")
        facts = []
        total = 0
        if self.memory is not None:
            try:
                facts = self.memory.recent(5)
                total = len(self.memory)
            except Exception:
                facts, total = [], 0
        if not bits and not facts:
            if rlang == "bn":
                return (f"এখনো কিছু মনে রাখিনি, {user_bn}। "
                        "'মনে রেখো' বলে কিছু বললেই সারা জীবন "
                        "রেখে দেব।")
            if rlang == "hi":
                return (f"अभी कुछ याद नहीं रखा, {user}। "
                        "'याद रखो' कहकर कुछ कहिए, रख लूँगा।")
            return (f"I don't have anything in memory yet, "
                    f"{user}. Say 'remember' followed by a "
                    "fact, and I'll keep it for good.")
        if facts:
            if rlang == "bn":
                bits.append("মনে রেখেছি: " + "। ".join(facts))
            elif rlang == "hi":
                bits.append("याद रखा है: " + "; ".join(facts))
            else:
                bits.append("I've noted: " + "; ".join(facts))
            if total > len(facts):
                more = total - len(facts)
                if rlang == "bn":
                    bits.append(f"আরও {_bn_num(more)}টা কথা "
                                "আছে")
                elif rlang == "hi":
                    bits.append(f"और {_hi_num(more)} बातें हैं")
                else:
                    bits.append(f"and {more} more")
        if rlang == "bn":
            return f"আমার মনে আছে, {user_bn}: " \
                   + "। ".join(bits) + "।"
        if rlang == "hi":
            return f"मुझे याद है, {user}: " \
                   + "; ".join(bits) + "।"
        return f"Here's what I remember, {user}: " \
               + "; ".join(bits) + "."

    # ------------------------------------------------------------------
    def _parse_reminder(self, text):
        """'remind me in 10 minutes to X' / 'remind me at 6 pm to X' /
        Bengali '... মনে করিয়ে দিও'. Returns a reply string or None."""
        due = None
        task = None
        m = re.search(r"\bremind me in\s+(\d+)\s*"
                      r"(minutes?|mins?|hours?|hrs?|seconds?|secs?)\b"
                      r"\s*(?:to\s+)?(.+)", text)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("hour") or unit.startswith("hr"):
                delta = timedelta(hours=n)
            elif unit.startswith("sec"):
                delta = timedelta(seconds=n)
            else:
                delta = timedelta(minutes=n)
            due = datetime.now() + delta
            task = _clean(m.group(3))
        if due is None:
            m = re.search(r"\bremind me at\s+(\d{1,2})(?::(\d{2}))?\s*"
                          r"(am|pm)?\b\s*(?:to\s+)?(.+)", text)
            if m:
                hour = int(m.group(1))
                minute = int(m.group(2) or 0)
                ap = m.group(3)
                if ap == "pm" and hour < 12:
                    hour += 12
                elif ap == "am" and hour == 12:
                    hour = 0
                now = datetime.now()
                due = now.replace(hour=hour, minute=minute,
                                  second=0, microsecond=0)
                if due <= now:
                    due += timedelta(days=1)  # that time today has passed
                task = _clean(m.group(4))
        if due is None and "মনে করিয়ে দিও" in text:
            parsed = self._parse_reminder_bn(text)
            if parsed:
                due, task = parsed
        if due is None or not task:
            return None
        if self.reminders is None:
            return self._loc("Reminders aren't switched on right now.",
                             "রিমাইন্ডার এখন চালু নেই।")
        self.reminders.add(due, task, self.lang)
        if self.lang == "bn":
            hour12 = due.hour % 12 or 12
            part = ("রাত" if due.hour < 4 else "সকাল" if due.hour < 12
                    else "দুপুর" if due.hour < 16
                    else "বিকেল" if due.hour < 19 else "রাত")
            when = (f"{part} {_bn_num(hour12)}টা "
                    f"{_bn_num(f'{due.minute:02d}')} মিনিটে")
            return f"ঠিক আছে, {when} মনে করিয়ে দেব: {task}।"
        when = due.strftime("%I:%M %p").lstrip("0")
        return f"Done. I'll remind you at {when} — {task}."

    def _parse_reminder_bn(self, text):
        """Pull (due, task) out of a Bengali reminder sentence."""
        latin = text.translate(_LATIN_DIGITS)
        due = None
        m = re.search(r"(\d+)\s*মিনিট", latin)
        if m:
            due = datetime.now() + timedelta(minutes=int(m.group(1)))
        else:
            m = re.search(r"(\d+)\s*ঘণ্টা", latin)
            if m:
                due = datetime.now() + timedelta(hours=int(m.group(1)))
        if due is None:
            return None
        task = text
        for junk in ("মনে করিয়ে দিও", "মিনিট", "ঘণ্টা", "আমাকে", "আমায়",
                     "পরে", "পর"):
            task = task.replace(junk, " ")
        task = re.sub(r"[০-৯0-9]+", " ", task)
        task = re.sub(r"\s+", " ", task).strip(" .!?")
        return due, (task or "তোমার রিমাইন্ডার")

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _execute_confirmed(self, kind):
        """Run a confirmable action NOW (shared by the yes-answer in
        _handle_confirmation and by full-control mode below)."""
        if kind == "shutdown":
            return actions.shutdown_pc(), "exit"
        if kind == "forget":
            if self.memory is not None:
                self.memory.clear()
            return self._loc("Done. I've forgotten everything.",
                             "হয়ে গেছে। সব ভুলে গেছি।"), None
        return actions.restart_pc(), "exit"

    def _confirm_or_execute(self, kind, question_en, question_bn):
        """Confirmation gate (v4.1).

        Arjun's standing instruction is FULL control of his own PC
        (config full_control, default ON, toggle in Settings): the
        action runs immediately — the action's own reply line is the
        brief spoken acknowledgement. With full_control OFF, the
        pre-v4.1 behaviour returns: park the action in self.pending
        and ask "are you sure?" first.
        """
        if self.cfg.get("full_control", True):
            log.info("Full control: executing %s without asking.", kind)
            _lb("SYSTEM", f"Full control: {kind} executed without asking")
            return self._execute_confirmed(kind)
        self.pending = _Confirm(kind)
        return self._loc(question_en, question_bn), "confirm"

    def _handle_confirmation(self, text):
        pending, self.pending = self.pending, None
        yes = re.search(r"\b(yes|yeah|yep|sure|ok|okay|confirm|do it)\b", text) \
            or "হ্যাঁ" in text or "হুম" in text or "ঠিক আছে" in text
        if yes:
            return self._execute_confirmed(pending.kind)
        if pending.kind in ("shutdown", "restart"):
            actions.cancel_shutdown()
        return self._loc("Okay, cancelled. I won't do anything.",
                         "ঠিক আছে, বাতিল করলাম। কিছু করব না।"), None

    # ------------------------------------------------ v5.0 YouTube play
    _YT_QUERY_LEADERS = ("a", "an", "the", "একটা", "একটি", "এক",
                         "ek", "koi", "কোনো", "कोई", "एक")

    def _yt_clean_query(self, query):
        """Drop leading filler words so the resolver searches
        for the thing itself: "a sad song" -> "sad song",
        "একটা sad song" -> "sad song"."""
        words = (query or "").split()
        while words and words[0].strip(".,!?").lower() \
                in self._YT_QUERY_LEADERS:
            words.pop(0)
        return " ".join(words).strip(" .!?")

    def _play_on_youtube(self, query):
        """PLAY the first YouTube result for query (v5.0).

        Returns (played, clean_query): played=True when a watch
        URL was opened and the video is actually starting; on
        any resolution failure the search page opens instead
        (the pre-v5.0 behaviour) and played=False, so the reply
        can say so honestly in one short line. The query is
        remembered for the "play the first one" follow-up."""
        q = self._yt_clean_query(query)
        if q:
            self._last_yt_query = q
        url = None
        try:
            import youtube_play
            url = youtube_play.first_video_url(q)
        except Exception:
            url = None
        # The opening itself goes through actions.play_on_youtube
        # (the one place that opens YouTube media): it resolves
        # through the same resolver — memoised, so no second
        # fetch — and opens the watch URL, or the search page
        # when resolution failed. This helper only decides what
        # the honest spoken reply is.
        actions.play_on_youtube(q)
        return (url is not None), q

    # v7.7 (item E): after playing a song, the ONE specific
    # follow-up offer rotates between these — and is only
    # ever appended when the previous reply did not already
    # end with an offer (see _song_done_line).
    _PLAY_OFFERS_BN = ("আরেকটা গান চালাব?",
                       "ভলিউম বাড়িয়ে দেব?")

    def _song_done_line(self, query=None):
        """The play confirmation in the owner's shape
        (v7.7, item E): COMPLETED form, never the
        progressive — he objected to "আমি চালাচ্ছি" and
        asked for done-and-dusted: "স্যার, আমি সং চালিয়ে
        দিলাম". Then AT MOST ONE follow-up offer specific
        to the finished action (the next song / the
        volume), rotating, and never when the previous
        reply already ended with an offer."""
        addr = self._addr_bn()
        if query:
            line = (f"ঠিক আছে {addr}, ইউটিউবে {query} "
                    "চালিয়ে দিলাম।")
        else:
            line = f"ঠিক আছে {addr}, গান চালিয়ে দিলাম।"
        try:
            if not getattr(self, "_last_reply_had_offer",
                           False):
                idx = getattr(self, "_play_offer_idx", 0)
                self._play_offer_idx = idx + 1
                line += " " + self._PLAY_OFFERS_BN[
                    idx % len(self._PLAY_OFFERS_BN)]
        except Exception:
            pass
        return line

    def _play_reply(self, query, played):
        """The short spoken line for a play attempt, in the
        command's language — honest when only search opened."""
        if self.lang == "bn":
            if played:
                return self._song_done_line(query)
            return (f"সরাসরি চালাতে পারলাম না, {self._addr_bn()} — "
                    f"{query}-এর search খুলে দিলাম।")
        if self.lang == "hi":
            if played:
                return f"यूट्यूब पर {query} चला रहा हूँ।"
            return (f"सीधे नहीं चला पाया, {self._addr()} — "
                    f"{query} की search खोल दी है।")
        if played:
            return f"Playing {query} on YouTube."
        return (f"Couldn't play it directly, {self._addr()} — "
                f"opened the search for {query}.")

    def _wants_first_one(self, text):
        """The "play the first one" follow-up (v5.0): EN "play
        the first one", BN "প্রথমটা চালাও", HI "पहला वाला चलाओ"
        — re-play the remembered query's top result."""
        if "প্রথমটা" in text:
            return True
        if "पहला वाला" in text or "पहली वाली" in text:
            return True
        return bool(
            re.search(r"\bfirst\s+(?:one|video|song|result)\b", text)
            and re.search(r"\bplay\b", text))

    def _first_one_reply(self):
        """Re-resolve the remembered query and play its first
        result; ask for a name when nothing is remembered."""
        q = (self._last_yt_query or "").strip()
        if not q:
            if self.lang == "bn":
                return (f"আগে কোনো গান বা ভিডিও খুঁজিনি, "
                        f"{self._addr_bn()} — নামটা বলো।")
            if self.lang == "hi":
                return (f"पहले कुछ खोजा नहीं है, {self._addr()} — "
                        "नाम बताइए।")
            return (f"Nothing searched yet, {self._addr()} — "
                    "name a song or video first.")
        played, query = self._play_on_youtube(q)
        return self._play_reply(query, played)

    # ------------------------------------------------ v5.2 crash-guard
    def _run_guarded(self, label, fn, timeout):
        """Run fn() on a daemon worker thread; wait up to
        `timeout` seconds. Returns (True, value) on completion,
        (False, None) on timeout or exception — both logged with
        the [CRASH-GUARD] tag.

        Used for every winlayout call in the dispatch path:
        ctypes into user32 is the one place a Python try/except
        cannot be fully trusted (an under-declared signature can
        wedge or fault NATIVELY), so those calls never run on
        the command thread again. A wedged worker is abandoned
        (daemon — it cannot block exit or freeze the loop),
        never joined a second time."""
        box = {}

        def _work():
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc

        worker = threading.Thread(target=_work, daemon=True,
                                  name="nalox-guard-" + label)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            log.error("[CRASH-GUARD] %s did not finish within "
                      "%.0fs — abandoned on its worker thread; "
                      "Nalox keeps running", label, timeout)
            _lb("ERROR", f"[CRASH-GUARD] {label} timed out — "
                         "skipped, Nalox keeps running")
            return False, None
        if "error" in box:
            exc = box["error"]
            log.error("[CRASH-GUARD] %s failed: %s: %s",
                      label, type(exc).__name__, exc)
            _lb("ERROR", f"[CRASH-GUARD] {label} failed: "
                         f"{type(exc).__name__}: {exc}")
            return False, None
        return True, box.get("value")

    # ------------------------------------------------ v5.1 split-screen
    def _snap_app_to(self, name, side):
        """Open (if needed) and snap one app to a screen half.

        Returns (opened, snapped). The app is opened through
        the EXISTING machinery — actions.open_app, with the
        website route as fallback for names that live in the
        browser (whatsapp, gmail…) — then winlayout polls for
        its window on the app's known title/process hints and
        snaps it. snapped=False with opened=True means the app
        is up but its window never showed: the reply says so
        and the app is left open, unsnapped.

        v5.2: the winlayout calls themselves run through
        _run_guarded (worker thread + join timeout) — see its
        docstring for why ctypes never runs on this thread."""
        import winlayout
        titles, procs = _app_window_hints(name)
        opened = False
        ok, hwnd = self._run_guarded(
            "window lookup",
            lambda: winlayout.find_window(titles, procs), 6.0)
        opened = bool(ok and hwnd is not None)
        if not opened:
            result = actions.open_app(name)
            if "could not find" in (result or "").lower():
                key = name.strip().lower()
                if key in actions.WEBSITES:
                    actions.open_website(name)
                    opened = True
                elif key == "youtube":
                    actions.open_youtube()
                    opened = True
            else:
                opened = True
        ok, snapped = self._run_guarded(
            "window snap",
            lambda: winlayout.snap_app(name, side, titles, procs),
            15.0)
        return opened, bool(ok and snapped)

    def _split_screen_reply(self, text):
        """Split-screen workspace commands (v5.1): the two-app
        arrangement and the single foreground-window form.
        Returns the spoken reply, or None when the text is not
        a split-screen command. Replies are one short line and
        honest: an app whose window can't be found is reported,
        never silently claimed as placed."""
        parsed = _split_screen_parse(text)
        if parsed is None:
            return None
        rlang = _text_lang(text, self.lang)
        user = self._addr()
        user_bn = self._addr_bn()
        if parsed[0] == "single":
            side = parsed[1]
            import winlayout
            _ok, snapped = self._run_guarded(
                "window snap",
                lambda: winlayout.snap_active(side), 6.0)
            ok = bool(_ok and snapped)
            side_bn = "বাম" if side == "left" else "ডান"
            if rlang == "bn":
                if ok:
                    return f"এটাকে {side_bn} দিকে রাখলাম, {user_bn}।"
                return f"window-টা সরাতে পারলাম না, {user_bn}।"
            if rlang == "hi":
                if ok:
                    return f"इसे {side} में रख दिया, {user}।"
                return f"वो window नहीं हिला पाया, {user}।"
            if ok:
                return f"Done, {user} — moved it to the {side}."
            return f"I couldn't move that window, {user}."
        _kind, left_app, right_app = parsed
        l_open, l_ok = self._snap_app_to(left_app, "left")
        r_open, r_ok = self._snap_app_to(right_app, "right")
        if l_ok and r_ok:
            if rlang == "bn":
                return (f"হয়ে গেছে, {user_bn} — বাম দিকে "
                        f"{left_app}, ডান দিকে {right_app}।")
            if rlang == "hi":
                return (f"हो गया, {user} — left में {left_app}, "
                        f"right में {right_app}।")
            return (f"Done, {user} — {left_app} on the left, "
                    f"{right_app} on the right.")
        # Partial / failed: name what actually happened, app by
        # app — placed, opened-but-window-not-found, or not
        # openable on this laptop.
        def _state(app, opened, snapped):
            if snapped:
                return ("ok", app)
            return ("window" if opened else "missing", app)
        states = [_state(left_app, l_open, l_ok),
                  _state(right_app, r_open, r_ok)]
        good = [a for s, a in states if s == "ok"]
        bad_window = [a for s, a in states if s == "window"]
        bad_missing = [a for s, a in states if s == "missing"]
        if rlang == "bn":
            bits = []
            if good:
                bits.append(f"{' আর '.join(good)} ঠিক জায়গায় "
                            "বসেছে")
            for a in bad_window:
                bits.append(f"{a}-এর window খুঁজে পেলাম না — "
                            "ওটা খোলা আছে, শুধু বসাতে পারলাম না")
            for a in bad_missing:
                bits.append(f"{a} এই ল্যাপটপে খুঁজে পেলাম না")
            return " — ".join(bits) + f", {user_bn}।"
        if rlang == "hi":
            bits = []
            if good:
                bits.append(f"{' और '.join(good)} अपनी जगह पर है")
            for a in bad_window:
                bits.append(f"{a} की window नहीं मिली — वो खुला "
                            "है, बस जगह पर नहीं बैठा पाया")
            for a in bad_missing:
                bits.append(f"{a} इस laptop पर नहीं मिला")
            return " — ".join(bits) + f", {user}।"
        bits = []
        if good:
            bits.append(f"{' and '.join(good)} in place")
        for a in bad_window:
            bits.append(f"couldn't find {a}'s window — it's "
                        "open, just not snapped")
        for a in bad_missing:
            bits.append(f"couldn't open {a} on this laptop")
        return " — ".join(bits) + f", {user}."

    # ------------------------------------------------ v5.4 phone control
    _PHONE_APP_DISPLAY = {
        "youtube": "YouTube", "whatsapp": "WhatsApp",
        "instagram": "Instagram", "chrome": "Chrome",
        "telegram": "Telegram", "spotify": "Spotify",
        "camera": "Camera", "settings": "Settings",
    }
    _PHONE_REL_EN = {"mother", "mom", "mummy", "maa", "father",
                     "dad", "papa"}
    # v6.1: the phone-mention tokens for the verb-free phone
    # open (_phone_app_mention) — EN/BN/HI, matched on
    # _normalise_asr tokens.
    _PHONE_TOKENS = {"phone", "ফোন", "ফোনে", "মোবাইল",
                     "mobile", "फोन", "मोबाइल"}
    _PHONE_CALL_STOP = {"me", "nalox", "yourself", "it", "a",
                        "an", "the", "karo", "kar", "koro",
                        "kor", "ho", "hai", "now", "back"}

    def _phone_action(self, kind, **kw):
        """One phone action (call / open / battery) through
        the v5.2 crash-guard — the same guarded path the snap
        tools use. phone_control already bounds every adb call
        (<= 10 s) and never raises; the guard is the second
        wall, so a wedged phone stack can only ever cost one
        honest "took too long" line. Returns the action's
        result dict.

        v6.0 TRANSPORT UNIFICATION: the Nalox Phone APP LINK
        is tried first whenever the app is connected
        (phone_link mirrors phone_control's result dicts, so
        every reply builder below works unchanged); ADB is
        the fallback — including when a link attempt fails
        mid-command, so a half-open socket can never strand a
        command the Wi-Fi path would have served. Verdicts
        that are transport-independent (unknown contact/app,
        app not installed) return at once instead of burning
        a second attempt."""
        import phone_control

        def _via_link(pl):
            if kind == "call":
                return pl.call_contact(self.cfg,
                                       kw.get("name", ""))
            if kind == "open":
                return pl.open_app(self.cfg, kw.get("app", ""))
            return pl.phone_battery(self.cfg)

        def _via_adb():
            if kind == "call":
                return phone_control.call_contact(
                    self.cfg, kw.get("name", ""))
            if kind == "open":
                return phone_control.open_app(
                    self.cfg, kw.get("app", ""))
            return phone_control.phone_battery(self.cfg)

        def _dispatch():
            try:
                import phone_link
                if phone_link.is_connected():
                    res = _via_link(phone_link)
                    if isinstance(res, dict) and res.get("ok"):
                        return res
                    if isinstance(res, dict) \
                            and res.get("reason") in (
                                "unknown_contact", "unknown_app",
                                "not_installed"):
                        return res
            except Exception:
                pass
            return _via_adb()

        ok, result = self._run_guarded("phone " + kind,
                                       _dispatch, 35.0)
        if not ok or not isinstance(result, dict):
            return {"ok": False, "reason": "timeout"}
        return result

    def _phone_down_line(self, result, rlang):
        """Why the phone didn't answer, in the command's
        language — short, honest, and it names the remedy:
        permission tap / missing tools / the Wi-Fi causes
        (asleep, off this Wi-Fi, Wireless debugging off, or a
        reboot changed the address → re-pair in Settings →
        Phone)."""
        user = self._addr()
        user_bn = self._addr_bn()
        if (result or {}).get("reason") == "timeout":
            if rlang == "bn":
                return (f"ফোনটা উত্তর দিতে দেরি করছে, "
                        f"{user_bn} — একটু পরে আবার বলো।")
            if rlang == "hi":
                return (f"फोन जवाब देने में देर कर रहा है, "
                        f"{user} — थोड़ी देर बाद फिर कहिए।")
            return (f"Your phone took too long to answer, "
                    f"{user} — try again in a moment.")
        state = (result or {}).get("state") or "none"
        if state == "unauthorized":
            if rlang == "bn":
                return (f"ফোনটা অনুমতি চাইছে, {user_bn} — ওর "
                        "screen-এ Allow চাপো (Wireless "
                        "debugging), তারপর আবার বলো।")
            if rlang == "hi":
                return (f"फोन अनुमति माँग रहा है, {user} — "
                        "उसकी screen पर Allow दबाइए (Wireless "
                        "debugging), फिर फिर से कहिए।")
            return (f"Your phone is asking permission, {user} "
                    "— tap Allow on its screen (Wireless "
                    "debugging), then ask me again.")
        if state == "noadb":
            if rlang == "bn":
                return (f"এই ল্যাপটপে phone control-এর tools "
                        f"নেই, {user_bn}।")
            if rlang == "hi":
                return (f"इस laptop पर phone control के tools "
                        f"नहीं हैं, {user}।")
            return (f"Phone control tools are missing on this "
                    f"laptop, {user}.")
        if rlang == "bn":
            return (f"ফোনের সঙ্গে যোগাযোগ হচ্ছে না, {user_bn} "
                    "— ফোন ঘুমিয়ে থাকতে পারে, এই Wi-Fi-তে "
                    "না-ও থাকতে পারে, বা Wireless debugging "
                    "বন্ধ থাকতে পারে। ফোন restart হয়ে থাকলে "
                    "address বদলে যায় — Settings → Phone "
                    "থেকে আবার pair করো।")
        if rlang == "hi":
            return (f"फोन से संपर्क नहीं हो रहा, {user} — "
                    "फोन सोया हो सकता है, इस Wi-Fi पर न हो, "
                    "या Wireless debugging बंद हो। फोन restart "
                    "हुआ हो तो address बदल जाता है — "
                    "Settings → Phone से फिर pair कीजिए।")
        return (f"Your phone isn't reachable, {user} — it "
                "may be asleep, off this Wi-Fi, or Wireless "
                "debugging is off. If it restarted, its "
                "address can change — re-pair from "
                "Settings → Phone.")

    def _phone_call_reply(self, result, spoken_name, rlang):
        user = self._addr()
        user_bn = self._addr_bn()
        disp = (result.get("name") or spoken_name or "").strip()
        if result.get("ok"):
            if result.get("mode") == "dial":
                if rlang == "bn":
                    return (f"সরাসরি কল শুরু হলো না, {user_bn} "
                            f"— {disp}-এর নম্বরটা dialer-এ "
                            "খুলে দিয়েছি; এক tap-এই কল হবে।")
                if rlang == "hi":
                    return (f"सीधे कॉल शुरू नहीं हुई, {user} — "
                            f"{disp} का नंबर dialer में खोल "
                            "दिया है; एक tap में कॉल लगेगी।")
                return (f"Direct calling didn't start, {user} "
                        f"— I've opened the dialer with "
                        f"{disp}'s number; one tap to call.")
            if rlang == "bn":
                return f"{disp}-কে কল করছি, {user_bn}।"
            if rlang == "hi":
                return f"{disp} को कॉल कर रहा हूँ, {user}।"
            your = "your " if disp.lower() in self._PHONE_REL_EN \
                else ""
            return f"Calling {your}{disp}, {user}."
        reason = result.get("reason")
        if reason == "unknown_contact":
            if rlang == "bn":
                return (f"{spoken_name}-এর নম্বর আমার কাছে "
                        f"নেই, {user_bn} — Settings → Phone-এ "
                        "যোগ করে দাও।")
            if rlang == "hi":
                return (f"{spoken_name} का नंबर मेरे पास नहीं "
                        f"है, {user} — Settings → Phone में "
                        "जोड़ दीजिए।")
            return (f"I don't have a number saved for "
                    f"{spoken_name}, {user} — add it in "
                    "Settings → Phone.")
        if reason == "not_connected":
            return self._phone_down_line(result, rlang)
        if rlang == "bn":
            return f"কলটা করা গেল না, {user_bn}।"
        if rlang == "hi":
            return f"कॉल नहीं हो पाई, {user}।"
        return f"The call didn't go through, {user}."

    def _phone_open_reply(self, result, spoken_app, rlang):
        user = self._addr()
        user_bn = self._addr_bn()
        canon = result.get("app")
        disp = self._PHONE_APP_DISPLAY.get(canon, spoken_app)
        if result.get("ok"):
            if rlang == "bn":
                return f"ফোনে {disp} খুলছি, {user_bn}।"
            if rlang == "hi":
                return f"फोन पर {disp} खोल रहा हूँ, {user}।"
            return f"Opening {disp} on your phone, {user}."
        reason = result.get("reason")
        if reason == "unknown_app":
            if rlang == "bn":
                return (f"{spoken_app} ফোনে খুলতে পারি না, "
                        f"{user_bn} — YouTube, WhatsApp, "
                        "Instagram, Chrome, Telegram, Spotify, "
                        "Camera আর Settings পারি।")
            if rlang == "hi":
                return (f"{spoken_app} फोन पर नहीं खोल सकता, "
                        f"{user} — YouTube, WhatsApp, "
                        "Instagram, Chrome, Telegram, Spotify, "
                        "Camera और Settings खोल सकता हूँ।")
            return (f"I can't open {spoken_app} on the phone "
                    f"yet, {user} — I know YouTube, WhatsApp, "
                    "Instagram, Chrome, Telegram, Spotify, "
                    "Camera and Settings.")
        if reason == "not_installed":
            if rlang == "bn":
                return (f"{disp} ফোনে installed নেই মনে হচ্ছে, "
                        f"{user_bn}।")
            if rlang == "hi":
                return (f"{disp} फोन में installed नहीं लगता, "
                        f"{user}।")
            return (f"{disp} doesn't seem to be installed on "
                    f"your phone, {user}.")
        if reason == "not_connected":
            return self._phone_down_line(result, rlang)
        if rlang == "bn":
            return f"{disp} খুলতে পারলাম না, {user_bn}।"
        if rlang == "hi":
            return f"{disp} नहीं खोल पाया, {user}।"
        return f"I couldn't open {disp} on the phone, {user}."

    def _phone_battery_reply(self, result, rlang):
        user = self._addr()
        user_bn = self._addr_bn()
        if result.get("ok"):
            level = result.get("level")
            if rlang == "bn":
                return (f"ফোনের ব্যাটারি {_bn_num(level)} "
                        f"শতাংশ, {user_bn}।")
            if rlang == "hi":
                return (f"आपके फोन की बैटरी {_hi_num(level)} "
                        f"प्रतिशत है, {user}।")
            return f"Your phone is at {level} percent, {user}."
        if result.get("reason") == "not_connected":
            return self._phone_down_line(result, rlang)
        if rlang == "bn":
            return f"ফোনের ব্যাটারি জানতে পারলাম না, {user_bn}।"
        if rlang == "hi":
            return f"फोन की बैटरी नहीं जान पाया, {user}।"
        return f"I couldn't read your phone's battery, {user}."

    def _phone_tool_line(self, kind, result, target):
        """The agent-tool result string (English, for the
        LLM) for a phone action — the same facts as the
        spoken lines, none of the theatre."""
        if result.get("ok"):
            if kind == "call":
                if result.get("mode") == "dial":
                    return (f"Direct call didn't start; the "
                            f"phone's dialer is open with "
                            f"{result.get('name') or target}'s "
                            "number filled in — one tap to call.")
                return (f"Calling "
                        f"{result.get('name') or target} on "
                        "Arjun's phone now.")
            if kind == "open":
                disp = self._PHONE_APP_DISPLAY.get(
                    result.get("app"), result.get("app")
                    or target)
                return f"Opened {disp} on Arjun's phone."
            return (f"Arjun's phone battery is at "
                    f"{result.get('level')}%.")
        reason = result.get("reason")
        if reason == "unknown_contact":
            return (f"No number is saved for '{target}'. Ask "
                    "Arjun to add it in Settings → Phone.")
        if reason == "unknown_app":
            return (f"'{target}' is not an app I can open on "
                    "the phone (youtube, whatsapp, instagram, "
                    "chrome, telegram, spotify, camera, "
                    "settings).")
        if reason == "not_installed":
            disp = self._PHONE_APP_DISPLAY.get(
                result.get("app"), target)
            return f"{disp} is not installed on Arjun's phone."
        if reason == "timeout":
            return "The phone action timed out."
        if result.get("state") == "unauthorized":
            return ("The phone is waiting for Arjun to tap "
                    "Allow (Wireless debugging) on its screen.")
        if result.get("state") == "noadb":
            return "Phone control tools (ADB) are missing."
        return ("Arjun's phone is not reachable over Wi-Fi "
                "right now (asleep, off this Wi-Fi, or "
                "Wireless debugging off; a reboot can change "
                "its address — re-pairing lives in "
                "Settings → Phone).")

    def _phone_link_intent(self, rlang):
        """v6.0: "send me the phone link" / "ফোনের লিংক
        পাঠাও" — pairing mode on for 10 minutes and the
        pairing URL pushed to the owner via Telegram (he taps
        it on the phone; zero typing). When Telegram isn't
        set up, the line points at Settings → Phone, which
        shows the same URL."""
        import phone_link
        url = phone_link.start_pairing(self.cfg)
        sent = False
        try:
            import telegram_bridge
            sent = bool(telegram_bridge.send_message(
                self.cfg,
                "📱 Nalox Phone pairing is ON for 10 minutes.\n"
                f"Open this link on your phone: {url}\n"
                "Then tap 1. Install Nalox Phone, and after "
                "installing, 2. Connect."))
        except Exception:
            sent = False
        user = self._addr()
        user_bn = self._addr_bn()
        if rlang == "bn":
            if sent:
                return (f"ফোনের লিংকটা Telegram-এ পাঠিয়ে "
                        f"দিলাম, {user_bn} — ফোনে লিংকটা খুলে "
                        "Install, তারপর Connect চাপলেই হবে।")
            return (f"পেয়ারিং চালু করে দিলাম, {user_bn} — "
                    "কিন্তু Telegram-এ পাঠাতে পারলাম না। "
                    "Settings-এর Phone অংশে লিংকটা পাবেন।")
        if rlang == "hi":
            if sent:
                return (f"फोन का link Telegram पर भेज दिया, "
                        f"{user} — फोन में खोलकर Install, फिर "
                        "Connect दबाइए।")
            return (f"Pairing चालू कर दिया, {user} — लेकिन "
                    "Telegram पर भेज नहीं पाया। Settings के "
                    "Phone हिस्से में link मिलेगा।")
        if sent:
            return (f"I've sent the phone link to your "
                    f"Telegram, {user} — open it on the phone, "
                    "tap Install, then Connect.")
        return (f"Pairing is on, {user} — but I couldn't "
                "send it via Telegram. The link is in "
                "Settings, under Phone.")

    def _phone_intents(self, text):
        """Phone commands (v5.4): call a saved contact FROM
        the phone, open an app ON the phone, the phone's
        battery — EN/BN/HI. Returns the spoken reply, or None
        when the utterance is not a phone command.

        Disambiguation is the whole game: a bare "open
        youtube" never matches here (no phone mention) and
        keeps its laptop meaning in the intents below; "call"
        has no laptop meaning, so call commands always mean
        the phone — but a bare English "call X" only counts
        when X is a relation word or a saved contact, so
        "call the doctor" still reaches the Doctor intent."""
        t = text or ""
        if not any(k in t for k in ("call", "কল", "फोन",
                                    "phone", "ফোন", "कॉल",
                                    "ব্যাটারি", "बैटरी",
                                    "battery", "লিংক", "লিঙ্ক",
                                    "लिंक", "link")):
            return None
        import phone_control
        rlang = _text_lang(t, self.lang)

        # ---------------- v6.0: send me the phone link --------
        # Pairing for the Nalox Phone app: mode on for 10
        # minutes + the URL pushed to his Telegram (he taps it
        # on the phone — zero typing). Checked FIRST: "link"
        # utterances carry no call/open meaning.
        low_t = t.lower()
        if (("link" in low_t and "phone" in low_t)
                or ("লিংক" in t and "ফোন" in t)
                or ("লিঙ্ক" in t and "ফোন" in t)
                or ("लिंक" in t and ("फोन" in t
                                     or "phone" in low_t))):
            return self._phone_link_intent(rlang)

        # ---------------- call a contact ----------------
        name = None
        via_my = False
        m = re.search(r"\bcall\b\s+(my\s+)?([a-z]+)", t)
        if m:
            via_my = bool(m.group(1))
            name = m.group(2)
        if name is None:
            m = re.search(
                r"([\u0980-\u09ff]+)\s*(?:-কে|কে)?\s*"
                r"(?:কল|ফোন)\s*(?:করো|কর|করুন|দাও|দিন)", t)
            if m:
                name = m.group(1)
        if name is None:
            m = re.search(
                r"([\u0900-\u097f]+)\s+को\s*(?:कॉल|call)\s*"
                r"(?:करो|कर|कीजिए)", t)
            if m:
                name = m.group(1)
        if name and re.fullmatch(r"[a-z]+", name):
            # Latin captures are the risky ones ("call the
            # doctor", "call karo" in roman Hindi): a stop
            # word kills the capture, and without "my" the
            # name must be a relation or a saved contact.
            if name in self._PHONE_CALL_STOP:
                name = None
            elif not via_my:
                key, _num = phone_control.resolve_contact(
                    self.cfg, name)
                if key is None and name not in self._PHONE_REL_EN:
                    name = None
        elif name:
            # Bengali/Hindi captures can grab the WRONG word
            # when a filler sits between the name and the
            # verb ("মাকে একটা কল দাও" captures একটা — "a/
            # one"). If the capture doesn't resolve to a
            # contact but another token in the sentence does,
            # the resolving token is the real name. An
            # unresolved capture still stands (an unsaved
            # relation gets the honest "no number saved"
            # line, spoken with its name).
            key, _num = phone_control.resolve_contact(
                self.cfg, name)
            if key is None:
                for token in re.split(r"\s+", t):
                    token = token.strip(".,!?।")
                    k2, _n2 = phone_control.resolve_contact(
                        self.cfg, token)
                    if k2:
                        name = token
                        break
        if not name and ("কল" in t or "कॉल" in t or "call" in t
                         or ("ফোন" in t and "কর" in t)):
            # Token scan: a saved/known relation anywhere in
            # the sentence ("মাকে একটা কল দাও", "maa ko call
            # karo") — resolve_contact does the alias work.
            for token in re.split(r"\s+", t):
                key, _num = phone_control.resolve_contact(
                    self.cfg, token.strip(".,!?।"))
                if key:
                    name = token.strip(".,!?।")
                    break
        if name:
            result = self._phone_action("call", name=name)
            return self._phone_call_reply(result, name, rlang)

        # ---------------- open an app on the phone ----------------
        app = None
        m = re.search(r"\bopen\s+(.+?)\s+(?:on|in)\s+"
                      r"(?:my\s+)?phone\b", t)
        if m:
            app = m.group(1)
        if app is None:
            m = re.search(r"ফোনে\s+(\S+)\s*"
                          r"(?:খোলো|খোল|খুলুন|ওপেন)", t) or \
                re.search(r"(\S+)\s+ফোনে\s*(?:খোলো|খোল|খুলুন)", t)
            if m:
                app = m.group(1)
        if app is None:
            m = re.search(r"फोन\s+(?:में|पर)\s+(\S+)\s*"
                          r"(?:खोलो|खोल|ओपन)", t) or \
                re.search(r"(\S+)\s+फोन\s+(?:में|पर)\s*"
                          r"(?:खोलो|खोल|ओपन)", t)
            if m:
                app = m.group(1)
        # ---------------- v6.1: verb-free phone open ----------------
        # Field 2026-11-15 16:02: "or pay new youtube in my
        # phone." and "ছুপেন, youtube, in my phone." — the
        # verb was garbled away, the verb patterns above
        # missed, and the object-first PC open intent further
        # down opened YouTube on the LAPTOP while he watched
        # his phone. An app name + a phone mention IS the
        # command; the verb is decoration. Sitting here —
        # before every PC open intent — the phone mention
        # VETOES the laptop open for that app.
        if app is None:
            app = self._phone_app_mention(t)
        if app:
            result = self._phone_action("open", app=app)
            return self._phone_open_reply(result, app, rlang)

        # ---------------- the phone's battery ----------------
        if ("phone" in t and "battery" in t) \
                or ("ফোন" in t and "ব্যাটারি" in t) \
                or ("फोन" in t and ("बैटरी" in t
                                     or "battery" in t)):
            result = self._phone_action("battery")
            return self._phone_battery_reply(result, rlang)
        return None

    def _phone_app_mention(self, t):
        """v6.1 VERB-FREE phone open: the canonical phone-app
        key when the utterance names a phone app AND anchors
        it to the phone — no verb required — else None.

        The rule (on _normalise_asr tokens, so Whisper's
        punctuation and predictable garbles are already
        canonical): the FIRST known app token is the target;
        it belongs to the phone when
          - a phone token follows it within 4 tokens
            ("youtube in my phone", "youtube ফোনে খোলো"), or
          - a locative phone form directly precedes it
            ("ফোনে youtube খোলো", "फोन में youtube खोलो",
            "in my phone youtube …").
        Anything else is NOT a phone command: "my phone is
        charging, open youtube" — the phone sits before the
        app, far away, with no locative — keeps its laptop
        meaning in the intents below. This mirrors the
        object-first design that made the PC chores
        reliable: match the OBJECT and its anchor, never
        the verb."""
        try:
            import phone_control
            aliases = phone_control.APP_ALIASES
        except Exception:
            return None
        toks = _normalise_asr(t or "").split()
        app_i = None
        app_key = None
        for i, tok in enumerate(toks):
            if tok in aliases:
                app_i, app_key = i, aliases[tok]
                break
        if app_i is None:
            return None
        # a phone token close AFTER the app
        for j in range(app_i + 1, min(len(toks), app_i + 5)):
            if toks[j] in self._PHONE_TOKENS:
                return app_key
        # a locative phone form directly BEFORE the app
        if app_i >= 1 and toks[app_i - 1] in ("ফোনে", "फोन"):
            return app_key
        if app_i >= 2 and toks[app_i - 2] == "फोन" \
                and toks[app_i - 1] in ("में", "पर"):
            return app_key
        if app_i >= 2 and toks[app_i - 1] == "phone" \
                and toks[app_i - 2] in ("in", "on"):
            return app_key
        if app_i >= 3 and toks[app_i - 1] == "phone" \
                and toks[app_i - 2] == "my" \
                and toks[app_i - 3] in ("in", "on"):
            return app_key
        return None

    # ------------------------------------------------ v5.6 PC chores
    def _chore_line(self, kind, ok, mb, rlang, user, user_bn):
        """One short spoken line for a finished PC chore."""
        if kind == "this_pc":
            if rlang == "bn":
                return (f"দিস পিসি খুলছি, {user_bn}।" if ok else
                        f"দিস পিসি খুলতে পারলাম না, {user_bn}।")
            if rlang == "hi":
                return (f"This PC खोल रहा हूँ, {user}।" if ok else
                        f"This PC नहीं खोल पाया, {user}।")
            return (f"Opening This PC, {user}." if ok else
                    f"I couldn't open This PC, {user}.")
        if kind == "rb_open":
            if rlang == "bn":
                return (f"রিসাইকেল বিন খুলছি, {user_bn}।" if ok else
                        f"রিসাইকেল বিন খুলতে পারলাম না, {user_bn}।")
            if rlang == "hi":
                return (f"रीसायकल बिन खोल रहा हूँ, {user}।" if ok else
                        f"रीसायकल बिन नहीं खोल पाया, {user}।")
            return (f"Opening the Recycle Bin, {user}." if ok else
                    f"I couldn't open the Recycle Bin, {user}.")
        if kind == "rb_empty":
            if rlang == "bn":
                return (f"রিসাইকেল বিন পরিষ্কার করে দিলাম, {user_bn}।"
                        if ok else
                        f"রিসাইকেল বিন খালি করতে পারলাম না, {user_bn}।")
            if rlang == "hi":
                return (f"रीसायकल बिन साफ़ कर दिया, {user}।" if ok else
                        f"रीसायकल बिन साफ़ नहीं कर पाया, {user}।")
            return (f"Recycle bin cleaned, {user}." if ok else
                    f"I couldn't empty the recycle bin, {user}.")
        # kind == "quick"
        if not ok:
            if rlang == "bn":
                return f"পিসি পরিষ্কার করতে পারলাম না, {user_bn}।"
            if rlang == "hi":
                return f"PC साफ़ नहीं कर पाया, {user}।"
            return f"I couldn't clean the PC just now, {user}."
        mb_txt = "%g" % mb
        if rlang == "bn":
            if mb >= 1:
                return ("রিসাইকেল বিন আর temporary file পরিষ্কার "
                        f"করে দিলাম — প্রায় {_bn_num(mb_txt)} MB "
                        f"জায়গা খালি হলো, {user_bn}।")
            return (f"রিসাইকেল বিন আর temporary file পরিষ্কার "
                    f"করে দিলাম, {user_bn}।")
        if rlang == "hi":
            if mb >= 1:
                return ("रीसायकल बिन और temporary file साफ़ कर "
                        f"दिए — करीब {_hi_num(mb_txt)} MB जगह खाली "
                        f"हुई, {user}।")
            return (f"रीसायकल बिन और temporary file साफ़ कर "
                    f"दिए, {user}।")
        if mb >= 1:
            return ("Cleaned the recycle bin and temporary "
                    f"files — freed about {mb_txt} MB, {user}.")
        return (f"Recycle bin and temporary files cleaned, "
                f"{user}.")

    # ------------------------------------------------ v5.8 custom
    def _custom_intents(self, text):
        """HIS OWN commands (v5.8 — "Make your own command"):
        the phrases he taught Nalox in the Command Center,
        stored in custom_commands.json. Returns the spoken
        reply, or None when nothing he taught matches.

        Matching runs on _normalise_asr tokens — the SAME
        normalisation the other content intents use — applied
        to BOTH the utterance and his stored phrase, so his
        own pronunciation of his own phrase ("opne the
        chrome" for a taught "open the chrome") still fires.
        A phrase matches when its tokens equal the utterance's
        tokens or appear in them as one unbroken run (so
        "please <phrase>" and "<phrase> now" also land).
        First matching command in the list wins."""
        if not self._custom:
            return None
        toks = _normalise_asr(text or "").split()
        if not toks:
            return None
        for cmd in list(self._custom):
            try:
                phrase_toks = _normalise_asr(
                    cmd.get("phrase") or "").split()
            except Exception:
                continue
            if not phrase_toks:
                continue
            if _tokens_run_in(toks, phrase_toks):
                return self._run_custom(cmd, text)
        return None

    def _run_custom(self, cmd, text):
        """Execute one taught command via actions.py and say
        one short line about it. Every route is failure-
        isolated: a broken target answers honestly, never a
        crash. For the "speak" action the reply IS his target
        text — Nalox says exactly what he taught it to say."""
        action = str(cmd.get("action") or "")
        target = str(cmd.get("target") or "").strip()
        user = self._addr()
        user_bn = self._addr_bn()
        rlang = _text_lang(text or "", self.lang)
        try:
            if action == "speak":
                return target
            if action == "open_app":
                return actions.open_app(target)
            if action == "open_folder":
                low = target.lower()
                if low in actions.FOLDERS:
                    return actions.open_folder(target)
                if os.path.isdir(os.path.expandvars(target)):
                    res = actions.open_path(target)
                    ok = bool(res.get("ok")) \
                        if isinstance(res, dict) else bool(res)
                    if ok:
                        return self._loc(
                            f"Opening {target}, {user}.",
                            f"{target} খুলছি, {user_bn}।")
                    return self._loc(
                        f"I couldn't open {target}, {user}.",
                        f"{target} খুলতে পারলাম না, {user_bn}।")
                return actions.open_folder(target)
            if action == "open_url":
                url = target if "://" in target \
                    else "https://" + target
                actions.open_url(url)
                return self._loc(
                    f"Opening {target}, {user}.",
                    f"{target} খুলছি, {user_bn}।")
            if action == "open_file":
                res = actions.open_path(target)
                ok = bool(res.get("ok")) \
                    if isinstance(res, dict) else bool(res)
                name = os.path.basename(
                    target.rstrip("\\/")) or target
                if ok:
                    return self._loc(
                        f"Opening {name}, {user}.",
                        f"{name} খুলছি, {user_bn}।")
                return self._loc(
                    f"I couldn't open {name}, {user}.",
                    f"{name} খুলতে পারলাম না, {user_bn}।")
            if action == "type_text":
                return actions.type_text(target)
            if action == "quick_clean":
                res = actions.pc_quick_clean()
                if isinstance(res, dict):
                    mb = float(res.get("temp_mb") or 0)
                    ok = bool(res.get("bin_ok")) \
                        or int(res.get("temp_files") or 0) > 0 \
                        or mb > 0
                else:
                    ok, mb = bool(res), 0.0
                return self._chore_line("quick", ok, mb, rlang,
                                        user, user_bn)
            if action == "empty_recycle_bin":
                res = actions.empty_recycle_bin()
                ok = bool(res.get("ok")) \
                    if isinstance(res, dict) else bool(res)
                return self._chore_line("rb_empty", ok, 0.0,
                                        rlang, user, user_bn)
        except Exception as exc:
            log.warning("[custom] %s -> %s failed: %s",
                        cmd.get("phrase"), action, exc)
        return self._loc(
            f"I couldn't do that one, {user}.",
            f"ওটা করতে পারলাম না, {user_bn}।")

    def _pc_chore_intents(self, text):
        """LOCAL PC chores (v5.6 — "বললেই করে ফেলে"): empty or
        open the recycle bin, open This PC, quick-clean the PC.
        Returns the spoken reply, or None when the utterance is
        not a chore.

        These run WITHOUT the LLM and WITHOUT confirmation —
        the owner has given full control and his standing order
        is that what he says simply happens (the recycle-bin
        incident: a chain model deliberated for 13 s and did
        nothing). Every action is failure-isolated: a broken
        chore answers with one short honest line, never a
        crash. Combined utterances the chain splitter did not
        cut ("open this PC and clean the C drive") run every
        chore they name, in spoken order, one joined reply."""
        t = text or ""
        if not t:
            return None
        norm = _normalise_asr(t)
        user = self._addr()
        user_bn = self._addr_bn()
        rlang = _text_lang(t, self.lang)

        rb_pos = _recycle_bin_pos(t, norm)
        tp_pos = _this_pc_pos(t)
        qc_pos = _quick_clean_pos(t)
        if rb_pos < 0 and tp_pos < 0 and qc_pos < 0:
            return None

        chores = []  # (position, kind)
        if tp_pos >= 0:
            chores.append((tp_pos, "this_pc"))
        if qc_pos >= 0:
            # the quick clean empties the bin itself, so a
            # recycle mention in the same breath is covered
            chores.append((qc_pos, "quick"))
        elif rb_pos >= 0:
            has_clean = any(v in t or v in norm
                            for v in _RECYCLE_CLEAN_VERBS)
            has_open = any(v in t for v in _RECYCLE_OPEN_VERBS)
            kind = "rb_open" if (has_open and not has_clean) \
                else "rb_empty"
            chores.append((rb_pos, kind))
        if not chores:
            return None
        chores.sort(key=lambda c: c[0])

        replies = []
        for _pos, kind in chores:
            ok, mb = False, 0.0
            try:
                if kind == "this_pc":
                    res = actions.open_this_pc()
                    ok = bool(res.get("ok")) \
                        if isinstance(res, dict) else bool(res)
                elif kind == "rb_open":
                    res = actions.open_recycle_bin()
                    ok = bool(res.get("ok")) \
                        if isinstance(res, dict) else bool(res)
                elif kind == "rb_empty":
                    res = actions.empty_recycle_bin()
                    ok = bool(res.get("ok")) \
                        if isinstance(res, dict) else bool(res)
                elif kind == "quick":
                    res = actions.pc_quick_clean()
                    if isinstance(res, dict):
                        mb = float(res.get("temp_mb") or 0)
                        ok = bool(res.get("bin_ok")) \
                            or int(res.get("temp_files") or 0) > 0 \
                            or mb > 0
                    else:
                        ok = bool(res)
            except Exception as exc:
                log.warning("[chores] %s failed: %s", kind, exc)
                ok, mb = False, 0.0
            replies.append(self._chore_line(
                kind, ok, mb, rlang, user, user_bn))
        return " ".join(replies)

    # ------------------------------------------------ v4.4 content intents
    _OPEN_VERBS = {"open", "ওপেন", "খোলো", "खोलो", "চালু", "kholo"}
    _PLAY_VERBS = {"play", "চালাও", "বাজাও", "শোনাও", "শুনাও",
                   "लगाओ", "बजाओ", "चलाओ",
                   "chalao", "bajao", "lagao", "sunao"}
    _SEARCH_VERBS = {"search", "সার্চ", "খোঁজো", "খোঁজ", "खोजो", "सर्च"}
    _QUERY_FILLERS = {
        "nalox", "nalaks", "nalex", "nalok", "nalux", "alex",
        "ন্যালক্স", "ন্যালোক্স", "नैलॉक्स", "नालोक्स", "नेलॉक्स",
        "youtube", "on", "the", "a", "an", "for", "me", "now",
        "please", "প্লিজ", "এখন", "তুমি", "তো", "এবার",
        "একটা", "একটি", "করো", "करो", "টা", "pe",
    }

    # ------------------------------------------------ v4.7 channels
    def _channel_reply(self, text, raw_text=None):
        """'Open / switch to a YouTube channel' (v4.7).

        Arjun, from his phone: "And switch CHANNEL to Naloxff" —
        the v4.6 router had nothing for it and shrugged. The name
        is matched on the RAW text when available, so the handle
        keeps the case he wrote (@Naloxff). A channel word plus an
        open/switch verb but NO name asks which one — never a
        guess. Returns a reply string or None.
        """
        src = raw_text if raw_text and str(raw_text).strip() else text
        src = (src or "").strip()
        low = src.lower()
        name = None
        m = re.search(r"(?:open|switch(?:\s+to)?|go\s+to|show)\s+"
                      r"(?:the\s+)?channel\s+(?:to\s+)?"
                      r"([a-z0-9][a-z0-9 ._-]{0,40})",
                      src, re.IGNORECASE)
        if m:
            name = m.group(1)
        if not name:
            m = re.search(r"switch\s+to\s+([a-z0-9][a-z0-9 ._-]{0,40}?)"
                          r"\s+channel\b", src, re.IGNORECASE)
            if m:
                name = m.group(1)
        if not name:
            m = re.search(r"চ্যানেল\s+([^।.!?]+?)\s*"
                          r"(?:খোলো|খোল|খুলো|খুলুন)", src)
            if m:
                name = m.group(1)
        if not name:
            m = re.search(r"([^।.!?]+?)\s+চ্যানেল\s*"
                          r"(?:খোলো|খোল|খুলো|খুলুন)", src)
            if m:
                name = m.group(1)
        if not name:
            m = re.search(r"(?:channel\s+(\S+)\s+खोलो|"
                          r"(\S+)\s+channel\s+खोलो)", src)
            if m:
                name = m.group(1) or m.group(2)
        if name:
            words = name.strip(" .,!?").split()
            while words and words[0].lower() in (
                    "nalox", "ন্যালক্স", "नैलॉक्स"):
                words.pop(0)
            while words and words[-1].lower() in (
                    "please", "now", "টা", "টি"):
                words.pop()
            name = " ".join(words)
            handle = re.sub(r"\s+", "", name).strip("._-")
            if handle and len(handle) <= 30 and "/" not in handle:
                actions.open_url("https://www.youtube.com/@" + handle)
                if self.lang == "bn":
                    return (f"{name} চ্যানেল খুলছি, "
                            f"{self._addr_bn()}।")
                if self.lang == "hi":
                    return (f"{name} चैनल खोल रहा हूँ, "
                            f"{self._addr()}।")
                return (f"Opening the {name} channel, "
                        f"{self._addr()}.")
        if ("channel" in low or "চ্যানেল" in src) and re.search(
                r"\b(open|switch|show|go)\b|খোলো|খোল|खोलो",
                low + " " + src):
            if self.lang == "bn":
                return f"কোন চ্যানেল, {self._addr_bn()}?"
            if self.lang == "hi":
                return f"कौन सा चैनल, {self._addr()}?"
            return f"Which channel, {self._addr()}?"
        return None

    def _content_query(self, tokens, extra_strip=()):
        """The query left after removing verbs, the platform
        token, the wake word and filler words — order preserved."""
        strip = (self._OPEN_VERBS | self._PLAY_VERBS
                 | self._SEARCH_VERBS | self._QUERY_FILLERS
                 | set(extra_strip))
        return " ".join(t for t in tokens if t not in strip)

    def _content_intents(self, text):
        """Content-word intents over ASR-normalised text (v4.4).

        Runs AFTER every exact-phrase intent (those always win)
        and BEFORE the agent fallback. It matches on the PRESENCE
        of content words — an object/platform token plus a verb —
        so predictable Whisper garbling ("য়ুটুব বুপন কোড়ো")
        still lands on the right action. Returns a reply string
        or None.
        """
        # v4.7: channel intent also lives here, so switch-forms
        # that reach the content rules directly are covered too.
        channel_reply = self._channel_reply(text)
        if channel_reply is not None:
            return channel_reply

        nt = _normalise_asr(text)
        if not nt:
            return None
        tokens = nt.split()
        tset = set(tokens)

        # --- YouTube: play <query> / search <query> / open ---
        if "youtube" in tset:
            query = self._content_query(tokens)
            if tset & self._PLAY_VERBS:
                if query:
                    played, q = self._play_on_youtube(query)
                    return self._play_reply(q, played)
                actions.open_youtube()
                return self._loc("Opening YouTube.", "ইউটিউব খুলছি।")
            if tset & self._SEARCH_VERBS:
                if query:
                    self._last_yt_query = query
                    actions.search_youtube(query)
                    return self._loc(
                        f"Searching YouTube for {query}.",
                        f"ইউটিউবে {query} খুঁজছি।")
                actions.open_youtube()
                return self._loc("Opening YouTube.", "ইউটিউব খুলছি।")
            actions.open_youtube()
            return self._loc("Opening YouTube.", "ইউটিউব খুলছি।")

        # --- Chrome / browser (any open-ish phrasing, or bare) ---
        if "chrome" in tset or "browser" in tset or "ব্রাউজার" in tset:
            return actions.open_app("chrome")

        # --- a song / music with a play verb ---
        # v5.0: the Latin media words stay IN the query ("sad
        # song" searches far better than "sad"); only the native
        # generic words (গান / गाना) are stripped as fillers.
        if tset & {"গান", "song", "music", "गाना", "गाने"} \
                and tset & self._PLAY_VERBS:
            query = self._content_query(
                tokens, extra_strip=("গান", "गाना", "गाने"))
            if query:
                played, q = self._play_on_youtube(query)
                return self._play_reply(q, played)
            if self.lang == "bn":
                played, _q = self._play_on_youtube("bangla song")
                if played:
                    return self._song_done_line()
                return ("সরাসরি চালাতে পারলাম না — গানের search "
                        "খুলে দিলাম।")
            if self.lang == "hi":
                played, _q = self._play_on_youtube("hindi song")
                if played:
                    return "गाना चला रहा हूँ।"
                return ("सीधे नहीं चला पाया — गाने की search खोल "
                        "दी है।")
            played, _q = self._play_on_youtube("music")
            if played:
                return "Playing music on YouTube."
            return ("Couldn't play it directly — opened the "
                    "music search.")

        # --- news (a খবর that missed the exact phrases) ---
        if "খবর" in tset:
            try:
                titles = skills.fetch_headlines(3)
            except Exception:
                titles = []
            if titles:
                return "আজকের বড় খবর: " + " ".join(
                    f"{_bn_num(i + 1)}. {t}।" for i, t in enumerate(titles))
            return f"এখন খবর পাচ্ছি না, {self._addr_bn()}।"

        # --- time / date / battery by content word ---
        if "সময়" in tset:
            return self._time_reply_bn() if self.lang == "bn" \
                else self._time_reply()
        if "समय" in tset or "वक़्त" in tset:
            return self._time_reply_hi()
        if "তারিখ" in tset:
            return self._date_reply_bn() if self.lang == "bn" \
                else self._date_reply()
        if "तारीख" in tset or "तारीख़" in tset:
            return self._date_reply_hi()
        if "ব্যাটারি" in tset:
            return self._battery_reply_bn() if self.lang == "bn" \
                else self._battery_reply()
        if "बैटरी" in tset:
            return self._battery_reply_hi()
        return None

    # ------------------------------------------------ v4.4 provider cache
    PROVIDER_TTL_SECONDS = 300.0

    def _cloud_configured(self):
        """True when any cloud provider key is pasted in Settings."""
        return any((self.cfg.get(k) or "").strip() for k in
                   ("freellm_api_key", "anthropic_api_key",
                    "openrouter_api_key",
                    "gemini_api_key", "groq_api_key",
                    "openai_api_key"))

    def _probe_ollama_once(self):
        """One short reachability check of the local Ollama server.

        The probe uses 127.0.0.1, never "localhost": on Windows
        "localhost" resolves to BOTH ::1 and 127.0.0.1, and with
        nothing listening each connect attempt ate the full
        timeout — that dual-stack penalty is exactly how the old
        per-command probe produced Arjun's flat ~3.0 s brain time
        (2 x 1.5 s) on every unmatched command.
        """
        try:
            import requests
            url = (self.cfg.get("ollama_url")
                   or "http://localhost:11434").rstrip("/")
            url = url.replace("://localhost", "://127.0.0.1")
            return requests.get(url + "/api/tags",
                                timeout=0.8).status_code == 200
        except Exception:
            return False

    def _start_provider_probe(self):
        """Refresh the Ollama availability cache in a daemon
        thread — never blocks startup speech or a command."""
        with self._prov_lock:
            if self._prov_thread is not None \
                    and self._prov_thread.is_alive():
                return

            def _run():
                try:
                    result = self._probe_ollama_once()
                    with self._prov_lock:
                        self._prov = {"at": time.monotonic(),
                                      "ollama": result}
                    log.info("Provider probe: ollama=%s, cloud "
                             "keys=%s", result,
                             self._cloud_configured())
                except Exception as exc:
                    log.error("[CRASH-GUARD] provider probe "
                              "thread failed: %s: %s",
                              type(exc).__name__, exc)

            self._prov_thread = threading.Thread(
                target=_run, daemon=True, name="nalox-provider-probe")
            self._prov_thread.start()

    def _ollama_available(self):
        """Cached Ollama availability. A stale cache (older than
        PROVIDER_TTL_SECONDS) kicks a background re-probe and the
        stale answer is used — the command path never waits.

        v5.2: the re-probe start is guarded here too — this runs
        inside _refresh_brain_status during Brain construction,
        and a probe that can't start (e.g. thread exhaustion)
        must never take the boot down with it."""
        with self._prov_lock:
            prov = dict(self._prov)
        if time.monotonic() - prov["at"] > self.PROVIDER_TTL_SECONDS:
            try:
                self._start_provider_probe()
            except Exception as exc:
                log.error("[CRASH-GUARD] provider probe failed "
                          "to start: %s: %s",
                          type(exc).__name__, exc)
        return bool(prov["ollama"])

    # ------------------------------------------------ v5.0 FreeLLMAPI
    def _freellm_base(self):
        """The configured router base URL, normalised: no
        trailing slash, and 127.0.0.1 instead of "localhost"
        (the v4.4 dual-stack lesson — a dead "localhost" connect
        costs the timeout twice on Windows)."""
        base = (self.cfg.get("freellm_base_url")
                or "http://127.0.0.1:31415/v1").strip().rstrip("/")
        return base.replace("://localhost", "://127.0.0.1")

    def _probe_freellm_once(self):
        """One short reachability check of the local router.
        ANY HTTP response — even a 401 — means the app is
        running; only an exception means it is down/closed.
        Key validity is validation's business (_validate_keys_now),
        not the reachability cache's."""
        try:
            import requests
            key = (self.cfg.get("freellm_api_key") or "").strip()
            headers = {"Authorization": f"Bearer {key}"} if key \
                else {}
            requests.get(self._freellm_base() + "/models",
                         headers=headers, timeout=(1.0, 1.5))
            return True
        except Exception:
            return False

    def _start_freellm_probe(self):
        """Refresh the FreeLLMAPI reachability cache in a daemon
        thread — never blocks startup speech or a command. A
        no-op while a probe is already running, and when no
        unified key is configured (nothing to reach)."""
        if not (self.cfg.get("freellm_api_key") or "").strip():
            return
        with self._prov_lock:
            if self._freellm_thread is not None \
                    and self._freellm_thread.is_alive():
                return

            def _run():
                try:
                    result = self._probe_freellm_once()
                    with self._prov_lock:
                        self._freellm = {"at": time.monotonic(),
                                         "up": result}
                    log.info("FreeLLMAPI probe: up=%s", result)
                except Exception as exc:
                    log.error("[CRASH-GUARD] FreeLLMAPI probe "
                              "thread failed: %s: %s",
                              type(exc).__name__, exc)

            self._freellm_thread = threading.Thread(
                target=_run, daemon=True, name="nalox-freellm-probe")
            self._freellm_thread.start()

    def _freellm_available(self):
        """Cached router reachability — the v4.4 rule: the
        command path NEVER pays a connect timeout for a closed
        app. A stale cache kicks a background re-probe and the
        stale answer is used."""
        if not (self.cfg.get("freellm_api_key") or "").strip():
            return False
        # v6.6: timeout demotion — while the cooldown runs the
        # router is skipped ENTIRELY (the direct providers get
        # their turn without paying 10 s a command to a hung
        # router). Once it expires, the normal cache logic
        # resumes and the next real call becomes the probe:
        # an answer reinstates the router, another timeout
        # re-demotes it (in _freellm_note_failure).
        if self._freellm_down_until:
            if time.monotonic() < self._freellm_down_until:
                return False
            self._freellm_down_until = 0.0
        with self._prov_lock:
            state = dict(self._freellm)
        if time.monotonic() - state["at"] > self.PROVIDER_TTL_SECONDS:
            try:
                self._start_freellm_probe()
            except Exception as exc:
                log.error("[CRASH-GUARD] FreeLLMAPI probe "
                          "failed to start: %s: %s",
                          type(exc).__name__, exc)
        return bool(state["up"])

    def _freellm_note_failure(self):
        """After a FreeLLMAPI agent/plain call failed, judge
        the failure (v6.6 — two kinds, two stories):

        TIMEOUT (checked FIRST — a ReadTimeout's reason string
        also contains "HTTPConnectionPool", which the old
        connection test swallowed): the app is RUNNING but not
        answering. It is demoted for FREELLM_COOLDOWN_S —
        _freellm_available returns False throughout, so the
        direct providers stop paying 10 s per command to a
        hung router; when the cooldown expires the next real
        call is the probe that can reinstate it. ONE log line
        per demotion, worded "is not answering" — never the
        "app may be closed" line, which is wrong for a timeout.

        CONNECTION error: the app was closed (or crashed)
        since the last probe — mark the reachability cache
        down at once (later commands skip instantly instead of
        paying the connect again) and leave ONE log line
        naming the likely cause. The spoken line stays short;
        this detail is for the log page. (Pre-v6.6 a timeout
        was deliberately NOT marked down — "a slow router is
        not a dead one"; the 19:24 field log, 10 s burned
        before the chain even started, retired that rule for
        timeouts specifically.)"""
        with self._status_lock:
            fail = self._last_agent_fail
        if not fail or fail[0] != "FreeLLMAPI":
            return
        reason = fail[1] or ""
        low = reason.lower()
        if "timeout" in low or "timed out" in low:
            now = time.monotonic()
            if now >= self._freellm_down_until:
                self._freellm_down_until = (now
                                             + FREELLM_COOLDOWN_S)
                _lb("ERROR", "[BRAIN] FreeLLMAPI is not answering — giving the direct providers a turn for a while.")
                log.error("[brain] FreeLLMAPI demoted for "
                          "%.0fs after a timeout (not "
                          "answering)", FREELLM_COOLDOWN_S)
            return
        if "onnection" not in reason and "refused" not in reason:
            return
        with self._prov_lock:
            self._freellm = {"at": time.monotonic(), "up": False}
        _lb("ERROR", "[BRAIN] FreeLLMAPI unreachable — the "
                     "FreeLLMAPI app may be closed. Open it to "
                     "use its models; other providers keep "
                     "answering meanwhile.")
        log.error("[brain] FreeLLMAPI marked down after a "
                  "connection failure (app closed?)")

    def _agent_available(self):
        """True when calling the brain is worth it at all:
        the Groq key is pasted (v6.8: Groq is the only cloud
        brain — the call itself is then the check) or a
        cached-reachable Ollama stands by. False means the
        local fallback must be served with ZERO network delay
        (v4.4)."""
        if (self.cfg.get("groq_api_key") or "").strip():
            return True
        # v7.6: the chat race widened the brain again (the
        # owner's order reversing v6.8's Groq-only rule for
        # the CHAT path) — a Gemini key or a live FreeLLMAPI
        # gateway also makes the call worth trying.
        if (self.cfg.get("gemini_api_key") or "").strip():
            return True
        try:
            if self._freellm_available():
                return True
        except Exception:
            pass
        return self._ollama_available()

    # ------------------------------------------------ v4.8 brain status
    # One truth, three renderings: brain_status (the dict), the
    # HUD header line and the boot [brain] log line (both from
    # brain_status_line()). Validation runs at boot in a daemon
    # thread and again after every config hot-reload.
    _PROVIDER_LABELS = {"freellm": "FreeLLMAPI",
                        "anthropic": "Claude",
                        "openrouter": "OpenRouter",
                        "gemini": "Gemini",
                        "groq": "Groq", "openai": "OpenAI",
                        "muse": "Muse Wonder",
                        "ollama": "Ollama", "local": "Local"}
    # (provider, cfg key field, models URL, label) — GET {base}/
    # models with the key is the cheapest honest "is this key
    # alive?" check. Tuple order = status-mode priority.
    # v6.8: GROQ ONLY (owner's order, 2026-11-15 20:31 IST —
    # "সবচেয়ে বেশি ফার্স্ট যে রিপ্লাই দিচ্ছে তাকে রেখে
    # বাকিগুলো মুছে ফেলো": Groq answered fast in every field
    # log while FreeLLMAPI/Gemini timed out and the rest 401'd,
    # so Groq is now the ONLY cloud brain — the only key
    # validation checks, the only provider the chain tries.
    # His other keys stay in Settings untouched; Nalox simply
    # never calls them. Ollama remains the silent offline
    # last resort (no key to validate; _note_ollama_at_boot).
    _KEY_CHECKS = (
        ("groq", "groq_api_key",
         "https://api.groq.com/openai/v1/models", "Groq"),
    )
    _HOT_RELOAD_KEYS = ("freellm_api_key", "freellm_base_url",
                        "freellm_model",
                        "anthropic_api_key", "openrouter_api_key",
                        "gemini_api_key",
                        "groq_api_key", "openai_api_key",
                        # v7.8: the Muse Wonder key + model
                        # ride the same hot-reload, so a key
                        # pasted into Settings → Brain reaches
                        # the running brain like every other
                        # provider's.
                        "muse_api_key", "muse_model",
                        "openrouter_model", "gemini_model",
                        "groq_model",
                        # v6.5: the model candidate lists ride
                        # the same hot-reload as the singles.
                        "gemini_models", "groq_models",
                        "openrouter_models",
                        "openai_model", "anthropic_model",
                        # v5.1: the cloud-ears switch — Ears reads
                        # the same shared cfg dict, so a Settings
                        # toggle lands without a restart too.
                        "cloud_ears")

    def _stat_mtime(self):
        try:
            return os.path.getmtime(self._cfg_path)
        except Exception:
            return None

    def _stat_path_mtime(self, path):
        """getmtime for an arbitrary path (v5.8 — the custom
        commands store watch); None when the file is absent."""
        try:
            return os.path.getmtime(path)
        except Exception:
            return None

    def _maybe_reload_custom(self):
        """CUSTOM-COMMANDS HOT-RELOAD (v5.8): if
        custom_commands.json changed on disk since we last
        looked (he saved a command in the Command Center),
        reload the list. One os.stat per handle() call, like
        config. A malformed or half-written file is IGNORED —
        the list he already has keeps working, and the mtime
        is only consumed by a successful read (retried next
        call), mirroring _maybe_reload_config."""
        if _custom_mod is None:
            return
        try:
            mtime = self._stat_path_mtime(self._custom_path)
            if mtime is None:
                if self._custom_mtime is not None:
                    # the file was deleted — his commands go too
                    self._custom = []
                    self._custom_mtime = None
                return
            if self._custom_mtime is None:
                self._custom_mtime = mtime
                # fall through and load: the file appeared
            elif mtime == self._custom_mtime:
                return
            fresh = _custom_mod.load_commands(self._custom_path)
            self._custom = fresh
            self._custom_mtime = mtime
            log.info("[custom] reloaded %d custom command(s)",
                     len(fresh))
        except Exception:
            return

    def _anthropic_key_looks_groq(self):
        """A gsk_… key in the Claude field is a Groq key in the
        wrong field — provable from the prefix alone, no network
        needed (Arjun's 11:55 log: he never made an Anthropic
        key, yet 'Claude connected' printed at every boot)."""
        key = (self.cfg.get("anthropic_api_key") or "").strip()
        return key.startswith("gsk_")

    def _refresh_brain_status(self):
        """Recompute brain_status from config + key checks + the
        Ollama cache. Mode follows the agent's own priority:
        FreeLLMAPI → Claude → OpenRouter → Gemini → Groq →
        OpenAI → Ollama → local — with one refinement (v4.9): the mode is the
        first configured provider that is NOT known-rejected,
        i.e. the brain that will actually answer. A rejected
        provider only becomes the mode when EVERY configured
        key is rejected (then the header shows the dead top of
        the line, with the wrong-field hint when it applies).
        Before v4.9 the mode was simply the first configured
        provider, so a healthy OpenRouter pasted under Arjun's
        dead Claude field still headlined "Claude — rejected"
        and the promised "Brain: OpenRouter ✓" never appeared."""
        with self._status_lock:
            checks = dict(self._key_checks)
        status = None
        fallback = None
        for prov, field, _url, _label in self._KEY_CHECKS:
            if (self.cfg.get(field) or "").strip():
                check = checks.get(prov)
                if check:
                    cand = {"mode": prov,
                            "key_state": check["state"],
                            "detail": check["detail"]}
                else:
                    cand = {"mode": prov, "key_state": "untested",
                            "detail": "checking…"}
                if fallback is None:
                    fallback = cand
                if cand["key_state"] != "rejected":
                    status = cand
                    break
        if status is None:
            status = fallback
        if status is None:
            if self._ollama_available():
                status = {"mode": "ollama", "key_state": "none",
                          "detail": "local server reachable"}
            else:
                status = {"mode": "local", "key_state": "none",
                          "detail": "no key configured"}
        # Wrong-field hint rides in the detail: a rejected Claude
        # key while the Groq field sits empty almost always means
        # the Groq key was pasted into Claude's field.
        if status["mode"] == "anthropic" \
                and status["key_state"] == "rejected":
            if self._anthropic_key_looks_groq():
                status["detail"] = (
                    "a Groq key (starts with gsk_) belongs in the "
                    "Groq field, not Claude's")
            elif not (self.cfg.get("groq_api_key") or "").strip():
                status["detail"] += (
                    " — if this is a Groq key (starts with gsk_), "
                    "it belongs in the Groq field, not Claude's")
        # Generalised plain truth: EVERY configured cloud key
        # rejected means Settings needs a visit, full stop.
        configured = [prov for prov, field, _u, _l
                      in self._KEY_CHECKS
                      if (self.cfg.get(field) or "").strip()]
        if configured and all(
                checks.get(p, {}).get("state") == "rejected"
                for p in configured):
            status["detail"] += (
                " | all configured keys rejected — check "
                "Settings → Brain")
        with self._status_lock:
            self.brain_status = status
        return status

    def _provider_rejected(self, provider):
        """True when validation (or a live 401/403) has marked
        this provider's key REJECTED. The agent skips such a
        provider instantly — the failure is already logged, and
        re-failing it on every command only burns seconds (with
        Arjun's gsk_ key in the Claude field, EVERY command used
        to pay for a doomed Anthropic call first). "unreachable"
        is NOT skipped: networks recover."""
        with self._status_lock:
            check = self._key_checks.get(provider) or {}
        return check.get("state") == "rejected"

    # ------------------------------------------------ v6.5 models
    # ------------------------------------------------ v7.4
    # SMART BRAIN ROUTING (the owner's orders, 2026-11-16:
    # 07:58 "instant answers", 08:17 "most powerful" —
    # simple talk uses the instant model, hard work the
    # strongest brain, AUTOMATICALLY). The decision is
    # deterministic and free: the same _looks_like_action_
    # request signal the act-don't-narrate guard already
    # computes — no classifier call, so routing adds zero
    # latency. brain_smart_routing OFF (or a pre-v7.4
    # config that never heard of it defaults ON via the
    # shipped default) — OFF means _tier_for returns None
    # and every call below behaves exactly as v7.3.
    def _smart_routing_on(self):
        try:
            return bool(self.cfg.get("brain_smart_routing",
                                     True))
        except Exception:
            return True

    def _power_model(self):
        """The POWER tier's head model (config
        groq_power_model; the shipped default when the key
        is missing or blank)."""
        try:
            name = str(self.cfg.get("groq_power_model")
                       or "").strip()
        except Exception:
            name = ""
        return name or "llama-3.3-70b-versatile"

    def _tier_for(self, text):
        """The routing tier for one utterance: "power" for
        an action request, "instant" for plain chat, None
        when smart routing is off (v7.3 behaviour)."""
        if not self._smart_routing_on():
            return None
        return ("power" if _looks_like_action_request(text)
                else "instant")

    def _model_candidates(self, provider, head_override=None):
        """The ordered model candidates for a walk provider
        (v6.5): the configured single model FIRST (his Settings
        choice always gets the first try), then the configured
        candidate list, de-duplicated, empties dropped. The
        list may live in config as a JSON list or a comma
        string — both are accepted. Non-walk providers get
        just their configured model.

        v7.4: head_override= forces one model to the front
        of the walk (the smart-routing tier head) — the rest
        of the order is untouched, so a dead tier head simply
        walks on to the usual candidates. (Named _override:
        this function's own local `head` below is the
        configured single model.)"""
        keys = _MODEL_WALK_PROVIDERS.get(provider)
        if keys is None:
            return []
        single_key, list_key = keys
        # The shipped defaults are the floor: a cfg that never
        # passed through config.load_config (or predates the
        # keys) still walks the seeded lists.
        try:
            import config as _cfg_mod
            _defaults = _cfg_mod.DEFAULTS
        except Exception:
            _defaults = {}
        out = []
        head = str(self.cfg.get(single_key)
                   or _defaults.get(single_key) or "").strip()
        if head:
            out.append(head)
        raw = self.cfg.get(list_key, _defaults.get(list_key))
        if isinstance(raw, str):
            raw = [part for part in re.split(r"[,\n]", raw)]
        if isinstance(raw, (list, tuple)):
            for item in raw:
                name = str(item or "").strip()
                if name and name not in out:
                    out.append(name)
        if provider == "groq" and out \
                and out[0] == _GROQ_STALE_REMEMBERED:
            # v7.3: the remembered reasoning model never heads
            # the walk again — the shipped instant-first order
            # rules; every configured candidate (the stale one
            # included, at its shipped position) stays in the
            # walk, and hand-added names keep their order after
            # the shipped ones.
            shipped = []
            for item in (_defaults.get(list_key) or []):
                name = str(item or "").strip()
                if name and name not in shipped:
                    shipped.append(name)
            reordered = []
            # The shipped primary heads the walk even when a
            # hand-edited list never contained it — the stale
            # memory is the only reason we are here, and the
            # shipped order rules means the instant model
            # leads, full stop. (If the name is dead for his
            # key, the walk's model-not-found step moves on,
            # as it always has.)
            primary = str(_defaults.get(single_key)
                          or "").strip()
            if primary:
                reordered.append(primary)
            reordered += [m for m in shipped
                          if m in out and m not in reordered]
            reordered += [m for m in out if m not in reordered]
            if reordered:
                out = reordered
        if head_override:
            head_override = str(head_override).strip()
            if head_override:
                out = [head_override] + [
                    m for m in out if m != head_override]
        # v7.5: compose with the account's DISCOVERED model
        # list when validation captured one (see the v7.5
        # note at _GROQ_STALE_REMEMBERED). The configured
        # heads (groq_model / groq_power_model ride in `out`
        # / the override) are filtered by existence like
        # every other name; nothing here may persist
        # anything (the Defect-1 discipline is untouched —
        # this only ORDERS the walk).
        try:
            _disc = list(self._discovered_models.get(provider)
                         or [])
        except Exception:
            _disc = []
        if _disc and out:
            _disc_keys = {_model_key(m) for m in _disc}
            _seen = set()
            _kept = []

            def _take(name):
                _k = _model_key(name)
                if _k and _k in _disc_keys and _k not in _seen:
                    _seen.add(_k)
                    _kept.append(name)

            if head_override:
                # Tier/validation walk: EXISTENCE ONLY — the
                # override head leads iff it exists, the
                # configured order is otherwise untouched,
                # then any other chat-capable model the
                # account has.
                for _m in out:
                    _take(_m)
                for _m in _disc:
                    if _chat_capable(_m):
                        _take(_m)
            else:
                # Chat walk: instant-class first (configured
                # members in configured order, then the
                # account's other instant-class names in
                # /models order), then the configured order
                # filtered to existing, then any other
                # chat-capable model present.
                for _m in out:
                    if _is_instant_class(_m):
                        _take(_m)
                for _m in _disc:
                    if _is_instant_class(_m) \
                            and _chat_capable(_m):
                        _take(_m)
                for _m in out:
                    _take(_m)
                for _m in _disc:
                    if _chat_capable(_m):
                        _take(_m)
            if _kept:
                out = _kept
                if not head_override:
                    # v7.6 AUTO-MODEL CHAT HEAD (the owner's
                    # "auto model" ask, 2026-11-16 11:12
                    # IST): boot validation's pick leads the
                    # CHAT walk. Validation proved that model
                    # answers on this account, and in the
                    # field its pick (qwen/qwen3.8-27b, the
                    # Brain Test's fastest at 0.59 s to the
                    # first token) sat BEHIND the shipped
                    # head (openai/gpt-oss-120b, 1.06 s)
                    # because the stale rule only kept the
                    # stale name out of validation, not out
                    # of the walk's front. The rest of the
                    # discovered walk follows, deduped, order
                    # preserved. Tier walks (head_override)
                    # are NOT touched — the power walk keeps
                    # the v7.4/v7.5 ordering exactly. With
                    # no validation pick recorded, or a pick
                    # the composed walk doesn't contain, the
                    # v7.5 composition stands unchanged.
                    _vm = (getattr(self, "_validation_model",
                                   None) or {}).get(provider)
                    if _vm:
                        _vk = _model_key(_vm)
                        for _i, _m in enumerate(out):
                            if _model_key(_m) == _vk:
                                if _i:
                                    out = ([out[_i]]
                                           + out[:_i]
                                           + out[_i + 1:])
                                break
        return out

    def _remember_working_model(self, provider, model, label,
                                single_key=None, tier=None,
                                answered=True):
        """Persist the model that actually answered (v6.5):
        the live cfg AND config.json on disk (read-modify-
        write of ONLY that key, patch_config style — his keys
        and choices are never touched). After this, the first
        candidate tried is the one that works.

        v7.4: single_key= remembers under a DIFFERENT key —
        the smart-routing power tier remembers its winner
        under groq_power_model, so a power answer never
        rewrites the instant tier's groq_model head (and
        vice versa). tier= records which tier answered, for
        the Command Center's tier-aware brain line.

        v7.4 (Defect 1): answered=False marks a BOOT-
        VALIDATION remember (the v6.5 /models repair in
        _check_one_key). Validation may repair the walk's
        remembered head, but it has answered NOTHING, so it
        must never pose as the talking brain: it records
        into _working_models only — _last_answered (which
        brain_status_line reads) and the tier mark are for
        real answers exclusively."""
        keys = _MODEL_WALK_PROVIDERS.get(provider)
        if keys is None or not model:
            return
        # v7.3: the in-memory record happens for EVERY answer
        # (even when the model is already the remembered one
        # and nothing needs persisting) — the Command Center's
        # brain line reads it.
        self._working_models[provider] = model
        if answered:
            self._last_answered[provider] = model
            # v7.8: WHO answered last, across providers —
            # the brain line names Muse Wonder when the
            # last real answer was its (see
            # brain_status_line).
            self._last_answer_provider = provider
            if tier is not None:
                self._last_answer_tier = tier
        else:
            # v7.6 (auto-model): a VALIDATION remember also
            # records the pick in _validation_model — kept
            # apart from real answers on purpose: the chat
            # walk heads itself with validation's pick (see
            # _model_candidates), and a later real answer —
            # above all a POWER-tier answer, which lands in
            # _working_models under the same provider — must
            # never move the chat head.
            try:
                self._validation_model[provider] = model
            except Exception:
                pass
        if single_key is None:
            single_key = keys[0]
        if str(self.cfg.get(single_key) or "").strip() == model:
            return
        self.cfg[single_key] = model
        _lb("BRAIN", f"[brain] {label}: model {model} works — "
                     "remembered as the default")
        log.info("[brain] %s working model remembered: %s",
                 label, model)
        try:
            path = self._cfg_path
            data = {}
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            if isinstance(data, dict):
                data[single_key] = model
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False,
                              indent=2)
        except Exception as exc:
            log.warning("[brain] could not persist the working "
                        "%s model: %s", label, exc)

    def brain_status_line(self):
        """The one short line the HUD header + boot log show."""
        s = getattr(self, "brain_status", None) or {}
        mode = s.get("mode", "local")
        label = self._PROVIDER_LABELS.get(mode, "Local")
        state = s.get("key_state", "none")
        detail = s.get("detail", "")
        if mode == "local":
            return "Brain: Local — no key"
        if mode == "ollama":
            return "Brain: Ollama (local)"
        if state == "ok":
            # v7.8: when the last REAL answer came from
            # Muse Wonder (a chat-race win), the line says
            # so — the owner can see the Meta brain is the
            # one talking. Before its first answer, and
            # after any other provider's answer, the line
            # below is byte-identical to v7.7.
            if getattr(self, "_last_answer_provider",
                       None) == "muse" \
                    and (getattr(self, "_last_answered",
                                 None) or {}).get("muse"):
                _mark = ("💪" if getattr(
                    self, "_last_answer_tier", None)
                    == "power" else "⚡")
                return f"Brain: Muse Wonder {_mark}"
            # v7.3: once a model has actually ANSWERED this
            # session, the line names it — the owner can see
            # the instant brain is the one talking ("Brain:
            # Groq · llama-3.1-8b-instant ⚡"). Before the
            # first answer the plain validated form stands.
            # v7.4: the mark follows the tier of the last
            # answer — 💪 when the POWER model did the work,
            # ⚡ for an instant-tier answer.
            # v7.4 (Defect 1): the named model comes from
            # _last_answered — REAL answers only. Boot
            # validation's repair remember (answered=False)
            # never lands here, so before the first real
            # answer the plain "Brain: Groq ✓" form stands
            # even when validation just repaired the head.
            _wm = (getattr(self, "_last_answered", None)
                   or {}).get(mode)
            if _wm:
                _mark = ("💪" if getattr(
                    self, "_last_answer_tier", None) == "power"
                    else "⚡")
                # v7.6: when walk self-discovery is active
                # for this provider, the line says "auto" —
                # the named model was reached through the
                # account's OWN model list, not a shipped
                # guess ("Brain: Groq · auto ·
                # qwen/qwen3.8-27b ⚡"). The named model
                # still comes from _last_answered only
                # (Defect-1 discipline is untouched).
                if (getattr(self, "_discovered_models", None)
                        or {}).get(mode):
                    return (f"Brain: {label} · auto · "
                            f"{_wm} {_mark}")
                return f"Brain: {label} · {_wm} {_mark}"
            return f"Brain: {label} ✓"
        if state == "rejected":
            m = re.search(r"HTTP (\d{3})", detail)
            code = m.group(1) if m else ""
            line = f"Brain: {label} — key rejected"
            if code:
                line += f" ({code})"
            if mode == "anthropic" \
                    and self._anthropic_key_looks_groq():
                line += " — gsk_ key belongs in the Groq field"
            return line
        if state == "down":
            # v5.0: a LOCAL provider whose app is not running —
            # a different problem from a dead key or a network
            # outage, and the headline must say which.
            return f"Brain: {label} — not running"
        if state == "unreachable":
            return f"Brain: {label} — unreachable"
        # untested: cloud checks still in flight — except the
        # gsk_ prefix, which is proof enough on its own.
        if mode == "anthropic" and self._anthropic_key_looks_groq():
            return ("Brain: Claude — wrong field? "
                    "(gsk_ is a Groq key)")
        return "Brain: checking…"

    def _validate_keys_async(self):
        """Start the key validation in a daemon thread (never
        blocks boot speech or a command). A no-op while a check
        is already running."""
        with self._status_lock:
            if self._validate_thread is not None \
                    and self._validate_thread.is_alive():
                return

            def _run():
                try:
                    self._validate_keys_now()
                except Exception:
                    pass

            self._validate_thread = threading.Thread(
                target=_run, daemon=True, name="nalox-key-check")
            self._validate_thread.start()

    def _publish_key_check(self, prov, result):
        """Merge ONE provider's fresh key check into the live
        state and refresh the headline AT ONCE (v5.2).

        Before v5.2, _validate_keys_now collected every result
        and published only after the LAST provider answered —
        so one slow or hung GET anywhere in the sequence froze
        the header at "Brain: checking…" for the whole run,
        and the async wrapper's already-running guard then
        blocked every later revalidation for the process's
        life. That is exactly what Arjun's v5.1 boots showed:
        the Anthropic 401 was logged, yet the brain line never
        resolved. Now the headline lands as soon as each
        provider — above all the effective one — is known;
        later checks keep refining it. (Runs are serialized
        by _validate_lock, so these merges never interleave
        with another run's.)"""
        try:
            with self._status_lock:
                self._key_checks[prov] = result
            self._refresh_brain_status()
        except Exception:
            pass

    def _validate_keys_now(self):
        """Validate each configured cloud key (serialized).

        v5.2: the whole run holds _validate_lock. Overlapping
        runs (the boot async thread vs a hot-reload re-check)
        used to interleave their writes to _key_checks, so a
        stale run finishing late could resurrect old states —
        a "rejected" key flipping back to "unreachable"
        mid-command. Serialized, runs queue in start order
        and the last one owns the final state."""
        with self._validate_lock:
            self._validate_keys_now_locked()

    def _check_one_key(self, requests, prov, field, url,
                       label):
        """ONE provider's key check (v6.13: extracted from
        the validation loop so the run can probe providers
        CONCURRENTLY — OpenJarvis import #2, engine
        discovery style). The behaviour is the loop body's,
        unchanged: one lightweight GET /models with bounded
        (connect, read) timeouts, the result published the
        moment it lands (v5.2). Returns (prov, result) —
        result None when the field is empty. Runs on a
        pool thread; everything it touches is either local,
        lock-guarded, or the publish path itself."""
        key = (self.cfg.get(field) or "").strip()
        if not key:
            return prov, None
        if url is None:
            # v5.0: FreeLLMAPI's base URL is configurable.
            url = self._freellm_base() + "/models"
        headers = {"Authorization": f"Bearer {key}"}
        if prov == "anthropic":
            headers = {"x-api-key": key,
                       "anthropic-version": "2023-06-01"}
        try:
            # v5.2: a (connect, read) tuple, not a scalar —
            # a scalar timeout is per-operation in requests,
            # so a slow-dripping endpoint could hold a check
            # open far past 6 s; the tuple bounds each phase.
            resp = requests.get(url, headers=headers,
                                timeout=(3.05, 5))
        except Exception as exc:
            detail = (f"{type(exc).__name__}: {exc}")[:120]
            if prov == "freellm" and (
                    "onnection" in type(exc).__name__
                    or "refused" in str(exc)):
                # The router APP is not running — a state
                # of its own ("down"), not a key problem and
                # not a network outage. The reachability
                # cache learns it too, so the agent skips
                # the provider instantly until a re-probe.
                result = {
                    "state": "down",
                    "detail": "not running — open the "
                              "FreeLLMAPI app"}
                with self._prov_lock:
                    self._freellm = {"at": time.monotonic(),
                                     "up": False}
                _lb("ERROR", "[BRAIN] FreeLLMAPI not running "
                             "— open the FreeLLMAPI app on "
                             "this laptop; it becomes the "
                             "brain as soon as it is up.")
                log.error("[brain] FreeLLMAPI not running "
                          "(connection refused)")
                self._publish_key_check(prov, result)
                return prov, result
            result = {"state": "unreachable",
                             "detail": detail}
            _lb("ERROR", f"[BRAIN] {label} key check FAILED: "
                         f"{detail}")
            log.error("[brain] %s key check failed: %s",
                      label, detail)
            self._publish_key_check(prov, result)
            return prov, result
        if prov == "freellm":
            # Any HTTP response at all = the app is up.
            with self._prov_lock:
                self._freellm = {"at": time.monotonic(),
                                 "up": True}
        if resp.status_code == 200:
            result = {"state": "ok", "detail": "key OK"}
            log.info("[brain] %s key check: OK", label)
            # v6.5: the candidate walk rides validation —
            # the /models list says which model names this
            # key may actually use, so a dead head model is
            # replaced BEFORE the first command pays for
            # the 404. Best-effort: an unparseable list
            # changes nothing (the live walk still covers
            # the call path), and a mismatch never marks
            # the key itself bad.
            if prov in _MODEL_WALK_PROVIDERS:
                try:
                    ids = set()
                    ordered_ids = []
                    for item in (resp.json().get("data")
                                 or []):
                        mid = str(item.get("id") or "")
                        if mid:
                            if mid not in ids:
                                ordered_ids.append(mid)
                            ids.add(mid)
                            if mid.startswith("models/"):
                                bare = mid[len("models/"):]
                                if bare not in ids:
                                    ordered_ids.append(bare)
                                ids.add(bare)
                    # v7.5 (walk self-discovery): keep the
                    # account's list — _model_candidates
                    # composes the effective walk from models
                    # that EXIST on this account, so a shipped
                    # name the account lacks (the field's
                    # three 404s, 2026-11-16 09:10 IST) costs
                    # no round-trip ever again. The repair
                    # loop below then probes in that effective
                    # order. Both lines go to the logbook, so
                    # the synced log shows what the account
                    # actually offers.
                    try:
                        self._discovered_models[prov] = \
                            list(ordered_ids)
                    except Exception:
                        pass
                    _lb("BRAIN",
                        f"[brain] {label}: models on this "
                        f"account ({len(ordered_ids)}): "
                        f"{', '.join(ordered_ids[:16])}")
                    _lb("BRAIN",
                        f"[brain] {label}: effective walk: "
                        f"{' -> '.join(self._model_candidates(prov))}")
                    for cand in self._model_candidates(prov):
                        if cand not in ids:
                            continue
                        # v7.4 (Defect 1): the probe walks the
                        # SAME order the answering walk uses
                        # (_model_candidates — stale rule
                        # included, instant first), but it
                        # NEVER re-crowns the stale remembered
                        # model: in the field (2026-11-16
                        # 08:24:57) Groq's /models list lacked
                        # the instant + 70b names, the probe
                        # reached openai/gpt-oss-120b, and its
                        # remember persisted the stale name
                        # over the migrated groq_model AND
                        # posed as the answering brain in the
                        # header. The stale candidate is
                        # skipped here (the live walk keeps
                        # it as a fallback candidate, as
                        # always), and the remember is
                        # answered=False — validation repairs
                        # the head, it does not answer.
                        if prov == "groq" and cand == \
                                _GROQ_STALE_REMEMBERED:
                            continue
                        self._remember_working_model(
                            prov, cand, label, answered=False)
                        # v7.6 (auto-model): the pick is
                        # logged ONCE here so the synced log
                        # shows which model validation chose
                        # as the chat head (see
                        # _model_candidates).
                        if ordered_ids:
                            _lb("BRAIN",
                                f"[brain] {label}: auto chat "
                                f"head: {cand} (validation "
                                f"pick — leads the chat walk)")
                        break
                except Exception:
                    pass
        elif resp.status_code in (401, 403):
            detail = (f"HTTP {resp.status_code} — "
                      f"{_err_snippet(resp)}")
            result = {"state": "rejected",
                             "detail": detail}
            _lb("ERROR", f"[BRAIN] {label} key REJECTED: "
                         f"{detail}")
            log.error("[brain] %s key rejected: %s",
                      label, detail)
        else:
            detail = (f"HTTP {resp.status_code} — "
                      f"{_err_snippet(resp)}")
            result = {"state": "unreachable",
                             "detail": detail}
            _lb("ERROR", f"[BRAIN] {label} key check FAILED: "
                         f"{detail}")
            log.error("[brain] %s key check failed: %s",
                      label, detail)
        # v5.2: publish THIS provider's result immediately —
        # the headline must not wait for the rest of the line.
        self._publish_key_check(prov, result)
        return prov, result

    def _validate_keys_now_locked(self):
        """One full validation pass (call ONLY under
        _validate_lock, via _validate_keys_now).

        Each configured key gets ONE lightweight GET /models
        call (bounded (connect, read) timeouts). Results are
        published INCREMENTALLY (v5.2, _publish_key_check):
        each provider lands in _key_checks + brain_status the
        moment its own check finishes. A rejected Claude key
        with an empty Groq field also earns the wrong-field
        hint as a logbook ERROR line.

        v6.13: the checks run CONCURRENTLY (OpenJarvis
        import #2 — engine/_discovery.py::discover_engines
        probes engine health in a thread pool and sorts the
        results deterministically). The key checks and the
        Ollama boot-note probe are independent network
        calls, so they share one pool: the run takes the
        SLOWEST single check (+ slack), not the sum, and
        no check can hold the run past its own timeouts.
        Collection is deterministic — results are gathered
        in _KEY_CHECKS table order for the final state,
        whatever order the pool finished in — and every
        log line is the same line the serial run produced.
        (Voice has no boot probe to add to the pool:
        describe_active() is a pure state read and engine
        health is deliberately lazy — v6.6/v6.7 stickiness
        + persisted parks — so the serial boot cost the
        field logs showed was always on this side.)"""
        try:
            import requests
        except Exception:
            return
        from concurrent.futures import ThreadPoolExecutor
        _checks = [(prov, field, url, label)
                   for prov, field, url, label
                   in self._KEY_CHECKS
                   if (self.cfg.get(field) or "").strip()]
        results = {}

        def _ollama_note():
            # v6.7: the offline brain gets its one boot
            # note — independent of every key check, so it
            # probes alongside them instead of after them.
            try:
                self._note_ollama_at_boot()
            except Exception:
                pass

        with ThreadPoolExecutor(
                max_workers=max(1, len(_checks) + 1),
                thread_name_prefix="nalox-key-probe") as pool:
            _futures = {pool.submit(self._check_one_key,
                                    requests, prov, field,
                                    url, label): prov
                        for prov, field, url, label
                        in _checks}
            _futures[pool.submit(_ollama_note)] = None
            for _fut, _prov in _futures.items():
                try:
                    _out = _fut.result()
                except Exception:
                    continue
                if _prov is not None and _out is not None:
                    _p, _result = _out
                    if _result is not None:
                        results[_p] = _result
        with self._status_lock:
            self._key_checks = results
        self._refresh_brain_status()
        # The wrong-field hint, spelled out once in the log: a
        # rejected Claude key + an empty Groq field is the exact
        # trap Arjun fell into (his gsk_ key sat in Claude's
        # field while Nalox claimed "Claude connected").
        if results.get("anthropic", {}).get("state") == "rejected" \
                and not (self.cfg.get("groq_api_key") or "").strip():
            _lb("ERROR",
                "[BRAIN] Claude key rejected — a Groq key (starts "
                "with gsk_) belongs in the Groq field, not "
                "Claude's. Move it in Settings → Brain.")
            log.error("[brain] hint: the rejected Claude key may "
                      "be a Groq key pasted into the wrong field")


    def _note_ollama_at_boot(self):
        """Note the OFFLINE brain once per Brain instance (v6.7).

        If Ollama answers on its local port, ONE logbook line
        names the model Nalox will fall back to when every
        cloud brain is down — the first walk candidate that is
        actually pulled, else the first pulled model. If it
        does not answer, ONE quiet file-log line and nothing
        more: Ollama is optional (SETUP-OLLAMA.txt), never a
        nag. Best-effort throughout — a note must never break
        validation."""
        if getattr(self, "_ollama_noted", False):
            return
        self._ollama_noted = True
        quiet = ("[brain] Ollama not detected — the offline "
                 "brain is off (optional, see SETUP-OLLAMA.txt)")
        try:
            import requests
            url = (self.cfg.get("ollama_url")
                   or "http://localhost:11434").rstrip("/")
            url = url.replace("://localhost", "://127.0.0.1")
            resp = requests.get(url + "/api/tags", timeout=1.5)
            if resp.status_code != 200:
                log.info(quiet)
                return
            installed = []
            try:
                for item in (resp.json().get("models") or []):
                    name = str(item.get("name") or "").strip()
                    if name:
                        installed.append(name)
            except Exception:
                pass
            model = None
            for cand in self._model_candidates("ollama"):
                if any(n == cand or n.startswith(cand + ":")
                       for n in installed):
                    model = cand
                    break
            if model is None:
                model = (installed[0] if installed
                         else self.cfg.get("ollama_model",
                                           "llama3.1"))
            _lb("BRAIN", f"[BRAIN] Offline brain (Ollama) "
                         f"ready: {model}")
            log.info("[brain] offline brain (Ollama) ready: %s",
                     model)
        except Exception:
            log.info(quiet)

    def _brain_fail(self, label, reason, provider=None,
                    http_status=None):
        """ONE logbook ERROR line per provider failure (v4.8):
        provider + reason (HTTP status + the provider's error
        code, or the exception class). Never key material. Also
        remembered for the honest fallback, and a 401/403 flips
        the live key state so the HUD tells the truth at once."""
        line = f"[BRAIN] {label} FAILED: {reason}"
        # v7.6: inside the chat race a provider failure is
        # EXPECTED (that is what the race is for) — it stays
        # out of the logbook and the failure record below
        # still lands, so an all-providers-down turn keeps
        # today's honest fallback. The python log keeps the
        # line for debugging.
        if getattr(getattr(self, "_race_tls", None),
                   "quiet", False):
            log.info("%s (chat race — silent)", line)
        else:
            _lb("ERROR", line)
            log.error(line)
        with self._status_lock:
            self._last_agent_fail = (label, reason,
                                     time.monotonic())
            # v7.9 (item D): the failure's CAUSE joins this
            # turn's set — _chat_fallback reads it to speak
            # the truthful line (a 429 death is a limit, not
            # a key problem). Guarded: the set is reset per
            # _agent_reply, and a stray call outside a turn
            # (boot validation) must never raise here.
            try:
                if http_status == 429:
                    self._turn_fail_causes.add("ratelimit")
                elif http_status in (401, 403):
                    self._turn_fail_causes.add("auth")
                else:
                    self._turn_fail_causes.add("other")
            except Exception:
                pass
            if provider and http_status in (401, 403):
                self._key_checks[provider] = {
                    "state": "rejected",
                    "detail": f"HTTP {http_status} — {reason}"}
        if provider and http_status in (401, 403):
            self._refresh_brain_status()
        # v7.8: Muse Wonder's auth/billing discipline —
        # a 401/403 (key rejected) or a 402 (billing)
        # parks the provider for the session with ONE
        # clear line (see _park_muse). Any other failure
        # (a timeout, a 5xx, a dead model name) never
        # parks: networks recover, and names are the
        # walk's business.
        if provider == "muse" \
                and http_status in (401, 402, 403):
            self._park_muse(http_status)

    def _park_muse(self, http_status):
        """Park Muse Wonder for the rest of the session
        (v7.8): the Meta API has rejected the key itself
        (401/403) or demands billing (402), so retrying it
        on every chat turn would only tax the race. ONE
        clear logbook line is the whole announcement —
        after that the provider is silent and absent,
        mirroring the ElevenLabs breaker. A restart (or a
        fresh key + restart) re-probes it, exactly like
        the session dead-model memory. Never raises; the
        key itself is never logged."""
        try:
            if getattr(self, "_muse_parked", None) is not None:
                return
            self._muse_parked = http_status
            if http_status == 402:
                line = ("[brain] Muse Wonder: billing "
                        "required (HTTP 402) — parked for "
                        "this session; the other brains "
                        "keep answering")
            else:
                line = (f"[brain] Muse Wonder: key "
                        f"rejected (HTTP {http_status}) — "
                        f"parked for this session; check "
                        f"the key in Settings → Brain")
            _lb("BRAIN", line)
            log.info(line)
        except Exception:
            pass

    def _muse_parked_now(self):
        """True once Muse Wonder is parked this session
        (v7.8) — the chat race fields it no longer."""
        return getattr(self, "_muse_parked", None) is not None

    # ------------------------------------------------ v7.9 429
    def _park_model_ratelimit(self, provider, model, label):
        """Park ONE model for the rate-limit cooldown
        (v7.9, item A): a 429 is a per-model, per-minute
        condition — the model sits out
        MODEL_RATELIMIT_COOLDOWN_S while the walk advances
        to the next candidate. ONE logbook line per park
        (a model already parked does not re-log), and the
        turn's cause set records "ratelimit" for the
        truthful fallback line (item D). Never raises; the
        model is NOT added to _dead_models — it is expected
        back, and the walk must never call it gone."""
        try:
            key = (provider, _model_key(model))
            now = time.monotonic()
            if self._model_cooldowns.get(key, 0.0) > now:
                return
            self._model_cooldowns[key] = (
                now + MODEL_RATELIMIT_COOLDOWN_S)
            try:
                self._turn_fail_causes.add("ratelimit")
            except Exception:
                pass
            line = (f"[brain] {label} model {model} "
                    f"rate-limited — parked 60s, "
                    f"trying next")
            _lb("BRAIN", line)
            log.info(line)
        except Exception:
            pass

    def _model_in_cooldown(self, provider, model):
        """True while (provider, model) sits in its 429
        cooldown (v7.9). An expired entry is dropped on
        sight — the model rejoins every walk at once."""
        try:
            key = (provider, _model_key(model))
            exp = self._model_cooldowns.get(key)
            if exp is None:
                return False
            if exp <= time.monotonic():
                self._model_cooldowns.pop(key, None)
                return False
            return True
        except Exception:
            return False

    def _last_fail_reason(self, label):
        """The recorded reason of the most recent agent
        failure for `label`, or a plain "no answer" —
        the why in the v7.9 fallback outcome lines."""
        try:
            with self._status_lock:
                fail = self._last_agent_fail
            if fail and fail[0] == label:
                return str(fail[1])
        except Exception:
            pass
        return "no answer"

    def _brain_unreachable(self):
        """True when a cloud key exists but the brain is failing:
        validation says rejected/unreachable, or the last agent
        attempt errored within the last 3 minutes."""
        if self.brain_status.get("key_state") in ("rejected",
                                                  "unreachable",
                                                  "down"):
            return True
        with self._status_lock:
            fail = self._last_agent_fail
        return bool(fail and time.monotonic() - fail[2] < 180.0)

    # ------------------------------------------------ v4.8 hot-reload
    def _maybe_reload_config(self):
        """CONFIG HOT-RELOAD: if config.json changed on disk
        since we last looked, merge its key/model/preference
        fields into the live config and re-validate the keys.

        A key pasted into Settings must take effect even if the
        restart hiccups or an older process is the one answering
        (v4.7's single-instance lock makes a second process ask
        the first to show itself — the FIRST process is exactly
        the one that never saw the key). Cheap: one os.stat per
        handle() call. A half-written or corrupt file is ignored
        and retried on the next call; the live config is never
        clobbered by a bad read. Preference fields are adopted
        only when the file's value is non-empty, so a stale file
        can never erase a voice-learned preference."""
        try:
            mtime = self._stat_mtime()
            if mtime is None:
                return
            if self._cfg_mtime is None:
                self._cfg_mtime = mtime
                return
            if mtime == self._cfg_mtime:
                return
            with open(self._cfg_path, "r", encoding="utf-8") as f:
                fresh = json.load(f)
            if not isinstance(fresh, dict):
                return
            # Only a successfully-read file consumes the mtime:
            # a half-written one is retried on the next call.
            self._cfg_mtime = mtime
        except Exception:
            return
        changed = []
        for key_name in self._HOT_RELOAD_KEYS:
            new = fresh.get(key_name)
            if new is None:
                new = ""
            if str(self.cfg.get(key_name) or "") != str(new):
                self.cfg[key_name] = new
                changed.append(key_name)
        for key_name in ("preferred_name", "preferred_lang"):
            new = str(fresh.get(key_name) or "").strip()
            if new and new != str(self.cfg.get(key_name) or ""):
                self._prefs[key_name] = new
                self.cfg[key_name] = new
                changed.append(key_name)
        if not changed:
            return
        notes = []
        for label, field in (("FreeLLMAPI", "freellm_api_key"),
                             ("Claude", "anthropic_api_key"),
                             ("OpenRouter", "openrouter_api_key"),
                             ("Gemini", "gemini_api_key"),
                             ("Groq", "groq_api_key"),
                             ("OpenAI", "openai_api_key")):
            if field in changed:
                notes.append(
                    f"{label} key now "
                    f"{'set' if (self.cfg.get(field) or '').strip() else 'cleared'}")
        msg = "[brain] config reloaded"
        if notes:
            msg += " — " + "; ".join(notes)
        else:
            msg += " (models/preferences)"
        log.info(msg)
        _lb("BRAIN", msg)
        self._refresh_brain_status()
        self._validate_keys_async()
        if any(k.startswith("freellm") for k in changed):
            # A pasted unified key (or a corrected base URL)
            # takes effect in THIS very call: probe the router
            # once, synchronously. That is affordable here — a
            # localhost check, ~1.5 s worst case, once per
            # config change; the per-command path still only
            # ever reads the cache.
            try:
                up = self._probe_freellm_once()
                with self._prov_lock:
                    self._freellm = {"at": time.monotonic(),
                                     "up": up}
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # v3 AGENT BRAIN: when an LLM is reachable, unmatched input goes to a
    # tool-using agent loop. v4.0 priority: Claude (Anthropic) → Groq →
    # OpenAI → Ollama (local). The regex/skill intents above always run
    # FIRST (fast + offline).
    def _execute_leaked_tool(self, name, args):
        """v6.0: run a tool call recovered from leaked markup
        (see _parse_leaked_tool_call). Known agent tools go
        through the normal _run_tool path; the one alias
        (open_file — not a real agent tool, but the obvious
        intent, with actions.open_path behind it) is served
        directly. Returns the short spoken result."""
        if name == "open_file":
            res = actions.open_path(str(args.get("path", "")))
            if isinstance(res, dict) and res.get("ok"):
                base = str(args.get("path", "")).rstrip("\\/") \
                    .replace("\\", "/").rsplit("/", 1)[-1]
                return f"Opened {base}." if base else "Opened it."
            return "I couldn't open that file."
        return self._run_tool(name, args)

    def _guard_reply(self, reply, label, user_text=None,
                     writing=False):
        """v5.4 SCRIPT GUARD, applied at every provider reply
        exit (agent + plain chat): a reply dominated by a
        script outside {Latin, Bengali, Devanagari} is treated
        as a provider FAILURE — logged, and None is returned
        so the cascade falls through to the next provider /
        the honest fallback instead of speaking Chinese (or
        Russian, or Arabic) at Arjun. See _reply_script_ok.

        v5.6 REASONING-LEAK GUARD, same contract: a text-only
        reply that reads as the model's internal deliberation
        (the recycle-bin incident's 13-second chain-of-thought)
        is also a provider failure — logged [cot-guard], None
        returned, cascade moves on. See
        _reply_looks_like_deliberation.

        v5.7 LENGTH CAP, same family: a reply over ~2 short
        sentences / ~45 words breaks the owner's two-line
        rule. On an ACTION turn (user_text given and not a
        question) it is a provider failure — logged
        [length-guard], None returned, cascade moves on. On
        a QUESTION / chat turn (or when no user text is
        known, e.g. plain chat) the reply is TRUNCATED to
        its first two sentences instead — the answer still
        lands, briefly. See _reply_over_cap/_truncate_reply.

        v5.7.1 WRITING EXEMPTION: writing=True marks text the
        owner READS rather than hears (a YouTube comment
        reply, an email draft) — the length cap is skipped
        for it, because a two-sentence email is a broken
        email. The script and CoT guards above STILL apply:
        a Chinese or deliberating draft is still wrong.

        v6.0 MARKUP-LEAK GUARD, the FIRST stage: a reply that
        is a tool call leaked as raw text (the Dots-model
        incident) is never spoken. When it parses to a known
        tool with plausible args it is EXECUTED via the tool
        path and the tool's short result becomes the reply;
        otherwise it is a provider failure (None → next
        provider). See _parse_leaked_tool_call.

        v6.4 LANGUAGE GUARD, same contract: with a learned
        bn/hi preference, a conversational reply that is not
        in the owner's language (an English answer to his
        Bengali, from a chain model that ignored the system
        directive) is a provider failure — logged
        [lang-guard], None returned, cascade moves on; if
        every provider fails it, _chat_fallback speaks its
        honest line in the preferred language. Like the
        length cap, this guard is SKIPPED for writing=True:
        an email or YouTube reply he asked to be written in
        English for others is written in English. See
        _reply_wrong_language.
        """
        leaked = _parse_leaked_tool_call(reply) if reply else None
        if leaked is not None:
            if leaked[0] == "malformed":
                log.warning("[markup-guard] %s reply rejected "
                            "(leaked tool markup, "
                            "unrecoverable): %r", label,
                            reply[:90])
                _lb("BRAIN", f"[markup-guard] {label} reply "
                             "rejected — leaked tool-call "
                             "markup; trying the next provider")
                return None
            name, args = leaked
            result = self._execute_leaked_tool(name, args)
            log.info("[markup-guard] %s leaked tool call "
                     "recovered and executed: %s %s",
                     label, name, args)
            _lb("BRAIN", f"[markup-guard] {label} sent its "
                         f"tool call as text — ran {name} "
                         "instead of speaking the markup")
            if result and not writing \
                    and _reply_over_cap(result):
                result = _truncate_reply(result) or result
            return result
        if reply and not _reply_script_ok(reply):
            log.warning("[script-guard] %s reply rejected "
                        "(wrong script): %r", label, reply[:90])
            _lb("BRAIN", f"[script-guard] {label} reply "
                         "rejected — wrong script; trying the "
                         "next provider")
            return None
        if reply and _reply_looks_like_deliberation(reply):
            log.warning("[cot-guard] %s reply rejected "
                        "(reasoning leak): %r", label, reply[:90])
            _lb("BRAIN", f"[cot-guard] {label} reply rejected "
                         "— internal reasoning, not an answer; "
                         "trying the next provider")
            return None
        if reply and not writing \
                and _reply_wrong_language(reply,
                                          self._pref_lang()):
            # v7.4: counted — the smart-routing escalation
            # reads the delta around a provider call (see
            # _agent_openai_compatible).
            try:
                self._guard_lang_trips = getattr(
                    self, "_guard_lang_trips", 0) + 1
            except Exception:
                pass
            # v7.6: this reply passed the markup, script
            # and CoT stages above and fails on LANGUAGE
            # alone — remember it as the turn's rescue
            # candidate. If the whole cascade still ends
            # without an answer, _agent_reply translates
            # THIS text to Bengali and speaks it instead
            # of discarding it into silence (see
            # _rescue_wrong_language_reply). The verdict
            # itself is unchanged: None is returned and
            # the cascade moves on exactly as before.
            try:
                self._lang_rescue_candidates[
                    threading.get_ident()] = reply
            except Exception:
                pass
            log.warning("[lang-guard] %s reply rejected "
                        "(not in the owner's reply language): "
                        "%r", label, reply[:90])
            _lb("BRAIN", f"[lang-guard] {label} reply "
                         "rejected — wrong language for the "
                         "owner's preference; trying the next "
                         "provider")
            return None
        if reply and not writing and _reply_over_cap(reply):
            if user_text is not None \
                    and not _looks_like_question(user_text):
                log.warning("[length-guard] %s reply rejected "
                            "(over the two-line cap): %r",
                            label, reply[:90])
                _lb("BRAIN", f"[length-guard] {label} reply "
                             "rejected — too long for a command "
                             "answer; trying the next provider")
                return None
            trimmed = _truncate_reply(reply)
            if trimmed and trimmed != reply:
                log.info("[length-guard] %s reply trimmed to "
                         "two sentences", label)
                _lb("BRAIN", f"[length-guard] {label} reply "
                             "trimmed to two sentences")
                return trimmed
            return reply
        # v7.7 (item E): the anti-repetition post-check —
        # the generic closing offer must not land twice in
        # a row (see _strip_repeated_generic_offer).
        if reply and not writing:
            reply = self._strip_repeated_generic_offer(reply)
        return reply

    def _strip_repeated_generic_offer(self, reply):
        """v7.7 (item E): when the PREVIOUS spoken reply
        already ended with a follow-up offer, a trailing
        GENERIC offer ("আর কিছু করতে পারি?" / "anything
        else?") is stripped from this one — the completion
        itself stands, plainly. A specific offer (tied to
        what was just done) is never stripped, and a reply
        that is ONLY the offer is left alone (stripping it
        would empty the turn). The state is the flag
        handle() records per turn (_note_reply_closing)."""
        try:
            if not getattr(self, "_last_reply_had_offer",
                           False):
                return reply
            sents = _split_sentences(reply or "")
            if len(sents) < 2:
                return reply
            if _is_generic_offer(sents[-1]):
                log.info("[brain] repeated generic closing "
                         "offer stripped (item E)")
                return " ".join(sents[:-1])
            return reply
        except Exception:
            return reply

    def _chat_fallback(self, text):
        reply = self._agent_reply(text)
        if reply:
            return reply
        user = self._addr()
        # v6.4: with a learned bn/hi preference, EVERY local
        # fallback below speaks the preferred language too —
        # Bengali-only replies (see _reply_wrong_language):
        # when every provider failed the language guard, the
        # honest line Arjun hears is Bengali, never the
        # English the utterance happened to be in. Without a
        # bn/hi preference the utterance's language rules, as
        # before.
        _pref = self._pref_lang()
        eff_lang = _pref if _pref in ("bn", "hi") else None
        # v4.8 HONEST FALLBACK: a key IS configured but the brain
        # just failed (rejected key / unreachable provider). The
        # v4.5 line below would claim "haven't learned yet" — a
        # lie that sent Arjun hunting in the wrong place. One
        # short line in his language naming the real problem and
        # the field to check (the active provider's own name, so
        # the sentence stays truthful for Claude/OpenAI too).
        # v7.9 (item D): TRUTHFUL FAILURE LINES — the
        # spoken line names THIS turn's real cause (see
        # _turn_fail_causes). A rate-limit death (every
        # Groq candidate 429/parked, the fallbacks spent)
        # is a LIMIT: the old line sent the owner to check
        # a healthy key (field 2026-11-16 13:19–13:33 IST:
        # 29 key-check lines spoken for one rate limit).
        # The limit line never mentions the key; an auth
        # cause keeps the key-check line below, and every
        # other cause keeps the connection line below —
        # both byte-identical to before.
        _causes = getattr(self, "_turn_fail_causes",
                          None) or ()
        if "ratelimit" in _causes \
                and "auth" not in _causes \
                and self._cloud_configured():
            qlang = eff_lang or _text_lang(text, self.lang)
            if qlang == "bn":
                return (f"দুঃখিত {self._addr_bn()}, "
                        "brain-এর limit শেষ হয়ে গেছে — "
                        "একটু পরে আবার চেষ্টা করুন।")
            if qlang == "hi":
                return ("मेरे brain की limit ख़त्म हो गई है, "
                        f"{user} — थोड़ी देर बाद फिर कोशिश "
                        "कीजिए।")
            return ("My brain has hit its usage limit, "
                    f"{user} — please try again in a "
                    "little while.")
        if self._cloud_configured() and self._brain_unreachable():
            label = self._PROVIDER_LABELS.get(
                self.brain_status.get("mode", ""), "Groq")
            qlang = eff_lang or _text_lang(text, self.lang)
            if qlang == "bn":
                return (f"আমার brain-এর connection-এ সমস্যা হচ্ছে, "
                        f"{self._addr_bn()} — Settings-এ {label} "
                        "key টা একবার check করবেন।")
            if qlang == "hi":
                return (f"मेरे brain के connection में दिक्कत है, "
                        f"{user} — Settings में {label} key एक बार "
                        "check कीजिए।")
            return (f"My brain connection has a problem, {user} — "
                    f"please check the {label} key in Settings.")
        # v4.5 ALWAYS-ANSWER: a question / small-talk attempt gets
        # a real conversational sentence in its own language —
        # honest about the limit, JARVIS-style, and it points at
        # what Nalox CAN do. Silence or a bare error is never the
        # answer to something Arjun actually asked.
        if _looks_like_question(text):
            qlang = eff_lang or _text_lang(text, self.lang)
            if qlang == "bn":
                user_bn = self._addr_bn()
                return (f"সেটা আমি এখনো শিখিনি, {user_bn}। তবে app "
                        "খোলা, গান, খবর, সময় — এগুলো বললেই করে দেব।")
            if qlang == "hi":
                return (f"वह मैंने अभी तक नहीं सीखा, {user}। लेकिन "
                        "ऐप खोलना, गाना, खबर और समय — ये कहो तो कर "
                        "दूँगा।")
            return (f"That I haven't learned yet, {user} — but "
                    "apps, music, news and the time are mine to "
                    "command.")
        # v4.4: SHORT JARVIS-style fallback. The v4.3 sentence
        # took ~7 s to speak; a miss should cost ~2 s.
        final_lang = eff_lang or self.lang
        if final_lang == "bn":
            user_bn = self._addr_bn()
            return f"ওটা ঠিক ধরতে পারলাম না, {user_bn}।"
        if final_lang == "hi":
            return f"वो मैं ठीक से समझ नहीं पाया, {user}।"
        return f"That one I couldn't quite catch, {user}."

    def _language_directive(self):
        """The agent's working-language rule, driven by the
        learned language preference — _pref_lang() reads cfg
        + prefs.json and handle()'s hot-reload keeps both
        current, so a preference learned by voice (or edited
        in Settings) changes this directive with NO restart.

        v6.3 shape (2026-11-15 18:22 IST): Bengali by default
        with pref bn, mirroring English/Hindi when he used
        them. SUPERSEDED for the reply side by the owner's
        escalation (18:45 IST): "আমি ইংলিশ বলতে চাই না ওর
        সঙ্গে" — understanding stays trilingual, but with
        pref bn the REPLIES are Bengali ONLY, even when he
        speaks English; pref hi mirrors with Hindi only.
        _reply_wrong_language enforces the same rule as a
        guard, because the free-chain models ignore
        directives. With pref en / no preference, the v4.3
        English-primary rule stands."""
        pref = self._pref_lang()
        if pref == "bn":
            return (" Language: Bengali is your default "
                    "working language with Arjun — it is his "
                    "mother tongue. ALWAYS reply in Bengali "
                    "(বাংলা), whatever language Arjun speaks. "
                    "Never reply in English or Hindi in "
                    "conversation, even when he speaks English "
                    "or Hindi: understand him in any of your "
                    "three languages, answer him in Bengali. "
                    "For short or ambiguous utterances, "
                    "default to Bengali.")
        if pref == "hi":
            return (" Language: Hindi is your default "
                    "working language with Arjun. ALWAYS reply "
                    "in Hindi (हिन्दी), whatever language Arjun "
                    "speaks. Never reply in English or Bengali "
                    "in conversation, even when he speaks "
                    "English or Bengali: understand him in any "
                    "of your three languages, answer him in "
                    "Hindi. For short or ambiguous utterances, "
                    "default to Hindi.")
        return (" Language: English is your primary language. "
                "When Arjun speaks Bengali or Hindi, reply in "
                "that same language with the same character — "
                "English, Bengali and Hindi are your three "
                "languages.")

    def _system_prompt(self):
        mode = MODES[self._mode()]
        prompt = (
            f"You are {self.cfg['assistant_name']}, "
            f"{self.cfg['user_name']}'s personal laptop assistant. "
            "You can act on the laptop with your tools. "
            + _JARVIS_CHARACTER + " " + mode["suffix"]
            + self._language_directive())
        # v4.7: a learned form of address binds the agent too —
        # his real name above stays a fact, the ADDRESS follows
        # the preference he taught Nalox ("call me Sir").
        _addr = self._addr()
        if _addr != str(self.cfg.get("user_name") or "Arjun"):
            prompt += (f" Address him as {_addr}, not by his "
                       "first name.")
        facts = []
        if getattr(self, "memory", None) is not None:
            try:
                facts = self.memory.facts()
            except Exception:
                facts = []
        # v5.4: the memory is REAL — a chain model once told
        # Arjun "আমার দীর্ঘমেয়াদী memory নেই", which is false
        # and cost trust. State it in the prompt itself, with
        # or without facts to inject.
        prompt += (" You have persistent long-term memory: "
                   "preferences and facts Arjun tells you are "
                   "saved on this laptop and survive restarts. "
                   "Never claim you have no long-term memory.")
        # v6.14: SELF-KNOWLEDGE (hearing) — field 2026-11-15
        # 22:45 IST: seconds after hearing him BY VOICE and
        # answering, the brain told Arjun "দুঃখিত, স্যার—
        # আমি আপনার ভয়েস ইনপুট শোনার সুবিধা নেই; টেক্সটের
        # মাধ্যমে জানাতে পারবেন।" — false, and it cost
        # trust exactly like the v5.4 memory denial. The
        # prompt now grounds what Nalox's body actually is:
        # ears first, voice out, Telegram as a second door.
        prompt += (" You hear Arjun by VOICE: he speaks to "
                   "you aloud and your Whisper ears "
                   "transcribe his speech — when a message "
                   "reaches you, he most likely just spoke "
                   "it. You speak your replies aloud with "
                   "your text-to-speech voice. You also "
                   "receive typed text from his Telegram. "
                   "NEVER claim you cannot hear voice input "
                   "or that you have no facility for it, and "
                   "never ask him to type instead of "
                   "speaking.")
        # v5.6: ACT FIRST — the recycle-bin incident: a chain
        # model narrated 13 s of deliberation and did nothing.
        # The thinking stays inside; the tool call is the reply.
        # v7.7 (item D): ASR TOLERANCE — the transcripts he
        # is heard through carry phonetic mistakes, Bengali
        # most of all; the model must reason about the
        # SOUNDS, not surrender to the spelling.
        prompt += (" Transcripts of Arjun's speech contain "
                   "phonetic mistakes — Bengali words are "
                   "often misheard (সং heard as সগ or সাঁগ, "
                   "প্লে as পিলে). Infer the most likely "
                   "intended request from the sounds and ACT "
                   "on it; say you could not understand ONLY "
                   "when no plausible intent exists at all.")
        prompt += (" Act first: when a request matches one of "
                   "your tools, call the tool and report the "
                   "result in one short line. Never narrate your "
                   "reasoning, your deliberation, or which tools "
                   "you have. Full PC control is on: never ask "
                   "for confirmation for PC chores like emptying "
                   "the recycle bin or cleaning temporary files "
                   "— just do them and report. Replies are at "
                   "most two short sentences.")
        # v6.8: ACT, DON'T NARRATE — the WhatsApp field
        # failure (2026-11-15 20:40 IST): asked to open a
        # message and reply to it, the brain answered
        # "রিপ্লাই দিতে পারি" and did NOTHING. A capability
        # claim is not an action; the guard in
        # _agent_openai_compatible retries once when it
        # happens anyway, but the prompt states the rule
        # first.
        prompt += (" If the request asks for an ACTION — "
                   "reply, send, open, type, call, write, "
                   "find — pursue it with tool calls in THIS "
                   "turn. Never end a turn with a bare "
                   "capability or intent claim (\"I can do "
                   "that\", \"আমি করে দেব\") as the whole "
                   "answer. If one step is impossible, do "
                   "every step you CAN and state exactly "
                   "which step blocked and why.")
        # v6.6: CONVERSATIONAL CLOSE — the one mannerism the
        # owner picked from the MARK LIV demo video he studied
        # (2026-11-15): its replies feel alive because they so
        # often end by offering the next step. Nalox may do
        # the same — inside the same two-sentence discipline,
        # never stacked on top of a question the reply already
        # asks. (Writing tasks never see this: they run
        # through _plain_chat's own system line, not this
        # prompt.)
        # v7.7 (item E): the close is now the owner's own
        # shape — a COMPLETED-form confirmation (never the
        # progressive "আমি চালাচ্ছি" he objected to) plus at
        # most one SPECIFIC next-step ask; the generic offer
        # survives only as an occasional alternative, never
        # twice in a row (the post-check in _guard_reply
        # enforces the repetition rule on top).
        prompt += (" Conversational close: when you complete "
                   "a task, confirm it in the COMPLETED form — "
                   "what is DONE, never the progressive (in "
                   "Bengali: 'ঠিক আছে স্যার, গান চালিয়ে "
                   "দিলাম।', never 'আমি চালাচ্ছি') — then you "
                   "may end the reply with ONE short follow-up "
                   "offer that fits what was just done (after "
                   "playing a song: offer the next one or the "
                   "volume; after opening YouTube: ask which "
                   "song or video — or in the owner's shape: "
                   "'তুমি এখন কি করতে চাও, বলো।'), in the "
                   "reply's own language — in Bengali, for "
                   "example: 'আর কিছু করতে পারি, স্যার?' The "
                   "offer counts inside your two-sentence "
                   "limit, and you must not add it when your "
                   "reply already asks a question. Never end "
                   "two replies in a row with the same offer.")
        # v6.1: the LIVE phone state. Field 2026-11-15 16:03:
        # the phone WAS connected through the app, a phone
        # follow-up reached the agent, and the model asked
        # "আপনার ফোন সম্পর্কে কী বলতে চান?" instead of
        # acting — nothing had told it the phone was there.
        # When the app link is up, the prompt says so, in
        # tool terms. (phone_link.is_connected() is an
        # in-memory read — this costs no adb call.)
        try:
            import phone_link
            if phone_link.is_connected():
                _dev = phone_link.device_name() \
                    or "Android phone"
                prompt += (
                    f" Arjun's phone ({_dev}) is connected "
                    "right now through the Nalox Phone app: "
                    "requests about 'my phone' — opening an "
                    "app on the phone, calling from the phone, "
                    "the phone's battery — are done with the "
                    "phone_call / phone_open_app / "
                    "phone_battery tools. Use them; never ask "
                    "what he means about the phone.")
        except Exception:
            pass
        if facts:
            prompt += (" Facts about " + self.cfg["user_name"] + ": "
                       + "; ".join(facts[-10:]) + ".")
        # v4.3: document memory — snippets retrieved for THIS
        # question by _agent_reply (silent when there are none).
        if getattr(self, "_doc_context", ""):
            prompt += (" From Arjun's own documents (use them when "
                       "relevant): " + self._doc_context)
        # v4.3: skill-file catalog (OpenJarvis-style) so the agent
        # knows the named skills exist; voice triggers run them
        # deterministically before the agent is even called.
        names = [s.get("name", "") for s in
                 getattr(self, "skill_files", []) if s.get("name")]
        if names:
            prompt += (" Installed skills: " + ", ".join(names) + ".")
        return prompt

    def _remember_chat(self, text, reply):
        # v7.6: chat-race worker threads never write the
        # history directly — a LOSING racer that finishes
        # late (abandoned) must not record a reply the
        # owner never heard. The race coordinator remembers
        # the winning reply itself, on the calling thread.
        try:
            if getattr(getattr(self, "_race_tls", None),
                       "racing", False):
                return
        except Exception:
            pass
        self.chat_history.append({"role": "user", "content": text})
        self.chat_history.append({"role": "assistant", "content": reply})
        del self.chat_history[:-16]

    # ------------------------------------------------------------ tools
    def _run_tool(self, name, args):
        """Execute one agent tool call; returns a short result string."""
        self._tool_run_count += 1
        args = args or {}
        # v5.2: the logbook/log file keeps the RAW [tool] line
        # (debugging needs the real name + args); the HUD shows
        # the friendly phrase instead — Arjun should never have
        # to read function names in his own window.
        raw_line = f"[tool] {name} {args}" if args \
            else f"[tool] {name}"
        _lb("BRAIN", raw_line)
        log.info(raw_line)
        hud = getattr(self, "hud", None)
        if hud is not None:
            try:
                hud.post(_tool_status_line(name))
            except Exception:
                pass
        try:
            if name == "open_youtube":
                return actions.open_youtube()
            if name == "search_youtube":
                return actions.search_youtube(str(args.get("query", "")))
            if name == "play_on_youtube" or name == "youtube_play":
                q = str(args.get("query", ""))
                if q.strip():
                    self._last_yt_query = q.strip()
                return actions.play_on_youtube(q)
            if name == "snap_app":
                app = str(args.get("app_name", "")).strip()
                side = str(args.get("side", "")).strip().lower()
                if not app or side not in ("left", "right"):
                    return ("snap_app needs an app name and a "
                            "side (left or right).")
                _opened, snapped = self._snap_app_to(app, side)
                if snapped:
                    return f"{app} is snapped to the {side}."
                if _opened:
                    return (f"{app} is open, but I couldn't "
                            f"find its window to snap.")
                return f"I couldn't open {app} on this laptop."
            if name == "snap_active":
                side = str(args.get("side", "")).strip().lower()
                if side not in ("left", "right"):
                    return ("snap_active needs a side "
                            "(left or right).")
                import winlayout
                _ok, snapped = self._run_guarded(
                    "window snap",
                    lambda: winlayout.snap_active(side), 6.0)
                if _ok and snapped:
                    return (f"Moved the active window to the "
                            f"{side}.")
                return "I couldn't move the active window."
            if name == "phone_call":
                contact = str(args.get("contact", "")).strip()
                if not contact:
                    return "phone_call needs a contact name."
                res = self._phone_action("call", name=contact)
                return self._phone_tool_line("call", res, contact)
            if name == "phone_open_app":
                app = str(args.get("app", "")).strip()
                if not app:
                    return "phone_open_app needs an app name."
                res = self._phone_action("open", app=app)
                return self._phone_tool_line("open", res, app)
            if name == "phone_battery":
                res = self._phone_action("battery")
                return self._phone_tool_line("battery", res, "")
            if name == "google_search":
                return actions.google_search(str(args.get("query", "")))
            if name == "open_website":
                return actions.open_website(str(args.get("name", "")))
            if name == "open_app":
                return actions.open_app(str(args.get("name", "")))
            if name == "close_app":
                return actions.close_app(
                    str(args.get("name", ""))) or (
                        "That app is not open right now.")
            if name == "open_folder":
                return actions.open_folder(str(args.get("name", "")))
            if name == "empty_recycle_bin":
                res = actions.empty_recycle_bin()
                if isinstance(res, dict) and res.get("ok"):
                    return "Recycle Bin emptied."
                if isinstance(res, dict):
                    return "I couldn't empty the Recycle Bin."
                return str(res)
            if name == "pc_quick_clean":
                res = actions.pc_quick_clean()
                if isinstance(res, dict):
                    mb = float(res.get("temp_mb") or 0)
                    if mb >= 1:
                        return ("Cleaned the recycle bin and "
                                "temporary files — freed about "
                                f"{'%g' % mb} MB.")
                    return ("Cleaned the recycle bin and "
                            "temporary files.")
                return str(res)
            if name == "open_this_pc":
                res = actions.open_this_pc()
                if isinstance(res, dict):
                    return ("Opened This PC." if res.get("ok")
                            else "I couldn't open This PC.")
                return str(res)
            if name == "volume":
                act = str(args.get("action", "")).strip().lower()
                if act not in ("up", "down", "mute"):
                    return "Unknown volume action (use up, down or mute)."
                return actions.volume(act)
            if name == "screenshot":
                return actions.screenshot()
            if name == "type_text":
                return actions.type_text(str(args.get("text", "")))
            if name == "press_key":
                return actions.press_key(str(args.get("key", "")))
            if name == "battery":
                return self._battery_reply()
            if name == "lock_pc":
                actions.lock_pc()
                return "Locked the laptop."
            if name == "find_leads":
                cfg = self.cfg
                cat = str(args.get("category") or "").strip().lower()
                if cat and cat != (cfg.get("lead_category") or "restaurant"):
                    cfg = dict(cfg)
                    cfg["lead_category"] = cat
                return skills.find_leads(cfg, self.lang)
            if name == "build_demo_website":
                reply, _slug = skills.build_demo(
                    self.cfg, str(args.get("business_name", "")), self.lang)
                return reply
            if name == "email_lead":
                if not self.cfg.get("allow_email_send", True):
                    return ("Email sending is turned off in Settings, "
                            "so I can't send that email.")
                target = str(args.get("business_name") or "").strip() or None
                return skills.email_outreach(self.cfg, target, self.lang)
            if name == "tell_time":
                return self._time_reply()
            if name == "tell_date":
                return self._date_reply()
            if name == "read_my_screen":
                import vision
                result = vision.look_at_screen()
                # v6.8: LOCAL VISION first — when Ollama is
                # up, its vision model (qwen3-vl:8b) describes
                # the screenshot itself, in the reply
                # language; any failure falls back to the
                # OCR text below, exactly as before.
                if self._ollama_available():
                    desc = vision.describe_screen_ollama(
                        self.cfg, result.get("image"), self.lang)
                    if desc:
                        return desc[:2000]
                screen_text = (result.get("text") or "").strip()
                if screen_text:
                    return screen_text[:2000]
                return ("The screen was captured, but no readable "
                        "text was found on it.")
            if name == "take_screenshot":
                import vision
                return ("Screenshot saved: "
                        + str(vision.capture_screen()))
            if name == "take_camera_photo":
                import vision
                photo = vision.capture_camera()
                if photo:
                    return f"Camera photo saved: {photo}"
                return "The camera is not available."
            if name == "youtube_reply_all":
                return self._youtube_reply_all()
            # ---- v4.3 tools ----
            if name == "organise_downloads":
                import skillfiles
                return skillfiles.organise_downloads()
            if name == "find_duplicate_files":
                import skillfiles
                folder = str(args.get("folder") or "").strip()
                if not folder:
                    folder = os.path.join(
                        os.path.expanduser("~"), "Downloads")
                return skillfiles.find_duplicate_files(folder)
            if name == "fetch_url_text":
                import skillfiles
                return skillfiles.fetch_url_text(
                    str(args.get("url", "")))
            if name == "summarise_text":
                src = str(args.get("text", ""))
                if not src.strip():
                    return "Nothing to summarise."
                out = self._plain_chat(
                    "Summarise this in 2-3 short spoken sentences, "
                    "no markdown:\n" + src[:4000])
                return out or (src[:200] + "...")
            if name == "draft_email_save":
                import skillfiles
                return skillfiles.draft_email_save(
                    str(args.get("topic", "")),
                    self._plain_chat_writing)
            if name == "index_my_folder":
                import docmemory
                folder = str(self.cfg.get("doc_folder") or "").strip()
                if not folder:
                    return (f"No document folder is set, {self._addr()} — "
                            "Settings-এর General-এ doc folder বসাও।")
                n = docmemory.index_folder(folder)
                if n:
                    return (f"Indexed your folder, {self._addr()} — {n} "
                            "chunks ready to search.")
                return ("I found no text or markdown files to "
                        f"index in that folder, {self._addr()}.")
            if name == "search_my_files":
                import docmemory
                query = str(args.get("query", ""))
                hits = docmemory.search(query, k=3)
                if not hits:
                    return f"Nothing in your files matches {query}."
                return " ".join(
                    f"{os.path.basename(p)}: {s}"
                    for p, s in hits)[:1200]
        except Exception as exc:
            return f"Tool {name} failed: {exc}"
        return f"Unknown tool: {name}"

    # ------------------------------------------------------------ agent
    # ------------------------------------------------- v6.0 adaptive order
    _PROVIDER_KEY_FIELDS = {
        "anthropic": "anthropic_api_key",
        "openrouter": "openrouter_api_key",
        "gemini": "gemini_api_key",
        "groq": "groq_api_key",
        "openai": "openai_api_key",
    }

    def _freellm_should_defer(self):
        """v6.0 C(2): True while FreeLLMAPI's recent average
        answer time is SLOW (> 8 s over at least 3 measured
        answers) AND a configured, non-rejected direct
        provider looks faster (measured faster, or never
        measured — an untried provider deserves its shot
        while the router crawls). The owner's FreeLLMAPI-
        first preference holds whenever the router performs;
        this only reorders while it doesn't. Any doubt →
        False (the standing order wins)."""
        try:
            import perflevel
            avg = perflevel.provider_avg("freellm",
                                         min_samples=3)
            if avg is None or avg <= 8.0:
                return False
            for name, field in self._PROVIDER_KEY_FIELDS.items():
                if not (self.cfg.get(field) or "").strip():
                    continue
                if self._provider_rejected(name):
                    continue
                if perflevel.provider_failing(name):
                    continue
                other = perflevel.provider_avg(name,
                                               min_samples=1)
                if other is None or other < avg:
                    return True
            return False
        except Exception:
            return False

    # ------------------------------------------------ v6.8
    # brain_state.json is GONE from the chain (owner's
    # Groq-only order): with exactly one cloud provider, the
    # v6.7 E cross-session provider memory had nothing left
    # to remember — Groq's working MODEL is still remembered
    # by the candidate walk in config (groq_model), which is
    # where that knowledge belongs. The file itself stays on
    # the updater deny-list (it is user data on his disk).

    # ------------------------------------------------ v7.6 rescue
    def _pop_lang_rescue_candidate(self):
        """This thread's language-guard rescue candidate
        (see _guard_reply's v7.6 stash), removed and
        returned — or None. Consuming (not peeking) keeps a
        stale candidate from leaking into a later turn."""
        try:
            return self._lang_rescue_candidates.pop(
                threading.get_ident(), None)
        except Exception:
            return None

    def _rescue_wrong_language_reply(self, text):
        """v7.6 REPLY-LANGUAGE RESCUE (item A): the cascade
        ended without an answer, but the language guard
        rejected an otherwise-valid reply on language alone
        this turn — translate THAT reply to Bengali and
        speak it, instead of discarding it into the honest
        fallback while the owner hears nothing.

        The candidate is only ever the FINAL spoken text:
        tool calls and their arguments are never translated
        (they executed, or not, long before this point —
        this runs after every retry, at the end of
        _agent_reply). All of the owner's rules still bind
        the rescued text: pref must be bn; a bare
        capability narration is the narrate guard's
        business, never rescued; the translation must pass
        the script guard and the language guard itself;
        the two-line cap applies exactly as _guard_reply
        applies it (an over-cap ACTION answer fails, a
        chat answer is trimmed). Writing tasks never reach
        here (the guard is skipped for them, so no
        candidate is ever stashed). Any failure — no
        candidate, translation unavailable, guards — returns
        None and _chat_fallback speaks today's honest line,
        unchanged."""
        try:
            candidate = self._pop_lang_rescue_candidate()
            if not candidate or not str(candidate).strip():
                return None
            if self._pref_lang() != "bn":
                return None
            candidate = str(candidate)
            if _looks_like_action_request(text) \
                    and _is_capability_claim(candidate):
                # v7.7 (item J): the v7.6 rule returned None
                # here — "a bare capability narration is the
                # narrate guard's business, never rescued".
                # But the narrate guard only ever sees a
                # reply that SURVIVED the guards; a claim
                # rejected on LANGUAGE never reaches it, so
                # the turn fell past this rescue into the
                # could-not-hear line (field 2026-11-16
                # 11:58 IST, twice: Groq answered the song
                # request in English, the guard rejected it,
                # and the owner heard "ওটা ঠিক ধরতে পারলাম
                # না" — a false claim about his hearing).
                # The narration rule itself is unchanged —
                # the claim TEXT is still never spoken, and
                # the translator never touches it — but the
                # turn now ends with the narrate guard's own
                # honest line instead of the hearing lie:
                # the job was not done, and Nalox says so.
                log.info("[brain] language-rejected claim "
                         "ends the turn honestly (item J)")
                _lb("BRAIN", "[brain] the only reply was a "
                             "claim in the wrong language — "
                             "ending honestly, not with the "
                             "could-not-hear line")
                return self._loc(
                    "Sorry sir, I could not do that just now.",
                    "দুঃখিত sir, কাজটা এখন করে উঠতে পারলাম না।")
            translated = _translate_to_bengali(candidate)
            if not translated:
                return None
            if not _reply_script_ok(translated):
                return None
            if _reply_wrong_language(translated, "bn"):
                return None
            if _reply_over_cap(translated):
                if text is not None \
                        and not _looks_like_question(text):
                    return None
                trimmed = _truncate_reply(translated)
                if trimmed:
                    translated = trimmed
            log.info("[brain] reply translated to Bengali "
                     "(rescue)")
            _lb("BRAIN", "[brain] reply translated to "
                         "Bengali (rescue)")
            return translated
        except Exception:
            return None

    # ------------------------------------------------ v7.6 chat race
    def _chat_racers(self, text, tier, groq_key):
        """The chat race's field (v7.6, item E): one
        callable per provider that is ACTUALLY configured
        and available — Groq (key pasted, not rejected;
        its walk is the discovered/auto walk of item B),
        Gemini (only when its Settings key exists),
        FreeLLMAPI (only when the local gateway answers
        its cached reachability probe). Each callable runs
        that provider's candidate walk with the race's
        per-call cap; the walk's guards apply unchanged.
        Returns [(name, provider, callable)].

        v7.8: Muse Wonder (Meta Model API) joins the
        field under the same discipline — only when its
        Settings → Brain key exists and the provider is
        not parked for the session (see _park_muse). No
        key = no racer and ZERO calls to api.meta.ai,
        anywhere in the program."""
        racers = []
        if groq_key and not self._provider_rejected("groq"):
            racers.append((
                "Groq", "groq",
                lambda: self._agent_openai_walk(
                    text, "https://api.groq.com/openai/v1",
                    groq_key,
                    self.cfg.get("groq_model",
                                 "llama-3.1-8b-instant"),
                    label="Groq", provider="groq",
                    timeout=CHAT_RACE_BUDGET_S, tier=tier)))
        gem_key = (self.cfg.get("gemini_api_key")
                   or "").strip()
        if gem_key and not self._provider_rejected("gemini"):
            racers.append((
                "Gemini", "gemini",
                lambda: self._agent_openai_walk(
                    text, GEMINI_BASE, gem_key,
                    self.cfg.get("gemini_model",
                                 "gemini-2.5-flash"),
                    label="Gemini", provider="gemini",
                    timeout=CHAT_RACE_BUDGET_S)))
        try:
            fl_up = self._freellm_available()
        except Exception:
            fl_up = False
        if fl_up:
            fl_key = (self.cfg.get("freellm_api_key")
                      or "").strip()
            racers.append((
                "FreeLLMAPI", "freellm",
                lambda: self._agent_openai_walk(
                    text, self._freellm_base(), fl_key,
                    self.cfg.get("freellm_model", "auto"),
                    label="FreeLLMAPI", provider="freellm",
                    timeout=CHAT_RACE_BUDGET_S)))
        # v7.8: Muse Wonder — the paid Meta brain races
        # only when its key is pasted and it is not parked
        # (a 401/402/403 earlier this session). Its walk
        # is the single configured model; the production
        # system prompt, every guard and the language
        # rescue apply to it exactly as to every racer.
        muse_key = (self.cfg.get("muse_api_key")
                    or "").strip()
        if muse_key and not self._muse_parked_now() \
                and not self._provider_rejected("muse"):
            racers.append((
                "muse-wonder", "muse",
                lambda: self._agent_openai_walk(
                    text, MUSE_BASE, muse_key,
                    self.cfg.get("muse_model",
                                 MUSE_DEFAULT_MODEL),
                    label="Muse Wonder", provider="muse",
                    timeout=CHAT_RACE_BUDGET_S, tier=tier)))
        return racers

    def _chat_race(self, text, tier, groq_key):
        """Race the configured chat providers (v7.6, item
        E). Returns (ran, reply): ran=False when fewer
        than two providers are configured (the caller then
        takes the serial path, byte-identical to v7.5);
        ran=True with reply=None when the race ran and
        nobody passed the guards in time.

        The first reply passing ALL guards wins at once;
        losers are abandoned daemon threads whose late
        results land in a dead result queue (their
        _remember_chat is suppressed by the racing flag —
        the coordinator remembers the WINNER). A finisher
        failing ONLY the language guard deposits its text
        as the rescue candidate and shortens the wait to
        the grace window: a native pass from a still-
        running provider beats the rescue, else the
        candidate is handed to _agent_reply's rescue.
        Provider failures inside the race are silent (the
        quiet flag) — ONE [brain] line names the winner
        and its milliseconds."""
        racers = self._chat_racers(text, tier, groq_key)
        if len(racers) < 2:
            return False, None
        import queue as _queue_mod
        done = _queue_mod.Queue()

        def _run(name, provider, fn):
            try:
                self._race_tls.quiet = True
                self._race_tls.racing = True
            except Exception:
                pass
            try:
                reply = fn()
            except Exception:
                reply = None
            cand = None
            if not reply:
                cand = self._pop_lang_rescue_candidate()
            done.put((name, provider, reply, cand))

        _t0 = time.monotonic()
        for _name, _prov, _fn in racers:
            try:
                threading.Thread(
                    target=_run, args=(_name, _prov, _fn),
                    daemon=True,
                    name=f"nalox-chat-race-{_prov}").start()
            except Exception:
                pass
        pending = len(racers)
        lang_cand = None
        deadline = _t0 + CHAT_RACE_BUDGET_S
        while pending > 0:
            _left = deadline - time.monotonic()
            if _left <= 0:
                break
            try:
                name, provider, reply, cand = done.get(
                    timeout=_left)
            except Exception:
                break
            pending -= 1
            if reply:
                _ms = int((time.monotonic() - _t0) * 1000)
                _lb("BRAIN", f"[brain] chat race: {name} "
                             f"answered first ({_ms} ms)")
                log.info("[brain] chat race: %s answered "
                         "first (%d ms)", name, _ms)
                try:
                    import perflevel
                    perflevel.record_provider(
                        provider, time.monotonic() - _t0, True)
                except Exception:
                    pass
                # v7.8: the winner's provider is the last
                # REAL answer's — the brain line reads it
                # (a non-walk winner like FreeLLMAPI never
                # records its own via _remember_working_
                # model, so the coordinator's word stands).
                try:
                    self._last_answer_provider = provider
                except Exception:
                    pass
                self._remember_chat(text, reply)
                return True, reply
            if cand and lang_cand is None:
                lang_cand = cand
                # Grace: a native pass may still beat the
                # rescue — but the turn never waits past
                # the grace for it.
                deadline = min(
                    deadline,
                    time.monotonic() + CHAT_RACE_GRACE_S)
        if lang_cand:
            # Hand the candidate to this thread's rescue
            # (item A) exactly as if the serial cascade's
            # final guard rejection had stashed it here.
            try:
                self._lang_rescue_candidates[
                    threading.get_ident()] = lang_cand
            except Exception:
                pass
        return True, None

    # ------------------------------------------------ v7.9 fallbacks
    def _agent_muse_fallback(self, text):
        """Muse Wonder WITH TOOLS as the agent path's
        first fallback (v7.9, item C): reached only when
        the Groq walk has failed ENTIRELY on an action
        turn. The same OpenAI-compatible tool machinery
        as every agent call (the Meta endpoint speaks it
        — see the v7.8 note at MUSE_BASE), the same
        guards, and v7.8's parking discipline (a 401/402/
        403 parks it for the session inside _brain_fail).
        No key / parked / rejected → returns None at once
        with zero network, and the order collapses to
        Groq → Ollama exactly as before. One logbook line
        per attempt + outcome."""
        try:
            key = (self.cfg.get("muse_api_key")
                   or "").strip()
        except Exception:
            key = ""
        if not key or self._muse_parked_now() \
                or self._provider_rejected("muse"):
            return None
        reply = self._agent_openai_compatible(
            text, MUSE_BASE, key,
            self.cfg.get("muse_model", MUSE_DEFAULT_MODEL),
            label="Muse Wonder", provider="muse",
            call_budgets=(AGENT_FIRST_CALL_BUDGET_S,
                          AGENT_CALL_BUDGET_S))
        if reply:
            _lb("BRAIN",
                "[brain] agent fallback: Muse Wonder "
                "answered")
            log.info("[brain] agent fallback: Muse Wonder "
                     "answered")
            return reply
        _why = self._last_fail_reason("Muse Wonder")
        _lb("BRAIN",
            f"[brain] agent fallback: Muse Wonder "
            f"failed: {_why}")
        log.info("[brain] agent fallback: Muse Wonder "
                 "failed: %s", _why)
        return None

    def _ollama_chat_net(self, text):
        """The chat path's Ollama safety net (v7.9,
        item B): the race (or the serial chat path) ended
        with no passing reply — before any failure line,
        ONE bounded Ollama attempt: the existing machinery
        (_agent_ollama → the impl, production system
        prompt, every guard), capped at the first live
        candidate with an ~8 s per-call budget
        (CHAT_OLLAMA_NET_TIMEOUT_S) instead of the full
        local walk. The bounding knobs ride on the
        instance so a monkeypatched _agent_ollama in the
        suites still sees the plain one-argument call.
        Attempt + outcome get ONE logbook line each way —
        "[brain] chat fallback: Ollama answered" /
        "…failed: <why>" — so the next sync finally shows
        whether his Ollama works in production (item E)."""
        _prev_timeout = getattr(
            self, "_ollama_timeout_override", None)
        _prev_max = getattr(
            self, "_ollama_max_candidates", None)
        self._ollama_timeout_override = \
            CHAT_OLLAMA_NET_TIMEOUT_S
        self._ollama_max_candidates = 1
        try:
            reply = self._agent_ollama(text)
        finally:
            self._ollama_timeout_override = _prev_timeout
            self._ollama_max_candidates = _prev_max
        if reply:
            _lb("BRAIN",
                "[brain] chat fallback: Ollama answered")
            log.info("[brain] chat fallback: Ollama "
                     "answered")
            return reply
        _why = getattr(self, "_ollama_last_error",
                       None) or "no answer"
        _lb("BRAIN",
            f"[brain] chat fallback: Ollama failed: "
            f"{_why}")
        log.info("[brain] chat fallback: Ollama failed: "
                 "%s", _why)
        return None

    def _arm_progress_line(self):
        """v7.9 (item I.3): arm the no-silent-work line
        for an AGENT turn. A daemon Timer fires once at
        AGENT_PROGRESS_S; if the turn is still running it
        speaks the cached progress line (fixed=True —
        male-warmed under item H) through the speaker.
        Returns the turn state the disarm flips. No
        speaker (tests, headless) = a state with no
        timer. Never raises."""
        state = {"done": False, "timer": None}
        try:
            speaker = getattr(self, "speaker", None)
            if speaker is None:
                return state

            def _fire():
                if state["done"]:
                    return
                state["done"] = True
                try:
                    speaker.say(AGENT_PROGRESS_LINE,
                                lang="bn", fixed=True)
                except Exception:
                    pass

            _t = threading.Timer(AGENT_PROGRESS_S, _fire)
            _t.daemon = True
            _t.start()
            state["timer"] = _t
        except Exception:
            pass
        return state

    def _disarm_progress_line(self, state):
        """The turn ended — the progress line must never
        speak for a finished turn (item I.3)."""
        try:
            state["done"] = True
            _t = state.get("timer")
            if _t is not None:
                _t.cancel()
        except Exception:
            pass

    def _agent_reply(self, text):
        """The brain (v6.8): GROQ, then the offline Ollama —
        nothing else is ever tried. (v7.6: true of the
        AGENT/action path only — the CHAT path races, see
        the v7.6 paragraph at the end of this docstring.)

        The owner's order (2026-11-15 20:31 IST, after a week
        of field logs): "সবচেয়ে বেশি ফার্স্ট যে রিপ্লাই
        দিচ্ছে তাকে রেখে বাকিগুলো মুছে ফেলো" — keep the
        fastest replier, remove the rest. Groq answered in
        seconds in every log while FreeLLMAPI and Gemini
        burned ~10 s a command on timeouts and Claude /
        OpenRouter / OpenAI sat rejected or empty; the
        per-command provider walk WAS the remaining latency.
        So the chain is now: Groq (with its v6.5 model
        candidate walk + remembered working model and every
        reply guard) → Ollama, the silent OFFLINE last
        resort, reached only when Groq fails entirely and a
        local server is actually answering (its cached probe
        costs the normal path nothing). His other keys stay
        in Settings untouched — Nalox simply never calls
        them. If Groq fails and Ollama is absent, None comes
        back and _chat_fallback speaks the honest line.

        v4.3: before calling anyone, a question of 3+ words
        quietly searches Arjun's indexed documents; the
        top-2 snippets ride along in the system prompt
        (self._doc_context). Silent on any failure — the
        chat must never notice the memory hiccup.

        v7.6: the CHAT path races the configured providers
        (item E — the owner reversed the Groq-only rule
        for chat: Groq / Gemini / FreeLLMAPI, first
        guard-passing reply wins), and a cascade that ends
        answerless gets the reply-language rescue (item A)
        before _chat_fallback's honest line. The
        AGENT/action path below is unchanged.

        v7.8: Muse Wonder (the owner's paid Meta brain)
        is one more chat racer when its key is pasted —
        the agent/action path STILL never calls it.

        v7.9: the fallbacks grow up (field log 2026-11-16
        13:19–13:33 IST — a Groq 429 killed a half-done
        Notepad chain and the fallback blamed the key).
        A 429 now advances the Groq walk instead of
        killing the turn (item A); the agent path, when
        the Groq walk fails entirely, falls back to Muse
        Wonder WITH TOOLS (item C — reversing v7.8's
        never-on-the-agent-path rule for the fallback
        position only; Groq still leads every turn) and
        then Ollama; a chat turn that ends answerless
        gets ONE bounded Ollama attempt before any
        failure line (item B); every fallback logs its
        attempt + outcome (item E); and the spoken
        failure line names the turn's real cause
        (item D, in _chat_fallback).

        v7.9 (item I): an ACTION turn additionally arms
        the agent per-call budgets (first call ~3 s,
        later calls ~5 s — a timeout advances the walk
        via _MODEL_SLOW) and the no-silent-work progress
        line (one cached Bengali line if the turn passes
        ~4 s), and one step's independent tool calls run
        concurrently. Chat turns get none of this.
        """
        self._doc_context = ""
        try:
            if text and len(str(text).split()) >= 3:
                import docmemory
                hits = docmemory.search(str(text), k=2)
                if hits:
                    self._doc_context = " ".join(
                        f"[{os.path.basename(p)}] {s}"
                        for p, s in hits)[:900]
        except Exception:
            self._doc_context = ""
        # v7.9 (item D): this turn's failure-cause set
        # starts empty — _brain_fail and the 429 park fill
        # it as the turn fails, and _chat_fallback reads
        # it to speak the truthful failure line.
        try:
            self._turn_fail_causes = set()
        except Exception:
            pass
        # v4.4: no provider available -> NO network at all.
        # The local fallback must cost ~0.0 s of brain time.
        if not self._agent_available():
            return None
        # v4.8: this attempt starts clean — _brain_fail
        # re-marks the failure below if a provider errors, so
        # the honest fallback judges THIS call, not an
        # ancient one.
        with self._status_lock:
            self._last_agent_fail = None
        # v7.6: a fresh turn starts with no rescue
        # candidates — the guards refill this turn's own as
        # providers answer (see _guard_reply).
        try:
            self._lang_rescue_candidates.clear()
        except Exception:
            pass
        groq_key = (self.cfg.get("groq_api_key") or "").strip()
        # v7.4: the smart-routing tier for this utterance
        # (None = routing off = v7.3 exactly).
        _tier = self._tier_for(text)
        if _tier is not None:
            log.info("[brain] smart routing: tier=%s",
                     _tier)
        # v7.6 (item E): a plain-CHAT turn races the
        # configured providers (see _chat_race); an ACTION
        # turn never races — the agent path keeps the v7.4
        # power walk exactly. When the race doesn't run
        # (fewer than two providers configured), the serial
        # Groq call below is v7.5 behaviour, untouched.
        _is_action = _looks_like_action_request(text)
        _race_ran = False
        if not _is_action:
            _race_ran, reply = self._chat_race(
                text, _tier, groq_key)
            if reply:
                return reply
        # v7.9 (item I): an ACTION turn arms the
        # no-silent-work progress line and the agent
        # per-call budgets; a CHAT turn gets neither
        # (chat/race budgets are unchanged).
        _budgets = (AGENT_FIRST_CALL_BUDGET_S,
                    AGENT_CALL_BUDGET_S) \
            if _is_action else None
        _progress = self._arm_progress_line() \
            if _is_action else None
        try:
            if not _race_ran and groq_key \
                    and not self._provider_rejected("groq"):
                reply = self._agent_openai_compatible(
                    text, "https://api.groq.com/openai/v1", groq_key,
                    self.cfg.get("groq_model",
                                 "llama-3.1-8b-instant"),
                    label="Groq", provider="groq", tier=_tier,
                    call_budgets=_budgets)
                if reply:
                    _lb("BRAIN", "Groq answered")
                    return reply
            if _is_action:
                # v7.9 (item C): the AGENT path's fallback
                # order — Groq (above) → Muse Wonder WITH
                # TOOLS when its key is pasted → Ollama → the
                # honest fallback. Every fallback logs its
                # attempt + outcome (items C/E), so the next
                # sync shows which brain actually carried the
                # turn — or that none could.
                reply = self._agent_muse_fallback(text)
                if reply:
                    return reply
                reply = self._agent_ollama(text)
                if reply:
                    _lb("BRAIN", "Ollama answered")
                    return reply
                _why = getattr(self, "_ollama_last_error",
                               None) or "no answer"
                _lb("BRAIN",
                    f"[brain] agent fallback: Ollama failed: "
                    f"{_why}")
                log.info("[brain] agent fallback: Ollama "
                         "failed: %s", _why)
            else:
                # v7.9 (item B): the CHAT path's safety net —
                # ONE bounded Ollama attempt stands between a
                # dead race / serial path and the failure
                # line (see _ollama_chat_net).
                reply = self._ollama_chat_net(text)
                if reply:
                    return reply
            # v7.6 (item A): the cascade ended answerless —
            # before the honest fallback, rescue the turn's
            # language-guard candidate by translating it to
            # Bengali (see _rescue_wrong_language_reply).
            rescued = self._rescue_wrong_language_reply(text)
            if rescued:
                self._remember_chat(text, rescued)
                return rescued
            return None
        finally:
            if _progress is not None:
                self._disarm_progress_line(_progress)

    def _anthropic_tools(self):
        """AGENT_TOOLS converted to the Anthropic tool format."""
        tools = []
        for t in AGENT_TOOLS:
            fn = t["function"]
            tools.append({"name": fn["name"],
                          "description": fn["description"],
                          "input_schema": fn["parameters"]})
        return tools

    def _anthropic_system(self):
        """The JARVIS system prompt + a line about the memory."""
        return (self._system_prompt()
                + " You also have long-term memory: the facts about "
                  "Arjun in this prompt are things you remember about "
                  "him — use them when they are relevant.")

    def _agent_anthropic(self, text):
        """v6.0 timing wrapper: record the attempt's latency
        + outcome in perflevel (the ⚡ Level and the adaptive
        provider order read it), then run the real loop."""
        _t0 = time.time()
        try:
            reply = self._agent_anthropic_impl(text)
        except Exception:
            reply = None
        try:
            import perflevel
            perflevel.record_provider(
                "anthropic", time.time() - _t0, bool(reply))
        except Exception:
            pass
        return reply

    def _agent_anthropic_impl(self, text):
        """Tool-using loop against the Anthropic Messages API (Claude).

        Raw HTTPS via requests — no SDK. Same tools and memory as
        every other provider, max ~5 tool rounds, short replies
        (max_tokens 400). On ANY failure: _brain_fail logs ONE
        logbook ERROR line (v4.8 — the old version warned into the
        python log only, invisible on the diagnostics page) and
        returns None, so _agent_reply moves on to Groq → OpenAI →
        Ollama.
        """
        try:
            import requests
            key = (self.cfg.get("anthropic_api_key") or "").strip()
            if not key:
                return None
            model = self.cfg.get("anthropic_model", "claude-sonnet-4-5")
            headers = {"x-api-key": key,
                       "anthropic-version": "2023-06-01",
                       "Content-Type": "application/json"}
            url = "https://api.anthropic.com/v1/messages"
            system = self._anthropic_system()
            history = [{"role": m["role"], "content": m["content"]}
                       for m in self.chat_history[-8:]
                       if m.get("role") in ("user", "assistant")
                       and isinstance(m.get("content"), str)]
            messages = history + [{"role": "user", "content": text}]
            tools = self._anthropic_tools()
            for _round in range(5):
                resp = requests.post(
                    url, headers=headers,
                    json={"model": model, "max_tokens": 400,
                          "system": system, "messages": messages,
                          "tools": tools},
                    timeout=PROVIDER_TIMEOUT_S)
                if resp.status_code != 200:
                    self._brain_fail(
                        "Claude",
                        f"HTTP {resp.status_code} — "
                        f"{_err_snippet(resp)}",
                        provider="anthropic",
                        http_status=resp.status_code)
                    return None
                blocks = resp.json().get("content") or []
                tool_uses = [b for b in blocks
                             if b.get("type") == "tool_use"]
                if not tool_uses:
                    reply = " ".join(
                        b.get("text", "") for b in blocks
                        if b.get("type") == "text").strip()
                    reply = self._guard_reply(reply, "Claude", text)
                    if reply:
                        self._remember_chat(text, reply)
                    return reply or None
                messages.append({"role": "assistant", "content": blocks})
                results = []
                for tu in tool_uses:
                    result = self._run_tool(tu.get("name", ""),
                                            tu.get("input") or {})
                    results.append({"type": "tool_result",
                                    "tool_use_id": tu.get("id", ""),
                                    "content": result})
                messages.append({"role": "user", "content": results})
            # Tool rounds used up — ask once more, without tools.
            resp = requests.post(
                url, headers=headers,
                json={"model": model, "max_tokens": 400,
                      "system": system, "messages": messages},
                timeout=PROVIDER_TIMEOUT_S)
            if resp.status_code != 200:
                self._brain_fail(
                    "Claude",
                    f"HTTP {resp.status_code} — {_err_snippet(resp)}",
                    provider="anthropic",
                    http_status=resp.status_code)
                return None
            blocks = resp.json().get("content") or []
            reply = " ".join(b.get("text", "") for b in blocks
                             if b.get("type") == "text").strip()
            reply = self._guard_reply(reply, "Claude", text)
            if reply:
                self._remember_chat(text, reply)
            return reply or None
        except Exception as exc:
            self._brain_fail(
                "Claude", f"{type(exc).__name__}: {exc}"[:160],
                provider="anthropic")
            return None

    def _plain_chat(self, prompt, writing=False):
        """One-shot chat completion WITHOUT tools — for writing
        tasks like a YouTube comment reply
        (youtube_tools.make_reply).

        v6.8: the same Groq-only rule as _agent_reply (the
        owner's order) — Groq with its model candidate walk,
        then the offline Ollama last resort. Returns the
        text, or None if no brain is reachable.

        v5.7.1: writing=True when the result is text the
        owner READS (comment replies, email drafts) — the
        reply then skips the spoken two-line length cap in
        _guard_reply, while the script and CoT guards still
        vet it. Spoken uses (e.g. the summarise_text tool,
        whose output is read aloud) keep the default
        writing=False.
        """
        # Groq, no tools (v6.8: the only cloud brain — see
        # _agent_reply for the owner's order and the field
        # evidence behind it).
        # v6.8: Groq is the ONLY entry (owner's Groq-only
        # order) — the walk/budget/guard body below is the
        # v6.5/v6.6 machinery, unchanged.
        for cfg_key, base_url, model_key, model_default, label, prov in (
                ("groq_api_key", "https://api.groq.com/openai/v1",
                 "groq_model", "llama-3.1-8b-instant", "Groq", "groq"),):
            api_key = (self.cfg.get(cfg_key) or "").strip()
            if not api_key or self._provider_rejected(prov):
                continue
            # v6.5: walk providers try their model candidates
            # in turn — a dead model name moves to the next
            # candidate; any other outcome (an answer, a guard
            # rejection, an HTTP failure, an exception) ends
            # this provider exactly as before.
            _walk = prov in _MODEL_WALK_PROVIDERS
            _candidates = (self._model_candidates(prov) if _walk
                           else [])
            if not _candidates:
                _candidates = [self.cfg.get(model_key,
                                            model_default)]
            _last_miss = None
            _walk_start = time.monotonic()
            for _ci, _cand in enumerate(_candidates):
                # v6.6: the same ONE total walk budget as the
                # agent path (MODEL_WALK_BUDGET_S across all
                # candidates, not a fresh cap per name).
                _remaining = MODEL_WALK_BUDGET_S - (
                    time.monotonic() - _walk_start)
                if _ci and _remaining <= 0:
                    self._brain_fail(
                        label,
                        f"model walk budget spent "
                        f"({MODEL_WALK_BUDGET_S:.0f}s) — tried "
                        f"{', '.join(_candidates[:_ci])} "
                        f"(plain chat)",
                        provider=prov)
                    break
                try:
                    import requests
                    # v6.13: a 429 retries with jittered
                    # backoff inside this candidate's own
                    # timeout (already the provider cap
                    # bounded by the walk remainder).
                    _call_timeout = min(
                        PROVIDER_TIMEOUT_S,
                        max(1.0, _remaining))
                    resp = _post_with_rl_retry(
                        requests.post,
                        base_url + "/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}",
                                 "Content-Type": "application/json"},
                        json_body={"model": _cand,
                                   "messages": [
                                       {"role": "system",
                                        "content": ("You are Nalox, Arjun's "
                                                    "assistant. Reply with ONLY "
                                                    "the text asked for — no "
                                                    "quotes, no preamble.")},
                                       {"role": "user",
                                        "content": prompt}],
                                   "max_tokens": 300},
                        timeout_s=_call_timeout,
                        deadline=(time.monotonic()
                                  + _call_timeout))
                    if resp.status_code == 200:
                        reply = (resp.json()["choices"][0]["message"]
                                 .get("content") or "").strip()
                        reply = self._guard_reply(reply, label,
                                                  writing=writing)
                        if reply:
                            # v7.3: unconditional — the call
                            # records the answering model in
                            # memory even when it is already
                            # the remembered head (nothing is
                            # persisted then; see the method).
                            self._remember_working_model(
                                prov, _cand, label)
                            _lb("BRAIN", f"{label} answered (plain chat)")
                            return reply
                        break
                    if _walk and _model_error_snippet(
                            resp.status_code, resp) is not None:
                        _last_miss = _cand
                        continue
                    # v4.8: was a silent `continue` — a dead key
                    # here starved YouTube replies invisibly too.
                    self._brain_fail(
                        label,
                        f"HTTP {resp.status_code} — "
                        f"{_err_snippet(resp)} (plain chat)",
                        provider=prov,
                        http_status=resp.status_code)
                    break
                except Exception as exc:
                    self._brain_fail(
                        label,
                        f"{type(exc).__name__}: {exc} (plain chat)"[:160],
                        provider=prov)
                    break
            else:
                if _last_miss is not None:
                    self._brain_fail(
                        label,
                        f"no working model — tried "
                        f"{', '.join(_candidates)} (plain chat)",
                        provider=prov)
        # Ollama (local), no tools. v4.4: the cached availability
        # decides — no fresh /api/tags probe on this path either.
        # v6.7: the candidate walk + the generous local timeout
        # ride along here too — a writing task deserves the same
        # dependable last resort as a spoken command.
        try:
            import requests
            url = self.cfg.get(
                "ollama_url", "http://localhost:11434").rstrip("/")
            if self._ollama_available():
                _candidates = self._model_candidates("ollama") or [
                    self.cfg.get("ollama_model", "llama3.1")]
                for _cand in _candidates:
                    resp = requests.post(
                        url + "/api/chat",
                        json={"model": _cand,
                              "messages": [
                                  {"role": "system",
                                   "content": ("You are Nalox, Arjun's "
                                               "assistant. Reply with ONLY "
                                               "the text asked for — no "
                                               "quotes, no preamble.")},
                                  {"role": "user", "content": prompt}],
                              "stream": False},
                        timeout=OLLAMA_TIMEOUT_S)
                    if resp.status_code != 200:
                        if _model_error_snippet(
                                resp.status_code, resp) is not None:
                            continue  # not pulled — next candidate
                        break  # a real failure — same as before
                    reply = ((resp.json().get("message") or {})
                             .get("content") or "").strip()
                    reply = self._guard_reply(reply, "Ollama",
                                              writing=writing)
                    if reply:
                        # v7.3: unconditional (see the Groq
                        # site above).
                        self._remember_working_model(
                            "ollama", _cand, "Ollama")
                        _lb("BRAIN", "Ollama answered (plain chat)")
                        return reply
                    break  # guard rejected it — provider failure
        except Exception:
            pass
        return None

    def _plain_chat_writing(self, prompt):
        """_plain_chat for WRITTEN output (v5.7.1): the text is
        saved/posted for the owner to read — an email draft via
        skillfiles.draft_email_save — so the spoken two-line
        length cap must not trim it. Script + CoT guards still
        apply inside _guard_reply. Matches the one-argument
        write_fn shape skillfiles expects."""
        return self._plain_chat(prompt, writing=True)

    def _agent_ollama(self, text):
        """Tool-using loop against a local Ollama server (/api/chat).

        v4.8: a server that isn't there is NOT a failure — Ollama
        is the optional local last resort and the provider cache
        owns that story — so the reachability probe stays silent.
        A server that IS there but refuses the chat call is a real
        failure and is logged like every other provider's.

        v6.7: the candidate walk (see OLLAMA_TIMEOUT_S) — the
        configured model tries first, then config ollama_models;
        a name Ollama has not pulled answers 404 ("model …
        not found") and the walk moves to the next candidate
        inside THIS call; the model that answers is remembered
        as the default. Every candidate gets the generous local
        timeout: Ollama is the last provider standing between
        the owner and the fallback line."""
        try:
            import requests
        except Exception:
            return None
        # v7.9 (item E): every attempt leaves its outcome
        # readable — _ollama_last_error names why this
        # attempt failed, so the fallback outcome lines in
        # _agent_reply can say it. The probe's silence is
        # unchanged (a server that isn't there is still not
        # a provider failure); the WHY is simply no longer
        # thrown away.
        try:
            self._ollama_last_error = None
        except Exception:
            pass
        url = self.cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
        try:
            if requests.get(url + "/api/tags",
                            timeout=1.5).status_code != 200:
                self._ollama_last_error = (
                    f"not reachable at {url}")
                return None
        except Exception:
            try:
                self._ollama_last_error = (
                    f"not reachable at {url}")
            except Exception:
                pass
            return None
        candidates = self._model_candidates("ollama") or [
            self.cfg.get("ollama_model", "llama3.1")]
        # v7.7 (item I): names already proven unpulled this
        # session are not retried (see _dead_models); when
        # every name is known-unpulled the call ends at
        # once — the failure line fired when they died.
        try:
            _dead = self._dead_models
        except Exception:
            _dead = ()
        if _dead:
            _live = [c for c in candidates
                     if ("ollama", _model_key(c)) not in _dead]
            if candidates and not _live:
                return None
            candidates = _live or candidates
        # v7.9 (item B): the chat safety net caps the
        # attempt at the first live candidate — ONE bounded
        # attempt, never the whole local walk. The knob is
        # set only around that call (see _ollama_chat_net);
        # everywhere else it is None and the walk is whole.
        try:
            _maxc = getattr(self, "_ollama_max_candidates",
                            None)
        except Exception:
            _maxc = None
        if _maxc:
            candidates = candidates[:max(1, int(_maxc))]
        last_miss = None
        for idx, cand in enumerate(candidates):
            reply = self._agent_ollama_impl(text, url, cand)
            if reply is _MODEL_MISS:
                last_miss = cand
                # v7.7 (item I): this name is dead for the
                # rest of the session — no later turn pays
                # for its 404 again.
                try:
                    self._dead_models.add(
                        ("ollama", _model_key(cand)))
                except Exception:
                    pass
                if idx + 1 < len(candidates):
                    _lb("BRAIN",
                        f"[brain] Ollama model {cand} is not "
                        f"pulled — trying {candidates[idx + 1]}")
                    log.info("[brain] Ollama model %s not "
                             "pulled; trying %s",
                             cand, candidates[idx + 1])
                continue
            if reply:
                # v7.3: unconditional (see _plain_chat).
                self._remember_working_model(
                    "ollama", cand, "Ollama")
                return reply
            # A real failure — the impl logged it; v7.9
            # keeps its reason for the fallback outcome
            # line (item E: the attempt's HTTP status must
            # be visible, once, in the log).
            try:
                self._ollama_last_error = \
                    self._last_fail_reason("Ollama")
            except Exception:
                pass
            return None
        # Every candidate was a name Ollama has not pulled:
        # ONE failure line for the whole walk.
        _reason = (
            f"no working model — tried {', '.join(candidates)} "
            f"(last not pulled: {last_miss}) — pull one with "
            f"SETUP-OLLAMA.txt")
        self._brain_fail(
            "Ollama", _reason, provider="ollama")
        try:
            self._ollama_last_error = _reason
        except Exception:
            pass
        return None

    def _agent_ollama_impl(self, text, url, model):
        """One Ollama model attempt (v6.7 split of _agent_ollama).

        Returns the reply, None on a real provider failure
        (already logged via _brain_fail), or _MODEL_MISS when
        Ollama answered with a dead model name (404 "not
        found") — the walk owns that story and logs a single
        failure only if every candidate misses. All guards
        (language/script/CoT/markup/length) apply via
        _guard_reply exactly as for the cloud providers."""
        try:
            import requests
            messages = ([{"role": "system", "content": self._system_prompt()}]
                        + self.chat_history[-8:]
                        + [{"role": "user", "content": text}])
            # v7.9 (item B): the chat safety net's bounded
            # per-call budget when the caller set the
            # override — otherwise the generous local
            # timeout, exactly as before.
            _timeout = getattr(
                self, "_ollama_timeout_override", None) \
                or OLLAMA_TIMEOUT_S
            _tools_ran_here = 0
            _continued = False
            for _round in range(3):
                resp = requests.post(
                    url + "/api/chat",
                    json={"model": model, "messages": messages,
                          "tools": AGENT_TOOLS, "stream": False},
                    timeout=_timeout)
                if resp.status_code != 200:
                    if _model_error_snippet(resp.status_code,
                                            resp) is not None:
                        return _MODEL_MISS
                    self._brain_fail(
                        "Ollama",
                        f"HTTP {resp.status_code} — "
                        f"{_err_snippet(resp)}",
                        provider="ollama",
                        http_status=resp.status_code)
                    return None
                msg = resp.json().get("message") or {}
                calls = msg.get("tool_calls") or []
                if not calls:
                    reply = (msg.get("content") or "").strip()
                    # v7.7 (item H): partial completion —
                    # same continuation as the cloud loop
                    # (see _agent_openai_compatible_impl).
                    if _tools_ran_here > 0 and not _continued \
                            and _looks_like_chain_request(
                            _owner_utterance(text)):
                        _continued = True
                        try:
                            self._turn_partial_after_continuation \
                                = True
                        except Exception:
                            pass
                        messages.append({
                            "role": "assistant",
                            "content": msg.get("content", "")})
                        messages.append({
                            "role": "user",
                            "content":
                                _CHAIN_CONTINUATION.strip()})
                        continue
                    reply = self._guard_reply(reply, "Ollama", text)
                    if reply:
                        self._remember_chat(text, reply)
                    return reply or None
                messages.append({"role": "assistant",
                                 "content": msg.get("content", ""),
                                 "tool_calls": calls})
                for call in calls:
                    fn = call.get("function") or {}
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    result = self._run_tool(fn.get("name", ""), args)
                    _tools_ran_here += 1
                    if _continued:
                        try:
                            self._turn_partial_after_continuation \
                                = False
                        except Exception:
                            pass
                    messages.append({"role": "tool", "content": result})
            # Tool rounds used up — ask once more, without tools.
            resp = requests.post(
                url + "/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=_timeout)
            if resp.status_code != 200:
                if _model_error_snippet(resp.status_code,
                                        resp) is not None:
                    return _MODEL_MISS
                self._brain_fail(
                    "Ollama",
                    f"HTTP {resp.status_code} — {_err_snippet(resp)}",
                    provider="ollama", http_status=resp.status_code)
                return None
            reply = ((resp.json().get("message") or {}).get("content")
                     or "").strip()
            reply = self._guard_reply(reply, "Ollama", text)
            if reply:
                self._remember_chat(text, reply)
            return reply or None
        except Exception as exc:
            self._brain_fail(
                "Ollama", f"{type(exc).__name__}: {exc}"[:160],
                provider="ollama")
            return None

    def _agent_openai_compatible(self, text, base_url, key, model,
                                 label="OpenAI-compatible",
                                 provider=None, timeout=PROVIDER_TIMEOUT_S,
                                 tier=None, call_budgets=None):
        """v6.0 timing wrapper: record the attempt's latency
        + outcome in perflevel under the provider's name
        (the ⚡ Level and the adaptive provider order read
        it), then run the real loop.

        v6.5: for a walk provider (Gemini / Groq / OpenRouter)
        this walks the model candidate list — a dead model
        name (the impl's _MODEL_MISS) moves to the next
        candidate inside THIS call; the candidate that answers
        is remembered as the provider's default. Any other
        failure stops the walk at once (it is a provider
        failure, already logged by the impl).

        v7.4: tier= is the smart-routing tier ("power" /
        "instant" / None — see _tier_for). A power call heads
        its walk with the power model and remembers its
        winner under groq_power_model. An INSTANT-tier answer
        to an ACTION request that trips the act-don't-narrate
        guard — or fails the language guard outright — gets
        its ONE retry from the POWER model instead of the
        same model (exactly one retry either way; the honest
        fallback after it is unchanged). tier=None (routing
        off) reproduces v7.3 exactly."""
        _t0 = time.time()
        _tools_before = self._tool_run_count
        _lang_trips_before = getattr(self, "_guard_lang_trips", 0)
        # v7.7 (item H): a fresh call starts with no
        # partial-completion mark (the impl sets it when
        # its continuation fires — see below).
        try:
            self._turn_partial_after_continuation = False
        except Exception:
            pass
        _head = None
        _remember_key = None
        if tier == "power":
            _head = self._power_model()
            _remember_key = "groq_power_model"
        _can_escalate = tier is not None and tier != "power"
        try:
            reply = self._agent_openai_walk(
                text, base_url, key, model, label=label,
                provider=provider, timeout=timeout, head=_head,
                remember_key=_remember_key, tier=tier,
                call_budgets=call_budgets)
        except Exception:
            reply = None
        # v6.8 ACT, DON'T NARRATE: the turn ended with ZERO
        # tool calls, the request asked for an action, and
        # the reply is a bare capability claim ("আমি রিপ্লাই
        # দিতে পারি।") — retry ONCE with the stern note
        # appended; the retry's tools execute normally. A
        # retry that answers honestly without claiming (it
        # names the blocker) is accepted; a retry that STILL
        # only narrates is replaced by the honest line — the
        # false claim never reaches his ears. Ability
        # questions never reach here (_looks_like_action_
        # request excludes them).
        if reply and self._tool_run_count == _tools_before \
                and _looks_like_action_request(text) \
                and _is_capability_claim(reply):
            _lb("BRAIN",
                "[brain] reply only CLAIMED the action (no "
                "tool ran) — retrying with a direct "
                "instruction")
            log.warning("[brain] capability claim with no "
                        "action — one stern retry")
            # v7.4: an instant-tier first attempt escalates
            # — the ONE stern retry goes to the POWER model;
            # a power attempt (or routing off) retries with
            # its own head, exactly as v7.3.
            _r_head, _r_key, _r_tier = _head, _remember_key, tier
            if _can_escalate:
                _r_head = self._power_model()
                _r_key = "groq_power_model"
                _r_tier = "power"
                _lb("BRAIN",
                    "[brain] escalating the retry to the "
                    f"power model ({_r_head})")
                log.warning("[brain] narrate retry escalated "
                            "to the power model %s", _r_head)
            try:
                reply2 = self._agent_openai_walk(
                    text + _NARRATE_STERN, base_url, key, model,
                    label=label, provider=provider,
                    timeout=timeout, head=_r_head,
                    remember_key=_r_key, tier=_r_tier,
                    call_budgets=call_budgets)
            except Exception:
                reply2 = None
            if reply2 and self._tool_run_count != _tools_before:
                reply = reply2
            elif reply2 and not _is_capability_claim(reply2):
                reply = reply2
            else:
                reply = self._loc(
                    "Sorry sir, I could not do that just now.",
                    "দুঃখিত sir, কাজটা এখন করে উঠতে পারলাম না।")
        elif not reply and _can_escalate \
                and self._tool_run_count == _tools_before \
                and getattr(self, "_guard_lang_trips", 0) \
                > _lang_trips_before \
                and _looks_like_action_request(text):
            # v7.4 LANGUAGE ESCALATION: the instant model's
            # answer to an ACTION request was rejected by the
            # language guard (a provider failure — no reply,
            # and no tool ran, so a retry cannot double-
            # execute anything). The ONE retry goes to the
            # POWER model; if it also fails, the normal
            # cascade (Ollama → the honest Bengali fallback)
            # follows, exactly as before.
            _p_head = self._power_model()
            _lb("BRAIN",
                "[brain] the instant model's reply failed "
                "the language guard — escalating to the "
                f"power model ({_p_head})")
            log.warning("[brain] language-guard escalation "
                        "to the power model %s", _p_head)
            try:
                reply2 = self._agent_openai_walk(
                    text, base_url, key, model, label=label,
                    provider=provider, timeout=timeout,
                    head=_p_head,
                    remember_key="groq_power_model",
                    tier="power",
                    call_budgets=call_budgets)
            except Exception:
                reply2 = None
            if reply2:
                reply = reply2
        # v7.7 (item H): PARTIAL COMPLETION, the endgame.
        # The impl's continuation fired (a multi-step
        # request, at least one tool ran, the model stopped
        # to narrate) and STILL no further tool ran — the
        # remaining steps were never executed, so a reply
        # reporting the job as done would be false. Unless
        # the reply honestly names a blocker (kept
        # verbatim), it is replaced by the honest partial
        # line: the first step happened, the rest did not.
        if reply and self._tool_run_count > _tools_before \
                and getattr(
                    self, "_turn_partial_after_continuation",
                    False) \
                and _looks_like_chain_request(text) \
                and not _reply_names_blocker(reply):
            _lb("BRAIN",
                "[brain] multi-step job only partly done — "
                "saying so instead of reporting it finished")
            log.warning("[brain] partial completion: the "
                        "continuation produced no further "
                        "tool — honest partial line")
            reply = self._loc(
                "Sorry sir, the first step is done but I "
                "could not finish the rest.",
                "দুঃখিত sir, প্রথম ধাপটা হয়েছে — বাকিটা "
                "করে উঠতে পারলাম না।")
        try:
            import perflevel
            perflevel.record_provider(
                provider or label, time.time() - _t0,
                bool(reply))
        except Exception:
            pass
        return reply

    def _agent_openai_walk(self, text, base_url, key, model,
                           label="OpenAI-compatible",
                           provider=None, timeout=PROVIDER_TIMEOUT_S,
                           head=None, remember_key=None, tier=None,
                           call_budgets=None):
        """One provider call, with the v6.5 candidate walk for
        walk providers. Non-walk providers (FreeLLMAPI, OpenAI)
        keep the exact single-model behaviour.

        v7.4: head= heads the walk with the smart-routing
        tier's model; remember_key= is where the winner is
        remembered (the power tier's own key); tier= rides
        along to the remember for the status line."""
        if provider not in _MODEL_WALK_PROVIDERS:
            # call_budgets is passed ONLY when armed — an
            # unarmed call keeps the impl's exact v7.8
            # signature (suites stub the impl with it).
            _extra = {"call_budgets": call_budgets} \
                if call_budgets else {}
            _direct = self._agent_openai_compatible_impl(
                text, base_url, key, model, label=label,
                provider=provider, timeout=timeout, **_extra)
            if _direct is _MODEL_SLOW:
                # v7.9 (item I): a non-walk provider has no
                # next candidate — the slowness is this
                # call's failure (the impl already logged
                # the move-on line); the turn's fallbacks
                # are the caller's business.
                self._brain_fail(
                    label, f"model {model} too slow",
                    provider=provider)
                return None
            return _direct
        candidates = self._model_candidates(
            provider, head_override=head) or [model]
        # v7.7 (item I): filter out this session's PROVEN
        # dead models before walking (see _dead_models in
        # __init__). When every candidate is already known
        # dead, the provider reports unavailable at once —
        # zero network, zero serial hop.
        try:
            _dead = self._dead_models
        except Exception:
            _dead = ()
        if _dead:
            _live = [c for c in candidates
                     if (provider, _model_key(c)) not in _dead]
            if candidates and not _live:
                self._brain_fail(
                    label,
                    f"every known model is gone this "
                    f"session — not retrying "
                    f"{', '.join(candidates)}",
                    provider=provider)
                return None
            candidates = _live or candidates
        # v7.9 (item A): the same filter drops models in
        # their 429 cooldown — a parked model is never
        # re-asked inside its 60 s, on any walk. When the
        # cooldown alone empties the walk, the provider
        # reports the RATE LIMIT (status 429, so the
        # turn's cause is truthful), never a dead key.
        _cooling = [c for c in candidates
                    if self._model_in_cooldown(provider, c)]
        if _cooling:
            _live = [c for c in candidates
                     if c not in _cooling]
            if candidates and not _live:
                self._brain_fail(
                    label,
                    f"every model is rate-limited "
                    f"(parked) — not retrying "
                    f"{', '.join(candidates)}",
                    provider=provider, http_status=429)
                return None
            candidates = _live or candidates
        last_miss = None
        last_ratelimit = None
        last_slow = None
        _walk_start = time.monotonic()
        for idx, cand in enumerate(candidates):
            # v6.6: the walk has ONE total budget across its
            # candidates (MODEL_WALK_BUDGET_S), not a fresh
            # provider cap per name — each candidate gets the
            # time LEFT in the budget, and when the budget is
            # spent the provider fails over at once (four slow
            # dead names must not stack into ~40 s).
            _remaining = MODEL_WALK_BUDGET_S - (
                time.monotonic() - _walk_start)
            if idx and _remaining <= 0:
                self._brain_fail(
                    label,
                    f"model walk budget spent "
                    f"({MODEL_WALK_BUDGET_S:.0f}s) — tried "
                    f"{', '.join(candidates[:idx])}",
                    provider=provider)
                return None
            _extra = {"call_budgets": call_budgets} \
                if call_budgets else {}
            reply = self._agent_openai_compatible_impl(
                text, base_url, key, cand, label=label,
                provider=provider,
                timeout=min(timeout, max(1.0, _remaining)),
                model_walk=True, **_extra)
            if reply is _MODEL_MISS:
                last_miss = cand
                # v7.7 (item I): this name is dead for the
                # rest of the session — no later turn pays
                # for its 404 again.
                try:
                    self._dead_models.add(
                        (provider, _model_key(cand)))
                except Exception:
                    pass
                if idx + 1 < len(candidates):
                    _lb("BRAIN",
                        f"[brain] {label} model {cand} is gone "
                        f"— trying {candidates[idx + 1]}")
                    log.info("[brain] %s model %s gone; trying "
                             "%s", label, cand,
                             candidates[idx + 1])
                continue
            if reply is _MODEL_RATELIMITED:
                # v7.9 (item A): the impl parked this model
                # for its 429 cooldown and logged the park —
                # advance exactly like a miss, but the model
                # is NOT dead and is never remembered as
                # gone; it rejoins the walk when the
                # cooldown lapses.
                last_ratelimit = cand
                continue
            if reply is _MODEL_SLOW:
                # v7.9 (item I): the candidate blew the
                # agent path's per-call budget (the impl
                # logged the move-on line) — advance like
                # a miss, but park nothing: a slow model
                # may answer fine next turn, and the
                # budget re-applies then anyway.
                last_slow = cand
                continue
            if reply:
                # v7.3: unconditional — a head answer records
                # the working model in memory too (the persist
                # inside still only happens on a change).
                # v7.4: the tier's own remember key + tier
                # ride along (both None on the v7.3 paths).
                self._remember_working_model(
                    provider, cand, label,
                    single_key=remember_key, tier=tier)
                return reply
            return None  # a real provider failure — impl logged it
        # Every candidate was a dead name: ONE failure line.
        # v7.9: a walk that ended PURELY on rate limits says
        # so instead, with the 429 as its status — the
        # turn's cause set (item D) and the log both name
        # the limit, not a dead model or a bad key.
        if last_miss is None and last_ratelimit is not None:
            self._brain_fail(
                label,
                f"rate limit reached on every model — "
                f"tried {', '.join(candidates)}",
                provider=provider, http_status=429)
            return None
        if last_miss is None and last_ratelimit is None \
                and last_slow is not None:
            self._brain_fail(
                label,
                f"every model too slow — "
                f"tried {', '.join(candidates)}",
                provider=provider)
            return None
        self._brain_fail(
            label,
            f"no working model — tried "
            f"{', '.join(candidates)} "
            f"(last dead: {last_miss})",
            provider=provider)
        return None

    def _agent_openai_compatible_impl(self, text, base_url, key,
                                      model,
                                      label="OpenAI-compatible",
                                      provider=None, timeout=PROVIDER_TIMEOUT_S,
                                      model_walk=False,
                                      call_budgets=None):
        """Tool-using loop against an OpenAI-compatible API (Groq/OpenAI).

        v4.8: EVERY failure is logged via _brain_fail (one logbook
        ERROR line: provider + HTTP status/error code, or the
        exception). The pre-v4.8 version returned None in total
        silence — a rejected key looked exactly like no key.

        v6.5: with model_walk=True (the candidate walk is
        driving), a dead-model-name failure returns _MODEL_MISS
        WITHOUT logging — the walk owns that story and logs a
        single failure only if every candidate is dead.

        v7.9: a 429 inside a walk returns _MODEL_RATELIMITED
        after parking the model for its cooldown (see
        _park_model_ratelimit) — the walk advances, on every
        round including post-tool continuations; a rate limit
        is never this call's terminal failure.

        v7.9 (item I): call_budgets=(first_s, later_s) —
        the AGENT path's per-call caps — bounds every post
        this impl makes (first call of the turn at
        first_s, later calls at later_s; the tighter of
        the passed timeout and the cap wins). A post that
        times out under armed budgets returns _MODEL_SLOW
        so the walk advances instead of the turn dying;
        unarmed (chat) calls keep the v7.8 behaviour
        exactly. One step's independent tool calls run
        concurrently (see _tools_parallel_ok).
        """
        try:
            import requests
            headers = {"Authorization": f"Bearer {key}",
                       "Content-Type": "application/json"}
            messages = ([{"role": "system", "content": self._system_prompt()}]
                        + self.chat_history[-8:]
                        + [{"role": "user", "content": text}])
            _tools_ran_here = 0
            _continued = False

            def _post(body, round_idx=0):
                """One POST for this call. v7.9: inside a
                model walk the candidate gets ONE post — a
                429 must advance the walk at once (the walk
                itself is the retry now), and the v6.13
                same-model backoff would only stack sleeps
                inside the turn's budget. Outside a walk
                the backoff runs exactly as v6.13 shipped
                it (its suites pin that path).

                v7.9 (item I): under call_budgets the post
                is capped (first call of the turn tighter)
                and a timeout returns _MODEL_SLOW — the
                walk advances; a slow candidate never
                holds a work turn hostage."""
                _eff = timeout
                if call_budgets:
                    _cap = call_budgets[0] if round_idx == 0 \
                        else call_budgets[1]
                    _eff = min(timeout, _cap)
                try:
                    if model_walk:
                        return requests.post(
                            base_url + "/chat/completions",
                            headers=headers, json=body,
                            timeout=_eff)
                    return _post_with_rl_retry(
                        requests.post,
                        base_url + "/chat/completions",
                        headers=headers, json_body=body,
                        timeout_s=_eff,
                        deadline=time.monotonic() + _eff)
                except requests.Timeout:
                    if not call_budgets:
                        raise
                    _lb("BRAIN",
                        f"[brain] {label} model {model} too "
                        f"slow (>{_eff:.0f}s) — moving on")
                    log.info("[brain] %s model %s too slow "
                             "(>%ss) — moving on",
                             label, model, _eff)
                    return _MODEL_SLOW

            def _error_out(resp):
                """The non-200 handling both post sites
                share. Returns the walk sentinel the caller
                must return (_MODEL_MISS /
                _MODEL_RATELIMITED), or None after recording
                a terminal provider failure — the caller
                then returns None itself. v7.9: a 429 inside
                a walk parks this model for its cooldown
                and advances; it is never a terminal
                failure while candidates remain."""
                if model_walk and resp.status_code == 429:
                    self._park_model_ratelimit(
                        provider, model, label)
                    return _MODEL_RATELIMITED
                if model_walk and _model_error_snippet(
                        resp.status_code, resp) is not None:
                    return _MODEL_MISS
                self._brain_fail(
                    label,
                    f"HTTP {resp.status_code} — "
                    f"{_err_snippet(resp)}",
                    provider=provider,
                    http_status=resp.status_code)
                return None

            for _round in range(3):
                resp = _post({"model": model,
                              "messages": messages,
                              "tools": AGENT_TOOLS,
                              "tool_choice": "auto",
                              "max_tokens": 300}, _round)
                if resp is _MODEL_SLOW:
                    return _MODEL_SLOW
                if resp.status_code != 200:
                    _out = _error_out(resp)
                    if _out is not None:
                        return _out
                    return None
                msg = resp.json()["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                if not calls:
                    reply = (msg.get("content") or "").strip()
                    # v7.7 (item H): PARTIAL COMPLETION — the
                    # model has already run a tool this turn
                    # and now stops to narrate, but the
                    # request has more steps. Do not let the
                    # turn end: hand the conversation back
                    # ONCE with the continuation note and let
                    # it call the remaining tools. The flag
                    # tells the wrapper the continuation was
                    # spent; a tool executed after it clears
                    # the flag again (progress resumed).
                    if _tools_ran_here > 0 and not _continued \
                            and _looks_like_chain_request(
                            _owner_utterance(text)):
                        _continued = True
                        try:
                            self._turn_partial_after_continuation \
                                = True
                        except Exception:
                            pass
                        log.info("[brain] multi-step request "
                                 "stopped after %d tool(s) — "
                                 "continuing the turn",
                                 _tools_ran_here)
                        _lb("BRAIN", "[brain] the job has "
                                     "more steps — continuing "
                                     "instead of narrating")
                        messages.append(msg)
                        messages.append({
                            "role": "user",
                            "content":
                                _CHAIN_CONTINUATION.strip()})
                        continue
                    reply = self._guard_reply(reply, label, text)
                    if reply:
                        self._remember_chat(text, reply)
                    return reply or None
                messages.append(msg)
                _parsed = []
                for call in calls:
                    fn = call.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments")
                                          or "{}")
                    except Exception:
                        args = {}
                    _parsed.append(
                        (call, fn.get("name", ""), args))
                _results = None
                if _tools_parallel_ok(
                        [n for _c, n, _a in _parsed]):
                    # v7.9 (item I.2): independent calls in
                    # one step run CONCURRENTLY; results
                    # are collected in call order, so the
                    # conversation the model sees is
                    # identical to the serial run's.
                    _lb("BRAIN",
                        f"[brain] running {len(_parsed)} "
                        "tools in parallel")
                    log.info("[brain] running %d tools in "
                             "parallel", len(_parsed))
                    try:
                        from concurrent.futures import \
                            ThreadPoolExecutor
                        with ThreadPoolExecutor(
                                max_workers=min(
                                    4, len(_parsed))) as _ex:
                            _results = list(_ex.map(
                                lambda p: self._run_tool(
                                    p[1], p[2]), _parsed))
                    except Exception:
                        _results = None
                if _results is None:
                    _results = [self._run_tool(n, a)
                                for _c, n, a in _parsed]
                for (call, _n, _a), result in zip(_parsed,
                                                  _results):
                    _tools_ran_here += 1
                    if _continued:
                        # Progress after the continuation:
                        # the partial flag clears (item H).
                        try:
                            self._turn_partial_after_continuation \
                                = False
                        except Exception:
                            pass
                    messages.append({"role": "tool",
                                     "tool_call_id": call.get("id", ""),
                                     "content": result})
            # Tool rounds used up — ask once more, without tools.
            resp = _post({"model": model, "messages": messages,
                          "max_tokens": 300}, 3)
            if resp is _MODEL_SLOW:
                return _MODEL_SLOW
            if resp.status_code != 200:
                _out = _error_out(resp)
                if _out is not None:
                    return _out
                return None
            reply = (resp.json()["choices"][0]["message"].get("content")
                     or "").strip()
            reply = self._guard_reply(reply, label, text)
            if reply:
                self._remember_chat(text, reply)
            return reply or None
        except Exception as exc:
            self._brain_fail(
                label, f"{type(exc).__name__}: {exc}"[:160],
                provider=provider)
            return None

def _clean(s):
    return re.sub(r"\s+", " ", s).strip(" .!?")
