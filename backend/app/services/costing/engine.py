"""Deterministic CNC cost engine.

price/part = material + machining + outside processes + purchased components
           + (setup + programming + first article) / quantity
           then contingency + uncertainty, volume discount, margin, rounded UP.

Philosophy: when information is missing or uncertain, choose the more expensive interpretation
and say so in `adjustments`. Every intermediate value is an overridable "line": the estimator can
replace any of them (material price, cycle time, complexity, rates, ...) and the rest recomputes.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .defaults import DEFAULT_SHOP_SETTINGS

MACHINE_RATE_KEY = {"mill3": "milling", "mill4": "milling4", "mill5": "milling5", "lathe": "turning", "millturn": "millturn"}
MACHINE_LABEL = {"mill3": "3-axis mill", "mill4": "4-axis mill", "mill5": "5-axis mill", "lathe": "Lathe", "millturn": "Mill-turn",
                 "lathe+mill3": "Lathe + 3-axis mill"}


def round_up(x: float, step: float) -> float:
    if step <= 0:
        return x
    return round(math.ceil(x / step - 1e-9) * step, 6)


class Calc:
    """Collects overridable lines so the UI can show computed vs. used values."""

    def __init__(self, overrides: dict | None):
        self.ov = overrides or {}
        self.lines: list[dict] = []
        self.adjustments: list[str] = []
        self.warnings: list[str] = []

    def val(self, key: str, computed: Any, label: str, unit: str = "", group: str = "", note: str = "") -> Any:
        o = self.ov.get(key)
        used = computed
        overridden = False
        if o is not None:
            v = o.get("value") if isinstance(o, dict) else o
            if v is not None and v != "":
                used = type(computed)(v) if isinstance(computed, (int, float)) and not isinstance(computed, bool) else v
                overridden = True
        self.lines.append({"key": key, "label": label, "group": group, "unit": unit, "computed": computed, "value": used, "overridden": overridden, "note": note})
        return used


# ------------------------------------------------------------------ drawing facts
def drawing_facts(drawing: dict | None) -> dict:
    items = (drawing or {}).get("items", [])
    bands = [i["band"] for i in items if i.get("band") is not None and i["band"] > 0]
    ras = [i["ra"] for i in items if i.get("ra")]
    meta = (drawing or {}).get("meta", {})
    return {
        "tightest_band": min(bands) if bands else None,
        "tight_count": sum(1 for b in bands if b <= 0.05),
        "very_tight_count": sum(1 for b in bands if b <= 0.025),
        "gdt_count": sum(1 for i in items if i.get("cat") == "gdt"),
        "min_ra": min(ras) if ras else None,
        "thread_count": sum(1 for i in items if i.get("cat") == "thread"),
        "fit_count": sum(1 for i in items if i.get("cat") == "fit"),
        "low_conf": sum(1 for i in items if (i.get("conf") or 1) < 0.6),
        "has_drawing": bool(items) or bool(meta),
        "fai": any("AS9102" in str(i.get("value", "")).upper() or "FIRST ARTICLE" in str(i.get("value", "")).upper() for i in items),
    }


# ------------------------------------------------------------------ complexity
def complexity(geo: dict, dwg: dict, family: str) -> dict:
    f = geo.get("features", [])
    pts: list[tuple[str, float]] = []

    def add(label, v):
        if v > 0:
            pts.append((label, round(v, 2)))

    setups = geo.get("setups") or 2
    add(f"{setups} setups", max(0, setups - 1) * 0.6)
    tb = dwg.get("tightest_band")
    if tb is not None:
        add(f"tightest tolerance band {tb:.3f} mm", 2.5 if tb <= 0.01 else 1.8 if tb <= 0.025 else 1.0 if tb <= 0.05 else 0.4 if tb <= 0.1 else 0)
    add(f"{dwg.get('gdt_count', 0)} GD&T callouts", min(1.5, 0.3 * dwg.get("gdt_count", 0)))
    ra = dwg.get("min_ra")
    if ra is not None:
        add(f"surface finish Ra {ra:g} µm", 1.5 if ra <= 0.4 else 1.0 if ra <= 0.8 else 0.4 if ra <= 1.6 else 0)
    holes = [x for x in f if x["type"] == "hole"]
    deep = sum(1 for h in holes if h.get("ld", 0) > 10)
    med = sum(1 for h in holes if 6 < h.get("ld", 0) <= 10)
    add(f"{deep} very deep holes (L/D>10)", min(2.0, 1.0 * deep))
    add(f"{med} deep holes (L/D 6-10)", min(1.0, 0.4 * med))
    for fl in geo.get("flags", []):
        if fl.get("code") == "deep_pocket":
            add("deep pocket / long-reach tooling", 1.5 if fl["sev"] == "high" else 0.8)
            break
    mw = (geo.get("min_wall") or {}).get("t") if isinstance(geo.get("min_wall"), dict) else geo.get("min_wall")
    if mw is not None:
        add(f"thin wall {mw:.2f} mm", 1.5 if mw < 1.0 else 0.8 if mw < 2.0 else 0)
    mr = geo.get("min_internal_radius")
    if mr is not None:
        add(f"small internal radius R{mr:.2f}", 1.5 if mr < 0.5 else 0.8 if mr < 1.0 else 0)
    add(f"{geo.get('undercut_faces', 0)} undercut faces", min(2.0, 0.5 * geo.get("undercut_faces", 0)))
    add("internal grooves", min(1.5, 0.75 * sum(1 for x in f if x["type"] == "groove")))
    add(f"{geo.get('freeform_faces', 0)} freeform faces", min(2.0, 0.1 * geo.get("freeform_faces", 0)))
    add("angled faces", 0.5 if geo.get("angled_faces") else 0)
    nfeat = len([x for x in f if x["type"] not in ("external_round",)])
    add(f"{nfeat} machined features", min(1.5, nfeat / 20))
    add(f"{dwg.get('thread_count', 0)} threads", min(1.0, 0.15 * dwg.get("thread_count", 0)))
    add("difficult material", {"stainless": 0.8, "titanium": 1.5, "nickel": 2.0, "tool_steel": 1.0}.get(family, 0))
    score = max(1.0, min(10.0, 1.0 + sum(v for _, v in pts)))
    return {"score": round(score, 1), "drivers": sorted(pts, key=lambda x: -x[1])}


# ------------------------------------------------------------------ machine suggestion
def suggest_machine(geo: dict, machines: list[dict]) -> dict:
    turned = geo.get("turned") or {}
    is_turned = (turned.get("ratio") or 0) > 0.7
    mill_feats = [x for x in geo.get("features", []) if x["type"] in ("hole", "slot", "pocket", "open_pocket") and not (is_turned and x.get("axis") == turned.get("axis"))]
    if is_turned:
        kind = "millturn" if mill_feats else "lathe"
        why = f"{round(100*turned['ratio'])}% of the surface is rotational about {turned['axis']}" + (f"; {len(mill_feats)} milled features off-axis" if mill_feats else "")
    elif geo.get("undercut_faces") or geo.get("freeform_faces", 0) > 4 or geo.get("angled_faces", 0) > 2:
        kind, why = "mill5", "angled, freeform or undercut faces"
    elif len({d.lstrip('+-') for d in geo.get("access_dirs", [])}) >= 3 and (geo.get("setups") or 0) > 3:
        kind, why = "mill4", "features on several sides around one axis"
    else:
        kind, why = "mill3", "prismatic part, features from the top/bottom"
    size = sorted(geo.get("size", [0, 0, 0]), reverse=True)
    fits = []
    for m in machines:
        mk = m.get("kind")
        if not m.get("active", True):
            continue
        if kind in ("lathe", "millturn") and mk in ("lathe", "millturn"):
            t = m.get("travel_mm") or [0, 0]
            ok = (turned.get("max_dia") or 0) <= (t[0] if t else 1e9) and (turned.get("length") or 0) <= (t[1] if len(t) > 1 else 1e9)
        elif kind in ("mill3", "mill4", "mill5") and mk in ("mill3", "mill4", "mill5", "millturn") and (mk == "millturn" or int(mk[-1]) >= int(kind[-1])):
            t = sorted(m.get("travel_mm") or [1e9, 1e9, 1e9], reverse=True)
            ok = all(size[i] <= t[i] for i in range(min(3, len(t))))
        else:
            continue
        if ok:
            fits.append(m.get("name"))
    if is_turned and mill_feats and not any(m.get("kind") == "millturn" for m in machines):
        kind_eff = "lathe+mill3"
        why += "; no mill-turn configured, so turning + separate milling setups"
    else:
        kind_eff = kind
    return {"kind": kind_eff, "label": MACHINE_LABEL.get(kind_eff, kind_eff), "why": why, "fits": fits}


# ------------------------------------------------------------------ main estimate
def estimate(inputs: dict, overrides: dict | None = None) -> dict:
    inp = deepcopy(inputs)
    S = {**DEFAULT_SHOP_SETTINGS, **(inp.get("settings") or {})}
    c = Calc(overrides)
    geo = inp.get("geometry") or {}
    dwg = drawing_facts(inp.get("drawing"))
    mat = inp.get("material") or {}
    rates = inp.get("rates") or {}
    qtys = sorted({int(q) for q in (inp.get("quantities") or [1]) if int(q) > 0}) or [1]

    has_geo = bool(geo.get("size")) and min(geo.get("size") or [0]) > 0
    size_ov = (overrides or {}).get("geometry.size_mm")
    if size_ov:
        import re as _re
        dims = [float(x) for x in _re.findall(r"\d*\.?\d+", str(size_ov.get("value") if isinstance(size_ov, dict) else size_ov))][:3]
        if len(dims) == 3:
            geo["size"] = dims
            if not has_geo:
                vol_ov = (overrides or {}).get("geometry.volume_cm3")
                v = float(vol_ov.get("value") if isinstance(vol_ov, dict) else vol_ov) if vol_ov else None
                geo["volume"] = (v * 1000) if v else dims[0] * dims[1] * dims[2] * 0.5
                geo["area"] = 2 * (dims[0] * dims[1] + dims[1] * dims[2] + dims[0] * dims[2]) * 1.5
                c.adjustments.append("Geometry entered manually" + ("" if v else ": part volume assumed 50% of the envelope (more material removal, so more time)") + ".")
            has_geo = True
    c.val("geometry.size_mm", " x ".join(f"{x:g}" for x in geo.get("size", [])) if has_geo else "", "Part envelope (L x W x H)", "mm", "geometry",
          "from 3D model" if not size_ov else "entered by estimator")
    if not has_geo:
        c.warnings.append("No 3D model geometry. Enter the part envelope (L x W x H) to price this part; it stays unpriced until then.")
        geo["size"] = [0, 0, 0]
    if not dwg["has_drawing"]:
        c.adjustments.append("No drawing analysed: tolerances and finish unknown, so extra uncertainty time is included.")
    if not mat.get("code"):
        c.adjustments.append("Material not identified: priced as the most expensive common grade (stainless 316). Confirm and override.")

    # ---- machine & complexity
    mach = suggest_machine(geo, inp.get("machines") or [])
    machine_kind = c.val("machine.kind", mach["kind"], "Suggested machine", group="process", note=mach["why"])
    cx = complexity(geo, dwg, mat.get("family", ""))
    score = c.val("complexity.score", cx["score"], "Complexity score (1-10)", group="complexity")
    cmult = c.val("complexity.multiplier", round(1 + 0.08 * (score - 1), 3), "Complexity time multiplier", "×", group="complexity")

    # ---- stock & material
    size = geo.get("size", [0, 0, 0])
    turned = geo.get("turned") or {}
    if str(machine_kind).startswith(("lathe", "millturn")) and turned.get("max_dia"):
        dia = turned["max_dia"] + 2 * S["turning_allowance_mm"]
        ln = turned.get("length", max(size)) + S["turning_length_allowance_mm"]
        stock_vol_cm3 = math.pi * (dia / 2) ** 2 * ln / 1000
        stock_desc = f"Round bar Ø{math.ceil(dia)} × {math.ceil(ln)} mm"
    else:
        dims = [math.ceil(s + 2 * S["stock_allowance_mm"]) for s in size]
        stock_vol_cm3 = dims[0] * dims[1] * dims[2] / 1000
        stock_desc = " × ".join(str(d) for d in dims) + " mm block"
    part_vol_cm3 = (geo.get("volume") or 0) / 1000
    density = mat.get("density_g_cm3") or 8.0
    stock_kg = c.val("material.stock_kg", round(stock_vol_cm3 * density / 1000 * (1 + S["material_scrap_pct"] / 100), 4), "Stock weight incl. scrap", "kg", "material", stock_desc)
    ppk = c.val("material.price_per_kg", float(mat.get("price_per_kg") or 0), "Material price", "$/kg", "material", mat.get("price_source", ""))
    mat_cost = c.val("material.cost_per_part", round(max(S["min_material_per_part"], stock_kg * ppk), 2), "Material cost per part", "$", "material")
    removed = max(0.0, stock_vol_cm3 - part_vol_cm3)

    # ---- cycle time
    machin = mat.get("machinability") or 0.14
    mrr = S["mrr_rough_cm3_min"] * machin * (1.4 if str(machine_kind).startswith(("lathe", "millturn")) else 1.0)
    rough = removed / max(mrr, 0.1)
    area_dm2 = (geo.get("area") or 0) / 10000
    ra = dwg.get("min_ra")
    finish = area_dm2 * S["finish_min_per_dm2"] / max(machin, 0.05) ** 0.5 * (1.6 if ra is not None and ra <= 0.8 else 1.0)
    feat_min = 0.0
    for x in geo.get("features", []):
        t = x["type"]
        if t == "hole":
            d = max(x.get("dia", 5), 1)
            depth = x.get("depth") or (x.get("ld", 1) * d)
            m = 0.3 + depth / (25 * max(machin, 0.1) ** 0.5) / 10
            if x.get("ld", 0) > 6:
                m *= 2.0  # peck drilling
            if x.get("cbore"):
                m += 0.4
            if x.get("csk"):
                m += 0.2
            feat_min += m
        elif t in ("pocket", "slot", "open_pocket"):
            feat_min += 0.8 + x.get("depth", 0) * 0.05
        elif t == "groove":
            feat_min += 1.5
        elif t == "undercut":
            feat_min += 0.8 * x.get("count", 1)
        elif t == "freeform":
            feat_min += 0.3 * x.get("count", 1)
    feat_min += 0.4 * dwg["thread_count"] + 0.8 * dwg["very_tight_count"] + 0.4 * max(0, dwg["tight_count"] - dwg["very_tight_count"]) + 0.5 * dwg["fit_count"]
    setups = int(c.val("process.setups", int(geo.get("setups") or 2), "Setups", "", "process"))
    handling = setups * S["handling_min_per_setup"] + S["deburr_min_base"] + area_dm2 * 0.3
    inspect_min = S["inspection_min_base"] + S["inspection_min_per_critical"] * (dwg["tight_count"] + dwg["gdt_count"])
    unc_items = dwg["low_conf"] + (0 if dwg["has_drawing"] else 3) + (geo.get("undercut_faces", 0) > 0) + (0 if mat.get("code") else 2)
    unc_pct = min(S["uncertainty_cap_pct"], S["uncertainty_pct_per_item"] * unc_items)
    base_cycle = (rough + finish + feat_min) * cmult + handling
    cycle_computed = round_up(base_cycle * S["time_calibration_factor"] * (1 + unc_pct / 100), 0.1)
    cycle = c.val("time.cycle_min", cycle_computed, "Machining cycle time per part", "min", "time",
                  f"rough {rough:.1f} + finish {finish:.1f} + features {feat_min:.1f}, ×{cmult} complexity, + handling {handling:.1f}, +{unc_pct:.0f}% uncertainty")
    insp = c.val("time.inspection_min", round_up(inspect_min, 0.1), "In-process inspection per part", "min", "time")
    setup_hr = c.val("time.setup_hr", round_up(setups * S["setup_hours_per_setup"] * (1 + 0.05 * (score - 1)), 0.05), "Setup time per lot", "h", "time")
    prog_hr = c.val("time.programming_hr", round_up((S["programming_base_hours"] + S["programming_hours_per_feature"] * len(geo.get("features", [])) + S["programming_hours_per_setup"] * setups) * (1 + 0.1 * (score - 1)) * (1.5 if machine_kind == "mill5" else 1.0), 0.05), "Programming time (one-off)", "h", "time")
    fai_hr = c.val("time.first_article_hr", S["first_article_hours"] + (1.5 if dwg["fai"] else 0) + (0.5 if dwg["gdt_count"] else 0), "First article / setup inspection per lot", "h", "time")

    # ---- rates
    rate_key = MACHINE_RATE_KEY.get(str(machine_kind).split("+")[0], "milling")
    mrate = c.val(f"rate.{rate_key}", float(rates.get(rate_key, rates.get("milling", 95.0))), f"Machine rate ({rate_key})", "$/h", "rates")
    srate = c.val("rate.setup", float(rates.get("setup", 85.0)), "Setup rate", "$/h", "rates")
    prate = c.val("rate.programming", float(rates.get("programming", 95.0)), "Programming rate", "$/h", "rates")
    irate = c.val("rate.inspection", float(rates.get("inspection", 90.0)), "Inspection rate", "$/h", "rates")

    # ---- outside processes & purchased
    procs = []
    weight_kg = part_vol_cm3 * density / 1000
    for p in inp.get("processes") or []:
        basis, price = p.get("basis", "per_part"), float(p.get("price", 0))
        per_part = price * (weight_kg if basis == "per_kg" else area_dm2 if basis == "per_dm2" else 1 if basis == "per_part" else 0)
        key = "process." + p["name"]
        per_part = c.val(key + ".per_part", round(per_part * (1 + p.get("markup_pct", 15) / 100), 2), p["name"] + " per part", "$", "outside", p.get("source", ""))
        lot = c.val(key + ".lot_charge", round(float(p.get("lot_charge", 0)) * (1 + p.get("markup_pct", 15) / 100), 2), p["name"] + " lot charge", "$", "outside")
        procs.append({"name": p["name"], "per_part": per_part, "lot": lot, "unpriced": p.get("unpriced", False)})
        if p.get("unpriced"):
            c.warnings.append(f"Outside process '{p['name']}' is not in your supplier list: priced at a conservative placeholder. Enter the real price.")
    purch = []
    for b in inp.get("purchased") or []:
        cost = c.val("purchased." + b["name"], float(b.get("unit_cost", 0)), b["name"] + " (purchased, each)", "$", "purchased")
        purch.append({"name": b["name"], "qty_per_part": b.get("qty_per_part", 1), "unit_cost": cost})
        if not cost:
            c.warnings.append(f"Purchased component '{b['name']}' has no cost yet.")

    margin = c.val("pricing.margin_pct", float(S["margin_pct"]), "Margin", "%", "pricing")
    cont = c.val("pricing.contingency_pct", float(S["contingency_pct"]), "Contingency", "%", "pricing")
    if unc_pct:
        c.adjustments.append(f"+{unc_pct:.0f}% cycle time for {unc_items} uncertain item(s) (low-confidence drawing values, missing inputs or undercuts).")
    if geo.get("undercut_faces"):
        c.adjustments.append("Undercut faces priced with extra time; confirm tooling or 5-axis access.")

    # ---- per quantity
    tiers = sorted(S.get("volume_tiers", []), key=lambda t: t["min_qty"])
    breaks = []
    for q in qtys:
        disc = 0.0
        for t in tiers:
            if q >= t["min_qty"]:
                disc = t["discount_pct"]
        machining = cycle / 60 * mrate
        inspection = insp / 60 * irate
        one_off = setup_hr * srate + prog_hr * prate + fai_hr * irate
        outside = sum(p["per_part"] + p["lot"] / q for p in procs)
        purchased = sum(p["unit_cost"] * p["qty_per_part"] for p in purch)
        labour = machining + inspection + one_off / q
        labour_disc = labour * (1 - disc / 100)
        subtotal = mat_cost + labour_disc + outside + purchased
        with_cont = subtotal * (1 + cont / 100)
        price = with_cont * (1 + margin / 100)
        price = max(price, S["min_order_charge"] / q)
        unit = round_up(price, S["price_rounding"] if price < 100 else 1.0)
        unit = c.val(f"price.unit.{q}", round(unit, 2) if has_geo else 0.0, f"Unit price at qty {q}", "$", "price")
        if not has_geo and not (overrides or {}).get(f"price.unit.{q}"):
            unit = None
        breaks.append({"qty": q, "material": round(mat_cost, 2), "machining": round(machining, 2), "inspection": round(inspection, 2),
                       "setup_programming_per_part": round(one_off / q, 2), "outside": round(outside, 2), "purchased": round(purchased, 2),
                       "volume_discount_pct": disc, "subtotal": round(subtotal, 2), "contingency": round(subtotal * cont / 100, 2),
                       "unit_price": unit, "extended": round(unit * q, 2) if unit is not None else None, "hours_per_part": round((cycle + insp) / 60, 3)})

    return {
        "machine": {**mach, "kind": machine_kind, "label": MACHINE_LABEL.get(machine_kind, machine_kind)},
        "complexity": {**cx, "score": score, "multiplier": cmult},
        "stock": {"description": stock_desc, "volume_cm3": round(stock_vol_cm3, 2), "removed_cm3": round(removed, 2), "kg": stock_kg},
        "complete": has_geo, "drawing_facts": dwg, "uncertainty_pct": unc_pct, "processes": procs, "purchased": purch,
        "breaks": breaks, "lines": c.lines, "adjustments": c.adjustments, "warnings": c.warnings,
    }
