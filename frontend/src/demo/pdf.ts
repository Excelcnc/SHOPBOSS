// PDF work for the demo, loaded only when needed: read an uploaded drawing (text layer + first page
// as an image) with pdf.js, and write the customer quote PDF with jsPDF (same layout as the server's).
/* eslint-disable @typescript-eslint/no-explicit-any */

export async function readPdf(file: Blob): Promise<{ text: string; pages: number; png: Blob; dataUrl: string }> {
  const pdfjs: any = await import("pdfjs-dist");
  const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()), isEvalSupported: false }).promise;
  const texts: string[] = [];
  for (let i = 1; i <= Math.min(doc.numPages, 4); i++) {
    const tc = await (await doc.getPage(i)).getTextContent();
    texts.push(tc.items.map((it: any) => it.str + (it.hasEOL ? "\n" : " ")).join(""));
  }
  const page = await doc.getPage(1);
  const base = page.getViewport({ scale: 1 });
  const scale = Math.min(3, 2200 / Math.max(base.width, base.height));
  const vp = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(vp.width); canvas.height = Math.round(vp.height);
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: ctx, viewport: vp }).promise;
  const png: Blob = await new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error("Couldn't draw the PDF page."))), "image/png"));
  return { text: texts.join("\n\n").replace(/[ \t]+/g, " ").trim(), pages: doc.numPages, png, dataUrl: canvas.toDataURL("image/png") };
}

export async function quotePdf(out: any, shop: any, rfq: any): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ unit: "pt", format: "letter" });
  const cur = shop.currency || "USD";
  const money = (x: number) => `${cur} ${x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const L = 58, W = 612 - 2 * L;
  let y = 72;
  doc.setFont("helvetica", "bold"); doc.setFontSize(20); doc.text(shop.name || "", 306, y, { align: "center" }); y += 30;
  doc.setFontSize(14); doc.text(`Quotation ${out.quote_number}`, L, y); y += 22;
  doc.setFont("helvetica", "normal"); doc.setFontSize(10);
  const today = new Date(out.created_at || Date.now()).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  for (const line of [`Date: ${today}    Valid until: ${out.valid_until}`, `Customer: ${rfq?.customer_name || ""}    Attn: ${rfq?.customer_contact || ""}`,
    `Your reference: ${rfq?.customer_rfq_no || rfq?.number || ""}`]) { doc.text(line, L, y); y += 15; }
  y += 12;
  const cols = [["Part number", 137], ["Rev", 36], ["Qty", 50], ["Price per part", 86], ["Extended", 94], ["Lead time", W - 403]] as const;
  const right = new Set([2, 3, 4]);
  const row = (cells: string[], head: boolean, shade: boolean) => {
    const h = 22;
    if (head) { doc.setFillColor(20, 50, 92); doc.rect(L, y, W, h, "F"); doc.setTextColor(255); doc.setFont("helvetica", "bold"); }
    else { if (shade) { doc.setFillColor(244, 246, 249); doc.rect(L, y, W, h, "F"); } doc.setTextColor(27, 32, 39); doc.setFont("helvetica", "normal"); }
    doc.setDrawColor(200, 207, 216); doc.rect(L, y, W, h);
    let x = L;
    cells.forEach((c, i) => {
      const w = cols[i][1];
      const t = doc.splitTextToSize(c, w - 10)[0] || "";
      doc.text(t, right.has(i) ? x + w - 5 : x + 5, y + 15, { align: right.has(i) ? "right" : "left" });
      if (i) doc.line(x, y, x, y + h);
      x += w;
    });
    y += h;
  };
  row(cols.map((c) => c[0]), true, false);
  out.lines.forEach((l: any, i: number) => row([l.part_number, l.revision || "-", Number(l.qty).toLocaleString("en-US"), money(l.unit_price), money(l.extended), l.lead_time || ""], false, i % 2 === 1));
  doc.setTextColor(27, 32, 39); doc.setFont("helvetica", "normal");
  y += 18;
  if (out.notes) for (const ln of doc.splitTextToSize(out.notes, W)) { doc.text(ln, L, y); y += 14; }
  return doc.output("blob");
}
