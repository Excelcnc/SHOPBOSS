import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initAuth } from "./auth";
import SignIn from "./pages/SignIn";
import "./index.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

initAuth()
  .then((ok) => root.render(<React.StrictMode>{ok ? <App /> : <SignIn />}</React.StrictMode>))
  .catch((e) => root.render(<p style={{ padding: 32 }}>Can't start: {String(e?.message || e)}</p>));
