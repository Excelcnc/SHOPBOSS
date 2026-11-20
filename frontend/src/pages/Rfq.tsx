import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Box, ChevronRight, FileText, Mail, Package, RefreshCw, Send, ShoppingCart } from "lucide-react";
import { api, money } from "../api";
import { Badge, Conf, STATUS, Src, toast, useAsync } from "../components/ui";
import { useMe } from "../App";

const FIELDS: [string, string][] = [["customer_name", "Customer"], ["customer_contact", "Contact"], ["customer_rfq_no", "Customer RFQ #"], ["part_numbers", "Part number(s)"],
  ["revision", "Revision"], ["quantities", "Quantities"], ["material", "Material"], ["special_processes", "Special processes"], ["requirements", "Requirements"], ["due_date", "Delivery"], ["quote_due", "Quote due"]];

export default function Rfq() {
  const { id } = useParams();
  const me = useMe();
  const r = useAsync(() => api.get(`/rfqs/${id}`), [id]);
  const [showMail, setShowMail] = useState(false);
  useEffect(() => { // poll while analysis runs
    if (!r.data || !["pending", "running"].includes(r.data.analysis_status)) return;
    const t = setTimeout(r.reload, 2500); return () => clearTimeout(t);
  }, [r.data]);
  if (!r.data) return <p className="p-8 text-steel-500">{r.error || "Loading…"}</p>;
  const d = r.data, cur = me?.shop?.currency || "USD";
  const machined = d.parts.filter((p: any) => p.kind !== "assembly");
  const asm = d.parts.filter((p: any) => p.kind === "assembly");
  const editField = async (k: string, v: string) => { await api.patch(`/rfqs/${id}`, { fields: { [k]: v } }); r.reload(); };
  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Link to="/" className="mb-3 inline-flex items-center gap-1 text-sm text-steel-500 hover:text-navy-700"><ArrowLeft size={14} /> Queue</Link>
      <div className="mb-5 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1"><div className="font-mono text-sm text-steel-500">{d.number}{d.customer_rfq_no && ` · customer ref ${d.customer_rfq_no}`}</div>
          <h1 className="text-xl font-semibold">{d.customer_name || "Unknown customer"} {(d.email?.subject || d.subject) && <span className="font-normal text-steel-500">— {d.email?.subject || d.subject}</span>}</h1></div>
        <select className="input !w-auto" value={d.status} onChange={async (e) => { await api.patch(`/rfqs/${id}`, { status: e.target.value }); r.reload(); }} aria-label="Status">
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <button className="btn" onClick={async () => { await api.post(`/rfqs/${id}/analyze`); toast("Re-analysing"); r.reload(); }}><RefreshCw size={14} /> Re-analyse</button>
        <Link to={`/rfq/${id}/quote`} className="btn btn-primary"><Send size={14} /> Build quote</Link>
      </div>
      {d.analysis_status !== "done" && <div className={`mb-4 rounded-md px-4 py-2 text-sm ${d.analysis_status === "error" ? "bg-red-50 text-red-800" : "bg-navy-50 text-navy-800"}`}>
        {d.analysis_status === "error" ? `Analysis failed: ${d.analysis_error}` : "Analysing drawings and models…"}</div>}
      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <section className="card">
            <div className="flex items-center border-b border-steel-200 px-4 py-3"><h2 className="font-semibold">Parts to quote</h2><span className="ml-2 text-sm text-steel-500">{machined.filter((p: any) => p.kind === "machined").length} machined{machined.some((p: any) => p.kind === "purchased") && `, ${machined.filter((p: any) => p.kind === "purchased").length} purchased`}</span></div>
            {asm.map((a: any) => <div key={a.id} className="flex items-center gap-2 border-b border-steel-100 bg-steel-50 px-4 py-2 text-sm"><Package size={15} className="text-navy-700" /> Assembly <b>{a.part_number}</b>
              {a.revision && <Badge>Rev {a.revision}</Badge>}<span className="text-steel-500">— {a.drawing_attachment_id ? "make/buy and quantities from the drawing parts list" : "quantities from the 3D model"}; prices below are for assemblies requested × qty per assembly</span></div>)}
            <ul>
              {machined.map((p: any) => {
                const v = p.versions?.[0]; const b = v?.breaks || [];
                return (
                  <li key={p.id} className="border-b border-steel-100 last:border-0">
                    <Link to={p.kind === "machined" ? `/rfq/${id}/part/${p.id}` : "#"} className={`flex items-center gap-4 px-4 py-3 ${p.kind === "machined" ? "hover:bg-navy-50/40" : "cursor-default"}`}>
                      <span className="grid h-10 w-10 flex-none place-items-center rounded-md bg-steel-100 text-steel-500">{p.kind === "purchased" ? <ShoppingCart size={18} /> : p.has_mesh ? <Box size={18} /> : <FileText size={18} />}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{p.part_number || "Unnamed"}</span>{p.revision && <Badge>Rev {p.revision}</Badge>}
                          {p.match?.bom_item && <Badge title="Item number on the drawing parts list">Item {p.match.bom_item}</Badge>}
                          {p.kind === "purchased" && <Badge tone="gray">Purchased × {p.qty_per_parent}</Badge>}
                          {p.parent_part_id && p.kind === "machined" && p.qty_per_parent > 1 && <Badge>× {p.qty_per_parent} per assembly</Badge>}
                          {p.material_code && <Badge tone="blue">{p.material_code}</Badge>}</div>
                        <div className="mt-0.5 text-xs text-steel-500">{p.description || (p.cad?.size ? p.cad.size.map((x: number) => x.toFixed(1)).join(" × ") + " mm" : "")}
                          {p.drawing_attachment_id ? " · drawing matched" : p.kind === "machined" ? " · no drawing" : ""}{p.model_attachment_id ? " · 3D model" : ""}</div>
                        {p.warnings?.length > 0 && <div className="mt-1 flex items-start gap-1 text-xs text-amber-800"><AlertTriangle size={12} className="mt-0.5 flex-none" />{p.warnings[0]}{p.warnings.length > 1 && ` (+${p.warnings.length - 1} more)`}</div>}
                      </div>
                      {p.kind === "machined" && <div className="text-right text-sm">{b.map((x: any) => <div key={x.qty} className="num"><span className="text-steel-500">{x.qty} ×</span> {x.unit_price == null ? <Badge tone="amber">needs input</Badge> : money(x.unit_price, cur)}</div>)}</div>}
                      {p.kind === "purchased" && <div className="text-right text-xs" onClick={(e) => e.preventDefault()}>
                        <div className="mb-0.5 text-steel-500">{p.purchased?.vendor || p.purchased?.reason}</div>
                        <label className="inline-flex items-center gap-1">Cost each <input className="input !w-20 !py-0.5 text-right font-mono" defaultValue={p.purchased?.unit_cost || ""} placeholder="0.00"
                          onBlur={async (e) => { await api.patch(`/parts/${p.id}`, { purchased: { ...p.purchased, unit_cost: +e.target.value || 0 } }); toast("Saved"); }} /></label></div>}
                      {p.kind === "machined" && <ChevronRight size={16} className="text-steel-400" />}
                    </Link>
                  </li>
                );
              })}
              {d.analysis_status === "done" && !machined.length && <li className="px-4 py-6 text-sm text-steel-500">No drawings or models found in this RFQ. Add files with Re-analyse after uploading.</li>}
            </ul>
          </section>
          {d.outputs?.length > 0 && <section className="card p-4"><h2 className="mb-2 font-semibold">Quotes sent</h2>
            {d.outputs.map((o: any) => <div key={o.id} className="flex items-center gap-3 border-t border-steel-100 py-2 text-sm"><span className="font-mono">{o.quote_number}</span><span className="text-steel-500">valid until {o.valid_until}</span>
              <span className="ml-auto num">{money(o.lines.reduce((s: number, l: any) => s + l.extended, 0), cur)}</span>
              <button className="btn btn-sm" onClick={() => api.open(`/outputs/${o.id}/pdf`).catch((e) => toast(e.message))}>PDF</button></div>)}</section>}
          <section className="card p-4"><h2 className="mb-2 font-semibold">Activity</h2>
            <ul className="space-y-1 text-xs text-steel-600">{d.activity.map((a: any, i: number) => <li key={i}><span className="text-steel-400">{new Date(a.at).toLocaleString()}</span> · {a.action}</li>)}</ul></section>
        </div>
        <aside className="space-y-5">
          <section className="card">
            <div className="flex items-center border-b border-steel-200 px-4 py-3"><h2 className="font-semibold">Extracted from the RFQ</h2>
              {d.extracted?.summary?.value && <Badge tone="blue">AI summary</Badge>}</div>
            {d.extracted?.summary?.value && <p className="border-b border-steel-100 px-4 py-2 text-sm">{d.extracted.summary.value}</p>}
            <dl className="divide-y divide-steel-100">
              {FIELDS.map(([k, l]) => { const f = d.extracted?.[k]; const v = Array.isArray(f?.value) ? f.value.join(", ") : f?.value ?? "";
                return <div key={k} className="px-4 py-2"><dt className="flex items-center gap-2 text-xs text-steel-500">{l}<span className="ml-auto flex items-center gap-1">{f && <Src s={f.source} />}{f && <Conf v={f.confidence} />}</span></dt>
                  <dd><input className="w-full rounded border border-transparent px-1 py-0.5 text-sm hover:border-steel-200 focus:border-navy-600 focus:outline-none" defaultValue={String(v)} placeholder="Not found" aria-label={l}
                    onBlur={(e) => e.target.value !== String(v) && editField(k, e.target.value)} />
                    {f?.ambiguous && <div className="text-xs text-amber-700">Unclear in the email — confirm with the customer</div>}</dd></div>; })}
            </dl>
          </section>
          <section className="card">
            <button className="flex w-full items-center gap-2 px-4 py-3 text-left font-semibold" onClick={() => setShowMail(!showMail)}><Mail size={15} /> Original email<span className="ml-auto text-xs font-normal text-steel-500">{showMail ? "Hide" : "Show"}</span></button>
            {showMail && d.email && <div className="border-t border-steel-200 px-4 py-3 text-sm"><div className="text-xs text-steel-500">From {d.email.from} · {new Date(d.email.received_at).toLocaleString()} · via {d.email.mailbox || d.email.source}</div>
              <pre className="mt-2 whitespace-pre-wrap font-sans">{d.email.body}</pre></div>}
            <ul className="border-t border-steel-200 px-4 py-2 text-sm">{d.attachments.map((a: any) => <li key={a.id} className="flex items-center gap-2 py-1"><FileText size={13} className="text-steel-400" />
              <button className="truncate text-navy-700 hover:underline" onClick={() => api.open(`/attachments/${a.id}/file`).catch((e) => toast(e.message))}>{a.filename}</button><span className="ml-auto text-xs text-steel-400">{a.kind}</span></li>)}</ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
