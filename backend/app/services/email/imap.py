"""IMAP intake for non-Microsoft mailboxes (Gmail, web hosts, other providers). Use an app password."""
from __future__ import annotations

import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


class ImapClient:
    def __init__(self, host: str, port: int, user: str, password: str, folder: str = "INBOX"):
        self.host, self.port, self.user, self.password = host, int(port or 993), user, password
        self.folder = folder if folder and folder.lower() != "inbox" else "INBOX"

    def __enter__(self):
        try:
            self.M = imaplib.IMAP4_SSL(self.host, self.port, timeout=60)
            self.M.login(self.user, self.password)
        except (OSError, imaplib.IMAP4.error) as e:
            raise RuntimeError(f"Could not sign in to {self.host} as {self.user}: {e}. Check the server, port and app password.")
        typ, data = self.M.select(f'"{self.folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Folder '{self.folder}' not found on {self.host}.")
        self.count = int((data or [b"0"])[0] or 0)
        return self

    def __exit__(self, *a):
        try:
            self.M.logout()
        except Exception:
            pass

    def uids_after(self, last: int) -> list[int]:
        typ, data = self.M.uid("search", None, f"UID {last + 1}:*")
        return [u for u in (int(x) for x in (data[0] or b"").split()) if u > last]

    def uids_since(self, days: int) -> list[int]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = self.M.uid("search", None, f"SINCE {since}")
        return [int(x) for x in (data[0] or b"").split()]

    def max_uid(self) -> int:
        typ, data = self.M.uid("search", None, "ALL")
        ids = [int(x) for x in (data[0] or b"").split()]
        return max(ids) if ids else 0

    def fetch(self, uid: int) -> bytes | None:
        typ, msg = self.M.uid("fetch", str(uid), "(RFC822)")
        return next((part[1] for part in msg or [] if isinstance(part, tuple)), None)


GUESS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
         "yahoo.com": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com", "zoho.com": "imap.zoho.com"}


def guess_host(address: str) -> str:
    dom = address.split("@")[-1].lower()
    return GUESS.get(dom, f"imap.{dom}" if re.match(r"^[a-z0-9.-]+$", dom) else "")
