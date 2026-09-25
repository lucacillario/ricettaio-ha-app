#!/bin/sh
set -eu

mkdir -p /data /data/uploads
chown -R ricettaio:ricettaio /data

exec su-exec ricettaio uvicorn app.main:app \
    --app-dir /app/backend \
    --host 0.0.0.0 \
    --port 8099 \
    --no-proxy-headers
