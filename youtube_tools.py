"""YouTube reply-all (v4.0): answer every unreplied comment on
Arjun's channel (MNY Intelligence) in one voice command.

How it works:
  - One-time setup (SETUP-YOUTUBE.txt): Arjun creates a Google Cloud
    OAuth client and puts youtube_client_secret.json in this folder.
  - First use opens HIS browser for Google consent (InstalledAppFlow,
    local server, port 0); the token — refresh token included — is
    cached in youtube_token.json, so consent is a one-time thing.
  - find_unreplied(): walks the channel's ~8 newest uploads and
    collects top-level comments whose thread contains NO reply from
    the channel owner himself.
  - make_reply(): the agent brain (plain chat, no tools) writes ONE
    short, warm, specific English reply per comment — never a
    copy-paste template.
  - reply_all(): posts the replies one by one. A failure on one
    comment never stops the run; a quota error stops it cleanly.

Everything is failure-guarded: brain._youtube_reply_all calls this
from a background thread and speaks the final count.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_PATH = os.path.join(BASE_DIR, "youtube_client_secret.json")
TOKEN_PATH = os.path.join(BASE_DIR, "youtube_token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

RECENT_VIDEOS = 8        # how many of the newest uploads to scan
COMMENTS_PER_VIDEO = 50  # comment threads fetched per video


def is_setup():
    """True once youtube_client_secret.json sits in the Nalox folder."""
    return os.path.exists(SECRET_PATH)


def get_service():
    """Build an authenticated YouTube v3 service.

    Returns (service, "ok") on success. (None, "not_setup") when the
    client-secret file is missing; (None, "error: ...") for anything
    else (no network, consent declined, bad secret file...).
    Runs the browser consent flow when there is no valid cached
    token; refreshes an expired token when a refresh token exists.
    """
    if not os.path.exists(SECRET_PATH):
        return None, "not_setup"
    try:
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(TOKEN_PATH):
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(
                TOKEN_PATH, SCOPES)
        if creds is None or not creds.valid:
            if creds is not None and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(
                    SECRET_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        return build("youtube", "v3", credentials=creds), "ok"
    except Exception as exc:
        return None, f"error: {exc}"


def my_channel_id(service):
    """The authenticated channel's own ID (None on failure)."""
    try:
        resp = service.channels().list(part="id", mine=True).execute()
        items = resp.get("items") or []
        if items:
            return items[0].get("id")
    except Exception:
        pass
    return None


def _author_channel_id(comment):
    """authorChannelId.value of a comment resource ('' if absent)."""
    snippet = comment.get("snippet") or {}
    return ((snippet.get("authorChannelId") or {}).get("value")) or ""


def _thread_has_owner_reply(service, thread, my_id):
    """True if any reply in the thread was written by the owner.

    commentThreads embeds only some replies; when the thread has
    more (totalReplyCount), the rest are fetched via comments.list
    so an owner reply is never missed (which would double-reply).
    """
    snippet = thread.get("snippet") or {}
    total = snippet.get("totalReplyCount", 0) or 0
    if total == 0:
        return False
    replies = ((thread.get("replies") or {}).get("comments")) or []
    for reply in replies:
        if _author_channel_id(reply) == my_id:
            return True
    if len(replies) < total:
        top_id = (snippet.get("topLevelComment") or {}).get("id")
        if top_id:
            try:
                resp = service.comments().list(
                    part="snippet", parentId=top_id,
                    maxResults=100).execute()
                for reply in resp.get("items") or []:
                    if _author_channel_id(reply) == my_id:
                        return True
            except Exception:
                pass  # fall back to what the thread itself showed
    return False


