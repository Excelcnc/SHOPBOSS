// In-browser stand-in for the CNC Quote server, used only by the demo build (npm run build:demo).
// Sample RFQs, analysis results, 3D meshes and drawings were recorded from a real server
// (demo/capture.py). Pricing runs through the browser copy of the cost engine, so overrides,
// quantities, materials, Save as and shop-rate changes recalculate exactly as on the server.
// Nothing leaves the browser; a reload starts again from the samples.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { estimate } from "./engine";

type Store = any;
let S: Store | null = null;
let loading: Promise<Store> | null = null;
const listeners = new Set<() => void>();

const clone = <T,>(x: T): T => structuredClone(x);
const now = () => new Date().toISOString();
const uid = () => Math.random().toString(16).slice(2) + Date.now().toString(16);
class ApiError extends Error {}
const fail = (msg: string): never => { throw new ApiError(msg); };
const NEEDS_SERVER = "needs the full app: 3D models and drawings are analysed on the server. In this demo, try the four sample RFQs.";

export function onDemoReset(fn: () => void) { listeners.add(fn); return () => listeners.delete(fn); }

async function load(): Promise<Store> {
  if (S) return S;
  if (!loading) {
    loading = fetch("demo-data.json").then((r) => {
      if (!r.ok) throw new Error(`Demo data didn't load (HTTP ${r.status}).`);
      return r.json();
    }).then((raw) => (S = init(raw)));
  }
  return loading;
}

let pristine: any = null;
function init(raw: any): Store {
  pristine = raw;
  const s = clone(raw);
  // give each version its full engine inputs (the API only shows part of them)
  for (const q of Object.values<any>(s.quote)) for (const v of q.versions) v.inputs = clone(s.engine_inputs[v.id]);
  s.outputs = {} as Record<string, any>;
  s.quoteCount = 0;
  return s;
}

export async function resetDemo() { S = init(pristine); listeners.forEach((f) => f()); }

// ------------------------------------------------------------------ derived views
function catalog() {
  const shop = S.shop;
  return {
    settings: shop.settings, materials: shop.materials, machines: shop.machines.map((m: any) => ({ ...m })),
    rates: Object.fromEntries(shop.rates.map((r: any) => [r.key, r.rate_per_hour])), currency: shop.currency,
  };
}

function versionDict(v: any) {
  const inputs: any = {};
  for (const k of ["material", "quantities", "processes", "purchased", "part"]) inputs[k] = v.inputs[k];
  return { ...v, inputs };
}

function partWithVersions(p: any) {
  const q = p.quote_id ? S.quote[p.quote_id] : null;
  return { ...p, versions: (q?.versions || []).map((v: any) => ({ id: v.id, number: v.number, label: v.label, status: v.status,
    breaks: (v.result.breaks || []).map((b: any) => ({ qty: b.qty, unit_price: b.unit_price, lead_weeks: b.lead_weeks })) })) };
}

function summary(r: any) {
  const priced = r.parts.filter((p: any) => {
    const q = p.quote_id && S.quote[p.quote_id];
    const b = q?.versions?.[0]?.result?.breaks || [];
    return b.length && b[0].unit_price != null;
  }).length;
  const base = S.rfqs.find((x: any) => x.id === r.id) || {};
  return { ...base, status: r.status, customer_name: r.customer_name, customer_contact: r.customer_contact, customer_email: r.customer_email,
    due_date: r.due_date, priced, parts: r.parts.filter((p: any) => p.kind === "machined").length };
}

function detail(r: any) {
  return { ...r, ...summary(r), parts: r.parts.map(partWithVersions), outputs: Object.values<any>(S.outputs).filter((o) => o.rfq_id === r.id).reverse(),
    extracted: r.extracted, email: r.email, attachments: r.attachments, activity: r.activity };
}

