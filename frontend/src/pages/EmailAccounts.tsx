import { useEffect, useState } from "react";
import { CheckCircle2, Mail, Plus, RefreshCw, Trash2, XCircle, Zap } from "lucide-react";
import { api } from "../api";
import { Badge, Modal, toast, useAsync } from "../components/ui";

export default function EmailAccounts({ admin }: { admin: boolean }) {
  const list = useAsync(() => api.get("/mailboxes"), []);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {  // back from "Connect with Microsoft"
    const q = new URLSearchParams(location.search);
    if (q.get("ms_connected")) setNotice({ ok: true, text: `Connected ${q.get("ms_connected")}. New RFQs will appear in the queue.` });
    else if (q.get("ms_error")) setNotice({ ok: false, text: q.get("ms_error")! });
    if (q.get("ms_connected") || q.get("ms_error")) history.replaceState(null, "", "/settings?tab=email");
  }, []);
  const reconnect = async (m: any) => {
    try { location.href = (await api.post("/mailboxes/microsoft/start", { address: m.address, folder: m.folder, label: m.label, filter_rfqs: m.filter_rfqs, reconnect_id: m.id })).url; }
    catch (e: any) { toast(e.message); }
  };
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
      {notice && <div className={`card flex items-start gap-2 p-4 text-sm ${notice.ok ? "text-emerald-800" : "text-red-800"}`} role="status">
        {notice.ok ? <CheckCircle2 size={16} className="mt-0.5 flex-none" /> : <XCircle size={16} className="mt-0.5 flex-none" />}<span>{notice.text}</span></div>}
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
                <div className="text-xs text-steel-500">{m.kind === "msoauth" ? `Microsoft · signed in as ${m.connected_as}` : m.kind === "graph" ? "Microsoft 365 (company app)" : `IMAP · ${m.imap_host}`}{m.label && ` · ${m.label}`}{m.instant && <span className="ml-1 inline-flex items-center gap-0.5 text-emerald-700"><Zap size={10} />instant</span>}</div>
                {results[m.id] && <div className={`mt-1 flex items-start gap-1 text-xs ${results[m.id].ok ? "text-emerald-700" : "text-red-700"}`}>{results[m.id].ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}{results[m.id].message}</div>}</td>
              <td className="td"><input className="input !w-28 !py-0.5 text-xs" disabled={!admin} defaultValue={m.folder} aria-label="Folder" onBlur={(e) => e.target.value !== m.folder && update(m.id, { folder: e.target.value })} /></td>
              <td className="td"><input type="checkbox" disabled={!admin} checked={m.filter_rfqs} onChange={(e) => update(m.id, { filter_rfqs: e.target.checked })} aria-label="RFQ filter" /></td>
              <td className="td text-xs">{m.last_error ? <span className="text-red-700">{m.last_error}</span> : m.last_sync_at ? <span className="text-steel-600">Checked {new Date(m.last_sync_at).toLocaleString()}</span> : <Badge>Not checked yet</Badge>}</td>
              <td className="td num text-right">{m.imported}</td><td className="td num text-right text-steel-500">{m.skipped}</td>
              <td className="td"><input type="checkbox" disabled={!admin} checked={m.active} onChange={(e) => update(m.id, { active: e.target.checked })} aria-label="Active" /></td>
              <td className="td whitespace-nowrap">
                {admin && m.kind === "msoauth" && <><button className="btn btn-sm" onClick={() => reconnect(m)}>Reconnect</button>{" "}</>}
                {admin && <button className="btn btn-sm" disabled={!!busy} onClick={() => act(m.id, "test")}>{busy === m.id + "test" ? "Testing…" : "Test"}</button>}{" "}
                <button className="btn btn-sm" disabled={!!busy} onClick={() => act(m.id, "sync")}><RefreshCw size={12} /> {busy === m.id + "sync" ? "Checking…" : "Check now"}</button>{" "}
                {admin && <RemoveButton onRemove={async () => { await api.del(`/mailboxes/${m.id}`); toast(`Disconnected ${m.address}`); list.reload(); }} />}</td>
            </tr>))}</tbody>
        </table>
        {d && !d.mailboxes.length && <p className="p-6 text-sm text-steel-500">No mailboxes connected yet. RFQs can still be uploaded as .eml / .msg files.</p>}
      </div>
      {adding && <AddMailbox graphAvailable={!!d?.graph_available} msConnect={!!d?.ms_connect} onClose={() => setAdding(false)} onAdded={(r) => { setAdding(false); setResults({ ...results, [r.id]: r.test }); list.reload(); }} />}
    </div>
  );
}

