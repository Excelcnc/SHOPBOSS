from app.services.drawing.dxf import analyze_dxf
from app.services.drawing.extract import analyze_pdf, image_to_pdf
from app.services.email.parse import extract_fields, parse_eml


def test_pdf_title_block_and_callouts(samples):
    r = analyze_pdf((samples / "SHF-3310_RevD.pdf").read_bytes())
    m = {k: v["value"] for k, v in r["meta"].items()}
    assert m["drawing_number"] == "SHF-3310" and m["revision"] == "D" and m["units"] == "MM"
    assert "4140" in m["material"]
    vals = {(i["cat"], i["value"]) for i in r["items"]}
    assert ("fit", "Ø30 g6") in vals and ("dimension", "180.00") in vals
    fit = next(i for i in r["items"] if i["cat"] == "fit")
    assert abs(fit["band"] - 0.013) < 1e-6 and fit["critical"]
    assert all(0 <= x <= 1 for i in r["items"] for x in i["bbox"])


def test_scan_has_no_text(samples):
    r = analyze_pdf(image_to_pdf((samples / "CAS-7781-04_scan.png").read_bytes()))
    assert r["has_text"] is False and r["items"] == []


def test_dxf(samples):
    r = analyze_dxf((samples / "FLG-5520_RevA.dxf").read_bytes())
    assert r["meta"]["drawing_number"]["value"] == "FLG-5520"
    assert "316L" in r["meta"]["material"]["value"]
    assert any(i["cat"] == "hole" and i["qty"] == 8 and i["value"] == "Ø14.0" for i in r["items"])


def test_eml_and_fields(samples):
    e = parse_eml((samples / "RFQ_BWP-2026-0418.eml").read_bytes())
    assert e.sender_email == "p.raman@brightwater-pumps.example" and len(e.attachments) == 1
    f = extract_fields(e.subject, e.body, e.sender_name, e.sender_email, [a[0] for a in e.attachments])
    assert f["customer_name"]["value"] == "Brightwater Pumps Ltd"
    assert f["customer_rfq_no"]["value"] == "BWP-2026-0418"
    assert 120 in f["quantities"]["value"]
    assert "15 January 2027" in f["due_date"]["value"] and "27 November 2026" in f["quote_due"]["value"]
    assert "316L" in f["material"]["value"]


def test_bom_from_assembly_drawing(samples):
    from app.services.drawing.bom import extract_bom
    rows = extract_bom((samples / "SENSOR-MOUNT-ASSY-100_RevA.pdf").read_bytes())
    by = {r["part_number"]: r for r in rows}
    assert len(rows) == 6
    assert by["ISO 4762 M6x20"]["qty"] == 4 and by["ISO 4762 M6x20"]["purchased"]
    assert by["ISO 7089 M6"]["qty"] == 4 and by["LBL-0007"]["purchased"]
    assert not by["BRK-20417"]["purchased"] and not by["BASE-PLATE-101"]["purchased"]
    assert by["BRK-20417"]["description"] == "MOUNTING BRACKET, SENSOR"
    assert all(r["bbox"] for r in rows)


def test_rfq_filter_for_shared_mailbox():
    from datetime import datetime, timezone
    from app.services.email.parse import ParsedEmail, looks_like_rfq
    mk = lambda subj, body, atts: ParsedEmail("<x>", "A", "a@b.c", subj, body, datetime.now(timezone.utc), [(n, b"") for n in atts])
    assert looks_like_rfq(mk("Parts", "see attached", ["BRK-1.step"]))[0]
    assert looks_like_rfq(mk("RFQ 4471 bracket", "please quote 50 pcs", ["BRK-1.pdf"]))[0]
    assert looks_like_rfq(mk("Request for quotation", "drawing to follow", []))[0]
    assert not looks_like_rfq(mk("Invoice 88231", "Please find attached invoice", ["INV-88231.pdf"]))[0]
    assert not looks_like_rfq(mk("Your order 5521 has shipped", "tracking attached", ["packing-slip.pdf"]))[0]
    assert not looks_like_rfq(mk("Quotation Q-2231 for aluminium bar", "our price for 6061 bar", ["Q-2231.pdf"]))[0]  # a supplier's quote to us
