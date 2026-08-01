/**
 * AgentTimeline —— 多 Agent 协作过程时间线可视化
 *
 * 两种模式：
 *   实时模式（isPolling=true, 无 turnId）：
 *     优先使用 SSE 实时推送（<50ms 延迟），连接失败 3 次后降级为 2s 轮询
 *   历史模式（turnId 有值）：挂载时一次性查询，折叠面板展示
 *
 * API:
 *   SSE:  GET /api/frontend/sessions/{session_id}/activities/stream
 *   Poll: GET /api/frontend/sessions/{session_id}/activities?mode=active|history&turn_id=xxx
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useActivityStream } from '../hooks/useActivityStream'
import type { Activity, StreamStatus } from '../hooks/useActivityStream'

interface AgentTimelineProps {
  sessionId: string | null
  turnId?: string
  isPolling: boolean
  authToken: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const ROLE_LABELS: Record<string, string> = {
  orchestrator: '协调器',
  skill_agent: '技能代理',
  researcher: '研究员',
  coder: '编程员',
  writer: '写作员',
}

function formatDuration(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`
}

function getActivityLabel(a: Activity): string {
  switch (a.event_type) {
    case 'agent_started':
      return `${ROLE_LABELS[a.agent_role] ?? a.agent_role} 开始处理`
    case 'thinking':
      return '思考中...'
    case 'tool_call_start':
      return `调用工具: ${a.tool_name}`
    case 'tool_call_result':
      return `${a.tool_name} 完成 (${formatDuration(a.duration_ms)})`
    case 'skill_used':
      return `使用技能: ${a.skill_name}`
    case 'agent_complete':
      return `生成回复完成 (${formatDuration(a.duration_ms)})`
    case 'agent_error':
      return `处理出错: ${a.metadata?.error ?? '未知错误'}`
    default:
      return a.event_type
  }
}

/** Whether the event should show as indented (tool/skill detail) */
function isIndented(a: Activity): boolean {
  return a.event_type === 'tool_call_start' || a.event_type === 'tool_call_result' || a.event_type === 'skill_used'
}

// ─── Icons ────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: Activity['status'] }) {
  if (status === 'completed') {
    return (
      <span className="shrink-0 w-2 h-2 rounded-full bg-green-500" />
    )
  }
  if (status === 'error') {
    return (
      <span className="shrink-0 w-2 h-2 rounded-full bg-red-500" />
    )
  }
  // active
  return (
    <span className="shrink-0 w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
  )
}

