import { useState, useCallback, useEffect, useRef } from 'react'
import type { Message, Session, ApiResponse, CurrentUser } from './types'

// --- Extracted components ---
import { Sidebar } from './components/Sidebar'
import { DashboardHome } from './components/DashboardHome'
import { ComingSoonView } from './components/ComingSoonView'
import { ChatMessages } from './components/ChatView'
import { UnifiedInputBar } from './components/UnifiedInputBar'
import { DashboardTopBar } from './components/DashboardTopBar'
import { ConfigDrawer } from './components/ConfigDrawer'
import { ExploreIcon } from './components/icons'

// --- Feature views / shared components ---
import { SkillManagerView } from './components/SkillManagerView'
import { MarketplaceView } from './components/MarketplaceView'
import { WorkspaceView } from './components/WorkspaceView'
import { LoginView } from './components/LoginView'
import { AutomationManagerView } from './components/AutomationManagerView'
import { ThemeProvider } from './components/ThemeContext'
import { LibraryView } from './components/LibraryView'
import { AppearanceSettings } from './components/AppearanceSettings'
import { ProfileSettings } from './components/ProfileSettings'
import { ModelConfigView } from './components/ModelConfigView'
import GlobalSearchView from './components/GlobalSearchView'

// ✅ P1 集成：导入 UX 优化组件库
import { LoadingStates } from './components/UXComponents'

// --- Config ---
const API_BASE = '/api/frontend'
// ROUTING_KEY is now dynamically constructed: `p2p:web_${username}`

