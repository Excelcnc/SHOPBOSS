from app.services.cad.analyze import analyze_step


def feats(p, t):
    return [f for f in p["features"] if f["type"] == t]


def test_bracket_features(samples):
    p = analyze_step(str(samples / "BRK-20417_RevC.step"), with_mesh=True)["parts"][0]
    assert [round(x, 2) for x in p["size"]] == [120.0, 80.0, 15.0]
    assert abs(p["volume"] / 1000 - 126.95) < 0.1
    holes = feats(p, "hole")
    cb = [h for h in holes if h["cbore"]]
    assert len(cb) == 4 and all(abs(h["dia"] - 6.6) < 1e-3 and abs(h["cbore"]["dia"] - 11) < 1e-3 and h["thru"] for h in cb)
    blind = [h for h in holes if not h["thru"]]
    assert len(blind) == 2 and all(abs(h["dia"] - 5.0) < 1e-3 and abs(h["depth"] - 20) < 0.01 for h in blind)
    assert any(abs(h["dia"] - 25) < 1e-3 and h["thru"] for h in holes)
    assert p["undercut_faces"] == 0
    assert len(p["mesh"]["faces"]) == p["faces"]


def test_shaft_is_turned_with_blind_tapped_ends(samples):
    p = analyze_step(str(samples / "SHF-3310_RevC.step"), with_mesh=False)["parts"][0]
    assert p["turned"]["ratio"] > 0.85 and p["turned"]["axis"] == "X"
    holes = feats(p, "hole")
    assert sum(1 for h in holes if abs(h["dia"] - 6) < 1e-3 and h["thru"]) == 2
    assert sum(1 for h in holes if abs(h["dia"] - 8.5) < 1e-3 and not h["thru"]) == 2
    assert any(f["type"] == "slot" for f in p["features"])
    assert p["undercut_faces"] == 0


def test_thin_wall_and_deep_pocket(samples):
    p = analyze_step(str(samples / "CAS-7781-04.step"), with_mesh=False)["parts"][0]
    assert abs(p["min_wall"]["t"] - 1.5) < 0.02
    codes = {f["code"] for f in p["flags"]}
    assert {"thin_wall", "deep_pocket"} <= codes


def test_assembly_bom(samples):
    r = analyze_step(str(samples / "SENSOR-MOUNT-ASSY-100.step"), with_mesh=False)
    assert r["assembly"]
    by = {p["name"]: p for p in r["parts"]}
    screws = next(p for n, p in by.items() if "4762" in n)
    pins = next(p for n, p in by.items() if "DOWEL" in n)
    assert screws["qty_per_assembly"] == 4 and screws["purchased_guess"]
    assert pins["qty_per_assembly"] == 2 and pins["purchased_guess"]
    assert not by["BRK-20417"]["purchased_guess"]


def test_internal_groove_is_undercut(tmp_path):
    import cadquery as cq
    b = cq.Workplane("XY").box(50, 50, 30).faces(">Z").workplane().hole(20)
    b = b.cut(cq.Workplane("XY").circle(13).circle(9.9).extrude(3).translate((0, 0, -1.5)))
    f = tmp_path / "groove.step"
    cq.exporters.export(b, str(f))
    p = analyze_step(str(f), with_mesh=False)["parts"][0]
    assert p["undercut_faces"] >= 1
    assert any(x["type"] == "groove" and abs(x["dia"] - 26) < 1e-3 for x in p["features"])
