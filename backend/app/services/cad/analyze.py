"""Exact B-rep analysis of STEP files with OpenCascade (OCP).

Produces, per machined part:
  * size: bounding box, volume, area, face/edge/solid counts
  * features: holes (through/blind, counterbore, countersink, drill point), bosses, internal radii,
    external rounds, pockets / slots / steps (recess floors), conical faces, angled faces, freeform faces
  * assessments: undercut faces (not reachable from any of the 6 principal directions), min wall
    thickness (ray sampled), deep holes / pockets, small radii, setups and machine-type hints
  * a display mesh with per-face triangle ranges so the UI can highlight any feature
and, for assemblies, the product tree with instance counts (BOM).

Nothing here guesses: every feature comes from surface types and measured geometry. Thread forms
are not modelled in most STEP files, so threads are inferred later from tap-drill sizes and drawing callouts.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import (GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
DIRS6 = [("+X", (1, 0, 0)), ("-X", (-1, 0, 0)), ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)), ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1))]


# ------------------------------------------------------------------ small vector helpers
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def scl(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)
def length(a): return math.sqrt(dot(a, a))


def axis_name(v) -> str:
    for n, a in AXES.items():
        if abs(dot(v, a)) > 0.999:
            return n
    return "(" + ", ".join(f"{x:.2f}" for x in v) + ")"


def signed_dir(v):
    for n, a in AXES.items():
        d = dot(v, a)
        if abs(d) > 0.999:
            return ("+" if d > 0 else "-") + n
    return None


def dist_to_axis(p, origin, axis):
    return length(cross(sub(p, origin), axis))


# ------------------------------------------------------------------ STEP reading
@dataclass
class Component:
    name: str
    shape: object
    instances: int = 1
    path: str = ""
    children: list = field(default_factory=list)
    is_assembly: bool = False


def _label_name(label: TDF_Label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def read_step(path: str) -> dict:
    """Return {'tree': Component, 'parts': {name: (shape, total_instances)}, 'header': {...}}."""
    doc = TDocStd_Document(TCollection_ExtendedString("cnc"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(path) != IFSelect_RetDone or not reader.Transfer(doc):
        # fall back to plain geometry reader
        r = STEPControl_Reader()
        if r.ReadFile(path) != IFSelect_RetDone:
            raise ValueError("The file is not a readable STEP file.")
        r.TransferRoots()
        shape = r.OneShape()
        comp = Component(name="Part", shape=shape)
        return {"tree": comp, "parts": {"Part": {"shape": shape, "qty": 1}}, "assembly": False, "header": step_header(path)}

    tool: XCAFDoc_ShapeTool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    parts: dict[str, dict] = {}

    def walk(label: TDF_Label, mult: int, path: str) -> Component:
        name = _label_name(label) or "Unnamed"
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        comp = Component(name=name, shape=shape, path=path + "/" + name)
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comp.is_assembly = True
            kids = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, kids, False)
            counts: dict[int, list] = {}
            for i in range(1, kids.Length() + 1):
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(kids.Value(i), ref)
                key = ref.Tag()
                counts.setdefault(key, [ref, 0])[1] += 1
            for ref, n in counts.values():
                child = walk(ref, mult * n, comp.path)
                child.instances = n
                comp.children.append(child)
        else:
            entry = parts.setdefault(name, {"shape": shape, "qty": 0})
            entry["qty"] += mult
        return comp

    tops = [walk(roots.Value(i), 1, "") for i in range(1, roots.Length() + 1)]
    tree = tops[0] if len(tops) == 1 else Component(name="Root", shape=None, children=tops, is_assembly=True)
    return {"tree": tree, "parts": parts, "assembly": tree.is_assembly, "header": step_header(path)}


def step_header(path: str) -> dict:
    meta: dict = {}
    try:
        with open(path, "rb") as fh:
            head = fh.read(400_000).decode("latin-1", "replace")
        m = re.search(r"FILE_NAME\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*\(([^)]*)\)\s*,\s*\(([^)]*)\)\s*,\s*'([^']*)'\s*,\s*'([^']*)'", head)
        if m:
            meta.update(file_name=m[1], timestamp=m[2], author=m[3].replace("'", "").strip(), organization=m[4].replace("'", "").strip(), preprocessor=m[5], originating_system=m[6])
        s = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", head)
        if s:
            meta["schema"] = s[1]
        mat = re.search(r"MATERIAL_DESIGNATION\s*\(\s*'([^']+)'", head)
        if mat:
            meta["material"] = mat[1]
    except OSError:
        pass
    return meta


def tree_to_dict(c: Component) -> dict:
    return {"name": c.name, "instances": c.instances, "assembly": c.is_assembly, "children": [tree_to_dict(k) for k in c.children]}


# ------------------------------------------------------------------ geometry helpers
def bbox(shape):
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return (x0, y0, z0), (x1, y1, z1)


def faces_of(shape):
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    return [TopoDS.Face_s(fmap.FindKey(i)) for i in range(1, fmap.Extent() + 1)]


def count(shape, kind):
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, m)
    return m.Extent()


def face_point_normal(face, u, v):
    p = gp_Pnt()
    from OCP.gp import gp_Vec
    n = gp_Vec()
    BRepGProp_Face(face).Normal(u, v, p, n)
    nn = (n.X(), n.Y(), n.Z())
    return (p.X(), p.Y(), p.Z()), norm(nn)


def face_area(face):
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, g)
    c = g.CentreOfMass()
    return g.Mass(), (c.X(), c.Y(), c.Z())


def sample_uv(face, n=3, edges=False):
    """Grid of UV samples. edges=True includes the parameter bounds (for axial extents)."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    fr = [i / (n - 1) for i in range(n)] if edges and n > 1 else [(i + 0.5) / n for i in range(n)]
    return [(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b) for a in fr for b in fr]


