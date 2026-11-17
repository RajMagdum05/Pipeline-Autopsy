import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const backendDir = path.resolve(process.cwd(), '..')
const runId = `${Date.now()}-${process.pid}`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8080/ui/',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'python -m uvicorn autopsy.main:app --host 127.0.0.1 --port 8080',
    cwd: backendDir,
    url: 'http://127.0.0.1:8080/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ...process.env,
      AUTOPSY_DATABASE_URL: `sqlite:///./ui-playwright-${runId}.db`,
      AUTOPSY_BLOB_DIR: `./ui-playwright-blobs-${runId}`,
      AUTOPSY_API_KEY: 'autopsy-playwright-local-key',
      AUTOPSY_SETTLE_SECONDS: '5',
      AUTOPSY_RECORD_DIR: '',
    },
  },
})
