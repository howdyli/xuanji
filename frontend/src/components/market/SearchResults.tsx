/**
 * SearchResults —— 搜索结果页面
 * 顶部: 返回 + 搜索词 + 结果数 + ViewToggle
 * Desktop: 左 FilterSidebar 240px + 右技能网格
 * Mobile: 筛选折叠 + 卡片列表
 */
import type { MarketSkillV2, FilterState, Category } from '../MarketplaceView'
import FilterSidebar from './FilterSidebar'
import SkillCardRich from './SkillCardRich'
import ViewToggle from './ViewToggle'
import RatingStars from './RatingStars'
import InstallButton from './InstallButton'

interface SearchResultsProps {
  skills: MarketSkillV2[]
  query: string
  filters: FilterState
  categories: Category[]
  onFiltersChange: (filters: FilterState) => void
  onSkillClick: (name: string) => void
  onInstall: (name: string) => void
  onBack: () => void
  loading?: boolean
  viewMode: 'grid' | 'list'
  onViewModeChange?: (mode: 'grid' | 'list') => void
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl p-4 animate-pulse min-h-[180px]"
          style={{ backgroundColor: 'var(--bg-secondary, #fff)', border: '1px solid var(--border-light, #E2E8F0)' }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gray-100" />
            <div className="w-12 h-4 rounded bg-gray-100" />
          </div>
          <div className="h-4 bg-gray-100 rounded mt-3 w-1/2" />
          <div className="h-3 bg-gray-100 rounded mt-3 w-full" />
          <div className="h-3 bg-gray-100 rounded mt-1.5 w-4/5" />
        </div>
      ))}
    </div>
  )
}

function SkeletonList() {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-xl p-4 animate-pulse"
          style={{ backgroundColor: 'var(--bg-secondary, #fff)', border: '1px solid var(--border-light, #E2E8F0)' }}
        >
          <div className="w-10 h-10 rounded-lg bg-gray-100 shrink-0" />
          <div className="flex-1 min-w-0 space-y-2">
            <div className="h-4 bg-gray-100 rounded w-1/3" />
            <div className="h-3 bg-gray-100 rounded w-2/3" />
          </div>
        </div>
      ))}
    </div>
  )
}

const GRADIENTS = [
  'from-violet-400 to-fuchsia-500',
  'from-sky-400 to-blue-500',
  'from-orange-400 to-rose-500',
  'from-amber-400 to-yellow-500',
  'from-pink-400 to-rose-500',
  'from-teal-400 to-emerald-500',
]

function gradientOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}

function SkillCardListItem({ skill, onInstall, onClick }: { skill: MarketSkillV2; onInstall: (n: string) => void; onClick: (n: string) => void }) {
  return (
    <div
      className="flex items-center gap-4 rounded-xl p-4 cursor-pointer transition-all hover:shadow-md"
      style={{ backgroundColor: 'var(--bg-secondary, #fff)', border: '1px solid var(--border-light, #E2E8F0)' }}
      onClick={() => onClick(skill.name)}
    >
      {/* Icon */}
      {skill.icon_url ? (
        <img src={skill.icon_url} alt="" className="w-10 h-10 rounded-lg object-cover shrink-0" />
      ) : (
        <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${gradientOf(skill.name)} flex items-center justify-center text-white text-sm font-semibold shrink-0`}>
          {skill.name.charAt(0).toUpperCase()}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="text-[14px] font-medium truncate" style={{ color: 'var(--text-primary, #1E293B)' }}>
            {skill.name}
          </h3>
          {skill.featured && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0"
              style={{ backgroundColor: 'var(--warning-50, #FFFBEB)', color: 'var(--warning-700, #B45309)' }}>
              精选
            </span>
          )}
        </div>
        <p className="text-[12.5px] mt-0.5 truncate" style={{ color: 'var(--text-secondary, #475569)' }}>
          {skill.description || '暂无描述'}
        </p>
      </div>

      {/* Rating + install */}
      <div className="hidden sm:flex items-center gap-4 shrink-0">
        <RatingStars value={skill.rating_avg} size="sm" />
        <div onClick={e => e.stopPropagation()}>
          <InstallButton installed={skill.installed} loading={false} onInstall={() => onInstall(skill.name)} />
        </div>
      </div>
    </div>
  )
}

function EmptyState({ query }: { query: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-4">
      <svg width="80" height="80" viewBox="0 0 120 120" fill="none" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
        <circle cx="60" cy="50" r="32" stroke="currentColor" strokeWidth="3" strokeDasharray="6 4" opacity="0.5" />
        <circle cx="60" cy="50" r="20" stroke="currentColor" strokeWidth="2" opacity="0.3" />
        <line x1="80" y1="72" x2="98" y2="90" stroke="currentColor" strokeWidth="4" strokeLinecap="round" opacity="0.6" />
        <line x1="50" y1="45" x2="70" y2="45" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4" />
        <line x1="53" y1="53" x2="67" y2="53" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4" />
      </svg>
      <p className="mt-4 text-[15px] font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
        未找到匹配的技能
      </p>
      <p className="mt-1.5 text-[13px] text-center max-w-sm" style={{ color: 'var(--text-secondary, #475569)' }}>
        没有与 "<strong>{query}</strong>" 匹配的技能。试试其他关键词，或浏览全部分类。
      </p>
    </div>
  )
}

export default function SearchResults({
  skills, query, filters, categories,
  onFiltersChange, onSkillClick, onInstall, onBack,
  loading, viewMode, onViewModeChange,
}: SearchResultsProps) {

  const handleClearFilters = () => {
    onFiltersChange({ category: null, source: [], minRating: 0, sortBy: 'popular', tags: [] })
  }

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-[13px] font-medium transition-colors hover:opacity-80"
          style={{ color: 'var(--text-secondary, #475569)' }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          返回
        </button>

        <span className="text-[13px]" style={{ color: 'var(--text-secondary, #475569)' }}>
          搜索: <strong style={{ color: 'var(--text-primary, #1E293B)' }}>"{query}"</strong>
        </span>

        <span
          className="text-[12px] px-2 py-0.5 rounded-full font-medium"
          style={{ backgroundColor: 'var(--primary-50, #EFF6FF)', color: 'var(--primary-600, #2563EB)' }}
        >
          共 {skills.length} 个结果
        </span>

        <div className="ml-auto">
          {onViewModeChange && <ViewToggle mode={viewMode} onChange={onViewModeChange} />}
        </div>
      </div>

      {/* Body: sidebar + grid */}
      <div className="flex flex-col lg:flex-row gap-5">
        <FilterSidebar
          filters={filters}
          onChange={onFiltersChange}
          categories={categories}
          onClear={handleClearFilters}
        />

        <div className="flex-1 min-w-0">
          {loading ? (
            viewMode === 'grid' ? <SkeletonGrid /> : <SkeletonList />
          ) : skills.length === 0 ? (
            <EmptyState query={query} />
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {skills.map(s => (
                <SkillCardRich key={s.name} skill={s} onInstall={onInstall} onClick={onSkillClick} />
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {skills.map(s => (
                <SkillCardListItem key={s.name} skill={s} onInstall={onInstall} onClick={onSkillClick} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
