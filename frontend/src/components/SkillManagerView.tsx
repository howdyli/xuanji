/**
 * SkillManagerView —— 重构后的「技能」主页面（4 列卡片网格风格）
 *
 * 布局结构：
 *   ┌─ 头部：标题 + 副标题 ─ 搜索框 ─ + 添加技能 ─┐
 *   ├─ Tabs：技能市场 / 已安装 N            ─┤
 *   ├─ 卡片网格（4 列响应式）              ─┤
 *   │  详情抽屉（右滑入） / 添加技能面板    ─┤
 *   └─────────────────────────────────────┘
 *
 * 旧 SkillsPanel.tsx 保留（兼容入口），不在此处复用。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

const API_BASE = '/api/frontend'
const TOKEN = 'test-token-dev-2024'
const authHeaders = { Authorization: `Bearer ${TOKEN}` }

// ─── Types ──────────────────────────────────────────────────────────────
export interface InstalledSkill {
  name: string
  source: 'builtin' | 'user'
  type: 'task' | 'reference'
  description: string
  author: string
  version: string
  enabled: boolean
  path: string | null
  files: string[]
  is_bundle: boolean
}

export interface MarketSkill {
  name: string
  source_type: 'vercel' | 'clawhub'
  version: string
  description: string
  author: string
  repo_url: string
  install_url: string
  updated_at: string | null
  fetched_at: string
  installed: boolean
}

interface DetailPayload extends Partial<InstalledSkill & MarketSkill> {
  skill_md?: string
  // origin distinguishes which kind of detail we are showing
  __kind?: 'installed' | 'market'
}

type Tab = 'market' | 'installed'

// ─── Inline icons (line style, match 玄机 palette) ────────────────
const SearchSvg = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)
const PlusSvg = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
)
const RefreshSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="23 4 23 10 17 10" />
    <polyline points="1 20 1 14 7 14" />
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
  </svg>
)
const MoreSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="12" r="1" />
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
  </svg>
)
const CloseSvg = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)
const StoreSvg = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 9l1-5h16l1 5" />
    <path d="M5 9v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9" />
    <path d="M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" />
  </svg>
)
const UploadSvg = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
)
const SparkSvg = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
  </svg>
)
const CheckSvg = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

// ─── Avatar gradient (deterministic by name) ───────────────────────────
const GRADIENTS = [
  'from-violet-400 to-fuchsia-500',
  'from-sky-400 to-blue-500',
  'from-sky-400 to-blue-500',
  'from-orange-400 to-rose-500',
  'from-amber-400 to-yellow-500',
  'from-pink-400 to-rose-500',
]
function gradientOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}
function initialOf(name: string): string {
  return (name[0] || '?').toUpperCase()
}

// ─── Card ─────────────────────────────────────────────────────────────
function SkillCard({
  name,
  description,
  isBundle,
  installed,
  badgeLabel,
  onClick,
}: {
  name: string
  description: string
  isBundle: boolean
  installed?: boolean
  badgeLabel?: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="group text-left bg-white border border-gray-200 rounded-xl p-4 hover:border-gray-300 hover:shadow-sm transition-all flex flex-col gap-3 min-h-[148px]"
    >
      {/* Top row: avatar + bundle badge + more */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className={`w-9 h-9 rounded-full bg-gradient-to-br ${gradientOf(name)} flex items-center justify-center text-white text-sm font-semibold shrink-0`}
          >
            {initialOf(name)}
          </div>
          {isBundle && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-50 text-violet-600 border border-violet-100">
              套件
            </span>
          )}
          {badgeLabel && !isBundle && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-600 border border-gray-200">
              {badgeLabel}
            </span>
          )}
        </div>
        <span
          className="w-6 h-6 flex items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
          title="查看详情"
        >
          <MoreSvg />
        </span>
      </div>

      {/* Title */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="text-[14px] font-medium text-gray-900 truncate">{name}</span>
        {installed && (
          <span className="text-emerald-500 shrink-0" title="已安装">
            <CheckSvg />
          </span>
        )}
      </div>

      {/* Description (2-line clamp) */}
      <p className="text-[12.5px] text-gray-500 leading-relaxed line-clamp-2 min-h-[36px]">
        {description || '暂无描述'}
      </p>
    </button>
  )
}

