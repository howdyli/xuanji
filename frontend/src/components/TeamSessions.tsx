/**
 * TeamSessions — 团队共享会话列表
 *
 * 展示指定团队内被共享的会话，支持点击进入（只读/可编辑取决于 permission）。
 */
import { useState, useEffect, useCallback } from 'react'

interface SharedSession {
  id: string
  title: string
  shared_by: string
  share_permission: 'view' | 'edit'
  message_count: number
  updated_at: string
}

interface Team {
  id: number
  name: string
}

interface TeamSessionsProps {
  authToken: string
  onSessionSelect?: (sessionId: string, permission: string) => void
}

export default function TeamSessions({ authToken, onSessionSelect }: TeamSessionsProps) {
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)
  const [sessions, setSessions] = useState<SharedSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Fetch teams on mount
  useEffect(() => {
    fetch('/api/frontend/teams', {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then(r => r.json())
      .then(data => {
        const t = data.teams || []
        setTeams(t)
        if (t.length > 0) setSelectedTeamId(t[0].id)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [authToken])

  // Fetch team sessions when team changes
  const fetchSessions = useCallback(async () => {
    if (!selectedTeamId) { setSessions([]); return }
    try {
      const res = await fetch(`/api/frontend/teams/${selectedTeamId}/sessions`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      if (!res.ok) throw new Error('获取失败')
      const data = await res.json()
      setSessions(data.sessions || [])
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取团队会话失败')
    }
  }, [selectedTeamId, authToken])

  useEffect(() => { fetchSessions() }, [fetchSessions])

  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso)
      const now = new Date()
      const diffMs = now.getTime() - d.getTime()
      if (diffMs < 60000) return '刚刚'
      if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)} 分钟前`
      if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)} 小时前`
      return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
    } catch {
      return ''
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>加载中...</span>
      </div>
    )
  }

  if (teams.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>还没有加入团队</span>
        <span className="text-[13px]" style={{ color: 'var(--text-tertiary)' }}>加入团队后可查看共享会话</span>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header + team selector */}
      <div className="px-6 py-4 border-b" style={{ borderColor: 'var(--border-light)' }}>
        <h2 className="text-[18px] font-bold mb-3" style={{ color: 'var(--text-primary)' }}>团队会话</h2>
        {teams.length > 1 && (
          <div className="flex gap-2 flex-wrap">
            {teams.map(t => (
              <button
                key={t.id}
                onClick={() => setSelectedTeamId(t.id)}
                className="text-[12px] px-3 py-1.5 rounded-full border transition-colors"
                style={{
                  borderColor: selectedTeamId === t.id ? 'var(--accent-primary, #3B82F6)' : 'var(--border-light)',
                  background: selectedTeamId === t.id ? 'rgba(59,130,246,0.08)' : 'transparent',
                  color: selectedTeamId === t.id ? 'var(--accent-primary, #3B82F6)' : 'var(--text-secondary)',
                }}
              >
                {t.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-3 text-[13px] text-red-500 bg-red-50 px-3 py-2 rounded-lg">{error}</div>
      )}

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>暂无共享会话</span>
            <span className="text-[13px]" style={{ color: 'var(--text-tertiary)' }}>
              团队成员在聊天中点击「共享」后，会话会出现在这里
            </span>
          </div>
        ) : (
          <div className="space-y-2">
            {sessions.map(s => (
              <button
                key={s.id}
                onClick={() => onSessionSelect?.(s.id, s.share_permission)}
                className="w-full text-left p-4 rounded-xl border transition-all hover:shadow-sm"
                style={{ borderColor: 'var(--border-light)', background: 'var(--bg-secondary)' }}
              >
                <div className="flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                      {s.title || '未命名会话'}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[12px]" style={{ color: 'var(--text-tertiary)' }}>
                        {s.shared_by} 共享
                      </span>
                      <span className="text-[12px]" style={{ color: 'var(--text-tertiary)' }}>
                        {s.message_count} 条消息
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0 ml-3">
                    <span className="text-[11px]" style={{ color: 'var(--text-tertiary)' }}>
                      {formatTime(s.updated_at)}
                    </span>
                    <span
                      className="text-[11px] px-1.5 py-0.5 rounded"
                      style={{
                        color: s.share_permission === 'edit' ? '#10B981' : '#6B7280',
                        background: s.share_permission === 'edit' ? '#10B98118' : '#6B728018',
                      }}
                    >
                      {s.share_permission === 'edit' ? '可编辑' : '只读'}
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
