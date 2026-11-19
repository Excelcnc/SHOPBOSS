// Browser port of backend/app/services/costing/engine.py, used only by the demo build so the
// estimator screens recalculate without a server. Keep it in step with the Python engine;
// demo/check-engine.mjs compares both on the recorded sample quotes.
/* eslint-disable @typescript-eslint/no-explicit-any */

const MACHINE_RATE_KEY: Record<string, string> = { mill3: "milling", mill4: "milling4", mill5: "milling5", lathe: "turning", millturn: "millturn" };
const MACHINE_LABEL: Record<string, string> = { mill3: "3-axis mill", mill4: "4-axis mill", mill5: "5-axis mill", lathe: "Lathe", millturn: "Mill-turn", "lathe+mill3": "Lathe + 3-axis mill" };
const INT_KEYS = (k: string) => k === "process.setups" || k.startsWith("lead.weeks.");

/** Python round(x, n): rounds the exact binary value (as toFixed does); exact ties go to even. */
const rnd = (x: number, n = 0) => {
  const exact = Math.abs(x).toFixed(Math.min(100, n + 60));  // enough digits to show the exact value
  const rest = exact.slice(exact.indexOf(".") + 1 + n);
  if (/^50*$/.test(rest)) {  // exactly halfway, e.g. 0.125 -> 0.12
    const lo = Math.floor(Math.abs(x) * 10 ** n);
    return Math.sign(x) * (lo % 2 === 0 ? lo : lo + 1) / 10 ** n;
  }
  return Number(x.toFixed(n));
};
const roundUp = (x: number, step: number) => (step <= 0 ? x : rnd(Math.ceil(x / step - 1e-9) * step, 6));
const g = (x: number) => String(parseFloat(x.toPrecision(6)));
const f1 = (x: number) => x.toFixed(1), f2 = (x: number) => x.toFixed(2), f3 = (x: number) => x.toFixed(3), f0 = (x: number) => x.toFixed(0);
/** Python 3.12+ sum() of floats: Neumaier compensated summation (plain += differs in the last bit). */
const sum = (a: number[]) => {
  let s = 0, c = 0;
  for (const x of a) { const t = s + x; c += Math.abs(s) >= Math.abs(x) ? (s - t) + x : (x - t) + s; s = t; }
  return s + c;
};
const startsWithAny = (s: string, pre: string[]) => pre.some((p) => s.startsWith(p));

class Calc {
  ov: Record<string, any>; lines: any[] = []; adjustments: string[] = []; warnings: string[] = [];
  constructor(ov: Record<string, any> | null) { this.ov = ov || {}; }
  val(key: string, computed: any, label: string, unit = "", group = "", note = ""): any {
    const o = this.ov[key];
    let used = computed, overridden = false;
    if (o != null) {
      const v = typeof o === "object" ? o.value : o;
      if (v != null && v !== "") {
        if (typeof computed === "number") {
          const n = Number(v);
          if (!Number.isNaN(n)) { used = INT_KEYS(key) ? Math.trunc(n) : n; overridden = true; }
        } else { used = v; overridden = true; }
      }
    }
    this.lines.push({ key, label, group, unit, computed, value: used, overridden, note });
    return used;
  }
}

function drawingFacts(drawing: any) {
  const items: any[] = drawing?.items || [];
  const bands = items.filter((i) => i.band != null && i.band > 0).map((i) => i.band);
  const ras = items.filter((i) => i.ra).map((i) => i.ra);
  const meta = drawing?.meta || {};
  return {
    tightest_band: bands.length ? Math.min(...bands) : null,
    tight_count: bands.filter((b) => b <= 0.05).length,
    very_tight_count: bands.filter((b) => b <= 0.025).length,
    gdt_count: items.filter((i) => i.cat === "gdt").length,
    min_ra: ras.length ? Math.min(...ras) : null,
    thread_count: items.filter((i) => i.cat === "thread").length,
    fit_count: items.filter((i) => i.cat === "fit").length,
    low_conf: items.filter((i) => (i.conf || 1) < 0.6).length,
    has_drawing: items.length > 0 || Object.keys(meta).length > 0,
    fai: items.some((i) => String(i.value ?? "").toUpperCase().includes("AS9102") || String(i.value ?? "").toUpperCase().includes("FIRST ARTICLE")),
  };
}

