/**
 * AutomationManagerView —— 「自动化」定时任务管理页面
 *
 * 布局：
 *   ┌─ 头部：标题 + 新建任务 + 从模板添加 ┐
 *   ├─ 任务卡片网格                        │
 *   │  模板选择器（Modal）                  │
 *   │  创建/编辑表单（Modal）               │
 *   └──────────────────────────────────────┘
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

const API_BASE = '/api/frontend'

// ─── Types ──────────────────────────────────────────────────────────────
interface AutomationTask {
  id: string
  name: string
  routing_key: string
  cron_expr: string
  content: string
  enabled: boolean
  description: string
  action_type: 'dispatch' | 'skill'
  skill_name: string
  last_run_at: string
  last_status: string
  fail_count: number
  max_retries: number
  created_at: string
  updated_at: string
}

interface TaskTemplate {
  name: string
  display_name: string
  description: string
  icon: string
  cron_expr: string
  cron_hint: string
  action_type: 'dispatch' | 'skill'
  skill_name: string
  content: string
}

// ─── SVG icons ──────────────────────────────────────────────────────────
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
const TrashSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
)
const EditSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)
const TemplateSvg = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
  </svg>
)
const ClockSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
  </svg>
)
const PlaySvg = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="5 3 19 12 5 21 5 3" />
  </svg>
)
const PauseSvg = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
  </svg>
)

// ─── Cron presets ───────────────────────────────────────────────────────
const CRON_PRESETS = [
  { label: '每小时', value: '0 * * * *' },
  { label: '每天 9:00', value: '0 9 * * *' },
  { label: '每天 18:00', value: '0 18 * * *' },
  { label: '工作日 9:00', value: '0 9 * * 1-5' },
  { label: '每周', value: '0 10 * * 1' },
  { label: '每4小时', value: '0 */4 * * *' },
]

// ─── Cron to human-readable Chinese ─────────────────────────────────────
const WEEKDAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

function cronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hour, dom, month, dow] = parts
  const time = hour.startsWith('*/')
    ? `每 ${hour.slice(2)} 小时`
    : `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (dom === '*' && month === '*') {
    if (dow === '*') return `每天 ${time}`
    if (dow === '1-5') return `每个工作日 ${time}`
    if (/^\d$/.test(dow)) return `每${WEEKDAY_NAMES[+dow] || dow} ${time}`
    if (dow === '0' || dow === '7') return `每周日 ${time}`
  }
  if (dom !== '*' && month === '*' && dow === '*') return `每月 ${dom}日 ${time}`
  return cron
}

// ─── Status badge ───────────────────────────────────────────────────────
function StatusBadge({ status, lastRun }: { status: string; lastRun: string }) {
  if (!lastRun) return <span className="text-[11px] text-gray-400">尚未执行</span>
  const ok = status === 'success'
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] ${ok ? 'text-emerald-600' : 'text-rose-500'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-rose-500'}`} />
      {ok ? '成功' : '失败'} · {formatTime(lastRun)}
    </span>
  )
}

function formatTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const m = Math.floor(diff / 60000)
    if (m < 1) return '刚刚'
    if (m < 60) return `${m}分钟前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}小时前`
    const days = Math.floor(h / 24)
    return `${days}天前`
  } catch { return '' }
}

