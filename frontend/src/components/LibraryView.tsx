/**
 * LibraryView —— 资料库主视图
 *
 * Phase 1: 任务成果（按 session 分组的文件列表）
 * Phase 2+: 我的文档 / 知识库（占位）
 *
 * 参考 WorkBuddy "我的文件" 风格：
 * - 标签页切换 + 筛选栏 + 搜索
 * - 按任务分组 + 可折叠
 * - 文件类型图标 + 元信息 + 下载/收藏
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const API_BASE = '/api/frontend'

// ─── Types ──────────────────────────────────────────────────────────────

interface FileInfo {
  name: string
  path: string
  type: string        // 中文: 文档/幻灯片/图片...
  type_key: string    // 英文: document/presentation/image...
  ext: string
  size: number
  mtime: string       // ISO 8601
}

interface FileGroup {
  session_id: string
  title: string
  icon: string        // main type_key
  file_count: number
  files: FileInfo[]
}

interface LibraryData {
  groups: FileGroup[]
  total: number
  type_options: string[]
}

// ─── Constants ──────────────────────────────────────────────────────────

const TYPE_LABELS: Record<string, string> = {
  all: '全部类型',
  document: '文档',
  presentation: '幻灯片',
  spreadsheet: '表格',
  image: '图片',
  diagram: '图表',
  other: '其他',
}

const TABS = [
  { id: 'tasks', label: '任务成果' },
  { id: 'docs', label: '我的文档' },
] as const

// ─── Inline Icons ───────────────────────────────────────────────────────

const SearchIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
)

const DownloadIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
  </svg>
)

const StarIcon = ({ filled }: { filled?: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
)

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
    <polyline points="9 18 15 12 9 6" />
  </svg>
)

const FolderIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
  </svg>
)

const BookOpenIcon = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
  </svg>
)

// ─── File Type Icons (colored SVGs) ─────────────────────────────────────

const FILE_TYPE_ICONS: Record<string, { icon: string; color: string }> = {
  '.docx': { icon: 'W', color: '#2b579a' },
  '.doc': { icon: 'W', color: '#2b579a' },
  '.pdf': { icon: 'P', color: '#d93025' },
  '.md': { icon: 'M', color: '#6b7280' },
  '.txt': { icon: 'T', color: '#6b7280' },
  '.pptx': { icon: 'P', color: '#d24726' },
  '.ppt': { icon: 'P', color: '#d24726' },
  '.xlsx': { icon: 'X', color: '#217346' },
  '.xls': { icon: 'X', color: '#217346' },
  '.csv': { icon: 'C', color: '#217346' },
  '.jpg': { icon: '🖼', color: '#8b5cf6' },
  '.jpeg': { icon: '🖼', color: '#8b5cf6' },
  '.png': { icon: '🖼', color: '#8b5cf6' },
  '.gif': { icon: '🖼', color: '#8b5cf6' },
  '.svg': { icon: '🖼', color: '#8b5cf6' },
  '.webp': { icon: '🖼', color: '#8b5cf6' },
  '.drawio': { icon: 'D', color: '#f59e0b' },
  '.vsdx': { icon: 'D', color: '#f59e0b' },
  '.json': { icon: '{ }', color: '#6b7280' },
}

function FileTypeBadge({ ext }: { ext: string }) {
  const info = FILE_TYPE_ICONS[ext] || { icon: '?', color: '#9ca3af' }
  const isEmoji = info.icon.length > 1 && info.icon.charCodeAt(0) > 127
  return (
    <div
      className="w-8 h-8 rounded-lg flex items-center justify-center text-[11px] font-bold shrink-0"
      style={{ backgroundColor: info.color + '15', color: info.color }}
    >
      {isEmoji ? <span className="text-sm">{info.icon}</span> : info.icon}
    </div>
  )
}

// ─── Group icon by type ────────────────────────────────────────────────

const GROUP_TYPE_ICONS: Record<string, { emoji: string; bg: string }> = {
  document: { emoji: '📄', bg: '#eff6ff' },
  presentation: { emoji: '📊', bg: '#fef3c7' },
  spreadsheet: { emoji: '📈', bg: '#ecfdf5' },
  image: { emoji: '🖼️', bg: '#faf5ff' },
  diagram: { emoji: '📐', bg: '#fff7ed' },
  other: { emoji: '📁', bg: '#f3f4f6' },
}

// ─── Helpers ────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function formatRelativeTime(isoStr: string): string {
  const now = Date.now()
  const then = new Date(isoStr).getTime()
  const diffMs = now - then
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay === 1) return '昨天'
  if (diffDay < 7) return `${diffDay}天前`
  // Show date for older items
  const d = new Date(isoStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

// ─── Main Component ─────────────────────────────────────────────────────

export function LibraryView({ authToken }: { authToken: string | null }) {
  const [activeTab, setActiveTab] = useState<string>('tasks')
  const [data, setData] = useState<LibraryData>({ groups: [], total: 0, type_options: [] })
  const [filterType, setFilterType] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [showFavs, setShowFavs] = useState(false)
  const [favorites, setFavorites] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())

  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const debouncedSearch = useRef('')

  // Fetch data
  const fetchFiles = useCallback(async () => {
    if (!authToken) return
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterType !== 'all') params.set('type', filterType)
      if (debouncedSearch.current) params.set('search', debouncedSearch.current)
      if (showFavs) params.set('favorites', 'true')
      const res = await fetch(`${API_BASE}/library/files?${params}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      const json = await res.json()
      setData(json)
    } catch (e) {
      console.error('library fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }, [authToken, filterType, showFavs])

  // Fetch favorites on mount
  const fetchFavorites = useCallback(async () => {
    if (!authToken) return
    try {
      const res = await fetch(`${API_BASE}/library/favorites`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      const json = await res.json()
      setFavorites(new Set(json.paths || []))
    } catch { /* ignore */ }
  }, [authToken])

  useEffect(() => { fetchFiles() }, [fetchFiles])
  useEffect(() => { fetchFavorites() }, [fetchFavorites])

  // Debounced search
  const handleSearchChange = (val: string) => {
    setSearchText(val)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => {
      debouncedSearch.current = val
      fetchFiles()
    }, 300)
  }

  // Toggle favorite
  const toggleFavorite = async (path: string) => {
    const isFav = favorites.has(path)
    const action = isFav ? 'remove' : 'add'

    // Optimistic update
    setFavorites(prev => {
      const next = new Set(prev)
      if (isFav) next.delete(path)
      else next.add(path)
      return next
    })

    if (authToken) {
      try {
        await fetch(`${API_BASE}/library/favorites`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${authToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ path, action }),
        })
      } catch { /* revert on error */ }
    }
  }

  // Toggle group collapse
  const toggleGroup = (sessionId: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev)
      if (next.has(sessionId)) next.delete(sessionId)
      else next.add(sessionId)
      return next
    })
  }

  // Download file
  const handleDownload = (file: FileInfo) => {
    const url = `${API_BASE}/files/download?path=/workspace${file.path}`
    const a = document.createElement('a')
    a.href = url
    a.download = file.name
    a.click()
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-5 sm:px-8 pt-5 pb-0">
        <h1 className="text-[20px] font-semibold text-gray-800 mb-1">资料库</h1>
        <p className="text-[13px] text-gray-400 mb-4">
          快捷查看任务成果，管理文档与知识库，为 AI 提供持续的记忆支持。
        </p>

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-gray-200">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-[13px] font-medium transition-colors relative
                ${activeTab === tab.id
                  ? 'text-gray-900'
                  : 'text-gray-400 hover:text-gray-600'}`}
            >
              {tab.label}
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-2 right-2 h-[2px] bg-gray-900 rounded-full" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 sm:px-8 pb-6">
        {activeTab === 'tasks' ? (
          <TaskResultsTab
            data={data}
            loading={loading}
            filterType={filterType}
            searchText={searchText}
            showFavs={showFavs}
            favorites={favorites}
            collapsedGroups={collapsedGroups}
            onFilterChange={setFilterType}
            onSearchChange={handleSearchChange}
            onToggleFavs={() => setShowFavs(!showFavs)}
            onToggleGroup={toggleGroup}
            onDownload={handleDownload}
            onToggleFavorite={toggleFavorite}
          />
        ) : (
          <MyDocsPlaceholder />
        )}
      </div>
    </div>
  )
}

// ─── Task Results Tab ───────────────────────────────────────────────────

function TaskResultsTab({
  data,
  loading,
  filterType,
  searchText,
  showFavs,
  favorites,
  collapsedGroups,
  onFilterChange,
  onSearchChange,
  onToggleFavs,
  onToggleGroup,
  onDownload,
  onToggleFavorite,
}: {
  data: LibraryData
  loading: boolean
  filterType: string
  searchText: string
  showFavs: boolean
  favorites: Set<string>
  collapsedGroups: Set<string>
  onFilterChange: (type: string) => void
  onSearchChange: (text: string) => void
  onToggleFavs: () => void
  onToggleGroup: (id: string) => void
  onDownload: (file: FileInfo) => void
  onToggleFavorite: (path: string) => void
}) {
  return (
    <div className="pt-4">
      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {/* Type filter */}
        <select
          value={filterType}
          onChange={e => onFilterChange(e.target.value)}
          className="h-9 px-3 rounded-lg border border-gray-200 bg-white text-[13px] text-gray-700 outline-none cursor-pointer hover:border-gray-300 focus:border-gray-400 transition-colors"
        >
          {Object.entries(TYPE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
            <SearchIcon />
          </div>
          <input
            type="text"
            value={searchText}
            onChange={e => onSearchChange(e.target.value)}
            placeholder="搜索文件、任务..."
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-gray-200 bg-white text-[13px] text-gray-700 placeholder-gray-400 outline-none hover:border-gray-300 focus:border-gray-400 transition-colors"
          />
        </div>

        {/* Favorites toggle */}
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showFavs}
            onChange={onToggleFavs}
            className="w-4 h-4 rounded border-gray-300 text-amber-500 focus:ring-amber-400 cursor-pointer"
          />
          <span className="text-[13px] text-gray-600">我的收藏</span>
        </label>
      </div>

      {/* File groups */}
      {loading ? (
        <LoadingSkeleton />
      ) : data.groups.length === 0 ? (
        <EmptyState hasSearch={!!searchText || filterType !== 'all'} />
      ) : (
        <div className="space-y-3">
          {/* Total count */}
          <div className="text-[12px] text-gray-400 mb-1">
            共 {data.total} 个文件，{data.groups.length} 个任务
          </div>

          {data.groups.map(group => (
            <FileGroupCard
              key={group.session_id}
              group={group}
              collapsed={collapsedGroups.has(group.session_id)}
              favorites={favorites}
              onToggle={() => onToggleGroup(group.session_id)}
              onDownload={onDownload}
              onToggleFavorite={onToggleFavorite}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── File Group Card ────────────────────────────────────────────────────

function FileGroupCard({
  group,
  collapsed,
  favorites,
  onToggle,
  onDownload,
  onToggleFavorite,
}: {
  group: FileGroup
  collapsed: boolean
  favorites: Set<string>
  onToggle: () => void
  onDownload: (file: FileInfo) => void
  onToggleFavorite: (path: string) => void
}) {
  const groupIcon = GROUP_TYPE_ICONS[group.icon] || GROUP_TYPE_ICONS.other

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Group header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50/80 transition-colors text-left"
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-base shrink-0"
          style={{ backgroundColor: groupIcon.bg }}
        >
          {groupIcon.emoji}
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-[13.5px] font-semibold text-gray-800 truncate block">
            {group.title}
          </span>
        </div>
        <span className="text-[12px] text-gray-400 shrink-0">
          {group.file_count} 个文件
        </span>
        <ChevronIcon open={!collapsed} />
      </button>

      {/* File list */}
      {!collapsed && (
        <div className="border-t border-gray-100">
          {group.files.map((file, idx) => (
            <FileRow
              key={file.path}
              file={file}
              isFav={favorites.has(file.path)}
              showBorder={idx > 0}
              onDownload={() => onDownload(file)}
              onToggleFavorite={() => onToggleFavorite(file.path)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── File Row ───────────────────────────────────────────────────────────

function FileRow({
  file,
  isFav,
  showBorder,
  onDownload,
  onToggleFavorite,
}: {
  file: FileInfo
  isFav: boolean
  showBorder: boolean
  onDownload: () => void
  onToggleFavorite: () => void
}) {
  return (
    <div
      className={`group flex items-center gap-3 px-4 py-2.5 hover:bg-blue-50/40 transition-colors
        ${showBorder ? 'border-t border-gray-50' : ''}`}
    >
      {/* File icon */}
      <FileTypeBadge ext={file.ext} />

      {/* File name */}
      <div className="flex-1 min-w-0">
        <button
          onClick={onDownload}
          className="text-[13px] text-gray-800 hover:text-blue-600 truncate block text-left transition-colors w-full"
          title={file.name}
        >
          {file.name}
        </button>
      </div>

      {/* Type label */}
      <span className="text-[12px] text-gray-400 shrink-0 hidden sm:inline w-14 text-center">
        {file.type}
      </span>

      {/* Time */}
      <span className="text-[12px] text-gray-400 shrink-0 hidden md:inline w-20 text-right">
        {formatRelativeTime(file.mtime)}
      </span>

      {/* Size */}
      <span className="text-[12px] text-gray-400 shrink-0 hidden sm:inline w-14 text-right">
        {formatFileSize(file.size)}
      </span>

      {/* Actions (visible on hover) */}
      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onToggleFavorite}
          className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors
            ${isFav ? 'text-amber-500 bg-amber-50' : 'text-gray-400 hover:text-amber-500 hover:bg-amber-50'}`}
          title={isFav ? '取消收藏' : '收藏'}
        >
          <StarIcon filled={isFav} />
        </button>
        <button
          onClick={onDownload}
          className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
          title="下载"
        >
          <DownloadIcon />
        </button>
      </div>
    </div>
  )
}

