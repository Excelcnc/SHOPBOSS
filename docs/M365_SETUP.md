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

   Frontend build settings: `VITE_ENTRA_CLIENT_ID=<sign-in app client id>` and `VITE_ENTRA_TENANT_ID=<tenant id>`.
5. Under **Authentication** for the sign-in app, add these Single-page application redirect URIs:
   the pilot's address (e.g. `https://quote.excel-cnc.com`) and `http://localhost:5173` for local testing.

## Connecting several mailboxes

Mailboxes are added in the app under **Shop settings › Email accounts** (admins only):

- **Microsoft 365** mailboxes (shared or personal, same tenant) use the mailbox app above — no
  password per mailbox. Add each one to the access-policy group so the app may read it:
  `Add-DistributionGroupMember -Identity "CNC Quote mailboxes" -Member sales@yourshop.com`
  (policy changes can take up to an hour to apply). Then click **Test** in the app.
- **Other providers** (Gmail, web hosts…) connect over IMAP with an app password, stored encrypted
  with the server's `SECRET_KEY` (set it once to a long random value and keep it).
- Each mailbox has its own folder, RFQ filter, on/off switch, "Check now", and import counts. The same
  email arriving in two connected mailboxes becomes one RFQ.

## Shared mailboxes (e.g. purchasing@)

A shared mailbox also receives invoices, order confirmations and suppliers' quotes. Two safeguards:

- `GRAPH_FOLDER=RFQ` — the app watches one folder only. Create it in Outlook (top level or under
  Inbox) and fill it with an Outlook rule or by dragging customer RFQs into it. Most reliable.
- `INTAKE_FILTER=true` (default) — an email becomes an RFQ only if it has a 3D model attached, or
  RFQ wording ("RFQ", "request for quote", "please quote"…). Invoices, shipping notices and supplier
  quotations are skipped. Anything missed can still be uploaded by hand as a .msg file.

A dedicated address (e.g. quotes@) that customers send RFQs to is cleanest long-term.

## 3. Check it

On the server, after filling in `.env`:

```bash
cd backend
python -m app.check_m365                        # mailbox access, permission, settings
python -m app.check_m365 someone.else@yourshop.com   # confirms the app can NOT read other mailboxes
```

Every line should say OK. It prints message counts only, never message contents.
