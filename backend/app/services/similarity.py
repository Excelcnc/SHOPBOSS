"""Similar-job search: a small numeric feature vector per part, compared with cosine similarity after
z-scoring across the shop's history. Works without pgvector for thousands of jobs; swap in pgvector later."""
from __future__ import annotations

import math

FAMILIES = ["aluminum", "steel", "stainless", "titanium", "copper", "plastic", "nickel", "tool_steel"]
FAMILY_OF = {"AL": "aluminum", "ST": "steel", "SS": "stainless", "TI": "titanium", "BR": "copper", "CU": "copper", "IN": "nickel", "TS": "tool_steel"}
NAMES = ["log_volume", "log_len", "log_wid", "log_hgt", "removal_ratio", "holes", "pockets", "setups", "turned", "tight", "gdt"] + [f"mat_{f}" for f in FAMILIES]


def family_of(code: str | None, text: str = "") -> str:
    if code:
        for pre, fam in FAMILY_OF.items():
            if code.upper().startswith(pre):
                return fam
        if code.upper() in ("POM", "PEEK", "UHMW", "NYLON", "PC"):
            return "plastic"
    t = (text or "").upper()
    for k, fam in [("STAINLESS", "stainless"), ("ALUM", "aluminum"), ("TITAN", "titanium"), ("BRASS", "copper"), ("COPPER", "copper"),
                   ("INCONEL", "nickel"), ("STEEL", "steel"), ("DELRIN", "plastic"), ("ACETAL", "plastic"), ("PEEK", "plastic"), ("NYLON", "plastic")]:
        if k in t:
            return fam
    return ""


def vector_from(size, volume, holes=0, pockets=0, setups=2, turned=False, tight=0, gdt=0, family="") -> list[float]:
    s = sorted([max(float(x), 0.1) for x in (size or [1, 1, 1])], reverse=True) + [0.1, 0.1, 0.1]
    box = s[0] * s[1] * s[2]
    vol = max(float(volume or 0), 0.1)
    return [math.log(vol), math.log(s[0]), math.log(s[1]), math.log(s[2]), 1 - min(1.0, vol / box) if box else 0, math.log1p(holes),
            math.log1p(pockets), float(setups or 2), 1.0 if turned else 0.0, math.log1p(tight), math.log1p(gdt)] + [1.0 if family == f else 0.0 for f in FAMILIES]


def part_vector(cad: dict, drawing: dict, material_code: str | None) -> list[float]:
    feats = cad.get("features", [])
    items = (drawing or {}).get("items", [])
    return vector_from(cad.get("size"), cad.get("volume"), sum(1 for f in feats if f["type"] == "hole"),
                       sum(1 for f in feats if f["type"] in ("pocket", "slot", "open_pocket")), cad.get("setups", 2),
                       bool(cad.get("turned") and cad["turned"].get("ratio", 0) > 0.7),
                       sum(1 for i in items if (i.get("band") or 9) <= 0.05), sum(1 for i in items if i.get("cat") == "gdt"), family_of(material_code))


def rank(target: list[float], candidates: list[tuple[object, list[float]]], k: int = 8) -> list[tuple[object, float]]:
    vecs = [v for _, v in candidates if v and len(v) == len(target)]
    if not vecs:
        return []
    n = len(target)
    mean = [sum(v[i] for v in vecs + [target]) / (len(vecs) + 1) for i in range(n)]
    sd = [max(1e-6, math.sqrt(sum((v[i] - mean[i]) ** 2 for v in vecs + [target]) / (len(vecs) + 1))) for i in range(n)]
    weights = [2.0, 1.5, 1.5, 1.0, 0.8, 1.0, 1.0, 0.8, 1.5, 0.8, 0.6] + [1.2] * len(FAMILIES)
    z = lambda v: [(v[i] - mean[i]) / sd[i] * weights[i] for i in range(n)]
    zt = z(target)
    out = []
    for obj, v in candidates:
        if not v or len(v) != n:
            continue
        zv = z(v)
        num = sum(a * b for a, b in zip(zt, zv))
        den = math.sqrt(sum(a * a for a in zt)) * math.sqrt(sum(b * b for b in zv)) or 1
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(zt, zv)))
        score = 0.5 * (num / den + 1) * math.exp(-dist / (2 * math.sqrt(n)))
        out.append((obj, round(score, 3)))
    out.sort(key=lambda x: -x[1])
    return out[:k]
