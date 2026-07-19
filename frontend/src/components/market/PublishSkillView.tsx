/**
 * PublishSkillView —— 发布技能三步向导
 *
 * Step 1: 基本信息（名称、描述、分类、标签、许可证、版本、仓库）
 * Step 2: 技能内容（ZIP 上传 + 截图）
 * Step 3: 预览 + 提交
 */
import { useState, useRef, type DragEvent, type ChangeEvent } from 'react'
import type { Category } from '../MarketplaceView'

// ─── Types ──────────────────────────────────────────────────────────────
export interface PublishSkillViewProps {
  authToken: string
  categories: Category[]
  onPublish: (formData: FormData) => void
  onSuccess: () => void
  onCancel: () => void
  loading?: boolean
}

interface FormState {
  name: string
  description: string
  category: string
  tags: string[]
  license: string
  version: string
  repo: string
  zipFile: File | null
  screenshots: File[]
}

const NAME_RE = /^[a-z][a-z0-9_-]{0,63}$/
const MAX_ZIP_BYTES = 10 * 1024 * 1024 // 10 MB
const MAX_SCREENSHOTS = 5
const LICENSES = ['MIT', 'Apache-2.0', 'GPL-3.0', '自定义']

const STEPS = [
  { id: 1, label: '基本信息' },
  { id: 2, label: '技能内容' },
  { id: 3, label: '预览提交' },
]

const initForm: FormState = {
  name: '',
  description: '',
  category: '',
  tags: [],
  license: 'MIT',
  version: '1.0.0',
  repo: '',
  zipFile: null,
  screenshots: [],
}

