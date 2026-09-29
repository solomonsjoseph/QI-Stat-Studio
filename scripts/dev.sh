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
uvicorn api.main:app --reload --port 8000 &
(cd web && npx vite --host 127.0.0.1 --port 5173) &
echo "backend http://127.0.0.1:8000  frontend http://127.0.0.1:5173  mode=${AI_PROVIDER:-from .env}"
wait
