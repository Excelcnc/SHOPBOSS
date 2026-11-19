import { useState } from "react";
import { CheckCircle2, Mail, Plus, RefreshCw, Trash2, XCircle, Zap } from "lucide-react";
import { api } from "../api";
import { Badge, Modal, toast, useAsync } from "../components/ui";

export default function EmailAccounts({ admin }: { admin: boolean }) {
  const list = useAsync(() => api.get("/mailboxes"), []);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const d = list.data;
  const act = async (id: string, what: "test" | "sync") => {
    setBusy(id + what);
    try {
      const r = await api.post(`/mailboxes/${id}/${what}`);
      if (what === "test") setResults({ ...results, [id]: r });
      else { toast(r.last_error ? `Sync failed: ${r.last_error}` : `Checked ${r.address}: ${r.imported} new RFQ(s)`); list.reload(); }
    } catch (e: any) { toast(e.message); } finally { setBusy(null); }
  };
  const update = async (id: string, body: any) => { try { await api.put(`/mailboxes/${id}`, body); list.reload(); } catch (e: any) { toast(e.message); } };
  return (
    <div className="space-y-4">
      <div className="card p-4 text-sm text-steel-600">
        <p>The app checks every connected mailbox and turns customer RFQs into quotes. With <b>RFQ filter</b> on, only emails with a 3D model attached or RFQ wording
          ("RFQ", "request for quote", "please quote"…) are taken, so shared mailboxes like purchasing@ don't fill the queue with invoices or supplier quotes.
          Watching a dedicated folder (e.g. <b>RFQ</b>, filled by an Outlook rule) is the most reliable.</p>
        <p className="mt-2">New mailboxes start from <b>now</b>; set "Import past days" to pull in recent RFQs on the first check.
          {d && (d.webhook ? " Microsoft 365 mailboxes update within seconds." : " Mailboxes are checked every 5 minutes.")}</p>
      </div>
      <div className="card overflow-x-auto">
        <div className="flex items-center border-b border-steel-200 px-4 py-3"><h2 className="font-semibold">Connected email accounts</h2>
          {admin && <button className="btn btn-primary ml-auto" onClick={() => setAdding(true)}><Plus size={14} /> Connect mailbox</button>}</div>
        <table className="w-full">
          <thead><tr><th className="th">Mailbox</th><th className="th">Folder</th><th className="th">RFQ filter</th><th className="th">Status</th><th className="th text-right">RFQs imported</th><th className="th text-right">Skipped</th><th className="th">Active</th><th className="th"></th></tr></thead>
          <tbody>{(d?.mailboxes || []).map((m: any) => (
            <tr key={m.id}>
              <td className="td"><div className="flex items-center gap-2 font-medium"><Mail size={14} className="text-steel-400" />{m.address}</div>
                <div className="text-xs text-steel-500">{m.kind === "graph" ? "Microsoft 365" : `IMAP · ${m.imap_host}`}{m.label && ` · ${m.label}`}{m.instant && <span className="ml-1 inline-flex items-center gap-0.5 text-emerald-700"><Zap size={10} />instant</span>}</div>
                {results[m.id] && <div className={`mt-1 flex items-start gap-1 text-xs ${results[m.id].ok ? "text-emerald-700" : "text-red-700"}`}>{results[m.id].ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}{results[m.id].message}</div>}</td>
              <td className="td"><input className="input !w-28 !py-0.5 text-xs" disabled={!admin} defaultValue={m.folder} aria-label="Folder" onBlur={(e) => e.target.value !== m.folder && update(m.id, { folder: e.target.value })} /></td>
              <td className="td"><input type="checkbox" disabled={!admin} checked={m.filter_rfqs} onChange={(e) => update(m.id, { filter_rfqs: e.target.checked })} aria-label="RFQ filter" /></td>
              <td className="td text-xs">{m.last_error ? <span className="text-red-700">{m.last_error}</span> : m.last_sync_at ? <span className="text-steel-600">Checked {new Date(m.last_sync_at).toLocaleString()}</span> : <Badge>Not checked yet</Badge>}</td>
              <td className="td num text-right">{m.imported}</td><td className="td num text-right text-steel-500">{m.skipped}</td>
              <td className="td"><input type="checkbox" disabled={!admin} checked={m.active} onChange={(e) => update(m.id, { active: e.target.checked })} aria-label="Active" /></td>
              <td className="td whitespace-nowrap">
                {admin && <button className="btn btn-sm" disabled={!!busy} onClick={() => act(m.id, "test")}>{busy === m.id + "test" ? "Testing…" : "Test"}</button>}{" "}
                <button className="btn btn-sm" disabled={!!busy} onClick={() => act(m.id, "sync")}><RefreshCw size={12} /> {busy === m.id + "sync" ? "Checking…" : "Check now"}</button>{" "}
                {admin && <RemoveButton onRemove={async () => { await api.del(`/mailboxes/${m.id}`); toast(`Disconnected ${m.address}`); list.reload(); }} />}</td>
            </tr>))}</tbody>
        </table>
        {d && !d.mailboxes.length && <p className="p-6 text-sm text-steel-500">No mailboxes connected yet. RFQs can still be uploaded as .eml / .msg files.</p>}
      </div>
      {adding && <AddMailbox graphAvailable={!!d?.graph_available} onClose={() => setAdding(false)} onAdded={(r) => { setAdding(false); setResults({ ...results, [r.id]: r.test }); list.reload(); }} />}
    </div>
  );
}

