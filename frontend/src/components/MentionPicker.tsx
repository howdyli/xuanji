/**
 * MentionPicker —— 会话输入框 @ 唤起的统一引用浮层（专家 / 技能两栏）。
 *
 * - 专家栏：复用 ExpertPickerList，选中即激活会话专家（现行为）。
 * - 技能栏：仅列会话启用的技能，选中后由调用方在输入框插入 `@技能名 ` token，
 *   发送时解析为 skill_hints（本条消息优先使用该技能）。
 * - query 由外部传入（@ 后输入的关键词），同时过滤两栏。
 *
 * 数据源与 SessionSkillsPicker 一致：GET /skills + GET /sessions/{sid}/skills
 * （无绑定行 = 全部启用）；鉴权由 apiFetch 自动附带。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../api/client'
import { ExpertPickerList } from './ExpertPicker'
import type { Expert } from './ExpertManagerView'

const API_BASE = '/api/frontend'

export interface SkillItem {
  name: string
  source: 'builtin' | 'user'
  enabled: boolean
}

/** 加载会话启用的技能列表（全部技能 ∩ 会话绑定集；绑定为 null 时取全部）。
 *  在输入栏层调用（镜像 useExperts 模式），发送时手动输入的 @技能也能识别。 */
export function useSessionSkills(sessionId: string | null, active: boolean) {
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!active) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      apiFetch<{ skills?: SkillItem[] }>(`${API_BASE}/skills`),
      sessionId
        ? apiFetch<{ skills?: string[] | null }>(
            `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/skills`,
          )
        : Promise.resolve({ skills: null } as { skills: string[] | null }),
    ])
      .then(([listResp, sessResp]) => {
        if (cancelled) return
        const all = (listResp.skills || []).filter((s) => s.enabled)
        const bound = sessResp.skills
        setSkills(
          bound === null || bound === undefined
            ? all
            : all.filter((s) => bound.includes(s.name)),
        )
      })
      .catch(() => {
        if (!cancelled) setSkills([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [active, sessionId])
  return { skills, loading }
}

interface MentionPickerProps {
  open: boolean
  anchorEl: HTMLElement | null
  query: string
  experts: Expert[]
  expertsLoading: boolean
  skills: SkillItem[]
  skillsLoading: boolean
  activeExpert: string | null
  onSelectExpert: (name: string) => void
  onSelectSkill: (name: string) => void
  onClose: () => void
}

export function MentionPicker({
  open, anchorEl, query, experts, expertsLoading, skills, skillsLoading,
  activeExpert, onSelectExpert, onSelectSkill, onClose,
}: MentionPickerProps) {
  const [tab, setTab] = useState<'expert' | 'skill'>('expert')
  const ref = useRef<HTMLDivElement>(null)

  // 点击外部 / Esc 关闭（点击锚定的输入框不算外部，避免边输入边关闭）
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

  useEffect(() => { if (!open) setTab('expert') }, [open])

  const filteredSkills = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return skills
    return skills.filter((s) => s.name.toLowerCase().includes(q))
  }, [skills, query])

  if (!open) return null
  return (
    <div ref={ref} className="flex flex-col max-h-[340px]">
      {/* 两栏 Tab */}
      <div className="flex items-center gap-0.5 p-1.5 border-b border-[rgba(0,0,0,0.06)]">
        {([['expert', '专家'], ['skill', '技能']] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-3 py-1 text-[12px] font-medium rounded-[6px] transition-colors ${
              tab === key ? 'bg-[#E9F3FB] text-[#185FA5]' : 'text-[#9b9892] hover:text-[#6b6963]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'expert' ? (
        <ExpertPickerList
          experts={experts}
          loading={expertsLoading}
          query={query}
          activeName={activeExpert}
          onSelect={onSelectExpert}
          showSearch={false}
        />
      ) : (
        <div className="overflow-y-auto py-1">
          {skillsLoading ? (
            <div className="px-3 py-6 text-center text-[12px] text-[#9b9892]">加载中…</div>
          ) : filteredSkills.length === 0 ? (
            <div className="px-3 py-6 text-center text-[12px] text-[#9b9892]">未找到可用技能</div>
          ) : (
            filteredSkills.map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() => onSelectSkill(s.name)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-left hover:bg-[#f0efe9] transition-colors"
              >
                <span className="w-7 h-7 rounded-full bg-[#E8F5E0] flex items-center justify-center shrink-0 text-[13px]">
                  ⚡
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] text-[#1a1917] truncate">{s.name}</span>
                  <span className="block text-[11px] text-[#9b9892]">
                    {s.source === 'user' ? '用户技能' : '内置技能'} · 本条消息优先使用
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
