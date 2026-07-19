import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Test-only config. Kept separate from vite.config.ts so the production
// build (`tsc -b && vite build`) stays untouched by test tooling.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    restoreMocks: true,
  },
})
