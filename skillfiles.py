"""Nalox skill files (v4.3) — OpenJarvis's TOML skill-recipes,
shrunk to a folder of small files Nalox can learn without a code
change.

A skill lives in skills/<name>.toml next to this module:

    [skill]
    name = "Organise Downloads"
    description = "Sort the Downloads folder into subfolders."
    triggers = ["organise my downloads", "downloads গোছাও"]

    [[skill.steps]]
    tool = "organise_downloads"
    [skill.steps.args]
    # string values may contain {query} (whatever Arjun said after
    # the trigger phrase) and {prev} (the previous step's result)

load_skills() scans the folder once (cached). Brain checks the
triggers BEFORE its generic patterns and the agent fallback: on a
match, run_skill() executes the steps in order through Brain's own
_run_tool dispatch and returns the final step's result to speak.

This module also hosts the small file tools the shipped skills
need (organise_downloads, find_duplicate_files, fetch_url_text) —
kept here so brain.py only dispatches.

Everything is guarded: a bad TOML file is skipped with a warning,
a failing step stops the skill with a calm line, and nothing here
can crash the assistant.
"""
import hashlib
import json
import logging
import os
import re

log = logging.getLogger("nalox.skillfiles")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
CAPTURES_DIR = os.path.join(BASE_DIR, "Nalox Captures")

_cache = None  # loaded skill list (per process)


# ------------------------------------------------------------ loading
def load_skills(force=False):
    """Scan skills/*.toml. Returns [{name, description, triggers,
    steps, file}]. Bad files are skipped, never fatal."""
    global _cache
    if _cache is not None and not force:
        return _cache
    skills = []
    try:
        import tomllib
    except Exception:
        log.warning("skillfiles: tomllib unavailable — no skills loaded")
        _cache = []
        return _cache
    try:
        names = sorted(os.listdir(SKILLS_DIR))
    except Exception:
        names = []
    for name in names:
        if not name.lower().endswith(".toml"):
            continue
        path = os.path.join(SKILLS_DIR, name)
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            meta = data.get("skill") or {}
            triggers = [str(t).strip().lower()
                        for t in meta.get("triggers") or [] if str(t).strip()]
            steps = []
            for step in meta.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                # OpenJarvis format uses tool_name; ours uses tool.
                tool = step.get("tool") or step.get("tool_name")
                if not tool:
                    continue  # skill_name sub-steps unsupported
                args = step.get("args")
                if not isinstance(args, dict):
                    args = {}
                    # OpenJarvis format: a JSON arguments_template.
                    template = step.get("arguments_template")
                    if isinstance(template, str) and template.strip():
                        try:
                            parsed = json.loads(template)
                            if isinstance(parsed, dict):
                                args = parsed
                        except Exception:
                            pass
                steps.append({
                    "tool": str(tool),
                    "args": {str(k): v for k, v in args.items()},
                    # OpenJarvis-style named output chaining.
                    "output_key": str(step.get("output_key") or ""),
                })
            if triggers and steps:
                skills.append({
                    "name": str(meta.get("name") or name),
                    "description": str(meta.get("description") or ""),
                    "triggers": triggers,
                    "steps": steps,
                    "file": name,
                })
            else:
                log.warning("skillfiles: %s has no triggers/steps — "
                            "skipped", name)
        except Exception as exc:
            log.warning("skillfiles: could not load %s (%s) — skipped",
                        name, exc)
    _cache = skills
    log.info("skillfiles: %d skill(s) loaded", len(skills))
    return skills


def count_skills():
    try:
        return len(load_skills())
    except Exception:
        return 0


def match_skill(skills, text):
    """First skill whose trigger starts `text`.

    Returns (skill, remainder) or (None, ""). The remainder is what
    Arjun said after the trigger phrase (fills {query}).
    """
    text = (text or "").strip().lower()
    for skill in skills or []:
        for trigger in skill["triggers"]:
            if text.startswith(trigger):
                remainder = text[len(trigger):].strip(" .!?")
                return skill, remainder
    return None, ""


def _fill(value, context):
    """Fill {query} / {prev} / {<output_key>} placeholders."""
    if isinstance(value, str):
        out = value
        for key, val in context.items():
            out = out.replace("{" + key + "}", val or "")
        return out
    return value


def run_skill(skill, remainder, run_tool):
    """Execute the skill's steps in order via run_tool(name, args).

    Placeholders fill from a context that starts as {query} (what
    Arjun said after the trigger) and gains {prev} (the previous
    step's result) plus every step's named output_key — the
    OpenJarvis chaining style. Returns the final step's result
    string (what Nalox speaks), or a calm failure line. Never
    raises.
    """
    context = {"query": remainder or "", "prev": ""}
    try:
        for step in skill["steps"]:
            args = {k: _fill(v, context)
                    for k, v in step["args"].items()}
            result = run_tool(step["tool"], args)
            context["prev"] = str(result or "")
            if step.get("output_key"):
                context[step["output_key"]] = context["prev"]
            log.info("skill %s step %s -> %s",
                     skill["name"], step["tool"],
                     context["prev"][:120])
        return context["prev"] or f"{skill['name']} done, Arjun."
    except Exception as exc:
        log.warning("skill %s failed: %s", skill.get("name"), exc)
        return f"That skill failed, Arjun — {exc}"


