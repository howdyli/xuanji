import { useState, useCallback, useEffect, useRef } from 'react'
import { SkillsPanel } from './components/SkillsPanel'
import { SkillManagerView } from './components/SkillManagerView'
import { SessionSkillsPicker } from './components/SessionSkillsPicker'
import { WorkspaceView } from './components/WorkspaceView'
import { LoginView } from './components/LoginView'
import { ExpertManagerView } from './components/ExpertManagerView'
import { AutomationManagerView } from './components/AutomationManagerView'
import { MarkdownRenderer } from './components/MarkdownRenderer'
import { ThemeProvider } from './components/ThemeContext'
import { AppearanceSettings } from './components/AppearanceSettings'
import { ProfileSettings } from './components/ProfileSettings'
import { ModelConfigView } from './components/ModelConfigView'

// --- Types ---
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface Session {
  id: string
  routing_key: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

interface ApiResponse {
  msg_id: string
  reply: string
  session_id: string
  duration_ms: number
}

// --- Config ---
const API_BASE = '/api/frontend'
const ROUTING_KEY = 'p2p:web_user'

// --- Icons (inline SVG, line style matching 玄机) ---
const Icon = ({ d, size = 18, strokeWidth = 1.6 }: { d: string; size?: number; strokeWidth?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
)

const SearchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)

const FilterIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <line x1="4" y1="6" x2="20" y2="6" />
    <line x1="7" y1="12" x2="17" y2="12" />
    <line x1="10" y1="18" x2="14" y2="18" />
  </svg>
)

const PlusIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
)

const AssistantIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="8" r="3" />
    <path d="M5 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2" />
  </svg>
)

const ExpertIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 10v6M2 10l10-5 10 5-10 5z" />
    <path d="M6 12v5c3 3 9 3 12 0v-5" />
  </svg>
)

const SkillIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
)

const ConnectorIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="9" width="6" height="6" rx="2" />
    <rect x="16" y="9" width="6" height="6" rx="2" />
    <path d="M8 12h8" />
  </svg>
)

const ExploreIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
  </svg>
)

const LibraryIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
  </svg>
)

const AutomationIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
)

const ModelConfigIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
)

const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

const CodeIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
)

const MonitorIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
    <line x1="8" y1="21" x2="16" y2="21" />
    <line x1="12" y1="17" x2="12" y2="21" />
  </svg>
)

const PaletteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
    <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
    <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
    <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
  </svg>
)

const SettingsIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

const SendIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
)

const AtIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="4" />
    <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />
  </svg>
)

const PaperclipIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
)

const PanelIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <line x1="9" y1="3" x2="9" y2="21" />
  </svg>
)

const ChevronRight = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
)

const FolderIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
  </svg>
)

// --- Robot illustration (line art SVG, responsive) ---
function RobotIllustration() {
  return (
    <img
      src="/xuanji-logo.png"
      alt="玄机"
      className="w-[clamp(220px,32vmin,360px)] h-[clamp(220px,32vmin,360px)] object-contain"
    />
  )
}

// --- Sidebar ---
const NAV_ITEMS = [
  { id: 'assistant', label: '助理', icon: <AssistantIcon /> },
  { id: 'expert', label: '专家', icon: <ExpertIcon /> },
  { id: 'skill', label: '技能', icon: <SkillIcon /> },
  { id: 'connector', label: '连接器', icon: <ConnectorIcon /> },
  { id: 'explore', label: '探索', icon: <ExploreIcon /> },
  { id: 'automation', label: '自动化', icon: <AutomationIcon /> },
  { id: 'model-config', label: '模型配置', icon: <ModelConfigIcon /> },
]

const NAV_ITEMS_EXPANDABLE = [
  { id: 'library', label: '资料库', icon: <LibraryIcon />, expandable: true },
]

