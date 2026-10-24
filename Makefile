.PHONY: setup stub real test e2e

# Backend port (override: make stub API_PORT=9000). Read by dev.sh, vite proxy, playwright.
API_PORT ?= 8010
export API_PORT

# Offline AI stub, no API key. Open http://127.0.0.1:5173
setup:
	./scripts/setup.sh

stub: setup
	./scripts/dev.sh stub

# Real AI from .env (openrouter/openai/local). Needs API key set there.
real: setup
	./scripts/dev.sh real

test:
	FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= PYTHONPATH=. python -m pytest -q
	cd web && npm run test

e2e:
	cd web && QISS_E2E=1 npx playwright test e2e/critical-path.spec.js --reporter=list
