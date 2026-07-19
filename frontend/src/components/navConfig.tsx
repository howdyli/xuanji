// --- Sidebar navigation config (shared by Sidebar and DashboardTopBar) ---
import { HomeIcon, FolderIcon, SkillIcon, ExploreIcon } from './icons'

export const NAV_ITEMS = [
  { id: 'assistant', label: '工作台', icon: <HomeIcon />, group: 'workflow', iconColor: 'blue' },
  { id: 'chat', label: '任务', icon: <FolderIcon />, group: 'workflow', iconColor: 'blue', badge: '3' },
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
