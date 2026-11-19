"""Encryption for stored credentials (IMAP app passwords). Key derived from SECRET_KEY."""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

log = logging.getLogger(__name__)


def _f() -> Fernet:
    key = get_settings().secret_key
    if not key:
        log.warning("SECRET_KEY is not set: using an insecure development key")
        key = "dev-only-insecure-key"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(text: str) -> str:
    return _f().encrypt(text.encode()).decode() if text else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _f().decrypt(token.encode()).decode()
    except InvalidToken:
        raise RuntimeError("Stored password can't be decrypted (SECRET_KEY changed). Re-enter the password.")