// ─── Detail Drawer ────────────────────────────────────────────────────
function DetailDrawer({
  payload,
  onClose,
  onAction,
  busy,
}: {
  payload: DetailPayload | null
  onClose: () => void
  onAction: (action: 'install' | 'uninstall' | 'toggle' | 'reinstall', skill: DetailPayload) => void
  busy: boolean
}) {
  if (!payload) return null
  const isInstalled = payload.__kind === 'installed' || payload.installed
  const name = payload.name || ''
  const description = payload.description || ''
  const author = payload.author || ''
  const version = payload.version || ''
  const skillMd = payload.skill_md || ''
  const repoUrl = payload.repo_url || ''
  const sourceLabel =
    payload.__kind === 'installed'
      ? payload.source === 'builtin' ? '内置' : '用户'
      : payload.source_type === 'vercel' ? 'Vercel Skills'
      : payload.source_type === 'clawhub' ? 'ClawHub'
      : ''

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="w-full max-w-[520px] h-full bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200/70">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${gradientOf(name)} flex items-center justify-center text-white text-base font-semibold shrink-0`}>
              {initialOf(name)}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="text-[15px] font-medium text-gray-900 truncate">{name}</h3>
                {payload.is_bundle && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-50 text-violet-600 border border-violet-100">
                    套件
                  </span>
                )}
              </div>
              <div className="text-[11.5px] text-gray-400 mt-0.5">
                {sourceLabel}{version ? ` · v${version}` : ''}{author ? ` · ${author}` : ''}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <CloseSvg />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <section>
            <div className="text-[11px] font-medium text-gray-400 mb-1.5">描述</div>
            <p className="text-[13px] text-gray-700 leading-relaxed whitespace-pre-wrap">
              {description || '暂无描述'}
            </p>
          </section>
          {repoUrl && (
            <section>
              <div className="text-[11px] font-medium text-gray-400 mb-1.5">仓库</div>
              <a
                href={repoUrl}
                target="_blank"
                rel="noreferrer"
                className="text-[12.5px] text-blue-600 hover:underline break-all"
              >
                {repoUrl}
              </a>
            </section>
          )}
          {skillMd && (
            <section>
              <div className="text-[11px] font-medium text-gray-400 mb-1.5">SKILL.md</div>
              <pre className="text-[11.5px] text-gray-700 bg-gray-50 border border-gray-200 rounded-lg p-3 max-h-[280px] overflow-auto whitespace-pre-wrap font-mono">
                {skillMd}
              </pre>
            </section>
          )}
          {payload.__kind === 'installed' && payload.files && payload.files.length > 0 && (
            <section>
              <div className="text-[11px] font-medium text-gray-400 mb-1.5">文件</div>
              <ul className="text-[12px] text-gray-600 space-y-1">
                {payload.files.map((f) => (
                  <li key={f} className="font-mono truncate">{f}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        {/* Footer actions */}
        <div className="px-5 py-3 border-t border-gray-200/70 flex items-center justify-end gap-2 bg-gray-50/50">
          {payload.__kind === 'market' ? (
            isInstalled ? (
              <button
                disabled={busy}
                onClick={() => onAction('reinstall', payload)}
                className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {busy ? '处理中…' : '重新安装'}
              </button>
            ) : (
              <button
                disabled={busy}
                onClick={() => onAction('install', payload)}
                className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {busy ? '安装中…' : '一键安装'}
              </button>
            )
          ) : (
            <>
              <button
                disabled={busy}
                onClick={() => onAction('toggle', payload)}
                className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {payload.enabled ? '禁用' : '启用'}
              </button>
              {payload.source === 'user' && (
                <button
                  disabled={busy}
                  onClick={() => onAction('uninstall', payload)}
                  className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-rose-200 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                >
                  卸载
                </button>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  )
}

// ─── Add-skill 三入口面板 + 上传/创建对话框 ─────────────────────────────
function AddSkillMenu({
  onClose,
  onPickMarket,
  onPickUpload,
  onPickCreate,
}: {
  onClose: () => void
  onPickMarket: () => void
  onPickUpload: () => void
  onPickCreate: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-[600px] bg-white rounded-2xl shadow-2xl border border-gray-200/60 overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h3 className="text-[14px] font-medium text-gray-900">添加技能</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <CloseSvg />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-3 p-5">
          <EntryCard icon={<StoreSvg />} title="从市场安装" subtitle="浏览 Vercel/ClawHub" onClick={onPickMarket} />
          <EntryCard icon={<UploadSvg />} title="上传压缩包" subtitle="本地 .zip 文件" onClick={onPickUpload} />
          <EntryCard icon={<SparkSvg />} title="创建技能" subtitle="编辑 SKILL.md" onClick={onPickCreate} />
        </div>
      </div>
    </div>
  )
}

function EntryCard({
  icon,
  title,
  subtitle,
  onClick,
}: {
  icon: React.ReactNode
  title: string
  subtitle: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="text-left bg-white border border-gray-200 rounded-xl p-4 hover:border-blue-300 hover:bg-blue-50/30 transition-colors flex flex-col gap-2"
    >
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center text-gray-700">
        {icon}
      </div>
      <div className="text-[13px] font-medium text-gray-900">{title}</div>
      <div className="text-[11.5px] text-gray-500">{subtitle}</div>
    </button>
  )
}

function UploadDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [overwrite, setOverwrite] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async () => {
    if (!file) {
      setErr('请选择 .zip 文件')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(
        `${API_BASE}/skills/upload${overwrite ? '?overwrite=true' : ''}`,
        { method: 'POST', headers: authHeaders, body: fd },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setErr(data?.error || `上传失败 (${res.status})`)
        return
      }
      onUploaded()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div onClick={(e) => e.stopPropagation()} className="relative w-full max-w-[440px] bg-white rounded-2xl shadow-2xl border border-gray-200/60 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h3 className="text-[14px] font-medium text-gray-900">上传技能压缩包</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <CloseSvg />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full text-[12.5px] text-gray-700 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-gray-100 file:text-gray-700 file:text-[12px] hover:file:bg-gray-200"
          />
          <label className="flex items-center gap-2 text-[12.5px] text-gray-600">
            <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
            覆盖同名技能
          </label>
          {err && <div className="text-[12px] text-rose-500">{err}</div>}
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button onClick={onClose} className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50">取消</button>
          <button onClick={submit} disabled={busy} className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50">
            {busy ? '上传中…' : '上传'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [body, setBody] = useState('')
  const [type_, setType] = useState<'task' | 'reference'>('task')
  const [author, setAuthor] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async () => {
    setBusy(true)
    setErr('')
    try {
      const res = await fetch(`${API_BASE}/skills`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, body, type: type_, author, version: '1.0.0' }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setErr(data?.error || `创建失败 (${res.status})`)
        return
      }
      onCreated()
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
          <h3 className="text-[14px] font-medium text-gray-900">创建技能</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <CloseSvg />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
          <Field label="名称（kebab-case 或 underscore，1-64 字符）">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-skill" className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="描述（一句话简介）">
            <input value={description} onChange={(e) => setDescription(e.target.value)} className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="类型">
            <div className="flex gap-2">
              {(['task', 'reference'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setType(t)}
                  className={`px-3 py-1 rounded-lg text-[12.5px] border ${type_ === t ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                >
                  {t === 'task' ? 'task（任务型）' : 'reference（参考型）'}
                </button>
              ))}
            </div>
          </Field>
          <Field label="作者（可选）">
            <input value={author} onChange={(e) => setAuthor(e.target.value)} className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-blue-400" />
          </Field>
          <Field label="SKILL.md 正文">
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={8}
              className="w-full px-3 py-2 text-[12.5px] font-mono border border-gray-200 rounded-lg outline-none focus:border-blue-400 resize-y"
              placeholder="# my-skill&#10;&#10;What this skill does..."
            />
          </Field>
          {err && <div className="text-[12px] text-rose-500">{err}</div>}
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button onClick={onClose} className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-700 hover:bg-gray-50">取消</button>
          <button
            onClick={submit}
            disabled={busy || !name.trim() || !description.trim() || !body.trim()}
            className="px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {busy ? '创建中…' : '创建'}
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

