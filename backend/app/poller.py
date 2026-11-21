"""Scheduler: every POLL_INTERVAL_S (5 minutes) queue a sync of every linked mailbox that is due, retry
files left in 'fetching', and keep the Graph webhook subscription of the app-permission mailbox alive.

Run: python -m app.poller   (one process per deployment)
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .jobs import enqueue
from .models import IntegrationState, Mailbox
from .services.email import imap
from .services.email.graph import GraphClient, ensure_subscription
from .services.email.sync import app_mailbox

log = logging.getLogger("poller")


def once() -> dict:
    s = get_settings()
    db = SessionLocal()
    out = {"queued": 0, "imap": None}
    try:
        st = db.scalar(select(IntegrationState).where(IntegrationState.kind == "tenant:" + s.intake_tenant_key))
        client = GraphClient.from_settings()
        if st and client:  # the configured quoting mailbox (application permission) becomes a linked mailbox too
            app_mailbox(db, st.shop_id, client.mailbox)
            db.commit()
            ensure_subscription(db, st.shop_id, client)
        if st:
            out["imap"] = imap.poll(db, st.shop_id)
        now = datetime.now(timezone.utc)
        for mb in db.scalars(select(Mailbox).where(Mailbox.status.in_(["connected", "error"]))).all():
            due = mb.next_try_at.replace(tzinfo=timezone.utc) if mb.next_try_at and mb.next_try_at.tzinfo is None else mb.next_try_at
            if due is None or due <= now:
                enqueue("sync", mb.id)
                out["queued"] += 1
        enqueue("retry_due", "")
    finally:
        db.close()
    return out


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            log.info("poll: %s", once())
        except Exception:
            log.exception("poll failed")
        time.sleep(get_settings().poll_interval_s)


if __name__ == "__main__":
    main()