def face_samples(face, k=6):
    """Points + outward normals guaranteed to lie on the (trimmed) face: taken from its triangulation."""
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    out = []
    if tri is None or tri.NbTriangles() == 0:
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        return [face_point_normal(face, (u0 + u1) / 2, (v0 + v1) / 2)]
    nt = tri.NbTriangles()
    step = max(1, nt // k)
    has_uv = tri.HasUVNodes()
    trsf = loc.Transformation()
    for t in range(1, nt + 1, step):
        a, b, c = tri.Triangle(t).Get()
        if has_uv:
            uv = [tri.UVNode(i) for i in (a, b, c)]
            u = sum(x.X() for x in uv) / 3
            v = sum(x.Y() for x in uv) / 3
            out.append(face_point_normal(face, u, v))
        else:
            ps = [tri.Node(i).Transformed(trsf) for i in (a, b, c)]
            q = (sum(x.X() for x in ps) / 3, sum(x.Y() for x in ps) / 3, sum(x.Z() for x in ps) / 3)
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            out.append((q, face_point_normal(face, (u0 + u1) / 2, (v0 + v1) / 2)[1]))
        if len(out) >= k:
            break
    return out


def boundary_points(face, per_edge=5):
    """Points on the face's boundary edges (exact, unlike the UV box of a planar face)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    pts = []
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        try:
            c = BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current()))
            a, b = c.FirstParameter(), c.LastParameter()
            for k in range(per_edge):
                q = c.Value(a + (b - a) * k / max(1, per_edge - 1))
                pts.append((q.X(), q.Y(), q.Z()))
        except Exception:
            pass
        ex.Next()
    return pts


class RayCaster:
    def __init__(self, shape, tol=1e-4):
        self.it = IntCurvesFace_ShapeIntersector()
        self.it.Load(shape, tol)

    def first_hit(self, origin, direction, tmin=1e-3, tmax=1e6):
        line = gp_Lin(gp_Pnt(*origin), gp_Dir(*direction))
        self.it.Perform(line, tmin, tmax)
        if not self.it.IsDone() or self.it.NbPnt() == 0:
            return None
        best = None
        for i in range(1, self.it.NbPnt() + 1):
            w = self.it.WParameter(i)
            if w > tmin and (best is None or w < best[0]):
                best = (w, self.it.Face(i))
        return best


# ------------------------------------------------------------------ face classification
def classify_face(face, idx):
    ad = BRepAdaptor_Surface(face, True)
    st = ad.GetType()
    area, centroid = face_area(face)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    um, vm = (u0 + u1) / 2, (v0 + v1) / 2
    p, n = face_point_normal(face, um, vm)
    rec = {"i": idx, "area": area, "centroid": centroid, "type": "other"}
    if st == GeomAbs_Plane:
        rec.update(type="plane", n=n)
        lo, hi = bbox(face)
        rec["lo"], rec["hi"] = lo, hi
        rec["boundary"] = boundary_points(face, 8)
    elif st in (GeomAbs_Cylinder, GeomAbs_Cone):
        if st == GeomAbs_Cylinder:
            g = ad.Cylinder()
            r = g.Radius()
        else:
            g = ad.Cone()
            r = g.RefRadius()
        ax = g.Axis()
        o = (ax.Location().X(), ax.Location().Y(), ax.Location().Z())
        a = norm((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))
        # concave (hole-like) when the outward normal points toward the axis
        foot = add(o, scl(a, dot(sub(p, o), a)))
        radial = norm(sub(p, foot))
        concave = dot(n, radial) < 0
        span = abs(u1 - u0)
        lo, hi = bbox(face)
        ts = [dot(c, a) for c in ((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]))]
        # axial extent: project the face's sample points
        tvals = []
        for q in boundary_points(face, 6) or [face_point_normal(face, uu, vv)[0] for uu, vv in sample_uv(face, 4, edges=True)]:
            tvals.append(dot(q, a))
        rec.update(type="cyl" if st == GeomAbs_Cylinder else "cone", r=r, axis=a, origin=o, concave=concave, span=span,
                   t0=min(tvals + ts) if st == GeomAbs_Cone else min(tvals), t1=max(tvals + ts) if st == GeomAbs_Cone else max(tvals))
        if st == GeomAbs_Cone:
            rec["half_angle"] = math.degrees(abs(g.SemiAngle()))
            radii = [dist_to_axis(q, o, a) for q in boundary_points(face, 6)] or [r]
            rec["rmin"], rec["rmax"] = min(radii), max(radii)
    elif st == GeomAbs_Torus:
        rec.update(type="torus")
    elif st == GeomAbs_Sphere:
        rec.update(type="sphere")
    else:
        rec.update(type="freeform")
    return rec


# ------------------------------------------------------------------ main part analysis
def analyze_shape(shape, name="Part") -> dict:
    lo, hi = bbox(shape)
    BRepMesh_IncrementalMesh(shape, (length(sub(hi, lo)) or 1.0) * 0.002, False, 0.4, True)
    size = [hi[i] - lo[i] for i in range(3)]
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    volume = abs(g.Mass())
    ga = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, ga)
    area = ga.Mass()
    faces = faces_of(shape)
    recs = [classify_face(f, i) for i, f in enumerate(faces)]
    rc = RayCaster(shape)
    features: list[dict] = []
    flags: list[dict] = []
    fid = [0]

    def feat(**kw):
        fid[0] += 1
        kw["id"] = f"F{fid[0]}"
        features.append(kw)
        return kw

    def extent_along(axis):
        vals = []
        for r in recs:
            vals += [dot(r.get("lo", r["centroid"]), axis), dot(r.get("hi", r["centroid"]), axis)]
        b0, b1 = bbox(shape)
        corners = [(x, y, z) for x in (b0[0], b1[0]) for y in (b0[1], b1[1]) for z in (b0[2], b1[2])]
        ts = [dot(c, axis) for c in corners]
        return min(ts), max(ts)

    # ---- merge coaxial cylinder faces of equal radius
    cyls: list[dict] = []
    for r in recs:
        if r["type"] != "cyl":
            continue
        hit = None
        for c in cyls:
            if (abs(c["r"] - r["r"]) < max(0.005, c["r"] * 1e-3) and abs(dot(c["axis"], r["axis"])) > 0.9999
                    and c["concave"] == r["concave"] and dist_to_axis(r["origin"], c["origin"], c["axis"]) < 0.01):
                s = 1 if dot(c["axis"], r["axis"]) > 0 else -1
                a0, a1 = (r["t0"], r["t1"]) if s > 0 else (-r["t1"], -r["t0"])
                if a0 <= c["t1"] + 0.05 and a1 >= c["t0"] - 0.05:
                    hit = c
                    c["span"] = min(2 * math.pi, c["span"] + r["span"])
                    c["t0"], c["t1"] = min(c["t0"], a0), max(c["t1"], a1)
                    c["faces"].append(r["i"])
                    break
        if not hit:
            cyls.append({**r, "faces": [r["i"]]})
    FULL = 1.6 * math.pi
    for c in cyls:
        c["kind"] = ("hole" if c["span"] >= FULL else "irad") if c["concave"] else ("boss" if c["span"] >= FULL else "orad")

    cones = [r for r in recs if r["type"] == "cone"]
    planes = [r for r in recs if r["type"] == "plane"]

    # ---- holes: coaxial stacks (counterbores), caps (blind), cones (csk, drill point)
    holes = [c for c in cyls if c["kind"] == "hole"]
    stacks: list[list[dict]] = []
    for h in holes:
        placed = False
        for st in stacks:
            ref = st[0]
            if abs(dot(ref["axis"], h["axis"])) > 0.9999 and dist_to_axis(h["origin"], ref["origin"], ref["axis"]) < 0.02:
                s = 1 if dot(ref["axis"], h["axis"]) > 0 else -1
                a0, a1 = (h["t0"], h["t1"]) if s > 0 else (-h["t1"], -h["t0"])
                if any(a0 <= o["t1"] + 0.05 and a1 >= o["t0"] - 0.05 for o in st):
                    h["t0"], h["t1"] = a0, a1
                    st.append(h)
                    placed = True
                    break
        if not placed:
            stacks.append([h])
    # merge stacks that became connected through a later member (e.g. a bore split by a groove)
    merged = True
    while merged:
        merged = False
        for i in range(len(stacks)):
            for j in range(i + 1, len(stacks)):
                A0, B0 = stacks[i][0], stacks[j][0]
                if abs(dot(A0["axis"], B0["axis"])) > 0.9999 and dist_to_axis(B0["origin"], A0["origin"], A0["axis"]) < 0.02:
                    s_ = 1 if dot(A0["axis"], B0["axis"]) > 0 else -1
                    if any((b["t0"] if s_ > 0 else -b["t1"]) <= a["t1"] + 0.05 and (b["t1"] if s_ > 0 else -b["t0"]) >= a["t0"] - 0.05 for a in stacks[i] for b in stacks[j]):
                        for b in stacks[j]:
                            if s_ < 0:
                                b["t0"], b["t1"] = -b["t1"], -b["t0"]
                        stacks[i] += stacks[j]
                        del stacks[j]
                        merged = True
                        break
            if merged:
                break
    used_faces = set()
    for st in stacks:
        st.sort(key=lambda x: x["r"])
        main = st[0]
        ax, o = main["axis"], main["origin"]
        t0, t1 = min(x["t0"] for x in st), max(x["t1"] for x in st)
        co = [c for c in cones if abs(dot(c["axis"], ax)) > 0.9999 and dist_to_axis(c["origin"], o, ax) < 0.02]
        def radial_max(p):
            return max((dist_to_axis(q, o, ax) for q in p["boundary"]), default=1e9)
        on_axis_planes = [p for p in planes if abs(dot(p["n"], ax)) > 0.9999 and dist_to_axis(p["centroid"], o, ax) < 0.02]
        caps = [p for p in on_axis_planes if radial_max(p) <= main["r"] * 1.02 + 0.01]
        rbig = max(x["r"] for x in st)
        ledges = [p for p in on_axis_planes if p not in caps and radial_max(p) <= rbig * 1.02 + 0.01]
        drill_pt = [c for c in co if c["concave"] and c["rmin"] < main["r"] * 0.3]
        csk = [c for c in co if c["concave"] and c["rmax"] > main["r"] * 1.15]
        thru = not caps and not drill_pt
        # larger coaxial cylinders: at an end of the bore = counterbore; strictly inside = internal groove
        bigger = [x for x in st if x["r"] - main["r"] > 0.03]
        grooves = [x for x in bigger if x["t0"] > t0 + 0.05 and x["t1"] < t1 - 0.05]
        ends = [x for x in bigger if x not in grooves]
        cb = max(ends, key=lambda x: x["r"]) if ends else None
        for gv in grooves:
            feat(type="groove", label="Internal groove (undercut)", dia=2 * gv["r"], width=gv["t1"] - gv["t0"], axis=axis_name(ax), faces=gv["faces"], confidence=0.85)
            flags.append({"sev": "high", "code": "internal_groove", "text": f"Internal groove Ø{2*gv['r']:.2f} × {gv['t1']-gv['t0']:.2f} wide inside Ø{2*main['r']:.2f} bore: grooving/undercut tool"})
        depth = None if thru else (t1 - t0)
        main_len = main["t1"] - main["t0"]
        ld = (main_len if thru else (t1 - t0)) / (2 * main["r"])
        fids = [i for x in st for i in x["faces"]] + [c["i"] for c in co] + [p["i"] for p in caps + ledges]
        used_faces.update(fids)
        detail = []
        if cb:
            detail.append(f"counterbore Ø{2*cb['r']:.3f} × {cb['t1']-cb['t0']:.2f} deep")
        if csk:
            detail.append(f"countersink {2*csk[0]['half_angle']:.0f}° to Ø{2*csk[0]['rmax']:.2f}")
        if drill_pt:
            detail.append("drill-point bottom")
        label = "Counterbored hole" if cb else "Countersunk hole" if csk else "Through hole" if thru else "Blind hole"
        feat(type="hole", label=label, dia=2 * main["r"], depth=depth, thru=thru, axis=axis_name(ax), axis_vec=list(ax),
             center=list(o), ld=ld, cbore={"dia": 2 * cb["r"], "depth": cb["t1"] - cb["t0"]} if cb else None,
             csk={"dia": 2 * csk[0]["rmax"], "angle": 2 * csk[0]["half_angle"]} if csk else None, detail=", ".join(detail),
             faces=fids, confidence=0.95)
        if ld > 6:
            flags.append({"sev": "high" if ld > 10 else "medium", "code": "deep_hole", "text": f"Deep hole Ø{2*main['r']:.2f}: depth/diameter {ld:.1f}:1", "feature": features[-1]["id"]})

    for c in cyls:
        if c["kind"] == "boss":
            feat(type="boss", label="Boss / outer diameter", dia=2 * c["r"], length=c["t1"] - c["t0"], axis=axis_name(c["axis"]), axis_vec=list(c["axis"]), center=list(c["origin"]), faces=c["faces"], confidence=0.95)
        elif c["kind"] == "irad":
            feat(type="internal_radius", label="Internal radius / fillet", r=c["r"], length=c["t1"] - c["t0"], axis=axis_name(c["axis"]), faces=c["faces"], confidence=0.9)
        elif c["kind"] == "orad":
            feat(type="external_round", label="External round", r=c["r"], length=c["t1"] - c["t0"], axis=axis_name(c["axis"]), faces=c["faces"], confidence=0.9)
    free_cones = [c for c in cones if c["i"] not in used_faces]
    if free_cones:
        feat(type="cone", label="Conical faces (chamfers / tapers)", count=len(free_cones), faces=[c["i"] for c in free_cones], confidence=0.85)

    # ---- recess floors: planar faces below the top in their normal direction, reachable from outside
    groups: dict[tuple, dict] = {}
    for p in planes:
        if p["i"] in used_faces:
            continue
        sd = signed_dir(p["n"])
        if not sd:
            continue
        ci = "XYZ".index(sd[1])
        sgn = 1 if sd[0] == "+" else -1
        top = hi[ci] if sgn > 0 else -lo[ci]
        depth = top - sgn * p["centroid"][ci]
        if depth < 0.05:
            continue
        if rc.first_hit(add(p["centroid"], scl(p["n"], 1e-3)), p["n"]):
            continue  # a wall of a cavity, not an accessible floor
        key = (sd, round(depth, 2))
        g2 = groups.setdefault(key, {"dir": sd, "depth": depth, "faces": [], "lo": [1e9] * 3, "hi": [-1e9] * 3, "open": 0})
        g2["faces"].append(p["i"])
        for k in range(3):
            g2["lo"][k] = min(g2["lo"][k], p["lo"][k])
            g2["hi"][k] = max(g2["hi"][k], p["hi"][k])
    for g2 in groups.values():
        ci = "XYZ".index(g2["dir"][1])
        others = [k for k in range(3) if k != ci]
        touches = sum((abs(g2["lo"][k] - lo[k]) < 0.05) + (abs(g2["hi"][k] - hi[k]) < 0.05) for k in others)
        w = sorted(g2["hi"][k] - g2["lo"][k] for k in others)
        if touches == 0:
            kind = "slot" if w[1] / max(w[0], 1e-6) > 2.5 else "pocket"
        else:
            kind = "step" if touches >= 3 else "open_pocket"
        label = {"pocket": "Pocket (closed)", "slot": "Slot / keyway (closed)", "step": "Step / shoulder", "open_pocket": "Open pocket / slot"}[kind]
        feat(type=kind, label=label, depth=g2["depth"], floor=w, dir=g2["dir"], faces=g2["faces"], confidence=0.8)

    angled = [p for p in planes if not signed_dir(p["n"])]
    if angled:
        feat(type="angled", label="Angled flat faces (chamfers / compound angles)", count=len(angled), faces=[p["i"] for p in angled], confidence=0.85)
    freeform = [r for r in recs if r["type"] in ("freeform", "torus", "sphere")]
    if freeform:
        feat(type="freeform", label="Freeform / toroidal / spherical faces", count=len(freeform), faces=[r["i"] for r in freeform], confidence=0.8)

    # ---- accessibility: undercuts = faces not visible from any principal direction
    access_dirs = set()
    undercut_faces = []
    for r in recs:
        if r["area"] < 1e-3:
            continue
        f = faces[r["i"]]
        reachable = False
        for nm, d in DIRS6:
            for q, nn in face_samples(f, 4):
                if dot(nn, d) < -0.02:
                    continue  # faces away from this approach direction
                start = add(q, scl(nn, 0.02))  # just off the surface, in air
                if not rc.first_hit(start, d, tmin=1e-4):
                    reachable = True
                    access_dirs.add(nm)
                    break
            if reachable:
                break
        if not reachable:
            undercut_faces.append(r["i"])
    if undercut_faces:
        feat(type="undercut", label="Undercut / hidden faces (not reachable from ±X ±Y ±Z)", count=len(undercut_faces), faces=undercut_faces, confidence=0.8)
        flags.append({"sev": "high", "code": "undercut", "text": f"{len(undercut_faces)} face(s) not reachable from any principal direction: undercut tooling, 5-axis or EDM"})

    # ---- wall thickness (ray sampling into material)
    min_wall = None
    samples = 0
    for r in recs:
        if r["type"] not in ("plane", "cyl") or r["area"] < 1.0:
            continue
        f = faces[r["i"]]
        for q, nn in face_samples(f, 8):
            inward = scl(nn, -1)
            h = rc.first_hit(add(q, scl(inward, 1e-3)), inward)
            samples += 1
            if not h:
                continue
            hq, hn = None, None
            try:
                hf = h[1]
                hu0, hu1, hv0, hv1 = BRepTools.UVBounds_s(hf)
                _, hn = face_point_normal(hf, (hu0 + hu1) / 2, (hv0 + hv1) / 2)
            except Exception:
                hn = None
            if hn is not None and BRepAdaptor_Surface(h[1], True).GetType() == GeomAbs_Plane and dot(hn, nn) > -0.95:
                continue
            if min_wall is None or h[0] < min_wall["t"]:
                min_wall = {"t": h[0], "at": list(q), "face": r["i"]}
    if min_wall and min_wall["t"] < 2.0:
        flags.append({"sev": "high" if min_wall["t"] < 1.0 else "medium", "code": "thin_wall", "text": f"Thin wall ≈ {min_wall['t']:.2f} mm (ray sampled)"})

    irads = [f["r"] for f in features if f["type"] == "internal_radius"]
    min_irad = min(irads) if irads else None
    if min_irad is not None and min_irad < 1.0:
        flags.append({"sev": "medium", "code": "small_radius", "text": f"Small internal radius R{min_irad:.2f} needs ≤ Ø{2*min_irad:.2f} end mill"})
    for f in features:
        if f["type"] in ("pocket", "slot", "open_pocket") and min_irad:
            ratio = f["depth"] / (2 * min_irad)
            if ratio > 4:
                flags.append({"sev": "high" if ratio > 8 else "medium", "code": "deep_pocket", "text": f"Deep {f['label'].lower()} {f['depth']:.1f} mm with R{min_irad:.2f} corners: tool L/D ≈ {ratio:.1f}", "feature": f["id"]})

    # ---- turned-part indicator
    bosses = [c for c in cyls if c["kind"] == "boss"]
    turned = None
    if bosses:
        big = max(bosses, key=lambda c: c["r"])
        coax = [c for c in cyls if abs(dot(c["axis"], big["axis"])) > 0.9999 and dist_to_axis(c["origin"], big["origin"], big["axis"]) < 0.02]
        perp = [p for p in planes if abs(dot(p["n"], big["axis"])) > 0.9999]
        rot_area = sum(recs[i]["area"] for c in coax for i in c["faces"]) + sum(p["area"] for p in perp)
        cone_area = sum(c["area"] for c in cones if abs(dot(c["axis"], big["axis"])) > 0.9999)
        turned = {"axis": axis_name(big["axis"]), "ratio": (rot_area + cone_area) / area if area else 0, "max_dia": 2 * big["r"],
                  "length": extent_along(big["axis"])[1] - extent_along(big["axis"])[0]}

    signed = {f["dir"] for f in features if f.get("dir")}
    for f in features:
        if f["type"] == "hole" and not any(s[1] == f["axis"] for s in signed):
            signed.add("+" + f["axis"])
    is_turned = bool(turned and turned["ratio"] > 0.7)
    mill_dirs = [s for s in signed if not (is_turned and s[1] == turned["axis"])]
    setups = (2 if is_turned else 0) + max(0 if is_turned else 2, len(mill_dirs)) + (1 if angled else 0)

    return {
        "name": name, "size": size, "bbox_min": list(lo), "bbox_max": list(hi), "volume": volume, "area": area,
        "faces": len(faces), "edges": count(shape, TopAbs_EDGE), "solids": count(shape, TopAbs_SOLID),
        "features": features, "flags": flags, "min_wall": min_wall, "wall_samples": samples,
        "min_internal_radius": min_irad, "turned": turned, "access_dirs": sorted(access_dirs),
        "angled_faces": len(angled), "freeform_faces": len(freeform), "undercut_faces": len(undercut_faces),
        "setups": min(8, setups), "face_types": [r["type"] for r in recs],
    }


def corners_of(p):
    lo, hi = p["lo"], p["hi"]
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


# ------------------------------------------------------------------ display mesh
def mesh(shape, deflection=None) -> dict:
    lo, hi = bbox(shape)
    diag = length(sub(hi, lo)) or 1.0
    BRepMesh_IncrementalMesh(shape, deflection or diag * 0.0008, False, 0.3, True)
    pos: list[float] = []
    idx: list[int] = []
    ranges = []
    for fi, face in enumerate(faces_of(shape)):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        start = len(idx) // 3
        if tri is not None:
            trsf = loc.Transformation()
            base = len(pos) // 3
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                pos += [round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)]
            rev = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                idx += [base + a - 1, base + (c if rev else b) - 1, base + (b if rev else c) - 1]
        ranges.append([start, len(idx) // 3 - 1])
    return {"positions": pos, "indices": idx, "faces": ranges}


# ------------------------------------------------------------------ purchased-part heuristics
PURCHASED_PATTERNS = [
    r"\bISO[\s_-]?(4762|4014|4017|4032|7380|10642|2338|8734|7089|7090)\b", r"\bDIN[\s_-]?(912|931|933|934|125|7991|6325|7984|471|472)\b",
    r"\b(SHCS|BHCS|FHCS|SCREW|BOLT|NUT|WASHER|BEARING|BUSHING|DOWEL|PIN|SPRING|CIRCLIP|RETAINING|O-?RING|INSERT|HELICOIL|STANDOFF|GROMMET|KEY\b)",
    r"\b\d{4,5}[A-Z]\d{2,4}\b",  # McMaster-style part numbers
    r"\bMISUMI\b", r"\b(6[0-9]{3}|60[0-9]{2})-?2?RS\b",
]


def purchased_guess(name: str) -> tuple[bool, str]:
    for pat in PURCHASED_PATTERNS:
        m = re.search(pat, name.upper())
        if m:
            return True, f"name matches '{m.group(0)}'"
    return False, ""


def analyze_step(path: str, with_mesh: bool = True) -> dict:
    """Analyze a STEP file (single part or assembly)."""
    data = read_step(path)
    out = {"assembly": data["assembly"], "header": data["header"], "tree": tree_to_dict(data["tree"]), "parts": []}
    import os
    stem = os.path.splitext(os.path.basename(path))[0]
    for name, entry in data["parts"].items():
        if not data["assembly"] and (not name or re.search(r"open cascade|step translator|^unnamed$|^part$", name, re.I)):
            name = stem
        shape = entry["shape"]
        if shape is None or shape.IsNull():
            continue
        purchased, why = purchased_guess(name)
        a = analyze_shape(shape, name)
        a["qty_per_assembly"] = entry["qty"]
        a["purchased_guess"] = purchased
        a["purchased_reason"] = why
        if with_mesh:
            a["mesh"] = mesh(shape)
        out["parts"].append(a)
    return out
