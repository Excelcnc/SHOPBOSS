// Microsoft Entra ID sign-in hook-up point. When VITE_ENTRA_CLIENT_ID is set, plug in @azure/msal-browser
// here and return an access token for the API scope. Without it the app runs in dev mode (header auth).
export const entraConfigured = Boolean(import.meta.env.VITE_ENTRA_CLIENT_ID);

export async function getToken(): Promise<string | null> {
  if (!entraConfigured) return null;
  const w = window as any;
  return w.__cncToken ? await w.__cncToken() : null;
}
