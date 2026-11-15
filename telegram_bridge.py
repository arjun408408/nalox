"""Phone connection: Telegram bridge.

Arjun talks to Nalox from his phone through a Telegram bot.
Only messages from the OWNER chat id are accepted.

SETUP (also in README.md):
  1. In Telegram, talk to @BotFather -> /newbot -> copy the bot token.
  2. Paste the token into config.json as "telegram_bot_token".
  3. Send any message to your new bot from your phone.
  4. Nalox prints your chat id in logs/nalox.log — paste it into
     config.json as "telegram_owner_chat_id" and restart Nalox.

If the token is empty, this module stays silently off.

v5.3 FIX (the 2026-11-15 boot death): this bridge used to start
polling with _offset = 0 and NO queue flush, so the first
getUpdates delivered every pending unacknowledged update
(Telegram keeps them ~24 h) and _handle executed them as if
live — including a "stop" Arjun had sent the bot while Nalox
was off, which returned brain action "exit" and killed the
fresh boot with os._exit(42) eight seconds in. Two defences
now, both in this module:
  1. run() FLUSHES the pending queue at startup — every queued
     update is discarded (and thereby acknowledged) unexecuted,
     with the count written to the logbook.
  2. A DATE GUARD drops any message dated before this bridge
     started (minus 120 s of slack), flush or no flush.
(The exit path itself is unchanged: this bridge exits only
on brain action "exit". v5.4 note: a "stop"/goodbye no longer
produces "exit" anywhere — brain returns "standby" (stop
speaking, keep listening) — so a Telegram "stop" now just
gets the standby reply and Nalox stays alive. Action "exit"
survives only for a confirmed PC shutdown/restart, where the
machine itself is going down anyway.)
"""
import logging
import os
import threading
import time

log = logging.getLogger("nalox.telegram")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _logbook(category, text):
    """Mirror one line into the 📋 Log page (v5.3).

    The bridge's own logger never reached the logbook, which is
    why the v5.2 boot death showed no cause on the page Arjun
    screenshots. Lazy import (logbook is stdlib-only and never
    raises) + a guard: a logging failure must never hurt the
    bridge."""
    try:
        import logbook
        logbook.log(category, text)
    except Exception:
        pass


def send_message(cfg, text):
    """One-shot send to the owner's chat (v4.3 — the morning digest
    push). Uses the same bot token + owner chat id as the bridge.
    Returns True/False; never raises."""
    token = (cfg.get("telegram_bot_token") or "").strip()
    owner = str(cfg.get("telegram_owner_chat_id") or "").strip()
    if not token or not owner or not text:
        return False
    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": owner, "text": str(text)[:4000]},
            timeout=15)
        return bool(resp.ok)
    except Exception as exc:
        log.warning("Telegram send_message failed: %s", exc)
        return False


