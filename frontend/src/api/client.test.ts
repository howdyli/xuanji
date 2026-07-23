import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { apiFetch, rawFetch, ApiError, classifyStatus, classifyError, streamMessage } from './client'

describe('classifyStatus', () => {
  it('maps auth failures to permission_denied', () => {
    expect(classifyStatus(401)).toBe('permission_denied')
    expect(classifyStatus(403)).toBe('permission_denied')
  })
  it('maps 429 to quota_exceeded', () => {
    expect(classifyStatus(429)).toBe('quota_exceeded')
  })
  it('maps 5xx to server_error', () => {
    expect(classifyStatus(500)).toBe('server_error')
    expect(classifyStatus(503)).toBe('server_error')
  })
  it('maps other client errors to unknown', () => {
    expect(classifyStatus(404)).toBe('unknown')
  })
})

describe('classifyError', () => {
  it('reads errorType from ApiError', () => {
    const err = new ApiError('boom', 'quota_exceeded', 429)
    expect(classifyError(err)).toBe('quota_exceeded')
  })
  it('classifies abort as network_timeout', () => {
    const err = new DOMException('aborted', 'AbortError')
    expect(classifyError(err)).toBe('network_timeout')
  })
  it('classifies generic fetch failure as network_timeout', () => {
    expect(classifyError(new Error('Failed to fetch'))).toBe('network_timeout')
  })
  it('defaults to unknown', () => {
    expect(classifyError(new Error('weird'))).toBe('unknown')
  })
})

describe('rawFetch / apiFetch', () => {
  beforeEach(() => {
    // Self-contained localStorage stub (jsdom's is not reliably exposed here).
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    })
    localStorage.setItem('auth_token', 'tkn')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('attaches Authorization header and serializes json body', async () => {
    const spy = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', spy)

    const data = await apiFetch<{ ok: boolean }>('/api/frontend/message', {
      method: 'POST',
      json: { a: 1 },
    })

    expect(data).toEqual({ ok: true })
    const init = spy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer tkn')
    expect(headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ a: 1 }))
  })

  it('throws a classified ApiError on non-2xx (the res.ok regression)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ error: 'no access' }), {
          status: 403,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(rawFetch('/x')).rejects.toMatchObject({
      errorType: 'permission_denied',
      status: 403,
      message: 'no access',
    })
  })

  it('wraps network failures into an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await expect(rawFetch('/x')).rejects.toBeInstanceOf(ApiError)
    await expect(rawFetch('/x')).rejects.toMatchObject({ errorType: 'network_timeout' })
  })
})

// Build a Response whose body streams the given SSE text (optionally split).
function sseResponse(frames: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f))
      controller.close()
    },
  })
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

describe('streamMessage', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    })
    localStorage.setItem('auth_token', 'tkn')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('accumulates deltas and resolves with the done payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'event: start\ndata: {"msg_id":"m1","session_id":"s1","trace_id":"t1"}\n\n',
          'event: delta\ndata: {"text":"Hel"}\n\n',
          'event: delta\ndata: {"text":"lo"}\n\n',
          'event: done\ndata: {"msg_id":"m1","reply":"Hello","session_id":"s1","duration_ms":12,"trace_id":"t1"}\n\n',
        ]),
      ),
    )

    const deltas: string[] = []
    let started = ''
    const done = await streamMessage(
      { content: 'hi' },
      {
        onStart: (d) => { started = d.msg_id },
        onDelta: (t) => deltas.push(t),
      },
    )

    expect(started).toBe('m1')
    expect(deltas).toEqual(['Hel', 'lo'])
    expect(done.reply).toBe('Hello')
    expect(done.session_id).toBe('s1')
  })

  it('handles frames split across chunk boundaries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'event: delta\ndata: {"text":"AB',
          'C"}\n\nevent: done\ndata: {"msg_id":"m2","reply":"ABC","session_id":"s2","duration_ms":1,"trace_id":"t2"}\n\n',
        ]),
      ),
    )

    const deltas: string[] = []
    const done = await streamMessage({ content: 'x' }, { onDelta: (t) => deltas.push(t) })
    expect(deltas.join('')).toBe('ABC')
    expect(done.reply).toBe('ABC')
  })

  it('throws a classified ApiError on an error frame', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'event: start\ndata: {"msg_id":"m3","session_id":"s3","trace_id":"t3"}\n\n',
          'event: error\ndata: {"message":"llm exploded"}\n\n',
        ]),
      ),
    )
    await expect(streamMessage({ content: 'x' })).rejects.toMatchObject({
      errorType: 'server_error',
      message: 'llm exploded',
    })
  })

  it('propagates a pre-dispatch ApiError from a non-2xx establishment', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ error: 'unauthorized' }), {
          status: 401,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )
    await expect(streamMessage({ content: 'x' })).rejects.toMatchObject({
      status: 401,
      errorType: 'permission_denied',
    })
  })
})
