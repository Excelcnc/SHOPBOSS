import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { api, money } from "../api";
import { Badge, toast, useAsync } from "../components/ui";
import { useMe } from "../App";
import EmailAccounts from "./EmailAccounts";
import Team from "./Team";

const KINDS = [["mill3", "3-axis mill"], ["mill4", "4-axis mill"], ["mill5", "5-axis mill"], ["lathe", "Lathe"], ["millturn", "Mill-turn"]];
const POLICY: [string, string, string][] = [["margin_pct", "Margin", "%"], ["contingency_pct", "Contingency (always applied)", "%"], ["uncertainty_pct_per_item", "Extra time per uncertain item", "%"],
  ["uncertainty_cap_pct", "Uncertainty cap", "%"], ["material_scrap_pct", "Material scrap / kerf", "%"], ["stock_allowance_mm", "Stock allowance per side (milling)", "mm"],
  ["min_order_charge", "Minimum order charge", "$"], ["setup_hours_per_setup", "Setup hours per setup", "h"], ["programming_base_hours", "Programming base", "h"],
  ["first_article_hours", "First-article inspection per lot", "h"], ["time_calibration_factor", "Time calibration factor", "×"], ["lead_queue_days", "Lead time: queue before start", "days"], ["lead_material_days", "Lead time: material arrival", "days"],
  ["lead_hours_per_day", "Lead time: machine hours per day for one job", "h"], ["lead_outside_buffer_days", "Lead time: shipping to outside processors", "days"], ["material_price_stale_days", "Warn when material price older than", "days"]];

