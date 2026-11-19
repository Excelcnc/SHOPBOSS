"""Connect with Microsoft: a shop admin (or the mailbox owner) signs in with Microsoft and allows the app
to read one mailbox, either their own or a shared mailbox they already have access to (e.g. sales@).
No Exchange PowerShell or access-policy group is needed, and it works for any company's Microsoft 365
and for Outlook.com, as far as the configured Microsoft app allows.

The sign-in is bound to the browser that started it (a short-lived cookie must match the signed
state), so nobody can trick an admin into connecting their mailbox to someone else's shop.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...crypto import encrypt
from ...models import Mailbox, User
from ..accounts import _secret
from .graph import SCOPES, DelegatedGraphClient, token_request

COOKIE = "cq_ms_connect"
HTTP_FACTORY = lambda: httpx.Client(timeout=60)  # replaced in tests
ISS = "cncquote-msconnect"


def configured() -> bool:
    return bool(get_settings().ms_connect)


def start(user: User, address: str, folder: str, label: str, filter_rfqs: bool, backfill_days: int, reconnect_id: str = "") -> tuple[str, str]:
    """Returns (Microsoft sign-in URL, nonce for the browser cookie)."""
    cfg = get_settings().ms_connect
    if not cfg:
        raise RuntimeError("Connect with Microsoft is not configured on the server.")
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode({"iss": ISS, "shop": user.shop_id, "user": user.id, "nonce": nonce, "address": (address or "").strip().lower(),
                        "folder": (folder or "inbox").strip() or "inbox", "label": (label or "")[:120], "filter": bool(filter_rfqs),
                        "backfill": max(0, min(90, int(backfill_days or 0))), "reconnect": reconnect_id,
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, _secret(), algorithm="HS256")
    q = {"client_id": cfg["client_id"], "response_type": "code", "redirect_uri": cfg["redirect_uri"], "response_mode": "query",
         "scope": SCOPES, "state": state, "prompt": "select_account"}
    if address:
        q["login_hint"] = address
    return f"https://login.microsoftonline.com/{cfg['tenant']}/oauth2/v2.0/authorize?{urlencode(q)}", nonce


def finish(db: Session, code: str, state: str, cookie_nonce: str | None, http: httpx.Client | None = None) -> Mailbox:
    """Handles Microsoft's redirect: checks the state, exchanges the code, tests the mailbox, saves it."""
    try:
        st = jwt.decode(state, _secret(), algorithms=["HS256"], issuer=ISS)
    except jwt.PyJWTError:
        raise RuntimeError("This sign-in link has expired. Start again from Shop settings › Email accounts.")
    if not cookie_nonce or not secrets.compare_digest(cookie_nonce, st["nonce"]):
        raise RuntimeError("Please start connecting the mailbox from Shop settings in this browser.")
    user = db.get(User, st["user"])
    if not user or user.shop_id != st["shop"] or user.role != "admin" or not user.active:
        raise RuntimeError("Only shop admins can connect mailboxes.")
    http = http or HTTP_FACTORY()
    cfg = get_settings().ms_connect
    tok = token_request(http, cfg, {"grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"]})
    me = http.get("https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName", headers={"Authorization": "Bearer " + tok["access_token"]}).json()
    who = (me.get("mail") or me.get("userPrincipalName") or "").lower()
    address = st["address"] or who
    if not address:
        raise RuntimeError("Microsoft didn't return an email address for this account.")
    rt = tok.get("refresh_token")
    if not rt:
        raise RuntimeError("Microsoft didn't allow offline access. An admin may need to approve the app.")
    client = DelegatedGraphClient(rt, address, st["folder"], http=http, cfg=cfg)
    client._token, client._exp = tok["access_token"], datetime.now(timezone.utc) + timedelta(minutes=30)
    try:
        client.folder_counts()
    except RuntimeError as e:
        msg = str(e)
        if address != who and ("denied" in msg or "not found" in msg):
            msg = (f"{who} can't open {address}. Ask your Microsoft 365 admin to give {who} access to that mailbox "
                   "(admin center › Teams & groups › Shared mailboxes › Read and manage), or sign in as its owner.")
        raise RuntimeError(msg)

    mb = db.get(Mailbox, st["reconnect"]) if st.get("reconnect") else None
    if mb and mb.shop_id != user.shop_id:
        mb = None
    if not mb:
        mb = db.scalar(select(Mailbox).where(Mailbox.shop_id == user.shop_id, Mailbox.kind == "msoauth", Mailbox.address == address, Mailbox.folder == st["folder"]))
    if not mb:
        mb = Mailbox(shop_id=user.shop_id, kind="msoauth", address=address, folder=st["folder"], label=st["label"],
                     filter_rfqs=st["filter"], backfill_days=st["backfill"], active=True, state={})
        db.add(mb)
    mb.oauth_token_enc = encrypt(client.refresh_token)
    mb.connected_as = who
    mb.last_error = None
    db.commit()
    from ..pipeline import audit
    audit(db, user.shop_id, "mailbox", address, "connect", {"kind": "msoauth", "as": who, "folder": st["folder"]}, user.id)
    db.commit()
    return mb
