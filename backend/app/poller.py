"""Mailbox poller: for every connected mailbox, renew its Graph webhook subscription and pull new mail
(Graph delta or IMAP) every few minutes.

Run: python -m app.poller   (one process per deployment)
"""
import logging
import time

from .db import SessionLocal
from .services.email.mailboxes import poll_all

log = logging.getLogger("poller")


def once() -> dict:
    db = SessionLocal()
    try:
        return poll_all(db)
    finally:
        db.close()


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
