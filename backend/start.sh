#!/bin/sh
# One container runs everything (Render single-service deployment):
# database migrations, the analysis worker, the mailbox poller and the web server.
set -e
alembic upgrade head
if [ -n "$REDIS_URL" ] && [ "$RUN_JOBS_INLINE" != "true" ]; then
  (while true; do rq worker analysis --url "$REDIS_URL" || true; echo "worker exited; restarting"; sleep 5; done) &
fi
(while true; do python -m app.poller || true; echo "poller exited; restarting"; sleep 30; done) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
