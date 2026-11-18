from app.services.cad.analyze import analyze_step
from app.services.costing.defaults import DEFAULT_MACHINES, DEFAULT_RATES, MATERIALS
from app.services.costing.engine import estimate

MATS = {c: {"code": c, "name": n, "aliases": a, "family": f, "density_g_cm3": d, "machinability": m, "price_per_kg": p} for c, n, a, f, d, m, p in MATERIALS}
RATES = {k: r for k, _, r in DEFAULT_RATES}
MACH = [{"name": n, "kind": k, "travel_mm": t} for n, k, _, t, _ in DEFAULT_MACHINES]


def base(samples, qtys=(1, 100)):
    geo = analyze_step(str(samples / "BRK-20417_RevC.step"), with_mesh=False)["parts"][0]
    return {"geometry": geo, "drawing": None, "material": MATS["AL6061"], "quantities": list(qtys), "rates": RATES, "machines": MACH, "processes": []}


def test_price_drops_with_quantity_and_is_rounded_up(samples):
    r = estimate(base(samples, (1, 10, 100, 500)))
    prices = [b["unit_price"] for b in r["breaks"]]
    assert prices == sorted(prices, reverse=True)
    assert all(abs(p * 20 - round(p * 20)) < 1e-6 for p in prices if p < 100)


def test_overrides_flow_through(samples):
    r0 = estimate(base(samples))
    r1 = estimate(base(samples), {"time.cycle_min": {"value": 60}, "material.price_per_kg": {"value": 30}})
    assert r1["breaks"][1]["unit_price"] > r0["breaks"][1]["unit_price"]
    line = next(l for l in r1["lines"] if l["key"] == "time.cycle_min")
    assert line["overridden"] and line["value"] == 60 and line["computed"] != 60


def test_unknown_material_is_conservative(samples):
    known = estimate(base(samples))
    inp = base(samples)
    inp["material"] = {**MATS["SS316"], "code": None}
    unknown = estimate(inp)
    assert unknown["breaks"][1]["unit_price"] > known["breaks"][1]["unit_price"] * 1.5
    assert any("Material not identified" in a for a in unknown["adjustments"])


def test_tight_tolerance_raises_complexity(samples):
    a = estimate(base(samples))
    inp = base(samples)
    inp["drawing"] = {"items": [{"cat": "fit", "value": "Ø25 H7", "band": 0.021}, {"cat": "gdt", "value": "⌖ 0.02"}, {"cat": "finish", "value": "Ra 0.4", "ra": 0.4}]}
    b = estimate(inp)
    assert b["complexity"]["score"] > a["complexity"]["score"]
    assert b["breaks"][1]["unit_price"] > a["breaks"][1]["unit_price"]


def test_no_geometry_stays_unpriced_until_envelope_entered():
    inp = {"geometry": {}, "drawing": None, "material": MATS["SS316"], "quantities": [60], "rates": RATES, "machines": MACH}
    assert estimate(inp)["breaks"][0]["unit_price"] is None
    r = estimate(inp, {"geometry.size_mm": {"value": "200 x 200 x 25"}})
    assert r["breaks"][0]["unit_price"] > 50
