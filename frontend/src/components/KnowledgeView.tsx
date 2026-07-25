/**
 * KnowledgeView —— 知识库主视图（P0）
 *
 * 天蓝规范，与「资料库」（只读任务成果）区分。功能：
 * - 知识库列表（个人 / 组织分组）+ 建库 / 删库
 * - 进入库 → 文档列表 + 状态徽标（待处理/处理中/就绪/失败）+ 上传（拖拽/选择）
 * - 文档详情：分块预览
 * - 调试检索：命中片段以 [n] 引用角标呈现
 *
 * 文档处理为后台异步，前端轮询 status 直至 ready/failed。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createBase,
  deleteBase,
  deleteDocument,
  getDocument,
  listBases,
  listDocuments,
  searchKnowledge,
  uploadDocument,
  type Citation,
  type DocStatus,
  type DocumentChunk,
  type KnowledgeBase,
  type KnowledgeDocument,
} from '../api/knowledge'
import { CitationBadge } from './CitationBadge'

const ACCEPTED_EXTS = '.pdf,.docx,.md,.markdown,.txt,.text'

// ─── Status badge ─────────────────────────────────────────────────────────

const STATUS_META: Record<DocStatus, { label: string; cls: string }> = {
  pending: { label: '待处理', cls: 'bg-gray-100 text-gray-500' },
  processing: { label: '处理中', cls: 'bg-sky-50 text-sky-600' },
  ready: { label: '就绪', cls: 'bg-emerald-50 text-emerald-600' },
  failed: { label: '失败', cls: 'bg-rose-50 text-rose-600' },
}

function StatusBadge({ status }: { status: DocStatus }) {
  const meta = STATUS_META[status] || STATUS_META.pending
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${meta.cls}`}>
      {status === 'processing' && (
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 mr-1 animate-pulse" />
      )}
      {meta.label}
    </span>
  )
}

function formatSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ─── Main component ─────────────────────────────────────────────────────────

export function KnowledgeView({
  authToken,
  isAdmin = false,
}: {
  authToken: string | null
  isAdmin?: boolean
}) {
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<KnowledgeBase | null>(null)

  const refreshBases = useCallback(async () => {
    if (!authToken) return
    setLoading(true)
    setError('')
    try {
      setBases(await listBases())
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [authToken])

  useEffect(() => { refreshBases() }, [refreshBases])

  if (selected) {
    return (
      <BaseDetail
        base={selected}
        isAdmin={isAdmin}
        onBack={() => { setSelected(null); refreshBases() }}
      />
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="shrink-0 px-5 sm:px-8 pt-5 pb-4">
        <h1 className="text-[20px] font-semibold text-gray-800 mb-1">知识库</h1>
        <p className="text-[13px] text-gray-400">
          上传文档构建专属知识库，AI 可在对话中检索并引用其中内容。
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-5 sm:px-8 pb-6">
        <BaseList
          bases={bases}
          loading={loading}
          error={error}
          isAdmin={isAdmin}
          onOpen={setSelected}
          onCreated={refreshBases}
          onDeleted={refreshBases}
        />
      </div>
    </div>
  )
}

// ─── Base list ────────────────────────────────────────────────────────────

function BaseList({
  bases,
  loading,
  error,
  isAdmin,
  onOpen,
  onCreated,
  onDeleted,
}: {
  bases: KnowledgeBase[]
  loading: boolean
  error: string
  isAdmin: boolean
  onOpen: (b: KnowledgeBase) => void
  onCreated: () => void
  onDeleted: () => void
}) {
  const [showCreate, setShowCreate] = useState(false)

  const personal = useMemo(() => bases.filter(b => b.scope === 'personal'), [bases])
  const org = useMemo(() => bases.filter(b => b.scope === 'org'), [bases])

  const handleDelete = async (b: KnowledgeBase) => {
    if (!window.confirm(`确定删除知识库「${b.name}」？其中所有文档与索引将一并删除。`)) return
    try {
      await deleteBase(b.id)
      onDeleted()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : '删除失败')
    }
  }

  return (
    <div className="pt-2">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[13px] text-gray-400">
          {loading ? '加载中…' : `共 ${bases.length} 个知识库`}
        </span>
        <button
          onClick={() => setShowCreate(true)}
          className="h-9 px-4 rounded-lg bg-sky-500 text-white text-[13px] font-medium
            hover:bg-sky-600 transition-colors"
        >
          + 新建知识库
        </button>
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-rose-50 text-rose-600 text-[13px]">{error}</div>
      )}

      {!loading && bases.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-sky-50 flex items-center justify-center text-sky-400 mb-4 text-2xl">
            📚
          </div>
          <h3 className="text-[15px] font-medium text-gray-700 mb-1.5">还没有知识库</h3>
          <p className="text-[13px] text-gray-400 max-w-sm">
            新建一个知识库并上传文档，AI 就能在对话中引用你的专属资料。
          </p>
        </div>
      )}

      {personal.length > 0 && (
        <BaseGroup title="个人" bases={personal} onOpen={onOpen} onDelete={handleDelete} />
      )}
      {org.length > 0 && (
        <BaseGroup title="组织" bases={org} onOpen={onOpen} onDelete={handleDelete} />
      )}

      {showCreate && (
        <CreateBaseModal
          isAdmin={isAdmin}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); onCreated() }}
        />
      )}
    </div>
  )
}

function BaseGroup({
  title,
  bases,
  onOpen,
  onDelete,
}: {
  title: string
  bases: KnowledgeBase[]
  onOpen: (b: KnowledgeBase) => void
  onDelete: (b: KnowledgeBase) => void
}) {
  return (
    <div className="mb-6">
      <h2 className="text-[12px] font-medium text-gray-400 mb-2 uppercase tracking-wide">{title}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {bases.map(b => (
          <div
            key={b.id}
            className="group relative bg-white rounded-xl border border-gray-200 p-4
              hover:border-sky-300 hover:shadow-sm transition-all cursor-pointer"
            onClick={() => onOpen(b)}
          >
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-sky-50 flex items-center justify-center text-sky-500 shrink-0">
                📘
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[14px] font-semibold text-gray-800 truncate">{b.name}</div>
                <div className="text-[12px] text-gray-400 mt-0.5">
                  {b.document_count ?? 0} 个文档
                </div>
              </div>
            </div>
            {b.description && (
              <p className="text-[12px] text-gray-500 mt-2 line-clamp-2">{b.description}</p>
            )}
            <button
              onClick={e => { e.stopPropagation(); onDelete(b) }}
              className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity
                text-gray-300 hover:text-rose-500 text-[12px]"
              title="删除知识库"
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function CreateBaseModal({
  isAdmin,
  onClose,
  onCreated,
}: {
  isAdmin: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'personal' | 'org'>('personal')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!name.trim()) { setErr('请填写名称'); return }
    setSubmitting(true)
    setErr('')
    try {
      await createBase({ name: name.trim(), scope, description: description.trim() })
      onCreated()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="w-[92%] max-w-md bg-white rounded-2xl p-5 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-[16px] font-semibold text-gray-800 mb-4">新建知识库</h3>
        <label className="block text-[13px] text-gray-600 mb-1">名称</label>
        <input
          autoFocus
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="如：产品文档、研究资料…"
          className="w-full h-9 px-3 mb-3 rounded-lg border border-gray-200 text-[13px] outline-none focus:border-sky-400"
        />
        <label className="block text-[13px] text-gray-600 mb-1">归属</label>
        <div className="flex gap-2 mb-3">
          <button
            onClick={() => setScope('personal')}
            className={`flex-1 h-9 rounded-lg text-[13px] border transition-colors ${
              scope === 'personal' ? 'border-sky-400 bg-sky-50 text-sky-600' : 'border-gray-200 text-gray-600'
            }`}
          >
            个人
          </button>
          <button
            onClick={() => isAdmin && setScope('org')}
            disabled={!isAdmin}
            title={isAdmin ? '' : '仅管理员可创建组织知识库'}
            className={`flex-1 h-9 rounded-lg text-[13px] border transition-colors ${
              scope === 'org' ? 'border-sky-400 bg-sky-50 text-sky-600' : 'border-gray-200 text-gray-600'
            } ${!isAdmin ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            组织
          </button>
        </div>
        <label className="block text-[13px] text-gray-600 mb-1">描述（可选）</label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 mb-3 rounded-lg border border-gray-200 text-[13px] outline-none focus:border-sky-400 resize-none"
        />
        {err && <div className="text-[12px] text-rose-500 mb-3">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="h-9 px-4 rounded-lg text-[13px] text-gray-600 hover:bg-gray-100">
            取消
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="h-9 px-4 rounded-lg bg-sky-500 text-white text-[13px] font-medium hover:bg-sky-600 disabled:opacity-50"
          >
            {submitting ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Base detail (documents) ────────────────────────────────────────────────

function BaseDetail({
  base,
  isAdmin,
  onBack,
}: {
  base: KnowledgeBase
  isAdmin: boolean
  onBack: () => void
}) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState('')
  const [detailDoc, setDetailDoc] = useState<KnowledgeDocument | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const canWrite = base.scope === 'personal' || isAdmin

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments(base.id))
    } catch {
      /* keep previous */
    } finally {
      setLoading(false)
    }
  }, [base.id])

  useEffect(() => { refresh() }, [refresh])

  // Poll while any document is still being processed.
  const hasPending = docs.some(d => d.status === 'pending' || d.status === 'processing')
  useEffect(() => {
    if (!hasPending) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [hasPending, refresh])

  const doUpload = async (files: FileList | File[]) => {
    setUploading(true)
    setNotice('')
    try {
      for (const file of Array.from(files)) {
        await uploadDocument(base.id, file)
      }
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDoc = async (doc: KnowledgeDocument) => {
    if (!window.confirm(`删除文档「${doc.title}」？`)) return
    try {
      await deleteDocument(doc.id)
      await refresh()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : '删除失败')
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="shrink-0 px-5 sm:px-8 pt-5 pb-4">
        <button onClick={onBack} className="text-[13px] text-gray-400 hover:text-gray-600 mb-2">
          ← 返回知识库列表
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[20px] font-semibold text-gray-800">{base.name}</h1>
            <p className="text-[13px] text-gray-400 mt-0.5">
              {base.scope === 'org' ? '组织知识库' : '个人知识库'} · {docs.length} 个文档
            </p>
          </div>
          {canWrite && (
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="h-9 px-4 rounded-lg bg-sky-500 text-white text-[13px] font-medium hover:bg-sky-600 disabled:opacity-50"
            >
              {uploading ? '上传中…' : '上传文档'}
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 sm:px-8 pb-6">
        <SearchPanel kbId={base.id} onOpenDocument={(id) => {
          const d = docs.find(x => x.id === id)
          if (d) setDetailDoc(d)
        }} />

        {canWrite && (
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => {
              e.preventDefault()
              setDragOver(false)
              if (e.dataTransfer.files.length) doUpload(e.dataTransfer.files)
            }}
            onClick={() => fileInputRef.current?.click()}
            className={`mb-4 rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
              dragOver ? 'border-sky-400 bg-sky-50' : 'border-gray-200 hover:border-sky-300'
            }`}
          >
            <div className="text-[13px] text-gray-500">
              拖拽文件到此处，或点击选择上传
            </div>
            <div className="text-[12px] text-gray-400 mt-1">
              支持 PDF / Word / Markdown / 文本，单文件 ≤ 32MB
            </div>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTS}
          multiple
          className="hidden"
          onChange={e => { if (e.target.files?.length) doUpload(e.target.files); e.target.value = '' }}
        />

        {notice && <div className="mb-3 px-3 py-2 rounded-lg bg-rose-50 text-rose-600 text-[13px]">{notice}</div>}

        {loading ? (
          <div className="text-[13px] text-gray-400 py-8 text-center">加载文档中…</div>
        ) : docs.length === 0 ? (
          <div className="text-[13px] text-gray-400 py-8 text-center">还没有文档，上传第一份资料吧。</div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {docs.map((doc, idx) => (
              <DocRow
                key={doc.id}
                doc={doc}
                showBorder={idx > 0}
                canWrite={canWrite}
                onOpen={() => setDetailDoc(doc)}
                onDelete={() => handleDeleteDoc(doc)}
                onRetry={() => fileInputRef.current?.click()}
              />
            ))}
          </div>
        )}
      </div>

      {detailDoc && (
        <DocDetailModal doc={detailDoc} onClose={() => setDetailDoc(null)} />
      )}
    </div>
  )
}

function DocRow({
  doc,
  showBorder,
  canWrite,
  onOpen,
  onDelete,
}: {
  doc: KnowledgeDocument
  showBorder: boolean
  canWrite: boolean
  onOpen: () => void
  onDelete: () => void
  onRetry: () => void
}) {
  return (
    <div className={`group flex items-center gap-3 px-4 py-3 hover:bg-sky-50/40 transition-colors ${showBorder ? 'border-t border-gray-50' : ''}`}>
      <div className="w-8 h-8 rounded-lg bg-gray-50 flex items-center justify-center text-[13px] shrink-0">📄</div>
      <button onClick={onOpen} className="flex-1 min-w-0 text-left">
        <div className="text-[13px] text-gray-800 truncate hover:text-sky-600">{doc.title}</div>
        <div className="text-[12px] text-gray-400 mt-0.5">
          {formatSize(doc.byte_size)}
          {doc.status === 'ready' && ` · ${doc.chunk_count} 块`}
          {doc.status === 'failed' && doc.error_msg && (
            <span className="text-rose-400" title={doc.error_msg}> · {doc.error_msg.slice(0, 40)}</span>
          )}
        </div>
      </button>
      <StatusBadge status={doc.status} />
      {canWrite && (
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-300 hover:text-rose-500 text-[12px] shrink-0"
        >
          删除
        </button>
      )}
    </div>
  )
}

function DocDetailModal({ doc, onClose }: { doc: KnowledgeDocument; onClose: () => void }) {
  const [chunks, setChunks] = useState<DocumentChunk[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    getDocument(doc.id, { limit: 100 })
      .then(res => { if (alive) setChunks(res.chunks) })
      .catch(() => { /* ignore */ })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [doc.id])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-[92%] max-w-2xl max-h-[80vh] bg-white rounded-2xl p-5 shadow-xl flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="text-[16px] font-semibold text-gray-800 truncate">{doc.title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-[18px] leading-none">×</button>
        </div>
        <div className="flex items-center gap-2 mb-3 shrink-0">
          <StatusBadge status={doc.status} />
          <span className="text-[12px] text-gray-400">{chunks.length} 个分块</span>
        </div>
        <div className="flex-1 overflow-y-auto space-y-2">
          {loading ? (
            <div className="text-[13px] text-gray-400 py-6 text-center">加载分块中…</div>
          ) : chunks.length === 0 ? (
            <div className="text-[13px] text-gray-400 py-6 text-center">暂无分块（可能仍在处理或解析失败）。</div>
          ) : (
            chunks.map(c => (
              <div key={c.id} className="rounded-lg border border-gray-100 p-3">
                <div className="text-[11px] text-gray-400 mb-1">
                  #{c.chunk_index} {c.locator && `· ${c.locator}`} · {c.token_count} tokens
                </div>
                <div className="text-[12.5px] text-gray-700 leading-relaxed whitespace-pre-wrap">{c.content}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Debug search panel ─────────────────────────────────────────────────────

function SearchPanel({
  kbId,
  onOpenDocument,
}: {
  kbId: string
  onOpenDocument: (documentId: string) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Citation[] | null>(null)
  const [searching, setSearching] = useState(false)

  const run = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      setResults(await searchKnowledge({ query: query.trim(), kb_id: kbId }))
    } catch {
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-gray-200 bg-white p-3">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') run() }}
          placeholder="试检索：输入问题，验证知识库命中效果…"
          className="flex-1 h-9 px-3 rounded-lg border border-gray-200 text-[13px] outline-none focus:border-sky-400"
        />
        <button
          onClick={run}
          disabled={searching}
          className="h-9 px-4 rounded-lg bg-sky-500 text-white text-[13px] font-medium hover:bg-sky-600 disabled:opacity-50"
        >
          {searching ? '检索中…' : '检索'}
        </button>
      </div>
      {results && (
        <div className="mt-3">
          {results.length === 0 ? (
            <div className="text-[13px] text-gray-400">未检索到相关内容。</div>
          ) : (
            <div className="space-y-2">
              {results.map(c => (
                <div key={c.n} className="flex items-start gap-2 text-[12.5px] text-gray-700">
                  <CitationBadge citation={c} onOpenDocument={onOpenDocument} />
                  <span className="flex-1">
                    <span className="font-medium text-gray-800">{c.title}</span>
                    {c.locator && <span className="text-gray-400"> · {c.locator}</span>}
                    <span className="block text-gray-500 mt-0.5 line-clamp-2">{c.snippet}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

