"""YouTube PLAY resolver (v5.0).

"Play a sad song" used to stop at the search-results page —
Nalox could search YouTube but could not actually PLAY
anything (Arjun's 12:50 report). This module closes the gap
without any API key or browser automation: YouTube's results
page embeds its data as JSON (ytInitialData), and the first
videoRenderer in it is the top real result (sponsored slots
use other renderer types, so they are skipped naturally).

first_video_url(query) -> the watch URL of the first result,
or None on ANY failure (offline, page shape changed, no
results). Callers fall back to opening the search page —
exactly the pre-v5.0 behaviour — and say so honestly.
"""
import json
import re
import time
from urllib.parse import quote_plus

import requests

_RESULTS_URL = "https://www.youtube.com/results?search_query="
_WATCH_URL = "https://www.youtube.com/watch?v="
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MEMO = {}
_MEMO_TTL = 30.0
_RENDERER_RE = re.compile(
    r'"videoRenderer"\s*:\s*\{\s*"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"')
_WATCH_RE = re.compile(r"watch\?v=([A-Za-z0-9_-]{11})")


def _initial_data(html):
    """Parse the ytInitialData JSON blob out of a results page."""
    idx = html.find("ytInitialData")
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(html[start:])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _walk_for_video(node, depth=0):
    """DFS in document order for the first videoRenderer's id."""
    if depth > 40 or node is None:
        return None
    if isinstance(node, dict):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            vid = renderer.get("videoId")
            if isinstance(vid, str) and _VIDEO_ID_RE.match(vid):
                return vid
        for value in node.values():
            found = _walk_for_video(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_for_video(item, depth + 1)
            if found:
                return found
    return None


def extract_first_video_id(html):
    """The first real video result's videoId in a results page.

    Order of attempts: (1) walk the parsed ytInitialData JSON
    for the first videoRenderer; (2) a videoRenderer-shaped
    regex over the raw page; (3) the first watch?v= link.
    Returns None when the page holds no video result at all.
    """
    if not html:
        return None
    data = _initial_data(html)
    if data is not None:
        vid = _walk_for_video(data)
        if vid:
            return vid
    m = _RENDERER_RE.search(html)
    if m:
        return m.group(1)
    m = _WATCH_RE.search(html)
    if m:
        return m.group(1)
    return None


def first_video_url(query, timeout=8):
    """Watch URL of the top YouTube result for query, or None.

    Results are memoised for ~30 s per query: Brain resolves
    first (to know whether playback will really happen, for
    its spoken reply) and actions.play_on_youtube then opens
    through the same resolver — the memo keeps that second
    call off the network.
    """
    q = (query or "").strip()
    if not q:
        return None
    key = q.lower()
    now = time.monotonic()
    hit = _MEMO.get(key)
    if hit and now - hit[0] < _MEMO_TTL:
        return hit[1]
    try:
        resp = requests.get(_RESULTS_URL + quote_plus(q),
                            headers=_HEADERS, timeout=timeout)
        if getattr(resp, "status_code", 0) != 200:
            return None
        vid = extract_first_video_id(resp.text or "")
    except Exception:
        return None
    url = (_WATCH_URL + vid) if vid else None
    if len(_MEMO) > 64:
        _MEMO.clear()
    _MEMO[key] = (now, url)
    return url
