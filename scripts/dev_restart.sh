#!/bin/bash
# Rebuild the web app and restart the local server on :8077.
cd "$(dirname "$0")/.."
(cd web && npx tsc -b && npx vite build >/dev/null) || exit 1
pid=$(netstat -ano | grep ":8077 " | grep LISTEN | awk '{print $5}' | head -1)
[ -n "$pid" ] && taskkill //PID $pid //F >/dev/null 2>&1
(PYTHONIOENCODING=utf-8 .venv/Scripts/python -m uvicorn encore.app:create_app --factory --port 8077 > var/server.log 2>&1 &)
for i in $(seq 1 40); do curl -s localhost:8077/api/status >/dev/null && break; sleep 1; done
curl -s localhost:8077/api/status | head -c 200; echo
