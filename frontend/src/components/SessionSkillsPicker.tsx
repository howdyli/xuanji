import { useEffect, useRef, useState } from 'react'

const API_BASE = '/api/frontend'
const TOKEN = 'test-token-dev-2024'
const authHeaders = { Authorization: `Bearer ${TOKEN}` }

interface SkillItem {
  name: string
  source: 'builtin' | 'user'
  enabled: boolean
}

interface Props {
  sessionId: string | null
  open: boolean
  anchorEl: HTMLElement | null
  onClose: () => void
}

/**
 * 会话技能选择浮层。
 * - selected = null  表示"全部启用"（与 DB 中无 session_skills 行一致）
 * - selected = []    表示"显式禁用所有"
 * - selected = [...] 表示子集
 */
export function SessionSkillsPicker({ sessionId, open, anchorEl, onClose }: Props) {
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [selected, setSelected] = useState<Set<string> | null>(null) // null = all
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [search, setSearch] = useState('')
  const popoverRef = useRef<HTMLDivElement>(null)

  // Load skill list + current session selection
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      fetch(`${API_BASE}/skills`, { headers: authHeaders }).then((r) => r.json()),
      sessionId
        ? fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/skills`, {
            headers: authHeaders,
          }).then((r) => r.json())
        : Promise.resolve({ skills: null }),
    ])
      .then(([listResp, sessResp]) => {
        if (cancelled) return
        const list: SkillItem[] = (listResp.skills || []).filter((s: SkillItem) => s.enabled)
        setSkills(list)
        if (sessResp.skills === null || sessResp.skills === undefined) {
          setSelected(null)
        } else {
          setSelected(new Set<string>(sessResp.skills))
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, sessionId])

  // Click outside to close
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        anchorEl &&
        !anchorEl.contains(e.target as Node)
      ) {
        onClose()
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open, anchorEl, onClose])

  if (!open) return null

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev ?? skills.map((s) => s.name))
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const enableAll = () => setSelected(null)
  const disableAll = () => setSelected(new Set())

  const handleSave = async () => {
    if (!sessionId) {
      onClose()
      return
    }
    setSaving(true)
    try {
      const body =
        selected === null
          ? { skills: null }
          : { skills: Array.from(selected) }
      await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/skills`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify(body),
      })
      onClose()
    } catch {
      // ignore for now
    } finally {
      setSaving(false)
    }
  }

  // Group skills by category
  const groupedSkills = (() => {
    const filtered = skills.filter((s) =>
      s.name.toLowerCase().includes(search.toLowerCase())
    )
    const groups: Record<string, SkillItem[]> = { '搜索类': [], '文档类': [], '系统类': [] }
    const SEARCH_PREFIXES = ['baidu', 'search', 'web']
    const DOC_PREFIXES = ['docx', 'pdf', 'xlsx', 'pptx']
    for (const s of filtered) {
      const lower = s.name.toLowerCase()
      if (SEARCH_PREFIXES.some((p) => lower.includes(p))) groups['搜索类'].push(s)
      else if (DOC_PREFIXES.some((p) => lower.includes(p))) groups['文档类'].push(s)
      else groups['系统类'].push(s)
    }
    return Object.entries(groups).filter(([, items]) => items.length > 0)
  })()

  return (
    <div
      ref={popoverRef}
      className="absolute bottom-full mb-2 left-0 w-[320px] bg-white border border-gray-200 rounded-xl shadow-xl z-40"
    >
      <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between">
        <span className="text-[12px] font-semibold text-gray-800">会话可用技能</span>
        <div className="flex items-center gap-1">
          <button onClick={enableAll} className={`text-[10.5px] px-1.5 py-0.5 rounded ${selected === null ? 'bg-blue-50 text-blue-700' : 'text-gray-500 hover:bg-gray-100'}`}>全部</button>
          <button onClick={disableAll} className="text-[10.5px] px-1.5 py-0.5 rounded text-gray-500 hover:bg-gray-100">清空</button>
        </div>
      </div>
      {/* Search */}
      <div className="px-3 py-2 border-b border-gray-100">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索技能..."
          className="w-full px-2.5 py-1.5 text-[12px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 bg-gray-50/50"
        />
      </div>
      {!sessionId && (
        <div className="px-3 py-2 text-[11px] text-amber-700 bg-amber-50 border-b border-amber-100">
          首条消息发送后，该选择将自动生效。
        </div>
      )}
      <div className="max-h-[280px] overflow-y-auto">
        {loading ? (
          <div className="px-3 py-4 text-[12px] text-gray-400 text-center">加载中...</div>
        ) : skills.length === 0 ? (
          <div className="px-3 py-4 text-[12px] text-gray-400 text-center">无可用技能</div>
        ) : (
          groupedSkills.map(([group, items]) => (
            <div key={group}>
              <div className="px-3 py-1.5 text-[10px] font-medium text-gray-400 uppercase tracking-wider bg-gray-50/50">{group}</div>
              {items.map((s) => {
                const checked = selected === null || selected.has(s.name)
                return (
                  <button
                    key={s.name}
                    onClick={() => toggle(s.name)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 transition-colors text-left"
                  >
                    <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${checked ? 'bg-blue-500 border-blue-500' : 'border-gray-300'}`}>
                      {checked && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>}
                    </span>
                    <span className="text-[12px] text-gray-700 flex-1">{s.name}</span>
                    {s.source === 'user' && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">U</span>
                    )}
                  </button>
                )
              })}
            </div>
          ))
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-100 flex items-center justify-between">
        <span className="text-[10.5px] text-gray-400">
          {selected === null ? '当前：全部启用' : `当前：已选 ${selected.size}/${skills.length}`}
        </span>
        <button onClick={handleSave} disabled={saving} className="px-3 py-1 rounded-lg bg-gray-900 text-white text-[11.5px] hover:bg-gray-800 disabled:bg-gray-400">
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  )
}
