/**
 * ShareDialog — 会话共享对话框
 *
 * 选择目标团队 + 权限（查看/可编辑），将当前会话共享给团队。
 */
import { useState, useEffect } from 'react'

interface Team {
  id: number
  name: string
  role?: string
}

interface ShareDialogProps {
  sessionId: string
  authToken: string
  onClose: () => void
  onShared?: () => void
}

export default function ShareDialog({ sessionId, authToken, onClose, onShared }: ShareDialogProps) {
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)
  const [permission, setPermission] = useState<'view' | 'edit'>('view')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/frontend/teams', {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then(r => r.json())
      .then(data => { setTeams(data.teams || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [authToken])

  const handleShare = async () => {
    if (!selectedTeamId) return
    setSubmitting(true)
    setError('')
    try {
      const res = await fetch(`/api/frontend/sessions/${sessionId}/share`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ team_id: selectedTeamId, permission }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || '共享失败')
      }
      onShared?.()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '共享失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }}>
      <div
        className="w-full max-w-sm rounded-2xl p-6 shadow-xl"
        style={{ background: 'var(--bg-primary, #fff)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[16px] font-bold" style={{ color: 'var(--text-primary)' }}>共享会话到团队</h3>
          <button onClick={onClose} className="text-[18px] leading-none" style={{ color: 'var(--text-tertiary)' }}>&times;</button>
        </div>

        {loading ? (
          <div className="py-6 text-center text-[13px]" style={{ color: 'var(--text-secondary)' }}>加载团队列表...</div>
        ) : teams.length === 0 ? (
          <div className="py-6 text-center text-[13px]" style={{ color: 'var(--text-secondary)' }}>
            你还没有加入任何团队，请先在「团队」页面创建或加入团队。
          </div>
        ) : (
          <>
            {/* Team selection */}
            <div className="mb-4">
              <label className="text-[12px] font-medium block mb-1.5" style={{ color: 'var(--text-secondary)' }}>选择团队</label>
              <div className="space-y-1.5">
                {teams.map(t => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTeamId(t.id)}
                    className="w-full text-left px-3 py-2 rounded-lg border text-[13px] transition-colors"
                    style={{
                      borderColor: selectedTeamId === t.id ? 'var(--accent-primary, #3B82F6)' : 'var(--border-light)',
                      background: selectedTeamId === t.id ? 'rgba(59,130,246,0.06)' : 'transparent',
                      color: 'var(--text-primary)',
                    }}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Permission selection */}
            <div className="mb-5">
              <label className="text-[12px] font-medium block mb-1.5" style={{ color: 'var(--text-secondary)' }}>共享权限</label>
              <div className="flex gap-2">
                <button
                  onClick={() => setPermission('view')}
                  className="flex-1 px-3 py-2 rounded-lg border text-[13px] text-center transition-colors"
                  style={{
                    borderColor: permission === 'view' ? 'var(--accent-primary, #3B82F6)' : 'var(--border-light)',
                    background: permission === 'view' ? 'rgba(59,130,246,0.06)' : 'transparent',
                    color: 'var(--text-primary)',
                  }}
                >
                  只读查看
                </button>
                <button
                  onClick={() => setPermission('edit')}
                  className="flex-1 px-3 py-2 rounded-lg border text-[13px] text-center transition-colors"
                  style={{
                    borderColor: permission === 'edit' ? 'var(--accent-primary, #3B82F6)' : 'var(--border-light)',
                    background: permission === 'edit' ? 'rgba(59,130,246,0.06)' : 'transparent',
                    color: 'var(--text-primary)',
                  }}
                >
                  可续写
                </button>
              </div>
            </div>

            {error && <div className="text-[12px] text-red-500 mb-3">{error}</div>}

            {/* Actions */}
            <div className="flex gap-2 justify-end">
              <button onClick={onClose} className="text-[13px] px-4 py-2 rounded-lg" style={{ color: 'var(--text-secondary)' }}>取消</button>
              <button
                onClick={handleShare}
                disabled={!selectedTeamId || submitting}
                className="text-[13px] px-4 py-2 rounded-lg text-white disabled:opacity-50"
                style={{ background: 'var(--accent-primary, #3B82F6)' }}
              >
                {submitting ? '共享中...' : '确认共享'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
