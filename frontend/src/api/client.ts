/**
 * 统一 API 客户端
 *
 * 目标：消除各组件里重复的 fetch + auth header + 错误处理，
 * 并把「HTTP 状态 → ErrorType」的分类逻辑集中到一处，避免依赖
 * 脆弱的字符串匹配（如 errorMessage.includes('401')）。
 *
 * 关键修复：原先多处 `fetch` 后直接 `res.json()`，从不检查 `res.ok`，
 * 导致 401/403/429/500 的响应体被当作成功结果解析。apiFetch 会显式
 * 校验状态码并抛出带 errorType 的 ApiError。
 */

import type { ErrorType } from '../components/UXComponents'

const API_BASE = '/api/frontend'

/** 默认请求超时（毫秒）。超时归类为 network_timeout。 */
const DEFAULT_TIMEOUT_MS = 60_000

/** 带分类信息的 API 错误。调用方可读取 `errorType` 直接驱动 ErrorDisplay。 */
export class ApiError extends Error {
  readonly errorType: ErrorType
  readonly status: number
  readonly body: unknown

  constructor(message: string, errorType: ErrorType, status: number, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.errorType = errorType
    this.status = status
    this.body = body
  }
}

/** 将 HTTP 状态码映射为 UX 错误类型。 */
export function classifyStatus(status: number): ErrorType {
  if (status === 401 || status === 403) return 'permission_denied'
  if (status === 429) return 'quota_exceeded'
  if (status >= 500) return 'server_error'
  return 'unknown'
}

/**
 * 将任意异常（含 ApiError / AbortError / 网络错误）归类为 ErrorType。
 * 供 catch 块统一使用，替代字符串 includes 匹配。
 */
export function classifyError(err: unknown): ErrorType {
  if (err instanceof ApiError) return err.errorType
  if (err instanceof DOMException && err.name === 'AbortError') return 'network_timeout'
  if (err instanceof Error) {
    const msg = err.message.toLowerCase()
    if (msg.includes('timeout') || msg.includes('aborted')) return 'network_timeout'
    if (msg.includes('failed to fetch') || msg.includes('networkerror')) return 'network_timeout'
  }
  return 'unknown'
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  /** JSON 请求体（自动序列化并设置 Content-Type）。 */
  json?: unknown
  /** 原始请求体（与 json 二选一）。 */
  body?: BodyInit
  /** 是否附带 Authorization 头，默认 true。 */
  auth?: boolean
  /** 超时毫秒数，默认 60s；传 0 表示不超时。 */
  timeoutMs?: number
}

/**
 * 统一 fetch 封装：附带鉴权头、JSON 序列化、超时、状态校验与错误分类。
 *
 * @returns 已解析的响应体（自动按 content-type 解析 JSON / 文本 / blob 由调用方选择时应改用 rawFetch）
 * @throws ApiError 当响应非 2xx 时；网络/超时错误亦会被封装为 ApiError。
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const res = await rawFetch(path, options)
  // 204 无内容
  if (res.status === 204) return undefined as T
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return (await res.json()) as T
  }
  return (await res.text()) as unknown as T
}

/**
 * 与 apiFetch 相同的鉴权/超时/状态校验，但返回原始 Response，
 * 供需要 blob / stream / 自定义解析的场景使用（如文件导出）。
 */
export async function rawFetch(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const {
    json,
    body,
    auth = true,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    headers,
    signal,
    ...rest
  } = options

  const url = path.startsWith('http') || path.startsWith('/') ? path : `${API_BASE}/${path}`

  const finalHeaders: Record<string, string> = {
    ...(auth ? authHeaders() : {}),
    ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
    ...((headers as Record<string, string>) || {}),
  }

  // 超时控制：合并外部 signal（若有）与内部超时 signal。
  const controller = new AbortController()
  const timer =
    timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : undefined
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let res: Response
  try {
    res = await fetch(url, {
      ...rest,
      headers: finalHeaders,
      body: json !== undefined ? JSON.stringify(json) : body,
      signal: controller.signal,
    })
  } catch (err) {
    // 网络失败 / 超时 —— 归类后重新抛出，调用方拿到统一的 ApiError。
    throw new ApiError(
      err instanceof Error ? err.message : String(err),
      classifyError(err),
      0,
    )
  } finally {
    if (timer) clearTimeout(timer)
  }

  if (!res.ok) {
    let parsedBody: unknown
    let detail = ''
    try {
      const text = await res.text()
      detail = text
      try {
        parsedBody = JSON.parse(text)
        const maybeMsg = (parsedBody as { error?: string; message?: string })
        detail = maybeMsg.error || maybeMsg.message || text
      } catch {
        /* 非 JSON 响应体，保留原始文本 */
      }
    } catch {
      /* 读取响应体失败，忽略 */
    }
    throw new ApiError(
      detail || `HTTP ${res.status}`,
      classifyStatus(res.status),
      res.status,
      parsedBody,
    )
  }

  return res
}

