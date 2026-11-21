"""API for linked mailboxes, file status, Retry, and file viewing through short-lived signed links."""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .auth import current_user, require_admin
from .config import get_settings
from .crypto import CryptoNotConfigured, encrypt_json, sign, verify
from .db import get_db
from .jobs import enqueue
from .models import Attachment, AuditLog, Mailbox, Rfq, User
from .services.email import oauth
from .services.email.http import MailboxAuthError
from .services.intake.files import PREVIEWABLE

router = APIRouter(prefix="/api")


def _mailbox_dict(m: Mailbox) -> dict:  # never includes tokens
    return {"id": m.id, "provider": m.provider, "auth": m.auth, "address": m.address, "status": m.status, "last_error": m.last_error,
            "linked_at": m.linked_at.isoformat() if m.linked_at else None, "last_sync_at": m.last_sync_at.isoformat() if m.last_sync_at else None,
            "backfill_days": m.backfill_days, "keywords": m.keywords}


def attachment_dict(a: Attachment) -> dict:
    ref = a.source_ref or {}
    return {"id": a.id, "filename": a.filename, "kind": a.kind, "ext": a.ext, "size": a.size, "mime": a.mime,
            "status": a.status, "status_reason": a.status_reason, "source": a.source, "origin": a.origin, "sender_email": a.sender_email,
            "export_controlled": a.export_controlled, "supersedes_id": a.supersedes_id, "stored": a.stored,
            "previewable": a.stored and a.ext in PREVIEWABLE, "url": ref.get("url") if a.kind == "link" else None,
            "portal": ref.get("portal"), "created_at": a.created_at.isoformat() if a.created_at else None}


# ------------------------------------------------------------------ export-controlled access
def can_open(user: User, a: Attachment) -> bool:
    return not a.export_controlled or bool(user.export_ok)


def guard(db: Session, user: User, a: Attachment, action: str):
    """Company isolation + export-control restriction. Every view of a restricted file is audited (allowed or denied)."""
    if a is None or a.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    if a.export_controlled:
        ok = can_open(user, a)
        db.add(AuditLog(shop_id=a.shop_id, user_id=user.id, entity="attachment", entity_id=a.id,
                        action=("view_" if ok else "denied_") + action, detail={"file": a.filename, "rfq_id": a.rfq_id, "export_controlled": True}))
        db.commit()
        if not ok:
            raise HTTPException(403, "Export-controlled file (ITAR/CUI/EAR): ask a shop admin for access")


# ------------------------------------------------------------------ mailboxes
class LinkBody(BaseModel):
    backfill_days: int = 0
    keywords: Optional[str] = None


@router.get("/mailboxes")
def list_mailboxes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Mailbox).where(Mailbox.shop_id == user.shop_id).order_by(Mailbox.created_at)).all()
    return {"mailboxes": [_mailbox_dict(m) for m in rows], "providers": {p: oauth.configured(p) for p in oauth.PROVIDERS}}


@router.post("/mailboxes/oauth/{provider}/start")
def link_start(provider: str, body: LinkBody, user: User = Depends(require_admin)):
    try:
        days = max(0, min(int(body.backfill_days), get_settings().max_backfill_days))
        return {"url": oauth.start(provider, user.shop_id, user.id, days, body.keywords)}
    except (MailboxAuthError, ValueError, CryptoNotConfigured) as e:
        raise HTTPException(400, str(e))