def find_unreplied(service, max_total=20):
    """Unreplied top-level comments on the channel's newest videos.

    Returns a list of {comment_id, author, text, video_title},
    newest videos first, at most max_total entries.
    """
    my_id = my_channel_id(service)
    if not my_id:
        return []
    # The uploads playlist = every video on the channel, newest first.
    resp = service.channels().list(
        part="contentDetails", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        return []
    uploads = ((items[0].get("contentDetails") or {})
               .get("relatedPlaylists") or {}).get("uploads")
    if not uploads:
        return []
    resp = service.playlistItems().list(
        part="snippet", playlistId=uploads,
        maxResults=RECENT_VIDEOS).execute()
    videos = []
    for item in resp.get("items") or []:
        snippet = item.get("snippet") or {}
        video_id = (snippet.get("resourceId") or {}).get("videoId")
        if video_id:
            videos.append((video_id, snippet.get("title") or ""))
    found = []
    for video_id, video_title in videos:
        if len(found) >= max_total:
            break
        try:
            resp = service.commentThreads().list(
                part="snippet,replies", videoId=video_id, order="time",
                maxResults=COMMENTS_PER_VIDEO).execute()
        except Exception:
            continue  # comments disabled on this video — skip it
        for thread in resp.get("items") or []:
            if len(found) >= max_total:
                break
            snippet = thread.get("snippet") or {}
            top = snippet.get("topLevelComment") or {}
            top_snippet = top.get("snippet") or {}
            if _thread_has_owner_reply(service, thread, my_id):
                continue
            found.append({
                "comment_id": top.get("id") or thread.get("id") or "",
                "author": top_snippet.get("authorDisplayName") or "",
                "text": (top_snippet.get("textOriginal")
                         or top_snippet.get("textDisplay") or ""),
                "video_title": video_title,
            })
    return found


def make_reply(brain, comment):
    """Write ONE short, warm, specific reply via the agent brain.

    Uses the brain's plain chat (no tools). Surrounding quotes are
    stripped. If no brain is reachable, a short genuine fallback is
    used so the run never stalls.
    """
    prompt = (
        "You are MNY Intelligence's channel manager (that's Muse's "
        "style): write ONE short, warm, friendly English reply to "
        "this YouTube comment. No hashtags, no emojis overload "
        "(max 1), never generic copy-paste — react to what they "
        f"said. Comment by {comment.get('author', '')}: "
        f"{comment.get('text', '')}")
    reply = None
    if brain is not None:
        try:
            # v5.7.1: a comment reply is WRITTEN text — it must
            # not be trimmed by the spoken two-line length cap.
            reply = brain._plain_chat(prompt, writing=True)
        except Exception:
            reply = None
    if not reply:
        return "Thank you so much for watching and for the comment!"
    reply = str(reply).strip()
    if len(reply) >= 2 and reply[0] == reply[-1] \
            and reply[0] in ("\"", "'"):
        reply = reply[1:-1].strip()
    return reply


def reply_all(brain, progress_cb=None):
    """Reply to every unreplied comment. Returns (posted, found).

    Per-comment errors are skipped and counted as failures; a quota
    error stops the run cleanly with whatever was posted so far.
    progress_cb(message) — optional — is called with milestones.
    """
    def _progress(msg):
        if progress_cb is not None:
            try:
                progress_cb(msg)
            except Exception:
                pass

    service, status = get_service()
    if service is None:
        _progress(f"YouTube is not ready ({status}).")
        return 0, 0
    try:
        comments = find_unreplied(service)
    except Exception as exc:
        _progress(f"Could not read the comments ({exc}).")
        return 0, 0
    found = len(comments)
    _progress(f"Found {found} unreplied comment(s).")
    posted = 0
    for comment in comments:
        if not comment.get("comment_id"):
            continue
        try:
            text = make_reply(brain, comment)
            service.comments().insert(
                part="snippet",
                body={"snippet": {
                    "parentId": comment["comment_id"],
                    "textOriginal": text}}).execute()
            posted += 1
            if posted % 5 == 0:
                _progress(f"Replied to {posted} comments so far.")
        except Exception as exc:
            if "quota" in str(exc).lower():
                _progress("YouTube quota reached — stopping here.")
                break
            continue  # one bad comment never stops the run
    return posted, found


# ------------------------------------------------------- stats (v4.3)
def channel_stats():
    """Channel numbers for the Morning Digest: subscribers, total
    views, and the newest video's title + views.

    Returns a dict, or None when YouTube is not set up / reachable
    (the digest then skips the section silently).
    """
    service, status = get_service()
    if service is None:
        return None
    try:
        resp = service.channels().list(
            part="statistics,contentDetails", mine=True).execute()
        items = resp.get("items") or []
        if not items:
            return None
        stats = items[0].get("statistics") or {}
        uploads = ((items[0].get("contentDetails") or {})
                   .get("relatedPlaylists") or {}).get("uploads")
        newest_title, newest_views = "", None
        if uploads:
            resp = service.playlistItems().list(
                part="snippet", playlistId=uploads,
                maxResults=1).execute()
            vids = resp.get("items") or []
            if vids:
                snippet = vids[0].get("snippet") or {}
                newest_title = snippet.get("title") or ""
                video_id = (snippet.get("resourceId") or {}) \
                    .get("videoId")
                if video_id:
                    vresp = service.videos().list(
                        part="statistics", id=video_id).execute()
                    vitems = vresp.get("items") or []
                    if vitems:
                        newest_views = int(
                            (vitems[0].get("statistics") or {})
                            .get("viewCount") or 0)
        return {
            "subscribers": int(stats.get("subscriberCount") or 0),
            "total_views": int(stats.get("viewCount") or 0),
            "video_count": int(stats.get("videoCount") or 0),
            "newest_title": newest_title,
            "newest_views": newest_views,
        }
    except Exception:
        return None


def stats_line(stats):
    """One speakable line from a channel_stats() dict."""
    line = (f"Your channel has {stats['subscribers']} subscribers "
            f"and {stats['total_views']} total views.")
    if stats.get("newest_title") and stats.get("newest_views") is not None:
        line += (f" Newest video: {stats['newest_title']} — "
                 f"{stats['newest_views']} views.")
    return line
