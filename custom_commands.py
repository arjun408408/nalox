"""Nalox custom commands (v5.8) — "Make your own command".

The owner teaches Nalox HIS phrases in HIS words, with no
coding: "When I say <phrase> → do <action> on <target>". The
form lives in the Command Center (dashboard.py); the brain
matches the phrases against what he says (ASR-normalised, so
his own pronunciation of his own phrase still fires) after
the built-in local intents and before the LLM — see
Brain._custom_intents in brain.py.

The store is custom_commands.json next to config.json: a
JSON list of {"phrase": str, "action": str, "target": str}.
It is user data, exactly like config.json: update packs
never ship or overwrite it (UPDATE.bat copies *.py only),
and a malformed file is ignored safely — Nalox just has no
custom commands until the file is fixed, never a crash.

Actions (the form's dropdown):
  open_app           -> actions.open_app(target)
  open_folder        -> actions.open_folder / open_path
  open_url           -> actions.open_url(target)
  open_file          -> actions.open_path(target)
  type_text          -> actions.type_text(target)
  speak              -> Nalox SAYS the target text
  quick_clean        -> actions.pc_quick_clean()
  empty_recycle_bin  -> actions.empty_recycle_bin()
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(BASE_DIR, "custom_commands.json")

ACTIONS = ("open_app", "open_folder", "open_url", "open_file",
           "type_text", "speak", "quick_clean",
           "empty_recycle_bin")

# Dropdown labels for the Command Center form — short, plain
# English (the owner reads basic English).
ACTION_LABELS = {
    "open_app": "Open an app",
    "open_folder": "Open a folder",
    "open_url": "Open a website",
    "open_file": "Open a file",
    "type_text": "Type some text",
    "speak": "Say something",
    "quick_clean": "Clean the PC (quick)",
    "empty_recycle_bin": "Empty the Recycle Bin",
}

# These two need no target — the form's target field is
# ignored for them.
NO_TARGET_ACTIONS = ("quick_clean", "empty_recycle_bin")


def _clean_entry(raw):
    """One stored entry -> a clean dict, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    phrase = str(raw.get("phrase") or "").strip()
    action = str(raw.get("action") or "").strip()
    target = str(raw.get("target") or "").strip()
    if not phrase or action not in ACTIONS:
        return None
    return {"phrase": phrase, "action": action,
            "target": target}


def load_commands(path=None):
    """The stored commands as a list of clean dicts.

    A MISSING file is simply an empty list. A malformed one
    RAISES (ValueError) — callers that hot-reload catch it and
    keep the list they already have, so a half-written file
    can never wipe his commands mid-flight."""
    path = path or STORE_PATH
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("custom_commands.json is not a list")
    out = []
    for raw in data:
        entry = _clean_entry(raw)
        if entry is not None:
            out.append(entry)
    return out


def load_commands_safe(path=None):
    """load_commands that never raises: [] on any problem."""
    try:
        return load_commands(path)
    except Exception:
        return []


def save_commands(commands, path=None):
    """Write the list back (cleaned). Temp file + replace, so
    a crash mid-write never leaves a torn store."""
    path = path or STORE_PATH
    cleaned = []
    for raw in commands or []:
        entry = _clean_entry(raw)
        if entry is not None:
            cleaned.append(entry)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return cleaned


def validate_command(phrase, action, target):
    """Form validation. Returns "" when the command is fine,
    else a short plain-English hint for the form to show."""
    if not str(phrase or "").strip():
        return "Type what you will say first — the “When I say…” box is empty."
    if action not in ACTIONS:
        return "Pick an action from the list."
    if action not in NO_TARGET_ACTIONS \
            and not str(target or "").strip():
        return "Type what to open / type / say — the “Do this…” box is empty."
    return ""


def add_command(phrase, action, target, path=None):
    """Add (or re-teach) a command and save. Re-teaching the
    same phrase replaces the old entry — the newest lesson
    wins. Returns the full stored list."""
    commands = load_commands_safe(path)
    new = {"phrase": str(phrase).strip(),
           "action": str(action).strip(),
           "target": str(target or "").strip()}
    key = new["phrase"].lower()
    commands = [c for c in commands
                if c["phrase"].lower() != key]
    commands.append(new)
    return save_commands(commands, path)


def delete_command(index, path=None):
    """Delete the command at index and save. Out-of-range is
    a no-op. Returns the full stored list."""
    commands = load_commands_safe(path)
    try:
        idx = int(index)
    except Exception:
        return commands
    if 0 <= idx < len(commands):
        commands.pop(idx)
    return save_commands(commands, path)
