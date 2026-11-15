"""Nalox's power skills (v2).

  1. find_leads(cfg, lang)      — find nearby businesses (OpenStreetMap)
     with / without a website; saves leads/leads.csv + no_website.csv.
  2. build_demo(cfg, name, lang) — generate a polished single-file demo
     website in demos/<slug>/index.html and open it in the browser.
  3. email_outreach(cfg, name, lang) — email the demo pitch (via mailer.py)
     to one named business, or to every no-website lead that has an
     email address on record ("email them"). Never invents addresses.

Data source: OpenStreetMap Overpass API — free, no API key needed.
"""
import csv
import html
import logging
import os
import re
import webbrowser

import mailer

# v4.7: learned-address helpers — user-facing lines in this
# module address him the way he taught Nalox ("call me Sir").
# Guarded: a memory_store problem falls back to his real name.
try:
    from memory_store import address_name as _addr_of
    from memory_store import address_name_bn as _addr_bn_of
except Exception:  # pragma: no cover
    def _addr_of(cfg):
        return (cfg or {}).get("user_name", "Arjun")

    def _addr_bn_of(cfg):
        name = _addr_of(cfg)
        return "অর্জুন" if name == "Arjun" else name

log = logging.getLogger("nalox.skills")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADS_DIR = os.path.join(BASE_DIR, "leads")
DEMOS_DIR = os.path.join(BASE_DIR, "demos")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
IP_GEO_URL = "http://ip-api.com/json"
USER_AGENT = "NaloxAssistant/2.0 (personal assistant; contact: owner laptop)"

CSV_FIELDS = ["name", "category", "phone", "email", "website",
              "cuisine", "address", "lat", "lon"]


# ------------------------------------------------------------------ utils
def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "business"


def _apology(lang, cfg=None):
    if lang == "bn":
        return (f"দুঃখিত {_addr_bn_of(cfg)}, এখন ম্যাপ চেক করতে "
                "পারলাম না। ইন্টারনেট কানেকশনটা দেখে আবার বলো।")
    return (f"Sorry, {_addr_of(cfg)}, I could not check the map "
            "right now. Please check the internet connection and "
            "try again.")


def _locate(cfg):
    """Return (lat, lon, place_label). home_location name wins; else IP geo."""
    import requests
    place = (cfg.get("home_location") or "").strip()
    if place:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT}, timeout=20,
        )
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"]), place
        log.warning("Nominatim found nothing for %r; falling back to IP geo.", place)
    resp = requests.get(IP_GEO_URL, timeout=15)
    data = resp.json()
    return float(data["lat"]), float(data["lon"]), data.get("city", "your area")


