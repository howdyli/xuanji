/**
 * LoginView — 玄机 AI 商业级登录界面 (v2.0)
 * 50/50 布局 · Fraunces + Plus Jakarta Sans · WCAG AA · 响应式
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

  const primary = theme.primaryColor || '#2554a0'
  const primaryHover = theme.primaryHover || '#1e3b6e'
  const accent = theme.accentColor || '#3067c3'

  /* ── Form validation & submit ─────────────────────────── */
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

  const API_BASE = '/api/frontend'

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

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2600)
  }

  /* ── Render ────────────────────────────────────────────── */
  return (
    <div style={{
      display: 'flex',
      minHeight: '100vh',
      fontFamily: "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
    }}>
      {/* ═══ Left Panel (Brand) ═══ */}
      <aside aria-label="产品介绍" style={{
        flex: 1,
        background: '#0d1f3c',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        padding: '48px 52px',
        minWidth: 0,
      }}>
        {/* Grid noise overlay */}
        <div aria-hidden="true" style={{
          position: 'absolute', inset: 0,
          backgroundImage: 'linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          pointerEvents: 'none',
        }} />
        {/* Circle decorations */}
        <div aria-hidden="true" style={{
          position: 'absolute', top: -130, right: -100,
          width: 380, height: 380, borderRadius: '50%',
          background: '#1e3b6e', opacity: 0.4, pointerEvents: 'none',
        }} />
        <div aria-hidden="true" style={{
          position: 'absolute', bottom: -80, left: -70,
          width: 260, height: 260, borderRadius: '50%',
          background: '#152b52', opacity: 0.5, pointerEvents: 'none',
        }} />

        {/* Content */}
        <div style={{ position: 'relative', zIndex: 1, flex: 1, display: 'flex', flexDirection: 'column' }}>

          {/* Brand mark */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 60 }}>
            <div aria-hidden="true" style={{
              width: 42, height: 42, borderRadius: 10, flexShrink: 0,
              background: 'linear-gradient(135deg, #5289d9, #2554a0)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 22, height: 22 }}>
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </div>
            <div>
              <span style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 22, fontWeight: 700, color: '#f4f8ff',
                lineHeight: 1, letterSpacing: '-0.02em', display: 'block',
              }}>玄机</span>
              <span style={{
                fontSize: 11, fontWeight: 500, color: '#85aee5',
                letterSpacing: '0.08em', textTransform: 'uppercase',
                marginTop: 2, display: 'block',
              }}>XUANJI · AI Platform</span>
            </div>
          </div>

          {/* Hero section */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>

            {/* Status badge */}
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 7,
              background: 'rgba(255,255,255,0.07)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 100, padding: '4px 12px 4px 8px',
              marginBottom: 24, width: 'fit-content',
            }}>
              <span aria-hidden="true" style={{
                width: 7, height: 7, borderRadius: '50%',
                background: '#059669', flexShrink: 0,
              }} />
              <span style={{
                fontSize: 12, fontWeight: 500, color: '#b8cff2',
                letterSpacing: '0.02em',
              }}>智能多体协作平台 · 2025</span>
            </div>

            {/* Main heading */}
            <h1 style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 'clamp(32px, 4vw, 46px)', fontWeight: 700,
              color: '#f4f8ff', lineHeight: 1.08,
              letterSpacing: '-0.03em', marginBottom: 16,
            }}>
              靠谱的<br /><span style={{ color: '#85aee5', fontStyle: 'normal' }}>工作伙伴</span>
            </h1>

            {/* Description */}
            <p style={{
              fontSize: 15, fontWeight: 400, color: '#85aee5',
              lineHeight: 1.7, maxWidth: 360, marginBottom: 40,
            }}>
              AI 专家团队协作，让复杂任务一键完成。<br />
              定时自动执行，代码与知识全程托管。
            </p>

            {/* Feature list */}
            <ul role="list" style={{
              listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 10,
              margin: 0, padding: 0,
            }}>
              {[
                { title: '多智能体协作', desc: '专家团队自动编排，复杂任务一键完成', icon: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M3 8a5 5 0 1 0 10 0A5 5 0 0 0 3 8Z" /><path d="M5.5 8l1.5 1.5 3.5-3" /></svg> },
                { title: '7×24 自动化', desc: '定时任务自动执行，无需人工干预', icon: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><rect x="2" y="2" width="12" height="12" rx="2" /><path d="M5 5h6M5 8h4M5 11h3" /></svg> },
                { title: '安全沙箱隔离', desc: '代码执行全程隔离，数据安全无忧', icon: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M8 2l2 2H12a1 1 0 0 1 1 1v2l2 1-2 1v2a1 1 0 0 1-1 1h-2l-2 2-2-2H4a1 1 0 0 1-1-1v-2L1 9l2-1V6a1 1 0 0 1 1-1h2l2-2Z" /></svg> },
                { title: '知识库记忆', desc: '上传文档构建专属知识库，AI 持续学习', icon: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M2 12s1-2 6-2 6 2 6 2" /><circle cx="8" cy="6" r="3" /></svg> },
              ].map((f) => (
                <li key={f.title} className="feature-item-hover" style={{
                  display: 'flex', alignItems: 'flex-start', gap: 14,
                  padding: '14px 18px', borderRadius: 14,
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  transition: 'background 140ms cubic-bezier(0.25,1,0.5,1)',
                  cursor: 'default',
                }}>
                  <div aria-hidden="true" style={{
                    width: 36, height: 36, borderRadius: 8, flexShrink: 0,
                    background: '#1e3b6e',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#85aee5',
                  }}>{f.icon}</div>
                  <div>
                    <p style={{
                      fontSize: 14, fontWeight: 600, color: 'rgba(244,248,255,0.92)',
                      marginBottom: 2,
                    }}>{f.title}</p>
                    <p style={{ fontSize: 12, color: '#5289d9', lineHeight: 1.5 }}>{f.desc}</p>
                  </div>
                </li>
              ))}
            </ul>

            {/* Stats row */}
            <div aria-label="平台数据" style={{
              display: 'flex', gap: 32, paddingTop: 32,
              borderTop: '1px solid rgba(255,255,255,0.1)',
              marginTop: 32,
            }}>
              {[
                { num: '12k+', label: '活跃用户' },
                { num: '98.6%', label: '任务成功率' },
                { num: '300ms', label: '平均响应' },
              ].map((s) => (
                <div key={s.label}>
                  <p style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 26, fontWeight: 700, color: '#f4f8ff',
                    letterSpacing: '-0.03em', lineHeight: 1, marginBottom: 4,
                  }}>{s.num}</p>
                  <p style={{
                    fontSize: 11, fontWeight: 500, color: '#5289d9',
                    letterSpacing: '0.04em',
                  }}>{s.label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </aside>

      {/* ═══ Right Panel (Form) ═══ */}
      <main style={{
        flex: 1, background: '#ffffff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '48px 48px', minWidth: 0,
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>

          {/* Form header */}
          <header style={{ marginBottom: 36 }}>
            <h2 style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 32, fontWeight: 700, color: '#111827',
              letterSpacing: '-0.025em', lineHeight: 1.15, marginBottom: 8,
            }}>欢迎回来</h2>
            <p style={{ fontSize: 14, color: '#4b5563', lineHeight: 1.6 }}>
              登录您的玄机账户以继续使用
            </p>
          </header>

          {/* Third-party login */}
          <div role="group" aria-label="快捷登录" style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 22,
          }}>
            <button type="button" aria-label="企业微信登录" onClick={() => showToast('企业微信登录即将支持')} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              height: 42, border: '1.5px solid #e5e7eb', borderRadius: 10,
              background: 'white', cursor: 'pointer',
              fontFamily: 'inherit', fontSize: 13, fontWeight: 500, color: '#1f2937',
              transition: 'all 140ms cubic-bezier(0.25,1,0.5,1)',
            }}>
              <svg viewBox="0 0 20 20" fill="none" style={{ width: 16, height: 16, flexShrink: 0 }}>
                <ellipse cx="7.5" cy="8.5" rx="4" ry="3.2" stroke="#07C160" strokeWidth="1.5" />
                <ellipse cx="13.5" cy="7.5" rx="3.2" ry="2.6" stroke="#07C160" strokeWidth="1.3" />
                <path d="M3.5 14c0-1.7 1.8-3 4-3s4 1.3 4 3" stroke="#07C160" strokeWidth="1.3" strokeLinecap="round" />
                <path d="M11 13c0-1.3 1.1-2.3 2.5-2.3S16 11.7 16 13" stroke="#07C160" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              企业微信
            </button>
            <button type="button" aria-label="飞书登录" onClick={() => showToast('飞书登录即将支持')} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              height: 42, border: '1.5px solid #e5e7eb', borderRadius: 10,
              background: 'white', cursor: 'pointer',
              fontFamily: 'inherit', fontSize: 13, fontWeight: 500, color: '#1f2937',
              transition: 'all 140ms cubic-bezier(0.25,1,0.5,1)',
            }}>
              <svg viewBox="0 0 20 20" fill="none" style={{ width: 16, height: 16, flexShrink: 0 }}>
                <path d="M10 3L4 6.5v7L10 17l6-3.5v-7L10 3Z" stroke="#1F6EEB" strokeWidth="1.5" strokeLinejoin="round" />
                <path d="M4 6.5L10 10M16 6.5L10 10M10 10v7" stroke="#1F6EEB" strokeWidth="1" strokeLinejoin="round" opacity="0.4" />
              </svg>
              飞书
            </button>
          </div>

          {/* Divider */}
          <div aria-hidden="true" style={{
            display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22,
          }}>
            <div style={{ flex: 1, height: 1, background: '#e5e7eb' }} />
            <span style={{ fontSize: 12, color: '#9ca3af', fontWeight: 500, whiteSpace: 'nowrap' }}>账号密码登录</span>
            <div style={{ flex: 1, height: 1, background: '#e5e7eb' }} />
          </div>

          {/* Global error alert */}
          {globalError && (
            <div role="alert" aria-live="assertive" style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '12px 14px', borderRadius: 10,
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18, marginBottom: 16 }}>

              {/* Username field */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <label htmlFor="login-username" style={{
                  fontSize: 13, fontWeight: 600, color: '#1f2937', letterSpacing: '0.01em',
                }}>用户名 / 邮箱</label>
                <div style={{ position: 'relative' }}>
                  <input
                    id="login-username"
                    type="text"
                    value={username}
                    onChange={(e) => { setUsername(e.target.value); if (fieldErrors.username) setFieldErrors(f => ({ ...f, username: undefined })) }}
                    placeholder="请输入账号或邮箱"
                    autoComplete="username"
                    autoCapitalize="off"
                    spellCheck={false}
                    aria-required="true"
                    aria-describedby={fieldErrors.username ? 'username-err' : undefined}
                    style={{
                      width: '100%', height: 44, padding: '0 16px',
                      border: `1.5px solid ${fieldErrors.username ? '#dc2626' : '#e5e7eb'}`,
                      borderRadius: 10, background: 'white',
                      fontFamily: 'inherit', fontSize: 14, color: '#111827',
                      outline: 'none', WebkitAppearance: 'none',
                      boxShadow: fieldErrors.username ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                      transition: 'border-color 140ms, box-shadow 140ms',
                    }}
                    onFocus={(e) => {
                      if (!fieldErrors.username) {
                        e.target.style.borderColor = accent
                        e.target.style.boxShadow = `0 0 0 3px rgba(48,103,195,0.12)`
                      }
                    }}
                    onBlur={(e) => {
                      if (!fieldErrors.username) {
                        e.target.style.borderColor = '#e5e7eb'
                        e.target.style.boxShadow = 'none'
                      }
                    }}
                  />
                </div>
                {fieldErrors.username && (
                  <p id="username-err" role="alert" style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    fontSize: 12, color: '#dc2626', marginTop: -4,
                  }}>
                    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" style={{ width: 12, height: 12, flexShrink: 0 }}>
                      <circle cx="6" cy="6" r="5" /><path d="M6 4v2.5M6 8v.5" />
                    </svg>
                    {fieldErrors.username}
                  </p>
                )}
              </div>

              {/* Password field */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <label htmlFor="login-password" style={{
                  fontSize: 13, fontWeight: 600, color: '#1f2937', letterSpacing: '0.01em',
                }}>密码</label>
                <div style={{ position: 'relative' }}>
                  <input
                    id="login-password"
                    type={showPw ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); if (fieldErrors.password) setFieldErrors(f => ({ ...f, password: undefined })) }}
                    placeholder="请输入密码"
                    autoComplete="current-password"
                    aria-required="true"
                    aria-describedby={fieldErrors.password ? 'password-err' : undefined}
                    style={{
                      width: '100%', height: 44, padding: '0 44px 0 16px',
                      border: `1.5px solid ${fieldErrors.password ? '#dc2626' : '#e5e7eb'}`,
                      borderRadius: 10, background: 'white',
                      fontFamily: 'inherit', fontSize: 14, color: '#111827',
                      outline: 'none', WebkitAppearance: 'none',
                      boxShadow: fieldErrors.password ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                      transition: 'border-color 140ms, box-shadow 140ms',
                    }}
                    onFocus={(e) => {
                      if (!fieldErrors.password) {
                        e.target.style.borderColor = accent
                        e.target.style.boxShadow = `0 0 0 3px rgba(48,103,195,0.12)`
                      }
                    }}
                    onBlur={(e) => {
                      if (!fieldErrors.password) {
                        e.target.style.borderColor = '#e5e7eb'
                        e.target.style.boxShadow = 'none'
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw(!showPw)}
                    aria-label={showPw ? '隐藏密码' : '显示密码'}
                    style={{
                      position: 'absolute', right: 0, top: 0, bottom: 0, width: 44,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      cursor: 'pointer', color: '#9ca3af', background: 'none', border: 'none',
                      borderRadius: '0 10px 10px 0',
                      transition: 'color 140ms',
                    }}
                  >
                    {showPw ? (
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}>
                        <path d="M2 2l12 12M6.5 6.7A2 2 0 0 0 9.3 9.5M4 4.4C2.6 5.5 1.5 7 1.5 7S4 11.5 8 11.5c1 0 1.9-.3 2.7-.7M6.5 3.8C7 3.6 7.5 3.5 8 3.5c4 0 6.5 4.5 6.5 4.5s-.9 1.8-2.5 3.1" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}>
                        <path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8Z" />
                        <circle cx="8" cy="8" r="2" />
                      </svg>
                    )}
                  </button>
                </div>
                {fieldErrors.password && (
                  <p id="password-err" role="alert" style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    fontSize: 12, color: '#dc2626', marginTop: -4,
                  }}>
                    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" style={{ width: 12, height: 12, flexShrink: 0 }}>
                      <circle cx="6" cy="6" r="5" /><path d="M6 4v2.5M6 8v.5" />
                    </svg>
                    {fieldErrors.password}
                  </p>
                )}
              </div>
            </div>

            {/* Remember me + Forgot password */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 22,
            }}>
              <label style={{
                display: 'flex', alignItems: 'center', gap: 8,
                cursor: 'pointer', userSelect: 'none',
                minHeight: 44, paddingRight: 8,
              }}>
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  style={{
                    appearance: 'none', WebkitAppearance: 'none',
                    width: 18, height: 18,
                    border: `1.5px solid ${remember ? primary : '#d1d5db'}`,
                    borderRadius: 5, background: remember ? primary : 'white',
                    cursor: 'pointer', flexShrink: 0,
                    transition: 'all 140ms cubic-bezier(0.25,1,0.5,1)',
                    position: 'relative',
                  }}
                />
                {remember && (
                  <svg viewBox="0 0 16 16" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                    style={{ position: 'absolute', width: 10, height: 10, pointerEvents: 'none', marginLeft: -22, marginTop: -1 }}>
                    <path d="M3 8l3.5 3.5L13 4" />
                  </svg>
                )}
                <span style={{ fontSize: 13, color: '#374151' }}>记住我</span>
              </label>
              <button
                type="button"
                onClick={() => showToast('密码找回功能即将上线')}
                style={{
                  fontSize: 13, fontWeight: 500, color: primary,
                  background: 'none', border: 'none', cursor: 'pointer',
                  minHeight: 44, display: 'flex', alignItems: 'center',
                  fontFamily: 'inherit', padding: 0,
                }}
              >忘记密码？</button>
            </div>

            {/* Submit button */}
            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%', height: 46, background: loading ? primary : primary,
                color: 'white', border: 'none', borderRadius: 10,
                fontFamily: 'inherit', fontSize: 15, fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                letterSpacing: '0.01em', marginBottom: 20,
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                opacity: loading ? 0.55 : 1,
                transition: 'background 140ms, transform 140ms, box-shadow 140ms',
              }}
              onMouseEnter={(e) => {
                if (!loading) {
                  e.currentTarget.style.background = primaryHover
                  e.currentTarget.style.transform = 'translateY(-1px)'
                  e.currentTarget.style.boxShadow = '0 6px 24px rgba(37,84,160,0.28)'
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = primary
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = 'none'
              }}
              onMouseDown={(e) => {
                if (!loading) {
                  e.currentTarget.style.transform = 'translateY(0)'
                  e.currentTarget.style.boxShadow = 'none'
                }
              }}
              onMouseUp={(e) => {
                if (!loading) {
                  e.currentTarget.style.transform = 'translateY(-1px)'
                  e.currentTarget.style.boxShadow = '0 6px 24px rgba(37,84,160,0.28)'
                }
              }}
            >
              {loading ? (
                <span style={{
                  display: 'block', width: 18, height: 18,
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: 'white', borderRadius: '50%',
                  animation: 'login-spin 0.6s linear infinite',
                }} />
              ) : (
                <>
                  <span>登录账户</span>
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}>
                    <path d="M3 8h10M9 4l4 4-4 4" />
                  </svg>
                </>
              )}
            </button>

            {/* Register prompt */}
            <p style={{ textAlign: 'center', fontSize: 13, color: '#6b7280' }}>
              还没有账号？{' '}
              <button
                type="button"
                onClick={() => showToast('注册功能即将上线')}
                style={{
                  color: primary, fontWeight: 600, background: 'none', border: 'none',
                  cursor: 'pointer', fontFamily: 'inherit', fontSize: 13, padding: 0,
                }}
              >立即注册 →</button>
            </p>
          </form>

          {/* Footer */}
          <footer style={{
            marginTop: 32, paddingTop: 20,
            borderTop: '1px solid #f3f4f6',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>© 2025 玄机 XUANJI · AI 智能工作平台</span>
            <nav aria-label="页脚链接" style={{ display: 'flex', gap: 12 }}>
              <button type="button" onClick={() => showToast('隐私政策')} style={{ fontSize: 11, color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}>隐私政策</button>
              <button type="button" onClick={() => showToast('服务条款')} style={{ fontSize: 11, color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}>服务条款</button>
            </nav>
          </footer>
        </div>
      </main>

      {/* Toast */}
      {toast && (
        <div role="status" aria-live="polite" style={{
          position: 'fixed', bottom: 24, right: 24,
          background: '#111827', color: 'white',
          padding: '10px 20px', borderRadius: 10,
          fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
          fontSize: 13, fontWeight: 500, zIndex: 999,
          animation: 'login-toast-in 260ms cubic-bezier(0.25,1,0.5,1) both',
        }}>{toast}</div>
      )}

      {/* Keyframe animations + hover styles */}
      <style>{`
        @keyframes login-spin { to { transform: rotate(360deg); } }
        @keyframes login-toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .feature-item-hover:hover {
          background: rgba(255,255,255,0.08) !important;
        }

        /* Responsive */
        @media (max-width: 960px) {
          aside { padding: 36px !important; flex: none !important; }
          aside + main { padding: 40px 36px !important; }
          /* Hide stats on tablet */
          aside [aria-label="平台数据"] { display: none !important; }
        }
        @media (max-width: 560px) {
          aside { padding: 28px 24px !important; }
          aside + main { padding: 32px 20px !important; }
          /* Single column third-party */
          main [role="group"] { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  )
}
