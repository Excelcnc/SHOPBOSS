"""Linked-mailbox sync: new mail -> RFQ -> real attachment bytes -> the same storage and analysis as uploads.

For every message: the email is recorded, one "fetching" row is created per attachment, then each
attachment's bytes are downloaded and handed to pipeline.add_files (the upload path), which checks,
expands, de-duplicates and stores them. Analysis is queued exactly as after a manual upload.
Failures are kept on the file row with a reason, so the UI can show them and offer Retry.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...crypto import decrypt_json, encrypt_json
from ...models import Attachment, Email, Mailbox, Rfq
from ..intake import links as L
from ..intake.files import Incoming, ext_of, is_noise, safe_name
from .http import MailboxAuthError, MailboxTransient

log = logging.getLogger(__name__)
DEFAULT_KEYWORDS = "RFQ, RFP, request for quote, request for quotation, quotation, quote, drawing, drawings, STEP, print, prints, bid"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


# ------------------------------------------------------------------ clients
def client_for(db: Session, mb: Mailbox, http=None, sleep=None):
    from .gmail import GmailClient
    from .graph import GraphClient

    def save(tokens: dict):
        mb.token_enc = encrypt_json(tokens)
        db.flush()

    if mb.provider == "gmail":
        return GmailClient(decrypt_json(mb.token_enc), http=http, on_tokens=save, sleep=sleep)
    if mb.auth == "app":
        c = GraphClient.from_settings()
        if not c or c.mailbox.lower() != mb.address.lower():
            raise MailboxAuthError("The Microsoft 365 app connection is not configured for this mailbox (GRAPH_* settings)")
        if http is not None:
            c.http = http
        c._sleep = sleep
        return c
    return GraphClient.for_user(decrypt_json(mb.token_enc), http=http, on_tokens=save, sleep=sleep)


def app_mailbox(db: Session, shop_id: str, address: str) -> Mailbox:
    mb = db.scalar(select(Mailbox).where(Mailbox.shop_id == shop_id, Mailbox.provider == "graph", Mailbox.address == address.lower()))
    if not mb:
        mb = Mailbox(shop_id=shop_id, provider="graph", auth="app", address=address.lower(), keywords="")
        db.add(mb)
        db.flush()
    return mb


# ------------------------------------------------------------------ relevance
def _relevant(mb: Mailbox, parsed, metas: list[dict]) -> bool:
    if parsed.sender_email and parsed.sender_email == (mb.address or "").lower():
        return False  # our own sent mail
    files = [m for m in metas if not _noise_meta(m)]
    found = L.find_links(parsed.body)
    if any(f.kind == "portal" for f in found):
        return True
    if not files and not found:
        return False
    kws = [k.strip().lower() for k in (mb.keywords if mb.keywords is not None else DEFAULT_KEYWORDS).split(",") if k.strip()]
    if not kws:
        return True  # dedicated quoting mailbox: every email with files or links
    hay = " ".join([parsed.subject, parsed.body[:5000]] + [m["name"] for m in files]).lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", hay) for k in kws) or \
        any(ext_of(m["name"]) in ("step", "stp", "igs", "iges", "dxf", "dwg", "sldprt", "x_t") for m in files)


def _noise_meta(m: dict) -> bool:
    """Decide from metadata alone (before downloading) whether an attachment is a logo/signature."""
    fake = Incoming(m["name"], b"\0" * max(int(m.get("size") or 0), 0) if int(m.get("size") or 0) < 300 * 1024 else b"\0" * (300 * 1024),
                    inline=bool(m.get("inline")))
    return bool(is_noise(fake))


# ------------------------------------------------------------------ ingest one message
def ingest_remote(db: Session, mb: Mailbox, client, remote_id: str, force: bool = False) -> Rfq | None:
    from ...jobs import enqueue, enqueue_analysis
    from ..pipeline import classify, create_rfq_from_email
    parsed, metas = client.message(remote_id)
    if db.scalar(select(Email.id).where(Email.shop_id == mb.shop_id, Email.message_id == parsed.message_id)):
        return None
    if not force and not _relevant(mb, parsed, metas):
        return None
    holders = []
    for m in metas:
        if _noise_meta(m):
            continue
        name = safe_name(m["name"])
        kind, ext = classify(name)
        ref = {"provider": mb.provider, "mailbox_id": mb.id, "message_id": remote_id, "attachment": m}
        if m.get("kind") == "reference":
            holders.append(Attachment(filename=name, kind="link", ext="", status="fetching", source="link", source_ref={**ref, "reference": True}))
        else:
            holders.append(Attachment(filename=name, kind=kind, ext=ext, size=int(m.get("size") or 0), mime=m.get("mime") or "",
                                      status="fetching", source_ref=ref))
    rfq = create_rfq_from_email(db, mb.shop_id, parsed, mb.provider, mailbox_id=mb.id, files=holders)
    db.commit()
    if rfq is None:
        return None
    for a in [x for x in rfq.attachments if x.status == "fetching" and x.kind != "link"]:
        fetch_attachment(db, a, client)
    db.commit()
    if any(a.status == "fetching" and a.kind == "link" for a in rfq.attachments):
        enqueue("links", rfq.id)
    enqueue_analysis(rfq.id)
    return rfq


def fetch_attachment(db: Session, a: Attachment, client) -> bool:
    """Download one attachment's bytes and store them through the upload path. Returns True when stored."""
    from ..pipeline import add_files
    ref = a.source_ref or {}
    meta = ref.get("attachment") or {}
    a.attempts = (a.attempts or 0) + 1
    try:
        if not meta.get("id") and not meta.get("attachment_id") and not meta.get("data"):
            meta = _find_by_name(client, ref["message_id"], a.filename)
            a.source_ref = {**ref, "attachment": meta}
        data = client.attachment(ref["message_id"], meta)
    except MailboxAuthError as e:
        a.status, a.status_reason = "failed", f"{e} — reconnect the mailbox in Settings, then Retry"
        raise
    except MailboxTransient as e:
        a.status, a.status_reason = "fetching", f"Mail service busy ({e}); retrying automatically"
        a.next_retry_at = _now() + timedelta(seconds=min(3600, 60 * 2 ** min(a.attempts, 6)))
        return False
    except FileNotFoundError:
        a.status, a.status_reason = "failed", "Expired or removed: the email or attachment is no longer in the mailbox"
        return False
    except ValueError as e:
        a.status, a.status_reason = "failed", f"Corrupted attachment data ({e})"
        return False
    rfq = db.get(Rfq, a.rfq_id) if a.rfq_id else a.rfq
    add_files(db, rfq, [Incoming(a.filename, data, mime=meta.get("mime", ""), inline=bool(meta.get("inline")), origin="email")], placeholder=a,
              source=a.source, email_id=a.email_id, mailbox_id=a.mailbox_id, sender_email=a.sender_email)
    a.next_retry_at = None
    return a.stored


