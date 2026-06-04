/**
 * ExpertManagerView —— 专家团队展示页（workbuddy 风格）
 *
 * 布局：分类标签导航 + 2列大卡片网格
 * 卡片：图标 + 标题 + 标签 + 描述 + 团队/成员 + 使用次数 + 召唤按钮
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

const API_BASE = '/api/frontend'

// ─── Types ──────────────────────────────────────────────────────────────
export interface Expert {
  id: number
  name: string
  display_name: string
  description: string
  icon: string
  system_prompt: string
  skills: string[]
  category: string
  tags: string[]
  team: string
  usage_count: number
  avatar_url: string
  created_at: string
  updated_at: string
}

interface Category {
  name: string
  count: number
}

// ─── Inline icons ───────────────────────────────────────────────────────
const SearchSvg = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)
const PlusSvg = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
  </svg>
)
const CloseSvg = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)
const CheckSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
)
const EditSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)
const TrashSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
)
const ChevronDownSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="6 9 12 15 18 9" />
  </svg>
)

// ─── Icon emoji map ─────────────────────────────────────────────────────
const ICON_EMOJIS: Record<string, string> = {
  dev: '👨‍💻',
  trading: '📊',
  content: '🎨',
  ip: '🏮',
  research: '🔍',
  cloud: '☁️',
  opc: '💼',
  stock: '📈',
  general: '🤖',
  coder: '💻',
  doc: '📄',
  researcher: '🔍',
  expert: '🧠',
}

// ─── Gradients ──────────────────────────────────────────────────────────
const GRADIENTS = [
  'from-blue-400 to-indigo-500',
  'from-sky-400 to-blue-500',
  'from-purple-400 to-fuchsia-500',
  'from-orange-400 to-rose-500',
  'from-amber-400 to-yellow-500',
  'from-pink-400 to-rose-500',
  'from-sky-400 to-cyan-500',
  'from-violet-400 to-purple-500',
]
function gradientOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}

// ─── Member avatar dots (simulated) ─────────────────────────────────────
const MEMBER_GRADIENTS = [
  'from-blue-300 to-blue-500',
  'from-blue-300 to-blue-500',
  'from-purple-300 to-purple-500',
  'from-orange-300 to-orange-500',
]
function MemberDots({ name }: { name: string }) {
  const count = Math.min(4, (name.length % 3) + 2)
  return (
    <div className="flex items-center -space-x-1.5">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`w-5 h-5 rounded-full bg-gradient-to-br ${MEMBER_GRADIENTS[i % MEMBER_GRADIENTS.length]} border-2 border-white`}
        />
      ))}
      {count >= 4 && (
        <div className="w-5 h-5 rounded-full bg-gray-100 border-2 border-white flex items-center justify-center">
          <span className="text-[8px] text-gray-500">...</span>
        </div>
      )}
    </div>
  )
}

// ─── Format usage count ─────────────────────────────────────────────────
function formatUsage(count: number): string {
  if (!count) return ''
  if (count >= 1) return `${count.toFixed(2)}万次使用`
  return `${(count * 10000).toFixed(0)}次使用`
}

// ─── Props ──────────────────────────────────────────────────────────────
interface ExpertManagerViewProps {
  authToken: string
  activeExpert: string | null
  onSelectExpert: (name: string | null) => void
}

// ─── Expert Card ────────────────────────────────────────────────────────
function ExpertCard({
  expert,
  isActive,
  isFeatured,
  onSelect,
  onClick,
}: {
  expert: Expert
  isActive: boolean
  isFeatured: boolean
  onSelect: () => void
  onClick: () => void
}) {
  return (
    <div
      className="group relative bg-white border rounded-2xl p-5 hover:shadow-md transition-all cursor-pointer flex flex-col gap-3 min-h-[220px]"
      style={{ borderColor: isActive ? '#3b82f6' : '#e5e7eb' }}
      onClick={onClick}
    >
      {/* Active indicator */}
      {isActive && (
        <div className="absolute top-4 right-4 w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center text-white shadow-sm">
          <CheckSvg />
        </div>
      )}

      {/* Icon + Title */}
      <div className="flex items-start gap-3">
        <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${gradientOf(expert.name)} flex items-center justify-center shrink-0 shadow-sm`}>
          <span className="text-xl">{ICON_EMOJIS[expert.icon] || '🧠'}</span>
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <h3 className="text-[15px] font-semibold text-gray-900 truncate leading-tight">
            {expert.display_name}
          </h3>
          <div className="text-[11px] text-gray-400 font-mono mt-0.5">{expert.name}</div>
        </div>
      </div>

      {/* Tags */}
      <div className="flex flex-wrap gap-1.5">
        {(expert.tags || []).slice(0, 3).map((tag: string) => (
          <span
            key={tag}
            className="px-2 py-0.5 rounded-full text-[11px] bg-gray-100 text-gray-600 border border-gray-200"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Description */}
      <p className="text-[12.5px] text-gray-500 leading-relaxed line-clamp-2 flex-1">
        {expert.description || '暂无描述'}
      </p>

      {/* Footer: Team + Members + Usage */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-100">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] text-gray-400 truncate">{expert.team || '玄机团队'}</span>
          <MemberDots name={expert.name} />
        </div>
        <span className="text-[11px] text-gray-500 shrink-0">
          {formatUsage(expert.usage_count)}
        </span>
      </div>

      {/* Featured "召唤" button (shown on first card when no expert selected) */}
      {isFeatured && !isActive && (
        <button
          onClick={(e) => { e.stopPropagation(); onSelect() }}
          className="absolute bottom-5 right-5 px-4 py-1.5 rounded-full bg-gray-900 text-white text-[12px] font-medium hover:bg-gray-800 shadow-sm transition-all"
        >
          召唤
        </button>
      )}
    </div>
  )
}

// ─── Category Tabs ──────────────────────────────────────────────────────
function CategoryTabs({
  categories,
  activeCategory,
  onCategoryChange,
}: {
  categories: Category[]
  activeCategory: string
  onCategoryChange: (cat: string) => void
}) {
  const allCat = { name: '全部', count: categories.reduce((s, c) => s + c.count, 0) }
  const tabs = [allCat, ...categories]

  return (
    <div className="flex items-center gap-2 overflow-x-auto scrollbar-hide py-2 px-1">
      {tabs.map((cat) => (
        <button
          key={cat.name}
          onClick={() => onCategoryChange(cat.name === '全部' ? '' : cat.name)}
          className={`shrink-0 px-4 py-1.5 rounded-full text-[13px] font-medium transition-all ${
            (cat.name === '全部' && !activeCategory) || cat.name === activeCategory
              ? 'bg-gray-900 text-white shadow-sm'
              : 'text-gray-600 hover:bg-gray-100'
          }`}
        >
          {cat.name}
          <span className="ml-1 text-[11px] opacity-60">({cat.count})</span>
        </button>
      ))}
    </div>
  )
}

// ─── Detail Drawer ──────────────────────────────────────────────────────
function DetailDrawer({
  expert,
  onClose,
  onEdit,
  onDelete,
  onSelect,
  isActive,
}: {
  expert: Expert | null
  onClose: () => void
  onEdit: () => void
  onDelete: () => void
  onSelect: () => void
  isActive: boolean
}) {
  if (!expert) return null
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="w-full max-w-[480px] h-full bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200/70">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${gradientOf(expert.name)} flex items-center justify-center shrink-0`}>
              <span className="text-xl">{ICON_EMOJIS[expert.icon] || '🧠'}</span>
            </div>
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold text-gray-900 truncate">{expert.display_name}</h3>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[11px] text-gray-400">{expert.team}</span>
                <span className="text-[11px] text-gray-300">|</span>
                <span className="text-[11px] text-blue-600">{expert.category}</span>
              </div>
            </div>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <CloseSvg />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Tags */}
          <section>
            <div className="flex flex-wrap gap-1.5">
              {(expert.tags || []).map((tag: string) => (
                <span key={tag} className="px-2.5 py-1 rounded-full text-[11px] bg-gray-100 text-gray-700 border border-gray-200">{tag}</span>
              ))}
            </div>
          </section>

          <section>
            <div className="text-[11px] font-medium text-gray-400 mb-1.5">描述</div>
            <p className="text-[13px] text-gray-700 leading-relaxed">{expert.description || '暂无描述'}</p>
          </section>

          <section>
            <div className="text-[11px] font-medium text-gray-400 mb-1.5">关联技能</div>
            {expert.skills.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {expert.skills.map((s: string) => (
                  <span key={s} className="px-2 py-0.5 rounded text-[11px] bg-blue-50 text-blue-700 border border-blue-200">{s}</span>
                ))}
              </div>
            ) : (
              <span className="text-[12px] text-gray-400">无关联技能</span>
            )}
          </section>

          {expert.system_prompt && (
            <section>
              <div className="text-[11px] font-medium text-gray-400 mb-1.5">系统提示词</div>
              <pre className="text-[11.5px] text-gray-700 bg-gray-50 border border-gray-200 rounded-lg p-3 max-h-[280px] overflow-auto whitespace-pre-wrap font-mono leading-relaxed">
                {expert.system_prompt}
              </pre>
            </section>
          )}

          <section>
            <div className="text-[11px] font-medium text-gray-400 mb-1">使用统计</div>
            <span className="text-[13px] text-gray-700">{formatUsage(expert.usage_count)}</span>
          </section>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200/70 flex items-center justify-between bg-gray-50/50">
          <button
            onClick={onDelete}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] rounded-lg text-rose-600 border border-rose-200 hover:bg-rose-50"
          >
            <TrashSvg /> 删除
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={onEdit}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50"
            >
              <EditSvg /> 编辑
            </button>
            <button
              onClick={onSelect}
              className={`px-4 py-1.5 text-[12px] rounded-lg font-medium ${
                isActive
                  ? 'bg-blue-50 border border-blue-200 text-blue-700'
                  : 'bg-gray-900 text-white hover:bg-gray-800'
              }`}
            >
              {isActive ? '当前使用中' : '召唤此专家'}
            </button>
          </div>
        </div>
      </aside>
    </div>
  )
}

