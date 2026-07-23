/**
 * NotificationBell —— 顶栏站内通知铃铛 + 下拉面板。
 *
 * 铃铛显示真实未读角标；点击展开下拉，拉取最近通知，支持标记单条/全部已读。
 * 点击面板外部关闭。所有请求失败静默降级（见 useNotifications）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNotifications } from '../hooks/useNotifications'
import { formatRelativeTime } from '../utils/format'

export function NotificationBell({ authToken }: { authToken: string }) {
  const { unreadCount, notifications, loading, loadList, markRead, markAllRead } =
    useNotifications(authToken)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev
      if (next) loadList()
      return next
    })
  }, [loadList])

  // 点击面板外部关闭。
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const badgeText = unreadCount > 99 ? '99+' : String(unreadCount)

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button className="topbar-button" title="通知" onClick={toggle} aria-label="通知">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span
            aria-label={`${unreadCount} 条未读`}
            style={{
              position: 'absolute',
              top: unreadCount > 9 ? 2 : 4,
              right: unreadCount > 9 ? 0 : 4,
              minWidth: 16,
              height: 16,
              padding: '0 4px',
              borderRadius: 8,
              background: 'var(--error-500)',
              color: '#fff',
              fontSize: 10,
              lineHeight: '16px',
              fontWeight: 600,
              textAlign: 'center',
              border: '2px solid var(--bg-secondary)',
              boxSizing: 'content-box',
            }}
          >
            {badgeText}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            width: 340,
            maxHeight: 440,
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-light)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 50,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 14px',
              borderBottom: '1px solid var(--border-light)',
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>通知</span>
            <button
              onClick={markAllRead}
              disabled={unreadCount === 0}
              style={{
                fontSize: 12,
                color: unreadCount === 0 ? 'var(--text-tertiary)' : 'var(--primary-600)',
                background: 'none',
                border: 'none',
                cursor: unreadCount === 0 ? 'default' : 'pointer',
              }}
            >
              全部已读
            </button>
          </div>

          <div style={{ overflowY: 'auto' }}>
            {loading ? (
              <div style={{ padding: '28px 0', textAlign: 'center', fontSize: 12.5, color: 'var(--text-tertiary)' }}>
                加载中…
              </div>
            ) : notifications.length === 0 ? (
              <div style={{ padding: '28px 0', textAlign: 'center', fontSize: 12.5, color: 'var(--text-tertiary)' }}>
                暂无通知
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => markRead(n.id)}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '10px 14px',
                    borderBottom: '1px solid var(--border-light)',
                    borderLeft: n.read ? '3px solid transparent' : '3px solid var(--primary-500)',
                    background: n.read ? 'transparent' : 'var(--bg-tertiary)',
                    cursor: 'pointer',
                  }}
                >
                  <div
                    style={{
                      fontSize: 12.5,
                      fontWeight: n.read ? 400 : 600,
                      color: 'var(--text-primary)',
                      marginBottom: n.body ? 3 : 0,
                    }}
                  >
                    {n.title}
                  </div>
                  {n.body && (
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                      {n.body}
                    </div>
                  )}
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 4 }}>
                    {formatRelativeTime(n.created_at)}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default NotificationBell
