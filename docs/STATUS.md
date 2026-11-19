# Status

## Operational (tested)

- Upload intake: `.eml`, Outlook `.msg`, loose files, ZIP archives; RFQ field extraction with confidence.
- Multiple connected mailboxes (Shop settings › Email accounts): Microsoft 365 via the Graph app and other providers via IMAP; per-mailbox folder, RFQ filter, test, check now, counts; duplicates across mailboxes merged. Tested against simulated Graph and IMAP servers; the live tenant answered and recognised the Excel CNC tenant and mailbox app.
- STEP analysis incl. assemblies/BOM; feature recognition listed in the README; 3D viewer.
- Parts lists (BOM) read from assembly PDF drawings (ruled or aligned tables): item, qty, part number, description, material, vendor, make/buy. The drawing governs quantities and make/buy; differences from the 3D model are flagged; items only on the drawing (washers, labels) are added.
- Lead time per quantity (queue + material + production + outside processes, in weeks), editable on the customer quote and printed on the PDF.
- PDF and DXF drawing extraction with locations; scans are detected as "no text layer".
- Model ↔ drawing pairing, revision-conflict and material-conflict warnings.
- Cost engine, overrides, Save As variants, locked final versions, quote PDF.
- Shop configuration: rates, machines, material prices, outside processes, pricing policy.
- History CSV import, similar-job search, won/lost feedback into history, calibration report.
- Accounts with any email provider: sign up with email + password, 6-digit code by email, sign in,
  forgot password, lockout after repeated wrong passwords. Each sign-up gets its own shop with default
  rates; admins invite teammates from **Shop settings → Team**. Optional "Sign in with Microsoft".
- Multi-shop data isolation; Microsoft 365 mailbox connections limited to shops proven at
  `GRAPH_SHOP_DOMAINS`.
- Database migrations (Alembic), applied automatically on start.
- Render deployment (`render.yaml`, docs/RENDER_SETUP.md): one service runs web, worker and poller.
- 38 automated backend tests (`cd backend && pytest`), plus browser walkthroughs (sign-up → first
  priced RFQ → invite teammate takes under a minute of app time).

## Implemented, needs your configuration to verify

- **Microsoft 365 mailbox intake** (Graph webhook, subscription renewal, delta sync). Unit-tested
  handshake only; needs your tenant (docs/M365_SETUP.md).
- **IMAP intake** for a forwarding address.
- **Microsoft sign-in**: sign-in screen (MSAL) and server token validation (v1 and v2 tokens) done; needs the sign-in app's client ID to test.
- **Setup check**: `python -m app.check_m365` verifies the mailbox app, permission, access policy and settings.
- **AI extraction** (Claude): email fields and drawing reading incl. scanned drawings, with
  confidence and locations. Needs `ANTHROPIC_API_KEY`. Not exercised against the live API in tests.
  RFQs with export-control wording (ITAR/EAR) are never sent to the AI.
- **Docker Compose** files are written but were not built in the development environment.

## Not yet supported

- DWG drawings (needs a server-side converter: ODA File Converter or LibreDWG) — ask for PDF/DXF.
- Native CAD (SolidWorks, Parasolid, NX, CATIA, Inventor) — ask for STEP. IGES/STL are recognised
  but not feature-analysed.
- Thread forms are not modelled in STEP; threads come from drawings and tap-drill sizes.
- Ribs and straight-edge chamfers are reported as generic faces, not named features.
- Live material market prices: reference prices are a dated snapshot; enter your supplier prices.
- JobBOSS² API and Mastercam integration (see ROADMAP).
- Other companies' Microsoft 365 mailboxes: no "Connect Outlook" button yet (needs delegated
  permissions). Until then they use IMAP or forward RFQs to a mailbox they can connect.
- Gmail one-click connect (needs Google's security review); IMAP with an app password works today.
- Export-controlled (ITAR/EAR) data: not suitable for an ordinary cloud host. AI is skipped for such
  RFQs, but the files are still stored. Tell shops not to upload ITAR technical data.