// ─── Main view ────────────────────────────────────────────────────────
export function SkillManagerView() {
  const [tab, setTab] = useState<Tab>('market')
  const [search, setSearch] = useState('')
  const [installed, setInstalled] = useState<InstalledSkill[]>([])
  const [market, setMarket] = useState<MarketSkill[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [detail, setDetail] = useState<DetailPayload | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [showAddMenu, setShowAddMenu] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [toast, setToast] = useState('')

  const fireToast = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(''), 2400)
  }, [])

  const loadInstalled = useCallback(async () => {
    const res = await fetch(`${API_BASE}/skills`, { headers: authHeaders })
    const data = await res.json().catch(() => ({}))
    if (res.ok && data?.skills) setInstalled(data.skills as InstalledSkill[])
    else if (!res.ok) setErr(data?.error || `加载失败 (${res.status})`)
  }, [])

  const loadMarket = useCallback(async (s = '') => {
    const url = `${API_BASE}/market/skills${s ? `?search=${encodeURIComponent(s)}` : ''}`
    const res = await fetch(url, { headers: authHeaders })
    const data = await res.json().catch(() => ({}))
    if (res.ok && data?.skills) setMarket(data.skills as MarketSkill[])
    else if (!res.ok) setErr(data?.error || `加载市场失败 (${res.status})`)
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      await Promise.all([loadInstalled(), loadMarket(search)])
    } finally {
      setLoading(false)
    }
  }, [loadInstalled, loadMarket, search])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // search debounce → re-fetch market on text change
  useEffect(() => {
    const id = window.setTimeout(() => {
      loadMarket(search)
    }, 280)
    return () => window.clearTimeout(id)
  }, [search, loadMarket])

  const filteredInstalled = useMemo(() => {
    if (!search) return installed
    const q = search.toLowerCase()
    return installed.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.author.toLowerCase().includes(q),
    )
  }, [installed, search])

  const installedNames = useMemo(() => new Set(installed.map((s) => s.name)), [installed])

  const openInstalledDetail = useCallback(async (name: string) => {
    setDetail({ name, __kind: 'installed' })
    const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(name)}`, { headers: authHeaders })
    const data = await res.json().catch(() => ({}))
    if (res.ok) setDetail({ ...data, __kind: 'installed' })
  }, [])

  const openMarketDetail = useCallback(
    async (name: string) => {
      setDetail({ name, __kind: 'market' })
      const res = await fetch(`${API_BASE}/market/skills/${encodeURIComponent(name)}`, {
        headers: authHeaders,
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) setDetail({ ...data, __kind: 'market' })
    },
    [],
  )

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    setErr('')
    try {
      const res = await fetch(`${API_BASE}/market/refresh`, { method: 'POST', headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setErr(data?.error || `刷新失败 (${res.status})`)
        fireToast('刷新失败')
      } else {
        fireToast('已刷新市场索引')
        await loadMarket(search)
      }
    } finally {
      setRefreshing(false)
    }
  }, [loadMarket, search, fireToast])

  const handleAction = useCallback(
    async (action: 'install' | 'uninstall' | 'toggle' | 'reinstall', s: DetailPayload) => {
      setActionBusy(true)
      try {
        if (action === 'install' || action === 'reinstall') {
          const url = `${API_BASE}/market/skills/${encodeURIComponent(s.name!)}/install${
            action === 'reinstall' ? '?overwrite=true' : ''
          }`
          const res = await fetch(url, { method: 'POST', headers: authHeaders })
          const data = await res.json().catch(() => ({}))
          if (!res.ok) {
            fireToast(`安装失败：${data?.error || res.status}`)
            return
          }
          fireToast('安装成功')
          await Promise.all([loadInstalled(), loadMarket(search)])
          setDetail((prev) => (prev ? { ...prev, installed: true } : prev))
        } else if (action === 'uninstall') {
          if (!confirm(`确定卸载技能「${s.name}」？此操作会删除本地文件。`)) return
          const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(s.name!)}`, {
            method: 'DELETE',
            headers: authHeaders,
          })
          const data = await res.json().catch(() => ({}))
          if (!res.ok) {
            fireToast(`卸载失败：${data?.error || res.status}`)
            return
          }
          fireToast('已卸载')
          setDetail(null)
          await Promise.all([loadInstalled(), loadMarket(search)])
        } else if (action === 'toggle') {
          const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(s.name!)}/toggle`, {
            method: 'POST',
            headers: { ...authHeaders, 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: !s.enabled }),
          })
          const data = await res.json().catch(() => ({}))
          if (!res.ok) {
            fireToast(`操作失败：${data?.error || res.status}`)
            return
          }
          await loadInstalled()
          setDetail((prev) => (prev ? { ...prev, enabled: !prev.enabled } : prev))
        }
      } finally {
        setActionBusy(false)
      }
    },
    [loadInstalled, loadMarket, search, fireToast],
  )

  // ── Render ──
  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50/40">
      {/* Header */}
      <header className="shrink-0 px-6 lg:px-8 pt-6 pb-4 bg-white border-b border-gray-200/70">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[22px] font-medium text-gray-900 leading-tight">技能</h1>
            <p className="text-[13px] text-gray-500 mt-1">赋予 玄机 更强大的能力</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 w-[260px]">
              <span className="text-gray-400"><SearchSvg /></span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索技能"
                className="flex-1 text-[12.5px] bg-transparent outline-none text-gray-700 placeholder-gray-400"
              />
            </div>
            {tab === 'market' && (
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[12.5px] rounded-lg bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                title="刷新市场索引"
              >
                <span className={refreshing ? 'animate-spin inline-flex' : 'inline-flex'}>
                  <RefreshSvg />
                </span>
                <span>{refreshing ? '刷新中…' : '刷新'}</span>
              </button>
            )}
            <button
              onClick={() => setShowAddMenu(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] rounded-lg bg-gray-900 text-white hover:bg-gray-800"
            >
              <PlusSvg size={14} />
              <span>添加技能</span>
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-4 flex items-center gap-6 border-b border-transparent -mb-4">
          <TabButton active={tab === 'market'} onClick={() => setTab('market')}>
            技能市场
          </TabButton>
          <TabButton active={tab === 'installed'} onClick={() => setTab('installed')}>
            已安装 <span className="text-gray-400 font-normal ml-0.5">{installed.length}</span>
          </TabButton>
        </div>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-6">
        {err && (
          <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">
            {err}
          </div>
        )}
        {loading ? (
          <GridSkeleton />
        ) : tab === 'market' ? (
          market.length === 0 ? (
            <EmptyState
              title={search ? '没有匹配的技能' : '市场为空'}
              hint={search ? '试试其他关键字，或点击右上角刷新。' : '点击右上角「刷新」从远程仓库同步索引。'}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {market.map((s) => (
                <SkillCard
                  key={s.name}
                  name={s.name}
                  description={s.description}
                  isBundle
                  installed={s.installed || installedNames.has(s.name)}
                  badgeLabel={s.source_type === 'vercel' ? 'Vercel' : 'ClawHub'}
                  onClick={() => openMarketDetail(s.name)}
                />
              ))}
            </div>
          )
        ) : filteredInstalled.length === 0 ? (
          <EmptyState
            title={search ? '没有匹配的已安装技能' : '尚未安装任何技能'}
            hint='去「技能市场」浏览，或点击右上角「添加技能」上传/创建。'
          />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredInstalled.map((s) => (
              <SkillCard
                key={s.name}
                name={s.name}
                description={s.description}
                isBundle={s.is_bundle}
                badgeLabel={s.source === 'builtin' ? '内置' : '用户'}
                onClick={() => openInstalledDetail(s.name)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Detail drawer */}
      <DetailDrawer
        payload={detail}
        onClose={() => setDetail(null)}
        onAction={handleAction}
        busy={actionBusy}
      />

      {/* Add-skill menu + dialogs */}
      {showAddMenu && (
        <AddSkillMenu
          onClose={() => setShowAddMenu(false)}
          onPickMarket={() => {
            setShowAddMenu(false)
            setTab('market')
          }}
          onPickUpload={() => {
            setShowAddMenu(false)
            setShowUpload(true)
          }}
          onPickCreate={() => {
            setShowAddMenu(false)
            setShowCreate(true)
          }}
        />
      )}
      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onUploaded={async () => {
            setShowUpload(false)
            setTab('installed')
            fireToast('上传成功')
            await loadInstalled()
          }}
        />
      )}
      {showCreate && (
        <CreateDialog
          onClose={() => setShowCreate(false)}
          onCreated={async () => {
            setShowCreate(false)
            setTab('installed')
            fireToast('创建成功')
            await loadInstalled()
          }}
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

function TabButton({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`relative pb-3 text-[13.5px] transition-colors ${
        active ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {children}
      {active && <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-gray-900 rounded-full" />}
    </button>
  )
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse min-h-[148px]">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-full bg-gray-100" />
            <div className="w-12 h-4 rounded bg-gray-100" />
          </div>
          <div className="h-4 bg-gray-100 rounded mt-3 w-1/2" />
          <div className="h-3 bg-gray-100 rounded mt-3 w-full" />
          <div className="h-3 bg-gray-100 rounded mt-1.5 w-4/5" />
        </div>
      ))}
    </div>
  )
}

function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="text-center py-20">
      <div className="text-[14px] text-gray-700 font-medium">{title}</div>
      <div className="text-[12.5px] text-gray-500 mt-1.5">{hint}</div>
    </div>
  )
}

export default SkillManagerView
