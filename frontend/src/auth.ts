// Microsoft Entra ID sign-in (MSAL). Enabled when VITE_ENTRA_CLIENT_ID is set at build time;
// otherwise the app runs in dev mode and the API trusts the X-Dev-User header (local use only).
import { InteractionRequiredAuthError, PublicClientApplication, type AccountInfo } from "@azure/msal-browser";

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined;
const tenant = (import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined) || "organizations";
export const entraConfigured = Boolean(clientId);
const scopes = clientId ? [`api://${clientId}/access_as_user`] : [];

export const msal = entraConfigured
  ? new PublicClientApplication({
      auth: { clientId: clientId!, authority: `https://login.microsoftonline.com/${tenant}`, redirectUri: window.location.origin },
      cache: { cacheLocation: "localStorage" },
    })
  : null;

/** Call once at start-up. Returns the signed-in account, or null when the user still has to sign in. */
export async function initAuth(): Promise<AccountInfo | null> {
  if (!msal) return null;
  await msal.initialize();
  const res = await msal.handleRedirectPromise();
  const acct = res?.account || msal.getAllAccounts()[0] || null;
  if (acct) msal.setActiveAccount(acct);
  return acct;
}

export function signIn() {
  return msal?.loginRedirect({ scopes, prompt: "select_account" });
}

export function signOut() {
  return msal?.logoutRedirect({ postLogoutRedirectUri: window.location.origin });
}

export async function getToken(): Promise<string | null> {
  if (!msal) return null;
  const account = msal.getActiveAccount() || msal.getAllAccounts()[0];
  if (!account) return null;
  try {
    return (await msal.acquireTokenSilent({ scopes, account })).accessToken;
  } catch (e) {
    if (e instanceof InteractionRequiredAuthError) await msal.acquireTokenRedirect({ scopes, account });
    throw e;
  }
}
