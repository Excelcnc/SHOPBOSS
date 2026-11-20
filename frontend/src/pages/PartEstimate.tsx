import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Copy, History, RotateCcw, ShieldCheck } from "lucide-react";
import { api, DEMO, money } from "../api";
import { Badge, Conf, Modal, Src, toast, useAsync } from "../components/ui";
import Viewer3D from "../components/Viewer3D";
import DrawingView from "../components/DrawingView";
import { useMe } from "../App";

const AskClaude = DEMO ? lazy(() => import("../demo/AskClaude")) : null;

const GROUPS: [string, string][] = [["lead", "Lead time"], ["geometry", "Geometry"], ["material", "Material"], ["time", "Time"], ["process", "Process"], ["complexity", "Complexity"], ["rates", "Rates"], ["outside", "Outside processes"], ["purchased", "Purchased"], ["pricing", "Pricing"], ["price", "Final unit price"]];
const MACHINES = [["mill3", "3-axis mill"], ["mill4", "4-axis mill"], ["mill5", "5-axis mill"], ["lathe", "Lathe"], ["millturn", "Mill-turn"], ["lathe+mill3", "Lathe + 3-axis mill"]];

export default function PartEstimate() {
  const { id, pid } = useParams();
  const me = useMe();
  const cur = me?.shop?.currency || "USD";
  const rfq = useAsync(() => api.get(`/rfqs/${id}`), [id]);
  const part = rfq.data?.parts.find((p: any) => p.id === pid);
  const quote = useAsync(() => (part?.quote_id ? api.get(`/quotes/${part.quote_id}`) : Promise.resolve(null)), [part?.quote_id]);
  const shop = useAsync(() => api.get("/shop"), []);
  const similar = useAsync(() => api.get(`/parts/${pid}/similar`), [pid]);
  const [vid, setVid] = useState<string | null>(null);
  const [view, setView] = useState<"3d" | "drawing">("3d");
  const [hlFeature, setHlFeature] = useState<string | null>(null);
  const [selCallout, setSelCallout] = useState<string | null>(null);
  const [saveAs, setSaveAs] = useState(false);
  const [busy, setBusy] = useState(false);
  const versions = quote.data?.versions || [];
  const v = versions.find((x: any) => x.id === vid) || versions[0];
  useEffect(() => { if (part && !part.has_mesh && part.drawing_attachment_id) setView("drawing"); }, [part?.id]);

  const replaceVersion = (nv: any) => quote.setData({ ...quote.data, versions: versions.map((x: any) => (x.id === nv.id ? nv : x)) });
  const patch = async (body: any) => {
    setBusy(true);
    try { replaceVersion(await api.patch(`/versions/${v.id}`, body)); } catch (e: any) { toast(e.message); } finally { setBusy(false); }
  };
  const features = part?.cad?.features || [];
  const items = part?.drawing?.items || [];
  const meta = part?.drawing?.meta || {};
  const hlFaces = useMemo(() => (features.find((f: any) => f.id === hlFeature)?.faces || []), [hlFeature, features]);
  const drawingAtt = rfq.data?.attachments.find((a: any) => a.id === part?.drawing_attachment_id);
  if (!rfq.data || !part) return <p className="p-8 text-steel-500">{rfq.error || "Loading…"}</p>;
  const R = v?.result;
  const final = v?.status !== "draft";

  return (
    <div className="px-6 py-5">
      <Link to={`/rfq/${id}`} className="mb-2 inline-flex items-center gap-1 text-sm text-steel-500 hover:text-navy-700"><ArrowLeft size={14} /> {rfq.data.number} · {rfq.data.customer_name}</Link>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{part.part_number}</h1>{part.revision && <Badge>Rev {part.revision}</Badge>}
        <span className="text-sm text-steel-500">{part.description}</span>
        <span className="text-sm text-steel-500">{part.cad?.size && part.cad.size.map((x: number) => x.toFixed(2)).join(" × ") + " mm"}</span>
        {part.match?.score > 0 && <span className="text-xs text-steel-500" title={(part.match.why || []).join("; ")}>model ↔ drawing match <Conf v={part.match.score} /></span>}
      </div>
      {part.warnings?.length > 0 && <div className="mb-4 space-y-1 rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">{part.warnings.map((w: string, i: number) => <div key={i} className="flex gap-2"><AlertTriangle size={14} className="mt-0.5 flex-none" />{w}</div>)}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,1fr)]">
        {/* ------------------------------------------------ left: model, drawing, features */}
        <div className="min-w-0 space-y-5">
          <div className="card overflow-hidden">
            <div className="flex border-b border-steel-200 text-sm">
              {[["3d", "3D model", part.has_mesh], ["drawing", "Drawing", !!drawingAtt]].map(([k, l, ok]: any) => (
                <button key={k} disabled={!ok} onClick={() => setView(k)} className={`px-4 py-2 font-medium ${view === k ? "border-b-2 border-navy-700 text-navy-700" : "text-steel-500"} disabled:opacity-40`}>{l}</button>))}
            </div>
            <div className="h-[460px]">
              {view === "3d" && part.has_mesh && <Viewer3D partId={part.id} features={features} highlight={hlFaces} />}
              {view === "drawing" && drawingAtt && <DrawingView attachmentId={drawingAtt.id} ext={drawingAtt.ext} selected={selCallout}
                boxes={[...items.map((i: any) => ({ id: i.id, bbox: i.bbox, page: i.page })), ...Object.entries(meta).map(([k, m]: any) => ({ id: "M:" + k, bbox: m.bbox, page: m.page }))]} />}
              {!part.has_mesh && !drawingAtt && <p className="p-6 text-sm text-steel-500">No model or drawing for this part.</p>}
            </div>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <section className="card">
              <h2 className="border-b border-steel-200 px-4 py-2.5 text-sm font-semibold">Recognised features <span className="font-normal text-steel-500">(click to highlight)</span></h2>
              <div className="max-h-80 overflow-y-auto">
                {features.length ? <table className="w-full"><tbody>{features.map((f: any) => (
                  <tr key={f.id} onClick={() => { setView("3d"); setHlFeature(hlFeature === f.id ? null : f.id); }} className={`cursor-pointer text-sm ${hlFeature === f.id ? "bg-orange-50" : "hover:bg-steel-50"}`}>
                    <td className="td font-mono text-xs text-steel-400">{f.id}</td>
                    <td className="td">{f.label}{f.detail && <div className="text-xs text-steel-500">{f.detail}</div>}</td>
                    <td className="td num whitespace-nowrap text-right">{f.dia ? `Ø${f.dia.toFixed(3)}` : f.r ? `R${f.r.toFixed(2)}` : f.floor ? f.floor.map((x: number) => x.toFixed(1)).join("×") : f.count ? `${f.count} faces` : ""}
                      <div className="text-xs text-steel-500">{f.thru ? "THRU" : f.depth != null ? `↧ ${f.depth.toFixed(2)}` : ""} {f.axis || f.dir || ""}</div></td></tr>))}</tbody></table>
                  : <p className="p-4 text-sm text-steel-500">No 3D model, so no geometry features.</p>}
              </div>
              {part.cad?.flags?.length > 0 && <div className="space-y-1 border-t border-steel-200 px-4 py-2 text-xs">{part.cad.flags.map((f: any, i: number) => <div key={i} className={f.sev === "high" ? "text-red-700" : "text-amber-700"}>⚠ {f.text}</div>)}</div>}
            </section>
            <section className="card">
              <h2 className="border-b border-steel-200 px-4 py-2.5 text-sm font-semibold">Drawing callouts</h2>
              <div className="max-h-80 overflow-y-auto">
                <table className="w-full"><tbody>
                  {Object.entries(meta).map(([k, m]: any) => <tr key={k} onClick={() => { setView("drawing"); setSelCallout("M:" + k); }} className={`cursor-pointer text-sm ${selCallout === "M:" + k ? "bg-orange-50" : "hover:bg-steel-50"}`}>
                    <td className="td text-xs text-steel-500">{k.replace(/_/g, " ")}</td><td className="td">{m.value}</td><td className="td"><Src s={m.src} /></td></tr>)}
                  {items.filter((i: any) => i.cat !== "note").map((i: any) => <tr key={i.id} onClick={() => { setView("drawing"); setSelCallout(i.id); }} className={`cursor-pointer text-sm ${selCallout === i.id ? "bg-orange-50" : "hover:bg-steel-50"}`}>
                    <td className="td text-xs text-steel-500">{i.label}{i.critical && <Badge tone="red">critical</Badge>}</td>
                    <td className="td font-mono text-xs">{i.qty > 1 ? `${i.qty}× ` : ""}{i.value} {i.tol || ""}</td><td className="td whitespace-nowrap"><Src s={i.src} /> {i.conf < 0.6 && <Badge tone="amber">verify</Badge>}</td></tr>)}
                </tbody></table>
                {!items.length && !Object.keys(meta).length && <p className="p-4 text-sm text-steel-500">No drawing callouts read. {drawingAtt && !part.drawing?.has_text && "This drawing has no text layer; enable AI extraction or read it manually."}</p>}
              </div>
            </section>
          </div>
          <SimilarJobs data={similar.data} cur={cur} />
          {AskClaude && v && <Suspense fallback={null}><AskClaude part={part} version={v} cur={cur} /></Suspense>}
        </div>

        {/* ------------------------------------------------ right: cost panel */}
        <div className="min-w-0">
          {!v ? <div className="card p-6 text-sm text-steel-500">{part.kind === "purchased" ? "Purchased component: add its cost on the assembly quote." : "No estimate yet."}</div> : (
            <div className="card sticky top-4">
              <div className="flex flex-wrap items-center gap-2 border-b border-steel-200 px-4 py-3">
                <select className="input !w-auto" value={v.id} onChange={(e) => setVid(e.target.value)} aria-label="Quote version">
                  {versions.map((x: any) => <option key={x.id} value={x.id}>v{x.number} · {x.label}{x.status !== "draft" ? " (final)" : ""}</option>)}</select>
                <button className="btn btn-sm" onClick={() => setSaveAs(true)}><Copy size={13} /> Save as…</button>
                {busy && <span className="text-xs text-steel-500">Recalculating…</span>}
                {final && <Badge tone="navy">Final, read-only</Badge>}
              </div>
              <div className="space-y-4 px-4 py-3">
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="label" htmlFor="mat">Material</label>
                    <select id="mat" className="input" disabled={final} value={v.inputs.material?.code || ""} onChange={(e) => patch({ material_code: e.target.value })}>
                      {!v.inputs.material?.code && <option value="">Unknown (priced as SS316)</option>}
                      {(shop.data?.materials || []).map((m: any) => <option key={m.code} value={m.code}>{m.name}</option>)}</select>
                    <div className="mt-1 text-[11px] text-steel-500">{part.material_source?.origin && `Detected from ${part.material_source.origin}. `}{v.inputs.material?.price_source}</div></div>
                  <Quantities q={v.inputs.quantities} disabled={final} onChange={(quantities) => patch({ quantities })} />
                </div>
                <table className="w-full">
                  <thead><tr><th className="th">Qty</th><th className="th text-right">Price / part</th><th className="th text-right">Extended</th><th className="th text-right">Hrs / part</th><th className="th text-right">Lead time</th></tr></thead>
                  <tbody>{R.breaks.map((b: any) => <tr key={b.qty}><td className="td num">{b.qty.toLocaleString()}</td>
                    <td className="td num text-right text-base font-semibold">{b.unit_price == null ? <Badge tone="amber">enter envelope</Badge> : money(b.unit_price, cur)}</td>
                    <td className="td num text-right">{money(b.extended, cur)}</td><td className="td num text-right text-steel-500">{b.unit_price == null ? "—" : b.hours_per_part.toFixed(2)}</td>
                    <td className="td num text-right" title={R.lines.find((l: any) => l.key === `lead.weeks.${b.qty}`)?.note}>{b.lead_weeks} wk</td></tr>)}</tbody>
                </table>
                <Breakdown R={R} cur={cur} />
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-md bg-steel-50 p-3"><div className="text-xs text-steel-500">Suggested machine (reference only)</div><div className="font-semibold">{R.machine.label}</div><div className="text-xs text-steel-500">{R.machine.why}</div></div>
                  <div className="rounded-md bg-steel-50 p-3"><div className="text-xs text-steel-500">Complexity</div><div className="font-semibold">{R.complexity.score} / 10 <span className="font-normal text-steel-500">× {R.complexity.multiplier} time</span></div>
                    <div className="text-xs text-steel-500">{R.complexity.drivers.slice(0, 3).map((d: any) => d[0]).join(" · ")}</div></div>
                </div>
                {(R.adjustments.length > 0 || R.warnings.length > 0) && <div className="space-y-1 rounded-md border border-navy-100 bg-navy-50 p-3 text-xs text-navy-900">
                  <div className="flex items-center gap-1 font-semibold"><ShieldCheck size={13} /> Margin protection</div>
                  {R.adjustments.map((a: string, i: number) => <div key={i}>• {a}</div>)}{R.warnings.map((a: string, i: number) => <div key={"w" + i} className="text-amber-800">⚠ {a}</div>)}</div>}
                <Overrides lines={R.lines} disabled={final} cur={cur} onSet={(k, val, reason) => patch({ overrides: { [k]: val }, reason })} />
                <Processes v={v} shop={shop.data} disabled={final} onChange={(processes) => patch({ processes })} />
              </div>
            </div>
          )}
        </div>
      </div>
      {saveAs && v && <SaveAs onClose={() => setSaveAs(false)} onSave={async (label) => { const nv = await api.post(`/versions/${v.id}/save-as`, { label }); quote.setData({ ...quote.data, versions: [...versions, nv] }); setVid(nv.id); setSaveAs(false); toast(`Saved as v${nv.number}`); }} />}
    </div>
  );
}

