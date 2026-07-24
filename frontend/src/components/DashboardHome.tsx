// --- Dashboard Home (content only, no input area) ---
import { useState, type ReactNode } from 'react'
import type { Session } from '../types'
import { formatRelativeTime } from '../utils/format'

// --- Quick action cards for dashboard ---
const DASH_ACTIONS = [
  { title: '写一份项目方案', desc: '基于需求自动生成结构清晰的项目方案文档，包含目标、里程碑与资源规划', prompt: '帮我写一份项目方案，包含需求梳理、技术选型和实施计划', iconBg: '#e8f1fb', iconColor: '#1a6fbf', icon: <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4"><path d="M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.4"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg> },
  { title: '分析市场数据', desc: '自动采集多源数据，生成可视化图表与深度洞察报告，支持导出 Excel/PPT', prompt: '帮我分析市场数据，生成一份分析报告', iconBg: '#e6f5ee', iconColor: '#2d9e6b', icon: <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4"><path d="M2 12l3.5-4 3 2 3.5-5L15 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/><path d="M2 14h12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg> },
  { title: '生成演示 PPT', desc: '一键将大纲转换为精美幻灯片，自动排版、配色、配图，支持在线预览与下载', prompt: '帮我生成一份演示PPT', iconBg: '#fef3dc', iconColor: '#b87c16', icon: <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4"><rect x="2" y="3" width="12" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.4"/><path d="M8 12v2M6 14h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/><path d="M6 7h4M6 9h2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg> },
  { title: '探索历史记忆', desc: '智能检索过往对话与文档，基于语义理解定位关键信息，支持跨会话关联', prompt: '搜索我的历史记忆，查找相关内容', iconBg: 'rgba(79, 110, 247, 0.1)', iconColor: '#4F6EF7', icon: <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4"><circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4"/><path d="M5.5 8h5M8 5.5v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg> },
]

// --- Onboarding example tasks for empty state ---
const EXAMPLE_TASKS = [
  { title: '帮我写一份周报', desc: '汇总本周工作进展，自动生成结构化周报', icon: '📝' },
  { title: '分析这份数据的趋势', desc: '上传数据文件，AI 自动识别趋势并给出洞察', icon: '📊' },
  { title: '帮我翻译这段英文', desc: '支持中英互译，保留专业术语与语境', icon: '🌐' },
]

export function DashboardHome({
  onSend,
  loading,
  username,
  sessions,
  onSessionSelect,
  onViewAllSessions,
  inputSlot,
}: {
  onSend: (text: string) => void
  loading: boolean
  username: string
  sessions: Session[]
  onSessionSelect: (id: string) => void
  onViewAllSessions?: () => void
  inputSlot?: ReactNode
}) {
  const [activeAction, setActiveAction] = useState<string | null>(null)

  const handleActionClick = (prompt: string, title: string) => {
    if (loading) return
    setActiveAction(title)
    onSend(prompt)
  }
  const recentSessions = sessions.slice(0, 5)
  const sessionIconColors = [
    'linear-gradient(135deg, #4F6EF7, #3D5CE5)',
    'linear-gradient(135deg, #10B981, #059669)',
    'linear-gradient(135deg, #8B5CF6, #7C3AED)',
    'linear-gradient(135deg, #F59E0B, #D97706)',
    'linear-gradient(135deg, #EF4444, #DC2626)'
  ]

  const hour = new Date().getHours()
  const greetText = hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'

  // Derive real stats from sessions data.
  const totalTasks = sessions.length
  const totalMessages = sessions.reduce((sum, s) => sum + (s.message_count || 0), 0)

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8 d-scroll" style={{ background: 'var(--bg-primary)' }}>
      {/* Greeting header */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        marginBottom: 'var(--space-8)',
      }} className="animate-fade-in-up">
        <div>
          <h2 style={{
            fontSize: 'var(--text-2xl)',
            fontWeight: 'var(--font-bold)',
            color: 'var(--text-primary)',
            margin: '0 0 var(--space-1) 0',
          }}>{greetText}，<strong>{username || 'Admin'}</strong></h2>
          <p style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--text-secondary)',
            margin: 0,
          }}>今天有什么需要处理的？</p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
          <span style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--text-tertiary)',
            background: 'var(--bg-tertiary)',
            padding: '3px 10px',
            borderRadius: 'var(--radius-sm)',
          }}>{totalTasks} 任务</span>
          <span style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--text-tertiary)',
            background: 'var(--bg-tertiary)',
            padding: '3px 10px',
            borderRadius: 'var(--radius-sm)',
          }}>{totalMessages} 消息</span>
        </div>
      </div>

      {/* Hero input slot — 输入优先，让用户第一眼就知道“从这里开始” */}
      {inputSlot && (
        <div style={{ marginBottom: 'var(--space-8)' }}>
          {inputSlot}
        </div>
      )}

      {/* Quick actions grid */}
      <section style={{ marginBottom: 'var(--space-10)' }}>
        <h3 style={{
          fontSize: 'var(--text-lg)',
          fontWeight: 'var(--font-bold)',
          color: 'var(--text-primary)',
          margin: '0 0 var(--space-5) 0',
          letterSpacing: '0.02em'
        }}>快捷操作</h3>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 'var(--space-4)'
        }}>
          {DASH_ACTIONS.map((a, i) => {
            const isActive = activeAction === a.title && loading
            return (
            <button
              key={a.title}
              onClick={() => handleActionClick(a.prompt, a.title)}
              disabled={loading}
              className="btn-press"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 'var(--space-2)',
                padding: 'var(--space-5)',
                borderRadius: 'var(--radius-lg)',
                background: 'var(--bg-secondary)',
                border: isActive ? '1px solid var(--primary-500)' : '1px solid var(--border-light)',
                cursor: loading ? 'default' : 'pointer',
                textAlign: 'left',
                opacity: loading && !isActive ? 0.6 : 1,
                transition: 'all var(--duration-fast) var(--ease-default)',
                animationDelay: `${i * 40}ms`,
              }}
              onMouseOver={(e) => {
                if (!loading) {
                  e.currentTarget.style.boxShadow = 'var(--shadow-md)'
                  e.currentTarget.style.transform = 'translateY(-2px)'
                }
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.boxShadow = 'none'
                e.currentTarget.style.transform = 'none'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', width: '100%' }}>
                <div style={{
                  width: 40,
                  height: 40,
                  borderRadius: 'var(--radius-md)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: a.iconBg,
                  color: a.iconColor,
                  flexShrink: 0,
                }}>
                  {isActive ? (
                    <svg className="animate-spin" width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="28" strokeDashoffset="8" />
                    </svg>
                  ) : a.icon}
                </div>
                <span style={{
                  fontSize: 'var(--text-sm)',
                  fontWeight: 'var(--font-semibold)',
                  color: 'var(--text-primary)',
                }}>{isActive ? '正在处理…' : a.title}</span>
              </div>
              <span style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}>{a.desc}</span>
            </button>
            )
          })}
        </div>
      </section>

      {/* Recent sessions list */}
      <section>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 'var(--space-4)'
        }}>
          <h3 style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--font-bold)',
            color: 'var(--text-primary)',
            margin: 0,
            letterSpacing: '0.02em'
          }}>最近会话</h3>
          <button
            onClick={onViewAllSessions}
            style={{
              color: 'var(--primary-500)',
              fontSize: '13px',
              fontWeight: '500',
              background: 'none',
              border: 'none',
              cursor: 'pointer'
            }}
          >查看全部 →</button>
        </div>

        {recentSessions.length === 0 ? (
          <div style={{
            padding: 'var(--space-6)',
            background: 'var(--bg-secondary)',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-light)'
          }}>
            <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', margin: '0 0 var(--space-4) 0' }}>还没有会话，试试这些任务开始吧 👇</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {EXAMPLE_TASKS.map((t) => (
                <button
                  key={t.title}
                  onClick={() => onSend(t.title)}
                  disabled={loading}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--space-3)',
                    padding: 'var(--space-3) var(--space-4)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border-light)',
                    background: 'var(--bg-primary)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'border-color 0.15s',
                  }}
                  onMouseOver={(e) => { e.currentTarget.style.borderColor = 'var(--primary-500)' }}
                  onMouseOut={(e) => { e.currentTarget.style.borderColor = 'var(--border-light)' }}
                >
                  <span style={{ fontSize: '18px' }}>{t.icon}</span>
                  <div>
                    <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-medium)', color: 'var(--text-primary)' }}>{t.title}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{t.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="card">
            {recentSessions.map((s, idx) => (
              <button
                key={s.id}
                onClick={() => onSessionSelect(s.id)}
                className="recent-item"
                style={{ borderLeft: `3px solid ${['#4F6EF7', '#10B981', '#8B5CF6', '#F59E0B', '#EF4444'][idx % 5]}` }}
              >
                <div className="list-item-avatar" style={{ background: sessionIconColors[idx % sessionIconColors.length] }}>
                  {(s.title || '新').charAt(0)}
                </div>
                <div className="list-item-content">
                  <div className="list-item-title">{s.title || '新任务'}</div>
                  <div className="list-item-subtitle">{s.message_count} 条消息</div>
                </div>
                <div className="list-item-meta">
                  <div className="list-item-time">{formatRelativeTime(s.updated_at)}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
