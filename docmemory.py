"""Document memory for Nalox (v4.3) — "search my files".

OpenJarvis indexes the user's documents and searches them with
SQLite FTS5; Nalox gets the same idea with the Python stdlib only
(no new packages). Arjun points Nalox at a folder in Settings
(config doc_folder); Nalox walks its .txt/.md files, chunks them
(~120 lines per chunk) and stores the chunks in docmemory.db:

    index_folder(path) -> number of chunks stored
    search(query, k=3) -> [(path, snippet), ...]  (best first)

Search uses FTS5 MATCH when SQLite has FTS5 (it normally does);
if the FTS5 module is missing, it falls back to a LIKE scan over
the same table. Indexing REPLACES the previous index (one folder
at a time — that is all Arjun needs).

Every function is guarded: a corrupt db, a missing folder or a bad
query returns an empty result, never an exception.
"""
import logging
import os
import sqlite3

log = logging.getLogger("nalox.docmemory")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "docmemory.db")

CHUNK_LINES = 120          # lines per chunk
MAX_FILE_BYTES = 2_000_000  # skip absurdly large text files
TEXT_EXTS = (".txt", ".md")

_fts5_ok = None  # probed once per process


def _connect():
    conn = sqlite3.connect(DB_PATH)
    return conn


def _has_fts5(conn):
    global _fts5_ok
    if _fts5_ok is not None:
        return _fts5_ok
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _probe_fts "
            "USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _probe_fts")
        _fts5_ok = True
    except Exception:
        _fts5_ok = False
    return _fts5_ok


def _ensure_table(conn):
    """Create the chunks table (FTS5 if possible, plain otherwise)."""
    if _has_fts5(conn):
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks "
            "USING fts5(path, content)")
    else:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks "
            "(path TEXT, content TEXT)")
    conn.commit()


def index_folder(path):
    """Index every .txt/.md under `path`. Returns the chunk count.

    Replaces any previous index. 0 on any failure (missing folder,
    unreadable files, db trouble) — callers treat 0 as "nothing
    indexed" and carry on.
    """
    try:
        path = os.path.expanduser(str(path or "").strip())
        if not path or not os.path.isdir(path):
            log.warning("docmemory: folder not found: %r", path)
            return 0
        rows = []
        for root, _dirs, files in os.walk(path):
            for name in sorted(files):
                if not name.lower().endswith(TEXT_EXTS):
                    continue
                full = os.path.join(root, name)
                try:
                    if os.path.getsize(full) > MAX_FILE_BYTES:
                        continue
                    with open(full, "r", encoding="utf-8",
                              errors="replace") as f:
                        lines = f.read().splitlines()
                except Exception:
                    continue
                for i in range(0, len(lines), CHUNK_LINES):
                    chunk = "\n".join(lines[i:i + CHUNK_LINES]).strip()
                    if chunk:
                        rows.append((full, chunk))
        conn = _connect()
        try:
            _ensure_table(conn)
            conn.execute("DELETE FROM chunks")
            conn.executemany(
                "INSERT INTO chunks (path, content) VALUES (?, ?)", rows)
            conn.commit()
        finally:
            conn.close()
        log.info("docmemory: indexed %d chunks from %s", len(rows), path)
        return len(rows)
    except Exception as exc:
        log.warning("docmemory index failed: %s", exc)
        return 0


def _snippet(content, query, width=220):
    """A readable excerpt of `content` around the first query term."""
    text = " ".join((content or "").split())
    low = text.lower()
    pos = -1
    for term in (query or "").lower().split():
        pos = low.find(term)
        if pos >= 0:
            break
    if pos < 0:
        return text[:width].strip()
    start = max(0, pos - 60)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return (prefix + text[start:end] + suffix).strip()


def search(query, k=3):
    """Search the index. Returns [(path, snippet)] — [] on failure."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        if not os.path.exists(DB_PATH):
            return []
        conn = _connect()
        try:
            _ensure_table(conn)
            rows = []
            if _has_fts5(conn):
                # FTS5 MATCH with quoted terms (OR semantics), ranked.
                terms = [t.replace('"', " ") for t in query.split() if t]
                if not terms:
                    return []
                match = " OR ".join(f'"{t}"' for t in terms)
                try:
                    rows = conn.execute(
                        "SELECT path, content FROM chunks "
                        "WHERE chunks MATCH ? LIMIT ?",
                        (match, int(k))).fetchall()
                except Exception:
                    rows = []  # fall through to the LIKE scan
            if not rows:
                like = "%" + query.replace("%", " ").split()[0] + "%" \
                    if query.split() else "%"
                rows = conn.execute(
                    "SELECT path, content FROM chunks "
                    "WHERE content LIKE ? LIMIT ?",
                    (like, int(k))).fetchall()
            return [(p, _snippet(c, query)) for p, c in rows]
        finally:
            conn.close()
    except Exception as exc:
        log.warning("docmemory search failed: %s", exc)
        return []


def indexed_count():
    """How many chunks are currently indexed (0 if none)."""
    try:
        if not os.path.exists(DB_PATH):
            return 0
        conn = _connect()
        try:
            _ensure_table(conn)
            row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0
