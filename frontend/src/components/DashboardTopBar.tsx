// --- Top bar ---
import { NAV_ITEMS, EXPANDABLE_ITEMS } from './navConfig'
import { NotificationBell } from './NotificationBell'

export function DashboardTopBar({ onOpenDrawer, isHome, activeNav, username, onSearchClick, authToken }: { onOpenDrawer: () => void; isHome?: boolean; activeNav?: string; username?: string; onSearchClick?: () => void; authToken: string }) {
  const hour = new Date().getHours()
  const greetText = hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'

  if (!isHome) {
    // Non-home views: dynamic breadcrumb bar
    const breadcrumbLabel = [...NAV_ITEMS, ...EXPANDABLE_ITEMS].find(item => item.id === activeNav)?.label || '工作台'
    return (
      <div className="topbar" style={{ borderBottom: 'none', boxShadow: 'var(--shadow-xs)', background: 'var(--bg-primary)' }}>
        <nav style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1.5)', fontSize: '13px', color: 'var(--text-tertiary)' }} aria-label="面包屑">
          <span>玄机</span>
          <span style={{ opacity: 0.4 }}>/</span>
          <span style={{ fontWeight: 'var(--font-medium)', color: 'var(--text-primary)' }}>{breadcrumbLabel}</span>
        </nav>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#10B981', display: 'inline-block' }} />
            <span>AI Ready</span>
          </div>
          <button className="topbar-button" title="智能配置" onClick={onOpenDrawer}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          <NotificationBell authToken={authToken} />
        </div>
      </div>
    )
  }

  // Home view: full top bar with tabs and search
  return (
    <div className="topbar" style={{ borderBottom: 'none', boxShadow: 'var(--shadow-xs)' }}>
      {/* Left section: Title + Tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-8)' }}>
        <h1 className="topbar-title">工作台</h1>
        <div className="tabs-container">
          <button className={`tab-button ${true ? 'active' : ''}`}>全部</button>
          <button className="tab-button">进行中</button>
          <button className="tab-button">已完成</button>
        </div>
      </div>

      {/* Right section: Search icon + Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        {/* Search icon button */}
        <button className="topbar-button" title="搜索 (⌘K)" onClick={onSearchClick} style={{ cursor: 'pointer' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
        </button>

        {/* Notification button */}
        <NotificationBell authToken={authToken} />

        {/* Settings button */}
        <button
          className="topbar-button"
          title="智能配置"
          onClick={onOpenDrawer}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
    </div>
  )
}
