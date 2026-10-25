#!/usr/bin/env bash
# Start backend + frontend. Usage: ./scripts/dev.sh stub|real
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Use the venv created by scripts/setup.sh unless another env is already active.
if [[ -z "${VIRTUAL_ENV:-}${CONDA_PREFIX:-}" && -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

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
# .env must not override the offline stub chosen on the command line.
case "${1:-}" in stub|test) export AI_PROVIDER=stub ;; esac

if [[ "${1:-}" == "real" ]]; then
  case "${AI_PROVIDER:-openrouter}" in
    openrouter) _k="${OPENROUTER_API_KEY:-}" ;;
    openai) _k="${OPENAI_API_KEY:-}" ;;
    gemini) _k="${GEMINI_API_KEY:-}" ;;
    *) _k="ok" ;; # local needs no key
  esac
  if [[ -z "$_k" || "$_k" == "sk-or-..." ]]; then
    echo "NOTE: no AI key set for AI_PROVIDER=${AI_PROVIDER:-openrouter}. Add it to .env (see .env.example)" >&2
    echo "      and restart. Starting anyway; AI features will be unavailable. Use 'make stub' for the offline demo." >&2
  fi
fi

# Matplotlib is used by the chart templates.  A read-only home directory should
# not make startup noisy or force a new font cache for every process.
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/qi-stat-studio-matplotlib}"
mkdir -p "$MPLCONFIGDIR"

alembic upgrade head

# Recover from a stamped-but-empty sqlite DB (alembic_version at head, no tables).
# That state yields Internal Server Error on /auth/register: "no such table: users".
# This probe deliberately exits with 2 when it repaired a SQLite file.  It is
# not an error, so temporarily disable `errexit` to inspect that status.
set +e
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
set -e
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
UVICORN_ARGS=(api.main:app --host 127.0.0.1 --port "${API_PORT:-8000}")
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
  if curl -sf --max-time 2 http://127.0.0.1:${API_PORT:-8000}/health >/dev/null 2>&1; then
    echo "backend ready http://127.0.0.1:${API_PORT:-8000}"
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

(cd web && API_PORT="${API_PORT:-8000}" npx vite --host 127.0.0.1 --port 5173) &
FRONTEND_PID=$!
echo "frontend http://127.0.0.1:5173  mode=${AI_PROVIDER:-from .env}"

# Open the app once the frontend answers. Skipped with QISS_NO_BROWSER=1, or when this machine has no
# display or opener (a remote server). The address is printed either way.
APP_URL="http://127.0.0.1:5173"
for _ in $(seq 1 60); do
  curl -sf --max-time 2 "$APP_URL" >/dev/null 2>&1 && break
  sleep 1
done
echo "QI Stat Studio is ready at $APP_URL. Register there, then use Settings to add your AI key."
echo "A mentor opens the share link from the resident's Download screen. Press Ctrl+C here to stop."
if [[ "${QISS_NO_BROWSER:-0}" != "1" ]]; then
  if command -v open >/dev/null 2>&1; then
    open "$APP_URL" >/dev/null 2>&1 || echo "Could not open a browser. Open $APP_URL yourself." >&2
  elif command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$APP_URL" >/dev/null 2>&1 || echo "Could not open a browser. Open $APP_URL yourself." >&2
  fi
fi
wait
