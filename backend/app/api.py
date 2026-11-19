"""REST API for the estimator UI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .auth import current_user, require_admin
from .config import get_settings
from .db import get_db
from .jobs import enqueue_analysis
from .models import (Attachment, AuditLog, HistoricalJob, Machine, Mailbox, Material, OutsideProcess, Part, Quote, QuoteOutput, QuoteVersion,
                     RateType, Rfq, Shop, User)
from .services import history as hist
from .services import quoting
from .services.drawing.extract import image_to_pdf, render_page_png
from .services.email.parse import ParsedEmail, extract_fields, parse_email_file
from .services.pipeline import add_files, audit, create_rfq_from_email
from .services.shopdata import shop_catalog

api = APIRouter(prefix="/api")


def own(obj, user: User):
    if obj is None or getattr(obj, "shop_id", None) != user.shop_id:
        raise HTTPException(404, "Not found")
    return obj


# ------------------------------------------------------------------ me & shop
@api.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    shop = db.get(Shop, user.shop_id)
    s = get_settings()
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role, "shop": {"id": shop.id, "name": shop.name, "currency": shop.currency},
            "integrations": {"mailboxes": [m.address for m in db.scalars(select(Mailbox).where(Mailbox.shop_id == user.shop_id, Mailbox.active.is_(True)))],
                             "ai": bool(s.anthropic_api_key and s.ai_enabled), "auth": s.auth_mode}}


@api.get("/shop")
def get_shop(user: User = Depends(current_user), db: Session = Depends(get_db)):
    shop = db.get(Shop, user.shop_id)
    cat = shop_catalog(db, user.shop_id)
    return {"name": shop.name, "currency": shop.currency, "settings": cat["settings"],
            "rates": [{"id": r.id, "key": r.key, "name": r.name, "rate_per_hour": r.rate_per_hour} for r in db.scalars(select(RateType).where(RateType.shop_id == user.shop_id).order_by(RateType.key))],
            "machines": [{"id": m.id, "name": m.name, "kind": m.kind, "rate_key": m.rate_key, "travel_mm": m.travel_mm, "capabilities": m.capabilities, "active": m.active}
                         for m in db.scalars(select(Machine).where(Machine.shop_id == user.shop_id))],
            "processes": [{"id": p.id, "name": p.name, "keywords": p.keywords, "supplier": p.supplier, "basis": p.basis, "price": p.price, "lot_charge": p.lot_charge,
                           "lead_days": p.lead_days, "markup_pct": p.markup_pct} for p in db.scalars(select(OutsideProcess).where(OutsideProcess.shop_id == user.shop_id))],
            "materials": sorted(cat["materials"], key=lambda m: m["name"])}


class ShopUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    settings: Optional[dict] = None


@api.put("/shop")
def update_shop(body: ShopUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    shop = db.get(Shop, user.shop_id)
    if body.name:
        shop.name = body.name
    if body.currency:
        shop.currency = body.currency.upper()[:3]
    if body.settings is not None:
        shop.settings = {**(shop.settings or {}), **body.settings}
    audit(db, shop.id, "shop", shop.id, "settings", body.model_dump(exclude_none=True), user.id)
    db.commit()
    return {"ok": True}


@api.put("/shop/material-prices/{code}")
def set_material_price(code: str, body: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Shop material price override (and optional custom density/machinability)."""
    row = db.scalar(select(Material).where(Material.shop_id == user.shop_id, Material.code == code))
    ref = db.scalar(select(Material).where(Material.shop_id.is_(None), Material.code == code))
    if not row:
        base = ref or Material(code=code, name=body.get("name", code), aliases=body.get("aliases", []), family=body.get("family", "steel"),
                               density_g_cm3=float(body.get("density_g_cm3", 7.85)), machinability=float(body.get("machinability", 0.3)), reference_price_per_kg=0)
        row = Material(shop_id=user.shop_id, code=code, name=body.get("name", base.name), aliases=body.get("aliases", base.aliases), family=base.family,
                       density_g_cm3=base.density_g_cm3, machinability=base.machinability, reference_price_per_kg=base.reference_price_per_kg,
                       reference_price_date=base.reference_price_date)
        db.add(row)
    for k in ("density_g_cm3", "machinability"):
        if k in body:
            setattr(row, k, float(body[k]))
    if "price_per_kg" in body:
        row.shop_price_per_kg = float(body["price_per_kg"]) if body["price_per_kg"] not in (None, "") else None
        row.shop_price_date = datetime.now(timezone.utc).date().isoformat()
    audit(db, user.shop_id, "material", code, "price", body, user.id)
    db.commit()
    return {"ok": True}


