// "Ask Claude about this estimate": a short chat on the part estimate screen. Claude gets the part's
// facts and the engine's calculated values; it explains and suggests, the estimator decides.
// Runs on the viewer's own Claude account through the page's `sample` capability (demo build only).
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from "react";
import { Send, Sparkles, Square } from "lucide-react";
import { claudeError, getSample } from "./claude";

type Turn = { role: "user" | "assistant"; content: string };
const STARTERS = ["Why is the price at the smallest quantity so high?", "What drives the cycle time?", "What should I check with the customer before quoting?"];

function context(part: any, v: any, cur: string) {
  const r = v.result || {};
  const fmt = (x: any) => (typeof x === "number" ? +x.toFixed(4) : x);
  const lines = (r.lines || []).map((l: any) => `${l.label}: ${fmt(l.value)} ${l.unit}${l.overridden ? ` (estimator override; calculated ${fmt(l.computed)})` : ""}${l.note ? ` [${l.note}]` : ""}`);
  const breaks = (r.breaks || []).map((b: any) => `qty ${b.qty}: ${b.unit_price == null ? "unpriced" : `${cur} ${b.unit_price}/part`}; material ${b.material}, machining ${b.machining}, inspection ${b.inspection}, setup+programming per part ${b.setup_programming_per_part}, outside ${b.outside}, contingency ${b.contingency}, lead ${b.lead_weeks} weeks`);
  const feats = (part.cad?.features || []).slice(0, 25).map((f: any) => `${f.type}${f.dia ? ` Ø${f.dia}` : ""}${f.depth ? ` depth ${f.depth}` : ""}${f.label ? ` (${f.label})` : ""}`);
  const callouts = (part.drawing?.items || []).slice(0, 30).map((i: any) => `${i.label}: ${i.value}${i.tol ? ` ${i.tol}` : ""}`);
  return [
    `Part ${part.part_number} Rev ${part.revision || "-"}: ${part.description || ""}. Material: ${v.inputs?.material?.name || "unknown"}.`,
    `Machine: ${r.machine?.label} (${r.machine?.why}). Complexity ${r.complexity?.score}/10, drivers: ${(r.complexity?.drivers || []).map((d: any) => d[0]).join("; ")}.`,
    `Price breaks:\n${breaks.join("\n")}`,
    `Calculated values:\n${lines.join("\n")}`,
    feats.length ? `3D features: ${feats.join("; ")}` : "No 3D model features.",
    callouts.length ? `Drawing callouts: ${callouts.join("; ")}` : "No drawing callouts.",
    (r.warnings || []).length ? `Warnings: ${r.warnings.join(" ")}` : "",
    (r.adjustments || []).length ? `Margin protection applied: ${r.adjustments.join(" ")}` : "",
    (part.warnings || []).length ? `Part warnings: ${part.warnings.join(" ")}` : "",
  ].filter(Boolean).join("\n\n");
}

export default function AskClaude({ part, version, cur }: { part: any; version: any; cur: string }) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ctl = useRef<AbortController | null>(null);

  useEffect(() => { let on = true; getSample().then((s) => on && setAvailable(!!s)); return () => { on = false; ctl.current?.abort(); }; }, []);
  useEffect(() => { setTurns([]); setAnswer(""); setError(""); }, [part.id]);
  if (available === false) return null;

  const ask = async (q: string) => {
    const text = q.trim();
    if (!text || busy) return;
    const sample = await getSample();
    if (!sample) { setAvailable(false); return; }
    const next: Turn[] = [...turns, { role: "user" as const, content: text }].slice(-8);
    setTurns(next); setDraft(""); setAnswer(""); setError(""); setBusy(true);
    const rules = "You help a CNC machine shop estimator understand an estimate from their cost engine. Answer in plain language, briefly " +
      "(under 150 words unless asked for more), using the numbers below. You don't set prices: suggest what to check or which value to override and why. " +
      "If the data doesn't answer the question, say so.\n\nESTIMATE\n" + context(part, version, cur);
    ctl.current = new AbortController();
    try {
      const { text: reply } = await sample([{ role: "user", content: rules }, ...next], { cache: false, signal: ctl.current.signal, onText: ({ text: t }: any) => setAnswer(t) });
      setTurns([...next, { role: "assistant", content: reply }]); setAnswer("");
    } catch (e: any) {
      if (e?.code === "not_granted" || e?.code === "sampling_disabled") { setAvailable(false); return; }
      if (e?.text) setTurns([...next, { role: "assistant", content: e.text + " …" }]);
      setAnswer(""); if (e?.code !== "cancelled") setError(claudeError(e));
    } finally { setBusy(false); }
  };

  return (
    <section className="card mt-4">
      <h2 className="flex items-center gap-2 border-b border-steel-200 px-4 py-2.5 text-sm font-semibold"><Sparkles size={14} /> Ask Claude about this estimate
        <span className="font-normal text-steel-500">uses your claude.ai account; Claude explains, you decide</span></h2>
      <div className="space-y-3 px-4 py-3 text-sm">
        {!turns.length && !busy && <div className="flex flex-wrap gap-2">{STARTERS.map((s) => <button key={s} className="btn btn-sm" onClick={() => ask(s)}>{s}</button>)}</div>}
        {turns.map((t, i) => <p key={i} className={`whitespace-pre-wrap ${t.role === "user" ? "font-medium text-navy-800" : "text-steel-800"}`}>{t.role === "user" ? "You: " : ""}{t.content}</p>)}
        {busy && <p className="whitespace-pre-wrap text-steel-800" aria-live="polite">{answer || "Thinking…"}</p>}
        {error && <p className="text-red-700">{error}</p>}
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(draft); }}>
          <input id="ask-claude" className="input" placeholder="Ask about price, time, material, tolerances…" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={busy} aria-label="Question for Claude" />
          {busy ? <button type="button" className="btn" onClick={() => ctl.current?.abort()}><Square size={13} /> Stop</button>
            : <button className="btn btn-primary" disabled={!draft.trim()}><Send size={13} /> Ask</button>}
        </form>
      </div>
    </section>
  );
}
