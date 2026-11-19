"""Connected mailboxes: test, sync (Graph or IMAP), webhook subscriptions, bootstrap from .env."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...crypto import decrypt
from ...models import IntegrationState, Mailbox
from .graph import GraphClient, graph_configured, new_client_state
from .imap import ImapClient
from .parse import ParsedEmail, looks_like_rfq, parse_eml

log = logging.getLogger(__name__)
now = lambda: datetime.now(timezone.utc)


def _ingest(db: Session, mb: Mailbox, parsed: ParsedEmail) -> bool:
    from ...jobs import enqueue_analysis
    from ..pipeline import create_rfq_from_email
    if mb.filter_rfqs:
        keep, why = looks_like_rfq(parsed)
        if not keep:
            log.info("%s: skipped non-RFQ email '%s' (%s)", mb.address, parsed.subject[:80], why)
            mb.skipped = (mb.skipped or 0) + 1
            return False
    rfq = create_rfq_from_email(db, mb.shop_id, parsed, mb.kind, mailbox=mb.address)
    if not rfq:
        return False  # duplicate (same message delivered to two connected mailboxes, or re-synced)
    mb.imported = (mb.imported or 0) + 1
    db.commit()
    enqueue_analysis(rfq.id)
    return True


def graph_client(mb: Mailbox, http: httpx.Client | None = None) -> GraphClient:
    return GraphClient.for_mailbox(mb.address, mb.folder, http)


def ingest_graph_message(db: Session, mb: Mailbox, msg_id: str, client: GraphClient | None = None) -> bool:
    return _ingest(db, mb, (client or graph_client(mb)).get_message(msg_id))


def sync(db: Session, mb: Mailbox, client=None) -> int:
    """Pull new mail for one mailbox. The first sync records the current position and only imports
    old mail when backfill_days > 0."""
    n = 0
    try:
        if mb.kind == "graph":
            c = client or graph_client(mb)
            st = dict(mb.state or {})
            first = not st.get("delta_link")
            since = now() - timedelta(days=mb.backfill_days) if first and mb.backfill_days else None
            ids, link = c.delta(st.get("delta_link"), since)
            if not first or since:
                for mid in ids:
                    n += _ingest(db, mb, c.get_message(mid))
            mb.state = {**st, "delta_link": link}
        else:
            st = dict(mb.state or {})
            with (client or ImapClient(mb.imap_host, mb.imap_port, mb.imap_user or mb.address, decrypt(mb.imap_password_enc), mb.folder)) as c:
                if "last_uid" not in st:
                    uids = c.uids_since(mb.backfill_days) if mb.backfill_days else []
                    last = c.max_uid()
                else:
                    last = int(st["last_uid"])
                    uids = c.uids_after(last)
                for uid in sorted(uids):
                    raw = c.fetch(uid)
                    if raw:
                        n += _ingest(db, mb, parse_eml(raw))
                    last = max(last, uid)
            mb.state = {**st, "last_uid": last}
        mb.last_error = None
    except Exception as e:
        db.rollback()
        mb = db.get(Mailbox, mb.id)
        mb.last_error = str(e)[:1000]
        log.warning("sync %s failed: %s", mb.address, e)
    mb.last_sync_at = now()
    db.commit()
    return n


def test(mb: Mailbox, client=None) -> dict:
    """Read-only connection check: sign in, open the folder, report counts. Never reads message contents."""
    try:
        if mb.kind == "graph":
            info = (client or graph_client(mb)).folder_counts()
            return {"ok": True, "message": f"Connected to {mb.address}, folder '{info.get('displayName', mb.folder)}': {info.get('totalItemCount')} messages, {info.get('unreadItemCount')} unread."}
        with (client or ImapClient(mb.imap_host, mb.imap_port, mb.imap_user or mb.address, decrypt(mb.imap_password_enc), mb.folder)) as c:
            return {"ok": True, "message": f"Connected to {mb.imap_host} as {mb.imap_user or mb.address}, folder '{c.folder}': {c.count} messages."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:500]}


def ensure_subscription(db: Session, mb: Mailbox, client: GraphClient | None = None):
    s = get_settings()
    if mb.kind != "graph" or not s.graph_webhook_url:
        return None
    c = client or graph_client(mb)
    st = dict(mb.state or {})
    sub = st.get("subscription")
    try:
        if sub and datetime.fromisoformat(sub["expirationDateTime"].replace("Z", "+00:00")) - now() > timedelta(hours=12):
            return sub
        if sub:
            sub = {**sub, **c.renew(sub["id"])}
        else:
            raise KeyError
    except Exception:
        cs = new_client_state()
        new = c.subscribe(s.graph_webhook_url, cs)
        sub = {"id": new["id"], "expirationDateTime": new["expirationDateTime"], "client_state": cs}
    mb.state = {**st, "subscription": {"id": sub["id"], "expirationDateTime": sub["expirationDateTime"], "client_state": sub.get("client_state") or st.get("subscription", {}).get("client_state")}}
    db.commit()
    return sub


def remove(db: Session, mb: Mailbox):
    sub = (mb.state or {}).get("subscription")
    if mb.kind == "graph" and sub and graph_configured():
        try:
            graph_client(mb).unsubscribe(sub["id"])
        except Exception:
            pass
    db.delete(mb)
    db.commit()


def bootstrap_from_env(db: Session):
    """Older single-mailbox setups (GRAPH_MAILBOX / IMAP_HOST in .env) become connected mailboxes once."""
    s = get_settings()
    st = db.scalar(select(IntegrationState).where(IntegrationState.kind == "tenant:" + s.intake_tenant_key))
    if not st:
        return
    if s.graph_mailbox and graph_configured():
        if not db.scalar(select(Mailbox).where(Mailbox.shop_id == st.shop_id, Mailbox.kind == "graph", Mailbox.address == s.graph_mailbox.lower())):
            db.add(Mailbox(shop_id=st.shop_id, kind="graph", address=s.graph_mailbox.lower(), label="From server settings", folder=s.graph_folder or "inbox", filter_rfqs=s.intake_filter))
    if s.imap_host and s.imap_user:
        from ...crypto import encrypt
        if not db.scalar(select(Mailbox).where(Mailbox.shop_id == st.shop_id, Mailbox.kind == "imap", Mailbox.address == s.imap_user.lower())):
            db.add(Mailbox(shop_id=st.shop_id, kind="imap", address=s.imap_user.lower(), label="From server settings", folder=s.imap_folder,
                           imap_host=s.imap_host, imap_user=s.imap_user, imap_password_enc=encrypt(s.imap_password), filter_rfqs=s.intake_filter))
    db.commit()


def poll_all(db: Session) -> dict:
    bootstrap_from_env(db)
    out = {}
    for mb in db.scalars(select(Mailbox).where(Mailbox.active.is_(True))).all():
        if mb.kind == "graph":
            try:
                ensure_subscription(db, mb)
            except Exception as e:
                log.warning("subscription for %s: %s", mb.address, e)
        out[mb.address + ":" + mb.folder] = sync(db, mb)
    return out
