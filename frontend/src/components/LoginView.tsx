/**
 * LoginView — 玄机 AI 登录界面 (v2.1 — optimized)
 * 左侧品牌区(1.15) + 右侧登录区(0.85) · 2×2 特性网格 · Tab 切换
 */

import { useState, type FormEvent } from 'react'

/* ─── Types ─────────────────────────────────────────────── */
interface LoginUser {
  id: number
  username: string
  created_at?: string
}

type Theme = {
  primaryColor?: string
  primaryHover?: string
  accentColor?: string
}

/* ─── Design Tokens ─────────────────────────────────────── */
const C = {
  navy950: '#0a1628',
  navy900: '#0f1f3d',
  navy800: '#152a4e',
  blue400: '#4F6EF7',
  blue600: '#3D5CE5',
  blue700: '#2D4BD3',
  green400: '#639922',
  white: '#ffffff',
  gray50: '#F8F9FA',
  gray100: '#F1F3F5',
  gray200: '#E9ECEF',
  gray300: '#DEE2E6',
  gray400: '#CED4DA',
  gray500: '#ADB5BD',
  gray600: '#868E96',
  gray700: '#495057',
  gray800: '#343A40',
  gray900: '#212529',
  radiusSm: 6,
  radiusMd: 10,
  radiusLg: 16,
} as const

