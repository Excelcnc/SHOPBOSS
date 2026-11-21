"""File links in RFQ emails (Dropbox, Google Drive, OneDrive/SharePoint, WeTransfer, Box) and supplier portals.

Links are downloaded only when they are public (or shared with our account): we never sign in to a
portal or a customer's site for them. When a download needs a login, the link is kept and the file is
flagged "Needs manual download" with the reason and a button to open the link.

Only https URLs on the providers' own hosts are fetched, and every redirect is checked again, so an
email cannot make the server call internal addresses (SSRF).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx

URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}|\\^`]+", re.I)

# provider -> hosts it may live on or redirect to (suffix match)
PROVIDERS = {
    "dropbox": ("dropbox.com", "dropboxusercontent.com", "db.tt"),
    "google_drive": ("drive.google.com", "docs.google.com", "drive.usercontent.google.com", "googleusercontent.com"),
    "onedrive": ("1drv.ms", "onedrive.live.com", "sharepoint.com", "api.onedrive.com", "onedrive.com", "sharepoint-df.com"),
    "wetransfer": ("wetransfer.com", "we.tl", "wetransfer.net"),
    "box": ("box.com", "app.box.com", "boxcloud.com", "box.net"),
}
# supplier portals: never fetched, only parsed and linked
PORTALS = {
    "vendra": ("vendra.io",),
    "ariba": ("ariba.com",),
    "coupa": ("coupahost.com", "coupa.com"),
    "jaggaer": ("jaggaer.com",),
    "sap_fieldglass": ("fieldglass.net",),
    "exostar": ("exostar.com",),
}
MAX_LINKS = 20


class NeedsManual(Exception):
    """The file behind a link needs a sign-in or can't be fetched automatically. The message is shown to the user."""


@dataclass
class Found:
    kind: str        # file | portal
    provider: str
    url: str


def _host_in(host: str, suffixes) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)


def provider_of(url: str) -> tuple[str, str]:
    host = urlparse(url).hostname or ""
    for name, hosts in PORTALS.items():
        if _host_in(host, hosts):
            return "portal", name
    for name, hosts in PROVIDERS.items():
        if _host_in(host, hosts):
            return "file", name
    return "", ""


def find_links(text: str) -> list[Found]:
    out, seen = [], set()
    for m in URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?*>")
        kind, prov = provider_of(url)
        if not kind:
            continue
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(Found(kind, prov, url))
        if len(out) >= MAX_LINKS:
            break
    return out