CRUD = {"rates": (RateType, ["key", "name", "rate_per_hour"]), "machines": (Machine, ["name", "kind", "rate_key", "travel_mm", "capabilities", "active"]),
        "processes": (OutsideProcess, ["name", "keywords", "supplier", "basis", "price", "lot_charge", "lead_days", "markup_pct"])}


@api.post("/shop/{kind}")
def crud_create(kind: str, body: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    model, fields = CRUD.get(kind, (None, None))
    if not model:
        raise HTTPException(404)
    obj = model(shop_id=user.shop_id, **{k: body[k] for k in fields if k in body})
    db.add(obj)
    audit(db, user.shop_id, kind, "new", "create", body, user.id)
    db.commit()
    return {"id": obj.id}


@api.put("/shop/{kind}/{oid}")
def crud_update(kind: str, oid: str, body: dict, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    model, fields = CRUD.get(kind, (None, None))
    if not model:
        raise HTTPException(404)
    obj = own(db.get(model, oid), user)
    for k in fields:
        if k in body:
            setattr(obj, k, body[k])
    audit(db, user.shop_id, kind, oid, "update", body, user.id)
    db.commit()
    return {"ok": True}


@api.delete("/shop/{kind}/{oid}")
def crud_delete(kind: str, oid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    model, _ = CRUD.get(kind, (None, None))
    if not model:
        raise HTTPException(404)
    db.delete(own(db.get(model, oid), user))
    audit(db, user.shop_id, kind, oid, "delete", {}, user.id)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ RFQs
def rfq_summary(db: Session, r: Rfq) -> dict:
    parts = r.parts
    priced = []
    for p in parts:
        q = db.scalar(select(Quote).where(Quote.part_id == p.id))
        if q and q.versions:
            b = q.versions[0].result.get("breaks", [])
            if b and b[0].get("unit_price") is not None:
                priced.append(p.id)
    return {"id": r.id, "number": r.number, "status": r.status, "customer_name": r.customer_name, "customer_contact": r.customer_contact,
            "customer_email": r.customer_email, "customer_rfq_no": r.customer_rfq_no, "due_date": r.due_date, "created_at": r.created_at.isoformat(),
            "analysis_status": r.analysis_status, "analysis_error": r.analysis_error, "assigned_to": r.assigned_to,
            "subject": (r.extracted.get("_subject") or {}).get("value") if isinstance(r.extracted.get("_subject"), dict) else None,
            "parts": sum(1 for p in parts if p.kind == "machined"), "priced": len(priced),
            "warnings": sum(len(p.warnings or []) for p in parts), "attachments": len(r.attachments)}


@api.get("/rfqs")
def list_rfqs(status: Optional[str] = None, q: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Rfq).where(Rfq.shop_id == user.shop_id).order_by(Rfq.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Rfq.status.in_(status.split(",")))
    rows = db.scalars(stmt).all()
    out = []
    from .models import Email
    for r in rows:
        s = rfq_summary(db, r)
        em = db.get(Email, r.email_id) if r.email_id else None
        s["subject"] = em.subject if em else r.extracted.get("subject", {}).get("value", "")
        if q and q.lower() not in json.dumps(s).lower() + " ".join(p.part_number.lower() for p in r.parts):
            continue
        out.append(s)
    return out


@api.post("/rfqs")
async def create_rfq(files: list[UploadFile] = File(default=[]), customer_name: str = Form(""), customer_email: str = Form(""),
                     subject: str = Form(""), notes: str = Form(""), quantities: str = Form(""),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Upload .eml/.msg emails (each becomes an RFQ) and/or loose drawings + models (one RFQ)."""
    mx = get_settings().max_attachment_mb * 2**20
    loose, created = [], []
    for f in files:
        data = await f.read()
        if len(data) > mx:
            raise HTTPException(413, f"{f.filename} is larger than {get_settings().max_attachment_mb} MB")
        if f.filename.lower().endswith((".eml", ".msg")):
            parsed = parse_email_file(f.filename, data)
            r = create_rfq_from_email(db, user.shop_id, parsed, "upload")
            if r:
                created.append(r)
        else:
            loose.append((f.filename, data))
    if loose or not created:
        body = notes + (f"\nQuantity: {quantities}" if quantities else "")
        parsed = ParsedEmail(f"<manual-{datetime.now(timezone.utc).timestamp()}@{user.id}>", "", customer_email, subject or "Manual RFQ",
                             body, datetime.now(timezone.utc), loose)
        r = create_rfq_from_email(db, user.shop_id, parsed, "upload")
        if customer_name:
            r.customer_name = customer_name
            r.extracted = {**r.extracted, "customer_name": {"value": customer_name, "confidence": 1, "source": "manual", "evidence": "entered"}}
        created.append(r)
    db.commit()
    for r in created:
        enqueue_analysis(r.id)
    return [{"id": r.id, "number": r.number} for r in created]


@api.get("/rfqs/{rid}")
def get_rfq(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .models import Email
    r = own(db.get(Rfq, rid), user)
    em = db.get(Email, r.email_id) if r.email_id else None
    parts = []
    for p in r.parts:
        q = db.scalar(select(Quote).where(Quote.part_id == p.id))
        parts.append({**part_dict(p), "quote_id": q.id if q else None,
                      "versions": [{"id": v.id, "number": v.number, "label": v.label, "status": v.status, "breaks": [{"qty": b["qty"], "unit_price": b["unit_price"], "lead_weeks": b.get("lead_weeks")} for b in v.result.get("breaks", [])]} for v in (q.versions if q else [])]})
    outputs = db.scalars(select(QuoteOutput).where(QuoteOutput.rfq_id == r.id).order_by(QuoteOutput.created_at.desc())).all()
    return {**rfq_summary(db, r), "extracted": r.extracted,
            "email": {"subject": em.subject, "from": f"{em.sender_name} <{em.sender_email}>", "received_at": em.received_at.isoformat(), "body": em.body, "source": em.source, "mailbox": em.mailbox} if em else None,
            "attachments": [{"id": a.id, "filename": a.filename, "kind": a.kind, "ext": a.ext, "size": a.size} for a in r.attachments],
            "parts": parts, "outputs": [{"id": o.id, "quote_number": o.quote_number, "lines": o.lines, "valid_until": o.valid_until, "created_at": o.created_at.isoformat()} for o in outputs],
            "activity": [{"action": a.action, "detail": a.detail, "at": a.at.isoformat(), "user_id": a.user_id} for a in db.scalars(select(AuditLog).where(AuditLog.entity_id == r.id).order_by(AuditLog.at.desc()).limit(50))]}


def part_dict(p: Part) -> dict:
    return {"id": p.id, "part_number": p.part_number, "revision": p.revision, "description": p.description, "kind": p.kind, "parent_part_id": p.parent_part_id,
            "qty_per_parent": p.qty_per_parent, "model_attachment_id": p.model_attachment_id, "drawing_attachment_id": p.drawing_attachment_id, "match": p.match,
            "cad": {k: v for k, v in (p.cad or {}).items() if k not in ("mesh_key",)}, "has_mesh": bool((p.cad or {}).get("mesh_key")),
            "drawing": p.drawing, "material_code": p.material_code, "material_source": p.material_source, "processes": p.processes,
            "warnings": p.warnings, "purchased": p.purchased}


class RfqPatch(BaseModel):
    status: Optional[str] = None
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    customer_email: Optional[str] = None
    customer_rfq_no: Optional[str] = None
    due_date: Optional[str] = None
    assigned_to: Optional[str] = None
    fields: Optional[dict] = None  # extracted field edits {key: value}


@api.patch("/rfqs/{rid}")
def patch_rfq(rid: str, body: RfqPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = own(db.get(Rfq, rid), user)
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        if k == "fields":
            ex = dict(r.extracted)
            for fk, fv in v.items():
                ex[fk] = {"value": fv, "confidence": 1.0, "source": "manual", "evidence": f"edited by {user.name}"}
            r.extracted = ex
        else:
            setattr(r, k, v)
    audit(db, r.shop_id, "rfq", r.id, "update", data, user.id)
    db.commit()
    return {"ok": True}


@api.post("/rfqs/{rid}/files")
async def add_rfq_files(rid: str, files: list[UploadFile] = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = own(db.get(Rfq, rid), user)
    add_files(db, r, [(f.filename, await f.read()) for f in files])
    audit(db, r.shop_id, "rfq", r.id, "files_added", {"files": [f.filename for f in files]}, user.id)
    db.commit()
    enqueue_analysis(r.id)
    return {"ok": True}


@api.post("/rfqs/{rid}/analyze")
def reanalyze(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = own(db.get(Rfq, rid), user)
    r.analysis_status = "pending"
    db.commit()
    enqueue_analysis(r.id)
    return {"ok": True}


@api.delete("/rfqs/{rid}")
def delete_rfq(rid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = own(db.get(Rfq, rid), user)
    for p in r.parts:
        for q in db.scalars(select(Quote).where(Quote.part_id == p.id)):
            db.delete(q)
    for o in db.scalars(select(QuoteOutput).where(QuoteOutput.rfq_id == r.id)):
        db.delete(o)
    db.flush()
    db.delete(r)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ files
@api.get("/attachments/{aid}/file")
def get_file(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own(db.get(Attachment, aid), user)
    mt = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(a.ext, "application/octet-stream")
    return Response(storage.get(a.storage_key), media_type=mt, headers={"Content-Disposition": f'inline; filename="{a.filename}"'})


@api.get("/attachments/{aid}/page/{page}.png")
def get_page(aid: str, page: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = own(db.get(Attachment, aid), user)
    data = storage.get(a.storage_key)
    if a.ext == "pdf":
        png = render_page_png(data, page, 2400)
    elif a.ext in ("png", "jpg", "jpeg"):
        png = render_page_png(image_to_pdf(data), 1, 2400)
    else:
        raise HTTPException(415, "No preview for this format")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@api.get("/parts/{pid}/mesh")
def get_mesh(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own(db.get(Part, pid), user)
    key = (p.cad or {}).get("mesh_key")
    if not key:
        raise HTTPException(404, "No 3D model for this part")
    return Response(storage.get(key), media_type="application/json", headers={"Cache-Control": "private, max-age=3600"})


class PartPatch(BaseModel):
    part_number: Optional[str] = None
    revision: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    material_code: Optional[str] = None
    drawing_attachment_id: Optional[str] = None
    purchased: Optional[dict] = None
    processes: Optional[list] = None


@api.patch("/parts/{pid}")
def patch_part(pid: str, body: PartPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own(db.get(Part, pid), user)
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(p, k, v)
    if "material_code" in data:
        p.material_source = {"code": data["material_code"], "origin": "estimator", "confidence": 1.0}
    q = db.scalar(select(Quote).where(Quote.part_id == p.id))
    # propagate identity/material/process edits into draft versions
    if q:
        for v in q.versions:
            if v.status == "draft":
                v.inputs = {**v.inputs, "part": {"part_number": p.part_number, "revision": p.revision}}
                if "processes" in data:
                    v.inputs = {**v.inputs, "processes": data["processes"]}
                if "material_code" in data:
                    quoting.set_inputs(db, v, material_code=data["material_code"])
                else:
                    quoting.recompute(db, v)
    audit(db, p.shop_id, "part", p.id, "update", data, user.id)
    db.commit()
    return part_dict(p)


# ------------------------------------------------------------------ quote versions
def version_dict(v: QuoteVersion) -> dict:
    return {"id": v.id, "quote_id": v.quote_id, "number": v.number, "label": v.label, "parent_version_id": v.parent_version_id, "status": v.status,
            "inputs": {k: v.inputs.get(k) for k in ("material", "quantities", "processes", "purchased", "part")}, "overrides": v.overrides, "result": v.result,
            "created_at": v.created_at.isoformat(), "updated_at": v.updated_at.isoformat()}


@api.get("/quotes/{qid}")
def get_quote(qid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = own(db.get(Quote, qid), user)
    return {"id": q.id, "part_id": q.part_id, "rfq_id": q.rfq_id, "versions": [version_dict(v) for v in q.versions]}


class VersionPatch(BaseModel):
    overrides: Optional[dict[str, Any]] = None  # key -> value (null clears)
    reason: str = ""
    quantities: Optional[list[int]] = None
    material_code: Optional[str] = None
    processes: Optional[list] = None
    purchased: Optional[list] = None
    label: Optional[str] = None
    refresh_catalog: bool = False


@api.patch("/versions/{vid}")
def patch_version(vid: str, body: VersionPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own(db.get(QuoteVersion, vid), user)
    if v.status != "draft":
        raise HTTPException(409, "This version is final. Use Save As to make a new variant.")
    if body.label:
        v.label = body.label
    if body.processes is not None:
        v.inputs = {**v.inputs, "processes": body.processes}
    if body.purchased is not None:
        v.inputs = {**v.inputs, "purchased": body.purchased}
    if body.material_code or body.quantities or body.refresh_catalog:
        quoting.set_inputs(db, v, material_code=body.material_code, quantities=body.quantities, refresh_catalog=body.refresh_catalog)
    if body.overrides:
        quoting.set_overrides(db, v, body.overrides, user.id, body.reason)
    else:
        quoting.recompute(db, v)
    db.commit()
    return version_dict(v)


@api.post("/versions/{vid}/save-as")
def save_as(vid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = own(db.get(QuoteVersion, vid), user)
    nv = quoting.save_as(db, v, body.get("label", ""), user.id)
    db.commit()
    return version_dict(nv)


@api.get("/parts/{pid}/similar")
def similar(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return hist.similar(db, own(db.get(Part, pid), user))


# ------------------------------------------------------------------ final quote
class FinalizeBody(BaseModel):
    lines: list[dict]
    valid_days: int = 30
    notes: str = ""


@api.post("/rfqs/{rid}/finalize")
def finalize(rid: str, body: FinalizeBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = own(db.get(Rfq, rid), user)
    try:
        out = quoting.finalize(db, r, body.lines, body.valid_days, body.notes, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"id": out.id, "quote_number": out.quote_number, "lines": out.lines, "valid_until": out.valid_until}


@api.get("/outputs/{oid}/pdf")
def output_pdf(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = own(db.get(QuoteOutput, oid), user)
    return Response(storage.get(o.pdf_key), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{o.quote_number}.pdf"'})


@api.post("/rfqs/{rid}/outcome")
def outcome(rid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Record won/lost; quoted parts are added to history for future similar-job searches."""
    r = own(db.get(Rfq, rid), user)
    res = body.get("outcome")
    if res not in ("won", "lost"):
        raise HTTPException(400, "outcome must be won or lost")
    r.status = res
    out = db.scalars(select(QuoteOutput).where(QuoteOutput.rfq_id == r.id).order_by(QuoteOutput.created_at.desc())).first()
    for ln in (out.lines if out else []):
        v = db.get(QuoteVersion, ln["version_id"])
        part = db.get(Part, db.get(Quote, v.quote_id).part_id) if v else None
        br = next((b for b in (v.result.get("breaks", []) if v else []) if b["qty"] == ln["qty"]), {})
        db.add(HistoricalJob(shop_id=r.shop_id, source="quote", external_ref=out.quote_number, part_number=ln["part_number"], revision=ln["revision"],
                             customer=r.customer_name, material=(part.material_code if part else "") or "", quantity=ln["qty"], unit_price=ln["unit_price"],
                             est_hours=br.get("hours_per_part", 0) * ln["qty"] if br else None, outcome=res, job_date=datetime.now(timezone.utc).date().isoformat(),
                             attributes={"size": part.cad.get("size") if part else None, "reason": body.get("reason", "")}, vector=part.vector if part else []))
    audit(db, r.shop_id, "rfq", r.id, res, body, user.id)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ history
@api.post("/history/import")
async def import_history(file: UploadFile = File(...), mapping: str = Form(""), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    res = hist.import_csv(db, user.shop_id, await file.read(), json.loads(mapping) if mapping else None)
    audit(db, user.shop_id, "history", "import", "import", {"rows": res["imported"], "file": file.filename}, user.id)
    db.commit()
    return res


@api.get("/history")
def list_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(HistoricalJob).where(HistoricalJob.shop_id == user.shop_id).order_by(HistoricalJob.created_at.desc()).limit(500)).all()
    return [{"id": h.id, "source": h.source, "ref": h.external_ref, "part_number": h.part_number, "revision": h.revision, "customer": h.customer, "material": h.material,
             "quantity": h.quantity, "unit_price": h.unit_price, "est_hours": h.est_hours, "actual_hours": h.actual_hours, "outcome": h.outcome, "date": h.job_date} for h in rows]


@api.get("/history/calibration")
def calibration(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return hist.calibration(db, user.shop_id)


# ------------------------------------------------------------------ intake webhooks
@api.post("/intake/graph/notify")
async def graph_notify(request: Request, db: Session = Depends(get_db)):
    """Microsoft Graph change notifications for any connected mailbox. The validation handshake echoes
    validationToken; each notification is matched to its mailbox by subscription id and client state."""
    token = request.query_params.get("validationToken")
    if token:
        return Response(token, media_type="text/plain")
    payload = await request.json()
    from .models import Mailbox
    from .services.email import mailboxes as mbx
    graph_boxes = db.scalars(select(Mailbox).where(Mailbox.kind.in_(mbx.MS_KINDS), Mailbox.active.is_(True))).all()
    for n in payload.get("value", []):
        mb = next((m for m in graph_boxes if (m.state or {}).get("subscription", {}).get("id") == n.get("subscriptionId")), None)
        if not mb or n.get("clientState") != mb.state["subscription"].get("client_state"):
            continue  # not ours
        mid = (n.get("resourceData") or {}).get("id")
        if mid:
            try:
                mbx.ingest_graph_message(db, mb, mid)
                db.commit()
            except Exception:
                db.rollback()  # the poller's delta sync picks it up
    return Response(status_code=202)


# ------------------------------------------------------------------ connected mailboxes
class MailboxBody(BaseModel):
    kind: Optional[str] = None          # graph | imap
    address: Optional[str] = None
    label: Optional[str] = None
    folder: Optional[str] = None
    filter_rfqs: Optional[bool] = None
    active: Optional[bool] = None
    backfill_days: Optional[int] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    imap_password: Optional[str] = None  # write-only


def mailbox_dict(m) -> dict:
    sub = (m.state or {}).get("subscription")
    return {"id": m.id, "kind": m.kind, "address": m.address, "label": m.label, "folder": m.folder, "filter_rfqs": m.filter_rfqs, "active": m.active,
            "backfill_days": m.backfill_days, "imap_host": m.imap_host, "imap_port": m.imap_port, "imap_user": m.imap_user, "has_password": bool(m.imap_password_enc), "connected_as": m.connected_as,
            "last_sync_at": m.last_sync_at.isoformat() if m.last_sync_at else None, "last_error": m.last_error, "imported": m.imported, "skipped": m.skipped,
            "instant": bool(sub), "synced_once": bool((m.state or {}).get("delta_link") or "last_uid" in (m.state or {}))}


@api.get("/mailboxes")
def list_mailboxes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .models import Mailbox
    from .services.email.graph import graph_allowed_for
    rows = db.scalars(select(Mailbox).where(Mailbox.shop_id == user.shop_id).order_by(Mailbox.created_at)).all()
    s = get_settings()
    from .services.email import msconnect
    return {"graph_available": graph_allowed_for(user), "ms_connect": msconnect.configured(), "webhook": bool(s.webhook_url), "mailboxes": [mailbox_dict(m) for m in rows]}


@api.post("/mailboxes")
def add_mailbox(body: MailboxBody, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    import re as _re
    from .crypto import encrypt
    from .models import Mailbox
    from .services.email.graph import graph_address_allowed, graph_allowed_for, graph_configured
    from .services.email.imap import guess_host
    addr = (body.address or "").strip().lower()
    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr):
        raise HTTPException(400, "Enter a valid email address.")
    kind = body.kind or "graph"
    if kind not in ("graph", "imap"):
        raise HTTPException(400, "kind must be graph or imap")
    if kind == "graph" and not graph_configured():
        raise HTTPException(400, "Microsoft 365 mailboxes need the mailbox app configured on the server (GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET).")
    if kind == "graph" and not (graph_allowed_for(user) and graph_address_allowed(addr)):
        raise HTTPException(403, "Direct Microsoft 365 connection isn't available for this mailbox. Connect it with IMAP, or forward RFQs to a mailbox you can connect.")
    if kind == "imap" and not body.imap_password:
        raise HTTPException(400, "Enter the app password for this mailbox.")
    folder = (body.folder or "inbox").strip() or "inbox"
    if db.scalar(select(Mailbox).where(Mailbox.shop_id == user.shop_id, Mailbox.kind == kind, Mailbox.address == addr, Mailbox.folder == folder)):
        raise HTTPException(409, "That mailbox and folder are already connected.")
    m = Mailbox(shop_id=user.shop_id, kind=kind, address=addr, label=body.label or "", folder=folder,
                filter_rfqs=True if body.filter_rfqs is None else body.filter_rfqs, active=True, backfill_days=max(0, min(90, body.backfill_days or 0)))
    if kind == "imap":
        m.imap_host = (body.imap_host or guess_host(addr)).strip()
        m.imap_port = body.imap_port or 993
        m.imap_user = (body.imap_user or addr).strip()
        m.imap_password_enc = encrypt(body.imap_password)
    db.add(m)
    audit(db, user.shop_id, "mailbox", addr, "connect", {"kind": kind, "folder": folder}, user.id)
    db.commit()
    from .services.email import mailboxes as mbx
    res = mbx.test(m)
    return {**mailbox_dict(m), "test": res}


class MsConnectBody(BaseModel):
    address: str = ""
    folder: str = "inbox"
    label: str = ""
    filter_rfqs: bool = True
    backfill_days: int = 0
    reconnect_id: str = ""


@api.post("/mailboxes/microsoft/start")
def ms_connect_start(body: MsConnectBody, response: Response, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Step 1 of Connect with Microsoft: returns the Microsoft sign-in address for the browser to open."""
    from .services.email import msconnect
    if body.reconnect_id:
        from .models import Mailbox
        own(db.get(Mailbox, body.reconnect_id), user)
    try:
        url, nonce = msconnect.start(user, body.address, body.folder, body.label, body.filter_rfqs, body.backfill_days, body.reconnect_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    response.set_cookie(msconnect.COOKIE, nonce, max_age=900, httponly=True, samesite="lax", path="/api/oauth",
                        secure=get_settings().app_url.startswith("https://"))
    return {"url": url}


@api.get("/oauth/microsoft/callback", include_in_schema=False)
def ms_connect_callback(request: Request, db: Session = Depends(get_db)):
    """Step 2: Microsoft sends the browser back here. Saves the mailbox, then returns to Shop settings."""
    from urllib.parse import urlencode
    from fastapi.responses import RedirectResponse
    from .services.email import mailboxes as mbx, msconnect
    q = request.query_params
    back = lambda **kw: RedirectResponse("/settings?" + urlencode({"tab": "email", **kw}), status_code=303)
    if q.get("error"):
        resp = back(ms_error=(q.get("error_description") or q["error"]).split(" Trace ID")[0][:300])
    else:
        try:
            mb = msconnect.finish(db, q.get("code", ""), q.get("state", ""), request.cookies.get(msconnect.COOKIE))
            try:
                mbx.ensure_subscription(db, mb)
            except Exception:
                pass  # falls back to 5-minute checks
            resp = back(ms_connected=mb.address)
        except RuntimeError as e:
            db.rollback()
            resp = back(ms_error=str(e)[:300])
    resp.delete_cookie(msconnect.COOKIE, path="/api/oauth")
    return resp


@api.put("/mailboxes/{mid}")
def update_mailbox(mid: str, body: MailboxBody, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .crypto import encrypt
    from .models import Mailbox
    m = own(db.get(Mailbox, mid), user)
    data = body.model_dump(exclude_none=True)
    for k in ("label", "filter_rfqs", "active", "backfill_days", "imap_host", "imap_port", "imap_user"):
        if k in data:
            setattr(m, k, data[k])
    if "folder" in data and data["folder"] != m.folder:
        m.folder = data["folder"].strip() or "inbox"
        m.state = {}  # new folder: start a fresh position (and subscription)
    if data.get("imap_password"):
        m.imap_password_enc = encrypt(data["imap_password"])
    audit(db, user.shop_id, "mailbox", m.address, "update", {k: v for k, v in data.items() if k != "imap_password"}, user.id)
    db.commit()
    return mailbox_dict(m)


@api.delete("/mailboxes/{mid}")
def delete_mailbox(mid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .models import Mailbox
    from .services.email import mailboxes as mbx
    m = own(db.get(Mailbox, mid), user)
    audit(db, user.shop_id, "mailbox", m.address, "disconnect", {}, user.id)
    mbx.remove(db, m)
    return {"ok": True}


@api.post("/mailboxes/{mid}/test")
def test_mailbox(mid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .models import Mailbox
    from .services.email import mailboxes as mbx
    return mbx.test(own(db.get(Mailbox, mid), user))


@api.post("/mailboxes/{mid}/sync")
def sync_mailbox(mid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .models import Mailbox
    from .services.email import mailboxes as mbx
    m = own(db.get(Mailbox, mid), user)
    n = mbx.sync(db, m)
    m = db.get(type(m), mid)
    return {"imported": n, **mailbox_dict(m)}
