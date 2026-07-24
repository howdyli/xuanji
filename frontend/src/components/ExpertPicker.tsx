/**
 * ExpertPicker —— 对话框内的专家选择内容与两种外壳。
 *
 * - useExperts()：加载 /experts 数据（供按钮浮层与 @ 内联浮层共用）。
 * - ExpertPickerList：搜索框 + 按分类分组的专家列表（核心可复用内容）。
 * - ExpertPickerPopover：底部「专家」按钮的浮层外壳（含 Esc / 点击外部关闭）。
 *
 * 复用「专家」页的 /experts 数据；鉴权由 apiFetch 自动附带。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../api/client'
import type { Expert } from './ExpertManagerView'

const API_BASE = '/api/frontend'

// 专家类型 → 头像 emoji（与 ExpertManagerView 保持一致）
const ICON_EMOJIS: Record<string, string> = {
  dev: '👨‍💻', trading: '📊', content: '🎨', ip: '🏮', research: '🔍',
  cloud: '☁️', opc: '💼', stock: '📈', general: '🤖', coder: '💻',
  doc: '📄', researcher: '🔍', expert: '🧠',
}
// 天蓝系渐变（对话框内头像）
const GRADIENTS = [
  'from-sky-400 to-blue-500',
  'from-blue-400 to-indigo-500',
  'from-cyan-400 to-sky-500',
  'from-indigo-400 to-blue-500',
  'from-teal-400 to-cyan-500',
]
function gradientOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}
function iconEmoji(icon: string): string {
  return ICON_EMOJIS[icon] || ICON_EMOJIS.expert
}

/** 加载专家列表（一次性，供浮层共用）。失败回退空数组。 */
export function useExperts() {
  const [experts, setExperts] = useState<Expert[]>([])
  const [loading, setLoading] = useState(true)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch<{ experts?: Expert[] }>(`${API_BASE}/experts`)
      setExperts(data.experts || [])
    } catch {
      setExperts([])
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])
  return { experts, loading }
}

interface ExpertPickerListProps {
  experts: Expert[]
  loading: boolean
  query: string
  onQueryChange?: (q: string) => void
  activeName: string | null
  onSelect: (name: string) => void
  /** 是否显示内置搜索框（@ 内联浮层用外部输入的关键词过滤，故关闭）。 */
  showSearch?: boolean
}

/** 搜索 + 按分类分组的专家列表（按钮浮层与 @ 浮层共用）。 */
export function ExpertPickerList({
  experts, loading, query, onQueryChange, activeName, onSelect, showSearch = true,
}: ExpertPickerListProps) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return experts
    return experts.filter((e) =>
      e.display_name.toLowerCase().includes(q) ||
      e.name.toLowerCase().includes(q) ||
      (e.category || '').toLowerCase().includes(q) ||
      (e.team || '').toLowerCase().includes(q),
    )
  }, [experts, query])

  const groups = useMemo(() => {
    const m = new Map<string, Expert[]>()
    for (const e of filtered) {
      const cat = e.category || '其他'
      if (!m.has(cat)) m.set(cat, [])
      m.get(cat)!.push(e)
    }
    return [...m.entries()]
  }, [filtered])

  return (
    <div className="flex flex-col max-h-[340px]">
      {showSearch && (
        <div className="p-2 border-b border-[rgba(0,0,0,0.06)]">
          <input
            autoFocus
            value={query}
            onChange={(e) => onQueryChange?.(e.target.value)}
            placeholder="搜索专家…"
            className="w-full px-2.5 py-1.5 text-[13px] rounded-lg bg-[#E9F3FB] text-[#4A6B82] outline-none placeholder:text-[#9db4c6] focus:ring-2 focus:ring-[#3898EC]/30"
          />
        </div>
      )}
      <div className="overflow-y-auto py-1">
        {loading ? (
          <div className="px-3 py-6 text-center text-[12px] text-[#9b9892]">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-[12px] text-[#9b9892]">未找到匹配的专家</div>
        ) : (
          groups.map(([cat, items]) => (
            <div key={cat} className="mb-1">
              <div className="px-3 py-1 text-[11px] font-medium text-[#9db4c6]">{cat}</div>
              {items.map((e) => (
                <button
                  key={e.name}
                  type="button"
                  onClick={() => onSelect(e.name)}
                  className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-left transition-colors ${
                    activeName === e.name ? 'bg-[#E9F3FB]' : 'hover:bg-[#f0efe9]'
                  }`}
                >
                  <span className={`w-7 h-7 rounded-full bg-gradient-to-br ${gradientOf(e.name)} flex items-center justify-center shrink-0 text-[13px] ring-2 ring-white shadow-sm`}>
                    {iconEmoji(e.icon)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-[#1a1917] truncate">{e.display_name}</span>
                    <span className="block text-[11px] text-[#9b9892] truncate">{e.team || e.category}</span>
                  </span>
                  {activeName === e.name && <span className="text-[#3898EC] shrink-0 text-[13px]">✓</span>}
                </button>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

interface ExpertPickerPopoverProps {
  open: boolean
  onClose: () => void
  activeName: string | null
  onSelect: (name: string) => void
  experts: Expert[]
  loading: boolean
  /** 锚定按钮，点击它不触发"点外关闭"（避免与按钮 toggle 冲突）。 */
  anchorEl?: HTMLElement | null
}

/** 底部「专家」按钮上方的浮层外壳。 */
export function ExpertPickerPopover({
  open, onClose, activeName, onSelect, experts, loading, anchorEl,
}: ExpertPickerPopoverProps) {
  const [query, setQuery] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        ref.current && !ref.current.contains(target) &&
        (!anchorEl || !anchorEl.contains(target))
      ) onClose()
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, anchorEl])

  useEffect(() => { if (!open) setQuery('') }, [open])

  if (!open) return null
  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 mb-2 w-[280px] bg-white border border-[rgba(0,0,0,0.08)] rounded-[12px] shadow-lg overflow-hidden z-20 animate-fade-in"
    >
      <ExpertPickerList
        experts={experts}
        loading={loading}
        query={query}
        onQueryChange={setQuery}
        activeName={activeName}
        onSelect={onSelect}
      />
    </div>
  )
}
