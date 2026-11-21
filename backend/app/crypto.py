"""Encryption at rest for mailbox OAuth tokens, and signing of short-lived file links.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using TOKEN_ENCRYPTION_KEY. They are
decrypted only in memory when a mailbox is synced, and never logged or returned by the API.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

log = logging.getLogger(__name__)
_DEV_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"shopboss-dev-only-not-secret").digest())


class CryptoNotConfigured(RuntimeError):
    pass


def _fernet() -> Fernet:
    s = get_settings()
    if s.token_encryption_key:
        return Fernet(s.token_encryption_key.encode())
    if s.auth_mode == "dev":
        return Fernet(_DEV_KEY)
    raise CryptoNotConfigured("TOKEN_ENCRYPTION_KEY is not set: mailbox tokens can't be stored")


def encrypt_json(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt_json(blob: str) -> dict:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()))
    except InvalidToken:
        raise CryptoNotConfigured("Stored mailbox token can't be decrypted (TOKEN_ENCRYPTION_KEY changed?). Reconnect the mailbox.") from None


def _link_key() -> bytes:
    s = get_settings()
    k = s.file_link_secret or s.token_encryption_key
    if k:
        return hashlib.sha256(("file-link:" + k).encode()).digest()
    if s.auth_mode == "dev":
        return hashlib.sha256(b"shopboss-dev-file-link").digest()
    raise CryptoNotConfigured("FILE_LINK_SECRET is not set")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def sign(payload: dict, ttl_s: int | None = None) -> str:
    """A compact signed token (HMAC-SHA256) that expires after ttl_s seconds."""
    body = {**payload, "exp": int(time.time()) + (ttl_s or get_settings().file_link_ttl_s)}
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    mac = _b64(hmac.new(_link_key(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{mac}"


def verify(token: str) -> dict | None:
    try:
        raw, mac = token.split(".", 1)
        good = _b64(hmac.new(_link_key(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, mac):
            return None
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if body.get("exp", 0) < time.time():
        return None
    return body
