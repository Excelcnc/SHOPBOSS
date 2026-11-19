"""Records the API responses the web app needs, from a running CNC Quote server, into demo-data.json
for the in-browser demo (npm run build:demo). Usage: python demo/capture.py http://localhost:8200"""
import base64, json, sys, urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
H = {"X-Dev-User": "estimator@example.com"}


def get(path, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(BASE + path, headers=H))
    b = r.read()
    return (b, r.headers.get("content-type", "")) if raw else json.loads(b)


d = {"me": get("/me"), "shop": get("/shop"), "rfqs": get("/rfqs"), "rfq": {}, "quote": {}, "mesh": {}, "similar": {},
     "page": {}, "file": {}, "mailboxes": get("/mailboxes"), "team": get("/team"), "history": get("/history"),
     "calibration": get("/history/calibration")}
for r in d["rfqs"]:
    full = get(f"/rfqs/{r['id']}")
    d["rfq"][r["id"]] = full
    for p in full["parts"]:
        if p.get("quote_id") and p["quote_id"] not in d["quote"]:
            d["quote"][p["quote_id"]] = get(f"/quotes/{p['quote_id']}")
        try:
            d["mesh"][p["id"]] = get(f"/parts/{p['id']}/mesh")
        except Exception:
            pass
        d["similar"][p["id"]] = get(f"/parts/{p['id']}/similar")
    for a in full.get("attachments", []):
        name = a["filename"].lower()
        if name.endswith((".pdf", ".dxf", ".png", ".jpg")):
            try:
                b, ct = get(f"/attachments/{a['id']}/page/1.png", raw=True)
                d["page"][a["id"]] = "data:image/png;base64," + base64.b64encode(b).decode()
            except Exception:
                pass
        if name.endswith((".pdf", ".png", ".jpg")):
            b, ct = get(f"/attachments/{a['id']}/file", raw=True)
            d["file"][a["id"]] = f"data:{ct.split(';')[0]};base64," + base64.b64encode(b).decode()
json.dump(d, open(sys.argv[2] if len(sys.argv) > 2 else "demo/demo-data.json", "w"), separators=(",", ":"))
print({k: (len(v) if hasattr(v, "__len__") else v) for k, v in d.items()})
