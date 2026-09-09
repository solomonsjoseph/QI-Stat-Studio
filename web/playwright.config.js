import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173'
const backendURL = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000'
const shouldStartServer = process.env.QISS_E2E_START_SERVER === '1'
const e2eDb = process.env.QISS_E2E_DB || 'e2e_qi_stat_studio.db'
const backendEnv = [
  'FERNET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
  'SECRET_KEY=e2e-secret-key',
  `DB_URL=sqlite:///./${e2eDb}`,
  'OPENROUTER_API_KEY=',
  'AI_PROVIDER=stub',
  'PYTHONPATH=.',
].join(' ')

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: shouldStartServer
    ? [
        {
          command: `cd .. && rm -f ${e2eDb} && ${backendEnv} alembic upgrade head && ${backendEnv} uvicorn api.main:app --host 127.0.0.1 --port 8000`,
          url: `${backendURL}/health`,
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          command: 'npm run dev -- --host 127.0.0.1',
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ]
    : undefined,
})