function complexity(geo: any, dwg: any, family: string) {
  const f: any[] = geo.features || [];
  const pts: [string, number][] = [];
  const add = (label: string, v: number) => { if (v > 0) pts.push([label, rnd(v, 2)]); };
  const setups = geo.setups || 2;
  add(`${setups} setups`, Math.max(0, setups - 1) * 0.6);
  const tb = dwg.tightest_band;
  if (tb != null) add(`tightest tolerance band ${f3(tb)} mm`, tb <= 0.01 ? 2.5 : tb <= 0.025 ? 1.8 : tb <= 0.05 ? 1.0 : tb <= 0.1 ? 0.4 : 0);
  add(`${dwg.gdt_count || 0} GD&T callouts`, Math.min(1.5, 0.3 * (dwg.gdt_count || 0)));
  const ra = dwg.min_ra;
  if (ra != null) add(`surface finish Ra ${g(ra)} µm`, ra <= 0.4 ? 1.5 : ra <= 0.8 ? 1.0 : ra <= 1.6 ? 0.4 : 0);
  const holes = f.filter((x) => x.type === "hole");
  const deep = holes.filter((h) => (h.ld || 0) > 10).length;
  const med = holes.filter((h) => (h.ld || 0) > 6 && (h.ld || 0) <= 10).length;
  add(`${deep} very deep holes (L/D>10)`, Math.min(2.0, 1.0 * deep));
  add(`${med} deep holes (L/D 6-10)`, Math.min(1.0, 0.4 * med));
  for (const fl of geo.flags || []) if (fl.code === "deep_pocket") { add("deep pocket / long-reach tooling", fl.sev === "high" ? 1.5 : 0.8); break; }
  const mw = geo.min_wall && typeof geo.min_wall === "object" ? geo.min_wall.t : geo.min_wall;
  if (mw != null) add(`thin wall ${f2(mw)} mm`, mw < 1.0 ? 1.5 : mw < 2.0 ? 0.8 : 0);
  const mr = geo.min_internal_radius;
  if (mr != null) add(`small internal radius R${f2(mr)}`, mr < 0.5 ? 1.5 : mr < 1.0 ? 0.8 : 0);
  add(`${geo.undercut_faces || 0} undercut faces`, Math.min(2.0, 0.5 * (geo.undercut_faces || 0)));
  add("internal grooves", Math.min(1.5, 0.75 * f.filter((x) => x.type === "groove").length));
  add(`${geo.freeform_faces || 0} freeform faces`, Math.min(2.0, 0.1 * (geo.freeform_faces || 0)));
  add("angled faces", geo.angled_faces ? 0.5 : 0);
  const nfeat = f.filter((x) => x.type !== "external_round").length;
  add(`${nfeat} machined features`, Math.min(1.5, nfeat / 20));
  add(`${dwg.thread_count || 0} threads`, Math.min(1.0, 0.15 * (dwg.thread_count || 0)));
  add("difficult material", ({ stainless: 0.8, titanium: 1.5, nickel: 2.0, tool_steel: 1.0 } as any)[family] || 0);
  const score = Math.max(1.0, Math.min(10.0, 1.0 + sum(pts.map((p) => p[1]))));
  return { score: rnd(score, 1), drivers: [...pts].sort((a, b) => b[1] - a[1]) };
}

