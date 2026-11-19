// Sign-in. The server tells the app what it supports (GET /api/config):
//  - dev mode: no sign-in (local development only)
//  - email + password accounts (any email provider): the server issues a session token
//  - "Sign in with Microsoft" (MSAL) when the server has a Microsoft sign-in app configured
import { InteractionRequiredAuthError, PublicClientApplication } from "@azure/msal-browser";

export type ServerConfig = { dev: boolean; signup_open: boolean; email_verification: boolean; microsoft: { client_id: string; tenant: string } | null };

const KEY = "cq_session";
let config: ServerConfig = { dev: true, signup_open: true, email_verification: false, microsoft: null };
let msal: PublicClientApplication | null = null;
let msScopes: string[] = [];

export const getConfig = () => config;

function safeGet(k: string) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k: string, v: string | null) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage blocked */ } }

export function setSession(token: string) { safeSet(KEY, token); }

/** Call once at start-up. Returns true when the user can use the app (signed in, or dev mode). */
export async function initAuth(): Promise<boolean> {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error(`The server is not answering (HTTP ${r.status}).`);
  config = await r.json();
  if (config.dev) return true;
  if (config.microsoft) {
    msal = new PublicClientApplication({
      auth: { clientId: config.microsoft.client_id, authority: `https://login.microsoftonline.com/${config.microsoft.tenant}`, redirectUri: window.location.origin },
      cache: { cacheLocation: "localStorage" },
    });
    msScopes = [`api://${config.microsoft.client_id}/access_as_user`];
    await msal.initialize();
    const res = await msal.handleRedirectPromise();
    const acct = res?.account || msal.getAllAccounts()[0] || null;
    if (acct) { msal.setActiveAccount(acct); return true; }
  }
  return Boolean(safeGet(KEY));
}

export function signInMicrosoft() {
  return msal?.loginRedirect({ scopes: msScopes, prompt: "select_account" });
}

export function signOut() {
  safeSet(KEY, null);
  const acct = msal?.getActiveAccount() || msal?.getAllAccounts()[0];
  if (msal && acct) return msal.logoutRedirect({ account: acct, postLogoutRedirectUri: window.location.origin });
  window.location.href = "/";
}

export async function getToken(): Promise<string | null> {
  if (config.dev) return null;
  const local = safeGet(KEY);
  if (local) return local;
  if (!msal) return null;
  const account = msal.getActiveAccount() || msal.getAllAccounts()[0];
  if (!account) return null;
  try {
    return (await msal.acquireTokenSilent({ scopes: msScopes, account })).accessToken;
  } catch (e) {
    if (e instanceof InteractionRequiredAuthError) await msal.acquireTokenRedirect({ scopes: msScopes, account });
    throw e;
  }
}

/** The server rejected the session (expired, password changed, account disabled): back to sign-in. */
export function sessionExpired() {
  if (config.dev) return;
  safeSet(KEY, null);
  window.location.href = "/";
}
