/**
 * GlobalSearchView —— 全局搜索组件
 *
 * 功能：280ms 防抖搜索、结果按会话标题分组、
 *       搜索词高亮、骨架屏 Loading、点击跳转会话
 *       Cmd+K 快捷键由 App.tsx 全局处理
 *
 * API: GET /api/frontend/search?q=xxx&mode=hybrid&limit=20
 * 响应: { results: [{session_id, title, match_count, max_score, created_at, preview}], total, query }
 */
import { useState, useEffect, useRef, useCallback } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────

interface SessionResult {
  session_id: string
  title: string
  match_count: number
  max_score: number
  created_at: string
  preview: string
}

interface SearchSessionsResponse {
  results: SessionResult[]
  total: number
  query: string
}

export interface GlobalSearchViewProps {
  authToken: string
  onNavigateToSession: (sessionId: string) => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const API_BASE = '/api/frontend/search'

/** 高亮搜索词 — 返回 JSX 节点数组 */
function highlightText(text: string, query: string): React.ReactNode {
  if (!query.trim() || !text) return text
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-yellow-200/50 dark:bg-yellow-500/30 rounded-sm px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────

function SkeletonGroup() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-xl p-4 border"
          style={{
            backgroundColor: 'var(--bg-secondary, #fff)',
            borderColor: 'var(--border-light, #E2E8F0)',
          }}
        >
          <div className="flex items-center gap-2 mb-3">
            <div className="w-5 h-5 rounded bg-gray-200" />
            <div className="h-4 rounded bg-gray-200 w-2/5" />
            <div className="h-3 rounded bg-gray-100 w-14" />
          </div>
          <div className="h-3 rounded bg-gray-100 w-full" />
          <div className="h-3 rounded bg-gray-100 w-4/5 mt-2" />
        </div>
      ))}
    </div>
  )
}

// ─── Session Card ─────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number }) {
  const color = score > 0.8 ? '#16a34a' : score > 0.5 ? '#ca8a04' : '#9ca3af'
  return (
    <span
      className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full font-medium"
      style={{
        backgroundColor: `${color}18`,
        color,
      }}
    >
      ★ {score.toFixed(2)}
    </span>
  )
}