// ─── SSE 流式聊天 ────────────────────────────────────────────────────────────

export interface StreamMessageBody {
  content: string
  session_id?: string
  routing_key?: string
  sender_id?: string
  expert?: string
}

export interface StreamStartData {
  msg_id: string
  session_id: string
  trace_id: string
}

export interface StreamDoneData extends StreamStartData {
  reply: string
  duration_ms: number
}

export interface StreamMessageHandlers {
  /** 收到 start 帧（含 msg_id / session_id / trace_id）。 */
  onStart?: (data: StreamStartData) => void
  /** 收到一段增量文本，用于打字机渲染。 */
  onDelta?: (text: string) => void
  /** 收到 done 帧，携带完整回复用于对账。 */
  onDone?: (data: StreamDoneData) => void
  /** 外部中断信号（如组件卸载 / 用户取消）。 */
  signal?: AbortSignal
}

/** 解析一段 SSE 文本，返回其中的完整事件帧。 */
function parseSSEBlocks(chunk: string): { event: string; data: string }[] {
  const out: { event: string; data: string }[] = []
  for (const block of chunk.split('\n\n')) {
    if (!block.trim() || block.startsWith(':')) continue
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7).trim()
      else if (line.startsWith('data: ')) data = line.slice(6)
    }
    if (data) out.push({ event, data })
  }
  return out
}

/**
 * 通过 SSE 流式发送一条消息并逐段消费回复。
 *
 * 使用 fetch + ReadableStream（而非原生 EventSource）以携带 Authorization 头。
 * 成功时返回完整回复用于对账；服务器 `error` 帧或非 2xx 均抛出带分类的 ApiError。
 * 调用方可在 stream 失败时回退到一次性 `apiFetch('/message')`。
 */
export async function streamMessage(
  body: StreamMessageBody,
  handlers: StreamMessageHandlers = {},
): Promise<StreamDoneData> {
  // 不设整体超时：AI 生成可能耗时数分钟，连接建立后靠 signal / 服务器关闭收尾。
  const res = await rawFetch(`${API_BASE}/message/stream`, {
    method: 'POST',
    timeoutMs: 0,
    json: body,
    headers: { Accept: 'text/event-stream' },
    signal: handlers.signal,
  })

  if (!res.body) {
    throw new ApiError('响应体为空，当前环境不支持流式', 'server_error', res.status)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let acc = ''
  let done: StreamDoneData | null = null

  try {
    while (true) {
      const { done: streamEnd, value } = await reader.read()
      if (streamEnd) break
      buffer += decoder.decode(value, { stream: true })

      const lastSep = buffer.lastIndexOf('\n\n')
      if (lastSep === -1) continue
      const processable = buffer.slice(0, lastSep + 2)
      buffer = buffer.slice(lastSep + 2)

      for (const evt of parseSSEBlocks(processable)) {
        if (evt.event === 'start') {
          handlers.onStart?.(JSON.parse(evt.data) as StreamStartData)
        } else if (evt.event === 'delta') {
          const { text } = JSON.parse(evt.data) as { text: string }
          acc += text
          handlers.onDelta?.(text)
        } else if (evt.event === 'done') {
          done = JSON.parse(evt.data) as StreamDoneData
        } else if (evt.event === 'error') {
          const { message } = JSON.parse(evt.data) as { message: string }
          throw new ApiError(message || '流式生成失败', 'server_error', res.status)
        }
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 已释放 */
    }
  }

  if (done) {
    handlers.onDone?.(done)
    return done
  }
  // 流意外结束但未收到 done：用已累积文本兜底，避免丢失内容。
  throw new ApiError('流式连接意外中断', 'network_timeout', res.status, { partial: acc })
}
