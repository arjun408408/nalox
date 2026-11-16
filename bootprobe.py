#!/usr/bin/env python3
"""Boot readiness probe coordinator (v7.11 — "Ready Means Ready").

WHY THIS MODULE EXISTS (the owner's diagnosis, 2026-11-16
14:59 IST, read off his own log): Nalox used to declare
"[ready]" while half its subsystems were still starting —
Gemini's dead-model hops, the Ollama auto-start and the
provider checks all landed MID-CONVERSATION, so his first
words paid for boot work and sometimes got no reply at all.
His order: on start, a loading screen with real progress;
during loading EVERY provider/subsystem is probed — what
works is marked working, what fails is marked failed and
skipped at talk time; only at 100% does the Command Center
open, fully ready. ALL models stay (nothing is deleted) —
the probe only checks, orders and marks.

This module is the pure coordination logic — no Tk, no
network, no nalox imports — so the test suites can pin the
gate semantics headlessly. nalox.py supplies one probe
function per stage (they wrap the EXISTING readiness
signals: the ears lane clients' ping lifecycle proof, the
Brain's validation thread, sounddevice's device pick, the
phone link's local state) and loadscreen.py renders the
state this coordinator publishes.

STAGE MODEL. Every stage resolves EXACTLY ONCE for the
gate: "ok" (✓), "warn" (⚠) and "fail" (✗) are all
resolutions — a failed stage never blocks the interface,
it is simply known-bad before the first word is spoken.
A stage that outlives its own timeout, or is still
pending when the gate's hard cap lands, is resolved as a
CAPPED warn ("still warming — will finish in
background"); its probe thread keeps running and its real
result, when it lands, replaces the capped warn in the
record (the gate count does not move — progress is
monotonic by construction).

THE GATE. wait_gate() blocks until every registered
stage has resolved or the cap (GATE_CAP_S from process
start) passes. Blocking vs non-blocking stages differ
only in what the loading screen emphasises — the gate
itself waits for ALL of them, because a resolved ✗ is
just as final as a ✓, and the cap guarantees the wait
cannot outlive GATE_CAP_S. An optional abort callback (the
loading UI reporting its own death) ends the wait early:
the caller then falls back to the pre-v7.11 boot
behaviour. Nothing in here ever raises into the caller.

v8.0: the gate gained THREE blocking stages that test the
system END TO END instead of only asking whether pieces
answer — "bigmodel" (the command lane's big transcription
model is LOADED, not merely loadable), "earstest" (one
real decode job completes through the command lane) and
"braintest" (one real minimal completion comes back from
the session's lead brain). The field lesson (v7.11
session, 2026-11-16): the probe declared 11/11 in ~6 s
while the big model was still loading, and the owner's
first hello died on an empty transcription. The cap rises
45 s → 180 s — the owner ordered real readiness over a
fast open ("loading যেন অনেকক্ষণ হয়... running test
একদম complete"). Per-stage deadlines still resolve a
stage as a warning under the gate cap, so a true hang
can never lock him out.

v9.0: the EARS ARE GONE (owner's text-first order) — the
four ears stages ("wake", "command", "bigmodel",
"earstest") are REMOVED from the stage set; there is no
local transcription model left to load or test. The mic
stage now means "a microphone is available for one-shot
dictation". "braintest" (one real completion from the
lead brain) stays — it is a brain check, not an ears
check. With the slow model-load stages gone the cap
drops 180 s → 90 s: the slowest remaining probes are the
Ollama check (40 s) and the brain answer test (30 s).
"""

import threading
import time

# The hard cap: the interface opens GATE_CAP_S after
# process start even if some stages are still warming.
# v8.0: 45 s → 180 s — the real-readiness stages (big
# model load + running tests) legitimately take longer
# than the v7.11 presence checks did, and the owner
# ordered the wait.
# v9.0: 180 s → 90 s — the ears stages (the slow ones)
# are gone with the ears; the slowest remaining probes
# are Ollama (40 s) and the brain answer test (30 s).
GATE_CAP_S = 90.0

