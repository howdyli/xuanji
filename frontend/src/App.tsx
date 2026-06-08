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
import { LibraryView } from './components/LibraryView'
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
const AssistantIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
  </svg>
)

const ExpertIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
)

const SkillIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </svg>
)

const ConnectorIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </svg>
)

const ExploreIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
  </svg>
)

const LibraryIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
  </svg>
)

const AutomationIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
)

const ModelConfigIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
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

// --- Sidebar Nav ---
const HomeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
  </svg>
)

const NAV_ITEMS = [
  { id: 'assistant', label: '工作台', icon: <HomeIcon />, group: 'core' },
  { id: 'chat', label: '助理', icon: <AssistantIcon />, group: 'core' },
  { id: 'expert', label: '专家', icon: <ExpertIcon />, group: 'core', badge: '3' },
  { id: 'skill', label: '技能', icon: <SkillIcon />, group: 'core' },
  { id: 'automation', label: '自动化', icon: <AutomationIcon />, group: 'core' },
  { id: 'connector', label: '连接器', icon: <ConnectorIcon />, group: 'ext' },
  { id: 'explore', label: '探索', icon: <ExploreIcon />, group: 'ext' },
  { id: 'model-config', label: '模型配置', icon: <ModelConfigIcon />, group: 'ext' },
]

