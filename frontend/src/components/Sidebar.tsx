// --- Sidebar (navigation, recent tasks, user panel) ---
import { useState, useEffect, useRef } from 'react'
import type { Session } from '../types'
import { formatRelativeTime } from '../utils/format'
import { AutomationIcon, ModelConfigIcon, LibraryIcon, SettingsIcon } from './icons'
import { NAV_ITEMS, NAV_WORKFLOW, NAV_TOOLS } from './navConfig'

// --- Export Menu Component ---
function ExportMenu({
  sessionId,
  onExport,
  onClose,
}: {
  sessionId: string
  onExport: (sessionId: string, format: 'pdf' | 'markdown' | 'docx') => void
  onClose: () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const items: { format: 'pdf' | 'markdown' | 'docx'; icon: string; label: string }[] = [
    { format: 'pdf', icon: '📄', label: '导出为 PDF' },
    { format: 'markdown', icon: '📝', label: '导出为 Markdown' },
    { format: 'docx', icon: '📋', label: '导出为 DOCX' },
  ]

  return (
    <div
      ref={menuRef}
      style={{
        position: 'absolute',
        top: '100%',
        right: 0,
        marginTop: 4,
        background: 'white',
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        border: '1px solid rgba(0,0,0,0.08)',
        zIndex: 100,
        minWidth: 160,
        padding: '4px 0',
        overflow: 'hidden',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item) => (
        <button
          key={item.format}
          onClick={() => {
            onExport(sessionId, item.format)
            onClose()
          }}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 14px',
            fontSize: 13,
            color: '#1a1917',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
          }}
          onMouseOver={(e) => (e.currentTarget.style.background = '#f0efe9')}
          onMouseOut={(e) => (e.currentTarget.style.background = 'transparent')}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  )
}

export function Sidebar({
  activeNav,
  onNavChange,
  sessions,
  activeSessionId,
  onSessionSelect,
  onNewTask,
  search,
  onSearchChange,
  username,
  onLogout,
  onSettings,
  onProfile,
  collapsed,
  onToggleCollapse,
  onExport,
  exportingSessionId,
}: {
  activeNav: string
  onNavChange: (id: string) => void
  sessions: Session[]
  activeSessionId: string | null
  onSessionSelect: (id: string) => void
  onNewTask: () => void | Promise<void>
  search: string
  onSearchChange: (v: string) => void
  username: string
  onLogout: () => void
  onSettings: () => void
  onProfile: () => void
  collapsed?: boolean
  onToggleCollapse?: () => void
  onExport: (sessionId: string, format: 'pdf' | 'markdown' | 'docx') => void
  exportingSessionId: string | null
}) {
  const [expanded, setExpanded] = useState(!collapsed)
  const [exportMenuSessionId, setExportMenuSessionId] = useState<string | null>(null)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
const userMenuRef = useRef<HTMLDivElement>(null)
const userBtnRef = useRef<HTMLDivElement>(null)

useEffect(() => {
  if (!userMenuOpen) return
  const handleClickOutside = (e: MouseEvent) => {
    if (
      userMenuRef.current && !userMenuRef.current.contains(e.target as Node) &&
      userBtnRef.current && !userBtnRef.current.contains(e.target as Node)
    ) {
      setUserMenuOpen(false)
    }
  }
  const handleEscape = (e: KeyboardEvent) => {
    if (e.key === 'Escape') setUserMenuOpen(false)
  }
  document.addEventListener('mousedown', handleClickOutside)
  document.addEventListener('keydown', handleEscape)
  return () => {
    document.removeEventListener('mousedown', handleClickOutside)
    document.removeEventListener('keydown', handleEscape)
  }
}, [userMenuOpen])

  // Sync internal expanded state when collapsed prop changes (e.g. window resize)
  useEffect(() => {
    setExpanded(!collapsed)
  }, [collapsed])

  const filtered = sessions.filter((s) =>
    !search || (s.title || '').toLowerCase().includes(search.toLowerCase())
  )

  const renderNavItem = (item: typeof NAV_ITEMS[0], showLabel: boolean) => {
    const isActive = activeNav === item.id

    return (
      <button
        key={item.id}
        onClick={() => onNavChange(item.id)}
        className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
        title={item.label}
        style={showLabel ? { width: '100%', justifyContent: 'flex-start', gap: '10px', padding: '0 12px' } : undefined}
      >
        {item.icon}
        {showLabel && <span style={{ fontSize: '13px', fontWeight: 500, whiteSpace: 'nowrap' }}>{item.label}</span>}
      </button>
    )
  }

  return (
    <aside className="sidebar" style={{ width: expanded ? 'var(--sidebar-width-expanded)' : 'var(--sidebar-width-collapsed)' }}>
      {/* Logo + Brand */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: expanded ? '12px' : '0',
        width: expanded ? 'calc(100% - var(--space-4))' : 'auto',
        padding: expanded ? '0 12px' : '0',
        marginBottom: 'var(--space-5)',
      }}>
        <div className="sidebar-logo" style={{ flexShrink: 0, marginBottom: 0 }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <line x1="5" y1="7" x2="19" y2="7" stroke="white" strokeWidth="2" strokeLinecap="round"/>
            <line x1="5" y1="12" x2="19" y2="12" stroke="white" strokeWidth="2" strokeLinecap="round"/>
            <line x1="5" y1="17" x2="19" y2="17" stroke="white" strokeWidth="2" strokeLinecap="round"/>
            <line x1="12" y1="4" x2="12" y2="20" stroke="white" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>
        {expanded && (
          <div className="sidebar-brand-text">
            <span className="sidebar-brand-name">玄机</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="sidebar-brand-sub">AI Workspace</span>
              <span className="sidebar-pro-badge">PRO</span>
            </div>
          </div>
        )}
      </div>
      {expanded && (
        <div style={{ width: 'calc(100% - 24px)', height: '1px', background: 'rgba(26,58,82,0.08)', margin: '0 12px var(--space-4)' }} />
      )}

      {/* New task button */}
      <button
        onClick={onNewTask}
        className={expanded ? 'sidebar-new-task-btn' : ''}
        style={{
          width: expanded ? 'calc(100% - var(--space-4))' : '52px',
          height: 48,
          background: 'rgba(56,152,236,0.12)',
          border: '1px solid rgba(56,152,236,0.3)',
          color: '#1A3A52',
          borderRadius: 'var(--radius-lg)',
          fontSize: expanded ? '13px' : '20px',
          fontWeight: 600,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: expanded ? '8px' : '0',
          marginBottom: 'var(--space-4)',
          transition: 'all var(--duration-fast) var(--ease-default)',
          padding: expanded ? '0 var(--space-4)' : '0',
          overflow: 'hidden',
          whiteSpace: 'nowrap'
        }}
        onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.22)'}
        onMouseOut={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.12)'}
        title="新建任务"
      >
        {expanded ? (
          <>
            <svg width="14" height="14" viewBox="0 0 12 12" fill="none"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
            新建任务
          </>
        ) : '+'}
      </button>

      {/* Navigation icons */}
      <nav style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        width: '100%',
        padding: expanded ? '0 12px' : '0 var(--space-2.5)',
        flexShrink: 0,
      }}>
        {expanded && <div className="sidebar-section-title">工作</div>}
        {NAV_WORKFLOW.map((item) => renderNavItem(item, expanded))}

        {/* Separator between workflow and tools */}
        <div style={{
          width: '80%',
          height: '1px',
          background: 'rgba(26,58,82,0.06)',
          margin: '8px auto',
        }} />

        {expanded && <div className="sidebar-section-title">工具</div>}
        {NAV_TOOLS.map((item) => renderNavItem(item, expanded))}
      </nav>

      {/* Recent tasks (only when expanded) */}
      {expanded && (
        <div style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          padding: '0 var(--space-3)',
          marginTop: 'var(--space-4)',
          minHeight: 0,
          minWidth: 0,
          width: '100%',
        }} className="d-scroll">
          <div style={{
            fontSize: '10px',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            color: 'rgba(26,58,82,0.55)',
            marginBottom: 'var(--space-2)'
          }}>
            最近任务
          </div>
          {filtered.slice(0, 5).map((s) => (
            <div key={s.id} style={{ position: 'relative' }}>
              <button
                onClick={() => onSessionSelect(s.id)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '13px',
                  color: '#3D6076',
                  transition: 'all var(--duration-fast) var(--ease-default)',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  paddingRight: '32px',
                }}
                onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.08)'}
                onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '11px',
                  fontWeight: 600,
                  flexShrink: 0,
                  background: s.id === activeSessionId ? 'linear-gradient(135deg, #3898EC, #2B7CD4)' : 'rgba(26,58,82,0.08)',
                  color: s.id === activeSessionId ? 'white' : '#3D6076'
                }}>
                  {(s.title || '新').charAt(0)}
                </div>
                <span style={{
                  flex: 1,
                  textAlign: 'left',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {s.title || '新任务'}
                </span>
                <span style={{fontSize: '11px', color: '#8BAFC4'}}>
                  {formatRelativeTime(s.updated_at)}
                </span>
              </button>
              {/* Export "..." menu button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setExportMenuSessionId(exportMenuSessionId === s.id ? null : s.id)
                }}
                style={{
                  position: 'absolute',
                  top: 4,
                  right: 4,
                  width: 24,
                  height: 24,
                  borderRadius: 4,
                  background: exportMenuSessionId === s.id ? 'rgba(56,152,236,0.12)' : 'transparent',
                  border: 'none',
                  color: '#6B93AA',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 14,
                  opacity: exportMenuSessionId === s.id ? 1 : 0,
                  transition: 'opacity 0.15s',
                }}
                className="session-export-btn"
                title="导出会话"
              >
                {exportingSessionId === s.id ? (
                  <span className="animate-spin" style={{ display: 'inline-block', fontSize: 12 }}>⟳</span>
                ) : '⋯'}
              </button>
              {exportMenuSessionId === s.id && (
                <ExportMenu
                  sessionId={s.id}
                  onExport={onExport}
                  onClose={() => setExportMenuSessionId(null)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Collapse toggle button */}
      <button
        onClick={() => {
          setExpanded(!expanded)
          if (onToggleCollapse) onToggleCollapse()
        }}
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          background: 'rgba(26,58,82,0.06)',
          border: 'none',
          color: '#4A6B82',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: 'var(--space-3) auto 0',
          flexShrink: 0,
          transition: 'all var(--duration-fast) var(--ease-default)'
        }}
        title={expanded ? "折叠侧边栏" : "展开侧边栏"}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform var(--duration-normal) var(--ease-default)'
          }}
        >
          <polyline points="15 18 9 12 15 6"/>
        </svg>
      </button>

      {/* User panel */}
      <div style={{
        marginTop: 'auto',
        paddingTop: 'var(--space-2)',
        flexShrink: 0,
        borderTop: '1px solid rgba(26,58,82,0.1)',
        position: 'relative',
        width: '100%',
        paddingLeft: expanded ? 'var(--space-2)' : '0',
        paddingRight: expanded ? 'var(--space-2)' : '0',
      }}>
        {/* Floating menu */}
        {userMenuOpen && (
          <div ref={userMenuRef} style={{
            position: 'absolute',
            bottom: '100%',
            left: expanded ? 'var(--space-3)' : '50%',
            transform: expanded ? 'none' : 'translateX(-50%)',
            marginBottom: '8px',
            background: 'rgba(255, 255, 255, 0.97)',
            backdropFilter: 'blur(12px)',
            borderRadius: '12px',
            padding: '8px',
            minWidth: '180px',
            boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
            zIndex: 100,
            display: 'flex',
            flexDirection: 'column',
            gap: '2px',
          }}>
            {[
              { id: 'automation', label: '转化', icon: <AutomationIcon /> },
              { id: 'model-config', label: '模型配置', icon: <ModelConfigIcon /> },
              { id: 'library', label: '资料库', icon: <LibraryIcon /> },
            ].map(item => (
              <button
                key={item.id}
                onClick={() => { onNavChange(item.id); setUserMenuOpen(false) }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: 'transparent',
                  border: 'none',
                  color: '#3D6076',
                  cursor: 'pointer',
                  fontSize: '13px',
                  transition: 'background 0.12s',
                  width: '100%',
                  textAlign: 'left',
                }}
                onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.08)'}
                onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            ))}
            <div style={{ height: '1px', background: 'rgba(26,58,82,0.08)', margin: '4px 0' }} />
            <button
              onClick={() => { onProfile(); setUserMenuOpen(false) }}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '13px',
                color: '#3D6076',
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.08)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
              </svg>
              <span>个人资料</span>
            </button>
            <button
              onClick={() => { onSettings(); setUserMenuOpen(false) }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '8px 12px',
                borderRadius: '8px',
                background: 'transparent',
                border: 'none',
                color: '#3D6076',
                cursor: 'pointer',
                fontSize: '13px',
                transition: 'background 0.12s',
                width: '100%',
                textAlign: 'left',
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.08)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
            >
              <SettingsIcon />
              <span>设置</span>
            </button>
            <button
              onClick={() => { onLogout(); setUserMenuOpen(false) }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '8px 12px',
                borderRadius: '8px',
                background: 'transparent',
                border: 'none',
                color: 'rgba(220,60,60,0.85)',
                cursor: 'pointer',
                fontSize: '13px',
                transition: 'background 0.12s',
                width: '100%',
                textAlign: 'left',
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'rgba(56,152,236,0.08)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              <span>退出登录</span>
            </button>
          </div>
        )}

        {/* User panel button (div+role to allow nested settings button) */}
        <div className="sidebar-user-panel-card">
        <div
          ref={userBtnRef}
          role="button"
          tabIndex={0}
          onClick={() => setUserMenuOpen(!userMenuOpen)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setUserMenuOpen(!userMenuOpen) } }}
          style={{
            width: expanded ? '100%' : '40px',
            height: expanded ? '48px' : '40px',
            borderRadius: expanded ? 'var(--radius-md)' : '50%',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: expanded ? 'flex-start' : 'center',
            gap: '10px',
            padding: expanded ? '0 12px' : '0',
            margin: expanded ? '0' : '0 auto',
            transition: 'all var(--duration-fast) var(--ease-default)',
          }}
          onMouseOver={(e) => e.currentTarget.style.background = expanded ? 'rgba(56,152,236,0.08)' : 'transparent'}
          onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
          title={`${username} - 点击打开菜单`}
        >
          {/* Avatar with online indicator */}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <div style={{
              width: expanded ? 36 : 40,
              height: expanded ? 36 : 40,
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #10B981, #059669)',
              color: 'white',
              fontWeight: 600,
              fontSize: expanded ? 13 : 14,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              boxShadow: '0 2px 8px rgba(16,185,129,0.3)',
            }}>
              {username.charAt(0).toUpperCase()}
            </div>
            {/* Online indicator */}
            <div style={{
              position: 'absolute',
              bottom: 0,
              right: 0,
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#10B981',
              border: '2px solid #E9F3FB',
            }} />
          </div>
          {expanded && (
            <>
              <div style={{ flex: 1, textAlign: 'left', overflow: 'hidden' }}>
                <div style={{ fontSize: '13px', fontWeight: 500, color: '#1A3A52', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{username}</div>
                <div style={{ fontSize: '11px', color: '#3898EC', whiteSpace: 'nowrap', fontWeight: 500 }}>PRO 会员</div>
              </div>
              {/* Dropdown arrow */}
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6B93AA" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, transform: userMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </>
          )}
        </div>
        </div>
      </div>
    </aside>
  )
}
