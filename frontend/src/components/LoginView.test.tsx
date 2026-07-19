import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginView } from './LoginView'

describe('LoginView', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function fillCredentials(user: ReturnType<typeof userEvent.setup>) {
    return (async () => {
      await user.type(
        screen.getByPlaceholderText('请输入账号或邮箱地址'),
        'alice',
      )
      await user.type(screen.getByPlaceholderText('请输入密码'), 'secret')
    })()
  }

  it('shows field validation errors and does not call the API on empty submit', async () => {
    const user = userEvent.setup()
    const onLogin = vi.fn()
    render(<LoginView onLogin={onLogin} />)

    await user.click(screen.getByRole('button', { name: /登录账户/ }))

    expect(screen.getByText('请输入用户名或邮箱')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    expect(onLogin).not.toHaveBeenCalled()
  })

  it('calls onLogin with token and user on successful login', async () => {
    const user = userEvent.setup()
    const onLogin = vi.fn()
    const fakeUser = { id: 1, username: 'alice' }
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ token: 'tok-123', user: fakeUser }),
    })
    render(<LoginView onLogin={onLogin} />)

    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: /登录账户/ }))

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith('tok-123', fakeUser))
    expect(fetch).toHaveBeenCalledWith(
      '/api/frontend/auth/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ username: 'alice', password: 'secret' }),
      }),
    )
  })

  it('shows the server error message and does not call onLogin on failure', async () => {
    const user = userEvent.setup()
    const onLogin = vi.fn()
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      json: async () => ({ detail: '账号已被锁定' }),
    })
    render(<LoginView onLogin={onLogin} />)

    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: /登录账户/ }))

    expect(await screen.findByText('账号已被锁定')).toBeInTheDocument()
    expect(onLogin).not.toHaveBeenCalled()
  })

  it('shows a network error message when fetch rejects', async () => {
    const user = userEvent.setup()
    const onLogin = vi.fn()
    ;(fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('network'))
    render(<LoginView onLogin={onLogin} />)

    await fillCredentials(user)
    await user.click(screen.getByRole('button', { name: /登录账户/ }))

    expect(
      await screen.findByText('登录失败，请检查网络后重试。'),
    ).toBeInTheDocument()
    expect(onLogin).not.toHaveBeenCalled()
  })
})