function RemoveButton({ onRemove }: { onRemove: () => void }) {
  const [sure, setSure] = useState(false);
  return sure ? <span className="inline-flex gap-1"><button className="btn btn-sm !border-red-300 text-red-700" onClick={onRemove}>Disconnect</button><button className="btn btn-sm" onClick={() => setSure(false)}>Keep</button></span>
    : <button className="btn btn-sm text-red-700" onClick={() => setSure(true)} aria-label="Disconnect"><Trash2 size={12} /></button>;
}

function AddMailbox({ graphAvailable, msConnect, onClose, onAdded }: { graphAvailable: boolean; msConnect: boolean; onClose: () => void; onAdded: (r: any) => void }) {
  const [kind, setKind] = useState<"ms" | "graph" | "imap">(msConnect ? "ms" : graphAvailable ? "graph" : "imap");
  const [f, setF] = useState<any>({ folder: "RFQ", filter_rfqs: true, backfill_days: 0 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async () => {
    setBusy(true); setErr("");
    try {
      if (kind === "ms") {
        const r = await api.post("/mailboxes/microsoft/start", { address: f.address || "", folder: f.folder, label: f.label || "", filter_rfqs: f.filter_rfqs, backfill_days: +f.backfill_days || 0 });
        location.href = r.url;  // Microsoft sign-in; comes back to this page
        return;
      }
      onAdded(await api.post("/mailboxes", { ...f, kind, backfill_days: +f.backfill_days || 0, imap_port: f.imap_port ? +f.imap_port : undefined }));
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const tab = (k: typeof kind, label: string, show: boolean) => show && <button className={`btn ${kind === k ? "btn-primary" : ""}`} onClick={() => setKind(k)}>{label}</button>;
  return (
    <Modal title="Connect a mailbox" onClose={onClose} wide footer={<><button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || (kind !== "ms" && !f.address)} onClick={save}>{busy ? "Connecting…" : kind === "ms" ? "Sign in with Microsoft" : "Connect and test"}</button></>}>
      <div className="mb-4 flex flex-wrap gap-2">
        {tab("ms", "Microsoft 365 / Outlook", msConnect)}
        {tab("graph", "Microsoft 365 (company app)", graphAvailable)}
        {tab("imap", "Gmail, Yahoo & others (IMAP)", true)}
      </div>
      {kind === "ms" && <div className="mb-3 space-y-2 text-sm text-steel-600">
        <p>You'll sign in with Microsoft and allow CNC Quote to <b>read</b> mail. Nothing for your IT admin to run.</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>Your own mailbox:</b> leave the address empty.</li>
          <li><b>A shared mailbox</b> such as sales@ or purchasing@: type its address, then sign in as someone who can already open it in Outlook.</li>
        </ul>
        <p className="text-xs text-steel-500">Some companies require an admin to approve new apps the first time; Microsoft will say so if needed.</p></div>}
      {kind === "graph" && <p className="mb-3 text-sm text-steel-600">Uses your company's CNC Quote mailbox app (no sign-in). The mailbox must be in the app's
        access-policy group ("CNC Quote mailboxes"), or the test will say access denied.</p>}
      {kind === "imap" && <p className="mb-3 text-sm text-steel-600">Gmail, Yahoo, iCloud, a web host or any provider with IMAP. Use an <b>app password</b>
        (Gmail: Google account › Security › 2-Step Verification › App passwords). The password is encrypted and never shown again.</p>}
      {!msConnect && !graphAvailable && <p className="mb-3 text-xs text-amber-800">Microsoft sign-in isn't set up on this server yet. Use IMAP, or set an Outlook rule that forwards RFQs to a mailbox you can connect here.</p>}
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label className="label" htmlFor="mb-a">Email address{kind === "ms" && " (empty = your own mailbox)"}</label>
          <input id="mb-a" className="input" placeholder={kind === "ms" ? "e.g. sales@yourshop.com" : "rfq@yourshop.com"} onChange={set("address")} /></div>
        <div><label className="label" htmlFor="mb-f">Folder to watch</label><input id="mb-f" className="input" value={f.folder} onChange={set("folder")} />
          <p className="mt-1 text-[11px] text-steel-500">"inbox" or a folder name like "RFQ" (top level or under Inbox).</p></div>
        <div><label className="label" htmlFor="mb-l">Label (optional)</label><input id="mb-l" className="input" placeholder="e.g. Sales" onChange={set("label")} /></div>
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