function Quantities({ q, onChange, disabled }: { q: number[]; onChange: (q: number[]) => void; disabled: boolean }) {
  const [t, setT] = useState("");
  return (
    <div><label className="label" htmlFor="qty-add">Quantities</label>
      <div className="flex flex-wrap items-center gap-1">{q.map((x) => <span key={x} className="inline-flex items-center gap-1 rounded bg-navy-50 px-2 py-0.5 text-xs font-medium text-navy-800">{x}
        {!disabled && q.length > 1 && <button aria-label={`Remove ${x}`} onClick={() => onChange(q.filter((y) => y !== x))}>×</button>}</span>)}
        {!disabled && <input id="qty-add" className="input !w-20 !py-0.5" placeholder="+ qty" value={t} onChange={(e) => setT(e.target.value.replace(/\D/g, ""))}
          onKeyDown={(e) => { if (e.key === "Enter" && +t > 0) { onChange([...q, +t]); setT(""); } }} />}</div></div>
  );
}

function Breakdown({ R, cur }: { R: any; cur: string }) {
  const [open, setOpen] = useState(false);
  const rows = [["material", "Material"], ["machining", "Machining"], ["inspection", "Inspection"], ["setup_programming_per_part", "Setup + programming / part"], ["outside", "Outside processes"], ["purchased", "Purchased"], ["contingency", "Contingency"], ["volume_discount_pct", "Volume discount %"]];
  return (
    <div><button className="text-xs font-medium text-navy-700 hover:underline" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} cost breakdown (internal only)</button>
      {open && <table className="mt-2 w-full text-xs"><thead><tr><th className="th">Per part</th>{R.breaks.map((b: any) => <th key={b.qty} className="th text-right">{b.qty}</th>)}</tr></thead>
        <tbody>{rows.map(([k, l]) => <tr key={k}><td className="td">{l}</td>{R.breaks.map((b: any) => <td key={b.qty} className="td num text-right">{k.endsWith("pct") ? `${b[k]}%` : money(b[k], cur)}</td>)}</tr>)}</tbody></table>}</div>
  );
}