// ─── Create/Edit Dialog ─────────────────────────────────────────────────
const ICON_OPTIONS = ['expert', 'dev', 'trading', 'content', 'research', 'cloud', 'opc', 'stock']
const CATEGORY_OPTIONS = ['技术工程', '金融投资', '内容创作', '数据智能', '行业顾问', 'OPC一人公司', '营销增长', '运营人力']

function ExpertFormDialog({
  onClose,
  onSaved,
  initial,
  authToken,
}: {
  onClose: () => void
  onSaved: () => void
  initial?: Expert | null
  authToken: string
}) {
  const isEdit = !!initial
  const [name, setName] = useState(initial?.name || '')
  const [displayName, setDisplayName] = useState(initial?.display_name || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [icon, setIcon] = useState(initial?.icon || 'expert')
  const [category, setCategory] = useState(initial?.category || '技术工程')
  const [tagsText, setTagsText] = useState((initial?.tags || []).join(', '))
  const [team, setTeam] = useState(initial?.team || '')
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt || '')
  const [skillsText, setSkillsText] = useState((initial?.skills || []).join(', '))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true)
    setErr('')
    const skills = skillsText.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
    const tags = tagsText.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
    const payload = { name, display_name: displayName, description, icon, system_prompt: systemPrompt, skills, category, tags, team }
    try {
      const url = isEdit ? `${API_BASE}/experts/${encodeURIComponent(name)}` : `${API_BASE}/experts`
      const method = isEdit ? 'PUT' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setErr(data?.error || `保存失败 (${res.status})`); return }
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div onClick={(e) => e.stopPropagation()} className="relative w-full max-w-[560px] bg-white rounded-2xl shadow-2xl border border-gray-200/60 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h3 className="text-[14px] font-medium text-gray-900">{isEdit ? '编辑专家' : '新建专家'}</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100">
            <CloseSvg />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3 max-h-[65vh] overflow-y-auto">
          <Field label="标识（英文，2-40 字符）">
            <input value={name} onChange={(e) => setName(e.target.value)} disabled={isEdit} placeholder="my-expert"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 disabled:bg-gray-50 disabled:text-gray-400" />
          </Field>
          <Field label="显示名称">
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="我的专家团队"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="描述">
            <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话描述..."
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="图标">
            <div className="flex flex-wrap gap-2">
              {ICON_OPTIONS.map((ic) => (
                <button key={ic} type="button" onClick={() => setIcon(ic)}
                  className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg border ${icon === ic ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                  {ICON_EMOJIS[ic] || '🧠'}
                </button>
              ))}
            </div>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="分类">
              <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 bg-white">
                {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="来源团队">
              <input value={team} onChange={(e) => setTeam(e.target.value)} placeholder="玄机团队"
                className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
            </Field>
          </div>
          <Field label="标签（逗号分隔）">
            <input value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="软件公司, 组织管理, 产品交付"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="关联技能（逗号分隔）">
            <input value={skillsText} onChange={(e) => setSkillsText(e.target.value)} placeholder="baidu_search, web_browse"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="系统提示词">
            <textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} rows={4}
              className="w-full px-3 py-2 text-[12.5px] font-mono border border-gray-200 rounded-lg outline-none focus:border-blue-400 resize-y leading-relaxed"
              placeholder="你是一位专业的 AI 助手..." />
          </Field>
          {err && <div className="text-[12px] text-rose-500">{err}</div>}
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button onClick={onClose} className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50">取消</button>
          <button onClick={submit} disabled={busy || !name.trim() || !displayName.trim()}
            className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50">
            {busy ? '保存中…' : isEdit ? '保存' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] font-medium text-gray-500 mb-1">{label}</div>
      {children}
    </label>
  )
}