// ─── Task Card ──────────────────────────────────────────────────────────
function TaskCard({
  task,
  onToggle,
  onEdit,
  onDelete,
}: {
  task: AutomationTask
  onToggle: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-5 flex flex-col gap-3 min-h-[180px] hover:shadow-md transition-all">
      {/* Header: name + toggle */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium text-gray-900 truncate">{task.name || '未命名任务'}</div>
          <div className="text-[11px] text-gray-400 mt-0.5">{cronToHuman(task.cron_expr)}</div>
        </div>
        <button
          onClick={onToggle}
          className={`shrink-0 w-10 h-[22px] rounded-full relative transition-colors ${task.enabled ? 'bg-blue-500' : 'bg-gray-300'}`}
          title={task.enabled ? '停用' : '启用'}
        >
          <span className={`absolute top-0.5 w-[18px] h-[18px] rounded-full bg-white shadow transition-transform ${task.enabled ? 'left-[21px]' : 'left-0.5'}`} />
        </button>
      </div>

      {/* Description */}
      <p className="text-[12px] text-gray-500 leading-relaxed line-clamp-2 flex-1">
        {task.description || task.content.slice(0, 60) || '暂无描述'}
      </p>

      {/* Tags */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`px-1.5 py-0.5 rounded text-[10px] border ${
          task.action_type === 'skill'
            ? 'bg-purple-50 border-purple-200 text-purple-700'
            : 'bg-blue-50 border-blue-200 text-blue-700'
        }`}>
          {task.action_type === 'skill' ? `技能: ${task.skill_name}` : '消息触发'}
        </span>
        <span className="flex items-center gap-0.5 text-[10px] text-gray-400">
          <ClockSvg /> {cronToHuman(task.cron_expr)}
        </span>
      </div>

      {/* Status + actions */}
      <div className="flex items-center justify-between pt-1 border-t border-gray-100">
        <StatusBadge status={task.last_status} lastRun={task.last_run_at} />
        <div className="flex items-center gap-1">
          <button onClick={onEdit} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100" title="编辑">
            <EditSvg />
          </button>
          <button onClick={onDelete} className="p-1.5 rounded-lg text-gray-400 hover:text-rose-500 hover:bg-rose-50" title="删除">
            <TrashSvg />
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Template Picker Modal ──────────────────────────────────────────────
function TemplatePicker({
  templates,
  onClose,
  onSelect,
}: {
  templates: TaskTemplate[]
  onClose: () => void
  onSelect: (t: TaskTemplate) => void
}) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div onClick={(e) => e.stopPropagation()} className="relative w-full max-w-[640px] bg-white rounded-2xl shadow-2xl border border-gray-200/60 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h3 className="text-[14px] font-medium text-gray-900">从模板添加任务</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100">
            <CloseSvg />
          </button>
        </div>
        <div className="px-5 py-4 max-h-[65vh] overflow-y-auto">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {templates.map((t) => (
              <button
                key={t.name}
                onClick={() => onSelect(t)}
                className="text-left p-3.5 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50/40 transition-all group"
              >
                <div className="flex items-center gap-2.5 mb-2">
                  <span className="text-xl">{t.icon}</span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-gray-900 group-hover:text-blue-700">{t.display_name}</div>
                    <div className="text-[10.5px] text-gray-400">{t.cron_hint}</div>
                  </div>
                </div>
                <p className="text-[11.5px] text-gray-500 leading-relaxed line-clamp-2">{t.description}</p>
                <div className="flex items-center gap-1.5 mt-2">
                  <span className={`px-1.5 py-0.5 rounded text-[9.5px] border ${
                    t.action_type === 'skill'
                      ? 'bg-purple-50 border-purple-200 text-purple-600'
                      : 'bg-blue-50 border-blue-200 text-blue-600'
                  }`}>
                    {t.action_type === 'skill' ? `技能: ${t.skill_name}` : '消息触发'}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Create/Edit Form Modal ─────────────────────────────────────────────
function TaskFormDialog({
  onClose,
  onSaved,
  authToken,
  initial,
}: {
  onClose: () => void
  onSaved: () => void
  authToken: string
  initial?: Partial<AutomationTask> & { from_template?: string }
}) {
  const isEdit = !!initial?.id
  const [name, setName] = useState(initial?.name || '')
  const [cronExpr, setCronExpr] = useState(initial?.cron_expr || '0 9 * * *')
  const [actionType, setActionType] = useState<'dispatch' | 'skill'>(initial?.action_type || 'dispatch')
  const [skillName, setSkillName] = useState(initial?.skill_name || '')
  const [content, setContent] = useState(initial?.content || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true)
    setErr('')
    try {
      if (isEdit) {
        const res = await fetch(`${API_BASE}/automation/tasks/${initial!.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
          body: JSON.stringify({ name, cron_expr: cronExpr, action_type: actionType, skill_name: skillName, content, description }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) { setErr(data?.error || `保存失败 (${res.status})`); return }
      } else if (initial?.from_template) {
        const res = await fetch(`${API_BASE}/automation/tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
          body: JSON.stringify({ from_template: initial.from_template, overrides: { name, cron_expr: cronExpr, action_type: actionType, skill_name: skillName, content, description } }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) { setErr(data?.error || `创建失败 (${res.status})`); return }
      } else {
        const res = await fetch(`${API_BASE}/automation/tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
          body: JSON.stringify({ name, cron_expr: cronExpr, action_type: actionType, skill_name: skillName, content, description }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) { setErr(data?.error || `创建失败 (${res.status})`); return }
      }
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
          <h3 className="text-[14px] font-medium text-gray-900">{isEdit ? '编辑任务' : '新建任务'}</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100">
            <CloseSvg />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3 max-h-[65vh] overflow-y-auto">
          <Field label="任务名称">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="每日工作总结"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="描述">
            <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话描述任务用途"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="执行周期">
            <div className="flex flex-wrap gap-1.5 mb-2">
              {CRON_PRESETS.map((p) => (
                <button key={p.value} type="button" onClick={() => setCronExpr(p.value)}
                  className={`px-2 py-1 text-[11px] rounded-lg border transition-colors ${
                    cronExpr === p.value ? 'bg-blue-50 border-blue-300 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}>{p.label}</button>
              ))}
            </div>
            <input value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} placeholder="0 9 * * *"
              className="w-full px-3 py-1.5 text-[12px] font-mono border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="执行方式">
            <div className="flex gap-2">
              <button type="button" onClick={() => setActionType('dispatch')}
                className={`flex-1 py-2 text-[12px] rounded-lg border transition-colors ${
                  actionType === 'dispatch' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}>消息触发</button>
              <button type="button" onClick={() => setActionType('skill')}
                className={`flex-1 py-2 text-[12px] rounded-lg border transition-colors ${
                  actionType === 'skill' ? 'bg-purple-50 border-purple-300 text-purple-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}>技能调用</button>
            </div>
          </Field>
          {actionType === 'skill' && (
            <Field label="技能名称">
              <input value={skillName} onChange={(e) => setSkillName(e.target.value)} placeholder="baidu_search"
                className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
            </Field>
          )}
          <Field label="任务内容（Prompt）">
            <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={4}
              className="w-full px-3 py-2 text-[12.5px] font-mono border border-gray-200 rounded-lg outline-none focus:border-blue-400 resize-y leading-relaxed"
              placeholder="请总结今天的工作内容..." />
          </Field>
          {err && <div className="text-[12px] text-rose-500">{err}</div>}
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button onClick={onClose} className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50">取消</button>
          <button onClick={submit} disabled={busy || !cronExpr.trim() || (!name.trim() && !content.trim())}
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
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse min-h-[160px]">
          <div className="flex justify-between"><div className="w-24 h-4 rounded bg-gray-100" /><div className="w-10 h-5 rounded-full bg-gray-100" /></div>
          <div className="h-4 bg-gray-100 rounded mt-4 w-full" />
          <div className="h-3 bg-gray-100 rounded mt-2 w-3/5" />
          <div className="h-6 bg-gray-100 rounded mt-4 w-1/3" />
        </div>
      ))}
    </div>
  )
}

// ─── Main View ──────────────────────────────────────────────────────────
export function AutomationManagerView({ authToken }: { authToken: string }) {
  const [tasks, setTasks] = useState<AutomationTask[]>([])
  const [templates, setTemplates] = useState<TaskTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)
  const [editingTask, setEditingTask] = useState<AutomationTask | null>(null)
  const [templateInitial, setTemplateInitial] = useState<(Partial<AutomationTask> & { from_template?: string }) | null>(null)
  const [toast, setToast] = useState('')
  const [err, setErr] = useState('')

  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${authToken}` }), [authToken])

  const fireToast = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(''), 2400)
  }, [])

  const loadTasks = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/automation/tasks`, { headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data?.tasks) setTasks(data.tasks)
      else if (!res.ok) setErr(data?.error || `加载失败 (${res.status})`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [authHeaders])

  const loadTemplates = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/automation/templates`, { headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data?.templates) setTemplates(data.templates)
    } catch { /* ignore */ }
  }, [authHeaders])

  useEffect(() => { loadTasks(); loadTemplates() }, [loadTasks, loadTemplates])

  const handleToggle = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/automation/tasks/${id}/toggle`, {
        method: 'PATCH', headers: authHeaders,
      })
      if (res.ok) await loadTasks()
      else fireToast('操作失败')
    } catch { fireToast('操作失败') }
  }, [authHeaders, loadTasks, fireToast])

  const handleDelete = useCallback(async (id: string, name: string) => {
    if (!confirm(`确定删除任务「${name || id}」？`)) return
    try {
      const res = await fetch(`${API_BASE}/automation/tasks/${id}`, {
        method: 'DELETE', headers: authHeaders,
      })
      if (res.ok) { fireToast('已删除'); await loadTasks() }
      else fireToast('删除失败')
    } catch { fireToast('删除失败') }
  }, [authHeaders, loadTasks, fireToast])

  const handleTemplateSelect = useCallback((t: TaskTemplate) => {
    setShowTemplates(false)
    setTemplateInitial({
      name: t.display_name,
      description: t.description,
      cron_expr: t.cron_expr,
      action_type: t.action_type,
      skill_name: t.skill_name,
      content: t.content,
      from_template: t.name,
    })
  }, [])

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50/40">
      {/* Header */}
      <header className="shrink-0 px-6 lg:px-8 pt-6 pb-4 bg-white border-b border-gray-200/70">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[22px] font-medium text-gray-900 leading-tight">自动化</h1>
            <p className="text-[13px] text-gray-500 mt-1">
              管理定时任务，让 AI 自动执行重复性工作
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={() => setShowTemplates(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50">
              <TemplateSvg /><span>从模板添加</span>
            </button>
            <button onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800">
              <PlusSvg size={14} /><span>新建任务</span>
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-6">
        {err && (
          <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">{err}</div>
        )}
        {loading ? (
          <GridSkeleton />
        ) : tasks.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-[14px] text-gray-700 font-medium">暂无定时任务</div>
            <div className="text-[12.5px] text-gray-500 mt-1.5">
              点击「新建任务」或「从模板添加」开始创建
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {tasks.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                onToggle={() => handleToggle(t.id)}
                onEdit={() => setEditingTask(t)}
                onDelete={() => handleDelete(t.id, t.name)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Template picker */}
      {showTemplates && (
        <TemplatePicker
          templates={templates}
          onClose={() => setShowTemplates(false)}
          onSelect={handleTemplateSelect}
        />
      )}

      {/* Create dialog */}
      {showCreate && (
        <TaskFormDialog
          onClose={() => setShowCreate(false)}
          onSaved={async () => { setShowCreate(false); fireToast('创建成功'); await loadTasks() }}
          authToken={authToken}
        />
      )}

      {/* Template-based create dialog */}
      {templateInitial && (
        <TaskFormDialog
          initial={templateInitial}
          onClose={() => setTemplateInitial(null)}
          onSaved={async () => { setTemplateInitial(null); fireToast('创建成功'); await loadTasks() }}
          authToken={authToken}
        />
      )}

      {/* Edit dialog */}
      {editingTask && (
        <TaskFormDialog
          initial={editingTask}
          onClose={() => setEditingTask(null)}
          onSaved={async () => { setEditingTask(null); fireToast('保存成功'); await loadTasks() }}
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

export default AutomationManagerView
