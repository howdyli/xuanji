/**
 * useActivityStream — fetch-based SSE hook for real-time Agent activity streaming.
 *
 * Uses fetch + ReadableStream instead of native EventSource to support
 * custom Authorization headers (avoiding token exposure in URL).
 *
 * Features:
 * - Real-time activity push with <50ms latency
 * - Exponential backoff reconnection (max 3 retries)
 * - Automatic fallback signal for polling degradation
 * - Clean abort on unmount / session change
 */
import { useState, useEffect, useRef, useCallback } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────

export interface Activity {
  event_type: string
  agent_role: string
  tool_name: string
  skill_name: string
  status: 'active' | 'completed' | 'error'
  duration_ms: number
  metadata: Record<string, any>
  created_at: string
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'done' | 'error' | 'fallback'

interface UseActivityStreamResult {
  activities: Activity[]
  status: StreamStatus
  error: string
}

// ─── SSE Frame Parser ─────────────────────────────────────────────────────

interface SSEEvent {
  event: string
  data: string
}

function parseSSEChunk(chunk: string): SSEEvent[] {
  const events: SSEEvent[] = []
  const blocks = chunk.split('\n\n')

  for (const block of blocks) {
    if (!block.trim() || block.startsWith(':')) continue // skip comments/heartbeats

    let event = 'message'
    let data = ''

    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) {
        event = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        data = line.slice(6)
      }
    }

    if (data) {
      events.push({ event, data })
    }
  }

  return events
}

// ─── Hook ─────────────────────────────────────────────────────────────────

const MAX_RETRIES = 3
const BACKOFF_BASE_MS = 1000

export function useActivityStream(
  sessionId: string | null,
  enabled: boolean,
  authToken: string,
): UseActivityStreamResult {
  const [activities, setActivities] = useState<Activity[]>([])
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [error, setError] = useState('')

  const abortRef = useRef<AbortController | null>(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  // Track mounted state
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const connect = useCallback(async () => {
    if (!sessionId || !authToken) return

    // Abort any existing connection
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    if (retryCountRef.current === 0) {
      setStatus('connecting')
    }
    setError('')

    try {
      const res = await fetch(
        `/api/frontend/sessions/${sessionId}/activities/stream`,
        {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${authToken}`,
            Accept: 'text/event-stream',
          },
          signal: controller.signal,
        },
      )

      if (!res.ok) {
        throw new Error(`SSE connection failed (${res.status})`)
      }

      if (!res.body) {
        throw new Error('Response body is null — streaming not supported')
      }

      // Successfully connected
      if (!mountedRef.current) return
      setStatus('streaming')
      retryCountRef.current = 0

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (!mountedRef.current) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE frames (separated by double newline)
        const lastDoubleNewline = buffer.lastIndexOf('\n\n')
        if (lastDoubleNewline === -1) continue

        const processable = buffer.slice(0, lastDoubleNewline + 2)
        buffer = buffer.slice(lastDoubleNewline + 2)

        const events = parseSSEChunk(processable)

        for (const evt of events) {
          if (!mountedRef.current) break

          if (evt.event === 'activity') {
            try {
              const activity: Activity = JSON.parse(evt.data)
              setActivities(prev => {
                // Pair tool_call_start → tool_call_result: update in place
                if (activity.event_type === 'tool_call_result') {
                  const idx = [...prev].reverse().findIndex(
                    a => a.event_type === 'tool_call_start'
                      && a.tool_name === activity.tool_name
                      && a.status === 'active'
                  )
                  if (idx !== -1) {
                    const updated = [...prev]
                    updated[idx] = { ...updated[idx], status: 'completed', duration_ms: activity.duration_ms }
                    return updated
                  }
                }
                // Pair agent_started → agent_complete
                if (activity.event_type === 'agent_complete') {
                  const idx = prev.findIndex(
                    a => a.event_type === 'agent_started' && a.status === 'active'
                  )
                  if (idx !== -1) {
                    const updated = [...prev]
                    updated[idx] = { ...updated[idx], status: 'completed', duration_ms: activity.duration_ms }
                    return [...updated, activity]
                  }
                }
                return [...prev, activity]
              })
            } catch {
              // Skip malformed JSON
            }
          } else if (evt.event === 'done') {
            setStatus('done')
            return
          } else if (evt.event === 'timeout') {
            // Server idle timeout — attempt silent reconnect
            if (retryCountRef.current < MAX_RETRIES) {
              retryCountRef.current += 1
              const delay = BACKOFF_BASE_MS * Math.pow(2, retryCountRef.current - 1)
              retryTimerRef.current = setTimeout(() => {
                if (mountedRef.current) connect()
              }, delay)
            } else {
              setStatus('fallback')
            }
            return
          }
        }
      }

      // Stream ended without 'done' event — might be network drop
      if (mountedRef.current && status !== 'done') {
        handleDisconnect()
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      if (!mountedRef.current) return
      handleDisconnect()
    }
  }, [sessionId, authToken]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleDisconnect = useCallback(() => {
    if (!mountedRef.current) return

    if (retryCountRef.current < MAX_RETRIES) {
      retryCountRef.current += 1
      const delay = BACKOFF_BASE_MS * Math.pow(2, retryCountRef.current - 1)
      setStatus('connecting')
      retryTimerRef.current = setTimeout(() => {
        if (mountedRef.current) connect()
      }, delay)
    } else {
      // Exhausted retries — signal fallback to polling
      setStatus('fallback')
      setError('SSE 连接失败，已切换为轮询模式')
    }
  }, [connect])

  // ── Main effect: connect when enabled ──
  useEffect(() => {
    if (!enabled || !sessionId) {
      // Reset state when disabled
      abortRef.current?.abort()
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
      retryCountRef.current = 0
      setActivities([])
      setStatus('idle')
      setError('')
      return
    }

    // Start connection
    retryCountRef.current = 0
    setActivities([])
    connect()

    return () => {
      abortRef.current?.abort()
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
      retryCountRef.current = 0
    }
  }, [enabled, sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  return { activities, status, error }
}
