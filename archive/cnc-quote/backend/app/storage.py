"""File storage. Local disk for development; the same interface maps onto Azure Blob / S3."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .config import get_settings


def _root() -> Path:
    p = Path(get_settings().storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def put(shop_id: str, data: bytes, filename: str) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)[-120:]
    key = f"{shop_id}/{sha[:2]}/{sha}_{safe}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return key, sha


def get(key: str) -> bytes:
    path = (_root() / key).resolve()
    if _root() not in path.parents:
        raise ValueError("invalid storage key")
    return path.read_bytes()


def local_path(key: str) -> str:
    path = (_root() / key).resolve()
    if _root() not in path.parents:
        raise ValueError("invalid storage key")
    return str(path)


def delete(key: str) -> None:
    try:
        os.remove(local_path(key))
    except FileNotFoundError:
        pass