function findPart(pid: string) {
  for (const r of Object.values<any>(S.rfq)) { const p = r.parts.find((x: any) => x.id === pid); if (p) return { r, p }; }
  return fail("Part not found");
}
function findVersion(vid: string) {
  for (const q of Object.values<any>(S.quote)) { const v = q.versions.find((x: any) => x.id === vid); if (v) return { q, v }; }
  return fail("Quote version not found");
}
const activity = (r: any, action: string, detail: any = {}) => r.activity.unshift({ action, detail, at: now(), user_id: S.me.id });

function materialInput(code: string | null | undefined) {
  const mats = S.shop.materials;
  const m = mats.find((x: any) => x.code === code);
  if (m) return clone(m);
  const ss = mats.find((x: any) => x.code === "SS316");
  return { ...clone(ss), code: null, price_source: "unknown material: stainless 316 assumed" };
}

function recompute(v: any) { v.result = estimate(v.inputs, v.overrides); v.updated_at = now(); }

function refreshInputs(v: any, materialCode?: string | null) {
  const cat = catalog();
  v.inputs = { ...v.inputs, material: materialInput(materialCode ?? v.inputs.material?.code), rates: cat.rates, machines: cat.machines, settings: cat.settings };
}

// ------------------------------------------------------------------ request handler
export async function demoRequest(method: string, path: string, body?: any): Promise<any> {
  await load();
  const res = route(method, path, body);
  return clone(res);
}