function SessionCard({
  session,
  query,
  onClick,
}: {
  session: SessionResult
  query: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-xl p-4 border transition-all hover:shadow-md cursor-pointer"
      style={{
        backgroundColor: 'var(--bg-secondary, #fff)',
        borderColor: 'var(--border-light, #E2E8F0)',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--primary-400, #60A5FA)' }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-light, #E2E8F0)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[14px]">📁</span>
        <span
          className="text-[13.5px] font-medium truncate flex-1 min-w-0"
          style={{ color: 'var(--text-primary, #1E293B)' }}
        >
          {highlightText(session.title || `会话 ${session.session_id.slice(0, 8)}...`, query)}
        </span>
        <ScoreBadge score={session.max_score} />
        <span
          className="shrink-0 text-[11.5px] px-1.5 py-0.5 rounded-full"
          style={{
            backgroundColor: 'var(--bg-tertiary, #F1F5F9)',
            color: 'var(--text-secondary, #64748B)',
          }}
        >
          {session.match_count} 条匹配
        </span>
      </div>
      {session.preview && (
        <div
          className="text-[12.5px] leading-relaxed pl-6"
          style={{ color: 'var(--text-secondary, #64748B)' }}
        >
          {highlightText(session.preview, query)}
        </div>
      )}
    </button>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────

export default function GlobalSearchView({ authToken, onNavigateToSession }: GlobalSearchViewProps) {
  const [query, setQuery] = useState('')
  const [sessions, setSessions] = useState<SessionResult[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState('')

  const inputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // ── Search API call ──
  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) return

    // Cancel previous request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    setSearched(true)

    try {
      const res = await fetch(`${API_BASE}?q=${encodeURIComponent(q.trim())}&mode=hybrid&limit=20`, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
        signal: controller.signal,
      })
      const data: SearchSessionsResponse = await res.json().catch(() => ({
        results: [],
        total: 0,
        query: q,
      }))
      if (!res.ok) {
        setError(`搜索失败 (${res.status})`)
        setSessions([])
        setTotal(0)
        return
      }
      setSessions(data.results ?? [])
      setTotal(data.total ?? 0)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError(e instanceof Error ? e.message : '搜索出错')
        setSessions([])
        setTotal(0)
      }
    } finally {
      setLoading(false)
    }
  }, [authToken])

  // ── 280ms debounce ──
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!query.trim()) {
      // Abort in-flight request + reset all state immediately
      abortRef.current?.abort()
      setSessions([])
      setTotal(0)
      setSearched(false)
      setLoading(false)
      setError('')
      return
    }
    timerRef.current = setTimeout(() => {
      doSearch(query.trim())
    }, 280)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Cleanup abort on unmount ──
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const handleClear = () => {
    // Abort in-flight request + reset all state
    abortRef.current?.abort()
    setQuery('')
    setSessions([])
    setTotal(0)
    setSearched(false)
    setLoading(false)
    setError('')
    inputRef.current?.focus()
  }

  /** Stop current search — abort + return to initial state */
  const handleStop = () => {
    abortRef.current?.abort()
    setLoading(false)
    setSearched(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && query.trim()) {
      if (timerRef.current) clearTimeout(timerRef.current)
      doSearch(query.trim())
    }
  }

  // ── Render ──
  return (
    <div className="flex-1 flex flex-col min-h-0" style={{ backgroundColor: 'var(--bg-primary, #F9FAFB)' }}>
      {/* Header */}
      <header className="shrink-0 px-6 lg:px-8 pt-8 pb-4">
        <div className="max-w-[800px] mx-auto">
          <h1 className="text-[22px] font-medium mb-1" style={{ color: 'var(--text-primary, #111827)' }}>
            全局搜索
          </h1>
          <p className="text-[13px] mb-5" style={{ color: 'var(--text-secondary, #6b7280)' }}>
            搜索所有会话中的消息内容
          </p>

          {/* Search bar */}
          <div className="max-w-[600px] mx-auto">
            <div
              className="flex items-center gap-2.5 px-4 py-3 rounded-xl border transition-all shadow-sm"
              style={{
                backgroundColor: 'var(--bg-secondary, #fff)',
                borderColor: 'var(--border-light, #E2E8F0)',
              }}
              onFocus={e => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--primary-500, #3B82F6)' }}
              onBlur={e => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-light, #E2E8F0)' }}
            >
              {/* Search icon — clickable */}
              <button
                onClick={() => { if (query.trim()) doSearch(query.trim()) }}
                className="shrink-0 p-0.5 rounded transition-colors hover:bg-gray-100"
                aria-label="搜索"
                style={{ color: 'var(--text-tertiary, #94A3B8)' }}
              >
                <svg
                  width="18" height="18" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="1.8"
                >
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
              </button>

              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="搜索会话内容..."
                autoFocus
                className="global-search-input flex-1 min-w-0 text-[14px] bg-transparent outline-none"
                style={{ color: 'var(--text-primary, #1E293B)' }}
              />

              {/* Clear / Stop button */}
              {query && loading && (
                <button
                  onClick={handleStop}
                  className="shrink-0 w-5 h-5 flex items-center justify-center rounded-full transition-colors hover:bg-gray-200"
                  style={{ color: 'var(--text-tertiary, #94A3B8)' }}
                  aria-label="停止搜索"
                  title="停止搜索"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="6" width="12" height="12" rx="2" />
                  </svg>
                </button>
              )}
              {query && !loading && (
                <button
                  onClick={handleClear}
                  className="shrink-0 w-5 h-5 flex items-center justify-center rounded-full transition-colors hover:bg-gray-200"
                  style={{ color: 'var(--text-tertiary, #94A3B8)' }}
                  aria-label="清除搜索"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              )}

              {/* Cmd+K hint */}
              {!query && (
                <kbd
                  className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono rounded border shrink-0"
                  style={{
                    color: 'var(--text-tertiary, #94A3B8)',
                    borderColor: 'var(--border-light, #E2E8F0)',
                    backgroundColor: 'var(--bg-tertiary, #F1F5F9)',
                  }}
                >
                  ⌘K
                </kbd>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Results area */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-4">
        <div className="max-w-[800px] mx-auto">

          {/* Loading skeleton */}
          {loading && <SkeletonGroup />}

          {/* Error */}
          {error && !loading && (
            <div className="p-4 rounded-xl bg-rose-50 border border-rose-100 text-[13px]" style={{ color: '#b91c1c' }}>
              ⚠️ {error}
            </div>
          )}

          {/* Results list */}
          {!loading && !error && sessions.length > 0 && (
            <div className="space-y-4">
              {/* Total count */}
              <div className="text-[12.5px]" style={{ color: 'var(--text-secondary, #64748B)' }}>
                找到 {total} 个会话
              </div>

              {sessions.map(session => (
                <SessionCard
                  key={session.session_id}
                  session={session}
                  query={query.trim()}
                  onClick={() => onNavigateToSession(session.session_id)}
                />
              ))}
            </div>
          )}

          {/* No results — backend returned empty */}
          {!loading && !error && searched && sessions.length === 0 && (
            <div className="text-center py-16">
              <div className="text-[36px] mb-3">🔍</div>
              <div className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #374151)' }}>
                没有找到匹配的内容
              </div>
              <div className="text-[12.5px] mt-1.5" style={{ color: 'var(--text-secondary, #6b7280)' }}>
                试试其他关键词
              </div>
            </div>
          )}

          {/* Initial state — no search yet */}
          {!loading && !error && !searched && (
            <div className="text-center py-20">
              <div className="text-[48px] mb-4 opacity-40">🔍</div>
              <div className="text-[14px]" style={{ color: 'var(--text-secondary, #6b7280)' }}>
                输入关键词搜索所有会话内容
              </div>
              <div className="text-[12px] mt-2" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
                支持 ⌘K 快速聚焦 · 支持模糊搜索
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
