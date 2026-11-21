"""Gmail (Google Workspace or personal) mailbox, read-only.

OAuth scope: https://www.googleapis.com/auth/gmail.readonly (cannot send, delete, move or label mail).
Attachments are downloaded with users.messages.attachments.get, whose `data` is URL-safe base64
without padding; it is decoded with intake.files.b64decode_any and then checked like any upload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parseaddr

import httpx

from ...config import get_settings
from ..intake.files import b64decode_any
from .http import MailboxAuthError, MailboxTransient, request
from .parse import ParsedEmail, _html_to_text

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "openid", "email"]


class GmailClient:
    def __init__(self, tokens: dict, http: httpx.Client | None = None, on_tokens=None, sleep=None):
        self.tokens = dict(tokens)
        self.http = http or httpx.Client(timeout=90)
        self.on_tokens = on_tokens          # called with refreshed tokens so they can be re-encrypted and saved
        self._sleep = sleep

    # ---- auth
    def refresh(self):
        s = get_settings()
        rt = self.tokens.get("refresh_token")
        if not rt:
            raise MailboxAuthError("Reconnect needed: no refresh token")
        r = request(self.http, "POST", TOKEN_URL, data={"client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                                         "refresh_token": rt, "grant_type": "refresh_token"}, **self._kw())
        if r.status_code in (400, 401):
            raise MailboxAuthError("Reconnect needed: Google access expired or was revoked")
        r.raise_for_status()
        j = r.json()
        self.tokens["access_token"] = j["access_token"]
        if self.on_tokens:
            self.on_tokens(self.tokens)

    def _kw(self):
        return {"sleep": self._sleep} if self._sleep else {}

    def get(self, path: str, **params) -> dict:
        if not self.tokens.get("access_token"):
            self.refresh()
        for attempt in range(2):
            r = request(self.http, "GET", API + path, params=params, headers={"Authorization": "Bearer " + self.tokens.get("access_token", "")}, **self._kw())
            if r.status_code == 401 and attempt == 0:
                self.refresh()
                continue
            if r.status_code == 403:
                raise MailboxAuthError("Reconnect needed: Gmail access was not granted (read-only permission missing)")
            if r.status_code == 404:
                raise FileNotFoundError(path)
            if r.status_code >= 400:
                raise MailboxTransient(f"Gmail error {r.status_code}")
            return r.json()
        raise MailboxAuthError("Reconnect needed: Google access expired")

    # ---- reading
    def profile(self) -> dict:
        return self.get("/profile")

    def list_ids(self, query: str, limit: int = 500) -> list[str]:
        ids, token = [], None
        while len(ids) < limit:
            params = {"q": query, "maxResults": 100}
            if token:
                params["pageToken"] = token
            j = self.get("/messages", **params)
            ids += [m["id"] for m in j.get("messages", [])]
            token = j.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def message(self, mid: str) -> tuple[ParsedEmail, list[dict]]:
        """The email (without file bytes) and the list of its attachments to fetch."""
        m = self.get(f"/messages/{mid}", format="full")
        payload = m.get("payload", {})
        hdr = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        name, addr = parseaddr(hdr.get("from", ""))
        texts, htmls, atts = [], [], []
        _walk(payload, texts, htmls, atts, mid)
        body = "\n".join(texts) if texts else _html_to_text("\n".join(htmls))
        when = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, tz=timezone.utc) if m.get("internalDate") else datetime.now(timezone.utc)
        mid_hdr = hdr.get("message-id") or f"<gmail-{mid}@mail.gmail.com>"
        return ParsedEmail(mid_hdr.strip(), name or addr, addr.lower(), hdr.get("subject", ""), body.strip(), when, [],
                           thread_id="gmail:" + m.get("threadId", ""), remote_id=mid), atts

    def attachment(self, mid: str, att: dict) -> bytes:
        if att.get("data"):
            return b64decode_any(att["data"])
        j = self.get(f"/messages/{mid}/attachments/{att['attachment_id']}")
        return b64decode_any(j.get("data", ""))


def _walk(part: dict, texts: list, htmls: list, atts: list, mid: str, nested: str = ""):
    mime = (part.get("mimeType") or "").lower()
    fname = part.get("filename") or ""
    body = part.get("body") or {}
    hdr = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    disp = hdr.get("content-disposition", "").lower()
    if fname or body.get("attachmentId") and not mime.startswith("text/"):
        if mime == "message/rfc822" and not fname:
            fname = "attached-message.eml"
        atts.append({"name": fname or "attachment", "mime": mime, "size": int(body.get("size") or 0),
                     "inline": disp.startswith("inline") or ("content-id" in hdr and not disp.startswith("attachment")),
                     "attachment_id": body.get("attachmentId", ""), "data": body.get("data", "") if not body.get("attachmentId") else "",
                     "nested": nested})
        if mime == "message/rfc822" and part.get("parts"):
            # Gmail sometimes also expands an attached email: its files are taken from the .eml itself
            return
        return
    if mime == "text/plain" and body.get("data") and not nested:
        texts.append(b64decode_any(body["data"]).decode("utf-8", "replace"))
    elif mime == "text/html" and body.get("data") and not nested:
        htmls.append(b64decode_any(body["data"]).decode("utf-8", "replace"))
    for sub in part.get("parts", []) or []:
        _walk(sub, texts, htmls, atts, mid, nested or ("fwd" if mime == "message/rfc822" else ""))


def auth_url(state: str, redirect_uri: str, login_hint: str = "") -> str:
    from urllib.parse import urlencode
    s = get_settings()
    q = {"client_id": s.google_client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state}
    if login_hint:
        q["login_hint"] = login_hint
    return AUTH_URL + "?" + urlencode(q)


def exchange_code(code: str, redirect_uri: str, http: httpx.Client | None = None) -> dict:
    s = get_settings()
    http = http or httpx.Client(timeout=30)
    r = request(http, "POST", TOKEN_URL, data={"code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                                "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    if r.status_code >= 400:
        raise MailboxAuthError("Google sign-in failed: " + (r.json().get("error_description") or r.json().get("error") or str(r.status_code)))
    j = r.json()
    granted = set((j.get("scope") or "").split())
    if "https://www.googleapis.com/auth/gmail.readonly" not in granted:
        raise MailboxAuthError("Gmail read-only permission was not granted")
    return {"access_token": j["access_token"], "refresh_token": j.get("refresh_token", ""), "scope": j.get("scope", "")}