def _find_by_name(client, message_id: str, filename: str) -> dict:
    _, metas = client.message(message_id)
    for m in metas:
        if m["name"].lower() == filename.lower():
            return m
    raise FileNotFoundError(filename)


# ------------------------------------------------------------------ links
def fetch_links(db: Session, rfq: Rfq, http=None, resolve=None, client=None) -> int:
    from ..pipeline import add_files
    n = 0
    for a in [x for x in rfq.attachments if x.kind == "link" and x.status == "fetching"]:
        ref = a.source_ref or {}
        try:
            url = ref.get("url")
            if ref.get("reference") and not url:
                mb = db.get(Mailbox, ref.get("mailbox_id"))
                c = client or client_for(db, mb)
                url = c.reference_url(ref["message_id"], ref["attachment"]["id"])
                kind, prov = L.provider_of(url)
                a.source_ref = {**ref, "url": url, "provider": prov}
                ref = a.source_ref
                if kind != "file":
                    raise L.NeedsManual("Cloud file shared from the sender's OneDrive/SharePoint: open the link and download it")
            kw = {"resolve": resolve} if resolve else {}
            name, data = L.fetch(ref.get("provider", ""), url, get_settings().max_attachment_mb * 2**20, http=http, **kw)
        except L.NeedsManual as e:
            a.status, a.status_reason = "needs_manual", f"Needs manual download: {e}"
            continue
        except (MailboxAuthError, MailboxTransient, FileNotFoundError) as e:
            a.status, a.status_reason = "needs_manual", f"Needs manual download: {e}"
            continue
        a.filename = safe_name(name)
        add_files(db, rfq, [Incoming(name, data, origin=f"link:{ref.get('provider', '')}")], placeholder=a, source="link",
                  email_id=a.email_id, mailbox_id=a.mailbox_id, sender_email=a.sender_email)
        n += 1
    db.commit()
    return n


