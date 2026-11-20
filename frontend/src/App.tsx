import { createContext, useContext, useEffect, useState } from "react";
import { BrowserRouter, MemoryRouter, NavLink, Route, Routes } from "react-router-dom";
import { Boxes, History as HistoryIcon, Inbox, Settings as SettingsIcon } from "lucide-react";
import { api, DEMO } from "./api";
import { getConfig, signOut } from "./auth";
import { useAsync } from "./components/ui";
import Queue from "./pages/Queue";
import Rfq from "./pages/Rfq";
import PartEstimate from "./pages/PartEstimate";
import QuoteBuilder from "./pages/QuoteBuilder";
import Settings from "./pages/Settings";
import History from "./pages/History";

export const MeCtx = createContext<any>(null);
export const useMe = () => useContext(MeCtx);

// The demo runs inside a page that can't change its own address, so it keeps the route in memory.
const Router = DEMO ? MemoryRouter : BrowserRouter;

function DemoBanner({ onReset }: { onReset: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900 sm:px-6">
      <b>Demo with sample RFQs.</b>
      <span>Prices recalculate live. Changes stay in this tab until you reload. Files you upload are read in your browser and, when you allow it, by Claude on your claude.ai account; nothing else leaves the page.</span>
      <button className="ml-auto underline hover:no-underline" onClick={onReset}>Reset demo</button>
    </div>
  );
}

export default function App() {
  const [gen, setGen] = useState(0);
  useEffect(() => {
    if (!DEMO) return;
    let off = () => {};
    import("./demo/api").then((d) => { off = d.onDemoReset(() => setGen((g) => g + 1)) as () => void; });
    return () => off();
  }, []);
  const reset = () => import("./demo/api").then((d) => d.resetDemo());
  return <AppInner key={gen} onReset={reset} />;
}

function AppInner({ onReset }: { onReset: () => void }) {
  const me = useAsync(() => api.get("/me"), []);
  const nav = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm md:py-2 ${isActive ? "bg-navy-700 text-white" : "text-navy-100 hover:bg-navy-800"}`;
  return (
    <MeCtx.Provider value={me.data}>
      <Router>
        <div className="flex h-full min-h-0 flex-col md:flex-row">
          <aside className="flex flex-none flex-col bg-navy-900 text-white md:w-56">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:block md:py-4">
              <div className="flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-md bg-navy-600"><Boxes size={18} /></span>
                <div><div className="text-sm font-bold leading-tight">CNC Quote</div><div className="text-[11px] text-navy-100/70">{me.data?.shop?.name || "…"}</div></div></div>
              <nav className="flex flex-1 flex-wrap gap-1 md:mt-4 md:flex-col">
                <NavLink to="/" end className={nav}><Inbox size={16} /> RFQ queue</NavLink>
                <NavLink to="/history" className={nav}><HistoryIcon size={16} /> Job history</NavLink>
                <NavLink to="/settings" className={nav}><SettingsIcon size={16} /> Shop settings</NavLink>
              </nav>
            </div>
            <div className="mt-auto hidden space-y-1 px-4 py-4 text-[11px] text-navy-100/70 md:block">
              <div>{me.data?.name} · {me.data?.role}</div>
              {!getConfig().dev && <button className="underline hover:text-white" onClick={() => signOut()}>Sign out</button>}
              <div>Mailboxes: {me.data?.integrations?.mailboxes?.length ? me.data.integrations.mailboxes.join(", ") : "none connected"}</div>
              <div>AI extraction: {me.data?.integrations?.ai ? "on" : "off"}</div>
            </div>
          </aside>
          <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            {DEMO && <DemoBanner onReset={onReset} />}
            {me.error ? <p className="p-8 text-red-700">Can't reach the server: {me.error}</p> : (
              <Routes>
                <Route path="/" element={<Queue />} />
                <Route path="/rfq/:id" element={<Rfq />} />
                <Route path="/rfq/:id/part/:pid" element={<PartEstimate />} />
                <Route path="/rfq/:id/quote" element={<QuoteBuilder />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/history" element={<History />} />
              </Routes>
            )}
          </main>
        </div>
      </Router>
    </MeCtx.Provider>
  );
}
