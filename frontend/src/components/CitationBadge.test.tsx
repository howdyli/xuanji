import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CitationBadge } from './CitationBadge'
import type { Citation } from '../api/knowledge'

const CITATION: Citation = {
  n: 2,
  document_id: 'doc-abc',
  chunk_index: 5,
  title: '产品需求文档',
  locator: 'page=3',
  snippet: '本节描述了知识库的检索流程与引用溯源机制。',
}

describe('CitationBadge', () => {
  it('renders the citation number', () => {
    render(<CitationBadge citation={CITATION} />)
    expect(screen.getByRole('button', { name: '引用 2' })).toHaveTextContent('2')
  })

  it('reveals the source snippet on click and hides it again', async () => {
    const user = userEvent.setup()
    render(<CitationBadge citation={CITATION} />)

    // popover hidden initially
    expect(screen.queryByRole('dialog')).toBeNull()

    await user.click(screen.getByRole('button', { name: '引用 2' }))
    const dialog = screen.getByRole('dialog', { name: '引用 2 详情' })
    expect(dialog).toHaveTextContent('产品需求文档')
    expect(dialog).toHaveTextContent('page=3')
    expect(dialog).toHaveTextContent('知识库的检索流程')

    // toggle closed
    await user.click(screen.getByRole('button', { name: '引用 2' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('invokes onOpenDocument with the document id', async () => {
    const user = userEvent.setup()
    let opened = ''
    render(<CitationBadge citation={CITATION} onOpenDocument={(id) => { opened = id }} />)

    await user.click(screen.getByRole('button', { name: '引用 2' }))
    await user.click(screen.getByText('查看原文 →'))
    expect(opened).toBe('doc-abc')
  })
})