STILL_WARMING = "still warming — will finish in background"

# (key, display label, blocking) — the fixed stage set,
# in display order. Blocking = the interface's promise
# (mic, brain, voice); the rest resolve or fail beside
# them and never hold the gate past the cap.
STAGE_DEFS = (
    # v9.0: "mic" = a microphone is available for one-shot
    # dictation. The v7.11/v8.0 ears stages (wake / command
    # / bigmodel / earstest) are REMOVED — the local Whisper
    # fleet they probed no longer exists.
    ("mic", "Microphone", True),
    ("groq", "Groq brain", True),
    ("braintest", "Brain answer test", True),
    ("voice", "Voice", True),
    ("gemini", "Gemini", False),
    ("freellm", "FreeLLMAPI", False),
    ("ollama", "Ollama (offline brain)", False),
    ("muse", "Muse Wonder", False),
    ("phone", "Phone link", False),
    ("telegram", "Telegram", False),
)

_STATUSES = ("ok", "warn", "fail")


class BootProbe:
    """Coordinates the boot stage probes (v7.11).

    on_update, when given, is called with
    (snapshot, progress) after every resolution — it is
    invoked OUTSIDE the lock and its failures are
    swallowed (a broken renderer must never break the
    gate). snapshot is a list of per-stage dicts in
    STAGE_DEFS order: {key, label, blocking, status,
    detail, resolved, capped}; status is "pending"
    until resolution.
    """

    def __init__(self, stage_defs=STAGE_DEFS, on_update=None,
                 clock=time.monotonic):
        self._clock = clock
        self._on_update = on_update
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stages = {}
        for key, label, blocking in stage_defs:
            self._stages[key] = {
                "key": key, "label": label,
                "blocking": bool(blocking),
                "status": "pending", "detail": "",
                "resolved": False, "capped": False,
                "deadline": None,
            }
        self._order = [k for k, _l, _b in stage_defs]
        self._resolved_count = 0
        self._gate_result = None

    # ------------------------------------------------ stages
    def start_stage(self, key, fn, timeout_s=30.0):
        """Run one stage's probe on a daemon thread.

        fn() returns (status, detail); an exception
        inside fn resolves the stage as "fail" with the
        exception's short name — a crashed probe is a
        KNOWN failure, never a hung gate. The stage's
        own timeout is enforced by the gate loop (the
        thread itself is never killed — Python cannot —
        its late result still lands via the capped-warn
        replacement rule). Unknown keys and double
        starts are ignored. Never raises.
        """
        try:
            with self._cond:
                stage = self._stages.get(key)
                if stage is None or stage.get("_started"):
                    return False
                stage["_started"] = True
                stage["deadline"] = self._clock() \
                    + max(1.0, float(timeout_s))

            def _run():
                try:
                    out = fn()
                    status, detail = out
                except Exception as exc:
                    status = "fail"
                    detail = (f"{type(exc).__name__}: "
                              f"{exc}")[:90]
                if status not in _STATUSES:
                    status = "warn"
                self._resolve(key, str(status),
                              str(detail or "")[:140])

            threading.Thread(target=_run, daemon=True,
                             name=f"nalox-bootprobe-{key}"
                             ).start()
            return True
        except Exception:
            return False

    def _resolve(self, key, status, detail, capped=False):
        """Record one stage's resolution (internal).

        First resolution wins and moves the gate count —
        EXCEPT that a capped warn (the gate's timeout
        placeholder) may be replaced ONCE by the stage's
        real late result, which updates status/detail
        without moving the count (progress stays
        monotonic)."""
        notify = False
        with self._cond:
            stage = self._stages.get(key)
            if stage is None:
                return
            if not stage["resolved"]:
                stage["resolved"] = True
                stage["status"] = status
                stage["detail"] = detail
                stage["capped"] = bool(capped)
                self._resolved_count += 1
                notify = True
            elif stage["capped"] and not capped:
                stage["status"] = status
                stage["detail"] = detail
                stage["capped"] = False
                notify = True
            if notify:
                self._cond.notify_all()
        if notify:
            self._emit()

    def _emit(self):
        cb = self._on_update
        if cb is None:
            return
        try:
            cb(self.snapshot(), self.progress())
        except Exception:
            pass

    # ------------------------------------------------ reads
    def snapshot(self):
        """The stages as display-ready dicts (copies)."""
        with self._lock:
            return [{k: st[k] for k in
                     ("key", "label", "blocking", "status",
                      "detail", "resolved", "capped")}
                    for st in (self._stages[k]
                               for k in self._order)]

    def progress(self):
        """Resolved / total, in [0.0, 1.0]. Monotonic:
        the count only ever grows."""
        with self._lock:
            total = len(self._order) or 1
            return self._resolved_count / total

    def all_resolved(self):
        with self._lock:
            return self._resolved_count >= len(self._order)

    def stage(self, key):
        """One stage's dict (a copy), or None."""
        with self._lock:
            st = self._stages.get(key)
            if st is None:
                return None
            return {k: st[k] for k in
                    ("key", "label", "blocking", "status",
                     "detail", "resolved", "capped")}

    # ------------------------------------------------ the gate
    def wait_gate(self, cap_deadline, abort=None):
        """Block until every stage resolves, the cap
        lands, or abort() says stop.

        cap_deadline is an ABSOLUTE time on this
        probe's clock (process start + GATE_CAP_S).
        Stages past their own per-stage deadline are
        capped-warned as the loop passes them; at the
        cap, every still-pending stage is capped-warned
        at once. Returns "ready" (all really resolved),
        "capped" (the gate opened on placeholders) or
        "aborted" (the abort callback fired — the
        caller falls back to pre-v7.11 boot behaviour).
        Never raises.
        """
        try:
            while True:
                changed = False
                result = None
                with self._cond:
                    if self._resolved_count >= len(self._order):
                        result = "capped" if any(
                            self._stages[k]["capped"]
                            for k in self._order) else "ready"
                        self._gate_result = result
                        return result
                    now = self._clock()
                    # Per-stage deadlines: a stage that
                    # outlives its own timeout resolves
                    # as a capped warn (its thread may
                    # still land the real result later).
                    for key in self._order:
                        st = self._stages[key]
                        if not st["resolved"] \
                                and st["deadline"] is not None \
                                and now >= st["deadline"]:
                            st["resolved"] = True
                            st["status"] = "warn"
                            st["detail"] = STILL_WARMING
                            st["capped"] = True
                            self._resolved_count += 1
                            changed = True
                    if self._resolved_count < len(self._order) \
                            and now >= cap_deadline:
                        for key in self._order:
                            st = self._stages[key]
                            if not st["resolved"]:
                                st["resolved"] = True
                                st["status"] = "warn"
                                st["detail"] = STILL_WARMING
                                st["capped"] = True
                                self._resolved_count += 1
                                changed = True
                    if self._resolved_count >= len(self._order):
                        self._gate_result = "capped"
                        result = "capped"
                    else:
                        # Sleep until the nearest
                        # interesting moment, in short
                        # slices so the abort callback
                        # stays responsive.
                        waits = [cap_deadline - now]
                        for key in self._order:
                            st = self._stages[key]
                            if not st["resolved"] \
                                    and st["deadline"] \
                                    is not None:
                                waits.append(
                                    st["deadline"] - now)
                        slice_s = min(0.25, max(
                            0.02, min(waits)))
                        self._cond.wait(timeout=slice_s)
                # Emits happen OUTSIDE the lock (the
                # snapshot re-acquires it).
                if changed:
                    self._emit()
                if result is not None:
                    return result
                if abort is not None:
                    try:
                        if abort():
                            self._gate_result = "aborted"
                            return self._gate_result
                    except Exception:
                        pass
        except Exception:
            # The gate itself must never brick startup:
            # an internal failure reads as an abort and
            # the caller boots the old way.
            self._gate_result = "aborted"
            return self._gate_result

    @property
    def gate_result(self):
        return self._gate_result
