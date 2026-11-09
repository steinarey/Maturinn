#!/bin/sh
set -e
alembic upgrade head
# The app reads /app/.env itself; uvicorn's proxy setting is read here, so take it from .env too
# unless it's set in the container's environment.
if [ -z "${FORWARDED_ALLOW_IPS:-}" ] && [ -f .env ]; then
  FORWARDED_ALLOW_IPS=$(sed -n 's/^[[:space:]]*FORWARDED_ALLOW_IPS[[:space:]]*=[[:space:]]*//p' .env | tail -n 1 | tr -d "\"'\r")
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
