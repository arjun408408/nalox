"""Reminders (v3): "remind me in 10 minutes to drink water".

Stored as JSON in reminders.json, next to the code:
    [{"due": "2026-11-15T18:30:00", "text": "call mom", "lang": "en"}]

brain.py parses commands and adds reminders here; nalox.py runs a
checker thread that pops due reminders and speaks them. On load, past
reminders are dropped — they were missed while Nalox was off.
"""
import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("nalox.reminders")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMINDERS_PATH = os.path.join(BASE_DIR, "reminders.json")


class ReminderStore:
    def __init__(self, path=REMINDERS_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._items = []
        self._load()
        missed = self.pop_due()  # drop (and log) anything already past
        if missed:
            log.info("Dropped %d reminder(s) that passed while Nalox was off.",
                     len(missed))

    # ------------------------------------------------------------ io
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._items = [d for d in data
                               if isinstance(d, dict) and d.get("due")
                               and d.get("text")]
        except FileNotFoundError:
            self._items = []
        except Exception as exc:
            log.warning("reminders.json unreadable (%s); starting empty.", exc)
            self._items = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            log.warning("Could not save reminders.json: %s", exc)

    # ------------------------------------------------------------ api
    def add(self, due_dt, text, lang="en"):
        item = {
            "due": due_dt.isoformat(timespec="seconds"),
            "text": (text or "").strip(),
            "lang": lang or "en",
        }
        with self._lock:
            self._items.append(item)
            self._items.sort(key=lambda d: d["due"])
            self._save()
        log.info("Reminder set for %s: %s", item["due"], item["text"])
        return item

    def pop_due(self, now=None):
        """Remove and return every reminder whose time has come."""
        now = now or datetime.now()
        due, keep = [], []
        with self._lock:
            for item in self._items:
                try:
                    when = datetime.fromisoformat(item["due"])
                except Exception:
                    continue  # corrupt entry — drop it
                (due if when <= now else keep).append(item)
            if due:
                self._items = keep
                self._save()
        return due

    def pending(self):
        with self._lock:
            return list(self._items)

    def __len__(self):
        with self._lock:
            return len(self._items)