def draft_email_save(topic, write_fn=None):
    """Draft an email about `topic` and SAVE it as a .txt file.

    The draft lands in 'Nalox Captures' next to this module. It is
    NEVER sent — Arjun reviews and sends drafts himself. When
    write_fn (the brain's plain chat) is given, it composes the
    body; otherwise a plain template is used.
    """
    topic = (topic or "").strip() or "a quick note"
    body = None
    if write_fn is not None:
        try:
            body = write_fn(
                "Write a short, polite email about: " + topic +
                ". Plain text only, ready to send, with a subject "
                "line first.")
        except Exception:
            body = None
    if not body:
        body = (f"Subject: {topic}\n\nHi,\n\n"
                f"Writing about: {topic}.\n\nBest regards,\nArjun")
    try:
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-",
                      topic.lower()).strip("-")[:40] or "draft"
        path = os.path.join(CAPTURES_DIR, f"email-draft-{slug}.txt")
        n = 1
        while os.path.exists(path):
            path = os.path.join(
                CAPTURES_DIR, f"email-draft-{slug}-{n}.txt")
            n += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return (f"Draft saved, Arjun — {os.path.basename(path)} in "
                "Nalox Captures. I did not send it.")
    except Exception as exc:
        return f"I could not save the draft: {exc}"


# ------------------------------------------------- the shipped tools
_DOWNLOAD_KINDS = [
    ("Images", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
                ".bmp", ".ico"}),
    ("Documents", {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf",
                   ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".odt"}),
    ("Videos", {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}),
    ("Audio", {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}),
    ("Archives", {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}),
    ("Installers", {".exe", ".msi"}),
]


def _downloads_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads")


def organise_downloads(folder=None):
    """Sort loose files in Downloads into per-kind subfolders.

    Report only what actually moved. Never overwrites: a name clash
    gets a " (1)" suffix. Folders themselves are left alone.
    """
    import shutil
    folder = folder or _downloads_dir()
    if not os.path.isdir(folder):
        return "The Downloads folder was not found, Arjun."
    moved = 0
    kinds_used = set()
    try:
        entries = list(os.scandir(folder))
    except Exception as exc:
        return f"I could not read Downloads: {exc}"
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            kind = "Other"
            for label, exts in _DOWNLOAD_KINDS:
                if ext in exts:
                    kind = label
                    break
            dest_dir = os.path.join(folder, kind)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, entry.name)
            n = 1
            while os.path.exists(dest):
                stem, suffix = os.path.splitext(entry.name)
                dest = os.path.join(dest_dir, f"{stem} ({n}){suffix}")
                n += 1
            shutil.move(entry.path, dest)
            moved += 1
            kinds_used.add(kind)
        except Exception:
            continue  # one locked file never stops the tidy-up
    if moved == 0:
        return "Downloads is already tidy, Arjun — nothing to move."
    return (f"Organised Downloads, Arjun: moved {moved} file"
            f"{'s' if moved != 1 else ''} into "
            f"{len(kinds_used)} folder{'s' if len(kinds_used) != 1 else ''}.")


def _md5(path, cap=200 * 1024 * 1024):
    """MD5 of a file, read in 1 MB blocks (files over `cap` are
    hashed on their first `cap` bytes — enough to group dupes)."""
    h = hashlib.md5()
    read = 0
    with open(path, "rb") as f:
        while read < cap:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
            read += len(block)
    return h.hexdigest()


def find_duplicate_files(folder=None, max_files=3000):
    """Report duplicate files (same size, then same MD5). No deletes."""
    folder = folder or _downloads_dir()
    if not os.path.isdir(folder):
        return "That folder was not found, Arjun."
    by_size = {}
    scanned = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if scanned >= max_files:
                break
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
            except Exception:
                continue
            if size <= 0:
                continue
            scanned += 1
            by_size.setdefault(size, []).append(full)
    groups = []
    wasted = 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for p in paths:
            try:
                by_hash.setdefault(_md5(p), []).append(p)
            except Exception:
                continue
        for _h, same in by_hash.items():
            if len(same) > 1:
                groups.append((size, same))
                wasted += size * (len(same) - 1)
    if not groups:
        return f"No duplicate files found in {os.path.basename(folder)}, Arjun."
    groups.sort(key=lambda g: g[0] * len(g[1]), reverse=True)
    size, same = groups[0]
    biggest = (f"Biggest: {os.path.basename(same[0])} appears "
               f"{len(same)} times.")
    return (f"Found {len(groups)} duplicate group"
            f"{'s' if len(groups) != 1 else ''}, wasting about "
            f"{wasted / (1024 * 1024):.1f} MB. {biggest} "
            "I did not delete anything.")


class _TextExtractor:
    """Minimal HTML -> text (stdlib html.parser), script/style dropped."""

    def __init__(self):
        from html.parser import HTMLParser

        outer = self

        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
                self.skip = 0

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "noscript"):
                    self.skip += 1
                if tag in ("p", "div", "br", "li", "h1", "h2", "h3"):
                    self.parts.append("\n")

            def handle_endtag(self, tag):
                if tag in ("script", "style", "noscript") and self.skip:
                    self.skip -= 1

            def handle_data(self, data):
                if not self.skip:
                    self.parts.append(data)

        self.parser = _P()

    def text(self, html_text):
        self.parser.feed(html_text or "")
        raw = "".join(self.parser.parts)
        return re.sub(r"\s+", " ", raw).strip()


def fetch_url_text(url, limit=1500):
    """Fetch a web page and return its readable text (truncated)."""
    import requests
    url = (url or "").strip()
    if not url:
        return "No web address was given."
    if not re.match(r"^https?://", url):
        url = "https://" + url
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (NaloxAssistant)"})
        resp.raise_for_status()
    except Exception as exc:
        return f"I could not open that page: {exc}"
    text = _TextExtractor().text(resp.text)
    if not text:
        return "That page had no readable text."
    return text[:limit]
