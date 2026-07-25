import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KnowledgeView } from './KnowledgeView'
import type { KnowledgeBase, KnowledgeDocument } from '../api/knowledge'

// Mock the typed knowledge API so the view is tested in isolation from fetch.
vi.mock('../api/knowledge', () => ({
  listBases: vi.fn(),
  createBase: vi.fn(),
  deleteBase: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  getDocument: vi.fn(),
  deleteDocument: vi.fn(),
  searchKnowledge: vi.fn(),
}))

import * as api from '../api/knowledge'

const BASES: KnowledgeBase[] = [
  {
    id: 'kb-personal1', name: '我的资料', scope: 'personal', owner_key: 'p2p:web_alice',
    org_id: null, description: '个人笔记', document_count: 2, created_by: 'alice',
  },
  {
    id: 'kb-org1', name: '团队手册', scope: 'org', owner_key: 'p2p:web_alice',
    org_id: 1, description: '', document_count: 5, created_by: 'admin',
  },
]

const DOCS: KnowledgeDocument[] = [
  {
    id: 'doc-1', kb_id: 'kb-personal1', title: 'ready.pdf', source_type: 'file', source_uri: '',
    mime: 'application/pdf', byte_size: 2048, status: 'ready', error_msg: '', chunk_count: 7,
    created_by: 'alice',
  },
  {
    id: 'doc-2', kb_id: 'kb-personal1', title: 'processing.docx', source_type: 'file', source_uri: '',
    mime: '', byte_size: 1024, status: 'processing', error_msg: '', chunk_count: 0, created_by: 'alice',
  },
  {
    id: 'doc-3', kb_id: 'kb-personal1', title: 'broken.txt', source_type: 'file', source_uri: '',
    mime: '', byte_size: 512, status: 'failed', error_msg: 'no extractable text', chunk_count: 0,
    created_by: 'alice',
  },
]

describe('KnowledgeView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listBases).mockResolvedValue(BASES)
    vi.mocked(api.listDocuments).mockResolvedValue(DOCS)
  })

  it('lists bases grouped by personal and org', async () => {
    render(<KnowledgeView authToken="t" isAdmin={false} />)
    expect(await screen.findByText('我的资料')).toBeInTheDocument()
    expect(screen.getByText('团队手册')).toBeInTheDocument()
    expect(screen.getByText('个人')).toBeInTheDocument()
    expect(screen.getByText('组织')).toBeInTheDocument()
    expect(screen.getByText('共 2 个知识库')).toBeInTheDocument()
  })

  it('creates a personal base through the modal', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createBase).mockResolvedValue({
      id: 'kb-new', name: '新库', scope: 'personal', owner_key: 'p2p:web_alice',
      org_id: null, description: '', created_by: 'alice',
    })
    render(<KnowledgeView authToken="t" isAdmin={false} />)
    await screen.findByText('我的资料')

    await user.click(screen.getByText('+ 新建知识库'))
    await user.type(screen.getByPlaceholderText(/产品文档/), '新库')
    await user.click(screen.getByText('创建'))

    await waitFor(() =>
      expect(api.createBase).toHaveBeenCalledWith(
        expect.objectContaining({ name: '新库', scope: 'personal' }),
      ),
    )
  })

  it('shows document status badges after opening a base', async () => {
    const user = userEvent.setup()
    render(<KnowledgeView authToken="t" isAdmin={false} />)
    await user.click(await screen.findByText('我的资料'))

    expect(await screen.findByText('ready.pdf')).toBeInTheDocument()
    expect(screen.getByText('就绪')).toBeInTheDocument()
    expect(screen.getByText('处理中')).toBeInTheDocument()
    expect(screen.getByText('失败')).toBeInTheDocument()
    // ready document surfaces its chunk count
    expect(screen.getByText(/7 块/)).toBeInTheDocument()
  })

  it('renders citation badges from a debug search', async () => {
    const user = userEvent.setup()
    vi.mocked(api.searchKnowledge).mockResolvedValue([
      { n: 1, document_id: 'doc-1', chunk_index: 0, title: 'ready.pdf', locator: 'page=1', snippet: '命中片段内容' },
    ])
    render(<KnowledgeView authToken="t" isAdmin={false} />)
    await user.click(await screen.findByText('我的资料'))

    await user.type(await screen.findByPlaceholderText(/试检索/), '关键词')
    await user.click(screen.getByText('检索'))

    const badge = await screen.findByRole('button', { name: '引用 1' })
    expect(badge).toBeInTheDocument()
    await user.click(badge)
    expect(within(screen.getByRole('dialog')).getByText(/命中片段内容/)).toBeInTheDocument()
  })
})
