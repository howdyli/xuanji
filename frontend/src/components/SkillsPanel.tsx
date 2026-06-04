import { useCallback, useEffect, useRef, useState } from 'react'

const API_BASE = '/api/frontend'
const TOKEN = 'test-token-dev-2024'

export interface SkillItem {
  name: string
  source: 'builtin' | 'user'
  type: string
  description: string
  author: string
  version: string
  enabled: boolean
}

interface SkillDetail extends SkillItem {
  body: string
  files: string[]
}

interface SkillsPanelProps {
  onClose?: () => void
}

const authHeaders = { Authorization: `Bearer ${TOKEN}` }

export function SkillsPanel({ onClose }: SkillsPanelProps) {
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [filter, setFilter] = useState<'all' | 'builtin' | 'user'>('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<SkillDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const refreshList = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API_BASE}/skills`, { headers: authHeaders })
      const j = await r.json()
      setSkills(j.skills || [])
      setError(null)
    } catch (e) {
      setError(`加载技能列表失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshList()
  }, [refreshList])

  useEffect(() => {
    if (!selected) {
      setDetail(null)
      return
    }
    let cancelled = false
    fetch(`${API_BASE}/skills/${encodeURIComponent(selected)}`, { headers: authHeaders })
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled) setDetail(j)
      })
      .catch(() => {
        if (!cancelled) setDetail(null)
      })
    return () => {
      cancelled = true
    }
  }, [selected])

  const filteredSkills = skills
    .filter((s) => filter === 'all' || s.source === filter)
    .filter(
      (s) =>
        !search ||
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.description.toLowerCase().includes(search.toLowerCase()),
    )

  const handleToggle = async (name: string) => {
    try {
      await fetch(`${API_BASE}/skills/${encodeURIComponent(name)}/toggle`, {
        method: 'POST',
        headers: authHeaders,
      })
      await refreshList()
    } catch (e) {
      setError(`切换状态失败: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`确定删除技能 "${name}" 吗？此操作不可撤销。`)) return
    try {
      const r = await fetch(`${API_BASE}/skills/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j.error || `HTTP ${r.status}`)
      }
      if (selected === name) setSelected(null)
      await refreshList()
    } catch (e) {
      setError(`删除失败: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleUpload = async (file: File) => {
    setLoading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${API_BASE}/skills/upload`, {
        method: 'POST',
        headers: authHeaders,
        body: fd,
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`)
      await refreshList()
      if (j.name) setSelected(j.name)
    } catch (e) {
      setError(`上传失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDownload = (name: string) => {
    const url = `${API_BASE}/skills/${encodeURIComponent(name)}/download`
    // Token through query is not implemented; rely on bearer via fetch then blob
    fetch(url, { headers: authHeaders })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `${name}.zip`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      })
      .catch((e) => setError(`下载失败: ${e instanceof Error ? e.message : String(e)}`))
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-white">
      {/* Header */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 sm:px-6 py-3 border-b border-gray-200/80">
        <div className="min-w-0">
          <h1 className="text-[15px] font-semibold text-gray-800">技能</h1>
          <p className="text-[11.5px] text-gray-500 mt-0.5 hidden sm:block">为智能体注入能力，支持创建、上传、下载和启用控制。</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleUpload(f)
            }}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-[12.5px] text-gray-700 hover:bg-gray-50"
          >
            上传 .zip
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-[12.5px] hover:bg-gray-800"
          >
            新建技能
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="px-2 py-1.5 rounded-lg text-gray-500 hover:bg-gray-100 text-[12.5px]"
            >
              关闭
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="shrink-0 px-6 py-2 bg-red-50 border-b border-red-100 text-[12px] text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            ×
          </button>
        </div>
      )}

      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        {/* List */}
        <div
          className={`md:w-[340px] md:shrink-0 md:border-r border-gray-200/80 flex flex-col ${
            selected ? 'hidden md:flex' : 'flex flex-1 md:flex-none'
          }`}
        >
          {/* Filter & Search */}
          <div className="shrink-0 p-3 space-y-2">
            <div className="flex items-center gap-1 bg-gray-100/80 rounded-lg p-0.5">
              {(['all', 'builtin', 'user'] as const).map((k) => (
                <button
                  key={k}
                  onClick={() => setFilter(k)}
                  className={`flex-1 px-2 py-1 rounded-md text-[11.5px] transition-colors ${
                    filter === k ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {k === 'all' ? '全部' : k === 'builtin' ? '内置' : '用户'}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索技能..."
              className="w-full px-2.5 py-1.5 text-[12.5px] bg-gray-50 border border-gray-200 rounded-lg outline-none focus:bg-white focus:border-gray-300"
            />
          </div>

          {/* List items */}
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
            {loading && skills.length === 0 ? (
              <div className="px-3 py-4 text-[12px] text-gray-400 text-center">加载中...</div>
            ) : filteredSkills.length === 0 ? (
              <div className="px-3 py-4 text-[12px] text-gray-400 text-center">暂无技能</div>
            ) : (
              filteredSkills.map((s) => (
                <button
                  key={s.name}
                  onClick={() => setSelected(s.name)}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                    selected === s.name ? 'bg-gray-100' : 'hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12.5px] font-medium text-gray-800 truncate">{s.name}</span>
                    <span
                      className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full ${
                        s.source === 'builtin'
                          ? 'bg-blue-50 text-blue-700'
                          : 'bg-blue-50 text-blue-700'
                      }`}
                    >
                      {s.source === 'builtin' ? '内置' : '用户'}
                    </span>
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">{s.description}</div>
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-[10px] text-gray-400">v{s.version}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        s.enabled ? 'text-blue-700 bg-blue-50' : 'text-gray-500 bg-gray-100'
                      }`}
                    >
                      {s.enabled ? '已启用' : '已禁用'}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Detail */}
        <div className={`flex-1 overflow-y-auto ${selected ? 'flex flex-col' : 'hidden md:flex md:flex-col'}`}>
          {!selected ? (
            <div className="h-full flex items-center justify-center text-[12.5px] text-gray-400">
              选择一个技能查看详情
            </div>
          ) : !detail ? (
            <div className="h-full flex items-center justify-center text-[12.5px] text-gray-400">加载中...</div>
          ) : (
            <div className="p-4 sm:p-6 max-w-3xl">
              {/* Mobile back button */}
              <button
                onClick={() => setSelected(null)}
                className="md:hidden mb-3 inline-flex items-center gap-1 text-[12px] text-gray-600 hover:text-gray-900"
              >
                <span>←</span>
                <span>返回列表</span>
              </button>
              <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <h2 className="text-[18px] font-semibold text-gray-900">{detail.name}</h2>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                        detail.source === 'builtin' ? 'bg-blue-50 text-blue-700' : 'bg-blue-50 text-blue-700'
                      }`}
                    >
                      {detail.source === 'builtin' ? '内置' : '用户'}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {detail.type}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-gray-500">
                    v{detail.version}
                    {detail.author && <span> · 作者 {detail.author}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleToggle(detail.name)}
                    className={`px-3 py-1.5 rounded-lg text-[12px] border transition-colors ${
                      detail.enabled
                        ? 'border-gray-200 text-gray-700 hover:bg-gray-50'
                        : 'border-blue-300 text-blue-700 bg-blue-50 hover:bg-blue-100'
                    }`}
                  >
                    {detail.enabled ? '禁用' : '启用'}
                  </button>
                  <button
                    onClick={() => handleDownload(detail.name)}
                    className="px-3 py-1.5 rounded-lg border border-gray-200 text-[12px] text-gray-700 hover:bg-gray-50"
                  >
                    下载
                  </button>
                  {detail.source === 'user' && (
                    <button
                      onClick={() => handleDelete(detail.name)}
                      className="px-3 py-1.5 rounded-lg border border-red-200 text-[12px] text-red-700 bg-red-50 hover:bg-red-100"
                    >
                      删除
                    </button>
                  )}
                </div>
              </div>

              <p className="text-[13px] text-gray-700 leading-relaxed mb-4">{detail.description}</p>

              {detail.files.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-[12px] font-semibold text-gray-700 mb-1.5">文件 ({detail.files.length})</h3>
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-2 max-h-32 overflow-y-auto">
                    {detail.files.map((f) => (
                      <div key={f} className="text-[11.5px] text-gray-600 font-mono">
                        {f}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h3 className="text-[12px] font-semibold text-gray-700 mb-1.5">SKILL.md</h3>
                <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-[11.5px] text-gray-700 whitespace-pre-wrap font-mono leading-relaxed max-h-[400px] overflow-y-auto">
                  {detail.body}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>

      {showCreate && (
        <CreateSkillDialog
          onClose={() => setShowCreate(false)}
          onCreated={async (name) => {
            setShowCreate(false)
            await refreshList()
            setSelected(name)
          }}
        />
      )}
    </div>
  )
}

function CreateSkillDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (name: string) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [author, setAuthor] = useState('')
  const [body, setBody] = useState(
    '## Instructions\n\n描述这个技能在何时使用，以及如何调用其脚本。\n',
  )
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!name.trim() || !description.trim()) {
      setError('名称和描述为必填项')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch(`${API_BASE}/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          author: author.trim() || 'user',
          body,
        }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`)
      onCreated(j.name || name.trim())
    } catch (e) {
      setError(`创建失败: ${e instanceof Error ? e.message : String(e)}`)
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-[560px] max-w-[92vw] max-h-[90vh] flex flex-col">
        <div className="shrink-0 px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-[14px] font-semibold text-gray-800">新建技能</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-lg">
            ×
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          <Field label="名称（小写字母/数字/下划线/短横线，2-64 字符）">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_skill"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-gray-400"
            />
          </Field>
          <Field label="描述">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="一句话说明这个技能的用途..."
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-gray-400 resize-none"
            />
          </Field>
          <Field label="作者（可选）">
            <input
              type="text"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="user"
              className="w-full px-3 py-1.5 text-[13px] border border-gray-200 rounded-lg outline-none focus:border-gray-400"
            />
          </Field>
          <Field label="SKILL.md 正文">
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={10}
              className="w-full px-3 py-2 text-[12px] font-mono border border-gray-200 rounded-lg outline-none focus:border-gray-400 resize-y"
            />
          </Field>
          {error && <div className="text-[12px] text-red-600">{error}</div>}
        </div>
        <div className="shrink-0 px-5 py-3 border-t border-gray-200 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-[12.5px] text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-4 py-1.5 rounded-lg bg-gray-900 text-white text-[12.5px] hover:bg-gray-800 disabled:bg-gray-400"
          >
            {submitting ? '创建中...' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11.5px] text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  )
}
