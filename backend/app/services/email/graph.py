"""Microsoft 365 mailbox intake via Microsoft Graph (application permissions).

One Graph app registration per deployment (GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET)
can read any mailbox in the tenant that its Exchange application access policy allows. Each connected
mailbox (models.Mailbox, kind="graph") keeps its own delta position and webhook subscription.

Flow per mailbox:
  1. A change-notification subscription on the watched folder calls POST /api/intake/graph/notify
     within seconds of a new message (subscriptions last < 3 days; the poller renews them).
  2. A delta query every few minutes catches anything a notification missed.
  3. New messages that look like RFQs are fetched with attachments and become RFQs (duplicates are
     ignored by internetMessageId), then analysis is queued.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from ...config import get_settings
from .parse import ParsedEmail, _html_to_text

log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"


def graph_configured() -> bool:
    s = get_settings()
    return bool(s.graph_tenant_id and s.graph_client_id and s.graph_client_secret)


class GraphClient:
    def __init__(self, tenant: str, client_id: str, secret: str, mailbox: str, folder: str = "inbox", http: httpx.Client | None = None):
        self.tenant, self.client_id, self.secret, self.mailbox = tenant, client_id, secret, mailbox
        self.folder = (folder or "inbox").strip()
        self.http = http or httpx.Client(timeout=60)
        self._token = None
        self._exp = datetime.min.replace(tzinfo=timezone.utc)
        self._folder_id = None

    @classmethod
    def for_mailbox(cls, address: str, folder: str = "inbox", http: httpx.Client | None = None):
        s = get_settings()
        if not graph_configured():
            raise RuntimeError("The Microsoft 365 app is not configured on the server (GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET).")
        return cls(s.graph_tenant_id, s.graph_client_id, s.graph_client_secret, address, folder, http)

    def token(self) -> str:
        if self._token and datetime.now(timezone.utc) < self._exp:
            return self._token
        import msal
        app = msal.ConfidentialClientApplication(self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}", client_credential=self.secret)
        r = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in r:
            desc = r.get("error_description") or str(r)
            known = {"AADSTS7000215": "the client secret is wrong. Paste the secret's Value (not its ID) into GRAPH_CLIENT_SECRET on the server.",
                     "AADSTS7000222": "the client secret has expired. Create a new one under Certificates & secrets.",
                     "AADSTS700016": "the mailbox app's client ID was not found in this tenant. Check GRAPH_CLIENT_ID.",
                     "AADSTS90002": "the tenant ID was not found. Check GRAPH_TENANT_ID."}
            hint = next((v for k, v in known.items() if k in desc), desc.split(" Trace ID")[0][:300])
            raise RuntimeError(f"Microsoft sign-in for the mailbox app failed: {hint}")
        self._token = r["access_token"]
        self._exp = datetime.now(timezone.utc) + timedelta(seconds=int(r.get("expires_in", 3600)) - 120)
        return self._token

    def _req(self, method, url, **kw):
        h = kw.pop("headers", {})
        h["Authorization"] = "Bearer " + self.token()
        r = self.http.request(method, url if url.startswith("http") else GRAPH + url, headers=h, **kw)
        if r.status_code == 429:
            raise RuntimeError("Microsoft Graph is throttling requests; will retry on the next poll.")
        if r.status_code in (401, 403):
            raise RuntimeError(f"Access to {self.mailbox} denied (HTTP {r.status_code}). Add it to the mailbox app's application access policy group.")
        if r.status_code == 404:
            raise RuntimeError(f"{self.mailbox} or its folder was not found (HTTP 404). Check the address.")
        r.raise_for_status()
        return r

    def folder_id(self) -> str:
        """Well-known 'inbox', or a folder found by name at the top level or under Inbox."""
        if self.folder.lower() == "inbox":
            return "inbox"
        if self._folder_id:
            return self._folder_id
        q = self.folder.replace("'", "''")
        for base in (f"/users/{self.mailbox}/mailFolders", f"/users/{self.mailbox}/mailFolders/inbox/childFolders"):
            hits = self._req("GET", f"{base}?$filter=displayName eq '{q}'&$select=id").json().get("value", [])
            if hits:
                self._folder_id = hits[0]["id"]
                return self._folder_id
        raise RuntimeError(f"Folder '{self.folder}' not found in {self.mailbox}. Create it (top level or under Inbox) or use Inbox.")

    def folder_counts(self) -> dict:
        return self._req("GET", f"/users/{self.mailbox}/mailFolders/{self.folder_id()}?$select=displayName,totalItemCount,unreadItemCount").json()

    # ---- subscriptions
    def subscribe(self, notify_url: str, client_state: str) -> dict:
        exp = (datetime.now(timezone.utc) + timedelta(minutes=4200)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        body = {"changeType": "created", "notificationUrl": notify_url, "resource": f"users/{self.mailbox}/mailFolders('{self.folder_id()}')/messages",
                "expirationDateTime": exp, "clientState": client_state}
        return self._req("POST", "/subscriptions", json=body).json()

    def renew(self, sub_id: str) -> dict:
        exp = (datetime.now(timezone.utc) + timedelta(minutes=4200)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        return self._req("PATCH", f"/subscriptions/{sub_id}", json={"expirationDateTime": exp}).json()

    def unsubscribe(self, sub_id: str):
        try:
            self._req("DELETE", f"/subscriptions/{sub_id}")
        except Exception as e:  # already expired is fine
            log.info("unsubscribe %s: %s", sub_id, e)

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

    def delta(self, delta_link: str | None, since: datetime | None = None) -> tuple[list[str], str]:
        url = delta_link
        if not url:
            url = f"/users/{self.mailbox}/mailFolders('{self.folder_id()}')/messages/delta?$select=id"
            if since:
                url += f"&$filter=receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        ids = []
        while True:
            r = self._req("GET", url).json()
            ids += [v["id"] for v in r.get("value", []) if "@removed" not in v]
            if "@odata.nextLink" in r:
                url = r["@odata.nextLink"]
            else:
                return ids, r.get("@odata.deltaLink", url)


def new_client_state() -> str:
    return secrets.token_urlsafe(24)
