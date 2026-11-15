"""⚡ Nalox Level (v6.0) — measured speed, shown honestly.

The owner asked for two things: Nalox should keep getting
faster, and the Command Center should SHOW a level that
reflects how fast Nalox actually is right now. This module
is the measuring stick:

* nalox.py records one timing sample per command (the same
  numbers as the [timing] log line: record / transcribe /
  brain / speak seconds).
* brain.py records every provider attempt's latency and
  outcome here.
* compute_level() — a PURE function over those samples —
  turns them into a 1-10 level, a word (Slow / Fast /
  Lightning) and ONE line naming the current bottleneck.
  The dashboard renders current_level(); the tests drive
  compute_level() directly.
* provider_avg() feeds brain's adaptive ordering: while
  FreeLLMAPI's recent average answer time is slow, the
  agent tries the fastest healthy direct provider first
  (the owner's FreeLLMAPI-first preference holds whenever
  the router is performing).

Nothing here does I/O; the deques are the only state.
"""

from collections import deque

_MAX_SAMPLES = 40
_samples = deque(maxlen=_MAX_SAMPLES)
_MAX_OUTCOMES = 8
_providers = {}  # name -> deque of (seconds, ok)


# ------------------------------------------------------------ recording
def record_sample(record_s=None, transcribe_s=None,
                  brain_s=None, speak_s=None):
    """One command's phase timings (seconds; None = phase
    didn't happen). Called by nalox.py where the [timing]
    line is written."""
    _samples.append({
        "record": record_s, "transcribe": transcribe_s,
        "brain": brain_s, "speak": speak_s,
    })


def record_provider(name, seconds, ok=True):
    """One brain-provider attempt: latency + outcome."""
    if not name:
        return
    dq = _providers.setdefault(name, deque(maxlen=_MAX_OUTCOMES))
    try:
        dq.append((float(seconds), bool(ok)))
    except Exception:
        pass


def reset():
    """Tests / a fresh session: forget everything measured."""
    _samples.clear()
    _providers.clear()


# ------------------------------------------------------------ provider stats
def provider_avg(name, min_samples=1):
    """Average latency of the provider's recent SUCCESSFUL
    answers, or None when there aren't enough of them.
    Failures never count — a dead key fails fast, and fast
    failure must not look like speed."""
    dq = _providers.get(name)
    if not dq:
        return None
    good = [s for s, ok in dq if ok]
    if len(good) < max(1, min_samples):
        return None
    return sum(good) / len(good)


def provider_failing(name):
    """True when the provider's last few attempts all
    failed (nothing succeeded recently)."""
    dq = _providers.get(name)
    if not dq or len(dq) < 2:
        return False
    recent = list(dq)[-3:]
    return all(not ok for _s, ok in recent)


def provider_health():
    """Snapshot for compute_level: {name: {"avg": s|None,
    "failing": bool}}."""
    return {name: {"avg": provider_avg(name),
                   "failing": provider_failing(name)}
            for name in _providers}


# ------------------------------------------------------------ the level
def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def _phase_points(value, stops):
    """Map a phase median to its points: stops are
    (limit_seconds, points) pairs, best first."""
    if value is None:
        return None
    for limit, points in stops:
        if value <= limit:
            return points
    return stops[-1][1] * 0.25


# Weights: brain 4, transcribe 3, speak 2, record 1 = 10.
_PHASES = (
    ("brain", 4.0, ((1.5, 4.0), (4.0, 3.2), (8.0, 2.4),
                    (15.0, 1.2), (30.0, 0.5)),
     "Brain chain is the slow part right now"),
    ("transcribe", 3.0, ((1.0, 3.0), (2.5, 2.4), (5.0, 1.5),
                         (10.0, 0.6)),
     "Hearing (transcription) is the slow part"),
    ("speak", 2.0, ((1.5, 2.0), (3.0, 1.6), (6.0, 1.0),
                    (12.0, 0.4)),
     "Speaking startup is the slow part"),
    ("record", 1.0, ((2.0, 1.0), (4.0, 0.8), (7.0, 0.5),
                     (12.0, 0.25)),
     "Listening pauses are the slow part"),
)


