// Thin API client. In dev the X-Dev-User header identifies the estimator; otherwise the app sends the
// session token (email account) or a Microsoft token (see src/auth.ts).
import { getConfig, getToken, sessionExpired } from "./auth";

export type Json = any;

export const DEMO = import.meta.env.VITE_DEMO === "1";

async function req<T = Json>(method: string, path: string, body?: any, isForm = false): Promise<T> {
  if (DEMO) {
    const { demoRequest } = await import("./demo/api");
    return demoRequest(method, path, body);
  }
  const headers: Record<string, string> = {};
  const token = await getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  else if (getConfig().dev) headers["X-Dev-User"] = localStorage.getItem("devUser") || "estimator@example.com";
  if (body && !isForm) headers["Content-Type"] = "application/json";
  const r = await fetch(`/api${path}`, { method, headers, body: isForm ? body : body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && !getConfig().dev) sessionExpired();
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : (r.blob() as any)) as Promise<T>;
}

export const api = {
  get: <T = Json>(p: string) => req<T>("GET", p),
  post: <T = Json>(p: string, b?: any) => req<T>("POST", p, b),
  put: <T = Json>(p: string, b?: any) => req<T>("PUT", p, b),
  patch: <T = Json>(p: string, b?: any) => req<T>("PATCH", p, b),
  del: <T = Json>(p: string) => req<T>("DELETE", p),
  form: <T = Json>(p: string, f: FormData) => req<T>("POST", p, f, true),
  blobUrl: async (p: string) => {
    if (DEMO) { const { demoFile } = await import("./demo/api"); return (await demoFile(p)).content; }
    return URL.createObjectURL(await req<Blob>("GET", p));
  },
  /** Opens a file (drawing, quote PDF) in a new tab; the demo shows it over the page instead. */
  open: async (p: string) => {
    if (DEMO) {
      const [{ demoFile }, { showViewer }] = await Promise.all([import("./demo/api"), import("./demo/viewer")]);
      return showViewer(await demoFile(p));
    }
    window.open(URL.createObjectURL(await req<Blob>("GET", p)));
  },
};

export const money = (v: number | null | undefined, cur = "USD") =>
  v == null ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: cur, maximumFractionDigits: 2 }).format(v);
export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
