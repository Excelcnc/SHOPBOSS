"""Deterministic drawing reading from the PDF text layer (PyMuPDF).

Every item carries page + normalized bbox [x0, y0, x1, y1] (0..1, top-left origin) and source
'text-layer'. Scanned drawings (no text layer) return has_text=False; the AI vision step reads those.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

GDT_SYM = {"⏥": "Flatness", "▱": "Flatness", "⏤": "Straightness", "∥": "Parallelism", "⫽": "Parallelism", "⊥": "Perpendicularity",
           "∠": "Angularity", "⌖": "Position", "◎": "Concentricity", "⌭": "Cylindricity", "○": "Circularity", "⌒": "Profile of a line",
           "⌓": "Profile of a surface", "↗": "Circular runout", "⌰": "Total runout", "⌯": "Symmetry"}
LABEL = re.compile(r"^(TITLE|DESCRIPTION|PART\s*(?:NO\.?|NUMBER)|DWG\.?\s*NO\.?|DRAWING\s*(?:NO\.?|NUMBER)|REV(?:ISION)?\.?|SCALE|SHEET|UNITS?|MATERIAL|FINISH|DRAWN(?:\s*BY)?|QTY\.?|QUANTITY|WEIGHT|CAGE)\s*:?$", re.I)


@dataclass
class Line:
    text: str
    bbox: list  # normalized
    page: int


def tol_band(s: str | None):
    if not s:
        return None
    m = re.search(r"±\s*(\d*\.?\d+)", s)
    if m:
        return 2 * float(m[1])
    m = re.search(r"\+\s*(\d*\.?\d+)\s*/\s*-\s*(\d*\.?\d+)", s)
    if m:
        return float(m[1]) + float(m[2])
    m = re.search(r"\(\s*([+-]?\d*\.?\d+)\s*/\s*([+-]?\d*\.?\d+)\s*\)", s)
    if m:
        return abs(float(m[1]) - float(m[2]))
    return None


def read_lines(pdf_bytes: bytes, max_pages: int = 5) -> tuple[list[list[Line]], int]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for pno in range(min(max_pages, doc.page_count)):
        page = doc[pno]
        W, H = page.rect.width, page.rect.height
        spans = []
        for block in page.get_text("dict")["blocks"]:
            for ln in block.get("lines", []):
                d = ln.get("dir", (1, 0))
                for sp in ln["spans"]:
                    t = sp["text"].strip()
                    if not t:
                        continue
                    x0, y0, x1, y1 = sp["bbox"]
                    spans.append({"s": t, "bbox": [x0 / W, y0 / H, x1 / W, y1 / H], "rot": abs(d[1]) > 0.1})
        pages.append(group_lines(spans, pno + 1))
    return pages, doc.page_count


def group_lines(spans: list[dict], page: int) -> list[Line]:
    flat = sorted([s for s in spans if not s["rot"]], key=lambda s: (s["bbox"][1], s["bbox"][0]))
    rot = [s for s in spans if s["rot"]]
    lines: list[dict] = []
    for it in flat:
        b = it["bbox"]
        h = b[3] - b[1]
        cy = (b[1] + b[3]) / 2
        hit = None
        for L in lines:
            if abs(L["cy"] - cy) < h * 0.45 and b[0] - L["bbox"][2] < h * 3 and b[0] >= L["bbox"][0] - h:
                hit = L
                break
        if hit:
            hit["items"].append(it)
            hit["bbox"] = [min(hit["bbox"][0], b[0]), min(hit["bbox"][1], b[1]), max(hit["bbox"][2], b[2]), max(hit["bbox"][3], b[3])]
        else:
            lines.append({"cy": cy, "bbox": list(b), "items": [it]})
    out = [Line(" ".join(i["s"] for i in sorted(L["items"], key=lambda x: x["bbox"][0])).strip(), L["bbox"], page) for L in lines]
    out += [Line(s["s"], s["bbox"], page) for s in rot]
    return [l for l in out if l.text]


def pair_labels(lines: list[Line]) -> list[Line]:
    """Title blocks: join a bare label ('REV') with the value to its right (or just below)."""
    extra = []
    for L in lines:
        if not LABEL.match(L.text.strip()):
            continue
        h = L.bbox[3] - L.bbox[1]
        cy = (L.bbox[1] + L.bbox[3]) / 2
        right = sorted([o for o in lines if o is not L and not LABEL.match(o.text.strip())
                        and abs((o.bbox[1] + o.bbox[3]) / 2 - cy) < h * 0.6 and o.bbox[0] > L.bbox[2] - h * 0.2 and o.bbox[0] - L.bbox[2] < 0.12],
                       key=lambda o: o.bbox[0])
        below = [] if right else sorted([o for o in lines if o is not L and not LABEL.match(o.text.strip())
                                         and 0 < o.bbox[1] - L.bbox[3] + h * 0.2 < h * 2.7 and abs(o.bbox[0] - L.bbox[0]) < 0.05], key=lambda o: o.bbox[1])
        v = (right or below or [None])[0]
        if v:
            extra.append(Line(L.text.strip().rstrip(":") + ": " + v.text,
                              [min(L.bbox[0], v.bbox[0]), min(L.bbox[1], v.bbox[1]), max(L.bbox[2], v.bbox[2]), max(L.bbox[3], v.bbox[3])], L.page))
    return extra


def extract(pages: list[list[Line]]) -> dict:
    items: list[dict] = []
    meta: dict = {}
    n = [0]

    def add(**o):
        n[0] += 1
        o.setdefault("conf", 0.9)
        o["id"] = f"T{n[0]}"
        o["src"] = "text-layer"
        items.append(o)

    def set_meta(k, v, L, conf=0.9):
        if v and k not in meta:
            meta[k] = {"value": v.strip().rstrip("."), "conf": conf, "page": L.page, "bbox": L.bbox, "src": "text-layer"}

    for lines in pages:
        for L in pair_labels(lines):
            t = L.text
            g = lambda rx: (re.match(rx, t, re.I) or [None, None])[1]
            set_meta("description", g(r"^(?:TITLE|DESCRIPTION): (.{3,60})$"), L)
            set_meta("drawing_number", g(r"^(?:PART\s*(?:NO\.?|NUMBER)|DWG\.?\s*NO\.?|DRAWING\s*(?:NO\.?|NUMBER)): ([A-Z0-9][A-Z0-9\-_.]{2,30})"), L)
            set_meta("revision", g(r"^REV(?:ISION)?\.?: ([A-Z0-9]{1,3})\b"), L)
            set_meta("scale", g(r"^SCALE: (.{1,12})$"), L)
            set_meta("units", g(r"^UNITS?: (MM|INCH(?:ES)?|IN|MILLIMET\w*)\b"), L)
            set_meta("quantity", g(r"^(?:QTY\.?|QUANTITY): (\d[\d,]*.*)$"), L)
            set_meta("material", g(r"^MATERIAL: (.{3,60})$"), L)
        for L in lines:
            l, bb, page = L.text, L.bbox, L.page
            for m in re.finditer(r"(?:(\d+)\s*[Xx×]\s*)?(Ø|⌀|R)?\s*(\d*\.?\d+)\s*(?:±|\+/-|\+-)\s*(\d*\.?\d+)", l):
                cat = "radius" if m[2] == "R" else "diameter" if m[2] else "dimension"
                add(cat=cat, label=cat.capitalize(), value=(m[2] or "") + m[3], tol="±" + m[4], qty=int(m[1]) if m[1] else None, page=page, bbox=bb, band=2 * float(m[4]), line=l[:120])
            for m in re.finditer(r"(?:(Ø|⌀)\s*)?(\d*\.?\d+)\s*\+\s*(\d*\.?\d+)\s*/\s*-\s*(\d*\.?\d+)", l):
                add(cat="diameter" if m[1] else "dimension", label="Diameter" if m[1] else "Dimension", value=("Ø" if m[1] else "") + m[2], tol=f"+{m[3]}/-{m[4]}", page=page, bbox=bb, band=float(m[3]) + float(m[4]), line=l[:120])
            for m in re.finditer(r"(?:Ø|⌀)\s*(\d*\.?\d+)\s*([a-hj-zA-HJ-Z]{1,2}\d{1,2})\b(?:\s*\(([^)]*)\))?", l):
                add(cat="fit", label="ISO fit", value=f"Ø{m[1]} {m[2]}", tol=m[3] or m[2], page=page, bbox=bb, band=tol_band("(" + m[3] + ")") if m[3] else None, line=l[:120])
            for m in re.finditer(r"(\d+)\s*[Xx×]\s*(?:Ø|⌀)\s*(\d*\.?\d+)([^,;]*)", l):
                add(cat="hole", label="Hole pattern", value="Ø" + m[2], qty=int(m[1]), note=m[3].strip()[:60], page=page, bbox=bb, line=l[:120])
            for m in re.finditer(r"(?:^|\s)(?:Ø|⌀)\s*(\d*\.?\d+)\s+(THRU|↧\s*\d*\.?\d+)([^,;]*)", l):
                if re.search(r"\d+\s*[Xx×]\s*$", l[max(0, m.start() - 6):m.start() + 1]):
                    continue
                sub = "cbore" if re.search(r"⌴|C'?BORE|COUNTERBORE", l, re.I) else "tapdrill" if re.search(r"TAP\s*DRILL", l, re.I) else "csink" if re.search(r"⌵|C'?SINK|CSK|COUNTERSINK", l, re.I) else None
                q = re.search(r"(\d+)\s*PLACE", m[3], re.I)
                add(cat="hole", sub=sub, label={"cbore": "Counterbore", "tapdrill": "Tap drill", "csink": "Countersink"}.get(sub, "Hole"), value="Ø" + m[1], qty=int(q[1]) if q else 1, note=(m[2] + m[3]).strip()[:60], page=page, bbox=bb, line=l[:120])
            for m in re.finditer(r"\bM(\d+(?:\.\d+)?)\s*[xX×]\s*(\d*\.?\d+)([^,;]{0,30})", l):
                add(cat="thread", label="Metric thread", value=f"M{m[1]}x{m[2]}{m[3].rstrip()}", page=page, bbox=bb, line=l[:120])
            for m in re.finditer(r"(?:#\d+|\d+/\d+|\d+\.\d+)\s*-\s*\d+\s*(?:UNC|UNF|UNEF|UN)[^,;]{0,16}", l, re.I):
                add(cat="thread", label="Unified thread", value=m[0].strip(), page=page, bbox=bb, line=l[:120])
            for m in re.finditer(r"\d+/\d+\s*-\s*\d+\s*NPT\w*", l, re.I):
                add(cat="thread", label="Pipe thread", value=m[0], page=page, bbox=bb, line=l[:120])
            for m in re.finditer(r"\bRa\s*(\d*\.?\d+)\s*(µm|um|μm|µin|uin|μin)?", l, re.I):
                add(cat="finish", label="Surface roughness", value=m[0].strip(), ra=float(m[1]) * (0.0254 if m[2] and "in" in m[2].lower() else 1.0), page=page, bbox=bb, line=l[:120])
            sym = next((k for k in GDT_SYM if k in l), None)
            if sym or re.search(r"\|\s*[A-Z](?:\s*-\s*[A-Z])?\s*(\||$)", l):
                add(cat="gdt", label=GDT_SYM.get(sym, "Feature control frame"), value=l[:80], page=page, bbox=bb, critical=True)
            for m in re.finditer(r"\b(KEYWAY|SLOT)\b[^,;]*", l, re.I):
                add(cat="slot", label=m[1].capitalize(), value=m[0].strip()[:60], page=page, bbox=bb)
            for m in re.finditer(r"\bPOCKET\b[^,;]*", l, re.I):
                add(cat="pocket", label="Pocket", value=m[0].strip()[:60], page=page, bbox=bb)
            for m in re.finditer(r"\bWALL\b[^,;]*", l, re.I):
                add(cat="wall", label="Wall thickness", value=m[0].strip()[:60], page=page, bbox=bb)
            for m in re.finditer(r"\b(WELD\w*|AWS\s*D\d[\w.]*|ISO\s*5817[^,;]*)", l, re.I):
                add(cat="weld", label="Welding", value=l[:80], page=page, bbox=bb)
            for m in re.finditer(r"\b(ASTM|AMS|MIL(?:-[A-Z]+)?|ASME|ISO|DIN|EN|SAE|AS|BS|JIS)[\s-]?[A-Z]?\d[\w.\-]*(?:\s+TYPE\s+[IVX]+)?(?:\s+CLASS\s+\d)?", l):
                add(cat="standard", label="Standard", value=m[0].rstrip(".,"), page=page, bbox=bb)
            for m in re.finditer(r"\b(\d{2}\s*-\s*\d{2}\s*HRC|HEAT\s*TREAT\w*[^.;]*|Q\s*&\s*T|CASE\s*HARDEN\w*[^.;]*|NITRID\w*[^.;]*|STRESS\s*RELIEVE\w*)", l, re.I):
                add(cat="heat", label="Heat treatment", value=m[0].strip(), page=page, bbox=bb)
                set_meta("heat_treatment", m[0], L, 0.85)
            for m in re.finditer(r"\b(ANODI[SZ]E[\w\s,\-]{0,40}|HARD\s*COAT|BLACK\s*OXIDE[^.;]*|PASSIVATE[^.;]*|ZINC\s*PLAT\w*[^.;]*|NICKEL\s*PLAT\w*[^.;]*|CHEM\s*FILM[^.;]*|ALODINE|POWDER\s*COAT\w*|BEAD\s*BLAST\w*)", l, re.I):
                add(cat="coating", label="Coating / finish", value=m[0].strip(), page=page, bbox=bb)
            if re.match(r"^\s*\d+\.\s+", l):
                add(cat="note", label="Note", value=l[:160], page=page, bbox=bb, conf=0.95)
            g = lambda rx: (re.search(rx, l, re.I) or [None, None])[1]
            set_meta("description", g(r"^TITLE[:\s]+(.{3,60})$"), L)
            set_meta("drawing_number", g(r"(?:PART|DWG|DRAWING)\s*(?:NO\.?|NUMBER|#)[:\s]*([A-Z0-9][A-Z0-9\-_.]{2,30})"), L)
            set_meta("revision", g(r"^REV(?:ISION)?\.?[:\s]+([A-Z0-9]{1,3})\b"), L)
            set_meta("units", g(r"\bUNITS?[:\s]+(MM|INCH(?:ES)?|IN)\b") or ("MM" if re.search(r"ALL DIMENSIONS (?:ARE )?IN MM", l, re.I) else None) or ("INCH" if re.search(r"ALL DIMENSIONS (?:ARE )?IN INCH", l, re.I) else None), L)
            set_meta("quantity", g(r"\bQTY\.?[:\s]+(\d[\d,]*(?:\s*PCS)?)"), L)
            set_meta("material", g(r"\bMATERIAL[:\s]+([^;]{3,60}?)\.?$"), L)
            set_meta("coating", g(r"\bFINISH[:\s]+([^;]{3,70}?)\.?$"), L)
            set_meta("general_tolerance", g(r"(?:UNLESS OTHERWISE SPECIFIED|UOS|GENERAL TOLERANCES?)[:\s]+(?:PER\s+)?(.{4,70})"), L)
            ra = re.search(r"\bRa\s*\d*\.?\d+\s*(?:µm|um|μm)?[^.;]*", l, re.I)
            if ra and re.search(r"UNLESS|ALL|GENERAL", l, re.I):
                set_meta("surface_finish", ra[0], L)
    seen = set()
    uniq = []
    for i in items:
        k = (i["cat"], i["value"], i.get("tol"))
        if k in seen:
            continue
        seen.add(k)
        if i.get("band") is None and i.get("tol"):
            i["band"] = tol_band(i["tol"])
        if i.get("band") is not None and i["band"] <= 0.05:
            i["critical"] = True
        uniq.append(i)
    return {"meta": meta, "items": uniq}


def analyze_pdf(pdf_bytes: bytes) -> dict:
    pages, total = read_lines(pdf_bytes)
    has_text = any(pages)
    res = extract(pages) if has_text else {"meta": {}, "items": []}
    res.update(pages=total, has_text=has_text, source="text-layer" if has_text else "none",
               text="\n".join(l.text for p in pages for l in p)[:30000])
    return res


def render_page_png(pdf_bytes: bytes, page: int = 1, max_px: int = 2400) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    p = doc[page - 1]
    zoom = max_px / max(p.rect.width, p.rect.height)
    return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")


def image_to_pdf(img_bytes: bytes) -> bytes:
    """Wrap a raster drawing (PNG/JPG) as a one-page PDF so the rest of the pipeline is uniform."""
    img = fitz.open(stream=img_bytes)
    pdf = fitz.open("pdf", img.convert_to_pdf())
    return pdf.tobytes()