def direct_url(provider: str, url: str) -> str:
    """Turn a share link into the provider's direct-download form where one exists."""
    u = urlparse(url)
    q = parse_qs(u.query)
    if provider == "dropbox":
        q.pop("dl", None)
        q["dl"] = ["1"]
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    if provider == "google_drive":
        m = re.search(r"/(?:file/d|open|uc)/([\w-]{10,})", u.path) or None
        fid = m.group(1) if m else (q.get("id") or [""])[0]
        if fid:
            return f"https://drive.google.com/uc?export=download&id={fid}"
        return url
    if provider == "onedrive":
        if _host_in(u.hostname or "", ("sharepoint.com",)):
            q["download"] = ["1"]
            return urlunparse(u._replace(query=urlencode(q, doseq=True)))
        return url
    return url


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _filename(resp: httpx.Response, url: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    return unquote(urlparse(url).path.rstrip("/").split("/")[-1]) or "download"


def fetch(provider: str, url: str, max_bytes: int, http: httpx.Client | None = None, resolve=_public_host) -> tuple[str, bytes]:
    """Download a public file link. Raises NeedsManual with a user-facing reason when it can't."""
    allowed = PROVIDERS.get(provider)
    if not allowed:
        raise NeedsManual("Not a supported file-sharing link")
    if provider == "box":
        raise NeedsManual("Box links need a Box sign-in: open the link and download the files")
    own = http is None
    http = http or httpx.Client(timeout=60, follow_redirects=False)
    try:
        cur = direct_url(provider, url)
        if provider == "wetransfer":
            cur = _wetransfer_direct(http, cur, resolve)
        for _ in range(8):
            p = urlparse(cur)
            if p.scheme != "https" or not _host_in(p.hostname or "", allowed) or not resolve(p.hostname or ""):
                raise NeedsManual("The link redirects to a site we don't download from automatically")
            with http.stream("GET", cur, headers={"User-Agent": "ShopBoss-RFQ-intake"}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    cur = str(httpx.URL(cur).join(r.headers.get("location", "")))
                    continue
                if r.status_code in (401, 403):
                    raise NeedsManual("Sign-in required: the link is not public")
                if r.status_code == 404:
                    raise NeedsManual("Link expired or the file was removed")
                if r.status_code >= 400:
                    raise NeedsManual(f"The file host answered {r.status_code}")
                ctype = r.headers.get("content-type", "").lower()
                if "text/html" in ctype:
                    raise NeedsManual("Sign-in or a confirmation page is needed: open the link and download the files")
                size = int(r.headers.get("content-length") or 0)
                if size > max_bytes:
                    raise NeedsManual(f"File is larger than {max_bytes // 2**20} MB")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > max_bytes:
                        raise NeedsManual(f"File is larger than {max_bytes // 2**20} MB")
                return _filename(r, cur), bytes(buf)
        raise NeedsManual("Too many redirects")
    except httpx.HTTPError as e:
        raise NeedsManual(f"Download failed ({type(e).__name__}); try again later") from None
    finally:
        if own:
            http.close()


def _wetransfer_direct(http: httpx.Client, url: str, resolve) -> str:
    """WeTransfer: resolve we.tl, then ask for the transfer's download link (works for public transfers only)."""
    for _ in range(5):
        p = urlparse(url)
        if not _host_in(p.hostname or "", PROVIDERS["wetransfer"]) or not resolve(p.hostname or ""):
            raise NeedsManual("The link redirects to a site we don't download from automatically")
        if _host_in(p.hostname or "", ("we.tl",)):
            r = http.get(url)
            if r.status_code not in (301, 302, 303, 307, 308):
                raise NeedsManual("WeTransfer link could not be opened")
            url = r.headers.get("location", "")
            continue
        m = re.search(r"/downloads/([0-9a-f]+)/(?:([0-9a-f]+)/)?([0-9a-f]+)", p.path)
        if not m:
            raise NeedsManual("WeTransfer link format not recognised: open it and download the files")
        tid, hash_ = m.group(1), m.group(3)
        r = http.post(f"https://wetransfer.com/api/v4/transfers/{tid}/download", json={"security_hash": hash_, "intent": "entire_transfer"})
        link = r.json().get("direct_link") if r.status_code == 200 else None
        if not link:
            raise NeedsManual("WeTransfer transfer expired or needs a password")
        return link
    raise NeedsManual("Too many redirects")


# ---- supplier portal notices
def parse_portal(provider: str, url: str, subject: str, body: str) -> dict:
    """Pull RFQ details out of a portal notice. Text is data only, never instructions."""
    text = f"{subject}\n{body}"
    rfq = re.search(r"(?i)\b(?:RFQ|RFP|quote request|request)\s*(?:#|no\.?|number|id)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-_/]{2,30})", text)
    due = re.search(r"(?i)\b(?:due|deadline|respond by|closes?|closing date|quote by)\s*(?:date)?\s*[:\-]?\s*([A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})", text)
    buyer = re.search(r"(?im)^\s*(?:buyer|from|customer|company)\s*:\s*(.{2,80})$", body or "")
    return {"portal": provider, "url": url, "rfq_no": rfq.group(1) if rfq else "", "due": due.group(1) if due else "",
            "buyer": buyer.group(1).strip() if buyer else ""}


def add_link_rows(db, rfq, parsed, email_id: str | None, mailbox_id: str | None):
    """Record every file link and portal link of an email as a file row on the RFQ (fetched later by a job)."""
    from ...models import Attachment
    have = {(a.source_ref or {}).get("url") for a in rfq.attachments}
    for f in find_links(f"{parsed.body}"):
        if f.url in have:
            continue
        if f.kind == "portal":
            info = parse_portal(f.provider, f.url, parsed.subject, parsed.body)
            name = f"{f.provider.title()} portal" + (f" · RFQ {info['rfq_no']}" if info["rfq_no"] else "")
            a = Attachment(shop_id=rfq.shop_id, filename=name, kind="link", ext="", source="portal", status="needs_manual",
                           status_reason="Supplier portal: sign in to the portal to see and download the RFQ files (we never sign in for you)",
                           email_id=email_id, mailbox_id=mailbox_id, sender_email=parsed.sender_email, source_ref={"url": f.url, "provider": f.provider, "portal": info})
            if info["rfq_no"] and not rfq.customer_rfq_no:
                rfq.customer_rfq_no = info["rfq_no"]
            if info["due"] and not rfq.due_date:
                rfq.due_date = info["due"]
        else:
            a = Attachment(shop_id=rfq.shop_id, filename=f"{f.provider.replace('_', ' ').title()} link", kind="link", ext="", source="link",
                           status="fetching", email_id=email_id, mailbox_id=mailbox_id, sender_email=parsed.sender_email,
                           source_ref={"url": f.url, "provider": f.provider}, export_controlled=bool(rfq.extracted.get("itar", {}).get("value")))
        rfq.attachments.append(a)
