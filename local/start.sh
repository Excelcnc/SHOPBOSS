#!/bin/sh
# macOS / Linux: start CNC Quote on this computer (needs Docker Desktop or Docker Engine).
set -e
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  key=$(head -c 48 /dev/urandom | base64 | tr -d '+/=\n')
  sed "s/__GENERATED__/$key/" local/env.local.template > .env
fi
docker compose up -d --build
echo "Waiting for http://localhost:8080 ..."
until curl -sf http://localhost:8080/api/health >/dev/null; do sleep 5; done
echo "CNC Quote is running: http://localhost:8080"
(open http://localhost:8080 2>/dev/null || xdg-open http://localhost:8080 2>/dev/null) || true