// ─── Empty State ────────────────────────────────────────────────────────

function EmptyState({ hasSearch }: { hasSearch: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center text-gray-400 mb-4">
        <FolderIcon />
      </div>
      <h3 className="text-[15px] font-medium text-gray-700 mb-1.5">
        {hasSearch ? '没有找到匹配的文件' : '暂无任务产出文件'}
      </h3>
      <p className="text-[13px] text-gray-400 max-w-sm">
        {hasSearch
          ? '试试调整筛选条件或搜索关键词'
          : '让玄机帮你生成一份报告、PPT 或方案，产出文件将自动出现在这里。'}
      </p>
    </div>
  )
}

// ─── Loading Skeleton ───────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-lg bg-gray-200" />
            <div className="h-4 bg-gray-200 rounded w-48" />
            <div className="h-3 bg-gray-100 rounded w-16 ml-auto" />
          </div>
          <div className="space-y-2">
            <div className="h-8 bg-gray-50 rounded" />
            <div className="h-8 bg-gray-50 rounded" />
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── My Docs Placeholder (Phase 2) ──────────────────────────────────────

function MyDocsPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-purple-50 flex items-center justify-center text-purple-400 mb-4">
        <BookOpenIcon />
      </div>
      <h3 className="text-[16px] font-semibold text-gray-700 mb-1.5">我的文档</h3>
      <p className="text-[13px] text-gray-400 max-w-sm mb-4">
        上传文档到资料库，AI 将在后续对话中自动引用，构建你的专属知识库。
      </p>
      <span className="px-4 py-1.5 rounded-full bg-gray-100 text-[12px] text-gray-500 font-medium">
        敬请期待
      </span>
    </div>
  )
}