export default function Settings() {
  const me = useMe();
  const admin = me?.role === "admin";
  const s = useAsync(() => api.get("/shop"), []);
  const loc = useLocation();
  const [tab, setTab] = useState(new URLSearchParams(loc.search).get("tab") || "email");
  if (!s.data) return <p className="p-8 text-steel-500">Loading…</p>;
  const d = s.data, cur = d.currency;
  const save = async (fn: () => Promise<any>) => { try { await fn(); toast("Saved"); s.reload(); } catch (e: any) { toast(e.message); } };
  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-1 text-xl font-semibold">Shop settings</h1>
      <p className="mb-4 text-sm text-steel-500">{admin ? "Changes apply to new estimates and to Re-calculate on drafts." : "Only shop admins can change settings."}</p>
      <div className="mb-4 flex flex-wrap gap-1">{[["email", "Email accounts"], ["team", "Team"], ["rates", "Rates"], ["machines", "Machines"], ["materials", "Materials"], ["processes", "Outside processes"], ["policy", "Pricing policy"]].map(([k, l]) =>
        <button key={k} onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 text-sm ${tab === k ? "bg-navy-700 text-white" : "text-steel-600 hover:bg-steel-100"}`}>{l}</button>)}</div>

      {tab === "email" && <EmailAccounts admin={admin} />}
      {tab === "team" && <Team admin={admin} />}

      {tab === "rates" && <div className="card overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Rate</th><th className="th">Key</th><th className="th text-right">{cur} / hour</th><th className="th"></th></tr></thead>
        <tbody>{d.rates.map((r: any) => <tr key={r.id}><td className="td">{r.name}</td><td className="td font-mono text-xs text-steel-500">{r.key}</td>
          <td className="td text-right"><input className="input !w-28 text-right font-mono" disabled={!admin} defaultValue={r.rate_per_hour} aria-label={r.name}
            onBlur={(e) => +e.target.value !== r.rate_per_hour && save(() => api.put(`/shop/rates/${r.id}`, { rate_per_hour: +e.target.value }))} /></td>
          <td className="td">{admin && !["milling", "turning", "setup", "programming", "inspection"].includes(r.key) && <button className="text-red-700" onClick={() => save(() => api.del(`/shop/rates/${r.id}`))} aria-label="Delete"><Trash2 size={14} /></button>}</td></tr>)}</tbody></table>
        {admin && <AddRow fields={[["name", "Name"], ["key", "Key (e.g. edm)"], ["rate_per_hour", "Rate"]]} onAdd={(v) => save(() => api.post("/shop/rates", { ...v, rate_per_hour: +v.rate_per_hour }))} />}</div>}

      {tab === "machines" && <div className="card overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Machine</th><th className="th">Type</th><th className="th">Rate</th><th className="th">Travel / capacity (mm)</th><th className="th">Active</th><th className="th"></th></tr></thead>
        <tbody>{d.machines.map((m: any) => <tr key={m.id}><td className="td">{m.name}</td><td className="td">{KINDS.find((k) => k[0] === m.kind)?.[1]}</td>
          <td className="td"><select className="input !w-auto !py-0.5 text-xs" disabled={!admin} value={m.rate_key} onChange={(e) => save(() => api.put(`/shop/machines/${m.id}`, { rate_key: e.target.value }))}>{d.rates.map((r: any) => <option key={r.key} value={r.key}>{r.name}</option>)}</select></td>
          <td className="td"><input className="input !w-40 font-mono text-xs" disabled={!admin} defaultValue={(m.travel_mm || []).join(" x ")} aria-label="Travel"
            onBlur={(e) => save(() => api.put(`/shop/machines/${m.id}`, { travel_mm: (e.target.value.match(/\d+(\.\d+)?/g) || []).map(Number) }))} /></td>
          <td className="td"><input type="checkbox" disabled={!admin} checked={m.active} onChange={(e) => save(() => api.put(`/shop/machines/${m.id}`, { active: e.target.checked }))} aria-label="Active" /></td>
          <td className="td">{admin && <button className="text-red-700" onClick={() => save(() => api.del(`/shop/machines/${m.id}`))} aria-label="Delete"><Trash2 size={14} /></button>}</td></tr>)}</tbody></table>
        {admin && <AddRow fields={[["name", "Name"], ["kind", "Type: mill3 / mill4 / mill5 / lathe / millturn"], ["travel_mm", "Travel e.g. 762 x 406 x 508"]]}
          onAdd={(v) => save(() => api.post("/shop/machines", { name: v.name, kind: v.kind, rate_key: { mill3: "milling", mill4: "milling4", mill5: "milling5", lathe: "turning", millturn: "millturn" }[v.kind as string] || "milling", travel_mm: (v.travel_mm.match(/\d+(\.\d+)?/g) || []).map(Number) }))} />}</div>}

      {tab === "materials" && <div className="card overflow-x-auto"><p className="border-b border-steel-200 px-4 py-2 text-xs text-steel-500">Reference prices are a starting point, not live market data. Enter your supplier's price per kg; estimates warn when a price gets stale.</p>
        <table className="w-full"><thead><tr><th className="th">Material</th><th className="th">Family</th><th className="th text-right">Density</th><th className="th text-right">Machinability</th><th className="th text-right">{cur} / kg</th><th className="th">Source</th></tr></thead>
          <tbody>{d.materials.map((m: any) => <tr key={m.code}><td className="td"><div className="font-medium">{m.name}</div><div className="text-[11px] text-steel-400">{m.code} · {m.aliases.slice(0, 4).join(", ")}</div></td>
            <td className="td text-xs">{m.family}</td><td className="td num text-right">{m.density_g_cm3}</td><td className="td num text-right">{m.machinability}</td>
            <td className="td text-right"><input className="input !w-24 text-right font-mono" disabled={!admin} defaultValue={m.price_per_kg} aria-label={`${m.name} price`}
              onBlur={(e) => +e.target.value !== m.price_per_kg && save(() => api.put(`/shop/material-prices/${m.code}`, { price_per_kg: +e.target.value }))} /></td>
            <td className="td text-xs">{m.price_source.startsWith("shop") ? <Badge tone="green">Your price</Badge> : <Badge>Reference</Badge>} {m.price_stale && <Badge tone="amber">stale</Badge>}</td></tr>)}</tbody></table></div>}

      {tab === "processes" && <div className="card overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Process</th><th className="th">Supplier</th><th className="th">Basis</th><th className="th text-right">Price</th><th className="th text-right">Lot charge</th><th className="th text-right">Markup %</th><th className="th">Detect words</th><th className="th"></th></tr></thead>
        <tbody>{d.processes.map((p: any) => <tr key={p.id}><td className="td font-medium">{p.name}</td>
          {(["supplier", "basis", "price", "lot_charge", "markup_pct"] as const).map((k) => <td key={k} className="td">
            {k === "basis" ? <select className="input !w-auto !py-0.5 text-xs" disabled={!admin} value={p.basis} onChange={(e) => save(() => api.put(`/shop/processes/${p.id}`, { basis: e.target.value }))}>
              {[["per_part", "per part"], ["per_kg", "per kg"], ["per_dm2", "per dm²"], ["per_lot", "per lot"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
              : <input className={`input !py-0.5 text-xs ${k === "supplier" ? "!w-36" : "!w-20 text-right font-mono"}`} disabled={!admin} defaultValue={p[k]} aria-label={k}
                onBlur={(e) => String(p[k]) !== e.target.value && save(() => api.put(`/shop/processes/${p.id}`, { [k]: k === "supplier" ? e.target.value : +e.target.value }))} />}</td>)}
          <td className="td text-[11px] text-steel-500">{p.keywords.join(", ")}</td>
          <td className="td">{admin && <button className="text-red-700" onClick={() => save(() => api.del(`/shop/processes/${p.id}`))} aria-label="Delete"><Trash2 size={14} /></button>}</td></tr>)}</tbody></table>
        {admin && <AddRow fields={[["name", "Process name"], ["keywords", "Detect words, comma separated"], ["price", "Price"], ["lot_charge", "Lot charge"]]}
          onAdd={(v) => save(() => api.post("/shop/processes", { name: v.name, keywords: v.keywords.split(",").map((x: string) => x.trim().toUpperCase()).filter(Boolean), basis: "per_part", price: +v.price || 0, lot_charge: +v.lot_charge || 0, markup_pct: 15 }))} />}</div>}

      {tab === "policy" && <div className="card p-4"><p className="mb-4 text-sm text-steel-500">How the engine protects margin. Raising contingency or uncertainty makes every estimate more conservative.</p>
        <div className="grid gap-3 md:grid-cols-2">{POLICY.map(([k, l, u]) => <div key={k} className="flex items-center gap-2"><label className="flex-1 text-sm" htmlFor={k}>{l}</label>
          <input id={k} className="input !w-24 text-right font-mono" disabled={!admin} defaultValue={d.settings[k]} onBlur={(e) => +e.target.value !== d.settings[k] && save(() => api.put("/shop", { settings: { [k]: +e.target.value } }))} /><span className="w-8 text-xs text-steel-500">{u}</span></div>)}</div>
        <h3 className="mb-2 mt-6 text-sm font-semibold">Volume discounts <span className="font-normal text-steel-500">(on machining, setup and programming only)</span></h3>
        <table><tbody>{d.settings.volume_tiers.map((t: any, i: number) => <tr key={i}><td className="td">From {t.min_qty} pcs</td><td className="td">{t.discount_pct}%</td></tr>)}</tbody></table>
        <p className="mt-1 text-xs text-steel-500">Edit tiers via the API for now (PUT /api/shop settings.volume_tiers).</p></div>}
    </div>
  );
}

function AddRow({ fields, onAdd }: { fields: [string, string][]; onAdd: (v: Record<string, any>) => void }) {
  const [v, setV] = useState<Record<string, string>>({});
  return <div className="flex flex-wrap items-end gap-2 border-t border-steel-200 px-4 py-3">{fields.map(([k, l]) => <div key={k}><label className="label" htmlFor={"add-" + k}>{l}</label><input id={"add-" + k} className="input !w-48" value={v[k] || ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></div>)}
    <button className="btn" disabled={!v[fields[0][0]]} onClick={() => { onAdd(v); setV({}); }}><Plus size={14} /> Add</button></div>;
}
