import { useState, useCallback, useEffect } from 'react'

// ── Icons ──────────────────────────────────────────────────────────

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
)

const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
)

const RefreshIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
  </svg>
)

const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
  </svg>
)

const TestIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
  </svg>
)

const DownloadIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
  </svg>
)

const ShieldIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
  </svg>
)

// ── Types ──────────────────────────────────────────────────────────

interface Channel {
  name: string
  base_url: string
  provider: string
  models: string[]
  default_model: string
  timeout: number
  enabled: boolean
  created_at: string
  last_test_at: string
  last_test_ok: boolean | null
  consecutive_failures: number
  api_key_preview: string
}

interface ModelConfigViewProps {
  authToken: string
}

const API = '/api/frontend/channels'

// ── Main Component ─────────────────────────────────────────────────

export function ModelConfigView({ authToken }: ModelConfigViewProps) {
  const [channels, setChannels] = useState<Channel[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [testingChannel, setTestingChannel] = useState<string | null>(null)
  const [fetchingModels, setFetchingModels] = useState<string | null>(null)

  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${authToken}`,
  }

  const fetchChannels = useCallback(async () => {
    try {
      const res = await fetch(API, { headers })
      if (res.ok) {
        const data = await res.json()
        setChannels(data.channels || [])
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [authToken]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchChannels() }, [fetchChannels])

  const toggleChannel = useCallback(async (name: string, enabled: boolean) => {
    await fetch(`${API}/${name}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ enabled: !enabled }),
    })
    fetchChannels()
  }, [authToken, fetchChannels]) // eslint-disable-line react-hooks/exhaustive-deps

  const deleteChannel = useCallback(async (name: string) => {
    if (!confirm(`确定删除渠道「${name}」吗？`)) return
    await fetch(`${API}/${name}`, { method: 'DELETE', headers })
    fetchChannels()
  }, [authToken, fetchChannels]) // eslint-disable-line react-hooks/exhaustive-deps

  const testChannel = useCallback(async (name: string) => {
    setTestingChannel(name)
    try {
      const res = await fetch(`${API}/${name}/test`, { method: 'POST', headers })
      const data = await res.json()
      if (data.ok) {
        alert(`✅ ${name} 连通成功 (${data.latency_ms}ms)`)
      } else {
        alert(`❌ ${name} 测试失败: ${data.error}`)
      }
    } catch {
      alert('网络错误')
    } finally {
      setTestingChannel(null)
      fetchChannels()
    }
  }, [authToken, fetchChannels]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchModels = useCallback(async (name: string) => {
    setFetchingModels(name)
    try {
      const res = await fetch(`${API}/${name}/fetch-models`, { method: 'POST', headers })
      const data = await res.json()
      if (data.models?.length) {
        alert(`已获取 ${data.models.length} 个模型`)
      } else {
        alert('未获取到模型列表')
      }
    } catch {
      alert('网络错误')
    } finally {
      setFetchingModels(null)
      fetchChannels()
    }
  }, [authToken, fetchChannels]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleChannelCreated = useCallback(() => {
    setShowAddDialog(false)
    fetchChannels()
  }, [fetchChannels])

  // Collect all models across channels
  const allModels = channels.flatMap((ch) =>
    ch.models.map((m) => ({
      model: m,
      channel: ch.name,
      enabled: ch.enabled,
      lastTestOk: ch.last_test_ok,
    }))
  )

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-2 text-gray-400 text-[13px]">
          <span className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-gray-600 animate-spin" />
          加载中...
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--bg-primary)] p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-[20px] font-semibold t-text-primary">模型配置</h1>
          <p className="text-[13px] t-text-secondary mt-1 max-w-lg">
            管理 AI 供应商连接，配置 API Key 和可用模型。
          </p>
        </div>
        <button
          onClick={() => setShowAddDialog(true)}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 transition-colors dark:bg-[var(--accent)] dark:hover:opacity-90"
        >
          <PlusIcon />
          <span>添加配置</span>
        </button>
      </div>

      {/* Provider Cards */}
      <div className="space-y-3">
        {channels.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 p-12 text-center">
            <div className="text-gray-400 text-[14px] mb-3">暂无供应商配置</div>
            <button
              onClick={() => setShowAddDialog(true)}
              className="text-[13px] text-blue-600 hover:text-blue-700 font-medium"
            >
              添加第一个配置 →
            </button>
          </div>
        ) : (
          channels.map((ch) => (
            <ProviderCard
              key={ch.name}
              channel={ch}
              onToggle={() => toggleChannel(ch.name, ch.enabled)}
              onDelete={() => deleteChannel(ch.name)}
              onTest={() => testChannel(ch.name)}
              onFetchModels={() => fetchModels(ch.name)}
              testing={testingChannel === ch.name}
              fetchingModels={fetchingModels === ch.name}
            />
          ))
        )}
      </div>

      {/* Model Health Table */}
      {allModels.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[15px] font-medium t-text-primary">模型列表</h2>
            <span className="text-[12px] t-text-tertiary">{allModels.length} 个模型</span>
          </div>
          <div className="rounded-xl border t-border-primary overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="t-bg-tertiary border-b t-border-primary">
                  <th className="text-left px-4 py-2.5 font-medium t-text-secondary">模型</th>
                  <th className="text-left px-4 py-2.5 font-medium t-text-secondary">供应商</th>
                  <th className="text-left px-4 py-2.5 font-medium t-text-secondary">状态</th>
                </tr>
              </thead>
              <tbody>
                {allModels.map((m, i) => (
                  <tr key={`${m.channel}-${m.model}`} className={`border-b t-border-primary ${i % 2 === 0 ? '' : 't-bg-secondary'}`}>
                    <td className="px-4 py-2.5 font-medium t-text-primary">{m.model}</td>
                    <td className="px-4 py-2.5 t-text-secondary">{m.channel}</td>
                    <td className="px-4 py-2.5">
                      <ModelStatusBadge enabled={m.enabled} lastTestOk={m.lastTestOk} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Add Dialog */}
      {showAddDialog && (
        <AddChannelDialog
          authToken={authToken}
          onClose={() => setShowAddDialog(false)}
          onCreated={handleChannelCreated}
        />
      )}
    </div>
  )
}

// ── Provider Card ──────────────────────────────────────────────────

function ProviderCard({
  channel: ch,
  onToggle,
  onDelete,
  onTest,
  onFetchModels,
  testing,
  fetchingModels,
}: {
  channel: Channel
  onToggle: () => void
  onDelete: () => void
  onTest: () => void
  onFetchModels: () => void
  testing: boolean
  fetchingModels: boolean
}) {
  const providerLabel: Record<string, string> = {
    openai_compatible: 'OpenAI 兼容',
    anthropic: 'Anthropic',
    deepseek: 'DeepSeek',
  }

  return (
    <div className="rounded-xl border t-border-primary t-bg-secondary p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Provider logo placeholder */}
          <div className="w-10 h-10 rounded-xl bg-gray-900 flex items-center justify-center text-white text-xs font-bold shrink-0">
            {ch.name.charAt(0).toUpperCase()}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[15px] font-semibold t-text-primary">{ch.name}</span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300">
                {providerLabel[ch.provider] || ch.provider}
              </span>
            </div>
            <div className="text-[12px] t-text-tertiary mt-0.5">
              {ch.models.length} 个模型可用 · API Key: {ch.api_key_preview}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Action buttons */}
          <button
            onClick={onTest}
            disabled={testing}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-500 hover:bg-blue-50 transition-colors disabled:opacity-50"
            title="测试连通性"
          >
            {testing ? <span className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-blue-500 animate-spin" /> : <TestIcon />}
          </button>
          <button
            onClick={onFetchModels}
            disabled={fetchingModels}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-500 hover:bg-blue-50 transition-colors disabled:opacity-50"
            title="拉取模型列表"
          >
            {fetchingModels ? <span className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-blue-500 animate-spin" /> : <DownloadIcon />}
          </button>
          <button
            onClick={onDelete}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="删除"
          >
            <TrashIcon />
          </button>

          {/* Toggle */}
          <button
            onClick={onToggle}
            className={`relative w-10 h-5.5 rounded-full transition-colors ${ch.enabled ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'}`}
            title={ch.enabled ? '已启用' : '已禁用'}
          >
            <span className={`absolute top-0.5 w-4.5 h-4.5 rounded-full bg-white shadow transition-transform ${ch.enabled ? 'left-5' : 'left-0.5'}`}
              style={{ width: '18px', height: '18px', top: '2px', left: ch.enabled ? '20px' : '2px' }}
            />
          </button>
        </div>
      </div>

      {/* Health status row */}
      {ch.last_test_at && (
        <div className="mt-3 flex items-center gap-2 text-[12px]">
          <ShieldIcon />
          <span className={ch.last_test_ok ? 'text-emerald-600' : 'text-red-500'}>
            {ch.last_test_ok ? '连通正常' : '连接异常'}
          </span>
          <span className="t-text-tertiary">
            · 上次检测: {new Date(ch.last_test_at).toLocaleString('zh-CN')}
          </span>
          {ch.consecutive_failures > 0 && (
            <span className="text-red-500">· 连续失败 {ch.consecutive_failures} 次</span>
          )}
        </div>
      )}
    </div>
  )
}

// ── Model Status Badge ─────────────────────────────────────────────

function ModelStatusBadge({ enabled, lastTestOk }: { enabled: boolean; lastTestOk: boolean | null }) {
  if (!enabled) {
    return <span className="text-[12px] text-gray-400">已禁用</span>
  }
  if (lastTestOk === null) {
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-gray-400">
        <span className="w-2 h-2 rounded-full bg-gray-300" />
        未检测
      </span>
    )
  }
  if (lastTestOk) {
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-emerald-600">
        <span className="w-2 h-2 rounded-full bg-emerald-500" />
        正常
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-red-500">
      <span className="w-2 h-2 rounded-full bg-red-500" />
      异常
    </span>
  )
}

// ── Add Channel Dialog ─────────────────────────────────────────────

function AddChannelDialog({
  authToken,
  onClose,
  onCreated,
}: {
  authToken: string
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [provider, setProvider] = useState('openai_compatible')
  const [defaultModel, setDefaultModel] = useState('')
  const [timeout, setTimeout_] = useState(30)
  const [modelsInput, setModelsInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const providers = [
    { value: 'openai_compatible', label: 'OpenAI 兼容' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'deepseek', label: 'DeepSeek' },
  ]

  const handleSave = async () => {
    setError('')
    if (!name.trim()) {
      setError('请输入渠道名称')
      return
    }
    if (!baseUrl.trim()) {
      setError('请输入 API Base URL')
      return
    }
    setSaving(true)
    try {
      const models = modelsInput
        .split(/[,，\n]/)
        .map((s) => s.trim())
        .filter(Boolean)

      const res = await fetch(API, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          name: name.trim(),
          base_url: baseUrl.trim(),
          api_key: apiKey,
          provider,
          default_model: defaultModel.trim(),
          timeout,
          models,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error || '创建失败')
        return
      }
      onCreated()
    } catch {
      setError('网络错误')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[520px] max-h-[85vh] bg-white rounded-2xl shadow-2xl border border-gray-200/80 overflow-hidden flex flex-col dark:bg-[var(--bg-primary)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0 dark:border-gray-700">
          <h2 className="text-[16px] font-semibold t-text-primary">添加供应商配置</h2>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors dark:hover:bg-gray-700">
            <CloseIcon />
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <FormField label="渠道名称" hint="唯一标识，如 deepseek、openai">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="deepseek"
              className="form-input"
            />
          </FormField>

          <FormField label="协议类型">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="form-input"
            >
              {providers.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </FormField>

          <FormField label="API Base URL" hint="如 https://api.deepseek.com">
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.deepseek.com"
              className="form-input"
            />
          </FormField>

          <FormField label="API Key" hint="密钥将安全存储，仅用于调用 API">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="form-input"
            />
          </FormField>

          <FormField label="默认模型" hint="留空则自动选择">
            <input
              type="text"
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder="deepseek-chat"
              className="form-input"
            />
          </FormField>

          <FormField label="模型列表（可选）" hint="逗号分隔，留空可在添加后通过「拉取模型」自动获取">
            <textarea
              value={modelsInput}
              onChange={(e) => setModelsInput(e.target.value)}
              placeholder="deepseek-chat, deepseek-reasoner"
              rows={2}
              className="form-input resize-none"
            />
          </FormField>

          <FormField label="请求超时（秒）">
            <input
              type="number"
              value={timeout}
              onChange={(e) => setTimeout_(Number(e.target.value))}
              min={5}
              max={300}
              className="form-input w-24"
            />
          </FormField>

          {error && (
            <div className="px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-600 dark:bg-red-900/20 dark:border-red-800">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2 shrink-0 dark:border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 text-[13px] t-text-secondary hover:bg-gray-50 transition-colors dark:border-gray-600 dark:hover:bg-gray-700"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 rounded-lg bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors dark:bg-[var(--accent)] dark:hover:opacity-90"
          >
            {saving ? '保存中...' : '添加'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Form Field Helper ──────────────────────────────────────────────

function FormField({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[13px] font-medium t-text-primary mb-1">{label}</label>
      {children}
      {hint && <div className="text-[11px] t-text-tertiary mt-1">{hint}</div>}
    </div>
  )
}
