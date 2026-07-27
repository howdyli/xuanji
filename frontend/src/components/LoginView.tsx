/**
 * LoginView — 玄机 AI 登录界面 (v2.2 — 天蓝色设计稿版)
 * 左侧深海军蓝品牌区 + 右侧留白表单区
 * 设计稿：左侧折线图插画 + 品牌标语，右侧社交登录 + 账号表单
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
  navyTop: '#0c2340',   // 深海军蓝 — 顶
  navyBot: '#123057',   // 深海军蓝 — 底
  sky: '#3898EC',       // 天蓝强调色（与侧边栏统一）
  skyHover: '#2B7CD4',
  white: '#ffffff',
  gray50: '#f7f8fa',
  gray100: '#f1f3f5',
  gray200: '#e6e8eb',
  gray300: '#d5d9de',
  gray400: '#b6bcc4',
  gray500: '#8a929c',
  gray600: '#6b7280',
  gray700: '#4b5563',
  gray800: '#374151',
  gray900: '#1f2430',
  radiusMd: 10,
  radiusLg: 14,
} as const

export function LoginView({ theme = {}, onLogin }: {
  theme?: Theme
  onLogin: (token: string, user: LoginUser) => void
}) {
  const sky = theme.primaryColor || C.sky
  const skyHover = theme.primaryHover || C.skyHover

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [globalError, setGlobalError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({})
  const [toast, setToast] = useState('')

  const API_BASE = '/api/frontend'

  /* ── Helpers ─────────────────────────────────────────── */
  function clearErrors() {
    setFieldErrors({})
    setGlobalError('')
  }

  function validate(): boolean {
    const errs: { username?: string; password?: string } = {}
    if (!username.trim()) errs.username = '请输入邮箱或账号'
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
        setGlobalError(data?.error || data?.detail || '邮箱或密码不正确，请重试。')
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
    width: '100%', padding: '13px 16px',
    fontSize: 14.5, border: `1.5px solid ${C.gray200}`,
    borderRadius: C.radiusMd, background: C.gray50,
    color: C.gray900, outline: 'none', fontFamily: 'inherit',
    transition: 'all 0.2s ease', WebkitAppearance: 'none' as never,
    boxSizing: 'border-box',
  }

  function focusInput(el: HTMLInputElement, err?: string) {
    if (err) return
    el.style.borderColor = sky
    el.style.background = C.white
    el.style.boxShadow = `0 0 0 3px rgba(56,152,236,0.12)`
  }
  function blurInput(el: HTMLInputElement, err?: string) {
    if (err) return
    el.style.borderColor = C.gray200
    el.style.background = C.gray50
    el.style.boxShadow = 'none'
  }

  /* ── Render ──────────────────────────────────────────── */
  return (
    <div className="lv-root" style={{
      display: 'flex', minHeight: '100vh',
      fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', 'PingFang SC', sans-serif",
    }}>

      {/* ═══ Left Panel (Brand) ═══ */}
      <aside className="lv-brand" style={{
        flex: '1.08 1 54%', position: 'relative', overflow: 'hidden',
        background: `linear-gradient(165deg, ${C.navyTop} 0%, ${C.navyBot} 100%)`,
        padding: '52px 56px', display: 'flex', flexDirection: 'column',
      }}>
        {/* Ambient glows — 增加纵深质感 */}
        <div aria-hidden style={{
          position: 'absolute', top: -160, right: -120, width: 480, height: 480,
          borderRadius: '50%', pointerEvents: 'none',
          background: 'radial-gradient(circle, rgba(56,152,236,0.16) 0%, transparent 70%)',
        }} />
        <div aria-hidden style={{
          position: 'absolute', bottom: -120, left: -80, width: 360, height: 360,
          borderRadius: '50%', pointerEvents: 'none',
          background: 'radial-gradient(circle, rgba(56,152,236,0.08) 0%, transparent 70%)',
        }} />
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, position: 'relative', zIndex: 1 }}>
          <div style={{
            width: 42, height: 42, display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg viewBox="0 0 40 40" style={{ width: 42, height: 42 }} fill="none">
              {/* hexagon */}
              <path d="M20 3L33.86 11v16L20 35 6.14 27V11L20 3z"
                fill="rgba(56,152,236,0.12)" stroke={sky} strokeWidth="2" strokeLinejoin="round" />
              {/* inner ring + dot */}
              <circle cx="20" cy="19" r="5.5" fill="none" stroke={sky} strokeWidth="2" />
              <circle cx="20" cy="19" r="2" fill={sky} />
            </svg>
          </div>
          <span style={{ fontSize: 22, fontWeight: 700, color: 'white', letterSpacing: 1 }}>玄机</span>
        </div>

        {/* Hero */}
        <div style={{ position: 'relative', zIndex: 1, marginTop: 'auto', marginBottom: 'auto', paddingTop: 28 }}>
          <div style={{
            fontSize: 13, fontWeight: 600, letterSpacing: 4,
            textTransform: 'uppercase', color: 'rgba(255,255,255,0.42)', marginBottom: 22,
          }}>Ai platform</div>

          <h2 style={{
            fontSize: 44, fontWeight: 800, color: 'white',
            lineHeight: 1.2, letterSpacing: 0.5, margin: 0,
          }}>
            让每一次推理<br />
            都有迹可循
          </h2>

          <p style={{
            marginTop: 20, fontSize: 15, color: 'rgba(255,255,255,0.55)',
            lineHeight: 1.75, maxWidth: 480,
          }}>
            从数据到决策，玄机为你拆解每一步逻辑链路——透明、可追溯、可复现。
          </p>

          {/* Data visualization card — 图表 + 关键指标重排 */}
          <div className="lv-viz" style={{
            marginTop: 34, padding: '24px 28px 20px', maxWidth: 620, width: '100%',
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.09)',
            borderRadius: 16, backdropFilter: 'blur(4px)',
          }}>
            {/* legend */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: sky }} />
                <span style={{ fontSize: 13, fontWeight: 500, color: 'rgba(255,255,255,0.72)' }}>推理准确率 · 近 7 日</span>
              </div>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: sky }}>↑ 98.6%</span>
            </div>

            {/* chart */}
            <svg viewBox="0 0 440 170" style={{ width: '100%', display: 'block' }} fill="none">
              <defs>
                <linearGradient id="lv-area" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={sky} stopOpacity="0.26" />
                  <stop offset="100%" stopColor={sky} stopOpacity="0" />
                </linearGradient>
              </defs>
              {/* baseline grid */}
              <g stroke="rgba(255,255,255,0.08)" strokeWidth="1">
                <line x1="0" y1="42" x2="440" y2="42" />
                <line x1="0" y1="84" x2="440" y2="84" />
                <line x1="0" y1="126" x2="440" y2="126" />
              </g>
              {/* area */}
              <polygon className="lv-chart-area" points="20,120 160,86 300,96 420,40 420,150 20,150" fill="url(#lv-area)" />
              {/* line */}
              <polyline className="lv-chart-line" points="20,120 160,86 300,96 420,40"
                stroke={sky} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              {/* nodes */}
              {[[20, 120], [160, 86], [300, 96], [420, 40]].map(([x, y], i) => (
                <circle key={i} className="lv-chart-node" style={{ animationDelay: `${0.6 + i * 0.15}s` }}
                  cx={x} cy={y} r="4.5" fill={C.navyBot} stroke={sky} strokeWidth="2.5" />
              ))}
            </svg>

            {/* x-axis labels */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, padding: '0 2px', fontSize: 11, color: 'rgba(255,255,255,0.34)' }}>
              <span>第 1 步</span><span>第 3 步</span><span>第 5 步</span><span>第 7 步</span>
            </div>

            {/* key metrics */}
            <div style={{ display: 'flex', marginTop: 18, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
              {[
                { v: '12k+', label: '服务团队' },
                { v: '3.2k', label: '今日推理' },
                { v: '500ms', label: '平均响应' },
              ].map((m, i) => (
                <div key={m.label} style={{
                  flex: 1, textAlign: i === 0 ? 'left' : 'center',
                  borderLeft: i === 0 ? 'none' : '1px solid rgba(255,255,255,0.08)',
                }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: 'white', letterSpacing: -0.3 }}>{m.v}</div>
                  <div style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.4)', marginTop: 3 }}>{m.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer line */}
        <div style={{
          position: 'relative', zIndex: 1, display: 'flex', alignItems: 'center', gap: 14,
          fontSize: 13, color: 'rgba(255,255,255,0.5)',
        }}>
          <span style={{ width: 28, height: 1.5, background: 'rgba(255,255,255,0.3)' }} />
          © 2026 玄机 XUANJI · v2.0
        </div>
      </aside>

      {/* ═══ Right Panel (Login Form) ═══ */}
      <main className="lv-form" style={{
        flex: '0.92 1 46%', background: C.white,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        padding: '48px 72px',
      }}>
        <div className="lv-enter" style={{ maxWidth: 400, width: '100%', margin: '0 auto' }}>

          {/* Header */}
          <header style={{ marginBottom: 28 }}>
            <h2 style={{
              fontSize: 30, fontWeight: 700, color: C.gray900,
              letterSpacing: -0.3, marginBottom: 10,
            }}>欢迎回来</h2>
            <p style={{ fontSize: 14.5, color: C.gray500 }}>登录你的玄机账户，继续探索</p>
          </header>

          {/* Social buttons */}
          <div style={{ display: 'flex', gap: 14, marginBottom: 22 }}>
            <button type="button" onClick={() => showToast('微信登录即将上线')}
              style={socialBtnStyle}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.gray300; e.currentTarget.style.background = C.gray50 }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.gray200; e.currentTarget.style.background = C.white }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="#09BB07">
                <path d="M8.69 2C4.6 2 1.28 4.74 1.28 8.12c0 1.95 1.1 3.68 2.83 4.82l-.71 2.13 2.48-1.24c.88.24 1.82.37 2.81.37.24 0 .48-.01.71-.03a4.9 4.9 0 0 1-.2-1.38c0-2.98 2.9-5.4 6.48-5.4.24 0 .47.02.7.05C15.83 3.65 12.6 2 8.69 2zM6.2 6.9a.93.93 0 1 1 0-1.86.93.93 0 0 1 0 1.86zm5 0a.93.93 0 1 1 0-1.86.93.93 0 0 1 0 1.86z"/>
                <path d="M22.72 13.4c0-2.85-2.85-5.17-6.36-5.17s-6.36 2.32-6.36 5.17 2.85 5.17 6.36 5.17c.73 0 1.43-.1 2.08-.28l1.9.95-.52-1.58c1.72-.95 2.9-2.5 2.9-4.26zm-8.43-.8a.77.77 0 1 1 0-1.54.77.77 0 0 1 0 1.54zm4.14 0a.77.77 0 1 1 0-1.54.77.77 0 0 1 0 1.54z"/>
              </svg>
              <span>微信</span>
            </button>
            <button type="button" onClick={() => showToast('GitHub 登录即将上线')}
              style={socialBtnStyle}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.gray300; e.currentTarget.style.background = C.gray50 }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.gray200; e.currentTarget.style.background = C.white }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="#1f2430">
                <path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.66-.22.66-.48v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.56 9.56 0 0 1 2.5-.34c.85 0 1.7.12 2.5.34 1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.16.58.67.48A10.01 10.01 0 0 0 22 12c0-5.52-4.48-10-10-10z"/>
              </svg>
              <span>GitHub</span>
            </button>
          </div>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 22 }}>
            <span style={{ flex: 1, height: 1, background: C.gray200 }} />
            <span style={{ fontSize: 12.5, color: C.gray500, whiteSpace: 'nowrap' }}>或使用账号登录</span>
            <span style={{ flex: 1, height: 1, background: C.gray200 }} />
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
            {/* Email */}
            <div style={{ marginBottom: 20 }}>
              <label htmlFor="login-username" style={labelStyle}>邮箱</label>
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => { setUsername(e.target.value); if (fieldErrors.username) setFieldErrors(f => ({ ...f, username: undefined })) }}
                placeholder="name@xuanji.ai"
                autoComplete="username"
                style={{
                  ...inputBase,
                  borderColor: fieldErrors.username ? '#dc2626' : C.gray200,
                  boxShadow: fieldErrors.username ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                }}
                onFocus={(e) => focusInput(e.target, fieldErrors.username)}
                onBlur={(e) => blurInput(e.target, fieldErrors.username)}
              />
              {fieldErrors.username && <FieldError msg={fieldErrors.username} />}
            </div>

            {/* Password */}
            <div style={{ marginBottom: 18 }}>
              <label htmlFor="login-password" style={labelStyle}>密码</label>
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
                    paddingRight: 56,
                    borderColor: fieldErrors.password ? '#dc2626' : C.gray200,
                    boxShadow: fieldErrors.password ? '0 0 0 3px rgba(220,38,38,0.10)' : undefined,
                  }}
                  onFocus={(e) => focusInput(e.target, fieldErrors.password)}
                  onBlur={(e) => blurInput(e.target, fieldErrors.password)}
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  style={{
                    position: 'absolute', right: 14, top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: C.gray500, fontSize: 13, fontFamily: 'inherit', padding: 0,
                  }}
                >{showPw ? '隐藏' : '显示'}</button>
              </div>
              {fieldErrors.password && <FieldError msg={fieldErrors.password} />}
            </div>

            {/* Remember me + Forgot */}
            <div style={{
              display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', marginBottom: 26,
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', position: 'relative' }}>
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  style={{
                    appearance: 'none', width: 18, height: 18,
                    border: `1.5px solid ${remember ? sky : C.gray300}`,
                    borderRadius: 5, cursor: 'pointer',
                    background: remember ? sky : 'white',
                    transition: 'all 0.15s', flexShrink: 0,
                  }}
                />
                {remember && (
                  <svg viewBox="0 0 10 10" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    style={{ position: 'absolute', width: 9, height: 9, left: 4.5, pointerEvents: 'none' }}>
                    <path d="M1 5l2.5 2.5L9 1.5" />
                  </svg>
                )}
                <span style={{ fontSize: 13.5, color: C.gray700 }}>记住我</span>
              </label>
              <button
                type="button"
                onClick={() => showToast('密码找回功能即将上线')}
                style={{
                  fontSize: 13.5, color: sky, fontWeight: 500,
                  background: 'none', border: 'none',
                  cursor: 'pointer', fontFamily: 'inherit', padding: 0,
                }}
              >忘记密码?</button>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%', padding: 14,
                fontSize: 15.5, fontWeight: 600, color: 'white',
                background: sky,
                border: 'none', borderRadius: C.radiusMd, cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                fontFamily: 'inherit', opacity: loading ? 0.75 : 1,
                boxShadow: loading ? 'none' : '0 4px 14px rgba(56,152,236,0.28)',
                transition: 'all 0.2s ease',
              }}
              onMouseEnter={(e) => { if (!loading) { e.currentTarget.style.background = skyHover; e.currentTarget.style.boxShadow = '0 8px 22px rgba(56,152,236,0.38)'; e.currentTarget.style.transform = 'translateY(-1px)' } }}
              onMouseLeave={(e) => { if (!loading) { e.currentTarget.style.background = sky; e.currentTarget.style.boxShadow = '0 4px 14px rgba(56,152,236,0.28)'; e.currentTarget.style.transform = 'translateY(0)' } }}
              onMouseDown={(e) => { if (!loading) e.currentTarget.style.transform = 'translateY(0)' }}
              onMouseUp={(e) => { if (!loading) e.currentTarget.style.transform = 'translateY(-1px)' }}
            >
              {loading ? (
                <span style={{
                  display: 'block', width: 18, height: 18,
                  border: '2px solid rgba(255,255,255,0.35)',
                  borderTopColor: 'white', borderRadius: '50%',
                  animation: 'lv-spin 0.6s linear infinite',
                }} />
              ) : '登录'}
            </button>
          </form>

          {/* Register link */}
          <p style={{ textAlign: 'center', marginTop: 24, fontSize: 14, color: C.gray500 }}>
            还没有账户？
            <button
              type="button"
              onClick={() => showToast('注册功能即将上线')}
              style={{
                color: sky, fontWeight: 600, marginLeft: 4,
                background: 'none', border: 'none', cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 14, padding: 0,
              }}
            >立即注册</button>
          </p>
        </div>
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
        @keyframes lv-spin { to { transform: rotate(360deg); } }
        @keyframes lv-toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes lv-fade-up {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes lv-draw { to { stroke-dashoffset: 0; } }
        @keyframes lv-node-in {
          from { opacity: 0; transform: scale(0); }
          to { opacity: 1; transform: scale(1); }
        }
        @keyframes lv-area-in { from { opacity: 0; } to { opacity: 1; } }
        .lv-enter { animation: lv-fade-up 0.55s cubic-bezier(0.25,1,0.5,1) both; }
        .lv-chart-line {
          stroke-dasharray: 500; stroke-dashoffset: 500;
          animation: lv-draw 1.4s cubic-bezier(0.65,0,0.35,1) 0.3s forwards;
        }
        .lv-chart-area { opacity: 0; animation: lv-area-in 0.8s ease 1.2s forwards; }
        .lv-chart-node {
          opacity: 0; transform-box: fill-box; transform-origin: center;
          animation: lv-node-in 0.42s cubic-bezier(0.34,1.56,0.64,1) both;
        }
        @media (max-width: 1024px) {
          .lv-brand { display: none !important; }
          .lv-form { flex: 1 !important; padding: 48px 40px !important; }
        }
        @media (max-width: 480px) {
          .lv-form { padding: 40px 24px !important; }
        }
        @media (prefers-reduced-motion: reduce) {
          .lv-enter, .lv-chart-line, .lv-chart-area, .lv-chart-node { animation: none !important; }
          .lv-chart-line { stroke-dashoffset: 0 !important; }
          .lv-chart-area, .lv-chart-node { opacity: 1 !important; }
        }
      `}</style>
    </div>
  )
}

/* ─── Sub-components / shared styles ─────────────────────── */
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 13.5, fontWeight: 500,
  color: C.gray700, marginBottom: 8,
}

const socialBtnStyle: React.CSSProperties = {
  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
  padding: '11px 0', fontSize: 14, fontWeight: 500, color: C.gray800,
  background: C.white, border: `1.5px solid ${C.gray200}`,
  borderRadius: C.radiusMd, cursor: 'pointer', fontFamily: 'inherit',
  transition: 'all 0.2s ease',
}

function FieldError({ msg }: { msg: string }) {
  return (
    <p role="alert" style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#dc2626', marginTop: 6 }}>
      <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" style={{ width: 12, height: 12 }}>
        <circle cx="6" cy="6" r="5" /><path d="M6 4v2.5M6 8v.5" />
      </svg>
      {msg}
    </p>
  )
}
