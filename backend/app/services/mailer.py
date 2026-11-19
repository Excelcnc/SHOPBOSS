"""Outgoing email over SMTP (verification codes, invitations).

Works with any SMTP service: Resend, Postmark, Brevo, SendGrid, Mailgun, or Microsoft 365
(smtp.office365.com with SMTP AUTH enabled for the sending mailbox)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

from ..config import get_settings

log = logging.getLogger(__name__)


def enabled() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send(to: str, subject: str, text: str) -> bool:
    s = get_settings()
    if not enabled():
        log.warning("SMTP not configured; email to %s not sent: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(text)
    ctx = ssl.create_default_context()
    if s.smtp_port == 465:
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30) as m:
            if s.smtp_user:
                m.login(s.smtp_user, s.smtp_password)
            m.send_message(msg, from_addr=parseaddr(s.smtp_from)[1])
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as m:
            if s.smtp_tls:
                m.starttls(context=ctx)
            if s.smtp_user:
                m.login(s.smtp_user, s.smtp_password)
            m.send_message(msg, from_addr=parseaddr(s.smtp_from)[1])
    return True