const NAV_ITEMS_EXPANDABLE = [
  { id: 'library', label: '资料库', icon: <LibraryIcon />, expandable: true, group: 'ext' },
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

  const renderNavItem = (item: typeof NAV_ITEMS[0]) => {
    const isActive = activeNav === item.id
    return (
      <button
        key={item.id}
        onClick={() => onNavChange(item.id)}
        className={`w-full flex items-center gap-3 px-3 py-[8px] rounded-[10px] text-[13px] font-medium transition-all duration-140 ${
          isActive ? 'd-nav-active' : 'text-[#475569] hover:bg-[#F8FAFC] hover:text-[#1E293B]'
        }`}
      >
        <span className={isActive ? 'opacity-100' : 'opacity-70'}>{item.icon}</span>
        <span className="flex-1 text-left">{item.label}</span>
        {(item as any).badge && (
          <span className="h-[18px] px-1.5 rounded-full bg-[#FEF2F2] text-[#EF4444] text-[10px] font-bold flex items-center">
            {(item as any).badge}
          </span>
        )}
      </button>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white border-r border-[#E2E8F0] overflow-hidden" style={{ width: 256 }}>
      {/* Brand */}
      <div className="px-4 py-4 border-b border-[#F1F5F9] flex items-center gap-3">
        <div className="w-8 h-8 rounded-[10px] flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, #3B82F6, #1D4ED8)' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
        </div>
        <div className="flex flex-col flex-1">
          <strong className="text-[15px] font-bold text-[#0F172A] leading-tight">玄机</strong>
          <span className="text-[10px] font-medium text-[#94A3B8] tracking-wide">v2.0.0</span>
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-3">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-[15px] h-[15px] text-[#94A3B8] pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索任务、技能、文档..."
            className="w-full h-9 pl-[34px] pr-3 border border-[#E2E8F0] rounded-[10px] bg-[#F8FAFC] text-[13px] text-[#334155] outline-none transition-all duration-140 placeholder:text-[#94A3B8] focus:bg-white focus:border-[#93C5FD] focus:shadow-[0_0_0_3px_#DBEAFE]"
          />
        </div>
      </div>

      {/* New task button */}
      <div className="px-4 pb-2">
        <button
          onClick={onNewTask}
          className="w-full h-[38px] bg-[#0F172A] text-white rounded-[10px] text-[13px] font-semibold flex items-center justify-center gap-2 transition-all duration-140 hover:bg-[#1E293B] hover:-translate-y-px hover:shadow-md"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          新建任务
        </button>
      </div>

      {/* Nav: 核心 */}
      <nav className="px-3 py-2">
        <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">核心</div>
        <div className="flex flex-col gap-px">
          {NAV_ITEMS.filter(i => i.group === 'core').map(renderNavItem)}
        </div>
      </nav>

      {/* Nav: 扩展 */}
      <nav className="px-3 py-2">
        <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">扩展</div>
        <div className="flex flex-col gap-px">
          {NAV_ITEMS.filter(i => i.group === 'ext').map(renderNavItem)}
          {NAV_ITEMS_EXPANDABLE.map(item => {
            const isActive = activeNav === item.id
            return (
              <button
                key={item.id}
                onClick={() => onNavChange(item.id)}
                className={`w-full flex items-center justify-between gap-3 px-3 py-[8px] rounded-[10px] text-[13px] font-medium transition-all duration-140 ${
                  isActive ? 'd-nav-active' : 'text-[#475569] hover:bg-[#F8FAFC] hover:text-[#1E293B]'
                }`}
              >
                <span className="flex items-center gap-3">
                  <span className={isActive ? 'opacity-100' : 'opacity-70'}>{item.icon}</span>
                  <span>{item.label}</span>
                </span>
                <ChevronRight />
              </button>
            )
          })}
        </div>
      </nav>

      {/* Recent tasks */}
      <div className="flex-1 overflow-y-auto px-3 py-2 d-scroll">
        <div className="flex items-center justify-between px-2 py-1 mb-0.5">
          <span className="text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">最近任务</span>
          <button className="text-[11px] text-[#2563EB] font-medium hover:underline">查看全部</button>
        </div>
        {filtered.length === 0 ? (
          <div className="px-2 py-3 text-[12px] text-[#94A3B8]">暂无任务</div>
        ) : (
          filtered.slice(0, 5).map((s) => (
            <button
              key={s.id}
              onClick={() => onSessionSelect(s.id)}
              className="w-full flex items-start gap-2 px-2 py-2 rounded-[10px] text-left transition-all duration-140 hover:bg-[#F8FAFC]"
            >
              <div className={`w-4 h-4 rounded border-[1.5px] mt-px shrink-0 flex items-center justify-center ${
                s.id === activeSessionId ? 'bg-[#10B981] border-[#10B981]' : 'border-[#CBD5E1]'
              }`}>
                {s.id === activeSessionId && (
                  <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="w-2.5 h-2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className={`text-[12px] text-[#334155] leading-snug truncate ${s.id === activeSessionId ? 'line-through text-[#94A3B8]' : ''}`}>
                  {s.title || '新任务'}
                </div>
                <div className="text-[11px] text-[#94A3B8] mt-px">{formatRelativeTime(s.updated_at)}</div>
              </div>
              <div className="w-[18px] h-[18px] rounded-full shrink-0 flex items-center justify-center text-white text-[8px] font-bold" style={{ background: 'linear-gradient(135deg, #93C5FD, #3B82F6)' }}>
                AI
              </div>
            </button>
          ))
        )}
      </div>

      {/* User footer */}
      <div className="px-4 py-3 border-t border-[#F1F5F9] flex items-center gap-3">
        <button onClick={onProfile} className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[12px] font-bold shrink-0" style={{ background: 'linear-gradient(135deg, #FF6B6B, #FF8E53)' }}>
          {username.charAt(0).toUpperCase()}
        </button>
        <div className="flex-1 min-w-0">
          <strong className="block text-[13px] font-semibold text-[#1E293B] leading-tight">{username}</strong>
          <span className="text-[11px] text-[#94A3B8]">超级管理员</span>
        </div>
        <button onClick={onSettings} className="w-8 h-8 rounded-[10px] flex items-center justify-center text-[#94A3B8] hover:bg-[#F1F5F9] hover:text-[#475569] transition-all duration-140" title="设置">
          <SettingsIcon />
        </button>
        <button onClick={onLogout} className="w-8 h-8 rounded-[10px] flex items-center justify-center text-[#94A3B8] hover:bg-[#F1F5F9] hover:text-red-500 transition-all duration-140" title="退出">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>
        </button>
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

// --- Quick action cards for dashboard ---
const DASH_ACTIONS = [
  { title: '写一份项目方案', desc: '基于需求自动生成结构清晰的项目方案文档，包含目标、里程碑与资源规划。', tag: '约 3 分钟', prompt: '帮我写一份项目方案，包含需求梳理、技术选型和实施计划', accent: 'blue', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg> },
  { title: '分析市场数据', desc: '自动采集多源数据，生成可视化图表与深度洞察报告，支持导出 Excel / PPT。', tag: '约 5 分钟', prompt: '帮我分析市场数据，生成一份分析报告', accent: 'green', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></svg> },
  { title: '生成演示 PPT', desc: '一键将大纲转换为精美幻灯片，自动排版、配色、配图，支持在线预览与下载。', tag: '约 4 分钟', prompt: '帮我生成一份演示PPT', accent: 'amber', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" /></svg> },
  { title: '探索历史记忆', desc: '智能检索过往对话与文档，基于语义理解快速定位关键信息，支持跨会话关联。', tag: '即时', prompt: '搜索我的历史记忆，查找相关内容', accent: 'purple', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg> },
]

const DASH_ACTIVITIES = [
  { color: 'bg-[#3B82F6]', title: '「Q2 财务报告」已生成完毕', desc: '专家 Agent 已完成数据分析与图表绘制', time: '10 分钟前' },
  { color: 'bg-[#10B981]', title: '新技能「PDF 智能解析」已安装', desc: '支持自动提取表格、图表与关键段落', time: '1 小时前' },
  { color: 'bg-[#8B5CF6]', title: '自动化任务「日报推送」运行成功', desc: '已发送至企业微信，共 3 位成员收到', time: '3 小时前' },
]

// --- Dashboard View (replaces WelcomeHero) ---
function DashboardView({
  onSend,
  loading,
  sessionId,
  username,
}: {
  onSend: (text: string) => void
  loading: boolean
  sessionId: string | null
  username: string
}) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    onSend(trimmed)
    setText('')
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  const hour = new Date().getHours()
  const greet = hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'

  const accentMap: Record<string, { bar: string; iconBg: string; iconColor: string }> = {
    blue: { bar: '#3B82F6', iconBg: '#DBEAFE', iconColor: '#2563EB' },
    green: { bar: '#10B981', iconBg: '#ECFDF5', iconColor: '#10B981' },
    amber: { bar: '#F59E0B', iconBg: '#FFFBEB', iconColor: '#F59E0B' },
    purple: { bar: '#8B5CF6', iconBg: '#F5F3FF', iconColor: '#8B5CF6' },
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6 d-scroll" style={{ background: '#F8FAFC' }}>
      {/* Welcome header */}
      <header className="mb-8">
        <p className="text-[13px] font-medium text-[#64748B] mb-1">{greet}，{username} &#x1F44B;</p>
        <h1 className="text-[28px] font-extrabold text-[#0F172A] leading-[1.2] mb-2" style={{ letterSpacing: '-0.02em' }}>
          玄机 · <span className="text-[#2563EB]">靠谱的工作伙伴</span>
        </h1>
        <p className="text-[14px] text-[#64748B] max-w-[520px] leading-relaxed">
          AI 专家团队协作，让复杂任务一键完成。今天有什么我可以帮你的？
        </p>
      </header>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4 mb-8 max-[1280px]:grid-cols-2 max-[640px]:grid-cols-1">
        {[
          { value: '128', label: '本月完成任务', iconBg: '#DBEAFE', iconColor: '#2563EB', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg> },
          { value: '46h', label: '节省工作时长', iconBg: '#ECFDF5', iconColor: '#10B981', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg> },
          { value: '24', label: '待处理对话', iconBg: '#FFFBEB', iconColor: '#F59E0B', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg> },
          { value: '98.2%', label: '任务成功率', iconBg: '#F5F3FF', iconColor: '#8B5CF6', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]"><path d="M12 2a10 10 0 1 0 10 10H12V2z" /><path d="M12 2a10 10 0 0 1 10 10" /></svg> },
        ].map((s, i) => (
          <div key={s.label} className="d-fade-up bg-white border border-[#E2E8F0] rounded-[14px] p-4 flex items-center gap-3 transition-all duration-140 hover:border-[#CBD5E1] hover:shadow-md hover:-translate-y-px" style={{ animationDelay: `${i * 40}ms` }}>
            <div className="w-10 h-10 rounded-[10px] flex items-center justify-center shrink-0" style={{ background: s.iconBg, color: s.iconColor }}>{s.icon}</div>
            <div>
              <div className="text-[20px] font-extrabold text-[#0F172A] leading-none">{s.value}</div>
              <div className="text-[12px] text-[#64748B] mt-0.5">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[16px] font-bold text-[#1E293B]">快捷操作</h2>
        <button className="text-[13px] font-semibold text-[#2563EB] flex items-center gap-0.5 hover:text-[#1D4ED8] transition-all duration-140 hover:gap-1">
          自定义 <ChevronRight />
        </button>
      </div>
      <div className="grid grid-cols-4 gap-4 mb-8 max-[960px]:grid-cols-2 max-[640px]:grid-cols-1">
        {DASH_ACTIONS.map((a, i) => {
          const colors = accentMap[a.accent]
          return (
            <button
              key={a.title}
              onClick={() => onSend(a.prompt)}
              disabled={loading}
              className="d-fade-up group relative bg-white border-[1.5px] border-[#E2E8F0] rounded-[20px] p-5 text-left transition-all duration-[240ms] hover:border-[#93C5FD] hover:shadow-lg hover:-translate-y-[3px] disabled:opacity-50 overflow-hidden"
              style={{ animationDelay: `${80 + i * 40}ms` }}
            >
              {/* Top accent bar */}
              <div className="absolute top-0 left-0 right-0 h-[3px] rounded-t-[20px] opacity-0 group-hover:opacity-100 transition-opacity" style={{ background: colors.bar }} />
              {/* Icon */}
              <div className="w-11 h-11 rounded-[14px] flex items-center justify-center mb-3" style={{ background: colors.iconBg, color: colors.iconColor }}>{a.icon}</div>
              <h4 className="text-[14px] font-bold text-[#1E293B] mb-1">{a.title}</h4>
              <p className="text-[12px] text-[#64748B] leading-relaxed">{a.desc}</p>
              <span className="inline-flex items-center gap-1 mt-3 text-[11px] font-semibold px-2 py-1 rounded-full bg-[#F1F5F9] text-[#475569]">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-2.5 h-2.5"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                {a.tag}
              </span>
            </button>
          )
        })}
      </div>

      {/* Input area */}
      <div className="bg-white border-[1.5px] border-[#E2E8F0] rounded-[20px] p-4 mb-6 transition-all duration-140 focus-within:border-[#93C5FD] focus-within:shadow-[0_0_0_3px_#DBEAFE,0_4px_12px_-2px_rgb(15_23_42/0.08)]">
        <textarea
          ref={inputRef}
          value={text}
          onChange={handleInput}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
          }}
          placeholder="输入任务描述，例如：帮我分析 Q3 销售数据并生成可视化报告..."
          rows={2}
          disabled={loading}
          className="w-full min-h-[60px] resize-none border-none outline-none text-[15px] text-[#1E293B] leading-relaxed bg-transparent placeholder:text-[#94A3B8] disabled:opacity-50"
        />
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-[#F1F5F9]">
          <div className="flex items-center gap-1">
            <ToolbarBtn icon={<PaperclipIcon />} label="附件" />
            <div className="w-px h-[18px] bg-[#E2E8F0] mx-1" />
            <ToolbarBtn icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="9" y1="21" x2="9" y2="9" /></svg>} label="实景沙箱" primary />
            <ToolbarBtn icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5"><path d="M12 2a10 10 0 1 0 10 10H12V2z" /></svg>} label="Chat+" />
            <ToolbarBtn icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" /></svg>} label="Auto" />
            <SkillButton sessionId={sessionId} />
          </div>
          <div className="flex items-center gap-2">
            <button className="w-9 h-9 rounded-[10px] flex items-center justify-center text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#334155] transition-all duration-140" title="本地工作空间">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>
            </button>
            <button
              onClick={handleSend}
              disabled={loading || !text.trim()}
              className="w-9 h-9 rounded-[10px] bg-[#2563EB] text-white flex items-center justify-center transition-all duration-140 hover:bg-[#1D4ED8] hover:-translate-y-px hover:shadow-[0_4px_12px_rgb(37_99_235/0.4)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <SendIcon />
            </button>
          </div>
        </div>
      </div>

      {/* Activity timeline */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[16px] font-bold text-[#1E293B]">最近动态</h2>
          <button className="text-[13px] font-semibold text-[#2563EB] flex items-center gap-0.5 hover:text-[#1D4ED8] transition-all duration-140 hover:gap-1">
            查看全部 <ChevronRight />
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {DASH_ACTIVITIES.map((a) => (
            <div key={a.title} className="flex items-start gap-3 px-4 py-3 bg-white border border-[#E2E8F0] rounded-[14px] transition-all duration-140 hover:border-[#CBD5E1] hover:shadow-sm">
              <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${a.color}`} />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-semibold text-[#1E293B] leading-snug">{a.title}</div>
                <div className="text-[12px] text-[#64748B] mt-px">{a.desc}</div>
              </div>
              <div className="text-[11px] text-[#94A3B8] shrink-0 mt-px">{a.time}</div>
            </div>
          ))}
        </div>
      </div>

      <p className="text-center text-[12px] text-[#94A3B8] pb-4">内容由 AI 生成，请核实重要信息。</p>
    </div>
  )
}

function ToolbarBtn({ icon, label, primary }: { icon: React.ReactNode; label: string; primary?: boolean }) {
  return (
    <button className={`h-8 px-3 rounded-[10px] text-[12px] font-semibold flex items-center gap-1.5 transition-all duration-140 ${
      primary ? 'bg-[#2563EB] text-white hover:bg-[#1D4ED8] hover:shadow-md' : 'text-[#475569] hover:bg-[#F1F5F9] hover:text-[#1E293B]'
    }`}>
      {icon}{label}
    </button>
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

// --- Top bar ---
function DashboardTopBar() {
  return (
    <div className="shrink-0 h-14 bg-white border-b border-[#E2E8F0] flex items-center px-6 gap-4">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-[13px] text-[#64748B]" aria-label="面包屑">
        <span>玄机</span>
        <ChevronRight />
        <span className="font-semibold text-[#1E293B]">工作台</span>
      </nav>
      <div className="ml-auto flex items-center gap-2">
        {/* Notification */}
        <button className="w-9 h-9 rounded-[10px] flex items-center justify-center text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#334155] transition-all duration-140 relative" title="通知">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
          <span className="absolute top-[7px] right-[7px] w-[7px] h-[7px] rounded-full bg-[#EF4444] border-2 border-white" />
        </button>
        {/* Help */}
        <button className="w-9 h-9 rounded-[10px] flex items-center justify-center text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#334155] transition-all duration-140" title="帮助">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
        </button>
        {/* Growth chip */}
        <div className="h-8 px-3 rounded-full bg-[#FFFBEB] text-[#F59E0B] text-[12px] font-semibold flex items-center gap-1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>
          成长计划
        </div>
      </div>
    </div>
  )
}

// --- Right Panel (智能配置) ---
function RightPanel() {
  const [activeModel, setActiveModel] = useState(0)
  const models = [
    { name: '灵享妙语 Pro', desc: '长文本 · 推理增强', avatar: '灵', gradient: 'linear-gradient(135deg, #60A5FA, #2563EB)' },
    { name: 'Chat+', desc: '多轮对话 · 代码生成', avatar: 'C', gradient: 'linear-gradient(135deg, #A78BFA, #8B5CF6)' },
    { name: 'Auto', desc: '自动规划 · 工具调用', avatar: 'A', gradient: 'linear-gradient(135deg, #10B981, #34D399)' },
  ]
  const skills = [
    { label: '文档生成', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg> },
    { label: '数据分析', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></svg> },
    { label: 'PPT 制作', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" /></svg> },
    { label: '会议纪要', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg> },
    { label: '翻译润色', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><path d="M12 2a10 10 0 1 0 10 10H12V2z" /><path d="M12 2a10 10 0 0 1 10 10" /></svg> },
    { label: '代码审查', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg> },
  ]

  return (
    <div className="w-[300px] shrink-0 bg-white border-l border-[#E2E8F0] flex flex-col overflow-hidden max-[1280px]:hidden">
      <div className="px-5 py-4 border-b border-[#F1F5F9] text-[14px] font-bold text-[#1E293B]">智能配置</div>
      <div className="flex-1 overflow-y-auto px-5 py-4 d-scroll">
        {/* Model switcher */}
        <div className="mb-6">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94A3B8] mb-3">当前模型</div>
          {models.map((m, i) => (
            <button
              key={m.name}
              onClick={() => setActiveModel(i)}
              className={`w-full flex items-center gap-3 p-3 rounded-[14px] border-[1.5px] mb-2 transition-all duration-140 cursor-pointer ${
                activeModel === i ? 'border-[#3B82F6] bg-[#EFF6FF]' : 'border-[#E2E8F0] hover:border-[#93C5FD] hover:bg-[#EFF6FF]'
              }`}
            >
              <div className="w-8 h-8 rounded-[10px] flex items-center justify-center text-[12px] font-bold text-white shrink-0" style={{ background: m.gradient }}>{m.avatar}</div>
              <div className="flex-1 min-w-0 text-left">
                <div className="text-[13px] font-semibold text-[#1E293B] leading-tight">{m.name}</div>
                <div className="text-[11px] text-[#64748B]">{m.desc}</div>
              </div>
              {activeModel === i ? (
                <div className="w-[18px] h-[18px] rounded-full bg-[#3B82F6] border-[#3B82F6] flex items-center justify-center shrink-0">
                  <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="w-2.5 h-2.5"><polyline points="20 6 9 17 4 12" /></svg>
                </div>
              ) : (
                <div className="w-[18px] h-[18px] rounded-full border-2 border-[#CBD5E1] shrink-0" />
              )}
            </button>
          ))}
        </div>

        {/* Common skills */}
        <div className="mb-6">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#94A3B8] mb-3">常用技能</div>
          <div className="flex flex-wrap gap-2">
            {skills.map((s) => (
              <span key={s.label} className="h-7 px-2.5 rounded-full bg-[#F1F5F9] text-[#475569] text-[12px] font-medium flex items-center gap-1 cursor-pointer transition-all duration-140 hover:bg-[#DBEAFE] hover:text-[#1D4ED8]">
                <span className="opacity-60">{s.icon}</span>
                {s.label}
              </span>
            ))}
          </div>
        </div>

        {/* Tips */}
        <div className="bg-gradient-to-br from-[#EFF6FF] to-white border border-[#BFDBFE] rounded-[14px] p-4">
          <h5 className="text-[13px] font-bold text-[#1E40AF] mb-2 flex items-center gap-1">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
            使用技巧
          </h5>
          <p className="text-[12px] text-[#475569] leading-relaxed">
            在输入框中使用 <strong>@专家</strong> 可以指定特定领域的 AI 专家协助你完成任务，例如 <strong>@数据分析师</strong> 或 <strong>@文案写手</strong>。
          </p>
          <div className="mt-2 px-3 py-2 bg-white border border-[#BFDBFE] rounded-[10px] text-[12px] text-[#1D4ED8] cursor-pointer transition-all duration-140 hover:bg-[#EFF6FF] hover:border-[#60A5FA]">
            @数据分析师 帮我分析上季度各渠道转化率
          </div>
        </div>
      </div>
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
    <div className="h-dvh w-dvw flex overflow-hidden relative" style={{ background: '#F8FAFC' }}>
      {/* Sidebar */}
      {sidebarVisible && (
        <>
          <div
            className="lg:hidden fixed inset-0 bg-black/30 z-30"
            onClick={() => setSidebarVisible(false)}
          />
          <aside className="fixed lg:static inset-y-0 left-0 z-40 shrink-0 shadow-xl lg:shadow-none" style={{ width: 256 }}>
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
        <DashboardTopBar />
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
            <LibraryView authToken={authToken} />
          </div>
        ) : activeNav === 'assistant' ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <DashboardView onSend={handleSend} loading={loading} sessionId={activeSessionId} username={currentUser.username} />
          </div>
        ) : messages.length === 0 && historyLoading ? (
          <div className="flex-1 flex items-center justify-center view-enter">
            <div className="flex flex-col items-center gap-3 text-[#94A3B8] text-[13px]">
              <span className="w-5 h-5 rounded-full border-2 border-[#CBD5E1] border-t-[#475569] animate-spin" />
              加载任务中...
            </div>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex-1 flex flex-col min-h-0 view-enter">
            <DashboardView onSend={handleSend} loading={loading} sessionId={activeSessionId} username={currentUser.username} />
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
      {/* Right panel - smart config */}
      <RightPanel />
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
