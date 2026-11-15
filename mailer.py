"""Nalox's mailer: Gmail outreach for the demo-website skill.

Uses smtplib with smtp.gmail.com:587 + STARTTLS. Needs a Gmail
APP PASSWORD (not the normal account password) — see README:
Google Account -> Security -> 2-Step Verification -> App passwords.

Config keys: "email_address" and "email_app_password".
If either is empty, email commands politely refuse (see skills.py).
Every send is logged.
"""
import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger("nalox.mailer")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def is_configured(cfg):
    return bool((cfg.get("email_address") or "").strip()
                and (cfg.get("email_app_password") or "").strip())


def send_pitch(cfg, to_email, business_name, demo_link=None):
    """Send the demo-website pitch to one business. Returns True/False.

    demo_link: public URL of the demo, or None when the demo only exists
    locally (demo_base_url not configured) — the email is honest about it.
    """
    sender = (cfg.get("email_address") or "").strip()
    password = (cfg.get("email_app_password") or "").strip()
    owner = cfg.get("user_name", "Arjun")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = f"A free demo website for {business_name}"

    if demo_link:
        link_line = f"You can see the demo here: {demo_link}\n"
    else:
        link_line = ("I have the demo ready on my computer and can put it "
                     "live for you right away if you like it.\n")

    msg.set_content(
        f"Hello {business_name} team,\n\n"
        f"I noticed {business_name} doesn't have a website yet, so I built "
        f"a small demo website for your business — completely free to look "
        f"at, no obligation at all.\n"
        f"{link_line}\n"
        f"If you like it, I can set it up properly for you (your own domain, "
        f"menu, photos, online orders — whatever you need). If not, no "
        f"worries at all.\n\n"
        f"Just reply to this email and we'll take it from there.\n\n"
        f"Best regards,\n{owner}\n"
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        log.info("EMAIL SENT: pitch to %s (%s), demo link: %s",
                 business_name, to_email, demo_link or "(local only)")
        return True
    except Exception as exc:
        log.error("EMAIL FAILED to %s (%s): %s", business_name, to_email, exc)
        return False