// ─── Skeleton ───────────────────────────────────────────────────────────
function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-2xl p-5 animate-pulse min-h-[220px]">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gray-100" />
            <div className="w-28 h-5 rounded bg-gray-100" />
          </div>
          <div className="flex gap-2 mt-3">
            <div className="w-16 h-5 rounded-full bg-gray-100" />
            <div className="w-20 h-5 rounded-full bg-gray-100" />
          </div>
          <div className="h-4 bg-gray-100 rounded mt-3 w-full" />
          <div className="h-4 bg-gray-100 rounded mt-1.5 w-3/4" />
        </div>
      ))}
    </div>
  )
}

// ─── Main View ──────────────────────────────────────────────────────────
export function ExpertManagerView({ authToken, activeExpert, onSelectExpert }: ExpertManagerViewProps) {
  const [experts, setExperts] = useState<Expert[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [activeCategory, setActiveCategory] = useState('')
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<Expert | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editingExpert, setEditingExpert] = useState<Expert | null>(null)
  const [toast, setToast] = useState('')
  const [err, setErr] = useState('')

  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${authToken}` }), [authToken])

  const fireToast = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(''), 2400)
  }, [])

  const loadExperts = useCallback(async () => {
    try {
      const url = activeCategory
        ? `${API_BASE}/experts?category=${encodeURIComponent(activeCategory)}`
        : `${API_BASE}/experts`
      const res = await fetch(url, { headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data?.experts) setExperts(data.experts)
      else if (!res.ok) setErr(data?.error || `加载失败 (${res.status})`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [authHeaders, activeCategory])

  const loadCategories = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/experts/categories`, { headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data?.categories) setCategories(data.categories)
    } catch { /* ignore */ }
  }, [authHeaders])

  useEffect(() => { loadExperts(); loadCategories() }, [loadExperts, loadCategories])

  const filtered = useMemo(() => {
    if (!search) return experts
    const q = search.toLowerCase()
    return experts.filter(
      (e) =>
        e.display_name.toLowerCase().includes(q) ||
        e.name.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q) ||
        (e.tags || []).some((t: string) => t.toLowerCase().includes(q)),
    )
  }, [experts, search])

  const handleDelete = useCallback(async (name: string) => {
    if (!confirm(`确定删除专家「${name}」？`)) return
    try {
      const res = await fetch(`${API_BASE}/experts/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (res.ok) {
        fireToast('已删除')
        setDetail(null)
        if (activeExpert === name) onSelectExpert(null)
        await loadExperts()
        await loadCategories()
      } else {
        fireToast('删除失败')
      }
    } catch { fireToast('删除失败') }
  }, [authHeaders, fireToast, loadExperts, loadCategories, activeExpert, onSelectExpert])

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50/40">
      {/* Header */}
      <header className="shrink-0 px-6 lg:px-8 pt-6 pb-3 bg-white border-b border-gray-200/70">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[22px] font-medium text-gray-900 leading-tight">专家</h1>
            <p className="text-[13px] text-gray-500 mt-1">
              选择专业团队，获得更精准的 AI 协作能力
              {activeExpert && (
                <span className="ml-2 text-blue-600">
                  · 当前：{experts.find((e) => e.name === activeExpert)?.display_name || activeExpert}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 w-[200px]">
              <span className="text-gray-400"><SearchSvg /></span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索专家"
                className="flex-1 text-[12.5px] bg-transparent outline-none text-gray-700 placeholder-gray-400"
              />
            </div>
            <button onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800">
              <PlusSvg size={14} /><span>新建专家</span>
            </button>
          </div>
        </div>

        {/* Category tabs */}
        <CategoryTabs
          categories={categories}
          activeCategory={activeCategory}
          onCategoryChange={setActiveCategory}
        />
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-6">
        {err && (
          <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">{err}</div>
        )}
        {loading ? (
          <GridSkeleton />
        ) : filtered.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-[14px] text-gray-700 font-medium">{search ? '没有匹配的专家' : '暂无专家'}</div>
            <div className="text-[12.5px] text-gray-500 mt-1.5">
              {search ? '试试其他关键字' : '点击「新建专家」创建你的第一个专家团队'}
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filtered.map((e, idx) => (
                <ExpertCard
                  key={e.name}
                  expert={e}
                  isActive={activeExpert === e.name}
                  isFeatured={activeExpert !== e.name}
                  onSelect={() => onSelectExpert(activeExpert === e.name ? null : e.name)}
                  onClick={() => setDetail(e)}
                />
              ))}
            </div>
            {filtered.length > 4 && (
              <div className="text-center mt-6">
                <button className="text-[13px] text-blue-600 hover:text-blue-800 inline-flex items-center gap-1">
                  显示更多 <ChevronDownSvg />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Detail drawer */}
      <DetailDrawer
        expert={detail}
        onClose={() => setDetail(null)}
        onEdit={() => { setEditingExpert(detail); setDetail(null) }}
        onDelete={() => detail && handleDelete(detail.name)}
        onSelect={() => {
          if (detail) {
            onSelectExpert(activeExpert === detail.name ? null : detail.name)
            setDetail(null)
          }
        }}
        isActive={detail ? activeExpert === detail.name : false}
      />

      {/* Create dialog */}
      {showCreate && (
        <ExpertFormDialog
          onClose={() => setShowCreate(false)}
          onSaved={async () => { setShowCreate(false); fireToast('创建成功'); await loadExperts(); await loadCategories() }}
          authToken={authToken}
        />
      )}

      {/* Edit dialog */}
      {editingExpert && (
        <ExpertFormDialog
          initial={editingExpert}
          onClose={() => setEditingExpert(null)}
          onSaved={async () => { setEditingExpert(null); fireToast('保存成功'); await loadExperts(); await loadCategories() }}
          authToken={authToken}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[80] px-4 py-2 rounded-lg bg-gray-900 text-white text-[12.5px] shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}

export default ExpertManagerView
