"""Background jobs. Production: Redis + RQ worker (`rq worker analysis mail`). Dev/tests: RUN_JOBS_INLINE=true."""
from __future__ import annotations

import logging

from .config import get_settings
from .db import SessionLocal

log = logging.getLogger(__name__)


def _run_process(rfq_id: str):
    from .services.pipeline import process_rfq
    db = SessionLocal()
    try:
        process_rfq(db, rfq_id)
    finally:
        db.close()


def _run_mail(task: str, oid: str, flag: bool = False):
    from .models import Attachment, Mailbox, Rfq
    from .services.email import sync
    db = SessionLocal()
    try:
        if task == "sync":
            mb = db.get(Mailbox, oid)
            if mb and mb.status != "disabled":
                return sync.sync_mailbox(db, mb, backfill=flag)
        elif task == "links":
            r = db.get(Rfq, oid)
            if r:
                sync.fetch_links(db, r)
                enqueue_analysis(r.id)
        elif task == "retry":
            a = db.get(Attachment, oid)
            if a:
                return sync.retry_attachment(db, a)
        elif task == "retry_due":
            return sync.retry_due(db, oid or None)
    finally:
        db.close()


def _queue(name: str):
    from redis import Redis
    from rq import Queue
    return Queue(name, connection=Redis.from_url(get_settings().redis_url), default_timeout=900)


def enqueue_analysis(rfq_id: str, wait: bool = False):
    if get_settings().run_jobs_inline:  # dev/tests: run in-process, synchronously
        _run_process(rfq_id)
        return
    _queue("analysis").enqueue(_run_process, rfq_id)


def enqueue(task: str, oid: str = "", flag: bool = False):
    """Mail jobs: 'sync' (mailbox id), 'links' (rfq id), 'retry' (attachment id), 'retry_due' (shop id or '')."""
    if get_settings().run_jobs_inline:
        return _run_mail(task, oid, flag)
    job_id = f"{task}:{oid}" if task in ("sync", "retry") else None  # one sync per mailbox at a time
    _queue("mail").enqueue(_run_mail, task, oid, flag, job_id=job_id)
