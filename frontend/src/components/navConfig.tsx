// --- Sidebar navigation config (shared by Sidebar and DashboardTopBar) ---
import { HomeIcon, FolderIcon, SkillIcon, ExploreIcon } from './icons'

function TeamIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
      <circle cx="9" cy="7" r="4"/>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
      <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>
  )
}

function ExpertIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4"/>
      <path d="M6 21v-1a6 6 0 0 1 12 0v1"/>
      <path d="M19 3l.7 1.6L21.5 5l-1.8.4L19 7l-.7-1.6L16.5 5l1.8-.4L19 3z"/>
    </svg>
  )
}

export const NAV_ITEMS = [
  { id: 'assistant', label: '工作台', icon: <HomeIcon />, group: 'workflow', iconColor: 'blue' },
  { id: 'chat', label: '任务', icon: <FolderIcon />, group: 'workflow', iconColor: 'blue' },
  { id: 'team', label: '团队', icon: <TeamIcon />, group: 'workflow', iconColor: 'blue' },
  { id: 'expert', label: '专家', icon: <ExpertIcon />, group: 'workflow', iconColor: 'blue' },
  { id: 'skill', label: '技能', icon: <SkillIcon />, group: 'automation', iconColor: 'purple' },
  { id: 'connector', label: '搜索', icon: <ExploreIcon />, group: 'system', iconColor: 'gray' },
]

export const EXPANDABLE_ITEMS = [
  { id: 'automation', label: '转化' },
  { id: 'model-config', label: '模型配置' },
  { id: 'library', label: '资料库' },
]

export const NAV_WORKFLOW = NAV_ITEMS.filter(i => i.group === 'workflow')
export const NAV_TOOLS = NAV_ITEMS.filter(i => i.group !== 'workflow')
