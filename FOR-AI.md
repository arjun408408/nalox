# FOR-AI.md — continuing the Nalox project

You are picking up **Nalox**, a personal JARVIS-style voice
assistant built for ONE user (Arjun) and his Windows laptop.
This doc is the handoff: architecture, how to test, how to
ship an update, and the owner's standing decisions — which
override your defaults whenever they conflict.

## The owner's standing decisions (do not relitigate)

1. **Full PC control, no confirmation prompts** (`full_control`
   default ON, his explicit decision). Settings keeps the toggle.
2. **STOP = STANDBY.** A voice/Telegram "stop" stops speaking
   and keeps listening — it must NEVER exit the process.
   Deliberate exit is tray/HUD clicks only (exit code 42 +
   `exit_requested.flag`).
3. **Wake line is "Yes Sir, I'm here."** (config `wake_line`).
   Nalox addresses him as **"Sir"** (learned preference,
   `prefs.json` + config mirror; Settings → "Call me").
4. **Trilingual: English (base/primary) + Bengali + Hindi.**
   Nothing else exists in Nalox's world — the language lock
   (`ALLOWED_LANGS = {en, bn, hi}`) is deliberate.
   **Replies follow the learned language preference — and
   with pref `bn` they are Bengali ONLY** (v6.4, his explicit
   escalation: he does not want to speak English with Nalox).
   Understanding stays trilingual; the reply side is enforced
   by the language guard in `brain._guard_reply`
   (`_reply_wrong_language`: a predominantly-Latin reply
   under a bn/hi preference is a provider failure and the
   cascade moves on; if all providers fail it, the honest
   fallback speaks the preferred language). Writing tasks
   (`writing=True`) are exempt — text he asks to be written
   in English for others stays English.
5. **Answer FAST and answer EVERYTHING heard, best-effort.**
   Even a wrong hearing beats silence. NEVER silently drop
   speech — in particular, never gate delivery on Whisper's
   `no_speech_prob` (it saturates at 1.00 on genuine Bengali;
   that bug ate his real commands in v4.3 and was removed in
   v4.5). `is_garbage()` is the only content filter.
6. **Voice: ONLY his ElevenLabs voice** (plain). The robot
   voice effect was rejected — do not re-enable it. Bengali
   voice is MALE (bn-BD-PradeepNeural default). Fallback chain
   when ElevenLabs fails: edge-tts → pyttsx3 → PowerShell SAPI.
7. **Always-on.** Window close = hide only; tray icon;
   supervisor relaunches on crash/kill; single-instance via an
   OS-held lock (never trust a PID file — see v6.0 notes in
   `nalox.py`).
8. **Replies SHORT** (~2 lines max) — except writing tasks
   (emails, replies, documents), which are exempt.
9. **Pronunciation tolerance is first-class** — fuzzy /
   sounds-like matching everywhere (canonical test:
   "mellox close common centre" → close the Command Center).
10. **Opened apps come to the FRONT; no persistent
    always-on-top** (raises are brief, ~1 s, then released).
11. **Keys are pasted by the owner LOCALLY into Settings —
    NEVER in chat.** Never ask for, accept, log or repeat a
    key from chat. If one appears in chat, tell him to revoke
    it and make a fresh one for Settings.
12. **No news at startup, no auto-YouTube at startup.**
    Greeting only at boot; the digest is on demand.
13. **The name is NALOX.** "Jarvis" is only his example of the
    style/persona. The persona model is JARVIS (polite,
    competent, "sir"), not a generic chatbot.
14. **Delivery bar:** investigate deeply FIRST, self-test
    thoroughly, deliver ONE version — no patch treadmill.

## Surfaces (v6.2 rules)

- **Every start lands on the Command Center** (autostart,
  manual launch, post-update restart). The plain app window
  is built withdrawn and no start path shows it.
- **"Wake up Nalox" opens ONLY the Command Center**, from any
  state. `nalox._show_for_wake_up()` is dashboard-only; the
  plain window is never a substitute on that path, and
  `_open_dashboard()` hides the plain window when the Center
  opens over it.
- The plain window still exists behind the **tray menu**
  ("Open Nalox") for diagnostics. The Command Center's top
  bar has ⚙ Settings + 📋 Log buttons wired to the HUD's own
  handlers (`Hud._on_settings` / `Hud._on_log`), so nothing
  the owner needs lives only on the plain window.

## Architecture map (file by file)