function route(method: string, fullPath: string, b: any): any {
  const [path, qs] = fullPath.split("?");
  const q = new URLSearchParams(qs || "");
  const seg = path.split("/").filter(Boolean);
  const M = method.toUpperCase();
  const is = (m: string, pattern: string) => {
    if (m !== M) return null;
    const p = pattern.split("/").filter(Boolean);
    if (p.length !== seg.length) return null;
    const out: Record<string, string> = {};
    for (let i = 0; i < p.length; i++) { if (p[i].startsWith(":")) out[p[i].slice(1)] = seg[i]; else if (p[i] !== seg[i]) return null; }
    return out;
  };
  let m: Record<string, string> | null;

  if (is("GET", "/me")) return { ...S.me, integrations: { ...S.me.integrations, mailboxes: S.mailboxes.mailboxes.filter((x: any) => x.active).map((x: any) => x.address) } };
  if (is("GET", "/config")) return { dev: true, signup_open: false, signup_domains: [], email_verification: false, microsoft: null };

  // RFQs
  if (is("GET", "/rfqs")) {
    const st = q.get("status"), text = (q.get("q") || "").toLowerCase();
    return Object.values<any>(S.rfq).map((r) => ({ r, s: summary(r) }))
      .filter(({ s }) => !st || st.split(",").includes(s.status))
      .filter(({ r, s }) => !text || (JSON.stringify(s) + " " + r.parts.map((p: any) => p.part_number).join(" ")).toLowerCase().includes(text))
      .sort((a, b2) => (a.s.created_at < b2.s.created_at ? 1 : -1)).map(({ s }) => s);
  }
  if (is("POST", "/rfqs")) return fail("Creating an RFQ from your own files " + NEEDS_SERVER);
  if ((m = is("GET", "/rfqs/:id"))) return detail(S.rfq[m.id] || fail("RFQ not found"));
  if ((m = is("PATCH", "/rfqs/:id"))) {
    const r = S.rfq[m.id] || fail("RFQ not found");
    for (const [k, v] of Object.entries<any>(b || {})) {
      if (k === "fields") for (const [fk, fv] of Object.entries(v)) r.extracted[fk] = { value: fv, confidence: 1, source: "manual", evidence: "edited in demo" };
      else r[k] = v;
    }
    activity(r, "update", b);
    return { ok: true };
  }
  if ((m = is("POST", "/rfqs/:id/analyze"))) return { ok: true };
  if ((m = is("POST", "/rfqs/:id/files"))) return fail("Adding files " + NEEDS_SERVER);
  if ((m = is("DELETE", "/rfqs/:id"))) { delete S.rfq[m.id]; return { ok: true }; }

  // parts
  if ((m = is("GET", "/parts/:id/mesh"))) return S.mesh[m.id] || fail("No 3D model for this part");
  if ((m = is("GET", "/parts/:id/similar"))) return S.similar[m.id] || [];
  if ((m = is("PATCH", "/parts/:id"))) {
    const { r, p } = findPart(m.id);
    Object.assign(p, b);
    if (b.material_code) p.material_source = { code: b.material_code, origin: "estimator", confidence: 1.0 };
    const qq = p.quote_id && S.quote[p.quote_id];
    for (const v of qq?.versions || []) if (v.status === "draft") {
      v.inputs = { ...v.inputs, part: { part_number: p.part_number, revision: p.revision } };
      if (b.processes) v.inputs.processes = b.processes;
      if (b.material_code) refreshInputs(v, b.material_code);
      recompute(v);
    }
    activity(r, "part_update", { part: p.part_number, ...b });
    return p;
  }

  // quotes and versions
  if ((m = is("GET", "/quotes/:id"))) { const qq = S.quote[m.id] || fail("Quote not found"); return { ...qq, versions: qq.versions.map(versionDict) }; }
  if ((m = is("PATCH", "/versions/:id"))) {
    const { v } = findVersion(m.id);
    if (v.status !== "draft") fail("This version is final. Use Save As to make a new variant.");
    if (b.label) v.label = b.label;
    if (b.processes) v.inputs.processes = b.processes;
    if (b.purchased) v.inputs.purchased = b.purchased;
    if (b.material_code || b.refresh_catalog) refreshInputs(v, b.material_code);
    if (b.quantities) v.inputs.quantities = [...new Set<number>(b.quantities.map((x: any) => Math.trunc(+x)).filter((x: number) => x > 0))].sort((a, c) => a - c);
    if (b.overrides) {
      const ov = { ...(v.overrides || {}) };
      for (const [k, val] of Object.entries<any>(b.overrides)) {
        if (val == null || val === "") delete ov[k];
        else ov[k] = { value: val, by: S.me.id, at: now(), reason: b.reason || "" };
      }
      v.overrides = ov;
    }
    recompute(v);
    return versionDict(v);
  }
  if ((m = is("POST", "/versions/:id/save-as"))) {
    const { q: qq, v } = findVersion(m.id);
    const n = Math.max(...qq.versions.map((x: any) => x.number)) + 1;
    const nv = { ...clone(v), id: uid(), number: n, label: b?.label || `Variant ${n}`, parent_version_id: v.id, status: "draft", created_at: now(), updated_at: now() };
    qq.versions.push(nv);
    return versionDict(nv);
  }

  // final quote
  if ((m = is("POST", "/rfqs/:id/finalize"))) {
    const r = S.rfq[m.id] || fail("RFQ not found");
    const lines = (b.lines || []).map((ln: any) => {
      const { v } = findVersion(ln.version_id);
      const qty = Math.trunc(+ln.qty);
      let br = v.result.breaks.find((x: any) => x.qty === qty);
      if (!br) { v.inputs.quantities = [...new Set([...v.inputs.quantities, qty])].sort((a: number, c: number) => a - c); recompute(v); br = v.result.breaks.find((x: any) => x.qty === qty); }
      if (br.unit_price == null) fail(`Part ${v.inputs.part?.part_number} is not priced yet (missing geometry).`);
      v.status = "final";
      return { part_number: v.inputs.part?.part_number || "", revision: v.inputs.part?.revision || "", qty, lead_time: ln.lead_time || `${br.lead_weeks} weeks ARO`,
        unit_price: br.unit_price, extended: Math.round(br.unit_price * qty * 100) / 100, version_id: v.id, description: ln.description || "" };
    });
    S.quoteCount += 1;
    const valid = new Date(Date.now() + (b.valid_days || 30) * 864e5).toISOString().slice(0, 10);
    const out = { id: uid(), rfq_id: r.id, quote_number: `Q-${new Date().getFullYear().toString().slice(2)}-${String(S.quoteCount).padStart(4, "0")}`,
      lines, valid_until: valid, notes: b.notes || "", created_at: now() };
    S.outputs[out.id] = out;
    r.status = "quoted";
    activity(r, "quoted", { quote_number: out.quote_number, lines: lines.length });
    return { id: out.id, quote_number: out.quote_number, lines, valid_until: valid };
  }
  if ((m = is("POST", "/rfqs/:id/outcome"))) {
    const r = S.rfq[m.id] || fail("RFQ not found");
    if (!["won", "lost"].includes(b?.outcome)) fail("outcome must be won or lost");
    r.status = b.outcome;
    const out = Object.values<any>(S.outputs).filter((o) => o.rfq_id === r.id).pop();
    for (const ln of out?.lines || []) S.history.unshift({ id: uid(), source: "quote", external_ref: out.quote_number, part_number: ln.part_number, revision: ln.revision,
      customer: r.customer_name, material: "", quantity: ln.qty, unit_price: ln.unit_price, outcome: b.outcome, date: now().slice(0, 10) });
    activity(r, b.outcome);
    return { ok: true };
  }

  // shop settings
  if (is("GET", "/shop")) return S.shop;
  if (is("PUT", "/shop")) {
    if (b.name) { S.shop.name = b.name; S.me.shop.name = b.name; }
    if (b.currency) S.shop.currency = String(b.currency).toUpperCase().slice(0, 3);
    if (b.settings) S.shop.settings = { ...S.shop.settings, ...b.settings };
    return { ok: true };
  }
  if ((m = is("PUT", "/shop/material-prices/:code"))) {
    const mat = S.shop.materials.find((x: any) => x.code === m!.code) || fail("Unknown material");
    mat.price_per_kg = +b.price_per_kg;
    mat.price_source = `shop price, dated ${now().slice(0, 10)}`;
    mat.price_stale = false;
    return { ok: true };
  }
  const kinds: Record<string, string> = { rates: "rates", machines: "machines", processes: "processes" };
  if (seg[0] === "shop" && kinds[seg[1]]) {
    const list = S.shop[kinds[seg[1]]];
    if (M === "POST" && seg.length === 2) { const row = { id: uid(), active: true, ...b }; if (seg[1] === "processes") Object.assign(row, { supplier: "", basis: "per_part", lead_days: 5, markup_pct: 15, keywords: String(b.keywords || "").split(",").map((x) => x.trim().toUpperCase()).filter(Boolean), price: +b.price || 0, lot_charge: +b.lot_charge || 0 }); list.push(row); return row; }
    const row = list.find((x: any) => x.id === seg[2]) || fail("Not found");
    if (M === "PUT") { Object.assign(row, b); return row; }
    if (M === "DELETE") { list.splice(list.indexOf(row), 1); return { ok: true }; }
  }

  // email accounts
  if (is("GET", "/mailboxes")) return S.mailboxes;
  if (is("POST", "/mailboxes") || is("POST", "/mailboxes/microsoft/start")) return fail("Connecting a real mailbox needs the full app. In the installed app this signs in with Microsoft or uses an IMAP app password.");
  if ((m = is("PUT", "/mailboxes/:id"))) { const mb = S.mailboxes.mailboxes.find((x: any) => x.id === m!.id); Object.assign(mb, b); return mb; }
  if ((m = is("DELETE", "/mailboxes/:id"))) { S.mailboxes.mailboxes = S.mailboxes.mailboxes.filter((x: any) => x.id !== m!.id); return { ok: true }; }
  if (seg[0] === "mailboxes") return { ok: false, message: "Mailbox checks need the full app." };

  // team
  if (is("GET", "/team")) return S.team;
  if (is("POST", "/team/invites")) {
    const email = String(b.email || "").trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) fail("Enter a valid email address.");
    if (S.team.users.some((u: any) => u.email === email) || S.team.invites.some((i: any) => i.email === email)) fail("That person is already on your team or invited.");
    const inv = { id: uid(), email, role: b.role || "estimator", invited_by: S.me.name, created_at: now() };
    S.team.invites.push(inv);
    return { id: inv.id, emailed: false };
  }
  if ((m = is("DELETE", "/team/invites/:id"))) { S.team.invites = S.team.invites.filter((x: any) => x.id !== m!.id); return { ok: true }; }
  if ((m = is("PUT", "/team/users/:id"))) { const u = S.team.users.find((x: any) => x.id === m!.id) || fail("Not found"); if (u.me) fail("You can't change your own role or disable yourself."); Object.assign(u, b); return { ok: true }; }

  // job history
  if (is("GET", "/history")) return S.history;
  if (is("GET", "/history/calibration")) return S.calibration;
  if (is("POST", "/history/import")) return fail("Importing a JobBOSS² export needs the full app. Eight example jobs are loaded here.");

  return fail(`The demo doesn't support ${M} ${path}.`);
}

