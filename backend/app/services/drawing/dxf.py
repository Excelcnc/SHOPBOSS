"""DXF drawings: extract TEXT/MTEXT/DIMENSION strings with positions and run the same callout extraction."""
from __future__ import annotations

import io

from .extract import Line, extract, group_lines


def _clean(s: str) -> str:
    import re
    s = re.sub(r"\\P", " ", s or "")
    s = re.sub(r"\\[A-Za-z][^;]*;", "", s).replace("{", "").replace("}", "")
    return s.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%p", "±").replace("%%P", "±").replace("%%d", "°").strip()


def analyze_dxf(data: bytes) -> dict:
    import ezdxf
    try:
        doc = ezdxf.read(io.StringIO(data.decode("utf-8", "replace")))
    except Exception as e:
        return {"error": f"DXF could not be read: {e}", "items": [], "meta": {}}
    msp = doc.modelspace()
    raw = []
    for e in msp:
        t = e.dxftype()
        if t in ("TEXT", "MTEXT", "DIMENSION"):
            try:
                txt = e.plain_text() if t == "MTEXT" else (e.dxf.text if t == "TEXT" else (e.dxf.get("text") or ""))
                p = e.dxf.insert if t != "DIMENSION" else e.dxf.get("text_midpoint", e.dxf.defpoint)
                h = (e.dxf.get("height", 2.5) if t == "TEXT" else e.dxf.get("char_height", 2.5) if t == "MTEXT" else 2.5) or 2.5
            except Exception:
                continue
            txt = _clean(txt)
            if txt and txt != "<>":
                raw.append((txt, p.x, p.y, h))
    if not raw:
        return {"meta": {}, "items": [], "has_text": False, "pages": 1, "source": "none", "text": "",
                "unreadable": [{"description": "DXF has no text entities.", "bbox": None}]}
    try:
        ext = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
        x0, y0, x1, y1 = ext[0][0], ext[0][1], ext[1][0], ext[1][1]
        assert x1 > x0 and y1 > y0
    except Exception:
        xs = [r[1] for r in raw]; ys = [r[2] for r in raw]
        x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    W, H = x1 - x0, y1 - y0
    spans = [{"s": t, "bbox": [(x - x0) / W, 1 - (y + h - y0) / H, (x + len(t) * h * 0.6 - x0) / W, 1 - (y - y0) / H], "rot": False} for t, x, y, h in raw]
    lines = group_lines(spans, 1)
    res = extract([lines])
    units = {1: "INCH", 4: "MM", 5: "CM", 6: "M"}.get(doc.header.get("$INSUNITS", 0))
    if units and "units" not in res["meta"]:
        res["meta"]["units"] = {"value": units, "conf": 0.9, "page": 1, "bbox": None, "src": "dxf-header"}
    res.update(pages=1, has_text=True, source="text-layer", text="\n".join(l.text for l in lines))
    return res
