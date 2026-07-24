// --- Task list view (all sessions) ---
// 「任务」导航的主区视图：展示全部会话/任务列表。
// 点击某条 → 由 App 选中会话并切到工作台打开对话。
import type { Session } from '../types'
import { formatRelativeTime } from '../utils/format'

const AVATAR_COLORS = [
  'linear-gradient(135deg, #4F6EF7, #3D5CE5)',
  'linear-gradient(135deg, #10B981, #059669)',
  'linear-gradient(135deg, #8B5CF6, #7C3AED)',
  'linear-gradient(135deg, #F59E0B, #D97706)',
  'linear-gradient(135deg, #EF4444, #DC2626)',
]

export function TaskListView({
  sessions,
  activeSessionId,
  onSelect,
  onNewTask,
}: {
  sessions: Session[]
  activeSessionId: string | null
  onSelect: (id: string) => void
  onNewTask: () => void
}) {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-8 d-scroll" style={{ background: 'var(--bg-primary)' }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 'var(--space-6)',
      }}>
        <div>
          <h1 style={{
            fontSize: 'var(--text-2xl)',
            fontWeight: 'var(--font-bold)',
            color: 'var(--text-primary)',
            margin: 0,
          }}>任务</h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', margin: 'var(--space-1) 0 0 0' }}>
            共 {sessions.length} 个会话
          </p>
        </div>
        <button
          onClick={onNewTask}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-4)',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            background: 'linear-gradient(135deg, #4F6EF7, #7C5CFC)',
            color: '#fff',
            fontSize: '13px',
            fontWeight: 'var(--font-semibold)',
            cursor: 'pointer',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M8 3v10M3 8h10" />
          </svg>
          新建任务
        </button>
      </div>

      {sessions.length === 0 ? (
        <div style={{
          padding: 'var(--space-10)',
          background: 'var(--bg-secondary)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-light)',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '32px', marginBottom: 'var(--space-3)' }}>📋</div>
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)', margin: '0 0 var(--space-4) 0' }}>
            还没有任务，点击「新建任务」开始吧
          </p>
        </div>
      ) : (
        <div className="card">
          {sessions.map((s, idx) => (
            <button
              key={s.id}
              onClick={() => onSelect(s.id)}
              className="recent-item"
              style={{
                borderLeft: `3px solid ${['#4F6EF7', '#10B981', '#8B5CF6', '#F59E0B', '#EF4444'][idx % 5]}`,
                background: s.id === activeSessionId ? 'var(--bg-tertiary)' : undefined,
              }}
            >
              <div className="list-item-avatar" style={{ background: AVATAR_COLORS[idx % AVATAR_COLORS.length] }}>
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
    </div>
  )
}
