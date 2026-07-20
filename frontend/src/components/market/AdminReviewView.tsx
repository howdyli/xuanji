/**
 * AdminReviewView —— 管理员技能审核面板
 *
 * 拉取 GET /admin/pending，以卡片列表展示待审核技能，
 * 提供「通过」「拒绝（可填原因）」操作 → POST /admin/skills/{name}/moderate。
 * 操作后刷新列表并通过 onCountChange 回传最新待审数量（供 Tab 角标）。
 */
import { useCallback, useEffect, useState } from 'react'

const API_BASE = '/api/frontend/market/community'

interface PendingSkill {
  name: string
  publisher: string
  category: string
  version: string
  description: string
  screenshots?: string[]
  created_at?: string
}

export function AdminReviewView({
  authToken,
  onCountChange,
  fireToast,
}: {
  authToken: string
  onCountChange?: (n: number) => void
  fireToast?: (msg: string) => void
}) {
  const [skills, setSkills] = useState<PendingSkill[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string>('')

  const authHeaders = useCallback(
    (): Record<string, string> => ({ Authorization: `Bearer ${authToken}` }),
    [authToken],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/admin/pending`, { headers: authHeaders() })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        const list = (data.skills ?? []) as PendingSkill[]
        setSkills(list)
        onCountChange?.(typeof data.total === 'number' ? data.total : list.length)
      } else {
        setError(data.error || `加载失败 (${res.status})`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [authHeaders, onCountChange])

  useEffect(() => {
    load()
  }, [load])

  const moderate = useCallback(
    async (name: string, action: 'approve' | 'reject') => {
      setBusy(name)
      try {
        const res = await fetch(
          `${API_BASE}/admin/skills/${encodeURIComponent(name)}/moderate`,
          {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, note: notes[name] || '' }),
          },
        )
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          fireToast?.(`操作失败：${data.error || res.status}`)
          return
        }
        fireToast?.(action === 'approve' ? '已通过' : '已拒绝')
        await load()
      } catch (e) {
        fireToast?.(`操作失败：${e instanceof Error ? e.message : String(e)}`)
      } finally {
        setBusy('')
      }
    },
    [authHeaders, notes, load, fireToast],
  )

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse min-h-[120px]">
            <div className="h-4 bg-gray-100 rounded w-1/3" />
            <div className="h-3 bg-gray-100 rounded mt-3 w-full" />
            <div className="h-3 bg-gray-100 rounded mt-1.5 w-4/5" />
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">
        {error}
      </div>
    )
  }

  if (skills.length === 0) {
    return (
      <div className="text-center py-20">
        <div className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #374151)' }}>
          暂无待审核技能
        </div>
        <div className="text-[12.5px] mt-1.5" style={{ color: 'var(--text-secondary, #6b7280)' }}>
          所有提交都已处理完毕
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {skills.map((s) => (
        <div key={s.name} className="bg-white border border-gray-200 rounded-xl p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-medium text-gray-900">{s.name}</span>
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                  v{s.version}
                </span>
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600">
                  {s.category}
                </span>
              </div>
              <div className="text-[12px] text-gray-500 mt-1">发布者：{s.publisher}</div>
            </div>
          </div>

          <p className="text-[12.5px] text-gray-700 mt-2 whitespace-pre-wrap break-words">
            {s.description || '（无描述）'}
          </p>

          {s.screenshots && s.screenshots.length > 0 && (
            <div className="flex gap-2 mt-3 overflow-x-auto">
              {s.screenshots.map((url, i) => (
                <img
                  key={i}
                  src={url}
                  alt={`${s.name} screenshot ${i + 1}`}
                  className="h-24 rounded-lg border border-gray-200 object-cover"
                />
              ))}
            </div>
          )}

          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <input
              type="text"
              value={notes[s.name] || ''}
              onChange={(e) => setNotes((prev) => ({ ...prev, [s.name]: e.target.value }))}
              placeholder="拒绝原因（可选）"
              className="flex-1 min-w-[160px] px-2.5 py-1.5 text-[12.5px] rounded-lg border border-gray-200 focus:outline-none focus:ring-1 focus:ring-gray-300"
            />
            <button
              onClick={() => moderate(s.name, 'approve')}
              disabled={busy === s.name}
              className="px-3 py-1.5 text-[12.5px] rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              通过
            </button>
            <button
              onClick={() => moderate(s.name, 'reject')}
              disabled={busy === s.name}
              className="px-3 py-1.5 text-[12.5px] rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
            >
              拒绝
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

export default AdminReviewView
