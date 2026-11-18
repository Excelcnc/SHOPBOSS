def upload(client, samples, names, **form):
    files = [("files", (n, (samples / n).read_bytes())) for n in names]
    r = client.post("/api/rfqs", files=files, data=form)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow(client, samples):
    created = upload(client, samples, ["BRK-20417_RevC.pdf", "BRK-20417_RevC.step"], customer_name="Northfield Robotics", subject="RFQ bracket", quantities="250, 500")
    rid = created[0]["id"]
    rfq = client.get(f"/api/rfqs/{rid}").json()
    assert rfq["analysis_status"] == "done", rfq["analysis_error"]
    part = next(p for p in rfq["parts"] if p["kind"] == "machined")
    assert part["part_number"] == "BRK-20417" and part["revision"] == "C" and part["material_code"] == "AL6061"
    assert part["match"]["score"] >= 0.6
    assert client.get(f"/api/parts/{part['id']}/mesh").status_code == 200
    assert client.get(f"/api/attachments/{part['drawing_attachment_id']}/page/1.png").headers["content-type"] == "image/png"
    q = client.get(f"/api/quotes/{part['quote_id']}").json()
    v = q["versions"][0]
    assert [b["qty"] for b in v["result"]["breaks"]] == [250, 500]
    p250 = v["result"]["breaks"][0]["unit_price"]
    # override cycle time -> price changes, original stays recoverable via computed value
    v2 = client.patch(f"/api/versions/{v['id']}", json={"overrides": {"time.cycle_min": 40}, "reason": "customer tolerance tighter than usual"}).json()
    assert v2["result"]["breaks"][0]["unit_price"] > p250
    # Save As a 7075 variant without touching the original
    nv = client.post(f"/api/versions/{v['id']}/save-as", json={"label": "7075 option"}).json()
    nv = client.patch(f"/api/versions/{nv['id']}", json={"material_code": "AL7075"}).json()
    assert nv["inputs"]["material"]["code"] == "AL7075" and nv["number"] == 2
    orig = client.get(f"/api/quotes/{part['quote_id']}").json()["versions"][0]
    assert orig["inputs"]["material"]["code"] == "AL6061"
    # finalize -> minimal quote + PDF
    out = client.post(f"/api/rfqs/{rid}/finalize", json={"lines": [{"version_id": v["id"], "qty": 250}], "valid_days": 30}).json()
    assert out["lines"][0]["part_number"] == "BRK-20417" and out["lines"][0]["revision"] == "C" and out["lines"][0]["qty"] == 250
    assert set(out["lines"][0]) >= {"part_number", "revision", "qty", "unit_price"}
    pdf = client.get(f"/api/outputs/{out['id']}/pdf")
    assert pdf.content[:4] == b"%PDF"
    # final versions are locked
    assert client.patch(f"/api/versions/{v['id']}", json={"overrides": {"time.cycle_min": 10}}).status_code == 409
    assert client.post(f"/api/rfqs/{rid}/outcome", json={"outcome": "won"}).json()["ok"]


def test_email_upload_and_similar_jobs(client, samples):
    upload(client, samples, ["BRK-20417_RevC.pdf", "BRK-20417_RevC.step"], quantities="100")
    created = upload(client, samples, ["RFQ_BWP-2026-0418.eml"])
    rfq = client.get(f"/api/rfqs/{created[0]['id']}").json()
    assert rfq["customer_name"] == "Brightwater Pumps Ltd"
    flange = rfq["parts"][0]
    assert flange["part_number"] == "FLG-5520" and flange["material_code"] == "SS316"
    assert any("No 3D model" in w for w in flange["warnings"])
    # history import + similar
    csv = "Job,Part_Number,Rev,Customer,Order_Qty,Unit_Price,Est_Total_Hrs,Act_Total_Hrs,Material,Order_Date,Status,Length,Width,Height\n" \
          "J1001,BRK-19000,A,Northfield,200,48.5,70,81,6061-T6,2026-03-02,Complete,118,78,15\n" \
          "J1002,SHF-1200,B,Halvorsen,50,140,60,66,4140,2026-04-11,Complete,180,40,40\n"
    r = client.post("/api/history/import", files={"file": ("jobs.csv", csv.encode())}).json()
    assert r["imported"] == 2 and r["mapping"]["actual_hours"] == "Act_Total_Hrs"
    rid = client.get("/api/rfqs").json()
    bracket = next(x for x in rid if x["parts"] and "BRK" not in x.get("subject", "") or True)
    br = client.get(f"/api/rfqs/{[x for x in rid if x['id'] != created[0]['id']][0]['id']}").json()
    pid = next(p["id"] for p in br["parts"] if p["kind"] == "machined")
    sim = client.get(f"/api/parts/{pid}/similar").json()
    assert sim and sim[0]["part_number"] == "BRK-19000"


def test_shop_config_and_material_override(client, samples):
    shop = client.get("/api/shop").json()
    assert any(r["key"] == "milling" for r in shop["rates"]) and len(shop["materials"]) > 20
    mill = next(r for r in shop["rates"] if r["key"] == "milling")
    assert client.put(f"/api/shop/rates/{mill['id']}", json={"rate_per_hour": 120}).json()["ok"]
    assert client.put("/api/shop/material-prices/AL6061", json={"price_per_kg": 9.25}).json()["ok"]
    m = next(x for x in client.get("/api/shop").json()["materials"] if x["code"] == "AL6061")
    assert m["price_per_kg"] == 9.25 and m["price_source"].startswith("shop price")


def test_graph_validation_handshake(client):
    r = client.post("/api/intake/graph/notify?validationToken=abc123")
    assert r.status_code == 200 and r.text == "abc123"


def test_assembly_rfq(client, samples):
    created = upload(client, samples, ["SENSOR-MOUNT-ASSY-100.step", "BRK-20417_RevC.pdf"], quantities="20")
    rfq = client.get(f"/api/rfqs/{created[0]['id']}").json()
    kinds = {p["part_number"]: (p["kind"], p["qty_per_parent"]) for p in rfq["parts"]}
    assert kinds["SENSOR-MOUNT-ASSY-100"][0] == "assembly"
    assert [v for k, v in kinds.items() if "4762" in k][0] == ("purchased", 4)
    brk = next(p for p in rfq["parts"] if p["part_number"] == "BRK-20417")
    assert brk["drawing_attachment_id"] and brk["versions"][0]["breaks"][0]["qty"] == 20