function suggestMachine(geo: any, machines: any[]) {
  const turned = geo.turned || {};
  const isTurned = (turned.ratio || 0) > 0.7;
  const millFeats = (geo.features || []).filter((x: any) => ["hole", "slot", "pocket", "open_pocket"].includes(x.type) && !(isTurned && x.axis === turned.axis));
  let kind: string, why: string;
  if (isTurned) {
    kind = millFeats.length ? "millturn" : "lathe";
    why = `${Math.round(100 * turned.ratio)}% of the surface is rotational about ${turned.axis}` + (millFeats.length ? `; ${millFeats.length} milled features off-axis` : "");
  } else if (geo.undercut_faces || (geo.freeform_faces || 0) > 4 || (geo.angled_faces || 0) > 2) { kind = "mill5"; why = "angled, freeform or undercut faces"; }
  else if (new Set((geo.access_dirs || []).map((d: string) => d.replace(/^[+-]+/, ""))).size >= 3 && (geo.setups || 0) > 3) { kind = "mill4"; why = "features on several sides around one axis"; }
  else { kind = "mill3"; why = "prismatic part, features from the top/bottom"; }
  const size = [...(geo.size || [0, 0, 0])].sort((a, b) => b - a);
  const fits: string[] = [];
  for (const m of machines) {
    const mk = m.kind;
    if (m.active === false) continue;
    let ok: boolean;
    if (["lathe", "millturn"].includes(kind) && ["lathe", "millturn"].includes(mk)) {
      const t = m.travel_mm || [0, 0];
      ok = (turned.max_dia || 0) <= (t.length ? t[0] : 1e9) && (turned.length || 0) <= (t.length > 1 ? t[1] : 1e9);
    } else if (["mill3", "mill4", "mill5"].includes(kind) && ["mill3", "mill4", "mill5", "millturn"].includes(mk) && (mk === "millturn" || +mk.slice(-1) >= +kind.slice(-1))) {
      const t = [...(m.travel_mm || [1e9, 1e9, 1e9])].sort((a: number, b: number) => b - a);
      ok = size.slice(0, Math.min(3, t.length)).every((s, i) => s <= t[i]);
    } else continue;
    if (ok) fits.push(m.name);
  }
  let kindEff = kind;
  if (isTurned && millFeats.length && !machines.some((m) => m.kind === "millturn")) { kindEff = "lathe+mill3"; why += "; no mill-turn configured, so turning + separate milling setups"; }
  return { kind: kindEff, label: MACHINE_LABEL[kindEff] || kindEff, why, fits };
}

