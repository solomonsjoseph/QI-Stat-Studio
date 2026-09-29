#!/usr/bin/env bash
# Start backend + frontend. Usage: ./scripts/dev.sh stub|real
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

case "${1:-}" in
  stub|test) export AI_PROVIDER=stub ;;
  real) ;; # uses AI_PROVIDER from .env (openrouter/openai/local)
  *) echo "usage: $0 stub|real"; exit 1 ;;
esac

alembic upgrade head
trap 'kill 0' EXIT INT TERM

# Bind IPv4 explicitly; wait until the worker is actually accepting (spaCy load can take 30-90s).
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 &
echo "waiting for backend /health (first start can take up to ~90s for spaCy)..."
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "backend ready http://127.0.0.1:8000"
    break
  fi
  if [[ "$i" -eq 90 ]]; then
    echo "backend failed to become healthy in 90s. Check uvicorn output above." >&2
    exit 1
  fi
  sleep 1
done

(cd web && npx vite --host 127.0.0.1 --port 5173) &
echo "frontend http://127.0.0.1:5173  mode=${AI_PROVIDER:-from .env}"
wait