function Overrides({ lines, onSet, disabled, cur }: { lines: any[]; onSet: (k: string, v: any, reason: string) => void; disabled: boolean; cur: string }) {
  return (
    <div><h3 className="mb-1 text-sm font-semibold">Calculated values <span className="font-normal text-steel-500">— type to override, ↺ to restore</span></h3>
      {GROUPS.map(([g, gl]) => { const ls = lines.filter((l) => l.group === g); if (!ls.length) return null;
        return <div key={g} className="mb-2"><div className="mb-1 mt-2 text-[11px] font-semibold uppercase tracking-wide text-steel-400">{gl}</div>
          {ls.map((l) => <OverrideRow key={l.key} l={l} disabled={disabled} onSet={onSet} />)}</div>; })}
    </div>
  );
}

function OverrideRow({ l, onSet, disabled }: { l: any; onSet: (k: string, v: any, reason: string) => void; disabled: boolean }) {
  const fmt = (x: any) => (typeof x === "number" ? (Math.abs(x) >= 100 ? x.toFixed(1) : +x.toFixed(4)).toString() : x ?? "");
  const [val, setVal] = useState(fmt(l.value));
  useEffect(() => setVal(fmt(l.value)), [l.value]);
  const commit = () => {
    if (val === fmt(l.value)) return;
    const n = typeof l.computed === "number" ? parseFloat(val) : val;
    if (typeof l.computed === "number" && Number.isNaN(n)) { setVal(fmt(l.value)); return; }
    onSet(l.key, n, "");
  };
  return (
    <div className={`flex items-center gap-2 rounded px-1 py-0.5 text-sm ${l.overridden ? "bg-amber-50" : ""}`} title={l.note}>
      <span className="min-w-0 flex-1 truncate">{l.label}</span>
      {l.overridden && <span className="text-[11px] text-steel-400 line-through" title="Calculated value">{fmt(l.computed)}</span>}
      {l.key === "machine.kind" ? (
        <select className="input !w-40 !py-0.5 text-xs" disabled={disabled} value={l.value} onChange={(e) => onSet(l.key, e.target.value, "")}>{MACHINES.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select>
      ) : (
        <input className={`input ${l.key === "geometry.size_mm" ? "!w-40" : "!w-28"} !py-0.5 text-right font-mono text-xs ${l.overridden ? "!border-amber-400" : ""}`} disabled={disabled} value={val} aria-label={l.label}
          placeholder={l.key === "geometry.size_mm" ? "L x W x H" : ""} onChange={(e) => setVal(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
      )}
      <span className="w-8 text-[11px] text-steel-400">{l.unit}</span>
      <button className="w-5 text-steel-400 hover:text-navy-700 disabled:invisible" disabled={!l.overridden || disabled} onClick={() => onSet(l.key, null, "")} aria-label="Restore calculated value"><RotateCcw size={12} /></button>
    </div>
  );
}

function Processes({ v, shop, onChange, disabled }: { v: any; shop: any; onChange: (p: any[]) => void; disabled: boolean }) {
  const procs = v.inputs.processes || [];
  const [add, setAdd] = useState("");
  return (
    <div><h3 className="mb-1 text-sm font-semibold">Outside processes</h3>
      {procs.length === 0 && <p className="text-xs text-steel-500">None detected.</p>}
      {procs.map((p: any) => <div key={p.name} className="flex items-center gap-2 py-0.5 text-sm"><span className="flex-1">{p.name}{p.unpriced && <Badge tone="amber">placeholder price</Badge>}<span className="ml-1 text-[11px] text-steel-400">{p.source}</span></span>
        {!disabled && <button className="text-xs text-red-700 hover:underline" onClick={() => onChange(procs.filter((x: any) => x.name !== p.name))}>Remove</button>}</div>)}
      {!disabled && <div className="mt-1 flex gap-2"><select className="input !py-0.5 text-xs" value={add} onChange={(e) => setAdd(e.target.value)} aria-label="Add outside process"><option value="">Add a process…</option>
        {(shop?.processes || []).filter((p: any) => !procs.some((x: any) => x.name === p.name)).map((p: any) => <option key={p.id} value={p.name}>{p.name}</option>)}</select>
        <button className="btn btn-sm" disabled={!add} onClick={() => { const p = shop.processes.find((x: any) => x.name === add); onChange([...procs, { ...p, source: "added by estimator" }]); setAdd(""); }}>Add</button></div>}
    </div>
  );
}

function SimilarJobs({ data, cur }: { data: any[] | undefined; cur: string }) {
  return (
    <section className="card">
      <h2 className="flex items-center gap-2 border-b border-steel-200 px-4 py-2.5 text-sm font-semibold"><History size={14} /> Similar past jobs <span className="font-normal text-steel-500">by size, features, material</span></h2>
      {!data?.length ? <p className="p-4 text-sm text-steel-500">No similar jobs yet. Import your JobBOSS² history under Job history.</p> : (
        <table className="w-full"><thead><tr><th className="th">Match</th><th className="th">Part</th><th className="th">Customer</th><th className="th">Material</th><th className="th text-right">Qty</th><th className="th text-right">Price</th><th className="th text-right">Est / act hrs</th><th className="th">Result</th></tr></thead>
          <tbody>{data.map((j) => <tr key={j.id}><td className="td"><Conf v={j.score} /></td><td className="td"><div className="font-medium">{j.part_number} {j.revision}</div><div className="text-xs text-steel-500">{j.date} · {j.kind === "quote" ? "our quote" : "history"}{j.size && ` · ${j.size.map((x: number) => Math.round(x)).join("×")}`}</div></td>
            <td className="td text-xs">{j.customer || "—"}</td><td className="td text-xs">{j.material || "—"}</td><td className="td num text-right">{j.quantity ?? "—"}</td><td className="td num text-right">{money(j.unit_price, cur)}</td>
            <td className="td num text-right text-xs">{j.est_hours ?? "—"} / {j.actual_hours ?? "—"}</td><td className="td">{j.outcome && <Badge tone={j.outcome === "won" ? "green" : "gray"}>{j.outcome}</Badge>}</td></tr>)}</tbody></table>
      )}
    </section>
  );
}

function SaveAs({ onClose, onSave }: { onClose: () => void; onSave: (l: string) => void }) {
  const [l, setL] = useState("");
  return <Modal title="Save as new variant" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={() => onSave(l)}>Save variant</button></>}>
    <p className="mb-3 text-sm text-steel-600">Creates a copy of this estimate (inputs and overrides) so you can change material, quantities or anything else without touching the original.</p>
    <label className="label" htmlFor="sa">Variant name</label><input id="sa" className="input" autoFocus placeholder="e.g. 7075 option, 1,000 pcs" value={l} onChange={(e) => setL(e.target.value)} /></Modal>;
}
