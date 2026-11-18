# Status

## Operational (tested)

- Upload intake: `.eml`, Outlook `.msg`, loose files, ZIP archives; RFQ field extraction with confidence.
- STEP analysis incl. assemblies/BOM; feature recognition listed in the README; 3D viewer.
- PDF and DXF drawing extraction with locations; scans are detected as "no text layer".
- Model ↔ drawing pairing, revision-conflict and material-conflict warnings.
- Cost engine, overrides, Save As variants, locked final versions, quote PDF.
- Shop configuration: rates, machines, material prices, outside processes, pricing policy.
- History CSV import, similar-job search, won/lost feedback into history, calibration report.
- Multi-shop data isolation (shop per sign-in tenant).
- 19 automated backend tests (`cd backend && pytest`), plus a browser walkthrough of all screens.

## Implemented, needs your configuration to verify

- **Microsoft 365 mailbox intake** (Graph webhook, subscription renewal, delta sync). Unit-tested
  handshake only; needs your tenant (docs/M365_SETUP.md).
- **IMAP intake** for a forwarding address.
- **Microsoft sign-in**: backend token validation done; frontend MSAL wiring pending.
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
- Database migrations: tables are created on startup; Alembic migrations before first production upgrade.