@router.get("/mailboxes/oauth/{provider}/callback")
def link_callback(provider: str, request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    back = get_settings().app_url.rstrip("/") + "/settings?tab=mailboxes"
    if error:
        return RedirectResponse(back + "&mailbox_error=" + quote("Sign-in was cancelled or refused"))
    try:
        st = oauth.read_state(state)
        if st["p"] != provider:
            raise MailboxAuthError("Sign-in link mismatch")
        user = db.get(User, st["u"])
        if not user or user.shop_id != st["s"] or user.role != "admin":
            raise MailboxAuthError("Only a shop admin can link a mailbox")
        tokens, address = oauth.exchange(provider, code)
        if not address:
            raise MailboxAuthError("Could not read the mailbox address")
        mb = db.scalar(select(Mailbox).where(Mailbox.shop_id == user.shop_id, Mailbox.provider == provider, Mailbox.address == address))
        if mb is None:
            mb = Mailbox(shop_id=user.shop_id, provider=provider, auth="oauth", address=address, created_by=user.id, backfill_days=st.get("b", 0),
                         keywords=st.get("k"))
            db.add(mb)
        mb.token_enc = encrypt_json(tokens)
        mb.status, mb.last_error, mb.failures = "connected", "", 0
        db.add(AuditLog(shop_id=user.shop_id, user_id=user.id, entity="mailbox", entity_id=mb.id or "", action="linked", detail={"provider": provider, "address": address}))
        db.commit()
        enqueue("sync", mb.id, bool(mb.backfill_days))
        return RedirectResponse(back + "&mailbox=" + quote(address))
    except (MailboxAuthError, CryptoNotConfigured) as e:
        return RedirectResponse(back + "&mailbox_error=" + quote(str(e)[:200]))


class MailboxPatch(BaseModel):
    enabled: Optional[bool] = None
    backfill_days: Optional[int] = None
    keywords: Optional[str] = None


@router.patch("/mailboxes/{mid}")
def patch_mailbox(mid: str, body: MailboxPatch, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mb = db.get(Mailbox, mid)
    if not mb or mb.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    if body.enabled is not None:
        mb.status = "connected" if body.enabled else "disabled"
    if body.backfill_days is not None:
        mb.backfill_days = max(0, min(body.backfill_days, get_settings().max_backfill_days))
    if body.keywords is not None:
        mb.keywords = body.keywords
    db.commit()
    return _mailbox_dict(mb)


@router.delete("/mailboxes/{mid}")
def unlink_mailbox(mid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mb = db.get(Mailbox, mid)
    if not mb or mb.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    db.add(AuditLog(shop_id=mb.shop_id, user_id=user.id, entity="mailbox", entity_id=mb.id, action="unlinked", detail={"address": mb.address}))
    db.delete(mb)  # tokens are deleted with it; RFQs and stored files stay
    db.commit()
    return {"ok": True}


@router.post("/mailboxes/check")
def check_now(backfill: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Check now': queue a sync of every linked mailbox of this shop, and retry stuck files."""
    rows = db.scalars(select(Mailbox).where(Mailbox.shop_id == user.shop_id, Mailbox.status != "disabled")).all()
    results = [enqueue("sync", m.id, backfill) for m in rows]
    enqueue("retry_due", user.shop_id)
    return {"queued": len(rows), "results": [r for r in results if r]}


# ------------------------------------------------------------------ files
@router.post("/attachments/{aid}/retry")
def retry(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Attachment, aid)
    if not a or a.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    a.status_reason = "Retrying…"
    if not a.stored:
        a.status = "fetching"
    db.commit()
    enqueue("retry", a.id)
    db.refresh(a)
    return attachment_dict(a)


@router.get("/attachments/{aid}/link")
def file_link(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A short-lived signed URL the browser can open directly (<iframe>, <img>, new tab). Never a public URL."""
    a = db.get(Attachment, aid)
    guard(db, user, a, "link")
    if not a.stored:
        raise HTTPException(409, a.status_reason or "The file is not stored yet")
    ttl = get_settings().file_link_ttl_s
    return {"url": f"/api/files/{sign({'a': a.id, 's': a.shop_id, 'u': user.id}, ttl)}", "expires_in": ttl,
            "mime": a.mime, "previewable": a.ext in PREVIEWABLE}


@router.get("/files/{token}")
def serve(token: str, download: bool = False, db: Session = Depends(get_db)):
    body = verify(token)
    if not body:
        raise HTTPException(403, "Link expired: open the file again from the RFQ")
    a, user = db.get(Attachment, body.get("a", "")), db.get(User, body.get("u", ""))
    if not a or not user or a.shop_id != body.get("s") or user.shop_id != a.shop_id:
        raise HTTPException(404, "Not found")
    guard(db, user, a, "file")
    mime = a.mime if a.mime and a.ext in PREVIEWABLE else "application/octet-stream"
    disp = "attachment" if download or a.ext not in PREVIEWABLE else "inline"
    fname = quote(a.filename)
    return Response(storage.get(a.storage_key), media_type=mime, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{fname}", "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
        "Referrer-Policy": "no-referrer"})


class ExportBody(BaseModel):
    export_ok: bool


@router.put("/users/{uid}/export-access")
def set_export_access(uid: str, body: ExportBody, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    u.export_ok = body.export_ok
    db.add(AuditLog(shop_id=user.shop_id, user_id=user.id, entity="user", entity_id=u.id, action="export_access", detail={"granted": body.export_ok}))
    db.commit()
    return {"id": u.id, "export_ok": u.export_ok}


@router.get("/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "export_ok": u.export_ok}
            for u in db.scalars(select(User).where(User.shop_id == user.shop_id)).all()]
