"""Mailbox poller: renews the Graph subscription, runs a Graph delta sync and an IMAP poll every few minutes.

Run: python -m app.poller   (one process per deployment)
"""
import logging
import time

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import IntegrationState
from .services.email import imap
from .services.email.graph import GraphClient, ensure_subscription, sync

log = logging.getLogger("poller")


def once() -> dict:
    s = get_settings()
    db = SessionLocal()
    out = {"graph": None, "imap": None}
    try:
        st = db.scalar(select(IntegrationState).where(IntegrationState.kind == "tenant:" + s.intake_tenant_key))
        if not st:
            log.warning("No shop for intake tenant %s yet (sign in once first)", s.intake_tenant_key)
            return out
        client = GraphClient.from_settings()
        if client:
            ensure_subscription(db, st.shop_id, client)
            out["graph"] = sync(db, st.shop_id, client)
        out["imap"] = imap.poll(db, st.shop_id)
    finally:
        db.close()
    return out


def main(interval_s: int = 300):
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            log.info("poll: %s", once())
        except Exception:
            log.exception("poll failed")
        time.sleep(interval_s)


if __name__ == "__main__":
    main()
