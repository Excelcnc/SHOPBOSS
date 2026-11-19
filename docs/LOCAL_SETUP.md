# Run CNC Quote on your own computer

This runs the whole app on one Windows PC (or Mac). It's for trying it out and for working on it:
there's **no sign-in** and it can only be opened **from that computer** (http://localhost:8080).
For the team portal, use Render (docs/RENDER_SETUP.md).

## What you need (one time)

1. **Windows 10/11** with about **10 GB free disk** and **8 GB RAM** (16 GB better).
2. **Docker Desktop**: https://www.docker.com/products/docker-desktop/ → *Download for Windows* →
   install with the default options (it uses WSL 2) → restart the PC → open Docker Desktop and accept
   the terms. You can skip signing in to Docker. Wait until the bottom-left says **Engine running**.

## Get the files

Either:
- **Download the ZIP** you were given (`cnc-quote-local.zip`), right-click → **Extract All…** →
  choose e.g. `C:\CNC Quote`, or
- **From GitHub** (signed in): https://github.com/Excelcnc/SHOPBOSS → branch **m365-signin** →
  green **Code** button → **Download ZIP** → Extract All.

Keep the folder somewhere permanent; don't run it from inside the ZIP.

## Start / stop

| Double-click | What it does |
|---|---|
| **Start CNC Quote.cmd** | First time: creates settings, builds and starts the app (10–20 min), then opens it in your browser. Later: under a minute. |
| **Stop CNC Quote.cmd** | Stops it. All RFQs, quotes and settings are kept. |
| **Show logs.cmd** | Shows what the app is doing, for troubleshooting. |

If Windows shows "Windows protected your PC", click **More info → Run anyway** (the scripts are plain
text files you can open in Notepad to check).

Try it with the files in the `samples` folder: **New RFQ** → drop `RFQ_BWP-2026-0418.eml`, or a
STEP file together with its PDF drawing.

## Settings

The first start creates a file named `.env` in the folder (open with Notepad). Optional lines:
- `ANTHROPIC_API_KEY=` turns on AI reading of emails and scanned drawings.
- `GRAPH_CLIENT_SECRET=` lets the local app read purchasing@ through the "CNC Quote mailbox" app.
  Paste the secret only into this file, never into chat or email. To connect mailboxes with
  "Sign in with Microsoft" locally, also add `http://localhost:8080/api/oauth/microsoft/callback` as a
  Web redirect URI on that app in Entra.

After changing `.env`, run Stop, then Start.

## Updating to a newer version

Download the new ZIP and extract it over the old folder (keep your `.env`), then Start. Your data
lives in Docker, not in the folder, so it's kept.

## Removing everything

Stop, then in a terminal in the folder: `docker compose down -v` (the `-v` deletes all local data),
and delete the folder.

## Folder layout

```
Start CNC Quote.cmd     Stop CNC Quote.cmd     Show logs.cmd     <- double-click these
backend/                Python API, CAD/drawing analysis, cost engine, tests
frontend/               React web app
docs/                   guides (this file, Render, Microsoft 365, estimating, status)
local/                  scripts and settings template used by the .cmd files
samples/                example RFQ email, STEP models and drawings to try
deploy/                 Excel CNC server settings (no secrets)
Dockerfile, docker-compose.yml, render.yaml   how the app is built and run
```
