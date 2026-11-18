"""Bill of materials (parts list) extraction from assembly drawings (PDF text layer).

1. Ruled tables: PyMuPDF finds cell boundaries; words are re-read inside each cell so spacing is kept.
2. Unruled lists: a header line containing ITEM/QTY/PART/DESCRIPTION defines the columns; rows are
   the text lines below it, words assigned to the nearest column.
Each row: item, qty, part_number, description, material, vendor, purchased flag (+ reason), bbox.
"""
from __future__ import annotations

import re

import fitz

COLS = {
    "item": r"^(ITEM|ITEM\s*NO\.?|FIND\s*NO\.?|BALLOON|POS\.?|NO\.?)$",
    "qty": r"^(QTY\.?|QUANTITY|QTY\.?\s*REQ'?D|REQ'?D|QTY/ASSY)$",
    "part_number": r"^(PART\s*(NO\.?|NUMBER|#)|P/N|DWG\s*NO\.?|DRAWING\s*(NO\.?|NUMBER)|ITEM\s*NUMBER)$",
    "description": r"^(DESCRIPTION|DESC\.?|NAME|TITLE)$",
    "material": r"^(MATERIAL|MAT'?L|MATERIAL\s*/\s*VENDOR|MATERIAL\s*/\s*SPEC)$",
    "vendor": r"^(VENDOR|SUPPLIER|MFR\.?|MANUFACTURER|SOURCE|MAKE/BUY|MAKE\s*/\s*BUY)$",
}
PURCHASED_RX = [
    (r"\b(PURCHASED|BUY|COTS|OFF[- ]THE[- ]SHELF|STOCK ITEM|CATALOG)\b", "marked purchased on the drawing"),
    (r"\b(MCMASTER|McMASTER|MISUMI|GRAINGER|MSC|BOSSARD|WURTH|WÜRTH|SKF|NSK|IGUS|SMC|FESTO|PARKER|SWAGELOK|DIGIKEY|MOUSER|KIPP|JERGENS)\b", "vendor named"),
    (r"\bISO[\s_-]?(4762|4014|4017|4032|7380|10642|2338|8734|7089|7090|7092)\b|\bDIN[\s_-]?(912|931|933|934|125|7991|6325|7984|471|472)\b|\bANSI\b|\bNAS\d+|\bMS\d{4,}", "standard part number"),
    (r"\b(SCREW|BOLT|NUT|WASHER|BEARING|BUSHING|DOWEL|PIN|SPRING|CIRCLIP|RETAINING RING|O-?RING|INSERT|HELI-?COIL|STANDOFF|GROMMET|LABEL|DECAL|MOTOR|SENSOR|CONNECTOR|CABLE|HOSE|FITTING|GASKET|SEAL)\b", "hardware / catalog item"),
    (r"\b\d{4,5}[A-Z]\d{2,4}\b", "vendor-style part number"),
]
MAKE_RX = r"\b(MAKE|MACHINED|MFG|IN[- ]HOUSE|FAB(RICATED)?)\b"


def _classify(row: dict) -> tuple[bool, str]:
    text = " ".join(str(row.get(k, "")) for k in ("part_number", "description", "material", "vendor")).upper()
    if re.search(MAKE_RX, str(row.get("vendor", "")).upper()):
        return False, "marked make on the drawing"
    # explicit purchased marking, named vendor, standard or vendor part number -> purchased
    for rx, why in PURCHASED_RX[:3] + PURCHASED_RX[4:]:
        if re.search(rx, text, re.I):
            return True, why
    # a material grade in the material column means we make it
    if re.search(r"\b\d{3,4}(-T\d+)?\b|ALUM|STEEL|STAINLESS|BRASS|TITANIUM|DELRIN|ACETAL|PEEK|NYLON|COPPER|BRONZE", str(row.get("material", "")).upper()):
        return False, "material specified (made in-house)"
    if re.search(PURCHASED_RX[3][0], text, re.I) and not re.search(r"\b(BRACKET|PLATE|HOUSING|BLOCK|SHAFT|SPACER|FLANGE|MOUNT|BODY|BASE|COVER|MANIFOLD)\b", text):
        return True, PURCHASED_RX[3][1]
    return False, ""


def _qty(s: str):
    m = re.search(r"\d+(\.\d+)?", s or "")
    if not m:
        return None
    v = float(m.group(0))
    return int(v) if v.is_integer() else v


