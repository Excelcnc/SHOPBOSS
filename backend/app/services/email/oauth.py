"""OAuth for linking mailboxes (read-only scopes only). The `state` parameter is a signed, short-lived token
carrying the shop, the user and the back-fill choice, so the callback needs no session cookie."""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from ...config import get_settings
from ...crypto import sign, verify
from . import gmail
from .graph import DELEGATED_SCOPES
from .http import MailboxAuthError, request

PROVIDERS = ("gmail", "graph")


def redirect_uri(provider: str) -> str:
    return get_settings().public_base_url.rstrip("/") + f"/api/mailboxes/oauth/{provider}/callback"


def configured(provider: str) -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret) if provider == "gmail" else bool(s.ms_oauth_client_id and s.ms_oauth_client_secret)


def start(provider: str, shop_id: str, user_id: str, backfill_days: int, keywords: str | None) -> str:
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    if not configured(provider):
        raise MailboxAuthError(f"{'Google' if provider == 'gmail' else 'Microsoft 365'} sign-in is not configured on the server yet (see docs/EMAIL_FILES.md)")
    st = sign({"p": provider, "s": shop_id, "u": user_id, "b": int(backfill_days), "k": keywords, "n": secrets.token_urlsafe(8)}, ttl_s=900)
    if provider == "gmail":
        return gmail.auth_url(st, redirect_uri("gmail"))
    s = get_settings()
    q = {"client_id": s.ms_oauth_client_id, "response_type": "code", "redirect_uri": redirect_uri("graph"), "response_mode": "query",
         "scope": " ".join(DELEGATED_SCOPES), "state": st, "prompt": "select_account"}
    return f"https://login.microsoftonline.com/{s.ms_oauth_tenant}/oauth2/v2.0/authorize?" + urlencode(q)


def read_state(state: str) -> dict:
    body = verify(state or "")
    if not body or body.get("p") not in PROVIDERS:
        raise MailboxAuthError("The sign-in link expired. Start linking the mailbox again.")
    return body


def exchange(provider: str, code: str, http: httpx.Client | None = None) -> tuple[dict, str]:
    """Returns (tokens, mailbox address)."""
    http = http or httpx.Client(timeout=30)
    if provider == "gmail":
        tokens = gmail.exchange_code(code, redirect_uri("gmail"), http)
        addr = gmail.GmailClient(tokens, http=http).profile().get("emailAddress", "")
        return tokens, addr.lower()
    s = get_settings()
    r = request(http, "POST", f"https://login.microsoftonline.com/{s.ms_oauth_tenant}/oauth2/v2.0/token",
                data={"client_id": s.ms_oauth_client_id, "client_secret": s.ms_oauth_client_secret, "grant_type": "authorization_code",
                      "code": code, "redirect_uri": redirect_uri("graph"), "scope": " ".join(DELEGATED_SCOPES)})
    if r.status_code >= 400:
        raise MailboxAuthError("Microsoft sign-in failed: " + str(r.json().get("error_description", r.status_code))[:200])
    j = r.json()
    granted = {x.lower() for x in (j.get("scope") or "").split()}
    if not any(x.endswith("mail.read") for x in granted):
        raise MailboxAuthError("Mail.Read (read-only) permission was not granted")
    tokens = {"refresh_token": j.get("refresh_token", ""), "access_token": j.get("access_token", "")}
    from .graph import GraphClient
    c = GraphClient.for_user(tokens, http=http)
    c._token = tokens["access_token"]
    from datetime import datetime, timedelta, timezone
    c._exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    me = c.me()
    return tokens, (me.get("mail") or me.get("userPrincipalName") or "").lower()
