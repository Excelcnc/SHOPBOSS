// Demo upload intake: turns files the viewer picks (an RFQ email, PDF drawings, drawing images)
// into an RFQ. The browser reads the files; Claude (the viewer's own claude.ai account, through the
// page's `sample` capability) extracts the customer details and each part's drawing facts; the cost
// engine prices from the drawing's overall size. 3D models need the server, as in the full app.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { claudeError, getSample } from "./claude";

export type Upload = { name: string; ext: string; size: number; blob: Blob };
export type Parsed = {
  email: { subject: string; from: string; fromEmail: string; date: string; body: string } | null;
  files: (Upload & { kind: "drawing" | "model" | "email" | "other"; text?: string; png?: Blob; dataUrl?: string; fileUrl?: string })[];
};

const EXPORT_CONTROL = /\b(ITAR|EAR99|EXPORT[- ]CONTROLLED|22 CFR 12[0-9]|USML|ECCN)\b/i;
const extOf = (n: string) => (n.split(".").pop() || "").toLowerCase();
const readAsDataUrl = (b: Blob) => new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => rej(r.error); r.readAsDataURL(b); });

// ------------------------------------------------------------------ .eml (MIME) parsing
function decodeWords(s: string) {
  return s.replace(/=\?([^?]+)\?([BQ])\?([^?]*)\?=/gi, (_, cs, enc, txt) => {
    try {
      const bytes = enc.toUpperCase() === "B" ? Uint8Array.from(atob(txt), (c) => c.charCodeAt(0))
        : Uint8Array.from(txt.replace(/_/g, " ").replace(/=([0-9A-F]{2})/gi, (_m: string, h: string) => String.fromCharCode(parseInt(h, 16))), (c: string) => c.charCodeAt(0));
      return new TextDecoder(cs).decode(bytes);
    } catch { return txt; }
  });
}
function splitHead(raw: string) {
  const i = raw.search(/\r?\n\r?\n/);
  const head = (i < 0 ? raw : raw.slice(0, i)).replace(/\r?\n[ \t]+/g, " ");
  const body = i < 0 ? "" : raw.slice(i).replace(/^\r?\n\r?\n/, "");
  const h: Record<string, string> = {};
  for (const line of head.split(/\r?\n/)) { const m = line.match(/^([\w-]+):\s*(.*)$/); if (m) h[m[1].toLowerCase()] = m[2]; }
  return { h, body };
}
const param = (v: string, k: string) => (v.match(new RegExp(`${k}\\*?="?([^";]+)"?`, "i")) || [])[1];
function decodeBody(body: string, enc: string): Uint8Array {
  enc = (enc || "").toLowerCase();
  if (enc === "base64") { const b = atob(body.replace(/\s+/g, "")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); }
  if (enc === "quoted-printable") body = body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
  return Uint8Array.from(body, (c) => c.charCodeAt(0) & 255);
}
const htmlToText = (h: string) => { const d = new DOMParser().parseFromString(h, "text/html"); d.querySelectorAll("style,script").forEach((x) => x.remove()); return (d.body?.innerText || d.body?.textContent || "").trim(); };

function parseEml(raw: string) {
  const top = splitHead(raw);
  const out = { subject: decodeWords(top.h["subject"] || ""), from: decodeWords(top.h["from"] || ""), date: top.h["date"] || "", text: "", html: "", attachments: [] as Upload[] };
  const walk = (h: Record<string, string>, body: string) => {
    const ct = h["content-type"] || "text/plain";
    if (/^multipart\//i.test(ct)) {
      const b = param(ct, "boundary");
      if (!b) return;
      for (const part of body.split("--" + b).slice(1)) {
        if (part.startsWith("--")) break;
        const p = splitHead(part.replace(/^\r?\n/, ""));
        walk(p.h, p.body);
      }
      return;
    }
    const disp = h["content-disposition"] || "";
    const name = decodeWords(param(disp, "filename") || param(ct, "name") || "");
    const bytes = decodeBody(body, h["content-transfer-encoding"]);
    if (name) { out.attachments.push({ name, ext: extOf(name), size: bytes.length, blob: new Blob([bytes]) }); return; }
    const txt = new TextDecoder(param(ct, "charset") || "utf-8").decode(bytes);
    if (/text\/plain/i.test(ct) && !out.text) out.text = txt;
    else if (/text\/html/i.test(ct) && !out.html) out.html = txt;
  };
  walk(top.h, top.body);
  return { ...out, body: (out.text || (out.html ? htmlToText(out.html) : "")).trim() };
}

