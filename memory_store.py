"""Nalox's long-term memory (v3): small facts Arjun asks it to remember.

Stored as JSON in memory.json, next to the code:
    [{"fact": "Arjun's sister is called Priya", "at": "2026-11-15T07:52:00"}]

Fully defensive: a missing/corrupt file just means an empty memory.
Facts are also passed to the agent brain's system prompt.
"""
import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("nalox.memory")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_PATH = os.path.join(BASE_DIR, "memory.json")


class MemoryStore:
    def __init__(self, path=MEMORY_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._facts = []
        self._load()

    # ------------------------------------------------------------ io
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._facts = [d for d in data
                               if isinstance(d, dict) and d.get("fact")]
        except FileNotFoundError:
            self._facts = []
        except Exception as exc:
            log.warning("memory.json unreadable (%s); starting empty.", exc)
            self._facts = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._facts, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            log.warning("Could not save memory.json: %s", exc)

    # ------------------------------------------------------------ api
    def remember(self, fact):
        fact = (fact or "").strip()
        if not fact:
            return False
        with self._lock:
            self._facts.append({
                "fact": fact,
                "at": datetime.now().isoformat(timespec="seconds"),
            })
            self._save()
        log.info("Memory stored: %s", fact)
        return True

    def facts(self):
        with self._lock:
            return [d["fact"] for d in self._facts]

    def recent(self, n=5):
        return self.facts()[-n:]

    def clear(self):
        with self._lock:
            self._facts = []
            self._save()
        log.info("Memory cleared.")

    def __len__(self):
        with self._lock:
            return len(self._facts)


# ------------------------------------------------------ digest skips
# v4.3: the Morning Digest taste filter. Phrases Arjun told Nalox
# to keep OUT of his digest ("don't include cricket in my digest")
# live in digest_skip.json next to this module — deliberately NOT
# in the fact list, so they never leak into the agent's system
# prompt as "facts about Arjun".
SKIP_PATH = os.path.join(BASE_DIR, "digest_skip.json")
_skip_lock = threading.Lock()


def load_digest_skips():
    """The digest skip phrases (lowercased). [] on any problem."""
    try:
        with open(SKIP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip().lower() for x in data if str(x).strip()]
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("digest_skip.json unreadable (%s)", exc)
    return []


def add_digest_skip(phrase):
    """Add one skip phrase. Returns True if it was newly added."""
    phrase = (phrase or "").strip().lower()
    if not phrase:
        return False
    with _skip_lock:
        skips = load_digest_skips()
        if phrase in skips:
            return False
        skips.append(phrase)
        try:
            with open(SKIP_PATH, "w", encoding="utf-8") as f:
                json.dump(skips, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            log.warning("Could not save digest_skip.json: %s", exc)
            return False
    log.info("Digest skip added: %s", phrase)
    return True


# ------------------------------------------------------ preferences (v4.7)
# Learned preferences live in prefs.json next to this module —
# deliberately NOT in the fact list either (same reasoning as the
# digest skips: they are settings, not "facts about Arjun" for the
# agent prompt). Two keys exist today:
#   "preferred_name" — how Nalox addresses him ("call me Sir")
#   "preferred_lang" — the language Nalox answers in ("বাংলায় বলো")
# brain.py learns them from plain speech (no API key needed),
# mirrors them into the live config dict, and Settings' "Call me"
# field reads/writes the same store (dual-write with config.json).
PREFS_PATH = os.path.join(BASE_DIR, "prefs.json")
_prefs_lock = threading.Lock()


def load_prefs():
    """The learned preferences as a dict. {} on any problem."""
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()
                    if v not in (None, "")}
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("prefs.json unreadable (%s)", exc)
    return {}


def set_pref(key, value):
    """Set one preference (empty/None clears it). Never raises;
    returns True when the store was written."""
    key = str(key or "").strip()
    if not key:
        return False
    with _prefs_lock:
        prefs = load_prefs()
        value = str(value).strip() if value is not None else ""
        if value:
            prefs[key] = value
        else:
            prefs.pop(key, None)
        try:
            with open(PREFS_PATH, "w", encoding="utf-8") as f:
                json.dump(prefs, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            log.warning("Could not save prefs.json: %s", exc)
            return False
    log.info("Preference set: %s = %r", key, value or "(cleared)")
    return True


def address_name(cfg):
    """How Nalox should ADDRESS him right now (v4.7).

    Resolution: the live config's "preferred_name" (brain mirrors
    learned values there, Settings writes there) -> prefs.json ->
    his real name (config "user_name", default "Arjun"). This is
    the ADDRESS, not the identity: the system prompt and tool
    descriptions keep using his real name as a fact.
    """
    cfg = cfg or {}
    name = str(cfg.get("preferred_name") or "").strip()
    if not name:
        try:
            name = str(load_prefs().get("preferred_name")
                       or "").strip()
        except Exception:
            name = ""
    if not name:
        name = str(cfg.get("user_name") or "Arjun").strip() or "Arjun"
    return name


def address_name_bn(cfg):
    """The Bengali-script form of the address: the default name
    renders as অর্জুন; a learned address (Sir / স্যার / Boss) is
    used verbatim — it is what he asked to be called."""
    name = address_name(cfg)
    return "অর্জুন" if name == "Arjun" else name
