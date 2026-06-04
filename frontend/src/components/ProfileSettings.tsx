import { useState, useCallback } from 'react'

// ── Icons ──────────────────────────────────────────────────────────

const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)

const UserIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
)

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)

const LockIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
)

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

// ── Types ──────────────────────────────────────────────────────────

interface ProfileSettingsProps {
  authToken: string
  user: { id: number; username: string; created_at?: string }
  onClose: () => void
  onUserUpdated: (user: { id: number; username: string; created_at?: string }) => void
}

const API = '/api/frontend/auth'

// ── Component ──────────────────────────────────────────────────────

export function ProfileSettings({ authToken, user, onClose, onUserUpdated }: ProfileSettingsProps) {
  // ── Username editing ────────────────────────────────────────────
  const [editingName, setEditingName] = useState(false)
  const [newUsername, setNewUsername] = useState(user.username)
  const [nameLoading, setNameLoading] = useState(false)
  const [nameError, setNameError] = useState('')
  const [nameSuccess, setNameSuccess] = useState('')

  // ── Password changing ──────────────────────────────────────────
  const [showPassword, setShowPassword] = useState(false)
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdLoading, setPwdLoading] = useState(false)
  const [pwdError, setPwdError] = useState('')
  const [pwdSuccess, setPwdSuccess] = useState('')

  // ── Avatar colors (derived from username) ──────────────────────
  const avatarGradient = 'bg-gradient-to-br from-orange-300 to-pink-400'

  // ── Save username ──────────────────────────────────────────────
  const saveUsername = useCallback(async () => {
    setNameError('')
    setNameSuccess('')
    const trimmed = newUsername.trim()
    if (trimmed === user.username) {
      setEditingName(false)
      return
    }
    if (trimmed.length < 2 || trimmed.length > 20) {
      setNameError('用户名需要 2-20 个字符')
      return
    }
    setNameLoading(true)
    try {
      const res = await fetch(`${API}/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ username: trimmed }),
      })
      const data = await res.json()
      if (!res.ok) {
        setNameError(data.error || '修改失败')
        return
      }
      onUserUpdated(data.user)
      setNameSuccess('用户名已更新')
      setEditingName(false)
      setTimeout(() => setNameSuccess(''), 3000)
    } catch {
      setNameError('网络错误')
    } finally {
      setNameLoading(false)
    }
  }, [authToken, newUsername, user.username, onUserUpdated])

  // ── Change password ────────────────────────────────────────────
  const changePassword = useCallback(async () => {
    setPwdError('')
    setPwdSuccess('')
    if (!oldPwd || !newPwd) {
      setPwdError('请填写完整')
      return
    }
    if (newPwd.length < 6) {
      setPwdError('新密码至少 6 个字符')
      return
    }
    if (newPwd !== confirmPwd) {
      setPwdError('两次输入的密码不一致')
      return
    }
    setPwdLoading(true)
    try {
      const res = await fetch(`${API}/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
      })
      const data = await res.json()
      if (!res.ok) {
        setPwdError(data.error || '修改失败')
        return
      }
      setPwdSuccess('密码已更新')
      setOldPwd('')
      setNewPwd('')
      setConfirmPwd('')
      setTimeout(() => setPwdSuccess(''), 3000)
    } catch {
      setPwdError('网络错误')
    } finally {
      setPwdLoading(false)
    }
  }, [authToken, oldPwd, newPwd, confirmPwd])

  // ── Format creation date ───────────────────────────────────────
  const createdDate = user.created_at
    ? new Date(user.created_at).toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '未知'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[560px] max-h-[85vh] bg-white rounded-2xl shadow-2xl border border-gray-200/80 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <h2 className="text-[16px] font-semibold text-gray-800">用户信息</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-7">

          {/* ── Profile card ────────────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">用户档案</div>
            <div className="text-[12px] text-gray-400 mb-4">设置你的头像和显示名称</div>

            <div className="flex items-center gap-5 p-4 rounded-xl bg-gray-50 border border-gray-100">
              {/* Avatar */}
              <div className={`w-16 h-16 rounded-2xl ${avatarGradient} flex items-center justify-center text-white text-xl font-bold shrink-0 shadow-sm`}>
                {user.username.charAt(0).toUpperCase()}
              </div>

              {/* Name + editing */}
              <div className="flex-1 min-w-0">
                {editingName ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveUsername()
                          if (e.key === 'Escape') {
                            setEditingName(false)
                            setNewUsername(user.username)
                            setNameError('')
                          }
                        }}
                        autoFocus
                        maxLength={20}
                        className="flex-1 px-3 py-2 text-[14px] font-medium border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 bg-white"
                        placeholder="输入新用户名"
                      />
                      <button
                        onClick={saveUsername}
                        disabled={nameLoading}
                        className="px-4 py-2 rounded-lg bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors"
                      >
                        {nameLoading ? '保存中...' : '保存'}
                      </button>
                      <button
                        onClick={() => {
                          setEditingName(false)
                          setNewUsername(user.username)
                          setNameError('')
                        }}
                        className="px-3 py-2 rounded-lg border border-gray-200 text-gray-500 text-[13px] hover:bg-gray-50 transition-colors"
                      >
                        取消
                      </button>
                    </div>
                    {nameError && (
                      <div className="text-[12px] text-red-500">{nameError}</div>
                    )}
                  </div>
                ) : (
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[18px] font-semibold text-gray-900">{user.username}</span>
                      <button
                        onClick={() => {
                          setNewUsername(user.username)
                          setEditingName(true)
                          setNameError('')
                        }}
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 transition-colors"
                        title="编辑用户名"
                      >
                        <EditIcon />
                      </button>
                    </div>
                    <div className="text-[12px] text-gray-400 mt-1">点击名字编辑 · 注册于 {createdDate}</div>
                  </div>
                )}
                {nameSuccess && (
                  <div className="mt-2 text-[12px] text-emerald-600 font-medium">{nameSuccess}</div>
                )}
              </div>
            </div>
          </section>

          {/* ── Account security ────────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">账户安全</div>
            <div className="text-[12px] text-gray-400 mb-4">修改登录密码</div>

            <div className="space-y-3">
              {/* Old password */}
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300">
                  <LockIcon />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={oldPwd}
                  onChange={(e) => setOldPwd(e.target.value)}
                  placeholder="当前密码"
                  className="w-full pl-10 pr-10 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 bg-gray-50/50"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 transition-colors"
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>

              {/* New password */}
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300">
                  <LockIcon />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={newPwd}
                  onChange={(e) => setNewPwd(e.target.value)}
                  placeholder="新密码（至少 6 个字符）"
                  className="w-full pl-10 pr-4 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 bg-gray-50/50"
                />
              </div>

              {/* Confirm password */}
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300">
                  <LockIcon />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={confirmPwd}
                  onChange={(e) => setConfirmPwd(e.target.value)}
                  placeholder="确认新密码"
                  className="w-full pl-10 pr-4 py-2.5 text-[14px] border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 bg-gray-50/50"
                />
              </div>

              {/* Error / Success */}
              {pwdError && (
                <div className="px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-600">
                  {pwdError}
                </div>
              )}
              {pwdSuccess && (
                <div className="px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-[13px] text-emerald-700">
                  {pwdSuccess}
                </div>
              )}

              {/* Submit */}
              <div className="flex justify-end pt-1">
                <button
                  onClick={changePassword}
                  disabled={pwdLoading || !oldPwd || !newPwd || !confirmPwd}
                  className="px-5 py-2.5 rounded-xl bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  {pwdLoading ? '提交中...' : '修改密码'}
                </button>
              </div>
            </div>
          </section>

          {/* ── Account info ────────────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">账户信息</div>
            <div className="text-[12px] text-gray-400 mb-3">基本账户详情</div>

            <div className="space-y-0 divide-y divide-gray-100">
              <InfoRow label="用户 ID" value={String(user.id)} />
              <InfoRow label="用户名" value={user.username} />
              <InfoRow label="注册时间" value={createdDate} />
              <InfoRow label="认证方式" value="本地账户" />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

// ── Info row helper ────────────────────────────────────────────────

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-[13px] text-gray-500">{label}</span>
      <span className="text-[13px] font-medium text-gray-800">{value}</span>
    </div>
  )
}