export function LoginView({ theme = {}, onLogin }: {
  theme?: Theme
  onLogin: (token: string, user: LoginUser) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [globalError, setGlobalError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({})
  const [toast, setToast] = useState('')
  const [activeTab, setActiveTab] = useState<'wechat' | 'feishu'>('wechat')

  const API_BASE = '/api/frontend'

  /* ── Helpers ─────────────────────────────────────────── */
  function clearErrors() {
    setFieldErrors({})
    setGlobalError('')
  }

  function validate(): boolean {
    const errs: { username?: string; password?: string } = {}
    if (!username.trim()) errs.username = '请输入用户名或邮箱'
    if (!password) errs.password = '请输入密码'
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2600)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    clearErrors()
    if (!validate()) return

    setLoading(true)
    setGlobalError('')
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        setGlobalError(data?.detail || '用户名或密码不正确，请重试。')
        return
      }
      const data = await res.json()
      onLogin(data.token, data.user)
    } catch {
      setGlobalError('登录失败，请检查网络后重试。')
    } finally {
      setLoading(false)
    }
  }

  /* ── Input style helper ──────────────────────────────── */
  const inputBase: React.CSSProperties = {
    width: '100%', padding: '12px 14px 12px 42px',
    fontSize: 14, border: `1.5px solid ${C.gray200}`,
    borderRadius: C.radiusMd, background: C.gray50,
    color: C.gray900, outline: 'none', fontFamily: 'inherit',
    transition: 'all 0.2s ease', WebkitAppearance: 'none' as never,
  }

  /* ── Render ──────────────────────────────────────────── */
  return (
    <div style={{
      display: 'flex', minHeight: '100vh',
      fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', 'PingFang SC', sans-serif",
    }}>

      {/* ═══ Left Panel (Brand) ═══ */}
      <aside style={{
        flex: 1.15, position: 'relative', overflow: 'hidden',
        background: `linear-gradient(165deg, ${C.navy950} 0%, ${C.navy900} 45%, ${C.navy800} 100%)`,
        padding: '48px 56px', display: 'flex', flexDirection: 'column',
      }}>
        {/* Decorative circles */}
        <div aria-hidden style={{
          position: 'absolute', top: -120, right: -80,
          width: 420, height: 420, borderRadius: '50%',
          background: `radial-gradient(circle, rgba(79,110,247,0.08) 0%, transparent 70%)`,
          pointerEvents: 'none',
        }} />
        <div aria-hidden style={{
          position: 'absolute', bottom: -60, left: -40,
          width: 300, height: 300, borderRadius: '50%',
          background: `radial-gradient(circle, rgba(99,153,34,0.06) 0%, transparent 70%)`,
          pointerEvents: 'none',
        }} />

        {/* Content wrapper */}
        <div style={{ position: 'relative', zIndex: 1, flex: 1, display: 'flex', flexDirection: 'column' }}>

          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: C.radiusMd,
              background: `linear-gradient(135deg, ${C.blue400}, ${C.blue600})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 4px 16px rgba(79,110,247,0.35)`,
            }}>
              <svg viewBox="0 0 24 24" style={{ width: 22, height: 22 }} fill="none">
                <line x1="5" y1="7" x2="19" y2="7" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                <line x1="5" y1="12" x2="19" y2="12" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                <line x1="5" y1="17" x2="19" y2="17" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                <line x1="12" y1="4" x2="12" y2="20" stroke="white" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 600, color: 'white', letterSpacing: 1, lineHeight: 1, margin: 0 }}>玄机</h1>
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)', letterSpacing: 2, textTransform: 'uppercase' }}>XUANJI · AI Platform</span>
            </div>
          </div>

          {/* Badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            marginTop: 28, padding: '6px 14px', width: 'fit-content',
            background: 'rgba(79,110,247,0.12)', border: '1px solid rgba(79,110,247,0.2)',
            borderRadius: 100,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: C.green400, animation: 'lv-pulse 2s ease-in-out infinite',
            }} />
            <span style={{ fontSize: 12, color: C.blue400 }}>智能多体协作平台 · 2026</span>
          </div>

          {/* Hero */}
          <div style={{ marginTop: 36 }}>
            <h2 style={{
              fontSize: 36, fontWeight: 700, color: 'white',
              lineHeight: 1.25, letterSpacing: -0.5, margin: 0,
            }}>
              靠谱的<br />
              <span style={{
                background: `linear-gradient(135deg, ${C.blue400}, #7C5CFC)`,
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>工作伙伴</span>
            </h2>
            <p style={{
              marginTop: 18, fontSize: 14.5, color: 'rgba(255,255,255,0.55)',
              lineHeight: 1.75, maxWidth: 380,
            }}>
              AI 驱动团队协作，让每项任务一一被响应。<br />
              支持自动执行、代码与知识库托管。
            </p>
          </div>

          {/* Features 2×2 grid */}
          <div style={{
            marginTop: 44, display: 'grid',
            gridTemplateColumns: '1fr 1fr', gap: 12,
          }}>
            {[
              {
                name: '多智能体协作', desc: '多 Agent 并行处理，复杂任务一键分发',
                iconBg: 'rgba(79,110,247,0.15)', iconColor: C.blue400,
                icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v4m0 14v4M4.22 4.22l2.83 2.83m9.9 9.9l2.83 2.83M1 12h4m14 0h4M4.22 19.78l2.83-2.83m9.9-9.9l2.83-2.83"/></svg>,
              },
              {
                name: '7×24 响应', desc: '全天候在线，无人值守不间断工作',
                iconBg: 'rgba(99,153,34,0.15)', iconColor: C.green400,
                icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10m-10 4h6m-6 4h4"/></svg>,
              },
              {
                name: '安全沙箱隔离', desc: '企业级隔离，数据安全无泄漏',
                iconBg: 'rgba(240,153,123,0.15)', iconColor: '#D85A30',
                icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
              },
              {
                name: '知识库记忆', desc: '上下文持久化，越用越懂你',
                iconBg: 'rgba(167,169,236,0.15)', iconColor: '#7F77DD',
                icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M8 7h8m-8 4h5"/></svg>,
              },
            ].map((f) => (
              <div key={f.name} style={{
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: C.radiusMd, padding: '18px 20px',
                transition: 'all 0.25s ease', cursor: 'default',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.13)'
                e.currentTarget.style.transform = 'translateY(-2px)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
              >
                <div style={{
                  width: 34, height: 34, borderRadius: 8,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginBottom: 10, background: f.iconBg, color: f.iconColor,
                }}>
                  <span style={{ width: 17, height: 17, display: 'block' }}>{f.icon}</span>
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.88)', marginBottom: 3 }}>{f.name}</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.38)', lineHeight: 1.5 }}>{f.desc}</div>
              </div>
            ))}
          </div>

          {/* Stats bar */}
          <div style={{
            marginTop: 'auto', paddingTop: 32,
            display: 'flex', gap: 32, alignItems: 'flex-start',
          }}>
            <div>
              <div style={{ fontSize: 26, fontWeight: 700, color: 'white', letterSpacing: -0.5 }}>
                12k<span style={{ fontSize: 16, color: C.blue400 }}>+</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>活跃用户</div>
            </div>
            <div style={{ width: 1, alignSelf: 'stretch', background: 'rgba(255,255,255,0.1)' }} />
            <div>
              <div style={{ fontSize: 26, fontWeight: 700, color: 'white', letterSpacing: -0.5 }}>
                98.6<span style={{ fontSize: 16, color: C.green400 }}>%</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>服务可用率</div>
            </div>
            <div style={{ width: 1, alignSelf: 'stretch', background: 'rgba(255,255,255,0.1)' }} />
            <div>
              <div style={{ fontSize: 26, fontWeight: 700, color: 'white', letterSpacing: -0.5 }}>
                500<span style={{ fontSize: 16, fontWeight: 500, color: 'rgba(255,255,255,0.5)' }}>ms</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>平均响应</div>
            </div>
          </div>

        </div>
      </aside>

      {/* ═══ Right Panel (Login Form) ═══ */}
      <main style={{
        flex: 0.85, background: C.white,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        padding: '48px 64px', position: 'relative',
      }}>
        <div style={{ maxWidth: 400, width: '100%', margin: '0 auto' }}>

          {/* Header */}
          <header style={{ marginBottom: 36 }}>
            <h2 style={{
              fontSize: 26, fontWeight: 700, color: C.gray900,
              letterSpacing: -0.3, marginBottom: 8,
            }}>欢迎回来</h2>
            <p style={{ fontSize: 14, color: C.gray500 }}>登录你的玄机账户以继续使用</p>
          </header>

          {/* Auth tabs */}
          <div style={{
            display: 'flex', background: C.gray100,
            borderRadius: C.radiusMd, padding: 3, marginBottom: 28,
          }}>
            {([
              { key: 'wechat' as const, label: '企业微信', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.66-.22.66-.48v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.56 9.56 0 0 1 2.5-.34c.85 0 1.7.12 2.5.34 1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.16.58.67.48A10.01 10.01 0 0 0 22 12c0-5.52-4.48-10-10-10z"/></svg> },
              { key: 'feishu' as const, label: '飞书', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg> },
            ]).map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                style={{
                  flex: 1, padding: '10px 0', textAlign: 'center',
                  fontSize: 13.5, fontWeight: 500,
                  color: activeTab === tab.key ? C.gray900 : C.gray500,
                  border: 'none', cursor: 'pointer',
                  background: activeTab === tab.key ? C.white : 'transparent',
                  borderRadius: 7,
                  boxShadow: activeTab === tab.key ? '0 1px 2px rgba(0,0,0,0.04)' : 'none',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                  transition: 'all 0.2s ease', fontFamily: 'inherit',
                }}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>

          {/* Global error */}
          {globalError && (
            <div role="alert" style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '12px 14px', borderRadius: C.radiusMd,
              background: '#fef2f2', border: '1px solid rgba(220,38,38,0.2)',
              marginBottom: 18,
            }}>
              <svg viewBox="0 0 16 16" fill="none" stroke="#dc2626" strokeWidth="1.5" strokeLinecap="round" style={{ width: 16, height: 16, flexShrink: 0, marginTop: 1 }}>
                <circle cx="8" cy="8" r="6" /><path d="M8 5v3.5M8 11v.5" />
              </svg>
              <span style={{ fontSize: 13, color: '#991b1b', lineHeight: 1.5 }}>{globalError}</span>
            </div>
          )}

          {/* Login form */}
          <form onSubmit={handleSubmit} noValidate>
            {/* Username */}
            <div style={{ marginBottom: 20 }}>
              <label htmlFor="login-username" style={{
                display: 'block', fontSize: 13, fontWeight: 500,
                color: C.gray700, marginBottom: 7,
              }}>用户名 / 邮箱</label>
              <div style={{ position: 'relative' }}>
                <input
                  id="login-username"
                  type="text"
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); if (fieldErrors.username) setFieldErrors(f => ({ ...f, username: undefined })) }}
                  placeholder="请输入账号或邮箱地址"
                  autoComplete="username"
                  style={{
                    ...inputBase,
                    borderColor: fieldErrors.username ? '#dc2626' : C.gray200,
                    boxShadow: fieldErrors.username ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                  }}
                  onFocus={(e) => {
                    if (!fieldErrors.username) {
                      e.target.style.borderColor = C.blue400
                      e.target.style.background = C.white
                      e.target.style.boxShadow = `0 0 0 3px rgba(79,110,247,0.10)`
                    }
                  }}
                  onBlur={(e) => {
                    if (!fieldErrors.username) {
                      e.target.style.borderColor = C.gray200
                      e.target.style.background = C.gray50
                      e.target.style.boxShadow = 'none'
                    }
                  }}
                />
                <span style={{
                  position: 'absolute', left: 14, top: '50%',
                  transform: 'translateY(-50%)', color: C.gray400,
                  display: 'flex', alignItems: 'center', pointerEvents: 'none',
                }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 17, height: 17 }}>
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                  </svg>
                </span>
              </div>
              {fieldErrors.username && (
                <p role="alert" style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#dc2626', marginTop: 4 }}>
                  <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" style={{ width: 12, height: 12 }}>
                    <circle cx="6" cy="6" r="5" /><path d="M6 4v2.5M6 8v.5" />
                  </svg>
                  {fieldErrors.username}
                </p>
              )}
            </div>

            {/* Password */}
            <div style={{ marginBottom: 20 }}>
              <label htmlFor="login-password" style={{
                display: 'block', fontSize: 13, fontWeight: 500,
                color: C.gray700, marginBottom: 7,
              }}>密码</label>
              <div style={{ position: 'relative' }}>
                <input
                  id="login-password"
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); if (fieldErrors.password) setFieldErrors(f => ({ ...f, password: undefined })) }}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  style={{
                    ...inputBase,
                    paddingRight: 44,
                    borderColor: fieldErrors.password ? '#dc2626' : C.gray200,
                    boxShadow: fieldErrors.password ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                  }}
                  onFocus={(e) => {
                    if (!fieldErrors.password) {
                      e.target.style.borderColor = C.blue400
                      e.target.style.background = C.white
                      e.target.style.boxShadow = `0 0 0 3px rgba(79,110,247,0.10)`
                    }
                  }}
                  onBlur={(e) => {
                    if (!fieldErrors.password) {
                      e.target.style.borderColor = C.gray200
                      e.target.style.background = C.gray50
                      e.target.style.boxShadow = 'none'
                    }
                  }}
                />
                <span style={{
                  position: 'absolute', left: 14, top: '50%',
                  transform: 'translateY(-50%)', color: C.gray400,
                  display: 'flex', alignItems: 'center', pointerEvents: 'none',
                }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 17, height: 17 }}>
                    <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                  </svg>
                </span>
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  aria-label={showPw ? '隐藏密码' : '显示密码'}
                  style={{
                    position: 'absolute', right: 14, top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: C.gray400, padding: 4, display: 'flex', alignItems: 'center',
                    transition: 'color 0.2s',
                  }}
                >
                  {showPw ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 17, height: 17 }}>
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 17, height: 17 }}>
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
                    </svg>
                  )}
                </button>
              </div>
              {fieldErrors.password && (
                <p role="alert" style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#dc2626', marginTop: 4 }}>
                  <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" style={{ width: 12, height: 12 }}>
                    <circle cx="6" cy="6" r="5" /><path d="M6 4v2.5M6 8v.5" />
                  </svg>
                  {fieldErrors.password}
                </p>
              )}
            </div>

            {/* Remember me + Forgot */}
            <div style={{
              display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', marginBottom: 26,
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  style={{
                    appearance: 'none', width: 16, height: 16,
                    border: `1.5px solid ${remember ? C.blue600 : C.gray300}`,
                    borderRadius: 4, cursor: 'pointer',
                    background: remember ? C.blue600 : 'white',
                    position: 'relative', transition: 'all 0.15s',
                  }}
                />
                {remember && (
                  <svg viewBox="0 0 10 10" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    style={{ position: 'absolute', width: 8, height: 8, pointerEvents: 'none', marginLeft: -21, marginTop: -1 }}>
                    <path d="M1.5 5l2.5 2.5L8.5 2" />
                  </svg>
                )}
                <span style={{ fontSize: 13, color: C.gray600, cursor: 'pointer' }}>记住我</span>
              </label>
              <button
                type="button"
                onClick={() => showToast('密码找回功能即将上线')}
                style={{
                  fontSize: 13, color: C.blue600, fontWeight: 500,
                  textDecoration: 'none', background: 'none', border: 'none',
                  cursor: 'pointer', fontFamily: 'inherit',
                }}
              >忘记密码?</button>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%', padding: 13,
                fontSize: 15, fontWeight: 600, color: 'white',
                background: loading ? C.blue600 : `linear-gradient(135deg, ${C.blue600}, ${C.blue700})`,
                border: 'none', borderRadius: C.radiusMd, cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                letterSpacing: 0.3, fontFamily: 'inherit',
                opacity: loading ? 0.7 : 1,
                transition: 'all 0.25s ease',
              }}
              onMouseEnter={(e) => {
                if (!loading) {
                  e.currentTarget.style.background = `linear-gradient(135deg, ${C.blue400}, ${C.blue600})`
                  e.currentTarget.style.boxShadow = `0 6px 20px rgba(61,92,229,0.35)`
                  e.currentTarget.style.transform = 'translateY(-1px)'
                }
              }}
              onMouseLeave={(e) => {
                if (!loading) {
                  e.currentTarget.style.background = `linear-gradient(135deg, ${C.blue600}, ${C.blue700})`
                  e.currentTarget.style.boxShadow = 'none'
                  e.currentTarget.style.transform = 'translateY(0)'
                }
              }}
              onMouseDown={(e) => {
                if (!loading) e.currentTarget.style.transform = 'translateY(0)'
              }}
              onMouseUp={(e) => {
                if (!loading) e.currentTarget.style.transform = 'translateY(-1px)'
              }}
            >
              {loading ? (
                <span style={{
                  display: 'block', width: 18, height: 18,
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: 'white', borderRadius: '50%',
                  animation: 'lv-spin 0.6s linear infinite',
                }} />
              ) : (
                <>
                  登录账户
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}>
                    <path d="M5 12h14m-7-7l7 7-7 7" />
                  </svg>
                </>
              )}
            </button>
          </form>

          {/* Register link */}
          <p style={{ textAlign: 'center', marginTop: 24, fontSize: 13.5, color: C.gray500 }}>
            还没有账号？
            <button
              type="button"
              onClick={() => showToast('注册功能即将上线')}
              style={{
                color: C.blue600, fontWeight: 600, marginLeft: 4,
                background: 'none', border: 'none', cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 13.5, padding: 0,
              }}
            >立即注册 &rarr;</button>
          </p>
        </div>

        {/* Footer */}
        <footer style={{
          marginTop: 'auto', paddingTop: 40,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: 11.5, color: C.gray400,
        }}>
          <span>&copy; 2025 玄机 XUANJI &middot; 本系统由 AI 驱动</span>
          <div style={{ display: 'flex', gap: 16 }}>
            <button type="button" onClick={() => showToast('隐私政策')} style={{ color: C.gray400, background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: 11.5, padding: 0 }}>隐私政策</button>
            <button type="button" onClick={() => showToast('服务条款')} style={{ color: C.gray400, background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: 11.5, padding: 0 }}>服务条款</button>
          </div>
        </footer>
      </main>

      {/* Toast */}
      {toast && (
        <div role="status" aria-live="polite" style={{
          position: 'fixed', bottom: 24, right: 24,
          background: C.gray900, color: 'white',
          padding: '10px 20px', borderRadius: C.radiusMd,
          fontSize: 13, fontWeight: 500, zIndex: 999,
          animation: 'lv-toast-in 260ms cubic-bezier(0.25,1,0.5,1) both',
        }}>{toast}</div>
      )}

      {/* Keyframe animations + responsive */}
      <style>{`
        @keyframes lv-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }
        @keyframes lv-spin { to { transform: rotate(360deg); } }
        @keyframes lv-toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 1024px) {
          aside { display: none !important; }
          main { flex: 1 !important; padding: 40px 32px !important; }
        }
        @media (max-width: 480px) {
          main { padding: 32px 24px !important; }
        }
      `}</style>
    </div>
  )
}
