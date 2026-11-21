"""Attachment decoding, file checks, ZIP safety, noise and duplicate detection."""
import base64
import io
import zipfile

import fitz
import pytest

from app.services.intake.archive import Limits, expand, unsafe_path
from app.services.intake.files import Incoming, b64decode_any, check, is_noise, sniff

MB = 2**20


def pdf_bytes(text="BRK-20417 REV C", password=None) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    kw = {"encryption": fitz.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password} if password else {}
    out = doc.tobytes(**kw)
    doc.close()
    return out


def zbytes(entries: dict, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------- decoding
def test_gmail_urlsafe_base64_without_padding_decodes_to_the_original_pdf():
    raw = pdf_bytes() + b"\xfb\xff\xfe"  # bytes that produce '-' and '_' in URL-safe base64
    enc = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert "=" not in enc
    assert b64decode_any(enc) == raw
    assert b64decode_any(base64.b64encode(raw)) == raw          # standard base64 too
    assert b64decode_any(enc[:40] + "\n" + enc[40:]) == raw      # line breaks are ignored


def test_invalid_base64_is_an_error_not_garbage():
    with pytest.raises(ValueError):
        b64decode_any("not*base64!")


def test_sniff_detects_real_types():
    assert sniff(pdf_bytes()) == "pdf"
    assert sniff(zbytes({"a.txt": "x"})) == "zip"
    assert sniff(b"ISO-10303-21;\nHEADER;") == "step"
    assert sniff(b"MZ\x90\x00rest") == "exe"


# ---------------------------------------------------------------- checks
def test_valid_pdf_is_stored_with_pdf_mime():
    v = check(Incoming("BRK-20417_RevC.pdf", pdf_bytes()), 50 * MB)
    assert v.ok and v.mime == "application/pdf" and v.status == "stored"


def test_octet_stream_pdf_still_gets_pdf_mime():
    v = check(Incoming("drawing.pdf", pdf_bytes(), mime="application/octet-stream"), 50 * MB)
    assert v.ok and v.mime == "application/pdf"


def test_fake_pdf_is_rejected_as_corrupted():
    v = check(Incoming("drawing.pdf", b"<html><body>Sign in to view</body></html>" * 10), 50 * MB)
    assert not v.ok and ("Blocked" in v.reason or "Corrupted" in v.reason)


def test_truncated_pdf_is_rejected_as_corrupted():
    v = check(Incoming("drawing.pdf", b"%PDF-1.7\n" + b"0" * 500), 50 * MB)
    assert not v.ok and v.reason.startswith("Corrupted")


def test_password_protected_pdf_is_flagged():
    v = check(Incoming("locked.pdf", pdf_bytes(password="secret")), 50 * MB)
    assert not v.ok and "Password-protected" in v.reason


def test_executables_and_scripts_are_rejected():
    for name, data in [("setup.exe", b"MZ" + b"\0" * 400), ("drawing.pdf.exe", b"MZ" + b"\0" * 400), ("run.js", b"alert(1)" * 50),
                       ("drawing.pdf", b"MZ" + b"\0" * 400), ("invoice.html", b"<html>" + b"x" * 400), ("tool.docm", b"PK\x03\x04" + b"0" * 400)]:
        v = check(Incoming(name, data), 50 * MB)
        assert not v.ok and v.status == "failed", name


def test_size_cap():
    v = check(Incoming("big.step", b"ISO-10303-21;" + b"0" * (2 * MB)), 1 * MB)
    assert not v.ok and "Too large" in v.reason


def test_unpreviewable_types_are_download_only():
    v = check(Incoming("part.sldprt", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 500), 50 * MB)
    assert v.ok and v.status == "download_only"


# ---------------------------------------------------------------- noise
def test_signature_images_logos_and_tiny_files_are_noise():
    assert is_noise(Incoming("image001.png", b"\x89PNG\r\n\x1a\n" + b"0" * 5000, inline=True))
    assert is_noise(Incoming("Outlook-signature_.png", b"\x89PNG\r\n\x1a\n" + b"0" * 40000))
    assert is_noise(Incoming("photo.jpg", b"\xff\xd8\xff" + b"0" * 9000, inline=True))
    assert is_noise(Incoming("invite.ics", b"BEGIN:VCALENDAR" + b"0" * 500))
    assert is_noise(Incoming("x.pdf", b"%PDF-1.4"))
    assert not is_noise(Incoming("scan_of_drawing.png", b"\x89PNG\r\n\x1a\n" + b"0" * 300000))
    assert not is_noise(Incoming("BRK-20417_RevC.pdf", pdf_bytes()))


# ---------------------------------------------------------------- ZIP safety
def test_zip_is_expanded_and_inner_names_are_flattened():
    ok, bad = expand([Incoming("rfq.zip", zbytes({"drawings/A-100.pdf": pdf_bytes(), "models/A-100.step": b"ISO-10303-21;" + b"0" * 300}))])
    assert sorted(f.name for f in ok) == ["A-100.pdf", "A-100.step"] and not bad
    assert all(f.origin == "zip:rfq.zip" for f in ok)


@pytest.mark.parametrize("name", ["../../etc/passwd", "/abs/evil.pdf", "C:/Windows/evil.pdf", "a/../../evil.pdf", "..\\..\\evil.pdf"])
def test_zip_slip_paths_are_blocked(name):
    assert unsafe_path(name)
    ok, bad = expand([Incoming("evil.zip", zbytes({name: pdf_bytes(), "good.pdf": pdf_bytes("good")}))])
    assert [f.name for f in ok] == ["good.pdf"]
    assert bad and "path traversal" in bad[0].reason


def test_safe_nested_paths_are_allowed():
    assert not unsafe_path("drawings/rev c/A-100.pdf")


def test_zip_bomb_is_blocked_by_ratio_while_reading():
    ok, bad = expand([Incoming("bomb.zip", zbytes({"zeros.pdf": b"\0" * (30 * MB)}))])
    assert not ok and "zip bomb" in bad[0].reason


def test_total_size_limit_is_enforced_on_real_bytes():
    rnd = __import__("os").urandom
    ok, bad = expand([Incoming("big.zip", zbytes({f"f{i}.step": rnd(2 * MB) for i in range(4)}, zipfile.ZIP_STORED))],
                     Limits(max_total=5 * MB, max_entry=10 * MB))
    assert len(ok) == 2 and "allowed size" in bad[0].reason


def test_too_many_files_is_limited():
    ok, bad = expand([Incoming("many.zip", zbytes({f"f{i}.txt": f"file {i} " * 40 for i in range(20)}))], Limits(max_files=5))
    assert len(ok) == 5 and "more than 5 files" in bad[0].reason


def test_nesting_depth_is_limited():
    inner = zbytes({"deep.pdf": pdf_bytes()})
    for _ in range(4):
        inner = zbytes({"nested.zip": inner})
    ok, bad = expand([Incoming("top.zip", inner)], Limits(max_depth=3))
    assert not ok and "Nested too deeply" in bad[0].reason


def test_corrupt_zip_is_reported():
    ok, bad = expand([Incoming("broken.zip", b"PK\x03\x04" + b"garbage" * 100)])
    assert not ok and "Corrupted ZIP" in bad[0].reason


def test_forwarded_email_attachment_is_opened_and_its_files_taken(samples):
    eml = (samples / "RFQ_BWP-2026-0418.eml").read_bytes()
    ok, bad = expand([Incoming("Fwd RFQ.eml", eml)])
    names = [f.name for f in ok]
    assert "Fwd RFQ.eml" in names and len(names) > 1 and not bad
    assert any(f.origin == "eml:Fwd RFQ.eml" for f in ok)
