"""Background jobs. Production: Redis + RQ worker (`rq worker analysis`). Dev/tests: RUN_JOBS_INLINE=true."""
from __future__ import annotations

import logging
import threading

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


def enqueue_analysis(rfq_id: str, wait: bool = False):
    s = get_settings()
    if s.run_jobs_inline:  # dev/tests: run in-process, synchronously
        _run_process(rfq_id)
        return
    from redis import Redis
    from rq import Queue
    Queue("analysis", connection=Redis.from_url(s.redis_url), default_timeout=900).enqueue(_run_process, rfq_id)
