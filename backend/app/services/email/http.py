"""HTTP for mailbox APIs: retry with backoff on rate limits and outages, typed auth errors.

Only GET requests are made to mail APIs (read-only); POST is used only for OAuth token endpoints.
Responses are never logged: they contain customer mail.
"""
from __future__ import annotations

import random
import time

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class MailboxAuthError(Exception):
    """The mailbox must be reconnected (token expired, revoked or consent removed)."""


class MailboxTransient(Exception):
    """Temporary failure (rate limit, outage). The job retries later with backoff."""


def request(http: httpx.Client, method: str, url: str, *, tries: int = 5, sleep=time.sleep, **kw) -> httpx.Response:
    last = None
    for i in range(tries):
        try:
            r = http.request(method, url, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = e
            sleep(min(60, 2 ** i + random.random()))
            continue
        if r.status_code in RETRY_STATUS:
            ra = r.headers.get("retry-after", "")
            wait = float(ra) if ra.replace(".", "", 1).isdigit() else min(60, 2 ** i + random.random())
            last = MailboxTransient(f"rate limited or unavailable ({r.status_code})")
            if i < tries - 1:
                sleep(min(wait, 120))
            continue
        return r
    raise MailboxTransient(str(last) if last else "mail service unavailable")