export function estimate(inputs: any, overrides: Record<string, any> | null): any {
  const inp = structuredClone(inputs);
  const S: any = { ...(inp.settings || {}) };
  const c = new Calc(overrides);
  const geo: any = inp.geometry || {};
  const dwg = drawingFacts(inp.drawing);
  const mat: any = inp.material || {};
  const rates: any = inp.rates || {};
  const qtys = [...new Set((inp.quantities || [1]).map((q: any) => Math.trunc(+q)).filter((q: number) => q > 0))].sort((a: any, b: any) => a - b) as number[];
  if (!qtys.length) qtys.push(1);

  let hasGeo = Boolean(geo.size) && Math.min(...(geo.size || [0])) > 0;
  const sizeOv = overrides?.["geometry.size_mm"];
  if (sizeOv) {
    const dims = (String(typeof sizeOv === "object" ? sizeOv.value : sizeOv).match(/\d*\.?\d+/g) || []).slice(0, 3).map(Number);
    if (dims.length === 3) {
      geo.size = dims;
      if (!hasGeo) {
        const volOv = overrides?.["geometry.volume_cm3"];
        const v = volOv ? Number(typeof volOv === "object" ? volOv.value : volOv) : null;
        geo.volume = v ? v * 1000 : dims[0] * dims[1] * dims[2] * 0.5;
        geo.area = 2 * (dims[0] * dims[1] + dims[1] * dims[2] + dims[0] * dims[2]) * 1.5;
        c.adjustments.push("Geometry entered manually" + (v ? "" : ": part volume assumed 50% of the envelope (more material removal, so more time)") + ".");
      }
      hasGeo = true;
    }
  }
  c.val("geometry.size_mm", hasGeo ? (geo.size || []).map(g).join(" x ") : "", "Part envelope (L x W x H)", "mm", "geometry", !sizeOv ? "from 3D model" : "entered by estimator");
  if (!hasGeo) { c.warnings.push("No 3D model geometry. Enter the part envelope (L x W x H) to price this part; it stays unpriced until then."); geo.size = [0, 0, 0]; }
  if (!dwg.has_drawing) c.adjustments.push("No drawing analysed: tolerances and finish unknown, so extra uncertainty time is included.");
  if (!mat.code) c.adjustments.push("Material not identified: priced as the most expensive common grade (stainless 316). Confirm and override.");

  const mach = suggestMachine(geo, inp.machines || []);
  const machineKind = String(c.val("machine.kind", mach.kind, "Suggested machine", "", "process", mach.why));
  const cx = complexity(geo, dwg, mat.family || "");
  const score = c.val("complexity.score", cx.score, "Complexity score (1-10)", "", "complexity");
  const cmult = c.val("complexity.multiplier", rnd(1 + 0.08 * (score - 1), 3), "Complexity time multiplier", "×", "complexity");

  const size = geo.size || [0, 0, 0];
  const turned = geo.turned || {};
  let stockVol: number, stockDesc: string;
  if (startsWithAny(machineKind, ["lathe", "millturn"]) && turned.max_dia) {
    const dia = turned.max_dia + 2 * S.turning_allowance_mm;
    const ln = (turned.length ?? Math.max(...size)) + S.turning_length_allowance_mm;
    stockVol = Math.PI * (dia / 2) ** 2 * ln / 1000;
    stockDesc = `Round bar Ø${Math.ceil(dia)} × ${Math.ceil(ln)} mm`;
  } else {
    const dims = size.map((s: number) => Math.ceil(s + 2 * S.stock_allowance_mm));
    stockVol = dims[0] * dims[1] * dims[2] / 1000;
    stockDesc = dims.join(" × ") + " mm block";
  }
  const partVol = (geo.volume || 0) / 1000;
  const density = mat.density_g_cm3 || 8.0;
  const stockKg = c.val("material.stock_kg", rnd(stockVol * density / 1000 * (1 + S.material_scrap_pct / 100), 4), "Stock weight incl. scrap", "kg", "material", stockDesc);
  const ppk = c.val("material.price_per_kg", Number(mat.price_per_kg || 0), "Material price", "$/kg", "material", mat.price_source || "");
  const matCost = c.val("material.cost_per_part", rnd(Math.max(S.min_material_per_part, stockKg * ppk), 2), "Material cost per part", "$", "material");
  const removed = Math.max(0, stockVol - partVol);

  const machin = mat.machinability || 0.14;
  const mrr = S.mrr_rough_cm3_min * machin * (startsWithAny(machineKind, ["lathe", "millturn"]) ? 1.4 : 1.0);
  const rough = removed / Math.max(mrr, 0.1);
  const areaDm2 = (geo.area || 0) / 10000;
  const ra = dwg.min_ra;
  const finish = areaDm2 * S.finish_min_per_dm2 / Math.max(machin, 0.05) ** 0.5 * (ra != null && ra <= 0.8 ? 1.6 : 1.0);
  let featMin = 0;
  for (const x of geo.features || []) {
    const t = x.type;
    if (t === "hole") {
      const d = Math.max(x.dia ?? 5, 1);
      const depth = x.depth || ((x.ld ?? 1) * d);
      let m = 0.3 + depth / (25 * Math.max(machin, 0.1) ** 0.5) / 10;
      if ((x.ld || 0) > 6) m *= 2.0;
      if (x.cbore) m += 0.4;
      if (x.csk) m += 0.2;
      featMin += m;
    } else if (["pocket", "slot", "open_pocket"].includes(t)) featMin += 0.8 + (x.depth || 0) * 0.05;
    else if (t === "groove") featMin += 1.5;
    else if (t === "undercut") featMin += 0.8 * (x.count ?? 1);
    else if (t === "freeform") featMin += 0.3 * (x.count ?? 1);
  }
  featMin += 0.4 * dwg.thread_count + 0.8 * dwg.very_tight_count + 0.4 * Math.max(0, dwg.tight_count - dwg.very_tight_count) + 0.5 * dwg.fit_count;
  const setups = Math.trunc(c.val("process.setups", Math.trunc(geo.setups || 2), "Setups", "", "process"));
  const handling = setups * S.handling_min_per_setup + S.deburr_min_base + areaDm2 * 0.3;
  const inspectMin = S.inspection_min_base + S.inspection_min_per_critical * (dwg.tight_count + dwg.gdt_count);
  const uncItems = dwg.low_conf + (dwg.has_drawing ? 0 : 3) + ((geo.undercut_faces || 0) > 0 ? 1 : 0) + (mat.code ? 0 : 2);
  const uncPct = Math.min(S.uncertainty_cap_pct, S.uncertainty_pct_per_item * uncItems);
  const baseCycle = (rough + finish + featMin) * cmult + handling;
  const cycle = c.val("time.cycle_min", roundUp(baseCycle * S.time_calibration_factor * (1 + uncPct / 100), 0.1), "Machining cycle time per part", "min", "time",
    `rough ${f1(rough)} + finish ${f1(finish)} + features ${f1(featMin)}, ×${cmult} complexity, + handling ${f1(handling)}, +${f0(uncPct)}% uncertainty`);
  const insp = c.val("time.inspection_min", roundUp(inspectMin, 0.1), "In-process inspection per part", "min", "time");
  const setupHr = c.val("time.setup_hr", roundUp(setups * S.setup_hours_per_setup * (1 + 0.05 * (score - 1)), 0.05), "Setup time per lot", "h", "time");
  const progHr = c.val("time.programming_hr", roundUp((S.programming_base_hours + S.programming_hours_per_feature * (geo.features || []).length + S.programming_hours_per_setup * setups) * (1 + 0.1 * (score - 1)) * (machineKind === "mill5" ? 1.5 : 1.0), 0.05), "Programming time (one-off)", "h", "time");
  const faiHr = c.val("time.first_article_hr", S.first_article_hours + (dwg.fai ? 1.5 : 0) + (dwg.gdt_count ? 0.5 : 0), "First article / setup inspection per lot", "h", "time");

  const rateKey = MACHINE_RATE_KEY[machineKind.split("+")[0]] || "milling";
  const mrate = c.val(`rate.${rateKey}`, Number(rates[rateKey] ?? rates.milling ?? 95.0), `Machine rate (${rateKey})`, "$/h", "rates");
  const srate = c.val("rate.setup", Number(rates.setup ?? 85.0), "Setup rate", "$/h", "rates");
  const prate = c.val("rate.programming", Number(rates.programming ?? 95.0), "Programming rate", "$/h", "rates");
  const irate = c.val("rate.inspection", Number(rates.inspection ?? 90.0), "Inspection rate", "$/h", "rates");

  const procs: any[] = [];
  const weightKg = partVol * density / 1000;
  for (const p of inp.processes || []) {
    const basis = p.basis || "per_part", price = Number(p.price || 0);
    let perPart = price * (basis === "per_kg" ? weightKg : basis === "per_dm2" ? areaDm2 : basis === "per_part" ? 1 : 0);
    const key = "process." + p.name;
    const mk = 1 + (p.markup_pct ?? 15) / 100;
    perPart = c.val(key + ".per_part", rnd(perPart * mk, 2), p.name + " per part", "$", "outside", p.source || "");
    const lot = c.val(key + ".lot_charge", rnd(Number(p.lot_charge || 0) * mk, 2), p.name + " lot charge", "$", "outside");
    procs.push({ name: p.name, per_part: perPart, lot, unpriced: p.unpriced || false, lead_days: Math.trunc(p.lead_days || 5) });
    if (p.unpriced) c.warnings.push(`Outside process '${p.name}' is not in your supplier list: priced at a conservative placeholder. Enter the real price.`);
  }
  const purch: any[] = [];
  for (const b of inp.purchased || []) {
    const cost = c.val("purchased." + b.name, Number(b.unit_cost || 0), b.name + " (purchased, each)", "$", "purchased");
    purch.push({ name: b.name, qty_per_part: b.qty_per_part ?? 1, unit_cost: cost });
    if (!cost) c.warnings.push(`Purchased component '${b.name}' has no cost yet.`);
  }

  const margin = c.val("pricing.margin_pct", Number(S.margin_pct), "Margin", "%", "pricing");
  const cont = c.val("pricing.contingency_pct", Number(S.contingency_pct), "Contingency", "%", "pricing");
  if (uncPct) c.adjustments.push(`+${f0(uncPct)}% cycle time for ${uncItems} uncertain item(s) (low-confidence drawing values, missing inputs or undercuts).`);
  if (geo.undercut_faces) c.adjustments.push("Undercut faces priced with extra time; confirm tooling or 5-axis access.");

  const tiers = [...(S.volume_tiers || [])].sort((a: any, b: any) => a.min_qty - b.min_qty);
  const breaks = qtys.map((q) => {
    let disc = 0;
    for (const t of tiers) if (q >= t.min_qty) disc = t.discount_pct;
    const machining = cycle / 60 * mrate;
    const inspection = insp / 60 * irate;
    const oneOff = setupHr * srate + progHr * prate + faiHr * irate;
    const outside = sum(procs.map((p) => p.per_part + p.lot / q));
    const purchased = sum(purch.map((p) => p.unit_cost * p.qty_per_part));
    const labour = machining + inspection + oneOff / q;
    const subtotal = matCost + labour * (1 - disc / 100) + outside + purchased;
    let price = subtotal * (1 + cont / 100) * (1 + margin / 100);
    price = Math.max(price, S.min_order_charge / q);
    let unit: number | null = roundUp(price, price < 100 ? S.price_rounding : 1.0);
    unit = c.val(`price.unit.${q}`, hasGeo ? rnd(unit, 2) : 0.0, `Unit price at qty ${q}`, "$", "price");
    if (!hasGeo && !overrides?.[`price.unit.${q}`]) unit = null;
    const prodDays = Math.ceil((setupHr + progHr * 0.5 + q * (cycle + insp) / 60) / Math.max(1.0, S.lead_hours_per_day));
    const outsideDays = sum(procs.map((p) => p.lead_days)) + (procs.length ? S.lead_outside_buffer_days : 0);
    const leadDays = S.lead_queue_days + S.lead_material_days + prodDays + outsideDays;
    const leadWeeks = c.val(`lead.weeks.${q}`, Math.ceil(leadDays / 5), `Lead time at qty ${q}`, "weeks", "lead",
      `${S.lead_queue_days} queue + ${S.lead_material_days} material + ${prodDays} production + ${outsideDays} outside processes = ${leadDays} working days`);
    return { qty: q, lead_weeks: leadWeeks, lead_days: leadDays, material: rnd(matCost, 2), machining: rnd(machining, 2), inspection: rnd(inspection, 2),
      setup_programming_per_part: rnd(oneOff / q, 2), outside: rnd(outside, 2), purchased: rnd(purchased, 2), volume_discount_pct: disc,
      subtotal: rnd(subtotal, 2), contingency: rnd(subtotal * cont / 100, 2), unit_price: unit, extended: unit != null ? rnd(unit * q, 2) : null,
      hours_per_part: rnd((cycle + insp) / 60, 3) };
  });

  return {
    machine: { ...mach, kind: machineKind, label: MACHINE_LABEL[machineKind] || machineKind },
    complexity: { ...cx, score, multiplier: cmult },
    stock: { description: stockDesc, volume_cm3: rnd(stockVol, 2), removed_cm3: rnd(removed, 2), kg: stockKg },
    complete: hasGeo, drawing_facts: dwg, uncertainty_pct: uncPct, processes: procs, purchased: purch,
    breaks, lines: c.lines, adjustments: c.adjustments, warnings: c.warnings,
  };
}
