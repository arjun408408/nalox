"""Recurring scheduled tasks for Nalox (v4.3) — OpenJarvis's
scheduler, deliberately shrunk to what Arjun actually asked for.

A task is stored in scheduled_tasks.json:

    {"id": 1, "action": "check_youtube_comments",
     "label": "check my YouTube comments",
     "time": "08:00", "days": "daily" | "weekdays",
     "channel": "speak" | "telegram" | "both",
     "last_run": "2026-11-15" | ""}

Actions are a SMALL fixed set mapped onto existing Nalox powers
(no arbitrary prompts — that keeps a 30-second tick safe):

    check_youtube_comments — count unreplied channel comments
    reply_all_comments     — youtube_tools.reply_all
    read_news              — top headlines
    channel_stats          — subscribers / views / newest video

run_due_tasks(cfg, brain, deliver) is called by nalox.py's checker
thread every ~30 s. deliver(text, channel) is nalox.py's callback
(speak it and/or Telegram it). A task runs at most once per day,
only inside its HH:MM minute, and only on matching days. Every
failure is contained: a broken task reports itself and is marked
run so it cannot spam.
"""
import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("nalox.scheduler")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_PATH = os.path.join(BASE_DIR, "scheduled_tasks.json")

ACTIONS = {
    "check_youtube_comments": "check YouTube comments",
    "reply_all_comments": "reply to all YouTube comments",
    "read_news": "read the news",
    "channel_stats": "report channel stats",
}

_lock = threading.Lock()
_tasks = None  # lazily loaded list of dicts


# ------------------------------------------------------------ storage
def _load():
    global _tasks
    if _tasks is not None:
        return _tasks
    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _tasks = [d for d in data if isinstance(d, dict)
                  and d.get("action") in ACTIONS] \
            if isinstance(data, list) else []
    except FileNotFoundError:
        _tasks = []
    except Exception as exc:
        log.warning("scheduled_tasks.json unreadable (%s)", exc)
        _tasks = []
    return _tasks


def _save():
    try:
        with open(TASKS_PATH, "w", encoding="utf-8") as f:
            json.dump(_tasks or [], f, ensure_ascii=False, indent=1)
    except Exception as exc:
        log.warning("Could not save scheduled_tasks.json: %s", exc)


def list_tasks():
    with _lock:
        return [dict(t) for t in _load()]


def add_task(action, label, time_hhmm, days="daily", channel="speak"):
    """Create a task. Returns the task dict (or None if invalid)."""
    if action not in ACTIONS:
        return None
    try:
        hh, mm = (int(x) for x in str(time_hhmm).split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        time_hhmm = f"{hh:02d}:{mm:02d}"
    except Exception:
        return None
    with _lock:
        tasks = _load()
        task = {
            "id": max([t.get("id", 0) for t in tasks], default=0) + 1,
            "action": action,
            "label": (label or ACTIONS[action]).strip(),
            "time": time_hhmm,
            "days": "weekdays" if days == "weekdays" else "daily",
            "channel": channel if channel in ("speak", "telegram",
                                              "both") else "speak",
            "last_run": "",
        }
        tasks.append(task)
        _save()
        log.info("Scheduled task added: %s", task)
        return dict(task)


def remove_task(index):
    """Remove the task at 1-based `index` (as spoken in the list).

    Returns the removed task's label, or None if out of range."""
    with _lock:
        tasks = _load()
        if 1 <= index <= len(tasks):
            gone = tasks.pop(index - 1)
            _save()
            log.info("Scheduled task removed: %s", gone)
            return gone.get("label") or ACTIONS.get(gone.get("action"),
                                                    "task")
    return None


def describe(task):
    """One speakable line: 'Every day at 08:00 — check comments'."""
    when = "Weekdays" if task.get("days") == "weekdays" else "Every day"
    return f"{when} at {task.get('time', '?')} — {task.get('label', '')}"


# ------------------------------------------------------------ actions
def _run_action(action, cfg, brain):
    """Execute one action; return the result text to deliver."""
    import skills
    import youtube_tools

    if action == "read_news":
        titles = skills.fetch_headlines(3)
        if titles:
            return "Top news: " + " ".join(
                f"{i + 1}. {t}." for i, t in enumerate(titles))
        return "No headlines right now, Arjun."
    if action in ("check_youtube_comments", "channel_stats",
                  "reply_all_comments"):
        if not youtube_tools.is_setup():
            return "YouTube is not set up yet, Arjun."
        if action == "channel_stats":
            stats = youtube_tools.channel_stats()
            if not stats:
                return "I could not read your channel stats, Arjun."
            return youtube_tools.stats_line(stats)
        service, status = youtube_tools.get_service()
        if service is None:
            return f"YouTube is not ready ({status}), Arjun."
        if action == "check_youtube_comments":
            comments = youtube_tools.find_unreplied(service)
            n = len(comments)
            if n == 0:
                return "No unreplied YouTube comments, Arjun. All clear."
            return (f"You have {n} unreplied YouTube comment"
                    f"{'s' if n != 1 else ''}, Arjun.")
        # reply_all_comments
        posted, found = youtube_tools.reply_all(brain)
        if found:
            return f"Done, Arjun. I replied to {posted} comments."
        return "Done, Arjun. There were no unreplied comments."
    return f"Unknown scheduled action: {action}"


# ------------------------------------------------------------ the tick
def _due(task, now):
    if task.get("last_run") == now.strftime("%Y-%m-%d"):
        return False
    if task.get("time") != now.strftime("%H:%M"):
        return False
    if task.get("days") == "weekdays" and now.weekday() >= 5:
        return False
    return True


def run_due_tasks(cfg, brain=None, deliver=None, now=None):
    """Run every task due right now. Returns [(task, result_text)].

    deliver(text, channel) is called (from a worker thread per task)
    with the result. The task is marked run BEFORE executing, so a
    crash can never make it fire twice or spam every tick.
    """
    now = now or datetime.now()
    ran = []
    with _lock:
        due = []
        for task in _load():
            if _due(task, now):
                task["last_run"] = now.strftime("%Y-%m-%d")
                due.append(dict(task))
        if due:
            _save()
    for task in due:
        def _work(task=task):
            try:
                result = _run_action(task["action"], cfg, brain)
            except Exception as exc:
                log.warning("Scheduled task %s failed: %s",
                            task.get("id"), exc)
                result = (f"A scheduled task failed, Arjun: "
                          f"{task.get('label', '')} ({exc})")
            log.info("Scheduled task ran: %s -> %s",
                     task.get("label"), result)
            if deliver is not None:
                try:
                    deliver(result, task.get("channel", "speak"))
                except Exception as exc:
                    log.warning("Scheduled task delivery failed: %s",
                                exc)
            return result

        # Actions run inline: nalox.py calls this from its own
        # background checker thread, so even a slow action (reply
        # all) blocks only that thread — never the assistant.
        result = _work()
        ran.append((task, result))
    return ran
