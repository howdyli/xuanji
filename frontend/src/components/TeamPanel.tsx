/**
 * TeamPanel — 团队管理面板
 *
 * 功能：我的团队列表、创建团队、团队详情（成员+角色）、
 *       邀请码生成/复制、加入团队。
 */
import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────

interface Team {
  id: number
  name: string
  description: string
  owner_id: number
  role?: string
  created_at: string
  members?: TeamMember[]
}

interface TeamMember {
  user_id: number
  username: string
  role: string
  joined_at: string
}

interface Invitation {
  code: string
  expires_at: string
  created_at: string
}

interface TeamPanelProps {
  authToken: string
}

// ─── Role Badge ───────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = {
    owner: '#F59E0B',
    admin: '#3B82F6',
    member: '#6B7280',
  }
  const labels: Record<string, string> = {
    owner: '创建者',
    admin: '管理员',
    member: '成员',
  }
  return (
    <span
      className="text-[11px] px-1.5 py-0.5 rounded font-medium"
      style={{ color: colors[role] || '#6B7280', background: `${colors[role] || '#6B7280'}18` }}
    >
      {labels[role] || role}
    </span>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────

export default function TeamPanel({ authToken }: TeamPanelProps) {
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Create team form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')

  // Join team form
  const [showJoin, setShowJoin] = useState(false)
  const [joinCode, setJoinCode] = useState('')

  // Invitation
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [copied, setCopied] = useState(false)

  const fetchTeams = useCallback(async () => {
    try {
      const data = await apiFetch<{ teams?: Team[] }>('/teams')
      setTeams(data.teams || [])
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取团队失败')
    } finally {
      setLoading(false)
    }
  }, [authToken])

  useEffect(() => { fetchTeams() }, [fetchTeams])

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      await apiFetch('/teams', {
        method: 'POST',
        json: { name: newName, description: newDesc },
      })
      setNewName('')
      setNewDesc('')
      setShowCreate(false)
      fetchTeams()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    }
  }

  const handleJoin = async () => {
    if (!joinCode.trim()) return
    try {
      await apiFetch('/teams/join', {
        method: 'POST',
        json: { code: joinCode.trim() },
      })
      setJoinCode('')
      setShowJoin(false)
      fetchTeams()
    } catch (e) {
      setError(e instanceof Error ? e.message : '加入失败')
    }
  }

  const handleViewTeam = async (team: Team) => {
    try {
      const data = await apiFetch<{ team: Team }>(`/teams/${team.id}`)
      setSelectedTeam(data.team)
      setInvitation(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取详情失败')
    }
  }

  const handleInvite = async () => {
    if (!selectedTeam) return
    try {
      const data = await apiFetch<{ invitation: Invitation }>(`/teams/${selectedTeam.id}/invitations`, {
        method: 'POST',
      })
      setInvitation(data.invitation)
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成邀请码失败')
    }
  }

  const handleCopyCode = () => {
    if (invitation) {
      navigator.clipboard.writeText(invitation.code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleRemoveMember = async (uid: number) => {
    if (!selectedTeam) return
    try {
      await apiFetch(`/teams/${selectedTeam.id}/members/${uid}`, { method: 'DELETE' })
      handleViewTeam(selectedTeam)
    } catch (e) {
      setError(e instanceof Error ? e.message : '移除失败')
    }
  }

  // ── Render ──

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>加载中...</span>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: 'var(--border-light)' }}>
        <h2 className="text-[18px] font-bold" style={{ color: 'var(--text-primary)' }}>团队协作</h2>
        <div className="flex gap-2">
          <button
            onClick={() => { setShowJoin(true); setShowCreate(false) }}
            className="text-[13px] px-3 py-1.5 rounded-lg border transition-colors"
            style={{ borderColor: 'var(--border-light)', color: 'var(--text-secondary)' }}
          >
            加入团队
          </button>
          <button
            onClick={() => { setShowCreate(true); setShowJoin(false) }}
            className="text-[13px] px-3 py-1.5 rounded-lg text-white transition-colors"
            style={{ background: 'var(--accent-primary, #3B82F6)' }}
          >
            创建团队
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-3 text-[13px] text-red-500 bg-red-50 px-3 py-2 rounded-lg">{error}</div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="mx-6 mt-4 p-4 rounded-xl border" style={{ borderColor: 'var(--border-light)', background: 'var(--bg-secondary)' }}>
          <div className="text-[14px] font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>创建新团队</div>
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="团队名称（2-30 字）"
            className="w-full mb-2 px-3 py-2 text-[13px] rounded-lg border outline-none"
            style={{ borderColor: 'var(--border-light)', background: 'var(--bg-primary)' }}
          />
          <input
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            placeholder="团队描述（可选）"
            className="w-full mb-3 px-3 py-2 text-[13px] rounded-lg border outline-none"
            style={{ borderColor: 'var(--border-light)', background: 'var(--bg-primary)' }}
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-[13px] px-3 py-1.5 rounded-lg" style={{ color: 'var(--text-secondary)' }}>取消</button>
            <button onClick={handleCreate} className="text-[13px] px-4 py-1.5 rounded-lg text-white" style={{ background: 'var(--accent-primary, #3B82F6)' }}>创建</button>
          </div>
        </div>
      )}

      {/* Join form */}
      {showJoin && (
        <div className="mx-6 mt-4 p-4 rounded-xl border" style={{ borderColor: 'var(--border-light)', background: 'var(--bg-secondary)' }}>
          <div className="text-[14px] font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>通过邀请码加入</div>
          <div className="flex gap-2">
            <input
              value={joinCode}
              onChange={e => setJoinCode(e.target.value)}
              placeholder="输入邀请码"
              className="flex-1 px-3 py-2 text-[13px] rounded-lg border outline-none"
              style={{ borderColor: 'var(--border-light)', background: 'var(--bg-primary)' }}
            />
            <button onClick={handleJoin} className="text-[13px] px-4 py-1.5 rounded-lg text-white" style={{ background: 'var(--accent-primary, #3B82F6)' }}>加入</button>
          </div>
        </div>
      )}

      {/* Content area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {selectedTeam ? (
          /* ── Team Detail View ── */
          <div>
            <button
              onClick={() => { setSelectedTeam(null); setInvitation(null) }}
              className="text-[13px] mb-4 flex items-center gap-1"
              style={{ color: 'var(--accent-primary, #3B82F6)' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
              返回团队列表
            </button>

            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-[16px] font-bold" style={{ color: 'var(--text-primary)' }}>{selectedTeam.name}</h3>
                {selectedTeam.description && (
                  <p className="text-[13px] mt-1" style={{ color: 'var(--text-secondary)' }}>{selectedTeam.description}</p>
                )}
              </div>
              <button
                onClick={handleInvite}
                className="text-[13px] px-3 py-1.5 rounded-lg border transition-colors"
                style={{ borderColor: 'var(--accent-primary, #3B82F6)', color: 'var(--accent-primary, #3B82F6)' }}
              >
                邀请成员
              </button>
            </div>

            {/* Invitation code display */}
            {invitation && (
              <div className="mb-4 p-3 rounded-lg border" style={{ borderColor: 'var(--border-light)', background: 'var(--bg-secondary)' }}>
                <div className="text-[12px] mb-1" style={{ color: 'var(--text-secondary)' }}>邀请码（72小时有效）</div>
                <div className="flex items-center gap-2">
                  <code className="text-[15px] font-mono font-bold" style={{ color: 'var(--text-primary)' }}>{invitation.code}</code>
                  <button
                    onClick={handleCopyCode}
                    className="text-[12px] px-2 py-1 rounded"
                    style={{ background: copied ? '#10B981' : 'var(--accent-primary, #3B82F6)', color: '#fff' }}
                  >
                    {copied ? '已复制' : '复制'}
                  </button>
                </div>
              </div>
            )}

            {/* Members list */}
            <div className="text-[13px] font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
              成员 ({selectedTeam.members?.length || 0})
            </div>
            <div className="space-y-2">
              {(selectedTeam.members || []).map(m => (
                <div key={m.user_id} className="flex items-center justify-between py-2 px-3 rounded-lg" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="flex items-center gap-2">
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-bold text-white"
                      style={{ background: 'var(--accent-primary, #3B82F6)' }}
                    >
                      {m.username[0]?.toUpperCase()}
                    </div>
                    <span className="text-[13px]" style={{ color: 'var(--text-primary)' }}>{m.username}</span>
                    <RoleBadge role={m.role} />
                  </div>
                  {m.role !== 'owner' && (
                    <button
                      onClick={() => handleRemoveMember(m.user_id)}
                      className="text-[12px] px-2 py-1 rounded"
                      style={{ color: '#EF4444' }}
                    >
                      移除
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          /* ── Team List View ── */
          <div>
            {teams.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                  <circle cx="9" cy="7" r="4"/>
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                  <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                </svg>
                <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>还没有加入任何团队</span>
                <span className="text-[13px]" style={{ color: 'var(--text-tertiary)' }}>创建一个团队或通过邀请码加入</span>
              </div>
            ) : (
              <div className="grid gap-3">
                {teams.map(team => (
                  <button
                    key={team.id}
                    onClick={() => handleViewTeam(team)}
                    className="w-full text-left p-4 rounded-xl border transition-all hover:shadow-sm"
                    style={{ borderColor: 'var(--border-light)', background: 'var(--bg-secondary)' }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-9 h-9 rounded-lg flex items-center justify-center text-[14px] font-bold text-white"
                          style={{ background: 'linear-gradient(135deg, #3B82F6, #8B5CF6)' }}
                        >
                          {team.name[0]?.toUpperCase()}
                        </div>
                        <div>
                          <div className="text-[14px] font-semibold" style={{ color: 'var(--text-primary)' }}>{team.name}</div>
                          {team.description && (
                            <div className="text-[12px] mt-0.5" style={{ color: 'var(--text-secondary)' }}>{team.description}</div>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {team.role && <RoleBadge role={team.role} />}
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="2">
                          <polyline points="9 18 15 12 9 6"/>
                        </svg>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
