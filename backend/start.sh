#!/usr/bin/env sh
set -e

# Railway/Render provide PORT. Default to 8080.
export SOURCERESS_HOST="${SOURCERESS_HOST:-0.0.0.0}"
export SOURCERESS_PORT="${SOURCERESS_PORT:-${PORT:-8080}}"

# Run migrations (best-effort) when using a real DB.
# For sqlite demo/local, skip.
DB_URL_EFFECTIVE="${DATABASE_URL:-${DB_URL:-}}"
if [ -n "$DB_URL_EFFECTIVE" ] && echo "$DB_URL_EFFECTIVE" | grep -q '^postgres'; then
  echo "[start] running migrations..."
  # Retry a bit in case DB is waking up.
  n=0
  until [ $n -ge 10 ]; do
    if alembic -c alembic.ini upgrade head; then
      echo "[start] migrations ok"
      break
    fi
    n=$((n+1))
    echo "[start] migrations failed, retrying ($n/10) ..."
    sleep 2
  done
fi

echo "[start] launching server on ${SOURCERESS_HOST}:${SOURCERESS_PORT}"
exec python run_server.py
