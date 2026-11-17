import { expect, test } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const apiKey = 'autopsy-playwright-local-key'
const headers = { 'X-Autopsy-Api-Key': apiKey }
const goldenDir = path.resolve(process.cwd(), '../evals/golden')
const cases = ['toy_healthy', 'toy_short_body', 'toy_publish_timeout']

test('serves the run list and diagnosed lineage from the bundled UI', async ({ page, request }) => {
  const manifest = await fs.readFile(path.join(goldenDir, cases[0], 'manifest.yaml'), 'utf8')
  const registered = await request.put('/v1/pipelines/toy-summarizer/versions/0.1.0', {
    headers: { ...headers, 'Content-Type': 'application/yaml' },
    data: manifest,
  })
  expect(registered.ok()).toBeTruthy()

  for (const caseName of cases) {
    const caseDir = path.join(goldenDir, caseName)
    const trace = JSON.parse(await fs.readFile(path.join(caseDir, 'trace.json'), 'utf8'))
    const ingested = await request.post('/v1/traces', { headers, data: trace })
    expect(ingested.ok(), `${caseName} trace ingestion`).toBeTruthy()
    for (const filename of await fs.readdir(path.join(caseDir, 'artifacts'))) {
      const artifact = JSON.parse(await fs.readFile(path.join(caseDir, 'artifacts', filename), 'utf8'))
      const uploaded = await request.post('/v1/artifacts', { headers, data: artifact })
      expect(uploaded.ok(), `${caseName} ${filename} artifact upload`).toBeTruthy()
    }
  }

  await page.addInitScript((key) => localStorage.setItem('pipeline-autopsy-api-key', key), apiKey)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Pipeline runs' })).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(3, { timeout: 30_000 })

  await page.goto('/runs/toy_short_body')
  await expect(page.getByRole('heading', { name: /toy_short_body/ })).toBeVisible()
  await expect(page.locator('[data-role="origin"][data-stage="fetch"]')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('schema.minLength')).toBeVisible()
})
