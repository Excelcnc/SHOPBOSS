"""Quote versions (overrides, Save As), final quote output and PDF."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import Part, Quote, QuoteOutput, QuoteVersion, Rfq, Shop
from .costing.engine import estimate
from .pipeline import audit, build_inputs
from .shopdata import shop_catalog


def recompute(db: Session, v: QuoteVersion):
    v.result = estimate(v.inputs, v.overrides)
    v.updated_at = datetime.now(timezone.utc)


def set_overrides(db: Session, v: QuoteVersion, changes: dict, user_id: str | None, reason: str = ""):
    """changes: {key: value or None (None removes the override)}."""
    ov = dict(v.overrides or {})
    for k, val in changes.items():
        if val is None or val == "":
            ov.pop(k, None)
        else:
            ov[k] = {"value": val, "by": user_id, "at": datetime.now(timezone.utc).isoformat(), "reason": reason}
    v.overrides = ov
    recompute(db, v)
    audit(db, v.shop_id, "quote_version", v.id, "override", {"changes": changes, "reason": reason}, user_id)


def set_inputs(db: Session, v: QuoteVersion, material_code: str | None = None, quantities: list[int] | None = None, refresh_catalog: bool = False):
    part = db.get(Part, db.get(Quote, v.quote_id).part_id)
    cat = shop_catalog(db, v.shop_id)
    if refresh_catalog or material_code:
        new = build_inputs(part, quantities or v.inputs.get("quantities", [1]), cat, material_code or v.inputs.get("material", {}).get("code"))
        new["processes"] = v.inputs.get("processes", new["processes"])
        new["purchased"] = v.inputs.get("purchased", [])
        v.inputs = new
    if quantities:
        v.inputs = {**v.inputs, "quantities": sorted({int(q) for q in quantities if int(q) > 0})}
    recompute(db, v)


def save_as(db: Session, v: QuoteVersion, label: str, user_id: str | None) -> QuoteVersion:
    q = db.get(Quote, v.quote_id)
    n = max(x.number for x in q.versions) + 1
    nv = QuoteVersion(shop_id=v.shop_id, quote_id=q.id, number=n, label=label or f"Variant {n}", parent_version_id=v.id,
                      inputs=dict(v.inputs), overrides=dict(v.overrides), result=dict(v.result), created_by=user_id)
    db.add(nv)
    db.flush()
    audit(db, v.shop_id, "quote_version", nv.id, "save_as", {"from": v.id, "label": nv.label}, user_id)
    return nv


def next_quote_number(db: Session, shop_id: str) -> str:
    n = len(db.scalars(select(QuoteOutput.id).where(QuoteOutput.shop_id == shop_id)).all()) + 1
    return f"Q-{datetime.now(timezone.utc):%y}-{n:04d}"


def finalize(db: Session, rfq: Rfq, lines: list[dict], valid_days: int, notes: str, user_id: str | None) -> QuoteOutput:
    """lines: [{version_id, qty}] -> frozen Part #, Rev, Qty, Price per part."""
    out_lines = []
    for ln in lines:
        v = db.get(QuoteVersion, ln["version_id"])
        if not v or v.shop_id != rfq.shop_id:
            raise ValueError("Unknown quote version")
        qty = int(ln["qty"])
        br = next((b for b in v.result.get("breaks", []) if b["qty"] == qty), None)
        if br is None:
            set_inputs(db, v, quantities=sorted(set(v.inputs.get("quantities", [])) | {qty}))
            br = next(b for b in v.result["breaks"] if b["qty"] == qty)
        if br["unit_price"] is None:
            raise ValueError(f"Part {v.inputs.get('part', {}).get('part_number')} is not priced yet (missing geometry).")
        part = v.inputs.get("part", {})
        out_lines.append({"part_number": part.get("part_number", ""), "revision": part.get("revision", ""), "qty": qty,
                          "unit_price": br["unit_price"], "extended": round(br["unit_price"] * qty, 2), "version_id": v.id,
                          "description": ln.get("description", "")})
        v.status = "final"
    out = QuoteOutput(shop_id=rfq.shop_id, rfq_id=rfq.id, quote_number=next_quote_number(db, rfq.shop_id), lines=out_lines,
                      valid_until=(date.today() + timedelta(days=valid_days)).isoformat(), notes=notes)
    db.add(out)
    db.flush()
    pdf = render_pdf(db.get(Shop, rfq.shop_id), rfq, out)
    out.pdf_key, _ = storage.put(rfq.shop_id, pdf, f"{out.quote_number}.pdf")
    rfq.status = "quoted"
    audit(db, rfq.shop_id, "rfq", rfq.id, "quoted", {"quote_number": out.quote_number, "lines": len(out_lines)}, user_id)
    return out


def render_pdf(shop: Shop, rfq: Rfq, out: QuoteOutput) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch, topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            title=f"Quotation {out.quote_number}")
    st = getSampleStyleSheet()
    cur = shop.currency or "USD"
    money = lambda x: f"{cur} {x:,.2f}"
    els = [Paragraph(f"<b>{shop.name}</b>", st["Title"]), Paragraph(f"Quotation <b>{out.quote_number}</b>", st["Heading2"]),
           Paragraph(f"Date: {date.today():%d %b %Y} &nbsp;&nbsp; Valid until: {out.valid_until}", st["Normal"]),
           Paragraph(f"Customer: {rfq.customer_name or ''} &nbsp;&nbsp; Attn: {rfq.customer_contact or ''}", st["Normal"]),
           Paragraph(f"Your reference: {rfq.customer_rfq_no or rfq.number}", st["Normal"]), Spacer(1, 16)]
    data = [["Part number", "Rev", "Qty", "Price per part", "Extended"]]
    for ln in out.lines:
        data.append([ln["part_number"], ln["revision"] or "-", f"{ln['qty']:,}", money(ln["unit_price"]), money(ln["extended"])])
    t = Table(data, colWidths=[2.3 * inch, 0.6 * inch, 0.8 * inch, 1.4 * inch, 1.4 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14325c")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cfd8")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    els += [t, Spacer(1, 14)]
    if out.notes:
        els.append(Paragraph(out.notes.replace("\n", "<br/>"), st["Normal"]))
    doc.build(els)
    return buf.getvalue()
