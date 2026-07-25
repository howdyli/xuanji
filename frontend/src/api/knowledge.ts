/**
 * 知识库 API 客户端
 *
 * 封装 /api/frontend/knowledge/* 的类型化调用，复用统一的 apiFetch
 * （鉴权 / 超时 / 错误分类）。上传走 multipart，单独使用 rawFetch。
 */

import { apiFetch, rawFetch } from './client'

export type KbScope = 'personal' | 'org'
export type DocStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface KnowledgeBase {
  id: string
  name: string
  scope: KbScope
  owner_key: string
  org_id: number | null
  description: string
  document_count?: number
  created_by: string
  created_at?: string
  updated_at?: string
}

export interface KnowledgeDocument {
  id: string
  kb_id: string
  title: string
  source_type: string
  source_uri: string
  mime: string
  byte_size: number
  status: DocStatus
  error_msg: string
  chunk_count: number
  created_by: string
  created_at?: string
  updated_at?: string
}

export interface DocumentChunk {
  id: string
  chunk_index: number
  content: string
  token_count: number
  locator: string
}

export interface Citation {
  n: number
  document_id: string
  chunk_index: number
  title: string
  locator: string
  snippet: string
}

export async function listBases(): Promise<KnowledgeBase[]> {
  const data = await apiFetch<{ bases: KnowledgeBase[] }>('/api/frontend/knowledge/bases')
  return data.bases || []
}

export async function createBase(input: {
  name: string
  scope: KbScope
  description?: string
}): Promise<KnowledgeBase> {
  return apiFetch<KnowledgeBase>('/api/frontend/knowledge/bases', {
    method: 'POST',
    json: input,
  })
}

export async function deleteBase(kbId: string): Promise<void> {
  await apiFetch(`/api/frontend/knowledge/bases/${kbId}`, { method: 'DELETE' })
}

export async function listDocuments(kbId: string): Promise<KnowledgeDocument[]> {
  const data = await apiFetch<{ documents: KnowledgeDocument[] }>(
    `/api/frontend/knowledge/bases/${kbId}/documents`,
  )
  return data.documents || []
}

export async function uploadDocument(
  kbId: string,
  file: File,
): Promise<{ id: string; status: DocStatus; title: string }> {
  const form = new FormData()
  form.append('file', file, file.name)
  const res = await rawFetch(`/api/frontend/knowledge/bases/${kbId}/documents`, {
    method: 'POST',
    body: form,
    timeoutMs: 120_000,
  })
  return res.json()
}

export async function getDocument(
  docId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<{ document: KnowledgeDocument; chunks: DocumentChunk[] }> {
  const params = new URLSearchParams()
  if (opts.limit != null) params.set('limit', String(opts.limit))
  if (opts.offset != null) params.set('offset', String(opts.offset))
  const qs = params.toString() ? `?${params}` : ''
  return apiFetch(`/api/frontend/knowledge/documents/${docId}${qs}`)
}

export async function deleteDocument(docId: string): Promise<void> {
  await apiFetch(`/api/frontend/knowledge/documents/${docId}`, { method: 'DELETE' })
}

export async function searchKnowledge(input: {
  query: string
  kb_id?: string
  top_k?: number
}): Promise<Citation[]> {
  const data = await apiFetch<{ citations: Citation[] }>('/api/frontend/knowledge/search', {
    method: 'POST',
    json: input,
  })
  return data.citations || []
}

// ── 会话 ↔ 知识库绑定 ─────────────────────────────────────────────────

export async function getSessionBases(
  sessionId: string,
): Promise<{ kb_ids: string[]; bases: KnowledgeBase[] }> {
  return apiFetch(
    `/api/frontend/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`,
  )
}

export async function setSessionBases(
  sessionId: string,
  kbIds: string[],
): Promise<{ kb_ids: string[] }> {
  return apiFetch(
    `/api/frontend/sessions/${encodeURIComponent(sessionId)}/knowledge-bases`,
    { method: 'PUT', json: { kb_ids: kbIds } },
  )
}
