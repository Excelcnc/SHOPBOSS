"""Material and outside-process detection from drawing notes, title block and email text."""
from __future__ import annotations

import re

KNOWN_PROCESS_WORDS = ["PLAT", "ANODI", "COAT", "OXIDE", "PASSIVAT", "HEAT TREAT", "HRC", "NITRID", "BLAST", "PAINT", "CHROME", "CADMIUM",
                       "NDT", "MAGNETIC PARTICLE", "PENETRANT", "X-RAY", "NADCAP", "LASER MARK", "ENGRAV"]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def detect_material(sources: list[tuple[str, str]], materials: list[dict]) -> dict | None:
    """sources: [(text, origin)] in priority order, e.g. drawing title block first, then email.
    Returns {code, name, confidence, origin, evidence, conflicts:[...]} or None."""
    hits = []
    for text, origin in sources:
        if not text:
            continue
        up = " " + text.upper().replace("ALUMINIUM", "ALUMINUM") + " "
        for m in materials:
            for alias in [m["code"], m["name"].upper()] + [a.upper() for a in m.get("aliases", [])]:
                a = alias.upper()
                if len(_norm(a)) < 2:
                    continue
                if re.search(r"(?<![A-Z0-9])" + re.escape(a) + (r"(?![A-Z0-9])" if len(_norm(a)) <= 4 else r"(?![0-9])"), up):
                    hits.append({"code": m["code"], "name": m["name"], "origin": origin, "alias": a, "len": len(a),
                                 "evidence": text.strip()[:160]})
    if not hits:
        return None
    # best = longest alias in the highest-priority source
    order = {o: i for i, (_, o) in enumerate(sources)}
    hits.sort(key=lambda h: (order.get(h["origin"], 99), -h["len"]))
    best = hits[0]
    conflicts = sorted({(h["code"], h["origin"]) for h in hits if h["code"] != best["code"]})
    conf = 0.95 if best["origin"].startswith("drawing") else 0.8
    if conflicts:
        conf -= 0.25
    return {"code": best["code"], "name": best["name"], "confidence": round(conf, 2), "origin": best["origin"], "evidence": best["evidence"],
            "conflicts": [{"code": c, "origin": o} for c, o in conflicts]}


def detect_processes(sources: list[tuple[str, str]], catalog: list[dict]) -> list[dict]:
    found: dict[str, dict] = {}
    full = " ".join(t for t, _ in sources if t).upper()
    for text, origin in sources:
        if not text:
            continue
        up = text.upper()
        for p in catalog:
            for kw in p.get("keywords", []):
                if kw.upper() in up and p["name"] not in found:
                    found[p["name"]] = {**p, "source": f"{origin}: '{kw}'", "unpriced": False}
    # process words we recognise but the shop has no supplier entry for -> conservative placeholder
    covered = " ".join(k.upper() for p in found.values() for k in p.get("keywords", []))
    for w in KNOWN_PROCESS_WORDS:
        if w in full and w not in covered and not any(w in k.upper() for p in catalog for k in p.get("keywords", [])):
            m = re.search(r"[^.\n;]*" + re.escape(w) + r"[^.\n;]*", full)
            name = f"Unlisted process: {m.group(0).strip()[:60] if m else w}"
            found[name] = {"name": name, "basis": "per_lot", "price": 0.0, "lot_charge": 250.0, "markup_pct": 0.0,
                           "source": "text", "unpriced": True}
    # avoid double counting anodize + hard anodize
    if "Hard anodize Type III" in found and "Anodize Type II (clear/color)" in found and "TYPE II " not in full.replace("TYPE III", ""):
        found.pop("Anodize Type II (clear/color)")
    return list(found.values())
