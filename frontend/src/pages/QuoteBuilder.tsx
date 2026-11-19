import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileDown, Trophy, XCircle } from "lucide-react";
import { api, money } from "../api";
import { Badge, toast, useAsync } from "../components/ui";
import { useMe } from "../App";

type Line = { part_id: string; part_number: string; revision: string; version_id: string; qty: number; include: boolean; lead_time: string };

export default function QuoteBuilder() {
  const { id } = useParams();
  const me = useMe();
  const cur = me?.shop?.currency || "USD";
  const r = useAsync(() => api.get(`/rfqs/${id}`), [id]);
  const [lines, setLines] = useState<Line[]>([]);
  const [notes, setNotes] = useState("Prices in " + cur + ", per part, ex-works. Lead times are from receipt of order (ARO) and confirmed at order.");
  const [days, setDays] = useState(30);
  const [out, setOut] = useState<any>(null);
  useEffect(() => {
    if (!r.data) return;
    const ls: Line[] = [];
    for (const p of r.data.parts.filter((x: any) => x.kind === "machined" && x.versions?.length)) {
      const v = p.versions[0];
      for (const b of v.breaks) ls.push({ part_id: p.id, part_number: p.part_number, revision: p.revision, version_id: v.id, qty: b.qty, include: true, lead_time: b.lead_weeks ? `${b.lead_weeks} weeks ARO` : "" });
    }
    setLines(ls);
  }, [r.data]);
  if (!r.data) return <p className="p-8 text-steel-500">Loading…</p>;
  const parts = r.data.parts.filter((x: any) => x.kind === "machined");
  const priceOf = (l: Line) => parts.find((p: any) => p.id === l.part_id)?.versions.find((v: any) => v.id === l.version_id)?.breaks.find((b: any) => b.qty === l.qty)?.unit_price;
  const included = lines.filter((l) => l.include);
  const missing = included.filter((l) => priceOf(l) == null);
  const finalize = async () => {
    try {
      const o = await api.post(`/rfqs/${id}/finalize`, { lines: included.map((l) => ({ version_id: l.version_id, qty: l.qty, lead_time: l.lead_time })), valid_days: days, notes });
      setOut(o); toast(`Quote ${o.quote_number} created`); r.reload();
    } catch (e: any) { toast(e.message); }
  };
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <Link to={`/rfq/${id}`} className="mb-3 inline-flex items-center gap-1 text-sm text-steel-500 hover:text-navy-700"><ArrowLeft size={14} /> {r.data.number}</Link>
      <h1 className="mb-1 text-xl font-semibold">Customer quote</h1>
      <p className="mb-5 text-sm text-steel-500">The customer sees only part number, revision, quantity, price per part and lead time. Choose which variant and quantities to include.</p>
      <div className="card mb-5 overflow-x-auto">
        <table className="w-full"><thead><tr><th className="th w-10"></th><th className="th">Part number</th><th className="th">Rev</th><th className="th">Variant</th><th className="th text-right">Qty</th><th className="th text-right">Price per part</th><th className="th text-right">Extended</th><th className="th">Lead time</th></tr></thead>
          <tbody>{lines.map((l, i) => { const p = parts.find((x: any) => x.id === l.part_id); const price = priceOf(l);
            return <tr key={i} className={l.include ? "" : "opacity-50"}>
              <td className="td"><input type="checkbox" checked={l.include} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, include: e.target.checked } : x)))} aria-label="Include line" /></td>
              <td className="td font-medium">{l.part_number}</td><td className="td">{l.revision || "—"}</td>
              <td className="td"><select className="input !w-auto !py-0.5 text-xs" value={l.version_id} onChange={(e) => {
                const v = p.versions.find((x: any) => x.id === e.target.value);
                const keep = v.breaks.some((b: any) => b.qty === l.qty) ? l.qty : v.breaks[0].qty;
                const lw = v.breaks.find((b: any) => b.qty === keep)?.lead_weeks;
                setLines(lines.map((x, j) => (j === i ? { ...x, version_id: v.id, qty: keep, lead_time: lw ? `${lw} weeks ARO` : x.lead_time } : x)));
              }}>{p.versions.map((v: any) => <option key={v.id} value={v.id}>v{v.number} · {v.label}</option>)}</select></td>
              <td className="td num text-right">{l.qty.toLocaleString()}</td>
              <td className="td num text-right font-semibold">{price == null ? <Badge tone="amber">needs input</Badge> : money(price, cur)}</td>
              <td className="td num text-right">{price == null ? "—" : money(price * l.qty, cur)}</td>
              <td className="td"><input className="input !w-40 !py-0.5 text-xs" value={l.lead_time} aria-label="Lead time" onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, lead_time: e.target.value } : x)))} /></td></tr>; })}</tbody></table>
        {!lines.length && <p className="p-6 text-sm text-steel-500">No priced parts yet.</p>}
      </div>
      <div className="mb-5 grid gap-4 md:grid-cols-[1fr_160px]">
        <div><label className="label" htmlFor="nt">Notes on the quote</label><textarea id="nt" className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        <div><label className="label" htmlFor="vd">Valid for (days)</label><input id="vd" type="number" className="input" value={days} onChange={(e) => setDays(+e.target.value)} /></div>
      </div>
      {missing.length > 0 && <p className="mb-3 text-sm text-amber-800">{missing.length} line(s) can't be priced yet: open the part and enter its envelope.</p>}
      <div className="flex gap-2"><button className="btn btn-primary" disabled={!included.length || missing.length > 0} onClick={finalize}>Create quote</button>
        {out && <button className="btn" onClick={() => api.open(`/outputs/${out.id}/pdf`).catch((e) => toast(e.message))}><FileDown size={14} /> Open PDF</button>}</div>
      {out && <div className="card mt-6 p-4"><div className="mb-2 font-semibold">Quote {out.quote_number} created · valid until {out.valid_until}</div>
        <p className="mb-3 text-sm text-steel-500">Included versions are now final; use Save As on the part to make changes. Record the result when the customer decides:</p>
        <div className="flex gap-2"><button className="btn" onClick={async () => { await api.post(`/rfqs/${id}/outcome`, { outcome: "won" }); toast("Marked won; added to history"); }}><Trophy size={14} /> Won</button>
          <button className="btn" onClick={async () => { await api.post(`/rfqs/${id}/outcome`, { outcome: "lost" }); toast("Marked lost; added to history"); }}><XCircle size={14} /> Lost</button></div></div>}
    </div>
  );
}