def _header_map(cells: list[str]) -> dict[int, str]:
    hm = {}
    for i, c in enumerate(cells):
        t = re.sub(r"\s+", " ", (c or "").strip().upper())
        for key, rx in COLS.items():
            if key not in hm.values() and re.match(rx, t):
                hm[i] = key
                break
    return hm


def _is_header(hm: dict) -> bool:
    v = set(hm.values())
    return "qty" in v and ("part_number" in v or "description" in v)


def _words_in(words, rect) -> str:
    x0, y0, x1, y1 = rect
    ws = [w for w in words if w[0] >= x0 - 1 and w[2] <= x1 + 1 and w[1] >= y0 - 1 and w[3] <= y1 + 1]
    ws.sort(key=lambda w: (round(w[1], 0), w[0]))
    return " ".join(w[4] for w in ws).strip()


def _finish(rows: list[dict], page: int, W: float, H: float, method: str) -> list[dict]:
    out = []
    for r in rows:
        if not (r.get("part_number") or r.get("description")):
            continue
        r["qty"] = _qty(str(r.get("qty", "")))
        mv = r.get("material", "")
        if not r.get("vendor") and mv and re.search(PURCHASED_RX[1][0], mv, re.I):
            r["vendor"] = mv  # combined MATERIAL / VENDOR column
        r["purchased"], r["purchased_reason"] = _classify(r)
        b = r.pop("_rect", None)
        r["bbox"] = [b[0] / W, b[1] / H, b[2] / W, b[3] / H] if b else None
        r["page"] = page
        r["method"] = method
        r["confidence"] = 0.95 if r["qty"] is not None and r.get("part_number") else 0.7
        out.append(r)
    return out


def extract_bom(pdf_bytes: bytes, max_pages: int = 5) -> list[dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    found: list[dict] = []
    for pno in range(min(max_pages, doc.page_count)):
        page = doc[pno]
        W, H = page.rect.width, page.rect.height
        words = page.get_text("words")
        # 1) ruled tables
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []
        for tb in tables:
            grid = [[(c if c else None) for c in row.cells] for row in tb.rows]
            if not grid:
                continue
            texts = [[_words_in(words, c) if c else "" for c in row] for row in grid]
            hidx = next((i for i, row in enumerate(texts[:3]) if _is_header(_header_map(row))), None)
            if hidx is None:
                continue
            hm = _header_map(texts[hidx])
            rows = []
            for ri in range(hidx + 1, len(texts)):
                r = {key: texts[ri][ci] for ci, key in hm.items() if ci < len(texts[ri])}
                cells = [c for c in grid[ri] if c]
                if cells:
                    r["_rect"] = (min(c[0] for c in cells), min(c[1] for c in cells), max(c[2] for c in cells), max(c[3] for c in cells))
                rows.append(r)
            found += _finish(rows, pno + 1, W, H, "table")
        if found:
            continue
        # 2) unruled: header line + aligned rows
        lines: dict[tuple, list] = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)
        ordered = sorted(lines.values(), key=lambda ws: (min(x[1] for x in ws), min(x[0] for x in ws)))
        for li, ws in enumerate(ordered):
            ws = sorted(ws, key=lambda w: w[0])
            # merge adjacent words into header tokens
            toks, cur = [], None
            for w in ws:
                if cur and w[0] - cur[2] < (w[3] - w[1]) * 0.6:
                    cur = [cur[0], min(cur[1], w[1]), w[2], max(cur[3], w[3]), cur[4] + " " + w[4]]
                else:
                    if cur:
                        toks.append(cur)
                    cur = list(w[:5])
            if cur:
                toks.append(cur)
            hm = _header_map([t[4] for t in toks])
            if not _is_header(hm):
                continue
            cols = sorted(((toks[i][0], key) for i, key in hm.items()))
            y = max(t[3] for t in toks)
            rows = []
            for ws2 in ordered[li + 1:]:
                top = min(x[1] for x in ws2)
                if top - y > 30:  # gap ends the list
                    break
                r: dict = {}
                for w in sorted(ws2, key=lambda w: w[0]):
                    key = [k for x, k in cols if x <= w[0] + 2]
                    key = key[-1] if key else cols[0][1]
                    r[key] = (r.get(key, "") + " " + w[4]).strip()
                r["_rect"] = (min(x[0] for x in ws2), top, max(x[2] for x in ws2), max(x[3] for x in ws2))
                rows.append(r)
                y = max(x[3] for x in ws2)
            found += _finish(rows, pno + 1, W, H, "aligned text")
            break
    return found
