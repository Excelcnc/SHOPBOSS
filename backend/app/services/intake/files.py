"""Checks every incoming file before it is stored or opened.

Email and file contents are untrusted. Nothing here executes or interprets them: we only look at
magic bytes, names and sizes, and (for PDFs) ask PyMuPDF whether the document opens.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field

# Extensions we never store or open (programs, scripts, installers, macro containers).
BLOCKED_EXT = {
    "exe", "dll", "com", "scr", "msi", "msp", "bat", "cmd", "ps1", "psm1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "jar", "app", "dmg", "pkg", "sh", "bash", "zsh", "py", "pl", "rb", "php", "lnk", "reg", "cpl", "iso", "img", "vhd",
    "apk", "deb", "rpm", "docm", "xlsm", "pptm", "dotm", "xlam", "html", "htm", "svg", "chm", "url", "iqy", "slk",
}
# MIME types for files we keep; anything else is served as application/octet-stream.
MIME = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "tif": "image/tiff", "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp",
    "step": "model/step", "stp": "model/step", "iges": "model/iges", "igs": "model/iges", "stl": "model/stl",
    "dxf": "image/vnd.dxf", "dwg": "image/vnd.dwg", "zip": "application/zip", "eml": "message/rfc822",
    "msg": "application/vnd.ms-outlook", "txt": "text/plain", "csv": "text/csv",
    "doc": "application/msword", "xls": "application/vnd.ms-excel", "ppt": "application/vnd.ms-powerpoint",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PREVIEWABLE = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp", "gif", "step", "stp", "stl"}
NOISE_EXT = {"ics", "vcf", "p7s", "p7m", "asc", "sig"}
NOISE_NAME = re.compile(r"(?i)^(image\d*|img_?\d*|outlook[-_ ]?[\w]*|logo[\w-]*|signature[\w-]*|banner[\w-]*|facebook|linkedin|twitter|x|instagram|youtube|icon[\w-]*|spacer|pixel)\.(png|jpe?g|gif|bmp|webp)$")
MIN_BYTES = 200                 # smaller than this is never a real drawing or model
SMALL_IMAGE = 25 * 1024         # inline images under this size are signatures and logos


@dataclass
class Incoming:
    """One file as it arrives, before checks. `origin` says where it came from (for the UI and audit)."""
    name: str
    data: bytes
    mime: str = ""
    inline: bool = False
    origin: str = ""            # e.g. "email", "zip:drawings.zip", "eml:Fwd RFQ.eml", "link:dropbox"
    meta: dict = field(default_factory=dict)


@dataclass
class Verdict:
    ok: bool
    ext: str
    mime: str
    status: str = "stored"      # stored | failed | download_only
    reason: str = ""


def b64decode_any(s: str | bytes) -> bytes:
    """Decode Gmail's URL-safe base64 (no padding) as well as standard base64."""
    if isinstance(s, bytes):
        s = s.decode("ascii", "strict")
    s = re.sub(r"\s+", "", s)
    s += "=" * (-len(s) % 4)
    try:
        if "-" in s or "_" in s:
            return base64.urlsafe_b64decode(s)
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"attachment data is not valid base64: {e}") from None


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def safe_name(name: str) -> str:
    """Keep the customer's file name but drop directories and control characters."""
    name = (name or "attachment").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".") or "attachment"
    return name[:200]


def sniff(data: bytes) -> str:
    """Best guess of the real type from magic bytes ('' when unknown)."""
    h = data[:16]
    if data[:1024].find(b"%PDF-") != -1:
        return "pdf"
    if h.startswith(b"PK\x03\x04") or h.startswith(b"PK\x05\x06"):
        return "zip"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tif"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"         # .msg, .doc, .xls, .sldprt, ...
    if h.startswith(b"MZ") or h.startswith(b"\x7fELF") or h[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"):
        return "exe"
    if h.startswith(b"AC10") or h.startswith(b"AC1."):
        return "dwg"
    head = data[:2048].lstrip().upper()
    if head.startswith(b"ISO-10303-21"):
        return "step"
    if head.startswith(b"#!"):
        return "script"
    if head.startswith(b"<!DOCTYPE HTML") or head.startswith(b"<HTML"):
        return "html"
    if re.match(rb"0\s*\r?\n\s*SECTION", data[:64].lstrip()):
        return "dxf"
    if re.match(rb"(?i)(received|return-path|from|message-id|mime-version|date|subject|delivered-to|x-[\w-]+):", data[:200]):
        return "eml"
    return ""


# extension -> magic types that are acceptable for it
_COMPATIBLE = {
    "pdf": {"pdf"}, "png": {"png"}, "jpg": {"jpg"}, "jpeg": {"jpg"}, "tif": {"tif"}, "tiff": {"tif"}, "gif": {"gif"},
    "zip": {"zip"}, "docx": {"zip"}, "xlsx": {"zip"}, "pptx": {"zip"}, "sldasm": {"ole", ""}, "sldprt": {"ole", ""},
    "slddrw": {"ole", ""}, "msg": {"ole"}, "doc": {"ole"}, "xls": {"ole"}, "ppt": {"ole"}, "step": {"step"}, "stp": {"step"},
    "dwg": {"dwg"}, "dxf": {"dxf", ""}, "eml": {"eml", ""},
}


def check(f: Incoming, max_bytes: int) -> Verdict:
    """Type check, size cap, executable/script rejection, PDF validity (corrupt, password-protected)."""
    name = safe_name(f.name)
    ext = ext_of(name)
    real = sniff(f.data)
    mime = MIME.get(ext, "application/octet-stream")
    if len(f.data) > max_bytes:
        return Verdict(False, ext, mime, "failed", f"Too large ({len(f.data) // 2**20} MB, limit {max_bytes // 2**20} MB)")
    if ext in BLOCKED_EXT or real in ("exe", "script", "html"):
        return Verdict(False, ext, mime, "failed", "Blocked: programs, scripts and web pages are not accepted")
    if not f.data:
        return Verdict(False, ext, mime, "failed", "Empty file")
    want = _COMPATIBLE.get(ext)
    if want is not None and real not in want:
        if ext == "pdf":
            return Verdict(False, ext, mime, "failed", "Corrupted: this is not a valid PDF (no PDF header)")
        return Verdict(False, ext, mime, "failed", f"File content does not match its .{ext} name")
    if ext == "pdf":
        reason = pdf_problem(f.data)
        if reason:
            return Verdict(False, ext, mime, "failed", reason)
    status = "stored" if ext in PREVIEWABLE or ext in ("dxf", "iges", "igs", "zip", "eml", "msg") else "download_only"
    return Verdict(True, ext, mime, status, "" if status == "stored" else "Stored. No preview for this file type: download to open it")


def pdf_problem(data: bytes) -> str:
    import fitz
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return "Corrupted: the PDF could not be opened"
    try:
        if doc.needs_pass:
            return "Password-protected PDF: ask the customer for an unprotected copy"
        if doc.page_count < 1:
            return "Corrupted: the PDF has no pages"
    finally:
        doc.close()
    return ""


def is_noise(f: Incoming) -> str:
    """Return why a file is noise (logo, signature image, calendar invite, tiny file), or ''."""
    name = safe_name(f.name)
    ext = ext_of(name)
    if ext in NOISE_EXT:
        return "calendar, contact or signature file"
    if len(f.data) < MIN_BYTES:
        return "tiny file"
    if ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
        if NOISE_NAME.match(name) and (f.inline or len(f.data) < 100 * 1024):
            return "signature or logo image"
        if f.inline and len(f.data) < SMALL_IMAGE:
            return "inline signature image"
    return ""
