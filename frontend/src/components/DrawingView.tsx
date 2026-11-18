import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export default function DrawingView({ attachmentId, ext, boxes, selected }: { attachmentId: string; ext: string; boxes: { id: string; bbox: number[] | null; page?: number }[]; selected: string | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setUrl(null); setErr(null);
    if (!["pdf", "png", "jpg", "jpeg"].includes(ext)) { setErr(ext === "dxf" ? "DXF preview isn't rendered yet; the callouts on the right were read from the DXF text." : "No preview for this format."); return; }
    let u = ""; api.blobUrl(`/attachments/${attachmentId}/page/1.png`).then((x) => setUrl((u = x))).catch((e) => setErr(String(e.message)));
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [attachmentId, ext]);
  useEffect(() => { document.getElementById("selbox")?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" }); }, [selected]);
  const sel = boxes.find((b) => b.id === selected);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-steel-200 bg-white px-2 py-1.5 text-xs">
        <button className="btn btn-sm" onClick={() => setZoom(Math.max(0.5, zoom / 1.4))} aria-label="Zoom out">−</button>
        <button className="btn btn-sm" onClick={() => setZoom(1)}>Fit</button>
        <button className="btn btn-sm" onClick={() => setZoom(Math.min(6, zoom * 1.4))} aria-label="Zoom in">+</button>
        <span className="ml-2 text-steel-500">Click a callout on the right to locate it on the sheet</span>
      </div>
      <div ref={wrap} className="relative min-h-[320px] flex-1 overflow-auto bg-steel-100">
        {err && <p className="p-6 text-sm text-steel-500">{err}</p>}
        {!url && !err && <p className="p-6 text-sm text-steel-500">Loading drawing…</p>}
        {url && (
          <div className="relative mx-auto" style={{ width: `${zoom * 100}%` }}>
            <img src={url} alt="Drawing" className="block w-full bg-white" />
            {sel?.bbox && (sel.page || 1) === 1 && (
              <div id="selbox" className="pointer-events-none absolute rounded border-2 border-orange-500 bg-orange-400/15 shadow-[0_0_0_3px_rgba(255,122,0,.25)]"
                style={{ left: `${sel.bbox[0] * 100 - 0.4}%`, top: `${sel.bbox[1] * 100 - 0.4}%`, width: `${(sel.bbox[2] - sel.bbox[0]) * 100 + 0.8}%`, height: `${(sel.bbox[3] - sel.bbox[1]) * 100 + 0.8}%` }} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