def _level_calc(samples, health=None):
    """compute_level + the raw score: (level, word,
    bottleneck_line, raw_total). raw_total is the unrounded
    0–10 score AFTER the failing-brain cap — the header's
    progress bar reads its fractional part as "progress to
    the next level" (v6.2)."""
    samples = [s for s in (samples or []) if isinstance(s, dict)]
    if not samples:
        return (0, "Warming up", "No commands measured yet "
                                 "this session", 0.0)
    total = 0.0
    measured_weight = 0.0
    worst_ratio = -1.0
    worst_line = "All fast — nothing is holding Nalox back"
    for key, weight, stops, line in _PHASES:
        med = _median([s.get(key) for s in samples])
        pts = _phase_points(med, stops)
        if pts is None:
            continue
        total += pts
        measured_weight += weight
        lost_ratio = (weight - pts) / weight
        if lost_ratio > worst_ratio:
            worst_ratio = lost_ratio
            worst_line = line
    if 0 < measured_weight < 10.0:
        # A phase with no samples yet (e.g. text-only
        # commands have no record phase) must not drag the
        # level down — score what was measured, scaled.
        total = total * 10.0 / measured_weight
    raw = max(1.0, min(10.0, total))
    level = int(round(raw))
    failing_brain = False
    if health:
        any_failing = any(
            isinstance(h, dict) and h.get("failing")
            for h in health.values())
        any_success = any(
            isinstance(h, dict) and h.get("avg") is not None
            for h in health.values())
        # Cap only when the brain AS A WHOLE is failing —
        # one dead provider in a chain that still answers is
        # a Settings matter, not a speed lie.
        failing_brain = any_failing and not any_success
    if failing_brain:
        level = min(level, 3)
        raw = min(raw, 3.0)
        worst_line = ("A brain provider is failing — check "
                      "its key in Settings")
    if level >= 8 and not failing_brain and worst_ratio <= 0.35:
        # Genuinely nothing is dragging: every measured
        # phase is near its best. (A high total with one
        # bad phase keeps that phase's bottleneck line.)
        worst_line = "All fast — nothing is holding Nalox back"
    if level >= 8:
        word = "Lightning"
    elif level >= 4:
        word = "Fast"
    else:
        word = "Slow"
    return (level, word, worst_line, raw)


def compute_level(samples, health=None):
    """PURE: (level, word, bottleneck_line).

    samples: list of dicts with any of record/transcribe/
    brain/speak in seconds. health: provider_health()-shaped
    dict (optional). Level is 1-10 once at least one sample
    exists; with no samples it is 0 ("Warming up"). A brain
    provider that is outright failing caps the level at 3 —
    speed claims would be a lie while answers fail."""
    level, word, line, _raw = _level_calc(samples, health)
    return (level, word, line)


def level_progress():
    """(level, word, frac_to_next) for the Command Center's
    BIG header Level (v6.2): the integer level, its word,
    and how far the raw score has travelled toward the NEXT
    level (0.0–1.0; 1.0 at level 10, 0.0 while warming up)."""
    level, word, _line, raw = _level_calc(list(_samples),
                                          provider_health())
    if level <= 0:
        return (0, word, 0.0)
    if level >= 10:
        return (level, word, 1.0)
    frac = raw - int(raw)
    return (level, word, max(0.0, min(1.0, frac)))


def current_level():
    """The dashboard's one call: compute_level over the
    live rolling state."""
    return compute_level(list(_samples), provider_health())


def level_line():
    """The SYSTEM-panel one-liner, e.g.
    "⚡ Nalox Level: 7/10 Fast — Brain chain is the slow
    part right now"."""
    level, word, line = current_level()
    if level <= 0:
        return f"⚡ Nalox Level: — ({word})"
    return f"⚡ Nalox Level: {level}/10 {word} — {line}"