// ─── Component ──────────────────────────────────────────────────────────
export default function PublishSkillView({
  categories,
  onPublish,
  onSuccess,
  onCancel,
  loading = false,
}: PublishSkillViewProps) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState<FormState>(initForm)
  const [tagInput, setTagInput] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dragOver, setDragOver] = useState(false)
  const zipRef = useRef<HTMLInputElement>(null)
  const shotRef = useRef<HTMLInputElement>(null)

  // ── helpers ──
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm(prev => ({ ...prev, [k]: v }))

  const validateStep1 = (): boolean => {
    const e: Record<string, string> = {}
    if (!NAME_RE.test(form.name)) e.name = '名称须为 kebab-case，如 my-skill（小写字母开头，1-64 字符）'
    if (!form.description.trim() || form.description.length > 200)
      e.description = '描述为必填项，1-200 字'
    if (!form.category) e.category = '请选择分类'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const validateStep2 = (): boolean => {
    const e: Record<string, string> = {}
    if (!form.zipFile) e.zipFile = '请上传技能 ZIP 包'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const goNext = () => {
    if (step === 1 && !validateStep1()) return
    if (step === 2 && !validateStep2()) return
    setStep(s => Math.min(s + 1, 3))
  }

  const goPrev = () => setStep(s => Math.max(s - 1, 1))

  const handleSubmit = () => {
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('description', form.description)
    fd.append('category', form.category)
    fd.append('tags', JSON.stringify(form.tags))
    fd.append('license', form.license)
    fd.append('version', form.version)
    if (form.repo) fd.append('repo', form.repo)
    if (form.zipFile) fd.append('zip', form.zipFile)
    form.screenshots.forEach(f => fd.append('screenshots', f))
    onPublish(fd)
  }

  // ── tag handling ──
  const addTag = () => {
    const t = tagInput.trim()
    if (t && form.tags.length < 5 && !form.tags.includes(t)) {
      set('tags', [...form.tags, t])
      setTagInput('')
    }
  }

  const removeTag = (t: string) => set('tags', form.tags.filter(x => x !== t))

  // ── file handling ──
  const handleZipDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.size <= MAX_ZIP_BYTES) set('zipFile', f)
    else setErrors(prev => ({ ...prev, zipFile: '文件超过 10MB 限制' }))
  }

  const handleZipChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f && f.size <= MAX_ZIP_BYTES) set('zipFile', f)
    else setErrors(prev => ({ ...prev, zipFile: '文件超过 10MB 限制' }))
  }

  const handleShotChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    const remaining = MAX_SCREENSHOTS - form.screenshots.length
    set('screenshots', [...form.screenshots, ...files.slice(0, remaining)])
  }

  const formatSize = (n: number) =>
    n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024).toFixed(0)} KB`

  // ── step indicator ──
  const StepIndicator = () => (
    <div className="flex items-center gap-2 mt-6">
      {STEPS.map(({ id, label }, i) => (
        <div key={id} className="flex items-center gap-2 flex-1">
          <div
            className="flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium shrink-0"
            style={{
              background:
                id < step ? 'var(--success-500, #22c55e)' :
                id === step ? 'var(--primary-500, #3b82f6)' : 'var(--gray-200, #e5e7eb)',
              color: id <= step ? '#fff' : 'var(--text-secondary, #6b7280)',
            }}
          >
            {id < step ? '✓' : id}
          </div>
          <span
            className="text-xs truncate"
            style={{ color: id === step ? 'var(--text-primary, #111827)' : 'var(--text-secondary, #6b7280)' }}
          >
            {label}
          </span>
          {i < STEPS.length - 1 && (
            <div className="flex-1 h-px mx-1" style={{ background: 'var(--border-light, #e5e7eb)' }} />
          )}
        </div>
      ))}
    </div>
  )

  // ── Step 1: 基本信息 ──
  const renderStep1 = () => (
    <div className="space-y-4">
      {/* 名称 */}
      <Field label="技能名称" required error={errors.name}>
        <input
          className="input-base"
          placeholder="my-skill-name"
          value={form.name}
          onChange={e => set('name', e.target.value)}
        />
      </Field>
      {/* 描述 */}
      <Field label="描述" required error={errors.description}>
        <textarea
          className="input-base min-h-[80px] resize-y"
          placeholder="简要描述你的技能（1-200 字）"
          maxLength={200}
          value={form.description}
          onChange={e => set('description', e.target.value)}
        />
        <span className="text-xs text-right block" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
          {form.description.length}/200
        </span>
      </Field>
      {/* 分类 */}
      <Field label="分类" required error={errors.category}>
        <select
          className="input-base"
          value={form.category}
          onChange={e => set('category', e.target.value)}
        >
          <option value="">请选择分类</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
          ))}
        </select>
      </Field>
      {/* 标签 */}
      <Field label={`标签（最多 5 个，回车添加）`}>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {form.tags.map(t => (
            <span
              key={t}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium cursor-pointer"
              style={{ background: 'var(--primary-100, #dbeafe)', color: 'var(--primary-700, #1d4ed8)' }}
              onClick={() => removeTag(t)}
            >
              {t} ×
            </span>
          ))}
        </div>
        {form.tags.length < 5 && (
          <input
            className="input-base"
            placeholder="输入标签后按回车"
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
          />
        )}
      </Field>
      {/* 许可证 + 版本 */}
      <div className="grid grid-cols-2 gap-4">
        <Field label="许可证">
          <select className="input-base" value={form.license} onChange={e => set('license', e.target.value)}>
            {LICENSES.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </Field>
        <Field label="版本号">
          <input
            className="input-base"
            value={form.version}
            onChange={e => set('version', e.target.value)}
          />
        </Field>
      </div>
      {/* 仓库 */}
      <Field label="仓库地址（可选）">
        <input
          className="input-base"
          placeholder="https://github.com/..."
          value={form.repo}
          onChange={e => set('repo', e.target.value)}
        />
      </Field>
    </div>
  )

  // ── Step 2: 技能内容 ──
  const renderStep2 = () => (
    <div className="space-y-5">
      {/* ZIP 上传 */}
      <Field label="技能 ZIP 包" required error={errors.zipFile}>
        {form.zipFile ? (
          <div
            className="flex items-center gap-3 p-3 rounded-lg border"
            style={{ borderColor: 'var(--border-light, #e5e7eb)', background: 'var(--gray-50, #f9fafb)' }}
          >
            <span className="text-lg">📦</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate" style={{ color: 'var(--text-primary, #111827)' }}>
                {form.zipFile.name}
              </p>
              <p className="text-xs" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
                {formatSize(form.zipFile.size)}
              </p>
            </div>
            <button
              className="text-xs px-2 py-1 rounded border"
              style={{ borderColor: 'var(--border-light, #e5e7eb)', color: 'var(--text-secondary, #6b7280)' }}
              onClick={() => { set('zipFile', null); if (zipRef.current) zipRef.current.value = '' }}
            >
              移除
            </button>
          </div>
        ) : (
          <div
            className={`flex flex-col items-center justify-center p-8 rounded-lg border-2 border-dashed cursor-pointer transition-colors ${dragOver ? 'border-blue-400 bg-blue-50' : ''}`}
            style={{ borderColor: dragOver ? undefined : 'var(--border-light, #e5e7eb)' }}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleZipDrop}
            onClick={() => zipRef.current?.click()}
          >
            <span className="text-3xl mb-2">📁</span>
            <p className="text-sm font-medium" style={{ color: 'var(--text-primary, #111827)' }}>
              拖拽 ZIP 文件到这里，或点击上传
            </p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
              最大 10MB
            </p>
          </div>
        )}
        <input
          ref={zipRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={handleZipChange}
        />
      </Field>

      {/* 截图 */}
      <Field label={`截图（可选，最多 ${MAX_SCREENSHOTS} 张）`}>
        <div className="flex flex-wrap gap-2">
          {form.screenshots.map((f, i) => (
            <div
              key={i}
              className="relative w-20 h-20 rounded-lg border overflow-hidden"
              style={{ borderColor: 'var(--border-light, #e5e7eb)' }}
            >
              <img src={URL.createObjectURL(f)} alt="" className="w-full h-full object-cover" />
              <button
                className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/50 text-white text-xs flex items-center justify-center"
                onClick={() => set('screenshots', form.screenshots.filter((_, j) => j !== i))}
              >×</button>
            </div>
          ))}
          {form.screenshots.length < MAX_SCREENSHOTS && (
            <button
              className="w-20 h-20 rounded-lg border-2 border-dashed flex flex-col items-center justify-center text-xs"
              style={{ borderColor: 'var(--border-light, #e5e7eb)', color: 'var(--text-tertiary, #9ca3af)' }}
              onClick={() => shotRef.current?.click()}
            >
              <span className="text-xl">+</span>
              添加
            </button>
          )}
        </div>
        <input
          ref={shotRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={handleShotChange}
        />
      </Field>
    </div>
  )

  // ── Step 3: 预览 + 提交 ──
  const renderStep3 = () => (
    <div className="space-y-4">
      <div
        className="rounded-xl border p-5 space-y-3"
        style={{ borderColor: 'var(--border-light, #e5e7eb)', background: 'var(--gray-50, #f9fafb)' }}
      >
        <h3 className="text-base font-semibold" style={{ color: 'var(--text-primary, #111827)' }}>
          {form.name}
          <span className="ml-2 text-xs font-normal" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
            v{form.version}
          </span>
        </h3>
        <p className="text-sm" style={{ color: 'var(--text-secondary, #374151)' }}>{form.description}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          <InfoPill label="分类" value={categories.find(c => c.id === form.category)?.name ?? form.category} />
          <InfoPill label="许可证" value={form.license} />
          {form.tags.map(t => (
            <span key={t} className="px-2 py-0.5 rounded-full" style={{ background: 'var(--primary-100, #dbeafe)', color: 'var(--primary-700, #1d4ed8)' }}>
              {t}
            </span>
          ))}
        </div>
        {form.repo && (
          <p className="text-xs" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
            仓库：<a href={form.repo} target="_blank" rel="noreferrer" className="underline text-blue-500">{form.repo}</a>
          </p>
        )}
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
          <span>📦 {form.zipFile?.name ?? '未上传'} ({form.zipFile ? formatSize(form.zipFile.size) : '-'})</span>
          <span>🖼 {form.screenshots.length} 张截图</span>
        </div>
      </div>

      <div
        className="p-3 rounded-lg text-xs"
        style={{ background: 'var(--info-50, #eff6ff)', color: 'var(--info-700, #1d4ed8)', border: '1px solid var(--info-200, #bfdbfe)' }}
      >
        ℹ️ 提交后将在 1-3 个工作日内完成审核
      </div>
    </div>
  )

  // ── Main render ──
  return (
    <div className="flex flex-col h-full bg-white rounded-xl border" style={{ borderColor: 'var(--border-light, #e5e7eb)' }}>
      {/* Header */}
      <div className="px-6 pt-5 pb-3 border-b" style={{ borderColor: 'var(--border-light, #e5e7eb)' }}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary, #111827)' }}>
            发布技能
          </h2>
          <button
            onClick={onCancel}
            className="text-sm px-3 py-1 rounded border"
            style={{ borderColor: 'var(--border-light, #e5e7eb)', color: 'var(--text-secondary, #6b7280)' }}
          >
            取消
          </button>
        </div>
        <StepIndicator />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {step === 1 && renderStep1()}
        {step === 2 && renderStep2()}
        {step === 3 && renderStep3()}
      </div>

      {/* Footer nav */}
      <div
        className="px-6 py-4 border-t flex items-center justify-between"
        style={{ borderColor: 'var(--border-light, #e5e7eb)' }}
      >
        <button
          className="btn-secondary"
          disabled={step === 1}
          onClick={goPrev}
        >
          上一步
        </button>
        <div className="text-xs" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
          步骤 {step} / {STEPS.length}
        </div>
        {step < 3 ? (
          <button className="btn-primary" onClick={goNext}>
            下一步
          </button>
        ) : (
          <button
            className="btn-primary"
            disabled={loading}
            onClick={handleSubmit}
          >
            {loading ? '提交中...' : '提交审核'}
          </button>
        )}
      </div>

      {/* Global styles for form controls */}
      <style>{`
        .input-base {
          width: 100%;
          padding: 8px 12px;
          font-size: 13px;
          border: 1px solid var(--border-light, #e5e7eb);
          border-radius: 8px;
          outline: none;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #111827);
          transition: border-color 0.15s;
        }
        .input-base:focus {
          border-color: var(--primary-400, #60a5fa);
          box-shadow: 0 0 0 2px var(--primary-100, #dbeafe);
        }
        .btn-primary {
          padding: 7px 20px;
          font-size: 13px;
          font-weight: 500;
          border-radius: 8px;
          background: var(--primary-500, #3b82f6);
          color: #fff;
          border: none;
          cursor: pointer;
          transition: background 0.15s;
        }
        .btn-primary:hover:not(:disabled) { background: var(--primary-600, #2563eb); }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-secondary {
          padding: 7px 20px;
          font-size: 13px;
          border-radius: 8px;
          background: var(--bg-primary, #fff);
          color: var(--text-secondary, #374151);
          border: 1px solid var(--border-light, #e5e7eb);
          cursor: pointer;
          transition: background 0.15s;
        }
        .btn-secondary:hover:not(:disabled) { background: var(--gray-50, #f9fafb); }
        .btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }
      `}</style>
    </div>
  )
}

// ─── Small helpers ──────────────────────────────────────────────────────
function Field({
  label,
  required,
  error,
  children,
}: {
  label: string
  required?: boolean
  error?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium mb-1 block" style={{ color: 'var(--text-secondary, #374151)' }}>
        {label}
        {required && <span className="ml-0.5 text-rose-500">*</span>}
      </span>
      {children}
      {error && (
        <span className="text-xs mt-0.5 block" style={{ color: 'var(--danger-500, #ef4444)' }}>
          {error}
        </span>
      )}
    </label>
  )
}

function InfoPill({ label, value }: { label: string; value: string }) {
  return (
    <span
      className="px-2 py-0.5 rounded-full"
      style={{ background: 'var(--gray-100, #f3f4f6)', color: 'var(--text-secondary, #374151)' }}
    >
      {label}: {value}
    </span>
  )
}
