import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { api, money } from "../api";
import { Badge, Empty, toast, useAsync } from "../components/ui";
import { useMe } from "../App";

export default function History() {
  const me = useMe();
  const cur = me?.shop?.currency || "USD";
  const list = useAsync(() => api.get("/history"), []);
  const cal = useAsync(() => api.get("/history/calibration"), []);
  const pick = useRef<HTMLInputElement>(null);
  const [last, setLast] = useState<any>(null);
  const upload = async (f: File) => {
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api.form("/history/import", fd); setLast(r); toast(`Imported ${r.imported} jobs`); list.reload(); cal.reload(); } catch (e: any) { toast(e.message); }
  };
  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-4 flex items-center gap-3"><h1 className="text-xl font-semibold">Job history</h1>
        {me?.role === "admin" && <button className="btn btn-primary ml-auto" onClick={() => pick.current?.click()}><Upload size={14} /> Import CSV</button>}
        <input ref={pick} type="file" accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></div>
      <div className="mb-5 grid gap-4 md:grid-cols-2">
        <div className="card p-4 text-sm"><h2 className="mb-1 font-semibold">Import from JobBOSS²</h2>
          <p className="text-steel-600">Export quotes or jobs to CSV (part, revision, customer, quantity, unit price, estimated and actual hours, material, date, status). Column names are matched automatically.
            Add Length, Width and Height columns (mm) if you have them: they power the size-based similar-job search.</p>
          {last && <p className="mt-2 text-xs text-steel-500">Last import: {last.imported} rows. Columns used: {Object.entries(last.mapping).map(([k, v]) => `${k} ← ${v}`).join(", ")}</p>}</div>
        <div className="card p-4 text-sm"><h2 className="mb-1 font-semibold">Calibration</h2>
          {cal.data && (cal.data.samples ? <p>Engine vs actual hours on {cal.data.samples} jobs: median ratio {cal.data.median_ratio}, 75th percentile {cal.data.p75_ratio}. Suggested time calibration factor <b>{cal.data.suggested_factor}</b> (Shop settings › Pricing policy).</p>
            : <p className="text-steel-600">{cal.data.jobs_with_actuals} imported jobs have actual hours. {cal.data.message}</p>)}</div>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full"><thead><tr><th className="th">Part</th><th className="th">Customer</th><th className="th">Material</th><th className="th text-right">Qty</th><th className="th text-right">Unit price</th><th className="th text-right">Est hrs</th><th className="th text-right">Actual hrs</th><th className="th">Result</th><th className="th">Date</th><th className="th">Source</th></tr></thead>
          <tbody>{(list.data || []).map((h: any) => <tr key={h.id}><td className="td font-medium">{h.part_number} <span className="text-steel-500">{h.revision}</span></td><td className="td">{h.customer}</td><td className="td text-xs">{h.material}</td>
            <td className="td num text-right">{h.quantity}</td><td className="td num text-right">{money(h.unit_price, cur)}</td><td className="td num text-right">{h.est_hours ?? "—"}</td><td className="td num text-right">{h.actual_hours ?? "—"}</td>
            <td className="td">{h.outcome && <Badge tone={h.outcome === "won" ? "green" : "gray"}>{h.outcome}</Badge>}</td><td className="td text-xs">{h.date}</td><td className="td text-xs text-steel-500">{h.source}</td></tr>)}</tbody></table>
        {list.data && !list.data.length && <Empty title="No history yet">Import a CSV from JobBOSS², or finish quotes and record won/lost: they're added automatically.</Empty>}
      </div>
    </div>
  );
}
