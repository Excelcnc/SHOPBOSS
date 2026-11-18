# Connecting Microsoft 365

Two separate things, both done once by a Microsoft 365 admin:

1. **Mailbox intake** — the app reads new mail in the quoting mailbox (e.g. `quotes@yourshop.com`).
2. **Sign-in** — estimators sign in with their Microsoft work accounts (`AUTH_MODE=entra`).

## 1. Mailbox intake (Microsoft Graph, application permission)

1. Entra admin center → **App registrations** → **New registration**. Name: `CNC Quote mailbox`.
   Supported account types: *this organizational directory only*. No redirect URI.
2. **API permissions** → Add → Microsoft Graph → **Application permissions** → `Mail.Read` →
   **Grant admin consent**.
3. **Certificates & secrets** → New client secret. Copy the value.
4. Restrict the app to the quoting mailbox only (strongly recommended; otherwise `Mail.Read`
   applies to every mailbox). In Exchange Online PowerShell:

   ```powershell
   New-DistributionGroup -Name "CNC Quote mailboxes" -Type Security -Members quotes@yourshop.com
   New-ApplicationAccessPolicy -AppId <client id> -PolicyScopeGroupId "CNC Quote mailboxes" `
     -AccessRight RestrictAccess -Description "CNC Quote reads only the quoting mailbox"
   Test-ApplicationAccessPolicy -Identity quotes@yourshop.com -AppId <client id>
   ```

5. Set in `.env`:

   ```
   GRAPH_TENANT_ID=<directory (tenant) id>
   GRAPH_CLIENT_ID=<application (client) id>
   GRAPH_CLIENT_SECRET=<secret value>
   GRAPH_MAILBOX=quotes@yourshop.com
   GRAPH_WEBHOOK_URL=https://<your public host>/api/intake/graph/notify
   GRAPH_CLIENT_STATE=<random string>
   INTAKE_TENANT_KEY=entra:<directory (tenant) id>
   ```

6. Start the `poller` service. It creates the webhook subscription, renews it before it expires
   (Graph subscriptions on mail last under 3 days), and runs a delta sync every 5 minutes so nothing
   is missed if a notification is lost. On its first run it records the current position and does
   **not** import old mail.

The webhook URL must be reachable from the internet over HTTPS. Without a public URL the poller's
delta sync alone still works (new RFQs appear within 5 minutes).

Estimators can also simply forward RFQs to the quoting mailbox.

## 2. Sign-in with Microsoft (Entra ID)

1. New app registration `CNC Quote` → **Expose an API** → set Application ID URI
   (`api://<client id>`) and add a scope `access_as_user`.
2. Add a **Single-page application** platform with your site URL as redirect URI.
3. For a single shop, set *Accounts in this organizational directory only*. To let other shops
   use the same deployment, choose *Accounts in any organizational directory* — each tenant gets its
   own isolated shop on first sign-in.
4. `.env`: `AUTH_MODE=entra`, `ENTRA_TENANT_ID=<tenant id or "organizations">`, `ENTRA_CLIENT_ID=<client id>`;
   frontend build arg `VITE_ENTRA_CLIENT_ID=<client id>`.

> The frontend sign-in (MSAL) hook is stubbed in `frontend/src/auth.ts`; wiring `@azure/msal-browser`
> into it is the first item in docs/ROADMAP.md. The backend token validation is implemented.