def _load_lead_rows():
    rows = []
    for fname in ("leads.csv", "no_website.csv"):
        path = os.path.join(LEADS_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("name"):
                        rows.append(row)
        except Exception as exc:
            log.warning("Could not read %s: %s", path, exc)
    return rows


def find_lead(name):
    """Best lead-row match for a spoken business name, or None."""
    if not name:
        return None
    needle = name.strip().lower()
    for row in _load_lead_rows():
        hay = (row.get("name") or "").lower()
        if hay and (needle in hay or hay in needle):
            return row
    return None


# ------------------------------------------------------- 1) find leads
def find_leads(cfg, lang="en"):
    """Search OpenStreetMap for nearby businesses; split by website."""
    import requests
    category = (cfg.get("lead_category") or "restaurant").strip().lower()
    try:
        radius_m = int(float(cfg.get("search_radius_km", 5)) * 1000)
    except Exception:
        radius_m = 5000

    try:
        lat, lon, place = _locate(cfg)
        query = (
            "[out:json][timeout:30];"
            f'nwr["amenity"="{category}"](around:{radius_m},{lat},{lon});'
            "out center;"
        )
        resp = requests.post(
            OVERPASS_URL, data={"data": query},
            headers={"User-Agent": USER_AGENT}, timeout=60,
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except Exception as exc:
        log.error("find_leads failed: %s", exc)
        return _apology(lang, cfg)

    rows, no_site = [], []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        website = (tags.get("website") or tags.get("contact:website") or "").strip()
        el_lat = el.get("lat") or (el.get("center") or {}).get("lat", "")
        el_lon = el.get("lon") or (el.get("center") or {}).get("lon", "")
        address = ", ".join(p for p in [
            (tags.get("addr:housenumber", "") + " " + tags.get("addr:street", "")).strip(),
            tags.get("addr:city", ""),
        ] if p)
        row = {
            "name": name,
            "category": category,
            "phone": (tags.get("phone") or tags.get("contact:phone") or "").strip(),
            "email": (tags.get("email") or tags.get("contact:email") or "").strip(),
            "website": website,
            "cuisine": (tags.get("cuisine") or "").strip(),
            "address": address,
            "lat": el_lat,
            "lon": el_lon,
        }
        rows.append(row)
        if not website:
            no_site.append(row)

    os.makedirs(LEADS_DIR, exist_ok=True)
    for fname, data in (("leads.csv", rows), ("no_website.csv", no_site)):
        path = os.path.join(LEADS_DIR, fname)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(data)
    log.info("Leads near %s: %d %ss, %d without website: %s",
             place, len(rows), category, len(no_site),
             ", ".join(r["name"] for r in no_site) or "(none)")

    names = ", ".join(r["name"] for r in no_site[:5])
    if lang == "bn":
        if not rows:
            return (f"{place}-এর কাছে কোনো {category} পেলাম না। "
                    "config-এ home_location বসালে আরও ঠিকঠাক খুঁজতে পারব।")
        return (f"{place}-এর কাছে {len(rows)}টা {category} পেয়েছি। "
                f"এর মধ্যে {len(no_site)}টার কোনো ওয়েবসাইট নেই"
                + (f": {names}।" if names else "।")
                + " পুরো লিস্ট leads ফোল্ডারে সেভ করে রেখেছি।")
    if not rows:
        return (f"I found no {category}s near {place}. "
                "Setting home_location in my config would help me search better.")
    return (f"I found {len(rows)} {category}s near {place}. "
            f"{len(no_site)} of them have no website"
            + (f": {names}." if names else ".")
            + " I saved the full list in my leads folder.")


# --------------------------------------------------- 2) build demo site
_DEMO_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} — {tagline}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI', Arial, sans-serif; }}
  body {{ color:#222; background:#faf7f2; }}
  .hero {{ background:linear-gradient(135deg,#10182b,#274b73); color:#fff;
          padding:90px 24px 70px; text-align:center; }}
  .hero h1 {{ font-size:3rem; letter-spacing:1px; }}
  .hero p {{ margin-top:14px; font-size:1.2rem; color:#f2c14e; }}
  .hero a.btn {{ display:inline-block; margin-top:28px; background:#f2c14e; color:#10182b;
          padding:12px 30px; border-radius:30px; text-decoration:none; font-weight:700; }}
  section {{ max-width:960px; margin:0 auto; padding:48px 24px; }}
  h2 {{ font-size:1.8rem; margin-bottom:16px; color:#10182b; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:18px; }}
  .card {{ background:#fff; border-radius:14px; padding:22px; box-shadow:0 4px 18px rgba(0,0,0,.08); }}
  .card h3 {{ margin-bottom:8px; color:#274b73; }}
  .price {{ color:#c98a00; font-weight:700; }}
  footer {{ background:#10182b; color:#cfd8e3; text-align:center; padding:28px 16px; font-size:.9rem; }}
  .contact p {{ margin:6px 0; font-size:1.05rem; }}
</style>
</head>
<body>
  <div class="hero">
    <h1>{name}</h1>
    <p>{tagline}</p>
    <a class="btn" href="#contact">Contact Us</a>
  </div>
  <section>
    <h2>About Us</h2>
    <p>Welcome to {name}. We are a much-loved local {category}{cuisine_line},
       serving our neighbourhood with pride. This is a demo page — imagine
       your photos, your story and your full story told right here.</p>
  </section>
  <section>
    <h2>{cards_title}</h2>
    <div class="cards">
{cards}
    </div>
  </section>
  <section class="contact" id="contact">
    <h2>Visit Us</h2>
{contact}
  </section>
  <footer>Demo website made for {name} — created by Nalox, Arjun's assistant.</footer>
</body>
</html>
"""

_MENU_ITEMS = [
    ("Chef's Special", "Our most loved signature dish, made fresh every day.", "₹299"),
    ("Family Combo", "A generous platter that feeds the whole family.", "₹599"),
    ("Fresh & Light", "Healthy, tasty and made to order.", "₹199"),
]
_SERVICE_ITEMS = [
    ("Our Speciality", "Quality work, honest prices, happy customers.", ""),
    ("Book an Appointment", "Call us and we'll keep your slot ready.", ""),
    ("Home Service", "We come to you — just ask.", ""),
]


def build_demo(cfg, name, lang="en", open_browser=True):
    """Generate demos/<slug>/index.html for a business.

    Returns (spoken_reply, slug). Uses phone/cuisine/address from the
    leads CSV when the name matches a known lead.
    """
    name = (name or "").strip()
    if not name:
        if lang == "bn":
            return "কার জন্য ওয়েবসাইট বানাব, নামটা বলো?", ""
        return "Tell me the business name and I'll build the demo website.", ""
    slug = _slugify(name)
    # Commands arrive lowercased from the brain — pretty-print ASCII names.
    display = name if any(ord(c) > 127 for c in name) else name.title()
    lead = find_lead(name) or {}
    phone = lead.get("phone", "")
    cuisine = lead.get("cuisine", "")
    address = lead.get("address", "")
    category = lead.get("category") or cfg.get("lead_category", "restaurant")

    is_food = category in ("restaurant", "cafe", "fast_food")
    items = _MENU_ITEMS if is_food else _SERVICE_ITEMS
    cards = "\n".join(
        f'      <div class="card"><h3>{html.escape(t)}</h3><p>{html.escape(d)}</p>'
        + (f'<p class="price">{html.escape(p)}</p>' if p else "")
        + "</div>"
        for t, d, p in items
    )
    contact_lines = []
    if address:
        contact_lines.append(f"    <p>📍 {html.escape(address)}</p>")
    if phone:
        contact_lines.append(f"    <p>📞 {html.escape(phone)}</p>")
    if lead.get("email"):
        contact_lines.append(f"    <p>✉️ {html.escape(lead['email'])}</p>")
    if not contact_lines:
        contact_lines.append("    <p>📍 Your address here &nbsp;•&nbsp; 📞 Your phone here</p>")

    page = _DEMO_TEMPLATE.format(
        name=html.escape(display),
        tagline=(f"Authentic {html.escape(cuisine)} food, made with love"
                 if cuisine else "Great food, warm hearts, happy customers"
                 if is_food else "Quality you can trust, service with a smile"),
        category=html.escape(category.replace("_", " ")),
        cuisine_line=f" known for our {html.escape(cuisine)} dishes" if cuisine else "",
        cards_title="Menu Highlights" if is_food else "What We Do",
        cards=cards,
        contact="\n".join(contact_lines),
    )

    out_dir = os.path.join(DEMOS_DIR, slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    log.info("Demo website built: %s", out_path)

    if open_browser:
        try:
            webbrowser.open("file:///" + out_path.replace(os.sep, "/"))
        except Exception as exc:
            log.warning("Could not open demo in browser: %s", exc)

    if lang == "bn":
        return f"হয়ে গেছে! {display}-এর জন্য ডেমো ওয়েবসাইট বানিয়ে browser-এ খুলে দিয়েছি।", slug
    return (f"Done! I made a demo website for {display} and opened it in your browser.", slug)


# ----------------------------------------------------- 3) email outreach
def email_outreach(cfg, name=None, lang="en"):
    """Email the demo pitch. name=None means 'email them' = every
    no-website lead that has an email address in the leads data."""
    bn = lang == "bn"
    if not mailer.is_configured(cfg):
        if bn:
            return (f"ইমেল এখনো সেটআপ হয়নি, {_addr_bn_of(cfg)}। config.json-এ তোমার Gmail "
                    "ঠিকানা আর একটা App Password বসাতে হবে — README-তে ধাপগুলো লেখা আছে।")
        return (f"Email is not set up yet, {_addr_of(cfg)}. Add your Gmail address and an "
                "App Password in my config file first — the README shows how.")

    targets = []
    if name:
        row = find_lead(name)
        if not row:
            if bn:
                return f"{name}-কে আমার leads লিস্টে পেলাম না। আগে 'রেস্টুরেন্ট খোঁজো' বললে লিস্ট বানিয়ে দেব।"
            return (f"I don't have {name} in my leads list yet. "
                    "Ask me to find restaurants near you first.")
        if not (row.get("email") or "").strip():
            if bn:
                return (f"{name}-এর কোনো ইমেল ঠিকানা ডেটায় পাইনি, তাই মেইল পাঠাতে পারছি না। "
                        "আমি কখনো ঠিকানা বানিয়ে নিই না।")
            return (f"{name} has no email address in the data I found, so I can't "
                    "email them. I never invent addresses.")
        targets = [row]
    else:
        targets = [r for r in _load_lead_rows()
                   if not (r.get("website") or "").strip()
                   and (r.get("email") or "").strip()]
        # De-duplicate by business name.
        seen, unique = set(), []
        for r in targets:
            key = r["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(r)
        targets = unique
        if not targets:
            if bn:
                return ("যেসব ব্যবসার ওয়েবসাইট নেই, তাদের কারো ইমেল ঠিকানা ম্যাপের "
                        "ডেটায় পাইনি — তাই এখন কাউকে মেইল পাঠানো যাচ্ছে না।")
            return ("None of the businesses without a website had an email address "
                    "in the map data, so there is nobody I can email yet.")

    base = (cfg.get("demo_base_url") or "").strip().rstrip("/")
    sent, failed = 0, 0
    for row in targets:
        _reply, slug = build_demo(cfg, row["name"], lang=lang, open_browser=False)
        link = f"{base}/{slug}/" if base else None
        if mailer.send_pitch(cfg, row["email"].strip(), row["name"], link):
            sent += 1
        else:
            failed += 1

    names = ", ".join(r["name"] for r in targets[:5])
    if bn:
        reply = f"{sent}টা ইমেল পাঠিয়েছি: {names}।"
        if failed:
            reply += f" {failed}টা পাঠাতে পারিনি — log-এ কারণ আছে।"
    else:
        reply = f"I sent {sent} email{'s' if sent != 1 else ''}: {names}."
        if failed:
            reply += f" {failed} failed — the log has the details."
    if not base:
        reply += (" তবে একটা কথা — ডেমোগুলো এখন এই laptop-এই আছে; সবার জন্য "
                  "link কাজ করাতে demo_base_url config-এ বসাতে হবে।" if bn else
                  " One honest note: the demos are saved on this laptop for now; "
                  "add a demo_base_url in config after hosting them so the links "
                  "work for everyone.")
    return reply


# ------------------------------------------------------------------ news
def fetch_headlines(limit=3):
    """Top headlines from Google News RSS (India, English).

    Duplicated from nalox.py so brain.py can answer "আজকের খবর"
    without importing the main module. Returns [] on any failure.
    """
    try:
        import requests
        import xml.etree.ElementTree as ET
        resp = requests.get(
            "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
            timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if title:
                titles.append(title.rsplit(" - ", 1)[0])  # drop the source
            if len(titles) >= limit:
                break
        return titles
    except Exception as exc:
        log.info("Headlines skipped: %s", exc)
        return []


# ---------------------------------------------------------------- weather
def fetch_weather(cfg):
    """Current weather from OpenWeatherMap (v4.3, digest section).

    Needs config openweather_api_key; city from config weather_city
    (default "Kolkata"). Returns {city, temp, condition} or None —
    no key / no network / bad key all quietly mean "no section".
    """
    key = (cfg.get("openweather_api_key") or "").strip()
    if not key:
        return None
    city = (cfg.get("weather_city") or "Kolkata").strip() or "Kolkata"
    try:
        import requests
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": key, "units": "metric"},
            timeout=6)
        resp.raise_for_status()
        data = resp.json()
        main = data.get("main") or {}
        weather = (data.get("weather") or [{}])[0]
        return {
            "city": data.get("name") or city,
            "temp": round(float(main.get("temp"))),
            "condition": (weather.get("description") or "").strip(),
        }
    except Exception as exc:
        log.info("Weather skipped: %s", exc)
        return None


# ------------------------------------------------------------------ gmail
def gmail_creds(cfg):
    """(address, app_password) for Gmail reading.

    The dedicated gmail_* keys win; when they are empty, the
    mailer's email_address / email_app_password are used — it is
    the same Gmail account and the same app password.
    """
    addr = (cfg.get("gmail_address") or cfg.get("email_address")
            or "").strip()
    pw = (cfg.get("gmail_app_password")
          or cfg.get("email_app_password") or "").strip()
    return addr, pw


def gmail_is_setup(cfg):
    addr, pw = gmail_creds(cfg)
    return bool(addr and pw)


def _decode_header_value(raw):
    """Decode a MIME header (From/Subject) to a plain string."""
    try:
        from email.header import decode_header
        parts = []
        for chunk, charset in decode_header(raw or ""):
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8",
                                          errors="replace"))
            else:
                parts.append(str(chunk))
        return " ".join(parts).strip()
    except Exception:
        return str(raw or "").strip()


def _gmail_connect(cfg):
    """Logged-in IMAP connection with INBOX selected (caller closes)."""
    import imaplib
    addr, pw = gmail_creds(cfg)
    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    conn.login(addr, pw)
    conn.select("INBOX", readonly=True)
    return conn


def gmail_unread_count(cfg):
    """Number of unread emails in the inbox. None on any failure."""
    if not gmail_is_setup(cfg):
        return None
    conn = None
    try:
        conn = _gmail_connect(cfg)
        _typ, data = conn.search(None, "UNSEEN")
        if data and data[0]:
            return len(data[0].split())
        return 0
    except Exception as exc:
        log.info("Gmail unread count failed: %s", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def gmail_latest_unread(cfg, n=5):
    """Newest-first unread mail: [{from, subject}]. [] on failure."""
    if not gmail_is_setup(cfg):
        return []
    conn = None
    try:
        import email as email_lib
        conn = _gmail_connect(cfg)
        _typ, data = conn.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []
        out = []
        for msg_id in reversed(ids[-int(n):]):
            try:
                _typ, fetched = conn.fetch(
                    msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                raw = b""
                for part in fetched or []:
                    if isinstance(part, tuple) and len(part) > 1 \
                            and isinstance(part[1], bytes):
                        raw = part[1]
                        break
                msg = email_lib.message_from_bytes(raw)
                sender = _decode_header_value(msg.get("From") or "")
                # "Name <a@b.c>" -> "Name" for speaking.
                sender = sender.split("<")[0].strip().strip('"') \
                    or sender
                out.append({
                    "from": sender or "unknown sender",
                    "subject": _decode_header_value(
                        msg.get("Subject") or "") or "(no subject)",
                })
            except Exception:
                continue
        return out
    except Exception as exc:
        log.info("Gmail latest unread failed: %s", exc)
        return []
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


# ------------------------------------------------------- morning digest
def _digest_battery_line(bn):
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is not None:
            pct = int(batt.percent)
            if bn:
                from brain import _bn_num
                return f"ব্যাটারি {_bn_num(pct)} শতাংশ আছে।"
            return f"Battery is at {pct} percent."
    except Exception:
        pass
    return ""


def digest(cfg, brain=None, reminders=None, lang="en",
           youtube_first=False):
    """Morning Digest 2.0 (v4.3). Returns (spoken_text, telegram_text).

    Ordered sections (each one failure-isolated and silently
    skipped when its source is off / unset / unreachable):
      greeting + date/time -> battery -> YouTube channel stats
      (FIRST when youtube_first — Creator mode) -> reminders due
      today -> news headlines (only when briefing_news is on;
      taste-filtered by the digest skip list) -> weather (only
      when an OpenWeatherMap key is set).
    `reminders` may be a ReminderStore or a list of pending dicts.
    """
    from datetime import datetime
    bn = str(lang or "en").lower().startswith("bn")
    now = datetime.now()
    user = _addr_of(cfg)
    lines = []

    # ---- greeting + date/time ----
    if bn:
        from brain import _BN_MONTHS, _BN_WEEKDAYS, _bn_num
        hour12 = now.hour % 12 or 12
        if now.hour < 4:
            part, greet = "রাত", "শুভ রাত্রি"
        elif now.hour < 12:
            part, greet = "সকাল", "শুভ সকাল"
        elif now.hour < 16:
            part, greet = "দুপুর", "শুভ দুপুর"
        elif now.hour < 19:
            part, greet = "বিকেল", "শুভ বিকেল"
        else:
            part, greet = "রাত", "শুভ সন্ধ্যা"
        lines.append(
            f"{greet}, {_addr_bn_of(cfg)}। আজ {_BN_WEEKDAYS[now.weekday()]}, "
            f"{_bn_num(now.day)} {_BN_MONTHS[now.month - 1]}। এখন {part} "
            f"{_bn_num(hour12)}টা বেজে {_bn_num(f'{now.minute:02d}')} মিনিট।")
    else:
        if now.hour < 12:
            greet = "Good morning"
        elif now.hour < 17:
            greet = "Good afternoon"
        else:
            greet = "Good evening"
        lines.append(
            f"{greet}, {user}. Today is {now.strftime('%A')}, "
            f"{now.day} {now.strftime('%B')}, "
            f"{now.strftime('%I:%M %p').lstrip('0')}.")

    battery = _digest_battery_line(bn)
    if battery:
        lines.append(battery)

    # ---- YouTube channel stats (skip silently when not set up) ----
    yt_line = ""
    try:
        import youtube_tools
        if youtube_tools.is_setup():
            stats = youtube_tools.channel_stats()
            if stats:
                yt_line = youtube_tools.stats_line(stats)
    except Exception as exc:
        log.info("Digest YouTube section skipped: %s", exc)
    if yt_line:
        if youtube_first:
            lines.insert(1, yt_line)
        else:
            lines.append(yt_line)

    # ---- reminders due today ----
    try:
        pending = []
        if reminders is not None:
            if hasattr(reminders, "pending"):
                pending = reminders.pending()
            elif isinstance(reminders, (list, tuple)):
                pending = list(reminders)
        today = now.date().isoformat()
        todays = []
        for item in pending:
            due = str(item.get("due") or "")
            if due.startswith(today):
                todays.append(item)
        if todays:
            bits = []
            for item in todays[:4]:
                try:
                    when = datetime.fromisoformat(item["due"]) \
                        .strftime("%I:%M %p").lstrip("0")
                except Exception:
                    when = ""
                bits.append(f"{item.get('text', '')}"
                            + (f" at {when}" if when else ""))
            if bn:
                lines.append("আজকের রিমাইন্ডার: " + "; ".join(bits) + "।")
            else:
                lines.append("Reminders today: " + "; ".join(bits) + ".")
    except Exception as exc:
        log.info("Digest reminders section skipped: %s", exc)

    # ---- news (only when briefing_news is on; taste-filtered) ----
    if cfg.get("briefing_news", False):
        try:
            titles = fetch_headlines(6)
            try:
                import memory_store
                skips = memory_store.load_digest_skips()
            except Exception:
                skips = []
            if skips:
                titles = [t for t in titles
                          if not any(s in t.lower() for s in skips)]
            titles = titles[:3]
            if titles:
                if bn:
                    from brain import _bn_num
                    lines.append("আজকের বড় খবর: " + " ".join(
                        f"{_bn_num(i + 1)}. {t}।"
                        for i, t in enumerate(titles)))
                else:
                    lines.append("Top news: " + " ".join(
                        f"{i + 1}. {t}." for i, t in enumerate(titles)))
        except Exception as exc:
            log.info("Digest news section skipped: %s", exc)

    # ---- weather (only when an OpenWeatherMap key is set) ----
    try:
        weather = fetch_weather(cfg)
        if weather:
            if bn:
                from brain import _bn_num
                lines.append(
                    f"{weather['city']}-এ এখন "
                    f"{_bn_num(weather['temp'])} ডিগ্রি, "
                    f"{weather['condition']}।")
            else:
                lines.append(
                    f"Weather in {weather['city']}: "
                    f"{weather['temp']} degrees, {weather['condition']}.")
    except Exception as exc:
        log.info("Digest weather section skipped: %s", exc)

    spoken = " ".join(lines)
    telegram = "☀️ Nalox digest\n" + "\n".join(lines)
    return spoken, telegram


def push_digest(cfg, telegram_text):
    """Send the digest to Arjun's phone (Telegram). Guarded."""
    try:
        import telegram_bridge
        return telegram_bridge.send_message(cfg, telegram_text)
    except Exception as exc:
        log.info("Digest Telegram push skipped: %s", exc)
        return False