class TelegramBridge(threading.Thread):
    def __init__(self, cfg, brain, speaker, ears):
        super().__init__(daemon=True, name="telegram-bridge")
        self.cfg = cfg
        self.brain = brain
        self.speaker = speaker
        self.ears = ears
        self.token = (cfg.get("telegram_bot_token") or "").strip()
        self.owner = str(cfg.get("telegram_owner_chat_id") or "").strip()
        self.api = f"https://api.telegram.org/bot{self.token}"
        self._offset = 0
        # v5.3: when this bridge started (epoch seconds) — the
        # date guard in _handle drops anything older than this
        # minus a slack, so a message sent while Nalox was off
        # can never execute. Set in run(); None until then.
        self._started_at = None

    # ------------------------------------------------------------------
    def _post(self, method, **params):
        import requests
        resp = requests.post(f"{self.api}/{method}", json=params, timeout=35)
        return resp.json()

    def _fetch_updates(self, offset, poll_timeout, http_timeout):
        """One getUpdates call with explicit offsets/timeouts.
        Returns the result list; RAISES on transport/HTTP errors
        (callers guard)."""
        import requests
        resp = requests.get(
            f"{self.api}/getUpdates",
            params={"offset": offset, "timeout": poll_timeout},
            timeout=http_timeout,
        )
        return resp.json().get("result", [])

    def _get_updates(self):
        return self._fetch_updates(self._offset, 25, 35)

    def _flush_pending(self):
        """v5.3 STARTUP QUEUE FLUSH: discard every update that
        queued up while Nalox was off, WITHOUT handling any of
        them, and advance _offset past the newest one.

        Telegram acknowledges updates once getUpdates is called
        with an offset above their id, so each fetch below (and
        the main loop's first poll with the final offset) confirms
        the batch before it server-side — the poisoned queue can
        never be delivered twice. Failure-isolated: any error is
        logged and the bridge continues into the normal loop,
        where the _handle date guard is the second line of
        defence."""
        discarded = 0
        try:
            for _ in range(10):  # bounded: <= 1000 queued updates
                pending = self._fetch_updates(self._offset, 0, 10)
                if not pending:
                    break
                discarded += len(pending)
                self._offset = max(u["update_id"] for u in pending) + 1
                if len(pending) < 100:  # a short page = the end
                    break
        except Exception as exc:
            log.warning("Telegram queue flush failed: %s", exc)
            _logbook("SYSTEM",
                     "Telegram: could not clear the old queued "
                     f"messages ({exc}) — anything sent before this "
                     "start will be ignored by its date instead.")
            return
        log.info("Telegram: discarded %d queued update(s) from "
                 "while Nalox was off.", discarded)
        _logbook("SYSTEM",
                 f"Telegram: discarded {discarded} queued "
                 "message(s) from while Nalox was off")

    def _send(self, chat_id, text):
        try:
            self._post("sendMessage", chat_id=chat_id, text=text[:4000])
        except Exception as exc:
            log.warning("Telegram send failed: %s", exc)

    # ------------------------------------------------------------------
    def run(self):
        # v5.3: the date guard's reference point — recorded
        # before anything can be handled.
        self._started_at = time.time()
        if not self.token:
            log.info("Telegram bridge off (no bot token in config).")
            return
        log.info("Telegram bridge started. Owner chat id: %s",
                 self.owner or "(not set yet — send the bot a message!)")
        # v5.3: throw away everything that arrived while Nalox
        # was off BEFORE the first live poll (see _flush_pending).
        self._flush_pending()
        while True:
            try:
                updates = self._get_updates()
            except Exception as exc:
                log.warning("Telegram poll error: %s", exc)
                time.sleep(5)
                continue
            for upd in updates:
                self._offset = upd["update_id"] + 1
                try:
                    self._handle(upd)
                except Exception as exc:
                    log.error("Telegram update error: %s", exc)

    def _handle(self, upd):
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # v5.3 DATE GUARD (belt & braces behind the startup
        # flush): a message dated before this bridge started
        # (120 s slack for clock skew) was sent while Nalox was
        # off or is a redelivery — NEVER execute it, whatever it
        # says. Applies to message and edited_message alike.
        sent_at = msg.get("date") or 0
        if (self._started_at and sent_at
                and sent_at < self._started_at - 120):
            when = time.strftime("%H:%M:%S",
                                 time.localtime(sent_at))
            log.info("Telegram: dropping stale queued message "
                     "from chat %s (sent %s, before this start).",
                     chat_id, when)
            _logbook("SYSTEM",
                     "Telegram: ignored an old queued message "
                     f"sent while Nalox was off (sent at {when}) "
                     "— not executed")
            return

        # First contact: help Arjun find his chat id.
        if not self.owner:
            log.info("TELEGRAM SETUP: message received from chat id %s. "
                     "Put this number into config.json as telegram_owner_chat_id "
                     "and restart Nalox.", chat_id)
            self._send(chat_id,
                       f"Hi! I'm Nalox. Your chat id is {chat_id}. "
                       "Add it to config.json (telegram_owner_chat_id) and restart me.")
            return

        if chat_id != self.owner:
            log.warning("Ignoring Telegram message from non-owner chat %s", chat_id)
            return

        text = msg.get("text", "").strip()

        # Voice message -> download + transcribe with the same Whisper.
        if "voice" in msg or "audio" in msg:
            text = self._transcribe_voice(msg.get("voice") or msg.get("audio"))
            if not text:
                self._send(chat_id, "Sorry, I couldn't understand that voice message.")
                return
            self._send(chat_id, f"🎙 You said: {text}")

        if not text:
            return

        reply, action = self.brain.handle(text)
        if reply:
            self._send(chat_id, reply)
            if self.cfg.get("speak_telegram_commands", True) and action != "exit":
                self.speaker.say(reply, lang=getattr(self.brain, "last_lang", None))
        if action == "exit":
            log.info("Exit requested from Telegram.")
            os._exit(42)  # supervisor treats 42 as a clean, do-not-restart exit

    def _transcribe_voice(self, voice):
        try:
            import requests
            file_id = voice["file_id"]
            info = requests.get(f"{self.api}/getFile",
                                params={"file_id": file_id}, timeout=15).json()
            file_path = info["result"]["file_path"]
            url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "logs", "telegram_voice.ogg")
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(requests.get(url, timeout=30).content)
            text, _lang = self.ears.transcribe_file(local)
            return text
        except Exception as exc:
            log.error("Voice transcription failed: %s", exc)
            return ""
