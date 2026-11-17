import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    restoreMocks: true,
    exclude: ['tests/e2e/**', '**/node_modules/**', '**/dist/**'],
  },
})
