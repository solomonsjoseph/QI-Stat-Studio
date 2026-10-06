#!/usr/bin/env bash
# Start backend + frontend. Usage: ./scripts/dev.sh stub|real
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

case "${1:-}" in
  stub|test) export AI_PROVIDER=stub ;;
  real) ;; # uses AI_PROVIDER from .env (openrouter/openai/local/gemini)
  *) echo "usage: $0 stub|real"; exit 1 ;;
esac

# Load .env so alembic and the schema check see the same DB_URL as uvicorn.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

alembic upgrade head

# Recover from a stamped-but-empty sqlite DB (alembic_version at head, no tables).
# That state yields Internal Server Error on /auth/register: "no such table: users".
python - <<'PY'
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine.url import make_url

url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL") or "sqlite:///./qi_stat_studio.db"
engine = create_engine(url)
tables = set(inspect(engine).get_table_names())
engine.dispose()
if "users" in tables:
    sys.exit(0)

parsed = make_url(url)
if parsed.get_backend_name() != "sqlite":
    print("ERROR: users table missing after alembic upgrade head.", file=sys.stderr)
    sys.exit(1)
if tables - {"alembic_version"}:
    print(f"ERROR: users table missing; existing tables={sorted(tables)}", file=sys.stderr)
    sys.exit(1)

db_path = Path(parsed.database or "qi_stat_studio.db")
if not db_path.is_absolute():
    db_path = Path.cwd() / db_path
db_path.unlink(missing_ok=True)
print(f"dev.sh: reset empty sqlite DB at {db_path}; re-running migrations")
sys.exit(2)
PY
schema_status=$?
if [[ "$schema_status" -eq 2 ]]; then
  alembic upgrade head
  python - <<'PY'
import os, sys
from sqlalchemy import create_engine, inspect
url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL") or "sqlite:///./qi_stat_studio.db"
engine = create_engine(url)
ok = "users" in set(inspect(engine).get_table_names())
engine.dispose()
if not ok:
    print("ERROR: users table still missing after sqlite reset.", file=sys.stderr)
sys.exit(0 if ok else 1)
PY
elif [[ "$schema_status" -ne 0 ]]; then
  exit "$schema_status"
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  # Kill only our children. `kill 0` takes down the whole process group and can
  # segfault make on some hosts when the wait loop exits early.
  if [[ -n "${FRONTEND_PID}" ]]; then kill "${FRONTEND_PID}" 2>/dev/null || true; fi
  if [[ -n "${BACKEND_PID}" ]]; then kill "${BACKEND_PID}" 2>/dev/null || true; fi
  wait "${FRONTEND_PID}" 2>/dev/null || true
  wait "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Default: no --reload. Reloader + WatchFiles on networked filesystems can keep
# /health unreachable for minutes while the worker imports. Set DEV_RELOAD=1 to
# opt in. litellm and spaCy load lazily on first use.
UVICORN_ARGS=(api.main:app --host 127.0.0.1 --port 8000)
if [[ "${DEV_RELOAD:-0}" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi
uvicorn "${UVICORN_ARGS[@]}" &
BACKEND_PID=$!

WAIT_SECS="${DEV_HEALTH_WAIT:-300}"
echo "waiting for backend /health (up to ${WAIT_SECS}s)..."
for i in $(seq 1 "${WAIT_SECS}"); do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "backend process exited before becoming healthy. Check uvicorn output above." >&2
    exit 1
  fi
  if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "backend ready http://127.0.0.1:8000"
    break
  fi
  if [[ "$i" -eq "${WAIT_SECS}" ]]; then
    echo "backend failed to become healthy in ${WAIT_SECS}s. Check uvicorn output above." >&2
    exit 1
  fi
  if (( i % 15 == 0 )); then
    echo "  still waiting (${i}s)..."
  fi
  sleep 1
done

(cd web && npx vite --host 127.0.0.1 --port 5173) &
FRONTEND_PID=$!
echo "frontend http://127.0.0.1:5173  mode=${AI_PROVIDER:-from .env}"
wait
