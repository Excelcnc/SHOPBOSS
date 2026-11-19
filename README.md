# CNC Quote

A web application that helps CNC machine shop estimators quote faster. It reads incoming RFQs
(email + STEP models + PDF/DXF drawings), recognises the features that cost money, and proposes a
conservative price per part from the shop's own rates. The estimator can override every number,
save variants, and send a clean quote: **Part number · Revision · Quantity · Price per part**.

Proprietary software of Excel CNC (see LICENSE). Other shops can sign up themselves with any email address; each shop's data is isolated.

## What it does

| Area | What works today |
|---|---|
| **Intake** | Microsoft 365 quoting mailbox via Microsoft Graph (webhook + delta sync), any mailbox via IMAP, or upload of `.eml` / Outlook `.msg` / loose files / ZIPs. Customer, contact, RFQ number, part numbers, revisions, quantity breaks, dates, material and special processes are extracted with a confidence score each. |
| **3D models** | STEP (incl. assemblies) analysed with the OpenCascade kernel on exact B-rep surfaces: size, volume, area, faces/edges; through/blind holes, counterbores, countersinks, drill points, internal grooves, pockets, slots, steps, bosses, fillets/internal radii, angled and freeform faces; undercuts (faces not reachable from ±X ±Y ±Z), thin walls (ray sampled), deep holes and pockets, turned-part detection, setup count. Interactive 3D viewer with feature highlighting, sections and measuring. |
| **Drawings** | PDF text layer with positions (title block, tolerances, ISO fits, hole callouts, threads, GD&T, Ra, coatings, heat treat, standards, notes); DXF; PNG/JPG scans via AI vision (optional). Click a callout to see it on the sheet. |
| **Matching** | Pairs each model with its drawing (part number, file name, matching dimensions); flags model/drawing revision conflicts. |
| **Assemblies** | Product tree and BOM from STEP; purchased components flagged (ISO/DIN fasteners, dowels, bearings, vendor part numbers); machined quantity = per-assembly quantity × sets. |
| **Estimating** | Material (detected, shop price or reference price), complexity score 1-10 with its drivers, machine-type suggestion, cycle/setup/programming/inspection time, outside processes from drawing notes, volume tiers, contingency, margin. Unknowns are priced on the expensive side and listed under *Margin protection*. |
| **Overrides & variants** | Every calculated value is editable and restorable; **Save as** creates a variant (material, quantity, anything) without touching the original; final versions are locked. |
| **History** | CSV import (JobBOSS² exports or any spreadsheet), similar-job search by size, features and material, calibration of the time model against actual hours. Won/lost quotes feed history automatically. |
| **Quote output** | Minimal customer quote PDF; internal cost breakdown never leaves the app. |

See [docs/STATUS.md](docs/STATUS.md) for exactly what is operational vs. needs configuration.

## Run it locally

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16, Redis (optional for dev).

```bash
# backend
cd backend
pip install -r requirements.txt
createdb cncquote   # user/password from DATABASE_URL in .env
RUN_JOBS_INLINE=true uvicorn app.main:app --reload --port 8000
```

```bash
# frontend (second terminal)
cd frontend
npm install
npm run dev     # http://localhost:5173
```

With `AUTH_MODE=dev` there is no sign-in (use `AUTH_MODE=prod` to try accounts locally); you act as `estimator@example.com` in a demo shop. Try the
files in `samples/` (upload `RFQ_BWP-2026-0418.eml`, or the bracket STEP + PDF).

Tests: `cd backend && pip install -r requirements-dev.txt && pytest` (needs a `cncquote_test` database).

Online: see [docs/RENDER_SETUP.md](docs/RENDER_SETUP.md) (Render Blueprint in `render.yaml`).

Docker: `cp .env.example .env && docker compose up --build` then open http://localhost:8080.

## Architecture

```
Microsoft 365 mailbox ─(Graph webhook + delta)─┐
IMAP forwarding mailbox ───────────────────────┤
Upload (.eml/.msg/files) ──────────────────────┤
                                               ▼
                         FastAPI (api)  ──► Redis queue ──► worker (rq)
                              │                              │  CAD: OpenCascade (OCP)
                              │                              │  Drawings: PyMuPDF / ezdxf
                              │                              │  AI extraction (optional, Claude)
                              ▼                              ▼
                        PostgreSQL  ◄──────────── cost engine (deterministic)
                              ▲
                     React + TypeScript web app (estimators)
```

The AI only extracts information (email fields, drawing callouts) and always reports confidence and
location; prices come from the deterministic engine and the shop's own rates.

Key code:
- `backend/app/services/cad/analyze.py` — STEP feature recognition
- `backend/app/services/drawing/extract.py` — drawing reading
- `backend/app/services/costing/engine.py` — cost engine (see docs/ESTIMATING.md)
- `backend/app/services/pipeline.py` — RFQ → parts → quotes
- `backend/app/services/email/graph.py` — Microsoft 365 intake
- `frontend/src/pages/PartEstimate.tsx` — the estimator's main screen

## Documentation
- [docs/RENDER_SETUP.md](docs/RENDER_SETUP.md) — put the app online (Render)
- [docs/M365_SETUP.md](docs/M365_SETUP.md) — connect the quoting mailbox and Microsoft sign-in
- [docs/ESTIMATING.md](docs/ESTIMATING.md) — how prices are calculated, and calibrating with your JobBOSS² data
- [docs/STATUS.md](docs/STATUS.md) — what works, what needs configuration, known limits
- [docs/ROADMAP.md](docs/ROADMAP.md) — next steps (JobBOSS², Mastercam, GitHub sign-in, offline)
