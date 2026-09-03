from __future__ import annotations
"""
mail_senders.py — Mail sender factory with priority-based fallback.

To add a new mail client:
  1. Subclass BaseSender and implement send_one(to, subject, body) -> bool
  2. Register it in MailSenderFactory([...]) in bus_tracker.py (lower index = higher priority)
"""

import smtplib
import time
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseSender:
    """All mail senders must implement this interface."""
    name: str = "base"
    # Seconds to wait between recipients (rate limit)
    rate_limit_sleep: float = 1.0

    def send_one(self, to: str, subject: str, body: str) -> bool:
        """Send to a single recipient. Return True on success, False on failure."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Sender implementations
# ---------------------------------------------------------------------------

class SmtpSender(BaseSender):
    """Direct SMTP sender with STARTTLS (e.g. Oracle Cloud SMTP, Gmail, etc.)"""
    name = "SMTP"
    rate_limit_sleep = 0.0  # No API rate limit for direct SMTP

    def __init__(self, host: str, port: int, username: str, password: str, from_address: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address

    def send_one(self, to: str, subject: str, body: str) -> bool:
        if not all([self.host, self.username, self.password, self.from_address]):
            print(f"[{self.name}] Skipping — SMTP credentials not fully configured.")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_address
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))  # body is HTML

            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.username, self.password)
                server.sendmail(self.from_address, to, msg.as_string())

            print(f"[{self.name}] Sent to {to} via {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[{self.name}] Exception: {e}")
            return False


class HourMailerSender(BaseSender):
    """https://rapidapi.com/hourmailer"""
    name = "HourMailer"
    rate_limit_sleep = 1.0

    def __init__(self, api_key: str):
        self.api_key = api_key

    def send_one(self, to: str, subject: str, body: str) -> bool:
        if not self.api_key:
            return False
        url = "https://hourmailer.p.rapidapi.com/send"
        headers = {
            "content-type": "application/json",
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "hourmailer.p.rapidapi.com",
        }
        payload = {"toAddress": to, "title": subject, "message": body}
        try:
            resp = requests.request("POST", url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                print(f"[{self.name}] Sent to {to} — {resp.text[:120]}")
                return True
            print(f"[{self.name}] Failed ({resp.status_code}) — {resp.text[:120]}")
            return False
        except Exception as e:
            print(f"[{self.name}] Exception: {e}")
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class MailSenderFactory:
    """
    Tries each sender in priority order (index 0 = highest priority).
    Falls back to the next sender if the current one fails for any recipient.
    """

    def __init__(self, senders: list[BaseSender]):
        self.senders = senders  # ordered by priority

    def send(self, recipients: list[str], subject: str, body: str) -> bool:
        """
        Send to all recipients using the highest-priority working sender.
        Falls back to the next sender if one fails.
        Returns True if all recipients received the email, False otherwise.
        """
        for sender in self.senders:
            print(f"[MailFactory] Trying sender: {sender.name}")
            all_ok = True

            for i, to in enumerate(recipients):
                to = to.strip()
                if not to:
                    continue
                if i > 0:
                    time.sleep(sender.rate_limit_sleep)

                success = sender.send_one(to, subject, body)
                if not success:
                    all_ok = False
                    break  # try next sender from scratch

            if all_ok:
                return True
            print(f"[MailFactory] {sender.name} failed — trying next sender...")

        print("[MailFactory] All senders exhausted. Email not sent.")
        return False
