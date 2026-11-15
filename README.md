# 🤖 Nalox — a personal JARVIS-style voice assistant

Nalox is a voice assistant for **one person's Windows laptop** (its
owner, Arjun). It listens for the wake word **"Nalox"**, understands
**English, Bengali and Hindi**, speaks back in the owner's own
ElevenLabs voice, and can run the whole laptop by voice: apps,
browser, YouTube, files, phone, messages — plus a fullscreen
**Command Center** dashboard that opens on **"Wake up Nalox"**.

> ⚠️ A fully OFF laptop cannot listen — no program can. With the
> laptop ON (even locked or with the screen off), Nalox is always
> listening.

---

## ✨ What it does

- **Wake word + follow-up listening** — say "Nalox", then your
  command; one-breath commands ("Nalox, YouTube খোলো") work too,
  and a short follow-up window keeps listening without the wake
  word.
- **Command Center** — *"Wake up Nalox"* (or any start of the app)
  opens a fullscreen dashboard: a blue particle orb with the
  owner's logo at its heart, a staged opening ceremony, the ⚡
  Nalox Level (measured speed) big in the header, a SYSTEM panel
  (CPU/RAM/disk/battery, mic, brain, phone, commands this session,
  uptime) and the live chat. ⚙ Settings and 📋 Log live on its top
  bar.
- **A real agent brain** — a provider chain (a local FreeLLMAPI
  router first, then Claude / OpenRouter / Gemini / Groq / OpenAI /
  Ollama) with tools: open apps and sites, search, YouTube play +
  comment replies, Gmail, calendar, reminders, scheduled tasks,
  document memory, PC chores (empty recycle bin, quick clean),
  chained commands ("build a website for X", lead generation).
- **Phone control** — the companion **Nalox Phone** Android app
  pairs over the LAN (link sent via Telegram): "call my mother",
  "open YouTube on my phone", battery, ring — by voice. Telegram
  bridge (@Naloxbot) also takes typed/spoken commands from the
  phone.
- **Learns preferences** — "call me Sir", "বাংলায় কথা বলো" are
  remembered for life (prefs + memory store). Custom voice
  commands can be taught from the Command Center ("⭐ Make your
  own command") — no coding.
- **Never hangs** — all speech-to-text runs in a separate worker
  process with hard deadlines (wake 4 s, command 12 s); a wedged
  decode is killed with its process and restarted automatically.
- **Always on** — closing the window only hides it; a tray icon
  and a supervisor relaunch it after any crash. Deliberate exit
  lives only in the tray/HUD Exit buttons. Voice "stop" means
  *standby* (stop speaking, keep listening) — never exit.
- **Self-updating** — Nalox checks its private GitHub repo at
  boot and every 6 hours and updates itself (see below).

## 🚀 Install (Windows)

Requires **Python 3.12** (3.11/3.13 also OK; 3.14+ is refused —
some wheels don't exist yet).

1. Unzip anywhere, run **INSTALL.bat** once. It builds `.venv`,
   installs `requirements.txt`, creates the Desktop/Start-Menu
   shortcuts and the login autostart (via `start_nalox.vbs`,
   fully silent — no console window ever).
2. Nalox starts at every Windows login and greets you. Say
   **"Nalox"** to wake it; say **"Wake up Nalox"** for the
   Command Center.

## ⚙️ Settings & keys

Everything is configured in the app: **Command Center → ⚙
Settings** (or the app window's Settings button). Nothing needs
hand-editing `config.json`. Keys are pasted **locally, only into
Settings** — never into chat or anywhere else. Highlights:

- **Voice** — ElevenLabs API key + voice ID (the owner's voice),
  Bengali voice chooser (Male/Female), voice speed, cloud hearing
  toggle.
- **Connections** — FreeLLMAPI (local router), Claude, OpenRouter,
  Gemini (free key from Google AI Studio), Groq, OpenAI, Telegram
  bot, Gmail app password, YouTube OAuth (see
  `SETUP-YOUTUBE.txt`), OpenWeather — each with a live Test
  button.
- **Microphone** — picker + test.
- **Phone** — send the pairing link, contacts (name=number),
  ADB-over-Wi-Fi fallback pairing.
- **General** — "Call me" name, the wake reply line, greeting,
  autostart, mode, document folder, 🩺 Doctor self-check.
- **Access & Control** — full PC control toggle (ON by the
  owner's standing decision: no confirmation prompts), YouTube
  replies, email sending.
- **Updates** — GitHub repo + read-only token + auto-update
  switch + "Check for updates now" (see below).

## 📱 The phone app

`phone-app/nalox-phone.apk` — a small Android app (no Play Store).
Pairing: ask Nalox *"send me the phone link"*, open the Telegram
link on the phone, Install, then Connect once. After that, voice
commands run on the phone over the local network (the PC's
internet is the phone's hotspot — pairing uses the address the
phone shows; see Settings → Phone for the full guide).

## 🔄 Self-update (from v6.2)

Nalox updates itself from the owner's **private GitHub repo:
[github.com/arjun408408/nalox](https://github.com/arjun408408/nalox)**
(the account is `arjun408408`; the repo is private and holds the
full source, so any AI can be handed the project from there).

1. **Settings → Updates** comes prefilled with the repo
   (`arjun408408/nalox`); the owner only pastes a **read-only
   fine-grained token** for that repo (locally, never in chat).
2. At boot (~60 s in) and every 6 hours, Nalox reads the repo's
   `version.txt` via the GitHub API with that token. If it's
   newer, it downloads the zipball and applies it exactly like
   UPDATE.bat did — code + assets + phone-app + platform-tools —
   **never** `config.json`, `custom_commands.json`, `prefs.json`,
   logs, flags/locks or any memory store.
3. It then restarts via the supervisor and announces once:
   *"I have updated myself to version X.Y, sir."*

**Release flow:** Muse (or any AI working on the project)
commits and pushes the source to `arjun408408/nalox` with the
release's `version.txt` bumped — that push IS the release; every
running Nalox picks it up on its next check. No UPDATE.bat
clicks any more. (UPDATE.bat still exists in this repo for
manual/offline packs.)

## 🛟 When something looks wrong

Open **📋 Log** (Command Center top bar): `nalox_page.html` shows
the whole conversation, the brain/voice/mic status header and
every error in plain sight; `nalox_log.txt` is the same in text,
and `nalox_fault.log` holds native-crash evidence.

## 📂 Layout

See **FOR-AI.md** for the full architecture map (file by file),
the test suites, and the owner's standing decisions — the doc any
future maintainer (human or AI) should read first.
