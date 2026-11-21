import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, Inbox, Paperclip, Plus, RefreshCw, Upload } from "lucide-react";
import { api, fmtDate } from "../api";
import { Badge, Empty, Modal, STATUS, toast, useAsync } from "../components/ui";
import { useMe } from "../App";

const TABS = [["new,estimating", "Open"], ["new", "New"], ["estimating", "Estimating"], ["quoted", "Quoted"], ["won", "Won"], ["lost", "Lost"], ["", "All"]];

export default function Queue() {
  const [tab, setTab] = useState("new,estimating");
  const [q, setQ] = useState("");
  const [show, setShow] = useState(false);
  const me = useMe();
  const list = useAsync(() => api.get(`/rfqs?${new URLSearchParams({ ...(tab ? { status: tab } : {}), ...(q ? { q } : {}) })}`), [tab, q]);
  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">RFQ queue</h1>
        {!me?.integrations?.graph && !me?.integrations?.imap && <Badge tone="amber">Mailbox not connected: upload emails or files</Badge>}
        <div className="ml-auto flex gap-2">
          <input className="input !w-64" placeholder="Search customer, RFQ, part number" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          <button className="btn" onClick={list.reload} aria-label="Refresh"><RefreshCw size={14} /></button>
          <button className="btn btn-primary" onClick={() => setShow(true)}><Plus size={14} /> New RFQ</button>
        </div>
      </div>
      <div className="mb-3 flex gap-1">{TABS.map(([v, l]) => <button key={l} onClick={() => setTab(v)} className={`rounded-md px-3 py-1.5 text-sm ${tab === v ? "bg-navy-700 text-white" : "text-steel-600 hover:bg-steel-100"}`}>{l}</button>)}</div>
      <div className="card overflow-x-auto">
        <table className="w-full">
          <thead><tr><th className="th">RFQ</th><th className="th">Customer</th><th className="th">Subject</th><th className="th">Received</th><th className="th">Quote due</th><th className="th">Parts priced</th><th className="th">Status</th></tr></thead>
          <tbody>
            {(list.data || []).map((r: any) => (
              <tr key={r.id} className="cursor-pointer hover:bg-navy-50/50">
                <td className="td"><Link to={`/rfq/${r.id}`} className="font-mono text-navy-700 hover:underline">{r.number || <span className="font-sans text-xs italic text-steel-500">Unassigned</span>}</Link></td>
                <td className="td"><div className="font-medium">{r.customer_name || "—"}</div><div className="text-xs text-steel-500">{r.customer_contact}</div></td>
                <td className="td max-w-[340px]"><Link to={`/rfq/${r.id}`} className="line-clamp-2">{r.subject}</Link>
                  <div className="mt-0.5 flex gap-2 text-xs text-steel-500"><span className="inline-flex items-center gap-0.5"><Paperclip size={11} />{r.attachments}</span>
                    {r.warnings > 0 && <span className="inline-flex items-center gap-0.5 text-amber-700"><AlertTriangle size={11} />{r.warnings} to check</span>}</div></td>
                <td className="td whitespace-nowrap text-steel-600">{fmtDate(r.created_at)}</td>
                <td className="td whitespace-nowrap">{r.due_date || "—"}</td>
                <td className="td num">{r.analysis_status === "done" ? `${r.priced}/${r.parts}` : <Badge tone={r.analysis_status === "error" ? "red" : "gray"}>{r.analysis_status === "error" ? "Analysis error" : "Analysing…"}</Badge>}</td>
                <td className="td"><Badge tone={STATUS[r.status]?.tone}>{STATUS[r.status]?.label || r.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && !list.data.length && <Empty icon={<Inbox size={36} />} title="No RFQs here">New RFQs arrive from the quoting mailbox, or upload an email (.eml / .msg) or drawings and STEP files.</Empty>}
        {list.loading && !list.data && <p className="p-6 text-sm text-steel-500">Loading…</p>}
      </div>
      {show && <NewRfq onClose={() => setShow(false)} />}
    </div>
  );
}

function NewRfq({ onClose }: { onClose: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const f = useRef<Record<string, string>>({});
  const pick = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const submit = async () => {
    setBusy(true);
    const fd = new FormData();
    files.forEach((x) => fd.append("files", x));
    Object.entries(f.current).forEach(([k, v]) => fd.append(k, v));
    try {
      const r = await api.form("/rfqs", fd);
      toast(r.length > 1 ? `Created ${r.length} RFQs` : "RFQ created");
      onClose(); nav(`/rfq/${r[0].id}`);
    } catch (e: any) { toast(e.message); setBusy(false); }
  };
  const set = (k: string) => (e: any) => (f.current[k] = e.target.value);
  return (
    <Modal title="New RFQ" onClose={onClose} wide footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || (!files.length && !f.current.subject)} onClick={submit}>{busy ? "Analysing…" : "Create and analyse"}</button></>}>
      <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); setFiles([...files, ...Array.from(e.dataTransfer.files)]); }}
        className={`mb-4 rounded-lg border-2 border-dashed p-6 text-center text-sm ${over ? "border-navy-600 bg-navy-50" : "border-steel-300"}`}>
        <Upload className="mx-auto mb-2 text-steel-400" />
        <p>Drop the customer's email (<b>.eml</b> or Outlook <b>.msg</b>), or drawings (PDF, DXF, PNG) and models (STEP, ZIP)</p>
        <button className="btn btn-sm mt-2" onClick={() => pick.current?.click()}>Choose files</button>
        <input ref={pick} type="file" multiple className="hidden" onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])])} />
        {files.length > 0 && <ul className="mt-3 text-left text-xs">{files.map((x, i) => <li key={i} className="flex justify-between border-t border-steel-100 py-1"><span>{x.name}</span><span className="text-steel-500">{(x.size / 1024).toFixed(0)} KB</span></li>)}</ul>}
      </div>
      <p className="mb-2 text-xs text-steel-500">For loose files (no email), add what you know. Emails are read automatically.</p>
      <div className="grid grid-cols-2 gap-3">
        <div><label className="label" htmlFor="n-c">Customer</label><input id="n-c" className="input" onChange={set("customer_name")} /></div>
        <div><label className="label" htmlFor="n-e">Customer email</label><input id="n-e" className="input" onChange={set("customer_email")} /></div>
        <div><label className="label" htmlFor="n-s">Subject</label><input id="n-s" className="input" onChange={set("subject")} /></div>
        <div><label className="label" htmlFor="n-q">Quantities</label><input id="n-q" className="input" placeholder="e.g. 25, 100, 500" onChange={set("quantities")} /></div>
        <div className="col-span-2"><label className="label" htmlFor="n-n">Notes (material, finish, due date…)</label><textarea id="n-n" className="input" rows={3} onChange={set("notes")} /></div>
      </div>
    </Modal>
  );
}
