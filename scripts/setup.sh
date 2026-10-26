#!/usr/bin/env bash
# Idempotent first-run setup used by `make stub` / `make real`. Skips anything already done.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

# Python env: use the active venv/conda env, else create and use ./.venv.
if [[ -z "${VIRTUAL_ENV:-}${CONDA_PREFIX:-}" ]]; then
  if [[ ! -d .venv ]]; then
    # The dependencies need Python 3.12 or newer. Take the newest one installed unless PYTHON says otherwise.
    py="${PYTHON:-}"
    for c in python3.14 python3.13 python3.12 python3; do
      [[ -n "$py" ]] && break
      command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' && py="$c"
    done
    [[ -n "$py" ]] || { echo "setup: Python 3.12 or newer is required but was not found. Install it, then run make again." >&2; exit 1; }
    echo "setup: creating .venv with $py"
    "$py" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Reinstall when requirements.txt changed since the last install, so an older environment is brought up to date.
sum_of() { python -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"; }
py_stamp="$(python -c 'import sys; print(sys.prefix)')/.qiss-requirements"
if [[ "$(cat "$py_stamp" 2>/dev/null)" != "$(sum_of requirements.txt)" ]] || ! python -c "import fastapi, uvicorn, alembic, spacy, litellm" 2>/dev/null; then
  echo "setup: installing Python dependencies"
  python -m pip install -r requirements.txt
  sum_of requirements.txt > "$py_stamp"
fi
# PHI scrubber needs this model (api/middleware/phi_scrubber.py).
if ! python -c "import spacy.util, sys; sys.exit(0 if spacy.util.is_package('en_core_web_sm') else 1)" 2>/dev/null; then
  echo "setup: downloading spaCy model en_core_web_sm"
  python -m spacy download en_core_web_sm
fi

js_stamp=web/node_modules/.qiss-lock
if [[ "$(cat "$js_stamp" 2>/dev/null)" != "$(sum_of web/package-lock.json)" ]]; then
  echo "setup: npm ci"
  (cd web && npm ci)
  sum_of web/package-lock.json > "$js_stamp"
fi

# .env is git-ignored. Create it from the template, then fill FERNET_KEY only if empty.
[[ -f .env ]] || { echo "setup: creating .env from .env.example"; cp .env.example .env; }
python - <<'PY'
import re
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
p = Path(".env")
t = p.read_text()
# Every clone gets its own session-signing secret instead of the shared placeholder from .env.example.
if not re.search(r"^SECRET_KEY=\s*(?!change-me)[^\s#]{16,}", t, re.M):
    line = "SECRET_KEY=" + secrets.token_urlsafe(48)
    t = re.sub(r"^SECRET_KEY=.*$", line, t, count=1, flags=re.M) if re.search(r"^SECRET_KEY=", t, re.M) else t + "\n" + line + "\n"
    p.write_text(t)
    print("setup: generated SECRET_KEY in .env")
if not re.search(r"^FERNET_KEY=\s*[^\s#]", t, re.M):
    line = "FERNET_KEY=" + Fernet.generate_key().decode()
    if re.search(r"^FERNET_KEY=", t, re.M):
        t = re.sub(r"^FERNET_KEY=.*$", line, t, count=1, flags=re.M)
    else:
        t += "\n" + line + "\n"
    p.write_text(t)
    print("setup: generated FERNET_KEY in .env (back it up; uploads cannot be decrypted without it)")
PY
