import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NotificationBell } from './NotificationBell'

// 根据请求 URL + method 路由到不同的 mock 响应。
function mockFetchRouter(opts: {
  count?: number
  notifications?: Array<Record<string, unknown>>
}) {
  const { count = 0, notifications = [] } = opts
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method || 'GET').toUpperCase()
    const ok = (data: unknown) => ({ ok: true, json: async () => data }) as Response
    if (url.endsWith('/unread-count')) return ok({ count })
    if (url.endsWith('/read-all') && method === 'POST') return ok({ updated: count })
    if (url.endsWith('/read') && method === 'POST') return ok({ ok: true })
    if (url.endsWith('/api/frontend/notifications')) return ok({ notifications, total: notifications.length })
    return ok({})
  })
}

const SAMPLE = [
  { id: 1, type: 'skill_approved', title: '你的技能「翻译」审核通过', body: '', payload: {}, read: false, created_at: new Date().toISOString() },
  { id: 2, type: 'skill_rejected', title: '你的版本更新「翻译」审核驳回', body: '审核意见：产物不合规', payload: {}, read: true, created_at: new Date().toISOString() },
]

describe('NotificationBell', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the unread badge when count > 0', async () => {
    vi.stubGlobal('fetch', mockFetchRouter({ count: 3 }))
    render(<NotificationBell authToken="t" />)
    expect(await screen.findByLabelText('3 条未读')).toHaveTextContent('3')
  })

  it('does not render a badge when count is 0', async () => {
    vi.stubGlobal('fetch', mockFetchRouter({ count: 0 }))
    render(<NotificationBell authToken="t" />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByLabelText(/条未读/)).toBeNull()
  })

  it('opens the dropdown and lists notifications', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockFetchRouter({ count: 1, notifications: SAMPLE }))
    render(<NotificationBell authToken="t" />)

    await user.click(screen.getByRole('button', { name: '通知' }))
    expect(await screen.findByText('你的技能「翻译」审核通过')).toBeInTheDocument()
    expect(screen.getByText('审核意见：产物不合规')).toBeInTheDocument()
  })

  it('marks a single notification read and decrements the badge', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockFetchRouter({ count: 1, notifications: SAMPLE }))
    render(<NotificationBell authToken="t" />)

    await user.click(screen.getByRole('button', { name: '通知' }))
    const item = await screen.findByText('你的技能「翻译」审核通过')
    await user.click(item)

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/frontend/notifications/1/read',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(screen.queryByLabelText(/条未读/)).toBeNull()
  })

  it('marks all read and clears the badge', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockFetchRouter({ count: 5, notifications: SAMPLE }))
    render(<NotificationBell authToken="t" />)

    await user.click(screen.getByRole('button', { name: '通知' }))
    await user.click(await screen.findByText('全部已读'))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/frontend/notifications/read-all',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(screen.queryByLabelText(/条未读/)).toBeNull()
  })

  it('degrades silently when fetch fails (no badge, no crash)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network') }))
    render(<NotificationBell authToken="t" />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByLabelText(/条未读/)).toBeNull()
    expect(screen.getByRole('button', { name: '通知' })).toBeInTheDocument()
  })
})