# ------------------------------------------------------------------ mailbox sync
def sync_mailbox(db: Session, mb: Mailbox, client=None, backfill: bool = False) -> dict:
    """Process new mail since the mailbox was linked (plus the optional back-fill). Safe to run repeatedly."""
    out = {"mailbox": mb.address, "new_rfqs": 0, "messages": 0, "error": ""}
    try:
        c = client or client_for(db, mb)
        cursor = mb.state.get("cursor")
        since = datetime.fromisoformat(cursor) if cursor and not backfill else _aware(mb.linked_at) - timedelta(days=min(mb.backfill_days or 0, get_settings().max_backfill_days))
        if mb.provider == "gmail":
            ids = c.list_ids(f"after:{int(since.timestamp())} -in:sent -in:chats -in:drafts")[::-1]  # oldest first
            items = [(i, None) for i in ids]
        else:
            items = [(m["id"], m.get("receivedDateTime")) for m in c.list_since(since)]
        newest = since
        for rid, received in items:
            out["messages"] += 1
            try:
                if ingest_remote(db, mb, c, rid):
                    out["new_rfqs"] += 1
            except FileNotFoundError:
                continue
            if received:
                newest = max(newest, datetime.fromisoformat(received.replace("Z", "+00:00")))
        if mb.provider == "gmail":
            newest = _now() - timedelta(minutes=10)  # Gmail "after:" has second resolution; duplicates are skipped by message id
        mb.state = {**(mb.state or {}), "cursor": (newest - timedelta(minutes=1)).isoformat()}
        mb.status, mb.last_error, mb.failures, mb.next_try_at, mb.last_sync_at = "connected", "", 0, None, _now()
    except MailboxAuthError as e:
        db.rollback()
        mb.status, mb.last_error = "reconnect", str(e)
        out["error"] = str(e)
    except (MailboxTransient, Exception) as e:  # noqa: BLE001 - keep the scheduler alive; never log mail content
        db.rollback()
        mb.failures = (mb.failures or 0) + 1
        mb.status, mb.last_error = "error", f"{type(e).__name__}: {str(e)[:300]}"
        mb.next_try_at = _now() + timedelta(seconds=min(3600, 60 * 2 ** min(mb.failures, 6)))
        out["error"] = mb.last_error
        log.warning("mailbox sync failed for %s: %s", mb.id, type(e).__name__)
    db.commit()
    return out


def retry_attachment(db: Session, a: Attachment, client=None, http=None, resolve=None) -> str:
    """The Retry button: fetch again (email or link), or re-run analysis when the file is already stored."""
    from ...jobs import enqueue_analysis
    if a.stored:
        enqueue_analysis(a.rfq_id)
        return "analysis queued"
    ref = a.source_ref or {}
    if a.kind == "link" or ref.get("url"):
        a.status = "fetching"
        db.commit()
        fetch_links(db, db.get(Rfq, a.rfq_id), http=http, resolve=resolve, client=client)
    elif ref.get("message_id"):
        mb = db.get(Mailbox, ref.get("mailbox_id")) if ref.get("mailbox_id") else None
        if mb is None:
            a.status, a.status_reason = "failed", "The mailbox this came from is no longer linked: link it again, then Retry"
            db.commit()
            return a.status
        a.status, a.status_reason = "fetching", ""
        try:
            fetch_attachment(db, a, client or client_for(db, mb))
        except MailboxAuthError as e:
            mb.status, mb.last_error = "reconnect", str(e)
    else:
        a.status, a.status_reason = "failed", "No way to fetch this file again: upload it on the RFQ"
    db.commit()
    if a.stored:
        enqueue_analysis(a.rfq_id)
    return a.status


def retry_due(db: Session, shop_id: str | None = None) -> int:
    """Re-try rows left in 'fetching' (rate limits, stuck imports) when their time has come."""
    q = select(Attachment).where(Attachment.status == "fetching")
    if shop_id:
        q = q.where(Attachment.shop_id == shop_id)
    n = 0
    for a in db.scalars(q.limit(200)).all():
        due = _aware(a.next_retry_at)
        if due is None or due <= _now():
            retry_attachment(db, a)
            n += 1
    return n
