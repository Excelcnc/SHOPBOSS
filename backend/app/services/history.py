"""Historical jobs: CSV import (JobBOSS² exports or any spreadsheet), similar-job search and calibration."""
from __future__ import annotations

import csv
import io
import re
import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HistoricalJob, Part, QuoteOutput, QuoteVersion
from .similarity import family_of, rank, vector_from

# Column names seen in JobBOSS² exports and typical spreadsheets. Override with an explicit mapping.
CANDIDATES = {
    "part_number": ["part_number", "part", "partno", "part_no", "part number", "item"],
    "revision": ["rev", "revision", "part_rev"],
    "customer": ["customer", "customer_name", "cust"],
    "quantity": ["quantity", "order_qty", "qty", "make_quantity", "quote_qty"],
    "unit_price": ["unit_price", "price", "unitprice", "quoted_price"],
    "est_hours": ["est_total_hrs", "est_hours", "estimated_hours", "est_hrs", "total_est_hrs"],
    "actual_hours": ["act_total_hrs", "actual_hours", "act_hours", "actual_hrs", "total_act_hrs"],
    "material": ["material", "material_desc", "material_description"],
    "job_date": ["order_date", "date", "quote_date", "job_date", "sched_start"],
    "outcome": ["status", "outcome", "result"],
    "external_ref": ["job", "job_number", "quote", "quote_number", "rfq"],
    "length": ["length", "len_mm", "x"], "width": ["width", "y"], "height": ["height", "thickness", "z"],
}


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def import_csv(db: Session, shop_id: str, data: bytes, mapping: dict | None = None) -> dict:
    text = data.decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return {"imported": 0, "mapping": {}}
    cols = {_key(c): c for c in rows[0].keys()}
    m = dict(mapping or {})
    for field, cands in CANDIDATES.items():
        if field not in m:
            hit = next((cols[_key(c)] for c in cands if _key(c) in cols), None)
            if hit:
                m[field] = hit
    n = 0
    for r in rows:
        g = lambda f: (r.get(m[f]) if f in m else None)
        pn = (g("part_number") or "").strip()
        if not pn:
            continue
        dims = [_num(g(k)) for k in ("length", "width", "height")]
        size = dims if all(dims) else None
        st = (g("outcome") or "").lower()
        outcome = "won" if re.search(r"won|closed|complete|shipped|active|released", st) else "lost" if re.search(r"lost|declin|no bid|cancel", st) else ""
        job = HistoricalJob(shop_id=shop_id, source="import", external_ref=(g("external_ref") or "")[:120], part_number=pn[:120], revision=(g("revision") or "")[:20],
                            customer=(g("customer") or "")[:300], material=(g("material") or "")[:120], quantity=int(_num(g("quantity")) or 1),
                            unit_price=_num(g("unit_price")), est_hours=_num(g("est_hours")), actual_hours=_num(g("actual_hours")),
                            outcome=outcome, job_date=(g("job_date") or "")[:10], attributes={"size": size} if size else {})
        if size:
            job.vector = vector_from(size, size[0] * size[1] * size[2] * 0.5, family=family_of(None, job.material))
        db.add(job)
        n += 1
    return {"imported": n, "mapping": m, "columns": list(rows[0].keys())}


def similar(db: Session, part: Part, k: int = 8) -> list[dict]:
    target = part.vector
    if not target:
        return []
    hist = db.scalars(select(HistoricalJob).where(HistoricalJob.shop_id == part.shop_id)).all()
    past_parts = db.scalars(select(Part).where(Part.shop_id == part.shop_id, Part.id != part.id, Part.kind == "machined")).all()
    cands = [(("job", h), h.vector) for h in hist if h.vector] + [(("part", p), p.vector) for p in past_parts if p.vector and p.rfq_id != part.rfq_id]
    out = []
    for (kind, obj), score in rank(target, cands, k):
        if kind == "job":
            out.append({"kind": "history", "id": obj.id, "score": score, "part_number": obj.part_number, "revision": obj.revision, "customer": obj.customer,
                        "material": obj.material, "quantity": obj.quantity, "unit_price": obj.unit_price, "est_hours": obj.est_hours,
                        "actual_hours": obj.actual_hours, "outcome": obj.outcome, "date": obj.job_date, "size": (obj.attributes or {}).get("size")})
        else:
            final = db.scalars(select(QuoteOutput).where(QuoteOutput.rfq_id == obj.rfq_id)).first()
            price = None
            if final:
                ln = next((l for l in final.lines if l["part_number"] == obj.part_number), None)
                price = ln and ln["unit_price"]
            out.append({"kind": "quote", "id": obj.id, "rfq_id": obj.rfq_id, "score": score, "part_number": obj.part_number, "revision": obj.revision,
                        "material": obj.material_code, "unit_price": price, "size": obj.cad.get("size"), "outcome": "",
                        "date": obj.created_at.date().isoformat()})
    return out


def calibration(db: Session, shop_id: str) -> dict:
    """Compare engine hours with actual hours where both exist (jobs linked to analysed parts)."""
    rows = []
    for h in db.scalars(select(HistoricalJob).where(HistoricalJob.shop_id == shop_id)).all():
        eng = (h.attributes or {}).get("engine_hours_per_part")
        if eng and h.actual_hours and h.quantity:
            rows.append({"part_number": h.part_number, "engine": eng, "actual_per_part": h.actual_hours / h.quantity, "ratio": (h.actual_hours / h.quantity) / eng})
    jobs_with_actuals = sum(1 for h in db.scalars(select(HistoricalJob).where(HistoricalJob.shop_id == shop_id)) if h.actual_hours)
    if not rows:
        return {"samples": 0, "jobs_with_actuals": jobs_with_actuals, "suggested_factor": None,
                "message": "Attach the STEP/PDF of past jobs that have actual hours to compare the engine against reality."}
    ratios = [r["ratio"] for r in rows]
    # conservative: use the 75th percentile so most jobs are covered
    q75 = sorted(ratios)[int(0.75 * (len(ratios) - 1))]
    return {"samples": len(rows), "jobs_with_actuals": jobs_with_actuals, "median_ratio": round(statistics.median(ratios), 3),
            "p75_ratio": round(q75, 3), "suggested_factor": round(max(q75, statistics.median(ratios)), 3), "rows": rows[:200]}