function Sidebar({
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
}: {
  activeNav: string
  onNavChange: (id: string) => void
  sessions: Session[]
  activeSessionId: string | null
  onSessionSelect: (id: string) => void
  onNewTask: () => void
  search: string
  onSearchChange: (v: string) => void
  username: string
  onLogout: () => void
  onSettings: () => void
  onProfile: () => void
}) {
  const filtered = sessions.filter((s) =>
    !search || (s.title || '').toLowerCase().includes(search.toLowerCase())
  )

  // Collapsible sections
  const [tasksOpen, setTasksOpen] = useState(true)

  return (
    <div className="h-full flex flex-col t-bg-secondary border-r t-border-secondary">
      {/* Logo */}
      <div className="px-4 pt-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-xs font-bold">
            玄
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[13px] font-semibold text-gray-800">玄机</span>
            <span className="text-[10px] text-gray-400">v2.0.0</span>
          </div>
        </div>
        <span className="w-2.5 h-2.5 rounded-full bg-blue-400 ring-2 ring-blue-100" title="在线" />
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-1.5">
          <div className="flex-1 flex items-center gap-2 t-bg-input border t-border-primary rounded-lg px-2.5 py-1.5">
            <span className="text-gray-400"><SearchIcon /></span>
            <input
              type="text"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="搜索任务"
              className="flex-1 text-[12px] bg-transparent outline-none t-text-primary placeholder:t-text-tertiary"
            />
          </div>
          <button className="w-7 h-7 flex items-center justify-center rounded-lg bg-white border border-gray-200 text-gray-500 hover:bg-gray-50">
            <FilterIcon />
          </button>
        </div>
      </div>

      {/* New task button */}
      <div className="px-3 pb-2">
        <button
          onClick={onNewTask}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 transition-colors dark:bg-[var(--accent)] dark:hover:opacity-90"
        >
          <PlusIcon />
          <span>新建任务</span>
        </button>
      </div>

      {/* Navigation */}
      <nav className="px-2 py-1 space-y-0.5">
        {/* Core */}
        <div className="px-3 py-1 text-[10px] text-gray-400 font-medium uppercase tracking-wider">核心</div>
        {NAV_ITEMS.filter((i) => ['assistant', 'expert', 'skill', 'automation'].includes(i.id)).map((item) => (
          <button
            key={item.id}
            onClick={() => onNavChange(item.id)}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] sidebar-item ${
              activeNav === item.id ? 't-bg-tertiary t-text-primary' : 't-text-secondary t-bg-hover'
            }`}
          >
            <span className="text-gray-500">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
        {/* Extended */}
        <div className="px-3 py-1 mt-2 text-[10px] text-gray-400 font-medium uppercase tracking-wider">扩展</div>
        {NAV_ITEMS.filter((i) => ['connector', 'explore', 'model-config'].includes(i.id)).map((item) => (
          <button
            key={item.id}
            onClick={() => onNavChange(item.id)}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] sidebar-item ${
              activeNav === item.id ? 't-bg-tertiary t-text-primary' : 't-text-secondary t-bg-hover'
            }`}
          >
            <span className="text-gray-500">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
        {NAV_ITEMS_EXPANDABLE.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavChange(item.id)}
            className={`w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-lg text-[13px] sidebar-item ${
              activeNav === item.id ? 't-bg-tertiary t-text-primary' : 't-text-secondary t-bg-hover'
            }`}
          >
            <span className="flex items-center gap-2.5">
              <span className="text-gray-500">{item.icon}</span>
              <span>{item.label}</span>
            </span>
            {(item as any).expandable && <span className="text-gray-400"><ChevronRight /></span>}
          </button>
        ))}
      </nav>

      {/* Sessions + Workspace sections */}
      <div className="flex-1 flex flex-col min-h-0 mt-2 overflow-y-auto">
        {/* Tasks section */}
        <div className="px-4 py-2 text-[11px] t-text-tertiary font-medium flex items-center gap-1 cursor-pointer select-none" onClick={() => setTasksOpen(!tasksOpen)}>
          <span className={`text-[9px] transition-transform ${tasksOpen ? '' : '-rotate-90'}`}>▼</span>
          任务 {filtered.length > 0 && `(${filtered.length})`}
        </div>
        {tasksOpen && (
          <div className="px-2 pb-2 space-y-0.5">
            {filtered.length === 0 ? (
              <div className="px-3 py-2 text-[11px] text-gray-400">暂无任务</div>
            ) : (
              filtered.map((s) => (
                <button
                  key={s.id}
                  onClick={() => onSessionSelect(s.id)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-left transition-colors group ${
                    s.id === activeSessionId ? 't-bg-tertiary' : 't-bg-hover'
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="text-blue-500 shrink-0"><CheckIcon /></span>
                    <span className="text-[12.5px] t-text-primary truncate">{s.title || '新任务'}</span>
                  </span>
                  <span className="text-[10px] t-text-tertiary shrink-0">
                    {formatRelativeTime(s.updated_at)}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* User profile */}
      <div className="px-3 py-3 border-t t-border-secondary flex items-center justify-between">
        <button
          onClick={onProfile}
          className="flex items-center gap-2.5 hover:opacity-80 transition-opacity rounded-lg px-1 py-0.5 -mx-1"
          title="用户信息"
        >
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-300 to-pink-400 flex items-center justify-center text-white text-xs font-semibold">
            {username.charAt(0).toUpperCase()}
          </div>
          <span className="text-[13px] t-text-primary font-medium">{username}</span>
        </button>
        <div className="flex items-center gap-1">
          <button
            onClick={onSettings}
            className="text-[12px] t-text-tertiary hover:t-text-secondary transition-colors p-1.5 rounded-lg hover:t-bg-hover"
            title="外观设置"
          >
            <SettingsIcon />
          </button>
          <button
            onClick={onLogout}
            className="text-[12px] t-text-tertiary hover:text-red-500 transition-colors px-2 py-1"
            title="退出登录"
          >
            退出
          </button>
        </div>
      </div>
    </div>
  )
}

function formatRelativeTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const m = Math.floor(diff / 60000)
    if (m < 1) return '刚刚'
    if (m < 60) return `${m}分钟前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}小时前`
    const days = Math.floor(h / 24)
    return `${days}天前`
  } catch {
    return ''
  }
}

// --- Quick Action Chip ---
function QuickChip({ label, icon }: { label: string; icon?: React.ReactNode }) {
  return (
    <button className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-gray-200 bg-white text-[12.5px] text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors whitespace-nowrap">
      {icon && <span className="text-gray-500">{icon}</span>}
      <span>{label}</span>
    </button>
  )
}

const QUICK_ACTIONS = [
  { label: '文档处理', icon: <Icon d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8" size={13} /> },
  { label: '金融服务', icon: <Icon d="M3 17l6-6 4 4 8-8" size={13} /> },
  { label: '数据分析及可视化', icon: <Icon d="M3 3v18h18 M7 14l4-4 4 4 5-5" size={13} /> },
  { label: '深度研究', icon: <SearchIcon /> },
  { label: '产品管理', icon: <Icon d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" size={13} /> },
  { label: '幻灯片', icon: <MonitorIcon /> },
  { label: '设计创意', icon: <PaletteIcon /> },
]

// --- Mode Tabs (开始 - 代码开发 / 日常办公 / 设计创意 - 任务) ---
function ModeTabs({ active, onChange }: { active: string; onChange: (id: string) => void }) {
  const modes = [
    { id: 'code', label: '代码开发', icon: <CodeIcon /> },
    { id: 'office', label: '日常办公', icon: <MonitorIcon /> },
    { id: 'design', label: '设计创意', icon: <PaletteIcon /> },
  ]
  return (
    <div className="flex items-center gap-3">
      <span className="text-[13px] text-gray-400">开始</span>
      <div className="flex items-center gap-1 bg-gray-100/80 rounded-full p-1">
        {modes.map((m) => (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[12.5px] transition-colors ${
              active === m.id
                ? 'bg-gray-900 text-white shadow-sm'
                : 'text-gray-600 hover:bg-white/70'
            }`}
          >
            {m.icon}
            <span>{m.label}</span>
          </button>
        ))}
      </div>
      <span className="text-[13px] text-gray-400">任务</span>
    </div>
  )
}

// --- Coming Soon View (placeholder for unimplemented modules) ---
function ComingSoonView({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-16 h-16 rounded-2xl bg-blue-50 flex items-center justify-center text-blue-500 mb-5">
        {icon}
      </div>
      <h2 className="text-[20px] font-semibold text-gray-800 mb-2">{title}</h2>
      <p className="text-[14px] text-gray-400 text-center max-w-sm mb-6">{description}</p>
      <span className="px-4 py-1.5 rounded-full bg-gray-100 text-[12px] text-gray-500 font-medium">
        敬请期待
      </span>
    </div>
  )
}

// --- Quick action card (expert-style) ---
const WELCOME_ACTIONS = [
  { title: '写一份项目方案', desc: '梳理需求并输出文档', prompt: '帮我写一份项目方案，包含需求梳理、技术选型和实施计划', icon: '📋', accent: 'from-blue-400 to-indigo-500' },
  { title: '分析市场数据', desc: '采集数据并生成报告', prompt: '帮我分析市场数据，生成一份分析报告', icon: '📊', accent: 'from-emerald-400 to-teal-500' },
  { title: '生成演示PPT', desc: '自动排版幻灯片', prompt: '帮我生成一份演示PPT', icon: '📑', accent: 'from-orange-400 to-rose-500' },
  { title: '搜索历史记忆', desc: '查找之前的对话', prompt: '搜索我的历史记忆，查找相关内容', icon: '🔍', accent: 'from-purple-400 to-fuchsia-500' },
]

// --- Welcome Hero (Empty state) ---
function WelcomeHero({
  onSend,
  loading,
  sessionId,
}: {
  onSend: (text: string) => void
  loading: boolean
  sessionId: string | null
}) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    onSend(trimmed)
    setText('')
  }

  // Auto-grow textarea
  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 py-4 sm:py-8 overflow-y-auto">
      <div className="w-full max-w-2xl sm:max-w-3xl xl:max-w-4xl flex flex-col items-center gap-4 sm:gap-5">
        {/* Logo */}
        <div className="shrink-0">
          <RobotIllustration />
        </div>

        {/* Tagline */}
        <h1 className="text-2xl sm:text-3xl md:text-[28px] lg:text-[32px] font-medium text-gray-800 tracking-tight text-center leading-tight">
          玄机<span className="font-normal text-gray-500">·</span>靠谱的工作伙伴
        </h1>

        {/* Quick action cards — expert style */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full">
          {WELCOME_ACTIONS.map((s) => (
            <button
              key={s.title}
              onClick={() => onSend(s.prompt)}
              disabled={loading}
              className="group relative p-3.5 rounded-xl bg-white border border-gray-200 hover:border-gray-300 hover:shadow-md transition-all text-left disabled:opacity-50 overflow-hidden"
            >
              {/* Accent top bar */}
              <div className={`absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r ${s.accent} opacity-0 group-hover:opacity-100 transition-opacity`} />
              {/* Icon + title */}
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-base">{s.icon}</span>
                <span className="text-[13px] font-semibold text-gray-800 leading-tight">{s.title}</span>
              </div>
              <div className="text-[11px] text-gray-400 leading-snug">{s.desc}</div>
            </button>
          ))}
        </div>

        {/* Input area — unified with cards above */}
        <div className="w-full">
          <div className="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
            {/* Top toolbar */}
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-100">
              <button className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <AtIcon />
              </button>
              <button className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <PaperclipIcon />
              </button>
            </div>

            {/* Textarea — auto-grow */}
            <textarea
              ref={inputRef}
              value={text}
              onChange={handleInput}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="输入消息..."
              rows={2}
              disabled={loading}
              className="w-full resize-none px-4 py-2.5 text-[13.5px] outline-none text-gray-800 placeholder-gray-400 bg-transparent disabled:opacity-50"
              style={{ maxHeight: '200px' }}
            />

            {/* Bottom toolbar */}
            <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 bg-gray-50/60 flex-wrap gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                {/* Safety badge */}
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-blue-50 text-blue-600 text-[10.5px] font-medium" title="安全沙箱环境">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                  <span>安全沙箱</span>
                </span>
                <div className="w-px h-4 bg-gray-200" />
                {/* Mode switcher */}
                <div className="flex items-center gap-1 bg-gray-100 rounded-full p-1">
                  <button className="flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] bg-gray-900 text-white shadow-sm" title="精细创作：由专家角色深度执行">
                    <CodeIcon />
                    <span>Craft</span>
                  </button>
                  <button className="flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] text-gray-600 hover:bg-white/70" title="智能路由：AI 自动选择最佳执行方式">
                    <span className="w-3.5 h-3.5 rounded-full bg-gradient-to-br from-purple-400 to-pink-400" />
                    <span>Auto</span>
                  </button>
                  <SkillButton sessionId={sessionId} />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] text-gray-500 hover:bg-white border border-transparent hover:border-gray-200">
                  <MonitorIcon />
                  <span>本地工作空间</span>
                </button>
                <button
                  onClick={handleSend}
                  disabled={loading || !text.trim()}
                  className="w-8 h-8 rounded-lg bg-gray-900 text-white flex items-center justify-center hover:bg-gray-800 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                >
                  <SendIcon />
                </button>
              </div>
            </div>
          </div>

          {/* Footer notice */}
          <div className="text-center mt-2 text-[11px] text-gray-400">
            内容由 AI 生成，请核实重要信息。
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Chat View ---
function ChatView({
  messages,
  loading,
  onSend,
  sessionId,
}: {
  messages: Message[]
  loading: boolean
  onSend: (text: string) => void
  sessionId: string | null
}) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    onSend(trimmed)
    setText('')
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6">
        <div className="max-w-2xl sm:max-w-3xl xl:max-w-4xl mx-auto space-y-4 sm:space-y-5">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {loading && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-300 to-blue-500 flex items-center justify-center text-white text-[10px] font-bold shrink-0">
                XP
              </div>
              <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="px-3 sm:px-6 pb-3 sm:pb-5 pt-2">
        <div className="max-w-2xl sm:max-w-3xl xl:max-w-4xl mx-auto">
          <div className="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-100">
              <button className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <AtIcon />
              </button>
              <button className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <PaperclipIcon />
              </button>
            </div>
            <textarea
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="输入消息..."
              rows={2}
              disabled={loading}
              className="w-full resize-none px-4 py-2.5 text-[13.5px] outline-none text-gray-800 placeholder-gray-400 bg-transparent disabled:opacity-50"
            />
            <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 bg-gray-50/60">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-400">Enter 发送 · Shift+Enter 换行</span>
                <SkillButton sessionId={sessionId} />
              </div>
              <button
                onClick={handleSend}
                disabled={loading || !text.trim()}
                className="w-8 h-8 rounded-lg bg-gray-900 text-white flex items-center justify-center hover:bg-gray-800 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                <SendIcon />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── file path link rendering ────────────────────────────────────────────────
// Matches /workspace/ paths ending with file extensions (.pptx, .docx, .js, .md, etc.)
// Uses lazy quantifier + extension check to stop before trailing text like `（约13KB）
const FILE_PATH_RE = /(\/workspace\/[^\s<>"'`]+?\.[a-zA-Z0-9]{2,5})/g;

function renderContent(content: string): React.ReactNode {
  const parts = content.split(FILE_PATH_RE);
  if (parts.length === 1) {
    return content; // No file paths — plain text
  }
  return parts.map((part, i) => {
    if (part.startsWith('/workspace/')) {
      const downloadUrl = `/api/frontend/files/download?path=${encodeURIComponent(part)}`;
      const filename = part.split('/').pop() || part;
      return (
        <a
          key={i}
          href={downloadUrl}
          className="text-blue-600 underline hover:text-blue-800"
          target="_blank"
          rel="noopener noreferrer"
        >
          {filename}
        </a>
      );
    }
    return part;
  });
}

// ── Collapsible content wrapper ──────────────────────────────────────────────
const COLLAPSE_THRESHOLD = 480 // px — roughly 20 lines of content

function CollapsibleBubble({ children, isUser }: { children: React.ReactNode; isUser: boolean }) {
  const contentRef = useRef<HTMLDivElement>(null)
  const [collapsed, setCollapsed] = useState(!isUser)
  const [overflows, setOverflows] = useState(false)

  useEffect(() => {
    if (!isUser && contentRef.current) {
      const h = contentRef.current.scrollHeight
      setOverflows(h > COLLAPSE_THRESHOLD)
      if (h <= COLLAPSE_THRESHOLD) setCollapsed(false)
    }
  }, [isUser])

  return (
    <div className="relative">
      <div
        ref={contentRef}
        className={overflows && collapsed ? 'max-h-[480px] overflow-hidden' : ''}
      >
        {children}
      </div>
      {overflows && collapsed && (
        <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-[var(--bg-bubble-assistant)] to-transparent pointer-events-none" />
      )}
      {overflows && (
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="mt-1.5 text-[12px] text-[var(--accent-text)] font-medium hover:underline"
        >
          {collapsed ? '展开完整内容 ↓' : '收起内容 ↑'}
        </button>
      )}
    </div>
  )
}

// ── Message bubble ───────────────────────────────────────────────────────────
function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-8 h-8 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0 ${
          isUser
            ? 'bg-gradient-to-br from-orange-300 to-pink-400'
            : 'bg-gradient-to-br from-blue-400 to-blue-600'
        }`}
      >
        {isUser ? '我' : '玄'}
      </div>
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-[13.5px] ${
            isUser
              ? 'bg-[var(--bg-bubble-user)] text-[var(--text-bubble-user)] rounded-tr-sm leading-relaxed whitespace-pre-wrap'
              : 'bg-[var(--bg-bubble-assistant)] text-[var(--text-bubble-assistant)] border t-border-primary rounded-tl-sm shadow-sm msg-bubble-ai'
          }`}
        >
          {isUser ? (
            renderContent(msg.content)
          ) : (
            <CollapsibleBubble isUser={false}>
              <MarkdownRenderer content={msg.content} />
            </CollapsibleBubble>
          )}
        </div>
        <span className="text-[10px] t-text-tertiary mt-1">
          {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </div>
  )
}

// --- Top toolbar ---
function TopToolbar({ onCollapse, onNew }: { onCollapse: () => void; onNew: () => void }) {
  return (
    <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b t-border-secondary">
      <div className="flex items-center gap-2">
        <button
          onClick={onCollapse}
          className="w-7 h-7 rounded-lg flex items-center justify-center t-text-secondary t-bg-hover"
          title="折叠侧栏"
        >
          <PanelIcon />
        </button>
        <button
          onClick={onNew}
          className="w-7 h-7 rounded-lg flex items-center justify-center t-text-secondary t-bg-hover"
          title="新建任务"
        >
          <PlusIcon size={14} />
        </button>
      </div>
      <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-blue-50 text-blue-700 text-[12px] font-medium hover:bg-blue-100 transition-colors">
        <span className="w-4 h-4 rounded-full bg-blue-500 flex items-center justify-center text-white text-[9px]">$</span>
        来成长计划赚积分
        <ChevronRight />
      </button>
    </div>
  )
}

// --- Main App ---
interface CurrentUser {
  id: number
  username: string
  created_at?: string
}

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
  const [activeExpert, setActiveExpert] = useState<string | null>(
    () => localStorage.getItem('active_expert'),
  )
  const [showAppearance, setShowAppearance] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  // Auto-collapse sidebar on small screens (< 1024px)
  const [sidebarVisible, setSidebarVisible] = useState(
    typeof window !== 'undefined' ? window.innerWidth >= 1024 : true,
  )
  const activeSessionIdRef = useRef(activeSessionId)
  activeSessionIdRef.current = activeSessionId

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
      setSidebarVisible((prev) => {
        const w = window.innerWidth
        // Auto-collapse below lg, auto-expand above
        if (w < 1024) return false
        return prev || true
      })
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
            routing_key: ROUTING_KEY,
            sender_id: 'web_user',
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
        setMessages((prev) => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: `请求失败: ${err instanceof Error ? err.message : String(err)}`,
            timestamp: new Date().toISOString(),
          },
        ])
      } finally {
        setLoading(false)
      }
    },
    [authToken, fetchSessions, activeExpert]
  )

  const handleNewTask = useCallback(() => {
    setActiveSessionId(null)
    setMessages([])
  }, [])

  // Render login page if not authenticated
  if (!authToken || !currentUser) {
    if (authLoading) {
      return (
        <div className="h-dvh w-dvw flex items-center justify-center bg-[#f8f9fa]">
          <div className="flex items-center gap-2 text-gray-400 text-[13px]">
            <span className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-gray-600 animate-spin" />
            加载中...
          </div>
        </div>
      )
    }
    return <LoginView onLogin={handleLogin} />
  }

  return (
    <ThemeProvider>
    <div className="h-dvh w-dvw flex t-bg-primary overflow-hidden relative">
      {/* Sidebar (overlay on small screens, inline on ≥ lg) */}
      {sidebarVisible && (
        <>
          {/* Mobile/tablet backdrop */}
          <div
            className="lg:hidden fixed inset-0 bg-black/30 z-30"
            onClick={() => setSidebarVisible(false)}
          />
          <aside className="fixed lg:static inset-y-0 left-0 z-40 w-[78vw] max-w-[300px] sm:w-[260px] lg:w-[240px] xl:w-[280px] shrink-0 shadow-xl lg:shadow-none">
            <Sidebar
              activeNav={activeNav}
              onNavChange={(id) => {
                setActiveNav(id)
                if (window.innerWidth < 1024) setSidebarVisible(false)
              }}
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSessionSelect={(id) => {
                handleSelectSession(id)
                if (window.innerWidth < 1024) setSidebarVisible(false)
              }}
              onNewTask={handleNewTask}
              search={search}
              onSearchChange={setSearch}
              username={currentUser.username}
              onLogout={handleLogout}
              onSettings={() => setShowAppearance(true)}
              onProfile={() => setShowProfile(true)}
            />
          </aside>
        </>
      )}

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        <TopToolbar
          onCollapse={() => setSidebarVisible((v) => !v)}
          onNew={handleNewTask}
        />
        {/* Active expert indicator */}
        {activeExpert && activeNav === 'assistant' && (
          <div className="px-4 py-1.5 bg-blue-50 border-b border-blue-100 flex items-center gap-2 text-[11.5px] text-blue-700 animate-fade-in">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
            <span>当前专家：{activeExpert}</span>
            <button
              onClick={() => {
                setActiveExpert(null)
                localStorage.removeItem('active_expert')
              }}
              className="ml-auto text-blue-500 hover:text-blue-700 underline"
            >
              切换
            </button>
          </div>
        )}
        {activeNav === 'workspace' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <WorkspaceView />
          </div>
        ) : activeNav === 'expert' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && (
              <ExpertManagerView
                authToken={authToken}
                activeExpert={activeExpert}
                onSelectExpert={(name) => {
                  setActiveExpert(name)
                  if (name) localStorage.setItem('active_expert', name)
                  else localStorage.removeItem('active_expert')
                }}
              />
            )}
          </div>
        ) : activeNav === 'automation' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && <AutomationManagerView authToken={authToken} />}
          </div>
        ) : activeNav === 'skill' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {/* 保留旧版为兼容入口：地址栏加 #legacy-skills 即可切回两栏列表版 */}
            {typeof window !== 'undefined' && window.location.hash === '#legacy-skills' ? (
              <SkillsPanel onClose={() => setActiveNav('assistant')} />
            ) : (
              <SkillManagerView />
            )}
          </div>
        ) : activeNav === 'model-config' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            {authToken && <ModelConfigView authToken={authToken} />}
          </div>
        ) : activeNav === 'connector' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ComingSoonView icon={<ConnectorIcon />} title="连接器" description="整合第三方服务（飞书、企业微信等），统一管理消息通道" />
          </div>
        ) : activeNav === 'explore' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ComingSoonView icon={<ExploreIcon />} title="探索" description="发现新技能、专家和工作流，扩展玄机的能力边界" />
          </div>
        ) : activeNav === 'library' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ComingSoonView icon={<LibraryIcon />} title="资料库" description="管理文档、笔记和知识库，为 AI 提供持续的记忆支持" />
          </div>
        ) : messages.length === 0 && historyLoading ? (
          <div className="flex-1 flex items-center justify-center view-enter">
            <div className="flex flex-col items-center gap-3 text-gray-400 text-[13px]">
              <span className="w-5 h-5 rounded-full border-2 border-gray-300 border-t-gray-600 animate-spin" />
              加载任务中...
            </div>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <WelcomeHero onSend={handleSend} loading={loading} sessionId={activeSessionId} />
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <ChatView
              messages={messages}
              loading={loading}
              onSend={handleSend}
              sessionId={activeSessionId}
            />
          </div>
        )}
      </main>
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

// 底部工具栏的“技能”按钮 + 浮层选择器
function SkillButton({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border transition-colors ${
          open
            ? 'bg-gray-900 text-white border-gray-900'
            : 'text-gray-600 border-transparent hover:bg-white hover:border-gray-200'
        }`}
      >
        <SkillIcon />
        <span>技能</span>
      </button>
      <SessionSkillsPicker
        sessionId={sessionId}
        open={open}
        anchorEl={btnRef.current}
        onClose={() => setOpen(false)}
      />
    </div>
  )
}

export default App
