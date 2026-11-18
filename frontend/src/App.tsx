import { createContext, useContext } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { Boxes, History as HistoryIcon, Inbox, Settings as SettingsIcon } from "lucide-react";
import { api } from "./api";
import { useAsync } from "./components/ui";
import Queue from "./pages/Queue";
import Rfq from "./pages/Rfq";
import PartEstimate from "./pages/PartEstimate";
import QuoteBuilder from "./pages/QuoteBuilder";
import Settings from "./pages/Settings";
import History from "./pages/History";

export const MeCtx = createContext<any>(null);
export const useMe = () => useContext(MeCtx);

export default function App() {
  const me = useAsync(() => api.get("/me"), []);
  const nav = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm ${isActive ? "bg-navy-700 text-white" : "text-navy-100 hover:bg-navy-800"}`;
  return (
    <MeCtx.Provider value={me.data}>
      <BrowserRouter>
        <div className="flex h-screen">
          <aside className="flex w-56 flex-none flex-col bg-navy-900 text-white">
            <div className="flex items-center gap-2 px-4 py-4"><span className="grid h-8 w-8 place-items-center rounded-md bg-navy-600"><Boxes size={18} /></span>
              <div><div className="text-sm font-bold leading-tight">CNC Quote</div><div className="text-[11px] text-navy-100/70">{me.data?.shop?.name || "…"}</div></div></div>
            <nav className="flex flex-col gap-1 px-2">
              <NavLink to="/" end className={nav}><Inbox size={16} /> RFQ queue</NavLink>
              <NavLink to="/history" className={nav}><HistoryIcon size={16} /> Job history</NavLink>
              <NavLink to="/settings" className={nav}><SettingsIcon size={16} /> Shop settings</NavLink>
            </nav>
            <div className="mt-auto space-y-1 px-4 py-4 text-[11px] text-navy-100/70">
              <div>{me.data?.name} · {me.data?.role}</div>
              <div>Mailbox: {me.data?.integrations?.graph ? me.data.integrations.graph_mailbox : me.data?.integrations?.imap ? "IMAP" : "not connected"}</div>
              <div>AI extraction: {me.data?.integrations?.ai ? "on" : "off"}</div>
            </div>
          </aside>
          <main className="min-w-0 flex-1 overflow-y-auto">
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
      </BrowserRouter>
    </MeCtx.Provider>
  );
}
