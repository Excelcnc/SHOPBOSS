import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { entraConfigured, initAuth, signIn } from "./auth";
import "./index.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

function SignIn() {
  return (
    <div className="flex h-screen items-center justify-center bg-navy-900">
      <div className="w-full max-w-sm rounded-lg bg-white p-8 text-center shadow-xl">
        <h1 className="mb-1 text-xl font-semibold">CNC Quote</h1>
        <p className="mb-6 text-sm text-steel-500">Sign in with your Microsoft work account.</p>
        <button className="btn btn-primary w-full justify-center py-2" onClick={() => signIn()}>Sign in with Microsoft</button>
      </div>
    </div>
  );
}

initAuth()
  .then((acct) => root.render(<React.StrictMode>{entraConfigured && !acct ? <SignIn /> : <App />}</React.StrictMode>))
  .catch((e) => root.render(<p style={{ padding: 32 }}>Sign-in failed: {String(e?.message || e)}</p>));
