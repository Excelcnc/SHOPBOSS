import { useState } from "react";
import { Boxes } from "lucide-react";
import { getConfig, setSession, signInMicrosoft } from "../auth";

type Mode = "signin" | "signup" | "verify" | "forgot" | "reset";

async function post(path: string, body: any) {
  const r = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data: any = {};
  try { data = await r.json(); } catch { /* empty */ }
  if (!r.ok) throw Object.assign(new Error(typeof data.detail === "string" ? data.detail : r.statusText), { status: r.status });
  return data;
}

function MicrosoftLogo() {
  return <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true"><path fill="#f25022" d="M1 1h9v9H1z" /><path fill="#7fba00" d="M11 1h9v9h-9z" /><path fill="#00a4ef" d="M1 11h9v9H1z" /><path fill="#ffb900" d="M11 11h9v9h-9z" /></svg>;
}

export default function SignIn() {
  const cfg = getConfig();
  const [mode, setMode] = useState<Mode>(new URLSearchParams(location.search).has("signup") ? "signup" : "signin");
  const [email, setEmail] = useState(new URLSearchParams(location.search).get("email") || "");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [shop, setShop] = useState("");
  const [code, setCode] = useState("");
  const [invitedTo, setInvitedTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const go = (m: Mode) => { setMode(m); setError(""); setInfo(""); setCode(""); };
  const done = (token: string) => { setSession(token); window.location.href = "/"; };

  async function run(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const checkInvite = async () => {
    if (!email.includes("@")) return;
    try {
      const r = await fetch(`/api/auth/invite?${new URLSearchParams({ email })}`).then((x) => x.json());
      setInvitedTo(r.invited ? r.shop : null);
    } catch { setInvitedTo(null); }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      if (mode === "signin") {
        try { done((await post("/auth/login", { email, password })).token); }
        catch (err: any) {
          if (err.status === 403 && err.message === "verify") { go("verify"); setInfo(`We sent a new 6-digit code to ${email}.`); return; }
          throw err;
        }
      } else if (mode === "signup") {
        const r = await post("/auth/signup", { email, password, name, shop_name: shop });
        if (r.token) return done(r.token);
        go("verify"); setInfo(`We sent a 6-digit code to ${email}. Check your inbox (and spam folder).`);
      } else if (mode === "verify") {
        done((await post("/auth/verify", { email, code })).token);
      } else if (mode === "forgot") {
        await post("/auth/forgot", { email });
        go("reset"); setInfo(`If ${email} has an account, a 6-digit code is on its way.`);
      } else if (mode === "reset") {
        done((await post("/auth/reset", { email, code, password })).token);
      }
    });
  };

  const title = { signin: "Sign in", signup: "Create your account", verify: "Check your email", forgot: "Reset your password", reset: "Choose a new password" }[mode];
  const button = { signin: "Sign in", signup: "Create account", verify: "Continue", forgot: "Send code", reset: "Save password and sign in" }[mode];
  const showMs = cfg.microsoft && (mode === "signin" || mode === "signup");

  return (
    <div className="flex min-h-screen items-center justify-center bg-navy-900 px-4 py-10">
      <div className="w-full max-w-sm rounded-lg bg-white p-7 shadow-xl">
        <div className="mb-5 flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-md bg-navy-700 text-white"><Boxes size={18} /></span>
          <span className="font-bold">CNC Quote</span></div>
        <h1 className="mb-1 text-lg font-semibold">{title}</h1>
        {mode === "signup" && <p className="mb-4 text-sm text-steel-500">Works with any email: Gmail, Outlook, Yahoo, your company address.</p>}
        {info && <p className="mb-3 rounded bg-navy-50 px-3 py-2 text-sm text-navy-900">{info}</p>}

        {showMs && <>
          <button type="button" className="btn w-full justify-center py-2" onClick={() => signInMicrosoft()}><MicrosoftLogo /> {mode === "signup" ? "Sign up" : "Sign in"} with Microsoft</button>
          <div className="my-4 flex items-center gap-3 text-xs text-steel-400"><span className="h-px flex-1 bg-steel-200" />or with email<span className="h-px flex-1 bg-steel-200" /></div>
        </>}

        <form onSubmit={submit} className="space-y-3">
          {mode !== "verify" && mode !== "reset" && <label className="block text-sm">Email
            <input className="input mt-1" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} onBlur={mode === "signup" ? checkInvite : undefined} /></label>}
          {mode === "signup" && <>
            <label className="block text-sm">Your name<input className="input mt-1" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></label>
            {invitedTo ? <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-800">You've been invited to <b>{invitedTo}</b>. You'll join their shop.</p>
              : <label className="block text-sm">Shop / company name<input className="input mt-1" autoComplete="organization" required value={shop} onChange={(e) => setShop(e.target.value)} /></label>}
          </>}
          {(mode === "verify" || mode === "reset") && <label className="block text-sm">6-digit code
            <input className="input mt-1 text-center font-mono text-lg tracking-[0.4em]" inputMode="numeric" autoComplete="one-time-code" maxLength={7} required autoFocus value={code} onChange={(e) => setCode(e.target.value)} /></label>}
          {(mode === "signin" || mode === "signup" || mode === "reset") && <label className="block text-sm">{mode === "reset" ? "New password" : "Password"}
            <input className="input mt-1" type="password" required minLength={mode === "signin" ? 1 : 10} autoComplete={mode === "signin" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
            {mode !== "signin" && <span className="mt-1 block text-xs text-steel-500">At least 10 characters.</span>}</label>}
          {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">{error}</p>}
          <button className="btn btn-primary w-full justify-center py-2" disabled={busy}>{busy ? "Please wait…" : button}</button>
        </form>

        <div className="mt-4 space-y-1 text-center text-sm">
          {mode === "signin" && <>
            {cfg.signup_open && <p>New here? <button className="text-navy-700 underline" onClick={() => go("signup")}>Create an account</button></p>}
            {!cfg.signup_open && <p className="text-steel-500">New users: ask your shop admin for an invitation, then <button className="text-navy-700 underline" onClick={() => go("signup")}>create your account</button>.</p>}
            {cfg.email_verification && <p><button className="text-steel-500 underline" onClick={() => go("forgot")}>Forgot password?</button></p>}
          </>}
          {mode === "signup" && <p>Already have an account? <button className="text-navy-700 underline" onClick={() => go("signin")}>Sign in</button></p>}
          {mode === "verify" && <p><button className="text-steel-500 underline" disabled={busy} onClick={() => run(async () => { await post("/auth/resend", { email }); setInfo(`New code sent to ${email}.`); })}>Send a new code</button></p>}
          {(mode === "verify" || mode === "forgot" || mode === "reset") && <p><button className="text-steel-500 underline" onClick={() => go("signin")}>Back to sign in</button></p>}
        </div>
      </div>
    </div>
  );
}
