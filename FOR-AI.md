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
   **v6.8:** the chain is now ElevenLabs → edge-tts →
   **Google Cloud TTS** → Google Translate TTS → pyttsx3 →
   PowerShell. The Translate voice is FEMALE for Bengali and
   has no alternative — the Cloud layer exists to restore the
   male rule (bn-IN-Standard-B) once he pastes his free
   Google Cloud key (Settings → Voice; SETUP-GOOGLE-VOICE.txt).
   No key = the layer is never attempted.
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
15. **CPU is NOT a constraint** (2026-11-15 19:51 IST:
    "তুমি সব করো… CPU-তে pressure পড়লে কিছু হবে না…
    কোনো বাধা নাই"). Use heavy local models whenever they
    make Nalox better — this supersedes every earlier
    CPU-caution rejection (it is why v6.7 ships the
    large-v3-turbo local ears fallback and strengthens the
    local Ollama brain). One non-exception: Pocket TTS
    stays out — it cannot speak Bengali; that is a language
    limit, not CPU.

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
| `ears.py` | Hearing: energy Segmenter + adaptive gate, wake matching (fuzzy, trilingual), command capture, cloud ears (Gemini → Groq → local). **All local faster-whisper decodes run in a worker PROCESS** (`_TxWorkerClient`/`_tx_process_main`, spawn) under deadlines measured from the job's ack: wake 8 s, command 12 s, file 30 s. **Liveness is an out-of-band heartbeat** (v6.4: dedicated queues + `_hb_echo_loop`, a worker thread that never touches the models — NEVER judge liveness through the serial job queue; busy ≠ dead). Wake/raw timeouts DROP the request and keep the worker; restarts need a dead heartbeat (≥3 s) or a dead process. Slow command/file decodes are waited out to hard caps (30 s / 45 s), late results used. Wake first pass = config `wake_model` (default **tiny**); a loud near-miss of the name (edit distance exactly 2, `_wake_near_miss`) retries once on `WAKE_RETRY_MODEL` ("base"); loud garbles retry once on the command model. **One-breath remainders are re-transcribed through the command path** (v6.6: the wake decode only finds the name — `transcribe_command_best` re-hears the same segment for the command itself, wake-name stripped; the wake remainder is the fallback, never the loss). **Local command model is `large-v3-turbo`** (v6.7 A: config `whisper_command_model`; cloud ears still first — this is only the local fallback; patch_config migrates the old shipped default "small" and preserves custom values; if the big model's load/download fails, `_get_model` latches a session fallback to "small" with ONE log line — in the worker the latch is reported to the parent as a "notice" result, since worker logging is disabled). **Big-model retry (v6.8):** the failure line now carries the REASON (`_big_model_error`), and the worker reports phase+reason in a `big-model-detail` notice before the fallback notice; a PRELOAD-phase failure arms ONE background retry in the parent (`BIG_MODEL_RETRY_DELAY_S` = 240 s, once per Nalox process) — when due, the next `request()` sends an `upgrade` job; the worker runs `_retry_big_model` on a daemon thread (the serial loop and wake listening never block), success swaps turbo in and posts `big-model-ready`, failure posts `big-model-retry-failed` and stays latched. Decode-phase failures never retry. **Live hearing preview** (v6.7 F): during command recording, `_PreviewPump` decodes the in-progress buffer with tiny in a SEPARATE worker process (its own `_TxWorkerClient`, tiny-only config; latest-snapshot-wins, `submit()` never blocks) and streams partials to the preview sink (nalox.py's `_DashboardPreviewSink` → the dashboard's YOU-bubble preview trio); the final transcript finalizes the bubble and is the only text the brain receives. No pump at all when the dashboard is hidden. **Turbo ladder (v6.10):** the owner's installed faster-whisper is OLD and rejects the name `large-v3-turbo` with a deterministic `ValueError: Invalid model size ...` (his build's accepted list ends at `large-v1`). The big-slot load now goes through `_try_load_big`: candidates = remembered resolution (from `ears_state.json`, the voice_state pattern; re-validated each boot) → configured name → `large-v3` → `large-v2` → `large-v1` → `medium`, intersected with `faster_whisper.utils.available_models()` when importable. An invalid-size ValueError walks to the next rung; any other exception keeps the v6.7/v6.8 latch + retry semantics untouched. If every rung is name-rejected, `_big_model_fail_kind = "invalid-size"` rides the `big-model-detail` notice (4th element) and the parent does NOT arm the 240 s retry (a retry would hit the same wall); other kinds still arm it. The serving rung is remembered in `ears_state.json` (updater deny-list + .gitignore) and reported via a `big-model-resolved` notice so the parent's ready line names the real model. The worker's `ready` sentinel carries a diag dict (`fw_version`, `command_configured`, `command_resolved`); the parent logs one boot line per spawn: `[ears] faster-whisper <ver>; command model configured=<cfg> resolved=<name|small (fallback)>`. requirements.txt pins `faster-whisper>=1.1.0` (first line that knows turbo); UPDATE.bat and the self-updater both pip-install on requirements change, so the library itself upgrades on a later UPDATE.bat run. **Wake Lane (v6.12):** the single worker is SPLIT — `Ears` builds two `_TxWorkerClient`s with lanes: the WAKE lane's process loads ONLY tiny+base and its job door (`_LaneRefused` in `_tx_process_main`) refuses command/file/upgrade jobs and any big-family model; the COMMAND lane preloads only "small", loads the big model LAZILY on first need, and owns the 240 s retry (`_maybe_big_retry` is armed on command/combined lanes only). Wake-segment escalations to the command model are the one `wake_pass` kind the command lane serves. Each process constructs models via `_construct_model` with a per-lane `cpu_threads` cap (wake 2 / command 4 / preview 2; config `ears_wake_threads`/`ears_command_threads`/`ears_preview_threads`). `_TxWorkerClient`'s default lane is "combined" = the pre-v6.12 single-worker behaviour (older suites pin it); `Ears._tx_client` reads as the command client, and assigning it stubs BOTH lanes (the suites' pattern). The lanes restart independently — a busy/dead command lane can no longer starve the wake word (the 2026-11-15 21:36–21:45 field bug: "worker slow" cooldown spam). |
| `brain.py` | The agent: deterministic intents first (wake/dashboard/**app close-open (v6.8)**/phone/PC chores/custom commands/memory/prefs), then the LLM tool loop. **Provider chain is GROQ-ONLY since v6.8** (owner's order 2026-11-15 20:31 IST — "keep the fastest replier, remove the rest"): `_agent_reply` and `_plain_chat` call Groq (with its v6.5 model candidate walk + remembered working model + all guards) and then **Ollama, the silent offline last resort**, reached only when Groq fails entirely and a local server answers. FreeLLMAPI/Claude/OpenRouter/Gemini/OpenAI are NEVER called — their keys stay in Settings untouched; their impls remain in the file as dormant code (test_v66 pins some of their constants/strings — do not "clean them up" without updating the suites). Boot validation validates Groq only. The v6.7 brain_state persistence is GONE from the chain (the model walk's config memory supersedes it); `brain_state.json` stays on the updater deny-list. **App control (v6.8):** `_app_control_intents` runs right after the dashboard intents, BEFORE the standby family and every open path — a close verb (close/quit/exit/kill, বন্ধ/बंद, bondho/bandho/bondo/bond) beside a known app closes it via `actions.close_app` and open can never fire for that utterance; open/close confirmations follow the language pref ("ক্রোম বন্ধ করছি।" / "Opening chrome."); there is also a `close_app` AGENT TOOL. **Act-don't-narrate guard (v6.8):** an agent turn ending with ZERO `_run_tool` executions + an action request + a bare capability claim ("আমি রিপ্লাই দিতে পারি।", "I can…") gets ONE stern retry inside `_agent_openai_compatible`; a retry that still narrates is replaced by the honest line — the false claim never surfaces. Ability QUESTIONS ("তুমি কি … পারো?", "can you …?") are excluded by `_is_ability_question`. Reply guards: length cap (writing exempt), script guard ({Latin, Bengali, Devanagari}), CoT/reasoning-leak guard, leaked-tool-call parse-and-execute, language guard (v6.4: under a bn/hi preference a wrong-language conversational reply is a provider failure; writing exempt). Latency discipline: provider caps 10 s; a provider's model walk has ONE total budget `MODEL_WALK_BUDGET_S` (12 s) across candidates. **Ollama walks too** (v6.7 B: `ollama_models` candidates via the same walk machinery, remembered like cloud models; `OLLAMA_TIMEOUT_S` = 30 s per candidate — it is the last resort, a slow true answer beats the fallback; boot validation notes "[BRAIN] Offline brain (Ollama) ready: <model>" when it answers, one quiet log line when absent; see SETUP-OLLAMA.txt). **Local vision (v6.8):** when Ollama is up (cached probe), `read_my_screen` and the deterministic look-at-screen reply prefer `vision.describe_screen_ollama` — the local VL model (config `ollama_vision_model`, default `qwen3-vl:8b`, the owner's ChatGPT-consulted pick; his PC has an 8 GB NVIDIA GPU) describes the screenshot itself via /api/chat with a base64 image, in the reply language, logging "[vision] answered by ollama <model>"; ANY failure falls back to the OCR-text path unchanged. The system prompt orders act-first tool use (v5.6) + the v6.8 no-narration rule, and invites ONE short follow-up close ("আর কিছু করতে পারি, স্যার?") inside the two-sentence cap (v6.6, from the MARK LIV video). |
| `voice.py` | Speech: ElevenLabs → edge-tts (20 s bound) → **Google Cloud TTS** (v6.8: REST texttospeech.googleapis.com, voice by language class — Bengali bn-IN-Standard-B, the MALE voice the free Translate layer lacks; only attempted when config `google_tts_api_key` is set — see SETUP-GOOGLE-VOICE.txt; joins the breaker/stickiness/persistence machinery as engine "google-cloud-tts") → **Google TTS** (v6.6: translate_tts via requests, language from requested lang else the text's script — the layer that guarantees Bengali/Hindi text is spoken in its own language; its Bengali voice is female, which is why the Cloud layer sits above it) → pyttsx3 → SAPI; per-reply engine stickiness + 5-min session breakers for the network engines (v6.6); **engine persistence** (v6.7 D: `voice_state.json` beside the code — user data, never shipped, updater deny-list — records last-good engine per language class + parked-until wall timestamps + the ElevenLabs down-state; a boot STARTS from the last working engine, parked engines stay parked, ElevenLabs gets exactly ONE re-probe per boot in case credits were bought; only NETWORK engines may become last_good — a pyttsx3 success must never poison it); barge-in support; speaking flag + watchdog. |
| `dashboard.py` | The Command Center: Toplevel hosted on the HUD's Tk root (ONE interpreter — never create a second `tk.Tk()`), orb/SYSTEM/CHAT, opening ceremony (v6.2), big ⚡ Level header, custom-command builder. Show mechanics are v6.1's (no confirm round-trip; real window state is the truth; generation-based hide). **YOU-bubble preview trio** (v6.7 F: `begin/update/end/cancel_you_preview` — the live hearing preview writes into the same chat model; `post()` finalizes an open preview when the `[mic] heard:` line lands and absorbs a duplicate of the finalized body for 5 s; chat purity unchanged — a preview IS a you line). |
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
| `actions.py` | PC actions (open app/URL/file, shell; **close_app (v6.8)** — taskkill by `APP_PROCESSES` image names, returns "Closing {name}." only when a process actually ended) + the step-aside hook (dashboard hides before an open so the app lands in front). |
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
  (Settings → Updates). Boot check ~60 s in, then every
  30 min (v7.2; 6-hourly through v7.1), only when
  repo+token set and auto on.
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
`test_v68.py`, plus `test_regression54.py`). **Run each suite
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
   `UPDATE-README.txt` + `SETUP-YOUTUBE.txt` +
   `SETUP-OLLAMA.txt` (v6.7+) + `SETUP-GOOGLE-VOICE.txt`
   (v6.8+) + `assets/`
   (logo.ico, logo_round.png) + `platform-tools/` +
   `skills/*.toml` + `phone-app/nalox-phone.apk`.
   **NEVER include `config.json` or `custom_commands.json`** (nor
   `voice_state.json` / `brain_state.json` / `prefs.json` —
   the updater's `_NEVER_FILES` deny-list enforces this
   on the self-update path too).
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
   Nalox self-updates on its next check (boot + 30-min
  checks since v7.2; 6-hourly before).

## Known open items (as of v6.8)

- ElevenLabs returns **402** on the owner's current plan —
  his credits decision, not a code bug; the fallback voice
  chain carries speech meanwhile.
- A Groq-shaped key may still sit in his Claude field —
  since v6.8 the Claude provider is never called at all, so
  it is fully inert; clearing the field is optional tidiness.
- **Google Cloud TTS key not yet pasted** — until he follows
  SETUP-GOOGLE-VOICE.txt, Bengali speech uses the female
  Translate voice (the male Cloud voice needs his key).
- YouTube OAuth + Gmail app-password guided setups are
  still owed (see `SETUP-YOUTUBE.txt`).
- The VM that builds packs has no Windows/display: Tk
  behaviour is verified headlessly (state machines + fakes)
  and on the owner's machine after delivery.

## v6.14 "Steady Ears" (2026-11-15)

Field-driven (owner's v6.13 log): the pipeline works and the
big ears model is GPU-verified ("large-v3-turbo on cuda
(float16)"); three residuals fixed. (1) Wake-lane starvation
under load bursts: the WAKE worker process gets a best-effort
priority raise at spawn (psutil nice — ABOVE_NORMAL on
Windows, -5 elsewhere; failure-silent, wake lane only,
`ears._raise_wake_worker_priority`); the lanes share a sync
bundle (`ears._lane_sync`: spawn-context Event + Value)
created by the parent and passed into `_tx_process_main` as
its 7th argument — the command lane's "small" preload waits
for the wake lane's READY (≤ `WAKE_READY_WAIT_S` 20 s, then
proceeds regardless) plus a ~1 s settle, and the wake worker
stamps `wake_ready` before its ready sentinel and sets
`wake_busy` while a wake decode runs, so a lazy big-model
load (`_try_load_big` → `_defer_big_load_for_wake`) polls
the flag for up to ~2 s before starting and then starts
anyway. Lanes without the bundle (combined/preview, older
6-arg callers) see none of this. (2) Brain self-knowledge:
the system prompt now grounds that Nalox hears the owner by
VOICE (wake word + Whisper), speaks via TTS, and also
receives Telegram text — it must never claim it cannot hear
voice input or ask him to type (field 22:45 IST it did
exactly that). Prompt-only; no reply guard. (3) TTS chunk
prefetch (voice.py): for the two engines with a separable
bytes synthesis (`google-tts`, `google-cloud-tts` —
`_PREFETCH_ENGINES`), say() arms the next chunk's text and
the serving engine starts synthesizing it at playback start
(one-chunk lookahead, generation-stamped slot); a stop
orphans the slot (never played, never consumed by a later
reply), and a consumed prefetch failure raises inside the
engine call so breaker bookkeeping counts it exactly once,
identically to a serial failure. edge-tts and ElevenLabs
are NOT prefetched (fused synth/play paths; the v6.11 edge
retry semantics are untouched). Tests: test_v614 (76).

## v7.0 "FINAL — Self-Healing Voice" (2026-11-15)

The owner's closing order: no more drip updates — one final
version that watches ITSELF. The v6.15 Voice Truth pass had
proven every existing guard present and the brain fast
(1.3 s); the remaining failure class was blockage at
UNINSTRUMENTED points (his field symptom all evening:
Telegram text instant, voice commands total silence). v7.0
makes the voice path self-healing + self-reporting; every
intervention leaves a logbook ERROR, which logsync carries
home. (1) AUDIO-STREAM HEALTH (ears.py): the _ChunkSource
callback now feeds _StreamHealth (frame counter +
per-chunk peak-to-peak window); _MicWatchdog (pure policy
on the Ears object) is evaluated in the wake loop every
MIC_WATCH_CHECK_S (5 s): no frames > ears_mic_no_frames_s
(6 s) → stream reopen + ERROR "[ears] microphone stream
restarted (no frames)"; frames flowing but perfectly
constant for ears_mic_flat_s (20 s) → reopen once per
episode + ERROR "(silent frames)" (variance, not level —
a live mic in a silent room still has ADC noise; only a
dead/muted digital stream is perfectly flat). Restarts
are budgeted (ears_mic_restart_budget 3 per
ears_mic_restart_window_s 600 s, sliding) and the legacy
v4.6 _MicHealth reopens share the budget via
note_external_restart; past the budget, one ERROR + the
mic-alert callback fires once per session (nalox.py
speaks "স্যার, মাইকে সমস্যা হচ্ছে।"), and restarts resume
as the window slides. The watchdog evaluates only inside
wait_for_wake_word, so command recording / speaking can
never false-trigger it. (2) MAIN-LOOP LIVENESS
(nalox.py): _StageWatch stamps stages at loop boundaries
(listening/heard/transcribing/thinking/speaking); a
daemon supervisor checks every WATCHDOG_CHECK_S (5 s):
"speaking" past watchdog_speaking_s (45 s) → voice.stop()
(the barge-in lever) + ERROR; any other non-listening
stage past watchdog_stage_s (90 s) → ERROR + recovery
(transcription stages call the new
Ears.respawn_transcription_workers(), which reuses the
lane clients' _restart). Max 1 intervention per stage
per 2 min; the process is never killed here; "listening"
is never judged (the stream watchdog owns it). Python
cannot force-return a wedged main-thread call — every
stage's underlying calls are individually bounded (see
3), so the watchdog is observer + the two real levers.
(3) BLOCKED-CALL AUDIT — no code changed, both paths
already bounded: wake decodes run through
_TxWorkerClient._pump (≤0.25 s slices against monotonic
deadlines; READY_TIMEOUT 60 / ACK_TIMEOUT 5 / decode
deadline from ack, WAKE_TX_DEADLINE 8 s; every auto-kind
timeout feeds _note_timeout; command/file hard caps
30/45 s); every network TTS synth carries a hard timeout
(google-tts 15 s/piece, google-cloud 15 s, ElevenLabs
30 s, edge wait_for 20 s, pyttsx3 thread + 30 s deadline,
PowerShell 60 s + kill; say() logs an ERROR past its
budget and the speaking flag self-clears at 45 s). One
documented exception: the DORMANT robot-ON pyttsx3 path
renders via runAndWait() inline — robot voice is OFF by
the owner's standing decision (config + patch force it),
so the path is unreachable in his configuration, and the
stage watchdog covers "speaking" regardless of engine.
New config keys (config.py DEFAULTS + patch-if-absent):
ears_mic_no_frames_s, ears_mic_flat_s,
ears_mic_restart_budget, ears_mic_restart_window_s,
watchdog_speaking_s, watchdog_stage_s. Real-audio
end-to-end results live in
~/workspace/nalox-tests/real-audio/RESULTS.md (real
faster-whisper base/small on this VM; large-v3-turbo was
NOT VM-tested). Tests: test_v70 (new) + the full battery.
Everything else is frozen at v6.14 (brain, providers,
Bengali-only replies, phone, Telegram, exit codes).

## v7.1 "Hearing That Never Falls Behind" (2026-11-16)

Built from WAKE-SLOWNESS-DIAGNOSIS.md (root cause PROVEN
from the first synced field log: wake escalations to the
command model triggered the lazy 1.6 GB big-model load
inside the command worker's serial loop; while it loaded,
2-thread tiny wake decodes blew the 8 s deadline →
cooldown episodes → the v6.13 anti-chain force-respawned
the HEALTHY wake worker while the 3-job mic queue stayed
pinned and drop-oldest discarded the owner's speech.
Recovery tracked the load FINISHING, never the respawn).
Fixes F1–F6 (ears.py / updater.py): (F1) wake escalations
(triggers a/b/c) retry with the resident escalation model
— new config wake_escalation_model, default "small" —
never the big model; command quality is unchanged (a
match's remainder is still re-heard cloud-first with the
REAL command model; listen_for_command untouched).
(F2) the anti-chain respawn now requires a TRUE STALL:
zero completed decodes in WAKE_STALL_WINDOW_S (60 s),
tracked via _TxWorkerClient._last_completion_at (any
result-shaped message in _classify counts, stale ones
included); a slow-but-completing lane gets
WAKE_EXTENDED_COOLDOWN_S (60 s) instead — no respawn, no
logbook ERROR. Gate ears_antichain_require_stall
(default ON; OFF = exact v6.13/v7.0 behaviour). (F3) the
wake consumer drops segments older than
ears_wake_segment_max_age_s (default 10 s, 0 = off) with
a throttled log line — wake-listening segments only;
commands are never dropped. (F4) no escalation when the
first pass never ran (request() records _last_submitted;
last_request_submitted(); a fail-fast None = not
submitted). (F5) a big load's START is flagged at the
load site (_big_load_started) and announced as a
"big-model-loading" notice at the next notice point —
before the ready sentinel for a preload load, AFTER the
paying job's result for a lazy one (never before the
result: the v6.13 discipline, a notice must not displace
a job's answer in a bounded reader). The parent logs
"[ears] big local model loading…" (throttled) — load
windows are measured now, not inferred. (F6) the
self-updater stops
the install's own adb server (kill-server, lazily) before
copying platform-tools, and a sharing/lock copy failure
(WinError 32/33 / PermissionError) fails the WHOLE apply
NAMING the file — never a silent skip (a skipped binary
would strand a half-updated install that version.txt
could never detect); the no-marker-on-failure discipline
is untouched. Two patterns RE-IMPLEMENTED from the
jarvis-hector study (techniques only — that repo has NO
license): (1) the fixed-line TTS disk cache (voice.py):
say(..., fixed=True) at exactly four nalox.py call sites
(boot greeting, wake ack, could-not-hear line, mic
warning); synthesized once per (text, engine, voice,
speed) and stored in the engine's NATIVE format under
cache/tts (ElevenLabs as WAV via _write_wav — no MP3
decoder ships with the install; the MP3 engines as MP3),
played through the same interruptible players (barge-in
identical), breaker-neutral (no _record_good, no breaker
notes); cache/ is updater-deny-listed + git-ignored and
never ships. (2) the startup mic probe (ears.py
pick_input_device): auto mode only (an explicit
mic_device is never probed), one-shot per process — a
silent default (peak < 0.001 over 0.5 s) is replaced by
the loudest working input with ONE status line.
Dashboard (the owner's order — updates were invisible):
the header carries a permanent VERSION BADGE from
version.txt (dashboard.running_version — the same source
as the boot line); the first Command Center open after
an update shows a ONE-TIME banner (set_update_notice,
fed by the popped updater marker in nalox.py; a UI
element, never a chat line — chat purity untouched); a
2 px accent strip under the top bar follows the status
colour; the SYSTEM panel gains a GPU row (guarded
nvidia-smi, 10 s cache, "—" when absent). New config keys
(DEFAULTS + patch-if-absent): wake_escalation_model,
ears_antichain_require_stall, ears_wake_segment_max_age_s.
Tests: test_v71 (new) + the full battery. Frozen as ever:
brain/providers, Bengali-only replies, phone app,
Telegram, exit codes.

## v7.2 — wake headroom, gate proof, faster self-update, visible mic (2026-11-16)

Built overnight on the owner's direct order after his
02:04 IST verdict on v7.1 ("কিছু হয়নি" — nothing
worked, ~3 min of testing). FIRST STEP was the fresh log
evidence, and it must be recorded honestly: the newest
sync reachable during the whole build (fetched
repeatedly, logs-branch sha 74e2530b) was STILL the
02:02:26 sync — no newer sync had landed. The complete
v7.1 session evidence is therefore 13 log lines: clean
boot 02:01:06, greeting composed 02:01:07 and SPOKEN via
google-tts 02:01:16, [ready], mic connected, gate
floor=0.0000 threshold=0.0060, Command Center closed
02:02:05, one heartbeat (state=listening, queue=0). Zero
[heard], zero worker-slow, zero queue growth, zero
watchdog lines; the fault log holds NO v7.1 crash (its
last boot marker is this very boot). That window proves
NEITHER a further ears defect NOR health: a wake segment
that decoded without matching, and speech the gate never
turned into a segment, are both invisible in it. No S5
fix was invented — S2 below exists precisely to make the
next such window decidable.

- S1 WAKE HEADROOM: the shipped `ears_wake_threads`
  default rises 2 -> 4 (config.py DEFAULTS +
  patch_config PATCH_IF_ABSENT + a WAKE_THREADS migration
  in the established shape: an existing 2 is the shipped
  v6.12 default and migrates; ANY other value is his and
  is preserved). The v6.12 caps predated the owner's
  lifted CPU constraint (2026-11-15). Command (4) and
  preview (2) caps unchanged.
- S2 GATE PROOF (ears.py + nalox.py): the Segmenter now
  flags its blip discards (`last_was_blip` — behaviour
  identical, the discard is no longer silent); the wake
  loop counts seg (submitted) / blip / short (<0.4 s
  drops) / peak chunk RMS into `Ears._listen_stats`;
  `wake_listen_stats()` snapshots + resets; the nalox.py
  heartbeat prints the deltas (`seg= blip= short=
  peak=`). Reading a future heartbeat: peak near the
  floor with seg=0 = the room was silent; a healthy peak
  with seg=0 and blip/short > 0 = he spoke and the gate
  dropped it; seg > 0 = segments are flowing to decode.
- S3 SELF-UPDATE CADENCE (updater.py): CHECK_INTERVAL_S
  and FAILED_RETRY_S 6 h -> 30 min. The existing shape is
  module constants, so this is a constant change — there
  is deliberately NO new config key. Boot check (~60 s)
  unchanged; a pushed fix now lands within the hour.
- S4 VISIBLE MIC (ears.py + dashboard.py): gate beats in
  the wake AND command loops stamp `ears._last_loud_at`;
  `ears.mic_activity()` returns (smoothed level, seconds
  since the last beat or None). The SYSTEM panel gains a
  live mic line under the mic name — `mic_live_text()`:
  an 8-cell level bar + "hearing you now" / "heard Xs
  ago" / "no speech heard yet" — refreshed on the 1 s
  stats tick, guarded end to end ("🎙 —" on any failure).
  This release's visible change (owner's UI rule).
Tests: test_v72 (new) + the full battery. Intentional
re-pins: test_v612 S6/S8 (the wake default is 4 now) and
the functional version-needle sweep 7.1 -> 7.2 in every
suite (test_v71's self-contained fixtures — fake zips,
formatter samples — untouched). Frozen as ever:
brain/providers, Bengali-only replies, phone app,
Telegram, exit codes, wake models + fuzzy matching.

## v7.3 "Instant Answers" — fast brain model, command race, no 402 tax (2026-11-16)

The owner's direct order (2026-11-16 07:58 IST): change
the brain so Nalox answers INSTANTLY — he dislikes the
current brain's slowness. The morning's synced log
(07:51:46, sha fb96904d) showed v7.2's first full voice
round-trip (heard "nalox, open the chrome", Chrome
opened, Bengali reply) with timing wake→record 15.4 s,
transcribe 23.6 s, brain 0.1 s, speak 3.5 s — plus the
wake ack's say() overrunning its budget (13 s > 11 s).
Three of those four numbers are this release; the
07:50:14 exit-code-1 crash is NOT (no traceback in the
sync yet — do not invent a fix for it).

- BRAIN SPEED (brain.py + config.py + patch_config.py):
  the brain stays Groq-only, but the PRIMARY model is
  now llama-3.1-8b-instant. The walk had remembered
  openai/gpt-oss-120b (a reasoning model, slow first
  token); the shipped order is instant -> llama-3.3-70b-
  versatile -> gpt-oss-120b -> qwen/qwen3-32b, in config
  DEFAULTS and patch-if-absent. A remembered gpt-oss-120b
  is STALE for this release: patch_config migrates the
  persisted groq_model (and the groq_models list when it
  is exactly the old shipped list), and brain.py's
  _model_candidates re-orders the walk to the shipped
  order whenever the stale model would head it (the
  shipped primary leads even if a hand-edited list lacks
  it; other remembered models keep winning). Both the
  agent path (_agent_openai_walk) and plain chat
  (_plain_chat) ride _model_candidates, so both changed.
  Ollama remains the silent offline last resort.
- COMMAND RACE (ears.py transcribe_command_best): the
  old path walked cloud ears SERIALLY (Gemini up to 6 s,
  then Groq Whisper up to 6 s) and only then started the
  local decode (12 s worker deadline) — worst case ~24 s
  ≈ the field's 23.6 s. Now the local decode and the
  cloud walk run on parallel daemon threads and the
  FIRST VALID result wins; the loser is abandoned, never
  awaited. All guards unchanged (cloud garbage/script/
  echo checks inside _cloud_transcribe, the local policy
  as-is, both deadlines as-is). cloud_ears="off" or no
  cloud key keeps the exact old local-only path. The
  wake path never comes here (F1–F4 untouched).
- NO 402 TAX (voice.py + nalox.py): the ElevenLabs boot
  re-probe left say(). It used to run inside the boot's
  first uncached utterance — on his hotspot the doomed
  402 round-trip cost seconds on the wake ack itself.
  _speak_elevenlabs is split into _synth_elevenlabs +
  playback; nalox.py calls speaker.start_boot_probe() at
  boot, which runs ONE tiny background synthesis ("."):
  a 402 keeps the block quietly, a success clears the
  block + persisted state so the custom voice returns
  from the next reply. While the block stands, say()
  makes ZERO ElevenLabs calls — _try_engine skips it
  instantly and the sticky engine speaks.
- VISIBLE CHANGE (brain.py brain_status_line): once a
  model has answered this session, the Command Center
  brain line names it — "Brain: Groq · llama-3.1-8b-
  instant ⚡" — fed by _working_models, recorded in
  _remember_working_model on EVERY success (head answers
  included; the persist still only happens on change).
  Before the first answer the line is the plain
  "Brain: Groq ✓". The one-time "✅ Updated to v7.3"
  banner is the standard v7.1 mechanism (its Bengali
  headline text is unchanged — test_v71 pins it).
Tests: test_v73 (new) + the full battery. Intentional
re-pins: test_v67 D1 (the re-probe is background now —
say() pays nothing; the probe's keep/clear behaviour is
pinned in test_v73 instead) and the functional version-
needle sweep 7.2 -> 7.3 in every suite. Frozen as ever:
providers (Groq-only), Bengali-only replies, phone app,
Telegram, exit codes, wake lane.

## v7.4 "Power Tier" — smart routing + the Brain Test (2026-11-16)

The owner's orders behind this release: 07:58 IST
instant answers (v7.3), 08:05 IST "after v7.3, add/test
GLM and show results — GLM becomes primary only if it
truly wins on speed + Bengali", and 08:17 IST "make
Nalox the MOST POWERFUL" — smart routing so simple talk
uses the instant model and hard work uses the strongest
brain automatically.

- SMART ROUTING (brain.py + config.py + patch_config.py):
  config brain_smart_routing (default ON; OFF = v7.3
  exactly) + groq_power_model (default
  llama-3.3-70b-versatile), both patch-if-absent.
  Brain._tier_for decides deterministically from the
  SAME _looks_like_action_request signal the
  act-don't-narrate guard uses — no classifier call, so
  routing costs zero latency. _agent_reply passes the
  tier to _agent_openai_compatible: a power call heads
  its walk with the power model (_model_candidates'
  new head_override — named to avoid the function's own
  local `head`) and remembers its winner under
  groq_power_model via _remember_working_model's new
  single_key, so tiers never contaminate each other's
  remembered head; plain chat rides the v7.3 instant
  walk unchanged. Deep-reasoning fallback stays in the
  walk behind the power model (openai/gpt-oss-120b).
  ESCALATION: when an instant-tier answer to an ACTION
  request trips the act-don't-narrate guard, the ONE
  stern retry goes to the power model; when it fails
  the language guard outright (no reply, and — checked
  — no tool ran, so nothing can double-execute), the
  ONE retry likewise goes to the power model
  (_guard_reply counts trips in _guard_lang_trips; the
  wrapper snapshots it). Exactly one retry either way;
  a power-tier attempt never escalates (it is already
  the top), and the honest Bengali fallback after a
  failed retry is unchanged. The answering chain stays
  Groq-only with Ollama the silent offline last resort.
- BRAIN TEST (new module brainbench.py + Settings):
  measurement ONLY — it never touches the answering
  chain. A fixed Bengali-first prompt set (chat /
  action / reasoning) runs against the Groq walk set,
  the Ollama models when the local server answers, and
  OpenRouter — the dormant provider's ONE sanctioned
  use, only when the owner presses the button with a
  key configured; its list always includes
  z-ai/glm-5.2 and z-ai/glm-5.2:free, and with no key
  those rows report "skipped — no OpenRouter key".
  Per candidate: answered count, median time-to-first-
  token (streamed), mean reply time, Bengali-script
  ratio, and the live guards' pass/fail. Bounds: 15 s
  per candidate across its prompts, 170 s for the whole
  test; a daemon thread refuses concurrent runs and is
  crash-guarded. The table is written to the logbook as
  [brainbench] lines (so it rides the log sync home)
  and shown in Settings → 🧠 Brain ("🧪 Brain Test").
  GLM joins the answering chain ONLY if a future
  benchmark + the owner's word say so — not here.
- VISIBLE CHANGE: the Settings Brain Test button +
  results table, and the tier-aware Command Center
  brain line — "Brain: Groq · llama-3.3-70b-versatile
  💪" after a power answer, ⚡ after an instant one
  (_remember_working_model records the tier in
  _last_answer_tier; brain_status_line picks the mark).
  The one-time "✅ Updated to v7.4" banner is the
  standard v7.1 mechanism (headline text unchanged —
  test_v71 pins it).
Tests: test_v74 (new) + the full battery. Frozen as
ever: providers (Groq-only answering), Bengali-only
replies, phone app, Telegram, exit codes, wake lane,
ears, voice. NOT fixed here: the 2026-11-16 07:50:14
exit-code-1 crash — still no traceback evidence; do
not invent one.

- SCOPE ADDITION (2026-11-16, from the synced v7.3
  session, sync 08:26:18 sha 8465c9b7) — two field-proven
  defects fixed in this same release:
  DEFECT 1 — boot validation re-crowned the stale model.
  At 08:24:57 the logbook recorded "[brain] Groq: model
  openai/gpt-oss-120b works — remembered as the default"
  and the header showed gpt-oss-120b ⚡ as the talking
  brain. Cause: _check_one_key's /models repair called
  _remember_working_model, which (a) persisted the first
  listed candidate — Groq's list that morning lacked the
  instant + 70b names, so the walk reached the stale
  candidate and overwrote the migrated groq_model — and
  (b) filled _working_models, which brain_status_line
  read as "the model that answered". Fix: validation
  probes in _model_candidates order (stale rule
  included) but SKIPS the stale candidate outright, and
  remembers with answered=False — a new _last_answered
  dict records REAL answers only and is what
  brain_status_line names; before the first real answer
  the line is the plain "Brain: Groq ✓". The v6.5 repair
  itself is unchanged for non-stale candidates (pinned
  by test_v65 A7 / test_v613 D1). brain_state.json needs
  no treatment: nothing has read it since v6.8 (it is
  updater deny-list only) — test_v74 pins that a stale
  brain_state.json on disk changes nothing.
  DEFECT 2 — wake-lane worker-slow under segment flood.
  08:25:29/08:26:04/08:27:09 "worker slow", heartbeat
  queue=1 seg=16 blip=2 peak=0.0846: a loud room's
  segments each earned a (b)/(c) small escalation, the
  serial tx thread fell behind, decodes missed
  deadlines, the cooldown tripped — throughput, not
  the v7.1 queue-pin. Fix (ears.py): while >=1 wake job
  is waiting, a segment whose tiny first pass is a
  CLEAR non-match (clean text, no wake word, no
  _wake_near_miss — the existing criteria, no new
  thresholds) skips the small escalation and is
  rejected at first-pass cost ("fast-reject"); near-
  misses keep the base retry, garbage keeps its
  escalation, an empty queue changes nothing, F1–F4
  untouched. Observability: every wake decode records
  path (tiny / base-retry / small-escalation /
  fast-reject) + duration into the listen stats; the
  heartbeat appends "dec=N (t.. b.. s.. r..) dmax=..s"
  when any decode ran, so the next sync shows real
  milliseconds instead of an undecidable window.

## v7.5 "Live Ears" — wake on the live stream + walk self-discovery (2026-11-16)

Owner's spec (09:21 IST, dictated): fix the HEARING
first — he speaks → Bengali text appears on screen
INSTANTLY as he speaks (live captions) → when he
stops, the heard text goes to the brain → the brain
answers by voice, best-effort with whatever was
heard. Field evidence: the v7.4 session (09:10–09:15)
showed six worker-slow episodes in ~5 loud minutes
(60% of segments escalating tiny→small, decodes to
16 s, v7.4 fast-reject r0), and his Brain Test showed
his Groq account lacks the shipped walk's first three
models (404 ×3; only openai/gpt-oss-120b answered).

- LIVE EARS (ears.py). While a wake segment is IN
  PROGRESS, wait_for_wake_word streams snapshots of
  it to a second _PreviewPump (preview lane, tiny-only)
  whose sink is _WakePartialSink. (a) WAKE ON THE
  PARTIAL: Ears._wake_partial_seen fires the wake the
  moment a non-garbage partial passes the PROVEN
  looks_like_wake_word (the batch tiny pass's own
  rule) — callbacks fire mid-speech (wake-up partials
  also raise the window), _partial_wake_event is set,
  and the loop finishes the breath (segmenter close,
  or WAKE_PARTIAL_TAIL_S = 2.0 s cap) and submits the
  segment as a PRIORITY job (dedicated slot
  _priority_job, taken by _tx_loop before the queue;
  the job tuple keeps its 4-shape; the handler learns
  the context from _current_job_id /
  _current_partial_woke attributes, never new params).
  The batch decode still confirms: agreement → the
  one-breath remainder via the proven re-hear, with
  callbacks NOT re-fired; disagreement → logged
  ("live partial woke Nalox but the batch decode
  heard…"), no command taken. A segment CUT by the
  tail cap (id in _partial_cut_ids) keeps its wake
  but its remainder is suppressed in _tx_handle_one.
  Silence/noise can never wake: no active segment →
  no snapshots → no partials (the pump is created
  lazily at the first segment; the real-audio harness
  gates this). F1–F4 + v7.4 fast-reject + cooldown
  semantics are unchanged for batch jobs; a
  partial-woke job is exempt from the F3 stale drop
  (its remainder is owed).
  (b) LIVE CAPTIONS: the same partials forward to the
  dashboard preview sink (begin/update in place) once
  a partial at least near-misses the name — room
  speech never opens a bubble; an unwoken segment's
  bubble is cancelled at segment end; Bengali
  partials display as Bengali (the decoder's own
  text, untouched). The final "[mic] heard:" line
  finalizes as before.
  (c) COMMAND RACE: the accumulated partial joins
  transcribe_command_best as a third racer (source
  "live-partial") after _partial_race_candidate
  validates it (cloud-guard family + coverage ≥
  PARTIAL_MIN_COVERAGE = 0.7 of the final audio). It
  is enqueued first (wins ties); with the cloud off
  it returns immediately and the local decode is
  skipped. listen_for_command passes its recording
  pump's partial; the one-breath re-hear passes the
  wake segment's registered partial. _PreviewPump
  now records (text, snapshot length, submit seq) —
  last_partial(since_seq) separates this segment's
  partial from a previous segment's leftover; the
  wake loop registers the final partial under the
  job id in _wake_partials (pruned to 8).
  (d) ESCALATION ECONOMY: the v7.4 fast-reject gains
  a second trigger — the batch tiny pass is a clear
  non-match AND the segment's live partial (coverage
  ≥ 0.7, clean, no wake word, no near-miss) heard no
  name either: two tiny hearings, same verdict → no
  small escalation even with an EMPTY queue (the
  field's r0 shape: the queue kept draining to zero
  between floods). Any doubt (garbage/match/
  near-miss/low coverage in either hearing) keeps
  full effort. Pinned by test_v75 D5 (flood with
  partials: 8 tiny passes, 0 escalations, 8
  fast-rejects).
  (e) PENDING HYGIENE: _set_pending_command stamps
  the remainder; take_pending_command drops one
  older than PENDING_COMMAND_TTL_S = 10 s, and while
  a live wake's remainder may still land (priority
  job in flight, or a recent partial fire with jobs
  queued) it waits up to PENDING_PARTIAL_GRACE_S =
  3 s instead of recording silence. No live wake in
  play → instant return, exactly as before.
- WALK SELF-DISCOVERY (brain.py). Boot validation's
  /models fetch now also stores the account's ORDERED
  model list on Brain._discovered_models and logs it
  + the effective walk as [brain] logbook lines.
  _model_candidates composes the walk from models
  that EXIST: normal walk = instant-class first
  (configured members in configured order, then the
  account's other instant-class names in /models
  order) → configured order ∩ existing → any other
  chat-capable model present (_chat_capable excludes
  whisper/tts/embed/guard/orpheus/canary/safeguard
  names); head_override walks get existence filtering
  only (the tier head leads iff it exists). The
  groq_model / groq_power_model heads ride in the
  walk, so they are filtered by existence too.
  /models failed/empty → the configured walk,
  byte-identical to v7.4. Composition is pure
  ordering: nothing persists (Defect-1 discipline),
  the stale rule runs first, the status line still
  reads _last_answered only. On the owner's account
  the walk collapses to openai/gpt-oss-120b alone —
  zero 404 round-trips.
- BRAIN TEST POLISH (brainbench.py). (a) A keyed
  provider with NO key configured is reported
  "skipped — no <Provider> key" with ZERO network
  calls — in collect_candidates (Groq joins
  OpenRouter here) and again inside _run_candidate
  as defence in depth. (b) An Ollama candidate's
  FIRST call gets CANDIDATE_BUDGET_S +
  OLLAMA_FIRST_CALL_EXTRA_S (45 s), still bounded by
  the whole-test deadline; a first-call timeout (incl.
  the requests ReadTimeout class) reports
  "timeout — cold load?", distinct from a hard
  failure. (c) The Groq set comes from the account
  list via _groq_account_models: configured names the
  account has are measured, configured names it lacks
  are rows marked "not on this account" (never
  called), plus up to 3 discovered chat-capable extras
  (instant-class first); a failed fetch keeps the
  v7.4 behaviour.
Tests: test_v75 (new) + the full battery. Frozen as
ever: GLM stays benchmark-only (needs his OpenRouter
key in Settings + his word), voice/TTS, phone app,
Telegram, exit codes. NOT fixed here: the
2026-11-16 07:50:14 exit-code-1 crash — still no
traceback evidence; do not invent one.

## v7.6 — "উত্তর এবার বাংলাতেই আসবে" (2026-11-16)

Field evidence (v7.5 session 2026-11-16 10:19–10:21 IST):
self-discovery worked (account walk gpt-oss-120b →
qwen/qwen3.8-27b → allam-2-7b → gpt-oss-20b; validation
remembered qwen/qwen3.8-27b), but the Brain Test showed
EVERY production model scoring Bengali 0% — models answer
Bengali prompts in English and the Bengali-only language
guard discarded each reply, so the owner spoke, saw the
caption, and heard nothing. Owner orders 11:12 + 11:18
IST: (1) ~1-second replies are the target; (2) GROQ-ONLY
IS REVERSED for the chat path — race every configured
provider, fastest valid answer wins; (3) captions must be
visible wherever he can see them.

A. Reply-language rescue (brain.py): the language guard
stashes a reply rejected on language ALONE (per-thread
dict `_lang_rescue_candidates`); when the cascade ends
answerless, `_rescue_wrong_language_reply` machine-
translates the stash to Bengali (free Google Translate
text endpoint, `_translate_to_bengali`, 3.5 s cap, never
raises) and speaks it — log line "[brain] reply
translated to Bengali (rescue)". Writing stays exempt;
tool arguments are never translated; a bare capability
narration is never rescued; the translated text must
pass the script + language guards and the two-line cap.
Translation failure → today's honest Bengali fallback,
unchanged.
B. Auto-model chat head: boot validation records its
pick in `_validation_model` (kept apart from
`_working_models`, so a power-tier answer can never move
the chat head); with discovery present, `_model_candidates`
leads the CHAT walk with it (power walk untouched;
no discovery = v7.5 exactly). Boot logs "[brain] …
auto chat head: <model>". `brain_status_line` shows
"Brain: Groq · auto · <last-answered model> ⚡/💪" when
discovery is active.
C. Brain Test production parity (brainbench.py): bench
requests carry the production system text (identity head
+ brain.py's own `_language_directive()` via a shell
Brain) through the module global `_ACTIVE_SYSTEM`, set
for the run only — transport signatures unchanged.
D. Banner per-version table in dashboard.py
(`_NOTICE_HEADLINES`; v7.1's exact line preserved);
v7.6 headline "উত্তর এবার বাংলাতেই আসবে".
E. Chat race (brain.py `_chat_race`): plain-chat turns
race Groq (discovered/auto walk) + Gemini (key in
Settings) + FreeLLMAPI (cached probe) — first
guard-passing reply wins, losers abandoned (daemon
threads, `_remember_chat` suppressed on racer threads,
`_brain_fail` quiet). A language-only finisher becomes
the rescue candidate and buys the field
CHAT_RACE_GRACE_S (1.5 s) to be beaten by a native pass;
first-finisher window CHAT_RACE_BUDGET_S (4.5 s). One
[brain] line names the winner + ms. Fewer than two
racers → the exact v7.5 serial path. The AGENT/action
path is unchanged (Groq power walk + Ollama).
F. Captions on both surfaces (nalox.py + hud.py): the
preview sink is now `_MultiPreviewSink` fanning out to
the dashboard sink and a new HUD sink; each sub-sink
gates on its OWN visibility, so a hidden Command Center
no longer starves the visible plain window (the v6.7
pump only streamed when the dashboard was visible). The
HUD grows an in-place mark-tracked "You …" preview line
(`preview_begin/update/finish`) that absorbs the
following "[mic] heard:" twin. Wake semantics, the
partial matcher and ears.py are untouched.

NOT in v7.6: ears/mic changes beyond F's sink routing,
TTS engines, phone/Telegram, GLM (still unmeasurable —
his OpenRouter account has zero credits and
glm-5.2:free 404s), the exit-1 crash (no traceback
exists; do not invent one).

## v7.7 — "শোনার লাইন এবার ডুববে না" (2026-11-16)

Field evidence: the synced log of 2026-11-16 11:55 IST
(v7.6 session) and 12:05 IST. Ten items, one release:

A. THE EXIT-1 CAUSE IS NOW PROVEN — the 11:55 sync's
fault tail contains the first traceback ever captured:
"Windows fatal exception: code 0xe0000002", current
thread inside the SAPI5 driver (pyttsx3/drivers/
sapi5.py; say -> _pump ->
setBusy -> startLoop -> runAndWait) called from
voice.py's in-process pyttsx3 thread, main thread
waiting in nalox.py's say() join, a Telegram thread ALSO
inside the voice layer — and the same session's
self-update restart "exiting (restart): self-update to
v7.6" was followed by "[supervisor] Nalox process DIED
(exit code 1)". This is the cause family for the exit-1
deaths (2026-11-15 x4 + 2026-11-16 07:50 + 11:53). (Two
earlier watcher claims of this theory were checked
against their syncs and REJECTED — those syncs genuinely
lacked the dump; it is proven only now, by this one.)
Fix: pyttsx3 runs in a CHILD PROCESS (voice.py
_PYTTSX3_CHILD_SRC, `python -c … speak|render`), spawned
through the single seam Speaker._launch_tts_child,
polled with the old stop/timeout discipline
(PYTTSX3_TIMEOUT unchanged); a child crash/timeout is an
ordinary engine failure for _try_engine's breaker. The
robot path renders via the child too (its playback stays
in-process — sounddevice/winsound are not SAPI).
Speaker._speak_pyttsx3(text, robot) signature unchanged.
Plus voice.stop_for_exit() — every exit path now stops
in-flight speech BEFORE exiting: nalox._restart_process,
the voice exit actions, updater.check_and_update,
hud._on_exit/_on_restart, tray exit/restart,
settings_ui Save & Restart, telegram_bridge exit. (The
boot stand-down sys.exit(43) is pre-Speaker — no speech
can exist; deliberately untouched.)

B. WAKE FLOOD, ROUND 2 (ears.py). Field: heartbeat
queue=3 SATURATED, seg=9, peak=0.2578 (gate 0.006), zero
[heard]; the earlier session's dec=7 had s3 — small
escalations were ~half the wake worker's time. (i)
_queue_pressure (waiting >= 1, snapshotted with the
existing _waiting): NO 'small' escalation for that
segment at ANY of the three small triggers (garbage /
out-of-set-lang / Bengali-script rescue) — the garbage
trigger had no gate at all before. The base near-miss
retry is NOT the small escalation and stays (different,
resident model; dec_base was 0 in the flood window).
Zero pressure = v7.6 exactly. (ii) _take_queue_job():
>= 2 waiting -> take the NEWEST, drop the older ones,
one aggregate line "[ears] dropped N stale wake
segments (queue pressure)"; 0/1 waiting = the old FIFO
get; the v7.5 priority slot still goes first; F3's
stale-age drop still applies to the taken job. (iii)
ears_wake_threads default 4 -> 6 (config.py DEFAULTS +
patch_config PATCH_IF_ABSENT + a chained migration:
stored 2 -> 4 (v7.2 step) -> 6 (v7.7 step); any other
value preserved). _LANE_DEFAULT_THREADS is NOT the
production default and is unchanged (test_v612 pins the
keyless (2,4,2) fallback tuple).

D. GARBLE-TOLERANT INTENT (brain.py). The owner's
screenshot: "আমার জন্য একটা সং প্লে করো" heard as "আমে
বলছি যে তুমি আয় আমাত জনে একটা সগ পিলে করো সগ" -> the
could-not-hear line. _correct_bengali_command_garble():
context-gated on a play verb token; rewrites সগ/সংগ/
সাঁগ/সঙ -> সং and পিলে -> প্লে; applied ONLY inside
_bengali_commands (never to agent/writing/quoted text).
The corrected play path strips verbs + song noun +
field fillers token-wise; an empty remainder plays the
bangla-song default. Plus an ASR-tolerance clause in
_system_prompt (infer intent from the sounds; the
could-not-hear fallback is only for NO plausible
intent).

E. COMPLETION MANNER (brain.py). The owner's shape:
completed form, never the progressive ("স্যার, আমি সং
চালিয়ে দিলাম", not "আমি চালাচ্ছি"), then ONE
next-step ask specific to the finished action. The
v6.6 close clause is rewritten to say exactly that
(its test needles are preserved). Deterministic play
confirmations (the গান block, the corrected path,
_play_reply, the content-intents play line) now return
_song_done_line(): "ঠিক আছে {addr}, … চালিয়ে দিলাম।"
+ a rotating play-specific offer ("আরেকটা গান
চালাব?" / "ভলিউম বাড়িয়ে দেব?") appended only when
the previous reply did not end with an offer.
Anti-repetition state: Brain._last_reply_had_offer,
recorded by handle() via _note_reply_closing on every
routed reply; _guard_reply's new post-check
(_strip_repeated_generic_offer) removes a trailing
GENERIC offer ("আর কিছু করতে পারি?" / "anything
else?") when the previous reply already ended with
one. The app-open line "ক্রোম খুলছি।" is NOT changed
(v6.8 field-verified, test-pinned).

F. CHROME PROFILE (actions.py). The screenshot's
picker stall: Chrome now launches with its last-used
profile — _chrome_last_profile() reads the Local State
JSON (profile.last_used), _chrome_command() builds
[exe, --profile-directory=<dir>, url?], open_url uses
it when the registry says Chrome is the default
browser, open_app uses it for chrome targets.
os.startfile cannot take arguments, so a known profile
means a direct Popen. Unknown profile / non-Chrome
default = today's behaviour, byte for byte.

G. NO CONSOLE FLASHES. Every console-capable child in
the task paths now launches with CREATE_NO_WINDOW
(per-module _hidden_console_kwargs(), phone_control's
existing pattern): actions (open_app Popen, taskkill,
shutdown/restart, the PowerShell recycle-bin fallback,
the explorer fallback), voice (the pyttsx3 child + the
PowerShell speech path), vision's PowerShell runner,
dashboard's nvidia-smi probe, settings_ui's autostart
PowerShell, updater's pip/adb/patch children.
Supervisor/boot behaviour untouched by design.

H. CHAINS COMPLETE EVERY STEP (brain.py). Field:
"নোটপ্যাড ওপেন করে আমার নামে কিছু লিখবে" — Notepad opened,
nothing written. Three layers: (1) _app_control_intents
DEFERS to the agent when an open carries a second
action clause (লিখ / write / type tokens, or play+song)
instead of consuming the utterance for the open alone;
(2) the agent loops (OpenAI-compatible AND Ollama)
continue the turn ONCE when a model stops to narrate
after >= 1 tool on a chain request
(_looks_like_chain_request + _CHAIN_CONTINUATION);
(3) the wrapper replaces a non-blocker final reply
with the honest partial line when the continuation
produced no further tool
(_turn_partial_after_continuation). Anthropic's loop is
unchanged (dormant provider, never configured). Two
precision rules the battery enforced: the chain
detector counts Bengali VERBS only (the nouns মেসেজ/
জবাব in the narrate list mark action-ness, not a
second action), and the continuation judges the chain
shape on the owner's words with any stern note
stripped (_owner_utterance) — the narrate retry's own
system text must not fake a chain.

I. DEAD-MODEL MEMORY (brain.py). Field: Gemini's
gone-hop (2.5-flash -> 2.0-flash -> 2.5-flash-lite ->
flash-latest) re-paid on EVERY turn. Brain._dead_models
holds (provider, model-key) pairs that returned
_MODEL_MISS; _agent_openai_walk filters them before
walking and fails at once when all candidates are
known-dead; _agent_ollama's loop gets the same filter.
Session scope only.

J. AGENT-PATH LANGUAGE SEAM (brain.py). Reproduced
against v7.6 before fixing: a substantive English
reply on the agent path WAS rescued (the v7.6 A6 pin),
but a language-rejected CAPABILITY CLAIM fell through
_rescue_wrong_language_reply's claim exclusion into
the could-not-hear line — the narrate guard, which the
exclusion defers to, never sees a language-rejected
reply. The 11:58 turns match this shape (Groq answered
in English, guard rejected, turn ended with "ওটা ঠিক
ধরতে পারলাম না"). Fix: at the answerless endgame a
claim candidate now returns the narrate guard's own
honest line ("দুঃখিত sir, কাজটা এখন করে উঠতে পারলাম
না।") instead of None — the claim TEXT is still never
spoken or translated (narration rules unchanged), but
the could-not-hear line can no longer end a turn in
which a provider produced a substantive reply.
test_v76 A5 is updated to the new endgame (translator
still never called; the None expectation became the
honest line) — disclosed intentional change.

NOT in v7.7: brain providers/race composition (v7.6's
field proof still owed — undisturbed), TTS engine
order, phone/Telegram behaviour, wake matcher
thresholds.

## v7.8 — "Muse Wonder যোগ হলো" (2026-11-16)

The owner's explicit order (2026-11-16 13:08 IST): add
Muse Wonder — Meta's frontier model, a PAID API — to
Nalox as a brain provider. (He was told on 2026-11-16
08:02 IST that Muse Spark itself has no API; Muse
Wonder is the Meta Model API's offered model, and he
chose it with the price known.)

FACTS (verified 2026-11-16 from ~/docs/muse.md,
dev.meta.ai docs and two independent write-ups): the
Meta Model API is OpenAI-compatible — base URL
https://api.meta.ai/v1, Chat Completions at
/chat/completions, Authorization: Bearer
<MODEL_API_KEY>, tool calling supported on that
surface. Model id "muse-wonder-1.0" (preview, 1M-token
context). Price $4.00/M input, $20.00/M output,
$0.20/M cached input. Keys are created at dev.meta.ai;
a payment method is required there FIRST — that is the
owner's side, never the program's.

WHAT SHIPPED:
- Config: muse_api_key ("" default) + muse_model
  ("muse-wonder-1.0") in config.py DEFAULTS and
  patch_config PATCH_IF_ABSENT (existing values never
  disturbed). Both ride brain's config hot-reload.
- Settings → 🧠 Brain: a "Muse Wonder (Meta Model
  API)" key field + Model field, wired like every
  other provider key field (collect_brain →
  collect_all → config.json; saved locally, never
  logged).
- Chat race (brain.py): with a key pasted and the
  provider not parked, Muse Wonder is one more racer
  ("muse-wonder" in the winner line) through
  _agent_openai_walk — production system prompt, the
  full guard pipeline and the translate-rescue apply
  unchanged. "muse" sits in _MODEL_WALK_PROVIDERS
  with the single configured model as its whole walk,
  so its answers record through
  _remember_working_model like any walk provider's.
  No key = ZERO calls to api.meta.ai anywhere
  (pinned in test_v78).
- Auth/billing discipline: an HTTP 401/403 (key
  rejected) or 402 (billing) from the Meta endpoint
  parks the provider for the session via
  Brain._park_muse — ONE clear logbook line, then the
  race fields it no longer; other failures never park.
  Session scope: a restart re-probes (the _dead_models
  discipline).
- Brain line: Brain._last_answer_provider (recorded
  on real answers + by the race coordinator) — after
  a Muse Wonder win the Command Center shows
  "Brain: Muse Wonder ⚡"; before its first answer
  the line is byte-identical to v7.7.
- Brain Test (brainbench.py): muse-wonder-1.0 via
  MUSE_BASE as a "muse" candidate, key-gated with the
  OpenRouter-style clean skip ("skipped — no Muse API
  key", zero network). Measurement only.

NOT in v7.8 (deliberate): the AGENT/action path —
it stays the Groq power walk + Ollama exactly.
Wonder's tool-calling inside Nalox's harness is
unproven; promoting it is a later, measurement-led
decision (the Brain Test numbers come first). Also
untouched: boot key validation (still Groq-only —
Muse is not in _KEY_CHECKS, so no api.meta.ai call
happens at boot either), TTS, ears, phone/Telegram,
exit paths. KNOWN EDGE: a config with ONLY a Muse
key (no Groq/Gemini/FreeLLMAPI) fields a one-racer
"race", which by the v7.6 rule does not run — Muse
is a race participant, not a standalone serial
provider; on the owner's machine Groq is configured,
so the field exists. All Muse traffic in tests is
STUBBED — no real Meta API key exists on the build
VM; the first live call happens on the owner's
machine after he pastes his key.

## v7.9 — "brain-এর limit লাগলেও অন্য brain উত্তর দেবে" (2026-11-16)

FIELD EVIDENCE (the owner's own synced log, 2026-11-16
13:19–13:33 IST, v7.7/v7.8 sessions): the chain "open
Notepad and write something good in my name" ran step 1
(open_app notepad 13:19:53), then the agent loop's NEXT
model call died on HTTP 429 (qwen/qwen3.8-27b org rate
limit) and the turn ended with the spoken line claiming
a connection problem and asking him to check his Groq
key — a false diagnosis. Two retries died identically;
by 13:24–13:33 nearly every turn ended in that line
(29 occurrences vs only 3 explicit 429 lines — race
failures are silent and the walk never advanced past a
429, and no Ollama attempt appeared anywhere). Second
evidence (sync 13:36:36 IST): heartbeat dec dmax=66.8 s —
ONE wake-lane 'small' escalation decode took 66.8 s;
worker-slow lines repeated while heartbeats sat in
state=listening: mid-work Nalox stalls into Listening
and wake-ups don't land. Third: the male Bengali voice
had not been ATTEMPTED since 2026-11-15 19:52 IST —
google-tts stickiness spoke every reply (female voice)
for ~18 h (see item H).

ROOT CAUSES (proven in code):
- `_post_with_rl_retry` retried the SAME model twice,
  then `_agent_openai_compatible_impl` treated the
  exhausted 429 as a terminal `_brain_fail` (a 429 is
  not a "dead name" per `_model_error_snippet`, which
  matches only 400/404), and `_agent_openai_walk`
  treats impl-None as terminal — THE WALK NEVER
  ADVANCED past a rate limit, on any call, including
  post-tool continuations.
- `_agent_reply` did call `_agent_ollama` after Groq,
  but the v4.8 probe rule returns None SILENTLY when
  Ollama doesn't answer its /api/tags probe, so no
  attempt was ever visible (and on the chat path there
  was no Ollama attempt at all behind the race).
- `_brain_fail` recorded `_last_agent_fail` for every
  failure and `_chat_fallback` spoke the key-check line
  whenever the cloud looked unreachable — cause-blind:
  a rate limit was reported as a key problem.
- The v7.1 F2 anti-chain gate respawns the wake lane
  only on ZERO completions in 60 s (or worker
  timeouts); a worker completing one decode per ~66 s
  trips neither, so a slow-decode jam persists.
- Voice: `_say_impl` step 1 is the persisted last_good
  engine (google-tts for bn) — edge-tts, the only male
  Bengali voice, only ran when google failed, and
  google essentially never fails.

ITEM A — 429 ADVANCES THE WALK (brain.py). A model
that answers 429 on a WALK call (model_walk=True —
the chat walk, the race's Groq racer, and EVERY
agent-loop call including post-tool continuations)
is parked for MODEL_RATELIMIT_COOLDOWN_S = 60 s
(`_park_model_ratelimit`, one log line: "[brain]
<label> model <m> rate-limited — parked 60s, trying
next") and the walk continues with the next
candidate; the impl returns the `_MODEL_RATELIMITED`
sentinel, never a terminal failure. Parked models
are filtered from every walk (`_model_in_cooldown`);
if the cooldown alone empties the walk, the turn
fails as a rate-limit death (http_status=429). The
impl's walk-mode post is a SINGLE bounded request —
the v6.13 jittered rl-retry survives ONLY on the
non-walk path (model_walk=False: _plain_chat and
direct callers; test_v613 E7 pins it). A 429 can
never, by itself, end a turn while untried
candidates remain.

ITEM B — CHAT OLLAMA SAFETY NET. When a chat turn's
race/serial path ends answerless, `_agent_reply`
makes ONE bounded Ollama attempt (`_ollama_chat_net`:
the production `_agent_ollama` machinery with an 8 s
timeout override and a single candidate) before any
failure line. One log line per outcome: "[brain]
chat fallback: Ollama answered" / "…failed: <why>".

ITEM C — AGENT FALLBACK ORDER. Groq walk → Muse
Wonder WITH TOOLS (`_agent_muse_fallback`: only when
a muse key is configured and not parked/rejected —
v7.8's rules; reverses v7.8's "never on the agent
path" for the FALLBACK position only; the primary
agent walk is unchanged) → Ollama → the honest
fallback. One log line per attempt + outcome. With
no Muse key this collapses to the pre-v7.9 order.

ITEM D — TRUTHFUL FAILURE LINES. `_brain_fail` now
also records the turn's failure CAUSE
(`_turn_fail_causes`: 429 → "ratelimit", 401/403 →
"auth", else "other"; reset per agent turn). In
`_chat_fallback`, a ratelimit-only death speaks the
LIMIT line ("দুঃখিত স্যার, brain-এর limit শেষ হয়ে
গেছে — একটু পরে আবার চেষ্টা করুন।" + hi/en variants)
— it never mentions the key or Settings. Auth keeps
the existing key-check line; other causes keep the
existing connection line; a turn with NO recorded
provider failure (e.g. every reply guard-rejected)
also keeps the connection line, byte-identical to
v7.8. Guard rejections never record a cause.

ITEM E — OLLAMA VISIBILITY. `_agent_ollama` records
`_ollama_last_error` (probe unreachable / impl
failure incl. its HTTP status — "[BRAIN] Ollama
FAILED: HTTP 500" already existed in the impl) and
both fallback call sites log it once per attempt.
Ollama itself is NOT repaired (it lives on the
owner's PC; the bench showed HTTP 500 at 10:20 IST —
the next sync will show whether production attempts
work).

ITEM F — WAKE SLOW-DECODE STALLS (ears.py). A wake
decode (any pass, incl. escalations) completing
slower than `ears_wake_decode_stall_s` (default
20.0) is a stall event ("[ears] wake decode took
Xs — stall", via the `_note_decode_stat`
funnel/`_note_wake_decode_stall`). Two stalls
within WAKE_DECODE_STALL_WINDOW_S = 600 s respawn
the wake lane through the same client kill/spawn
the anti-chain uses (logbook ERROR "[ears] wake
lane restarted (repeated slow decodes)"), riding
the worker restart budget; the segment queue lives
in Ears, so the queued newest segment survives.
Zero-stall behaviour is byte-identical to v7.8.

ITEM G — UPDATES LAND BY THEMSELVES (updater.py).
The owner's words: "তুমি দিলেই অটোমেটিক আপডেট করে
নেবে". CHECK_INTERVAL_S / FAILED_RETRY_S 30 min →
5 min. `poke_check()` — wired into the Command
Center's show path (dashboard.show) — runs a check
on its own thread, debounced to one per
POKE_DEBOUNCE_S = 120 s; start_background registers
the (cfg, restart_fn) it needs. Apply policy is
unchanged (deny-list, adb kill-server, marker,
spoken announcement + banner after restart) EXCEPT
the restart defers while a voice turn is busy:
check_and_update asks the busy probe (nalox.py
registers one: stage != listening or voice speaking)
and, when busy, a daemon `_deferred_restart` polls
every DEFER_POLL_S = 5 s until the turn ends, capped
at DEFER_MAX_S = 600 s, then restarts anyway. The
immediate path is factored into `_restart_now` and
is byte-identical to v7.8 (exiting line, v7.7
stop_for_exit, restart callback).

ITEM H — THE MALE VOICE SPEAKS (voice.py). Rule
(gender-first): a Bengali reply with bn_voice =
bn-BD-PradeepNeural (the male choice) attempts
edge-tts FIRST — ElevenLabs keeps canonical first
place (his own voice outranks fallbacks while alive;
its 402 block makes the attempt free) — ahead of the
persisted last_good engine, under
MALE_EDGE_BUDGET_S = 7.0 (the whole attempt, retry
included; `_speak_edge` reads the armed
`self._edge_budget_s`). On edge failure the reply
falls through to the existing order and ONE line
logs: "[voice] male voice unavailable — female
fallback for this reply" (once per reply). At boot,
nalox.py passes the Bengali fixed lines to
`start_male_cache_warming`: a background edge pass
writes cache/tts entries under the edge engine key,
and `_fixed_cache_lookup` prefers the edge entry
when Bengali-male is configured; one boot line
("[voice] male voice cache warmed" / "…warming
failed — will retry next boot"). The session
breaker is unchanged (2 consecutive failures park
edge for 300 s — successes reset it, and under
male-first most replies now succeed). QUEUED NEXT
STEP if edge-first still fails in the field: Piper's
bn_BD voice (openSLR-based, gender/quality
unverified) — deliberately not integrated here. The
Google Cloud key path stays closed (billing-card
wall; do not revive).

ITEM I — WORK TURNS FEEL INSTANT (brain.py). The
owner's words: replies within 1–2 s and the work
itself fast. Field baseline: chat ~1.0–1.3 s when
healthy; agent turns logged brain 7.2–7.5 s (walk
stalls, dead candidates, serial everything) and the
failed ones died at ~7 s. Three parts:
(1) Tight first-call budget on the AGENT path:
call_budgets=(AGENT_FIRST_CALL_BUDGET_S=3.0,
AGENT_CALL_BUDGET_S=5.0) threads _agent_reply →
_agent_openai_compatible → _agent_openai_walk →
_agent_openai_compatible_impl (the Muse fallback
passes it too); every post is capped at
min(passed timeout, cap) — round 0 at 3 s, later
rounds at 5 s — and a post that times out returns
_MODEL_SLOW: the walk advances (no parking; the
budget re-applies next turn), a non-walk call maps
it to a "model too slow" failure and the turn's
fallbacks proceed. Chat/race calls pass
call_budgets=None and are byte-identical to v7.8.
(2) Concurrent independent tools: one step's calls
run through a ThreadPoolExecutor (≤4 workers,
results collected in call order) when
_tools_parallel_ok says they are independent —
same-name repeats unless the tool is
sequence-critical (_PARALLEL_NEVER_TOOLS:
type_text, press_key, snap_app, snap_active,
phone_call, email_lead, lock_pc), or a mixed batch
of read-only gatherers (_PARALLEL_SAFE_TOOLS).
One log line: "[brain] running N tools in
parallel". Everything else keeps the serial loop;
the Ollama impl keeps its serial loop too (the
offline last resort is not the latency problem).
(3) No silent work: an action turn arms
_arm_progress_line — a daemon Timer at
AGENT_PROGRESS_S=4.0 s speaks AGENT_PROGRESS_LINE
("কাজটা চলছে, sir — একটু অপেক্ষা করুন।") via
speaker.say(lang="bn", fixed=True), at most once
per turn, disarmed in a finally when the turn ends;
the line joined nalox.py's fixed-line set, so it
is male-warmed and cache-served. HONEST BUDGETS:
chat ~1 s; work starts instantly (wake ack + first
tool); a typical 2-step job targets ~3–5 s
end-to-end. A guaranteed 1–2 s TOTAL for
multi-step cloud work is not physically possible
and was not promised.

DELIBERATELY UNTOUCHED: `_plain_chat` (writing
tasks), the race's guard/rescue semantics, v7.7
A–J, v7.8's Muse race participation, Settings UI,
phone/Telegram, ears beyond item F, Ollama itself.

TESTS: test_v79 pins A–H (429 advance on chat +
agent + the field's post-tool chain; park skip +
expiry; Ollama net save + log; Wonder-with-tools
save; per-cause spoken lines; Ollama 500 logged as
500; stall counting/respawn/under-cap; updater 5
min + poke debounce + busy deferral + cap; male-first
order, double-failure fallback line, female/English
unchanged, warming writes + lookup preference,
warming failure inert). Disclosed amendments:
test_v72 S3 (cadence 30 min → 5 min, item G) and
test_v67 D1 session 2 (edge is now attempted once
before google under male-first — the v6.6 "tax" pin
becomes the v7.9 rule). All provider traffic in
tests is stubbed; the owner's real Groq rate limit
and Ollama's real 500 cannot be reproduced on the
build VM.