// --- Main App ---
function App() {
  // Auth state
  const [authToken, setAuthToken] = useState<string | null>(
    () => localStorage.getItem('auth_token'),
  )
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [authLoading, setAuthLoading] = useState(true)

  const [messages, setMessages] = useState<Message[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)

  const [activeNav, setActiveNav] = useState('assistant')
  const [search, setSearch] = useState('')
  const [activeExpert] = useState<string | null>(
    () => localStorage.getItem('active_expert'),
  )
  const [showAppearance, setShowAppearance] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Global Cmd+K → switch to search view
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setActiveNav('connector')
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // Auto-collapse sidebar on small screens (< 1024px)
  const [sidebarVisible, setSidebarVisible] = useState(
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true,
  )
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    typeof window !== 'undefined' ? window.innerWidth < 1024 : false,
  )
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  )
  const activeSessionIdRef = useRef(activeSessionId)
  activeSessionIdRef.current = activeSessionId
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Verify token on mount
  useEffect(() => {
    if (!authToken) {
      setAuthLoading(false)
      return
    }
    fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error('invalid token')
        return r.json()
      })
      .then((data) => {
        setCurrentUser(data.user)
      })
      .catch(() => {
        // Token is invalid — clear it
        localStorage.removeItem('auth_token')
        setAuthToken(null)
        setCurrentUser(null)
      })
      .finally(() => setAuthLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleLogin = useCallback((token: string, user: CurrentUser) => {
    localStorage.setItem('auth_token', token)
    setAuthToken(token)
    setCurrentUser(user)
  }, [])

  const handleLogout = useCallback(async () => {
    if (authToken) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${authToken}` },
        })
      } catch { /* ignore */ }
    }
    localStorage.removeItem('auth_token')
    setAuthToken(null)
    setCurrentUser(null)
    setMessages([])
    setSessions([])
    setActiveSessionId(null)
  }, [authToken])

  // Auto-toggle sidebar based on viewport width
  useEffect(() => {
    const onResize = () => {
      const w = window.innerWidth
      setSidebarVisible(w >= 768)
      setSidebarCollapsed(w < 1024)
      setIsMobile(w < 768)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Helper to fetch sessions list
  const fetchSessions = useCallback(() => {
    if (!authToken) return
    fetch(`${API_BASE}/sessions`, {
      headers: { Authorization: `Bearer ${authToken}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.sessions) setSessions(data.sessions)
      })
      .catch(() => {})
  }, [authToken])

  // Load sessions on mount (only when authenticated)
  useEffect(() => {
    if (authToken && currentUser) fetchSessions()
  }, [authToken, currentUser, fetchSessions])

  // Poll sessions every 30s + refresh on tab focus for near-real-time counters
  useEffect(() => {
    if (!authToken) return
    const poll = setInterval(fetchSessions, 30_000)
    const onFocus = () => fetchSessions()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') fetchSessions()
    })
    return () => {
      clearInterval(poll)
      window.removeEventListener('focus', onFocus)
    }
  }, [authToken, fetchSessions])

  // Load messages when a session is selected
  const handleSelectSession = useCallback(async (id: string) => {
    if (!authToken) return
    setActiveSessionId(id)
    setHistoryLoading(true)
    try {
      const res = await fetch(`${API_BASE}/sessions/${id}/messages`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      const data = await res.json()
      if (data.messages) {
        setMessages(data.messages.map((m: any) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          timestamp: m.timestamp || new Date().toISOString(),
        })))
      } else {
        setMessages([])
      }
    } catch {
      setMessages([])
    } finally {
      setHistoryLoading(false)
    }
  }, [authToken])

  // Navigate to session from GlobalSearch results
  const handleNavigateToSession = useCallback((sessionId: string) => {
    handleSelectSession(sessionId)
    setActiveNav('assistant')
  }, [handleSelectSession])

  const handleSend = useCallback(
    async (text: string) => {
      if (!authToken) return
      const now = new Date().toISOString()
      setMessages((prev) => [
        ...prev,
        { id: `user_${Date.now()}`, role: 'user', content: text, timestamp: now },
      ])
      setLoading(true)



      try {
        const res = await fetch(`${API_BASE}/message`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify({
            content: text,
            session_id: activeSessionIdRef.current || undefined,
            routing_key: `p2p:web_${currentUser?.username || 'anonymous'}`,
            sender_id: currentUser?.username || 'web_user',
            expert: activeExpert || undefined,
          }),
        })
        const data: ApiResponse = await res.json()
        setMessages((prev) => [
          ...prev,
          {
            id: data.msg_id,
            role: 'assistant',
            content: data.reply || '(空回复)',
            timestamp: new Date().toISOString(),
          },
        ])
        if (data.session_id) {
          setActiveSessionId(data.session_id)
          // Refresh sessions list to pick up new/updated session
          fetchSessions()
        }
      } catch (err) {
        // ✅ P1 集成：使用 ErrorDisplay 替换简单错误文本
        const errorMessage = err instanceof Error ? err.message : String(err)
        const errorType = errorMessage.includes('timeout') ? 'network_timeout' as const
          : errorMessage.includes('401') || errorMessage.includes('403') ? 'permission_denied' as const
          : errorMessage.includes('429') ? 'quota_exceeded' as const
          : 'server_error' as const

        setMessages((prev) => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: `[ERROR_DISPLAY:${errorType}:${errorMessage}]`,  // 特殊标记，由 MessageBubble 解析
            timestamp: new Date().toISOString(),
          },
        ])
      } finally {
        setLoading(false)
      }
    },
    [authToken, fetchSessions, activeExpert]
  )

  const handleNewTask = useCallback(async () => {
    setActiveSessionId(null)
    setMessages([])
    // Ensure we land on the workbench so the fresh conversation is visible
    // even when the user triggers this from Search / Skills views.
    setActiveNav('assistant')
    // Ask backend to create a new session so subsequent messages
    // land in a fresh conversation instead of the previous active one.
    try {
      const r = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}` },
      })
      if (r.ok) {
        const data = await r.json()
        setActiveSessionId(data.session_id)
      }
    } catch {
      // Fallback: the backend will create a session on first message
    }
    fetchSessions()
  }, [authToken, fetchSessions])

  // Export session handler
  const [exportingSessionId, setExportingSessionId] = useState<string | null>(null)
  const handleExport = useCallback(async (sessionId: string, format: 'pdf' | 'markdown' | 'docx') => {
    try {
      setExportingSessionId(sessionId)
      const token = localStorage.getItem('auth_token')
      const response = await fetch(
        `/api/frontend/sessions/${sessionId}/export?format=${format}`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (!response.ok) throw new Error('Export failed')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${sessionId}.${format === 'markdown' ? 'md' : format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export error:', err)
    } finally {
      setExportingSessionId(null)
    }
  }, [])

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault()
        handleNewTask()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleNewTask])

  // Render login page if not authenticated
  if (!authToken || !currentUser) {
    if (authLoading) {
      return (
        <div className="h-dvh w-dvw flex items-center justify-center bg-[#f8f9fa]">
          {/* ✅ P1 集成：使用 LoadingStates pulse 变体 */}
          <div className="flex flex-col items-center gap-4">
            <LoadingStates variant="pulse" size="lg" text="加载中..." />
            <span className="text-gray-400 text-[13px]">正在验证身份…</span>
          </div>
        </div>
      )
    }
    return <LoginView onLogin={handleLogin} />
  }

  // On mobile the sidebar is shown as a full-width overlay, so the desktop
  // "collapsed" (icon-only) state must not apply there.
  const sidebarShowsCollapsed = !isMobile && sidebarCollapsed

  return (
    <ThemeProvider>
    <div className="h-dvh w-dvw flex overflow-hidden relative" style={{ background: 'var(--bg-primary)' }}>
      {/* Hamburger menu button - visible only on mobile (< 768px) when sidebar is hidden */}
      {!sidebarVisible && (
        <button
          onClick={() => setSidebarVisible(true)}
          className="md:hidden fixed top-4 left-4 z-50 w-10 h-10 rounded-lg bg-white shadow-md flex items-center justify-center border border-slate-200"
          title="打开菜单"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-700">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      )}

      {/* Sidebar - responsive: hidden on mobile, collapsed on tablet, expanded on desktop */}
      {sidebarVisible && (
        <>
          {/* Mobile overlay backdrop */}
          <div
            className="md:hidden fixed inset-0 bg-black/30 z-30"
            onClick={() => setSidebarVisible(false)}
          />
          <div
            className="fixed md:static inset-y-0 left-0 z-40 shrink-0 shadow-xl md:shadow-none"
            style={{ width: sidebarShowsCollapsed ? 'var(--sidebar-width-collapsed)' : 'var(--sidebar-width-expanded)' }}
          >
            <Sidebar
              activeNav={activeNav}
              onNavChange={(id) => {
                setActiveNav(id)
                if (window.innerWidth < 768) setSidebarVisible(false)
              }}
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSessionSelect={(id) => {
                handleSelectSession(id)
                if (window.innerWidth < 768) setSidebarVisible(false)
              }}
              onNewTask={handleNewTask}
              search={search}
              onSearchChange={setSearch}
              username={currentUser.username}
              onLogout={handleLogout}
              onSettings={() => setShowAppearance(true)}
              onProfile={() => setShowProfile(true)}
              collapsed={sidebarShowsCollapsed}
              onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
              onExport={handleExport}
              exportingSessionId={exportingSessionId}
            />
          </div>
        </>
      )}

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        <DashboardTopBar onOpenDrawer={() => setDrawerOpen(true)} isHome={messages.length === 0 && !historyLoading && activeNav === 'assistant'} activeNav={activeNav} username={currentUser.username} onSearchClick={() => setActiveNav('connector')} />
        {activeNav === 'workspace' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <WorkspaceView />
          </div>
        ) : activeNav === 'chat' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ChatMessages messages={messages} loading={loading} sessionTitle={sessions.find(s => s.id === activeSessionId)?.title || ''} onOpenDrawer={() => setDrawerOpen(true)} sessionId={activeSessionId} authToken={authToken!} />
            <UnifiedInputBar isHome={false} loading={loading} onSend={handleSend} sessionId={activeSessionId} inputRef={inputRef} />
          </div>
        ) : activeNav === 'automation' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && <AutomationManagerView authToken={authToken} />}
          </div>
        ) : activeNav === 'skill' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {typeof window !== 'undefined' && window.location.hash === '#legacy-skills' ? (
              <SkillManagerView />
            ) : (
              <MarketplaceView authToken={authToken!} />
            )}
          </div>
        ) : activeNav === 'model-config' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && <ModelConfigView authToken={authToken} />}
          </div>
        ) : activeNav === 'connector' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && <GlobalSearchView authToken={authToken} onNavigateToSession={handleNavigateToSession} />}
          </div>
        ) : activeNav === 'explore' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ComingSoonView icon={<ExploreIcon />} title="探索" description="发现新技能、专家和工作流，扩展玄机的能力边界" />
          </div>
        ) : activeNav === 'library' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <LibraryView authToken={authToken} />
          </div>
        ) : messages.length === 0 && !historyLoading ? (
          /* ── Unified Workspace: Home state ── */
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <DashboardHome onSend={handleSend} loading={loading} username={currentUser.username} sessions={sessions} onSessionSelect={(id) => { handleSelectSession(id); if (window.innerWidth < 1024) setSidebarVisible(false) }} onViewAllSessions={() => setActiveNav('chat')} inputSlot={<UnifiedInputBar isHome={true} loading={loading} onSend={handleSend} sessionId={activeSessionId} inputRef={inputRef} embedded />} />
          </div>
        ) : messages.length === 0 && historyLoading ? (
          <div className="flex-1 flex items-center justify-center view-enter">
            {/* ✅ P1 集成：使用 LoadingStates skeleton 变体 */}
            <div className="flex flex-col items-center gap-4 w-full max-w-md px-6">
              <LoadingStates variant="skeleton" text="加载任务中..." />
              <span className="text-[#94A3B8] text-[13px]">正在获取会话记录…</span>
            </div>
          </div>
        ) : (
          /* ── Unified Workspace: Chat state ── */
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ChatMessages messages={messages} loading={loading} sessionTitle={sessions.find(s => s.id === activeSessionId)?.title || ''} onOpenDrawer={() => setDrawerOpen(true)} sessionId={activeSessionId} authToken={authToken!} />
            <UnifiedInputBar isHome={false} loading={loading} onSend={handleSend} sessionId={activeSessionId} inputRef={inputRef} />
          </div>
        )}
      </main>
      {/* Drawer overlay */}
      {drawerOpen && (
        <div
          className="fixed inset-0 bg-black/15 z-40 transition-opacity"
          onClick={() => setDrawerOpen(false)}
        />
      )}
      {/* AI Config Drawer */}
      <aside
        className={`fixed top-0 right-0 w-[320px] h-dvh bg-white border-l border-[rgba(0,0,0,0.08)] shadow-[-4px_0_24px_rgba(0,0,0,0.1)] z-50 flex flex-col transition-transform duration-[280ms] ${
          drawerOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <ConfigDrawer onClose={() => setDrawerOpen(false)} />
      </aside>
      {showAppearance && <AppearanceSettings onClose={() => setShowAppearance(false)} />}
      {showProfile && currentUser && authToken && (
        <ProfileSettings
          authToken={authToken}
          user={currentUser}
          onClose={() => setShowProfile(false)}
          onUserUpdated={(updatedUser) => setCurrentUser(updatedUser as CurrentUser)}
        />
      )}
    </div>
    </ThemeProvider>
  )
}

export default App
