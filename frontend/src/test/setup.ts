// Vitest global setup — registers jest-dom matchers (toBeInTheDocument, etc.)
// and cleans up the DOM between tests.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom does not always provide a functional localStorage; provide a minimal
// in-memory implementation so code paths that read auth tokens (apiFetch) work.
if (typeof globalThis.localStorage === 'undefined' || typeof globalThis.localStorage.getItem !== 'function') {
  const store = new Map<string, string>()
  globalThis.localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, String(v)) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() { return store.size },
  } as Storage
}

afterEach(() => {
  cleanup()
})