function CompletedCheck() {
  return (
    <svg
      width="12" height="12" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0 text-green-500"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

// ─── Loading Dots ─────────────────────────────────────────────────────────

function LoadingDots() {
  return (
    <span className="inline-flex items-center gap-0.5 ml-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  )
}

// ─── Timeline Item ────────────────────────────────────────────────────────

function TimelineItem({ activity, isLast }: { activity: Activity; isLast: boolean }) {
  const label = getActivityLabel(activity)
  const indent = isIndented(activity)
  const isResult = activity.event_type === 'tool_call_result' && activity.status === 'completed'

  return (
    <div className="relative flex gap-3" style={{ paddingLeft: indent ? '1.5rem' : undefined }}>
      {/* Vertical line + dot column */}
      <div className="flex flex-col items-center shrink-0" style={{ width: '8px' }}>
        <div className="relative z-10 mt-1.5">
          {isResult ? <CompletedCheck /> : <StatusDot status={activity.status} />}
        </div>
        {!isLast && (
          <div
            className="flex-1 w-0.5 my-1"
            style={{ backgroundColor: 'var(--border-light, #E2E8F0)' }}
          />
        )}
      </div>

      {/* Content */}
      <div className={`pb-4 min-w-0 ${isLast ? '' : ''}`}>
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[13px] leading-snug"
            style={{ color: 'var(--text-primary, #1E293B)' }}
          >
            {label}
          </span>
          {activity.duration_ms > 0 && activity.event_type === 'tool_call_result' && (
            <span className="text-xs" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
              {formatDuration(activity.duration_ms)}
            </span>
          )}
        </div>

        {/* Sub-info: skill name for tool calls */}
        {activity.event_type === 'tool_call_start' && activity.skill_name && (
          <div
            className="text-[12px] mt-0.5"
            style={{ color: 'var(--text-secondary, #64748B)' }}
          >
            技能: {activity.skill_name}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Status Indicator ─────────────────────────────────────────────────────

function StreamIndicator({ status }: { status: StreamStatus }) {
  if (status === 'connecting') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--text-secondary, #64748B)' }}>
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        连接中...
      </span>
    )
  }
  if (status === 'streaming') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--text-secondary, #64748B)' }}>
        <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
        实时同步
      </span>
    )
  }
  if (status === 'done') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--text-secondary, #64748B)' }}>
        <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
        执行完成
      </span>
    )
  }
  return null
}

// ─── Main Component ───────────────────────────────────────────────────────

export default function AgentTimeline({ sessionId, turnId, isPolling, authToken }: AgentTimelineProps) {
  const [pollActivities, setPollActivities] = useState<Activity[]>([])
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [usePolling, setUsePolling] = useState(false) // fallback flag

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const listEndRef = useRef<HTMLDivElement | null>(null)

  const isHistoryMode = !!turnId

  // ── SSE real-time stream (primary mode) ──
  const { activities: sseActivities, status: streamStatus, error: sseError } = useActivityStream(
    isHistoryMode ? null : sessionId,
    isPolling && !isHistoryMode && !usePolling,
    authToken,
  )

  // ── Detect SSE fallback → switch to polling ──
  useEffect(() => {
    if (streamStatus === 'fallback') {
      setUsePolling(true)
    }
  }, [streamStatus])

  // ── Choose active data source ──
  const activities = (!isHistoryMode && !usePolling) ? sseActivities : pollActivities
  const currentStatus: StreamStatus = (!isHistoryMode && !usePolling) ? streamStatus : 'streaming'

  // ── Auto-scroll to bottom on new activities ──
  useEffect(() => {
    if (!isHistoryMode && activities.length > 0) {
      listEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activities.length, isHistoryMode])

  // ── Polling fetch (fallback + history mode) ──
  const fetchActivities = useCallback(async () => {
    if (!sessionId || !authToken) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const mode = isHistoryMode ? 'history' : 'active'
    const params = new URLSearchParams({ mode })
    if (turnId) params.set('turn_id', turnId)

    try {
      const res = await fetch(
        `/api/frontend/sessions/${sessionId}/activities?${params.toString()}`,
        {
          method: 'GET',
          headers: { Authorization: `Bearer ${authToken}` },
          signal: controller.signal,
        },
      )
      if (!res.ok) {
        setError(`获取活动失败 (${res.status})`)
        return
      }
      const data = await res.json().catch(() => ({ activities: [] }))
      setPollActivities(data.activities ?? [])
      setError('')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError(e instanceof Error ? e.message : '获取活动出错')
      }
    }
  }, [sessionId, authToken, isHistoryMode, turnId])

  // ── Polling mode: interval (fallback for real-time) ──
  useEffect(() => {
    if (isHistoryMode) return
    if (!usePolling) return // SSE is primary

    if (isPolling && sessionId) {
      fetchActivities()
      intervalRef.current = setInterval(fetchActivities, 2000)
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      abortRef.current?.abort()
      setPollActivities([])
      setError('')
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [isPolling, sessionId, isHistoryMode, usePolling]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── History mode: fetch once on mount ──
  useEffect(() => {
    if (!isHistoryMode || !sessionId) return
    fetchActivities()
    return () => { abortRef.current?.abort() }
  }, [isHistoryMode, sessionId, turnId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Cleanup on unmount ──
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  // ── Render ──

  // Nothing to show when no session
  if (!sessionId) return null

  // History mode: collapsible panel
  if (isHistoryMode) {
    const count = activities.length
    if (count === 0 && !error) return null

    return (
      <div
        className="rounded-lg border overflow-hidden"
        style={{
          borderColor: 'var(--border-light, #E2E8F0)',
          backgroundColor: 'var(--bg-secondary, #fff)',
        }}
      >
        <button
          onClick={() => setExpanded(prev => !prev)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer"
          style={{ color: 'var(--text-primary, #1E293B)' }}
        >
          <span>Agent 执行过程 ({count} 步)</span>
          <svg
            width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round"
            className="shrink-0 transition-transform"
            style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {expanded && (
          <div className="px-4 pb-3 pt-1 max-h-80 overflow-y-auto">
            {error && (
              <div className="text-[12px] text-red-500 mb-2">⚠️ {error}</div>
            )}
            {activities.map((a, i) => (
              <TimelineItem key={`${a.created_at}-${i}`} activity={a} isLast={i === activities.length - 1} />
            ))}
          </div>
        )}
      </div>
    )
  }

  // Real-time mode (SSE primary, polling fallback)
  const displayError = error || sseError
  if (!isPolling && activities.length === 0 && currentStatus === 'idle') return null

  return (
    <div className="py-2">
      {/* Status indicator bar */}
      <div className="flex items-center justify-between px-2 mb-1">
        <StreamIndicator status={currentStatus} />
        {usePolling && (
          <span className="text-[11px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
            轮询模式
          </span>
        )}
      </div>

      {displayError && (
        <div className="text-[12px] text-red-500 mb-2 px-2">⚠️ {displayError}</div>
      )}

      {activities.length > 0 ? (
        <div className="max-h-80 overflow-y-auto">
          {activities.map((a, i) => (
            <TimelineItem key={`${a.created_at}-${i}`} activity={a} isLast={i === activities.length - 1} />
          ))}
          <div ref={listEndRef} />
        </div>
      ) : (
        // Empty state while connecting/streaming
        <div
          className="flex items-center gap-2 text-[13px] px-2 py-1"
          style={{ color: 'var(--text-secondary, #64748B)' }}
        >
          处理中...<LoadingDots />
        </div>
      )}
    </div>
  )
}
