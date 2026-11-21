import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";

type Mesh = { positions: number[]; indices: number[]; faces: [number, number][] };
const BASE = [0.74, 0.77, 0.81], HL = [0.98, 0.5, 0.1];
const KIND: Record<string, number[]> = { hole: [0.27, 0.48, 1.0], internal_radius: [0.92, 0.63, 0.19], groove: [0.85, 0.2, 0.2], undercut: [0.85, 0.2, 0.2] };

export default function Viewer3D({ partId, features, highlight }: { partId: string; features: any[]; highlight: number[] }) {
  const host = useRef<HTMLDivElement>(null);
  const S = useRef<any>({});
  const [status, setStatus] = useState("Loading model…");
  const [section, setSection] = useState<string>("");
  const [secT, setSecT] = useState(0.5);
  const [measure, setMeasure] = useState(false);
  const [meas, setMeas] = useState<string>("");

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    renderer.localClippingEnabled = true;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#e9edf2");
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e6);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8090a0, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 0.8); scene.add(key);
    const clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
    const overlay = new THREE.Group(); scene.add(overlay);
    S.current = { renderer, scene, camera, controls, clip, overlay };
    const ro = new ResizeObserver(() => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); });
    ro.observe(el);
    let dead = false;
    const loop = () => { if (dead) return; requestAnimationFrame(loop); controls.update(); key.position.copy(camera.position); renderer.render(scene, camera); };
    loop();
    api.get<Mesh>(`/parts/${partId}/mesh`).then((m) => {
      if (dead) return;
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(m.positions, 3));
      g.setIndex(m.indices);
      g.computeVertexNormals();
      // non-indexed copy so each face colours independently
      const ng = g.toNonIndexed(); ng.computeVertexNormals();
      ng.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(ng.attributes.position.count * 3), 3));
      const mat = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.2, roughness: 0.55, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      const mesh = new THREE.Mesh(ng, mat);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), new THREE.LineBasicMaterial({ color: "#1d2731", transparent: true, opacity: 0.6 }));
      scene.add(mesh, edges);
      g.computeBoundingBox();
      const bb = g.boundingBox!; const c = bb.getCenter(new THREE.Vector3()); const r = bb.getSize(new THREE.Vector3()).length() / 2 || 1;
      Object.assign(S.current, { mesh, edges, faces: m.faces, center: c, radius: r, bb });
      view("iso"); paint(); setStatus("");
    }).catch((e) => setStatus(String(e.message || e)));
    const ray = new THREE.Raycaster(); let down: number[] | null = null;
    const onDown = (e: PointerEvent) => (down = [e.clientX, e.clientY]);
    const onUp = (e: PointerEvent) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !S.current.measuring || !S.current.mesh) return;
      const r = renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const hit = ray.intersectObject(S.current.mesh)[0]; if (!hit) return;
      const pts: THREE.Vector3[] = (S.current.pts = (S.current.pts || []).length >= 2 ? [] : S.current.pts || []);
      if (!pts.length) overlay.clear();
      pts.push(hit.point.clone());
      const dot = new THREE.Mesh(new THREE.SphereGeometry(S.current.radius * 0.012), new THREE.MeshBasicMaterial({ color: 0xff7a00, depthTest: false })); dot.position.copy(hit.point); dot.renderOrder = 9; overlay.add(dot);
      if (pts.length === 2) {
        overlay.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xff7a00, depthTest: false })));
        const d = pts[0].distanceTo(pts[1]); const dd = pts[1].clone().sub(pts[0]);
        setMeas(`${d.toFixed(3)} mm  (ΔX ${Math.abs(dd.x).toFixed(3)}  ΔY ${Math.abs(dd.y).toFixed(3)}  ΔZ ${Math.abs(dd.z).toFixed(3)})`);
      } else setMeas("Click a second point");
    };
    renderer.domElement.addEventListener("pointerdown", onDown); renderer.domElement.addEventListener("pointerup", onUp);
    return () => { dead = true; ro.disconnect(); renderer.dispose(); el.innerHTML = ""; };
  }, [partId]);

  function view(n: string) {
    const s = S.current; if (!s.center) return;
    const dirs: Record<string, number[]> = { iso: [1, -1.2, 0.9], top: [0, -1e-4, 1], front: [0, -1, 0], right: [1, 0, 0] };
    const d = s.radius * 3.4; const v = new THREE.Vector3(...dirs[n]).normalize().multiplyScalar(d);
    s.controls.target.copy(s.center); s.camera.position.copy(s.center).add(v); s.camera.near = d / 200; s.camera.far = d * 50; s.camera.updateProjectionMatrix();
  }
  function paint() {
    const s = S.current; if (!s.mesh) return;
    const col = s.mesh.geometry.attributes.color; const arr = col.array as Float32Array;
    const kindOf: Record<number, number[]> = {};
    for (const f of features || []) if (KIND[f.type]) for (const fi of f.faces || []) kindOf[fi] = KIND[f.type];
    const hl = new Set(highlight);
    s.faces.forEach(([a, b]: [number, number], fi: number) => {
      const c = hl.has(fi) ? HL : kindOf[fi] || BASE;
      for (let t = a; t <= b; t++) for (let k = 0; k < 3; k++) { const v = (t * 3 + k) * 3; arr[v] = c[0]; arr[v + 1] = c[1]; arr[v + 2] = c[2]; }
    });
    col.needsUpdate = true;
    if (highlight.length && s.bb) { // focus
      const box = new THREE.Box3(); const p = s.mesh.geometry.attributes.position; const v = new THREE.Vector3();
      for (const fi of highlight) { const [a, b] = s.faces[fi] || [0, -1]; for (let t = a; t <= b; t++) for (let k = 0; k < 3; k++) box.expandByPoint(v.fromBufferAttribute(p, t * 3 + k)); }
      if (!box.isEmpty()) { const c = box.getCenter(new THREE.Vector3()); const dir = s.camera.position.clone().sub(s.controls.target).normalize(); s.controls.target.copy(c); s.camera.position.copy(c).add(dir.multiplyScalar(Math.max(s.radius * 0.6, box.getSize(new THREE.Vector3()).length() * 1.4) * 2.4)); }
    }
  }
  useEffect(paint, [highlight, features]);
  useEffect(() => {
    const s = S.current; if (!s.mesh) return;
    const mats = [s.mesh.material, s.edges.material];
    if (!section) mats.forEach((m: any) => { m.clippingPlanes = []; m.needsUpdate = true; });
    else { const i = "xyz".indexOf(section); const n = [0, 0, 0]; n[i] = -1; const lo = s.bb.min.getComponent(i), hi = s.bb.max.getComponent(i);
      s.clip.set(new THREE.Vector3(...n), lo + (hi - lo) * secT); mats.forEach((m: any) => { m.clippingPlanes = [s.clip]; m.needsUpdate = true; }); }
  }, [section, secT]);
  useEffect(() => { S.current.measuring = measure; S.current.pts = []; S.current.overlay?.clear(); setMeas(measure ? "Click two points on the model" : ""); }, [measure]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b border-steel-200 bg-white px-2 py-1.5 text-xs">
        {["iso", "top", "front", "right"].map((v) => <button key={v} className="btn btn-sm" onClick={() => view(v)}>{v[0].toUpperCase() + v.slice(1)}</button>)}
        <span className="mx-1 h-4 w-px bg-steel-200" />
        <button className={`btn btn-sm ${measure ? "btn-primary" : ""}`} onClick={() => setMeasure(!measure)}>Measure</button>
        <label className="ml-1 flex items-center gap-1">Section
          <select className="input !w-auto !py-0.5 text-xs" value={section} onChange={(e) => setSection(e.target.value)} aria-label="Section plane">
            <option value="">Off</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></label>
        {section && <input type="range" min={0} max={1} step={0.01} value={secT} onChange={(e) => setSecT(+e.target.value)} aria-label="Section position" />}
        <span className="ml-auto flex gap-2 text-steel-500"><Sw c="#457aff" l="Holes" /><Sw c="#eba130" l="Radii" /><Sw c="#d93333" l="Undercut" /><Sw c="#fa801a" l="Selected" /></span>
      </div>
      <div className="relative min-h-[320px] flex-1"><div ref={host} className="absolute inset-0" />
        {(status || meas) && <div className="absolute bottom-2 left-2 rounded bg-white/90 px-2 py-1 text-xs shadow">{status || meas}</div>}</div>
    </div>
  );
}
const Sw = ({ c, l }: { c: string; l: string }) => <span className="inline-flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>;