| File | Role |
|---|---|
| `nalox.py` | Main process: boot, single-instance claim, main loop (wake → command → brain → speak), exit/restart paths, tray/poller/updater wiring, boot surface. Exit codes: 42 deliberate (supervisor stops), 43 duplicate launch, 1/0 restart-style (supervisor relaunches). |
| `supervisor.py` | Launches `nalox.py` via pythonw (no console), relaunches on crash, honours exit code 42 + `exit_requested.flag` (consumed once), own OS lock. |
| `start_nalox.vbs` | Silent launcher (pythonw → supervisor). Startup shortcut + Desktop shortcut target. |
| `ears.py` | Hearing: energy Segmenter + adaptive gate, wake matching (fuzzy, trilingual), command capture, cloud ears (Gemini → Groq → local). **All local faster-whisper decodes run in a worker PROCESS** (`_TxWorkerClient`/`_tx_process_main`, spawn) under deadlines measured from the job's ack: wake 8 s, command 12 s, file 30 s. **Liveness is an out-of-band heartbeat** (v6.4: dedicated queues + `_hb_echo_loop`, a worker thread that never touches the models — NEVER judge liveness through the serial job queue; busy ≠ dead). Wake/raw timeouts DROP the request and keep the worker; restarts need a dead heartbeat (≥3 s) or a dead process. Slow command/file decodes are waited out to hard caps (30 s / 45 s), late results used. Wake first pass = config `wake_model` (default **tiny**); a loud near-miss of the name (edit distance exactly 2, `_wake_near_miss`) retries once on `WAKE_RETRY_MODEL` ("base"); loud garbles retry once on the command model. |
| `brain.py` | The agent: deterministic intents first (wake/dashboard/phone/PC chores/custom commands/memory/prefs), then the LLM tool loop. Provider priority: FreeLLMAPI → Claude → OpenRouter → Gemini → Groq → OpenAI → Ollama, with perflevel-driven adaptive ordering. Reply guards: length cap (writing exempt), script guard ({Latin, Bengali, Devanagari}), CoT/reasoning-leak guard, leaked-tool-call parse-and-execute, language guard (v6.4: under a bn/hi preference a wrong-language conversational reply is a provider failure; writing exempt). |
| `voice.py` | Speech: ElevenLabs → edge-tts (20 s bound) → pyttsx3 → SAPI; barge-in support; speaking flag + watchdog. |
| `dashboard.py` | The Command Center: Toplevel hosted on the HUD's Tk root (ONE interpreter — never create a second `tk.Tk()`), orb/SYSTEM/CHAT, opening ceremony (v6.2), big ⚡ Level header, custom-command builder. Show mechanics are v6.1's (no confirm round-trip; real window state is the truth; generation-based hide). |
| `hud.py` | The plain app window: built WITHDRAWN (v6.2), X = hide, buttons (Log/Settings/Command Center/Hide/Restart/Exit). Owns the single Tk root/thread; `run_on_tk` hosts the dashboard. |
| `settings_ui.py` | The Settings window (all config lives here; merges into config.json atomically, preserves unknown keys). Sections: Voice, Connections, Microphone, Phone, General, Access & Control, Updates (v6.2). |
| `config.py` | DEFAULTS + `load_config()` merge. `CONFIG` singleton. |
| `patch_config.py` | Shipped in packs; flips ONLY its listed keys / adds new defaults when absent — the owner's keys and choices are never overwritten. |
| `updater.py` | v6.2 self-update from GitHub (config-driven; see below). |
| `logbook.py` | Diagnostics: `nalox_log.txt` + `nalox_page.html`, status header, session command counter (v6.2). Thread-safe, never raises. |
| `perflevel.py` | ⚡ Nalox Level: pure `compute_level` over timing samples + provider health; `level_progress()` for the header bar; adaptive provider ordering data. |
| `phone_link.py` | Nalox Phone app link: pairing page :8765 (10-min pairing mode), TCP command server :8766 (token auth), device state. |
| `phone_control.py` | Phone actions: link-first, ADB-over-Wi-Fi fallback (USB-cable ADB was rejected by the owner — Wi-Fi only; his PC internet is his phone's hotspot). |
| `telegram_bridge.py` | @Naloxbot bridge: owner-gated, text + voice notes; **queued messages are discarded at boot by design** (a queued "stop" once killed boots). |
| `actions.py` | PC actions (open app/URL/file, shell) + the step-aside hook (dashboard hides before an open so the app lands in front). |
| `winlayout.py` | Window placement (split-screen, bring-to-front). |
| `custom_commands.py` | His taught commands (`custom_commands.json`, hot-reloaded; matched after built-ins on ASR-normalised tokens). |
| `memory_store.py` / `docmemory.py` | Persistent prefs/facts (remember-for-life) + document memory (SQLite FTS5). |
| `skills.py` / `skillfiles.py` | Digest, weather, Gmail, lead-gen, demo sites; TOML skill recipes in `skills/`. |
| `youtube_tools.py` / `youtube_play.py` | YouTube OAuth comments/replies; "play X" opens the watch URL. |
| `gcal.py`, `mailer.py`, `reminders.py`, `scheduler.py`, `doctor.py`, `vision.py`, `tray.py`, `create_shortcut.py` | Calendar (via YouTube OAuth), email, reminders, scheduled tasks, self-check, screenshots, tray icon, shortcut creation. |
| `INSTALL.bat` / `UPDATE.bat` | One-time install (Python 3.12 required; hard-stops 3.14+) / one-click update pack applier (CRLF, goto-style, no parenthesized blocks; copies *.py + version.txt + skills/ + assets/ + platform-tools/ + phone-app/ + SETUP-YOUTUBE.txt; pip only when requirements.txt md5 changes). |
| `phone-app/` | The Android app APK (source project lives outside this tree). **The APK is signed with one release keystore that must be reused for every version; the keystore never ships in any zip.** |

## Self-update (v6.2) — how it must stay

- Config keys: `github_repo`, `github_token`, `auto_update`
  (Settings → Updates). Boot check ~60 s in, then 6-hourly,
  only when repo+token set and auto on.
- Apply = UPDATE.bat parity (whitelist in `updater._wanted`);
  **user data NEVER ships or gets overwritten**: `config.json`,
  `custom_commands.json`, `prefs.json`, logs, `*.flag`, `*.lock`,
  memory stores, captures. The deny list (`_never`) is checked
  before the whitelist.
- After applying: write `updated_to.txt`, log
  `[sys] exiting (restart): self-update to vX.Y`, exit via the
  restart path. Next boot pops the marker and speaks the
  update line ONCE.
- Failures: one logbook line, no retry until the next
  scheduled check (manual Settings check = force).

## Tests

Suites live OUTSIDE this tree (owner's workspace:
`nalox-tests/`), one file per version (`test_v54.py` …
`test_v65.py`, plus `test_regression54.py`). **Run each suite
in its OWN pristine copy of the tree** (copy the tree, copy
the suite file into the copy's root, run with python3) —
the suites are state-sensitive and leak config/prefs state
into each other if run in one tree. All suites must be green
before a pack ships. Version stamps inside old suites are
bumped per release; checks that pin intentionally-changed
behaviour are updated with a note, never silently deleted.

## Building an update pack

1. Bump `version.txt`; update the `UPDATE.bat` banner (keep
   CRLF + goto style) and prepend a Bengali section to
   `UPDATE-README.txt` (owner-facing, plain language).
2. Run the full battery (above) in pristine copies.
3. Zip the cumulative update pack: all root `*.py` +
   `version.txt` + `requirements.txt` + `UPDATE.bat` +
   `UPDATE-README.txt` + `SETUP-YOUTUBE.txt` + `assets/`
   (logo.ico, logo_round.png) + `platform-tools/` +
   `skills/*.toml` + `phone-app/nalox-phone.apk`.
   **NEVER include `config.json` or `custom_commands.json`.**
   Verify: entry list, version string, APK + requirements
   md5s unchanged unless intentionally bumped.
4. The full-tree zip mirrors the whole tree (for fresh
   installs) — same exclusions for anything with real user
   data; the tree's own `config.json` is a blank-key template.
5. From v6.2 the source is committed to the owner's private
   GitHub repo — **github.com/arjun408408/nalox** (account
   `arjun408408`, PRIVATE, created 2026-11-15). The release
   flow is: commit + push the source with `version.txt`
   bumped — that push IS the release. Nalox's updater
   (updater.py) reads the repo's `version.txt` and downloads
   the zipball from this repo using the owner's read-only
   token (config `github_repo` defaults to
   `arjun408408/nalox`, patch-if-absent; `github_token` stays
   "" until he pastes one into Settings → Updates — never
   ask for it in chat, never commit a token). Every running
   Nalox self-updates on its next check (boot + 6-hourly).

## Known open items (as of v6.2)

- ElevenLabs returns **402** on the owner's current plan —
  his credits decision, not a code bug; the fallback voice
  chain carries speech meanwhile.
- A Groq-shaped key may still sit in his Claude field
  (harmless 401s; FreeLLMAPI answers first). He can clear
  the Claude field in Settings to silence it.
- YouTube OAuth + Gmail app-password guided setups are
  still owed (see `SETUP-YOUTUBE.txt`).
- The VM that builds packs has no Windows/display: Tk
  behaviour is verified headlessly (state machines + fakes)
  and on the owner's machine after delivery.