// ------------------------------------------------------------------ read the uploads
export async function readUploads(files: File[], onStep: (s: string) => void): Promise<Parsed> {
  const res: Parsed = { email: null, files: [] };
  const queue: Upload[] = files.map((f) => ({ name: f.name, ext: extOf(f.name), size: f.size, blob: f }));
  while (queue.length) {
    const u = queue.shift()!;
    if (u.ext === "eml") {
      onStep(`Reading ${u.name}`);
      const e = parseEml(await u.blob.text());
      const fromEmail = (e.from.match(/<([^>]+)>/) || [, e.from.match(/\S+@\S+/)?.[0] || ""])[1] || "";
      res.email = { subject: e.subject, from: e.from, fromEmail, date: e.date, body: e.body.slice(0, 20000) };
      res.files.push({ ...u, kind: "email" });
      queue.push(...e.attachments);
    } else if (u.ext === "pdf") {
      onStep(`Reading drawing ${u.name}`);
      const { readPdf } = await import("./pdf");
      const p = await readPdf(u.blob);
      res.files.push({ ...u, kind: "drawing", text: p.text.slice(0, 15000), png: p.png, dataUrl: p.dataUrl, fileUrl: await readAsDataUrl(new Blob([u.blob], { type: "application/pdf" })) });
    } else if (["png", "jpg", "jpeg", "webp", "gif"].includes(u.ext)) {
      const typed = new Blob([u.blob], { type: u.ext === "jpg" ? "image/jpeg" : `image/${u.ext}` });
      const url = await readAsDataUrl(typed);
      res.files.push({ ...u, blob: typed, kind: "drawing", png: typed, dataUrl: url, fileUrl: url });
    } else if (["step", "stp", "iges", "igs", "stl", "x_t", "sldprt", "zip"].includes(u.ext)) {
      res.files.push({ ...u, kind: "model" });
    } else {
      res.files.push({ ...u, kind: "other" });
    }
  }
  return res;
}

// ------------------------------------------------------------------ ask Claude
export type Extracted = {
  customer_name?: string | null; customer_contact?: string | null; customer_email?: string | null; customer_rfq_no?: string | null;
  quote_due?: string | null; due_date?: string | null; quantities?: number[]; summary?: string; requirements?: string[];
  parts?: {
    part_number?: string; revision?: string | null; description?: string | null; material_code?: string | null; material_text?: string | null;
    envelope_mm?: number[] | null; finishes?: string[]; source_file?: string | null; confidence?: number;
    callouts?: { cat?: string; label?: string; value?: string; tol_band_mm?: number | null; ra_um?: number | null }[];
  }[];
  warnings?: string[];
};

export async function askClaude(p: Parsed, materials: any[], processes: any[], onStep: (s: string) => void):
  Promise<{ data: Extracted | null; note: string | null; usedImages: boolean }> {
  const sample = await getSample();
  if (!sample) return { data: null, note: "Claude isn't available in this view, so nothing was read automatically. Enter the part size to price it.", usedImages: false };
  const allText = [p.email?.subject, p.email?.body, ...p.files.map((f) => f.text || "")].join("\n");
  if (EXPORT_CONTROL.test(allText))
    return { data: null, note: "Export-control wording (ITAR/EAR) found, so these files were not sent to Claude. Enter the details by hand.", usedImages: false };
  const lim = await sample.limits?.().catch(() => null);
  const drawings = p.files.filter((f) => f.kind === "drawing" && f.png);
  const images = lim?.images ? drawings.slice(0, lim.images.maxCount).map((f) => f.png!) : [];
  const prompt = [
    "You read incoming requests for quotation (RFQs) for a CNC machine shop. Extract facts only; never invent prices.",
    "Convert inch dimensions to millimetres. If something isn't stated, use null (or an empty list).",
    p.email ? `EMAIL\nFrom: ${p.email.from}\nSubject: ${p.email.subject}\nDate: ${p.email.date}\n\n${p.email.body.slice(0, 12000)}` : "No email was uploaded.",
    ...p.files.filter((f) => f.kind !== "email").map((f) => `FILE ${f.name} (${f.kind})${f.text ? `\nText layer of the drawing:\n${f.text.slice(0, 8000)}` : f.kind === "drawing" ? "\n(image only: read it from the attached picture)" : ""}`),
    images.length ? `The attached image(s) are the first page of these drawings, in order: ${drawings.slice(0, images.length).map((f) => f.name).join(", ")}.` : "",
    `Shop material codes (choose material_code from these only, or null): ${materials.map((m) => `${m.code}=${m.name}`).join("; ")}`,
    `Outside processes the shop buys (mention matching finishes by name): ${processes.map((x) => x.name).join("; ")}`,
    `Reply with only one JSON object of this shape:
{"customer_name":str|null,"customer_contact":str|null,"customer_email":str|null,"customer_rfq_no":str|null,
 "quote_due":"YYYY-MM-DD"|null,"due_date":str|null,"quantities":[int],"summary":"one sentence for the estimator",
 "requirements":[str],"warnings":[str],
 "parts":[{"part_number":str,"revision":str|null,"description":str|null,"material_code":str|null,"material_text":str|null,
   "envelope_mm":[length,width,height] (overall part size in mm, largest first) or null,
   "finishes":[str],"source_file":file name it came from,"confidence":0..1,
   "callouts":[{"cat":"dimension"|"diameter"|"thread"|"fit"|"gdt"|"finish"|"coating"|"heat_treat"|"note"|"standard","label":str,"value":str,
     "tol_band_mm":total tolerance band in mm or null,"ra_um":surface roughness Ra in µm or null}] (at most 30, the ones that drive cost)}]}
One part per drawing (an assembly drawing with a parts list is one part per machined item you can size). Warnings: revision conflicts, missing information, anything an estimator must check.`,
  ].filter(Boolean).join("\n\n");
  onStep(images.length ? "Claude is reading the email and drawings…" : "Claude is reading the files…");
  try {
    const data = await sample.json(prompt, images.length ? { images } : {});
    return { data: data && typeof data === "object" ? (data as Extracted) : null, note: null, usedImages: images.length > 0 };
  } catch (e: any) {
    return { data: null, note: claudeError(e), usedImages: false };
  }
}
