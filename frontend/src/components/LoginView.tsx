import { useState, useCallback } from 'react'

interface LoginViewProps {
  onLogin: (token: string, user: { id: number; username: string }) => void
}

const API = '/api/frontend/auth'

export function LoginView({ onLogin }: LoginViewProps) {
  const [view, setView] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPwd, setShowPwd] = useState(false)

  const handleLogin = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      setError('')

      const uname = username.trim()
      if (!uname) {
        setError('请输入用户名')
        return
      }
      if (password.length < 6) {
        setError('密码至少 6 个字符')
        return
      }

      setLoading(true)
      try {
        const res = await fetch(`${API}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: uname, password }),
        })
        const data = await res.json()
        if (!res.ok) {
          setError(data.error || '登录失败')
          return
        }
        onLogin(data.token, data.user)
      } catch {
        setError('网络错误，请重试')
      } finally {
        setLoading(false)
      }
    },
    [username, password, onLogin],
  )

  const handleRegister = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      setError('')

      const uname = username.trim()
      if (uname.length < 2 || uname.length > 20) {
        setError('用户名需要 2-20 个字符')
        return
      }
      if (password.length < 6) {
        setError('密码至少 6 个字符')
        return
      }
      if (password !== confirmPassword) {
        setError('两次输入的密码不一致')
        return
      }

      setLoading(true)
      try {
        const res = await fetch(`${API}/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: uname, password }),
        })
        const data = await res.json()
        if (!res.ok) {
          setError(data.error || '注册失败')
          return
        }
        // Registration success → switch back to login with success message
        setView('login')
        setPassword('')
        setConfirmPassword('')
        setSuccess(`账户 "${uname}" 注册成功，请登录`)
      } catch {
        setError('网络错误，请重试')
      } finally {
        setLoading(false)
      }
    },
    [username, password, confirmPassword],
  )

  const switchView = useCallback((v: 'login' | 'register') => {
    setView(v)
    setError('')
    setSuccess('')
    setPassword('')
    setConfirmPassword('')
  }, [])

  // ── Eye icon for password visibility ────────────────────────────────
  const EyeIcon = ({ open }: { open: boolean }) => (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {open ? (
        <>
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
          <circle cx="12" cy="12" r="3" />
        </>
      ) : (
        <>
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
          <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </>
      )}
    </svg>
  )

  // ── Register View ─────────────────────────────────────────────────
  if (view === 'register') {
    return (
      <div className="h-dvh w-dvw flex items-center justify-center bg-[#f0f2f5]">
        <div className="w-[440px] bg-white rounded-2xl shadow-[0_8px_40px_rgba(0,0,0,0.08)] border border-gray-100/80 overflow-hidden">
          {/* Header */}
          <div className="px-10 pt-10 pb-7">
            <div className="flex items-center gap-3.5 mb-10">
              <div className="flex items-center justify-center w-11 h-11 rounded-xl bg-gradient-to-br from-blue-400 to-blue-600 text-white text-base font-bold shrink-0 shadow-sm">
                玄
              </div>
              <div>
                <div className="text-[16px] font-semibold text-gray-800 tracking-wide">玄机</div>
                <div className="text-[12px] text-gray-400 mt-0.5">AI 工作助手</div>
              </div>
            </div>
            <h2 className="text-[22px] font-bold text-gray-900 tracking-wide">注册</h2>
            <p className="text-[14px] text-gray-400 mt-2">创建您的玄机账户</p>
          </div>

          {/* Form */}
          <form onSubmit={handleRegister} className="px-10 pb-10">
            <div className="space-y-5">
              <div className="flex items-center gap-3">
                <label className="shrink-0 w-[72px] text-[14px] font-medium text-gray-600 text-right">用户名</label>
                <div className="relative flex-1">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="请输入用户名"
                    autoComplete="username"
                    className="w-full pl-10 pr-4 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-colors bg-gray-50/50"
                  />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="shrink-0 w-[72px] text-[14px] font-medium text-gray-600 text-right">密码</label>
                <div className="relative flex-1">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <input
                    type={showPwd ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="请输入密码（至少6位）"
                    autoComplete="new-password"
                    className="w-full pl-10 pr-10 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-colors bg-gray-50/50"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd(!showPwd)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 transition-colors"
                  >
                    <EyeIcon open={showPwd} />
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="shrink-0 w-[72px] text-[14px] font-medium text-gray-600 text-right">确认密码</label>
                <div className="relative flex-1">
                  <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="再次输入密码"
                    autoComplete="new-password"
                    className="w-full pl-10 pr-4 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-colors bg-gray-50/50"
                  />
                </div>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="mt-4 px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-600">
                {error}
              </div>
            )}

            {/* Submit */}
            <div className="flex justify-center mt-8">
              <button
                type="submit"
                disabled={loading}
                className="w-1/3 py-3 rounded-xl bg-blue-600 text-white text-[15px] font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
              >
                {loading ? '注册中...' : '注册'}
              </button>
            </div>

            {/* Back to login link */}
            <p className="text-center text-[13px] text-gray-400 mt-7">
              已有账号？{' '}
              <button
                type="button"
                onClick={() => switchView('login')}
                className="text-blue-600 font-medium hover:text-blue-700 hover:underline transition-colors"
              >
                返回登录
              </button>
            </p>
          </form>
        </div>
      </div>
    )
  }

  // ── Login View ────────────────────────────────────────────────────
  return (
    <div className="h-dvh w-dvw flex items-center justify-center bg-[#f0f2f5]">
      <div className="w-[440px] bg-white rounded-2xl shadow-[0_8px_40px_rgba(0,0,0,0.08)] border border-gray-100/80 overflow-hidden">
        {/* Header */}
        <div className="px-10 pt-10 pb-7">
          <div className="flex items-center gap-3.5 mb-10">
            <img src="/xuanji-logo.png" alt="玄机" className="w-11 h-11 rounded-xl object-contain shrink-0" />
            <div>
              <div className="text-[16px] font-semibold text-gray-800 tracking-wide">玄机</div>
              <div className="text-[12px] text-gray-400 mt-0.5">AI 工作助手</div>
            </div>
          </div>
          <h2 className="text-[22px] font-bold text-gray-900 tracking-wide">登录</h2>
          <p className="text-[14px] text-gray-400 mt-2">欢迎回来，登录以继续使用</p>
        </div>

        {/* Form */}
        <form onSubmit={handleLogin} className="px-10 pb-10">
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <label className="shrink-0 w-[72px] text-[14px] font-medium text-gray-600 text-right">用户名</label>
              <div className="relative flex-1">
                <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  autoComplete="username"
                  className="w-full pl-10 pr-4 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-colors bg-gray-50/50"
                />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <label className="shrink-0 w-[72px] text-[14px] font-medium text-gray-600 text-right">密码</label>
              <div className="relative flex-1">
                <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <input
                  type={showPwd ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  className="w-full pl-10 pr-10 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-colors bg-gray-50/50"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 transition-colors"
                >
                  <EyeIcon open={showPwd} />
                </button>
              </div>
            </div>
          </div>

          {/* Success message */}
          {success && (
            <div className="mt-4 px-4 py-2.5 rounded-lg bg-blue-50 border border-blue-200 text-[13px] text-blue-700">
              {success}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="mt-4 px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-600">
              {error}
            </div>
          )}

          {/* Submit button */}
          <div className="flex justify-center mt-8">
            <button
              type="submit"
              disabled={loading}
              className="w-1/3 py-3 rounded-xl bg-blue-600 text-white text-[15px] font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
            >
              {loading ? '登录中...' : '登录'}
            </button>
          </div>

          {/* Divider + Register link */}
          <div className="flex items-center gap-3 mt-8">
            <div className="flex-1 h-px bg-gray-200" />
            <span className="text-[12px] text-gray-300">或</span>
            <div className="flex-1 h-px bg-gray-200" />
          </div>
          <p className="text-center text-[13px] text-gray-400 mt-5">
            还没有账号？{' '}
            <button
              type="button"
              onClick={() => switchView('register')}
              className="text-blue-600 font-medium hover:text-blue-700 hover:underline transition-colors"
            >
              立即注册
            </button>
          </p>

          {/* Hint */}
          <p className="text-center text-[12px] text-gray-300 mt-4">
            默认账户: admin / admin123
          </p>
        </form>
      </div>
    </div>
  )
}
