"""Nalox Brain Test (v7.4) — MEASUREMENT ONLY.

The owner's orders (2026-11-16): v7.3 made the brain
instant (llama-3.1-8b-instant primary); he then asked for
GLM to be added and TESTED — "GLM becomes primary only if
it truly wins" (08:05 IST) — and for Nalox to be the MOST
POWERFUL via smart routing (08:17 IST). This module is
the measuring instrument for that decision: it runs one
fixed Bengali-first prompt set against every brain
candidate Nalox could use and reports, per candidate,
whether it answered, how fast the first token came, how
long a reply took, how Bengali the replies are, and
whether they pass the same script/language guards the
live brain enforces (brain._reply_script_ok /
_reply_wrong_language).

Candidates:
  * Groq — the live walk's model set (answering chain).
  * OpenRouter — ONLY here, and ONLY when the owner
    explicitly presses the Brain Test button with an
    OpenRouter key configured. The dormant OpenRouter
    path is never part of the answering chain (v6.8
    Groq-only order); this is its one sanctioned use.
    The candidate list always includes z-ai/glm-5.2 and
    z-ai/glm-5.2:free (the MYRAA brain he asked about);
    with no key configured those rows report
    "skipped — no OpenRouter key" so the gap is visible,
    never silent.
  * Ollama — the offline brain's models, when the local
    server answers; otherwise visible skipped rows.
  * Muse Wonder (v7.8) — the owner's paid Meta brain,
    measured through the Meta Model API ONLY when its
    key is configured (it also races live chat — see
    brain.py); with no key the row reports
    "skipped — no Muse API key", never a call.

Bounds: each candidate gets CANDIDATE_BUDGET_S (15 s)
across all its prompts, each single call is capped by
what is left of that budget, and the whole test stops
starting new candidates at TEST_BUDGET_S (170 s). The
test runs on a daemon thread, refuses to run twice at
once, and is guarded end to end — a benchmark crash can
never take Nalox down (start_benchmark catches all).

Results land in three places: the logbook as
[brainbench] lines (so they ride the log sync home),
this module's last_results() for the Settings UI, and
the caller's on_done callback.
"""
import logging
import threading
import time

log = logging.getLogger("nalox.brainbench")

# The fixed prompt set — Bengali-first per the owner's
# language rules: one chat question, one action request,
# one short reasoning question. Measurement completions
# carry NO tools: nothing here can act on the PC.
PROMPTS = (
    ("chat",
     "আকাশ নীল কেন? এক-দুই লাইনে উত্তর দাও।"),
    ("action",
     "আমার জন্য ক্রোম ব্রাউজারটা খুলে দাও।"),
    ("reasoning",
     "একটি ট্রেন ঘণ্টায় ৬০ কিলোমিটার বেগে আড়াই ঘণ্টা "
     "চলল। মোট কত কিলোমিটার গেল? শুধু উত্তরটা দাও।"),
)

_SYSTEM = ("You are Nalox, Arjun's personal assistant. "
           "Reply in Bengali only, briefly — at most two "
           "short sentences.")

# v7.6 (production parity): while a benchmark runs, the
# transports carry the PRODUCTION system text instead of
# the bench's own line above — the identity head of
# brain.py's system prompt plus brain.py's OWN language
# directive for this cfg, composed by brain.py's code
# (see _production_system). The v7.4/v7.5 bench measured
# a bare model against a one-line plea for Bengali and
# reported Bengali 0% for every candidate; production
# sends a much stronger directive, so the bench's
# Bengali% must be measured under production conditions
# to mean anything. Set by run_benchmark, cleared when
# it returns; direct transport calls (tests) see None
# and keep the v7.4 bench line.
_ACTIVE_SYSTEM = None


def _production_system(cfg):
    """The system text bench requests carry (v7.6): the
    production chat path's prompt head — the same
    identity sentence brain._system_prompt opens with,
    plus the SAME Bengali language directive it appends,
    produced by brain.py's own _language_directive on a
    shell Brain holding just this cfg (the directive
    reads cfg + prefs only). Any failure keeps the
    bench's own line — measuring must never break."""
    try:
        import brain as _brain
        shell = _brain.Brain.__new__(_brain.Brain)
        shell.cfg = cfg
        shell._prefs = {}
        directive = shell._language_directive()
        name = str(cfg.get("assistant_name") or "Nalox")
        user = str(cfg.get("user_name") or "Arjun")
        return (f"You are {name}, {user}'s personal "
                f"laptop assistant." + directive
                + " Replies are at most two short "
                  "sentences.")
    except Exception:
        return _SYSTEM

GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# v7.8: the Meta Model API (OpenAI-compatible) — Muse
# Wonder's bench transport rides the same streamed call
# as Groq/OpenRouter.
MUSE_BASE = "https://api.meta.ai/v1"
MUSE_DEFAULT_MODEL = "muse-wonder-1.0"
GLM_MODELS = ("z-ai/glm-5.2", "z-ai/glm-5.2:free")

CANDIDATE_BUDGET_S = 15.0    # per candidate, all prompts
TEST_BUDGET_S = 170.0        # the whole test
_MAX_TOKENS = 400            # same cap as the agent path
# v7.5: an Ollama candidate's FIRST call may take this much
# EXTRA time — a cold local model spends tens of seconds
# just loading into VRAM before its first token (the field
# test's qwen3:8b ReadTimeout at the plain 15 s cap,
# 2026-11-16 09:10 IST). A first call that still times out
# is reported as "timeout — cold load?", distinct from a
# hard failure. The whole test stays inside TEST_BUDGET_S.
OLLAMA_FIRST_CALL_EXTRA_S = 45.0

_run_lock = threading.Lock()
_state_lock = threading.Lock()
_state = {"running": False, "at": None, "rows": [],
          "lines": [], "error": None}


def _lb(text):
    """One [brainbench] line into the logbook (guarded) —
    the logbook file is what the log sync carries home."""
    try:
        import logbook
        logbook.log("BRAIN", text)
    except Exception:
        pass
    log.info("%s", text)


# ------------------------------------------------------------ candidates
def _cfg_candidates(cfg, single_key, list_key):
    """The candidate set for one provider from config: the
    single model + the configured list + the shipped
    defaults list, de-duplicated, order preserved. (The
    benchmark measures the SET the walk can pick from;
    the remembered head's position is irrelevant here.)"""
    out = []
    try:
        import config as _cfg_mod
        defaults = _cfg_mod.DEFAULTS
    except Exception:
        defaults = {}
    head = str(cfg.get(single_key)
               or defaults.get(single_key) or "").strip()
    if head:
        out.append(head)
    for raw in (cfg.get(list_key), defaults.get(list_key)):
        if isinstance(raw, str):
            raw = [p for p in raw.replace("\n", ",").split(",")]
        if isinstance(raw, (list, tuple)):
            for item in raw:
                name = str(item or "").strip()
                if name and name not in out:
                    out.append(name)
    return out


