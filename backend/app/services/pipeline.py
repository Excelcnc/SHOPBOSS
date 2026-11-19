"""RFQ processing pipeline: intake -> analysis -> parts -> initial quotes."""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import Attachment, AuditLog, Email, Part, Quote, QuoteVersion, Rfq
from .ai.provider import get_provider
from .cad.analyze import analyze_step
from .costing.detect import detect_material, detect_processes
from .costing.engine import estimate
from .drawing.extract import analyze_pdf, image_to_pdf, render_page_png
from .email.parse import ParsedEmail, extract_fields
from .shopdata import shop_catalog
from .similarity import part_vector

log = logging.getLogger(__name__)
MODEL_EXT = {"step", "stp", "iges", "igs", "stl", "sldprt", "sldasm", "x_t", "x_b", "ipt", "iam", "prt", "catpart", "catproduct"}
DRAWING_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "dxf", "dwg", "slddrw"}


def classify(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in MODEL_EXT:
        return "model", ext
    if ext in DRAWING_EXT:
        return "drawing", ext
    if ext in ("eml", "msg"):
        return "email", ext
    if ext == "zip":
        return "archive", ext
    return "other", ext


def audit(db: Session, shop_id: str, entity: str, entity_id: str, action: str, detail=None, user_id=None):
    db.add(AuditLog(shop_id=shop_id, user_id=user_id, entity=entity, entity_id=entity_id, action=action, detail=detail or {}))


def next_rfq_number(db: Session, shop_id: str) -> str:
    y = datetime.now(timezone.utc).year
    n = db.scalar(select(Rfq.id).where(Rfq.shop_id == shop_id).order_by(Rfq.created_at.desc()).limit(1))
    count = len(db.scalars(select(Rfq.id).where(Rfq.shop_id == shop_id)).all())
    return f"RFQ-{y}-{count + 1:04d}"


def add_files(db: Session, rfq: Rfq, files: list[tuple[str, bytes]]):
    import io
    import zipfile
    for name, data in files:
        kind, ext = classify(name)
        if kind == "archive":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    inner = [(i.filename.split("/")[-1], z.read(i)) for i in z.infolist() if not i.is_dir() and i.file_size < 200 * 2**20 and not i.filename.startswith("__MACOSX")]
                add_files(db, rfq, inner)
            except zipfile.BadZipFile:
                pass
            continue
        key, sha = storage.put(rfq.shop_id, data, name)
        if any(a.sha256 == sha for a in rfq.attachments):
            continue
        rfq.attachments.append(Attachment(shop_id=rfq.shop_id, filename=name, kind=kind, ext=ext, size=len(data), sha256=sha, storage_key=key))


def create_rfq_from_email(db: Session, shop_id: str, parsed: ParsedEmail, source: str, mailbox: str = "") -> Rfq | None:
    if db.scalar(select(Email).where(Email.shop_id == shop_id, Email.message_id == parsed.message_id)):
        return None  # duplicate delivery
    em = Email(shop_id=shop_id, source=source, mailbox=mailbox, message_id=parsed.message_id, sender_name=parsed.sender_name, sender_email=parsed.sender_email,
               subject=parsed.subject, body=parsed.body, received_at=parsed.received_at)
    db.add(em)
    db.flush()
    fields = extract_fields(parsed.subject, parsed.body, parsed.sender_name, parsed.sender_email, [a[0] for a in parsed.attachments])
    rfq = Rfq(shop_id=shop_id, number=next_rfq_number(db, shop_id), email_id=em.id, extracted=fields,
              customer_name=str(fields.get("customer_name", {}).get("value", "")), customer_contact=parsed.sender_name,
              customer_email=parsed.sender_email, customer_rfq_no=str(fields.get("customer_rfq_no", {}).get("value", "")),
              due_date=str(fields.get("quote_due", {}).get("value", "")) or None)
    db.add(rfq)
    db.flush()
    add_files(db, rfq, parsed.attachments)
    audit(db, shop_id, "rfq", rfq.id, "created", {"source": source, "mailbox": mailbox, "subject": parsed.subject, "attachments": len(parsed.attachments)})
    return rfq


# ------------------------------------------------------------------ analysis
def _norm_pn(s: str) -> str:
    s = re.sub(r"(?i)[_\-\s.]*rev(ision)?[_\-\s.]*[a-z0-9]{1,2}$", "", s or "")
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def analyze_drawing(att: Attachment, use_ai: bool, ai) -> dict:
    data = storage.get(att.storage_key)
    if att.ext in ("dwg", "slddrw", "tif", "tiff"):
        return {"error": {"dwg": "DWG needs a server-side converter (ODA File Converter or LibreDWG), not configured. Ask for PDF or DXF.",
                          "slddrw": "SolidWorks drawing: ask for a PDF export."}.get(att.ext, "Unsupported drawing format."), "items": [], "meta": {}}
    if att.ext == "dxf":
        from .drawing.dxf import analyze_dxf
        return analyze_dxf(data)
    pdf = data if att.ext == "pdf" else image_to_pdf(data)
    res = analyze_pdf(pdf)
    res["filename"] = att.filename
    if res["has_text"]:
        from .drawing.bom import extract_bom
        res["bom"] = extract_bom(pdf)
    if use_ai and ai.available():
        try:
            pngs = [render_page_png(pdf, p) for p in range(1, min(2, res["pages"]) + 1)]
            out = ai.read_drawing(pngs, res.get("text", ""), att.filename)
            if out:
                merge_ai_drawing(res, out)
        except Exception as e:  # never fail the pipeline on AI problems
            log.warning("AI drawing read failed for %s: %s", att.filename, e)
            res["ai_error"] = str(e)[:300]
    if not res["has_text"] and res.get("source") != "ai-vision":
        res.setdefault("unreadable", []).append({"description": "Scanned drawing with no text layer: configure AI or enter key values manually.", "bbox": None})
    return res


def merge_ai_drawing(res: dict, ai: dict):
    """AI items are kept with their confidence; values also found verbatim in the text layer are marked verified."""
    norm = lambda s: re.sub(r"[^A-Z0-9.]", "", str(s or "").upper())
    lines = res.get("text", "")
    nl = norm(lines)

    def bb(b):
        if not b or len(b) != 4:
            return None
        s = 1000.0 if max(b) > 1.001 else 1.0
        x0, y0, x1, y1 = [max(0.0, min(1.0, v / s)) for v in b]
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    ai_items = []
    for i, it in enumerate(ai.get("items", [])):
        v = it.get("value") or ""
        verified = bool(res["has_text"] and len(norm(v)) >= 2 and norm(v) in nl)
        ai_items.append({"id": f"A{i+1}", "cat": it["cat"], "label": it["label"], "value": v, "tol": it.get("tol"), "qty": it.get("qty"),
                         "critical": it.get("critical", False), "conf": max(it.get("confidence", 0), 0.95) if verified else it.get("confidence", 0),
                         "page": 1, "bbox": bb(it.get("bbox")), "src": "ai+text" if verified else "ai-vision"})
    from .drawing.extract import tol_band
    for it in ai_items:
        it["band"] = tol_band(it.get("tol"))
        if it["band"] is not None and it["band"] <= 0.05:
            it["critical"] = True
    covered = lambda t: any(norm(a["value"]) and (norm(a["value"]) in norm(t["value"]) or norm(t["value"]) in norm(a["value"])) for a in ai_items)
    # text-layer items stay authoritative; AI items add what the text layer missed
    res["items"] = res["items"] + [a for a in ai_items if not any(norm(t["value"]) == norm(a["value"]) for t in res["items"])] if res["has_text"] else ai_items
    for k, m in (ai.get("meta") or {}).items():
        if m and m.get("value") and k not in res["meta"]:
            res["meta"][k] = {"value": m["value"], "conf": m.get("confidence", 0), "bbox": bb(m.get("bbox")), "page": 1, "src": "ai-vision"}
    res["unreadable"] = [{"description": u["description"], "bbox": bb(u.get("bbox"))} for u in ai.get("unreadable", [])]
    res["notes"] = ai.get("notes", [])[:40]
    res["source"] = "ai+text" if res["has_text"] else "ai-vision"


def match_score(model_name: str, model_size: list, drawing: dict, drawing_file: str) -> tuple[float, list[str]]:
    why = []
    s = 0.0
    dn = _norm_pn((drawing.get("meta", {}).get("drawing_number") or {}).get("value", ""))
    df = _norm_pn(drawing_file.rsplit(".", 1)[0])
    mn = _norm_pn(model_name)
    for cand, label in ((dn, "drawing number"), (df, "drawing file name")):
        if cand and mn and (cand == mn or cand in mn or mn in cand):
            s += 0.6 if label == "drawing number" else 0.4
            why.append(f"part number matches {label}")
            break
    dims = []
    for it in drawing.get("items", []):
        if it.get("cat") in ("dimension", "diameter", "fit"):
            m = re.search(r"\d*\.?\d+", it.get("value", ""))
            if m:
                dims.append(float(m.group(0)))
    hits = sum(1 for v in model_size if any(abs(v - d) <= max(0.05, d * 0.002) for d in dims))
    if hits:
        s += 0.15 * hits
        why.append(f"{hits} overall dimension(s) found on the drawing")
    return min(1.0, s), why


def process_rfq(db: Session, rfq_id: str):
    rfq = db.get(Rfq, rfq_id)
    if not rfq:
        return
    rfq.analysis_status = "running"
    db.commit()
    try:
        _process(db, rfq)
        rfq.analysis_status = "done"
        rfq.analysis_error = None
        if rfq.status == "new":
            rfq.status = "estimating"
    except Exception as e:  # keep the RFQ usable; show the error
        log.exception("analysis failed")
        db.rollback()
        rfq = db.get(Rfq, rfq_id)
        rfq.analysis_status = "error"
        rfq.analysis_error = str(e)[:2000]
    db.commit()


def _process(db: Session, rfq: Rfq):
    ai = get_provider()
    itar = bool(rfq.extracted.get("itar", {}).get("value"))
    use_ai = ai.available() and not itar
    em = db.get(Email, rfq.email_id) if rfq.email_id else None
    if use_ai and em:
        try:
            out = ai.extract_email(em.subject, em.body, f"{em.sender_name} <{em.sender_email}>", [a.filename for a in rfq.attachments])
            if out:
                merged = dict(rfq.extracted)
                for k, v in out["fields"].items():
                    if v.get("value") in (None, ""):
                        continue
                    cur = merged.get(k)
                    if cur and cur.get("source") == "manual":
                        continue
                    if not cur or v["confidence"] >= cur.get("confidence", 0):
                        merged[k] = {"value": v["value"], "confidence": v["confidence"], "evidence": v["evidence"], "source": "ai-email", "ambiguous": v["ambiguous"]}
                merged["summary"] = {"value": out.get("summary", ""), "confidence": 1, "source": "ai-email"}
                merged["ai_parts"] = {"value": out.get("parts", []), "confidence": 1, "source": "ai-email"}
                rfq.extracted = merged
                if not rfq.customer_name and merged.get("customer_name"):
                    rfq.customer_name = str(merged["customer_name"]["value"])
        except Exception as e:
            log.warning("AI email extraction failed: %s", e)

    # drawings
    drawings = {}
    for att in rfq.attachments:
        if att.kind == "drawing":
            drawings[att.id] = analyze_drawing(att, use_ai, ai)
    # models -> machined parts
    model_parts = []  # (att, part_analysis, assembly_info)
    assemblies = []
    for att in rfq.attachments:
        if att.kind != "model":
            continue
        if att.ext in ("step", "stp"):
            res = analyze_step(storage.local_path(att.storage_key))
            if res["assembly"]:
                assemblies.append((att, res))
            for p in res["parts"]:
                model_parts.append((att, p, res["assembly"]))
        else:
            model_parts.append((att, {"name": att.filename.rsplit(".", 1)[0], "error": f".{att.ext} files can't be analysed. Ask the customer for STEP (AP214/AP242).", "size": [0, 0, 0], "features": [], "flags": []}, False))

    # remove previous parts/quotes for a clean re-run (quotes with saved versions are kept by part number below)
    for p in list(rfq.parts):
        for q in db.scalars(select(Quote).where(Quote.part_id == p.id)).all():
            db.delete(q)
        db.delete(p)
    db.flush()

    # pair drawings with model parts (greedy by score)
    asm_drawings = {did: d for did, d in drawings.items() if d.get("bom")}
    pairs = []
    for i, (att, p, _) in enumerate(model_parts):
        for did, d in drawings.items():
            if did in asm_drawings:
                continue
            dfile = next(a.filename for a in rfq.attachments if a.id == did)
            sc, why = match_score(p["name"], p.get("size", []), d, dfile)
            if sc > 0:
                pairs.append((sc, i, did, why))
    pairs.sort(reverse=True)
    used_m, used_d, matched = set(), set(), {}
    for sc, i, did, why in pairs:
        if i in used_m or did in used_d or sc < 0.3:
            continue
        used_m.add(i)
        used_d.add(did)
        matched[i] = (did, sc, why)
    # a single model + single drawing with no evidence: pair, but flag low confidence
    single_pair = len(model_parts) == 1 and len(drawings) == 1 and not asm_drawings
    if single_pair and not matched:
        matched[0] = (next(iter(drawings)), 0.2, ["only model and only drawing in the RFQ (no matching evidence)"])

    cat = shop_catalog(db, rfq.shop_id)
    email_qty = rfq.extracted.get("quantities", {}).get("value") or [1]
    if isinstance(email_qty, str):
        email_qty = [int(x) for x in re.findall(r"\d+", email_qty.replace(",", ""))] or [1]
    email_mat = str(rfq.extracted.get("material", {}).get("value") or "")
    email_proc = str(rfq.extracted.get("special_processes", {}).get("value") or "")

    asm_part = {}
    bom_of: dict[str, list] = {}  # assembly part id -> parts-list rows from its drawing
    free_bom = dict(asm_drawings)
    for att, res in assemblies:
        name = res["tree"]["name"]
        did = next((k for k, d in free_bom.items() if _norm_pn((d.get("meta", {}).get("drawing_number") or {}).get("value", "")) in (_norm_pn(name), "") or len(assemblies) == 1), None)
        d = free_bom.pop(did, None) if did else None
        meta = (d or {}).get("meta", {})
        ap = Part(shop_id=rfq.shop_id, rfq_id=rfq.id, part_number=name, kind="assembly", model_attachment_id=att.id, drawing_attachment_id=did,
                  revision=(meta.get("revision") or {}).get("value", ""), description=(meta.get("description") or {}).get("value", ""),
                  cad={"tree": res["tree"], "header": res["header"]}, drawing=d or {}, warnings=[])
        db.add(ap)
        db.flush()
        asm_part[att.id] = ap
        if d:
            bom_of[ap.id] = [dict(r, _used=False) for r in d["bom"]]
    for did, d in free_bom.items():  # assembly drawing without a STEP assembly
        meta = d.get("meta", {})
        att = next(a for a in rfq.attachments if a.id == did)
        ap = Part(shop_id=rfq.shop_id, rfq_id=rfq.id, part_number=(meta.get("drawing_number") or {}).get("value") or att.filename.rsplit(".", 1)[0], kind="assembly",
                  revision=(meta.get("revision") or {}).get("value", ""), description=(meta.get("description") or {}).get("value", ""),
                  drawing_attachment_id=did, drawing=d, warnings=["Assembly drawing without a 3D assembly: parts come from the drawing parts list."])
        db.add(ap)
        db.flush()
        bom_of[ap.id] = [dict(r, _used=False) for r in d["bom"]]

    def bom_row(parent_id, name):
        n = _norm_pn(re.sub(r"[-_ ]\d+$", "", name))
        for r in bom_of.get(parent_id, []):
            pn = _norm_pn(r.get("part_number", ""))
            if pn and n and (pn == n or pn in n or n in pn) and not r["_used"]:
                return r
        return None

    for i, (att, p, in_asm) in enumerate(model_parts):
        did, sc, why = matched.get(i, (None, 0, []))
        d = drawings.get(did) if did else None
        meta = (d or {}).get("meta", {})
        pn = (meta.get("drawing_number") or {}).get("value") or re.sub(r"(?i)[_\-\s.]*rev[_\-\s.]*[a-z0-9]{1,2}$", "", p["name"])
        rev = (meta.get("revision") or {}).get("value") or (re.search(r"(?i)rev[_\-\s.]?([a-z0-9]{1,2})$", p["name"]) or [None, ""])[1].upper()
        purchased = bool(p.get("purchased_guess"))
        row = bom_row(asm_part[att.id].id, p["name"]) if in_asm else None
        bom_warn = []
        if row:
            row["_used"] = True
            purchased = bool(row["purchased"])  # the drawing parts list governs make/buy
            if row.get("qty") is not None and row["qty"] != p.get("qty_per_assembly", 1):
                bom_warn.append(f"Quantity conflict: drawing parts list says {row['qty']}, 3D model has {p.get('qty_per_assembly', 1)}. The drawing governs; confirm with the customer.")
            if row.get("qty") is not None:
                p["qty_per_assembly"] = row["qty"]
            if row.get("part_number"):
                pn = row["part_number"] if purchased or not d else pn
        elif in_asm and asm_part[att.id].id in bom_of:
            bom_warn.append("In the 3D model but not on the drawing parts list. Confirm whether it is supplied.")
        part = Part(shop_id=rfq.shop_id, rfq_id=rfq.id, part_number=pn, revision=rev or "",
                    description=(meta.get("description") or {}).get("value", ""), kind="purchased" if purchased else "machined",
                    parent_part_id=asm_part[att.id].id if in_asm else None, qty_per_parent=p.get("qty_per_assembly", 1),
                    model_attachment_id=att.id, drawing_attachment_id=did,
                    match={"score": round(sc, 2), "why": why, "drawing": did}, cad={k: v for k, v in p.items() if k != "mesh"},
                    drawing=d or {}, warnings=[])
        part.warnings += bom_warn
        if row:
            part.description = part.description or row.get("description", "")
            part.match = {**part.match, "bom_item": row.get("item"), "bom_source": "drawing parts list"}
        if p.get("error"):
            part.warnings.append(p["error"])
        if purchased:
            part.purchased = {"reason": (f"drawing parts list: {row['purchased_reason']}" if row else p.get("purchased_reason", "")),
                              "vendor": (row or {}).get("vendor") or "", "description": (row or {}).get("description", ""), "unit_cost": 0.0}
        # material
        texts = [((meta.get("material") or {}).get("value", ""), "drawing title block"), ((d or {}).get("text", ""), "drawing notes"),
                 ((row or {}).get("material", ""), "drawing parts list"), (email_mat, "email")]
        m = detect_material(texts, cat["materials"]) if not purchased else None
        if purchased:
            pass
        elif m:
            part.material_code = m["code"]
            part.material_source = m
            if m.get("conflicts"):
                part.warnings.append(f"Material conflict: {m['code']} from {m['origin']} vs " + ", ".join(f"{c['code']} ({c['origin']})" for c in m["conflicts"]))
        else:
            part.warnings.append("Material not found on drawing or email: priced as stainless 316 until confirmed.")
        part.processes = [] if purchased else detect_processes([((d or {}).get("text", ""), "drawing"), (email_proc, "email")], cat["processes"])
        if d and d.get("error"):
            part.warnings.append(d["error"])
        if did is None and not purchased and drawings:
            part.warnings.append("No drawing matched to this model. Pair it manually.")
        if did and sc < 0.5:
            part.warnings.append("Model/drawing pairing is uncertain. Check it.")
        # revision check
        mrev = (re.search(r"(?i)rev[_\-\s.]?([a-z0-9]{1,2})$", p["name"]) or [None, None])[1]
        if mrev and rev and mrev.upper() != rev.upper():
            part.warnings.append(f"Revision conflict: model file is Rev {mrev.upper()}, drawing is Rev {rev}. The drawing governs; confirm with the customer.")
        db.add(part)
        db.flush()
        if mesh := p.get("mesh"):
            import json
            key, _ = storage.put(rfq.shop_id, json.dumps(mesh).encode(), f"mesh_{part.id}.json")
            part.cad = {**part.cad, "mesh_key": key}
        part.vector = part_vector(part.cad, part.drawing, part.material_code)
        if not purchased:
            qtys = sorted({max(1, q * (part.qty_per_parent or 1)) for q in email_qty})
            create_quote(db, rfq, part, qtys, cat)
    # drawings that matched nothing become drawing-only parts (geometry entered manually)
    for did, d in drawings.items():
        if did in used_d or did in asm_drawings or single_pair:
            continue
        meta = d.get("meta", {})
        att = next(a for a in rfq.attachments if a.id == did)
        dn = (meta.get("drawing_number") or {}).get("value") or att.filename.rsplit(".", 1)[0]
        parent, prow = None, None
        for pid in bom_of:
            prow = bom_row(pid, dn)
            if prow:
                parent = pid
                prow["_used"] = True
                break
        part = Part(parent_part_id=parent, qty_per_parent=(prow or {}).get("qty") or 1,shop_id=rfq.shop_id, rfq_id=rfq.id, part_number=(meta.get("drawing_number") or {}).get("value") or att.filename.rsplit(".", 1)[0],
                    revision=(meta.get("revision") or {}).get("value", ""), description=(meta.get("description") or {}).get("value", ""),
                    drawing_attachment_id=did, drawing=d, warnings=["No 3D model: size and features come from the drawing only. Enter stock size and cycle time."])
        texts = [((meta.get("material") or {}).get("value", ""), "drawing title block"), (d.get("text", ""), "drawing notes"), (email_mat, "email")]
        m = detect_material(texts, cat["materials"])
        if m:
            part.material_code, part.material_source = m["code"], m
        part.processes = detect_processes([(d.get("text", ""), "drawing"), (email_proc, "email")], cat["processes"])
        db.add(part)
        db.flush()
        create_quote(db, rfq, part, sorted({max(1, q * (part.qty_per_parent or 1)) for q in email_qty}), cat)
    # parts-list rows with no model and no drawing (hardware, labels, or machined parts not supplied)
    for pid, rows in bom_of.items():
        for r in rows:
            if r["_used"]:
                continue
            r["_used"] = True
            part = Part(shop_id=rfq.shop_id, rfq_id=rfq.id, part_number=r.get("part_number") or r.get("description", "Item " + str(r.get("item"))),
                        description=r.get("description", ""), kind="purchased" if r["purchased"] else "machined", parent_part_id=pid,
                        qty_per_parent=r.get("qty") or 1, match={"bom_item": r.get("item"), "bom_source": "drawing parts list"}, warnings=[])
            if r["purchased"]:
                part.purchased = {"reason": f"drawing parts list: {r['purchased_reason']}", "vendor": r.get("vendor") or "", "description": r.get("description", ""), "unit_cost": 0.0}
                part.warnings.append("On the drawing parts list only (not in the 3D model). Enter its cost.")
            else:
                part.warnings.append("Machined item on the parts list with no model or drawing supplied. Request it, or enter the envelope to price it.")
                m = detect_material([(r.get("material", ""), "drawing parts list")], cat["materials"])
                if m:
                    part.material_code, part.material_source = m["code"], m
            db.add(part)
            db.flush()
            if not r["purchased"]:
                create_quote(db, rfq, part, sorted({max(1, q * (part.qty_per_parent or 1)) for q in email_qty}), cat)
    audit(db, rfq.shop_id, "rfq", rfq.id, "analyzed", {"parts": len(model_parts), "drawings": len(drawings), "ai": use_ai})


# ------------------------------------------------------------------ quoting
def build_inputs(part: Part, quantities: list[int], cat: dict, material_code: str | None = None) -> dict:
    code = material_code or part.material_code
    mat = next((m for m in cat["materials"] if m["code"] == code), None)
    if mat is None:
        mat = {**next(m for m in cat["materials"] if m["code"] == "SS316"), "code": None, "price_source": "unknown material: stainless 316 assumed"}
    purchased = []
    return {
        "geometry": part.cad if part.cad.get("size") else {"size": [0, 0, 0], "features": []},
        "drawing": {"items": part.drawing.get("items", []), "meta": part.drawing.get("meta", {})},
        "material": mat, "quantities": quantities, "rates": cat["rates"], "machines": cat["machines"],
        "processes": part.processes, "purchased": purchased, "settings": cat["settings"],
        "part": {"part_number": part.part_number, "revision": part.revision},
    }


def create_quote(db: Session, rfq: Rfq, part: Part, quantities: list[int], cat: dict, user_id=None) -> Quote:
    q = Quote(shop_id=rfq.shop_id, rfq_id=rfq.id, part_id=part.id)
    db.add(q)
    db.flush()
    inputs = build_inputs(part, quantities, cat)
    v = QuoteVersion(shop_id=rfq.shop_id, quote_id=q.id, number=1, label="Original", inputs=inputs, overrides={},
                     result=estimate(inputs, {}), created_by=user_id)
    db.add(v)
    return q