function RemoveButton({ onRemove }: { onRemove: () => void }) {
  const [sure, setSure] = useState(false);
  return sure ? <span className="inline-flex gap-1"><button className="btn btn-sm !border-red-300 text-red-700" onClick={onRemove}>Disconnect</button><button className="btn btn-sm" onClick={() => setSure(false)}>Keep</button></span>
    : <button className="btn btn-sm text-red-700" onClick={() => setSure(true)} aria-label="Disconnect"><Trash2 size={12} /></button>;
}

function AddMailbox({ graphAvailable, onClose, onAdded }: { graphAvailable: boolean; onClose: () => void; onAdded: (r: any) => void }) {
  const [kind, setKind] = useState<"graph" | "imap">(graphAvailable ? "graph" : "imap");
  const [f, setF] = useState<any>({ folder: "RFQ", filter_rfqs: true, backfill_days: 0 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async () => {
    setBusy(true); setErr("");
    try { onAdded(await api.post("/mailboxes", { ...f, kind, backfill_days: +f.backfill_days || 0, imap_port: f.imap_port ? +f.imap_port : undefined })); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title="Connect a mailbox" onClose={onClose} wide footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || !f.address} onClick={save}>{busy ? "Connecting…" : "Connect and test"}</button></>}>
      <div className="mb-4 flex gap-2">
        <button className={`btn ${kind === "graph" ? "btn-primary" : ""}`} disabled={!graphAvailable} onClick={() => setKind("graph")}>Microsoft 365 / Outlook</button>
        <button className={`btn ${kind === "imap" ? "btn-primary" : ""}`} onClick={() => setKind("imap")}>Other provider (IMAP)</button>
      </div>
      {kind === "graph" ? (
        <p className="mb-3 text-sm text-steel-600">Any mailbox in your Microsoft 365 (shared or personal). It uses the CNC Quote mailbox app, so no password is needed,
          but your admin must add the mailbox to the app's access-policy group (docs/M365_SETUP.md, step 4) or the test will say access denied.</p>
      ) : (
        <p className="mb-3 text-sm text-steel-600">Gmail, a web host or any provider with IMAP. Use an <b>app password</b> (Gmail: Google account › Security › App passwords).
          The password is encrypted and never shown again.</p>
      )}
      {!graphAvailable && <p className="mb-3 text-xs text-amber-800">Direct Microsoft 365 connection isn't available for your shop yet. Use IMAP (Gmail, Yahoo, iCloud, most web hosts) with an app password,
        or set a rule in Outlook that forwards RFQs to a mailbox you can connect here.</p>}
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label className="label" htmlFor="mb-a">Email address</label><input id="mb-a" className="input" placeholder="rfq@yourshop.com" onChange={set("address")} /></div>
        <div><label className="label" htmlFor="mb-f">Folder to watch</label><input id="mb-f" className="input" value={f.folder} onChange={set("folder")} />
          <p className="mt-1 text-[11px] text-steel-500">"inbox" or a folder name like "RFQ" (top level or under Inbox).</p></div>
        <div><label className="label" htmlFor="mb-l">Label (optional)</label><input id="mb-l" className="input" placeholder="e.g. Purchasing" onChange={set("label")} /></div>
        {kind === "imap" && <>
          <div><label className="label" htmlFor="mb-h">IMAP server</label><input id="mb-h" className="input" placeholder="imap.gmail.com (guessed if blank)" onChange={set("imap_host")} /></div>
          <div><label className="label" htmlFor="mb-p">Port</label><input id="mb-p" className="input" placeholder="993" onChange={set("imap_port")} /></div>
          <div><label className="label" htmlFor="mb-u">Username</label><input id="mb-u" className="input" placeholder="usually the email address" onChange={set("imap_user")} /></div>
          <div><label className="label" htmlFor="mb-pw">App password</label><input id="mb-pw" type="password" className="input" autoComplete="new-password" onChange={set("imap_password")} /></div>
        </>}
        <div><label className="label" htmlFor="mb-b">Import past days on first check</label><input id="mb-b" type="number" min={0} max={90} className="input" value={f.backfill_days} onChange={set("backfill_days")} /></div>
        <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={f.filter_rfqs} onChange={set("filter_rfqs")} /> Only take emails that look like RFQs</label>
      </div>
      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
    </Modal>
  );
}
