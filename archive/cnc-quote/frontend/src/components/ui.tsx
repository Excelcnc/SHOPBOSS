import { ReactNode, useEffect, useState } from "react";
import { X } from "lucide-react";

export function Badge({ tone = "gray", children, title }: { tone?: "gray" | "blue" | "green" | "amber" | "red" | "navy"; children: ReactNode; title?: string }) {
  const t = {
    gray: "bg-steel-100 text-steel-600", blue: "bg-navy-50 text-navy-700", green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700", navy: "bg-navy-800 text-white",
  }[tone];
  return <span title={title} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold ${t}`}>{children}</span>;
}

export const STATUS: Record<string, { label: string; tone: any }> = {
  new: { label: "New", tone: "blue" }, estimating: { label: "Estimating", tone: "amber" }, quoted: { label: "Quoted", tone: "navy" },
  won: { label: "Won", tone: "green" }, lost: { label: "Lost", tone: "gray" },
};

export function Conf({ v }: { v?: number | null }) {
  if (v == null) return null;
  const p = Math.round(v * 100);
  const c = v >= 0.8 ? "bg-emerald-500" : v >= 0.6 ? "bg-amber-500" : "bg-red-500";
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-steel-500" title={`Confidence ${p}%`}>
      <span className="h-1.5 w-8 overflow-hidden rounded bg-steel-200"><span className={`block h-full ${c}`} style={{ width: `${p}%` }} /></span>
      {p}%
    </span>
  );
}

export function Src({ s }: { s?: string }) {
  const m: Record<string, [string, any, string]> = {
    "text-layer": ["Text layer", "green", "Read verbatim from the file"], "ai+text": ["AI + text", "green", "Read by AI and found verbatim in the file"],
    "ai-vision": ["AI read", "blue", "Read by AI from the image only; verify"], "ai-email": ["AI", "blue", "Extracted by AI from the email"],
    "email-pattern": ["Email", "gray", "Matched in the email text"], manual: ["Manual", "gray", "Entered by an estimator"], "dxf-header": ["DXF", "green", ""],
  };
  const [l, t, title] = m[s || ""] || [s || "—", "gray", ""];
  return <Badge tone={t} title={title}>{l}</Badge>;
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`card flex max-h-[90vh] w-full flex-col shadow-xl ${wide ? "max-w-3xl" : "max-w-lg"}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-center border-b border-steel-200 px-5 py-3"><h3 className="font-semibold">{title}</h3>
          <button className="ml-auto rounded p-1 hover:bg-steel-100" onClick={onClose} aria-label="Close"><X size={16} /></button></div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-steel-200 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: any[]): { data: T | undefined; error: string | null; loading: boolean; reload: () => void; setData: (d: T) => void } {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setError(null); } }).catch((e) => live && setError(String(e.message || e))).finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1), setData };
}

let toastTimer: any;
export function toast(msg: string) {
  let el = document.getElementById("toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status"); el.className = "fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 rounded-md bg-navy-900 px-4 py-2 text-sm text-white shadow-lg"; document.body.appendChild(el); }
  el.textContent = msg; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => (el!.hidden = true), 3500);
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return <div className="flex flex-col items-center gap-2 px-6 py-14 text-center text-steel-500">{icon}<p className="font-medium text-steel-700">{title}</p>{children}</div>;
}
