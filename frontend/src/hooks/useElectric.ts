// React hooks for ElectricSQL and general app state
import { useState, useCallback, useEffect } from 'react'

export function useElectricClient() {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    async function init() {
      try {
        const { initElectric } = await import('../electric/db')
        await initElectric()
      } catch {
        // ElectricSQL is optional
      }
      setReady(true)
    }
    init()
  }, [])

  return { ready }
}

// Generic fetch hook for REST API
export function useApiFetch() {
  const [loading, setLoading] = useState(false)

  const apiPost = useCallback(async (path: string, body: any) => {
    setLoading(true)
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer test-token-dev-2024',
        },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.text()
        throw new Error(`HTTP ${res.status}: ${err}`)
      }
      return await res.json()
    } finally {
      setLoading(false)
    }
  }, [])

  const apiGet = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await fetch(path, {
        headers: { 'Authorization': 'Bearer test-token-dev-2024' },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return await res.json()
    } finally {
      setLoading(false)
    }
  }, [])

  return { apiPost, apiGet, loading }
}
