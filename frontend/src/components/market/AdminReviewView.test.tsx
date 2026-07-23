import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { AdminReviewView } from './AdminReviewView'

function mockPending(skills: Array<Record<string, unknown>>) {
  return vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => ({ skills, total: skills.length }),
  }) as unknown as Response)
}

describe('AdminReviewView', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the 版本更新 badge and version diff for a pending update', async () => {
    vi.stubGlobal(
      'fetch',
      mockPending([
        {
          name: 'translator',
          publisher: 'alice',
          category: 'tool',
          version: '1.0.0',
          description: 'a tool',
          has_pending_update: true,
          pending_version: '2.0.0',
          install_url: 'local://a',
          pending_install_url: 'local://b',
        },
      ]),
    )
    render(<AdminReviewView authToken="t" />)

    expect(await screen.findByText('版本更新')).toBeInTheDocument()
    expect(screen.getByText('v1.0.0 → v2.0.0')).toBeInTheDocument()
    expect(screen.getByText('安装地址变更：')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '通过更新' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '驳回更新' })).toBeInTheDocument()
  })

  it('renders a first-publish skill without the 版本更新 badge', async () => {
    vi.stubGlobal(
      'fetch',
      mockPending([
        {
          name: 'summarizer',
          publisher: 'bob',
          category: 'tool',
          version: '0.1.0',
          description: 'first publish',
        },
      ]),
    )
    render(<AdminReviewView authToken="t" />)

    await waitFor(() => expect(screen.getByText('summarizer')).toBeInTheDocument())
    expect(screen.queryByText('版本更新')).toBeNull()
    expect(screen.getByText('v0.1.0')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '通过' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '拒绝' })).toBeInTheDocument()
  })
})
