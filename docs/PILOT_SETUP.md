# Excel CNC pilot: setup from GitHub

## Part A — Microsoft app registrations (one is missing)

You found one client ID because only one app registration exists. The pilot uses two:

| App registration | Used for | Holds a secret? |
|---|---|---|
| **CNC Quote mailbox** (exists) | Server reads the RFQ folder in purchasing@ (Mail.Read application permission) | Yes |
| **CNC Quote** (to create) | Estimators sign in with their Microsoft accounts | No |

Keeping them separate means the app that can read the mailbox is never the one browsers talk to.

### A1. Check the existing one
Entra admin center (https://entra.microsoft.com) → **Identity → Applications → App registrations → All applications**.
Open the app with client ID `02a1a3b2-f8ea-4f71-889e-89937d38902b`. If its name isn't "CNC Quote mailbox", rename it under
**Branding & properties**. It should have **API permissions → Microsoft Graph → Mail.Read (Application)** with
"Granted for Excel CNC", and a client secret under **Certificates & secrets**.

### A2. Create the sign-in app
1. **App registrations → New registration**
   - Name: `CNC Quote`
   - Supported account types: **Accounts in this organizational directory only (single tenant)**
   - Redirect URI: platform **Single-page application (SPA)**, URI `http://localhost:8080`
   - **Register**
2. On **Overview**, copy the **Application (client) ID**. This is the sign-in client ID (not a secret).
3. **Expose an API** → Application ID URI → **Add** → accept `api://<that client id>` → **Save**.
   Then **Add a scope**: name `access_as_user`, who can consent **Admins and users**,
   admin consent display name `Access CNC Quote`, description `Sign in to CNC Quote`, **Enabled** → **Add scope**.
4. **API permissions**: Microsoft Graph **User.Read (Delegated)** is there by default. Click **Grant admin consent for Excel CNC**.
5. Do **not** create a secret for this app.
6. Later, when the pilot has an https address, add it under **Authentication → Single-page application → Add URI**.

## Part B — Install on a shop PC or server from GitHub

Needs: Windows 10/11 Pro or Windows Server (or Linux), 16 GB RAM, ~20 GB disk, a GitHub account with access to Excelcnc/SHOPBOSS.

1. Install **Git for Windows** (https://git-scm.com/download/win) and **Docker Desktop** (https://www.docker.com/products/docker-desktop, WSL 2 option). Restart.
2. Open PowerShell:
   ```powershell
   git clone https://github.com/Excelcnc/SHOPBOSS.git
   cd SHOPBOSS
   git checkout m365-signin      # until this branch is merged into main
   copy deploy\excel-cnc.env .env
   notepad .env
   ```
   Git opens a browser window to sign in to GitHub the first time.
3. In `.env` fill in:
   - `GRAPH_CLIENT_SECRET` = the secret **Value** from the mailbox app (A1)
   - `GRAPH_CLIENT_STATE` = any long random text
   - `ENTRA_CLIENT_ID` = the **new sign-in app** client ID (A2); the web page reads it from the server
   - optional `ANTHROPIC_API_KEY`
4. In Outlook, create the **RFQ** folder in purchasing@ (top level or under Inbox) and a rule that moves customer RFQs into it.
5. Start it (first build takes 10–20 minutes):
   ```powershell
   docker compose up -d --build
   ```
6. Check the Microsoft 365 connection; every line should say OK:
   ```powershell
   docker compose exec api python -m app.check_m365
   docker compose exec api python -m app.check_m365 someone.else@excel-cnc.com
   ```
7. Open **http://localhost:8080** on that PC and sign in. The first person to sign in becomes the shop admin.
8. Updating later: `git pull` then `docker compose up -d --build`.

### Limits of a shop-PC install
- Microsoft only allows sign-in over plain `http` on `localhost`, so other estimators' PCs need an
  **https** address. Options: host on Azure, or put the PC behind a reverse proxy with a certificate.
- Without a public https address, new RFQs arrive by 5-minute polling instead of instantly.
- The Docker images have not yet been built end-to-end (the development environment could not download
  OS packages). If the first build fails, send the error text.