// ------------------------------------------------------------------ files (drawings, quote preview)
const esc = (s: any) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

/** What "open" shows for a file path: an image (drawing page) or an HTML quote preview. */
export async function demoFile(path: string): Promise<{ kind: "image" | "html"; content: string; title: string }> {
  await load();
  let m = path.match(/^\/attachments\/([^/]+)\/page\/1\.png$/);
  if (m) return { kind: "image", content: S.page[m[1]] || fail("No drawing preview"), title: "Drawing" };
  m = path.match(/^\/attachments\/([^/]+)\/file$/);
  if (m) {
    const att = Object.values<any>(S.rfq).flatMap((r) => r.attachments).find((a: any) => a.id === m![1]);
    if (S.page[m[1]]) return { kind: "image", content: S.page[m[1]], title: att?.filename || "Drawing" };
    fail(`${att?.filename || "This file"} opens in the full app (3D model files are shown in the part's 3D view here).`);
  }
  m = path.match(/^\/outputs\/([^/]+)\/pdf$/);
  if (m) {
    const o = S.outputs[m[1]] || fail("Quote not found");
    const r = S.rfq[o.rfq_id];
    const money = (x: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: S.shop.currency || "USD" }).format(x);
    const rows = o.lines.map((l: any) => `<tr><td>${esc(l.part_number)}</td><td>${esc(l.revision || "-")}</td><td class="r">${l.qty.toLocaleString()}</td><td class="r">${money(l.unit_price)}</td><td class="r">${money(l.extended)}</td><td>${esc(l.lead_time)}</td></tr>`).join("");
    return { kind: "html", title: `Quotation ${o.quote_number}`, content: `
      <div class="q"><h2>${esc(S.shop.name)}</h2><h3>Quotation ${esc(o.quote_number)}</h3>
      <p>Date: ${new Date(o.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })} · Valid until: ${esc(o.valid_until)}</p>
      <p>Customer: ${esc(r?.customer_name)} · Attn: ${esc(r?.customer_contact)}</p><p>Your reference: ${esc(r?.customer_rfq_no || r?.number)}</p>
      <div class="tw"><table><thead><tr><th>Part number</th><th>Rev</th><th class="r">Qty</th><th class="r">Price per part</th><th class="r">Extended</th><th>Lead time</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${o.notes ? `<p>${esc(o.notes).replace(/\n/g, "<br>")}</p>` : ""}
      <p class="note">This is how the customer PDF lays out. The installed app creates the actual PDF file.</p></div>` };
  }
  return fail("This file opens in the full app.");
}

export { ApiError };
