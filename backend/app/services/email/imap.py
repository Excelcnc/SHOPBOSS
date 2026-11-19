"""Generic mailbox intake over IMAP (a dedicated address that RFQs are forwarded to)."""
from __future__ import annotations

import imaplib
import logging

from sqlalchemy.orm import Session

from ...config import get_settings
from .graph import _state
from .parse import parse_eml

log = logging.getLogger(__name__)


def poll(db: Session, shop_id: str) -> int:
    s = get_settings()
    if not (s.imap_host and s.imap_user):
        return 0
    from ...jobs import enqueue_analysis
    from ..pipeline import create_rfq_from_email
    st = _state(db, shop_id, "imap")
    last = int(st.state.get("last_uid", 0))
    n = 0
    with imaplib.IMAP4_SSL(s.imap_host) as M:
        M.login(s.imap_user, s.imap_password)
        M.select(s.imap_folder, readonly=True)
        typ, data = M.uid("search", None, f"UID {last + 1}:*")
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > last]
        for uid in uids:
            typ, msg = M.uid("fetch", str(uid), "(RFC822)")
            raw = next((part[1] for part in msg if isinstance(part, tuple)), None)
            if raw:
                from .parse import looks_like_rfq
                parsed = parse_eml(raw)
                rfq = create_rfq_from_email(db, shop_id, parsed, "imap") if looks_like_rfq(parsed)[0] else None
                db.commit()
                if rfq:
                    enqueue_analysis(rfq.id)
                    n += 1
            last = max(last, uid)
    st.state = {**st.state, "last_uid": last}
    db.commit()
    return n
