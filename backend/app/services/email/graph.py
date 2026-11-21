"""Microsoft 365 mailbox intake via Microsoft Graph (application permissions).

Setup (docs/M365_SETUP.md): register an app in Entra ID, grant application permission Mail.Read
(admin consent), and restrict it to the quoting mailbox with an Exchange Application Access Policy.

Flow:
  1. A change-notification subscription on the mailbox Inbox calls POST /api/intake/graph/notify
     within seconds of a new message (subscriptions last < 3 days; the poller renews them).
  2. A delta query every few minutes catches anything a notification missed.
  3. Each new message is fetched with its attachments and becomes an RFQ (duplicates are ignored by
     internetMessageId), then analysis is queued.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import IntegrationState
from .http import MailboxAuthError, request
from .parse import ParsedEmail, _html_to_text

log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"


DELEGATED_SCOPES = ["offline_access", "User.Read", "Mail.Read"]   # read-only; never Mail.ReadWrite or Mail.Send


class GraphClient:
    """Application permission (one configured mailbox, env settings) or delegated OAuth (a user's own mailbox).

    Only GET requests are sent to mail resources: the app never moves, deletes, flags or sends mail.
    """

    def __init__(self, tenant: str, client_id: str, secret: str, mailbox: str, http: httpx.Client | None = None,
                 delegated: dict | None = None, on_tokens=None, sleep=None):
        self.tenant, self.client_id, self.secret, self.mailbox = tenant, client_id, secret, mailbox
        self.http = http or httpx.Client(timeout=120)
        self._token = None
        self._exp = datetime.min.replace(tzinfo=timezone.utc)
        self.delegated = dict(delegated) if delegated is not None else None
        self.on_tokens = on_tokens
        self._sleep = sleep
        self.base = "/me" if delegated is not None else f"/users/{mailbox}"

    @classmethod
    def for_user(cls, tokens: dict, http=None, on_tokens=None, sleep=None):
        s = get_settings()
        return cls(s.ms_oauth_tenant, s.ms_oauth_client_id, s.ms_oauth_client_secret, "", http=http, delegated=tokens, on_tokens=on_tokens, sleep=sleep)

    @classmethod
    def from_settings(cls):
        s = get_settings()
        if not (s.graph_tenant_id and s.graph_client_id and s.graph_client_secret and s.graph_mailbox):
            return None
        return cls(s.graph_tenant_id, s.graph_client_id, s.graph_client_secret, s.graph_mailbox)

    def token(self) -> str:
        if self._token and datetime.now(timezone.utc) < self._exp:
            return self._token
        if self.delegated is not None:
            return self._refresh_delegated()
        import msal
        app = msal.ConfidentialClientApplication(self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}", client_credential=self.secret)
        r = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in r:
            raise RuntimeError(f"Graph token error: {r.get('error_description') or r}")
        self._token = r["access_token"]
        self._exp = datetime.now(timezone.utc) + timedelta(seconds=int(r.get("expires_in", 3600)) - 120)
        return self._token

    def _refresh_delegated(self) -> str:
        rt = (self.delegated or {}).get("refresh_token")
        if not rt:
            raise MailboxAuthError("Reconnect needed: no refresh token")
        r = request(self.http, "POST", f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token",
                    data={"client_id": self.client_id, "client_secret": self.secret, "grant_type": "refresh_token",
                          "refresh_token": rt, "scope": " ".join(DELEGATED_SCOPES)}, **self._kw())
        if r.status_code in (400, 401):
            raise MailboxAuthError("Reconnect needed: Microsoft 365 access expired or was revoked")
        r.raise_for_status()
        j = r.json()
        self.delegated["refresh_token"] = j.get("refresh_token", rt)
        self._token = j["access_token"]
        self._exp = datetime.now(timezone.utc) + timedelta(seconds=int(j.get("expires_in", 3600)) - 120)
        if self.on_tokens:
            self.on_tokens(self.delegated)
        return self._token

    def _kw(self):
        return {"sleep": self._sleep} if self._sleep else {}

    def _req(self, method, url, **kw):
        h = kw.pop("headers", {})
        for attempt in range(2):
            h["Authorization"] = "Bearer " + self.token()
            r = request(self.http, method, url if url.startswith("http") else GRAPH + url, headers=h, **self._kw(), **kw)
            if r.status_code == 401 and attempt == 0:
                self._token = None
                continue
            if r.status_code == 401:
                raise MailboxAuthError("Reconnect needed: Microsoft 365 access expired")
            if r.status_code == 403:
                raise MailboxAuthError("Access denied by Microsoft 365 (permission or mailbox access policy)")
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r
        raise MailboxAuthError("Reconnect needed")

    # ---- reading for linked mailboxes (all GET)
    def me(self) -> dict:
        return self._req("GET", f"{self.base}?$select=mail,userPrincipalName").json()

    def list_since(self, since: datetime, limit: int = 500) -> list[dict]:
        iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (f"{self.base}/messages?$filter=receivedDateTime ge {iso}&$orderby=receivedDateTime asc"
               "&$select=id,receivedDateTime,hasAttachments,subject&$top=50")
        out = []
        while url and len(out) < limit:
            j = self._req("GET", url).json()
            out += j.get("value", [])
            url = j.get("@odata.nextLink")
        return out[:limit]

    def message(self, msg_id: str) -> tuple[ParsedEmail, list[dict]]:
        """The email (without file bytes) and its attachment list (fetched one by one afterwards)."""
        sel = "subject,body,from,receivedDateTime,internetMessageId,hasAttachments,conversationId"
        m = self._req("GET", f"{self.base}/messages/{msg_id}?$select={sel}", headers={"Prefer": 'outlook.body-content-type="text"'}).json()
        atts = []
        if m.get("hasAttachments"):
            url = f"{self.base}/messages/{msg_id}/attachments?$select=id,name,size,isInline,contentType"
            while url:
                j = self._req("GET", url).json()
                for a in j.get("value", []):
                    t = a.get("@odata.type", "")
                    kind = "file" if t.endswith("fileAttachment") else "item" if t.endswith("itemAttachment") else "reference" if t.endswith("referenceAttachment") else ""
                    if kind:
                        name = a.get("name") or "attachment"
                        if kind == "item" and not name.lower().endswith((".eml", ".msg")):
                            name += ".eml"
                        atts.append({"id": a["id"], "name": name, "size": a.get("size", 0), "inline": bool(a.get("isInline")),
                                     "mime": a.get("contentType") or "", "kind": kind})
                url = j.get("@odata.nextLink")
        body = m.get("body", {})
        text = body.get("content", "") if body.get("contentType") == "text" else _html_to_text(body.get("content", ""))
        frm = (m.get("from") or {}).get("emailAddress", {})
        when = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")) if m.get("receivedDateTime") else datetime.now(timezone.utc)
        return ParsedEmail(m.get("internetMessageId") or msg_id, frm.get("name", ""), (frm.get("address") or "").lower(), m.get("subject", ""),
                           text, when, [], thread_id="graph:" + (m.get("conversationId") or ""), remote_id=msg_id), atts

    def attachment(self, msg_id: str, att: dict) -> bytes:
        """Raw bytes. fileAttachment: the file. itemAttachment (a forwarded email): its MIME (.eml).
        $value streams the content, so large attachments (up to Exchange's 150 MB) work without base64 in JSON."""
        if att.get("kind") == "reference":
            raise FileNotFoundError("cloud attachment: handled as a link")
        return self._req("GET", f"{self.base}/messages/{msg_id}/attachments/{att['id']}/$value").content

    def reference_url(self, msg_id: str, att_id: str) -> str:
        j = self._req("GET", f"{self.base}/messages/{msg_id}/attachments/{att_id}").json()
        return j.get("sourceUrl", "")

    # ---- subscriptions
    def subscribe(self, notify_url: str, client_state: str) -> dict:
        exp = (datetime.now(timezone.utc) + timedelta(minutes=4200)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        body = {"changeType": "created", "notificationUrl": notify_url, "resource": f"users/{self.mailbox}/mailFolders('inbox')/messages",
                "expirationDateTime": exp, "clientState": client_state}
        return self._req("POST", "/subscriptions", json=body).json()

    def renew(self, sub_id: str) -> dict:
        exp = (datetime.now(timezone.utc) + timedelta(minutes=4200)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        return self._req("PATCH", f"/subscriptions/{sub_id}", json={"expirationDateTime": exp}).json()

    # ---- messages
    def get_message(self, msg_id: str) -> ParsedEmail:
        sel = "subject,body,from,receivedDateTime,internetMessageId,hasAttachments"
        m = self._req("GET", f"/users/{self.mailbox}/messages/{msg_id}?$select={sel}", headers={"Prefer": 'outlook.body-content-type="text"'}).json()
        atts = []
        if m.get("hasAttachments"):
            lst = self._req("GET", f"/users/{self.mailbox}/messages/{msg_id}/attachments?$select=id,name,size,isInline").json().get("value", [])
            for a in lst:
                if a.get("@odata.type") != "#microsoft.graph.fileAttachment" or a.get("size", 0) > get_settings().max_attachment_mb * 2**20:
                    continue
                raw = self._req("GET", f"/users/{self.mailbox}/messages/{msg_id}/attachments/{a['id']}/$value").content
                atts.append((a["name"], raw))
        body = m.get("body", {})
        text = body.get("content", "") if body.get("contentType") == "text" else _html_to_text(body.get("content", ""))
        frm = (m.get("from") or {}).get("emailAddress", {})
        when = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")) if m.get("receivedDateTime") else datetime.now(timezone.utc)
        return ParsedEmail(m.get("internetMessageId") or msg_id, frm.get("name", ""), frm.get("address", ""), m.get("subject", ""), text, when, atts)

    def delta(self, delta_link: str | None) -> tuple[list[str], str]:
        url = delta_link or f"/users/{self.mailbox}/mailFolders('inbox')/messages/delta?$select=id"
        ids = []
        while True:
            r = self._req("GET", url).json()
            ids += [v["id"] for v in r.get("value", []) if "@removed" not in v]
            if "@odata.nextLink" in r:
                url = r["@odata.nextLink"]
            else:
                return ids, r.get("@odata.deltaLink", url)


def _state(db: Session, shop_id: str, kind: str) -> IntegrationState:
    st = db.scalar(select(IntegrationState).where(IntegrationState.shop_id == shop_id, IntegrationState.kind == kind))
    if not st:
        st = IntegrationState(shop_id=shop_id, kind=kind, state={})
        db.add(st)
        db.flush()
    return st


def ingest_message(db: Session, shop_id: str, client: GraphClient, msg_id: str):
    """Webhook / delta path for the configured (application-permission) mailbox: same intake as linked mailboxes."""
    from .sync import app_mailbox, ingest_remote
    mb = app_mailbox(db, shop_id, client.mailbox)
    return ingest_remote(db, mb, client, msg_id)


def sync(db: Session, shop_id: str, client: GraphClient, first_run_backfill: bool = False) -> int:
    """Delta sync. The first run only records the delta position (no backfill of old mail) unless asked."""
    st = _state(db, shop_id, "graph")
    link = st.state.get("delta_link")
    ids, new_link = client.delta(link)
    n = 0
    if link or first_run_backfill:
        for mid in ids:
            if ingest_message(db, shop_id, client, mid):
                n += 1
    st.state = {**st.state, "delta_link": new_link, "last_sync": datetime.now(timezone.utc).isoformat()}
    db.commit()
    return n


def ensure_subscription(db: Session, shop_id: str, client: GraphClient):
    s = get_settings()
    if not s.graph_webhook_url:
        return None
    st = _state(db, shop_id, "graph")
    sub = st.state.get("subscription")
    try:
        if sub:
            exp = datetime.fromisoformat(sub["expirationDateTime"].replace("Z", "+00:00"))
            if exp - datetime.now(timezone.utc) < timedelta(hours=12):
                sub = client.renew(sub["id"])
        else:
            sub = client.subscribe(s.graph_webhook_url, s.graph_client_state)
    except httpx.HTTPStatusError as e:
        log.warning("subscription renew/create failed (%s); recreating", e)
        sub = client.subscribe(s.graph_webhook_url, s.graph_client_state)
    st.state = {**st.state, "subscription": {"id": sub["id"], "expirationDateTime": sub["expirationDateTime"]}}
    db.commit()
    return sub
