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
  if (S.claudeOn === undefined) S.claudeOn = !!(await (await import("./claude")).getSample());
  if (method.toUpperCase() === "POST" && path === "/rfqs" && body instanceof FormData) return clone(await createFromUpload(body));
  const res = route(method, path, body);
  return clone(res);
}

// ------------------------------------------------------------------ uploads (read by Claude in the viewer's account)
const CATS = new Set(["dimension", "diameter", "thread", "fit", "gdt", "finish", "coating", "heat_treat", "note", "standard"]);

async function createFromUpload(form: FormData) {
  const { readUploads, askClaude } = await import("./intake");
  const { toast } = await import("../components/ui");
  const files = form.getAll("files").filter((f): f is File => f instanceof File);
  const field = (k: string) => String(form.get(k) || "").trim();
  if (!files.length) fail("Add the customer's email (.eml) or drawings (PDF, PNG, JPG) to create an RFQ in the demo.");
  const step = (t: string) => toast(t);
  const parsed = await readUploads(files, step);
  const { data, note, usedImages } = await askClaude(parsed, S.shop.materials, S.shop.processes, step);
  const ex = data || {};

  // RFQ shell
  const n = Math.max(0, ...Object.values<any>(S.rfq).map((r) => +String(r.number).split("-").pop()! || 0)) + 1;
  const id = uid(), at = now();
  const src = (v: any, fromImage = false) => ({ value: v, confidence: 0.8, source: fromImage ? "ai-vision" : "ai-email", evidence: "read by Claude" });
  const extracted: any = {};
  const qtyField = field("quantities").split(/[;,\s]+/).map((x) => parseInt(x, 10)).filter((x) => x > 0);
  const quantities = qtyField.length ? qtyField : (ex.quantities || []).map((x: any) => Math.trunc(+x)).filter((x: number) => x > 0);
  for (const [k, v] of Object.entries<any>({ customer_name: ex.customer_name, customer_contact: ex.customer_contact, customer_rfq_no: ex.customer_rfq_no,
    quote_due: ex.quote_due, due_date: ex.due_date, summary: ex.summary, requirements: ex.requirements?.length ? ex.requirements : null })) if (v) extracted[k] = src(v);
  if (quantities.length) extracted.quantities = qtyField.length ? { value: quantities, confidence: 1, source: "manual", evidence: "entered" } : src(quantities);
  if (field("customer_name")) extracted.customer_name = { value: field("customer_name"), confidence: 1, source: "manual", evidence: "entered" };

  // attachments
  const attachments = parsed.files.map((f) => {
    const a = { id: uid(), filename: f.name, kind: f.kind, ext: f.ext, size: f.size };
    if (f.dataUrl) S.page[a.id] = f.dataUrl;
    if (f.fileUrl) S.file[a.id] = f.fileUrl;
    return { a, f };
  });
  const cat = catalog();
  const parts: any[] = [];
  const claudeParts = (ex.parts || []).filter((p: any) => p && (p.part_number || p.envelope_mm));
  const drawingsAtt = attachments.filter((x) => x.f.kind === "drawing");
  const models = attachments.filter((x) => x.f.kind === "model");
  const specs: any[] = claudeParts.length ? claudeParts : drawingsAtt.concat(models).map((x) => ({ part_number: x.f.name.replace(/\.[^.]+$/, ""), source_file: x.f.name }));
  for (const sp of specs) {
    const stem = String(sp.part_number || "").toUpperCase();
    const dwg = drawingsAtt.find((x) => x.f.name === sp.source_file) || drawingsAtt.find((x) => stem && x.f.name.toUpperCase().includes(stem)) || (specs.length === 1 ? drawingsAtt[0] : undefined);
    const model = models.find((x) => stem && x.f.name.toUpperCase().includes(stem));
    const fromImage = !!dwg && !dwg.f.text;
    const items = (sp.callouts || []).slice(0, 30).map((c: any, i: number) => ({
      id: "C" + (i + 1), cat: CATS.has(c.cat) ? c.cat : "note", label: c.label || c.cat || "Note", value: String(c.value ?? ""),
      band: typeof c.tol_band_mm === "number" && c.tol_band_mm > 0 ? c.tol_band_mm : undefined, ra: typeof c.ra_um === "number" && c.ra_um > 0 ? c.ra_um : undefined,
      conf: Math.max(0.4, Math.min(0.95, sp.confidence ?? 0.75)), src: fromImage ? "ai-vision" : "ai+text", page: 1, bbox: null }));
    const text = [dwg?.f.text, ...(sp.finishes || []), ...items.map((i: any) => i.value), parsed.email?.body].join(" ").toUpperCase();
    const procs = S.shop.processes.filter((pr: any) => (pr.keywords || []).some((k: string) => text.includes(String(k).toUpperCase())))
      .map((pr: any) => ({ name: pr.name, basis: pr.basis, price: pr.price, lot_charge: pr.lot_charge, markup_pct: pr.markup_pct, lead_days: pr.lead_days,
        keywords: pr.keywords, supplier: pr.supplier, unpriced: false, source: "drawing (read by Claude)" }));
    const code = S.shop.materials.some((m: any) => m.code === sp.material_code) ? sp.material_code : null;
    const env = Array.isArray(sp.envelope_mm) && sp.envelope_mm.length === 3 && sp.envelope_mm.every((x: any) => +x > 0) ? sp.envelope_mm.map((x: any) => +(+x).toFixed(2)) : null;
    const warnings: string[] = [];
    if (model) warnings.push(`3D model ${model.f.name} attached: geometry analysis needs the full app, so this part is priced from the drawing's overall size.`);
    if (!env) warnings.push("Overall size not found. Enter the part envelope (L x W x H) under Calculated values to price it.");
    if (!code) warnings.push(sp.material_text ? `Material "${sp.material_text}" isn't in your materials list: priced as stainless 316 until you pick one.` : "Material not found: priced as stainless 316 until you pick one.");
    const partId = uid(), quoteId = uid(), verId = uid();
    const inputs = { geometry: { size: [0, 0, 0], features: [] }, drawing: { items, meta: {} }, material: materialInput(code), quantities: quantities.length ? quantities : [1],
      rates: cat.rates, machines: cat.machines, processes: procs, purchased: [], settings: cat.settings, part: { part_number: sp.part_number || "PART", revision: sp.revision || "" } };
    const overrides: any = env ? { "geometry.size_mm": { value: env.join(" x "), by: "claude", at, reason: `overall size read from ${dwg?.f.name || "the drawing"} by Claude` } } : {};
    const v = { id: verId, quote_id: quoteId, number: 1, label: "Original", parent_version_id: null, status: "draft", inputs, overrides, result: estimate(inputs, overrides), created_at: at, updated_at: at };
    S.quote[quoteId] = { id: quoteId, part_id: partId, rfq_id: id, versions: [v] };
    parts.push({ id: partId, part_number: sp.part_number || "PART", revision: sp.revision || "", description: sp.description || "", kind: "machined", parent_part_id: null,
      qty_per_parent: 1, model_attachment_id: model?.a.id || null, drawing_attachment_id: dwg?.a.id || null,
      match: dwg ? { score: 0.8, why: ["paired by Claude"], drawing: dwg.a.id } : {}, cad: {}, has_mesh: false, drawing: { items, meta: {} },
      material_code: code, material_source: { code, origin: "read by Claude", evidence: sp.material_text || "", confidence: sp.confidence ?? 0.75, conflicts: [] },
      processes: procs, warnings: [...warnings, ...((ex.warnings || []) as string[]).slice(0, 4)], purchased: {}, quote_id: quoteId });
  }
  if (ex.parts?.length) {
    const img = !drawingsAtt.some((x) => x.f.text);
    const uniq = (a: any[]) => [...new Set(a.filter(Boolean).map(String))];
    extracted.part_numbers = src(parts.map((p) => p.part_number).join(", "), img);
    const revs = uniq(claudeParts.map((p: any) => p.revision)), mats = uniq(claudeParts.map((p: any) => p.material_text)), fin = uniq(claudeParts.flatMap((p: any) => p.finishes || []));
    if (revs.length) extracted.revision = src(revs.join(", "), img);
    if (mats.length) extracted.material = src(mats.join(", "), img);
    if (fin.length) extracted.special_processes = src(fin, img);
  }
  const customer = field("customer_name") || ex.customer_name || "";
  const rfq: any = { id, number: `RFQ-${new Date().getFullYear()}-${String(n).padStart(4, "0")}`, status: "new", customer_name: customer,
    customer_contact: ex.customer_contact || "", customer_email: field("customer_email") || ex.customer_email || parsed.email?.fromEmail || "", customer_rfq_no: ex.customer_rfq_no || "",
    due_date: ex.due_date || null, created_at: at, analysis_status: "done", analysis_error: null, assigned_to: null,
    subject: field("subject") || parsed.email?.subject || parts.map((p) => p.part_number).join(", "), extracted,
    email: parsed.email ? { subject: parsed.email.subject, from: parsed.email.from, received_at: at, body: parsed.email.body, source: "upload", mailbox: "" } : null,
    attachments: attachments.map((x) => x.a), parts, outputs: [], activity: [] };
  if (field("notes")) rfq.extracted.notes = { value: field("notes"), confidence: 1, source: "manual", evidence: "entered" };
  activity(rfq, "created", { source: "upload", attachments: attachments.length });
  activity(rfq, "analyzed", { ai: !!data, images: usedImages, parts: parts.length, note });
  S.rfq[id] = rfq;
  S.rfqs.unshift({ id, number: rfq.number, status: "new", customer_name: customer, customer_contact: rfq.customer_contact, customer_email: rfq.customer_email,
    customer_rfq_no: rfq.customer_rfq_no, due_date: rfq.due_date, created_at: at, analysis_status: "done", analysis_error: null, assigned_to: null,
    subject: rfq.subject, parts: parts.length, priced: 0, warnings: parts.reduce((s, p) => s + p.warnings.length, 0), attachments: attachments.length });
  if (note) toast(note);
  return [{ id, number: rfq.number }];
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

  if (is("GET", "/me")) return { ...S.me, integrations: { ...S.me.integrations, ai: S.claudeOn ? "on (Claude, your claude.ai account)" : false,
    mailboxes: S.mailboxes.mailboxes.filter((x: any) => x.active).map((x: any) => x.address) } };
  if (is("GET", "/config")) return { dev: true, signup_open: false, signup_domains: [], email_verification: false, microsoft: null };

  // RFQs
  if (is("GET", "/rfqs")) {
    const st = q.get("status"), text = (q.get("q") || "").toLowerCase();
    return Object.values<any>(S.rfq).map((r) => ({ r, s: summary(r) }))
      .filter(({ s }) => !st || st.split(",").includes(s.status))
      .filter(({ r, s }) => !text || (JSON.stringify(s) + " " + r.parts.map((p: any) => p.part_number).join(" ")).toLowerCase().includes(text))
      .sort((a, b2) => (a.s.created_at < b2.s.created_at ? 1 : -1)).map(({ s }) => s);
  }
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
  if ((m = is("POST", "/rfqs/:id/files"))) return fail("In the demo, add files by creating a new RFQ with them (New RFQ on the queue).");
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
export type DemoFile = { kind: "image" | "html"; content: string; title: string; download?: { filename: string; make: () => Promise<Blob>; label: string } };

export async function demoFile(path: string): Promise<DemoFile> {
  await load();
  let m = path.match(/^\/attachments\/([^/]+)\/page\/1\.png$/);
  if (m) return { kind: "image", content: S.page[m[1]] || fail("No drawing preview"), title: "Drawing" };
  m = path.match(/^\/attachments\/([^/]+)\/file$/);
  if (m) {
    const att = Object.values<any>(S.rfq).flatMap((r) => r.attachments).find((a: any) => a.id === m![1]);
    const orig = S.file[m[1]];
    const download = orig ? { filename: att?.filename || "drawing", label: "Download original", make: async () => (await import("./claude")).dataUrlToBlob(orig) } : undefined;
    if (S.page[m[1]]) return { kind: "image", content: S.page[m[1]], title: att?.filename || "Drawing", download };
    fail(`${att?.filename || "This file"} opens in the full app (3D model files are shown in the part's 3D view here).`);
  }
  m = path.match(/^\/outputs\/([^/]+)\/pdf$/);
  if (m) {
    const o = S.outputs[m[1]] || fail("Quote not found");
    const r = S.rfq[o.rfq_id];
    const money = (x: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: S.shop.currency || "USD" }).format(x);
    const rows = o.lines.map((l: any) => `<tr><td>${esc(l.part_number)}</td><td>${esc(l.revision || "-")}</td><td class="r">${l.qty.toLocaleString()}</td><td class="r">${money(l.unit_price)}</td><td class="r">${money(l.extended)}</td><td>${esc(l.lead_time)}</td></tr>`).join("");
    const download = { filename: `${o.quote_number}.pdf`, label: "Download PDF", make: async () => (await import("./pdf")).quotePdf(o, S.shop, r) };
    return { kind: "html", title: `Quotation ${o.quote_number}`, download, content: `
      <div class="q"><h2>${esc(S.shop.name)}</h2><h3>Quotation ${esc(o.quote_number)}</h3>
      <p>Date: ${new Date(o.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })} · Valid until: ${esc(o.valid_until)}</p>
      <p>Customer: ${esc(r?.customer_name)} · Attn: ${esc(r?.customer_contact)}</p><p>Your reference: ${esc(r?.customer_rfq_no || r?.number)}</p>
      <div class="tw"><table><thead><tr><th>Part number</th><th>Rev</th><th class="r">Qty</th><th class="r">Price per part</th><th class="r">Extended</th><th>Lead time</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${o.notes ? `<p>${esc(o.notes).replace(/\n/g, "<br>")}</p>` : ""}
      <p class="note">Preview of the customer quote. Download PDF saves the file you send to the customer.</p></div>` };
  }
  return fail("This file opens in the full app.");
}

export { ApiError };