def _groq_account_models(cfg):
    """The Groq account's own model list (v7.5), ordered as
    the /models endpoint returned it — or None when the
    fetch fails for any reason (no key, non-200, network),
    in which case the bench keeps its v7.4 behaviour. One
    short guarded call; the bench is the only caller."""
    key = str(cfg.get("groq_api_key") or "").strip()
    if not key:
        return None
    try:
        import requests
        resp = requests.get(
            GROQ_BASE + "/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=5)
        if resp.status_code != 200:
            return None
        out = []
        for item in (resp.json().get("data") or []):
            mid = str(item.get("id") or "").strip()
            if mid.startswith("models/"):
                mid = mid[len("models/"):]
            if mid and mid not in out:
                out.append(mid)
        return out or None
    except Exception:
        return None


def _discovered_groq_rows(cfg, configured):
    """The bench's Groq rows under self-discovery (v7.5):
    the configured names in configured order — the ones
    the account HAS are measured, the ones it lacks are
    reported "not on this account" without a call — plus
    up to 3 chat-capable models the account has that the
    config never named (instant-class first). Returns
    None when the account list is unavailable."""
    account = _groq_account_models(cfg)
    if account is None:
        return None
    try:
        import brain as _brain
        _key = _brain._model_key
        _chat = _brain._chat_capable
        _inst = _brain._is_instant_class
    except Exception:
        def _key(m):
            return str(m or "").strip()
        def _chat(m):
            return bool(str(m or "").strip())
        def _inst(m):
            return "instant" in str(m or "").lower()
    account_keys = {_key(m) for m in account}
    rows = []
    for model in configured:
        if _key(model) in account_keys:
            rows.append(("Groq", "groq", model, ""))
        else:
            rows.append(("Groq", "groq", model,
                         "not on this account"))
    configured_keys = {_key(m) for m in configured}
    extras = [m for m in account
              if _key(m) not in configured_keys
              and _chat(m)]
    extras.sort(key=lambda m: 0 if _inst(m) else 1)
    for model in extras[:3]:
        rows.append(("Groq", "groq", model, ""))
    return rows


def collect_candidates(cfg):
    """[(provider_label, kind, model, note)] — kind is
    "groq" / "openrouter" / "ollama" / "muse"; note is a
    skip reason for rows that must be REPORTED without a
    call (no OpenRouter key / Ollama not answering / no
    Muse API key), else "". Never raises."""
    rows = []
    try:
        _groq_configured = _cfg_candidates(cfg, "groq_model",
                                           "groq_models")
        if not str(cfg.get("groq_api_key") or "").strip():
            # v7.5: no key — the rows REPORT the gap, no
            # network call is made (v7.4 attempted and the
            # field table filled with 401 noise).
            for model in _groq_configured:
                rows.append(("Groq", "groq", model,
                             "no Groq key"))
        else:
            _disc_rows = _discovered_groq_rows(
                cfg, _groq_configured)
            if _disc_rows is not None:
                rows.extend(_disc_rows)
            else:
                for model in _groq_configured:
                    rows.append(("Groq", "groq", model, ""))
    except Exception:
        pass
    try:
        or_key = str(cfg.get("openrouter_api_key")
                     or "").strip()
        if or_key:
            models = _cfg_candidates(cfg, "openrouter_model",
                                     "openrouter_models")
            for glm in GLM_MODELS:
                if glm not in models:
                    models.append(glm)
            for model in models:
                rows.append(("OpenRouter", "openrouter",
                             model, ""))
        else:
            for glm in GLM_MODELS:
                rows.append(("OpenRouter", "openrouter", glm,
                             "no OpenRouter key"))
    except Exception:
        pass
    try:
        # v7.8: Muse Wonder — one candidate (the
        # configured model), called ONLY with its key
        # configured; without one the row reports the gap
        # and api.meta.ai is never touched.
        muse_model = str(cfg.get("muse_model")
                         or MUSE_DEFAULT_MODEL).strip() \
            or MUSE_DEFAULT_MODEL
        if str(cfg.get("muse_api_key") or "").strip():
            rows.append(("Muse Wonder", "muse", muse_model,
                         ""))
        else:
            rows.append(("Muse Wonder", "muse", muse_model,
                         "no Muse API key"))
    except Exception:
        pass
    try:
        models = _cfg_candidates(cfg, "ollama_model",
                                 "ollama_models")
        if models:
            if _ollama_answers(cfg):
                for model in models:
                    rows.append(("Ollama", "ollama", model, ""))
            else:
                for model in models:
                    rows.append(("Ollama", "ollama", model,
                                 "Ollama not running"))
    except Exception:
        pass
    return rows


def _ollama_answers(cfg):
    """True when the local Ollama server answers /api/tags
    (a 2 s probe — the benchmark's only liveness check)."""
    try:
        import requests
        url = str(cfg.get("ollama_url",
                          "http://localhost:11434")).rstrip("/")
        resp = requests.get(url + "/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


# ------------------------------------------------------------ transports
# Each transport returns (reply_text, ttft_s, total_s) and
# raises on any failure. budget_s caps the whole call.
# Tests monkeypatch these two functions with fakes.
def _call_openai_compatible(base_url, key, model, prompt,
                            budget_s):
    """One streamed chat completion against an
    OpenAI-compatible endpoint (Groq / OpenRouter).
    ttft = time to the first content chunk."""
    import requests
    t0 = time.monotonic()
    deadline = t0 + max(1.0, budget_s)
    resp = requests.post(
        base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={"model": model,
              "messages": [
                  {"role": "system",
                   "content": _ACTIVE_SYSTEM or _SYSTEM},
                  {"role": "user", "content": prompt}],
              "max_tokens": _MAX_TOKENS,
              "stream": True},
        timeout=(3.0, max(1.0, budget_s)), stream=True)
    try:
        if resp.status_code != 200:
            snippet = ""
            try:
                snippet = (resp.text or "")[:120]
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {resp.status_code} {snippet}".strip())
        ttft = None
        parts = []
        for line in resp.iter_lines(decode_unicode=True):
            if time.monotonic() > deadline:
                raise TimeoutError("call budget spent")
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                import json
                chunk = json.loads(data)
                delta = (chunk["choices"][0].get("delta")
                         or {})
                piece = delta.get("content") or ""
            except Exception:
                continue
            if piece:
                if ttft is None:
                    ttft = time.monotonic() - t0
                parts.append(piece)
        total = time.monotonic() - t0
        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("empty reply")
        return text, (ttft if ttft is not None else total), total
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _call_ollama(base_url, model, prompt, budget_s):
    """One streamed /api/chat call against local Ollama.
    Same return shape as _call_openai_compatible."""
    import json
    import requests
    t0 = time.monotonic()
    deadline = t0 + max(1.0, budget_s)
    resp = requests.post(
        base_url + "/api/chat",
        json={"model": model,
              "messages": [
                  {"role": "system",
                   "content": _ACTIVE_SYSTEM or _SYSTEM},
                  {"role": "user", "content": prompt}],
              "stream": True},
        timeout=(3.0, max(1.0, budget_s)), stream=True)
    try:
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        ttft = None
        parts = []
        for line in resp.iter_lines(decode_unicode=True):
            if time.monotonic() > deadline:
                raise TimeoutError("call budget spent")
            if not line:
                continue
            try:
                chunk = json.loads(line)
                piece = ((chunk.get("message") or {})
                         .get("content") or "")
            except Exception:
                continue
            if piece:
                if ttft is None:
                    ttft = time.monotonic() - t0
                parts.append(piece)
            if chunk.get("done"):
                break
        total = time.monotonic() - t0
        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("empty reply")
        return text, (ttft if ttft is not None else total), total
    finally:
        try:
            resp.close()
        except Exception:
            pass


# ------------------------------------------------------------ scoring
def _bengali_ratio(text):
    """Bengali-script letters / all letters (0..1)."""
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    bn = sum(1 for ch in letters
             if 0x0980 <= ord(ch) <= 0x09FF)
    return bn / len(letters)


def _guards_pass(replies):
    """Every reply passes the live brain's script guard
    and the Bengali language guard (pref "bn")."""
    try:
        import brain as _brain
        for reply in replies:
            if not _brain._reply_script_ok(reply):
                return False
            if _brain._reply_wrong_language(reply, "bn"):
                return False
        return True
    except Exception:
        return False


def _median(values):
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def _skipped_row(kind, model, reason):
    """A reported-without-a-call row (v7.5)."""
    return {
        "provider": kind, "model": model,
        "status": f"skipped — {reason}",
        "answered": 0, "prompts": len(PROMPTS),
        "ttft_s": None, "total_s": None,
        "bn_ratio": 0.0, "guard_pass": False,
        "note": "",
    }


def _run_candidate(cfg, kind, model, test_deadline):
    """Measure one candidate. Returns its row dict."""
    # v7.5: a keyed provider with NO key configured is
    # reported, never called — defence in depth behind
    # collect_candidates' own skip notes (the field's 401
    # noise came from rows that reached the transport with
    # an empty key).
    if kind in ("groq", "openrouter", "muse"):
        _field = {"groq": "groq_api_key",
                  "openrouter": "openrouter_api_key",
                  "muse": "muse_api_key"}[kind]
        _reason = {"groq": "no Groq key",
                   "openrouter": "no OpenRouter key",
                   "muse": "no Muse API key"}[kind]
        if not str(cfg.get(_field) or "").strip():
            return _skipped_row(kind, model, _reason)
    if kind == "groq":
        key = str(cfg.get("groq_api_key") or "").strip()

        def call(prompt, budget):
            return _call_openai_compatible(
                GROQ_BASE, key, model, prompt, budget)
    elif kind == "openrouter":
        key = str(cfg.get("openrouter_api_key") or "").strip()

        def call(prompt, budget):
            return _call_openai_compatible(
                OPENROUTER_BASE, key, model, prompt, budget)
    elif kind == "muse":
        key = str(cfg.get("muse_api_key") or "").strip()

        def call(prompt, budget):
            return _call_openai_compatible(
                MUSE_BASE, key, model, prompt, budget)
    else:
        url = str(cfg.get("ollama_url",
                          "http://localhost:11434")).rstrip("/")

        def call(prompt, budget):
            return _call_ollama(url, model, prompt, budget)
    budget_end = min(time.monotonic() + CANDIDATE_BUDGET_S,
                     test_deadline)
    replies = []
    ttfts = []
    totals = []
    timed_out = False
    cold_timeout = False
    last_error = ""
    for _idx, (_name, prompt) in enumerate(PROMPTS):
        # v7.5: an Ollama candidate's FIRST call gets the
        # cold-load allowance on top of the candidate
        # budget (still bounded by the whole-test deadline).
        _end = budget_end
        if kind == "ollama" and _idx == 0:
            _end = min(budget_end + OLLAMA_FIRST_CALL_EXTRA_S,
                       test_deadline)
        remaining = _end - time.monotonic()
        if remaining <= 0.25:
            timed_out = True
            break
        try:
            text, ttft, total = call(prompt, remaining)
            replies.append(text)
            ttfts.append(ttft)
            totals.append(total)
        except TimeoutError:
            timed_out = True
            last_error = "timeout"
            if kind == "ollama" and _idx == 0:
                # The model may simply still be loading —
                # reported distinctly from a hard timeout.
                cold_timeout = True
            break
        except Exception as exc:
            # requests spells a read timeout as an exception
            # class of its own, not TimeoutError — the same
            # cold-load reading applies when a local model's
            # first call dies that way.
            if kind == "ollama" and _idx == 0 \
                    and "timeout" in type(exc).__name__.lower():
                timed_out = True
                cold_timeout = True
                last_error = "timeout"
                break
            last_error = f"{type(exc).__name__}: {exc}"[:80]
            break
    if len(replies) == len(PROMPTS):
        status = "ok"
    elif replies:
        status = "partial"
    elif cold_timeout:
        status = "timeout — cold load?"
    elif timed_out:
        status = "timeout"
    else:
        status = "failed"
    return {
        "provider": kind, "model": model, "status": status,
        "answered": len(replies), "prompts": len(PROMPTS),
        "ttft_s": _median(ttfts),
        "total_s": (sum(totals) / len(totals)) if totals else None,
        "bn_ratio": _bengali_ratio(" ".join(replies)),
        "guard_pass": bool(replies) and _guards_pass(replies),
        "note": last_error if status in (
            "failed", "timeout", "timeout — cold load?")
        else "",
    }


def format_row(row):
    """One compact [brainbench] line for a result row."""
    label = {"groq": "Groq", "openrouter": "OpenRouter",
             "ollama": "Ollama",
             "muse": "Muse Wonder"}.get(row.get("provider"),
                                        row.get("provider",
                                                "?"))
    head = f"[brainbench] {label} · {row.get('model', '?')} — "
    status = row.get("status", "?")
    if status.startswith("skipped"):
        return head + status
    parts = [f"{status} {row.get('answered', 0)}/"
             f"{row.get('prompts', len(PROMPTS))}"]
    if row.get("ttft_s") is not None:
        parts.append(f"first token {row['ttft_s']:.2f}s")
    if row.get("total_s") is not None:
        parts.append(f"reply {row['total_s']:.2f}s")
    if status in ("ok", "partial"):
        parts.append(f"Bengali {round(100 * row.get('bn_ratio', 0))}%")
        parts.append("guards ✓" if row.get("guard_pass")
                     else "guards ✗")
    if row.get("note"):
        parts.append(row["note"])
    return head + " · ".join(parts)


# ------------------------------------------------------------ the test
def run_benchmark(cfg):
    """Run the whole test NOW (blocking; bounded by
    TEST_BUDGET_S). Returns {"rows", "lines", "at"} and
    mirrors the table into the logbook. Guarded: a
    failure inside still returns a result dict."""
    cfg = dict(cfg or {})
    # v7.6: this run's requests carry the production
    # system text (see _production_system); cleared on
    # the way out so nothing outside a run inherits it.
    global _ACTIVE_SYSTEM
    _ACTIVE_SYSTEM = _production_system(cfg)
    started = time.monotonic()
    deadline = started + TEST_BUDGET_S
    rows = []
    lines = []
    candidates = collect_candidates(cfg)
    header = (f"[brainbench] Brain Test started — "
              f"{len(candidates)} candidates, "
              f"{len(PROMPTS)} Bengali prompts each")
    lines.append(header)
    _lb(header)
    for label, kind, model, skip_note in candidates:
        if skip_note:
            row = {"provider": kind, "model": model,
                   "status": f"skipped — {skip_note}",
                   "answered": 0, "prompts": len(PROMPTS),
                   "ttft_s": None, "total_s": None,
                   "bn_ratio": 0.0, "guard_pass": False,
                   "note": ""}
        elif time.monotonic() > deadline:
            row = {"provider": kind, "model": model,
                   "status": "skipped — test budget spent",
                   "answered": 0, "prompts": len(PROMPTS),
                   "ttft_s": None, "total_s": None,
                   "bn_ratio": 0.0, "guard_pass": False,
                   "note": ""}
        else:
            try:
                row = _run_candidate(cfg, kind, model, deadline)
            except Exception as exc:  # never take Nalox down
                row = {"provider": kind, "model": model,
                       "status": "failed",
                       "answered": 0, "prompts": len(PROMPTS),
                       "ttft_s": None, "total_s": None,
                       "bn_ratio": 0.0, "guard_pass": False,
                       "note": f"{type(exc).__name__}: {exc}"[:80]}
        rows.append(row)
        line = format_row(row)
        lines.append(line)
        _lb(line)
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    fastest = None
    if ok_rows:
        fastest = min(ok_rows,
                      key=lambda r: (r.get("ttft_s")
                                     if r.get("ttft_s") is not None
                                     else 999.0))
    took = time.monotonic() - started
    if fastest is not None:
        footer = (f"[brainbench] Brain Test done in "
                  f"{took:.0f}s — fastest full pass: "
                  f"{fastest['provider']} · {fastest['model']} "
                  f"(first token {fastest['ttft_s']:.2f}s)")
    else:
        footer = (f"[brainbench] Brain Test done in "
                  f"{took:.0f}s — no candidate completed "
                  f"the full set")
    lines.append(footer)
    _lb(footer)
    _ACTIVE_SYSTEM = None
    return {"rows": rows, "lines": lines, "at": time.time()}


def is_running():
    with _state_lock:
        return bool(_state.get("running"))


def last_results():
    """A copy of the latest state for the UI:
    {"running", "at", "rows", "lines", "error"}."""
    with _state_lock:
        return {"running": bool(_state.get("running")),
                "at": _state.get("at"),
                "rows": list(_state.get("rows") or []),
                "lines": list(_state.get("lines") or []),
                "error": _state.get("error")}


def start_benchmark(cfg, on_done=None):
    """Start the test on a daemon thread. Returns False
    when a test is already running (the refusal the UI
    shows), True when this call started it. The thread is
    fully guarded — its failure is recorded in the state,
    never raised."""
    if not _run_lock.acquire(blocking=False):
        return False
    with _state_lock:
        _state["running"] = True
        _state["error"] = None

    def _work():
        result = None
        try:
            result = run_benchmark(cfg)
        except Exception as exc:  # crash-guard: record, never raise
            with _state_lock:
                _state["error"] = (
                    f"{type(exc).__name__}: {exc}")[:160]
            _lb(f"[brainbench] Brain Test crashed — "
                f"{type(exc).__name__}: {exc}"[:160])
        finally:
            with _state_lock:
                _state["running"] = False
                if result is not None:
                    _state["rows"] = result.get("rows", [])
                    _state["lines"] = result.get("lines", [])
                    _state["at"] = result.get("at")
            _run_lock.release()
            if on_done is not None:
                try:
                    on_done(last_results())
                except Exception:
                    pass

    try:
        threading.Thread(target=_work, daemon=True,
                         name="nalox-brainbench").start()
    except Exception:
        with _state_lock:
            _state["running"] = False
        _run_lock.release()
        return False
    return True
