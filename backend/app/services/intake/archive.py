"""Safe expansion of containers: ZIP archives and emails attached to emails (.eml / .msg).

ZIP limits (zip bombs, zip-slip, nesting) are enforced while reading: the sizes in the ZIP header are
not trusted, every entry is read through a counting stream that stops at the limit.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass

from .files import Incoming, ext_of, safe_name, sniff


@dataclass
class Limits:
    max_files: int = 300            # entries per archive (all levels together)
    max_total: int = 1024 * 2**20   # uncompressed bytes per archive (all levels together)
    max_entry: int = 200 * 2**20    # one uncompressed entry
    max_ratio: int = 200            # uncompressed / compressed, per entry (only checked above 1 MB)
    max_depth: int = 3              # zip in zip in zip, eml in zip, ...


@dataclass
class Rejected:
    name: str
    reason: str
    origin: str = ""


class _Budget:
    def __init__(self, lim: Limits):
        self.lim, self.files, self.bytes = lim, 0, 0


def unsafe_path(name: str) -> bool:
    """True for entries that would escape an extraction folder (zip-slip) or are device/absolute paths."""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
        return True
    norm = posixpath.normpath(n)
    return norm == ".." or norm.startswith("../") or "/../" in f"/{norm}/"


def _read_entry(z: zipfile.ZipFile, info: zipfile.ZipInfo, budget: _Budget) -> bytes:
    lim = budget.lim
    cap = min(lim.max_entry, lim.max_total - budget.bytes)
    out = io.BytesIO()
    with z.open(info) as fh:
        while True:
            chunk = fh.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            if out.tell() > cap:
                raise ValueError("archive is larger than the allowed size")
            if out.tell() > 2**20 and info.compress_size and out.tell() / max(1, info.compress_size) > lim.max_ratio:
                raise ValueError("compression ratio is suspicious (possible zip bomb)")
    budget.bytes += out.tell()
    return out.getvalue()


def _unzip(f: Incoming, depth: int, budget: _Budget, ok: list, bad: list):
    origin = f"zip:{safe_name(f.name)}"
    try:
        z = zipfile.ZipFile(io.BytesIO(f.data))
    except (zipfile.BadZipFile, ValueError):
        bad.append(Rejected(f.name, "Corrupted ZIP archive", f.origin))
        return
    with z:
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/") or info.filename.endswith(".DS_Store"):
                continue
            budget.files += 1
            if budget.files > budget.lim.max_files:
                bad.append(Rejected(f.name, f"Archive has more than {budget.lim.max_files} files; the rest were skipped", origin))
                return
            if unsafe_path(info.filename):
                bad.append(Rejected(info.filename, "Blocked: unsafe path inside the ZIP (path traversal)", origin))
                continue
            if info.flag_bits & 0x1:
                bad.append(Rejected(info.filename, "Password-protected file inside the ZIP", origin))
                continue
            try:
                data = _read_entry(z, info, budget)
            except ValueError as e:
                bad.append(Rejected(info.filename, f"Blocked: {e}", origin))
                if "allowed size" in str(e):
                    return
                continue
            except (zipfile.BadZipFile, EOFError, OSError, NotImplementedError):
                bad.append(Rejected(info.filename, "Corrupted entry in the ZIP", origin))
                continue
            _expand(Incoming(info.filename.replace("\\", "/").split("/")[-1], data, origin=origin, meta={"path": info.filename}),
                    depth + 1, budget, ok, bad)


def _attached_email(f: Incoming, depth: int, budget: _Budget, ok: list, bad: list):
    from ..email.parse import parse_email_file
    kind = "msg" if sniff(f.data) == "ole" else "eml"
    try:
        parsed = parse_email_file("x." + kind, f.data)
    except Exception:
        bad.append(Rejected(f.name, "Attached email could not be read", f.origin))
        return
    origin = f"{kind}:{safe_name(f.name)}"
    ok.append(Incoming(f.name if ext_of(f.name) in ("eml", "msg") else f"{safe_name(f.name)}.{kind}", f.data, origin=f.origin,
                       meta={"forwarded_from": parsed.sender_email, "subject": parsed.subject, "body": parsed.body[:20000]}))
    for name, data in parsed.attachments:
        _expand(Incoming(name, data, origin=origin), depth + 1, budget, ok, bad)


def _expand(f: Incoming, depth: int, budget: _Budget, ok: list, bad: list):
    ext, real = ext_of(f.name), sniff(f.data)
    container = "zip" if ext == "zip" or (real == "zip" and ext not in ("docx", "xlsx", "pptx")) else \
                "email" if ext in ("eml", "msg") or f.mime == "message/rfc822" else ""
    if container and depth >= budget.lim.max_depth:
        bad.append(Rejected(f.name, f"Nested too deeply (more than {budget.lim.max_depth} levels)", f.origin))
        return
    if container == "zip":
        if depth == 0:
            ok.append(f)  # keep the original archive as received
        _unzip(f, depth, budget, ok, bad)
    elif container == "email":
        _attached_email(f, depth, budget, ok, bad)
    else:
        ok.append(f)


def expand(files: list[Incoming], limits: Limits | None = None) -> tuple[list[Incoming], list[Rejected]]:
    """Flatten ZIPs and attached emails into plain files. Attached emails are kept as files too."""
    ok, bad = [], []
    lim = limits or Limits()
    for f in files:
        _expand(f, 0, _Budget(lim), ok, bad)
    return ok, bad
