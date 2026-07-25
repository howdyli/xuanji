import { useEffect, useRef, useState } from 'react'
import { listBases, getSessionBases, setSessionBases } from '../api/knowledge'
import type { KnowledgeBase } from '../api/knowledge'

const MAX_BINDINGS = 5 // 与后端 _MAX_SESSION_KB_BINDINGS 一致

interface Props {
  sessionId: string
  open: boolean
  anchorEl: HTMLElement | null
  onClose: () => void
  /** 保存成功后回调（用于父级刷新徽标数量） */
  onSaved: (kbIds: string[]) => void
}

/**
 * 会话知识库绑定浮层（仿 SessionSkillsPicker）。
 * - 仅列出个人库（组织库暂不支持聊天内绑定，见设计文档 §9）
 * - 多选（上限 5 个），保存时全量替换绑定；空选 = 解绑全部
 */
export function SessionKnowledgePicker({ sessionId, open, anchorEl, onClose, onSaved }: Props) {
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const popoverRef = useRef<HTMLDivElement>(null)

  // Load personal bases + current session bindings
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([listBases(), getSessionBases(sessionId)])
      .then(([allBases, bound]) => {
        if (cancelled) return
        setBases(allBases.filter((b) => b.scope === 'personal'))
        setSelected(new Set(bound.kb_ids))
      })
      .catch(() => {
        if (!cancelled) setError('加载知识库列表失败')
      })
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

  const toggle = (kbId: string) => {
    setError('')
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(kbId)) {
        next.delete(kbId)
      } else if (next.size >= MAX_BINDINGS) {
        setError(`最多绑定 ${MAX_BINDINGS} 个知识库`)
        return prev
      } else {
        next.add(kbId)
      }
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const kbIds = Array.from(selected)
      await setSessionBases(sessionId, kbIds)
      onSaved(kbIds)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      ref={popoverRef}
      className="absolute bottom-full mb-2 left-0 w-[320px] bg-white border border-gray-200 rounded-xl shadow-xl z-40"
    >
      <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between">
        <span className="text-[12px] font-semibold text-gray-800">会话引用的知识库</span>
        <span className="text-[10.5px] text-gray-400">绑定后检索限定在所选库内</span>
      </div>
      {error && (
        <div className="px-3 py-2 text-[11px] text-red-700 bg-red-50 border-b border-red-100">{error}</div>
      )}
      <div className="max-h-[280px] overflow-y-auto">
        {loading ? (
          <div className="px-3 py-4 text-[12px] text-gray-400 text-center">加载中...</div>
        ) : bases.length === 0 ? (
          <div className="px-3 py-4 text-[12px] text-gray-400 text-center">
            暂无个人知识库，可在「知识库」页面创建
          </div>
        ) : (
          bases.map((b) => {
            const checked = selected.has(b.id)
            return (
              <button
                key={b.id}
                onClick={() => toggle(b.id)}
                className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 transition-colors text-left"
              >
                <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${checked ? 'bg-blue-500 border-blue-500' : 'border-gray-300'}`}>
                  {checked && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>}
                </span>
                <span className="text-[12px] text-gray-700 flex-1 truncate">{b.name}</span>
                <span className="text-[10px] text-gray-400 shrink-0">{b.document_count ?? 0} 文档</span>
              </button>
            )
          })
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-100 flex items-center justify-between">
        <span className="text-[10.5px] text-gray-400">
          {selected.size === 0 ? '未绑定：检索全部个人库' : `已选 ${selected.size}/${MAX_BINDINGS}`}
        </span>
        <button onClick={handleSave} disabled={saving} className="px-3 py-1 rounded-lg bg-gray-900 text-white text-[11.5px] hover:bg-gray-800 disabled:bg-gray-400">
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  )
}
